"""The repository list of the progress commands: its source, its trust and redaction."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from factory_tools import progress

LF = "Shashkist/Learning_factory"
FACTORY = "Shashkist/factory"


@pytest.fixture(autouse=True)
def no_repos_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)
    progress._repo_cache.clear()


def listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    f = tmp_path / "repos.yaml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LF_REPOS_FILE", str(f))
    return f


def test_without_a_file_the_built_in_pair_applies() -> None:
    assert progress.lane_repo("") == ""
    assert progress.lane_repo(LF.lower()) == ""
    assert progress.lane_repo("shashkist/FACTORY") == FACTORY
    assert progress.lane_repo("acme/widgets") is None


def test_canonical_name_is_the_full_name_and_the_default_when_none_given() -> None:
    assert progress.canon_repo("") == LF
    assert progress.canon_repo(LF.lower()) == LF
    assert progress.canon_repo(["x"]) is None
    assert progress.canon_repo("acme/widgets") is None


def test_no_default_in_the_list_means_no_default_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing(tmp_path, monkeypatch, "- repo: acme/w\n")
    assert progress.canon_repo("") == ""
    assert progress.lane_repo("acme/w") == "acme/w"
    assert progress.lane_repo("") == ""


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not: a list\n",
        "- just a string\n",
        "- [unclosed\n",
        "- repo: 123\n- repo: [a, b]\n- repo: a/b/c\n- repo: me@x.com\n",
        "[" * 20000 + "]" * 20000 + "\n",
    ],
)
def test_an_unusable_file_falls_back_with_one_stderr_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    listing(tmp_path, monkeypatch, text)
    assert progress.lane_repo(FACTORY) == FACTORY
    assert progress.lane_repo(LF) == ""
    assert progress.lane_repo("acme/widgets") is None
    err = capsys.readouterr().err
    assert err.count("repository list ignored") == 1


def test_a_missing_file_falls_back_to_the_built_in_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LF_REPOS_FILE", str(tmp_path / "nope.yaml"))
    assert progress.lane_repo(LF) == ""


def test_a_file_over_64_kb_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = "".join(f"- repo: acme/r{i}\n" for i in range(5000)) + "- repo: acme/last\n"
    assert len(body) > progress.REPOS_FILE_MAX
    listing(tmp_path, monkeypatch, body)
    assert progress.lane_repo("acme/last") is None
    assert progress.lane_repo(LF) == ""


def test_an_alias_bomb_is_never_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["- &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for i in range(1, 12):
        lines.append(f"- &a{i} [" + ", ".join([f"*a{i - 1}"] * 10) + "]")
    lines.append("- repo: *a11")
    listing(tmp_path, monkeypatch, "\n".join(lines) + "\n")
    t0 = time.time()
    assert progress.lane_repo(LF) == ""
    assert time.time() - t0 < 5


def test_only_owner_name_strings_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing(
        tmp_path,
        monkeypatch,
        f"- repo: {LF}\n  default: true\n- repo: acme/ok.name-1\n- repo: Shashkist\n"
        "- repo: https://evil.example/x\n- repo: 'a b/c'\n- 5\n",
    )
    assert progress.lane_repo("acme/ok.name-1") == "acme/ok.name-1"
    assert progress.lane_repo("Shashkist") is None
    assert progress.lane_repo("https://evil.example/x") is None


def test_entries_differing_only_in_case_are_one_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing(tmp_path, monkeypatch, "- repo: Acme/Widgets\n- repo: acme/widgets\n  default: true\n")
    assert progress._repo_list() == (("Acme/Widgets",), "Acme/Widgets")
    assert progress.lane_repo("ACME/WIDGETS") == ""


def test_the_default_is_the_listed_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing(tmp_path, monkeypatch, f"- repo: {LF}\n- repo: acme/w\n  default: true\n")
    assert progress.lane_repo("acme/W") == ""
    assert progress.lane_repo(LF) == LF
    assert progress.lane_repo(FACTORY) is None


def test_the_list_is_loaded_once_per_file_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = listing(tmp_path, monkeypatch, "- repo: acme/w\n  default: true\n")
    calls: list[str] = []
    real = progress._read_repo_list
    monkeypatch.setattr(progress, "_read_repo_list", lambda p: (calls.append(p), real(p))[1])
    for _ in range(5):
        progress.lane_repo("acme/w")
        progress.scrub("x")
    assert len(calls) == 1
    f.write_text("- repo: acme/other\n  default: true\n", encoding="utf-8")
    assert progress.lane_repo("acme/w") is None
    assert len(calls) == 2


def test_scrub_follows_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listing(tmp_path, monkeypatch, "- repo: acme/w.io\n  default: true\n")
    assert progress.scrub("see https://github.com/acme/w.io/pull/1") == (
        "see https://github.com/acme/w.io/pull/1"
    )
    assert progress.scrub("see https://github.com/acme/wXio/pull/1") == "see <url>"
    assert progress.scrub("see https://github.com/Shashkist/factory/pull/1") == "see <url>"
    assert progress.scrub("see github.com/Shashkist/factory/pull/1") == "see <url>"


def test_a_stored_empty_repo_renders_in_the_default_lane() -> None:
    ev = {
        "kind": "step",
        "at": "2999-01-01T00:00:00+00:00",
        "issue": 3,
        "repo": "",
        "agent": "a",
        "role": "implementer",
        "station": "build",
        "substep": "x",
        "status": "start",
        "detail": "",
        "title": "",
    }
    live = progress.render([ev, {**ev, "repo": FACTORY, "agent": "b"}])
    assert sorted((i["repo"], i["issue"]) for i in live["issues"]) == [("", 3), (FACTORY, 3)]


def test_add_stores_the_full_default_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ev = tmp_path / "e.jsonl"
    monkeypatch.setenv("LF_PROGRESS_FILE", str(ev))
    args = ["add", "--issue", "3", "--agent", "a", "--role", "implementer", "--station", "build"]
    assert progress.main([*args, "--substep", "x", "--status", "start"]) == 0
    assert f'"repo": "{LF}"' in ev.read_text(encoding="utf-8")


def run_file(args: list[str], env: dict[str, str], flags: list[str] | None = None) -> None:
    r = subprocess.run(
        [sys.executable, *(flags or []), progress.__file__, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_progress_runs_as_a_plain_file_without_site_packages(tmp_path: Path) -> None:
    out = tmp_path / "live.json"
    env = {**os.environ, "LF_PROGRESS_FILE": str(tmp_path / "e.jsonl")}
    env.pop("PYTHONPATH", None)
    env.pop("LF_REPOS_FILE", None)
    run_file(["pass-start"], env, ["-S"])
    run_file(["render", "--out", str(out)], env, ["-S"])
    assert out.exists()


def test_progress_runs_as_a_plain_file_with_a_list(tmp_path: Path) -> None:
    out = tmp_path / "live.json"
    repos = tmp_path / "r.yaml"
    repos.write_text(f"- repo: {FACTORY}\n  default: true\n", encoding="utf-8")
    env = {
        **os.environ,
        "LF_PROGRESS_FILE": str(tmp_path / "e.jsonl"),
        "LF_REPOS_FILE": str(repos),
    }
    env.pop("PYTHONPATH", None)
    run_file(["render", "--out", str(out)], env)
    assert out.exists()


def test_main_starts_no_watchdog_but_run_does(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(progress.hook_io, "start_watchdog", lambda code: started.append("hook"))
    monkeypatch.setattr(progress, "_start_publish_watchdog", lambda argv: started.append("pub"))
    monkeypatch.setattr(progress, "cmd_hook", lambda: None)
    monkeypatch.setattr(progress, "cmd_publish", lambda a: False)
    progress.main(["hook"])
    progress.main(["publish", "--key", "k", "--host", "h"])
    assert started == []
    progress.run(["hook"])
    progress.run(["publish", "--key", "k", "--host", "h"])
    progress.run(["pass-end", "--help"])
    assert started == ["hook", "pub"]
