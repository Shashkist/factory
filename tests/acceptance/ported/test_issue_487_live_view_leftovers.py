# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_487_live_view_leftovers.py at 29e3bf3 (factory#42).
# The two reducer/script cases are not ported.
"""Exam for issue #487 (review of #484): stale waits, silent agents and per-step lane issues.

Same harness as the #68 exams (reducer output fed to the page in node, see dom_harness_68.js).

  1. A stale `wait` is not "now": a manager `check/ci wait` 50 min ago followed by `ship/close #86 done`
     48 min ago leaves no `now: ci` on the lane line, no "running" in the check detail and no `now: ci` on
     the card, and #86 is shipped. `tests` start, `ci` wait, `tests` start again gives `now: tests`.
  2. A silent agent (latest step `running`, last heard from 15 min or more before `generated_at`) does not
     make its lane "working": `[data-lane]` has data-running="0" and its header does not say "working".
  4. Lane steps belong to the issue they were logged for: an agent whose first event was on #3 and who
     later logs ship steps with `--issue 86` has them in lane #86 and not in lane #3. In the reducer each
     sub-step keeps its own `issue`.
"""
# ruff: noqa: E501
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exam68_lanes", HERE / "test_issue_68_live_view_lanes.py")
assert _spec and _spec.loader
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

HOURGLASS, ago, render, start_pass, step, text, walk = m.HOURGLASS, m.ago, m.render, m.start_pass, m.step, m.text, m.walk
base = m.base


def other():
    return step("exam-4", 4, "exam", "read issue", "start", ago(1), role="exam-writer", title="Other")


def stale_wait():
    return [
        start_pass(120),
        step("manager", 86, "check", "ci", "wait", ago(50), title="Task 86"),
        step("manager", 86, "ship", "close #86", "done", ago(48), title="Task 86"),
        other(),
    ]


def lane_head_text(root, issue: int) -> str:
    got = m.lanes(root, issue)
    assert got, f"no lane for #{issue}"
    return text(got[0])


# ---- 1. stale wait -----------------------------------------------------------------------------------

def test_stale_wait_lane_line_does_not_say_now_ci(tmp_path):
    # another agent keeps #86's lane open, so there is a lane line to check (the shipped lane has none)
    live = render([*stale_wait(), step("implementer-86", 86, "build", "tests", "start", ago(1), role="implementer", title="Task 86")])
    root = m.run_page(tmp_path, live)
    assert m.lanes(root, 86), "lane #86 should be open while the implementer works on it"
    t = m.lane_now_text(root, 86)
    assert t.startswith("now: ") and "tests" in t, t
    assert "now: ci" not in t and "ci" not in t.replace("close", ""), t


def test_stale_wait_check_detail_shows_no_running(tmp_path):
    # another agent keeps #86's lane open so that the check station can be opened
    live = render([*stale_wait(), step("implementer-86", 86, "build", "tests", "start", ago(1), role="implementer", title="Task 86")])
    root = m.run_page(tmp_path, live, clicks=[{"lane": 86, "st": "check"}])
    m.assert_detail_not_running(root, 86, "check", "ci")


def test_stale_wait_card_does_not_say_now_ci(tmp_path):
    root = m.run_page(tmp_path, render(stale_wait()))
    assert "now: ci" not in m.card_now_text(root, "manager")
    assert "ci" not in m.card_now_text(root, "manager").replace("close", "")


def test_stale_wait_task_86_ships(tmp_path):
    root = m.run_page(tmp_path, render(stale_wait()))
    done = " ".join(text(n) for n in m.by_class(root, "lane-done"))
    assert "#86" in done, f"#86 not listed as shipped: {done!r}"
    assert not m.lanes(root, 86)


def _tests_ci_tests():
    return [
        start_pass(),
        step("manager", 86, "build", "tests", "start", ago(10), title="Task 86"),
        step("manager", 86, "check", "ci", "wait", ago(5), title="Task 86"),
        step("manager", 86, "build", "tests", "start", ago(1), title="Task 86"),
    ]


def test_tests_ci_wait_tests_again_lane_says_now_tests_not_ci(tmp_path):
    t = m.lane_now_text(m.run_page(tmp_path, render(_tests_ci_tests())), 86)
    assert t.startswith("now: ") and "tests" in t and "ci" not in t, t


def test_tests_ci_wait_tests_again_card_says_now_tests_not_ci(tmp_path):
    t = m.card_now_text(m.run_page(tmp_path, render(_tests_ci_tests())), "manager")
    assert "tests" in t and "ci" not in t, t


# ---- 2. silent agent ---------------------------------------------------------------------------------

def _silent(minutes: float):
    return [
        start_pass(120),
        step("implementer-7", 7, "build", "commit", "start", ago(minutes), role="implementer", title="Task 7"),
    ]


def test_silent_agent_does_not_make_the_lane_working(tmp_path):
    root = m.run_page(tmp_path, render(_silent(30)))
    lane = m.lanes(root, 7)[0]
    assert lane["a"].get("data-running") == "0", lane["a"]
    assert "working" not in lane_head_text(root, 7)


def test_agent_silent_for_exactly_fifteen_minutes_does_not_make_the_lane_working(tmp_path):
    root = m.run_page(tmp_path, render(_silent(15)))
    assert m.lanes(root, 7)[0]["a"].get("data-running") == "0"


def test_recently_heard_agent_makes_the_lane_working(tmp_path):
    root = m.run_page(tmp_path, render(_silent(2)))
    lane = m.lanes(root, 7)[0]
    assert lane["a"].get("data-running") == "1"
    assert "working" in lane_head_text(root, 7)


