# Ported from Shashkist/Learning_factory scripts/test_factory_progress.py (after LF #558).
# Lint: the LF code is kept verbatim, so the ruff noqa line below silences long lines (E501), the
# now-unused sys import (F401, crew file) and timezone.utc (UP017); LF does not hold its scripts to this profile.
# Changes versus LF (imports and paths only; every case and assertion is kept):
#  - `sys.path.insert(0, <scripts dir>)` removed: the modules are now the package, imported as
#    `from factory_tools import hook_io as _hook_io` and `from factory_tools import progress as fp`
#    (was `import _hook_io` and `import factory_progress as fp`).
#  - subprocess cases run `Path(fp.__file__)`, now src/factory_tools/progress.py (was scripts/factory_progress.py);
#    the file must stay runnable as a plain file. conftest.py puts src/ on PYTHONPATH for those children.
#  - Environment variable names (LF_PROGRESS_FILE, LF_CREW_DIR, LF_PUBLISH_TIMEOUT_S, ...) are unchanged (spec G8).
# ruff: noqa: E501, F401, UP017
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from factory_tools import hook_io as _hook_io
from factory_tools import progress as fp


@pytest.fixture(autouse=True)
def events_file(tmp_path, monkeypatch):
    f = tmp_path / "progress.jsonl"
    monkeypatch.setenv("LF_PROGRESS_FILE", str(f))
    monkeypatch.delenv("LF_CREW_DIR", raising=False)   # the laptop sets it; the crew view is opt-in per case
    return f


def add(issue, agent, role, station, substep, status, detail=None, monkeypatch=None):
    args = ["add", "--issue", str(issue), "--agent", agent, "--role", role, "--station", station,
            "--substep", substep, "--status", status]
    if detail is not None:
        args += ["--detail-file", "-"]
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(detail))
    assert fp.main(args) == 0


def test_agents_and_substeps_follow_the_latest_status(monkeypatch):
    fp.main(["pass-start", "--pass-no", "3", "--budget", "10"])
    add(46, "impl-46", "implementer", "build", "unit tests", "start")
    add(46, "impl-46", "implementer", "build", "unit tests", "done", "12 passed", monkeypatch)
    add(46, "rev-46", "reviewer", "check", "round 1", "start")
    live = fp.render(fp.read_events())
    assert live["runner"]["state"] == "running" and live["runner"]["pass_no"] == 3
    impl = next(a for a in live["agents"] if a["id"] == "impl-46")
    assert impl["substeps"] == [dict(impl["substeps"][0], substep="unit tests", status="done", detail="12 passed")]
    assert live["issues"][0]["station"] == "check"
    assert [e["status"] for e in live["log"]] == ["start", "done", "start"]


def test_only_the_current_pass_is_rendered():
    fp.main(["pass-start"])
    add(1, "old", "implementer", "build", "x", "start")
    fp.main(["pass-end"])
    fp.main(["pass-start"])
    add(2, "new", "reviewer", "check", "y", "start")
    live = fp.render(fp.read_events())
    assert [a["id"] for a in live["agents"]] == ["new"]


def test_pass_end_makes_the_runner_idle_and_ends_running_agents():
    fp.main(["pass-start"])
    add(5, "impl-5", "implementer", "build", "code", "start")
    fp.main(["pass-end", "--result", "done"])
    live = fp.render(fp.read_events())
    assert live["runner"]["state"] == "idle" and live["agents"][0]["state"] == "ended"


def test_failures_mark_the_agent(monkeypatch):
    add(7, "impl-7", "implementer", "build", "ci", "fail", "pytest: 2 failed", monkeypatch)
    assert fp.render(fp.read_events())["agents"][0]["state"] == "failed"


def test_detail_is_cleaned_and_capped(monkeypatch):
    add(1, "a", "manager", "plan", "pick", "done", "line1\nline2\x1b[31m" + "x" * 500, monkeypatch)
    d = fp.render(fp.read_events())["log"][0]["detail"]
    assert "\n" not in d and "\x1b" not in d and len(d) <= fp.DETAIL_MAX


def test_bad_input_never_fails_the_caller(events_file, capsys):
    assert fp.main(["add", "--agent", "a", "--role", "boss", "--station", "plan", "--substep", "x", "--status", "start"]) == 0
    assert "factory_progress" in capsys.readouterr().err
    assert not events_file.exists()


