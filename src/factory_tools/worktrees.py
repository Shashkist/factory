"""Remove the worktrees and local branches whose work is finished (#47).

A worktree is removed only when its work is safe somewhere else: the PR merged, or the PR closed
and the branch is on the remote, or (a subagent worktree idle longer than the stale-claim window
and older than this pass) its tip commit is on a remote branch. Anything with tracked changes, a
live claim, an open PR or no PR is KEPT. Untracked-only worktrees are removed after their names
are listed. The main worktree and the worktree the command runs from are never touched. A folder
the OS reports busy is SKIPPED with one line, never forced.

One line per worktree: `<STATUS> <path> <reason>`, STATUS REMOVED | KEPT | SKIPPED. `--dry-run`
prints the same words and changes nothing. gh is only read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory_tools import claims

TIMEOUT = 120
STALE_AFTER = claims.DEFAULT_STALE_AFTER.total_seconds()
FEATURE = re.compile(r"^f/(\d+)-")
MAX_NAMES = 20

Status = tuple[list[str], list[str], list[str]]
Gh = Callable[[list[str]], str]


def decide_feature(
    prs: list[dict[str, Any]],
    claimed: bool,
    merged_safe: Callable[[list[dict[str, Any]]], tuple[bool, str]],
    remote_safe: Callable[[], tuple[bool, str]],
) -> tuple[bool, str]:
    """(remove?, reason) for an `f/<n>-...` branch.

    The two callables are only called when needed and return (ok, why).
    """
    if claimed:
        return False, "issue has a live claim"
    if not prs:
        return False, "no PR for this branch"
    if any(p.get("state") == "OPEN" for p in prs):
        return False, "PR is open"
    merged = [p for p in prs if p.get("state") == "MERGED" or p.get("mergedAt")]
    if merged:
        ok, why = merged_safe(merged)
        return (True, "PR merged") if ok else (False, why)
    ok, why = remote_safe()
    return (True, "PR closed, branch tip is on the remote") if ok else (False, why)


def decide_subagent(
    created: float, pass_start: float | None, tip_on_remote: bool, now: float | None = None
) -> tuple[bool, str]:
    """(remove?, reason) for a subagent worktree from its last activity and whether it is pushed."""
    if pass_start is None:
        return False, "no --pass-start, age unknown"
    if created >= pass_start:
        return False, "created in this pass"
    if (time.time() if now is None else now) - created < STALE_AFTER:
        return False, "recent activity inside the stale-claim window"
    if tip_on_remote:
        return True, "older than this pass, tip is on the remote"
    return False, "older than this pass but the tip is not on any remote branch"


def git(cwd: Path | str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=TIMEOUT, check=False,
    )


def parse_worktrees(porcelain: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for block in porcelain.strip().split("\n\n"):
        wt: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            wt[key] = value
        if "worktree" in wt:
            wt["branch"] = wt.get("branch", "").removeprefix("refs/heads/")
            out.append(wt)
    return out


def split_status(path: Path) -> Status | None:
    """(tracked changes, untracked, ignored) of a worktree, None when git cannot say."""
    r = git(path, "status", "--porcelain", "--ignored=matching")
    if r.returncode != 0:
        return None
    out = r.stdout.splitlines()
    tracked = [ln[3:] for ln in out if not ln.startswith(("??", "!!"))]
    untracked = [ln[3:] for ln in out if ln.startswith("??")]
    ignored = [ln[3:] for ln in out if ln.startswith("!!")]
    return tracked, untracked, ignored


def is_ancestor(cwd: Path, commit: str, of: str) -> bool | None:
    """True / False, None when git cannot tell (for example the object is not here)."""
    rc = git(cwd, "merge-base", "--is-ancestor", commit, of).returncode
    return True if rc == 0 else False if rc == 1 else None


def merged_safe(main_root: Path, tip: str, merged: list[dict[str, Any]]) -> tuple[bool, str]:
    """The local tip must be a merged head or inside one: nothing was committed after the merge."""
    heads = [p["headRefOid"] for p in merged if p.get("headRefOid")]
    if not heads:
        return False, "merged PR has no head commit to compare with the local tip"
    answers = [is_ancestor(main_root, tip, h) for h in heads]
    if any(a is True for a in answers):
        return True, "ok"
    if any(a is None for a in answers):
        return False, "merged head not available locally"
    return False, "local commits after the merge"


def remote_safe(main_root: Path, branch: str, tip: str, dry_run: bool = False) -> tuple[bool, str]:
    """Ask the remote itself (not a tracking ref); the tip must be inside its branch."""
    r = git(main_root, "ls-remote", "origin", "refs/heads/" + branch)
    if r.returncode != 0:
        return False, "remote unreachable, cannot confirm the branch is pushed"
    head = r.stdout.split()[:1]
    if not head:
        return False, "branch is not on the remote"
    if is_ancestor(main_root, tip, head[0]):
        return True, "ok"
    if dry_run:
        return False, "would fetch to confirm the branch is pushed"
    git(main_root, "fetch", "-q", "origin", "refs/heads/" + branch)
    if is_ancestor(main_root, tip, head[0]):
        return True, "ok"
    return False, "local commits are not on the remote branch"


def tip_on_remote(main_root: Path, tip: str, dry_run: bool = False) -> tuple[bool, str]:
    """Ask the remote for its heads; the tip must be one of them or inside one."""
    if not tip:
        return False, "cannot read the branch tip"
    r = git(main_root, "ls-remote", "origin", "refs/heads/*")
    if r.returncode != 0:
        return False, "remote unreachable, cannot confirm the tip is pushed"
    heads = [ln.split()[0] for ln in r.stdout.splitlines() if ln.split()]
    if tip in heads:
        return True, "ok"
    missing = [h for h in heads if git(main_root, "cat-file", "-e", h + "^{commit}").returncode]
    if missing:
        if dry_run:
            return False, "would fetch to confirm the tip is pushed"
        git(main_root, "fetch", "-q", "origin")
    if any(is_ancestor(main_root, tip, h) is True for h in heads):
        return True, "ok"
    return False, "older than this pass but the tip is not on any remote branch"


def parse_iso(text: str) -> float:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def say(status: str, path: Path, reason: str) -> None:
    print(f"{status} {path} {reason}", flush=True)


def list_names(untracked: list[str], ignored: list[str]) -> str:
    lines = []
    for label, items in (("untracked", untracked), ("ignored", ignored)):
        if items:
            more = f", ... and {len(items) - MAX_NAMES} more" if len(items) > MAX_NAMES else ""
            lines.append(f"  {label}: " + ", ".join(items[:MAX_NAMES]) + more)
    return "\n".join(lines)


def folder_is_free(path: Path) -> bool:
    """Rename the folder away and back: a folder some process holds (Windows) refuses."""
    tmp = path.with_name(f"{path.name}.ft-free-check-{os.getpid()}")
    try:
        path.rename(tmp)
    except OSError:
        return False
    try:
        tmp.rename(path)
    except OSError:
        print(f"WARNING {tmp} could not be renamed back to {path}", flush=True)
        return False
    return True


def remove(main_root: Path, path: Path, branch: str, reason: str, dry_run: bool) -> None:
    status = split_status(path)
    if status is None:
        say("KEPT", path, "git status failed, cannot tell what is in it")
        return
    tracked, untracked, ignored = status
    if tracked:
        say("KEPT", path, "tracked changes: " + ", ".join(tracked[:5]))
        return
    names = list_names(untracked, ignored)
    if dry_run:
        say("REMOVED", path, "would remove (" + reason + ")")
        if names:
            print(names, flush=True)
        return
    if names:
        print(names, flush=True)
    if not folder_is_free(path):
        say("SKIPPED", path, "busy")
        return
    r = git(main_root, "worktree", "remove", "--force", str(path))
    if r.returncode != 0 or path.exists():
        first = (r.stderr.strip().splitlines() or ["folder still present"])[0]
        say("SKIPPED", path, "busy, not removed: " + first)
        return
    if branch:
        git(main_root, "branch", "-D", branch)
    say("REMOVED", path, reason)


def newest_under(p: Path, limit: int = 5000) -> list[Path]:
    """The path itself and, for a folder, what is inside it (bounded)."""
    found = [p]
    if p.is_dir() and not p.is_symlink():
        for root, dirs, files in os.walk(p):
            found += [Path(root) / n for n in dirs + files]
            if len(found) > limit:
                break
    return found


def changed_paths(path: Path, status: Status) -> list[Path]:
    """Modified and untracked paths: a file a live session just wrote counts as activity."""
    tracked, untracked, _ = status
    out: list[Path] = []
    for entry in [e.split(" -> ")[-1] for e in tracked] + untracked:
        out += newest_under(path / entry.strip('"'))
    return out


def last_activity_files(path: Path) -> list[Path]:
    """The git files a live session keeps writing: the index and the HEAD reflog."""
    r = git(path, "rev-parse", "--absolute-git-dir")
    if r.returncode != 0 or not r.stdout.strip():
        return []
    gd = Path(r.stdout.strip())
    return [gd / "index", gd / "logs" / "HEAD"]


def _judge_feature(
    branch: str, issue: int, main_root: Path, path: Path, dry_run: bool, gh: Gh
) -> None:
    try:
        claim, _ = claims.find_claim(issue, gh)
        prs = json.loads(
            gh(["pr", "list", "--head", branch, "--state", "all",
                "--json", "number,state,mergedAt,headRefOid"])
        )
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        say("KEPT", path, "gh unavailable: " + str(e)[:80])
        return
    tip = git(path, "rev-parse", "HEAD").stdout.strip()
    if not tip:
        say("KEPT", path, "cannot read the branch tip")
        return
    go, reason = decide_feature(
        prs, claim is not None,
        lambda merged: merged_safe(main_root, tip, merged),
        lambda: remote_safe(main_root, branch, tip, dry_run),
    )
    if go:
        remove(main_root, path, branch, reason, dry_run)
    else:
        say("KEPT", path, reason)


def _judge_subagent(
    branch: str, main_root: Path, path: Path, dry_run: bool, pass_start: float | None
) -> None:
    # read the git files' times first: `git status` refreshes the index itself
    stamps = [path, path / ".git", *last_activity_files(path)]
    created = max(f.stat().st_mtime for f in stamps if f.exists())
    status = split_status(path)
    if status is None:
        say("KEPT", path, "git status failed, cannot tell what is in it")
        return
    touched = [f.stat().st_mtime for f in changed_paths(path, status) if f.exists()]
    created = max([created, *touched])
    go, reason = decide_subagent(created, pass_start, True)
    if go:
        tip = git(path, "rev-parse", "HEAD").stdout.strip()
        go, why = tip_on_remote(main_root, tip, dry_run)
        reason = reason if go else why
    if go:
        remove(main_root, path, branch, reason, dry_run)
    else:
        say("KEPT", path, reason)


def judge(
    wt: dict[str, str], main_root: Path, here: Path, args: argparse.Namespace,
    pass_start: float | None, gh: Gh,
) -> None:
    path = Path(wt["worktree"]).resolve()
    branch = wt["branch"]
    m = FEATURE.match(branch)
    if args.issue is not None and not (m and int(m.group(1)) == args.issue):
        return
    if path == here:
        say("KEPT", path, "the worktree this command runs from")
    elif not path.exists():
        say("KEPT", path, "folder missing, left to git worktree prune")
    elif "locked" in wt:
        say("KEPT", path, "locked" + (": " + wt["locked"] if wt["locked"] else ""))
    elif m:
        _judge_feature(branch, int(m.group(1)), main_root, path, args.dry_run, gh)
    elif (
        branch.startswith("worktree-agent-")
        and path.parent.name == "worktrees"
        and path.name.startswith("agent-")
    ):
        _judge_subagent(branch, main_root, path, args.dry_run, pass_start)
    else:
        say("KEPT", path, "not a factory branch")


def claimed_by_git(main_root: Path, d: Path) -> bool:
    """True when git's own records point at folder d: a worktree being added right now.

    A real leftover's .git file points at an admin dir that no longer exists. An unreadable
    record counts as claimed.
    """
    try:
        dot_git = d / ".git"
        if dot_git.is_file():
            text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("gitdir:") and Path(text[len("gitdir:"):].strip()).exists():
                return True
        target = d.resolve()
        admin_root = main_root / ".git" / "worktrees"
        if admin_root.is_dir():
            for admin in admin_root.iterdir():
                record = admin / "gitdir"
                if record.is_file():
                    points_at = Path(record.read_text(encoding="utf-8", errors="replace").strip())
                    if points_at.parent.resolve() == target:
                        return True
    except OSError:
        return True
    return False


def sweep_leftovers(main_root: Path, known: set[Path], dry_run: bool) -> None:
    """Folders under .claude/worktrees unknown to git that hold nothing or only a .git file."""
    for d in sorted((main_root / ".claude" / "worktrees").glob("*")):
        if not d.is_dir() or d.resolve() in known:
            continue
        entries = list(d.iterdir())
        if not entries:
            what = "empty leftover folder"
        elif len(entries) == 1 and entries[0].name == ".git" and entries[0].is_file():
            what = "leftover folder with only a .git file"
        else:
            say("KEPT", d, "unknown to git but holds files")
            continue
        if claimed_by_git(main_root, d):
            say("KEPT", d, "git records point at it (a worktree being added)")
            continue
        if dry_run:
            say("REMOVED", d, "would remove (" + what + ")")
        else:
            try:
                shutil.rmtree(d)
                say("REMOVED", d, what)
            except OSError as e:
                say("SKIPPED", d, "busy, not removed: " + str(e)[:80])


def run_prune(args: argparse.Namespace) -> int:
    pass_start = parse_iso(args.pass_start) if args.pass_start else None
    gh = claims.scoped(claims._run, args.repo)
    here = Path(git(".", "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if not args.dry_run:
        # not a bare prune: an admin dir git is creating right now has no gitdir file yet
        git(here, "worktree", "prune", "--expire", "90.minutes.ago")
    trees = parse_worktrees(git(here, "worktree", "list", "--porcelain").stdout)
    main_root = Path(trees[0]["worktree"]).resolve()
    for wt in trees[1:]:
        try:
            judge(wt, main_root, here, args, pass_start, gh)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            say("KEPT", Path(wt["worktree"]), "error, left alone: " + str(e)[:80])
    if args.issue is None:
        fresh = parse_worktrees(git(here, "worktree", "list", "--porcelain").stdout)
        known = {Path(t["worktree"]).resolve() for t in trees + fresh}
        sweep_leftovers(main_root, known, args.dry_run)
    return 0


def add_commands(groups: Any) -> None:
    wt = groups.add_parser("worktrees", help="worktrees and local branches of finished work")
    cmds = wt.add_subparsers(dest="command", required=True)
    p = cmds.add_parser("prune", help="remove worktrees and branches whose PR is merged or closed")
    p.add_argument("--dry-run", action="store_true", help="print what would happen, change nothing")
    p.add_argument("--issue", type=int, help="only the worktree of f/<n>-..., no leftover sweep")
    p.add_argument("--pass-start", help="ISO 8601 start of this pass (subagent worktrees)")
    p.add_argument("--repo", help="owner/name gh is aimed at")
    p.set_defaults(func=run_prune)
