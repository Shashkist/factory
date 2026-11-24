"""Live progress of the factory: who is doing what, right now.

Two event sources, both written by the factory itself (never read from Claude Code's transcripts):
  * steps: the manager and every agent report their sub-steps (`add`), in factory words;
  * hooks: Claude Code hooks (PreToolUse, PostToolUse, Notification, SubagentStop, Stop,
    SessionStart) loaded only for factory runs (`--settings <the factory's hook settings>`)
    record which worker is busy with which kind of tool (`hook`). Hooks record only allowlisted
    fields: no tool input, no text from prompts, titles, paths or branches.

`render` builds live.json from an explicit public schema (the publish step is the redaction
boundary), and `publish` pushes it with a key that can only write that one file.

  python -m factory_tools progress add --issue 46 --agent implementer-46 --role implementer \
      --station build --substep "unit tests" --status start [--detail-file -]
  python -m factory_tools progress hook < hook-event.json        (from Claude Code hooks)
  python -m factory_tools progress pass-start | pass-end | runner-state --state idle
  python -m factory_tools progress render --out live.json
  python -m factory_tools progress publish --key KEY --host root@HOST

Events file: $LF_PROGRESS_FILE, else ~/.lf-factory/progress.jsonl. `hook` does nothing unless
$LF_PROGRESS_FILE is set (only factory runs set it). Nothing here ever fails the caller.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __name__ == "__main__" and not __package__:
    # run as a plain file, with only the standard library: the package is found from the file's
    # place, and the script's own folder must not shadow the standard library
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from factory_tools import hook_io  # noqa: E402

SCHEMA = 1
STATIONS = ("plan", "exam", "build", "check", "ship")
STATUSES = ("start", "done", "fail", "wait", "skip", "stopped")
ROLES = (
    "manager",
    "planner",
    "researcher",
    "exam-writer",
    "implementer",
    "reviewer",
    "scribe",
    "runner",
)
WORKER_ROLES = ("manager", "researcher", "exam-writer", "implementer", "reviewer", "scribe")
TOOL_CATEGORIES = {
    "Bash": "Bash",
    "PowerShell": "Bash",
    "Read": "Read",
    "Edit": "Edit",
    "Write": "Write",
    "MultiEdit": "Edit",
    "NotebookEdit": "Edit",
    "Grep": "Search",
    "Glob": "Search",
    "Agent": "Agent",
    "Task": "Agent",
    "WebSearch": "Web",
    "WebFetch": "Web",
    "Skill": "Skill",
    "TodoWrite": "Plan",
}
DEFAULT_REPOS = ("Shashkist/Learning_factory", "Shashkist/factory")
DEFAULT_REPO = DEFAULT_REPOS[0]  # without a repository list, events without a repo belong here


REPOS_FILE_MAX = 64 * 1024
_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_RepoList = tuple[tuple[str, ...], str | None]
_repo_cache: dict[tuple[str, int, int], _RepoList] = {}


def _read_repo_list(path: str) -> _RepoList:
    """Parse the list in `path`; it is not trusted: a big file, or anything but `owner/name`
    strings, is ignored. Raises on any problem."""
    import yaml  # only needed when a list is given

    if os.stat(path).st_size > REPOS_FILE_MAX:
        raise ValueError("file over 64 KB")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("not a list")
    names: dict[str, str] = {}  # lower case -> first spelling
    default: str | None = None
    for row in data:
        name = row.get("repo") if isinstance(row, dict) else None
        if not isinstance(name, str) or not _REPO_NAME.fullmatch(name):
            continue
        canon = names.setdefault(name.lower(), name)
        if default is None and row.get("default") is True:
            default = canon
    if not names:
        raise ValueError("no owner/name entries")
    return tuple(names.values()), default


def _repo_list() -> _RepoList:
    """The listed repositories and the default one, from the YAML list in $LF_REPOS_FILE
    (`- repo: owner/name`, `default: true`), loaded once per process for one file state; the
    built-in pair when the file is absent or unusable."""
    path = os.environ.get("LF_REPOS_FILE")
    if not path:
        return DEFAULT_REPOS, DEFAULT_REPO
    try:
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
    except OSError:
        key = (path, -1, -1)
    if key not in _repo_cache:
        try:
            _repo_cache[key] = _read_repo_list(path)
        except Exception as exc:
            print(
                f"factory_progress: repository list ignored ({type(exc).__name__}); "
                "using the built-in pair",
                file=sys.stderr,
            )
            _repo_cache[key] = (DEFAULT_REPOS, DEFAULT_REPO)
    return _repo_cache[key]


def canon_repo(repo: object) -> str | None:
    """The full canonical name of a listed repository (the default's name when none is given),
    None for anything else (names are compared case-insensitively)."""
    repos, default = _repo_list()
    if not repo:
        return default or ""
    if not isinstance(repo, str):
        return None
    return {r.lower(): r for r in repos}.get(repo.lower())


def lane_repo(repo: object) -> str | None:
    """The lane of a stored repository: "" for the default repository (also a stored ""), its
    canonical name for another listed one, None for anything unlisted."""
    if not repo:
        return ""
    name = canon_repo(repo)
    if name is None:
        return None
    return "" if name == _repo_list()[1] else name


DETAIL_MAX = 160
LOG_TAIL = 60
ABANDONED = timedelta(
    minutes=15
)  # a tool with no PostToolUse after this long is not shown as running
HEARTBEAT_S = 60  # publish at least this often even when nothing changed
# The server's ufw LIMIT rule rejects a 7th new SSH connection within 30 s from one address, and
# every rejected attempt renews the block. Keep the publisher to 2 connections per 30 s and back
# off on failure.
MIN_GAP_S = 15  # at most one push per 15 s, even when the content keeps changing
BACKOFF_S = 90  # after a failed push, wait this long before trying again
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_SLUG = re.compile(r"^[\w .:/#()+\-]{1,60}$", re.UNICODE)
_SCRUB_FIXED = [
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    # any other scheme (sftp, smb, file, s3, ssh, redis ...); http(s) is decided by `other` below
    (re.compile(r"(?<![\w+.-])(?!https?://)[a-z][a-z0-9+.-]*://\S*", re.IGNORECASE), "<url>"),
    (re.compile(r"(?<![:/\w])//[\w.-]+\S*"), "<url>"),  # scheme-relative //host/x
    # UNC: two slashes of either kind, at least one a backslash, then the host
    (re.compile(r"(?:\\[\\/]|/\\)[^\s\\/]+(?:[\\/]\S*)?"), "<path>"),
    (re.compile(r"(?<![A-Z0-9])A(?:KI|SI)A[0-9A-Z]{16}(?![A-Z0-9])"), "<redacted>"),
]
_SCRUB_PATHS = [
    (re.compile(r"(?:[A-Za-z]:\\|/(?:root|home|Users|etc|var|tmp|opt|srv|c)/)\S*"), "<path>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "<redacted>"),
]


@functools.cache
def _scrub_rules(repos: tuple[str, ...]) -> list[tuple[re.Pattern[str], str]]:
    """The URL rules for a repository list: links to a listed repository survive, other URLs go."""
    listed = "".join(rf"(?!{re.escape(r)}(?:[/?#\s]|$))" for r in repos)
    ok = "".join(rf"(?!github\.com/{re.escape(r)}(?:[/?#\s]|$))" for r in repos)
    own = r"(?!(?:[\w-]+\.)*shashkist\.com(?::\d+)?(?:[/?#\s]|$))"
    other = re.compile(rf"https?://{ok}{own}\S+", re.IGNORECASE)
    traversal = re.compile(
        r"(?:https?://|\bgithub\.com/)\S*"
        r"(?:/\.\.|%2e|%25|%5c|%2f|%c0%ae|\\|&#0*46;|&#x0*2e;|/[．｡。])\S*",
        re.IGNORECASE,
    )
    bare = re.compile(rf"\bgithub\.com/{listed}\S+", re.IGNORECASE)
    return [
        *_SCRUB_FIXED,
        (other, "<url>"),
        (traversal, "<url>"),
        (bare, "<url>"),
        *_SCRUB_PATHS,
    ]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def issue_no(v: object) -> int:
    """A positive issue number, or 0 for anything else ("0", None, text)."""
    try:
        n = int(v or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def events_path() -> Path:
    p = os.environ.get("LF_PROGRESS_FILE")
    return Path(p) if p else Path.home() / ".lf-factory" / "progress.jsonl"


def clean(text: str, limit: int = DETAIL_MAX) -> str:
    """Untrusted text: no control characters, capped. The page renders it as text only."""
    # scrubbed before the cut (whole forms become placeholders), and again by `render`
    text = scrub(_CTRL.sub(" ", text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if not text[limit - 1].isspace():
        # the cut is inside a word: drop it whole, so no head of a key, token or address is left
        cut = cut.rsplit(None, 1)[0] if cut.split(None, 1)[1:] else ""
    return cut.rstrip() + "…"


def scrub(text: str) -> str:
    """Public text: hosts, emails, foreign URLs, absolute paths and key-like strings removed."""
    for rx, repl in _scrub_rules(_repo_list()[0]):
        text = rx.sub(repl, text)
    return text


def short_id(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:8] if raw else "-"


def append(event: dict[str, Any]) -> None:
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events() -> list[dict[str, Any]]:
    path = events_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def current_pass(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events since the last pass-start (the whole file if there is none)."""
    start = 0
    for i, e in enumerate(events):
        if e.get("kind") == "pass-start":
            start = i
    return events[start:]


# ---- hooks -> worker events (allowlisted fields only) -------------------------------------------


def hook_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    name = payload.get("hook_event_name", "")
    agent_type = payload.get("agent_type") or ""
    role = agent_type if agent_type in WORKER_ROLES else ("agent" if agent_type else "manager")
    worker = short_id(payload.get("agent_id") or payload.get("session_id") or "")
    base = {"kind": "worker", "at": now(), "worker": worker, "role": role}
    if name in ("PreToolUse", "PostToolUse"):
        tool = payload.get("tool_name", "")
        cat = TOOL_CATEGORIES.get(tool, "MCP" if tool.startswith("mcp__") else "Other")
        return {
            **base,
            "event": "tool-start" if name == "PreToolUse" else "tool-end",
            "tool": cat,
            "call": short_id(payload.get("tool_use_id", "")),
        }
    if name == "Notification":
        return {**base, "event": "waiting"}
    if name in ("SubagentStop", "Stop"):
        return {**base, "event": "stopped" if name == "SubagentStop" else "idle"}
    if name == "SessionStart":
        return {**base, "event": "session-start"}
    return None


_TOOL_NAMES = {*TOOL_CATEGORIES.values(), "MCP", "Other"}


def _typed_worker_event(e: dict[str, Any]) -> dict[str, Any]:
    """A worker event from the file, with its free fields held to their allowlists."""
    wid, role, tool = str(e.get("worker", "")), e.get("role"), e.get("tool")
    return {
        **e,
        "worker": scrub(wid) if re.fullmatch(r"[\w.-]{1,40}", wid) else short_id(wid),
        "role": role if role in (*WORKER_ROLES, "agent") else "agent",
        "tool": tool if tool in _TOOL_NAMES else "Other",
    }


def _int_or_none(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def render_workers(evs: list[dict[str, Any]], at: datetime) -> list[dict[str, Any]]:
    workers: dict[str, dict[str, Any]] = {}
    for e in evs:
        if e.get("kind") != "worker":
            continue
        e = _typed_worker_event(e)
        w = workers.setdefault(
            e["worker"],
            {
                "id": e["worker"],
                "role": e["role"],
                "state": "idle",
                "tool": None,
                "tools": {},
                "started": e["at"],
                "last": e["at"],
                "_open": {},
            },
        )
        w["last"] = e["at"]
        if w["role"] in ("manager", "agent") and e["role"] not in ("manager", "agent"):
            w["role"] = e["role"]
        ev = e["event"]
        if ev == "tool-start":
            w["_open"][e.get("call") or e["at"]] = (e["tool"], e["at"])
            w["tools"][e["tool"]] = w["tools"].get(e["tool"], 0) + 1
            w["state"] = "busy"
        elif ev == "tool-end":
            w["_open"].pop(e.get("call"), None) if e.get("call") in w["_open"] else (
                w["_open"].popitem() if w["_open"] else None
            )
            w["state"] = "busy" if w["_open"] else "thinking"
        elif ev == "waiting":
            w["state"] = "waiting"
        elif ev == "stopped":
            w["state"], w["_open"] = "finished", {}
        elif ev == "idle":
            w["state"], w["_open"] = "idle", {}
    out = []
    for w in workers.values():
        live = {k: v for k, v in w["_open"].items() if at - parse(v[1]) < ABANDONED}
        w["tool"] = next(iter(live.values()))[0] if live else None
        if w["state"] == "busy" and not live:
            w["state"] = "thinking"
        del w["_open"]
        out.append(w)
    return out


# ---- render: the public schema ------------------------------------------------------------------


def render_crew(at: datetime) -> list[dict[str, Any]]:
    """Agents and subagents from the transcripts (factory_tools.crew). Off unless LF_CREW_DIR is set
    (the laptop runner sets it), so tests and other machines never read anyone's transcripts."""
    d = os.environ.get("LF_CREW_DIR")
    if not d:
        return []
    try:
        from factory_tools import crew

        pf = os.environ.get("LF_PROGRESS_FILE")
        return crew.build(Path(d), at, scrub, Path(pf + ".crew-cache.json") if pf else None)
    except Exception:  # noqa: BLE001 - the crew view must never break the publisher
        return []


def render(events: list[dict[str, Any]]) -> dict[str, Any]:
    # the redaction boundary: step events of a repository that is not on the allowlist are dropped,
    # names normalised
    evs = [
        {**e, "repo": lane_repo(e.get("repo"))} if e.get("kind") == "step" else e
        for e in current_pass(events)
        if e.get("kind") != "step"
        or (lane_repo(e.get("repo")) is not None and e.get("status") in STATUSES)
    ]
    t = now()
    runner = {
        "state": "idle",
        "pass_no": None,
        "budget": None,
        "pass_started": None,
        "pass_ended": None,
        "result": None,
        "note": "",
    }
    agents: dict[str, dict[str, Any]] = {}
    prev_issue: dict[
        str, tuple[str, int] | None
    ] = {}  # per agent: (repository, issue) of its previous sub-step
    issues: dict[tuple[str, int], dict[str, Any]] = {}
    for e in evs:
        kind = e.get("kind")
        if kind == "pass-start":
            runner.update(
                state="running",
                pass_started=e["at"],
                pass_ended=None,
                result=None,
                pass_no=e.get("pass_no"),
                budget=e.get("budget"),
                note="",
            )
        elif kind == "pass-end":
            runner.update(state="idle", pass_ended=e["at"], result=e.get("result"))
            for a in agents.values():
                if a["state"] == "running":
                    a["state"] = "ended"
        elif kind == "runner-state":
            runner.update(state=e.get("state", "idle"), note=e.get("note", ""))
        elif kind == "step":
            aid = e["agent"]
            a = agents.setdefault(
                aid,
                {
                    "id": aid,
                    "role": e["role"],
                    "issue": issue_no(e.get("issue")) or None,
                    "station": e["station"],
                    "state": "running",
                    "started": e["at"],
                    "last": e["at"],
                    "substeps": [],
                    "repo": e.get("repo") or "",
                },
            )
            prev_station = a["station"]
            a["last"], a["station"] = e["at"], e["station"]
            own = issue_no(e.get("issue"))
            step = (
                (e.get("repo") or "", own)
                if own
                else (prev_issue.get(aid) or ((a["repo"], a["issue"]) if a["issue"] else None))
            )  # unscoped: the previous sub-step's issue
            closed = None
            if not own and e["status"] in ("done", "fail"):
                # #527: an unscoped done/fail closes the agent's latest open step of the same
                # station + sub-step, in any issue
                open_ = [
                    s
                    for s in a["substeps"]
                    if s["substep"] == e["substep"]
                    and s["station"] == e["station"]
                    and s["status"] in ("start", "wait")
                    and s.get("issue")
                    and (not e.get("repo") or s["repo"] == e["repo"])
                ]
                if open_:
                    closed = max(
                        reversed(open_), key=lambda s: s["at"]
                    )  # a tie on `at`: the step logged last
                    step = (closed["repo"], closed["issue"])
            if closed:
                # #527: a close found by the open-step match does not move the agent's lane or
                # station
                a["station"] = prev_station
            else:
                prev_issue[aid] = step
            step_repo, step_issue = step or ("", None)
            sub = next(
                (
                    s
                    for s in a["substeps"]
                    if s["substep"] == e["substep"]
                    and s["station"] == e["station"]
                    and s.get("issue") == step_issue
                    and s.get("repo") == step_repo
                ),
                None,
            )
            if sub:
                sub.update(status=e["status"], at=e["at"], detail=e.get("detail", ""))
            else:
                a["substeps"].append(
                    {
                        "station": e["station"],
                        "substep": e["substep"],
                        "status": e["status"],
                        "issue": step_issue,
                        "repo": step_repo,
                        "started": e["at"],
                        "at": e["at"],
                        "detail": e.get("detail", ""),
                    }
                )
            if e["status"] in ("fail", "stopped"):
                a["state"] = "failed" if e["status"] == "fail" else "stopped"
            elif e["substep"] == "finished" and e["status"] == "done":
                a["state"] = "done"
            elif a["state"] != "stopped":
                a["state"] = "running"  # a later start/done recovers from a failure
            if step_issue:
                i = issues.setdefault(
                    (step_repo, step_issue),
                    {"issue": step_issue, "repo": step_repo, "title": "", "station": e["station"]},
                )
                i["station"] = e["station"]
                if e.get("title"):
                    i["title"] = e["title"]
    log = [e for e in evs if e.get("kind") == "step"][-LOG_TAIL:]
    # Public schema, field by field: nothing reaches live.json unless it is named here.
    return {
        "schema": SCHEMA,
        "generated_at": t,
        "updated": t,
        "runner": {
            "state": scrub(str(runner["state"])),
            "pass_no": _int_or_none(runner["pass_no"]),
            "budget": _int_or_none(runner["budget"]),
            "pass_started": runner["pass_started"],
            "pass_ended": runner["pass_ended"],
            "result": None if runner["result"] is None else scrub(str(runner["result"])),
            "note": scrub(str(runner["note"])),
        },
        "issues": [
            {
                "issue": i["issue"],
                "repo": i["repo"],
                "title": scrub(i["title"]),
                "station": scrub(str(i["station"])),
            }
            for i in issues.values()
        ],
        "agents": [
            {
                "id": scrub(a["id"]),
                "role": scrub(str(a["role"])),
                "issue": a["issue"],
                "repo": a["repo"],
                "station": scrub(str(a["station"])),
                "state": a["state"],
                "started": a["started"],
                "last": a["last"],
                "substeps": [
                    {
                        "station": scrub(str(s["station"])),
                        "substep": scrub(s["substep"]),
                        "status": s["status"],
                        "issue": s["issue"],
                        "repo": s["repo"],
                        "started": s["started"],
                        "at": s["at"],
                        "detail": scrub(s["detail"]),
                    }
                    for s in a["substeps"]
                ],
            }
            for a in agents.values()
        ],
        "workers": render_workers(
            [
                e
                for e in evs
                if not runner["pass_started"] or parse(e["at"]) >= parse(runner["pass_started"])
            ],
            parse(t),
        ),
        "crew": render_crew(parse(t)),
        "log": [
            {
                "at": e["at"],
                "issue": issue_no(e.get("issue")) or None,
                "repo": e.get("repo") or "",
                "agent": scrub(e["agent"]),
                "role": scrub(str(e["role"])),
                "station": scrub(str(e["station"])),
                "substep": scrub(e["substep"]),
                "status": e["status"],
                "detail": scrub(e.get("detail", "")),
            }
            for e in log
        ],
    }


# ---- commands -----------------------------------------------------------------------------------


def cmd_add(a: argparse.Namespace) -> None:
    if a.station not in STATIONS or a.status not in STATUSES or a.role not in ROLES:
        raise ValueError(f"station must be {STATIONS}, status {STATUSES}, role {ROLES}")
    if not _SLUG.match(a.substep) or not _SLUG.match(a.agent):
        raise ValueError("agent and substep: up to 60 letters, digits, space and . : / # ( ) + -")
    repo = canon_repo(a.repo)
    if repo is None:
        raise ValueError("repo: a repository from the repository list")
    detail = sys.stdin.read() if a.detail_file == "-" else ""
    append(
        {
            "kind": "step",
            "at": now(),
            "issue": a.issue,
            "repo": repo,
            "title": clean(a.title or "", 120),
            "agent": a.agent,
            "role": a.role,
            "station": a.station,
            "substep": a.substep,
            "status": a.status,
            "detail": clean(detail),
        }
    )


def cmd_hook() -> None:
    if not os.environ.get("LF_PROGRESS_FILE"):
        return  # not a factory run: record nothing
    raw = hook_io.read_stdin()
    if raw is None:
        return  # stdin never closed (parent gone): record nothing, never fail the caller
    ev = hook_event(json.loads(raw or "{}"))
    if ev:
        append(ev)


def cmd_render(a: argparse.Namespace) -> Path:
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(render(read_events()), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out


def content_hash(live: dict[str, Any]) -> str:
    body = {k: v for k, v in live.items() if k not in ("generated_at", "updated")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


_ssh_proc: list[subprocess.Popen[bytes]] = []  # the push in flight, for the watchdog


def _publish_timeout() -> float:
    try:
        t = float(os.environ.get("LF_PUBLISH_TIMEOUT_S") or 30)
    except ValueError:
        return 30.0
    return t if t > 0 else 30.0


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                timeout=5,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # its own session: pgid == pid
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _push(argv: list[str], data: bytes, timeout: float) -> None:
    """Run ssh with `data` on stdin, bounded; on timeout or error kill its whole process tree.
    ssh's output
    goes to the null device so nothing it starts can hold a pipe of the caller or of this
    process."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
    _ssh_proc.append(proc)

    def feed() -> None:  # a blocking write must not hold the caller: the child may never read stdin
        try:
            assert proc.stdin is not None
            proc.stdin.write(data)
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threading.Thread(target=feed, daemon=True).start()
    try:
        proc.wait(timeout=timeout)
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, argv[0])
    except BaseException:
        _kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.SubprocessError:
            pass
        raise
    finally:
        _ssh_proc.clear()


_pushed = (
    threading.Event()
)  # set right before the success write: the watchdog must not overwrite it


def _write_state(state: Path, text: str) -> None:
    tmp = state.with_name(state.name + f".{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, state)


def _publish_expired(state: Path) -> None:
    for proc in _ssh_proc:
        _kill_tree(proc)
    if not _pushed.is_set():
        try:
            _write_state(state, f"fail {time.time()}")
        except OSError:
            pass
    os._exit(0)


def _start_publish_watchdog(argv: list[str]) -> threading.Timer | None:
    """CLI only: the publish process ends at T + 15 s whatever hangs (read_events, render, ssh)."""
    if "--key" not in argv or argv.index("--key") + 1 >= len(argv):
        return None
    timer = threading.Timer(
        _publish_timeout() + 15, _publish_expired, (Path(argv[argv.index("--key") + 1] + ".last"),)
    )
    timer.daemon = True
    timer.start()
    return timer


def cmd_publish(a: argparse.Namespace) -> bool:
    """Push live.json when its content changed (at most every MIN_GAP_S), or every HEARTBEAT_S as a
    liveness signal; after a failure wait BACKOFF_S. State file: '<hash> <time>' or 'fail <time>'.
    --force pushes now (the final state of a pass must not be dropped by the gap); --min-age N is
    the
    between-passes heartbeat: push iff the last push is at least N s old, whatever the content."""
    return _publish(a, Path(a.key + ".last"))


def _publish(a: argparse.Namespace, state: Path) -> bool:
    live = render(read_events())
    h = content_hash(live)
    now = time.time()
    try:
        last_h, last_t = state.read_text().split()
        age = now - float(last_t)
        force, min_age = getattr(a, "force", False), getattr(a, "min_age", None)
        if last_h == "fail" and age < BACKOFF_S and not force:
            return False
        if last_h != "fail" and not force:
            if min_age is not None:
                if age < min_age:
                    return False
            elif age < MIN_GAP_S or (last_h == h and age < HEARTBEAT_S):
                return False
    except (OSError, ValueError):
        pass
    data = json.dumps(live, ensure_ascii=False).encode("utf-8")
    # The server key has a forced command that writes stdin to live.json (tmp + rename) and nothing
    # else.
    argv = [
        "ssh",
        "-i",
        a.key,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=3",
        a.host,
    ]
    try:
        _push(argv, data, _publish_timeout())
    except (OSError, subprocess.SubprocessError):
        _write_state(state, f"fail {now}")
        raise
    _pushed.set()
    _write_state(state, f"{h} {now}")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add")
    for flag in ("--agent", "--role", "--station", "--substep", "--status"):
        ad.add_argument(flag, required=True)
    ad.add_argument("--issue", type=int)
    ad.add_argument("--repo", default="")  # owner/name; default: this repository
    ad.add_argument("--title", default="")
    ad.add_argument("--detail-file")
    sub.add_parser("hook")
    ps = sub.add_parser("pass-start")
    ps.add_argument("--pass-no", type=int)
    ps.add_argument("--budget", type=int)
    pe = sub.add_parser("pass-end")
    pe.add_argument("--result", default="done")
    rs = sub.add_parser("runner-state")
    rs.add_argument("--state", required=True, choices=["idle", "paused", "budget", "running"])
    rs.add_argument("--note", default="")
    rn = sub.add_parser("render")
    rn.add_argument("--out", required=True)
    pb = sub.add_parser("publish")
    pb.add_argument("--key", required=True)
    pb.add_argument("--host", required=True)
    pb.add_argument("--force", action="store_true")
    pb.add_argument("--min-age", type=float)
    try:
        a = p.parse_args(argv)
        if a.cmd == "add":
            cmd_add(a)
        elif a.cmd == "hook":
            cmd_hook()
        elif a.cmd == "pass-start":
            append({"kind": "pass-start", "at": now(), "pass_no": a.pass_no, "budget": a.budget})
        elif a.cmd == "pass-end":
            append({"kind": "pass-end", "at": now(), "result": clean(a.result, 40)})
        elif a.cmd == "runner-state":
            append(
                {"kind": "runner-state", "at": now(), "state": a.state, "note": clean(a.note, 120)}
            )
        elif a.cmd == "render":
            cmd_render(a)
        elif a.cmd == "publish":
            cmd_publish(a)
    except SystemExit:
        pass  # argparse errors: still never fail the caller
    except Exception as exc:
        print(f"factory_progress: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


def run(argv: list[str] | None = None) -> int:
    """The entry point of every command line: start the watchdog the command needs, then `main`.
    `main` itself starts none, so in-process callers are never killed."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["hook"]:
        hook_io.start_watchdog(0)  # a hook must never outlive its caller; exiting 0 never blocks it
    elif args[:1] == ["publish"]:
        _start_publish_watchdog(args)
    return main(args)


if __name__ == "__main__":
    sys.exit(run())
