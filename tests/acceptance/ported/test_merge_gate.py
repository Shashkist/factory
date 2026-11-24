# Ported from Learning Factory scripts/test_merge_gate.py and scripts/test_merge_gate_review.py
# (#84, D148 and its amendments 1 to 3; spec G8). Changes versus LF:
#   - the gate is driven as the command `factory-tools merge-gate <pr> --session <s>
#     [--repo ...] [--author ...]` (`python -m factory_tools merge-gate`) against a fake `gh`
#     process (tests/acceptance/fake_gh_merge_gate.py) instead of `merge_gate.main(argv, run=...)`;
#     the fake serves the same hand-written JSON as LF's in-process fake.
#   - paths: LF's labs/manager/... example files became this repository's tests/acceptance/...
#     and src/... (this repository has no labs/); LF's scripts/test_*.py exam files have no
#     counterpart here.
#   - the live case (LF_GATE_LIVE, merged LF PR #560) is dropped: no live GitHub calls.
#   - test_timed_out_and_action_required_checks_hold is one case per state (parametrized).
#   Every other case and assertion is as in LF.
"""Exam: `factory-tools merge-gate <pr> --session <name>` decides MERGE or HOLD from facts only.

NO NETWORK. See tests/acceptance/merge_gate_world.py and fake_gh_merge_gate.py for the fake.
With --repo the gate reaches the repository the way the claim tools do (`-R repo` on gh
commands, the repo in api paths).
"""

from pathlib import Path

import pytest
from merge_gate_world import (
    CODE_FILE,
    EXAM_FILE,
    HEAD,
    OLD,
    OTHER,
    Gate,
    assert_single_hold,
    check,
    claim_comment,
    code_commits,
    holds,
    verdict,
)


