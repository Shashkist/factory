"""Issue #35: the merge gate as `factory-tools merge-gate` (from #28, LF D148).

Observable behaviour only: the command line (run as `python -m factory_tools merge-gate`, the
same entry point as the `factory-tools` script) against a fake `gh` process, and the text of
the plugin's manager skill. No live GitHub call.

Criterion 1 (the ported LF exam passes against fakes) lives in tests/acceptance/ported/
test_merge_gate.py. Here: criteria 2 and 3, and the scope items LF's exam does not cover.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import ROOT, env
from merge_gate_world import (
    CODE_FILE,
    EXAM_FILE,
    HEAD,
    HERE,
    OLD,
    SESSION,
    Gate,
    assert_single_hold,
    check,
    claim_comment,
)

SKILL = ROOT / "plugin" / "skills" / "factory" / "SKILL.md"


@pytest.fixture
def make(tmp_path: Path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


# ---- criterion 2: --help lists the three arguments ----------


def test_help_lists_pr_repo_and_session():
    proc = subprocess.run(
        [sys.executable, "-m", "factory_tools", "merge-gate", "--help"],
        cwd=ROOT, env=env(), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert re.search(r"\bpr\b", out, re.IGNORECASE), out
    assert "--repo" in out, out
    assert "--session" in out, out


def test_merge_gate_is_listed_by_the_top_level_help():
    proc = subprocess.run(
        [sys.executable, "-m", "factory_tools", "--help"],
        cwd=ROOT, env=env(), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "merge-gate" in proc.stdout


# ---- criterion 3: the plugin skill's merge step works unchanged ----------


def skill_merge_line() -> str:
    for line in SKILL.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("factory-tools merge-gate"):
            return line.strip()
    raise AssertionError("no `factory-tools merge-gate ...` line in " + str(SKILL))


def test_skill_names_the_merge_gate_command_with_the_three_arguments():
    line = skill_merge_line()
    assert "<pr>" in line and "--repo <repo>" in line and "--session <you>" in line, line


def fill(line: str, pr: str, repo: str, session: str) -> list[str]:
    """The skill's line with its placeholders replaced, as the manager would."""
    filled = line.replace("<pr>", pr).replace("<repo>", repo).replace("<you>", session)
    assert "<" not in filled, "a placeholder is left unfilled: " + filled
    argv = shlex.split(filled)
    assert argv[:2] == ["factory-tools", "merge-gate"], argv
    return argv[2:]


def test_skill_command_line_is_accepted_unchanged_and_merges(make):
    argv = fill(skill_merge_line(), "9", HERE, SESSION)
    proc = make().command("merge-gate", *argv)
    assert (proc.returncode, proc.stdout.split()) == (0, ["MERGE"]), proc.stderr


def test_skill_command_line_holds_with_a_reason_per_line(make):
    gh = make(statusCheckRollup=[check("unit", "FAILURE"), check("exam-integrity")], comments=[])
    argv = fill(skill_merge_line(), "9", HERE, SESSION)
    proc = gh.command("merge-gate", *argv)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert proc.returncode != 0
    assert len(lines) >= 2 and all(ln.startswith("HOLD: ") for ln in lines), lines


def test_skill_command_uses_the_session_it_is_given(make):
    argv = fill(skill_merge_line(), "9", HERE, "someone-else")
    proc = make().command("merge-gate", *argv)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert proc.returncode == 1
    assert len(lines) == 1 and "claim" in lines[0].lower() and "someone-else" in lines[0], lines


# ---- usage errors ----------


@pytest.mark.parametrize("argv", [["9"], ["--session", SESSION]])
def test_pr_and_session_are_required(make, argv):
    proc = make().command("merge-gate", *argv)
    assert proc.returncode != 0
    assert "MERGE" not in proc.stdout.split()
    assert "invalid choice" not in proc.stderr, proc.stderr  # the command must exist
    missing = "--session" if argv == ["9"] else "pr"
    assert missing in proc.stderr, proc.stderr


# ---- scope: no tests/acceptance change in the same commit as code ----------


def test_commit_touching_tests_acceptance_together_with_code_holds(make):
    gh = make()
    gh.files[HEAD] = [EXAM_FILE, CODE_FILE]
    assert_single_hold(gh.run(), "acceptance")


def test_mixed_commit_earlier_in_the_pr_holds(make):
    gh = make()
    gh.files[OLD] = ["tests/acceptance/test_issue_5_y.py", "src/factory_tools/other.py"]
    gh.files[HEAD] = ["src/factory_tools/thing.py"]
    assert_single_hold(gh.run(), "acceptance")


def test_exam_only_and_code_only_commits_are_fine(make):
    gh = make()
    gh.files[OLD] = ["tests/acceptance/test_issue_5_x.py", "tests/acceptance/helpers.py"]
    gh.files[HEAD] = ["src/factory_tools/thing.py", "tests/unit/test_thing.py"]
    assert gh.run() == (0, ["MERGE"])


# ---- scope: the claim in every repository the PR closes ----------


def test_claim_is_checked_in_the_repository_of_the_pr(make):
    gh = make()
    gh.issues["5"] = [claim_comment("another-session")]
    assert_single_hold(gh.run("--repo", HERE), "claim")


def test_every_closed_issue_needs_the_claim_of_this_session(make):
    gh = make(body="Closes #5\nCloses #6\n")
    gh.issues["6"] = [claim_comment("another-session", number=6)]
    code, lines = gh.run()
    assert code == 1 and len(lines) == 1 and "#6" in lines[0], lines


# ---- scope: the verdict is for the current head ----------


def test_head_moved_since_the_approval_holds(make):
    gh = make(headRefOid=OLD[:-1] + "f")
    gh.pr["commits"] = [{"oid": gh.pr["headRefOid"]}]
    gh.files = {gh.pr["headRefOid"]: [CODE_FILE]}
    assert_single_hold(gh.run(), "verdict")
