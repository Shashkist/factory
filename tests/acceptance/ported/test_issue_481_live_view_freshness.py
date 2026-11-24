# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_481_live_view_freshness.py at 29e3bf3 (factory#42).
# Whole file. dom_harness_481.js is copied next to dom_harness_6.js (it serves snapshot.json per step).
"""Exam for issue #481: header age label, sub-step detail on the agent card, freshness thresholds.

Same approach as the #68, #487 and #504 exams (the reducer's output is fed to the page in node), with
dom_harness_481.js, a copy of the #68 harness that can also serve snapshot.json and returns the #updated
header node.

  1. Header age: the header reads "snapshot updated <age>" (the age of the GitHub data), and does not carry
     the live block's age. While a pass runs, the live block shows its own age ("<n> s ago" / "<n> min ago").
  2. Sub-step detail: the agent card shows the (scrubbed) one-line detail of the agent's current sub-step,
     under it, as plain text. An agent without a detail renders as before.
  3. Freshness: "Laptop offline or asleep" appears at more than 2 min of silence while a pass runs. When
     runner.state is idle, paused or budget, the page says "idle, last check <age>" and waits more than
     35 min before it says offline. Both thresholds are exclusive: exactly 2 min / exactly 35 min is not
     offline yet.
"""
# ruff: noqa: E501
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HARNESS481 = HERE.parent / "dashboard" / "dom_harness_481.js"

_spec = importlib.util.spec_from_file_location("exam68_lanes_481", HERE / "test_issue_68_live_view_lanes.py")
assert _spec and _spec.loader
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

base = m.base
ago, render, start_pass, step, text, walk = m.ago, m.render, m.start_pass, m.step, m.text, m.walk
NOW = base.NOW
iso = base.iso
OFFLINE = "laptop offline or asleep"


def vtext(n) -> str:
    """Text a person can see: nothing under a `hidden` attribute."""
    if isinstance(n, str):
        return n
    if "hidden" in n["a"]:
        return ""
    return "".join(vtext(c) for c in n["c"])


def has_class(n, cls: str) -> bool:
    return cls in (n["a"].get("class") or "").split()


def snapshot(minutes_old: float = 10) -> dict:
    return {
        "generated_at": iso(NOW - timedelta(minutes=minutes_old)),
        "claim": None,
        "issues": {"open": 3, "closed": 5, "by_status": {"ready": 1}},
        "queue": [],
        "prs": {"open": [], "merged": []},
        "owner_open": [],
        "decisions": [],
        "runs": {},
        "server": {},
        "throughput": {"closed_per_day": [0] * 14, "median_lead_time_hours": 1.5, "open_incidents": 0},
    }


def run_full(tmp_path: Path, live: dict, snap: dict | None = None) -> dict:
    node = shutil.which("node")
    assert node, "node is required for the live-view exam"
    scenario = tmp_path / "scenario481.json"
    scenario.write_text(json.dumps({"now": iso(NOW), "steps": [{"now": iso(NOW), "live": live, "snapshot": snap}]}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS481), str(base.INDEX), str(base.APP), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])["steps"][0]
    assert not out["errors"], out["errors"]
    assert out["live"] is not None, "no element with id=live in index.html"
    assert out["updated"] is not None, "no element with id=updated in index.html"
    return out


def aged(live: dict, seconds: float, **runner) -> dict:
    live = copy.deepcopy(live)
    live["generated_at"] = live["updated"] = iso(NOW - timedelta(seconds=seconds))
    if runner:
        live["runner"].update(runner)
    return live


def running_live() -> dict:
    return render([start_pass(120), step("manager", 3, "build", "tests", "start", ago(10), title="Task 3")])


def not_running(state: str) -> dict:
    return {"state": state, "pass_no": None, "budget": None, "pass_started": None}


def offline(tmp_path: Path, live: dict) -> bool:
    return OFFLINE in vtext(run_full(tmp_path, live)["live"]).lower()


def card(root, agent_id: str) -> dict:
    cards = [n for n in walk(root) if n["a"].get("data-agent-id") == agent_id]
    assert cards, f"no agent card {agent_id}"
    return cards[0]


# ---- 1. header age label ------------------------------------------------------------------------------

def test_header_age_reads_snapshot_updated_with_the_age_of_the_github_data(tmp_path):
    out = run_full(tmp_path, aged(running_live(), 80), snapshot(10))
    head = text(out["updated"]).lower()
    assert re.search(r"snapshot updated\s*:?\s*10 min ago", head), head


