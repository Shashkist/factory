"""Issue #45 (D13, D18): one dashboard per repository, with a top navigation bar to switch between them.

The page is exercised the way #6's exam does it: the real builder (`python -m factory_tools.dashboard build
--fixtures ...`) writes snapshot.json from recorded fixtures of two (and, for criterion 3, three)
repositories, and the page (index.html + app.js) is run in a fake browser under node
(`dashboard/dom_harness_45.js`: a copy of #6's harness with a live address bar and tab clicks) with that
snapshot and a live.json. So the exam does not fix the shape of snapshot.json, only what the page shows.

SEMANTICS CHOSEN FOR THE EXAM (the implementer follows these; the issue leaves them open)

* The top bar is a `<nav>` (or an element with role="tablist"). Its tabs are the `<a>`, `<button>` or
  `[role=tab]` elements inside it: one per repository in the data, in the data's order (repos.yaml order),
  each carrying the repository's short name (the part after "/") as a whole word.
* The selected tab is marked with `aria-current` (any value but "false", e.g. "page"). Exactly one tab is.
* Each tab shows a small count: any number in the tab's text (open issues, or "2 working": the exam does
  not say which).
* Address: the hash form `#/<short name>`, e.g. `#/factory`, `#/Learning_factory`. A tab is a link to its
  address (or sets it with location.hash / history.pushState); the exam follows the link or listens for
  the page's own handler. No hash, or a hash naming no repository in the data, opens the HOST repository.
* Host rule: the data does not name a host (snapshot.json has no such key, and `repos` is ordered as
  repos.yaml is), and the current page already takes `Object.keys(repos)[0]` as the host (`hostRepo`), so
  the host is the FIRST repository listed. In the exam's data that is Learning_factory.
* "The bar" for criteria 2 and 4 is everything on the page outside `<main>` (header and nav). The
  per-repository area is `<main>`. "Anywhere outside the bar" means anywhere in the page body outside the
  `<nav>`.
* The runner is shared: its state, its pass number and when it last checked are in the bar, outside
  `<main>`, whichever repository is selected.
* Rows inside a repository's view say `#575`, never `Learning_factory#575` or `factory#575`.
* Narrow screens (criterion 4): the harness is a fake DOM and cannot measure layout, so the exam asserts the
  CSS rules that guarantee it: the tab row (the tabs' parent, or the `<nav>`) has `overflow-x: auto|scroll`
  or `flex-wrap: wrap`, no rule on html, body, header, nav or main fixes a width or min-width over 390 px,
  and the viewport meta tag is set.
* Privacy (LF D14): built files hold only what the page shows: seeded emails, token-shaped strings and
  STATE.md text never reach any output file, no field beyond the page's (body, author, labels, ...) is carried.

Test names: c1, c2, c3 cover the issue's criterion 1 (tabs, only-its-rows, address), c4 criterion 2 (runner),
c5 criterion 3 (third repository), c6 the dropped prefix, c7 criterion 4 (390 px), c8 criterion 5 (privacy).

Titles of repository A carry the word ALPHA, those of B BRAVO, those of C CHARLIE, so "another repository's
rows do not appear" is a text search. Fixtures are fake.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import SRC
from test_issue_6_dashboard import (
    EMAIL_RE,
    EMAILS,
    STATE_TEXT,
    TOKEN_RE,
    TOKENS,
    build,
    claim_comment,
    decisions_md,
    issue,
    owner_md,
    pr,
    run,
    state_md,
    write_json,
)

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "dashboard" / "dom_harness_45.js"
STATIC = SRC / "factory_tools" / "dashboard" / "static"
PAGE_FILES = ("index.html", "app.js", "styles.css", "theme.js")

LF = "Shashkist/Learning_factory"   # first in repos.yaml: the host
FA = "Shashkist/factory"
CH = "Shashkist/charlie"
SHORT = {LF: "Learning_factory", FA: "factory", CH: "charlie"}
TOKEN_OF = {LF: "ALPHA", FA: "BRAVO", CH: "CHARLIE"}
NOW = "2026-11-24T12:00:00Z"


# ---- data -----------------------------------------------------------------------------------------------

def make_world(root: Path, with_third: bool = False, fa_extra_open: int = 0) -> tuple[Path, Path]:
    fx = root / "fx"
    d = {r: fx / r.replace("/", "__") for r in (LF, FA, CH)}
    for p in d.values():
        p.mkdir(parents=True)
    write_json(d[LF] / "issues.json", [
        issue(7, "ALPHA seven ready", "OPEN", ["status:ready", "priority:p1", "phase:1"]),
        issue(11, "ALPHA eleven working", "OPEN", ["status:in-progress", "priority:p2", "phase:1"]),
        issue(13, "ALPHA thirteen done", "CLOSED", ["status:done"], created="2026-11-20T03:00:00Z",
              closed="2026-11-20T10:00:00Z", reason="COMPLETED"),  # lead time 7 h
    ])
    write_json(d[FA] / "issues.json", [
        issue(7, "BRAVO seven ready", "OPEN", ["status:ready", "priority:p1", "phase:1"]),
        issue(6, "BRAVO six review", "OPEN", ["status:in-review", "priority:p1", "phase:1"]),
        issue(4, "BRAVO four done", "CLOSED", ["status:done"], created="2026-11-19T01:00:00Z",
              closed="2026-11-19T20:00:00Z", reason="COMPLETED"),  # lead time 19 h
        issue(5, "BRAVO five done", "CLOSED", ["status:done"], created="2026-11-20T01:00:00Z",
              closed="2026-11-20T20:00:00Z", reason="COMPLETED"),
        issue(9, "BRAVO nine done", "CLOSED", ["status:done"], created="2026-11-21T01:00:00Z",
              closed="2026-11-21T20:00:00Z", reason="COMPLETED"),
    ])
    if fa_extra_open:   # factory gets more open issues than the host, so the two repositories and the total all differ
        extra = [issue(20 + k, f"BRAVO extra {k} ready", "OPEN", ["status:ready", "priority:p2", "phase:1"])
                 for k in range(fa_extra_open)]
        write_json(d[FA] / "issues.json", json.loads((d[FA] / "issues.json").read_text(encoding="utf-8")) + extra)
    write_json(d[CH] / "issues.json", [
        issue(3, "CHARLIE three ready", "OPEN", ["status:ready", "priority:p1", "phase:1"]),
    ])
    write_json(d[LF] / "prs.json", [pr(20, "ALPHA open pr", "OPEN"), pr(21, "ALPHA merged pr", "MERGED", "2026-11-13T09:00:00Z")])
    write_json(d[FA] / "prs.json", [pr(31, "BRAVO open pr", "OPEN"), pr(30, "BRAVO merged pr", "MERGED", "2026-11-14T09:00:00Z")])
    write_json(d[CH] / "prs.json", [pr(40, "CHARLIE open pr", "OPEN")])
    write_json(d[LF] / "runs.json", [run("CI", "success", "2026-11-24T10:00:00Z", n=1)])
    write_json(d[FA] / "runs.json", [run("CI", "failure", "2026-11-24T10:00:00Z", n=2)])
    write_json(d[LF] / "comments-11.json", {"comments": [
        claim_comment("lf-winner", "building", "2026-11-24T11:00:00+00:00", "f/11-alpha-branch")]})
    write_json(d[FA] / "comments-6.json", {"comments": [
        claim_comment("fa-reviewer", "waiting for review", "2026-11-24T11:30:00+00:00", "f/6-bravo-branch")]})
    (d[LF] / "DECISIONS.md").write_text(decisions_md([("D1", "ALPHA first decision")]), encoding="utf-8")
    (d[FA] / "DECISIONS.md").write_text(decisions_md([("D1", "BRAVO first decision")]), encoding="utf-8")
    (d[CH] / "DECISIONS.md").write_text(decisions_md([("D1", "CHARLIE first decision")]), encoding="utf-8")
    (d[LF] / "OWNER.md").write_text(owner_md([("O1", "ALPHA owner item")], []), encoding="utf-8")
    (d[FA] / "OWNER.md").write_text(owner_md([("O3", "BRAVO owner item")], []), encoding="utf-8")
    (d[CH] / "OWNER.md").write_text(owner_md([("O5", "CHARLIE owner item")], []), encoding="utf-8")
    for p in d.values():
        (p / "STATE.md").write_text(state_md(), encoding="utf-8")
    repos = root / "repos.yaml"
    listed = [LF, FA, CH] if with_third else [LF, FA]
    repos.write_text("".join(f"- repo: {r}\n  note: ignored\n" for r in listed), encoding="utf-8")
    return repos, fx


def build_world(root: Path, with_third: bool = False, fa_extra_open: int = 0):
    repos, fx = make_world(root, with_third, fa_extra_open)
    out = root / "site"
    cwd = root / "cwd"
    cwd.mkdir()
    p = build(cwd, repos, out, fx)
    assert p.returncode == 0, p.stdout + p.stderr
    return out, json.loads((out / "snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world2(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("w2"))


@pytest.fixture(scope="module")
def world_counts(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("wc"), fa_extra_open=2)


@pytest.fixture(scope="module")
def world3(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("w3"), with_third=True)


def live(state: str = "running", repos: tuple[str, ...] = (LF, FA, CH)) -> dict:
    runner = {"state": state}
    if state == "running":
        runner.update({"pass_no": 24, "budget": 40})
    rows = {LF: [(7, "ALPHA seven lane", "build"), (11, "ALPHA eleven lane", "check")],
            FA: [(7, "BRAVO seven lane", "exam"), (6, "BRAVO six lane", "check")],
            CH: [(3, "CHARLIE three lane", "plan")]}
    return {"generated_at": "2026-11-24T11:59:30+00:00", "schema": 1, "runner": runner,
            "issues": [{"issue": n, "repo": r, "title": t, "station": s} for r in repos for n, t, s in rows[r]],
            "agents": [], "workers": [], "crew": [], "log": []}


def shared_live(repos: tuple[str, ...] = (LF, FA)) -> dict:
    """live.json whose agents, log and crew hold entries of both repositories, in the builder's real shapes:
    the host's entries carry repo "", another repository's its full name; a crew node's title starts with
    its repository's short name ("factory#7 ...") or with a bare "#11" for the host."""
    d = live("running", repos)
    t0, t1 = "2026-11-24T11:50:00+00:00", "2026-11-24T11:59:00+00:00"

    def sub(name, n, repo, tag, at):
        return {"station": "build", "substep": f"{tag} {name}", "status": "done", "issue": n, "repo": repo,
                "started": t0, "at": at, "detail": f"{tag} detail {name}"}

    d["agents"] = [{
        "id": "agent-mixed", "role": "implementer", "issue": 11, "repo": "", "station": "build", "state": "running",
        "started": t0, "last": t1,
        "substeps": [sub("one", 11, "", "ALPHA", "2026-11-24T11:52:00+00:00"),
                     sub("one", 7, FA, "BRAVO", "2026-11-24T11:54:00+00:00"),
                     sub("two", 11, "", "ALPHA", "2026-11-24T11:56:00+00:00"),
                     sub("two", 6, FA, "BRAVO", "2026-11-24T11:58:00+00:00")],
    }]

    def row(n, repo, tag, k):
        return {"at": f"2026-11-24T11:5{k}:00+00:00", "issue": n, "repo": repo, "agent": "agent-mixed",
                "role": "implementer", "station": "build", "substep": f"step {k}", "status": "done",
                "detail": f"{tag} log row {k}"}

    d["log"] = [row(11, "", "ALPHA", 1), row(7, FA, "BRAVO", 2), row(11, "", "ALPHA", 3), row(6, FA, "BRAVO", 4),
                {"at": "2026-11-24T11:55:00+00:00", "issue": None, "repo": "", "agent": "manager", "role": "manager",
                 "station": "plan", "substep": "pass start", "status": "done", "detail": "SHARED log row"}]

    def node(i, title, type_="implementer", kind="agent"):
        return {"id": i, "kind": kind, "type": type_, "title": title, "state": "busy", "model": "m",
                "started": t0, "last": t1, "children": []}

    root = node("c0", "manager pass 24", "manager", "session")
    root["children"] = [node("c1", "#11 ALPHA crew bare"), node("c2", "Learning_factory#11 ALPHA crew prefixed"),
                        node("c3", "factory#7 BRAVO crew prefixed")]
    d["crew"] = [root]
    return d


