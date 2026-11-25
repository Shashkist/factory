"""Issue #1, criteria 3, 4 and 6: workflow files, pinning, project config."""

import re
import tomllib

import pytest
import yaml
from helpers import ROOT, workflow_text

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


def test_ci_workflow_runs_all_checks() -> None:
    t = workflow_text("ci.yml")
    assert "ruff check" in t
    assert "mypy src" in t
    assert "pytest" in t
    assert "tests/unit" in t
    assert "tests/acceptance" in t
    assert "--junitxml" in t
    # D25: the judges are calls to the reusable workflows, pinned by a full SHA
    assert re.search(r"junit-gate\.yml@[0-9a-f]{40}", t), "no pinned junit-gate.yml call"
    assert re.search(r"exam-integrity\.yml@[0-9a-f]{40}", t), "no pinned exam-integrity.yml call"


def test_ci_workflow_exam_integrity_runs_on_pull_requests() -> None:
    # D25: the calling job carries the pull_request condition
    jobs = yaml.safe_load(workflow_text("ci.yml"))["jobs"]
    calls = [
        j
        for j in jobs.values()
        if re.search(r"exam-integrity\.yml@[0-9a-f]{40}$", str(j.get("uses")))
    ]
    assert calls, "no job calls exam-integrity.yml@<sha>"
    for j in calls:
        assert "pull_request" in str(j.get("if", "")), j


def test_judge_is_not_run_from_the_prs_tree() -> None:
    # D25 (replaces the bootstrap-comment case): both calls are pinned to a full SHA and
    # ci.yml runs no exam_integrity.py / junit_gate.py from the checkout.
    t = workflow_text("ci.yml")
    lines = [ln for ln in t.splitlines() if not ln.strip().startswith("#")]
    code = chr(10).join(lines)
    assert re.search(r"junit-gate\.yml@[0-9a-f]{40}", code)
    assert re.search(r"exam-integrity\.yml@[0-9a-f]{40}", code)
    assert "exam_integrity.py" not in code
    assert "junit_gate.py" not in code
    assert "--bootstrap" not in code


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
