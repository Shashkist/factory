"""A world for the merge gate exam: a fake `gh` with one pull request (#9) that is good.

The gate is run as a real command (`python -m factory_tools merge-gate ...`, the same entry
point as the `factory-tools` script). The fake `gh` is wired in by a sitecustomize on
PYTHONPATH that redirects subprocess calls whose program is `gh` to fake_gh_merge_gate.py,
so no PATH tricks are needed (same device as the claims exam). No live GitHub call is made.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from helpers import SRC, env

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from factory_tools import claims  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_gh_merge_gate.py"
HERE = "Shashkist/factory"
OTHER = "Shashkist/Learning_factory"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OLD = "0123456789abcdef0123456789abcdef01234567"
EXAM_FILE = "tests/acceptance/test_issue_5_x.py"
CODE_FILE = "src/factory_tools/thing.py"
SESSION = "lf-pass-1"
EXAM_GATE = "acceptance / gate"

SITECUSTOMIZE = '''\
import shutil
import subprocess
import sys

_FAKE = {fake!r}
_init = subprocess.Popen.__init__
_which = shutil.which


def _patched(self, args, *a, **k):
    if isinstance(args, (list, tuple)) and args and str(args[0]) in ("gh", "gh.exe"):
        args = [sys.executable, _FAKE, *args[1:]]
    _init(self, args, *a, **k)


def _which_gh(cmd, *a, **k):
    found = _which(cmd, *a, **k)
    return found or ("gh" if str(cmd) in ("gh", "gh.exe") else None)


subprocess.Popen.__init__ = _patched
shutil.which = _which_gh
'''


def check(name: str, conclusion: str = "SUCCESS", status: str = "COMPLETED") -> dict[str, str]:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def good_checks() -> list[dict[str, str]]:
    return [check("unit"), check("exam-integrity")]


def verdict(
    kind: str = "APPROVE",
    sha: str = HEAD,
    k: int = 1,
    author: str = "Shashkist",
    at: str = "2026-11-24T10:00:00Z",
    body: str | None = None,
) -> dict[str, Any]:
    first = body if body is not None else "Review round " + str(k) + ": " + kind + " at " + sha
    return {"author": {"login": author}, "body": first + "\n\nDetails follow.", "createdAt": at}


def claim_comment(
    session: str = SESSION, released: bool = False, number: int = 5
) -> dict[str, Any]:
    if released:
        body = claims.retraction(session, "done")
    else:
        now = claims.now()
        body = claims.render(
            {"session": session, "branch": "f/5-x", "worktree": "C:/wt", "claimed": now,
             "heartbeat": now, "step": "ship"}
        )
    url = "https://github.com/o/r/issues/" + str(number) + "#issuecomment-77"
    return {"body": body, "url": url}


def code_commits(n: int, last: str = HEAD) -> tuple[list[str], list[dict[str, str]]]:
    """n commit ids ending in `last`, all meant to change code."""
    oids = [format(i + 1, "040x") for i in range(n - 1)] + [last]
    return oids, [{"oid": o} for o in oids]


class Gate:
    """One pull request (#9) in HERE and OTHER, good by default; `over` overrides PR fields."""

    def __init__(self, base: Path, **over: Any) -> None:
        self.base = base
        self.state_path = base / "state.json"
        (base / "home").mkdir()
        (base / "work").mkdir()
        (base / "site").mkdir()
        (base / "site" / "sitecustomize.py").write_text(
            SITECUSTOMIZE.format(fake=str(FAKE)), encoding="utf-8"
        )
        pr: dict[str, Any] = {
            "author": {"login": "Shashkist"},
            "body": "What.\n\nCloses #5\n",
            "headRefOid": HEAD,
            "commits": [{"oid": OLD}, {"oid": HEAD}],
            "statusCheckRollup": good_checks(),
            "comments": [verdict()],
            "url": "https://github.com/" + HERE + "/pull/9",
        }
        pr.update(over)
        self.pr = pr
        self.files: dict[str, list[str]] = {OLD: [EXAM_FILE], HEAD: [CODE_FILE]}
        self.issues: dict[str, list[dict[str, Any]]] = {"5": [claim_comment()]}
        # The conclusion of the exam gate check added to a non-empty rollup that lacks one
        # (#76: the gate needs it to be SUCCESS). None adds nothing, so it is missing.
        self.exam_gate: str | None = "SUCCESS"

    def write(self) -> None:
        pr = dict(self.pr)
        rollup = list(pr.get("statusCheckRollup") or [])
        if rollup and self.exam_gate and not any(c.get("name") == EXAM_GATE for c in rollup):
            pr["statusCheckRollup"] = rollup + [check(EXAM_GATE, self.exam_gate)]
        repo = {"prs": {"9": pr}, "commits": self.files, "issues": self.issues}
        self.state_path.write_text(
            json.dumps({"default": HERE, "calls": [], "writes": [],
                        "repos": {HERE: repo, OTHER: repo}}),
            encoding="utf-8",
        )

    def state(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def calls(self) -> list[list[str]]:
        calls: list[list[str]] = self.state()["calls"]
        return calls

    def command(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """`factory-tools <argv>` against the fake gh, in an empty directory."""
        self.write()
        e = env(
            {
                "FAKE_GH_STATE": str(self.state_path),
                "HOME": str(self.base / "home"),
                "USERPROFILE": str(self.base / "home"),
            }
        )
        e["PYTHONPATH"] = str(self.base / "site") + os.pathsep + e["PYTHONPATH"]
        proc = subprocess.run(
            [sys.executable, "-m", "factory_tools", *argv],
            cwd=self.base / "work",
            env=e,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert self.state()["writes"] == [], "the gate must be read-only"
        return proc

    def run(self, *extra: str, session: str = SESSION) -> tuple[int, list[str]]:
        """The gate on PR 9: (exit code, non-empty stdout lines)."""
        proc = self.command("merge-gate", "9", "--session", session, *extra)
        return proc.returncode, [ln for ln in proc.stdout.splitlines() if ln.strip()]


def holds(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.startswith("HOLD: ")]


def assert_single_hold(result: tuple[int, list[str]], *words: str) -> None:
    code, lines = result
    assert code == 1, result
    assert len(lines) == 1 and lines[0].startswith("HOLD: "), lines
    for w in words:
        assert w.lower() in lines[0].lower(), (w, lines)

