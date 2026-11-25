"""Deterministic merge gate (ported from Learning Factory D148): MERGE or HOLD from facts only.

Prints `MERGE`, or one `HOLD: <reason>` line per reason. Exit 0 / 1. Read-only.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import yaml

from factory_tools import claims
from factory_tools.ci.exam_integrity import _is_code, _is_exam

MAX_REVIEW_ROUNDS = 2
MAX_CI_ROUNDS = 5
PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
EXAM_GATE = "acceptance / gate"
WORKFLOWS_REPO = "Shashkist/factory"
CI_FILE = ".github/workflows/ci.yml"
RAW = "Accept: application/vnd.github.raw+json"
JOB_URL = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/(\d+)/job/\d+/?$")
VERDICT = re.compile(r"^Review round (\d+): (APPROVE|CHANGES) at ([0-9a-fA-F]{7,40})\s*$")
CLOSES = re.compile(r"^\s*closes\s+#(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def _is_exam_integrity(name: str) -> bool:
    """`exam-integrity`, or a reusable-workflow job named `<caller> / exam-integrity`."""
    return name == "exam-integrity" or name.endswith(" / exam-integrity")


def _check_reasons(checks: list[dict[str, Any]], exam_gate: str = EXAM_GATE) -> list[str]:
    if not checks:
        return ["no checks have run on this PR"]
    reasons = []
    for c in checks:
        name = c.get("name") or c.get("context") or "?"
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if c.get("status", "COMPLETED") != "COMPLETED" or state in ("", "PENDING", "EXPECTED"):
            reasons.append(f"{name} is pending")
        elif state not in PASSED or (
            (_is_exam_integrity(name) or name == exam_gate) and state != "SUCCESS"
        ):
            reasons.append(f"{name} ended in {state.lower()}")
    if not any(_is_exam_integrity(c.get("name") or c.get("context") or "") for c in checks):
        reasons.append("exam-integrity has not run")
    if not any((c.get("name") or c.get("context")) == exam_gate for c in checks):
        reasons.append(f"{exam_gate} has not run")
    return reasons


class _Reads:
    """The D29 reads of one decision (workflow runs, the head's ci.yml, compares), each made once.

    `gh` is scoped to the PR's repository: its `repos/{owner}/{repo}/` paths name it.
    """

    def __init__(self, gh: claims.Run, repo: str | None, wf_repo: str, head: str) -> None:
        self.gh, self.repo, self.wf_repo, self.head = gh, repo, wf_repo, head
        self.cache: dict[str, str | None] = {}

    def _api(self, *args: str) -> str | None:
        key = " ".join(args)
        if key not in self.cache:
            try:
                self.cache[key] = self.gh(["api", *args])
            except (RuntimeError, OSError):
                self.cache[key] = None
        return self.cache[key]

    def run_of(self, url_repo: str, run_id: str) -> dict[str, Any] | None:
        """The run, read in the PR's repository.

        Without `--repo` the PR's repository has no name here, so the run is also read under the
        repository its URL names: run ids are unique across GitHub, so both reads succeed only
        when the URL names the PR's repository.
        """
        texts = [self._api(f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}")]
        if not self.repo:
            texts.append(self._api(f"repos/{url_repo}/actions/runs/{run_id}"))
        if any(t is None for t in texts):
            return None
        try:
            data = json.loads(texts[0] or "")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def ci_jobs(self) -> dict[str, Any] | None:
        """The jobs of the head's ci.yml (raw text, or the API's base64 JSON)."""
        text = self._api("-H", RAW, f"repos/{{owner}}/{{repo}}/contents/{CI_FILE}?ref={self.head}")
        if text is None:
            return None
        try:
            wrapped = json.loads(text)
            if isinstance(wrapped, dict) and wrapped.get("encoding") == "base64":
                text = base64.b64decode(wrapped.get("content") or "").decode("utf-8")
        except ValueError:
            pass
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return jobs if isinstance(jobs, dict) else None

    def on_main(self, sha: str) -> bool:
        """The workflows repository's compare of main with `sha` says `behind` or `identical`."""
        try:
            status = json.loads(self._api(f"repos/{self.wf_repo}/compare/main...{sha}") or "")
        except ValueError:
            return False
        return isinstance(status, dict) and status.get("status") in ("behind", "identical")


