"""Deterministic merge gate (ported from Learning Factory D148): MERGE or HOLD from facts only.

Prints `MERGE`, or one `HOLD: <reason>` line per reason. Exit 0 / 1. Read-only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Hashable
from typing import Any

import yaml

from factory_tools import claims
from factory_tools.ci.exam_integrity import _globs, _is_ci_surface, _is_code, _is_exam

MAX_REVIEW_ROUNDS = 2
MAX_CI_ROUNDS = 5
PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
EXAM_GATE = "acceptance / gate"
WORKFLOWS_REPO = "Shashkist/factory"
CI_FILE = ".github/workflows/ci.yml"
RAW = "Accept: application/vnd.github.raw+json"
JOB_URL = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/(\d+)/job/(\d+)/?$")
VERDICT = re.compile(r"^Review round (\d+): (APPROVE|CHANGES) at ([0-9a-fA-F]{7,40})\s*$")
DECIDES = re.compile(r"^Decides: #(\d+) round (\d+)(?:[ .].*)?$")
D_HEADING = re.compile(r"^## D(\d+)\b")
DECISIONS = "docs/factory/DECISIONS.md"
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


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that refuses a mapping with the same key twice (loaders keep the last)."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, Hashable):
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        None, None, f"duplicate key {key!r}", key_node.start_mark
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


class _Reads:
    """The D29 reads of one decision (workflow runs, the head's ci.yml, compares), each made once.

    `gh` is scoped to the PR's repository: its `repos/{owner}/{repo}/` paths name it.
    """

    def __init__(self, gh: claims.Run, repo: str | None, wf_repo: str, head: str) -> None:
        self.gh, self.repo, self.wf_repo, self.head = gh, repo, wf_repo, head
        self.cache: dict[str, str | None] = {}
        self.file_read = False
        self.file_reasons: list[str] = []

    def _api(self, *args: str) -> str | None:
        key = " ".join(args)
        if key not in self.cache:
            try:
                self.cache[key] = self.gh(["api", *args])
            except (RuntimeError, OSError):
                self.cache[key] = None
        return self.cache[key]

    def run_of(self, url_repo: str, run_id: str) -> dict[str, Any] | None:
        """The run, read in the PR's repository."""
        return self._actions("runs", url_repo, run_id)

    def job_of(self, url_repo: str, job_id: str) -> dict[str, Any] | None:
        """The Actions job, read in the PR's repository (D29 amendment 3)."""
        return self._actions("jobs", url_repo, job_id)

    def _actions(self, kind: str, url_repo: str, item_id: str) -> dict[str, Any] | None:
        """A run or job object, each read once.

        Without `--repo` the PR's repository has no name here, so it is also read under the
        repository the URL names: run and job ids are unique across GitHub, so both reads
        succeed only when the URL names the PR's repository.
        """
        texts = [self._api(f"repos/{{owner}}/{{repo}}/actions/{kind}/{item_id}")]
        if not self.repo:
            texts.append(self._api(f"repos/{url_repo}/actions/{kind}/{item_id}"))
        if any(t is None for t in texts):
            return None
        try:
            data = json.loads(texts[0] or "")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def ci_jobs(self) -> dict[str, Any] | None:
        """The jobs of the head's ci.yml (raw form), or None when unreadable or a key repeats.

        The first read also records the file's own HOLD reasons (D29 amendments 1 and 2): a
        job `name:` with an expression, a shown name with ` / `, or a shown name whose white
        space is not single and inner only, cannot be tied to a check name.
        """
        text = self._api("-H", RAW, f"repos/{{owner}}/{{repo}}/contents/{CI_FILE}?ref={self.head}")
        if text is None:
            return None
        try:
            data = yaml.load(text, Loader=_UniqueKeyLoader)
        except yaml.YAMLError:
            return None
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict):
            return None
        if not self.file_read:
            self.file_read = True
            for j, job in jobs.items():
                raw = job.get("name") if isinstance(job, dict) else None
                if "${{" in str(raw or ""):
                    self.file_reasons.append(
                        f"{CI_FILE}: job {j!r} is named by an expression ({raw}),"
                        " which GitHub may show under any check name"
                    )
                elif " / " in _shown(j, job):
                    self.file_reasons.append(
                        f"{CI_FILE}: job {j!r} is shown as {_shown(j, job)!r},"
                        " a name with ' / ' that a called workflow's checks also take"
                    )
                elif _shown(j, job) != " ".join(_shown(j, job).split()):
                    self.file_reasons.append(
                        f"{CI_FILE}: job {j!r} is shown as {_shown(j, job)!r},"
                        " a name with leading, trailing or repeated white space that"
                        " GitHub may show as another job's name"
                    )
        return jobs

    def on_main(self, sha: str) -> bool:
        """The workflows repository's compare of main with `sha` says `behind` or `identical`."""
        try:
            status = json.loads(self._api(f"repos/{self.wf_repo}/compare/main...{sha}") or "")
        except ValueError:
            return False
        return isinstance(status, dict) and status.get("status") in ("behind", "identical")


