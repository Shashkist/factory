"""Unit tests of the merge gate's pure parts and its gh call shapes."""

import json

import pytest

from factory_tools.pipeline import merge_gate

SHORT = "a1b2c3d"
EXAM = {"name": "exam-integrity", "conclusion": "SUCCESS"}


def test_check_reasons_pass_and_hold():
    assert merge_gate._check_reasons([{"name": "u", "conclusion": "NEUTRAL"}, EXAM]) == []
    assert merge_gate._check_reasons([]) == ["no checks have run on this PR"]
    assert merge_gate._check_reasons([EXAM, {"name": "u", "status": "QUEUED"}]) == [
        "u is pending"
    ]
    skipped = [{"name": "exam-integrity", "conclusion": "SKIPPED"}]
    assert merge_gate._check_reasons(skipped) == ["exam-integrity ended in skipped"]


def test_verdicts_use_first_line_and_author_only():
    def c(who: str, body: str, at: str) -> dict:
        return {"author": {"login": who}, "body": body, "createdAt": at}

    comments = [
        c("a", f"Review round 2: APPROVE at {SHORT}\nmore", "2"),
        c("b", f"Review round 1: CHANGES at {SHORT}", "1"),
        c("a", f"see Review round 3: APPROVE at {SHORT}", "3"),
    ]
    assert merge_gate._verdicts(comments, "a") == [(2, "APPROVE", SHORT)]


def test_commit_files_names_the_repository_in_the_path_never_dash_r():
    calls: list[list[str]] = []

    def run(args: list[str]) -> str:
        calls.append(args)
        return json.dumps({"files": []})

    assert merge_gate._commit_files(run, "o/r", "abc") == {"files": []}
    assert merge_gate._commit_files(run, None, "abc") == {"files": []}
    assert calls == [
        ["api", "repos/o/r/commits/abc"],
        ["api", "repos/{owner}/{repo}/commits/abc"],
    ]


def test_commit_files_without_repo_raises_on_failure():
    def run(args: list[str]) -> str:
        raise RuntimeError("no")

    with pytest.raises(RuntimeError):
        merge_gate._commit_files(run, None, "abc")
