"""Issue #61 (slice B of #5, D25): ci.yml calls the reusable workflows by a full SHA of main.

Reads ci.yml as data, and runs the merge gate against a fake `gh` for the check names.
"""

import os
import re
import shlex
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


EXAM_COMMAND = (
    "uv run pytest -c pytest.ini tests/acceptance -q -o addopts=\"\" "
    "--confcutdir=tests --junitxml=acceptance.xml"
)


def test_acceptance_test_command_is_exactly_the_hardened_exam_command():
    cmd = str((job("acceptance").get("with") or {}).get("test-command", ""))
    assert shlex.split(cmd) == shlex.split(EXAM_COMMAND), cmd


def test_junit_file_matches_the_junitxml_path():
    w = job("acceptance").get("with") or {}
    m = re.search(r"--junitxml[= ]\s*(\S+)", str(w.get("test-command", "")))
    assert m, w
    assert w.get("junit-file", "acceptance.xml") == m.group(1).strip("\"'"), w


def test_exam_integrity_job_runs_only_for_pull_requests():
    cond = "".join(str(job("exam-integrity").get("if", "")).split())
    assert cond == "github.event_name=='pull_request'", cond


def test_acceptance_call_keeps_the_plugin_autoload_defence_on():
    # junit-gate.yml defaults disable-pytest-plugin-autoload to true (D3 amendment 1(b), D25):
    # leaving it out is fine, setting it to anything but true switches the defence off.
    w = job("acceptance").get("with") or {}
    assert w.get("disable-pytest-plugin-autoload", True) is True, w


def test_exam_integrity_call_does_not_steer_the_checked_range():
    # base-ref/head-sha-like inputs could make the checked range empty ("checked 0 commits: ok").
    # Only the path inputs planned in #65 may ever appear.
    w = job("exam-integrity").get("with") or {}
    assert set(w) <= {"exam-paths", "ci-paths"}, w


def test_acceptance_job_has_no_condition_that_could_skip_it():
    assert "if" not in job("acceptance"), job("acceptance").get("if")
    assert "needs" not in job("acceptance"), job("acceptance").get("needs")


def test_both_calls_are_pinned_to_the_same_sha():
    assert pin("acceptance", JUNIT_USES) == pin("exam-integrity", EXAM_USES)


GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
        env=GIT_ENV,
    )


def fetch_main(unshallow: bool = False) -> None:
    # CI checks out shallowly: fetch main's history from origin (public repo, anonymous)
    args = ["fetch", "-q", "--no-tags"]
    if unshallow:
        args.append("--unshallow")
    fetched = git(*args, "origin", "+refs/heads/main:refs/remotes/origin/main")
    if fetched.returncode != 0:
        pytest.fail(f"could not fetch origin/main to check the pin: {fetched.stderr}")


def test_the_pinned_sha_is_a_commit_on_main():
    sha = pin("acceptance", JUNIT_USES)
    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    have_sha = git("cat-file", "-e", sha + "^{commit}").returncode == 0
    have_main = git("rev-parse", "--verify", "-q", "origin/main").returncode == 0
    fetched = False
    if shallow or not have_sha or not have_main:
        fetch_main(unshallow=shallow)
        fetched = True
    if git("cat-file", "-e", sha + "^{commit}").returncode != 0:
        pytest.fail(f"{sha} is not a commit of this repository")
    proc = git("merge-base", "--is-ancestor", sha, "origin/main")
    if proc.returncode != 0 and not fetched:
        fetch_main()  # a stale local origin/main must not give a false red
        proc = git("merge-base", "--is-ancestor", sha, "origin/main")
    assert proc.returncode == 0, f"{sha} is not an ancestor of origin/main: {proc.stderr}"


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