# ---- page runner and DOM helpers ------------------------------------------------------------------------

def run_page(tmp_path: Path, snapshot: dict, steps: list[dict], hash_: str = "") -> list[dict]:
    node = shutil.which("node")
    assert node, "node is required for the page exam"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": NOW, "hash": hash_, "snapshot": snapshot, "steps": steps}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(STATIC / "index.html"), str(STATIC / "app.js"), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])["steps"]
    for s in out:
        assert not [e for e in s["errors"] if not e.startswith("no tab")], s["errors"]
    return out


def view(tmp_path, snap, hash_="", state="running", click=None, repos=(LF, FA, CH)) -> dict:
    step = {"now": NOW, "live": live(state, repos)}
    if click:
        step["clicks"] = [{"tab": click}]
    return run_page(tmp_path, snap, [step], hash_)[0]


def walk(n, path=()):
    if isinstance(n, str):
        return
    yield n, path
    for c in n["c"]:
        yield from walk(c, (*path, n))


def text(n, skip=lambda n: False) -> str:
    if isinstance(n, str):
        return n
    if skip(n):
        return ""
    return " ".join(text(c, skip) for c in n["c"])


def is_bar(n) -> bool:
    return n["t"] == "nav" or n["a"].get("role") == "tablist"


def bars(page):
    return [n for n, _ in walk(page) if is_bar(n)]


