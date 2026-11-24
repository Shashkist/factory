# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_68_live_view_lanes.py at 29e3bf3 (factory#42).
# The two reducer-only cases at the end are not ported. dom_harness_6.js is the #68 harness plus snapshot and page output.
"""Exam for issue #68, round 2: the swimlane view and pass-end (review of the first PR).

The default view is the swimlane view (one `.lane` per task); the agent cards sit in a collapsed fold. The
same rule that holds for the card sub-steps (see test_issue_68_live_view_state.py) must hold everywhere a
sub-step is shown as current:

  A `start` sub-step counts as RUNNING only if (1) it is the agent's latest sub-step (no sub-step of that
  agent has a strictly later timestamp; same-second ties keep it running), (2) the agent was silent for
  less than 15 minutes (agent `last` vs live.json `generated_at`) and (3) the agent state is not ended
  (`ended` or `done`, i.e. after pass-end; `failed` and `stopped` keep their latest step running, D136 and
  the #51 exam).

Observable places, all read from the page fed with the real reducer's output (#51 harness plus a click,
see dom_harness_68.js):
  * `.lane-now` inside `[data-lane="<issue>"]`: the text starts with "now: " only for a running sub-step.
    Otherwise it says "last: ..." or the element is absent.
  * `[data-lane-detail="<station>"]` (opened by clicking `button[data-st="<station>"]` of the lane): the `li`
    of a running sub-step shows the hourglass and "running"; any other open (`data-status="start"`)
    sub-step shows neither the hourglass nor the word "running".
  * `.live-now` on the agent card (`[data-agent-id]`): names the sub-step only if it is running.
  * A lane held back only by a stale open sub-step is not held back: with the PR unknown, a lane whose
    station is ship with a later `ship ... done` step is listed in `.lane-done` ("Shipped this pass") and
    has no `[data-lane]` element.
  * No hourglass anywhere (card, lane detail, `.lane-now`) once the pass has ended.
Reducer: an issue given as the string "0" creates no issue row; a current-pass worker is kept when one of
its hook lines stamped before `pass_started` lands after the pass-start line, and that old line does not
count (workers are built only from events with `at >= pass_started`).
"""
# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HARNESS68 = HERE.parent / "dashboard" / "dom_harness_6.js"

_spec = importlib.util.spec_from_file_location("exam68_base", HERE / "test_issue_68_live_view_state.py")
assert _spec and _spec.loader
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

HOURGLASS, NOW, ago, render, start_pass, step, text, walk = (
    base.HOURGLASS, base.NOW, base.ago, base.render, base.start_pass, base.step, base.text, base.walk)


def run_page(tmp_path: Path, live: dict, clicks: list[dict] | None = None) -> dict:
    node = shutil.which("node")
    assert node, "node is required for the live-view exam"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": base.iso(NOW), "steps": [{"now": base.iso(NOW), "live": live, "clicks": clicks or []}]}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS68), str(base.INDEX), str(base.APP), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])["steps"][0]
    assert not out["errors"], out["errors"]
    assert out["live"] is not None, "no element with id=live in index.html"
    return out["live"]


def by_class(root, cls: str) -> list[dict]:
    return [n for n in walk(root) if cls in (n["a"].get("class") or "").split()]


def lanes(root, issue: int) -> list[dict]:
    return [n for n in walk(root) if n["a"].get("data-lane") == str(issue)]


def lane_now_text(root, issue: int) -> str:
    got = lanes(root, issue)
    assert got, f"no lane for #{issue}"
    nodes = by_class(got[0], "lane-now")
    return text(nodes[0]) if nodes else ""


def open_items(root, issue: int, station: str, name: str) -> list[str]:
    got = lanes(root, issue)
    assert got, f"no lane for #{issue}"
    det = [n for n in walk(got[0]) if n["a"].get("data-lane-detail") == station]
    assert det, f"no [data-lane-detail={station!r}] after clicking the station button"
    return [text(li) for li in walk(det[0])
            if li["t"] == "li" and li["a"].get("data-status") in ("start", "wait") and name in text(li)]


