"""Exam for #117: the progress hook keeps a small import path.

Under pass load a hook call took 7 to 15 s against a 5 s timeout. Bare interpreter start is
outside our control; the part we own is what `progress hook` imports. These tests run the real
hook in a subprocess and read the modules it loaded from `python -X importtime` (stderr).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

PAYLOAD = {
    "hook_event_name": "PreToolUse",
    "session_id": "sess117",
    "tool_name": "Bash",
    "tool_use_id": "toolu117",
    "tool_input": {"command": "echo hello"},
}

# Heavy modules the hook has no need of: the CLI tree and the YAML parser.
FORBIDDEN = (
    "yaml",
    "factory_tools.profile",
    "factory_tools.methodology",
    "factory_tools.claims",
    "factory_tools.worktrees",
    "factory_tools.pipeline",
)

# Cap on factory_tools.* modules. Today's minimum is the package, __main__ (or cli entry), the
# progress module and hook_io: 4. One spare for a small shared helper; far below the ~15+ the
# whole CLI tree loads now, so a re-grown import path is caught.
MAX_FACTORY_MODULES = 5

_IMPORT_LINE = re.compile(r"^import time:\s+\d+ \|\s+\d+ \|(\s*)(\S+)\s*$")


def _env(progress_file: Path | None, home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LF_")}
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = env["USERPROFILE"] = str(home)
    env.pop("PYTHONSTARTUP", None)
    if progress_file is not None:
        env["LF_PROGRESS_FILE"] = str(progress_file)
    return env


def _run(args: list[str], env: dict[str, str], stdin: str = "", importtime: bool = False):
    cmd = [sys.executable, "-P"]
    if importtime:
        cmd += ["-X", "importtime"]
    cmd += ["-m", "factory_tools", *args]
    return subprocess.run(
        cmd, input=stdin, capture_output=True, text=True, env=env, timeout=120, cwd=env["HOME"]
    )


def _loaded(stderr: str) -> set[str]:
    return {m.group(2) for line in stderr.splitlines() if (m := _IMPORT_LINE.match(line))}


@pytest.fixture
def hook_run(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    events = tmp_path / "progress.jsonl"
    r = _run(["progress", "hook"], _env(events, home), json.dumps(PAYLOAD), importtime=True)
    return r, events


def test_hook_still_appends_exactly_one_event_with_the_expected_fields(hook_run) -> None:
    r, events = hook_run
    assert r.returncode == 0, r.stderr[-500:]
    lines = events.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["kind"] == "worker"
    assert ev["event"] == "tool-start"
    assert ev["role"] == "manager"
    assert ev["tool"] == "Bash"
    assert ev["worker"] and ev["call"] and ev["at"]
    assert "echo hello" not in lines[0]  # allowlisted fields only


def test_the_import_probe_sees_the_hook_modules(hook_run) -> None:
    # guards the other tests: the probe must really list imports of this run
    r, _ = hook_run
    mods = _loaded(r.stderr)
    assert "json" in mods and "factory_tools.progress" in mods


@pytest.mark.parametrize("name", FORBIDDEN)
def test_hook_does_not_import_the_heavy_modules(hook_run, name: str) -> None:
    r, _ = hook_run
    bad = sorted(m for m in _loaded(r.stderr) if m == name or m.startswith(name + "."))
    assert not bad, f"progress hook imported {bad}"


def test_hook_import_path_stays_small(hook_run) -> None:
    r, _ = hook_run
    ours = sorted(m for m in _loaded(r.stderr) if m.split(".")[0] == "factory_tools")
    assert len(ours) <= MAX_FACTORY_MODULES, f"{len(ours)} factory_tools modules: {ours}"


def test_hook_without_progress_file_writes_nothing_and_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    r = _run(["progress", "hook"], _env(None, home), json.dumps(PAYLOAD))
    assert r.returncode == 0
    assert list(home.rglob("*")) == []
    assert list(tmp_path.glob("*.jsonl")) == []


def test_other_progress_subcommands_still_work(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    events = tmp_path / "progress.jsonl"
    env = _env(events, home)
    r = _run(
        [
            "progress", "add", "--repo", "Shashkist/factory", "--issue", "117",
            "--agent", "exam-writer-117", "--role", "exam-writer", "--station", "exam",
            "--substep", "write exam", "--status", "start",
        ],
        env,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr[-500:]
    ev = json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
    assert ev["issue"] == 117 and ev["substep"] == "write exam"
    out = tmp_path / "live.json"
    rr = _run(["progress", "render", "--out", str(out)], env)
    assert rr.returncode == 0, rr.stderr[-500:]
    assert json.loads(out.read_text(encoding="utf-8"))


def test_full_cli_still_loads_its_whole_tree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    r = _run(["--help"], _env(None, home))
    assert r.returncode == 0 and "progress" in r.stdout
