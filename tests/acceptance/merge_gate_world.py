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

# D29 (#80): the exam gate and exam-integrity results only count when they are backed by a run
# of the pinned reusable workflows. The default world backs every protected SUCCESS check run
# that carries no run data of its own with a genuine, valid run (see `Gate.auto_backing`).
WF_REPO = "Shashkist/factory"
PIN = "34f9188d89b057f5cf753b3112e312a6689c88b2"
RUN_ID = "45624202389"
GATE_FILE = "junit-gate.yml"
INTEGRITY_FILE = "exam-integrity.yml"
CI_PATH = ".github/workflows/ci.yml"


def uses(workflow: str, pin: str = PIN, wf_repo: str = WF_REPO) -> str:
    return wf_repo + "/.github/workflows/" + workflow + "@" + pin


def job_url(repo: str, run_id: str, job_id: str) -> str:
    return "https://github.com/" + repo + "/actions/runs/" + run_id + "/job/" + job_id


def real_run(
    head: str = HEAD,
    refs: list[tuple[str, str]] | None = None,
    path: str = CI_PATH,
    event: str = "pull_request",
) -> dict[str, Any]:
    """A workflow run of ci.yml as `gh api repos/<r>/actions/runs/<id>` returns it.

    `refs` are (path@sha, sha) pairs; by default the two reusable workflows this repository's
    ci.yml calls, both listed, as GitHub does even for a skipped caller job.
    """
    if refs is None:
        refs = [(uses(GATE_FILE), PIN), (uses(INTEGRITY_FILE), PIN)]
    return {
        "id": 1,
        "path": path,
        "head_sha": head,
        "event": event,
        "referenced_workflows": [{"path": p, "sha": s} for p, s in refs],
    }


def caller(job_id: str, workflow: str, pin: str = PIN, wf_repo: str = WF_REPO, **extra: str) -> str:
    """A caller job of a reusable workflow (extra keys like `if_` are written as `if:`)."""
    lines = ["  " + job_id + ":"]
    for k, v in extra.items():
        lines.append("    " + k.rstrip("_").replace("_", "-") + ": " + v)
    lines.append("    uses: " + uses(workflow, pin, wf_repo))
    return "\n".join(lines) + "\n"


def plain_job(job_id: str, shown: str | None = None) -> str:
    """An ordinary job whose only step is `run: true`, optionally shown under another name."""
    named = "    name: " + shown + "\n" if shown else ""
    steps = "    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"
    return "  " + job_id + ":\n" + named + steps


CI_HEAD = (
    "name: CI\n\non:\n  pull_request:\n  push:\n    branches: [main]\n\njobs:\n"
    "  checks:\n    name: Lint, types, unit tests\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: uv run pytest tests/unit -q\n"
)


def ci_yml(*jobs: str) -> str:
    """A ci.yml; with no jobs given, the callers of this repository's own ci.yml."""
    if not jobs:
        jobs = (
            caller("acceptance", GATE_FILE),
            caller("exam-integrity", INTEGRITY_FILE, if_="github.event_name == 'pull_request'"),
        )
    return CI_HEAD + "".join(jobs)


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


def run_check(
    name: str, repo: str, run_id: str, job_id: str, conclusion: str = "SUCCESS"
) -> dict[str, str]:
    """A check run as `gh pr view --json statusCheckRollup` shows it, backed by a job URL."""
    c = check(name, conclusion)
    c["detailsUrl"] = job_url(repo, run_id, job_id)
    c["workflowName"] = "CI"
    return c