def test_header_age_does_not_carry_the_live_blocks_age(tmp_path):
    out = run_full(tmp_path, aged(running_live(), 80), snapshot(10))
    head = text(out["updated"]).lower()
    assert "live status" not in head, head
    assert "80 s" not in head and "1 min ago" not in head, head


def test_header_age_label_is_the_same_while_no_pass_is_running(tmp_path):
    live = aged(running_live(), 300, **not_running("idle"))
    head = text(run_full(tmp_path, live, snapshot(25))["updated"]).lower()
    assert re.search(r"snapshot updated\s*:?\s*25 min ago", head), head


def test_live_block_shows_its_own_age_while_a_pass_is_running(tmp_path):
    out = run_full(tmp_path, aged(running_live(), 80), snapshot(10))
    t = vtext(out["live"])
    assert re.search(r"\b(80 s|1 min) ago", t), t


# ---- 2. sub-step detail on the agent card -------------------------------------------------------------

DETAIL = "writing the exam for the lanes"


def _detail_live(detail: str) -> dict:
    return render([
        start_pass(120),
        step("manager", 3, "plan", "pick", "done", ago(8), title="Task 3", detail="chose the next issue"),
        step("manager", 3, "build", "tests", "start", ago(2), title="Task 3", detail=detail),
    ])


def test_agent_card_shows_the_detail_of_the_current_substep(tmp_path):
    out = run_full(tmp_path, _detail_live(DETAIL))
    c = card(out["live"], "manager")
    assert DETAIL in text(c), text(c)


def test_agent_card_detail_comes_after_the_now_line_not_in_the_header(tmp_path):
    out = run_full(tmp_path, _detail_live(DETAIL))
    c = card(out["live"], "manager")
    full = text(c)
    assert DETAIL in full, full
    now = [n for n in walk(c) if has_class(n, "live-now")]
    assert now, "no .live-now on the card"
    assert full.index(text(now[0])) < full.index(DETAIL), full
    head = [n for n in walk(c) if has_class(n, "live-head")]
    assert head and DETAIL not in text(head[0])


def test_agent_card_detail_is_the_same_scrubbed_text_as_the_event_log(tmp_path):
    raw = "mailed ops@example.org about 10.1.2.3"
    live = _detail_live(raw)
    scrubbed = base.agent(live, "manager")["substeps"][-1]["detail"]
    assert "<email>" in scrubbed and "ops@example.org" not in scrubbed, scrubbed
    out = run_full(tmp_path, live)
    c = text(card(out["live"], "manager"))
    assert scrubbed in c, c
    assert "ops@example.org" not in c and "10.1.2.3" not in c, c
    rows = [text(n) for n in walk(out["live"]) if "data-log-row" in n["a"]]
    assert any(scrubbed in r for r in rows), rows


def test_agent_card_detail_is_plain_text_never_markup(tmp_path):
    hostile = '<img src=x onerror="window.pwned=1"><b>x</b>'
    out = run_full(tmp_path, _detail_live(hostile))
    c = card(out["live"], "manager")
    assert hostile in text(c)
    assert not out["innerHTML"], out["innerHTML"]
    assert out["pwned"] is None
    assert not [n for n in walk(c) if n["t"] == "img"]
    harmless = card(run_full(tmp_path, _detail_live("plain words"))["live"], "manager")
    assert len([n for n in walk(c) if n["t"] == "b"]) == len([n for n in walk(harmless) if n["t"] == "b"])


def test_agent_without_detail_renders_as_before(tmp_path):
    empty = _detail_live("")
    missing = copy.deepcopy(empty)
    for s in base.agent(missing, "manager")["substeps"]:
        s.pop("detail", None)
    c = card(run_full(tmp_path, empty)["live"], "manager")
    a = text(c)
    b = text(card(run_full(tmp_path, missing)["live"], "manager"))
    assert a == b, (a, b)
    assert not re.search(r"undefined|NaN|\bnull\b|\[object", a), a
    blank = [n for n in walk(c) if "detail" in (n["a"].get("class") or "") and not text(n).strip()]
    assert not blank, "an agent without a detail must not get an empty detail element"
    lis = [text(n) for n in walk(c) if n["t"] == "li" and n["a"].get("data-substep")]
    assert lis == ["✅ pick #3", "⏳ tests #3"], lis


# ---- 3. freshness thresholds --------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [(30, False), (119, False), (120, False), (121, True), (35 * 60, True)])
def test_running_pass_goes_offline_after_more_than_two_minutes(tmp_path, seconds, expected):
    assert offline(tmp_path, aged(running_live(), seconds)) is expected