def test_render_writes_valid_json(tmp_path):
    fp.main(["pass-start"])
    out = tmp_path / "live.json"
    fp.main(["render", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["runner"]["state"] == "running"


def test_cli_runs_as_a_script(tmp_path):
    out = tmp_path / "l.json"
    r = subprocess.run([sys.executable, str(Path(fp.__file__)), "render", "--out", str(out)], capture_output=True)
    assert r.returncode == 0 and out.exists()


def test_runner_state_is_shown_between_passes():
    fp.main(["pass-start"])
    fp.main(["pass-end"])
    fp.main(["runner-state", "--state", "paused", "--note", "PAUSE file present"])
    r = fp.render(fp.read_events())["runner"]
    assert r["state"] == "paused" and r["note"] == "PAUSE file present"


def hook(payload, monkeypatch):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    assert fp.main(["hook"]) == 0


def test_hooks_show_workers_busy_with_a_tool_category(monkeypatch):
    fp.main(["pass-start"])
    hook({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash", "tool_use_id": "t1",
          "tool_input": {"command": "cat /root/.env"}}, monkeypatch)
    hook({"hook_event_name": "PreToolUse", "session_id": "s1", "agent_id": "a7", "agent_type": "implementer",
          "tool_name": "mcp__github__create_pr", "tool_use_id": "t2"}, monkeypatch)
    live = fp.render(fp.read_events())
    w = {x["role"]: x for x in live["workers"]}
    assert w["manager"]["state"] == "busy" and w["manager"]["tool"] == "Bash"
    assert w["implementer"]["tool"] == "MCP"
    assert "cat" not in json.dumps(live) and ".env" not in json.dumps(live) and "github__" not in json.dumps(live)
    hook({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_use_id": "t1"}, monkeypatch)
    w = {x["role"]: x for x in fp.render(fp.read_events())["workers"]}
    assert w["manager"]["state"] == "thinking" and w["manager"]["tool"] is None and w["manager"]["tools"] == {"Bash": 1}


def test_waiting_and_finished_workers(monkeypatch):
    hook({"hook_event_name": "Notification", "session_id": "s1", "message": "Claude needs your permission"}, monkeypatch)
    hook({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "a1", "agent_type": "reviewer"}, monkeypatch)
    states = {x["role"]: x["state"] for x in fp.render(fp.read_events())["workers"]}
    assert states == {"manager": "waiting", "reviewer": "finished"}


def test_hooks_record_nothing_outside_factory_runs(monkeypatch, events_file):
    monkeypatch.delenv("LF_PROGRESS_FILE")
    monkeypatch.setattr(fp, "events_path", lambda: events_file)
    hook({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash"}, monkeypatch)
    assert not events_file.exists()


def test_public_text_is_scrubbed(monkeypatch):
    add(3, "impl-3", "implementer", "build", "deploy", "fail",
        "PR https://github.com/Shashkist/Learning_factory/pull/9 ssh root@207.154.193.238 failed, see " + "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "log and https://evil.example/a mail me@x.com "
        "key abcdefghijklmnopqrstuvwxyz0123456789ABCD", monkeypatch)
    d = fp.render(fp.read_events())["log"][0]["detail"]
    for leak in ("207.154", "C:" + chr(92) + "Users", "evil.example", "me@x.com", "abcdefghijklmnop"):
        assert leak not in d
    assert "github.com/Shashkist/Learning_factory/pull/9" in d


def test_live_json_has_schema_and_no_unknown_fields(monkeypatch):
    fp.main(["pass-start"])
    add(1, "m", "manager", "plan", "pick #1", "done", "x", monkeypatch)
    live = fp.render(fp.read_events())
    assert live["schema"] == 1 and set(live) == {"schema", "generated_at", "updated", "runner", "issues", "agents", "workers", "crew", "log"}


def test_publish_skips_unchanged_content_and_respects_the_ssh_rate_limit(monkeypatch, tmp_path):
    calls, clock = [], [1000.0]
    monkeypatch.setattr(fp, "_push", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(fp.time, "time", lambda: clock[0])
    ns = type("A", (), {"key": str(tmp_path / "k"), "host": "h"})
    fp.main(["pass-start"])
    assert fp.cmd_publish(ns) is True
    add(1, "m", "manager", "plan", "pick", "start", monkeypatch=monkeypatch)
    clock[0] += 5
    assert fp.cmd_publish(ns) is False      # changed, but within MIN_GAP_S of the last push
    clock[0] += fp.MIN_GAP_S
    assert fp.cmd_publish(ns) is True       # changed and the gap has passed
    clock[0] += fp.MIN_GAP_S
    assert fp.cmd_publish(ns) is False      # unchanged within the heartbeat
    clock[0] += fp.HEARTBEAT_S
    assert fp.cmd_publish(ns) is True       # heartbeat
    assert len(calls) == 3


def test_publish_backs_off_after_a_failed_push(monkeypatch, tmp_path):
    calls, clock = [], [1000.0]
    def boom(*a, **k):
        calls.append(1)
        raise fp.subprocess.TimeoutExpired("ssh", 30)
    monkeypatch.setattr(fp, "_push", boom)
    monkeypatch.setattr(fp.time, "time", lambda: clock[0])
    ns = type("A", (), {"key": str(tmp_path / "k"), "host": "h"})
    fp.main(["pass-start"])
    with pytest.raises(fp.subprocess.TimeoutExpired):
        fp.cmd_publish(ns)
    clock[0] += fp.BACKOFF_S - 1
    assert fp.cmd_publish(ns) is False      # retrying now would renew the firewall block
    clock[0] += 2
    with pytest.raises(fp.subprocess.TimeoutExpired):
        fp.cmd_publish(ns)
    assert len(calls) == 2


def test_publish_force_pushes_the_final_state_inside_the_gap(monkeypatch, tmp_path):
    calls, clock = [], [1000.0]
    monkeypatch.setattr(fp, "_push", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(fp.time, "time", lambda: clock[0])
    ns = type("A", (), {"key": str(tmp_path / "k"), "host": "h", "force": False, "min_age": None})
    fp.main(["pass-start"])
    assert fp.cmd_publish(ns) is True
    fp.main(["pass-end"])
    clock[0] += 3
    assert fp.cmd_publish(ns) is False      # the normal gap would drop the pass-end
    ns.force = True
    assert fp.cmd_publish(ns) is True       # the runner's final push is forced
    assert len(calls) == 2


def test_publish_min_age_is_a_heartbeat_between_passes(monkeypatch, tmp_path):
    calls, clock = [], [1000.0]
    monkeypatch.setattr(fp, "_push", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(fp.time, "time", lambda: clock[0])
    ns = type("A", (), {"key": str(tmp_path / "k"), "host": "h", "force": False, "min_age": 50.0})
    fp.main(["pass-end"])
    assert fp.cmd_publish(ns) is True
    clock[0] += 30
    assert fp.cmd_publish(ns) is False      # pushed 30 s ago (by a pass or a heartbeat): nothing to do
    clock[0] += 25
    assert fp.cmd_publish(ns) is True       # 55 s: unchanged content, still pushed so the page stays "online"
    assert len(calls) == 2


def test_publish_cli_accepts_force_and_min_age(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(fp, "cmd_publish", lambda a: seen.append((a.force, a.min_age)))
    fp.main(["publish", "--key", "k", "--host", "h", "--force"])
    fp.main(["publish", "--key", "k", "--host", "h", "--min-age", "50"])
    assert seen == [(True, None), (False, 50.0)]


def test_hook_exits_when_stdin_never_closes(tmp_path):
    env = {**os.environ, "LF_PROGRESS_FILE": str(tmp_path / "ev.jsonl"), "LF_HOOK_STDIN_TIMEOUT": "1"}
    p = subprocess.Popen([sys.executable, str(Path(fp.__file__)), "hook"], stdin=subprocess.PIPE, env=env)
    t0 = time.time()
    try:
        assert p.wait(timeout=5) == 0
    finally:
        p.kill()
        p.stdin.close()
    assert time.time() - t0 < 5
    assert not (tmp_path / "ev.jsonl").exists()


def test_read_stdin_returns_payload_and_none_on_timeout(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("abc"))
    assert _hook_io.read_stdin(1) == "abc"

    class Never:
        def read(self):
            threading.Event().wait(3)
            return ""
    monkeypatch.setattr(sys, "stdin", Never())
    assert _hook_io.read_stdin(0.2) is None


def test_failed_agent_recovers_on_a_later_substep_but_stopped_is_sticky():
    fp.main(["pass-start", "--pass-no", "1", "--budget", "1"])
    add(5, "a", "implementer", "build", "ci 1", "fail")
    assert fp.render(fp.read_events())["agents"][0]["state"] == "failed"
    add(5, "a", "implementer", "build", "ci 2", "start")
    assert fp.render(fp.read_events())["agents"][0]["state"] == "running"
    add(5, "a", "implementer", "build", "ci 2", "stopped")
    add(5, "a", "implementer", "build", "ci 3", "done")
    assert fp.render(fp.read_events())["agents"][0]["state"] == "stopped"


def test_issue_zero_creates_no_issue_row_and_no_agent_issue():
    fp.main(["pass-start", "--pass-no", "1", "--budget", "1"])
    add(0, "m", "manager", "ship", "manager pass", "start")
    live = fp.render(fp.read_events())
    assert live["issues"] == []
    assert live["agents"][0]["issue"] is None

def _step(at, issue, agent="a", substep="x", status="start"):
    return {"kind": "step", "at": at, "issue": issue, "agent": agent, "role": "implementer",
            "station": "build", "substep": substep, "status": status, "title": "", "detail": ""}


def _worker(at, wid="w1"):
    return {"kind": "worker", "at": at, "worker": wid, "role": "manager", "event": "idle"}


def _issues_of(events, agent, substep):
    live = fp.render([{"kind": "pass-start", "at": "2999-01-01T00:00:00Z", "pass_no": 1, "budget": 1}, *events])
    return {s["issue"]: s["status"] for a in live["agents"] if a["id"] == agent for s in a["substeps"] if s["substep"] == substep}


def test_unscoped_done_closes_the_latest_open_step_of_the_same_agent_and_substep():
    ev = [_step("2999-01-01T00:00:01Z", 3, "m", "ci wait"), _step("2999-01-01T00:00:02Z", 5, "m", "ci wait"),
          _step("2999-01-01T00:00:03Z", 86, "m", "merge"), _step("2999-01-01T00:00:04Z", None, "m", "ci wait", "done")]
    assert _issues_of(ev, "m", "ci wait") == {3: "start", 5: "done"}


def test_unscoped_done_with_no_open_step_falls_back_to_the_previous_substep_issue():
    ev = [_step("2999-01-01T00:00:01Z", 3, "m", "ci wait", "done"), _step("2999-01-01T00:00:02Z", 86, "m", "merge"),
          _step("2999-01-01T00:00:03Z", None, "m", "ci wait", "done")]
    assert _issues_of(ev, "m", "ci wait") == {3: "done", 86: "done"}


def test_unscoped_done_never_closes_another_agents_step():
    ev = [_step("2999-01-01T00:00:01Z", 3, "other", "ci wait"), _step("2999-01-01T00:00:02Z", 86, "m", "merge"),
          _step("2999-01-01T00:00:03Z", None, "m", "ci wait", "fail")]
    assert _issues_of(ev, "other", "ci wait") == {3: "start"}
    assert _issues_of(ev, "m", "ci wait") == {86: "fail"}


def _e(sec, issue, sub, status="start", station="check", repo="", agent="m"):
    return {"kind": "step", "at": f"2999-01-01T00:00:{sec:02d}Z", "issue": issue, "repo": repo, "agent": agent, "role": "manager",
            "station": station, "substep": sub, "status": status, "title": "", "detail": ""}


def _live(events):
    return fp.render([{"kind": "pass-start", "at": "2999-01-01T00:00:00Z", "pass_no": 1, "budget": 1}, *events])


def _rows(live, sub, agent="m"):
    return {(s["repo"], s["issue"]): s["status"] for a in live["agents"] if a["id"] == agent for s in a["substeps"] if s["substep"] == sub}


def test_open_step_match_keeps_the_previous_issue_pointer_and_agent_station():
    live = _live([_e(1, 3, "ci wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done"), _e(4, None, "deploy")])
    assert _rows(live, "deploy") == {("", 86): "start"}
    assert _rows(live, "ci wait") == {("", 3): "done"}
    # station right after the close is still the one of the merge step
    live = _live([_e(1, 3, "ci wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done")])
    assert live["agents"][0]["station"] == "ship"


def test_unscoped_close_naming_a_repository_only_matches_that_repository():
    ev = [_e(1, 3, "ci wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done", repo="Shashkist/factory")]
    rows = _rows(_live(ev), "ci wait")
    assert rows == {("", 3): "start", ("", 86): "done"}


def test_unscoped_close_without_repo_matches_the_open_step_of_a_foreign_repository():
    ev = [_e(1, 3, "ci wait", repo="Shashkist/factory"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done")]
    assert _rows(_live(ev), "ci wait") == {("Shashkist/factory", 3): "done"}


def test_a_wait_step_counts_as_open():
    ev = [_e(1, 3, "ci wait", "wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done")]
    assert _rows(_live(ev), "ci wait") == {("", 3): "done"}


def test_the_station_must_match_for_the_close():
    ev = [_e(1, 3, "ci wait", station="ship"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done", station="check")]
    assert _rows(_live(ev), "ci wait") == {("", 3): "start", ("", 86): "done"}


def test_an_unscoped_start_follows_the_previous_substep_not_the_open_step():
    ev = [_e(1, 3, "ci wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "start")]
    assert _rows(_live(ev), "ci wait") == {("", 3): "start", ("", 86): "start"}


def test_a_tie_on_at_closes_the_step_logged_last():
    ev = [_e(1, 3, "ci wait"), _e(1, 5, "ci wait"), _e(2, 86, "merge", station="ship"), _e(3, None, "ci wait", "done")]
    assert _rows(_live(ev), "ci wait") == {("", 3): "start", ("", 5): "done"}


def test_workers_come_from_events_after_pass_start_not_whole_workers():
    evs = [{"kind": "pass-start", "at": "2026-01-01T10:00:00+00:00"},
           _worker("2026-01-01T09:59:59+00:00"), _worker("2026-01-01T10:00:05+00:00")]
    w = fp.render(evs)["workers"]
    assert len(w) == 1 and w[0]["started"] == "2026-01-01T10:00:05+00:00"


def test_pass_start_compared_as_datetimes_not_strings():
    # 10:30+02:00 is 08:30 UTC, before 09:00 UTC, though the string sorts after
    evs = [{"kind": "pass-start", "at": "2026-01-01T09:00:00+00:00"},
           _worker("2026-01-01T10:30:00+02:00", "early"), _worker("2026-01-01T09:30:00+00:00", "late")]
    assert [w["id"] for w in fp.render(evs)["workers"]] == ["late"]


def test_issue_zero_string_is_no_issue():
    evs = [_step("2026-01-01T10:00:00+00:00", "0"), _step("2026-01-01T10:00:01+00:00", "junk", agent="b"),
           _step("2026-01-01T10:00:02+00:00", "7", agent="c")]
    live = fp.render(evs)
    assert [i["issue"] for i in live["issues"]] == [7]
    assert {a["id"]: a["issue"] for a in live["agents"]} == {"a": None, "b": None, "c": 7}


def _add_repo(repo):
    return fp.main(["add", "--issue", "5", "--repo", repo, "--agent", "a", "--role", "implementer", "--station", "build",
                    "--substep", "x", "--status", "start"])


def test_only_allowlisted_repositories_reach_live_json(events_file, capsys):
    token = "A" * 40
    for bad in ("evil/secret-project", f"{token}/x", f"owner/{token}"):
        assert _add_repo(bad) == 0   # never fails the caller, same as other bad input
        assert "factory_progress" in capsys.readouterr().err
    assert not events_file.exists()
    assert _add_repo("SHASHKIST/Factory") == 0
    assert _add_repo("shashkist/learning_factory") == 0
    live = fp.render(fp.read_events())
    assert token not in json.dumps(live)
    assert sorted(i["repo"] for i in live["issues"]) == ["", "Shashkist/factory"]


def test_render_drops_hand_edited_events_with_a_foreign_repo(events_file):
    ev = {"kind": "step", "at": fp.now(), "issue": 1, "repo": "leak/name", "agent": "a", "role": "implementer",
          "station": "build", "substep": "x", "status": "start", "detail": "", "title": ""}
    events_file.write_text(json.dumps(ev) + chr(10), encoding="utf-8")
    assert "leak/name" not in json.dumps(fp.render(fp.read_events()))


def test_dot_segments_and_lookalike_urls_are_redacted():
    for url in ("https://github.com/Shashkist/factory/../../someone/else/pull/1",
                "https://github.com/Shashkist/factory/%2e%2e/x", "https://github.com/Shashkist/Learning_factory-evil/x"):
        assert fp.scrub("see " + url) == "see <url>"
    ok = "https://github.com/Shashkist/Learning_factory/pull/9"
    assert fp.scrub(ok) == ok


@pytest.mark.parametrize("text", [
    "github.com/Shashkist/factory/../../someone/else",
    "github.com/Shashkist/Learning_factory/x/../../../someone/else",
    "github.com/Shashkist/factory/%2e%2e/someone",
    r"github.com/Shashkist/factory/a\someone",
    "https://github.com/Shashkist/factory/pull%2f..%2f..%2fsomeone",
    "github.com/Shashkist/factory/pull%2Fsomeone",
    "https://evil.shashkist.com.someone.net/x",
    "https://attackershashkist.com/x",
    "https://shashkist.com:!@someone.net/x",
    "https://labs.shashkist.com:%@someone.net/x",
])
def test_scrub_redacts_traversal_and_lookalike_hosts(text):
    assert fp.scrub("see " + text) == "see <url>"


@pytest.mark.parametrize("text", [
    "https://github.com/Shashkist/Learning_factory/pull/552",
    "https://github.com/Shashkist/factory/pull/1.",
    "(https://github.com/Shashkist/factory/pull/1)",
    "https://lab.shashkist.com/x",
    "https://labs.shashkist.com",
    "https://labs.shashkist.com:443/x",
])
def test_scrub_keeps_plain_allowed_urls(text):
    assert fp.scrub(text) == text


def test_publish_timeout_env_is_read_and_bad_values_fall_back(monkeypatch):
    monkeypatch.delenv("LF_PUBLISH_TIMEOUT_S", raising=False)
    assert fp._publish_timeout() == 30
    monkeypatch.setenv("LF_PUBLISH_TIMEOUT_S", "2.5")
    assert fp._publish_timeout() == 2.5
    for bad in ("x", "0", "-1"):
        monkeypatch.setenv("LF_PUBLISH_TIMEOUT_S", bad)
        assert fp._publish_timeout() == 30


def test_publish_ssh_argv_has_keepalive_options(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(fp, "_push", lambda argv, data, t: seen.append((argv, t)))
    monkeypatch.setenv("LF_PUBLISH_TIMEOUT_S", "7")
    fp.main(["pass-start"])
    fp.cmd_publish(type("A", (), {"key": str(tmp_path / "k"), "host": "h"}))
    argv, t = seen[0]
    joined = " ".join(argv)
    assert t == 7
    for opt in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=10",
                "ServerAliveInterval=5", "ServerAliveCountMax=3"):
        assert opt in joined


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX commands")
def test_push_times_out_kills_ssh_and_fails_on_nonzero_exit():
    with pytest.raises(subprocess.TimeoutExpired):
        fp._push(["sleep", "30"], b"x", 0.5)
    assert fp._ssh_proc == []
    with pytest.raises(subprocess.CalledProcessError):
        fp._push(["false"], b"x", 5)
    fp._push(["cat"], b"x", 5)


def _pid_gone(pid):
    end = time.time() + 5
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    return False


def test_push_is_bounded_when_the_child_never_reads_a_large_stdin():
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        fp._push([sys.executable, "-c", "import time; time.sleep(60)"], b"x" * 200_000, 2)
    took = time.time() - t0
    print(f"bounded push took {took:.1f}s")
    assert took < 7
    assert fp._ssh_proc == []


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX process groups")
def test_push_timeout_kills_the_grandchild_too(tmp_path):
    pidfile = tmp_path / "gc"
    code = ("import subprocess, sys, time; "
            f"g = subprocess.Popen(['sleep', '300']); open({str(pidfile)!r}, 'w').write(str(g.pid)); "
            "time.sleep(300)")
    with pytest.raises(subprocess.TimeoutExpired):
        fp._push([sys.executable, "-c", code], b"x", 1.5)
    assert _pid_gone(int(pidfile.read_text()))


def test_expired_watchdog_does_not_overwrite_a_finished_push(monkeypatch, tmp_path):
    state = tmp_path / "k.last"
    monkeypatch.setattr(fp.os, "_exit", lambda c: None)
    monkeypatch.setattr(fp, "_pushed", threading.Event())
    fp._pushed.set()
    state.write_text("abc 1.0")
    fp._publish_expired(state)
    assert state.read_text() == "abc 1.0"
    fp._pushed.clear()
    fp._publish_expired(state)
    assert state.read_text().startswith("fail ")