def _shown(job_id: str, job: Any) -> str:
    """The name GitHub shows for a job: its `name:`, else its id."""
    name = job.get("name") if isinstance(job, dict) else None
    return str(name) if name else job_id


def _binding_reason(check: dict[str, Any], workflow: str, reads: _Reads) -> str | None:
    """Why a SUCCESS exam check is not backed by the pinned reusable workflow (D29), or None."""
    name = check.get("name") or check.get("context") or "?"
    if check.get("__typename") != "CheckRun":
        return f"{name} is a commit status, not a check run"
    caller, sep, _ = name.partition(" / ")
    if not sep:
        return f"{name} has no caller job part (`<caller> / <job>`)"
    m = JOB_URL.match(check.get("detailsUrl") or "")
    if not m:
        return f"{name}: details URL is not a job of a workflow run"
    url_repo, run_id = m.group(1), m.group(2)
    if reads.repo and url_repo.lower() != reads.repo.lower():
        return f"{name}: details URL is a run of {url_repo}, not of {reads.repo}"
    run = reads.run_of(url_repo, run_id)
    if run is None:
        return f"{name}: run {run_id} is not a readable workflow run of this repository"
    if run.get("path") != CI_FILE:
        return f"{name}: run {run_id} is of {run.get('path')}, not {CI_FILE}"
    if str(run.get("head_sha") or "").lower() != reads.head:
        return f"{name}: run {run_id} is not for head {reads.head[:7]}"
    called = f"{reads.wf_repo}/.github/workflows/{workflow}"
    refs = {
        str(r.get("path")): str(r.get("sha"))
        for r in run.get("referenced_workflows") or []
        if isinstance(r, dict) and str(r.get("path")).partition("@")[0].lower() == called.lower()
    }
    if not refs:
        return f"{name}: run {run_id} does not call {called}"
    jobs = reads.ci_jobs()
    if jobs is None:
        return f"{name}: cannot read {CI_FILE} at head {reads.head[:7]}"
    if any(_shown(j, job) == name for j, job in jobs.items()):
        return f"{name}: a job of {CI_FILE} is shown under the full check name"
    callers = [job for j, job in jobs.items() if _shown(j, job) == caller]
    if len(callers) != 1:
        return f"{name}: {CI_FILE} has {len(callers)} jobs named {caller!r}, not one"
    uses = callers[0].get("uses") if isinstance(callers[0], dict) else None
    if uses not in refs:
        return f"{name}: job {caller!r} does not use the {workflow} that run {run_id} called"
    if not reads.on_main(refs[uses]):
        return f"{name}: {workflow}@{refs[uses][:7]} is not on main of {reads.wf_repo}"
    return None


def _binding_reasons(checks: list[dict[str, Any]], exam_gate: str, reads: _Reads) -> list[str]:
    """D29 for every SUCCESS exam gate and exam-integrity check (other states hold already)."""
    reasons = []
    for c in checks:
        name = c.get("name") or c.get("context") or ""
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if c.get("status", "COMPLETED") != "COMPLETED" or state != "SUCCESS":
            continue
        if name == exam_gate:
            workflow = "junit-gate.yml"
        elif _is_exam_integrity(name):
            workflow = "exam-integrity.yml"
        else:
            continue
        reason = _binding_reason(c, workflow, reads)
        if reason:
            reasons.append(reason)
    return reasons


def _verdicts(comments: list[dict[str, Any]], author: str) -> list[tuple[int, str, str]]:
    found = []
    for c in sorted(comments, key=lambda c: c.get("createdAt", "")):
        if (c.get("author") or {}).get("login") != author:
            continue
        m = VERDICT.match((c.get("body") or "").split("\n", 1)[0])
        if m:
            found.append((int(m.group(1)), m.group(2), m.group(3).lower()))
    return found


