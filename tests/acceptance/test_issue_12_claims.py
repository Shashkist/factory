"""Issue #12: claims across repositories (spec 5.1, 11 v0, 13).

Observable behaviour only: the `factory-tools` command line (run as `python -m factory_tools`)
against a fake `gh` that keeps several repositories, and the module source for token handling.

The fake `gh` is wired in without touching PATH: a sitecustomize on PYTHONPATH redirects
subprocess calls whose program is `gh` to tests/acceptance/fake_gh_claims.py, so the exam
behaves the same on Linux and on Windows. The module must therefore start `gh` as a
subprocess whose first argument is `gh` (or find it with shutil.which("gh")).

Criterion 1 (the ported LF tests) lives in tests/acceptance/ported/.
"""

import ast
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers import ROOT, env, module_file

FAKE = Path(__file__).resolve().parent / "fake_gh_claims.py"
FACTORY = "Shashkist/factory"
LF = "Shashkist/Learning_factory"
SENTINEL = "EXAM-SENTINEL-NOT-A-TOKEN-7f3a91"

SITECUSTOMIZE = '''\
import shutil
import subprocess
import sys

_FAKE = {fake!r}
_init = subprocess.Popen.__init__
_which = shutil.which


def _patched(self, args, *a, **k):
    if isinstance(args, (list, tuple)) and args and str(args[0]) in ("gh", "gh.exe"):
        args = [sys.executable, _FAKE, *args[1:]]
    _init(self, args, *a, **k)


def _which_gh(cmd, *a, **k):
    found = _which(cmd, *a, **k)
    return found or ("gh" if str(cmd) in ("gh", "gh.exe") else None)


subprocess.Popen.__init__ = _patched
shutil.which = _which_gh
'''


def iso(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).replace(microsecond=0).isoformat()


def claim_body(session: str, branch: str, heartbeat_min: float = 1) -> str:
    """A claim comment in LF's format (marker, JSON, END), written by hand."""
    payload = {
        "session": session,
        "branch": branch,
        "worktree": "",
        "claimed": iso(heartbeat_min + 5),
        "heartbeat": iso(heartbeat_min),
        "step": "working",
    }
    return "<!-- pulsesign-issue-claim\n" + json.dumps(payload) + "\n-->\nClaimed by " + session