def tabs_of(page) -> list[dict]:
    found = []
    for bar in bars(page):
        for n, _ in walk(bar):
            if n["t"] in ("a", "button") or n["a"].get("role") == "tab":
                if n not in found:
                    found.append(n)
    assert found, "no top bar: expected a <nav> (or role=tablist) holding one tab per repository"
    return found


def words(s: str) -> set[str]:
    return set(re.findall(r"[\w.-]+", s))


def selected(page) -> list[str]:
    """Short names of the tabs marked aria-current."""
    out = []
    for t in tabs_of(page):
        v = t["a"].get("aria-current")
        if v is not None and v != "false":
            out.append(next(w for w in re.findall(r"[\w.-]+", text(t)) if w in SHORT.values()))
    return out


def tab_names(page) -> list[str]:
    return [next(w for w in re.findall(r"[\w.-]+", text(t)) if w in SHORT.values()) for t in tabs_of(page)]


def body_outside_bar(page) -> str:
    return text(page, is_bar)


def bar_text(page) -> str:
    """Everything outside <main>: the header and the nav."""
    return text(page, lambda n: n["t"] == "main")


def main_text(page) -> str:
    return " ".join(text(n) for n, _ in walk(page) if n["t"] == "main")


def assert_only(page, repo: str, others: tuple[str, ...]):
    outside = body_outside_bar(page)
    assert selected(page) == [SHORT[repo]], f"selected tab: {selected(page)}"
    for need in own_needles(repo):
        assert need in outside, f"{need!r} missing from the {SHORT[repo]} view"
    for other in others:
        assert TOKEN_OF[other] not in outside, f"{TOKEN_OF[other]} rows of {SHORT[other]} show in the {SHORT[repo]} view"


