"""Issue #75: the merge gate takes the exam and CI-surface globs (D34).

Observable behaviour only: `factory-tools merge-gate` run as a command against the fake gh of
the gate world (see test_issue_35_merge_gate.py). `--exam-paths` and `--ci-paths` have the
form of the exam-integrity judge's options: repeatable, each value split on white space.
"""

from pathlib import Path

import pytest
from merge_gate_world import (
    CODE_FILE,
    EXAM_FILE,
    HEAD,
    OLD,
    Gate,
    assert_single_hold,
    code_commits,
)

NESTED_GLOB = "labs/*/tests/acceptance/**"
NESTED_EXAM = "labs/x/tests/acceptance/test_issue_5_x.py"
NESTED_CODE = "labs/x/app/thing.py"
CI_GLOB = "labs/x/ci/**"
CI_FILE = "labs/x/ci/pipeline.yml"


@pytest.fixture
def make(tmp_path: Path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


def _mixed(make) -> Gate:
    gh = make()
    gh.files[HEAD] = [NESTED_EXAM, NESTED_CODE]
    return gh


# ---- criterion 1: the gate takes the globs as options ----------


def test_the_options_are_accepted_and_a_good_pr_still_merges(make):
    gh = make()
    gh.files = {OLD: [NESTED_CODE], HEAD: [NESTED_CODE]}
    code, lines = gh.run("--exam-paths", NESTED_GLOB, "--ci-paths", CI_GLOB)
    assert (code, lines) == (0, ["MERGE"])


def test_help_lists_the_two_options(make):
    proc = make().command("merge-gate", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--exam-paths" in proc.stdout and "--ci-paths" in proc.stdout, proc.stdout


# ---- criterion 2: a nested-layout PR mixing exam and code in one commit is held ----------


def test_nested_commit_mixing_exam_and_code_is_held_with_the_exam_paths_option(make):
    result = _mixed(make).run("--exam-paths", NESTED_GLOB)
    assert_single_hold(result, HEAD[:7], "together")


def test_exam_paths_value_with_several_globs_split_on_white_space(make):
    result = _mixed(make).run("--exam-paths", "docs/none/** " + NESTED_GLOB)
    assert_single_hold(result, HEAD[:7], "together")


def test_exam_paths_may_be_repeated(make):
    result = _mixed(make).run("--exam-paths", "docs/none/**", "--exam-paths", NESTED_GLOB)
    assert_single_hold(result, HEAD[:7], "together")


def test_the_same_nested_pr_without_the_option_is_not_held_for_mixing(make):
    code, lines = _mixed(make).run()
    assert (code, lines) == (0, ["MERGE"])


def test_nested_exam_in_its_own_commit_is_not_held_with_the_option(make):
    gh = make()
    gh.files = {OLD: [NESTED_EXAM], HEAD: [NESTED_CODE]}
    assert gh.run("--exam-paths", NESTED_GLOB) == (0, ["MERGE"])


# ---- the CI-round count uses the exam globs ----------


def _six_commits(make) -> Gate:
    """Five commits that change only the nested exam, then one that changes code."""
    oids, commits = code_commits(6)
    gh = make(commits=commits, headRefOid=HEAD)
    gh.pr["commits"] = commits[:-1] + [{"oid": HEAD}]
    oids = [c["oid"] for c in gh.pr["commits"]]
    gh.files = {o: [NESTED_EXAM] for o in oids[:-1]}
    gh.files[oids[-1]] = [NESTED_CODE]
    return gh


def test_all_nested_exam_commits_are_not_ci_rounds_with_the_option(make):
    assert _six_commits(make).run("--exam-paths", NESTED_GLOB) == (0, ["MERGE"])


def test_without_the_option_six_nested_commits_are_over_the_ci_round_limit(make):
    result = _six_commits(make).run()
    assert_single_hold(result, "ci round")


# ---- the CI-surface hold ----------


def _exam_then_ci(make, exam: str, ci: str) -> Gate:
    gh = make()
    gh.files = {OLD: [exam], HEAD: [ci]}
    return gh


def test_exam_and_ci_surface_across_commits_is_held_with_ci_paths(make):
    gh = _exam_then_ci(make, NESTED_EXAM, CI_FILE)
    result = gh.run("--exam-paths", NESTED_GLOB, "--ci-paths", CI_GLOB)
    assert_single_hold(result, "exam", "ci")


def test_ci_paths_alone_holds_exam_and_ci_surface_with_the_default_exam_rules(make):
    gh = _exam_then_ci(make, EXAM_FILE, CI_FILE)
    assert_single_hold(gh.run("--ci-paths", CI_GLOB), "exam", "ci")


def test_exam_paths_alone_holds_exam_and_the_default_ci_surface(make):
    gh = _exam_then_ci(make, NESTED_EXAM, ".github/workflows/ci.yml")
    assert_single_hold(gh.run("--exam-paths", NESTED_GLOB), "exam", "ci")


def test_ci_surface_without_the_exam_is_not_held(make):
    gh = _exam_then_ci(make, NESTED_CODE, CI_FILE)
    code, lines = gh.run("--exam-paths", NESTED_GLOB, "--ci-paths", CI_GLOB)
    assert (code, lines) == (0, ["MERGE"])


# ---- the defaults keep today's behaviour ----------


def test_without_options_exam_and_ci_surface_is_not_held(make):
    gh = _exam_then_ci(make, EXAM_FILE, "src/factory_tools/ci/exam_integrity.py")
    assert gh.run() == (0, ["MERGE"])


def test_without_options_a_top_level_mixed_commit_is_still_held(make):
    gh = make()
    gh.files[HEAD] = [EXAM_FILE, CODE_FILE]
    assert_single_hold(gh.run(), HEAD[:7], "together")
