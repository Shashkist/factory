"""Unit tests of the merge gate's pure parts and its gh call shapes."""

import json

import pytest

from factory_tools.pipeline import merge_gate

SHORT = "a1b2c3d"
EXAM = {"name": "exam-integrity", "conclusion": "SUCCESS"}


GATE = {"name": "acceptance / gate", "conclusion": "SUCCESS"}


def test_check_reasons_pass_and_hold():
    assert merge_gate._check_reasons([{"name": "u", "conclusion": "NEUTRAL"}, EXAM, GATE]) == []
    assert merge_gate._check_reasons([]) == ["no checks have run on this PR"]
    assert merge_gate._check_reasons([EXAM, GATE, {"name": "u", "status": "QUEUED"}]) == [
        "u is pending"
    ]
    skipped = [{"name": "exam-integrity", "conclusion": "SKIPPED"}, GATE]
    assert merge_gate._check_reasons(skipped) == ["exam-integrity ended in skipped"]


@pytest.mark.parametrize("state", ["SKIPPED", "NEUTRAL", "FAILURE"])
def test_exam_gate_must_succeed(state):
    gate = {"name": "acceptance / gate", "conclusion": state}
    expected = [f"acceptance / gate ended in {state.lower()}"]
    assert merge_gate._check_reasons([EXAM, gate]) == expected


def test_exam_gate_missing_holds_and_option_renames_it():
    assert merge_gate._check_reasons([EXAM]) == ["acceptance / gate has not run"]
    other = {"name": "ci / gate", "conclusion": "SUCCESS"}
    assert merge_gate._check_reasons([EXAM, other], "ci / gate") == []
    assert merge_gate._check_reasons([EXAM, GATE], "ci / gate") == ["ci / gate has not run"]


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
        ["api", "--paginate", "repos/o/r/commits/abc"],
        ["api", "--paginate", "repos/{owner}/{repo}/commits/abc"],
    ]


def test_commit_files_without_repo_raises_on_failure():
    def run(args: list[str]) -> str:
        raise RuntimeError("no")

    with pytest.raises(RuntimeError):
        merge_gate._commit_files(run, None, "abc")


def test_commit_files_merges_concatenated_pages_and_gate_holds_on_page_two():
    page1 = {"files": [{"filename": f"src/f{i}.py"} for i in range(300)]}
    page2 = {"files": [{"filename": "tests/acceptance/test_x.py"}, {"filename": "src/g.py"}]}

    def run(args: list[str]) -> str:
        return json.dumps(page1) + json.dumps(page2)

    assert len(merge_gate._commit_files(run, "o/r", "abc")["files"]) == 302
    pr = {"commits": [{"oid": "abcdef0123"}]}
    reasons = merge_gate._commit_reasons(pr, run, "o/r")
    assert len(reasons) == 1 and "tests/acceptance" in reasons[0]


@pytest.mark.parametrize("name", ["exam-integrity", "exam-integrity / exam-integrity"])
def test_exam_integrity_names_count(name):
    assert merge_gate._check_reasons([{"name": name, "conclusion": "SUCCESS"}, GATE]) == []
    skipped = [{"name": name, "conclusion": "SKIPPED"}, GATE]
    assert merge_gate._check_reasons(skipped) == [f"{name} ended in skipped"]


@pytest.mark.parametrize(
    "name", ["exam-integrity-lint", "exam-integrity / other", "x / exam-integrity-2"]
)
def test_exam_integrity_lookalikes_do_not_count(name):
    reasons = merge_gate._check_reasons([{"name": name, "conclusion": "SUCCESS"}, GATE])
    assert reasons == ["exam-integrity has not run"]