def assert_detail_not_running(root, issue, station, name):
    items = open_items(root, issue, station, name)
    assert items, f"no open sub-step {name!r} in the {station} detail"
    for t in items:
        assert HOURGLASS not in t and "running" not in t, f"station detail still shows it as running: {t!r}"


def card_now_text(root, agent_id: str) -> str:
    cards = [n for n in walk(root) if n["a"].get("data-agent-id") == agent_id]
    assert cards, f"no agent card {agent_id}"
    nodes = by_class(cards[0], "live-now")
    return text(nodes[0]) if nodes else ""


def c7d42():
    """The reviewer's repro: manager ship/deploy start 50 min ago, then ship/close #86 done 48 min ago."""
    return [
        start_pass(120),
        step("manager", 86, "ship", "deploy", "start", ago(50), title="Task 86"),
        step("manager", 86, "ship", "close #86", "done", ago(48), title="Task 86"),
    ]


# ---- lane "now:" line ------------------------------------------------------------------------------

def test_lane_now_line_does_not_show_the_abandoned_deploy_of_the_lf_c7d42_sequence(tmp_path):
    # a second task keeps the page busy; #86 may be shown as an open lane or as shipped
    live = render([*c7d42(), step("exam-4", 4, "exam", "read issue", "start", ago(1), role="exam-writer", title="Other")])
    root = run_page(tmp_path, live)
    if lanes(root, 86):
        t = lane_now_text(root, 86)
        assert not t.startswith("now:") and "now: deploy" not in t, t


def test_lane_now_line_names_the_latest_open_substep_not_an_older_abandoned_one(tmp_path):
    live = render([
        start_pass(120),
        step("manager", 86, "build", "merge", "start", ago(10), title="Task 86"),
        step("manager", 86, "check", "ci", "start", ago(8), title="Task 86"),
        step("manager", 86, "check", "ci round 2", "wait", ago(1), title="Task 86"),
    ])
    t = lane_now_text(run_page(tmp_path, live), 86)
    assert t.startswith("now: ") and "ci round 2" in t, t
    assert "merge" not in t


def test_lane_now_line_of_a_silent_agent_is_not_now(tmp_path):
    live = render([
        start_pass(120),
        step("implementer-7", 7, "build", "tests", "done", ago(40), role="implementer", title="Task 7"),
        step("implementer-7", 7, "build", "commit", "start", ago(30), role="implementer", title="Task 7"),
    ])
    t = lane_now_text(run_page(tmp_path, live), 7)
    assert not t.startswith("now:"), t


def test_lane_now_line_recent_latest_open_substep_is_now(tmp_path):
    live = render([start_pass(), step("manager", 86, "ship", "deploy", "start", ago(2), title="Task 86")])
    t = lane_now_text(run_page(tmp_path, live), 86)
    assert t.startswith("now: ") and "deploy" in t, t


# ---- lane station detail ---------------------------------------------------------------------------

def test_lane_station_detail_older_open_substep_has_no_hourglass_and_no_running(tmp_path):
    live = render([
        start_pass(120),
        step("manager", 86, "ship", "deploy", "start", ago(10), title="Task 86"),
        step("manager", 86, "ship", "close #86", "start", ago(1), title="Task 86"),
    ])
    root = run_page(tmp_path, live, clicks=[{"lane": 86, "st": "ship"}])
    assert_detail_not_running(root, 86, "ship", "deploy")
    cur = open_items(root, 86, "ship", "close #86")
    assert cur and HOURGLASS in cur[0] and "running" in cur[0], cur


def test_lane_station_detail_substep_of_a_silent_agent_is_not_running(tmp_path):
    live = render([
        start_pass(120),
        step("implementer-7", 7, "build", "commit", "start", ago(30), role="implementer", title="Task 7"),
    ])
    root = run_page(tmp_path, live, clicks=[{"lane": 7, "st": "build"}])
    assert_detail_not_running(root, 7, "build", "commit")


# ---- card "now:" line --------------------------------------------------------------------------------

def test_card_now_line_does_not_show_the_abandoned_deploy_of_the_lf_c7d42_sequence(tmp_path):
    root = run_page(tmp_path, render(c7d42()))
    t = card_now_text(root, "manager")
    assert "deploy" not in t, f"card now: line names the abandoned sub-step: {t!r}"


