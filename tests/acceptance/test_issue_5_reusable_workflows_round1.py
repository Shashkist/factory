"""Issue #5, review round 1 (D23): the exam pins what the first build let through.

The JUnit gate must run in its own job that never checks out the caller, the
judge must run only from its own checkout, exam integrity must not fetch and
must refuse an empty head or base, and the limits must be written down.
"""

import json
import re
from typing import Any

import pytest
import yaml
from helpers import ROOT, workflow_text

WF_DIR = ROOT / ".github" / "workflows"
FILES = ["exam-integrity.yml", "junit-gate.yml"]
JUDGE_WORDS = ("factory_tools", "junit_gate", "exam_integrity")


def load(name: str) -> dict[str, Any]:
    assert (WF_DIR / name).is_file(), f"{name} does not exist"
    data = yaml.safe_load(workflow_text(name))
    assert isinstance(data, dict), f"{name} is not a YAML mapping"
    return data


def jobs(name: str) -> dict[str, dict[str, Any]]:
    return load(name).get("jobs") or {}


def job_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


def all_steps(name: str) -> list[dict[str, Any]]:
    return [s for j in jobs(name).values() for s in job_steps(j)]


def blob(node: Any) -> str:
    return json.dumps(node)


def uses_of(step: dict[str, Any]) -> str:
    return str(step.get("uses", ""))


def is_judge_checkout(step: dict[str, Any]) -> bool:
    return "checkout" in uses_of(step) and "job.workflow_repository" in str(
        (step.get("with") or {}).get("repository", "")
    )


def is_caller_checkout(step: dict[str, Any]) -> bool:
    return "checkout" in uses_of(step) and not is_judge_checkout(step)


def runs(name: str) -> list[str]:
    return [s["run"] for s in all_steps(name) if isinstance(s.get("run"), str)]


def cond(value: Any) -> str:
    """An `if:` value without whitespace; GitHub accepts it with or without ${{ }}."""
    return re.sub(r"\s+", "", str(value))


def always_runs(value: Any) -> bool:
    return cond(value) in ("${{!cancelled()}}", "!cancelled()", "${{always()}}", "always()")


def code_text(name: str) -> str:
    assert (WF_DIR / name).is_file(), f"{name} does not exist"
    return "\n".join(
        ln for ln in workflow_text(name).splitlines() if not ln.strip().startswith("#")
    )


def judge_prefix_problems(script: str, judge_path: str) -> list[str]:
    """Every `factory_tools/ci/` in a script must sit under the judge checkout path."""
    bad: list[str] = []
    want = judge_path.removeprefix("./").strip("/") + "/"
    for m in re.finditer(r"([^\s\"'=:]*)factory_tools/ci/", script):
        prefix = m.group(1)
        for ws in ("${{ github.workspace }}/", "${GITHUB_WORKSPACE}/", "$GITHUB_WORKSPACE/"):
            prefix = prefix.replace(ws, "")
        while prefix.startswith("./"):
            prefix = prefix[2:]
        if not prefix.startswith(want):
            bad.append(m.group(0))
    return bad


def judge_checkout_path(name: str) -> str:
    found = [s for s in all_steps(name) if is_judge_checkout(s)]
    assert found, "no judge checkout"
    paths = {str((s.get("with") or {}).get("path", "")) for s in found}
    assert "" not in paths, "judge checkout has no path"
    assert len(paths) == 1
    return paths.pop()


def split_jobs() -> tuple[str, dict[str, Any], str, dict[str, Any]]:
    js = jobs("junit-gate.yml")
    assert len(js) == 2, f"junit-gate.yml needs two jobs (exam and gate), has {len(js)}"
    gate_name = next((k for k, j in js.items() if j.get("needs")), "")
    assert gate_name, "no job has needs:"
    needs = js[gate_name]["needs"]
    needs = [needs] if isinstance(needs, str) else list(needs)
    assert len(needs) == 1 and needs[0] in js and needs[0] != gate_name
    return needs[0], js[needs[0]], gate_name, js[gate_name]


# ---- the path checker itself (guards against a checker that accepts everything)


