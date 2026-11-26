"""Issue #87: review leftovers of the live view (criteria 1 to 6; 7 is a follow-up).

The page (index.html + app.js) runs in the fake browser of `dashboard/dom_harness_87.js` under node (a copy of
#54's with document.hidden / visibilitychange, scrollTop and a per-step "no timers" switch). The snapshot comes
from the real builder (`build_world`), live.json is written by hand in the builder's shapes. Fixtures are fake.

SEMANTICS CHOSEN FOR THE EXAM

* Criterion 1: a worker of role R is attached to the sole running agent of role R unless the worker is
  `finished` AND its `started` is before the agent's `started` minus 60 s. A finished worker that started at or
  after that point still matches (the rule of the issue); a not-finished worker always matches.
* Criterion 2: the `.live-log` element after a re-render has the scrollTop the viewer left on the old one (the
  harness has no layout, so the exam sets scrollTop on the element and reads it after the next render).
* Criterion 3: a station called `constructor` (or `__proto__`, `toString`) is an unknown station: it renders
  without an error, and the page still shows the issue. Also a static check of the five lookup tables.
* Criterion 4: the banner is the element `#live-offline`; shown means it has no `hidden` attribute.
* Criterion 5: an update whose generated_at is older than the one on screen is applied.
* Criterion 6: while document.hidden is true a poll tick does not fetch live.json; a `visibilitychange` to
  visible fetches it once.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_issue_45_repo_tabs import LF, NOW, build_world, live, text, walk
from test_issue_54_repo_view_followups import STATIC, T0, T1, cards_text, with_class

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "dashboard" / "dom_harness_87.js"
APP_JS = STATIC / "app.js"
TICK_NOW = "2026-11-24T12:00:30Z"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("w87"))


def run_steps(tmp_path: Path, snapshot: dict, steps: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node, "node is required for the page exam"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": NOW, "hash": "", "snapshot": snapshot, "steps": steps}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(STATIC / "index.html"), str(APP_JS), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["steps"]


def step(live_data, now=NOW, **kw) -> dict:
    return {"now": now, "live": live_data, **kw}


def live_fetches(s: dict) -> list[dict]:
    return [f for f in s["fetches"] if "live.json" in f["url"]]


def agent(i, role, state, started, repo=""):
    return {"id": i, "role": role, "issue": 11, "repo": repo, "station": "build", "state": state, "started": started,
            "last": T1, "substeps": [{"station": "build", "substep": f"{i} step", "status": "start", "issue": 11,
                                      "repo": repo, "started": started, "at": T1, "detail": ""}]}


def worker(i, role, state, started, tool):
    return {"id": i, "role": role, "state": state, "tool": tool, "tools": {}, "started": started, "last": T1}


def page_with(tmp_path, snap, d) -> dict:
    s = run_steps(tmp_path, snap, [step(d)])[0]
    assert not s["errors"], s["errors"]
    return s["page"]


# ---- criterion 1: a finished worker never attaches to a newer card of its role -------------------------------

R1_START, R2_START = "2026-11-24T10:00:00+00:00", "2026-11-24T11:50:00+00:00"


def reviewer_world(workers: list[dict]) -> dict:
    d = live("running", (LF,))
    d["agents"] = [agent("rev-r1", "reviewer", "done", R1_START), agent("rev-r2", "reviewer", "running", R2_START)]
    d["workers"] = workers
    return d


def test_c1_a_finished_round_1_worker_is_not_inside_the_round_2_reviewer_card(world, tmp_path):
    d = reviewer_world([worker("w-old", "reviewer", "finished", R1_START, "ToolRoundOne")])
    page = page_with(tmp_path, world[1], d)
    cards = with_class(page, "live-agent")
    assert len(cards) == 2, "premise: both reviewer cards are on the page"
    assert "ToolRoundOne" not in cards_text(page) and not [
        w for c in cards for w, _ in walk(c) if "live-worker" in w["a"].get("class", "").split()
    ], f"a finished worker of round 1 sits inside an agent card: {cards_text(page)!r}"


def test_c1_a_running_worker_still_attaches_to_the_sole_running_reviewer(world, tmp_path):
    d = reviewer_world([worker("w-new", "reviewer", "busy", R2_START, "ToolRoundTwo")])
    page = page_with(tmp_path, world[1], d)
    assert "ToolRoundTwo" in cards_text(page), "control: the running worker is in the running reviewer's card"


def test_c1_a_finished_worker_that_started_after_the_agent_still_attaches(world, tmp_path):
    d = reviewer_world([worker("w-quick", "reviewer", "finished", "2026-11-24T11:55:00+00:00", "ToolQuick")])
    page = page_with(tmp_path, world[1], d)
    assert "ToolQuick" in cards_text(page), "the rule matches finished workers that started after the agent's start minus 60 s"


def test_c1_the_60_second_slack_before_the_agent_start_is_kept(world, tmp_path):
    d = reviewer_world([worker("w-edge", "reviewer", "finished", "2026-11-24T11:49:10+00:00", "ToolEdge")])
    page = page_with(tmp_path, world[1], d)
    assert "ToolEdge" in cards_text(page), "a worker that started 50 s before the agent is within the 60 s slack"


# ---- criterion 2: the log keeps its scroll position -------------------------------------------------------------

def log_rows(n: int) -> list[dict]:
    return [{"at": f"2026-11-24T11:{i % 60:02d}:00+00:00", "agent": "impl-1", "station": "build", "substep": f"row {i}",
             "status": "start", "detail": "", "issue": 11, "repo": ""} for i in range(n)]


def test_c2_re_rendering_the_live_box_keeps_the_log_scroll_position(world, tmp_path):
    d1 = live("running", (LF,))
    d1["log"] = log_rows(30)
    d2 = live("running", (LF,))
    d2["generated_at"] = "2026-11-24T11:59:45+00:00"
    d2["log"] = log_rows(31)
    out = run_steps(tmp_path, world[1], [step(d1), step(d2, now=TICK_NOW, scroll={"sel": ".live-log", "top": 240})])
    assert out[0]["scrollTops"] == [0], "premise: one log, at the top"
    assert len([n for n, _ in walk(out[1]["page"]) if "live-row" in n["a"].get("class", "").split()]) == 31, "premise: the new data was rendered"
    assert out[1]["scrollTops"] == [240], f"the log lost its scroll position on re-render: {out[1]['scrollTops']}"


def test_c2_the_scroll_position_survives_several_re_renders(world, tmp_path):
    ds = []
    for k in range(3):
        d = live("running", (LF,))
        d["generated_at"] = f"2026-11-24T11:59:{30 + k * 5:02d}+00:00"
        d["log"] = log_rows(30 + k)
        ds.append(d)
    out = run_steps(tmp_path, world[1], [step(ds[0]), step(ds[1], now=TICK_NOW, scroll={"sel": ".live-log", "top": 90}),
                                         step(ds[2], now=TICK_NOW)])
    assert out[2]["scrollTops"] == [90]


# ---- criterion 3: prototype-safe lookup tables ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["constructor", "__proto__", "toString", "hasOwnProperty"])
def test_c3_a_station_named_like_an_object_member_renders_without_throwing(world, tmp_path, name):
    d = live("running", (LF,))
    d["issues"] = [{"issue": 11, "repo": "", "title": "ZULU eleven lane", "station": name}]
    d["agents"] = [agent("a-odd", "implementer", "running", T0)]
    d["agents"][0]["station"] = name
    d["agents"][0]["substeps"][0]["station"] = name
    s = run_steps(tmp_path, world[1], [step(d)])[0]
    assert not s["errors"], s["errors"]
    assert "ZULU eleven lane" in text(s["page"]), "the issue is not on the page"
    assert with_class(s["page"], "live-agent"), "the agent card is missing"


@pytest.mark.parametrize("role", ["constructor", "__proto__", "toString"])
def test_c3_a_role_named_like_an_object_member_renders_without_throwing(world, tmp_path, role):
    d = live("running", (LF,))
    d["agents"] = [agent("a-odd", role, "running", T0)]
    d["workers"] = [worker("w-odd", role, "busy", T0, "ToolOdd")]
    s = run_steps(tmp_path, world[1], [step(d)])[0]
    assert not s["errors"], s["errors"]
    assert with_class(s["page"], "live-agent"), "the agent card is missing"
    assert "function" not in " ".join(text(c) for c in with_class(s["page"], "live-agent")).lower(), "a prototype member leaked into a card"


@pytest.mark.parametrize("name", ["at", "LIVE_ICONS", "LIVE_ROLE_ICONS", "LIVE_ENDED", "names"])
def test_c3_the_lookup_table_is_created_without_a_prototype(name):
    src = APP_JS.read_text(encoding="utf-8")
    decls = re.findall(rf"\bvar\s+{name}\s*=\s*([^;]*;)", src)
    assert decls, f"no `var {name} = ...` in app.js"
    for body in decls:
        assert "Object.create(null)" in body, f"`{name}` is a plain object literal: {body[:60]!r}"


# ---- criterion 4: missing or unparseable generated_at -> offline banner ------------------------------------------

def banner(page) -> dict:
    found = [n for n, _ in walk(page) if n["a"].get("id") == "live-offline"]
    assert len(found) == 1, f"expected one #live-offline element, found {len(found)}"
    return found[0]


def shown(n: dict) -> bool:
    return "hidden" not in n["a"]


def test_c4_a_fresh_generated_at_hides_the_banner(world, tmp_path):
    d = live("running", (LF,))
    d["generated_at"] = "2026-11-24T11:59:50+00:00"
    assert not shown(banner(page_with(tmp_path, world[1], d))), "control: a fresh state needs no banner"


def test_c4_a_missing_generated_at_shows_the_offline_banner(world, tmp_path):
    d = live("running", (LF,))
    del d["generated_at"]
    b = banner(page_with(tmp_path, world[1], d))
    assert shown(b), "no generated_at: the banner stays hidden"
    assert "offline or asleep" in text(b).lower()


@pytest.mark.parametrize("bad", ["", "yesterday", "2026-13-45T99:99:99", None])
def test_c4_an_unparseable_generated_at_shows_the_offline_banner(world, tmp_path, bad):
    d = live("running", (LF,))
    d["generated_at"] = bad
    b = banner(page_with(tmp_path, world[1], d))
    assert shown(b), f"generated_at={bad!r}: the banner stays hidden"
    assert "offline or asleep" in text(b).lower()


# ---- criterion 5: no out-of-order guard -------------------------------------------------------------------------------

def titled(title: str, generated: str) -> dict:
    d = live("running", (LF,))
    d["generated_at"] = generated
    d["issues"] = [{"issue": 11, "repo": "", "title": title, "station": "build"}]
    return d


def test_c5_an_update_with_an_older_generated_at_is_applied(world, tmp_path):
    first = titled("FIRST state title", "2026-11-24T11:59:30+00:00")
    back = titled("SECOND state title", "2026-11-24T11:40:00+00:00")
    out = run_steps(tmp_path, world[1], [step(first), step(back, now=TICK_NOW)])
    assert "FIRST state title" in text(out[0]["page"]), "premise: the first state is shown"
    assert "SECOND state title" in text(out[1]["page"]), "the update with the older generated_at was dropped"
    assert "FIRST state title" not in text(out[1]["page"])


def test_c5_updates_keep_flowing_after_a_clock_correction(world, tmp_path):
    a = titled("TITLE A", "2026-11-24T11:59:30+00:00")
    b = titled("TITLE B", "2026-11-24T11:30:00+00:00")
    c = titled("TITLE C", "2026-11-24T11:31:00+00:00")
    out = run_steps(tmp_path, world[1], [step(a), step(b, now=TICK_NOW), step(c, now=TICK_NOW)])
    assert "TITLE C" in text(out[2]["page"]), "updates froze after the clock went backwards"


# ---- criterion 6: no polling while the tab is hidden ---------------------------------------------------------------------

def test_c6_a_poll_tick_fetches_live_json_while_the_tab_is_visible(world, tmp_path):
    d = live("running", (LF,))
    out = run_steps(tmp_path, world[1], [step(d), step(d, now=TICK_NOW)])
    assert len(live_fetches(out[1])) == 1, "control: a tick of a visible tab polls once"


def test_c6_a_poll_tick_does_not_fetch_while_the_tab_is_hidden(world, tmp_path):
    d = live("running", (LF,))
    out = run_steps(tmp_path, world[1], [step(d), step(d, now=TICK_NOW, hidden=True), step(d, now=TICK_NOW)])
    assert not live_fetches(out[1]), f"a hidden tab polled: {live_fetches(out[1])}"
    assert not live_fetches(out[2]), "still hidden: no poll"


def test_c6_visibilitychange_to_visible_polls_once(world, tmp_path):
    d1 = titled("BEFORE hide", "2026-11-24T11:59:30+00:00")
    d2 = titled("AFTER show", "2026-11-24T11:59:55+00:00")
    out = run_steps(tmp_path, world[1], [
        step(d1),
        step(d1, now=TICK_NOW, hidden=True),
        step(d2, now=TICK_NOW, hidden=False, fire=["visibilitychange"], tick=False)])
    assert not live_fetches(out[1]), "premise: nothing fetched while hidden"
    assert len(live_fetches(out[2])) == 1, f"visibilitychange to visible must poll exactly once: {live_fetches(out[2])}"
    assert "AFTER show" in text(out[2]["page"]), "the poll's data was not rendered"


def test_c6_visibilitychange_to_hidden_does_not_poll(world, tmp_path):
    d = live("running", (LF,))
    out = run_steps(tmp_path, world[1], [step(d), step(d, now=TICK_NOW, hidden=True, fire=["visibilitychange"], tick=False)])
    assert not live_fetches(out[1]), "going hidden must not fetch"