def _shown(job_id: Any, job: Any) -> str:
    """The name GitHub shows for a job: its `name:`, else its id."""
    name = job.get("name") if isinstance(job, dict) else None
    return str(name) if name else str(job_id)


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
    url_repo, run_id, job_id = m.group(1), m.group(2), m.group(3)
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
    pinned = {path for path, sha in refs.items() if reads.on_main(sha)}
    if not pinned:
        shas = ", ".join(sorted(sha[:7] for sha in refs.values()))
        return f"{name}: {workflow}@{shas} is not on main of {reads.wf_repo}"
    jobs = reads.ci_jobs()
    if jobs is None:
        return f"{name}: cannot read {CI_FILE} at head {reads.head[:7]} as YAML with unique keys"
    if any(_shown(j, job) == name for j, job in jobs.items()):
        return f"{name}: a job of {CI_FILE} is shown under the full check name"
    callers = [job for j, job in jobs.items() if _shown(j, job) == caller]
    if len(callers) != 1:
        return f"{name}: {CI_FILE} has {len(callers)} jobs named {caller!r}, not one"
    uses = callers[0].get("uses") if isinstance(callers[0], dict) else None
    if not isinstance(uses, str):
        return f"{name}: job {caller!r} has a `uses:` that is not a string"
    if uses not in pinned:
        return f"{name}: job {caller!r} does not use a {workflow} on main that run {run_id} called"
    return job_reason(name, run_id, job_id, reads.job_of(url_repo, job_id), reads.head)


def job_reason(
    name: str, run_id: str, job_id: str, job: dict[str, Any] | None, head: str
) -> str | None:
    """Why the details URL's job is not the check run's own Actions job (D29 amendment 3)."""
    if job is None:
        return f"{name}: job {job_id} is not a readable Actions job of this repository"
    if not isinstance(job.get("run_id"), int):
        return f"{name}: job {job_id} has no run_id"
    if not isinstance(job.get("name"), str):
        return f"{name}: job {job_id} has no name"
    if not isinstance(job.get("head_sha"), str):
        return f"{name}: job {job_id} has no head sha"
    if str(job["run_id"]) != run_id:
        return f"{name}: job {job_id} belongs to run {job['run_id']}, not run {run_id}"
    if job["head_sha"].lower() != head:
        return f"{name}: job {job_id} is not for head {head[:7]}"
    if job["name"] != name:
        return f"{name}: job {job_id} is named {job['name']!r}, not the check name"
    if job.get("status") != "completed" or job.get("conclusion") != "success":
        return (
            f"{name}: job {job_id} is {job.get('status')}/{job.get('conclusion')},"
            " not completed with success"
        )
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
    return reasons + reads.file_reasons


def _verdicts(comments: list[dict[str, Any]], author: str) -> list[tuple[int, str, str]]:
    found = []
    for c in sorted(comments, key=lambda c: c.get("createdAt", "")):
        if (c.get("author") or {}).get("login") != author:
            continue
        m = VERDICT.match((c.get("body") or "").split("\n", 1)[0])
        if m:
            found.append((int(m.group(1)), m.group(2), m.group(3).lower()))
    return found


