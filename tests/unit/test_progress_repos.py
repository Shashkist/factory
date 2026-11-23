"""The repository list of the progress commands: its source and its effect on redaction."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from factory_tools import progress

LF = "Shashkist/Learning_factory"
FACTORY = "Shashkist/factory"


@pytest.fixture(autouse=True)
def no_repos_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)


def listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    f = tmp_path / "repos.yaml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LF_REPOS_FILE", str(f))


def test_without_a_file_the_built_in_pair_applies() -> None:
    assert progress.canon_repo("") == ""
    assert progress.canon_repo(LF.lower()) == ""
    assert progress.canon_repo("shashkist/FACTORY") == FACTORY
    assert progress.canon_repo("acme/widgets") is None


@pytest.mark.parametrize("text", ["", "not: a list\n", "- just a string\n", "- [unclosed\n"])
def test_an_unusable_file_falls_back_to_the_built_in_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    listing(tmp_path, monkeypatch, text)
    assert progress.canon_repo(FACTORY) == FACTORY
    assert progress.canon_repo("acme/widgets") is None


def test_a_missing_file_falls_back_to_the_built_in_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LF_REPOS_FILE", str(tmp_path / "nope.yaml"))
    assert progress.canon_repo(LF) == ""


def test_the_default_is_the_listed_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing(tmp_path, monkeypatch, f"- repo: {LF}\n- repo: acme/w\n  default: true\n")
    assert progress.canon_repo("acme/W") == ""
    assert progress.canon_repo(LF) == LF
    assert progress.canon_repo(FACTORY) is None


def test_a_list_without_a_default_scopes_every_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing(tmp_path, monkeypatch, "- repo: acme/w\n")
    assert progress.canon_repo("acme/w") == "acme/w"
    assert progress.canon_repo("") == ""


def test_scrub_follows_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing(tmp_path, monkeypatch, "- repo: acme/w\n  default: true\n")
    assert progress.scrub("see https://github.com/acme/w/pull/1") == (
        "see https://github.com/acme/w/pull/1"
    )
    assert progress.scrub("see https://github.com/Shashkist/factory/pull/1") == "see <url>"
    assert progress.scrub("see github.com/Shashkist/factory/pull/1") == "see <url>"


def test_progress_runs_as_a_plain_file(tmp_path: Path) -> None:
    events = tmp_path / "e.jsonl"
    out = tmp_path / "live.json"
    env = {**os.environ, "LF_PROGRESS_FILE": str(events)}
    env.pop("PYTHONPATH", None)
    for args in (["pass-start"], ["render", "--out", str(out)]):
        r = subprocess.run(
            [sys.executable, progress.__file__, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 0 and r.stderr == ""
    assert out.exists()
