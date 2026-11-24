"""Issue #13: live progress and the crew view in the package (factory-tools progress ...).

The LF progress and crew tests are ported unchanged in tests/acceptance/ported/. This file holds the
new criteria, checked through the command line and the files the commands write.

How the exam supplies the project's repository list: the same way LF's scripts learn repositories,
a YAML list in the format of docs/factory/repos.yaml (`- repo: owner/name`, `default: true` on
the repository that events without --repo belong to), whose path comes from $LF_REPOS_FILE.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from helpers import ROOT, env, module_file

LF = "Shashkist/Learning_factory"
FACTORY = "Shashkist/factory"
FAKE_TOKEN = "fake-token-9f8e7d6c5b4a39281706-not-real"
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

REPOS_YAML = (
    f"- repo: {LF}\n  default: true\n"
    f"- repo: {FACTORY}\n  default: false\n"
    "- repo: acme/widgets\n  default: false\n"
)


class Sandbox:
    """An events file, a repos file and a scratch dir, passed to every child process."""

    def __init__(self, base: Path, with_repos: bool = True) -> None:
        self.base = base
        self.events = base / "progress.jsonl"
        self.repos = base / "repos.yaml"
        self.repos.write_text(REPOS_YAML, encoding="utf-8")
        self.with_repos = with_repos

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        e = env({"LF_PROGRESS_FILE": str(self.events)})
        e.pop("LF_CREW_DIR", None)
        if self.with_repos:
            e["LF_REPOS_FILE"] = str(self.repos)
        else:
            e.pop("LF_REPOS_FILE", None)
        if extra:
            e.update(extra)
        return e

    def cli(
        self, *args: str, stdin: str = "", extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "factory_tools", "progress", *args],
            cwd=self.base,
            env=self.env(extra),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def add(
        self,
        issue: int | None,
        *,
        repo: str | None = None,
        agent: str = "impl-1",
        role: str = "implementer",
        station: str = "build",
        substep: str = "unit tests",
        status: str = "start",
        detail: str | None = None,
        title: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        a = ["add", "--agent", agent, "--role", role, "--station", station, "--substep", substep]
        a += ["--status", status]
        if issue is not None:
            a += ["--issue", str(issue)]
        if repo is not None:
            a += ["--repo", repo]
        if title is not None:
            a += ["--title", title]
        if detail is not None:
            a += ["--detail-file", "-"]
        return self.cli(*a, stdin=detail or "")

    def render(self, extra: dict[str, str] | None = None) -> dict[str, Any]:
        out = self.base / "live.json"
        r = self.cli("render", "--out", str(out), extra=extra)
        assert r.returncode == 0, r.stderr
        assert out.exists(), "render wrote no file"
        data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
        return data


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def lanes(live: dict[str, Any]) -> list[tuple[str, int]]:
    return sorted((i["repo"], i["issue"]) for i in live["issues"])


# ---- 1. the commands exist -------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd", ["add", "hook", "pass-start", "pass-end", "runner-state", "render", "publish"]
)
def test_progress_subcommand_exists(cmd: str, sb: Sandbox) -> None:
    r = sb.cli(cmd, "--help")
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_progress_group_is_listed_by_the_cli(sb: Sandbox) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "factory_tools", "--help"],
        cwd=sb.base,
        env=sb.env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0 and "progress" in r.stdout


def test_modules_exist_as_files() -> None:
    for m in ("progress", "hook_io", "crew"):
        assert module_file(f"factory_tools.{m}") is not None, f"src/factory_tools/{m}.py is missing"


def test_commands_write_and_render_a_pass(sb: Sandbox) -> None:
    assert sb.cli("pass-start", "--pass-no", "4", "--budget", "9").returncode == 0
    assert (
        sb.add(
            13, repo=FACTORY, title="Tools slice 2", detail="12 passed", status="done"
        ).returncode
        == 0
    )
    assert (
        sb.cli("runner-state", "--state", "paused", "--note", "PAUSE file present").returncode == 0
    )
    live = sb.render()
    assert live["runner"]["state"] == "paused" and live["runner"]["pass_no"] == 4
    assert live["issues"][0]["title"] == "Tools slice 2"
    assert sb.cli("pass-end", "--result", "done").returncode == 0
    assert sb.render()["runner"]["state"] == "idle"


def test_hook_records_only_inside_a_factory_run(sb: Sandbox) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_use_id": "t1",
            "tool_input": {"command": "cat /root/.env"},
        }
    )
    outside = sb.env()
    outside.pop("LF_PROGRESS_FILE")
    outside["HOME"] = outside["USERPROFILE"] = str(sb.base / "home")
    r = subprocess.run(
        [sys.executable, "-m", "factory_tools", "progress", "hook"],
        cwd=sb.base,
        env=outside,
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert not sb.events.exists() and not (sb.base / "home").exists()
    assert sb.cli("pass-start").returncode == 0
    r = sb.cli("hook", stdin=payload)
    assert r.returncode == 0
    workers = {w["role"]: w for w in sb.render()["workers"]}
    assert workers["manager"]["tool"] == "Bash"
    assert ".env" not in json.dumps(sb.render())


def test_publish_never_fails_the_caller(sb: Sandbox, tmp_path: Path) -> None:
    sb.cli("pass-start")
    r = sb.cli(
        "publish",
        "--key",
        str(tmp_path / "no-such-key"),
        "--host",
        "nobody@127.0.0.1",
        "--force",
        extra={"LF_PUBLISH_TIMEOUT_S": "5"},
    )
    assert r.returncode == 0


# ---- 2. default repository and lanes keyed by repository and issue ---------------------------


def test_event_without_repo_works_as_today(sb: Sandbox) -> None:
    assert sb.add(12).returncode == 0
    live = sb.render()
    assert lanes(live) == [("", 12)]  # the default repository is shown as ""
    agent = live["agents"][0]
    assert agent["repo"] == "" and agent["substeps"][0]["repo"] == ""


def test_default_repository_comes_from_the_repository_list(tmp_path: Path) -> None:
    box = Sandbox(tmp_path)
    box.repos.write_text(
        f"- repo: {FACTORY}\n  default: true\n- repo: {LF}\n  default: false\n", encoding="utf-8"
    )
    assert box.add(12).returncode == 0
    assert box.add(12, repo=LF, agent="impl-2").returncode == 0
    live = box.render()
    assert lanes(live) == [("", 12), (LF, 12)]


def test_event_without_repo_works_without_any_repository_list(tmp_path: Path) -> None:
    box = Sandbox(tmp_path, with_repos=False)
    assert box.add(12).returncode == 0
    assert lanes(box.render()) == [("", 12)]


def test_same_issue_number_in_two_repositories_is_two_lanes(sb: Sandbox) -> None:
    assert sb.add(12, agent="impl-lf", station="build").returncode == 0
    assert sb.add(12, repo=FACTORY, agent="impl-f", station="check").returncode == 0
    live = sb.render()
    assert lanes(live) == [("", 12), (FACTORY, 12)]
    stations = {i["repo"]: i["station"] for i in live["issues"]}
    assert stations == {"": "build", FACTORY: "check"}
    by_agent = {a["id"]: a for a in live["agents"]}
    assert by_agent["impl-lf"]["repo"] == "" and by_agent["impl-f"]["repo"] == FACTORY


def test_explicit_default_repository_is_the_same_lane_as_no_repo(sb: Sandbox) -> None:
    assert sb.add(12).returncode == 0
    assert sb.add(12, repo=LF.lower(), agent="impl-2").returncode == 0
    assert lanes(sb.render()) == [("", 12)]


def test_repository_names_are_case_insensitive_and_canonical(sb: Sandbox) -> None:
    assert sb.add(12, repo="SHASHKIST/Factory").returncode == 0
    assert lanes(sb.render()) == [(FACTORY, 12)]


def test_unscoped_close_does_not_cross_lanes(sb: Sandbox) -> None:
    sb.add(12, agent="m", role="manager", station="check", substep="ci wait")
    sb.add(12, repo=FACTORY, agent="m", role="manager", station="check", substep="ci wait")
    sb.add(
        None,
        repo=FACTORY,
        agent="m",
        role="manager",
        station="check",
        substep="ci wait",
        status="done",
    )
    rows = {
        (s["repo"], s["issue"]): s["status"]
        for a in sb.render()["agents"]
        for s in a["substeps"]
        if s["substep"] == "ci wait"
    }
    assert rows == {("", 12): "start", (FACTORY, 12): "done"}


def test_a_repository_listed_for_the_project_gets_its_own_lane(sb: Sandbox) -> None:
    assert sb.add(12, repo="acme/widgets").returncode == 0
    assert lanes(sb.render()) == [("acme/widgets", 12)]


def test_a_repository_not_in_the_list_is_rejected_and_never_rendered(sb: Sandbox) -> None:
    r = sb.add(5, repo="evil/secret-project")
    assert r.returncode == 0  # never fails the caller
    assert "evil/secret-project" not in json.dumps(sb.render())
    assert not sb.events.exists()
    assert r.stderr.strip() != ""


def test_hand_edited_event_with_a_foreign_repo_is_dropped(sb: Sandbox) -> None:
    ev = {
        "kind": "step",
        "at": "2999-01-01T00:00:00+00:00",
        "issue": 1,
        "repo": "leak/name",
        "agent": "a",
        "role": "implementer",
        "station": "build",
        "substep": "x",
        "status": "start",
        "detail": "",
        "title": "",
    }
    sb.events.write_text(json.dumps(ev) + "\n", encoding="utf-8")
    assert "leak/name" not in json.dumps(sb.render())


# ---- 3. redaction ----------------------------------------------------------------------------

BACKSLASH = chr(92)
WIN_PATH = "C:" + BACKSLASH + "Users" + BACKSLASH + "someone" + BACKSLASH + "log.txt"


def details(live: dict[str, Any]) -> list[str]:
    out = [s["detail"] for a in live["agents"] for s in a["substeps"]]
    out += [e["detail"] for e in live["log"]]
    return out


def test_redaction_keeps_links_to_the_project_repositories(sb: Sandbox) -> None:
    keep = [
        "https://github.com/Shashkist/factory/pull/3",
        "https://github.com/Shashkist/Learning_factory/pull/9",
        "https://github.com/acme/widgets/pull/4",
    ]
    for i, url in enumerate(keep):
        assert sb.add(i + 1, detail=f"see {url}", agent=f"impl-{i}").returncode == 0
    ds = details(sb.render())
    for url in keep:
        assert f"see {url}" in ds, f"{url} was redacted: {ds}"


def test_redaction_keeps_the_factory_link_without_a_repository_list(tmp_path: Path) -> None:
    box = Sandbox(tmp_path, with_repos=False)
    url = "https://github.com/Shashkist/factory/pull/3"
    assert box.add(3, detail=f"opened {url}").returncode == 0
    assert f"opened {url}" in details(box.render())


def test_redaction_still_removes_foreign_urls_emails_and_paths(sb: Sandbox) -> None:
    text = (
        "PR https://github.com/Shashkist/factory/pull/3 "
        "from https://evil.example/a and https://github.com/someone/else/pull/1 "
        f"mail me@x.com at 10.1.2.3 in {WIN_PATH} and /home/user/.env"
    )
    assert sb.add(3, repo=FACTORY, detail=text).returncode == 0
    live = sb.render()
    blob = json.dumps(live)
    assert "github.com/Shashkist/factory/pull/3" in blob
    for leak in (
        "evil.example",
        "someone/else",
        "me@x.com",
        "10.1.2.3",
        "Users",
        "/home/user",
        ".env",
    ):
        assert leak not in blob, leak
    d = next(d for d in details(live) if "pull/3" in d)
    assert "<url>" in d and "<email>" in d and "<path>" in d


def test_a_repository_that_is_not_listed_is_redacted_even_when_it_looks_similar(
    sb: Sandbox,
) -> None:
    lookalikes = [
        "https://github.com/Shashkist/factory-evil/x",
        "https://github.com/Shashkist/factory/../../someone/else/pull/1",
        "https://github.com/Shashkist/factory/%2e%2e/x",
        "https://github.com/acme/widgets-evil/x",
        "https://github.com/acme/other/pull/1",
        "github.com/acme/widgets/../../someone/else",
    ]
    for i, url in enumerate(lookalikes):
        assert sb.add(i + 1, detail=f"see {url}", agent=f"impl-{i}").returncode == 0
    ds = details(sb.render())
    assert ds and all(d == "see <url>" for d in ds[: len(lookalikes)]), ds


def test_the_set_of_allowed_repositories_follows_the_project_list(tmp_path: Path) -> None:
    box = Sandbox(tmp_path)
    box.repos.write_text("- repo: acme/widgets\n  default: true\n", encoding="utf-8")
    assert box.add(1, detail="see https://github.com/acme/widgets/pull/4").returncode == 0
    assert (
        box.add(2, detail="see https://github.com/acme/gadgets/pull/4", agent="impl-2").returncode
        == 0
    )
    ds = details(box.render())
    assert "see https://github.com/acme/widgets/pull/4" in ds
    assert "see <url>" in ds


# ---- 4. no command reads, prints or stores a token -------------------------------------------

SOURCES = ("progress", "hook_io", "crew")
TOKEN_PATTERNS = [
    r"GH_TOKEN",
    r"GITHUB_TOKEN",
    r"ANTHROPIC_API_KEY",
    r"CLAUDE_CODE_OAUTH",
    r"OAUTH",
    r"auth\s+token",
    r"\.netrc",
    r"\.credentials",
    r"credential",
    r"GITHUB_PAT",
    r"secrets\.",
]


@pytest.mark.parametrize("name", SOURCES)
def test_modules_contain_no_token_handling(name: str) -> None:
    path = module_file(f"factory_tools.{name}")
    assert path is not None, f"src/factory_tools/{name}.py is missing"
    text = path.read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    for pat in TOKEN_PATTERNS:
        assert not re.search(pat, code, re.IGNORECASE), f"{name}.py handles {pat}"
    for m in re.finditer(r"os\.environ(?:\.get)?\(?\[?\s*[\"'](\w+)[\"']", code):
        var = m.group(1)
        assert not re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL", var, re.IGNORECASE), var


def test_no_command_prints_or_stores_a_token_from_the_environment(
    sb: Sandbox, tmp_path: Path
) -> None:
    tokens = {v: FAKE_TOKEN for v in TOKEN_VARS}
    crew_dir = tmp_path / "proj"
    now = "2026-11-15T12:00:00Z"
    sess = crew_dir / "sess-1.jsonl"
    crew_dir.mkdir()
    sess.write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": now,
                "message": {
                    "model": "m",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": f"echo {FAKE_TOKEN}", "description": "Watch CI"},
                        }
                    ],
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "user",
                "timestamp": now,
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": FAKE_TOKEN}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    outputs: list[str] = []

    def run(*args: str, stdin: str = "") -> None:
        r = sb.cli(*args, stdin=stdin, extra={**tokens, "LF_CREW_DIR": str(crew_dir)})
        outputs.extend([r.stdout, r.stderr])

    run("pass-start", "--pass-no", "1")
    run(
        "add",
        "--issue",
        "13",
        "--repo",
        FACTORY,
        "--agent",
        "impl-13",
        "--role",
        "implementer",
        "--station",
        "build",
        "--substep",
        "unit tests",
        "--status",
        "start",
        "--detail-file",
        "-",
        stdin="ran with no secrets",
    )
    run(
        "hook",
        stdin=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "tool_name": "Bash",
                "tool_use_id": "t1",
                "tool_input": {"command": f"echo {FAKE_TOKEN}"},
            }
        ),
    )
    run("runner-state", "--state", "idle", "--note", "between passes")
    run("render", "--out", str(sb.base / "live.json"))
    run("publish", "--key", str(sb.base / "no-key"), "--host", "nobody@127.0.0.1", "--force")
    run("pass-end")
    # a bad invocation prints a usage error: it must not echo the environment either
    run("add", "--issue", "x")

    for out in outputs:
        assert FAKE_TOKEN not in out
    stored = [p for p in sb.base.rglob("*") if p.is_file()]
    assert sb.events in stored and (sb.base / "live.json") in stored
    for p in stored:
        if p == sess:
            continue
        assert FAKE_TOKEN not in p.read_text(encoding="utf-8", errors="replace"), p
    assert not any(FAKE_TOKEN in str(os.environ.get(v, "")) for v in TOKEN_VARS)


# ---- review round 1 (D8): cases that wrong implementations passed --------------------------------


def write_repos(box: Sandbox, text: str) -> None:
    box.repos.write_text(text, encoding="utf-8")


def test_listed_name_with_a_dot_is_matched_literally(tmp_path: Path) -> None:
    box = Sandbox(tmp_path)
    write_repos(box, f"- repo: {LF}\n  default: true\n- repo: acme/widgets.io\n  default: false\n")
    assert box.add(1, detail="see https://github.com/acme/widgets.io/pull/4").returncode == 0
    assert (
        box.add(
            2, detail="see https://github.com/acme/widgetsXio/pull/4", agent="impl-2"
        ).returncode
        == 0
    )
    assert (
        box.add(3, detail="see github.com/acme/widgetsXio/pull/4", agent="impl-3").returncode == 0
    )
    ds = details(box.render())
    assert "see https://github.com/acme/widgets.io/pull/4" in ds
    assert "see <url>" in ds
    assert not any("widgetsXio" in d for d in ds), ds
    assert box.add(4, repo="acme/widgets.io", agent="impl-4").returncode == 0
    assert box.add(5, repo="acme/widgetsXio", agent="impl-5").returncode == 0
    assert lanes(box.render()) == [("", 1), ("", 2), ("", 3), ("acme/widgets.io", 4)]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Shashkist/factory.evil.com/x",
        "github.com/Shashkist/factory.evil.com",
        "https://github.com/Shashkist/factory-evil/pull/1",
        "https://github.com/Shashkist/Learning_factory.evil.com/x",
        "github.com/Shashkist/Learning_factory.evil.com",
    ],
)
def test_lookalike_repository_links_are_redacted(sb: Sandbox, url: str) -> None:
    assert sb.add(3, repo=FACTORY, detail=f"see {url}").returncode == 0
    assert details(sb.render())[0] == "see <url>"


def _spawn_hook(sb: Sandbox, extra: dict[str, str]) -> float:
    p = subprocess.Popen(
        [sys.executable, "-m", "factory_tools", "progress", "hook"],
        cwd=sb.base,
        env=sb.env(extra),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    t0 = time.time()
    try:
        assert p.wait(timeout=20) == 0
    finally:
        p.kill()
        if p.stdin:
            p.stdin.close()
    return time.time() - t0


def test_hook_watchdog_ends_a_hook_whose_stdin_never_closes(sb: Sandbox) -> None:
    # the stdin read bound is far away, so only the process watchdog can end this hook in time
    assert _spawn_hook(sb, {"LF_HOOK_STDIN_TIMEOUT": "120", "LF_HOOK_WATCHDOG_S": "2"}) < 20
    assert not sb.events.exists()


def test_hook_stdin_bound_applies_through_the_documented_entry_point(sb: Sandbox) -> None:
    assert _spawn_hook(sb, {"LF_HOOK_STDIN_TIMEOUT": "1", "LF_HOOK_WATCHDOG_S": "120"}) < 20
    assert not sb.events.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="needs a fifo")
def test_publish_watchdog_ends_a_publish_that_hangs_before_the_copy(sb: Sandbox) -> None:
    # the events file never reads (a fifo with no writer): only the watchdog can end publish
    os.mkfifo(sb.events)
    key = sb.base / "key"
    t0 = time.time()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "factory_tools",
            "progress",
            "publish",
            "--key",
            str(key),
            "--host",
            "nobody@127.0.0.1",
            "--force",
        ],
        cwd=sb.base,
        env=sb.env({"LF_PUBLISH_TIMEOUT_S": "1"}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert time.time() - t0 < 40
    assert r.returncode == 0
    state = Path(str(key) + ".last")
    assert state.exists() and state.read_text().startswith("fail ")


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX stand-in")
def test_publish_is_bounded_when_the_remote_copy_never_returns(sb: Sandbox) -> None:
    bin_dir = sb.base / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "ssh"
    stand_in.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    stand_in.chmod(0o755)
    sb.cli("pass-start")
    key = sb.base / "key"
    t0 = time.time()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "factory_tools",
            "progress",
            "publish",
            "--key",
            str(key),
            "--host",
            "nobody@127.0.0.1",
            "--force",
        ],
        cwd=sb.base,
        env=sb.env(
            {"LF_PUBLISH_TIMEOUT_S": "2", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert time.time() - t0 < 30
    assert r.returncode == 0
    assert Path(str(key) + ".last").read_text().startswith("fail ")


def test_plain_file_run_needs_only_the_standard_library(tmp_path: Path) -> None:
    out = tmp_path / "live.json"
    e = env({"LF_PROGRESS_FILE": str(tmp_path / "progress.jsonl")})
    e.pop("PYTHONPATH", None)
    e.pop("LF_REPOS_FILE", None)
    script = ROOT / "src" / "factory_tools" / "progress.py"
    r = subprocess.run(
        [sys.executable, "-S", str(script), "render", "--out", str(out)],
        cwd=tmp_path,
        env=e,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists() and json.loads(out.read_text(encoding="utf-8"))["schema"] == 1


def alias_bomb(levels: int = 9) -> str:
    lines = ["- &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for i in range(1, levels):
        lines.append(f"- &a{i} [" + ", ".join([f"*a{i - 1}"] * 10) + "]")
    lines.append(f"- repo: *a{levels - 1}")
    return "\n".join(lines) + "\n"


def many_entries() -> str:
    body = "".join(f"- repo: acme/r{i}\n  default: false\n" for i in range(4000))
    return body + f"- repo: {LF}\n  default: true\n"


BAD_LISTS = {
    "alias-bomb": alias_bomb(),
    "deep-nesting": "[" * 20000 + "]" * 20000 + "\n",
    "oversized": many_entries(),
}


@pytest.mark.parametrize("kind", sorted(BAD_LISTS))
def test_a_bad_repository_file_falls_back_to_the_builtin_pair(tmp_path: Path, kind: str) -> None:
    box = Sandbox(tmp_path)
    write_repos(box, BAD_LISTS[kind])
    t0 = time.time()
    a = box.add(7, repo=FACTORY, detail="see https://github.com/Shashkist/factory/pull/3")
    b = box.add(8, agent="impl-2", detail="see https://github.com/acme/r5/pull/1")
    c = box.add(9, repo="acme/r5", agent="impl-3")
    live = box.render()
    assert time.time() - t0 < 30
    assert a.returncode == b.returncode == c.returncode == 0
    assert lanes(live) == [("", 8), (FACTORY, 7)]  # the event is kept, the unlisted lane is not
    ds = details(live)
    assert "see https://github.com/Shashkist/factory/pull/3" in ds
    assert "see <url>" in ds


def test_entries_that_are_not_owner_name_strings_are_ignored(tmp_path: Path) -> None:
    box = Sandbox(tmp_path)
    write_repos(
        box,
        f"- repo: {LF}\n  default: true\n"
        f"- repo: {FACTORY}\n"
        "- repo: Shashkist\n"
        "- repo: me@x.com\n"
        "- repo: https://evil.example/x\n"
        "- repo: 123\n"
        "- repo: [a, b]\n"
        "- repo: a/b/c\n"
        "- repo: {a: b}\n"
        "- not-an-entry\n",
    )
    for i, bad in enumerate(["Shashkist", "me@x.com", "https://evil.example/x", "a/b/c"]):
        assert box.add(20 + i, repo=bad, agent=f"bad-{i}").returncode == 0
    assert (
        box.add(
            1, repo=FACTORY, detail="see https://github.com/Shashkist/factory/pull/3"
        ).returncode
        == 0
    )
    assert (
        box.add(
            2, agent="impl-2", detail="see https://github.com/Shashkist/other/pull/1"
        ).returncode
        == 0
    )
    assert (
        box.add(3, agent="impl-3", detail="see https://github.com/evil.example/x").returncode == 0
    )
    live = box.render()
    blob = json.dumps(live)
    assert "me@x.com" not in blob and "evil.example" not in blob
    assert lanes(live) == [("", 2), ("", 3), (FACTORY, 1)]
    ds = details(live)
    assert "see https://github.com/Shashkist/factory/pull/3" in ds
    assert not any("Shashkist/other" in d for d in ds)


def test_event_without_repo_keeps_its_own_repository_when_the_list_changes(tmp_path: Path) -> None:
    box = Sandbox(tmp_path, with_repos=False)  # list unset: the built-in default is LF
    assert box.add(12).returncode == 0
    box.with_repos = True
    write_repos(box, f"- repo: {FACTORY}\n  default: true\n- repo: {LF}\n  default: false\n")
    assert lanes(box.render()) == [(LF, 12)]  # not re-attributed to the new default
    assert box.add(12, agent="impl-2").returncode == 0  # written with FACTORY as the default
    box.with_repos = False
    assert lanes(box.render()) == [("", 12), (FACTORY, 12)]
