"""Issue #6 (D12, D13): the factory dashboard moves into this repository. Factory-side half.

Criteria covered here: 1 (snapshot per repository), 3 (repository tag on the page), 4 (privacy of the
built files). Criteria 2 and 5 belong to Shashkist/Learning_factory#568 and are not tested here.

CONTRACT for the implementer (D13, plus the readings below where D13 is silent)

Entry point, stdlib + PyYAML only:

    python -m factory_tools.dashboard build --repos <repos.yaml> --out <dir> [--fixtures <dir>] [--now <iso>]

* repos.yaml    a list of `- repo: owner/name` (other keys ignored). Order is kept.
* --fixtures    no `gh` call and no network. Everything for repository owner/name is read from
                `<fixtures>/<owner>__<name>/`: issues.json, prs.json, runs.json, comments-<n>.json (the
                shapes LF's builder read), plus DECISIONS.md and OWNER.md. STATE.md is never read.
                A missing file means an empty list or empty text, never an error.
* --out         created if missing. Receives `snapshot.json` and the page files `index.html`, `app.js`,
                `styles.css`, `theme.js`, copied byte for byte from `src/factory_tools/dashboard/static/`.
* --now         the clock (default: the real now). `generated_at` is that instant, ISO 8601.
* Works with no GH_TOKEN, no GITHUB_TOKEN and no `gh` on PATH when --fixtures is given.

snapshot.json keeps LF's keys (generated_at, issues, queue, claim, prs, runs, server, decisions,
owner_open, throughput; `state` is gone) and adds two:
    repos   {"owner/name": {"issues": {open, closed, by_status, by_phase, by_priority}}}   in repos.yaml order
    lanes   [{repo, issue, title}] for every open issue labelled status:in-progress or status:in-review
Every item of queue, lanes, prs.open, prs.merged, decisions and owner_open carries `repo` ("owner/name").
`claim` (null or one claim, LF's rule: first non-released claim comment, in-progress issues before
in-review issues, repositories in repos.yaml order) carries `repo` too. Each run carries `repo`
(`runs` may be nested by repository or by workflow, the exam walks it). Top-level `issues` are the totals
over all repositories; `throughput` is over all repositories.

Page: for every lane (.lane, from live.json `issues`), every `.live-issue` row and every queue row
(`#queue li`) the short repository name (the part after "/") appears as its own word, e.g. `factory#7`
or `Learning_factory#7`.

Fixtures are generated here, fake, with seeded emails and token-shaped strings that must never reach the
output.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from helpers import SRC

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "dashboard" / "dom_harness_6.js"
STATIC = SRC / "factory_tools" / "dashboard" / "static"
PAGE_FILES = ("index.html", "app.js", "styles.css", "theme.js")

LF = "Shashkist/Learning_factory"
FA = "Shashkist/factory"
NOW = "2026-11-24T12:00:00Z"

# Seeded values that must be dropped. Built at run time so no token-shaped literal sits in the repository.
STATE_TEXT = "SEEDED-STATE-TEXT-" + "7c1e"
EMAILS = ["jane.doe" + "@example.com", "ops.team" + "@example.org", "owner.note" + "@example.net"]
TOKENS = ["ghp_" + "Ab3dE6gH9jK2mN5pQ8sT1vX4zC7bF0hJ3kL6", "github_pat_" + "11AB12CD34EF56GH78IJ90_klmnop", "sk-ant-" + "api03-QwErTyUiOpAsDfGhJkLz12"]
TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|gh[ousr]_[A-Za-z0-9]{20,}|sk-ant-[\w-]{16,}|AKIA[0-9A-Z]{16}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")


# ---- fixtures ------------------------------------------------------------------------------------------

def issue(n, title, state, labels, created="2026-11-01T08:00:00Z", closed=None, reason=None):
    d = {
        "number": n, "title": title, "state": state, "labels": [{"name": x} for x in labels],
        "createdAt": created, "closedAt": closed, "url": f"https://github.com/x/y/issues/{n}",
        # fields the page never shows: the builder must not carry them
        "body": f"Please mail {EMAILS[0]}. token {TOKENS[0]}",
        "author": {"login": "someone", "email": EMAILS[1]},
    }
    if reason:
        d["stateReason"] = reason
    return d


def pr(n, title, state, merged=None):
    return {"number": n, "title": title, "state": state, "url": f"https://github.com/x/y/pull/{n}",
            "mergedAt": merged, "headRefName": f"f/{n}-x", "isDraft": False,
            "body": f"see {TOKENS[1]} and {EMAILS[2]}"}


def run(workflow, conclusion, created, branch="main", n=1):
    return {"databaseId": n, "workflowName": workflow, "status": "completed", "conclusion": conclusion,
            "headBranch": branch, "createdAt": created, "url": f"https://github.com/x/y/actions/runs/{n}",
            "actor": {"login": "bot", "email": EMAILS[0]}}


def claim_comment(session, step, heartbeat, branch, released=False):
    if released:
        data = {"released": "2026-11-24T09:00:00+00:00", "by": session, "reason": "lost the race"}
    else:
        data = {"branch": branch, "claimed": "2026-11-24T07:00:00+00:00", "heartbeat": heartbeat,
                "session": session, "step": step, "worktree": "", "contact": EMAILS[1], "key": TOKENS[2]}
    body = "<!-- pulsesign-issue-claim\n" + json.dumps(data, indent=2) + "\n-->\nclaim comment\n"
    return {"id": "IC_1", "author": {"login": "someone", "email": EMAILS[0]}, "body": body,
            "createdAt": "2026-11-24T08:00:00Z", "url": "https://github.com/x/y/issues/1#issuecomment-1"}


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def state_md() -> str:
    return f"# State\n\n## Now\n\n{STATE_TEXT} building something secret-ish\n\n## Next (in order)\n\n{STATE_TEXT} next\n\n## Health\n\n{STATE_TEXT} health\n"


def decisions_md(items: list[tuple[str, str]]) -> str:
    out = "# Decisions\n\nIntro text.\n\n"
    for i, t in items:
        out += f"## {i} · {t}\nin force · owner · 2026-11-20\n\n**Decision.** Mail {EMAILS[2]} or use {TOKENS[0]}.\n\n"
    return out


def owner_md(open_items: list[tuple[str, str]], done: list[tuple[str, str]]) -> str:
    out = "# Owner\n\n"
    for i, t in open_items:
        out += f"- [ ] **{i} · {t}.** Contact {EMAILS[1]} with {TOKENS[2]}.\n"
    for i, t in done:
        out += f"- [x] **{i} · {t}.** done\n"
    return out


def make_fixtures(root: Path) -> tuple[Path, Path]:
    """Two repositories, issue number 7 ready in both. Returns (repos.yaml, fixtures dir)."""
    fx = root / "fx"
    lf = fx / LF.replace("/", "__")
    fa = fx / FA.replace("/", "__")
    lf.mkdir(parents=True)
    fa.mkdir(parents=True)
    write_json(lf / "issues.json", [
        issue(7, "LF seven ready", "OPEN", ["status:ready", "priority:p1", "phase:1"]),
        issue(11, "LF eleven working", "OPEN", ["status:in-progress", "priority:p2", "phase:1"]),
        issue(12, "LF twelve blocked", "OPEN", ["status:blocked", "priority:p3", "phase:2"]),
        issue(13, "LF thirteen done", "CLOSED", ["status:done"], closed="2026-11-12T10:00:00Z", reason="COMPLETED"),
    ])
    write_json(fa / "issues.json", [
        issue(6, "Factory six dashboard", "OPEN", ["status:in-review", "priority:p1", "phase:1"]),
        issue(7, "Factory seven ready", "OPEN", ["status:ready", "priority:p1", "phase:1"]),
        issue(8, "Factory eight ready", "OPEN", ["status:ready", "priority:p2", "phase:1"]),
        issue(4, "Factory four done", "CLOSED", ["status:done"], closed="2026-11-13T10:00:00Z", reason="COMPLETED"),
        issue(5, "Factory five old", "CLOSED", ["status:done"], closed="2026-10-01T10:00:00Z", reason="COMPLETED"),
    ])
    write_json(lf / "prs.json", [
        pr(20, "LF open pr", "OPEN"),
        pr(21, "LF merged pr", "MERGED", "2026-11-13T09:00:00Z"),
    ])
    write_json(fa / "prs.json", [
        pr(30, "Factory merged pr", "MERGED", "2026-11-14T09:00:00Z"),
        pr(31, "Factory closed pr", "CLOSED"),
    ])
    write_json(lf / "runs.json", [
        run("CI", "success", "2026-11-24T10:00:00Z", n=1),
        run("CI", "failure", "2026-11-24T11:00:00Z", branch="f/11-x", n=2),
        run("Deploy", "success", "2026-11-24T10:30:00Z", n=3),
    ])
    write_json(fa / "runs.json", [run("CI", "failure", "2026-11-24T10:00:00Z", n=4)])
    write_json(lf / "comments-11.json", {"comments": [
        claim_comment("lf-loser", "x", "2026-11-24T10:00:00+00:00", "f/11-a", released=True),
        claim_comment("lf-winner", "building", "2026-11-24T11:00:00+00:00", "f/11-lf"),
    ]})
    write_json(fa / "comments-6.json", {"comments": [
        claim_comment("fa-reviewer", "waiting for review", "2026-11-24T11:30:00+00:00", "f/6-dashboard")]})
    (lf / "DECISIONS.md").write_text(decisions_md([("D1", "LF first decision"), ("D2", "LF second decision")]), encoding="utf-8")
    (fa / "DECISIONS.md").write_text(decisions_md([("D1", "Factory first decision")]), encoding="utf-8")
    (lf / "OWNER.md").write_text(owner_md([("O1", "LF owner item")], [("O2", "LF finished item")]), encoding="utf-8")
    (fa / "OWNER.md").write_text(owner_md([("O3", "Factory owner item")], []), encoding="utf-8")
    (lf / "STATE.md").write_text(state_md(), encoding="utf-8")
    (fa / "STATE.md").write_text(state_md(), encoding="utf-8")
    repos = root / "repos.yaml"
    repos.write_text(f"- repo: {LF}\n  profile: lf\n  track: main\n- repo: {FA}\n  note: other keys are ignored\n", encoding="utf-8")
    return repos, fx


def bare_env() -> dict[str, str]:
    """An environment with no token, no gh, nothing but what Python needs to start."""
    e = {"PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8", "PATH": ""}
    for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "HOME"):
        if k in os.environ:
            e[k] = os.environ[k]
    return e


def build(cwd: Path, repos: Path, out: Path, fixtures: Path | None, now: str | None = NOW):
    args = [sys.executable, "-m", "factory_tools.dashboard", "build", "--repos", str(repos), "--out", str(out)]
    if fixtures is not None:
        args += ["--fixtures", str(fixtures)]
    if now:
        args += ["--now", now]
    return subprocess.run(args, cwd=cwd, env=bare_env(), capture_output=True, text=True, encoding="utf-8", timeout=120)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("dash")
    repos, fx = make_fixtures(root)
    out = root / "site"
    cwd = root / "cwd"  # not the repository: nothing may be read relative to the working directory
    cwd.mkdir()
    p = build(cwd, repos, out, fx)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (out / "snapshot.json").is_file(), "the build wrote no snapshot.json"
    return out, json.loads((out / "snapshot.json").read_text(encoding="utf-8")), (repos, fx, root)


def items_of(snap, key):
    got = snap[key]
    assert isinstance(got, list), f"{key} must be a list of repo-tagged items"
    return got


def walk_runs(node, repo_hint=None):
    """Every run dict (has 'conclusion') under snapshot['runs'], whatever the nesting."""
    if isinstance(node, dict):
        if "conclusion" in node:
            yield node
        else:
            for v in node.values():
                yield from walk_runs(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_runs(v)


# ---- criterion 1: the builder, two repositories --------------------------------------------------------

def test_c1_build_entry_point_writes_snapshot_and_page_files(built):
    out, _, _ = built
    for name in ("snapshot.json", *PAGE_FILES):
        assert (out / name).is_file(), f"{name} missing from the output"


def test_c1_generated_at_is_the_given_now(built):
    snap = built[1]
    got = datetime.fromisoformat(snap["generated_at"].replace("Z", "+00:00"))
    assert got == datetime.fromisoformat("2026-11-24T12:00:00+00:00")


def test_c1_repos_lists_each_repository_in_repos_yaml_order(built):
    assert list(built[1]["repos"]) == [LF, FA]


def test_c1_counts_per_repository(built):
    repos = built[1]["repos"]
    assert repos[LF]["issues"] == {
        "open": 3, "closed": 1,
        "by_status": {"ready": 1, "in-progress": 1, "blocked": 1},
        "by_phase": {"1": 2, "2": 1},
        "by_priority": {"p1": 1, "p2": 1, "p3": 1},
    }
    assert repos[FA]["issues"] == {
        "open": 3, "closed": 2,
        "by_status": {"in-review": 1, "ready": 2},
        "by_phase": {"1": 3},
        "by_priority": {"p1": 2, "p2": 1},
    }


def test_c1_top_level_issue_counts_are_the_totals(built):
    issues = built[1]["issues"]
    assert issues["open"] == 6 and issues["closed"] == 3
    assert issues["by_status"] == {"ready": 3, "in-progress": 1, "in-review": 1, "blocked": 1}
    assert issues["by_priority"] == {"p1": 3, "p2": 2, "p3": 1}
    assert issues["by_phase"] == {"1": 5, "2": 1}


def test_c1_queue_rows_carry_their_repository_and_keep_the_same_number_apart(built):
    queue = items_of(built[1], "queue")
    got = [(q["repo"], q["number"], q["priority"]) for q in queue]
    assert sorted(got) == sorted([(LF, 7, "p1"), (FA, 7, "p1"), (FA, 8, "p2")])
    assert [q["priority"] for q in queue] == ["p1", "p1", "p2"], "highest priority first"
    assert {q["title"] for q in queue if q["number"] == 7} == {"LF seven ready", "Factory seven ready"}


def test_c1_lanes_per_repository(built):
    lanes = items_of(built[1], "lanes")
    assert sorted((lane["repo"], lane["issue"]) for lane in lanes) == sorted([(LF, 11), (FA, 6)])
    assert {lane["title"] for lane in lanes} == {"LF eleven working", "Factory six dashboard"}


def test_c1_claim_comes_from_the_repository_of_the_in_progress_issue(built):
    claim = built[1]["claim"]
    assert claim is not None
    assert (claim["repo"], claim["issue"]) == (LF, 11)
    assert claim["session"] == "lf-winner", "a released claim comment must be skipped"
    assert claim["branch"] == "f/11-lf"


def test_c1_pull_requests_are_tagged_and_merged_newest_first(built):
    prs = built[1]["prs"]
    assert [(p["repo"], p["number"]) for p in prs["open"]] == [(LF, 20)]
    assert [(p["repo"], p["number"]) for p in prs["merged"]] == [(FA, 30), (LF, 21)]
    assert all(p["merged_at"] for p in prs["merged"])
    everything = json.dumps(prs)
    assert "Factory closed pr" not in everything, "a closed, unmerged PR appears nowhere"


def test_c1_runs_are_tagged_and_only_main_counts(built):
    # the workflow name may be the key of the nesting rather than a field: compare conclusions per repo
    by_repo: dict[str, list[str]] = {}
    for r in walk_runs(built[1]["runs"]):
        by_repo.setdefault(r["repo"], []).append(r["conclusion"])
    assert sorted(by_repo[LF]) == ["success", "success"], "LF: latest main CI and Deploy; the branch failure is ignored"
    assert by_repo[FA] == ["failure"]


def test_c1_decisions_and_owner_items_are_tagged(built):
    snap = built[1]
    dec = [(d["repo"], d["id"], d["title"]) for d in items_of(snap, "decisions")]
    assert sorted(dec) == sorted([(LF, "D1", "LF first decision"), (LF, "D2", "LF second decision"),
                                  (FA, "D1", "Factory first decision")])
    own = [(o["repo"], o["id"], o["title"]) for o in items_of(snap, "owner_open")]
    assert sorted(own) == sorted([(LF, "O1", "LF owner item"), (FA, "O3", "Factory owner item")]), \
        "checked items are omitted, the trailing dot of the bold title is dropped"


def test_c1_throughput_covers_both_repositories(built):
    t = built[1]["throughput"]
    assert len(t["closed_per_day"]) == 14
    assert sum(t["closed_per_day"]) == 2, "LF #13 and factory #4 closed in the window, factory #5 did not"
    assert t["closed_per_day"][1] == 1 and t["closed_per_day"][2] == 1, "oldest first; the last day is the UTC date of --now"
    assert t["open_incidents"] == 0


def test_c1_repos_yaml_extra_keys_are_ignored_and_missing_files_are_empty(tmp_path):
    fx = tmp_path / "fx"
    (fx / "Shashkist__empty").mkdir(parents=True)
    repos = tmp_path / "repos.yaml"
    repos.write_text("- repo: Shashkist/empty\n  anything: [1, 2]\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    p = build(cwd, repos, tmp_path / "site", fx)
    assert p.returncode == 0, p.stdout + p.stderr
    snap = json.loads((tmp_path / "site" / "snapshot.json").read_text(encoding="utf-8"))
    assert snap["repos"]["Shashkist/empty"]["issues"]["open"] == 0
    assert snap["queue"] == [] and snap["claim"] is None and snap["lanes"] == []


def test_c1_same_inputs_give_the_same_snapshot(built, tmp_path):
    out, _, (repos, fx, _) = built
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    p = build(cwd, repos, tmp_path / "again", fx)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (tmp_path / "again" / "snapshot.json").read_bytes() == (out / "snapshot.json").read_bytes()


# ---- the entry point needs no secret -------------------------------------------------------------------

def test_build_runs_with_fixtures_and_an_empty_environment(tmp_path):
    repos, fx = make_fixtures(tmp_path)
    env = bare_env()
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"} & set(env)
    assert env["PATH"] == "", "no gh can be found: fixtures mode must not call it"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    p = build(cwd, repos, tmp_path / "site", fx)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Traceback" not in p.stderr
    assert (tmp_path / "site" / "snapshot.json").is_file() and (tmp_path / "site" / "index.html").is_file()


def test_build_creates_the_out_directory_and_leaves_no_state_file_behind(tmp_path):
    repos, fx = make_fixtures(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    out = tmp_path / "deep" / "er" / "site"
    p = build(cwd, repos, out, fx)
    assert p.returncode == 0, p.stdout + p.stderr
    assert out.is_dir()
    assert list(cwd.iterdir()) == [], "the build writes only to --out"


# ---- the page as package data --------------------------------------------------------------------------

def test_the_page_files_are_package_data_and_the_build_copies_them_unchanged(built):
    out, _, _ = built
    for name in PAGE_FILES:
        assert (STATIC / name).is_file(), f"src/factory_tools/dashboard/static/{name} missing"
        assert (out / name).read_bytes() == (STATIC / name).read_bytes(), f"{name} changed on the way out"


# ---- criterion 3: the page shows a repository tag (node + the LF fake browser) -------------------------

def snapshot_for_page() -> dict:
    def tag(repo, n, title, prio="p1"):
        return {"repo": repo, "number": n, "title": title, "priority": prio, "url": f"https://github.com/{repo}/issues/{n}"}
    return {
        "generated_at": "2026-11-24T11:59:00+00:00",
        "issues": {"open": 3, "closed": 1, "by_status": {"ready": 3}, "by_phase": {"1": 3}, "by_priority": {"p1": 2, "p2": 1}},
        "repos": {
            LF: {"issues": {"open": 1, "closed": 1, "by_status": {"ready": 1}, "by_phase": {"1": 1}, "by_priority": {"p1": 1}}},
            FA: {"issues": {"open": 2, "closed": 0, "by_status": {"ready": 2}, "by_phase": {"1": 2}, "by_priority": {"p1": 1, "p2": 1}}},
        },
        "lanes": [],
        "queue": [tag(LF, 7, "LF seven ready"), tag(FA, 7, "Factory seven ready"), tag(FA, 8, "Factory eight ready", "p2")],
        "claim": None,
        "prs": {"open": [{"repo": FA, "number": 20, "title": "Open pr", "url": "https://github.com/Shashkist/factory/pull/20"}],
                "merged": [{"repo": LF, "number": 21, "title": "Merged pr", "url": "https://github.com/Shashkist/Learning_factory/pull/21",
                            "merged_at": "2026-11-23T09:00:00Z"}]},
        "runs": {LF: {"CI": {"repo": LF, "status": "completed", "conclusion": "success", "url": "https://github.com/x/y/actions/runs/1"}},
                 FA: {"CI": {"repo": FA, "status": "completed", "conclusion": "failure", "url": "https://github.com/x/y/actions/runs/2"}}},
        "server": None,
        "decisions": [{"repo": LF, "id": "D1", "title": "LF first decision"}, {"repo": FA, "id": "D1", "title": "Factory first decision"}],
        "owner_open": [{"repo": FA, "id": "O3", "title": "Factory owner item"}],
        "throughput": {"closed_per_day": [0] * 13 + [1], "median_lead_time_hours": 4, "open_incidents": 0},
    }


def live_for_page() -> dict:
    return {
        "generated_at": "2026-11-24T11:59:30+00:00",
        "schema": 1, "runner": {"state": "running"},
        "issues": [
            {"issue": 7, "repo": LF, "title": "LF seven lane", "station": "build"},
            {"issue": 7, "repo": FA, "title": "Factory seven lane", "station": "exam"},
            {"issue": 6, "repo": FA, "title": "Factory six lane", "station": "check"},
        ],
        "agents": [], "workers": [], "crew": [], "log": [],
    }


def run_page(tmp_path: Path, snapshot: dict, live: dict) -> dict:
    node = shutil.which("node")
    assert node, "node is required for the page exam"
    assert (STATIC / "index.html").is_file() and (STATIC / "app.js").is_file(), \
        "the page is not at src/factory_tools/dashboard/static/"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"now": "2026-11-24T12:00:00Z", "snapshot": snapshot,
                                    "steps": [{"now": "2026-11-24T12:00:00Z", "live": live}]}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(STATIC / "index.html"), str(STATIC / "app.js"), str(scenario)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    step = json.loads(p.stdout.strip().splitlines()[-1])["steps"][0]
    assert not step["errors"], step["errors"]
    return step


def walk(n):
    if isinstance(n, str):
        return
    yield n
    for c in n["c"]:
        yield from walk(c)


def text(n) -> str:
    return n if isinstance(n, str) else "".join(text(c) for c in n["c"])


def with_class(root, cls):
    return [n for n in walk(root) if cls in (n["a"].get("class") or "").split()]


def words(s: str) -> set[str]:
    return set(re.findall(r"[\w.-]+", s))


def assert_tagged(rows: list[str], expected: list[tuple[str, int]]):
    """rows[i] names repo expected[i][0] (short name as its own word) and not the other repository."""
    assert len(rows) == len(expected), rows
    for row, (repo, n) in zip(rows, expected, strict=True):
        short = repo.split("/")[1]
        w = words(row)
        assert short in w, f"no repository tag {short!r} in {row!r}"
        assert str(n) in w or f"#{n}" in row, f"issue number {n} missing in {row!r}"
        if short == "factory":
            assert "Learning_factory" not in w, f"wrong repository tag in {row!r}"
        else:
            assert "factory" not in w, f"wrong repository tag in {row!r}"


def test_c3_every_queue_row_shows_its_repository(tmp_path):
    step = run_page(tmp_path, snapshot_for_page(), live_for_page())
    ul = next(n for n in walk(step["page"]) if n["a"].get("id") == "queue")
    rows = [text(li) for li in walk(ul) if li["t"] == "li"]
    assert_tagged(rows, [(LF, 7), (FA, 7), (FA, 8)])


def test_c3_every_lane_shows_its_repository(tmp_path):
    step = run_page(tmp_path, snapshot_for_page(), live_for_page())
    heads = [text(h) for h in with_class(step["live"], "lane-head")]
    assert len(heads) == 3, "two lanes with the same issue number in two repositories stay two lanes"
    by_title = {t: h for t in ("LF seven lane", "Factory seven lane", "Factory six lane") for h in heads if t in h}
    assert_tagged([by_title["LF seven lane"]], [(LF, 7)])
    assert_tagged([by_title["Factory seven lane"]], [(FA, 7)])
    assert_tagged([by_title["Factory six lane"]], [(FA, 6)])


def test_c3_every_issue_row_in_the_stations_view_shows_its_repository(tmp_path):
    step = run_page(tmp_path, snapshot_for_page(), live_for_page())
    rows = [text(r) for r in with_class(step["live"], "live-issue")]
    assert len(rows) == 3, rows
    expected = {"LF seven lane": (LF, 7), "Factory seven lane": (FA, 7), "Factory six lane": (FA, 6)}
    for title, want in expected.items():
        assert_tagged([next(r for r in rows if title in r)], [want])


def test_c3_the_two_repository_snapshot_renders_without_errors_or_unsafe_markup(tmp_path):
    step = run_page(tmp_path, snapshot_for_page(), live_for_page())
    assert step["innerHTML"] == [] and step["style_attr"] == []
    page_text = text(step["page"])
    for needle in ("Factory eight ready", "Merged pr", "Open pr", "Factory owner item"):
        assert needle in page_text, f"{needle!r} not on the page"
    assert "snapshot unavailable" not in page_text


def test_c3_hostile_titles_stay_text(tmp_path):
    snap = snapshot_for_page()
    evil = "<img src=x onerror=\"globalThis.pwned=1\">"
    snap["queue"][0]["title"] = evil
    live = live_for_page()
    live["issues"][0]["title"] = evil
    step = run_page(tmp_path, snap, live)
    assert step["innerHTML"] == [] and step["pwned"] is None
    assert evil in text(step["page"]), "the title is shown as plain text"
    assert not [n for n in walk(step["page"]) if n["t"] == "img"]


# ---- criterion 4: the built files hold only what the page shows ----------------------------------------

def all_out_files(out: Path) -> list[Path]:
    return sorted(p for p in out.rglob("*") if p.is_file())


def test_c4_output_holds_only_the_snapshot_and_the_page_files(built):
    out, _, _ = built
    names = {p.relative_to(out).as_posix() for p in all_out_files(out)}
    assert {"snapshot.json", *PAGE_FILES} <= names
    assert not [n for n in names if n.lower().endswith((".md", ".yaml", ".yml"))], names
    assert not [n for n in names if "state" in n.lower() or "decisions" in n.lower() or "owner" in n.lower()], names


def test_c4_no_state_text_in_any_built_file(built):
    out, snap, _ = built
    assert "state" not in snap, "STATE.md text is not published (LF D14)"
    for p in all_out_files(out):
        data = p.read_text(encoding="utf-8", errors="replace")
        assert STATE_TEXT not in data, f"STATE text leaked into {p.name}"


def test_c4_no_email_address_in_any_built_file(built):
    out, _, _ = built
    for p in all_out_files(out):
        data = p.read_text(encoding="utf-8", errors="replace")
        for e in EMAILS:
            assert e not in data, f"a seeded email leaked into {p.name}"
    assert not EMAIL_RE.findall((out / "snapshot.json").read_text(encoding="utf-8"))


def test_c4_no_token_shaped_string_in_any_built_file(built):
    out, _, _ = built
    for p in all_out_files(out):
        data = p.read_text(encoding="utf-8", errors="replace")
        for t in TOKENS:
            assert t not in data, f"a seeded token leaked into {p.name}"
        assert not TOKEN_RE.findall(data), f"a token-shaped string in {p.name}"


def test_c4_snapshot_has_only_the_keys_the_page_shows(built):
    snap = built[1]
    allowed = {"generated_at", "issues", "repos", "lanes", "queue", "claim", "prs", "runs", "server",
               "decisions", "owner_open", "throughput"}
    assert set(snap) <= allowed, sorted(set(snap) - allowed)
    assert {"repos", "lanes", "queue", "prs", "decisions", "owner_open", "throughput"} <= set(snap)


def test_c4_items_carry_no_fields_beyond_what_the_page_shows(built):
    snap = built[1]
    allowed = {
        "queue": {"repo", "number", "title", "url", "priority"},
        "lanes": {"repo", "issue", "title", "url", "status", "station"},
        "decisions": {"repo", "id", "title"},
        "owner_open": {"repo", "id", "title"},
    }
    for key, keys in allowed.items():
        for item in snap[key]:
            assert set(item) <= keys, (key, sorted(set(item) - keys))
    for p in snap["prs"]["open"]:
        assert set(p) <= {"repo", "number", "title", "url"}, p
    for p in snap["prs"]["merged"]:
        assert set(p) <= {"repo", "number", "title", "url", "merged_at"}, p
    for r in walk_runs(snap["runs"]):
        assert set(r) <= {"repo", "workflow", "status", "conclusion", "url"}, r
    assert set(snap["claim"]) <= {"repo", "issue", "session", "step", "branch", "heartbeat"}
