"""Issue #54: follow-ups of the per-repository dashboard view (#45, review of #53).

Same harness and data as #45's exam (`test_issue_45_repo_tabs.py`: the real builder writes snapshot.json from
recorded fixtures, the page index.html + app.js runs in a fake browser under node). The harness here,
`dashboard/dom_harness_54.js`, is #45's plus a station click and a 404 snapshot. The exam checks the
rendered DOM only (criterion 5 also reads two source files).

SEMANTICS CHOSEN FOR THE EXAM

* Criterion 1: workers carry no repository. A worker belongs to an agent only when exactly one running agent
  of its role exists in the FULL live data; otherwise it is on no agent card. So with one implementer per
  repository no agent card in either view holds a worker; with one implementer in all, its card (in the view
  that shows that agent) holds the worker. Where an unowned worker goes is not fixed.
* Criterion 2: a crew node is a `.crew-card` (its title in `.crew-title`) in the Crew block. A title names a
  repository when its short name is a WHOLE word of it ("factory" in "Review round 2 of factory PR #53"; not
  in "Prefactory notes", not as part of "Learning_factory").
* Criterion 3: the lane's own detail lines are the `.lane-step-detail` elements outside the station panel
  (`.lane-detail`); the panel's own lines are those inside it. A lane shows at most 3, the latest by start,
  and none that the open panel shows. (How many remain when the panel hides some is not fixed: only
  "at most 3" and "none of the panel's".)
* Criterion 4: with no snapshot (404) the Live block either holds back, or every issue row names its
  repository (`factory#7`); two rows "#7" of different repositories must never both appear bare.
* Criterion 5: `laneLabel` has no unused parameter; `first_claim` has no `comments=None` default and does
  not fall back to `Source.comments`.

Titles of repository A carry ALPHA, those of B BRAVO. Fixtures are fake.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import SRC
from test_issue_45_repo_tabs import (
    FA,
    LF,
    NOW,
    SHORT,
    assert_only,
    build_world,
    live,
    main_text,
    shared_live,
    text,
    walk,
)

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "dashboard" / "dom_harness_54.js"
STATIC = SRC / "factory_tools" / "dashboard" / "static"
T0, T1 = "2026-11-24T11:50:00+00:00", "2026-11-24T11:59:00+00:00"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("w54"))


# ---- runner ----------------------------------------------------------------------------------------------

def run_page(tmp_path: Path, snapshot: dict | None, steps: list[dict], hash_: str = "") -> list[dict]:
    node = shutil.which("node")
    assert node, "node is required for the page exam"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": NOW, "hash": hash_, "snapshot": snapshot, "steps": steps}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(STATIC / "index.html"), str(STATIC / "app.js"), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["steps"]


def page_of(tmp_path, snap, live_data, click=None, st=None, hash_="") -> dict:
    step: dict = {"now": NOW, "live": live_data}
    clicks = []
    if click:
        clicks.append({"tab": click})
    if st:
        clicks.append(st)
    if clicks:
        step["clicks"] = clicks
    s = run_page(tmp_path, snap, [step], hash_)[0]
    errors = [e for e in s["errors"] if snap is not None or "HTTP 404" not in e]   # the page logs the snapshot it never got
    assert not errors, errors
    return s["page"]


def classes(n) -> list[str]:
    return [] if isinstance(n, str) else n["a"].get("class", "").split()


def with_class(page, cls: str) -> list[dict]:
    return [n for n, _ in walk(page) if cls in classes(n)]


# ---- criterion 1: workers are matched on the full data, then filtered ---------------------------------------

def agent(i, role, n, repo, tag):
    return {"id": i, "role": role, "issue": n, "repo": repo, "station": "build", "state": "running",
            "started": T0, "last": T1,
            "substeps": [{"station": "build", "substep": f"{tag} step", "status": "start", "issue": n, "repo": repo,
                          "started": T0, "at": T1, "detail": ""}]}


def worker(i, role, tool):
    return {"id": i, "role": role, "state": "running", "tool": tool, "tools": {}}


def cards_text(page) -> str:
    return " | ".join(text(c) for c in with_class(page, "live-agent"))


@pytest.mark.parametrize("click,repo,other", [(None, LF, FA), ("factory", FA, LF)])
def test_c1_with_one_implementer_per_repository_no_agent_card_holds_the_workers(world, tmp_path, click, repo, other):
    d = live("running", (LF, FA))
    d["agents"] = [agent("a-lf", "implementer", 11, "", "ALPHA"), agent("a-fa", "implementer", 6, FA, "BRAVO")]
    d["workers"] = [worker("w1", "implementer", "ToolOne"), worker("w2", "implementer", "ToolTwo")]
    page = page_of(tmp_path, world[1], d, click=click)
    assert_only(page, repo, (other,))
    assert with_class(page, "live-agent"), "the view's own implementer card is shown"
    cards = cards_text(page)
    assert "ToolOne" not in cards and "ToolTwo" not in cards, f"workers of unknown repository are on an agent card: {cards!r}"


def test_c1_a_sole_implementer_in_the_data_still_owns_the_worker_in_its_own_view(world, tmp_path):
    d = live("running", (LF, FA))
    d["agents"] = [agent("a-lf", "implementer", 11, "", "ALPHA"), agent("a-fa", "reviewer", 6, FA, "BRAVO")]
    d["workers"] = [worker("w1", "implementer", "ToolImpl"), worker("w2", "reviewer", "ToolRev")]
    lf = cards_text(page_of(tmp_path, world[1], d))
    (tmp_path / "fa").mkdir()
    fa = cards_text(page_of(tmp_path / "fa", world[1], d, click="factory"))
    assert "ToolImpl" in lf and "ToolRev" not in lf, lf
    assert "ToolRev" in fa and "ToolImpl" not in fa, fa


# ---- criterion 2: a crew title naming a repository as a whole word -----------------------------------------

def crew_view(tmp_path, snap, titles: list[str], click=None) -> str:
    d = shared_live()
    kids = d["crew"][0]["children"]
    for k, title in enumerate(titles):
        kids.append({"id": f"x{k}", "kind": "agent", "type": "reviewer", "title": title, "state": "busy", "model": "m",
                     "started": T0, "last": T1, "children": []})
    page = page_of(tmp_path, snap, d, click=click)
    return " ".join(text(c) for c in with_class(page, "crew-title"))


def both_views(tmp_path, snap, title: str) -> tuple[str, str]:
    host = crew_view(tmp_path, snap, [title])
    (tmp_path / "fa").mkdir()
    other = crew_view(tmp_path / "fa", snap, [title], click="factory")
    return host, other


def test_c2_a_title_naming_the_other_repository_as_a_word_is_in_that_view_not_the_hosts(world, tmp_path):
    title = "Review round 2 of factory PR #53"
    host, other = both_views(tmp_path, world[1], title)
    assert title not in host, "a node about factory shows in the Learning_factory view"
    assert title in other, "a node about factory is missing from the factory view"


def test_c2_a_title_that_only_contains_the_name_inside_another_word_is_not_moved(world, tmp_path):
    title = "Prefactory notes for PR #9"
    host, other = both_views(tmp_path, world[1], title)
    assert title in host and title not in other


def test_c2_a_title_naming_the_host_repository_stays_in_the_host_view(world, tmp_path):
    title = "Review round 1 of Learning_factory PR #12"
    host, other = both_views(tmp_path, world[1], title)
    assert title in host and title not in other


def test_c2_a_title_naming_no_repository_stays_in_the_host_view(world, tmp_path):
    title = "Exam for #11 and nothing else"
    host, other = both_views(tmp_path, world[1], title)
    assert title in host and title not in other


# D21: a title moves only when the short name stands right before the reference ("factory #53", "factory PR #53",
# "factory issue #53"); a title that merely mentions the factory elsewhere stays with the host.

@pytest.mark.parametrize("title", [
    "Implement #583 factory package pin",
    "Fix #26 Factory dashboard incident",
    "Reviewer for #568 (pinned factory build)",
    "Learning-factory #4 review",
])
def test_c2_a_host_title_that_mentions_the_factory_elsewhere_stays_in_the_host_view(world, tmp_path, title):
    host, other = both_views(tmp_path, world[1], title)
    assert title in host, "a host crew node left the host view"
    assert title not in other, "a host crew node shows in the factory view"


@pytest.mark.parametrize("title", ["factory #53 review", "Factory PR #53 review", "factory issue #53 review"])
def test_c2_a_title_with_the_short_name_right_before_the_reference_is_in_that_view_not_the_hosts(world, tmp_path, title):
    host, other = both_views(tmp_path, world[1], title)
    assert title not in host, "a node about factory shows in the Learning_factory view"
    assert title in other, "a node about factory is missing from the factory view"


def test_c2_a_host_title_naming_the_factory_stays_on_the_host_lane_even_if_the_factory_has_that_number(world, tmp_path):
    title = "Fix #26 Factory dashboard incident"
    d = shared_live()
    d["issues"] += [{"issue": 26, "repo": LF, "title": "ALPHA twenty-six lane", "station": "build"},
                    {"issue": 26, "repo": FA, "title": "BRAVO twenty-six lane", "station": "build"}]
    d["crew"][0]["children"].append({"id": "x26", "kind": "agent", "type": "implementer", "title": title, "state": "busy",
                                     "model": "m", "started": T0, "last": T1, "children": []})
    host = text(page_of(tmp_path, world[1], d))
    (tmp_path / "fa").mkdir()
    other = text(page_of(tmp_path / "fa", world[1], d, click="factory"))
    assert "ALPHA twenty-six lane" in host and "BRAVO twenty-six lane" not in host
    assert "BRAVO twenty-six lane" in other and "ALPHA twenty-six lane" not in other
    assert title in host, "the host node is missing from the host view"
    assert title not in other, "the host node is on factory's lane or in the factory view"


def test_c2_an_empty_repository_short_name_in_live_data_captures_no_title(world, tmp_path):
    title = "Fix #12: broken - retry"   # punctuation pairs would match an empty name as a "whole word"
    d = shared_live()
    d["issues"].append({"issue": 5, "repo": "Shashkist/", "title": "EMPTY five lane", "station": "plan"})
    d["crew"][0]["children"].append({"id": "xe", "kind": "agent", "type": "reviewer", "title": title, "state": "busy",
                                     "model": "m", "started": T0, "last": T1, "children": []})
    host = " ".join(text(c) for c in with_class(page_of(tmp_path, world[1], d), "crew-title"))
    assert title in host, "a host title was captured by an empty repository name"


# ---- criterion 3: the lane's detail lines -------------------------------------------------------------------

def lane_live() -> dict:
    d = live("running", (LF, FA))
    subs = []
    order = [("exam", "E1"), ("exam", "E2"), ("build", "B1"), ("build", "B2"), ("build", "B3"), ("build", "B4")]
    for k, (station, tag) in enumerate(order):
        subs.append({"station": station, "substep": f"sub {tag}", "status": "done", "issue": 11, "repo": "",
                     "started": f"2026-11-24T11:5{k}:00+00:00", "at": f"2026-11-24T11:5{k}:30+00:00", "detail": f"DETAIL-{tag}"})
    d["agents"] = [{"id": "a1", "role": "implementer", "issue": 11, "repo": "", "station": "build", "state": "running",
                    "started": T0, "last": T1, "substeps": subs}]
    return d


def lane_details(page) -> tuple[list[str], list[str]]:
    """(the lane's own detail lines, the open station panel's lines) as texts."""
    own, panel = [], []
    for n, path in walk(page):
        if "lane-step-detail" in classes(n):
            (panel if any("lane-detail" in classes(p) for p in path) else own).append(text(n).strip())
    return own, panel


def test_c3_a_lane_shows_at_most_the_last_three_sub_step_details(world, tmp_path):
    own, panel = lane_details(page_of(tmp_path, world[1], lane_live()))
    assert panel == []
    assert sorted(own) == ["DETAIL-B2", "DETAIL-B3", "DETAIL-B4"], own


def test_c3_a_lane_with_few_details_shows_them_all(world, tmp_path):
    d = lane_live()
    d["agents"][0]["substeps"] = d["agents"][0]["substeps"][:2]
    own, _ = lane_details(page_of(tmp_path, world[1], d))
    assert sorted(own) == ["DETAIL-E1", "DETAIL-E2"], own


def test_c3_the_lane_does_not_repeat_the_details_an_open_station_panel_shows(world, tmp_path):
    page = page_of(tmp_path, world[1], lane_live(), st={"lane": "ALPHA eleven", "st": "build"})
    own, panel = lane_details(page)
    assert sorted(panel) == ["DETAIL-B1", "DETAIL-B2", "DETAIL-B3", "DETAIL-B4"], f"the open panel lists its station's details: {panel}"
    assert len(own) <= 3, own
    assert not set(own) & set(panel), f"the lane repeats the panel's details: {own}"


def test_c3_closing_the_panel_brings_the_lane_details_back(world, tmp_path):
    st = {"lane": "ALPHA eleven", "st": "build"}
    s = run_page(tmp_path, world[1], [{"now": NOW, "live": lane_live(), "clicks": [st, st]}])[0]
    assert not s["errors"], s["errors"]
    own, panel = lane_details(s["page"])
    assert panel == [] and sorted(own) == ["DETAIL-B2", "DETAIL-B3", "DETAIL-B4"], (own, panel)


# ---- criterion 4: no snapshot, no unprefixed pair ---------------------------------------------------------

ROW = re.compile(r"([\w./-]*)#(\d+) (ALPHA|BRAVO) (\w+)")
OWNER = {"ALPHA": SHORT[LF], "BRAVO": SHORT[FA]}


def test_c4_without_a_snapshot_the_live_block_never_shows_two_repositories_without_their_prefix(tmp_path):
    page = page_of(tmp_path, None, live("running", (LF, FA)))
    seen = ROW.findall(text(page))
    for prefix, n, token, _ in seen:
        assert prefix.split("/")[-1] == OWNER[token], f"#{n} {token} row shows without its repository ({prefix!r}): {seen}"


def test_c4_without_a_snapshot_no_bare_number_of_either_repository_shows_in_agent_cards_either(tmp_path):
    d = live("running", (LF, FA))
    d["agents"] = [agent("a-lf", "implementer", 7, LF, "ALPHA"), agent("a-fa", "reviewer", 7, FA, "BRAVO")]
    page = page_of(tmp_path, None, d)
    bare = [ct for ct in (text(c) for c in with_class(page, "live-agent") + with_class(page, "live-issue"))
            if re.search(r"(?<![\w./-])#7\b", ct)]
    assert not bare, f"a bare #7 shows with no snapshot while two repositories have a #7: {bare}"


def test_c4_with_a_snapshot_the_prefix_is_still_dropped_inside_a_view(world, tmp_path):
    page = page_of(tmp_path, world[1], live("running", (LF, FA)))
    assert "#7 ALPHA seven" in main_text(page) and "Learning_factory#7" not in main_text(page)


# ---- criterion 5: unused code is gone -------------------------------------------------------------------

def test_c5_lane_label_has_no_unused_parameter():
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    m = re.search(r"function laneLabel\(([^)]*)\)\s*\{", src)
    assert m, "laneLabel is gone or renamed: update the exam"
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    depth, i = 1, m.end()
    while depth and i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    body = src[m.end():i]
    for p in params:
        assert re.search(rf"\b{re.escape(p)}\b", body), f"laneLabel's parameter {p!r} is never used"


def test_c5_first_claim_has_no_comments_default_or_fallback():
    path = SRC / "factory_tools" / "dashboard" / "snapshot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "first_claim")
    names = [a.arg for a in fn.args.args]
    defaults = dict(zip(names[len(names) - len(fn.args.defaults):], fn.args.defaults, strict=True))
    assert not isinstance(defaults.get("comments"), ast.Constant), "first_claim still defaults comments to None"
    assert "Source.comments" not in ast.unparse(fn), "first_claim still falls back to Source.comments"