def own_needles(repo: str) -> list[str]:
    t = TOKEN_OF[repo]
    if repo == CH:
        return [f"{t} three ready", f"{t} three lane", f"{t} open pr", f"{t} owner item", f"{t} first decision"]
    n = {LF: (7, 11), FA: (7, 6)}[repo]
    return [f"{t} seven ready", f"{t} seven lane", f"{t} open pr", f"{t} owner item", f"{t} first decision",
            f"{t} {'eleven' if repo == LF else 'six'} lane", f"{t} merged pr", str(n[1])]


# ---- criterion 1: one tab per repository --------------------------------------------------------------

def test_c1_bar_has_one_tab_per_repository_in_data_order(world2, tmp_path):
    page = view(tmp_path, world2[1], repos=(LF, FA))["page"]
    assert tab_names(page) == ["Learning_factory", "factory"]


def test_c1_selected_tab_is_marked_with_aria_current_and_only_one(world2, tmp_path):
    page = view(tmp_path, world2[1], repos=(LF, FA))["page"]
    assert selected(page) == ["Learning_factory"]


def test_c1_each_tab_carries_a_small_count(world2, tmp_path):
    page = view(tmp_path, world2[1], repos=(LF, FA))["page"]
    for t in tabs_of(page):
        assert re.search(r"\d", text(t)), f"no count in the tab {text(t)!r}"