def _commit_files(run: claims.Run, repo: str | None, oid: str) -> dict[str, Any]:
    """The commit as `gh api` returns it.

    `gh api` has no `-R`: the repository is named in the path, or the `{owner}/{repo}`
    placeholder is filled from the current checkout (D17).
    """
    path = f"repos/{repo}/commits/{oid}" if repo else f"repos/{{owner}}/{{repo}}/commits/{oid}"
    # --paginate prints one JSON object per page, concatenated with no separator.
    text = run(["api", "--paginate", path])
    decoder = json.JSONDecoder()
    merged: list[Any] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        page, pos = decoder.raw_decode(text, pos)
        merged.extend(page.get("files") or [])
    return {"files": merged}


def _commit_reasons(pr: dict[str, Any], run: claims.Run, repo: str | None) -> list[str]:
    reasons = []
    ci_rounds = 0
    for commit in pr.get("commits") or []:
        oid = commit["oid"]
        files = _commit_files(run, repo, oid)
        pairs = [(f["filename"], f.get("previous_filename")) for f in files.get("files", [])]
        names = [n for pair in pairs for n in pair if n]
        if any(_is_exam(n) for n in names) and any(_is_code(n) for n in names):
            reasons.append(f"commit {oid[:7]} changes tests/acceptance together with code")
        if not (names and all(_is_exam(n) for n in names)):
            ci_rounds += 1
    if ci_rounds > MAX_CI_ROUNDS:
        reasons.append(f"ci round {ci_rounds} is over the limit of {MAX_CI_ROUNDS}")
    return reasons


def _claim_reasons(pr: dict[str, Any], session: str, gh: claims.Run) -> list[str]:
    reasons = []
    closed = {int(n) for n in CLOSES.findall(pr.get("body") or "")}
    pr_repo = (pr.get("url") or "").split("/pull/")[0].lower()
    for ref in pr.get("closingIssuesReferences") or []:
        ref_repo = (ref.get("url") or "").split("/issues/")[0].lower()
        if pr_repo and ref_repo and ref_repo != pr_repo:
            reasons.append(f"closes #{ref.get('number')} in another repository")
        else:
            closed.add(int(ref["number"]))
    if not closed:
        reasons.append("PR body has no `Closes #n` for the issue it ships")
    for n in sorted(closed):
        claim, _ = claims.find_claim(n, gh)
        if not claim or claim.get("session") != session:
            reasons.append(f"claim for #{n} is not held by session {session}")
    return reasons


def decide(
    pr_number: str,
    session: str,
    repo: str | None = None,
    author: str | None = None,
    exam_gate: str = EXAM_GATE,
    run: claims.Run = claims._run,
    workflows_repo: str = WORKFLOWS_REPO,
) -> list[str]:
    """The HOLD reasons for a pull request; empty means MERGE."""
    gh = claims.scoped(run, repo)
    fields = (
        "author,body,headRefOid,isCrossRepository,commits,statusCheckRollup,comments,"
        "url,closingIssuesReferences"
    )
    pr = json.loads(gh(["pr", "view", pr_number, "--json", fields]))
    head = pr["headRefOid"].lower()
    author = author or pr["author"]["login"]
    checks = pr.get("statusCheckRollup") or []
    reasons = _check_reasons(checks, exam_gate)
    reasons += _binding_reasons(checks, exam_gate, _Reads(gh, repo, workflows_repo, head))
    if pr.get("isCrossRepository") is True:
        reasons.append("cross-repository pull request")

    verdicts = _verdicts(pr.get("comments") or [], author)
    for_head = [v for v in verdicts if head.startswith(v[2])]
    if not for_head or for_head[-1][1] != "APPROVE":
        reasons.append(f"no APPROVE verdict for head {head[:7]}")
    rounds = max((v[0] for v in verdicts), default=0)
    if rounds > MAX_REVIEW_ROUNDS:
        reasons.append(f"review round {rounds} is over the limit of {MAX_REVIEW_ROUNDS}")

    return reasons + _commit_reasons(pr, run, repo) + _claim_reasons(pr, session, gh)


def run_command(args: Any) -> int:
    reasons = decide(
        args.pr, args.session, args.repo, args.author, args.exam_gate,
        workflows_repo=args.workflows_repo,
    )
    for r in reasons:
        print("HOLD: " + r)
    if not reasons:
        print("MERGE")
    return 1 if reasons else 0
