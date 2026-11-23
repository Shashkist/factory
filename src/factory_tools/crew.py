"""Crew view for live.json: who is working right now, as a tree of agents and subagents.

Owner infrastructure (D35 family). Reads Claude Code's own transcripts of factory runs, no hooks:
  <dir>/<session>.jsonl                              one manager pass (headless `claude -p`)
  <dir>/<session>/subagents/agent-<id>.jsonl         one subagent (any depth)
  <dir>/<session>/subagents/agent-<id>.meta.json     agentType, description, toolUseId, finished
A subagent's parent is the transcript that holds the tool_use whose id is its meta `toolUseId`.

"Running" = a tool_use with no tool_result yet (younger than OPEN_MAX); this also covers subagents
that never report a stop. Only the tail of each file is read (TAIL_BYTES), parsed summaries are
cached
by (mtime, size).

Publishing boundary: an ALLOW-LIST. Never tool input or output, prompts, messages or thinking. Per
tool only: Bash/PowerShell/Agent/Task -> the call's own short `description`; Skill -> skill name;
Read/Edit/Write/... -> the repo-relative path (nothing for paths outside the repo); MCP -> "op
(server)".
Every string goes through the caller's scrub() and is length-capped; the page renders text only.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / ".claude" / "projects" / "C--projects-Learning-factory-factory"
TAIL_BYTES = 400_000
HEAD_BYTES = 16_000
SESSION_WINDOW = timedelta(hours=2)  # sessions whose transcript changed within this window
MAX_SESSIONS = 3
MAX_CHILDREN = 8  # per parent, newest first
MAX_DEPTH = 3
BUSY_S = 45  # active this recently -> "thinking" even with no open tool
OPEN_MAX = timedelta(minutes=15)  # an open tool older than this is not shown as running
RECENT = 6
CAPS = {"title": 70, "label": 90, "tool": 40}
PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
DESC_TOOLS = {"Bash", "PowerShell", "Agent", "Task"}
_REPO_PATH = re.compile(
    r"(?:^|/)((?:labs|scripts|docs|courses|\.github|\.claude/skills)/[\w./-]+)$"
)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _cap(text: str, n: int) -> str:
    text = _CTRL.sub(" ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat(timespec="seconds") if d else None


def tool_label(name: str, inp: object) -> str:
    """The allow-listed, unscrubbed label of one tool call ('' when nothing may be shown)."""
    inp = inp if isinstance(inp, dict) else {}
    if name in DESC_TOOLS:
        return str(inp.get("description") or "")
    if name == "Skill":
        return str(inp.get("skill") or "")
    if name in PATH_TOOLS:
        p = str(inp.get("file_path") or inp.get("notebook_path") or "").replace("\\", "/")
        m = _REPO_PATH.search(p)
        return m.group(1) if m else ""
    return ""


def tool_name(name: str) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"{parts[-1]} ({parts[1]})" if len(parts) >= 3 else "mcp"
    return name


def _lines(path: Path, size: int) -> list[str]:
    """Complete lines of the file's tail: the cut first line and a half-written last line are
    dropped."""
    with path.open("rb") as f:
        start = max(0, size - TAIL_BYTES)
        f.seek(start)
        data = f.read(size - start)
    end = data.rfind(b"\n")
    data = data[: end + 1] if end >= 0 else b""
    out = data.decode("utf-8", "replace").splitlines()
    return out[1:] if start > 0 and out else out


def _first_ts(path: Path) -> str | None:
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES).decode("utf-8", "replace").splitlines()
    for line in head:
        try:
            t: str | None = json.loads(line).get("timestamp")
        except ValueError:
            continue
        if t:
            return str(t)
    return None


def summarize(path: Path) -> dict[str, Any]:
    """Parse one transcript tail into tool calls (allow-listed) and timestamps."""
    st = path.stat()
    calls: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    done: set[str] = set()
    last = model = None
    for line in _lines(path, st.st_size):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        last = r.get("timestamp") or last
        msg: dict[str, Any] = r["message"] if isinstance(r.get("message"), dict) else {}
        if r.get("type") == "assistant" and msg.get("model"):
            model = msg["model"]
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("id"):
                calls[c["id"]] = {
                    "name": str(c.get("name") or ""),
                    "label": tool_label(str(c.get("name") or ""), c.get("input")),
                    "at": r.get("timestamp"),
                }
                order.append(c["id"])
            elif c.get("type") == "tool_result" and c.get("tool_use_id"):
                done.add(c["tool_use_id"])
    return {
        "calls": calls,
        "order": order,
        "done": sorted(done),
        "last": last,
        "model": model,
        "first": _first_ts(path),
        "mtime": st.st_mtime,
    }


class Cache:
    """Summaries keyed by (path, mtime, size); persisted between the publisher's short-lived
    runs."""

    def __init__(self, file: Path | None):
        self.file = file
        self.data: dict[str, Any] = {}
        self.used: dict[str, Any] = {}
        if file and file.exists():
            try:
                self.data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}

    def get(self, path: Path) -> dict[str, Any]:
        st = path.stat()
        key = str(path)
        hit = self.data.get(key)
        if not (hit and hit.get("_k") == [st.st_mtime, st.st_size]):
            hit = {**summarize(path), "_k": [st.st_mtime, st.st_size]}
        self.used[key] = hit
        return hit

    def save(self) -> None:
        if not self.file:
            return
        try:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.used), encoding="utf-8")
            os.replace(tmp, self.file)
        except OSError:
            pass


def _short_model(m: str | None) -> str:
    m = (m or "").replace("claude-", "")
    return re.sub(r"-\d{8}$", "", m)[:24]


def _node(
    kind: str,
    sid: str,
    s: dict[str, Any],
    now: datetime,
    meta: dict[str, Any],
    scrub: Callable[[str], str],
) -> dict[str, Any]:
    done = set(s["done"])
    open_ = [
        i
        for i in s["order"]
        if i not in done and (_ts(s["calls"][i]["at"]) or now) > now - OPEN_MAX
    ]
    cur = s["calls"][open_[-1]] if open_ and not meta.get("finished") else None
    last = _ts(s["last"]) or datetime.fromtimestamp(s["mtime"], UTC)
    if meta.get("finished"):
        state = "finished"
    elif cur:
        state = "busy"
    elif (now - last).total_seconds() <= BUSY_S:
        state = "thinking"
    else:
        state = "idle"
    recent = [tool_name(s["calls"][i]["name"]) for i in s["order"][-RECENT:]]
    return {
        "id": sid[:12],
        "kind": kind,
        "type": _cap(
            scrub(str(meta.get("agentType") or ("manager" if kind == "session" else "agent"))),
            CAPS["tool"],
        ),
        "title": _cap(scrub(str(meta.get("description") or "")), CAPS["title"]),
        "model": _short_model(meta.get("pickedEffortModel") or s.get("model")),
        "state": state,
        "tool": _cap(tool_name(cur["name"]), CAPS["tool"]) if cur else None,
        "label": _cap(scrub(cur["label"]), CAPS["label"]) if cur else "",
        "recent": [_cap(t, CAPS["tool"]) for t in recent],
        "started": _iso(_ts(s.get("first"))),
        "last": _iso(last),
        "children": [],
        "more": 0,
    }


def build(
    dir_: Path | None, now: datetime, scrub: Callable[[str], str], cache_file: Path | None = None
) -> list[dict[str, Any]]:
    """The crew tree: up to MAX_SESSIONS recent sessions, each with its subagents nested by
    parent."""
    d = Path(dir_) if dir_ else DEFAULT_DIR
    if not d.is_dir():
        return []
    cache = Cache(cache_file)
    sessions = []
    for f in d.glob("*.jsonl"):
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if datetime.fromtimestamp(mt, UTC) >= now - SESSION_WINDOW:
            sessions.append((mt, f))
    out = []
    for _, f in sorted(sessions, reverse=True)[:MAX_SESSIONS]:
        try:
            out.append(_session_tree(f, now, scrub, cache))
        except OSError:
            continue  # one unreadable file must not blank the view
    cache.save()
    return out


def _session_tree(
    f: Path, now: datetime, scrub: Callable[[str], str], cache: Cache
) -> dict[str, Any]:
    sid = f.stem
    root_sum = cache.get(f)
    root = _node("session", sid, root_sum, now, {}, scrub)
    owners: dict[str, dict[str, Any]] = {
        i: root for i in root_sum["order"]
    }  # tool_use id -> node that made the call
    subs = []
    sub_dir = f.with_suffix("") / "subagents"
    if sub_dir.is_dir():
        for m in sub_dir.glob("agent-*.meta.json"):
            t = m.with_name(m.name[: -len(".meta.json")] + ".jsonl")
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
                s = cache.get(t) if t.exists() else None
            except (OSError, ValueError):
                continue
            if not s:
                continue
            node = _node("subagent", t.stem.removeprefix("agent-"), s, now, meta, scrub)
            subs.append((meta.get("toolUseId"), node, s))
            for i in s["order"]:
                owners[i] = node
    depth = {id(root): 0}
    pending = sorted(subs, key=lambda x: x[1]["last"] or "")
    for _ in range(MAX_DEPTH + 1):  # parents may be other subagents: attach in rounds
        rest = []
        for tid, node, s in pending:
            parent = owners.get(tid)
            if parent is None or id(parent) not in depth:
                rest.append((tid, node, s))
                continue
            if depth[id(parent)] >= MAX_DEPTH:
                continue
            parent["children"].append(node)
            depth[id(node)] = depth[id(parent)] + 1
        pending = rest
    # parent call not in the tail any more: hang it under the session
    for _tid, node, _s in pending:
        root["children"].append(node)
        depth[id(node)] = 1
    _trim(root)
    if any(c["state"] in ("busy", "thinking") for c in _walk(root)) and root["state"] == "idle":
        root["state"] = "waiting"  # the manager waits on its subagents
    return root


def _walk(n: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for c in n["children"]:
        yield c
        yield from _walk(c)


def _trim(n: dict[str, Any]) -> None:
    rank = {"busy": 0, "thinking": 1, "waiting": 2, "idle": 3, "finished": 4}
    kids = sorted(
        n["children"],
        key=lambda c: (
            rank.get(c["state"], 5),
            -(_ts(c["last"]) or datetime.min.replace(tzinfo=UTC)).timestamp(),
        ),
    )
    n["more"] = max(0, len(kids) - MAX_CHILDREN)
    n["children"] = kids[:MAX_CHILDREN]
    for c in n["children"]:
        _trim(c)