def test_c1_clicking_a_tab_moves_the_selection(world2, tmp_path):
    step = view(tmp_path, world2[1], click="factory", repos=(LF, FA))
    assert selected(step["page"]) == ["factory"]


# ---- criterion 1 (scope): every block shows only the selected repository --------------------------------

def test_c2_host_view_shows_only_host_rows_in_every_block(world2, tmp_path):
    page = view(tmp_path, world2[1], repos=(LF, FA))["page"]
    assert_only(page, LF, (FA,))


def test_c2_selecting_a_repository_shows_only_its_rows_in_every_block(world2, tmp_path):
    page = view(tmp_path, world2[1], click="factory", repos=(LF, FA))["page"]
    assert_only(page, FA, (LF,))


def test_c2_selecting_back_to_the_first_repository_drops_the_other_rows(world2, tmp_path):
    steps = [{"now": NOW, "live": live(repos=(LF, FA)), "clicks": [{"tab": "factory"}]},
             {"now": NOW, "live": live(repos=(LF, FA)), "clicks": [{"tab": "Learning_factory"}]}]
    page = run_page(tmp_path, world2[1], steps)[1]["page"]
    assert_only(page, LF, (FA,))


def test_c2_pipeline_claim_is_the_selected_repositorys(world2, tmp_path):
    lf = body_outside_bar(view(tmp_path, world2[1], repos=(LF, FA))["page"])
    assert "f/11-alpha-branch" in lf and "bravo-branch" not in lf
    fa = body_outside_bar(view(tmp_path, world2[1], click="factory", repos=(LF, FA))["page"])
    assert "f/6-bravo-branch" in fa and "alpha-branch" not in fa


def test_c2_health_shows_only_the_selected_repositorys_runs(world2, tmp_path):
    lf = body_outside_bar(view(tmp_path, world2[1], repos=(LF, FA))["page"])
    assert "success" in lf and "failure" not in lf
    fa = body_outside_bar(view(tmp_path, world2[1], click="factory", repos=(LF, FA))["page"])
    assert "failure" in fa and "success" not in fa


def test_c2_throughput_is_the_selected_repositorys(world2, tmp_path):
    lf = body_outside_bar(view(tmp_path, world2[1], repos=(LF, FA))["page"])
    assert re.search(r"(?<![\d.])7(\.0)? h\b", lf), "Learning_factory's median lead time is 7 h"
    assert not re.search(r"(?<![\d.])19(\.0)? h\b", lf), "factory's lead time (19 h) leaks into the other view"
    fa = body_outside_bar(view(tmp_path, world2[1], click="factory", repos=(LF, FA))["page"])
    assert re.search(r"(?<![\d.])19(\.0)? h\b", fa)
    assert not re.search(r"(?<![\d.])7(\.0)? h\b", fa)


def test_c2_the_counts_card_does_not_list_the_other_repository(world2, tmp_path):
    page = view(tmp_path, world2[1], click="factory", repos=(LF, FA))["page"]
    assert "Learning_factory" not in words(body_outside_bar(page)), "another repository's name outside the bar"


# ---- criterion 1 (address) ------------------------------------------------------------------------------

def test_c3_no_address_opens_the_host_repository(world2, tmp_path):
    page = view(tmp_path, world2[1], hash_="", repos=(LF, FA))["page"]
    assert selected(page) == ["Learning_factory"]


def test_c3_the_hash_address_opens_that_repository_directly(world2, tmp_path):
    page = view(tmp_path, world2[1], hash_="#/factory", repos=(LF, FA))["page"]
    assert_only(page, FA, (LF,))


def test_c3_the_host_address_opens_the_host(world2, tmp_path):
    page = view(tmp_path, world2[1], hash_="#/Learning_factory", repos=(LF, FA))["page"]
    assert_only(page, LF, (FA,))


def test_c3_an_unknown_name_falls_back_to_the_host(world2, tmp_path):
    step = view(tmp_path, world2[1], hash_="#/no-such-repo", repos=(LF, FA))
    assert_only(step["page"], LF, (FA,))


