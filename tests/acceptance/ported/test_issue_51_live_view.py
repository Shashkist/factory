# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_51_live_view.py at 29e3bf3 (factory#42).
# Paths: the page is src/factory_tools/dashboard/static, the reducer src/factory_tools/progress.py, the fake browser
# tests/acceptance/dashboard/dom_harness_6.js. The three nginx cases (deploy, not the page) are not ported.
# Adapted: worker ids in the fixtures are wmgr/wexam/wimpl/wrev (were w-mgr, ...): the package reducer hashes worker ids that are not [a-z0-9]{1,12} (#22).
"""Exam for issue #51: the Live section of the factory dashboard.

The page is run for real (index.html + app.js) in node, against a small fake browser
(dom_harness_51.js, part of this exam). live.json fixtures are produced by the real
scripts/factory_progress.py render(), so they have the exact published shape. Node is required;
the job runs on ubuntu-latest, which has it. A missing node fails the exam, it never skips.

CONTRACT (the builder works from this; nothing else about the markup is tested)

index.html
  * `<section id="live">` is the FIRST <section> inside <main>, with a heading whose text is "Live".
  * the page's own JS fills it; anything that must be invisible uses the `hidden` ATTRIBUTE
    (a class alone does not count). No inline `style` attribute (the CSP is default-src 'self'),
    no 'unsafe-inline' added to the CSP.
app.js
  * keeps fetching snapshot.json; fetches live.json with `cache: "no-store"` and a `?t=<number>`
    cache-buster, once at load and then every 3000 ms (setInterval or chained setTimeout);
    the buster differs between polls.
  * no innerHTML / outerHTML / insertAdjacentHTML / document.write anywhere (text via textContent).
  * a response that is empty, not JSON, not an object with `schema: 1`, an HTTP error or a network
    error leaves the rendered Live section byte-identical; the next good response replaces it.
  * "laptop offline or asleep" is in VISIBLE text (no `hidden` ancestor) iff
    now - generated_at > 2 minutes, re-evaluated on every poll, also when the poll fails.
Inside #live, after the first good response:
  * runner bar: visible text names the state (running | idle | paused | budget), for running also
    "pass 3" and the budget "8" (case-insensitive, e.g. "Pass 3 of 8"), and the elapsed time since
    pass_started as "<n> min" (e.g. "10 min").
  * five `[data-live-station]` elements, in this order, values plan exam build check ship; each has
    its name as visible text (Plan, Exam, ...). The issues of live.json `issues` ("#<n>" and
    title) and the agent cards sit inside the element of their station.
  * agent card: `[data-agent-id="<id>"]` with `data-state="<agent state>"`; its text has the role,
    "#<issue>", the issue title, the elapsed time since `started` ("<n> min"), and the progress
    "<done>/<total>" over its substeps. `[data-current-substep]` inside it holds the name of the
    current sub-step (the latest one that is start or wait, else the last). Sub-step list:
    one `[data-substep="<name>"]` per sub-step with `data-status="<status>"`; its text holds the
    icon: start hourglass, done check mark, fail cross, wait pause, skip skip-forward, stopped stop.
    Finished agents stay (data-state="done").
  * worker card: `[data-worker-id="<id>"]` with `data-state="<busy|thinking|waiting|idle|finished>"`;
    text has the role, the current tool category when there is one, and every key of `tools` with
    its count as text (the sparkline may be an SVG with <title>s). `styles.css` has a @keyframes rule
    and mentions `busy` (the pulsing dot).
  * log: one `[data-log-row]` per event, newest first, at most 60; the text has agent, station,
    sub-step and detail, in that order.
  * no "undefined", "null" or "NaN" in the visible text, for any valid live.json (also without
    workers, or with all lists empty).
styles.css
  * rules whose selector mentions `live` use the design tokens (var(--...)), no colour literals.
nginx (labs/deploy/nginx/factory.conf, installed by install-block.sh)
  * `location = /live.json` with `Cache-Control "no-cache"` and the X-Robots-Tag header
    (add_header in a location replaces the server-level ones).
"""
# ruff: noqa: E501
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
COMPONENT = REPO / "src" / "factory_tools" / "dashboard" / "static"
INDEX = COMPONENT / "index.html"
APP = COMPONENT / "app.js"
CSS = COMPONENT / "styles.css"
HARNESS = HERE.parent / "dashboard" / "dom_harness_6.js"