@pytest.fixture
def make(tmp_path: Path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


# ---- all good -------------------------------------------------------------

def test_all_facts_good_prints_merge_and_exits_zero(make):
    assert make().run() == (0, ["MERGE"])


def test_neutral_and_skipped_checks_count_as_passed(make):
    gh = make(statusCheckRollup=[check("unit"), check("exam-integrity"),
                                 check("docker", "SKIPPED"), check("lint", "NEUTRAL")])
    assert gh.run() == (0, ["MERGE"])


def test_gate_is_read_only_and_only_reads(make):
    gh = make()
    gh.run()
    calls = gh.calls()
    assert calls and all(c[0] in ("pr", "api", "issue") for c in calls)


# ---- CI check states -------------------------------------------------------

def test_pending_check_holds(make):
    gh = make(statusCheckRollup=[check("unit", "", "IN_PROGRESS"), check("exam-integrity")])
    assert_single_hold(gh.run(), "unit", "pending")


def test_queued_check_holds(make):
    gh = make(statusCheckRollup=[check("unit", "", "QUEUED"), check("exam-integrity")])
    assert_single_hold(gh.run(), "unit")


def test_failed_check_holds(make):
    gh = make(statusCheckRollup=[check("unit", "FAILURE"), check("exam-integrity")])
    assert_single_hold(gh.run(), "unit", "failure")


def test_cancelled_check_holds(make):
    gh = make(statusCheckRollup=[check("unit", "CANCELLED"), check("exam-integrity")])
    assert_single_hold(gh.run(), "unit", "cancelled")


@pytest.mark.parametrize("state", ["TIMED_OUT", "ACTION_REQUIRED"])
def test_timed_out_and_action_required_checks_hold(make, state):
    gh = make(statusCheckRollup=[check("unit", state), check("exam-integrity")])
    assert_single_hold(gh.run(), "unit")


def test_no_checks_at_all_holds(make):
    code, lines = make(statusCheckRollup=[]).run()
    assert code == 1 and holds(lines)
    assert any("check" in ln.lower() for ln in holds(lines))
    assert "MERGE" not in lines


def test_missing_exam_integrity_check_holds(make):
    gh = make(statusCheckRollup=[check("unit")])
    assert_single_hold(gh.run(), "exam-integrity")


def test_failed_exam_integrity_check_holds(make):
    gh = make(statusCheckRollup=[check("unit"), check("exam-integrity", "FAILURE")])
    assert_single_hold(gh.run(), "exam-integrity")


def test_skipped_exam_integrity_holds(make):
    gh = make(statusCheckRollup=[check("unit"), check("exam-integrity", "SKIPPED")])
    assert_single_hold(gh.run(), "exam-integrity")


def test_neutral_exam_integrity_holds(make):
    gh = make(statusCheckRollup=[check("unit"), check("exam-integrity", "NEUTRAL")])
    assert_single_hold(gh.run(), "exam-integrity")


# ---- verdict -----------------------------------------------------------------

def test_no_verdict_comment_holds(make):
    assert_single_hold(make(comments=[]).run(), "verdict")


def test_changes_verdict_for_head_holds(make):
    assert_single_hold(make(comments=[verdict("CHANGES")]).run(), "verdict")


def test_latest_verdict_wins_changes_after_approve_holds(make):
    gh = make(comments=[verdict("APPROVE", at="2026-11-24T10:00:00Z"),
                        verdict("CHANGES", at="2026-11-24T11:00:00Z")])
    assert_single_hold(gh.run(), "verdict")


def test_latest_verdict_wins_approve_after_changes_merges(make):
    gh = make(comments=[verdict("CHANGES", at="2026-11-24T10:00:00Z"),
                        verdict("APPROVE", sha=HEAD, k=2, at="2026-11-24T11:00:00Z")])
    assert gh.run() == (0, ["MERGE"])


def test_approve_for_an_older_sha_holds(make):
    assert_single_hold(make(comments=[verdict("APPROVE", sha=OLD)]).run(), "verdict")


def test_short_sha_prefix_of_head_counts(make):
    assert make(comments=[verdict("APPROVE", sha=HEAD[:7])]).run() == (0, ["MERGE"])


def test_prose_line_containing_approve_is_not_a_verdict(make):
    gh = make(comments=[verdict(body="I APPROVE of this change at " + HEAD),
                        verdict(body="Verdict: APPROVE")])
    assert_single_hold(gh.run(), "verdict")


def test_verdict_must_be_the_first_line(make):
    c = verdict()
    c["body"] = "Looks fine.\n" + c["body"]
    assert_single_hold(make(comments=[c]).run(), "verdict")


def test_verdict_from_another_author_is_ignored(make):
    gh = make(comments=[verdict("APPROVE", author="passer-by")])
    assert_single_hold(gh.run(), "verdict")


def test_other_authors_changes_does_not_override_an_approve(make):
    gh = make(comments=[verdict("APPROVE", at="2026-11-24T10:00:00Z"),
                        verdict("CHANGES", author="passer-by", at="2026-11-24T11:00:00Z")])
    assert gh.run() == (0, ["MERGE"])


def test_author_option_names_who_may_post_the_verdict(make):
    gh = make(comments=[verdict("APPROVE", author="reviewer-bot")])
    assert gh.run("--author", "reviewer-bot") == (0, ["MERGE"])


def test_author_option_rejects_the_pr_author_when_another_is_named(make):
    gh = make(comments=[verdict("APPROVE", author="Shashkist")])
    assert_single_hold(gh.run("--author", "reviewer-bot"), "verdict")


# ---- rounds ------------------------------------------------------------------

def test_review_round_three_holds(make):
    gh = make(comments=[verdict("CHANGES", k=1, at="2026-11-24T08:00:00Z"),
                        verdict("CHANGES", k=2, sha=OLD, at="2026-11-24T09:00:00Z"),
                        verdict("APPROVE", k=3, at="2026-11-24T10:00:00Z")])
    assert_single_hold(gh.run(), "review round")


def test_review_round_two_still_merges(make):
    gh = make(comments=[verdict("CHANGES", k=1, sha=OLD, at="2026-11-24T08:00:00Z"),
                        verdict("APPROVE", k=2, at="2026-11-24T10:00:00Z")])
    assert gh.run() == (0, ["MERGE"])


def test_six_code_commits_hold(make):
    oids, commits = code_commits(6)
    gh = make(commits=commits)
    gh.files = {o: [CODE_FILE] for o in oids}
    assert_single_hold(gh.run(), "ci round")


def test_five_code_commits_still_merge(make):
    oids, commits = code_commits(5)
    gh = make(commits=commits)
    gh.files = {o: [CODE_FILE] for o in oids}
    assert gh.run() == (0, ["MERGE"])


def test_exam_only_commits_are_not_counted(make):
    exam = [format(100 + i, "040x") for i in range(4)]
    oids, commits = code_commits(5)
    gh = make(commits=[{"oid": o} for o in exam] + commits)
    gh.files = {o: [EXAM_FILE] for o in exam}
    gh.files.update({o: [CODE_FILE] for o in oids})
    # 9 commits, but only 5 of them change code: 5 CI rounds, within the limit.
    assert gh.run() == (0, ["MERGE"])


def test_tests_acceptance_commits_are_not_ci_rounds(make):
    exam = "0" * 39 + "9"
    oids, commits = code_commits(5)
    gh = make(commits=[{"oid": exam}] + commits)
    gh.files = {o: [CODE_FILE] for o in oids}
    gh.files[exam] = ["tests/acceptance/test_issue_14_x.py"]
    assert gh.run() == (0, ["MERGE"])


# ---- claim -------------------------------------------------------------------

def test_claim_held_by_another_session_holds(make):
    gh = make()
    gh.issues["5"] = [claim_comment("lf-someone-else")]
    assert_single_hold(gh.run(), "claim")


def test_released_claim_holds(make):
    gh = make()
    gh.issues["5"] = [claim_comment("lf-pass-1", released=True)]
    assert_single_hold(gh.run(), "claim")


def test_no_claim_holds(make):
    gh = make()
    gh.issues["5"] = []
    assert_single_hold(gh.run(), "claim")


def test_no_linked_issue_holds(make):
    gh = make(body="What. No closing keyword here, only #5 in prose.")
    assert_single_hold(gh.run(), "issue")


def test_claim_is_read_for_the_issue_named_by_closes(make):
    gh = make(body="Text\n\nCloses #42\n")
    gh.run()
    views = [c for c in gh.calls() if c[:2] == ["issue", "view"]]
    assert views and views[0][2] == "42"


def test_closes_in_the_middle_of_a_sentence_is_ignored(make):
    gh = make(body="This partially closes #7 of the plan.")
    assert_single_hold(gh.run(), "issue")


def test_every_closes_line_needs_the_claim(make):
    gh = make(body="What.\n\nCloses #5\nCloses #7\n")
    code, lines = gh.run()
    assert code == 1 and len(lines) == 1 and "#7" in lines[0] and "claim" in lines[0]


def test_two_closes_lines_both_claimed_merge(make):
    gh = make(body="Closes #5\nCloses #7\n")
    gh.issues["7"] = [claim_comment(number=7)]
    assert gh.run() == (0, ["MERGE"])


def test_closing_keyword_anywhere_needs_the_claim(make):
    gh = make(body="Closes #5\nThis also fixes #7.\n",
              closingIssuesReferences=[{"number": 5}, {"number": 7}])
    code, lines = gh.run()
    assert code == 1 and len(lines) == 1 and "#7" in lines[0] and "claim" in lines[0]


def test_closing_an_issue_in_another_repository_holds(make):
    gh = make(url="https://github.com/o/r/pull/9",
              closingIssuesReferences=[{"number": 5, "url": "https://github.com/o/r/issues/5"},
                                       {"number": 3, "url": "https://github.com/x/y/issues/3"}])
    assert_single_hold(gh.run(), "another repository")


def test_cross_repository_pr_holds(make):
    assert_single_hold(make(isCrossRepository=True).run(), "cross-repository")


def test_same_repository_pr_merges(make):
    assert make(isCrossRepository=False).run() == (0, ["MERGE"])


# ---- several reasons, repo option ---------------------------------------------------

def test_several_reasons_give_several_hold_lines(make):
    gh = make(statusCheckRollup=[check("unit", "FAILURE"), check("exam-integrity")], comments=[])
    gh.issues["5"] = [claim_comment("lf-someone-else")]
    code, lines = gh.run()
    assert code == 1
    assert len(lines) >= 3 and all(ln.startswith("HOLD: ") for ln in lines), lines
    text = "\n".join(lines).lower()
    for word in ("unit", "verdict", "claim"):
        assert word in text
    assert "MERGE" not in lines


def test_repo_option_reaches_that_repository_with_dash_R(make):
    gh = make()
    assert gh.run("--repo", OTHER) == (0, ["MERGE"])
    for c in gh.calls():
        if c[0] == "api":
            paths = [a for a in c if a.startswith("repos/")]
            assert any(OTHER in a or "{owner}/{repo}" in a for a in paths), c
        else:
            assert c[c.index("-R") + 1] == OTHER, c


def test_without_repo_option_no_dash_R(make):
    gh = make()
    gh.run()
    calls = gh.calls()
    assert calls and not any("-R" in c for c in calls)