def test_c3_selecting_a_tab_changes_the_address_and_a_reload_keeps_it(world2, tmp_path):
    first = view(tmp_path, world2[1], click="factory", repos=(LF, FA))
    assert first["hash"] == "#/factory", f"address after selecting factory: {first['hash']!r}"
    (tmp_path / "again").mkdir()
    reloaded = view(tmp_path / "again", world2[1], hash_=first["hash"], repos=(LF, FA))
    assert_only(reloaded["page"], FA, (LF,))


def test_c3_back_returns_to_the_previous_repository(world2, tmp_path):
    steps = [{"now": NOW, "live": live(repos=(LF, FA)), "clicks": [{"tab": "factory"}]},
             {"now": NOW, "live": live(repos=(LF, FA)), "back": True}]
    out = run_page(tmp_path, world2[1], steps)
    assert selected(out[0]["page"]) == ["factory"]
    assert_only(out[1]["page"], LF, (FA,))


# ---- criterion 2: the runner is in the bar on every view -----------------------------------------------

@pytest.mark.parametrize("click", [None, "factory"])
def test_c4_runner_running_pass_and_last_check_are_in_the_bar_on_every_view(world2, tmp_path, click):
    page = view(tmp_path, world2[1], click=click, repos=(LF, FA))["page"]
    bar = bar_text(page)
    assert re.search(r"running", bar, re.I), f"no runner state outside <main>: {bar!r}"
    assert re.search(r"pass\s+24", bar, re.I), f"no pass number outside <main>: {bar!r}"
    assert re.search(r"\d+\s*(s|sec|secs|seconds|min|mins|minutes|h)\b|just now|ago", bar, re.I), \
        f"no last-check age outside <main>: {bar!r}"


@pytest.mark.parametrize("click", [None, "factory"])
def test_c4_an_idle_runner_shows_idle_in_the_bar_on_every_view(world2, tmp_path, click):
    page = view(tmp_path, world2[1], state="idle", click=click, repos=(LF, FA))["page"]
    bar = bar_text(page)
    assert re.search(r"idle", bar, re.I), f"no idle state outside <main>: {bar!r}"
    assert not re.search(r"pass\s+24", bar, re.I)


# ---- criterion 3: data-driven ---------------------------------------------------------------------------

def test_c5_a_third_repository_in_the_data_appears_in_the_bar(world3, tmp_path):
    page = view(tmp_path, world3[1])["page"]
    assert tab_names(page) == ["Learning_factory", "factory", "charlie"]
    assert selected(page) == ["Learning_factory"]
    for t in tabs_of(page):
        assert re.search(r"\d", text(t))


def test_c5_the_third_repository_opens_by_tab_and_by_address_with_only_its_rows(world3, tmp_path):
    clicked = view(tmp_path, world3[1], click="charlie")
    assert_only(clicked["page"], CH, (LF, FA))
    assert clicked["hash"] == "#/charlie"
    (tmp_path / "again").mkdir()
    direct = view(tmp_path / "again", world3[1], hash_="#/charlie")
    assert_only(direct["page"], CH, (LF, FA))


def test_c5_the_page_code_names_no_repository(world3):
    for name in ("index.html", "app.js"):
        src = (STATIC / name).read_text(encoding="utf-8").lower()
        assert "charlie" not in src, f"{name} names a repository"


# ---- rows drop the repository prefix --------------------------------------------------------------------

@pytest.mark.parametrize("click,repo", [(None, LF), ("factory", FA)])
def test_c6_rows_inside_a_repository_view_show_the_number_not_the_prefixed_one(world2, tmp_path, click, repo):
    page = view(tmp_path, world2[1], click=click, repos=(LF, FA))["page"]
    outside = body_outside_bar(page)
    assert not re.findall(r"[A-Za-z_][\w-]*#\d+", outside), \
        f"prefixed rows in the {SHORT[repo]} view: {re.findall(r'[A-Za-z_][\w-]*#[0-9]+', outside)}"
    own = {LF: (7, 11, 20, 21), FA: (7, 6, 31, 30)}[repo]
    for n in own:
        assert re.search(rf"(?<![\w#])#{n}(?!\d)", outside), f"#{n} missing from the {SHORT[repo]} view"


# ---- criterion 4: phone width ---------------------------------------------------------------------------

