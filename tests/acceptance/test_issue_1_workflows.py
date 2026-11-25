"""Issue #1, criteria 3, 4 and 6: workflow files, pinning, project config."""

import re
import tomllib

import pytest
import yaml
from helpers import ROOT, workflow_text

# Transitional per D26: the three judge cases accept either the inline form or the
# reusable form (pinned junit-gate.yml / exam-integrity.yml calls), each checked whole.
# PR C tightens them to the reusable form only.
WF_DIR = ROOT / ".github" / "workflows"


def workflows() -> list[str]:
    return sorted(p.name for p in WF_DIR.glob("*.yml")) if WF_DIR.is_dir() else []


def test_there_is_at_least_one_workflow() -> None:
    assert workflows()


def test_ci_workflow_exists_and_runs_on_pull_requests_and_main_pushes() -> None:
    t = workflow_text("ci.yml")
    assert "pull_request" in t
    assert re.search(r"^\s*push\s*:", t, re.M), "no push trigger"
    assert "main" in t


def _code(t: str) -> str:
    return "\n".join(ln for ln in t.splitlines() if not ln.strip().startswith("#"))


def _pinned(t: str) -> bool:
    return bool(
        re.search(r"junit-gate\.yml@[0-9a-f]{40}", t)
        and re.search(r"exam-integrity\.yml@[0-9a-f]{40}", t)
    )


def _inline_checks_ok(t: str) -> bool:
    return "junit_gate" in t and "exam_integrity" in t


def _inline_integrity_pr_ok(t: str) -> bool:
    lines = t.splitlines()
    idx = [i for i, ln in enumerate(lines) if "exam_integrity" in ln]
    if not idx:
        return False
    block = "\n".join(lines[max(0, idx[0] - 15) : idx[-1] + 5])
    return "pull_request" in block


def _inline_bootstrap_ok(t: str) -> bool:
    comments = [ln for ln in t.splitlines() if ln.strip().startswith("#")]
    return (
        "--bootstrap" in t
        and any("bootstrap" in c.lower() for c in comments)
        and "git show" in t
    )


def _reusable_checks_ok(t: str) -> bool:
    return _pinned(t)


def _reusable_integrity_pr_ok(t: str) -> bool:
    jobs = yaml.safe_load(t)["jobs"]
    calls = [
        j
        for j in jobs.values()
        if re.search(r"exam-integrity\.yml@[0-9a-f]{40}$", str(j.get("uses")))
    ]
    return bool(calls) and all("pull_request" in str(j.get("if", "")) for j in calls)


def _reusable_no_local_judge_ok(t: str) -> bool:
    code = _code(t)
    return (
        _pinned(code)
        and "exam_integrity.py" not in code
        and "junit_gate.py" not in code
        and "--bootstrap" not in code
    )


def test_ci_workflow_runs_all_checks() -> None:
    t = workflow_text("ci.yml")
    assert "ruff check" in t
    assert "mypy src" in t
    assert "pytest" in t
    assert "tests/unit" in t
    assert "tests/acceptance" in t
    assert "--junitxml" in t
    assert _inline_checks_ok(t) or _reusable_checks_ok(t), "neither inline nor reusable judges"


def test_ci_workflow_exam_integrity_runs_on_pull_requests() -> None:
    t = workflow_text("ci.yml")
    assert _inline_integrity_pr_ok(t) or _reusable_integrity_pr_ok(t)


def test_bootstrap_mode_is_a_fallback_documented_in_a_comment() -> None:
    t = workflow_text("ci.yml")
    assert _inline_bootstrap_ok(t) or _reusable_no_local_judge_ok(t)


@pytest.mark.parametrize("name", workflows() or ["<none>"])
def test_every_action_is_pinned_by_a_full_commit_sha(name: str) -> None:
    assert name != "<none>", "no workflow files"
    uses = [
        ln.split("uses:", 1)[1].strip()
        for ln in workflow_text(name).splitlines()
        if re.match(r"^\s*-?\s*uses:", ln)
    ]
    for u in uses:
        if u.startswith("./"):
            continue
        assert re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}(\s|$)", u), f"{name}: {u}"


def test_gitattributes_forces_lf() -> None:
    t = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in t.splitlines()


def test_pyproject_declares_python_312_and_does_not_configure_pytest() -> None:
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    assert "3.12" in data["project"]["requires-python"]
    assert "[tool.pytest" not in raw
    assert "pytest" not in data.get("tool", {})
