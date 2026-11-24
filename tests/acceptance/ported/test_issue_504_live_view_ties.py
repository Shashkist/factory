# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_504_live_view_ties.py at 29e3bf3 (factory#42).
# The four reducer/script cases are not ported.
"""Exam for issue #504 (review of #499): same-second ties, unscoped steps, and the issue shown on the card.

Same harness as the #68 and #487 exams (reducer output fed to the page in node).

  1. Same-second tie across issues: an agent whose latest sub-steps, tied at the same second, sit in two
     lanes counts as working in both lanes.
  2. A step logged without --issue follows the issue of the agent's previous sub-step, in the stored
     state (factory_progress.py) and in the page's lanes.
  5. The agent card header shows the latest issue, and every step on the card shows its own issue.
"""
# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exam68_lanes_504", HERE / "test_issue_68_live_view_lanes.py")
assert _spec and _spec.loader
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

ago, render, start_pass, step, text, walk, base = m.ago, m.render, m.start_pass, m.step, m.text, m.walk, m.base


def running(root, issue: int) -> str | None:
    got = m.lanes(root, issue)
    assert got, f"no lane for #{issue}"
    return got[0]["a"].get("data-running")


def head_text(root, issue: int) -> str:
    return text(m.lanes(root, issue)[0])


def card(root, agent_id: str) -> dict:
    cards = [n for n in walk(root) if n["a"].get("data-agent-id") == agent_id]
    assert cards, f"no agent card {agent_id}"
    return cards[0]


# ---- 1. same-second tie across issues -------------------------------------------------------------------

def _tie(first_issue: int, second_issue: int):
    names = {3: ("check", "ci wait", "wait"), 86: ("ship", "merge", "start")}
    evs = [start_pass(120), step("manager", 3, "plan", "pick #3", "done", ago(30), title="Task 3")]
    for n in (first_issue, second_issue):
        st, sub, status = names[n]
        evs.append(step("manager", n, st, sub, status, ago(1), title=f"Task {n}"))
    return evs


def test_same_second_tie_across_issues_agent_works_in_both_lanes(tmp_path):
    root = m.run_page(tmp_path, render(_tie(3, 86)))
    assert (running(root, 3), running(root, 86)) == ("1", "1"), (running(root, 3), running(root, 86))
    assert "working" in head_text(root, 3) and "working" in head_text(root, 86)


def test_same_second_tie_does_not_depend_on_the_order_of_the_steps(tmp_path):
    root = m.run_page(tmp_path, render(_tie(86, 3)))
    assert (running(root, 3), running(root, 86)) == ("1", "1"), (running(root, 3), running(root, 86))


def test_same_second_tie_lane_that_says_now_also_says_working(tmp_path):
    root = m.run_page(tmp_path, render(_tie(3, 86)))
    assert "ci wait" in m.lane_now_text(root, 3), m.lane_now_text(root, 3)
    assert running(root, 3) == "1" and "working" in head_text(root, 3)


def test_a_strictly_later_step_still_leaves_the_earlier_lane(tmp_path):
    evs = [start_pass(120),
           step("manager", 3, "check", "ci wait", "wait", ago(2), title="Task 3"),
           step("manager", 86, "ship", "merge", "start", ago(1), title="Task 86")]
    root = m.run_page(tmp_path, render(evs))
    assert (running(root, 3), running(root, 86)) == ("0", "1")


# ---- 2. a step without --issue follows the previous sub-step's issue --------------------------------------

def _journey():
    return [
        start_pass(120),
        step("manager", 3, "plan", "pick #3", "done", ago(40), title="Task 3"),
        step("manager", 86, "plan", "pick #86", "done", ago(20), title="Task 86"),
    ]


def _unscoped_step(issue):
    return {"kind": "step", "at": ago(1), "issue": issue, "title": "", "agent": "manager", "role": "manager",
            "station": "check", "substep": "verify", "status": "start", "detail": ""}


def _unscoped_live(variant):
    live = render([*_journey(), _unscoped_step(86)])
    sub = base.agent(live, "manager")["substeps"][-1]
    assert sub["substep"] == "verify"
    if variant == "null":
        sub["issue"] = None
    else:
        del sub["issue"]
    return live


