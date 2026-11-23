# Ported from Shashkist/Learning_factory scripts/test_factory_crew.py (after LF #558).
# Lint: the LF code is kept verbatim, so the ruff noqa line below silences long lines (E501), the
# now-unused sys import (F401, crew file) and timezone.utc (UP017); LF does not hold its scripts to this profile.
# Changes versus LF (imports and paths only; every case and assertion is kept):
#  - `sys.path.insert(0, <scripts dir>)` removed: the modules are now the package, imported as
#    `from factory_tools import crew as fc` and `from factory_tools import progress as fp`
#    (was `import factory_crew as fc` and `import factory_progress as fp`).
#  - Environment variable names (LF_CREW_DIR, LF_PROGRESS_FILE, ...) are unchanged (spec G8).
# ruff: noqa: E501, F401, UP017
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory_tools import crew as fc
from factory_tools import progress as fp

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)


def ts(sec_ago: float) -> str:
    return (NOW - timedelta(seconds=sec_ago)).isoformat().replace("+00:00", "Z")


def use(i, name, inp, ago):
    return {"type": "assistant", "timestamp": ts(ago),
            "message": {"model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}


def result(i, ago):
    return {"type": "user", "timestamp": ts(ago),
            "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": "SECRET OUTPUT ghp_abc"}]}}


def write(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def touch_now(*paths):
    import os
    for p in paths:
        os.utime(p, (NOW.timestamp(), NOW.timestamp()))


def factory(tmp_path):
    d = tmp_path / "proj"
    s = d / "sess-1.jsonl"
    write(s, [
        {"type": "session-owner", "accountUuid": "acct-123", "organizationUuid": "org-9"},
        use("t1", "Skill", {"skill": "factory"}, 600), result("t1", 590),
        use("t2", "Agent", {"description": "Implement #7 lifecycle", "prompt": "PROMPT TEXT", "subagent_type": "implementer"}, 500),
        use("t3", "Bash", {"command": "gh secret set X < key", "description": "Watch CI on PR #9"}, 5),
    ])
    sub = d / "sess-1" / "subagents"
    write(sub / "agent-aaa.jsonl", [
        use("a1", "Edit", {"file_path": "C:\\projects\\Learning_factory-factory\\labs\\manager\\app\\main.py", "old_string": "x", "new_string": "y"}, 300),
        result("a1", 290),
        use("a2", "Agent", {"description": "Research gVisor sudo", "prompt": "p"}, 200),
        use("a3", "Read", {"file_path": "C:\\Users\\someone\\secrets.txt"}, 10),
    ])
    (sub / "agent-aaa.meta.json").write_text(json.dumps({"agentType": "implementer", "description": "Implement #7 lifecycle",
                                                        "toolUseId": "t2", "finished": False}), encoding="utf-8")
    write(sub / "agent-bbb.jsonl", [use("b1", "mcp__github__create_issue", {"body": "private body"}, 20)])
    (sub / "agent-bbb.meta.json").write_text(json.dumps({"agentType": "researcher", "description": "Research gVisor sudo",
                                                        "toolUseId": "a2", "finished": False}), encoding="utf-8")
    write(sub / "agent-ccc.jsonl", [use("c1", "Bash", {"command": "ls", "description": "List"}, 900)])
    (sub / "agent-ccc.meta.json").write_text(json.dumps({"agentType": "reviewer", "description": "Review PR #8",
                                                        "toolUseId": "gone-from-tail", "finished": True}), encoding="utf-8")
    touch_now(s, *sub.iterdir())
    return d


def test_tree_nests_subagents_under_the_call_that_spawned_them(tmp_path):
    [root] = fc.build(factory(tmp_path), NOW, fp.scrub)
    assert root["kind"] == "session" and root["type"] == "manager"
    kids = {c["type"]: c for c in root["children"]}
    assert set(kids) == {"implementer", "reviewer"}          # reviewer: parent call no longer in the tail
    [grand] = kids["implementer"]["children"]
    assert grand["type"] == "researcher" and grand["title"] == "Research gVisor sudo"


def test_running_means_an_open_tool_use_and_labels_come_from_the_allow_list(tmp_path):
    [root] = fc.build(factory(tmp_path), NOW, fp.scrub)
    assert root["state"] == "busy" and root["tool"] == "Bash" and root["label"] == "Watch CI on PR #9"
    impl = next(c for c in root["children"] if c["type"] == "implementer")
    assert impl["state"] == "busy" and impl["tool"] == "Read" and impl["label"] == ""   # path outside the repo: nothing
    res = impl["children"][0]
    assert res["tool"] == "create_issue (github)" and res["label"] == ""
    rev = next(c for c in root["children"] if c["type"] == "reviewer")
    assert rev["state"] == "finished" and rev["tool"] is None


def test_repo_paths_are_shown_relative(tmp_path):
    assert fc.tool_label("Edit", {"file_path": "C:\\projects\\Learning_factory-factory\\labs\\manager\\app\\main.py"}) == "labs/manager/app/main.py"
    assert fc.tool_label("Write", {"file_path": "/home/x/.ssh/id_rsa"}) == ""
    assert fc.tool_label("Skill", {"skill": "factory"}) == "factory"
    assert fc.tool_label("Grep", {"pattern": "password"}) == ""


def test_nothing_outside_the_allow_list_is_published(tmp_path):
    blob = json.dumps(fc.build(factory(tmp_path), NOW, fp.scrub))
    for secret in ("gh secret set", "PROMPT TEXT", "SECRET OUTPUT", "ghp_", "private body", "acct-123", "org-9",
                   "someone", "secrets.txt", "C:\\\\", "old_string"):
        assert secret not in blob, secret


def test_stale_open_tools_and_old_sessions_are_not_running(tmp_path):
    d = tmp_path / "proj"
    write(d / "old.jsonl", [use("x", "Bash", {"description": "long ago"}, 60 * 60)])
    touch_now(d / "old.jsonl")
    [root] = fc.build(d, NOW, fp.scrub)
    assert root["state"] == "idle" and root["tool"] is None   # open for an hour: abandoned, not running
    import os
    old = (NOW - timedelta(hours=3)).timestamp()
    os.utime(d / "old.jsonl", (old, old))
    assert fc.build(d, NOW, fp.scrub) == []


def test_tail_reading_drops_cut_and_half_written_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "TAIL_BYTES", 700)   # ~3 lines: the cut one is dropped
    p = tmp_path / "t.jsonl"
    body = "".join(json.dumps(use(f"id{i}", "Bash", {"description": f"step {i}"}, 100 - i)) + "\n" for i in range(10))
    p.write_text(body + '{"type": "assistant", "half', encoding="utf-8")
    s = fc.summarize(p)
    assert s["order"] and s["order"][-1] == "id9"


