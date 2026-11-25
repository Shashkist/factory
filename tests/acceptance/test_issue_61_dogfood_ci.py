"""Issue #61 (slice B of #5, D25): ci.yml calls the reusable workflows by a full SHA of main.

Reads ci.yml as data, and runs the merge gate against a fake `gh` for the check names.
"""

import re
import subprocess
from typing import Any

import pytest
import yaml
from helpers import ROOT, workflow_text
from merge_gate_world import Gate, assert_single_hold, check

JUNIT_USES = re.compile(r"^Shashkist/factory/\.github/workflows/junit-gate\.yml@([0-9a-f]{40})$")
EXAM_USES = re.compile(r"^Shashkist/factory/\.github/workflows/exam-integrity\.yml@([0-9a-f]{40})$")


def jobs() -> dict[str, Any]:
    data = yaml.safe_load(workflow_text("ci.yml"))
    return dict(data["jobs"])


def job(name: str) -> dict[str, Any]:
    j = jobs().get(name)
    assert isinstance(j, dict), f"ci.yml has no job {name!r}"
    return j


def code_text() -> str:
    return "\n".join(
        ln for ln in workflow_text("ci.yml").splitlines() if not ln.strip().startswith("#")
    )


def pin(name: str, rx: re.Pattern[str]) -> str:
    m = rx.match(str(job(name).get("uses", "")))
    uses = job(name).get("uses")
    assert m, f"job {name!r} does not use the reusable workflow by a full SHA: {uses}"
    return m.group(1)


# ---- criterion 2: ci.yml calls both workflows by full SHA ----------


def test_acceptance_job_calls_junit_gate_by_full_sha():
    pin("acceptance", JUNIT_USES)


def test_exam_integrity_job_calls_exam_integrity_by_full_sha():
    pin("exam-integrity", EXAM_USES)


def test_acceptance_test_command_keeps_the_runtime_defences():
    cmd = str((job("acceptance").get("with") or {}).get("test-command", ""))
    assert "tests/acceptance" in cmd, cmd
    assert "--junitxml" in cmd, cmd
    assert re.search(r"-c\s+pytest\.ini\b", cmd), cmd
    assert re.search(r"-o\s+addopts=(\"\"|'')", cmd), cmd
    assert "--confcutdir=tests" in cmd, cmd


def test_junit_file_matches_the_junitxml_path():
    w = job("acceptance").get("with") or {}
    m = re.search(r"--junitxml[= ]\s*(\S+)", str(w.get("test-command", "")))
    assert m, w
    assert w.get("junit-file", "acceptance.xml") == m.group(1).strip("\"'"), w


def test_exam_integrity_job_runs_only_for_pull_requests():
    cond = "".join(str(job("exam-integrity").get("if", "")).split())
    assert cond == "github.event_name=='pull_request'", cond


def test_both_calls_are_pinned_to_the_same_sha():
    assert pin("acceptance", JUNIT_USES) == pin("exam-integrity", EXAM_USES)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120
    )


def test_the_pinned_sha_is_a_commit_on_main():
    sha = pin("acceptance", JUNIT_USES)
    if git("cat-file", "-e", sha + "^{commit}").returncode != 0:
        if git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
            pytest.skip("shallow checkout: the pinned commit is not in the local history")
        pytest.fail(f"{sha} is not a commit of this repository")
    have_main = git("rev-parse", "--verify", "-q", "origin/main").returncode == 0
    # a PR's HEAD contains main, so without origin/main HEAD is the next best ancestor test
    main = "origin/main" if have_main else "HEAD"
    proc = git("merge-base", "--is-ancestor", sha, main)
    assert proc.returncode == 0, f"{sha} is not an ancestor of {main}: {proc.stderr}"


def test_ci_no_longer_runs_the_judge_scripts_from_the_checkout():
    code = code_text()  # non-comment lines only
    assert "exam_integrity.py" not in code
    assert "junit_gate.py" not in code
    assert "--bootstrap" not in code
    assert 'python3 "$script"' not in code


def test_checks_job_still_runs_ruff_mypy_and_unit_tests():
    steps = job("checks").get("steps") or []
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "ruff check" in runs
    assert "mypy src" in runs
    assert "pytest tests/unit" in runs


# ---- criterion 3: the merge gate sees the reusable check name ----------


@pytest.fixture
def make(tmp_path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


COUNTED = ["exam-integrity", "exam-integrity / exam-integrity", "ci / exam-integrity"]


@pytest.mark.parametrize("name", COUNTED)
def test_gate_merges_when_a_counted_exam_integrity_check_succeeds(make, name):
    gh = make(statusCheckRollup=[check("unit"), check(name)])
    code, lines = gh.run()
    assert (code, lines) == (0, ["MERGE"]), (code, lines)


@pytest.mark.parametrize("state", ["SKIPPED", "NEUTRAL", "FAILURE"])
@pytest.mark.parametrize("name", COUNTED[1:])
def test_gate_holds_when_a_suffixed_exam_integrity_check_is_not_success(make, name, state):
    gh = make(statusCheckRollup=[check("unit"), check(name, state)])
    assert_single_hold(gh.run(), name, state)


@pytest.mark.parametrize("name", COUNTED[1:])
def test_gate_holds_when_a_suffixed_exam_integrity_check_is_pending(make, name):
    gh = make(statusCheckRollup=[check("unit"), check(name, "", "IN_PROGRESS")])
    assert_single_hold(gh.run(), name, "pending")


@pytest.mark.parametrize(
    "name", ["exam-integrity-lint", "exam-integrity / other", "x / exam-integrity-2"]
)
def test_gate_does_not_count_lookalike_checks(make, name):
    gh = make(statusCheckRollup=[check("unit"), check(name)])
    assert_single_hold(gh.run(), "exam-integrity has not run")
