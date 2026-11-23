"""Issue #1, criteria 3, 4 and 6: workflow files, pinning, project config."""

import re
import tomllib

import pytest
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
    assert "junit_gate" in t
    assert "exam_integrity" in t


def test_ci_workflow_exam_integrity_runs_on_pull_requests() -> None:
    lines = workflow_text("ci.yml").splitlines()
    idx = [i for i, ln in enumerate(lines) if "exam_integrity" in ln]
    assert idx, "no exam_integrity step"
    block = "\n".join(lines[max(0, idx[0] - 15) : idx[-1] + 5])
    assert "pull_request" in block


def test_bootstrap_mode_is_a_fallback_documented_in_a_comment() -> None:
    t = workflow_text("ci.yml")
    assert "--bootstrap" in t
    comments = [ln for ln in t.splitlines() if ln.strip().startswith("#")]
    assert any("bootstrap" in c.lower() for c in comments), "no comment on bootstrap"
    # the base branch copy is preferred: fetched from the base ref with git show
    assert "git show" in t


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
