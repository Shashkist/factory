"""Issue #76: the merge gate holds when the exam gate check did not conclude SUCCESS.

Configuration choice: the exam gate check is `acceptance / gate` by default and is
renamed with a CLI option on the command, `factory-tools merge-gate 9 --session S
--exam-gate "<check name>"` (like `--author` and `--repo`, which already configure the gate).

Observable behaviour only: the command against a fake `gh`. The harness (merge_gate_world)
adds a SUCCESS `acceptance / gate` to any non-empty rollup that lacks one, unless a case sets
`gh.exam_gate`; so older cases keep testing their own rule.
"""

import pytest
from merge_gate_world import EXAM_GATE, Gate, assert_single_hold, check

NAME = EXAM_GATE


@pytest.fixture
def make(tmp_path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


def rollup(*extra):
    return [check("unit"), check("exam-integrity"), *extra]


# ---- criterion 1: SUCCESS only, for the exam gate check ----------


@pytest.mark.parametrize("state", ["SKIPPED", "NEUTRAL"])
def test_exam_gate_check_skipped_or_neutral_holds_with_a_reason_naming_it(make, state):
    gh = make(statusCheckRollup=rollup(check(NAME, state)))
    assert_single_hold(gh.run(), NAME, state)


@pytest.mark.parametrize("state", ["FAILURE", "CANCELLED"])
def test_exam_gate_check_failed_or_cancelled_still_holds(make, state):
    gh = make(statusCheckRollup=rollup(check(NAME, state)))
    assert_single_hold(gh.run(), NAME, state)


def test_exam_gate_check_pending_holds(make):
    gh = make(statusCheckRollup=rollup(check(NAME, "", "IN_PROGRESS")))
    assert_single_hold(gh.run(), NAME, "pending")


def test_missing_exam_gate_check_holds_with_a_reason_naming_it(make):
    gh = make(statusCheckRollup=rollup())
    gh.exam_gate = None
    assert_single_hold(gh.run(), NAME)


def test_exam_gate_check_success_merges(make):
    gh = make(statusCheckRollup=rollup(check("acceptance / exam"), check(NAME)))
    assert gh.run() == (0, ["MERGE"])


@pytest.mark.parametrize("state", ["SKIPPED", "NEUTRAL"])
def test_other_checks_keep_the_rule_that_skipped_and_neutral_pass(make, state):
    gh = make(statusCheckRollup=rollup(check("lint", state), check("acceptance / exam", state)))
    assert gh.run() == (0, ["MERGE"])


def test_a_lookalike_name_is_not_the_exam_gate_check(make):
    lookalikes = [check("acceptance / gate-2"), check("x / acceptance / gate")]
    gh = make(statusCheckRollup=rollup(*lookalikes))
    gh.exam_gate = None
    assert_single_hold(gh.run(), NAME)


def test_exam_gate_name_can_be_configured_with_an_option(make):
    gh = make(statusCheckRollup=rollup(check("ci / exam gate", "SKIPPED")))
    gh.exam_gate = None
    assert_single_hold(gh.run("--exam-gate", "ci / exam gate"), "ci / exam gate", "skipped")


def test_configured_name_replaces_the_default_one(make):
    gh = make(statusCheckRollup=rollup(check("ci / exam gate"), check(NAME, "SKIPPED")))
    assert gh.run("--exam-gate", "ci / exam gate") == (0, ["MERGE"])


def test_configured_name_missing_holds(make):
    gh = make(statusCheckRollup=rollup())
    assert_single_hold(gh.run("--exam-gate", "ci / exam gate"), "ci / exam gate")


# ---- criterion 2: a PR whose acceptance call skipped is held; green PRs merge ----------


def test_pr_with_both_acceptance_checks_skipped_is_held(make):
    gh = make(
        statusCheckRollup=rollup(check("acceptance / exam", "SKIPPED"), check(NAME, "SKIPPED"))
    )
    code, lines = gh.run()
    hold = [ln for ln in lines if ln.startswith("HOLD: ")]
    assert code == 1 and "MERGE" not in lines, lines
    assert any(NAME in ln and "skipped" in ln.lower() for ln in hold), lines


def test_pr_with_only_the_exam_check_skipped_is_not_held_by_it_alone(make):
    gh = make(statusCheckRollup=rollup(check("acceptance / exam", "SKIPPED"), check(NAME)))
    assert gh.run() == (0, ["MERGE"])


def test_green_pr_with_all_checks_successful_still_merges(make):
    gh = make(statusCheckRollup=rollup(check("acceptance / exam"), check(NAME)))
    assert gh.run() == (0, ["MERGE"])


def test_default_world_with_the_default_checks_merges(make):
    assert make().run() == (0, ["MERGE"])


# ---- criterion 3: this repository's ci.yml passes no exam-paths / ci-paths ----------


def test_ci_yml_exam_integrity_call_passes_no_exam_paths_or_ci_paths():
    import yaml
    from helpers import workflow_text

    call = yaml.safe_load(workflow_text("ci.yml"))["jobs"]["exam-integrity"]
    with_ = call.get("with") or {}
    assert "exam-paths" not in with_ and "ci-paths" not in with_, with_
