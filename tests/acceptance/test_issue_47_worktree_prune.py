"""Issue #47: `factory-tools worktrees prune` removes finished work (worktree and local branch).

Product version of the rule Learning Factory built for itself (LF #577, decision D152 with its
two amendments). Observable behaviour only: the command line against real temporary git
repositories (a bare "remote" plus a clone, built under tmp_path) and a fake `gh` process, and
the text of the plugin's manager skill. No network, no real clone is touched.

CLI shape fixed by this exam
    factory-tools worktrees prune [--dry-run] [--issue <n>] [--pass-start <iso8601>]
                                  [--repo <owner/name>]
  (run as `python -m factory_tools worktrees prune ...`; the cwd is inside a clone; exit code 0
  whenever the command could do its job, also when it kept everything.)
  * Without --issue it sweeps every worktree of the clone (the orient call, once per pass). With
    `--issue <n>` it looks only at the worktree whose branch is `f/<n>-...` and does not sweep
    leftover folders (the close-step call).
  * `--pass-start` is the instant the current pass began (ISO 8601, a trailing `Z` or an offset
    or none meaning UTC). `--repo` is the repository `gh` is aimed at: every gh call then ends
    with `-R <owner/name>`; without it gh is called bare.
  * One stdout line per worktree or leftover folder, `<STATUS> <path> <reason>`, where STATUS is
    one of REMOVED, KEPT, SKIPPED (a folder the OS reports busy: one line, never forced). The
    path is the folder, as git prints it. The reason is free text, except that a KEPT line for
    tracked changes contains the word "tracked" and names the changed file, and a KEPT line for
    a locked worktree contains "locked" and not "busy".
  * Under `--dry-run` the same lines are printed with the same STATUS word (REMOVED means "would
    remove") and nothing changes: no folder, no branch, no file, no git admin data.
  * Before a worktree is removed its untracked and ignored top-level names are printed on stdout
    (so `output.json`, `archive`, `.venv` appear in the output). Under --dry-run too.
  * The branch of a removed worktree is deleted too (`git branch -D`).
  * gh is only read (`pr list`, `issue view`), never written, and every call ends with
    `-R <owner/name>` when --repo is given.

Rules, per worktree (a worktree is "judged" in this order)
  * the main worktree, and the worktree the command runs from: never touched (KEPT or no line);
  * a locked worktree (`git worktree lock`): KEPT;
  * branch `f/<n>-slug`: gh is asked `pr list --head <branch> --state all --json ...` (JSON
    objects with number, state OPEN/CLOSED/MERGED, mergedAt, headRefOid) and
    `issue view <n> --json comments` (the claim comment of `factory_tools.claims`);
      - any gh failure, a live claim, no PR, an OPEN PR: KEPT;
      - MERGED: removed only when the local tip is the merged head or an ancestor of it (no work
        after the merge);
      - CLOSED, not merged: removed only when `git ls-remote origin refs/heads/<branch>` (the
        server itself, not a stale tracking ref) has the branch and the local tip is inside it;
        branch only local, deleted on the server, remote unreachable: KEPT;
      - then, whatever the PR: tracked changes (modified or staged) KEPT and named; a `git
        status` that fails KEPT; untracked and ignored files only: removed after listing them;
  * branch `worktree-agent-*` in `.claude/worktrees/agent-*` (a subagent): needs --pass-start;
    KEPT without it. Its last activity is the newest of the folder, its `.git` file, the git dir's
    `index` and `logs/HEAD`, and any modified or untracked file inside it. Activity at or after
    --pass-start, or within the last 90 minutes (the stale-claim window): KEPT. Older: removed
    only when its tip commit is on (or inside) a remote branch as the server says, and it has no
    tracked changes; else KEPT;
  * any other branch: KEPT, never removed.
Leftovers (only in the sweep, not with --issue): a folder directly under `.claude/worktrees/` that
git does not know and that is empty, or holds only a `.git` FILE, is removed; a folder holding
anything else (files, a `.git` directory) is never removed. A folder whose `.git` file points
at a git admin directory that exists (a worktree git is adding right now) is KEPT.
Not tested (not portable): "a folder Windows reports busy is skipped".

Skill (criterion 3): `plugin/skills/factory/SKILL.md` names `factory-tools worktrees prune` in
step "0 - Orient" (with `--pass-start`, no `--issue`) and in step "7 - Close with evidence"
(with `--issue`, after the release), and the close step tells the manager to report tracked
changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from helpers import ROOT, SRC

FAKE = Path(__file__).resolve().parent / "fake_gh_worktrees.py"
SKILL = ROOT / "plugin" / "skills" / "factory" / "SKILL.md"
REPO_NAME = "Shashkist/factory"

SITECUSTOMIZE = """\
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
"""

IDENT = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **IDENT}
    )
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout.strip()


def iso(seconds_ago: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago, UTC).isoformat()


def gitdir(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--absolute-git-dir"))


def set_age(path: Path, seconds_ago: float) -> None:
    """Make the whole worktree look untouched for that long: folder, .git file and git dir."""
    when = time.time() - seconds_ago
    targets = [path, path / ".git", gitdir(path)]
    for root, dirs, files in os.walk(gitdir(path)):
        targets += [Path(root) / n for n in dirs + files]
    for p in targets:
        os.utime(p, (when, when))


def touch_activity(path: Path, seconds_ago: float) -> None:
    """Recent git activity (index, logs/HEAD) while the folder and .git file stay old."""
    when = time.time() - seconds_ago
    for name in ("index", "logs/HEAD"):
        f = gitdir(path) / name
        if f.exists():
            os.utime(f, (when, when))


class World:
    """A bare remote, a clone with `main` pushed, and a fake gh holding PRs and claims."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.remote = tmp / "remote.git"
        self.repo = tmp / "repo"
        self.state_file = tmp / "gh_state.json"
        self.state: dict[str, Any] = {"prs": {}, "claims": {}, "calls": []}
        self.save()
        site = tmp / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(
            SITECUSTOMIZE.format(fake=str(FAKE)), encoding="utf-8"
        )
        self.env = {
            **os.environ,
            **IDENT,
            "PYTHONPATH": os.pathsep.join([str(site), str(SRC)]),
            "PYTHONIOENCODING": "utf-8",
            "FAKE_GH_STATE": str(self.state_file),
        }
        git(tmp, "init", "--bare", "-b", "main", str(self.remote))
        git(tmp, "init", "-b", "main", str(self.repo))
        git(self.repo, "remote", "add", "origin", str(self.remote))
        (self.repo / "README.md").write_text("hello\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "init")
        git(self.repo, "push", "origin", "main")

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")

    def reload(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_file.read_text(encoding="utf-8"))
        return data

    def pr(self, branch: str, state: str, head: str | None = None) -> None:
        """Record a PR for the branch. headRefOid defaults to the branch tip right now."""
        merged = "2026-11-20T10:00:00Z" if state == "MERGED" else None
        if head is None:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", "-q", "refs/heads/" + branch],
                cwd=self.repo, capture_output=True, text=True,
            )
            head = r.stdout.strip()
        self.state["prs"][branch] = [
            {"number": 1, "state": state, "mergedAt": merged, "headRefOid": head}
        ]
        self.save()

    def gh_fails(self, *commands: str) -> None:
        self.state["fail"] = list(commands)
        self.save()

    def claim(self, issue: int, released: bool = False) -> None:
        """A claim comment, in the factory's own format (factory_tools.claims)."""
        sys.path.insert(0, str(SRC))
        try:
            from factory_tools import claims
        finally:
            sys.path.remove(str(SRC))
        if released:
            text = claims.retraction("other-session", "done")
        else:
            stamp = claims.now()
            text = claims.render(
                {"session": "other-session", "branch": f"f/{issue}-x", "worktree": "C:/wt",
                 "claimed": stamp, "heartbeat": stamp, "step": "build"}
            )
        self.state["claims"][str(issue)] = [text]
        self.save()

    def worktree(self, branch: str, folder: str, push: bool = False, inside: bool = False,
                 commit: bool = True) -> Path:
        path = (self.repo / folder) if inside else (self.tmp / folder)
        git(self.repo, "worktree", "add", "-b", branch, str(path), "main")
        if not commit:
            return path
        (path / "work.txt").write_text(branch + "\n")
        git(path, "add", "work.txt")
        git(path, "commit", "-m", "work on " + branch)
        if push:
            git(path, "push", "origin", branch)
        return path

    def run(
        self, *args: str, cwd: Path | None = None, repo: bool = True
    ) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "-m", "factory_tools", "worktrees", "prune", *args]
        if repo:
            cmd += ["--repo", REPO_NAME]
        return subprocess.run(
            cmd, cwd=cwd or self.repo, env=self.env, capture_output=True, text=True, timeout=120
        )

    def branches(self) -> list[str]:
        return git(self.repo, "branch", "--format=%(refname:short)").split()

    @staticmethod
    def line(out: str, folder: str) -> str:
        for ln in out.splitlines():
            if folder in ln.replace("\\", "/"):
                return ln
        return ""

    def snapshot(self) -> dict[str, str]:
        """Every working file of the clone and its worktrees, the branch list, the admin dirs."""
        seen: dict[str, str] = {"branches": git(self.repo, "branch", "-a")}
        for root in (self.repo, *self.tmp.glob("wt-*")):
            for p in sorted(root.rglob("*")):
                rel = p.relative_to(root).parts
                if rel[:1] == (".git",) or p.name == ".git":
                    continue
                seen[str(p)] = p.read_bytes().hex() if p.is_file() else "dir"
        seen["admin"] = ",".join(sorted(os.listdir(self.repo / ".git" / "worktrees")))
        return seen


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