# ---- 4. lane steps by their own issue -----------------------------------------------------------------

def _two_issues():
    return [
        start_pass(120),
        step("manager", 3, "plan", "pick", "done", ago(30), title="Task 3"),
        step("manager", 86, "ship", "deploy", "start", ago(1), title="Task 86"),
    ]


def test_ship_steps_of_a_manager_that_started_on_another_issue_show_in_their_own_lane(tmp_path):
    live = render([*_two_issues(), other()])
    root = m.run_page(tmp_path, live)
    t86 = m.lane_now_text(root, 86)
    assert t86.startswith("now: ") and "deploy" in t86, t86
    if m.lanes(root, 3):
        assert "deploy" not in m.lane_now_text(root, 3)
        assert HOURGLASS not in text(m.lanes(root, 3)[0])


def test_left_lane_of_two_issues_is_not_running(tmp_path):
    root = m.run_page(tmp_path, render([*_two_issues(), other()]))
    assert m.lanes(root, 3), "lane #3 should still be listed"
    assert m.lanes(root, 3)[0]["a"].get("data-running") == "0", m.lanes(root, 3)[0]["a"]
    assert "working" not in lane_head_text(root, 3)
    assert m.lanes(root, 86)[0]["a"].get("data-running") == "1"


# ---- 2/4. the same step names on several issues; a lane the manager has left ----------------------------

def _repeated_names():
    return [
        start_pass(120),
        step("manager", 3, "check", "ci wait", "wait", ago(30), title="Task 3"),
        step("manager", 3, "ship", "merge", "start", ago(29), title="Task 3"),
        step("manager", 85, "check", "ci wait", "wait", ago(15), title="Task 85"),
        step("manager", 85, "ship", "merge", "done", ago(14), title="Task 85"),
        step("manager", 85, "ship", "close #85", "done", ago(13), title="Task 85"),
        step("implementer-85", 85, "build", "tests", "start", ago(1), role="implementer", title="Task 85"),
        step("manager", 86, "check", "ci wait", "wait", ago(2), title="Task 86"),
    ]


def _ship_items(root, issue: int) -> dict[str, str]:
    det = [n for n in walk(m.lanes(root, issue)[0]) if n["a"].get("data-lane-detail") == "ship"]
    assert det, f"no ship detail in lane #{issue}"
    return {text(li): li["a"].get("data-status") for li in walk(det[0]) if li["t"] == "li"}


def test_same_step_names_on_several_issues_stay_in_their_own_lane(tmp_path):
    clicks = [{"lane": 3, "st": "ship"}, {"lane": 85, "st": "ship"}]
    root = m.run_page(tmp_path, render(_repeated_names()), clicks=clicks)
    for n in (3, 85, 86):
        assert m.lanes(root, n), f"lane #{n} missing"
    in3, in85 = _ship_items(root, 3), _ship_items(root, 85)
    merge3 = [st for t, st in in3.items() if "merge" in t]
    merge85 = [st for t, st in in85.items() if "merge" in t]
    assert merge3 == ["start"], f"lane #3 should keep its own merge (started): {in3}"
    assert merge85 == ["done"], f"lane #85 should have its own merge (done), not #3's: {in85}"
    assert any("close #85" in t for t in in85), in85
    assert not any("close" in t for t in in3), in3
    assert "merge" in m.lane_now_text(root, 3), m.lane_now_text(root, 3)


def test_lane_keeps_its_own_ci_wait_when_other_issues_log_the_same_step(tmp_path):
    root = m.run_page(tmp_path, render(_repeated_names()), clicks=[{"lane": 3, "st": "check"}])
    det = [n for n in walk(m.lanes(root, 3)[0]) if n["a"].get("data-lane-detail") == "check"]
    assert det, "no check detail in lane #3"
    lis = [li for li in walk(det[0]) if li["t"] == "li" and "ci wait" in text(li)]
    assert len(lis) == 1 and lis[0]["a"].get("data-status") == "wait", [text(x) for x in lis]


def test_lane_elapsed_time_uses_its_own_issues_start(tmp_path):
    root = m.run_page(tmp_path, render(_repeated_names()))
    t = m.lane_now_text(root, 86)
    assert t.startswith("now: ") and "ci wait" in t, t
    assert "2 min" in t or "120 s" in t, f"lane #86 should show about 2 min since its own start: {t!r}"
    assert "30 min" not in t and "15 min" not in t, t


def _left_lanes():
    return [
        start_pass(120),
        step("manager", 3, "plan", "orient", "done", ago(56), title="Task 3"),
        step("manager", 85, "plan", "pick #85", "done", ago(55), title="Task 85"),
        step("manager", 85, "plan", "decide D140", "done", ago(55), title="Task 85"),
        step("manager", 86, "plan", "pick #86", "done", ago(1), title="Task 86"),
        step("manager", 86, "build", "dispatch implementer", "start", ago(1), title="Task 86"),
    ]


def test_only_the_lane_the_manager_is_on_is_working(tmp_path):
    root = m.run_page(tmp_path, render(_left_lanes()))
    running = {n: m.lanes(root, n)[0]["a"].get("data-running") for n in (3, 85, 86)}
    assert running == {3: "0", 85: "0", 86: "1"}, running
    assert "working" not in lane_head_text(root, 3) and "working" not in lane_head_text(root, 85)
    assert "working" in lane_head_text(root, 86)
