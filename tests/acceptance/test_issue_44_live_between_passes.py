"""Issue #44: the Live block between passes (idle header, but the Manager row says "working" and the lanes of
the ended pass say "waiting for 2.8 h").

The events file is real: the exam writes progress.jsonl, runs the real renderer (`factory-tools progress
render`) over it and feeds the resulting live.json to the page (index.html + app.js) in the fake browser of
`dashboard/dom_harness_54.js` under node, with the clock injected (NOW). Only the stamps the renderer takes from
the wall clock (generated_at, updated) are replaced with fixed times, and the crew block (which the renderer
fills from transcripts, off in tests) is set by hand to what the owner saw: a manager session whose last tool
call is still "Bash ...", state busy.

DATA SHAPE ASSUMPTIONS (the issue does not fix them)

* "Ended pass": runner.state is idle (the renderer sets it on `pass-end`, with runner.pass_ended and
  runner.result), or the events end with `pass-end`.
* The Manager row is the element with class `lane-manager` (the page's current row); its text is judged.
* "last pass": the page says it, case-insensitively ("last pass", "Last pass"), anywhere in the main area.
* The row shows the last pass's result (the text of runner.result) and when it ended: a relative time
  ("2.6 h ago", "35 min ago") or a clock time (hh:mm). The exam accepts either.
* A live "waiting" lane is a lane whose head says "waiting" (today: "waiting · for 2.8 h"). An ended
  pass's lanes may be collapsed or listed, but each still names its task (title) so the owner can see
  what shipped and what paused.
* Control: during a live pass (no pass-end, runner running, agents recently active) the Manager row still
  says "working" and a lane still says "working".
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from test_issue_13_progress import Sandbox
from test_issue_45_repo_tabs import build_world, main_text, text
from test_issue_54_repo_view_followups import page_of, with_class

T = "2026-11-24T{}:00+00:00"
TITLES = {7: "ALPHA seven shipped lane", 11: "BRAVO eleven paused lane", 12: "CHARLIE twelve paused lane"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("w44"))


# ---- the events file -> live.json, through the real renderer ---------------------------------------------

def ev(kind: str, hhmm: str, **kw) -> dict:
    return {"kind": kind, "at": T.format(hhmm), **kw}


def step(hhmm, issue, station, status, substep, agent="impl-1", role="implementer"):
    return ev("step", hhmm, issue=issue, repo="", title=TITLES[issue], agent=agent, role=role, station=station,
              substep=substep, status=status, detail="")


def render(base: Path, events: list[dict], generated: str, crew_state: str = "busy") -> dict:
    sb = Sandbox(base)
    sb.events.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "factory_tools", "progress", "render", "--out", str(base / "live.json")],
                       cwd=base, env=sb.env(), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    d = json.loads((base / "live.json").read_text(encoding="utf-8"))
    d["generated_at"] = d["updated"] = T.format(generated)
    d["crew"] = [{"id": "c0", "kind": "session", "type": "manager", "title": "manager pass", "state": crew_state,
                  "model": "m", "started": T.format("08:55"), "last": T.format("09:24"),
                  "tool": "Bash", "label": "Fetch and show factory state", "children": []}]
    return d


def ended_pass_events() -> list[dict]:
    """Pass 23 started 08:55, ended 09:25, and the file ends with pass-end."""
    return [
        ev("pass-start", "08:55", pass_no=23, budget=40),
        step("09:10", 7, "build", "start", "implement"),
        step("09:12", 7, "ship", "done", "merge", agent="mgr-1", role="manager"),
        step("09:15", 11, "check", "wait", "review round 2", agent="rev-1", role="reviewer"),
        step("09:18", 12, "exam", "wait", "exam waits on owner", agent="exam-1", role="exam-writer"),
        ev("pass-end", "09:25", result="shipped 1, paused 2"),
    ]


def live_pass_events() -> list[dict]:
    """Pass 24 running: agents active two minutes before generated_at, no pass-end."""
    return [
        ev("pass-start", "11:50", pass_no=24, budget=40),
        step("11:55", 11, "build", "start", "implement"),
        step("11:57", 12, "exam", "start", "write exam", agent="exam-1", role="exam-writer"),
    ]


def page(tmp_path, snap, live_data) -> dict:
    return page_of(tmp_path, snap, live_data)


def manager_row(pg) -> str:
    rows = with_class(pg, "lane-manager")
    assert rows, "no Manager row in the Live block"
    return text(rows[0])


def main_area(pg) -> str:
    return main_text(pg)


def lane_heads(pg) -> list[str]:
    return [text(n) for n in with_class(pg, "lane-head")]


WAITING_LANE = re.compile(r"\bwaiting\b[\s·:,-]*for\s+[\d.]+\s*(s|min|h)\b", re.I)
WHEN = re.compile(r"\d+(\.\d+)?\s*(s|sec|min|h)\b|\b\d{1,2}:\d{2}\b", re.I)


# ---- criterion 1: the Manager row between passes ------------------------------------------------------------

def test_c1_manager_row_does_not_say_working_when_the_pass_has_ended(world, tmp_path):
    d = render(tmp_path, ended_pass_events(), "09:30")
    assert d["runner"]["state"] == "idle", "premise: the renderer reports an idle runner after pass-end"
    row = manager_row(page(tmp_path, world[1], d))
    assert "working" not in row.lower(), f"Manager row of an ended pass: {row!r}"
    assert "now:" not in row.lower(), f"Manager row still shows the last tool call: {row!r}"


def test_c1_manager_row_shows_the_last_pass_result_and_when_it_ended(world, tmp_path):
    d = render(tmp_path, ended_pass_events(), "09:30")
    row = manager_row(page(tmp_path, world[1], d))
    assert "shipped 1, paused 2" in row, f"the last pass's result is missing from the Manager row: {row!r}"
    assert WHEN.search(row), f"when the pass ended is missing from the Manager row: {row!r}"


def test_c1_manager_row_does_not_say_working_when_the_runner_is_idle_without_a_pass_end(world, tmp_path):
    events = [ev("pass-start", "08:55", pass_no=23, budget=40), step("09:10", 7, "build", "start", "implement"),
              ev("runner-state", "09:20", state="idle", note="")]
    d = render(tmp_path, events, "09:30")
    assert d["runner"]["state"] == "idle", "premise: runner-state idle"
    row = manager_row(page(tmp_path, world[1], d))
    assert "working" not in row.lower(), f"Manager row of an idle runner: {row!r}"


# ---- criterion 2: lanes of an ended pass --------------------------------------------------------------------

def test_c2_lanes_of_an_ended_pass_are_not_shown_as_live_waiting_lanes(world, tmp_path):
    d = render(tmp_path, ended_pass_events(), "09:30")
    pg = page(tmp_path, world[1], d)
    heads = lane_heads(pg)
    waiting = [h for h in heads if WAITING_LANE.search(h) or re.search(r"\bwaiting\b", h, re.I)]
    assert not waiting, f"live waiting lanes after the pass ended: {waiting}"
    assert not WAITING_LANE.search(main_area(pg)), "'waiting for N h' still on the page"
    assert not [n for n in with_class(pg, "lane") if n["a"].get("data-running") == "1"], "a lane of the ended pass is marked running"


def test_c2_lanes_of_an_ended_pass_are_shown_as_last_pass_and_still_name_their_tasks(world, tmp_path):
    d = render(tmp_path, ended_pass_events(), "09:30")
    area = main_area(page(tmp_path, world[1], d))
    assert re.search(r"last pass", area, re.I), "no 'last pass' label for the lanes of the ended pass"
    for n in (11, 12):
        assert TITLES[n] in area, f"the paused task #{n} vanished from the page: it should be listed under the last pass"
    assert TITLES[7] in area, "the shipped task vanished from the page"


# ---- criterion 3: the control case, a live pass keeps its live state ------------------------------------------

def test_c3_control_during_a_live_pass_the_manager_row_says_working(world, tmp_path):
    d = render(tmp_path, live_pass_events(), "11:59")
    assert d["runner"]["state"] == "running", "premise: the pass is running"
    row = manager_row(page(tmp_path, world[1], d))
    assert "working" in row.lower(), f"live Manager row lost its state: {row!r}"


def test_c3_control_during_a_live_pass_the_lanes_are_live_not_last_pass(world, tmp_path):
    d = render(tmp_path, live_pass_events(), "11:59")
    pg = page(tmp_path, world[1], d)
    heads = lane_heads(pg)
    assert any(TITLES[11] in h or TITLES[12] in h for h in heads), f"live lanes missing: {heads}"
    assert any("working" in h.lower() for h in heads), f"no live lane says working: {heads}"
    assert [n for n in with_class(pg, "lane") if n["a"].get("data-running") == "1"], "no live lane is marked running"
    assert not re.search(r"last pass:", main_area(pg), re.I), "a live pass's lanes are labelled as the last pass"