def css_rules() -> list[tuple[list[str], str]]:
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "styles.css").read_text(encoding="utf-8"), flags=re.S)
    return [([s.strip() for s in m.group(1).split(",")], m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css) if not m.group(1).strip().startswith("@")]


def matches(el, selector: str) -> bool:
    last = re.split(r"[\s>+~]+", selector.strip())[-1]
    if not last or ":" in last:
        return False
    classes = (el["a"].get("class") or "").split()
    for part in re.findall(r"[#.]?[\w-]+|\*", last):
        if part == "*":
            continue
        if part[0] == "#":
            if el["a"].get("id") != part[1:]:
                return False
        elif part[0] == ".":
            if part[1:] not in classes:
                return False
        elif el["t"] != part.lower():
            return False
    return True


def decls_for(el) -> list[str]:
    return [d.lower() for sels, d in css_rules() if any(matches(el, s) for s in sels)]


def test_c7_at_390px_the_bar_scrolls_or_wraps_and_nothing_fixes_a_wide_width(world2, tmp_path):
    page = view(tmp_path, world2[1], repos=(LF, FA))["page"]
    tab = tabs_of(page)[0]
    bar = bars(page)[0]
    chain = None
    for n, path in walk(page):
        if n is tab:
            chain = [p for p in (*path, n)]
    assert chain
    row_chain = [n for n in chain[chain.index(bar):][::-1]]   # the tab's parent up to the bar, inclusive
    row_chain = [n for n in row_chain if n is not tab]
    ok = False
    for el in row_chain:
        for d in decls_for(el):
            if re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", d) or re.search(r"flex-wrap\s*:\s*wrap", d):
                ok = True
    assert ok, "the tab row needs overflow-x: auto|scroll or flex-wrap: wrap so 390 px does not scroll the page sideways"
    guarded = [n for n, _ in walk(page) if n["t"] in ("html", "body", "header", "nav", "main")] + row_chain
    for el in guarded:
        for d in decls_for(el):
            for m in re.finditer(r"(?<![\w-])(min-width|width)\s*:\s*(\d+(?:\.\d+)?)px", d):
                assert float(m.group(2)) <= 390, f"{el['t']} has a fixed {m.group(1)} of {m.group(2)}px"
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<meta[^>]+name="viewport"[^>]+width=device-width', html)


# ---- criterion 5: LF D14 privacy on the built output ----------------------------------------------------

def all_files(out: Path) -> list[Path]:
    return sorted(p for p in out.rglob("*") if p.is_file())


def test_c8_built_files_are_only_the_snapshot_and_the_page(world2):
    out = world2[0]
    names = {p.relative_to(out).as_posix() for p in all_files(out)}
    assert names == {"snapshot.json", *PAGE_FILES}, names


def test_c8_no_state_text_email_or_token_in_any_built_file(world2):
    out, snap = world2
    assert "state" not in snap
    for p in all_files(out):
        data = p.read_text(encoding="utf-8", errors="replace")
        assert STATE_TEXT not in data, f"STATE text in {p.name}"
        for needle in (*EMAILS, *TOKENS):
            assert needle not in data, f"a seeded value leaked into {p.name}"
        assert not TOKEN_RE.findall(data), f"token-shaped string in {p.name}"
    assert not EMAIL_RE.findall((out / "snapshot.json").read_text(encoding="utf-8"))


def test_c8_the_snapshot_carries_no_field_the_page_does_not_show(world2):
    forbidden = {"body", "author", "email", "contact", "key", "labels", "createdAt", "closedAt", "actor",
                 "headRefName", "isDraft", "databaseId", "worktree"}
    seen: set[str] = set()

    def keys(n):
        if isinstance(n, dict):
            for k, v in n.items():
                seen.add(k)
                keys(v)
        elif isinstance(n, list):
            for v in n:
                keys(v)

    keys(world2[1])
    assert not (seen & forbidden), sorted(seen & forbidden)


def test_c8_every_repository_view_renders_without_unsafe_markup_or_leaks(world2, tmp_path):
    for click in (None, "factory"):
        step = view(tmp_path, world2[1], click=click, repos=(LF, FA))
        assert step["innerHTML"] == [] and step["style_attr"] == []
        page_text = text(step["page"])
        assert STATE_TEXT not in page_text and not EMAIL_RE.findall(page_text) and not TOKEN_RE.findall(page_text)


