"""Issue #102: the merge gate merges past the review-round limit under D36 (owner, O27).

Observable behaviour only: `python -m factory_tools merge-gate` against the fake `gh` of the
merge gate world, with a DECISIONS.md the exam writes. No live GitHub call.

The limit is the gate's review-round limit (2). Pull request #9 closes issue #5.

The contract this exam pins (the implementer may not change it):

* The gate reads the decision log from `--decisions PATH`; without the option, from
  `docs/factory/DECISIONS.md` relative to the current directory. A missing file means no
  D-entries, so the limit holds as today.
* A D-entry is a section of that file that starts at a line `## D<n>` (for example
  `## D33 · #67: ...`) and runs to the next line that starts with `## ` or the end of file.
* A D-entry names a round of this PR when the text of that one section contains BOTH
  a reference to the PR or to an issue it closes (`#9` or `#5`, with a word boundary, so `#90`
  is not `#9`) AND the words `round <k>` (case-insensitive, `round 3` is not `round 30`).
  One section may name several rounds. The round and the PR must be in the same section.
* Extra rounds are the review rounds numbered above the limit (3, 4, ...), read from the
  `Review round <k>: APPROVE|CHANGES at <sha>` verdicts of the PR author. The PR merges past
  the limit only when: every extra round has a D-entry naming it; every extra round except the
  latest verdict is a CHANGES verdict (the latest one, the fresh reviewer's, is the APPROVE);
  the latest verdict is APPROVE at the exact head commit; and every other rule of the gate
  (checks, exam integrity, claims) holds. Otherwise the gate HOLDs.
* A HOLD for a missing D-entry names the round (`round <k>`) of each extra round that has none.
* On MERGE past the limit the gate prints, before the final `MERGE` line, one line per matched
  D-entry that contains its id (`D32`) and the rounds it was matched for (`round 3`). It prints
  no line for a D-entry that was not matched. Within the limit the output is exactly `MERGE`.
"""

from pathlib import Path

import pytest
from merge_gate_world import HEAD, OLD, Gate, check, verdict

DEC = "DECISIONS.md"
TOP = "# Decisions\n\nSome intro.\n\n"


@pytest.fixture
def make(tmp_path: Path):
    def build(**over):
        return Gate(tmp_path, **over)

    return build


def entry(n: int, text: str) -> str:
    return "## D" + str(n) + " · a decision\n**Decision.** " + text + "\n\n"


def write_log(gh: Gate, *entries: str) -> str:
    path = gh.base / DEC
    path.write_text(TOP + "".join(entries), encoding="utf-8")
    return str(path)


def rounds(last: int, kinds: dict[int, str] | None = None, sha_last: str = HEAD) -> list[dict]:
    """Verdicts for rounds 1..last: CHANGES (at an old commit) except the last, an APPROVE."""
    kinds = kinds or {}
    out = []
    for k in range(1, last + 1):
        kind = kinds.get(k, "APPROVE" if k == last else "CHANGES")
        sha = sha_last if k == last else OLD
        out.append(verdict(kind, sha=sha, k=k, at=f"2026-11-24T{8 + k:02d}:00:00Z"))
    return out


def holds_of(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.startswith("HOLD: ")]


def assert_hold(result: tuple[int, list[str]], *words: str) -> str:
    code, lines = result
    assert code == 1, result
    assert "MERGE" not in lines, lines
    text = "\n".join(holds_of(lines)).lower()
    assert holds_of(lines), lines
    for w in words:
        assert w.lower() in text, (w, lines)
    return text


# ---- criterion 1: decided rounds past the limit, fresh APPROVE at head, checks green: MERGE ----


def test_criterion_1_two_extra_rounds_each_decided_with_approve_at_head_merge(make):
    gh = make(comments=rounds(4))
    log = write_log(
        gh,
        entry(31, "Not this one, it names no PR. round 3 elsewhere."),
        entry(32, "PR #9 round 3 found a hole; fixed in one more commit."),
        entry(33, "PR #9: round 4 verifies the fix."),
    )
    code, lines = gh.run("--decisions", log)
    assert (code, lines[-1:]) == (0, ["MERGE"]), (code, lines)


def test_criterion_1_one_extra_round_decided_with_approve_at_head_merges(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(40, "Issue #5, round 3: the manager decides what it fixes."))
    code, lines = gh.run("--decisions", log)
    assert (code, lines[-1:]) == (0, ["MERGE"]), (code, lines)


def test_criterion_1_one_entry_may_name_several_rounds(make):
    gh = make(comments=rounds(4))
    log = write_log(gh, entry(41, "PR #9: round 3 and round 4 are decided here."))
    code, lines = gh.run("--decisions", log)
    assert (code, lines[-1:]) == (0, ["MERGE"]), (code, lines)


def test_criterion_1_the_default_log_path_is_docs_factory_decisions_md(make):
    gh = make(comments=rounds(3))
    default = gh.base / "work" / "docs" / "factory"
    default.mkdir(parents=True)
    (default / DEC).write_text(TOP + entry(42, "PR #9 round 3 is decided."), encoding="utf-8")
    code, lines = gh.run()
    assert (code, lines[-1:]) == (0, ["MERGE"]), (code, lines)


# ---- criterion 2: an extra round with no D-entry holds, naming the round ----


