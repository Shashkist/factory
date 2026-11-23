"""Unit tests for what the claims port adds to LF's issue_lock: several --repo values,
--repos-file, the origin default, and failure handling across several repositories."""

import json
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from factory_tools import claims

A = "Shashkist/factory"
B = "Shashkist/Learning_factory"
C = "Shashkist/other"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Gh:
    """Fake gh: one claimed #5 per repository, `broken` repositories fail."""

    def __init__(self, broken: tuple[str, ...] = ()) -> None:
        self.broken = set(broken)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        repo = argv[argv.index("-R") + 1] if "-R" in argv else "(bare)"
        if repo in self.broken:
            raise RuntimeError("gh failed")
        if argv[:2] == ["issue", "view"]:
            body = claims.render(
                {"session": "s-" + repo, "branch": "f/5-x", "worktree": "",
                 "claimed": now_iso(), "heartbeat": now_iso(), "step": "x"}
            )
            return json.dumps({"comments": [{"body": body, "url": "u#issuecomment-1"}]})
        if argv[:2] == ["issue", "list"]:
            return json.dumps([{"number": 5, "title": "t", "updatedAt": now_iso()}])
        return ""


def parse(*argv: str) -> Namespace:
    return claims.build_parser().parse_args(argv)


def test_one_repo_value_stays_a_string() -> None:
    assert parse("status", "--repo", A).repo == A


def test_several_repo_values_become_a_list() -> None:
    assert parse("status", "--repo", A, "--repo", B).repo == [A, B]
    assert parse("stale", "--repo", A, "--repo", B, "--repo", C).repo == [A, B, C]


def test_no_repo_value_is_none() -> None:
    args = parse("status")
    assert args.repo is None and args.repos_file is None


def test_repos_file_option_is_parsed() -> None:
    assert parse("stale", "--repos-file", "x.yaml").repos_file == "x.yaml"


def test_status_reads_every_named_repository_with_dash_r(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gh = Gh()
    args = Namespace(json=True, repo=[A, B], default_repo="", repos=[], clones={})
    assert claims.cmd_status(args, gh) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["repo"] for r in rows] == [A, B]
    assert all("-R" in c for c in gh.calls)


def test_one_unreadable_repository_of_several_is_skipped_and_exit_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(json=True, repo=[A, C], default_repo="", repos=[], clones={})
    assert claims.cmd_status(args, Gh(broken=(C,))) == 0
    cap = capsys.readouterr()
    assert [r["repo"] for r in json.loads(cap.out)] == [A]
    assert C in cap.err


def test_all_named_repositories_unreadable_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(json=True, repo=[A, C], default_repo="", repos=[], clones={})
    assert claims.cmd_status(args, Gh(broken=(A, C))) == 1
    assert "[]" not in capsys.readouterr().out


def test_resolve_scope_reads_the_named_repos_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    monkeypatch.setattr(claims, "origin_repo", lambda: A)
    listing = tmp_path / "repos.yaml"
    listing.write_text("- repo: " + A + "\n- repo: " + C + "\n  clone: C:\\c\n", encoding="utf-8")
    args = Namespace(repo=None, repos_file=str(listing))
    claims.resolve_scope(args)
    assert args.repos == [A, C]
    assert args.default_repo == A
    assert args.clones == {C: "C:\\c"}


def test_resolve_scope_honours_the_lf_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = tmp_path / "repos.yaml"
    listing.write_text("- repo: " + A + "\n- repo: " + C + "\n", encoding="utf-8")
    monkeypatch.setenv("LF_REPOS_FILE", str(listing))
    monkeypatch.setattr(claims, "origin_repo", lambda: A)
    args = Namespace(repo=None, repos_file=None)
    claims.resolve_scope(args)
    assert args.repos == [A, C]


def test_resolve_scope_with_repo_and_no_file_does_not_read_a_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    monkeypatch.setattr(claims, "origin_repo", lambda: None)
    args = Namespace(repo=A, repos_file=None)
    claims.resolve_scope(args)
    assert args.default_repo == "" and args.repos == []
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Shashkist/factory.git",
        "https://github.com/Shashkist/factory",
        "git@github.com:Shashkist/factory.git",
    ],
)
def test_origin_repo_parses_remote_urls(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Proc:
        returncode = 0
        stdout = url + "\n"

    monkeypatch.setattr(claims.subprocess, "run", lambda *a, **k: Proc())
    assert claims.origin_repo() == A


def test_origin_repo_is_none_without_a_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        returncode = 2
        stdout = ""

    monkeypatch.setattr(claims.subprocess, "run", lambda *a, **k: Proc())
    assert claims.origin_repo() is None


def test_take_over_line_uses_the_factory_tools_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args: Any = Namespace(older_than=0.0, repo=[A], default_repo="", repos=[], clones={})
    assert claims.cmd_stale(args, Gh()) == 0
    out = capsys.readouterr().out
    assert "python -m factory_tools claim 5" in out and "--repo " + A in out