# ---- review round 1: malformed addresses, shared live data, per-repository counts, a thin entry ----------

@pytest.mark.parametrize("bad", ["#/%", "#/%E0%A4%A", "#/%zz", "#/%25%"])
def test_r1_a_malformed_address_opens_the_host_repository(world2, tmp_path, bad):
    # a link cut in the middle of an escape makes decodeURIComponent throw: the page must still open the host
    step = view(tmp_path, world2[1], hash_=bad, repos=(LF, FA))
    assert tab_names(step["page"]) == ["Learning_factory", "factory"], "the bar has its tabs"
    assert_only(step["page"], LF, (FA,))


def test_r1_a_malformed_address_still_lets_the_other_tab_be_selected(world2, tmp_path):
    step = view(tmp_path, world2[1], hash_="#/%E0%A4%A", click="factory", repos=(LF, FA))
    assert_only(step["page"], FA, (LF,))


def view_shared(tmp_path, snap, hash_="", click=None) -> dict:
    step = {"now": NOW, "live": shared_live()}
    if click:
        step["clicks"] = [{"tab": click}]
    return run_page(tmp_path, snap, [step], hash_)[0]


def test_r1_the_host_view_shows_only_the_hosts_agent_steps_log_rows_and_crew_nodes(world2, tmp_path):
    page = view_shared(tmp_path, world2[1])["page"]
    main = main_text(page)
    assert_only(page, LF, (FA,))
    for need in ("ALPHA one", "ALPHA two", "ALPHA detail one", "ALPHA log row 1", "ALPHA log row 3",
                 "ALPHA crew bare", "ALPHA crew prefixed", "SHARED log row"):
        assert need in main, f"{need!r} missing from the Learning_factory Live block"
    leaks = re.findall(r"BRAVO[ \w]*", main)
    assert not leaks, f"factory's entries show in the Learning_factory view: {leaks[:6]}"


def test_r1_the_other_repositorys_view_shows_only_its_own_agent_steps_log_rows_and_crew_nodes(world2, tmp_path):
    page = view_shared(tmp_path, world2[1], click="factory")["page"]
    main = main_text(page)
    assert_only(page, FA, (LF,))
    for need in ("BRAVO one", "BRAVO two", "BRAVO detail one", "BRAVO log row 2", "BRAVO log row 4",
                 "BRAVO crew prefixed", "SHARED log row"):
        assert need in main, f"{need!r} missing from the factory Live block"
    leaks = re.findall(r"ALPHA[ \w]*", main)
    assert not leaks, f"Learning_factory's entries show in the factory view: {leaks[:6]}"


def counts_line(page) -> tuple[int, int]:
    m = re.search(r"(\d+)\s+open,?\s+(\d+)\s+closed", main_text(page))
    assert m, f"no 'N open, M closed' line in <main>: {main_text(page)[:300]!r}"
    return int(m.group(1)), int(m.group(2))


def test_r1_each_repositorys_counts_line_shows_its_own_open_and_closed(world_counts, tmp_path):
    snap = world_counts[1]
    total = (snap["issues"]["open"], snap["issues"]["closed"])
    assert total == (6, 4), total   # the builder's own data: LF 2 open 1 closed, factory 4 open 3 closed
    lf = counts_line(view(tmp_path, snap, repos=(LF, FA))["page"])
    (tmp_path / "fa").mkdir()
    fa = counts_line(view(tmp_path / "fa", snap, click="factory", repos=(LF, FA))["page"])
    assert lf == (2, 1), f"Learning_factory counts line shows {lf}"
    assert fa == (4, 3), f"factory counts line shows {fa}"


@pytest.mark.parametrize("click", [None, "factory"])
def test_r1_a_repository_entry_without_throughput_still_renders_the_rest(world2, tmp_path, click):
    snap = json.loads(json.dumps(world2[1]))
    for entry in snap["repos"].values():
        entry.pop("throughput", None)
    step = view(tmp_path, snap, click=click, repos=(LF, FA))   # run_page fails on any thrown or swallowed error
    repo, other = (FA, LF) if click else (LF, FA)
    assert_only(step["page"], repo, (other,))
    assert counts_line(step["page"]) == {LF: (2, 1), FA: (2, 3)}[repo]