def test_cache_reuses_unchanged_files(tmp_path, monkeypatch):
    d = factory(tmp_path)
    cache = tmp_path / "cache.json"
    fc.build(d, NOW, fp.scrub, cache)
    calls = []
    real = fc.summarize
    monkeypatch.setattr(fc, "summarize", lambda p: calls.append(p) or real(p))
    fc.build(d, NOW, fp.scrub, cache)
    assert calls == []


def test_render_has_no_crew_unless_the_runner_enables_it(monkeypatch, tmp_path):
    monkeypatch.setenv("LF_PROGRESS_FILE", str(tmp_path / "p.jsonl"))
    monkeypatch.delenv("LF_CREW_DIR", raising=False)
    assert fp.render([])["crew"] == []
    monkeypatch.setenv("LF_CREW_DIR", str(factory(tmp_path)))
    monkeypatch.setattr(fc, "datetime", datetime)  # no-op: build() takes the render time
    crew = fp.render_crew(NOW)
    assert crew and crew[0]["children"]


def test_a_broken_transcript_never_breaks_the_publisher(monkeypatch, tmp_path):
    monkeypatch.setenv("LF_CREW_DIR", str(tmp_path))
    monkeypatch.setattr(fc, "build", lambda *a, **k: 1 / 0)
    assert fp.render_crew(NOW) == []
