"""Bounded stdin and a whole-process watchdog for Claude Code hook scripts (#230).

A hook blocked in sys.stdin.read() never exits when its parent died or the pipe stays open, and
orphans pile up. Read in a daemon thread with a bounded join, and kill the process at WATCHDOG_S.
"""

from __future__ import annotations

import os
import sys
import threading

STDIN_TIMEOUT_S = 10.0
WATCHDOG_S = 30.0


def read_stdin(timeout: float | None = None) -> str | None:
    """All of stdin, or None if it did not close within `timeout` seconds (env
    LF_HOOK_STDIN_TIMEOUT)."""
    if timeout is None:
        timeout = float(os.environ.get("LF_HOOK_STDIN_TIMEOUT") or STDIN_TIMEOUT_S)
    box: list[str] = []
    t = threading.Thread(target=lambda: box.append(sys.stdin.read()), daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def start_watchdog(exit_code: int) -> threading.Timer:
    """Hard-exit the process with `exit_code` after WATCHDOG_S (env LF_HOOK_WATCHDOG_S)."""
    s = float(os.environ.get("LF_HOOK_WATCHDOG_S") or WATCHDOG_S)
    timer = threading.Timer(s, os._exit, (exit_code,))
    timer.daemon = True
    timer.start()
    return timer