def _d_entries(path: str) -> list[tuple[int, str]]:
    """The D-entries of a decision log: `## D<n>` to the next `## ` line. Missing file: none."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    entries: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        m = D_HEADING.match(line)
        if m:
            current = []
            entries.append((int(m.group(1)), current))
        elif line.startswith("## "):
            current = None
        if current is not None:
            current.append(line)
    return [(n, "\n".join(body)) for n, body in entries]


def _decided_rounds(
    entries: list[tuple[int, str]], refs: set[int], rounds: list[int]
) -> dict[int, list[int]]:
    """For each round, the D-entries with a `Decides: #<n> round <k>` line for this PR or issue."""
    found: dict[int, list[int]] = {}
    for n, text in entries:
        for line in text.splitlines():
            m = DECIDES.match(line)
            if m and int(m.group(1)) in refs and int(m.group(2)) in rounds:
                ids = found.setdefault(int(m.group(2)), [])
                if n not in ids:
                    ids.append(n)
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


def _commit_reasons(
    pr: dict[str, Any],
    run: claims.Run,
    repo: str | None,
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
) -> list[str]:
    """Exam-with-code mixing per commit, CI rounds, and (with globs given) exam with CI surface."""
    reasons = []
    ci_rounds = 0
    all_names: list[str] = []
    for commit in pr.get("commits") or []:
        oid = commit["oid"]
        files = _commit_files(run, repo, oid)
        pairs = [(f["filename"], f.get("previous_filename")) for f in files.get("files", [])]
        names = [n for pair in pairs for n in pair if n]
        all_names += names
        if any(_is_exam(n, exam_paths) for n in names) and any(
            _is_code(n, exam_paths) for n in names
        ):
            reasons.append(f"commit {oid[:7]} changes tests/acceptance together with code")
        if not (names and all(_is_exam(n, exam_paths) for n in names)):
            ci_rounds += 1
    if ci_rounds > MAX_CI_ROUNDS:
        reasons.append(f"ci round {ci_rounds} is over the limit of {MAX_CI_ROUNDS}")
    if (
        (exam_paths is not None or ci_paths is not None)
        and any(_is_exam(n, exam_paths) for n in all_names)
        and any(_is_ci_surface(n, ci_paths) for n in all_names)
    ):
        reasons.append("PR changes the exam together with the CI surface")
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
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
    decisions: str = DECISIONS,
    notes: list[str] | None = None,
) -> list[str]:
    """The HOLD reasons for a pull request; empty means MERGE.

    Past the review-round limit (D36) every extra round needs a D-entry; the entries matched are
    appended to `notes`.
    """
    gh = claims.scoped(run, repo)
    fields = (
        "number,author,body,headRefOid,isCrossRepository,commits,statusCheckRollup,comments,"
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
    extra = [v for v in verdicts if v[0] > MAX_REVIEW_ROUNDS]
    if extra:
        if verdicts[-1][1] != "APPROVE" or not head.startswith(verdicts[-1][2]):
            reasons.append("the latest verdict is not an APPROVE at the head, past the limit")
        refs = {int(pr["number"])}
        refs |= {int(r["number"]) for r in pr.get("closingIssuesReferences") or []}
        refs |= {int(n) for n in CLOSES.findall(pr.get("body") or "")}
        numbers = sorted({v[0] for v in extra})
        decided = _decided_rounds(_d_entries(decisions), refs, numbers)
        for k in numbers:
            if k not in decided:
                reasons.append(
                    f"review round {k} is over the limit of {MAX_REVIEW_ROUNDS} "
                    "and no D-entry names it"
                )
        # The span that asks for the extra rounds: from the first verdict at the limit, or the
        # verdict just before the first extra round if that comes earlier, to the latest. Round
        # labels alone cannot be trusted here: a verdict labelled low may sit inside the span.
        first_extra = next(i for i, v in enumerate(verdicts) if v[0] > MAX_REVIEW_ROUNDS)
        at_limit = next(i for i, v in enumerate(verdicts) if v[0] >= MAX_REVIEW_ROUNDS)
        if first_extra == 0:
            reasons.append(
                f"review round {verdicts[0][0]} was not asked for by a CHANGES verdict on this PR"
            )
        tail = verdicts[max(0, min(at_limit, first_extra - 1)):]
        for v in tail[:-1]:
            if v[1] != "CHANGES":
                reasons.append(f"review round {v[0]} was not a CHANGES verdict, more followed")
        for a, b in zip(tail, tail[1:], strict=False):
            if b[0] <= a[0]:
                reasons.append(f"review round {b[0]} follows round {a[0]}, not strictly after it")
        if notes is not None:
            by_entry: dict[int, list[int]] = {}
            for k, ids in decided.items():
                for n in ids:
                    by_entry.setdefault(n, []).append(k)
            notes += [
                f"D{n} decides " + ", ".join(f"round {k}" for k in sorted(ks))
                for n, ks in sorted(by_entry.items())
            ]

    reasons += _commit_reasons(pr, run, repo, exam_paths, ci_paths)
    return reasons + _claim_reasons(pr, session, gh)


def run_command(args: Any) -> int:
    notes: list[str] = []
    reasons = decide(
        args.pr, args.session, args.repo, args.author, args.exam_gate,
        workflows_repo=args.workflows_repo,
        exam_paths=_globs(args.exam_paths),
        ci_paths=_globs(args.ci_paths),
        decisions=args.decisions,
        notes=notes,
    )
    for r in reasons:
        print("HOLD: " + r)
    if not reasons:
        for note in notes:
            print(note)
        print("MERGE")
    return 1 if reasons else 0
