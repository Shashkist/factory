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

    monkeypatch.setattr(claims, "_run", lambda argv: (_ for _ in ()).throw(RuntimeError("no")))
    monkeypatch.setattr(claims.subprocess, "run", lambda *a, **k: Proc())
    assert claims.origin_repo() == A


def test_origin_repo_is_none_without_a_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        returncode = 2
        stdout = ""

    monkeypatch.setattr(claims, "_run", lambda argv: (_ for _ in ()).throw(RuntimeError("no")))
    monkeypatch.setattr(claims.subprocess, "run", lambda *a, **k: Proc())
    assert claims.origin_repo() is None


def test_origin_repo_is_what_gh_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claims, "_run", lambda argv: json.dumps({"nameWithOwner": C}))
    assert claims.origin_repo() == C


def test_all_unreadable_without_a_default_exits_one() -> None:
    args = Namespace(json=True, repo=None, default_repo="", repos=[A, C], clones={})
    assert claims.cmd_status(args, Gh(broken=(A, C))) == 1
    args = Namespace(older_than=0.0, repo=None, default_repo="", repos=[A, C], clones={})
    assert claims.cmd_stale(args, Gh(broken=(A, C))) == 1


def test_one_readable_without_a_default_exits_zero() -> None:
    args = Namespace(json=True, repo=None, default_repo="", repos=[A, C], clones={})
    assert claims.cmd_status(args, Gh(broken=(C,))) == 0


def test_no_repository_and_no_file_exits_one_and_says_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    monkeypatch.setattr(claims, "origin_repo", lambda: None)
    assert claims.cmd_status(Namespace(json=True, repo=None, repos_file=None), Gh()) == 1
    assert "--repo" in capsys.readouterr().err


def test_no_origin_uses_only_the_file_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    monkeypatch.setattr(claims, "origin_repo", lambda: None)
    listing = tmp_path / "repos.yaml"
    listing.write_text("- repo: " + C + "\n", encoding="utf-8")
    args = Namespace(repo=None, repos_file=str(listing))
    claims.resolve_scope(args)
    assert args.repos == [C] and args.default_repo == ""
    assert capsys.readouterr().err == ""


def test_claimed_uses_the_current_repository_as_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(claims, "origin_repo", lambda: A)
    gh = Gh()
    rows = claims.claimed([A], gh)
    assert [r["repo"] for r in rows] == [A]
    assert all("-R" not in c for c in gh.calls)


def test_repo_with_the_default_file_reads_clones_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    monkeypatch.setattr(claims, "origin_repo", lambda: None)
    (tmp_path / "docs" / "factory").mkdir(parents=True)
    (tmp_path / "docs" / "factory" / "repos.yaml").write_text(
        "- repo: " + A + "\n  clone: C:\\a\n- repo: " + C + "\n", encoding="utf-8"
    )
    args = Namespace(repo=A, repos_file=None)
    claims.resolve_scope(args)
    assert args.repos == [] and args.clones == {A: "C:\\a"}
    assert capsys.readouterr().err == ""


def test_repeated_repo_values_are_dropped_case_insensitively(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(json=True, repo=[A, A.lower(), C, A], default_repo="", repos=[], clones={})
    assert claims.cmd_status(args, Gh()) == 0
    assert [r["repo"] for r in json.loads(capsys.readouterr().out)] == [A, C]


def test_take_over_line_uses_the_factory_tools_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args: Any = Namespace(older_than=0.0, repo=[A], default_repo="", repos=[], clones={})
    assert claims.cmd_stale(args, Gh()) == 0
    out = capsys.readouterr().out
    assert "python -m factory_tools claim 5" in out and "--repo " + A in out