def test_unscoped_step_in_the_page_belongs_to_the_latest_issue_lane(tmp_path):
    for variant in ("null", "missing"):
        root = m.run_page(tmp_path, _unscoped_live(variant))
        t86 = m.lane_now_text(root, 86)
        assert t86.startswith("now: ") and "verify" in t86, (variant, t86)
        if m.lanes(root, 3):
            assert "verify" not in m.lane_now_text(root, 3), variant


def test_unscoped_step_makes_the_latest_issue_working_and_the_first_one_not(tmp_path):
    for variant in ("null", "missing"):
        root = m.run_page(tmp_path, _unscoped_live(variant))
        assert running(root, 86) == "1" and "working" in head_text(root, 86), variant
        if m.lanes(root, 3):
            assert running(root, 3) == "0" and "working" not in head_text(root, 3), variant


# ---- 5. the card shows the latest issue and each step's issue ---------------------------------------------

def _two_issue_card():
    return [
        start_pass(120),
        step("manager", 3, "check", "ci wait", "wait", ago(30), title="Task 3"),
        step("manager", 3, "ship", "merge", "done", ago(29), title="Task 3"),
        step("manager", 86, "check", "ci wait", "wait", ago(3), title="Task 86"),
        step("manager", 86, "ship", "merge", "start", ago(1), title="Task 86"),
    ]


def test_card_header_shows_the_latest_issue_not_the_first(tmp_path):
    root = m.run_page(tmp_path, render(_two_issue_card()))
    head = m.by_class(card(root, "manager"), "live-head")
    assert head, "no .live-head on the manager card"
    t = text(head[0])
    assert re.search(r"#86(?!\d)", t), t
    assert not re.search(r"#3(?!\d)", t), t


def test_each_step_on_the_card_shows_its_own_issue(tmp_path):
    root = m.run_page(tmp_path, render(_two_issue_card()))
    lis = [n for n in walk(card(root, "manager")) if n["t"] == "li" and n["a"].get("data-substep")]
    assert len(lis) == 4, [text(x) for x in lis]
    seen = {}
    for li in lis:
        name = li["a"]["data-substep"]
        nums = {int(x) for x in re.findall(r"#(\d+)", text(li))}
        assert len(nums) == 1, f"step {name!r} on the card should show exactly one issue: {text(li)!r}"
        seen.setdefault(name, set()).update(nums)
    assert seen == {"ci wait": {3, 86}, "merge": {3, 86}}, seen
    by_status = {(li["a"]["data-substep"], li["a"].get("data-status")): text(li) for li in lis}
    assert "#3" in by_status[("merge", "done")] and "#86" in by_status[("merge", "start")], by_status


# ---- 2b. an unscoped step also moves the lane's station (review round 1 of the #504 PR) -------------------

def _unscoped(station, substep, status, at):
    return {"kind": "step", "at": at, "issue": None, "title": "", "agent": "manager", "role": "manager",
            "station": station, "substep": substep, "status": status, "detail": ""}


def _marks(root, issue: int) -> dict:
    got = m.lanes(root, issue)
    assert got, f"no lane for #{issue}"
    return {n["a"].get("data-st"): n["a"].get("data-mark") for n in m.by_class(got[0], "lane-st")}


def test_unscoped_step_lane_station_bar_shows_check_as_the_active_station(tmp_path):
    root = m.run_page(tmp_path, render([*_journey(), _unscoped_step(None)]))
    marks = _marks(root, 86)
    assert marks.get("check") == "active", marks
    assert marks.get("plan") == "done", marks


def test_unscoped_ship_step_marks_the_lane_shipped_like_a_scoped_one(tmp_path):
    def shipped(issue):
        ship = {**_unscoped("ship", "merge", "done", ago(1)), "issue": issue}
        root = m.run_page(tmp_path, render([*_journey(), step("manager", 86, "check", "verify", "done", ago(5), title="Task 86"), ship,
                                            step("exam-4", 4, "exam", "read issue", "start", ago(1), role="exam-writer", title="Other")]))
        done = " ".join(text(n) for n in m.by_class(root, "lane-done"))
        return "#86" in done and not m.lanes(root, 86)

    assert shipped(86), "control: the scoped ship step should mark #86 shipped"
    assert shipped(None), "an unscoped ship step should mark #86 shipped"
