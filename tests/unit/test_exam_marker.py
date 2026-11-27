import json
import subprocess
from pathlib import Path

import pytest

from factory_tools.ci import exam_integrity
from factory_tools.ci.exam_marker import main, pick

SHA = "a" * 40


def _c(cid: int, assoc: str = "OWNER", first: str = f"exam-commit: {SHA}", edited: bool = False):
    return {
        "id": cid,
        "author_association": assoc,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z" if edited else "2026-01-01T00:00:00Z",
        "first": first,
    }


def test_no_comments_means_no_marker() -> None:
    assert pick([]) == []


@pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_trusted_first_marker_counts(assoc: str) -> None:
    assert pick([_c(1, assoc)]) == [SHA]


@pytest.mark.parametrize("assoc", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "", "MANNEQUIN"])
def test_untrusted_marker_is_ignored(assoc: str) -> None:
    assert pick([_c(1, assoc)]) == []


def test_trusted_markers_form_a_chain_and_untrusted_ones_are_skipped() -> None:
    other = "b" * 40
    later = _c(3, first=f"exam-commit: {other}")
    got = pick([_c(1, "NONE", f"exam-commit: {other}"), _c(2), later])
    assert got == [SHA, other]


def test_edited_marker_is_refused() -> None:
    with pytest.raises(ValueError, match="edited"):
        pick([_c(1, edited=True), _c(2)])


@pytest.mark.parametrize(
    "first",
    [
        "exam-commit:",
        "exam-commit: ",
        f"exam-commit: {SHA} (exam)",
        f"exam-commit: {SHA[:39]}",
        f"exam-commit: {'A' * 40}",
        f"exam-commit:{SHA}",
    ],
)
def test_malformed_marker_line_is_ignored_not_counted(
    first: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert pick([_c(1, first=first), _c(2)]) == [SHA]
    assert "ignoring exam-commit comment 1" in capsys.readouterr().err


def test_malformed_edited_marker_does_not_fail_the_run() -> None:
    assert pick([_c(1, first="exam-commit:", edited=True), _c(2)]) == [SHA]


def test_main_prints_the_values_and_fails_on_an_edited_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(json.dumps(_c(1)) + "\n") == 0
    assert capsys.readouterr().out.strip() == SHA
    assert main(json.dumps(_c(1, edited=True))) == 1
    assert main("not json") == 1


def test_main_splits_on_newline_only(capsys: pytest.CaptureFixture[str]) -> None:
    # U+0085 and U+2028 inside a JSON line (gh's jq prints them raw) must not split it.
    weird = json.dumps(_c(1, "NONE", "exam-commit: x\x85y z"), ensure_ascii=False)
    assert "\x85" in weird
    assert main(weird + "\n" + json.dumps(_c(2)) + "\n") == 0
    assert capsys.readouterr().out.strip() == SHA


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_exam_commit_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests" / "acceptance").mkdir(parents=True)
    exam = tmp_path / "tests" / "acceptance" / "x.py"
    exam.write_text("v1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "exam")
    e = _git(tmp_path, "rev-parse", "HEAD")
    exam.write_text("v2\n")
    _git(tmp_path, "commit", "-qam", "exam edit")
    monkeypatch.chdir(tmp_path)
    check = exam_integrity._check_exam_commit
    assert any("tests/acceptance/x.py" in m and e in m for m in check(e, "HEAD", None))
    assert check(e, "HEAD", ["docs/**"]) == []  # not exam under these globs
    assert check(_git(tmp_path, "rev-parse", "HEAD"), "HEAD", None) == []
    assert "40-hex" in check("abc", "HEAD", None)[0]
    assert "not a commit" in check("0" * 40, "HEAD", None)[0]
    assert "ancestor" in check(_git(tmp_path, "rev-parse", "HEAD"), "HEAD~1", None)[0]


def _repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests" / "acceptance").mkdir(parents=True)


def _commit(tmp_path: Path, name: str, text: str) -> str:
    (tmp_path / name).write_text(text)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", name)
    return _git(tmp_path, "rev-parse", "HEAD")


def test_marker_chain_supersedes_only_with_an_identical_exam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path)
    e1 = _commit(tmp_path, "tests/acceptance/x.py", "v1\n")
    _git(tmp_path, "commit", "-q", "--amend", "-m", "exam again", "--date", "2001-01-01T00:00:00")
    e2 = _git(tmp_path, "rev-parse", "HEAD")  # same tree, new SHA (a rebase)
    assert e1 != e2
    head = _commit(tmp_path, "src.py", "code\n")
    monkeypatch.chdir(tmp_path)
    chain = exam_integrity._check_marker_chain
    assert chain([e1, e2], head, None) == []  # identical exam: the newest marker is used
    assert f"exam-commit marker used: {e2}" in capsys.readouterr().out
    # a later marker whose exam differs is refused, naming both SHAs
    moved = _commit(tmp_path, "tests/acceptance/x.py", "v2\n")
    err = chain([e2, moved], "HEAD", None)
    assert len(err) == 1 and e2 in err[0] and moved in err[0] and "tests/acceptance/x.py" in err[0]
    # a chain member that is not a commit fails closed
    assert "not a commit" in chain([e2, "0" * 40], "HEAD", None)[0]
    assert chain([moved], "HEAD", None) == []  # a single marker is checked as before


def test_main_takes_several_exam_commit_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path)
    base = _commit(tmp_path, "a.txt", "a\n")
    e = _commit(tmp_path, "tests/acceptance/x.py", "v1\n")
    _git(tmp_path, "checkout", "-q", "-b", "pr")
    head = _commit(tmp_path, "src.py", "code\n")
    monkeypatch.chdir(tmp_path)
    args = exam_integrity._parse(["main", head, f"--exam-commit={e}", f"--exam-commit={e}"])
    assert args.exam_commit == [e, e]
    assert exam_integrity.main(base, head, False, None, None, args.exam_commit) == 0


