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
    assert pick([]) is None


@pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_trusted_first_marker_counts(assoc: str) -> None:
    assert pick([_c(1, assoc)]) == SHA


@pytest.mark.parametrize("assoc", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "", "MANNEQUIN"])
def test_untrusted_marker_is_ignored(assoc: str) -> None:
    assert pick([_c(1, assoc)]) is None


def test_only_the_first_trusted_marker_counts() -> None:
    other = "b" * 40
    later = _c(3, first=f"exam-commit: {other}")
    got = pick([_c(1, "NONE", f"exam-commit: {other}"), _c(2), later])
    assert got == SHA


def test_edited_first_marker_is_refused() -> None:
    with pytest.raises(ValueError, match="edited"):
        pick([_c(1, edited=True), _c(2)])


def test_main_prints_the_value_and_fails_on_an_edited_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(json.dumps(_c(1)) + "\n") == 0
    assert capsys.readouterr().out.strip() == SHA
    assert main(json.dumps(_c(1, edited=True))) == 1
    assert main("not json") == 1


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
