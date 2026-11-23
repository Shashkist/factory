# Ported from Learning Factory scripts/test_issue_lock.py (spec G8). Changes versus LF:
#   - import: `import issue_lock` became `from factory_tools import claims as issue_lock`
#     (the script moved into the package as factory_tools.claims).
#   - lint: a file-level ruff noqa comment for E501 and UP017 (LF code is not held to this
#     repo's ruff rules: long lines, timezone.utc). A comment only; no code line altered.
#   Nothing else changed: every case and assertion is as in LF.
# ruff: noqa: E501, UP017
"""Tests for the advisory issue lock.

NO NETWORK, EVER. `gh` is injected as a fake that records what it was asked to
do, the same shape `test_prune_rate_counters.py` uses -- so these run on a
laptop with no credentials and cannot touch the live tracker. A test that
claimed a real issue would be a test that fights the thing it is testing.

WHAT IS ACTUALLY UNDER TEST is the refusal logic, because that is the whole
product: taking a free issue is easy, and the decisions worth pinning are
"someone live holds this" and "this one is abandoned, here is the branch".
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from factory_tools import claims as issue_lock


def iso(minutes_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ).replace(microsecond=0).isoformat()


def claim_comment(session="e-sign-e4", branch="feat/theirs", heartbeat_min=1, step="working", blocked=None):
    body = issue_lock.render(
        {
            "session": session,
            "branch": branch,
            "worktree": "C:/wt",
            "claimed": iso(heartbeat_min + 5),
            "heartbeat": iso(heartbeat_min),
            "step": step,
            **({} if blocked is None else {"blocked": blocked}),
        }
    )
    return {"body": body, "url": "https://github.com/o/r/issues/1#issuecomment-4242"}


class FakeGh:
    """Answers the three shapes this script asks for, and records the rest."""

    def __init__(self, comments=None, issues=None, then=None, recent=None):
        self.comments = comments if comments is not None else []
        #: What the UNFILTERED `issue list` returns -- the recently-updated
        #: sweep, which carries `updatedAt`.
        self.recent = recent if recent is not None else []
        #: What `issue view` returns from the SECOND call onwards. A race is
        #: exactly this: nothing when you look, a rival when you look again.
        self.then = then
        self.issues = issues if issues is not None else []
        self.calls: list[list[str]] = []
        self._views = 0

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["issue", "view"]:
            self._views += 1
            if self.then is not None and self._views > 1:
                return json.dumps({"comments": self.then})
            return json.dumps({"comments": self.comments})
        if args[:2] == ["issue", "list"]:
            # The two list queries are different questions and the fake has to
            # tell them apart, or the union path below is never exercised.
            labelled = "--label" in args
            return json.dumps(self.issues if labelled else self.recent)
        return ""

    def did(self, *fragments):
        return [c for c in self.calls if all(any(f in a for a in c) for f in fragments)]


def args(**over):
    class A:
        number = 1
        session = "e-sign-65"
        branch = "feat/mine"
        worktree = "C:/mine"
        step = None
        steal = False
        reason = None
        stale_after = 90
        blocked = None
        force = False
        json = False
        older_than = 90

    a = A()
    for k, v in over.items():
        setattr(a, k, v)
    return a


class TestParsing:
    def test_a_comment_that_is_not_a_claim_is_not_one(self):
        assert issue_lock.parse_claim("just a person talking") is None

    def test_a_hand_mangled_claim_reads_as_no_claim_rather_than_crashing(self):
        # Errs towards letting work proceed: an unreadable lock must not be a
        # permanent one, and it must not take the tool down for every issue.
        mangled = f"{issue_lock.MARKER}\n{{not json,,,}}\n{issue_lock.END}"
        assert issue_lock.parse_claim(mangled) is None

    def test_a_claim_survives_a_round_trip_through_its_own_rendering(self):
        original = {
            "session": "e-sign-65",
            "branch": "feat/x",
            "worktree": "",
            "claimed": iso(10),
            "heartbeat": iso(1),
            "step": "writing the failing test",
        }
        assert issue_lock.parse_claim(issue_lock.render(original)) == original

    def test_the_rendered_comment_is_readable_by_a_person_too(self):
        body = issue_lock.render(
            {"session": "e-sign-65", "branch": "feat/x", "heartbeat": iso(0), "step": "s"}
        )
        # A lock only a script can see just moves the collision elsewhere.
        assert "Claimed by" in body and "e-sign-65" in body and "feat/x" in body


class TestClaiming:
    def test_takes_an_unclaimed_issue_and_marks_it_in_progress(self):
        gh = FakeGh()
        assert issue_lock.cmd_claim(args(), gh) == 0
        assert gh.did("issue", "comment")
        assert gh.did("--add-label", issue_lock.CLAIM_LABEL)

    def test_refuses_an_issue_a_LIVE_session_holds(self):
        gh = FakeGh(comments=[claim_comment(heartbeat_min=3)])
        assert issue_lock.cmd_claim(args(), gh) == 1
        # And changes nothing -- a refused claim that still relabelled would be
        # worse than no lock at all.
        assert not gh.did("--add-label")

    def test_takes_over_an_issue_whose_session_has_gone_quiet(self):
        gh = FakeGh(comments=[claim_comment(heartbeat_min=500)])
        assert issue_lock.cmd_claim(args(), gh) == 0

    def test_stealing_a_live_claim_demands_a_reason(self):
        gh = FakeGh(comments=[claim_comment(heartbeat_min=2)])
        assert issue_lock.cmd_claim(args(steal=True), gh) == 1

    def test_a_steal_records_who_it_was_taken_from(self):
        gh = FakeGh(comments=[claim_comment(session="e-sign-e4", heartbeat_min=2)])
        assert issue_lock.cmd_claim(args(steal=True, reason="session gone"), gh) == 0
        patched = gh.did("PATCH")[0]
        written = issue_lock.parse_claim(patched[-1].split("body=", 1)[1])
        assert written["stolen_from"] == "e-sign-e4"
        assert written["steal_reason"] == "session gone"

    def test_reclaiming_your_own_issue_keeps_the_original_claimed_time(self):
        first = claim_comment(session="e-sign-65", heartbeat_min=30)
        gh = FakeGh(comments=[first])
        issue_lock.cmd_claim(args(), gh)
        written = issue_lock.parse_claim(gh.did("PATCH")[0][-1].split("body=", 1)[1])
        assert written["claimed"] == issue_lock.parse_claim(first["body"])["claimed"]


class TestHeartbeat:
    def test_refuses_to_beat_somebody_else_s_claim(self):
        gh = FakeGh(comments=[claim_comment(session="e-sign-e4")])
        assert issue_lock.cmd_heartbeat(args(), gh) == 1

    def test_records_the_current_step(self):
        gh = FakeGh(comments=[claim_comment(session="e-sign-65")])
        assert issue_lock.cmd_heartbeat(args(step="running the e2e"), gh) == 0
        written = issue_lock.parse_claim(gh.did("PATCH")[0][-1].split("body=", 1)[1])
        assert written["step"] == "running the e2e"

    def test_beating_an_unclaimed_issue_is_an_error_not_a_silent_claim(self):
        # Otherwise a typo'd issue number silently locks something else.
        assert issue_lock.cmd_heartbeat(args(), FakeGh()) == 1


class TestRecovery:
    """The reason the tool exists: a session died, the work did not."""

    def test_stale_names_the_branch_so_the_work_can_be_continued(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(branch="feat/half-done", heartbeat_min=300)],
            issues=[{"number": 7, "title": "Something half-finished"}],
        )
        assert issue_lock.cmd_stale(args(older_than=90), gh) == 0
        out = capsys.readouterr().out
        assert "feat/half-done" in out
        # Continuing the branch is the point; freeing the issue is incidental.
        assert "continue" in out and "take over" in out

    def test_a_live_claim_is_not_reported_as_stale(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=5)],
            issues=[{"number": 7, "title": "In hand"}],
        )
        issue_lock.cmd_stale(args(older_than=90), gh)
        assert "feat/theirs" not in capsys.readouterr().out

    def test_an_unparseable_heartbeat_counts_as_abandoned(self):
        # "Assume alive" would lock an issue for ever on one bad timestamp.
        assert issue_lock.age_minutes("not-a-date") == float("inf")

    def test_a_released_claim_frees_the_issue(self, capsys):
        released = {
            "body": f"{issue_lock.MARKER}\n"
            + json.dumps({"released": iso(1), "by": "e-sign-e4"})
            + f"\n{issue_lock.END}",
            "url": "https://github.com/o/r/issues/1#issuecomment-1",
        }
        gh = FakeGh(comments=[released], issues=[{"number": 7, "title": "Free"}])
        issue_lock.cmd_status(args(), gh)
        assert "No issues are claimed" in capsys.readouterr().out


class TestStatus:
    def test_reports_who_holds_what(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(session="e-sign-e4", branch="feat/theirs")],
            issues=[{"number": 42, "title": "Theirs"}],
        )
        assert issue_lock.cmd_status(args(), gh) == 0
        out = capsys.readouterr().out
        assert "e-sign-e4" in out and "feat/theirs" in out and "42" in out

    def test_json_mode_is_machine_readable(self, capsys):
        gh = FakeGh(
            comments=[claim_comment()],
            issues=[{"number": 42, "title": "Theirs"}],
        )
        issue_lock.cmd_status(args(json=True), gh)
        parsed = json.loads(capsys.readouterr().out)
        assert parsed[0]["claim"]["session"] == "e-sign-e4"

    def test_public_claimed_helper_returns_the_claim_rows(self):
        gh = FakeGh(comments=[claim_comment()], issues=[{"number": 42, "title": "Theirs"}])
        rows = issue_lock.claimed([issue_lock.HERE_REPO], gh)
        assert [(r["repo"], r["number"]) for r in rows] == [(issue_lock.HERE_REPO, 42)]
        assert issue_lock.claimed([issue_lock.HERE_REPO], FakeGh()) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


class TestTheRaceTheLabelIndexCannotSee:
    """Two sessions claiming in the same second.

    GitHub's label search lags a write by a second or two, so both sessions
    read "unclaimed" and both post. Comments are immediately consistent, which
    is the only reason this is detectable at all. Both sides run the same
    comparison over the same data and reach the same answer without talking.
    """

    #: Fixed ids, not hashes: the assertion below is about WHICH comment gets
    #: retracted, and a fixture whose ids move between runs cannot make it.
    THEIRS_ID = 111
    MINE_ID = 222

    def _both_claimed(self, mine_at, theirs_at):
        """An issue that already carries two live claims."""

        def c(session, branch, claimed, cid):
            return {
                "body": issue_lock.render(
                    {
                        "session": session,
                        "branch": branch,
                        "claimed": claimed,
                        "heartbeat": iso(0),
                        "step": "racing",
                    }
                ),
                "url": f"https://github.com/o/r/issues/1#issuecomment-{cid}",
            }

        # Theirs FIRST, so a naive "release the first live claim" unlocks the
        # winner -- which is the bug this class exists to keep out.
        return [
            c("e-sign-e4", "feat/theirs", theirs_at, self.THEIRS_ID),
            c("e-sign-65", "feat/mine", mine_at, self.MINE_ID),
        ]

    def test_the_later_claimant_stands_down(self, capsys):
        # Nothing when I check; both of us when I read back. That IS the race.
        gh = FakeGh(comments=[], then=self._both_claimed(mine_at=iso(0), theirs_at=iso(1)))
        assert issue_lock.cmd_claim(args(), gh) == 1

        # Stood down means RELEASED, not merely "returned 1" -- a claim left
        # behind would keep the issue locked by a session that walked away.
        patches = [c for c in gh.calls if "PATCH" in c]
        assert patches, "standing down must retract the claim, not just refuse"

        # AND IT MUST BE MY COMMENT. `find_claim` returns the first live claim,
        # which here is the WINNER's -- retracting that would unlock the issue
        # for the session that just won the race. Mutation-checked: pointing
        # the retraction at find_claim's answer fails exactly this assertion.
        retracted = patches[-1]
        assert str(self.MINE_ID) in " ".join(retracted)
        assert str(self.THEIRS_ID) not in " ".join(retracted)

        body = " ".join(retracted).split("body=", 1)[1]
        assert issue_lock.parse_claim(body).get("released")

        assert "e-sign-e4" in capsys.readouterr().err

    def test_the_earlier_claimant_proceeds(self):
        gh = FakeGh(comments=[], then=self._both_claimed(mine_at=iso(2), theirs_at=iso(0)))
        assert issue_lock.cmd_claim(args(), gh) == 0
        assert gh.did("--add-label", issue_lock.CLAIM_LABEL)

    def test_a_dead_rival_does_not_win_the_race(self):
        # Their claim is older, so a naive "earliest wins" would hand them an
        # issue they are no longer working on.
        gh = FakeGh(
            comments=[],
            then=[
                claim_comment(session="e-sign-e4", heartbeat_min=500),
                {
                    "body": issue_lock.render(
                        {
                            "session": "e-sign-65",
                            "branch": "feat/mine",
                            "claimed": iso(1),
                            "heartbeat": iso(0),
                            "step": "racing",
                        }
                    ),
                    "url": "https://github.com/o/r/issues/1#issuecomment-2",
                },
            ]
        )
        assert issue_lock.cmd_claim(args(), gh) == 0


class TestTheLagTheLabelIndexHides:
    """`status` must not under-report a claim that was just made.

    A peer claimed #153, `claim` confirmed it, and `status` answered "No
    issues are claimed" a second later -- because `status` went through the
    label index alone and that index lags a write. A status that under-reports
    invites exactly the double-claim the lock exists to prevent, so it now
    unions the label query with a recently-updated sweep.
    """

    def test_finds_a_claim_the_label_index_has_not_indexed_yet(self, capsys):
        # The label query returns NOTHING, which is what the lag looks like.
        gh = FakeGh(
            comments=[claim_comment(session="e-sign-5d", branch="fix/153")],
            issues=[],
            recent=[{"number": 153, "title": "Header scrolls away", "updatedAt": iso(0)}],
        )
        assert issue_lock.cmd_status(args(), gh) == 0
        out = capsys.readouterr().out
        assert "153" in out and "e-sign-5d" in out and "fix/153" in out

    def test_does_not_trawl_issues_nobody_has_touched(self, capsys):
        # An old issue in the sweep is not worth a comment read; the whole
        # point of the window is to keep the extra cost bounded.
        gh = FakeGh(
            comments=[claim_comment()],
            issues=[],
            recent=[{"number": 9, "title": "Ancient", "updatedAt": iso(60 * 24)}],
        )
        issue_lock.cmd_status(args(), gh)
        assert "No issues are claimed" in capsys.readouterr().out

    def test_the_two_queries_are_unioned_not_replaced(self, capsys):
        # A labelled issue still shows even when the recent sweep misses it.
        gh = FakeGh(
            comments=[claim_comment(session="e-sign-e4", branch="feat/theirs")],
            issues=[{"number": 42, "title": "Labelled"}],
            recent=[],
        )
        issue_lock.cmd_status(args(), gh)
        assert "42" in capsys.readouterr().out


class TestSilenceHasTwoCauses:
    """A claim goes quiet for two reasons that want OPPOSITE responses.

    `stale` measured silence and offered `--steal` under everything it found.
    But *died waiting* is safe to steal and *waiting on a human* is not:
    stealing a parked claim duplicates work that is already finished, which is
    the exact collision this file exists to prevent.

    THE ASYMMETRY IS THE ARGUMENT. Failing to steal a dead claim costs delay.
    Stealing a live one costs two sessions writing the same code. So the
    default is biased away from stealing whenever the holder said it was
    blocked on something outside this machine.

    Found for real: two sessions sat five days awaiting an owner decision on a
    push. Both claims read as stale and stealable, and both held finished work.
    """

    def test_a_blocked_claim_is_still_listed_because_visibility_is_the_point(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300, blocked=True, step="awaiting owner approval")],
            issues=[{"number": 7, "title": "Parked on a human"}],
        )
        assert issue_lock.cmd_stale(args(older_than=90), gh) == 0
        out = capsys.readouterr().out
        # Hiding it would be worse than offering the steal: a reader must still
        # see that the issue is held and by whom.
        assert "#7" in out
        assert "awaiting owner approval" in out

    def test_a_blocked_claim_does_not_offer_the_take_over_command(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300, blocked=True)],
            issues=[{"number": 7, "title": "Parked on a human"}],
        )
        issue_lock.cmd_stale(args(older_than=90), gh)
        out = capsys.readouterr().out
        # The steal line is a suggestion, and printing it under a claim that is
        # merely patient is what makes the wrong thing the easy thing.
        assert "--steal" not in out
        assert "take over" not in out

    def test_it_says_the_silence_is_deliberate_rather_than_leaving_it_ambiguous(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300, blocked=True)],
            issues=[{"number": 7, "title": "Parked on a human"}],
        )
        issue_lock.cmd_stale(args(older_than=90), gh)
        out = capsys.readouterr().out
        assert "held" in out.lower()
        # And the branch still, because continuing the work is always the point.
        assert "feat/theirs" in out

    def test_an_unblocked_stale_claim_still_offers_the_steal(self, capsys):
        # The recovery path is the reason the tool exists; this must not have
        # been narrowed into uselessness by the change above.
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300, blocked=False)],
            issues=[{"number": 7, "title": "Genuinely gone"}],
        )
        issue_lock.cmd_stale(args(older_than=90), gh)
        out = capsys.readouterr().out
        assert "--steal" in out and "take over" in out

    def test_a_claim_predating_the_flag_is_treated_as_stealable(self, capsys):
        # Every claim written before this change has no `blocked` key at all.
        # Absence must mean "not blocked", or one deploy freezes every existing
        # claim permanently.
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300)],
            issues=[{"number": 7, "title": "Written last week"}],
        )
        issue_lock.cmd_stale(args(older_than=90), gh)
        assert "--steal" in capsys.readouterr().out

    def test_a_heartbeat_can_clear_the_block_when_the_wait_ends(self, capsys):
        # Being unblocked is a state change like any other, and a session that
        # gets its answer must be able to say so without re-claiming.
        gh = FakeGh(comments=[claim_comment(session="e-sign-65", heartbeat_min=1, blocked=True)])
        issue_lock.cmd_heartbeat(args(number=1, session="e-sign-65", blocked=False, step="cleared"), gh)
        written = gh.did("issue", "comment")
        assert written, "the heartbeat wrote nothing"
        assert "blocked: false" in written[-1][-1].lower() or "blocked" not in written[-1][-1].lower()

    def test_an_ordinary_heartbeat_does_not_quietly_clear_the_block(self):
        """The mutation that found this survived every other test in the file.

        A plain heartbeat is the MOST COMMON operation -- a session beats at
        every step it would otherwise narrate -- so a heartbeat that cleared
        the flag would make the whole feature evaporate on the next beat, and
        nothing here would have said so. Hence the tri-state: absent means
        leave it alone, and only an explicit flag moves it.
        """
        gh = FakeGh(comments=[claim_comment(session="e-sign-65", heartbeat_min=1, blocked=True)])
        issue_lock.cmd_heartbeat(args(number=1, session="e-sign-65", step="still waiting"), gh)
        written = gh.did("issue", "comment")[-1][-1]
        assert '"blocked": true' in written, "a routine heartbeat dropped the block"

    def test_status_marks_a_blocked_claim_so_a_reader_sees_it_without_asking(self, capsys):
        gh = FakeGh(
            comments=[claim_comment(heartbeat_min=300, blocked=True)],
            issues=[{"number": 7, "title": "Parked"}],
        )
        issue_lock.cmd_status(args(), gh)
        out = capsys.readouterr().out
        assert "7" in out
        assert "held" in out.lower() or "blocked" in out.lower()