class World:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.state_path = base / "state.json"
        self.home = base / "home"
        self.home.mkdir()
        self.cwd = base / "work"
        self.cwd.mkdir()
        site = base / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(
            SITECUSTOMIZE.format(fake=str(FAKE)), encoding="utf-8"
        )
        self.site = site
        self.state_path.write_text(
            json.dumps(
                {
                    "default": FACTORY,
                    "next_id": 1000,
                    "calls": [],
                    "repos": {
                        r: {
                            "issues": {
                                "5": {"title": "Five in " + r, "labels": ["status:ready"],
                                      "comments": []}
                            }
                        }
                        for r in (FACTORY, LF)
                    },
                }
            ),
            encoding="utf-8",
        )

    def state(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def seed_claim(self, repo: str, number: int, session: str, branch: str, minutes: float) -> None:
        s = self.state()
        issue = s["repos"][repo]["issues"][str(number)]
        cid = s["next_id"]
        s["next_id"] += 1
        issue["comments"].append(
            {
                "id": cid,
                "body": claim_body(session, branch, minutes),
                "url": "https://github.com/" + repo + "/issues/" + str(number)
                + "#issuecomment-" + str(cid),
            }
        )
        issue["labels"] = ["status:in-progress"]
        self.state_path.write_text(json.dumps(s), encoding="utf-8")

    def comments(self, repo: str, number: int = 5) -> list[str]:
        return [c["body"] for c in self.state()["repos"][repo]["issues"][str(number)]["comments"]]

    def run(
        self, *argv: str, cwd: Path | None = None, extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        e = env(
            {
                "FAKE_GH_STATE": str(self.state_path),
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                **(extra or {}),
            }
        )
        e["PYTHONPATH"] = str(self.site) + os.pathsep + e["PYTHONPATH"]
        e.pop("LF_REPOS_FILE", None)
        if extra:
            e.update(extra)
        return subprocess.run(
            [sys.executable, "-m", "factory_tools", *argv],
            cwd=cwd or self.cwd,
            env=e,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def claim(self, repo: str, session: str, branch: str) -> subprocess.CompletedProcess[str]:
        return self.run(
            "claim", "5", "--session", session, "--branch", branch, "--repo", repo
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def list_file(base: Path, *repos: str) -> Path:
    p = base / "repos.yaml"
    p.write_text("".join("- repo: " + r + "\n" for r in repos), encoding="utf-8")
    return p


def status_rows(out: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(out)
    return rows


# --- criterion 2: coexisting claims, status over both repositories -----------------------


COMMANDS = ["claim", "release", "heartbeat", "status", "stale"]


@pytest.mark.parametrize("command", COMMANDS)
def test_command_exists_under_factory_tools_and_accepts_repo(world: World, command: str) -> None:
    r = world.run(command, "--help")
    assert r.returncode == 0, r.stderr
    assert "--repo" in r.stdout


def test_factory_tools_lists_the_claim_commands(world: World) -> None:
    r = world.run("--help")
    assert r.returncode == 0, r.stderr
    for command in COMMANDS:
        assert command in r.stdout


def test_claims_on_the_same_number_in_two_repositories_coexist(world: World) -> None:
    a = world.claim(FACTORY, "sess-a", "f/5-factory")
    b = world.claim(LF, "sess-b", "f/5-lf")
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    # Each claim sits on its own repository's issue, and nowhere else.
    (only_a,) = world.comments(FACTORY)
    (only_b,) = world.comments(LF)
    assert "sess-a" in only_a and "sess-b" not in only_a
    assert "sess-b" in only_b and "sess-a" not in only_b
    # Taking the second did not make the first look refused or released.
    assert "released" not in only_a and "released" not in only_b


def test_a_claim_in_one_repository_does_not_block_the_other_session_elsewhere(
    world: World,
) -> None:
    assert world.claim(FACTORY, "sess-a", "f/5-x").returncode == 0
    # The same number, the same branch name, another repository: not a collision.
    assert world.claim(LF, "sess-b", "f/5-x").returncode == 0
    # But the same repository is still protected.
    refused = world.claim(FACTORY, "sess-c", "f/5-y")
    assert refused.returncode == 1


def test_status_over_two_repo_values_lists_both_with_their_repository(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    r = world.run("status", "--repo", FACTORY, "--repo", LF)
    assert r.returncode == 0, r.stderr
    line_a = next(ln for ln in r.stdout.splitlines() if "sess-a" in ln)
    line_b = next(ln for ln in r.stdout.splitlines() if "sess-b" in ln)
    assert FACTORY in line_a and LF not in line_a
    assert LF in line_b and FACTORY not in line_b


def test_status_json_over_two_repo_values_has_a_repo_per_row(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    r = world.run("status", "--json", "--repo", FACTORY, "--repo", LF)
    assert r.returncode == 0, r.stderr
    rows = status_rows(r.stdout)
    assert sorted((x["repo"], x["number"]) for x in rows) == sorted([(FACTORY, 5), (LF, 5)])
    by_repo = {x["repo"]: x["claim"]["session"] for x in rows}
    assert by_repo == {FACTORY: "sess-a", LF: "sess-b"}


def test_status_over_a_repositories_list_file_lists_both(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    listing = list_file(world.base, FACTORY, LF)
    r = world.run("status", "--json", "--repos-file", str(listing))
    assert r.returncode == 0, r.stderr
    assert {x["repo"] for x in status_rows(r.stdout)} == {FACTORY, LF}


def test_status_reads_the_repositories_list_file_named_by_the_lf_variable(world: World) -> None:
    # LF keeps using LF_REPOS_FILE (spec G8): its name and meaning do not change.
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    listing = list_file(world.base, FACTORY, LF)
    r = world.run("status", "--json", extra={"LF_REPOS_FILE": str(listing)})
    assert r.returncode == 0, r.stderr
    assert {x["repo"] for x in status_rows(r.stdout)} == {FACTORY, LF}


def test_status_with_one_repo_value_shows_only_that_repository(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    r = world.run("status", "--json", "--repo", LF)
    assert r.returncode == 0, r.stderr
    assert [x["repo"] for x in status_rows(r.stdout)] == [LF]


def test_stale_over_several_repo_values_shows_the_repository_in_each_row(world: World) -> None:
    world.seed_claim(FACTORY, 5, "gone-a", "f/5-factory", 300)
    world.seed_claim(LF, 5, "gone-b", "f/5-lf", 300)
    r = world.run("stale", "--older-than", "90", "--repo", FACTORY, "--repo", LF)
    assert r.returncode == 0, r.stderr
    blocks = [b for b in r.stdout.split("\n#") if "gone-" in b]
    assert len(blocks) == 2
    block_a = next(b for b in blocks if "gone-a" in b)
    block_b = next(b for b in blocks if "gone-b" in b)
    assert FACTORY in block_a and LF not in block_a
    assert LF in block_b and FACTORY not in block_b
    # The take-over line for a claim in another repository must say which one.
    assert "--repo" in block_a or "--repo" in block_b


def test_stale_over_a_repositories_list_file_lists_both(world: World) -> None:
    world.seed_claim(FACTORY, 5, "gone-a", "f/5-factory", 300)
    world.seed_claim(LF, 5, "gone-b", "f/5-lf", 300)
    listing = list_file(world.base, FACTORY, LF)
    r = world.run("stale", "--older-than", "90", "--repos-file", str(listing))
    assert r.returncode == 0, r.stderr
    assert "gone-a" in r.stdout and "gone-b" in r.stdout


def test_heartbeat_and_release_act_on_the_repository_named(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    beat = world.run(
        "heartbeat", "5", "--session", "sess-a", "--repo", FACTORY, "--step", "testing"
    )
    assert beat.returncode == 0, beat.stderr
    assert "testing" in world.comments(FACTORY)[0]
    assert "testing" not in world.comments(LF)[0]

    rel = world.run("release", "5", "--session", "sess-a", "--repo", FACTORY)
    assert rel.returncode == 0, rel.stderr
    status = world.run("status", "--json", "--repo", FACTORY, "--repo", LF)
    assert [(x["repo"], x["claim"]["session"]) for x in status_rows(status.stdout)] == [
        (LF, "sess-b")
    ]


def test_without_repo_the_command_uses_the_repository_of_the_current_directory(
    world: World,
) -> None:
    checkout = world.base / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/" + FACTORY + ".git"],
        cwd=checkout,
        check=True,
    )
    r = world.run("claim", "5", "--session", "sess-a", "--branch", "f/5-x", cwd=checkout)
    assert r.returncode == 0, r.stderr
    assert any("sess-a" in c for c in world.comments(FACTORY))
    assert world.comments(LF) == []


def test_a_repository_that_cannot_be_read_is_reported_not_silently_empty(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    r = world.run("status", "--repo", FACTORY, "--repo", "Shashkist/does-not-exist")
    # LF's rule for a failed repository: say so once, keep the others.
    assert "Shashkist/does-not-exist" in r.stderr
    assert "sess-a" in r.stdout


# --- criterion 3: no token handling -----------------------------------------------------


def claims_source() -> str:
    path = module_file("factory_tools.claims")
    assert path is not None, "factory_tools.claims does not exist"
    return path.read_text(encoding="utf-8")


SECRETISH = re.compile(
    r"token|secret|password|passwd|credential|authorization|bearer|ghp_|gho_|ghs_|github_pat",
    re.IGNORECASE,
)


def literals_and_names(source: str) -> list[str]:
    """String literals (docstrings excluded) and identifiers in the code."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append(node.value)
        elif isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, ast.arg):
            found.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            found.append(node.arg)
    return found


def test_claims_module_holds_no_token_handling_in_its_code() -> None:
    hits = [x for x in literals_and_names(claims_source()) if SECRETISH.search(x)]
    assert hits == [], "token or credential handling in factory_tools.claims: " + repr(hits)


def test_claims_module_never_calls_gh_auth() -> None:
    for literal in literals_and_names(claims_source()):
        assert literal.strip().split(" ")[0] != "auth", "factory_tools.claims runs gh auth"
    assert "auth token" not in claims_source().replace("\n", " ")


def test_claims_module_reads_no_credential_variable() -> None:
    src = claims_source()
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_PAT"):
        assert name not in src
    for key in re.findall(r"environ(?:\.get)?\(?\[?\s*[\"']([A-Za-z0-9_]+)[\"']", src):
        assert not SECRETISH.search(key), "reads environment variable " + key


def test_no_command_echoes_or_stores_a_token_from_the_environment(world: World) -> None:
    tokens = {
        "GH_TOKEN": SENTINEL,
        "GITHUB_TOKEN": SENTINEL + "-b",
        "GH_ENTERPRISE_TOKEN": SENTINEL + "-c",
    }
    world.seed_claim(LF, 5, "gone-b", "f/5-lf", 300)
    listing = list_file(world.base, FACTORY, LF)
    runs = [
        world.run("claim", "5", "--session", "sess-a", "--branch", "f/5-x", "--repo", FACTORY,
                  extra=tokens),
        world.run("heartbeat", "5", "--session", "sess-a", "--repo", FACTORY, "--step", "s",
                  extra=tokens),
        world.run("status", "--repo", FACTORY, "--repo", LF, extra=tokens),
        world.run("status", "--json", "--repos-file", str(listing), extra=tokens),
        world.run("stale", "--older-than", "90", "--repo", LF, extra=tokens),
        world.run("release", "5", "--session", "sess-a", "--repo", FACTORY, extra=tokens),
    ]
    for r in runs:
        assert r.returncode == 0, r.stderr
        for value in tokens.values():
            assert value not in r.stdout
            assert value not in r.stderr

    # Nothing reached gh as an argument or into a comment, and gh was never asked for auth.
    state = world.state()
    blob = json.dumps(state)
    for value in tokens.values():
        assert value not in blob
    assert not [c for c in state["calls"] if c[:1] == ["auth"]]

    # Nothing was stored: no file under the working directory, home or temp area holds it.
    for root in (world.cwd, world.home):
        for p in root.rglob("*"):
            if p.is_file():
                data = p.read_bytes()
                for value in tokens.values():
                    assert value.encode() not in data, "token stored in " + str(p)


def test_the_claims_module_exists_in_the_package() -> None:
    assert module_file("factory_tools.claims") == ROOT / "src" / "factory_tools" / "claims.py"


# --- review round 1: cases a wrong port passed (D7) --------------------------------------


def checkout_of(world: World, repo: str) -> Path:
    """A git checkout whose origin is `repo` (and, for the fake, the repository gh targets)."""
    d = world.base / "checkout"
    d.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/" + repo + ".git"],
        cwd=d,
        check=True,
    )
    return d


def test_heartbeat_acts_on_the_named_repository_not_the_default_one(world: World) -> None:
    # The fake's default repository is FACTORY; a call without -R would land there.
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    before = world.comments(FACTORY)
    beat = world.run("heartbeat", "5", "--session", "sess-b", "--repo", LF, "--step", "testing")
    assert beat.returncode == 0, beat.stderr
    assert "testing" in world.comments(LF)[0]
    assert world.comments(FACTORY) == before


def test_release_acts_on_the_named_repository_not_the_default_one(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    before = world.comments(FACTORY)
    rel = world.run("release", "5", "--session", "sess-b", "--repo", LF)
    assert rel.returncode == 0, rel.stderr
    assert world.comments(FACTORY) == before
    status = world.run("status", "--json", "--repo", FACTORY, "--repo", LF)
    assert [(x["repo"], x["claim"]["session"]) for x in status_rows(status.stdout)] == [
        (FACTORY, "sess-a")
    ]


def test_status_exits_non_zero_when_every_named_repository_is_unreadable(world: World) -> None:
    r = world.run("status", "--repo", "Shashkist/nope-1", "--repo", "Shashkist/nope-2")
    assert r.returncode != 0
    assert "No issues are claimed." not in r.stdout
    assert "Shashkist/nope-1" in r.stderr and "Shashkist/nope-2" in r.stderr


def test_stale_exits_non_zero_when_every_named_repository_is_unreadable(world: World) -> None:
    r = world.run(
        "stale", "--older-than", "90", "--repo", "Shashkist/nope-1", "--repo", "Shashkist/nope-2"
    )
    assert r.returncode != 0
    assert "No claim is older than" not in r.stdout
    assert "Shashkist/nope-1" in r.stderr and "Shashkist/nope-2" in r.stderr


def test_status_with_no_origin_and_an_all_unreadable_list_file_exits_non_zero(
    world: World,
) -> None:
    listing = list_file(world.base, "Shashkist/nope-1", "Shashkist/nope-2")
    r = world.run("status", "--repos-file", str(listing))
    assert r.returncode != 0
    assert "No issues are claimed." not in r.stdout


def test_stale_with_no_origin_and_an_all_unreadable_list_file_exits_non_zero(
    world: World,
) -> None:
    listing = list_file(world.base, "Shashkist/nope-1", "Shashkist/nope-2")
    r = world.run("stale", "--older-than", "90", "--repos-file", str(listing))
    assert r.returncode != 0
    assert "No claim is older than" not in r.stdout


def test_status_without_repo_reads_and_labels_the_repository_of_the_checkout(
    world: World,
) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    r = world.run("status", "--json", cwd=checkout_of(world, LF))
    assert r.returncode == 0, r.stderr
    rows = status_rows(r.stdout)
    assert [(x["repo"], x["claim"]["session"]) for x in rows] == [(LF, "sess-b")]


def test_status_without_repo_text_rows_are_labelled_with_the_checkout_repository(
    world: World,
) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    world.claim(LF, "sess-b", "f/5-lf")
    r = world.run("status", cwd=checkout_of(world, LF))
    assert r.returncode == 0, r.stderr
    line = next(ln for ln in r.stdout.splitlines() if "sess-b" in ln)
    assert LF in line
    assert "sess-a" not in r.stdout


def test_status_with_no_checkout_no_repo_and_no_list_file_asks_for_repo(world: World) -> None:
    world.claim(LF, "sess-b", "f/5-lf")
    before = len(world.state()["calls"])
    r = world.run("status")
    assert r.returncode != 0
    assert "--repo" in r.stderr + r.stdout
    assert "sess-b" not in r.stdout
    # The command itself read nothing from the repository of any particular owner.
    own = world.state()["calls"][before:]
    assert [c for c in own if LF in " ".join(c)] == []


def test_stale_with_no_checkout_no_repo_and_no_list_file_asks_for_repo(world: World) -> None:
    world.seed_claim(LF, 5, "gone-b", "f/5-lf", 300)
    before = len(world.state()["calls"])
    r = world.run("stale", "--older-than", "90")
    assert r.returncode != 0
    assert "--repo" in r.stderr + r.stdout
    assert "gone-b" not in r.stdout
    own = world.state()["calls"][before:]
    assert [c for c in own if LF in " ".join(c)] == []


def test_a_repeated_repo_value_lists_each_claim_once(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    r = world.run("status", "--json", "--repo", FACTORY, "--repo", FACTORY.lower())
    assert r.returncode == 0, r.stderr
    assert [(x["repo"], x["claim"]["session"]) for x in status_rows(r.stdout)] == [
        (FACTORY, "sess-a")
    ]


def test_a_repeated_repo_value_in_text_output_lists_each_claim_once(world: World) -> None:
    world.claim(FACTORY, "sess-a", "f/5-factory")
    r = world.run("status", "--repo", FACTORY, "--repo", FACTORY.lower())
    assert r.returncode == 0, r.stderr
    assert sum("sess-a" in ln for ln in r.stdout.splitlines()) == 1


def test_stale_with_repo_still_reads_clone_paths_from_the_default_list_file(
    world: World,
) -> None:
    world.seed_claim(FACTORY, 5, "gone-a", "f/5-factory", 300)
    (world.cwd / "docs" / "factory").mkdir(parents=True)
    (world.cwd / "docs" / "factory" / "repos.yaml").write_text(
        "- repo: " + FACTORY + "\n  clone: /srv/clones/factory\n", encoding="utf-8"
    )
    r = world.run("stale", "--older-than", "90", "--repo", FACTORY)
    assert r.returncode == 0, r.stderr
    assert "gone-a" in r.stdout
    assert "git -C" in r.stdout
    assert "/srv/clones/factory" in r.stdout