@pytest.mark.parametrize(
    "script",
    [
        "python3 ./src/factory_tools/ci/junit_gate.py x",
        "python3 src/factory_tools/ci/junit_gate.py x",
        "python3 $GITHUB_WORKSPACE/src/factory_tools/ci/junit_gate.py x",
        'python3 "${GITHUB_WORKSPACE}/src/factory_tools/ci/junit_gate.py" x',
        "python3 ${{ github.workspace }}/src/factory_tools/ci/junit_gate.py x",
    ],
)
def test_checker_flags_a_judge_run_from_the_callers_tree(script: str) -> None:
    assert judge_prefix_problems(script, ".factory-tools")


def test_checker_accepts_the_judge_checkout_path() -> None:
    ok = 'python3 -I ".factory-tools/src/factory_tools/ci/junit_gate.py" x'
    assert not judge_prefix_problems(ok, ".factory-tools")


# ---- judge path and weakened versions


@pytest.mark.parametrize("name", FILES)
def test_round1_every_factory_tools_ci_reference_is_under_the_judge_checkout_path(
    name: str,
) -> None:
    path = judge_checkout_path(name)
    scripts = "\n".join(runs(name))
    assert "factory_tools/ci/" in scripts, "no run step calls the judge by path"
    assert not judge_prefix_problems(scripts, path), judge_prefix_problems(scripts, path)


@pytest.mark.parametrize("name", FILES)
def test_round1_no_or_fallback_and_no_bootstrap_on_a_judge_run(name: str) -> None:
    judge_runs = [r for r in runs(name) if any(w in r for w in JUDGE_WORDS)]
    assert judge_runs, "no run step runs a judge"
    for r in judge_runs:
        assert "||" not in r, "a fallback after the judge can hide its failure"
        assert "--bootstrap" not in r, "--bootstrap switches the check off"


@pytest.mark.parametrize("name", FILES)
def test_round1_no_continue_on_error_anywhere(name: str) -> None:
    assert "continue-on-error" not in code_text(name)


@pytest.mark.parametrize("name", FILES)
def test_round1_judge_steps_are_not_switched_off_by_a_condition(name: str) -> None:
    judge_steps = [
        s for s in all_steps(name) if any(w in str(s.get("run", "")) for w in JUDGE_WORDS)
    ]
    assert judge_steps, "no judge step"
    for s in judge_steps:
        if "if" in s:
            assert always_runs(s["if"]), f"judge step has if: {s['if']}"


# ---- junit-gate.yml: two jobs


def test_round1_junit_gate_has_an_exam_job_and_a_gate_job_that_needs_it() -> None:
    split_jobs()


def test_round1_exam_job_checks_out_the_caller_and_runs_the_test_command() -> None:
    _, exam, _, _ = split_jobs()
    st = job_steps(exam)
    assert any(is_caller_checkout(s) for s in st), "exam job does not check out the caller"
    assert any("inputs.test-command" in blob(s) for s in st), "exam job does not run the command"


def test_round1_exam_job_uploads_the_report_with_a_pinned_action_even_on_failure() -> None:
    _, exam, _, _ = split_jobs()
    ups = [s for s in job_steps(exam) if "upload-artifact" in uses_of(s)]
    assert ups, "no upload-artifact step in the exam job"
    for u in ups:
        pin = uses_of(u).split("#")[0].strip()
        assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", pin)
        assert always_runs(u.get("if")), f"upload does not run on failure: {u.get('if')}"


def test_round1_artifact_name_is_not_a_bare_constant() -> None:
    _, exam, _, gate = split_jobs()
    names = [
        str((s.get("with") or {}).get("name", ""))
        for j in (exam, gate)
        for s in job_steps(j)
        if "artifact" in uses_of(s)
    ]
    assert len(names) >= 2, "upload and download both need a name"
    for n in names:
        assert "${{" in n, f"artifact name is a constant: {n!r}"


def test_round1_gate_job_runs_even_when_the_exam_job_failed() -> None:
    _, _, _, gate = split_jobs()
    assert always_runs(gate.get("if")), f"gate job if: {gate.get('if')!r}"


