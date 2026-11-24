"""Deterministic merge gate (ported from Learning Factory D148): MERGE or HOLD from facts only.

Prints `MERGE`, or one `HOLD: <reason>` line per reason. Exit 0 / 1. Read-only.
"""

from __future__ import annotations

import json
import re
from typing import Any

from factory_tools import claims
from factory_tools.ci.exam_integrity import _is_code, _is_exam

MAX_REVIEW_ROUNDS = 2
MAX_CI_ROUNDS = 5
PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
VERDICT = re.compile(r"^Review round (\d+): (APPROVE|CHANGES) at ([0-9a-fA-F]{7,40})\s*$")
CLOSES = re.compile(r"^\s*closes\s+#(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def _check_reasons(checks: list[dict[str, Any]]) -> list[str]:
    if not checks:
        return ["no checks have run on this PR"]
    reasons = []
    for c in checks:
        name = c.get("name") or c.get("context") or "?"
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if c.get("status", "COMPLETED") != "COMPLETED" or state in ("", "PENDING", "EXPECTED"):
            reasons.append(f"{name} is pending")
        elif state not in PASSED or (name == "exam-integrity" and state != "SUCCESS"):
            reasons.append(f"{name} ended in {state.lower()}")
    if not any((c.get("name") or c.get("context")) == "exam-integrity" for c in checks):
        reasons.append("exam-integrity has not run")
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
    """The commit as `gh api` returns it: the full repository path, else `-R` on the placeholder."""
    placeholder = f"repos/{{owner}}/{{repo}}/commits/{oid}"
    path = f"repos/{repo}/commits/{oid}" if repo else placeholder
    try:
        files: dict[str, Any] = json.loads(run(["api", path]))
    except RuntimeError:
        if not repo:
            raise
        files = json.loads(run(["api", placeholder, "-R", repo]))
    return files


def _commit_reasons(pr: dict[str, Any], run: claims.Run, repo: str | None) -> list[str]:
    reasons = []
    ci_rounds = 0
    for commit in pr.get("commits") or []:
        oid = commit["oid"]
        files = _commit_files(run, repo, oid)
        names = [f["filename"] for f in files.get("files", [])]
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
    run: claims.Run = claims._run,
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
    reasons = _check_reasons(pr.get("statusCheckRollup") or [])
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
    reasons = decide(args.pr, args.session, args.repo, args.author)
    for r in reasons:
        print("HOLD: " + r)
    if not reasons:
        print("MERGE")
    return 1 if reasons else 0