def status_context(context: str, state: str = "SUCCESS") -> dict[str, str]:
    return {
        "__typename": "StatusContext",
        "context": context,
        "state": state,
        "targetUrl": "https://example.invalid/status",
    }


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
        # D29 data served by the fake gh. `runs` maps a run id to its API object, `ci_yml` is the
        # head's ci.yml text, `compare` maps a workflows-repo sha to its compare status against
        # main. While `runs` is None (the default) the world backs every protected SUCCESS
        # check run without run data by a valid run (`auto_backing`); a case that sets `runs`
        # owns all three and the rollup's details URLs.
        self.runs: dict[str, dict[str, Any]] | None = None
        self.ci_yml: str | None = None
        self.compare: dict[str, str] = {PIN: "behind"}
        self.wf_repo = WF_REPO
        self.pr_repo = HERE
        self.exam_gate_name = EXAM_GATE

    def auto_backing(
        self, rollup: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        """The rollup with run data added to protected SUCCESS check runs, the runs, ci.yml.

        A bare `exam-integrity` is shown as `exam-integrity / exam-integrity`, the name a
        reusable-workflow call really gives it (a caller job cannot also be the job shown under
        the full check name).
        """
        out: list[dict[str, Any]] = []
        runs: dict[str, Any] = {}
        callers: dict[str, str] = {}
        for c in rollup:
            name = c.get("name") or ""
            integrity = name == "exam-integrity" or name.endswith(" / exam-integrity")
            gate = name in (EXAM_GATE, self.exam_gate_name)
            if (
                c.get("__typename") != "CheckRun"
                or c.get("conclusion") != "SUCCESS"
                or c.get("detailsUrl")
                or not (integrity or gate)
            ):
                out.append(c)
                continue
            if name == "exam-integrity":
                name = "exam-integrity / exam-integrity"
            if " / " not in name:
                out.append(c)
                continue
            job_id = str(100 + len(out))
            c = dict(c, name=name, detailsUrl=job_url(self.pr_repo, RUN_ID, job_id))
            out.append(c)
            prefix = name.split(" / ")[0]
            callers[prefix] = caller(
                prefix, INTEGRITY_FILE if integrity else GATE_FILE, wf_repo=self.wf_repo
            )
            runs[RUN_ID] = real_run(
                refs=[
                    (uses(GATE_FILE, wf_repo=self.wf_repo), PIN),
                    (uses(INTEGRITY_FILE, wf_repo=self.wf_repo), PIN),
                ]
            )
        return out, runs, ci_yml(*callers.values()) if callers else ci_yml()

    def write(self) -> None:
        pr = dict(self.pr)
        rollup = list(pr.get("statusCheckRollup") or [])
        if rollup and self.exam_gate and not any(c.get("name") == EXAM_GATE for c in rollup):
            rollup = rollup + [check(EXAM_GATE, self.exam_gate)]
        runs, text = self.runs, self.ci_yml
        if runs is None:
            rollup, runs, text = self.auto_backing(rollup)
        pr["statusCheckRollup"] = rollup
        repo = {"prs": {"9": pr}, "commits": self.files, "issues": self.issues}
        repos = {HERE: repo, OTHER: repo}
        repos.setdefault(self.wf_repo, repo)
        keys = {self.pr_repo.lower(), HERE.lower(), OTHER.lower()}
        contents = {k: {CI_PATH + "@" + pr["headRefOid"]: text or ci_yml()} for k in keys}
        self.state_path.write_text(
            json.dumps({"default": HERE, "calls": [], "writes": [], "repos": repos,
                        "runs": {k: runs for k in keys}, "contents": contents,
                        "compare": {self.wf_repo.lower(): self.compare}}),
            encoding="utf-8",
        )

    def state(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def workflow_calls(self) -> list[list[str]]:
        calls: list[list[str]] = self.state().get("workflow_calls", [])
        return calls

    def calls(self) -> list[list[str]]:
        calls: list[list[str]] = self.state()["calls"]
        return calls

    def command(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """`factory-tools <argv>` against the fake gh, in an empty directory."""
        if "--repo" in argv:
            self.pr_repo = argv[argv.index("--repo") + 1]
        if "--workflows-repo" in argv and self.runs is None:
            self.wf_repo = argv[argv.index("--workflows-repo") + 1]
        if "--exam-gate" in argv:
            self.exam_gate_name = argv[argv.index("--exam-gate") + 1]
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