@pytest.mark.parametrize("state", ["idle", "paused", "budget"])
def test_not_running_shows_idle_last_check_with_the_age(tmp_path, state):
    live = aged(running_live(), 10 * 60, **not_running(state))
    t = vtext(run_full(tmp_path, live)["live"]).lower()
    assert "idle, last check 10 min ago" in t, t


@pytest.mark.parametrize("state", ["idle", "paused", "budget"])
@pytest.mark.parametrize("seconds,expected", [
    (3 * 60, False),          # more than the 2 min that applies while a pass runs
    (20 * 60, False),
    (34 * 60 + 59, False),
    (35 * 60, False),         # exactly 35 min is not offline yet
    (35 * 60 + 1, True),
    (3 * 3600, True),
])
def test_not_running_waits_35_minutes_before_saying_offline(tmp_path, state, seconds, expected):
    assert offline(tmp_path, aged(running_live(), seconds, **not_running(state))) is expected


def test_running_state_does_not_say_idle_last_check(tmp_path):
    t = vtext(run_full(tmp_path, aged(running_live(), 30))["live"]).lower()
    assert "idle, last check" not in t, t


def test_idle_last_check_age_follows_the_heartbeat_not_the_updated_field(tmp_path):
    live = aged(running_live(), 5 * 60, **not_running("idle"))
    live["updated"] = iso(NOW - timedelta(minutes=30))
    t = vtext(run_full(tmp_path, live)["live"]).lower()
    assert "idle, last check 5 min ago" in t, t


# ---- 4. the clock moves while live.json stays byte-identical -------------------------------------------

def run_clock(tmp_path: Path, live: dict, *minutes_later: float, snap: dict | None = None) -> list[dict]:
    """Step 0 at NOW, then one step per entry at NOW + that many minutes. Every step answers with the same
    live.json body, and no timer slower than 10 s fires, so snapshot.json is not reloaded in between."""
    node = shutil.which("node")
    assert node, "node is required for the live-view exam"
    steps = [{"now": iso(NOW), "live": live, "snapshot": snap}]
    steps += [{"now": iso(NOW + timedelta(minutes=mm)), "live": live} for mm in minutes_later]
    scenario = tmp_path / "scenario481_clock.json"
    scenario.write_text(json.dumps({"now": iso(NOW), "steps": steps}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS481), str(base.INDEX), str(base.APP), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    outs = json.loads(p.stdout.strip().splitlines()[-1])["steps"]
    for o in outs:
        assert not o["errors"], o["errors"]
        assert o["live"] is not None, "no element with id=live in index.html"
    return outs


@pytest.mark.parametrize("state", ["idle", "paused", "budget"])
def test_idle_last_check_age_moves_with_the_clock_when_live_json_is_unchanged(tmp_path, state):
    live = aged(running_live(), 10, **not_running(state))
    first, second = (vtext(o["live"]).lower() for o in run_clock(tmp_path, live, 4))
    assert re.search(r"idle, last check 10 s ago", first), first
    assert re.search(r"idle, last check 4 min ago", second), second
    assert "10 s ago" not in second, second


def test_running_live_block_age_moves_with_the_clock_when_live_json_is_unchanged(tmp_path):
    live = aged(running_live(), 10)
    first, second = (vtext(o["live"]).lower() for o in run_clock(tmp_path, live, 1.5))
    assert re.search(r"\b10 s ago", first), first
    assert re.search(r"\b(100 s|1 min) ago", second), second
    assert "10 s ago" not in second.replace("100 s ago", ""), second


def test_live_block_age_keeps_moving_over_several_ticks_with_one_live_json(tmp_path):
    live = aged(running_live(), 10, **not_running("idle"))
    outs = run_clock(tmp_path, live, 2, 10, 20)
    texts = [vtext(o["live"]).lower() for o in outs]
    for t, want in zip(texts, ["10 s ago", "2 min ago", "10 min ago", "20 min ago"], strict=True):
        assert f"idle, last check {want}" in t, texts


def test_offline_running_pass_does_not_keep_the_first_paint_age_next_to_the_banner(tmp_path):
    live = aged(running_live(), 10)
    first, last = (vtext(o["live"]).lower() for o in run_clock(tmp_path, live, 3))
    assert OFFLINE not in first, first
    assert OFFLINE in last, last
    assert "10 s ago" not in last, last


def test_offline_idle_runner_does_not_keep_the_first_paint_age_next_to_the_banner(tmp_path):
    live = aged(running_live(), 10, **not_running("idle"))
    first, last = (vtext(o["live"]).lower() for o in run_clock(tmp_path, live, 36))
    assert OFFLINE not in first, first
    assert OFFLINE in last, last
    assert "10 s ago" not in last, last