NOW = datetime(2026, 11, 15, 10, 0, 0, tzinfo=UTC)
OFFLINE = "laptop offline or asleep"
ICONS = {"start": "⏳", "done": "✅", "fail": "❌", "wait": "⏸",
         "skip": "⏭", "stopped": "⏹"}


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def ago(minutes: float = 0, seconds: float = 0) -> str:
    return iso(NOW - timedelta(minutes=minutes, seconds=seconds))


@pytest.fixture(scope="module", autouse=True)
def _no_crew_dir():
    """The laptop's runner sets LF_CREW_DIR (crew view from local transcripts); the exam must not read it."""
    mp = pytest.MonkeyPatch()
    mp.delenv("LF_CREW_DIR", raising=False)
    yield
    mp.undo()


# ---- fixtures from the real renderer -----------------------------------------------------------

def _load_progress():
    spec = importlib.util.spec_from_file_location("factory_progress_51", REPO / "src" / "factory_tools" / "progress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def step(agent, role, issue, title, station, sub, status, at, detail=""):
    return {"kind": "step", "at": at, "issue": issue, "title": title, "agent": agent, "role": role,
            "station": station, "substep": sub, "status": status, "detail": detail}


def worker_events():
    ev = []
    for i in range(12):  # twelve Bash calls, the last one still open
        ev.append({"kind": "worker", "at": ago(9, 50 - i), "worker": "wmgr", "role": "manager",
                   "event": "tool-start", "tool": "Bash", "call": f"c{i}"})
        if i < 11:
            ev.append({"kind": "worker", "at": ago(9, 49 - i), "worker": "wmgr", "role": "manager",
                       "event": "tool-end", "tool": "Bash", "call": f"c{i}"})
    for i in range(3):
        ev.append({"kind": "worker", "at": ago(3, 30 - i), "worker": "wmgr", "role": "manager",
                   "event": "tool-start", "tool": "Read", "call": f"r{i}"})
        ev.append({"kind": "worker", "at": ago(3, 29 - i), "worker": "wmgr", "role": "manager",
                   "event": "tool-end", "tool": "Read", "call": f"r{i}"})
    ev.append({"kind": "worker", "at": ago(2), "worker": "wmgr", "role": "manager",
               "event": "tool-start", "tool": "Bash", "call": "last"})
    ev += [
        {"kind": "worker", "at": ago(2), "worker": "wexam", "role": "exam-writer", "event": "tool-start",
         "tool": "Edit", "call": "e1"},
        {"kind": "worker", "at": ago(1), "worker": "wexam", "role": "exam-writer", "event": "tool-end",
         "tool": "Edit", "call": "e1"},
        {"kind": "worker", "at": ago(1), "worker": "wimpl", "role": "implementer", "event": "waiting"},
        {"kind": "worker", "at": ago(1), "worker": "wrev", "role": "reviewer", "event": "stopped"},
    ]
    return ev


def build_live(log_steps: int = 0, hostile: bool = False) -> dict:
    fp = _load_progress()
    fp.now = lambda: iso(NOW)  # render() stamps generated_at with this
    t51 = "<script>window.pwned=1</script>" if hostile else "Dashboard: live view"
    sub = "<marquee>tests</marquee>" if hostile else "tests"
    det = '<img src=x onerror="window.pwned=1">' if hostile else "writing the exam"
    ev = [{"kind": "pass-start", "at": ago(10), "pass_no": 3, "budget": 8}]
    ev += [
        step("exam-writer-51", "exam-writer", 51, t51, "exam", "read issue", "start", ago(8)),
        step("exam-writer-51", "exam-writer", 51, t51, "exam", "read issue", "done", ago(7)),
        step("exam-writer-51", "exam-writer", 51, t51, "exam", "fixtures", "start", ago(6)),
        step("exam-writer-51", "exam-writer", 51, t51, "exam", "fixtures", "done", ago(5)),
        step("exam-writer-51", "exam-writer", 51, t51, "exam", sub, "start", ago(4), det),
    ]
    for s_, st in [("one", "start"), ("two", "done"), ("three", "fail"), ("four", "wait"),
                   ("five", "skip"), ("six", "stopped")]:
        ev.append(step("implementer-50", "implementer", 50, "Bootstrap safety", "build", s_, st, ago(3)))
    ev += [
        step("reviewer-49", "reviewer", 49, "Session hardening", "check", "review", "done", ago(2)),
        step("reviewer-49", "reviewer", 49, "Session hardening", "check", "finished", "done", ago(1)),
    ]
    for i in range(log_steps):
        ev.append(step("manager", "manager", None, "", "plan", f"tick {i:03d}", "done", ago(0, 50 - i % 50),
                       f"event-{i + 1:03d}"))
    ev += worker_events()
    return fp.render(ev)


def with_age(live: dict, seconds: int) -> dict:
    live = copy.deepcopy(live)
    live["generated_at"] = live["updated"] = iso(NOW - timedelta(seconds=seconds))
    return live


# ---- running the page --------------------------------------------------------------------------

def run_page(tmp_path: Path, steps: list[dict]) -> dict:
    node = shutil.which("node")
    assert node, "node is required for the live-view exam (ubuntu-latest has it)"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": iso(NOW), "steps": steps}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(INDEX), str(APP), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def page(tmp_path: Path, *lives, gap: int = 3) -> dict:
    """Serve each live.json in turn, `gap` seconds apart (the first answers the page load)."""
    steps = []
    for i, lv in enumerate(lives):
        at = iso(NOW + timedelta(seconds=gap * i))
        steps.append({"now": at, "live": lv})
    return run_page(tmp_path, steps)


# ---- tree helpers (nodes are {t, a, c} or str) -------------------------------------------------

def text(n) -> str:
    return n if isinstance(n, str) else "".join(text(c) for c in n["c"])


def vtext(n) -> str:
    """Text a person can see: nothing under a `hidden` attribute."""
    if isinstance(n, str):
        return n
    if "hidden" in n["a"]:
        return ""
    return "".join(vtext(c) for c in n["c"])


def walk(n):
    if isinstance(n, str):
        return
    yield n
    for c in n["c"]:
        yield from walk(c)


def find(root, attr, value=None):
    return [n for n in walk(root) if attr in n["a"] and (value is None or n["a"][attr] == value)]


def one(root, attr, value=None):
    got = find(root, attr, value)
    assert got, f"no element with {attr}={value!r} in #live"
    return got[0]


def live_tree(result: dict, i: int = 0) -> dict:
    root = result["steps"][i]["live"]
    assert root is not None, "no element with id=live in index.html"
    return root


@pytest.fixture(scope="module")
def good_live() -> dict:
    return build_live(log_steps=0)


@pytest.fixture(scope="module")
def good(tmp_path_factory, good_live):
    return page(tmp_path_factory.mktemp("good"), good_live)


# ---- fixtures are sane (the exam cannot pass on bad data) --------------------------------------

def test_fixture_has_the_published_shape(good_live):
    assert good_live["schema"] == 1 and good_live["generated_at"] == iso(NOW)
    assert good_live["runner"]["state"] == "running" and good_live["runner"]["pass_no"] == 3
    assert {a["id"]: a["state"] for a in good_live["agents"]} == {
        "exam-writer-51": "running", "implementer-50": "stopped", "reviewer-49": "done"}
    assert {w["id"]: w["state"] for w in good_live["workers"]} == {
        "wmgr": "busy", "wexam": "thinking", "wimpl": "waiting", "wrev": "finished"}
    mgr = next(w for w in good_live["workers"] if w["id"] == "wmgr")
    assert mgr["tools"] == {"Bash": 13, "Read": 3} and mgr["tool"] == "Bash"


# ---- Live section: markup, polling -------------------------------------------------------------

class _First(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_main = False
        self.first = None
        self.heading = None
        self._in_live = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.in_main = True
        elif tag == "section" and self.in_main and self.first is None:
            self.first = a.get("id")
            self._in_live = True
        elif tag in ("h1", "h2", "h3") and self._in_live and self.heading is None:
            self.heading = ""

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3") and self._in_live and self.heading is not None:
            self._in_live = False

    def handle_data(self, data):
        if self._in_live and self.heading is not None:
            self.heading += data


def test_live_section_is_the_first_section_of_the_page_and_titled_live():
    p = _First()
    p.feed(INDEX.read_text(encoding="utf-8"))
    assert p.first == "live"
    assert (p.heading or "").strip().lower() == "live"


def test_page_never_interprets_html_or_loosens_the_csp():
    src = APP.read_text(encoding="utf-8")
    assert not re.search(r"\.(innerHTML|outerHTML)|insertAdjacentHTML|document\.write", src)
    assert "unsafe-inline" not in INDEX.read_text(encoding="utf-8")
    assert "eval(" not in src and "new Function" not in src


def test_live_json_is_polled_with_cache_buster_and_no_store(tmp_path, good_live):
    r = page(tmp_path, good_live, good_live)
    for i in (0, 1):
        live = [f for f in r["steps"][i]["fetches"] if "live.json" in f["url"]]
        assert len(live) == 1, f"step {i}: expected one live.json fetch, got {r['steps'][i]['fetches']}"
        assert re.search(r"live\.json\?t=\d+", live[0]["url"]), live[0]["url"]
        assert live[0]["cache"] == "no-store"


def test_cache_buster_changes_between_polls(tmp_path, good_live):
    r = page(tmp_path, good_live, good_live, good_live)
    ts = []
    for s in r["steps"]:
        ts += [re.search(r"\?t=(\d+)", f["url"]).group(1) for f in s["fetches"] if "live.json" in f["url"]]
    assert len(ts) == 3 and len(set(ts)) == 3, ts


def test_live_json_is_polled_every_3_seconds(tmp_path, good_live):
    r = page(tmp_path, good_live)
    assert 3000 in r["delays"], r["delays"]
    # live.json is fetched by a timer, not only at load: a later step fetches it again
    r2 = page(tmp_path, good_live, good_live)
    assert any("live.json" in f["url"] for f in r2["steps"][1]["fetches"])


def test_the_rest_of_the_page_still_uses_snapshot_json(tmp_path, good_live):
    r = page(tmp_path, good_live)
    assert any("snapshot.json" in f["url"] for f in r["steps"][0]["fetches"])


def test_page_runs_without_errors(good):
    assert good["steps"][0]["errors"] == []
    assert good["steps"][0]["style_attr"] == []


# ---- runner bar --------------------------------------------------------------------------------

def _runner(live, **kw):
    live = copy.deepcopy(live)
    live["runner"].update(kw)
    return live


def test_runner_bar_running_shows_pass_budget_and_elapsed(good):
    t = vtext(live_tree(good)).lower()
    assert "running" in t
    assert re.search(r"pass\s*3\b", t), t
    assert re.search(r"\b8\b", t)
    assert re.search(r"\b10\s*m", t), "elapsed since pass_started (10 min) missing"


@pytest.mark.parametrize("state,word", [("idle", "idle"), ("paused", "paused"), ("budget", "budget")])
def test_runner_bar_other_states(tmp_path, good_live, state, word):
    lv = _runner(good_live, state=state, pass_no=None, budget=None, pass_started=None)
    t = vtext(live_tree(page(tmp_path, lv))).lower()
    assert word in t
    assert not re.search(r"pass\s*3\b", t)


# ---- offline banner ----------------------------------------------------------------------------

def test_no_offline_banner_when_fresh(tmp_path, good_live):
    r = page(tmp_path, with_age(good_live, 90))
    assert OFFLINE not in vtext(live_tree(r)).lower()


def test_offline_banner_when_generated_at_is_older_than_two_minutes(tmp_path, good_live):
    r = page(tmp_path, with_age(good_live, 150))
    assert OFFLINE in vtext(live_tree(r)).lower()


def test_offline_banner_uses_generated_at_not_the_clock_of_the_server_alone(tmp_path, good_live):
    # fresh generated_at but an old `updated` must not trigger it; the heartbeat moves generated_at
    lv = with_age(good_live, 20)
    lv["updated"] = iso(NOW - timedelta(minutes=30))
    assert OFFLINE not in vtext(live_tree(page(tmp_path, lv))).lower()


def test_offline_banner_appears_when_the_laptop_goes_quiet_and_clears_on_heartbeat(tmp_path, good_live):
    fresh = with_age(good_live, 10)
    steps = [
        {"now": iso(NOW), "live": fresh},
        {"now": iso(NOW + timedelta(seconds=60)), "live": fresh},    # 70 s old: still fine
        {"now": iso(NOW + timedelta(seconds=150)), "live": fresh},   # 160 s old: offline
        {"now": iso(NOW + timedelta(seconds=300)), "live": with_age(good_live, 5)},  # heartbeat is back
    ]
    # the last step serves data stamped relative to NOW, so restamp it to the step time
    steps[3]["live"] = copy.deepcopy(good_live)
    steps[3]["live"]["generated_at"] = steps[3]["live"]["updated"] = iso(NOW + timedelta(seconds=295))
    r = run_page(tmp_path, steps)
    seen = [OFFLINE in vtext(live_tree(r, i)).lower() for i in range(4)]
    assert seen == [False, False, True, False], seen


def test_offline_banner_shows_when_polls_fail_and_the_last_state_stays(tmp_path, good_live):
    fresh = with_age(good_live, 10)
    steps = [
        {"now": iso(NOW), "live": fresh},
        {"now": iso(NOW + timedelta(seconds=200)), "live": {"error": True}},
    ]
    r = run_page(tmp_path, steps)
    t = vtext(live_tree(r, 1))
    assert OFFLINE in t.lower()
    assert find(live_tree(r, 1), "data-agent-id", "exam-writer-51"), "last good state must stay"


# ---- production line ---------------------------------------------------------------------------

def stations(root):
    return find(root, "data-live-station")


def test_five_stations_in_order(good):
    st = stations(live_tree(good))
    assert [s["a"]["data-live-station"] for s in st] == ["plan", "exam", "build", "check", "ship"]
    for s, name in zip(st, ["plan", "exam", "build", "check", "ship"], strict=True):
        assert name in vtext(s).lower()


def test_issues_and_agent_cards_sit_at_their_station(good):
    root = live_tree(good)
    by = {s["a"]["data-live-station"]: s for s in stations(root)}
    assert "#51" in text(by["exam"]) and "Dashboard: live view" in text(by["exam"])
    assert "#50" in text(by["build"]) and "Bootstrap safety" in text(by["build"])
    assert "#49" in text(by["check"]) and "Session hardening" in text(by["check"])
    assert [n["a"]["data-agent-id"] for n in find(by["exam"], "data-agent-id")] == ["exam-writer-51"]
    assert [n["a"]["data-agent-id"] for n in find(by["build"], "data-agent-id")] == ["implementer-50"]
    assert [n["a"]["data-agent-id"] for n in find(by["check"], "data-agent-id")] == ["reviewer-49"]
    assert not find(by["plan"], "data-agent-id") and not find(by["ship"], "data-agent-id")


# ---- agent cards -------------------------------------------------------------------------------

def card(good, agent_id):
    return one(live_tree(good), "data-agent-id", agent_id)


def test_agent_card_role_issue_title_elapsed(good):
    c = card(good, "exam-writer-51")
    t = vtext(c)
    assert re.search(r"exam[- ]writer", t, re.I)
    assert "#51" in t and "Dashboard: live view" in t
    assert re.search(r"\b8\s*m", t), "elapsed since started (8 min) missing: " + t


def test_agent_card_progress_is_done_over_total(good):
    assert "2/3" in vtext(card(good, "exam-writer-51"))
    assert "1/6" in vtext(card(good, "implementer-50"))
    assert "2/2" in vtext(card(good, "reviewer-49"))


def test_agent_card_names_the_current_substep(good):
    cur = one(card(good, "exam-writer-51"), "data-current-substep")
    assert text(cur).strip() == "tests"


def test_agent_card_lists_substeps_with_status_icons(good):
    c = card(good, "implementer-50")
    items = find(c, "data-substep")
    assert [i["a"]["data-substep"] for i in items] == ["one", "two", "three", "four", "five", "six"]
    for item, status in zip(items, ["start", "done", "fail", "wait", "skip", "stopped"], strict=True):
        assert item["a"].get("data-status") == status
        assert ICONS[status] in text(item), (status, text(item))
        assert item["a"]["data-substep"] in text(item)


def test_agent_card_state_is_exposed_and_finished_agents_stay(good):
    root = live_tree(good)
    states = {n["a"]["data-agent-id"]: n["a"].get("data-state") for n in find(root, "data-agent-id")}
    assert states == {"exam-writer-51": "running", "implementer-50": "stopped", "reviewer-49": "done"}


# ---- worker cards ------------------------------------------------------------------------------

def test_worker_cards_show_state_role_tool_and_tool_counts(good):
    root = live_tree(good)
    ws = {n["a"]["data-worker-id"]: n for n in find(root, "data-worker-id")}
    assert {k: v["a"].get("data-state") for k, v in ws.items()} == {
        "wmgr": "busy", "wexam": "thinking", "wimpl": "waiting", "wrev": "finished"}
    mgr = vtext(ws["wmgr"])
    assert re.search(r"manager", mgr, re.I) and "Bash" in mgr
    assert "Read" in mgr and "13" in mgr and "3" in mgr
    assert re.search(r"exam[- ]writer", vtext(ws["wexam"]), re.I)
    assert re.search(r"implementer", vtext(ws["wimpl"]), re.I)
    assert re.search(r"reviewer", vtext(ws["wrev"]), re.I)


def test_idle_tool_is_not_printed_as_null(good):
    root = live_tree(good)
    w = one(root, "data-worker-id", "wrev")
    assert not re.search(r"null|undefined|None", vtext(w))


def test_busy_worker_has_a_pulsing_dot_in_the_stylesheet():
    css = CSS.read_text(encoding="utf-8")
    assert "@keyframes" in css and "busy" in css


def test_live_styles_use_design_tokens_not_colour_literals():
    css = CSS.read_text(encoding="utf-8")
    rules = [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "live" in s]
    assert rules, "no stylesheet rules for the live section"
    for sel, body in rules:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body), f"{sel}: use var(--token)"
    assert any("var(--" in b for _, b in rules)


# ---- event log ---------------------------------------------------------------------------------

def test_log_is_newest_first_and_capped_at_60(tmp_path):
    live = build_live(log_steps=75)
    # render() keeps 60; hand the page 75 to show that the page caps as well
    base = live["log"][-1]
    live["log"] = [{**base, "substep": f"tick {i:03d}", "detail": f"event-{i:03d}"} for i in range(1, 76)]
    rows = find(live_tree(page(tmp_path, live)), "data-log-row")
    assert len(rows) == 60
    assert "event-075" in text(rows[0]) and "event-016" in text(rows[-1])
    order = [int(re.search(r"event-(\d+)", text(r)).group(1)) for r in rows]
    assert order == sorted(order, reverse=True)


def test_log_row_has_agent_station_substep_and_detail_in_order(tmp_path):
    live = build_live(log_steps=3)
    rows = find(live_tree(page(tmp_path, live)), "data-log-row")
    t = vtext(rows[0])
    assert "event-003" in t
    idx = [t.lower().find(x) for x in ("manager", "plan", "tick 002", "event-003")]
    assert all(i >= 0 for i in idx), t
    assert idx == sorted(idx), t


def test_log_of_the_published_fixture_shows_every_step(good, good_live):
    rows = find(live_tree(good), "data-log-row")
    assert len(rows) == len(good_live["log"]) == 13
    assert "finished" in text(rows[0]) and "reviewer-49" in text(rows[0])


# ---- untrusted text ----------------------------------------------------------------------------

def test_script_and_html_in_title_substep_and_detail_show_up_as_text(tmp_path):
    hostile = build_live(hostile=True)
    r = page(tmp_path, hostile)
    s = r["steps"][0]
    root = live_tree(r)
    t = text(root)
    assert "<script>window.pwned=1</script>" in t, "title must be shown as text"
    assert "<marquee>tests</marquee>" in t, "sub-step must be shown as text"
    assert '<img src=x onerror="window.pwned=1">' in t, "detail must be shown as text"
    assert s["innerHTML"] == [], "HTML was handed to the parser"
    assert s["pwned"] is None
    assert s["errors"] == []
    bad = [n["t"] for n in walk(root) if n["t"] in ("script", "img", "marquee", "iframe", "svg-script")]
    assert bad == []
    for n in walk(root):
        assert not [k for k in n["a"] if k.lower().startswith("on")], n
        assert not str(n["a"].get("href", "")).lower().startswith("javascript:")


def test_hostile_text_in_the_log_row_detail_is_text(tmp_path):
    rows = find(live_tree(page(tmp_path, build_live(hostile=True))), "data-log-row")
    assert any('<img src=x onerror="window.pwned=1">' in text(r) for r in rows)


# ---- empty or invalid live.json ----------------------------------------------------------------

BAD = [
    pytest.param("", id="empty-body"),
    pytest.param("{not json", id="not-json"),
    pytest.param('{"schema": 1, "runner": {"state": "run', id="half-written"),
    pytest.param("null", id="null"),
    pytest.param("[]", id="array"),
    pytest.param("{}", id="empty-object"),
    pytest.param({"http": 500}, id="http-500"),
    pytest.param({"http": 404}, id="http-404"),
    pytest.param({"error": True}, id="network-error"),
]


@pytest.mark.parametrize("bad", BAD)
def test_invalid_live_json_keeps_the_last_good_state(tmp_path, good_live, bad):
    lv = with_age(good_live, 0)
    r = page(tmp_path, lv, bad, gap=0)
    before, after = live_tree(r, 0), live_tree(r, 1)
    assert find(before, "data-agent-id"), "the good state must have rendered"
    assert after == before
    assert r["steps"][1]["errors"] == []
    assert any("live.json" in f["url"] for f in r["steps"][1]["fetches"]), "the page must keep polling"


def test_page_recovers_after_a_bad_response(tmp_path, good_live):
    changed = _runner(with_age(good_live, 0), state="idle", pass_no=None, budget=None, pass_started=None)
    r = page(tmp_path, with_age(good_live, 0), "", {"http": 500}, changed, gap=0)
    assert r["steps"][3]["errors"] == []
    t = vtext(live_tree(r, 3)).lower()
    assert "idle" in t and not re.search(r"pass\s*3\b", t)


@pytest.mark.parametrize("bad", BAD)
def test_invalid_live_json_before_any_good_state_breaks_nothing(tmp_path, bad):
    r = page(tmp_path, bad)
    assert r["steps"][0]["errors"] == []
    root = live_tree(r)
    assert not re.search(r"undefined|NaN|\bnull\b", vtext(root))
    assert "[object" not in vtext(root)


# ---- odd but valid data ------------------------------------------------------------------------

def test_valid_data_never_prints_undefined_null_or_nan(good):
    t = vtext(live_tree(good))
    assert not re.search(r"undefined|NaN|\bnull\b|\[object", t), t


def test_data_without_workers_and_with_empty_lists_still_renders(tmp_path, good_live):
    lv = copy.deepcopy(good_live)
    del lv["workers"]
    r1 = page(tmp_path, lv)
    assert r1["steps"][0]["errors"] == []
    assert len(stations(live_tree(r1))) == 5
    assert find(live_tree(r1), "data-agent-id")

    empty = {**good_live, "issues": [], "agents": [], "workers": [], "log": []}
    r2 = page(tmp_path, empty)
    root = live_tree(r2)
    assert r2["steps"][0]["errors"] == []
    assert len(stations(root)) == 5
    assert not find(root, "data-agent-id") and not find(root, "data-worker-id")
    assert not find(root, "data-log-row")
    assert not re.search(r"undefined|NaN|\bnull\b", vtext(root))


def test_agents_with_missing_optional_fields_render(tmp_path, good_live):
    lv = copy.deepcopy(good_live)
    lv["agents"][0]["issue"] = None
    lv["agents"][0]["substeps"] = []
    lv["workers"][0]["tool"] = None
    lv["workers"][0]["tools"] = {}
    r = page(tmp_path, lv)
    assert r["steps"][0]["errors"] == []
    t = vtext(live_tree(r))
    assert not re.search(r"undefined|NaN|\bnull\b", t)
    assert find(live_tree(r), "data-agent-id", "exam-writer-51")


# ---- nginx -------------------------------------------------------------------------------------