# ---- the command exists ---------------------------------------------------------------------


def test_help_lists_the_flags_and_the_group_is_listed_at_the_top() -> None:
    base = [sys.executable, "-m", "factory_tools"]
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"}
    top = subprocess.run([*base, "--help"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert top.returncode == 0 and "worktrees" in top.stdout, top.stdout + top.stderr
    h = subprocess.run(
        [*base, "worktrees", "prune", "--help"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert h.returncode == 0, h.stderr
    for flag in ("--dry-run", "--issue", "--pass-start", "--repo"):
        assert flag in h.stdout, h.stdout


# ---- criterion 1: each rule ----------------------------------------------------------------


def test_merged_pr_removes_worktree_and_local_branch(w: World) -> None:
    wt = w.worktree("f/11-merged", "wt-11")
    w.pr("f/11-merged", "MERGED")
    out = ok(w.run())
    assert not wt.exists()
    assert "f/11-merged" not in w.branches()
    assert w.line(out, "wt-11").startswith("REMOVED"), out


def test_closed_pr_with_branch_on_remote_is_removed(w: World) -> None:
    wt = w.worktree("f/12-closed", "wt-12", push=True)
    w.pr("f/12-closed", "CLOSED")
    out = ok(w.run())
    assert not wt.exists()
    assert "f/12-closed" not in w.branches()
    assert w.line(out, "wt-12").startswith("REMOVED"), out


def test_closed_pr_with_branch_only_local_is_kept(w: World) -> None:
    wt = w.worktree("f/13-local", "wt-13")
    w.pr("f/13-local", "CLOSED")
    out = ok(w.run())
    assert wt.exists() and "f/13-local" in w.branches()
    assert w.line(out, "wt-13").startswith("KEPT"), out


def test_tracked_change_is_kept_and_reported(w: World) -> None:
    wt = w.worktree("f/14-dirty", "wt-14")
    w.pr("f/14-dirty", "MERGED")
    (wt / "work.txt").write_text("edited\n")
    out = ok(w.run())
    assert wt.exists() and "f/14-dirty" in w.branches()
    assert (wt / "work.txt").read_text() == "edited\n"
    line = w.line(out, "wt-14")
    assert line.startswith("KEPT") and "tracked" in line.lower(), out
    assert "work.txt" in line, "the line names the changed file"


def test_staged_change_is_kept_and_reported(w: World) -> None:
    wt = w.worktree("f/15-staged", "wt-15")
    w.pr("f/15-staged", "MERGED")
    (wt / "new.txt").write_text("staged\n")
    git(wt, "add", "new.txt")
    out = ok(w.run())
    assert wt.exists() and "f/15-staged" in w.branches()
    line = w.line(out, "wt-15")
    assert line.startswith("KEPT") and "tracked" in line.lower(), out


def test_untracked_only_is_listed_then_removed(w: World) -> None:
    wt = w.worktree("f/16-untracked", "wt-16")
    w.pr("f/16-untracked", "MERGED")
    (wt / "output.json").write_text("{}")
    (wt / "archive").mkdir()
    (wt / "archive" / "old-report.txt").write_text("x")
    out = ok(w.run())
    assert not wt.exists() and "f/16-untracked" not in w.branches()
    assert "output.json" in out and "archive" in out
    assert w.line(out, "wt-16").startswith("REMOVED"), out


def test_claimed_issue_is_kept(w: World) -> None:
    wt = w.worktree("f/20-claimed", "wt-20")
    w.pr("f/20-claimed", "MERGED")
    w.claim(20)
    out = ok(w.run())
    assert wt.exists() and "f/20-claimed" in w.branches()
    assert w.line(out, "wt-20").startswith("KEPT"), out


def test_released_claim_does_not_keep_the_worktree(w: World) -> None:
    wt = w.worktree("f/23-released", "wt-23")
    w.pr("f/23-released", "MERGED")
    w.claim(23, released=True)
    out = ok(w.run())
    assert not wt.exists() and "f/23-released" not in w.branches()
    assert w.line(out, "wt-23").startswith("REMOVED"), out


def test_subagent_worktree_newer_than_pass_start_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-new", ".claude/worktrees/agent-new", push=True, inside=True)
    set_age(wt, 0)
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and "worktree-agent-new" in w.branches()
    assert w.line(out, "agent-new").startswith("KEPT"), out


# ---- the rest of the rules (issue text and the lessons of LF D152) ---------------------------


def test_open_pr_is_kept(w: World) -> None:
    wt = w.worktree("f/21-open", "wt-21", push=True)
    w.pr("f/21-open", "OPEN")
    out = ok(w.run())
    assert wt.exists() and "f/21-open" in w.branches()
    assert w.line(out, "wt-21").startswith("KEPT"), out


def test_branch_without_pr_is_kept(w: World) -> None:
    wt = w.worktree("f/22-nopr", "wt-22", push=True)
    out = ok(w.run())
    assert wt.exists() and "f/22-nopr" in w.branches()
    assert w.line(out, "wt-22").startswith("KEPT"), out


def test_worktree_on_a_non_factory_branch_is_never_removed(w: World) -> None:
    wt = w.worktree("feature/mine", "wt-90")
    w.pr("feature/mine", "MERGED")
    out = ok(w.run())
    assert wt.exists() and "feature/mine" in w.branches()
    assert not w.line(out, "wt-90").startswith("REMOVED"), out


def test_main_worktree_is_never_touched(w: World) -> None:
    # The main worktree sits on a merged, pushed feature branch and the sweep runs from another
    # worktree, so only a rule "never the main worktree" keeps it.
    git(w.repo, "checkout", "-b", "f/60-main")
    (w.repo / "main-work.txt").write_text("x\n")
    git(w.repo, "add", "main-work.txt")
    git(w.repo, "commit", "-m", "work in the main worktree")
    git(w.repo, "push", "origin", "f/60-main")
    w.pr("f/60-main", "MERGED")
    (w.repo / "scratch.txt").write_text("untracked in main\n")
    elsewhere = w.worktree("f/61-elsewhere", "wt-61")
    out = ok(w.run(cwd=elsewhere))
    assert (w.repo / "README.md").exists() and (w.repo / "scratch.txt").exists()
    assert git(w.repo, "branch", "--show-current") == "f/60-main"
    main_lines = [
        ln for ln in out.replace("\\", "/").splitlines()
        if str(w.repo).replace("\\", "/") + " " in ln + " "
    ]
    assert not any(ln.startswith("REMOVED") for ln in main_lines), out
    assert "f/60-main" in w.branches()


def test_the_worktree_the_command_runs_from_is_never_removed(w: World) -> None:
    here = w.worktree("f/81-here", "wt-81")
    other = w.worktree("f/82-other", "wt-82")
    w.pr("f/81-here", "MERGED")
    w.pr("f/82-other", "MERGED")
    out = ok(w.run(cwd=here))
    assert here.exists() and "f/81-here" in w.branches()
    assert not w.line(out, "wt-81").startswith("REMOVED"), out
    assert not other.exists()


def test_issue_flag_limits_to_that_issues_branch(w: World) -> None:
    a = w.worktree("f/31-a", "wt-31")
    b = w.worktree("f/32-b", "wt-32")
    w.pr("f/31-a", "MERGED")
    w.pr("f/32-b", "MERGED")
    ok(w.run("--issue", "31"))
    assert not a.exists() and "f/31-a" not in w.branches()
    assert b.exists() and "f/32-b" in w.branches()


def test_issue_flag_does_not_sweep_leftover_folders(w: World) -> None:
    w.worktree("f/33-c", "wt-33")
    w.pr("f/33-c", "MERGED")
    empty = w.repo / ".claude" / "worktrees" / "agent-empty-keep"
    empty.mkdir(parents=True)
    ok(w.run("--issue", "33", "--pass-start", iso(3600)))
    assert empty.exists()


def test_a_merged_pr_with_a_local_commit_after_the_merge_is_kept(w: World) -> None:
    wt = w.worktree("f/70-after", "wt-70")
    w.pr("f/70-after", "MERGED")  # headRefOid is the tip at merge time
    (wt / "late.txt").write_text("made after the merge\n")
    git(wt, "add", "late.txt")
    git(wt, "commit", "-m", "late work")
    out = ok(w.run())
    assert wt.exists() and "f/70-after" in w.branches()
    assert w.line(out, "wt-70").startswith("KEPT"), out


def test_a_merged_pr_with_the_local_tip_behind_the_merged_head_is_removed(w: World) -> None:
    wt = w.worktree("f/71-behind", "wt-71")
    w.pr("f/71-behind", "MERGED")
    git(wt, "reset", "--hard", "HEAD~1")  # tip is an ancestor of the merged head
    out = ok(w.run())
    assert not wt.exists() and "f/71-behind" not in w.branches()
    assert w.line(out, "wt-71").startswith("REMOVED"), out


def test_a_closed_pr_with_unpushed_commits_beyond_the_remote_branch_is_kept(w: World) -> None:
    wt = w.worktree("f/72-unpushed", "wt-72", push=True)
    w.pr("f/72-unpushed", "CLOSED")
    (wt / "more.txt").write_text("never pushed\n")
    git(wt, "add", "more.txt")
    git(wt, "commit", "-m", "unpushed work")
    out = ok(w.run())
    assert wt.exists() and "f/72-unpushed" in w.branches()
    assert w.line(out, "wt-72").startswith("KEPT"), out


def test_a_closed_pr_whose_branch_was_deleted_on_the_server_is_kept_despite_a_tracking_ref(
    w: World,
) -> None:
    wt = w.worktree("f/73-stale", "wt-73", push=True)
    w.pr("f/73-stale", "CLOSED")
    git(w.remote, "update-ref", "-d", "refs/heads/f/73-stale")  # behind the clone's back
    assert git(w.repo, "rev-parse", "--verify", "refs/remotes/origin/f/73-stale")
    out = ok(w.run())
    assert wt.exists() and "f/73-stale" in w.branches()
    assert w.line(out, "wt-73").startswith("KEPT"), out


def test_a_closed_pr_with_the_remote_ahead_of_the_local_tip_is_removed(w: World) -> None:
    wt = w.worktree("f/74-ahead", "wt-74", push=True)
    (wt / "more.txt").write_text("pushed later\n")
    git(wt, "add", "more.txt")
    git(wt, "commit", "-m", "more")
    git(wt, "push", "origin", "f/74-ahead")
    git(wt, "reset", "--hard", "HEAD~1")  # local tip is contained in the remote branch
    w.pr("f/74-ahead", "CLOSED")
    out = ok(w.run())
    assert not wt.exists() and "f/74-ahead" not in w.branches()
    assert w.line(out, "wt-74").startswith("REMOVED"), out


def test_a_closed_pr_with_an_unreachable_remote_is_kept(w: World) -> None:
    wt = w.worktree("f/75-offline", "wt-75", push=True)
    w.pr("f/75-offline", "CLOSED")
    git(w.repo, "remote", "set-url", "origin", str(w.tmp / "no-such-remote.git"))
    out = ok(w.run())
    assert wt.exists() and "f/75-offline" in w.branches()
    assert w.line(out, "wt-75").startswith("KEPT"), out


def test_unreadable_git_status_is_kept_and_the_sweep_goes_on(w: World) -> None:
    broken = w.worktree("f/76-broken", "wt-76")
    other = w.worktree("f/77-fine", "wt-77")
    w.pr("f/76-broken", "MERGED")
    w.pr("f/77-fine", "MERGED")
    (broken / "work.txt").write_text("precious edit\n")
    (gitdir(broken) / "index").write_bytes(b"this is not an index file")
    r = subprocess.run(["git", "status", "--porcelain"], cwd=broken, capture_output=True, text=True)
    assert r.returncode != 0, "setup: git status must fail in the broken worktree"
    out = ok(w.run())
    assert broken.exists() and "f/76-broken" in w.branches()
    assert (broken / "work.txt").read_text() == "precious edit\n"
    assert w.line(out, "wt-76").startswith("KEPT"), out
    assert not other.exists() and "f/77-fine" not in w.branches(), "one failure stopped the sweep"


@pytest.mark.parametrize("failing", [["all"], ["pr"], ["issue"]])
def test_a_gh_failure_keeps_the_worktree(w: World, failing: list[str]) -> None:
    wt = w.worktree("f/80-gh", "wt-80")
    w.pr("f/80-gh", "MERGED")
    w.gh_fails(*failing)
    out = ok(w.run())
    assert wt.exists() and "f/80-gh" in w.branches()
    assert w.line(out, "wt-80").startswith("KEPT"), out


def test_a_locked_worktree_is_kept_and_reported_as_locked(w: World) -> None:
    wt = w.worktree("f/91-locked", "wt-91")
    w.pr("f/91-locked", "MERGED")
    git(w.repo, "worktree", "lock", "--reason", "on a usb stick", str(wt))
    out = ok(w.run())
    line = w.line(out, "wt-91")
    assert wt.exists() and "f/91-locked" in w.branches()
    assert line.startswith("KEPT") and "locked" in line.lower(), out
    assert "busy" not in line.lower(), out


def test_ignored_files_are_listed_before_a_removable_worktree_is_removed(w: World) -> None:
    wt = w.worktree("f/92-ignored", "wt-92")
    (wt / ".gitignore").write_text(".venv/\nnode_modules/\n.env\n")
    git(wt, "add", ".gitignore")
    git(wt, "commit", "-m", "ignore things")
    w.pr("f/92-ignored", "MERGED")
    (wt / ".venv").mkdir()
    (wt / ".venv" / "pyvenv.cfg").write_text("home = x\n")
    (wt / "node_modules" / "pkg").mkdir(parents=True)
    (wt / "node_modules" / "pkg" / "index.js").write_text("1\n")
    (wt / ".env").write_text("A=1\n")
    out = ok(w.run())
    assert not wt.exists() and "f/92-ignored" not in w.branches()
    assert ".venv" in out and "node_modules" in out and ".env" in out, out


def test_gh_is_only_read_and_aimed_at_the_named_repository(w: World) -> None:
    w.worktree("f/95-calls", "wt-95")
    w.pr("f/95-calls", "MERGED")
    ok(w.run())
    calls = w.reload()["calls"]
    assert calls, "gh was never asked"
    for c in calls:
        assert c[:2] in (["pr", "list"], ["issue", "view"]), c
        assert c[-2:] == ["-R", REPO_NAME], c
    assert any(c[:2] == ["pr", "list"] for c in calls)
    assert any(c[:2] == ["issue", "view"] and c[2] == "95" for c in calls)


def test_without_repo_gh_is_called_bare(w: World) -> None:
    wt = w.worktree("f/96-bare", "wt-96")
    w.pr("f/96-bare", "MERGED")
    ok(w.run(repo=False))
    assert not wt.exists()
    assert all("-R" not in c for c in w.reload()["calls"])


# ---- subagent worktrees ----------------------------------------------------------------------


def test_subagent_worktree_older_with_tip_on_remote_is_removed(w: World) -> None:
    wt = w.worktree("worktree-agent-old", ".claude/worktrees/agent-old", inside=True)
    git(wt, "push", "origin", "worktree-agent-old:refs/heads/f/40-saved")
    set_age(wt, 7200)
    out = ok(w.run("--pass-start", iso(3600)))
    assert not wt.exists() and "worktree-agent-old" not in w.branches()
    assert w.line(out, "agent-old").startswith("REMOVED"), out


def test_subagent_worktree_older_with_tip_not_on_remote_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-lost", ".claude/worktrees/agent-lost", inside=True)
    set_age(wt, 7200)
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and "worktree-agent-lost" in w.branches()
    assert w.line(out, "agent-lost").startswith("KEPT"), out


def test_subagent_worktree_is_kept_when_there_is_no_pass_start(w: World) -> None:
    wt = w.worktree("worktree-agent-nostart", ".claude/worktrees/agent-nostart", push=True,
                    inside=True)
    set_age(wt, 8 * 3600)
    out = ok(w.run())
    assert wt.exists() and "worktree-agent-nostart" in w.branches()
    assert w.line(out, "agent-nostart").startswith("KEPT"), out


def test_subagent_worktree_with_recent_git_activity_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-live", ".claude/worktrees/agent-live", push=True, inside=True)
    set_age(wt, 7200)  # folder and .git file look old ...
    touch_activity(wt, 300)  # ... but the index and logs/HEAD were written 5 minutes ago
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and "worktree-agent-live" in w.branches()
    assert w.line(out, "agent-live").startswith("KEPT"), out


def test_commitless_subagent_worktree_with_recent_git_activity_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-fresh", ".claude/worktrees/agent-fresh", inside=True,
                    commit=False)  # tip is main, which is on origin
    set_age(wt, 7200)
    touch_activity(wt, 300)
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and "worktree-agent-fresh" in w.branches()
    assert w.line(out, "agent-fresh").startswith("KEPT"), out


def test_subagent_worktree_with_a_freshly_written_untracked_file_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-writing", ".claude/worktrees/agent-writing", push=True,
                    inside=True)
    set_age(wt, 8 * 3600)
    (wt / "notes.txt").write_text("being written right now\n")  # mtime is now
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and (wt / "notes.txt").exists()
    assert w.line(out, "agent-writing").startswith("KEPT"), out


def test_subagent_worktree_idle_longer_than_the_window_is_removed(w: World) -> None:
    wt = w.worktree("worktree-agent-idle", ".claude/worktrees/agent-idle", push=True, inside=True)
    set_age(wt, 8 * 3600)
    out = ok(w.run("--pass-start", iso(3600)))
    assert not wt.exists() and "worktree-agent-idle" not in w.branches()
    assert w.line(out, "agent-idle").startswith("REMOVED"), out


def test_subagent_worktree_with_tracked_changes_is_kept_even_when_old_and_pushed(
    w: World,
) -> None:
    wt = w.worktree("worktree-agent-dirty", ".claude/worktrees/agent-dirty", push=True,
                    inside=True)
    (wt / "work.txt").write_text("edited\n")
    set_age(wt, 8 * 3600)
    os.utime(wt / "work.txt", (time.time() - 8 * 3600,) * 2)
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and (wt / "work.txt").read_text() == "edited\n"
    line = w.line(out, "agent-dirty")
    assert line.startswith("KEPT") and "tracked" in line.lower(), out


# ---- leftover folders ------------------------------------------------------------------------


def test_leftover_folder_with_only_a_git_file_is_removed(w: World) -> None:
    leftover = w.repo / ".claude" / "worktrees" / "agent-gone"
    leftover.mkdir(parents=True)
    (leftover / ".git").write_text(f"gitdir: {w.repo / '.git' / 'worktrees' / 'agent-gone'}\n")
    out = ok(w.run("--pass-start", iso(3600)))
    assert not leftover.exists()
    assert w.line(out, "agent-gone").startswith("REMOVED"), out


def test_empty_leftover_folder_is_removed(w: World) -> None:
    empty = w.repo / ".claude" / "worktrees" / "agent-empty-dir"
    empty.mkdir(parents=True)
    out = ok(w.run("--pass-start", iso(3600)))
    line = w.line(out, "agent-empty-dir")
    assert not empty.exists(), out
    assert line.startswith("REMOVED") and "busy" not in line.lower(), out
    assert "holds files" not in line


def test_leftover_folder_holding_a_git_directory_is_kept(w: World) -> None:
    inside = w.repo / ".claude" / "worktrees" / "agent-fullrepo"
    inside.mkdir(parents=True)
    git(inside, "init", "-b", "main")
    out = ok(w.run("--pass-start", iso(3600)))
    assert (inside / ".git" / "HEAD").exists()
    assert not w.line(out, "agent-fullrepo").startswith("REMOVED"), out


def test_leftover_folder_git_is_still_adding_is_kept(w: World) -> None:
    # `git worktree add` makes the folder and the admin dir first, the folder's .git file last;
    # a .git file that points at an admin dir that exists is a worktree being added right now.
    admin = w.repo / ".git" / "worktrees" / "agent-adding"
    admin.mkdir(parents=True)
    adding = w.repo / ".claude" / "worktrees" / "agent-adding"
    adding.mkdir(parents=True)
    (adding / ".git").write_text(f"gitdir: {admin.as_posix()}\n")
    out = ok(w.run("--pass-start", iso(3600)))
    assert (adding / ".git").exists() and admin.exists()
    assert not w.line(out, "agent-adding").startswith("REMOVED"), out


def test_unknown_folders_are_never_removed(w: World) -> None:
    notes = w.repo / ".claude" / "worktrees" / "notes"
    notes.mkdir(parents=True)
    (notes / "todo.md").write_text("mine\n")
    copy = w.repo / ".claude" / "worktrees" / "agent-copy"
    (copy / "src").mkdir(parents=True)
    (copy / "src" / "a.py").write_text("x = 1\n")
    (copy / ".git").write_text("gitdir: /nonexistent\n")  # a .git file, but also files
    elsewhere = w.repo / "scratch-dir"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("keep\n")
    out = ok(w.run("--pass-start", iso(3600)))
    assert (notes / "todo.md").exists()
    assert (copy / "src" / "a.py").exists()
    assert (elsewhere / "keep.txt").exists()
    assert not w.line(out, "/notes").startswith("REMOVED")
    assert not w.line(out, "agent-copy").startswith("REMOVED")


# ---- criterion 2: --dry-run changes nothing --------------------------------------------------


def test_dry_run_changes_nothing_but_says_what_it_would_do(w: World) -> None:
    merged = w.worktree("f/51-merged", "wt-51")
    (merged / "scratch.txt").write_text("x")
    w.pr("f/51-merged", "MERGED")
    sub = w.worktree("worktree-agent-dry", ".claude/worktrees/agent-dry", inside=True)
    git(sub, "push", "origin", "worktree-agent-dry:refs/heads/f/52-saved")
    set_age(sub, 7200)
    leftover = w.repo / ".claude" / "worktrees" / "agent-empty"
    leftover.mkdir(parents=True)
    (leftover / ".git").write_text("gitdir: /nonexistent\n")
    before = w.snapshot()
    out = ok(w.run("--dry-run", "--pass-start", iso(3600)))
    assert merged.exists() and sub.exists() and leftover.exists()
    assert {"f/51-merged", "worktree-agent-dry"} <= set(w.branches())
    assert (merged / "scratch.txt").read_text() == "x"
    assert w.snapshot() == before
    for folder in ("wt-51", "agent-dry", "agent-empty"):
        assert w.line(out, folder).startswith("REMOVED"), out


def test_dry_run_changes_nothing_for_ignored_files_and_empty_leftovers(w: World) -> None:
    wt = w.worktree("f/93-dry", "wt-93")
    (wt / ".gitignore").write_text(".env\n")
    git(wt, "add", ".gitignore")
    git(wt, "commit", "-m", "ignore")
    w.pr("f/93-dry", "MERGED")
    (wt / ".env").write_text("A=1\n")
    empty = w.repo / ".claude" / "worktrees" / "agent-empty-dry"
    empty.mkdir(parents=True)
    idle = w.worktree("worktree-agent-idle2", ".claude/worktrees/agent-idle2", push=True,
                      inside=True)
    set_age(idle, 8 * 3600)
    out = ok(w.run("--dry-run", "--pass-start", iso(3600)))
    assert (wt / ".env").read_text() == "A=1\n" and empty.exists() and idle.exists()
    assert {"f/93-dry", "worktree-agent-idle2"} <= set(w.branches())
    assert ".env" in out
    for folder in ("wt-93", "agent-empty-dry", "agent-idle2"):
        assert w.line(out, folder).startswith("REMOVED"), out


def test_dry_run_prints_the_same_kept_lines_as_a_real_run(w: World) -> None:
    dirty = w.worktree("f/97-dirty", "wt-97")
    w.pr("f/97-dirty", "MERGED")
    (dirty / "work.txt").write_text("edited\n")
    w.worktree("f/98-open", "wt-98", push=True)
    w.pr("f/98-open", "OPEN")
    out = ok(w.run("--dry-run"))
    assert w.line(out, "wt-97").startswith("KEPT") and "tracked" in w.line(out, "wt-97").lower()
    assert w.line(out, "wt-98").startswith("KEPT")


# ---- criterion 3: the skill names both call sites -------------------------------------------


def _step(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_skill_names_the_command_in_orient_once_per_pass_and_in_close_for_the_issue() -> None:
    text = SKILL.read_text(encoding="utf-8")
    orient = _step(text, "## 0 - Orient", "\n## 1 ")
    close = _step(text, "## 7 - Close with evidence", "\n## 8 ")
    assert "factory-tools worktrees prune" in orient, "orient must run the prune"
    assert "--pass-start" in orient, "orient hands over the start of the pass"
    assert "--issue" not in orient.split("worktrees prune", 1)[1].splitlines()[0]
    assert "factory-tools worktrees prune" in close, "close must run the prune"
    assert "--issue" in close.split("worktrees prune", 1)[1].splitlines()[0]


def test_skill_close_step_reports_tracked_changes_and_prunes_after_the_release() -> None:
    text = SKILL.read_text(encoding="utf-8")
    close = _step(text, "## 7 - Close with evidence", "\n## 8 ")
    assert "tracked" in close.lower(), "tracked changes are reported on the issue"
    assert close.index("factory-tools release") < close.index("factory-tools worktrees prune"), (
        "the claim is released first, or the prune would keep the worktree it was asked about"
    )
