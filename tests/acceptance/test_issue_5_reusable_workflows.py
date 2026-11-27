"""Issue #5 (slice A): reusable exam-integrity and JUnit-gate workflows.

Reads the two workflow files as data. The judge must come from the pinned
Factory commit (job.workflow_repository at job.workflow_sha), never from the
caller's checkout, and neither workflow may touch a secret or a write token.
"""

import json
import re
from typing import Any

import pytest
import yaml
from helpers import ROOT, workflow_text

FILES = ["exam-integrity.yml", "junit-gate.yml"]
WF_DIR = ROOT / ".github" / "workflows"


def load(name: str) -> dict[str, Any]:
    assert (WF_DIR / name).is_file(), f"{name} does not exist"
    data = yaml.safe_load(workflow_text(name))
    assert isinstance(data, dict), f"{name} is not a YAML mapping"
    return data


def on_block(wf: dict[str, Any]) -> Any:
    # YAML 1.1 parses the bare key `on` as boolean True.
    return wf["on"] if "on" in wf else wf.get(True)


def steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for job in (wf.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def code_text(name: str) -> str:
    """The file without comment-only lines."""
    assert (WF_DIR / name).is_file(), f"{name} does not exist"
    return "\n".join(
        ln for ln in workflow_text(name).splitlines() if not ln.strip().startswith("#")
    )


def blob(step: Any) -> str:
    return json.dumps(step)


def is_tools_checkout(step: dict[str, Any]) -> bool:
    return "checkout" in str(step.get("uses", "")) and "job.workflow_repository" in str(
        (step.get("with") or {}).get("repository", "")
    )


def tools_steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps that fetch/install/check out the factory tools."""
    return [
        s
        for s in steps(wf)
        if "job.workflow_repository" in blob(s) and "job.workflow_sha" in blob(s)
    ]


def run_scripts(wf: dict[str, Any]) -> list[str]:
    return [s["run"] for s in steps(wf) if isinstance(s.get("run"), str)]


def write_permissions(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "permissions":
                if isinstance(v, str) and "write" in v:
                    found.append(v)
                elif isinstance(v, dict):
                    found += [f"{pk}: {pv}" for pk, pv in v.items() if "write" in str(pv)]
            else:
                found += write_permissions(v)
    elif isinstance(node, list):
        for x in node:
            found += write_permissions(x)
    return found


@pytest.mark.parametrize("name", FILES)
def test_criterion_1_workflow_file_exists(name: str) -> None:
    assert (WF_DIR / name).is_file(), f"{name} does not exist"


@pytest.mark.parametrize("name", FILES)
def test_criterion_1_triggers_on_workflow_call(name: str) -> None:
    on = on_block(load(name))
    assert isinstance(on, dict) and "workflow_call" in on, "no on: workflow_call"


@pytest.mark.parametrize("name", FILES)
def test_criterion_1_inputs_are_declared_with_a_description_each(name: str) -> None:
    on = on_block(load(name))
    call = on["workflow_call"] or {}
    inputs = call.get("inputs") or {}
    assert inputs, "no inputs declared"
    for key, spec in inputs.items():
        desc = (spec or {}).get("description")
        assert isinstance(desc, str) and desc.strip(), f"input {key} has no description"


@pytest.mark.parametrize("name", FILES)
def test_criterion_1_top_level_permissions_are_read_only_contents(name: str) -> None:
    wf = load(name)
    perms = wf.get("permissions")
    assert isinstance(perms, dict), "no top-level permissions mapping"
    assert perms.get("contents") == "read"
    assert not write_permissions(wf), "a permission grants write"


@pytest.mark.parametrize("name", FILES)
def test_criterion_2_every_uses_is_pinned_by_a_full_commit_sha(name: str) -> None:
    uses = [
        ln.split("uses:", 1)[1].split("#")[0].strip().strip("'\"")
        for ln in code_text(name).splitlines()
        if "uses:" in ln
    ]
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u), f"not pinned: {u}"


@pytest.mark.parametrize("name", FILES)
def test_criterion_3_tools_come_from_job_workflow_repository_at_job_workflow_sha(
    name: str,
) -> None:
    wf = load(name)
    found = tools_steps(wf)
    assert found, "no step uses job.workflow_repository together with job.workflow_sha"
    for s in found:
        if "checkout" in str(s.get("uses", "")):
            w = s.get("with") or {}
            assert "job.workflow_repository" in str(w.get("repository", ""))
            assert "job.workflow_sha" in str(w.get("ref", ""))


@pytest.mark.parametrize("name", FILES)
def test_criterion_3_no_moving_or_caller_ref_for_the_tools(name: str) -> None:
    wf = load(name)
    assert tools_steps(wf), "no tools step found"
    text = code_text(name)
    for bad in ("github.sha", "github.workflow_sha"):
        assert bad not in text, f"{bad} used"
    assert not re.search(r"github\.ref\b", text), "github.ref used"
    assert not re.search(r"@(main|master)\b", text), "install from a branch"
    assert not re.search(r"ref:\s*['\"]?(main|master|refs/heads/\S+)", text)
    assert not re.search(r"--branch[ =]\S+|git clone", text), "unpinned clone"


@pytest.mark.parametrize("name", FILES)
def test_criterion_3_judge_does_not_run_from_the_callers_checkout(name: str) -> None:
    wf = load(name)
    checkouts = [s for s in steps(wf) if is_tools_checkout(s)]
    for s in checkouts:
        # The tools must not be written over the caller's working tree.
        assert (s.get("with") or {}).get("path"), "tools checkout has no path"
    scripts = "\n".join(run_scripts(wf))
    assert "factory_tools" in scripts, "no run step calls the judge"
    # A bare src/factory_tools is the caller's tree; only <tools path>/src/... is ok.
    assert not re.search(r"(?<![\w./$}-])src/factory_tools", scripts), (
        "judge run from a path in the caller's checkout"
    )
    assert not re.search(r"PYTHONPATH=['\"]?(\./)?src\b", scripts)
    assert not re.search(r"\bpip install\b[^\n]*(\s\.(\s|$)|-e\s+\.)", scripts)
    if not checkouts:
        # installed from the pinned git ref instead: a step must name it
        assert tools_steps(wf)


def test_criterion_4_exam_integrity_gets_base_ref_and_head_sha_of_the_calling_pr() -> None:
    wf = load("exam-integrity.yml")
    step = next((s for s in steps(wf) if "exam_integrity" in str(s.get("run", ""))), None)
    assert step is not None, "no step runs exam_integrity"
    b = blob(step)
    assert "github.event.pull_request.head.sha" in b
    assert "github.base_ref" in b or "github.event.pull_request.base" in b


def test_criterion_4_exam_integrity_checks_out_the_caller_with_full_history() -> None:
    wf = load("exam-integrity.yml")
    caller = [
        s
        for s in steps(wf)
        if "checkout" in str(s.get("uses", "")) and not is_tools_checkout(s)
    ]
    assert caller, "no checkout of the caller"
    assert any(str((s.get("with") or {}).get("fetch-depth")) == "0" for s in caller)


def test_criterion_4_exam_integrity_failure_fails_the_job() -> None:
    wf = load("exam-integrity.yml")
    ran = False
    for s in steps(wf):
        if "exam_integrity" in str(s.get("run", "")):
            ran = True
            assert not s.get("continue-on-error"), "continue-on-error hides a failure"
            assert "|| true" not in s["run"]
    assert ran, "no step runs exam_integrity"
    for job in wf["jobs"].values():
        assert not job.get("continue-on-error")


def test_criterion_4_junit_gate_runs_the_gate_module_on_the_input_report() -> None:
    wf = load("junit-gate.yml")
    step = next((s for s in steps(wf) if "junit_gate" in str(s.get("run", ""))), None)
    assert step is not None, "no step runs junit_gate"
    assert "inputs." in blob(step), "report is not taken from an input"
    assert "|| true" not in step["run"]
    assert not step.get("continue-on-error")
    inputs = on_block(wf)["workflow_call"]["inputs"]
    assert any(re.search(r"junit|report|xml", k, re.I) for k in inputs)


@pytest.mark.parametrize("name", FILES)
def test_criterion_5_no_secret_and_no_github_token(name: str) -> None:
    text = code_text(name)
    assert "secrets." not in text
    assert not re.search(r"^\s*secrets\s*:", text, re.M)
    assert "GITHUB_TOKEN" not in text
    if name == "exam-integrity.yml":
        # D43 amendment 1: the marker step reads the PR comments with the job
        # token. github.token may appear once, as GH_TOKEN in the env: of a step
        # whose run calls gh api on the comments; anywhere else it is refused.
        allowed = [
            s
            for s in steps(load(name))
            if isinstance(s.get("run"), str)
            and "gh api" in s["run"]
            and "comments" in s["run"]
            and isinstance(s.get("env"), dict)
            and re.fullmatch(r"\$\{\{\s*github\.token\s*\}\}", str(s["env"].get("GH_TOKEN", "")))
        ]
        total = len(re.findall(r"github\.token", text))
        assert total <= 1, f"github.token appears {total} times, at most one is allowed"
        if total == 1:
            assert len(allowed) == 1, (
                "github.token is only allowed as GH_TOKEN in the env of the step "
                "that runs gh api on the PR comments"
            )
            assert len(re.findall(r"github\.token", json.dumps(allowed[0]["env"]))) == 1
    else:
        assert "github.token" not in text


@pytest.mark.parametrize("name", FILES)
def test_criterion_5_no_job_level_permission_grants_write(name: str) -> None:
    wf = load(name)
    for job_name, job in wf["jobs"].items():
        assert not write_permissions(job), f"job {job_name} grants write"
    assert not write_permissions(wf)