def test_criterion_2_one_extra_round_without_any_d_entry_holds_naming_the_round(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(43, "An unrelated decision about #12, round 1."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_criterion_2_without_a_decision_log_the_limit_holds_as_today(make):
    gh = make(comments=rounds(3))
    assert_hold(gh.run("--decisions", str(gh.base / "no-such-file.md")), "round 3")


def test_criterion_2_two_extra_rounds_only_one_decided_holds_naming_the_missing_one(make):
    gh = make(comments=rounds(4))
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    text = assert_hold(gh.run("--decisions", log), "round 4")
    assert "round 3" not in text, text


def test_criterion_2_two_extra_rounds_only_the_later_decided_names_the_earlier(make):
    gh = make(comments=rounds(4))
    log = write_log(gh, entry(33, "PR #9 round 4 is decided."))
    text = assert_hold(gh.run("--decisions", log), "round 3")
    assert "round 4" not in text, text


def test_criterion_2_a_d_entry_that_names_the_round_but_another_pr_and_issue_holds(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(44, "PR #8, issue #7, round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_criterion_2_pr_90_is_not_pr_9(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(45, "PR #90 round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_criterion_2_a_d_entry_that_names_the_pr_but_not_that_round_holds(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(46, "PR #9 round 2 is decided; round 30 too."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_criterion_2_the_pr_and_the_round_must_be_in_the_same_d_entry(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(47, "PR #9 is mentioned here."), entry(48, "Round 3 is here."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_criterion_2_text_before_the_first_d_heading_is_not_a_d_entry(make):
    gh = make(comments=rounds(3))
    path = gh.base / DEC
    path.write_text(
        "# Decisions\n\nPR #9 round 3 is decided.\n\n## Not a D heading\nPR #9 round 3\n",
        encoding="utf-8",
    )
    assert_hold(gh.run("--decisions", str(path)), "round 3")


# ---- the rounds themselves: CHANGES, then a fresh APPROVE ----


def test_an_extra_round_that_was_an_approve_followed_by_more_rounds_holds(make):
    gh = make(comments=rounds(4, kinds={3: "APPROVE"}))
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."), entry(33, "PR #9 round 4 too."))
    assert_hold(gh.run("--decisions", log), "round 3")


def test_the_latest_verdict_being_changes_holds(make):
    gh = make(comments=rounds(3, kinds={3: "CHANGES"}))
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "verdict")


# ---- criterion 3: the latest verdict is APPROVE, but not at the head commit ----


def test_criterion_3_approve_at_another_commit_holds_even_with_every_round_decided(make):
    gh = make(comments=rounds(4, sha_last=OLD))
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."), entry(33, "PR #9 round 4 too."))
    assert_hold(gh.run("--decisions", log), "verdict")


def test_criterion_3_head_moved_after_the_approve_holds(make):
    new_head = "f" * 40
    gh = make(comments=rounds(3), headRefOid=new_head)
    gh.pr["commits"] = [{"oid": OLD}, {"oid": new_head}]
    gh.files[new_head] = gh.files[HEAD]
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "verdict")


# ---- criterion 4: a new PR with the same commits does not reset the count ----


def test_criterion_4_decisions_of_the_held_pr_do_not_decide_the_new_pr(make):
    # The reviewer keeps counting on the new PR (#9): rounds 3 and 4. The decisions were
    # taken for the held PR (#8, issue #7), so none of them names this PR or its issue.
    gh = make(comments=rounds(4))
    log = write_log(gh, entry(32, "PR #8 round 3 is decided."), entry(33, "PR #8 round 4 too."))
    assert_hold(gh.run("--decisions", log), "round 3", "round 4")


# ---- criterion 5: the gate prints which D-entries it matched ----


def test_criterion_5_the_gate_prints_the_matched_d_entries_and_only_those(make):
    gh = make(comments=rounds(4))
    log = write_log(
        gh,
        entry(31, "PR #12 round 3 belongs to another PR."),
        entry(32, "PR #9 round 3 found a hole."),
        entry(33, "PR #9 round 4 verifies it."),
    )
    code, lines = gh.run("--decisions", log)
    assert code == 0 and lines[-1] == "MERGE", (code, lines)
    printed = lines[:-1]
    d32 = [ln for ln in printed if "D32" in ln]
    d33 = [ln for ln in printed if "D33" in ln]
    assert len(d32) == 1 and "round 3" in d32[0].lower(), printed
    assert len(d33) == 1 and "round 4" in d33[0].lower(), printed
    assert not any("D31" in ln for ln in printed), printed


# ---- the other rules still hold, a D-entry overrides only the round limit ----


@pytest.mark.parametrize(
    "rollup",
    [
        [check("unit", "FAILURE"), check("exam-integrity")],
        [check("unit", "", "IN_PROGRESS"), check("exam-integrity")],
    ],
    ids=["red", "pending"],
)
def test_approve_at_head_but_a_required_check_not_green_holds(make, rollup):
    gh = make(comments=rounds(3), statusCheckRollup=rollup)
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "unit")


def test_exam_integrity_still_holds_past_the_limit(make):
    gh = make(comments=rounds(3))
    gh.files[HEAD] = ["tests/acceptance/test_issue_5_x.py", "src/factory_tools/thing.py"]
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    assert_hold(gh.run("--decisions", log), "acceptance")


def test_the_claim_still_holds_past_the_limit(make):
    gh = make(comments=rounds(3))
    log = write_log(gh, entry(32, "PR #9 round 3 is decided."))
    assert_hold(gh.run("--decisions", log, session="someone-else"), "claim")


# ---- rounds within the limit are unaffected ----


def test_rounds_within_the_limit_merge_with_no_d_entry_and_print_only_merge(make):
    gh = make(comments=rounds(2))
    log = write_log(gh, entry(32, "PR #9 round 2 is decided, though nobody needs it."))
    assert gh.run("--decisions", log) == (0, ["MERGE"])


def test_rounds_within_the_limit_merge_without_a_decision_log(make):
    gh = make(comments=rounds(2))
    assert gh.run() == (0, ["MERGE"])