def test_round1_gate_job_never_checks_out_the_caller() -> None:
    _, _, _, gate = split_jobs()
    checkouts = [s for s in job_steps(gate) if "checkout" in uses_of(s)]
    assert len(checkouts) == 1, "the gate job needs exactly one checkout, the judge"
    assert is_judge_checkout(checkouts[0])
    w = checkouts[0].get("with") or {}
    assert "job.workflow_sha" in str(w.get("ref", ""))


def test_round1_gate_job_downloads_the_report_with_a_pinned_action() -> None:
    _, _, _, gate = split_jobs()
    downs = [s for s in job_steps(gate) if "download-artifact" in uses_of(s)]
    assert downs, "no download-artifact step in the gate job"
    for d in downs:
        pin = uses_of(d).split("#")[0].strip()
        assert re.fullmatch(r"actions/download-artifact@[0-9a-f]{40}", pin)


def test_round1_gate_job_runs_the_judge_with_the_absolute_interpreter_in_isolated_mode() -> None:
    _, _, _, gate = split_jobs()
    judge = [s for s in job_steps(gate) if "junit_gate" in str(s.get("run", ""))]
    assert judge, "the gate job does not run junit_gate"
    path = judge_checkout_path("junit-gate.yml")
    for s in judge:
        assert "/usr/bin/python3 -I " in s["run"], "judge not run as /usr/bin/python3 -I"
        assert not judge_prefix_problems(s["run"], path)


def test_round1_test_command_never_runs_in_the_gate_job() -> None:
    _, _, _, gate = split_jobs()
    text = blob(gate)
    assert "test-command" not in text and "TEST_COMMAND" not in text
    assert not any("bash -c" in str(s.get("run", "")) for s in job_steps(gate))


# ---- exam-integrity.yml


def test_round1_exam_integrity_does_not_fetch() -> None:
    text = code_text("exam-integrity.yml")
    assert "git fetch" not in text
    assert not re.search(r"\bgit\s+(-\S+\s+)*(fetch|pull)\b", text)


@pytest.mark.parametrize("var", ["HEAD_SHA", "BASE_REF"])
def test_round1_exam_integrity_refuses_an_empty_head_or_base(var: str) -> None:
    step = next(
        (s for s in all_steps("exam-integrity.yml") if "exam_integrity" in str(s.get("run", ""))),
        None,
    )
    assert step is not None, "no step runs exam_integrity"
    script = step["run"]
    assert var in blob(step.get("env") or {}), f"{var} not in the step env"
    check = re.search(rf'(-n|-z)\s+"?\$\{{?{var}\}}?"?', script)
    assert check, f"no explicit check of {var}"
    before_judge = script.split("exam_integrity")[0]
    assert check.start() < len(before_judge), "the check must come before the judge runs"
    assert re.search(r"exit\s+[1-9]", before_judge), "the check does not exit non-zero first"


def test_round1_exam_integrity_is_never_skipped_by_an_if() -> None:
    wf = load("exam-integrity.yml")
    assert "if" not in wf
    for j in wf["jobs"].values():
        assert "if" not in j, "a job-level if could skip the check"
    for s in all_steps("exam-integrity.yml"):
        if "exam_integrity" in str(s.get("run", "")):
            assert "if" not in s, "the judge step is conditional"


# ---- timeout input and limits written down


def test_round1_timeout_minutes_is_a_described_input_used_by_the_exam_job() -> None:
    wf = load("junit-gate.yml")
    on = wf["on"] if "on" in wf else wf.get(True)
    inputs = on["workflow_call"]["inputs"]
    assert "timeout-minutes" in inputs, "no timeout-minutes input"
    desc = (inputs["timeout-minutes"] or {}).get("description")
    assert isinstance(desc, str) and desc.strip()
    _, exam, _, _ = split_jobs()
    assert "inputs.timeout-minutes" in str(exam.get("timeout-minutes", ""))


def test_round1_exam_integrity_header_states_the_tests_limit_and_issue_65() -> None:
    header: list[str] = []
    for ln in workflow_text("exam-integrity.yml").splitlines():
        if not ln.strip().startswith("#"):
            break
        header.append(ln)
    text = "\n".join(header)
    assert "#65" in text, "header does not mention #65"
    assert re.search(r"top-level\s+`?tests/`?", text), "header lacks the top-level tests/ limit"
