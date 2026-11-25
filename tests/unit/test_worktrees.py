"""Unit tests for the pure decisions of `factory_tools.worktrees`."""

from __future__ import annotations

from factory_tools import worktrees as wt

NOW = 1_000_000.0
START = NOW - 3600


def never() -> tuple[bool, str]:
    raise AssertionError("must not be asked")


def test_live_claim_wins_over_everything() -> None:
    go, why = wt.decide_feature([{"state": "MERGED"}], True, lambda m: never(), never)
    assert not go and "claim" in why


def test_no_pr_and_open_pr_are_kept() -> None:
    assert not wt.decide_feature([], False, lambda m: never(), never)[0]
    assert not wt.decide_feature([{"state": "OPEN"}], False, lambda m: never(), never)[0]


def test_merged_follows_the_merged_safety_check() -> None:
    prs = [{"state": "MERGED", "headRefOid": "a"}]
    assert wt.decide_feature(prs, False, lambda m: (True, "ok"), never) == (True, "PR merged")
    go, why = wt.decide_feature(prs, False, lambda m: (False, "after"), never)
    assert not go and why == "after"


def test_closed_follows_the_remote_check() -> None:
    prs = [{"state": "CLOSED"}]
    assert wt.decide_feature(prs, False, lambda m: never(), lambda: (True, "ok"))[0]
    assert not wt.decide_feature(prs, False, lambda m: never(), lambda: (False, "no"))[0]


def test_subagent_needs_pass_start_and_idle_time() -> None:
    assert not wt.decide_subagent(NOW - 9999, None, True, NOW)[0]
    assert not wt.decide_subagent(START + 1, START, True, NOW)[0]
    assert not wt.decide_subagent(NOW - 600, START + 3000, True, NOW)[0]
    assert wt.decide_subagent(NOW - 9999, START, True, NOW)[0]
    assert not wt.decide_subagent(NOW - 9999, START, False, NOW)[0]


def test_parse_iso_reads_z_offset_and_naive_as_utc() -> None:
    z = wt.parse_iso("2026-11-20T10:00:00Z")
    assert z == wt.parse_iso("2026-11-20T10:00:00+00:00") == wt.parse_iso("2026-11-20T10:00:00")
    assert wt.parse_iso("2026-11-20T12:00:00+02:00") == z


def test_parse_worktrees_strips_the_branch_prefix_and_keeps_locked() -> None:
    text = "worktree /a\nHEAD x\nbranch refs/heads/main\n\nworktree /b\nlocked on usb\n"
    trees = wt.parse_worktrees(text)
    assert [t["branch"] for t in trees] == ["main", ""]
    assert trees[1]["locked"] == "on usb"


def test_list_names_caps_long_lists() -> None:
    out = wt.list_names([f"f{i}" for i in range(25)], [".venv/"])
    assert "and 5 more" in out and "ignored: .venv/" in out