def test_marker_step_does_not_write_into_the_workspace() -> None:
    wf = (Path(__file__).parents[2] / ".github" / "workflows" / "exam-integrity.yml").read_text()
    assert "comments.jsonl" not in wf
    assert "set -eo pipefail" in wf
    assert "| /usr/bin/python3 -I .factory-tools/src/factory_tools/ci/exam_marker.py" in wf


def _rebased_clone(tmp_path: Path, prune: bool) -> tuple[Path, str, str, str]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _repo(origin)
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    e1 = _commit(origin, "tests/acceptance/x.py", "v1\n")
    _git(origin, "commit", "-q", "--amend", "-m", "exam again", "--date", "2001-01-01T00:00:00")
    e2 = _git(origin, "rev-parse", "HEAD")  # a rebase: same exam, new SHA, e1 unreachable
    head = _commit(origin, "src.py", "code\n")
    if prune:
        _git(origin, "reflog", "expire", "--expire=now", "--all")
        _git(origin, "gc", "-q", "--prune=now")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "--no-local", str(origin), str(clone))
    assert subprocess.run(["git", "cat-file", "-e", e1], cwd=clone).returncode != 0
    return clone, e1, e2, head


def test_chain_fetches_an_unreachable_earlier_marker_by_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clone, e1, e2, head = _rebased_clone(tmp_path, prune=False)
    monkeypatch.chdir(clone)
    assert exam_integrity._check_marker_chain([e1, e2], head, None) == []
    assert f"fetching exam-commit marker {e1}" in capsys.readouterr().out


def test_chain_fails_closed_when_the_earlier_marker_is_not_fetchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, e1, e2, head = _rebased_clone(tmp_path, prune=True)
    monkeypatch.chdir(clone)
    err = exam_integrity._check_marker_chain([e1, e2], head, None)
    assert err and e1 in err[0] and "delete the earlier marker comment" in err[0]


def test_marker_first_line_may_end_with_a_carriage_return() -> None:
    assert pick([_c(1, first=f"exam-commit: {SHA}\r")]) == [SHA]
    assert pick([_c(1, first=f"exam-commit: {SHA}\r\r")]) == []