def test_card_now_line_names_the_latest_recent_open_substep(tmp_path):
    live = render([
        start_pass(),
        step("manager", 3, "plan", "pick", "start", ago(10)),
        step("manager", 3, "build", "merge", "start", ago(2)),
    ])
    t = card_now_text(run_page(tmp_path, live), "manager")
    assert "merge" in t and "pick" not in t, t


def test_card_now_line_does_not_pick_an_older_open_step_over_a_later_done_one(tmp_path):
    live = render([
        start_pass(),
        step("manager", 3, "plan", "pick", "start", ago(10)),
        step("manager", 3, "build", "merge", "done", ago(2)),
    ])
    t = card_now_text(run_page(tmp_path, live), "manager")
    assert "pick" not in t, t


def test_same_second_start_keeps_the_hourglass_on_the_card(tmp_path):
    """A start that shares its second with later-listed steps is a tie, not abandoned (deliberate)."""
    live = render([
        start_pass(),
        step("manager", 3, "build", "merge", "start", ago(1)),
        step("manager", 3, "build", "tests", "start", ago(1)),
    ])
    root = run_page(tmp_path, live)
    assert HOURGLASS in base.substep_text(root, "manager", "merge")


# ---- a stale open step does not hold a lane back from shipped --------------------------------------

@pytest.mark.parametrize("stale_station,stale_name", [("build", "tests"), ("ship", "deploy")])
def test_lane_with_only_a_stale_open_step_and_a_later_done_ship_step_is_shipped(tmp_path, stale_station, stale_name):
    live = render([
        start_pass(120),
        step("manager", 86, stale_station, stale_name, "start", ago(50), title="Task 86"),
        step("manager", 86, "ship", "close #86", "done", ago(48), title="Task 86"),
        step("exam-4", 4, "exam", "read issue", "start", ago(1), role="exam-writer", title="Other"),
    ])
    root = run_page(tmp_path, live)
    done = " ".join(text(n) for n in by_class(root, "lane-done"))
    assert "#86" in done, f"#86 not listed as shipped: {done!r}"
    assert not lanes(root, 86), "#86 still has an open lane"


def test_lane_with_a_live_open_step_is_not_shipped(tmp_path):
    live = render([
        start_pass(),
        step("manager", 86, "ship", "close #86", "done", ago(2), title="Task 86"),
        step("implementer-86", 86, "build", "tests", "start", ago(1), role="implementer", title="Task 86"),
    ])
    root = run_page(tmp_path, live)
    assert lanes(root, 86), "a lane where another agent's latest step is live must stay an open lane"


# ---- no hourglass after pass-end ---------------------------------------------------------------------

def _with_state(state: str) -> dict:
    live = render([
        start_pass(),
        step("manager", 86, "build", "tests", "done", ago(5), title="Task 86"),
        step("manager", 86, "ship", "deploy", "start", ago(1), title="Task 86"),
    ])
    for a in live["agents"]:
        a["state"] = state
    return live


@pytest.mark.parametrize("state", ["ended", "done"])   # failed/stopped keep their last step running (#51, D136)
def test_no_hourglass_for_an_agent_in_an_ended_state(tmp_path, state):
    root = run_page(tmp_path, _with_state(state), clicks=[{"lane": 86, "st": "ship"}])
    assert_detail_not_running(root, 86, "ship", "deploy")
    assert not lane_now_text(root, 86).startswith("now:"), lane_now_text(root, 86)
    assert HOURGLASS not in base.substep_text(root, "manager", "deploy")
    assert "deploy" not in card_now_text(root, "manager")


def test_no_hourglass_anywhere_after_a_real_pass_end(tmp_path):
    live = render([
        start_pass(),
        step("manager", 86, "ship", "deploy", "start", ago(2), title="Task 86"),
        {"kind": "pass-end", "at": ago(1), "result": "ok"},
    ])
    root = run_page(tmp_path, live, clicks=[{"lane": 86, "st": "ship"}])
    assert HOURGLASS not in base.substep_text(root, "manager", "deploy")
    assert_detail_not_running(root, 86, "ship", "deploy")
    assert not lane_now_text(root, 86).startswith("now:")


# ---- reducer -----------------------------------------------------------------------------------------


