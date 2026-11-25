"""Issue #47, review round 1: the gaps the first exam left open.

Same world as `test_issue_47_worktree_prune.py` (real temporary git repositories, a fake gh,
the command line), plus:

  * `--dry-run` with a prunable worktree, when judging would need a fetch, and for the index
    (a dry run must not rewrite any index: the clone is shared with other sessions);
  * a finished worktree that holds another worktree or a nested repository is KEPT, with a
    reason that names the nested path, and nothing under it is touched;
  * `--repo` must name the clone the command runs in (origin), else it refuses and removes
    nothing; the skill says to run the prune from each repository's own clone;
  * Windows consoles: a non-ASCII path does not crash the output, non-ASCII file names count
    as activity;
  * a `worktree-agent-*` branch outside `.claude/worktrees` is not a subagent worktree.

Nothing here is for a particular implementation: every case is stated by the issue's rules
(never lose work, `--dry-run` changes nothing) and the review of PR 55.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import ROOT
from test_issue_47_worktree_prune import World, git, gitdir, iso, ok, set_age

SKILL = ROOT / "plugin" / "skills" / "factory" / "SKILL.md"


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def norm(text: str) -> str:
    return text.replace("\\", "/")


def refs(repo: Path) -> str:
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def set_origin_url(w: World, url: str) -> None:
    """Make origin look like a GitHub URL, while git still reaches the local bare remote."""
    git(w.repo, "remote", "set-url", "origin", url)
    git(w.repo, "config", f"url.{w.remote.as_posix()}.insteadOf", url)


# ---- criterion 2, more: --dry-run changes nothing -------------------------------------------


def test_dry_run_with_a_prunable_worktree_reports_it_and_prunes_nothing(w: World) -> None:
    gone = w.worktree("f/101-gone", "wt-101")
    w.pr("f/101-gone", "MERGED")
    other = w.worktree("f/102-here", "wt-102")
    w.pr("f/102-here", "MERGED")
    # The folder disappears behind git's back: git lists the worktree as prunable.
    shutil.rmtree(gone)
    admin = w.repo / ".git" / "worktrees"
    before_admin = sorted(os.listdir(admin))
    assert "wt-101" in before_admin
    out = ok(w.run("--dry-run"))
    assert sorted(os.listdir(admin)) == before_admin, "a dry run pruned git's admin data"
    assert "f/101-gone" in w.branches() and "f/102-here" in w.branches()
    assert other.exists()
    assert "wt-101" in norm(out), "the prunable worktree is not mentioned: " + out
    assert w.line(out, "wt-102").startswith("REMOVED"), out


def test_a_real_run_prunes_the_worktree_whose_folder_is_gone(w: World) -> None:
    gone = w.worktree("f/103-gone", "wt-103")
    w.pr("f/103-gone", "MERGED")
    shutil.rmtree(gone)
    ok(w.run())
    assert not (w.repo / ".git" / "worktrees" / "wt-103").exists()  # git may drop the empty parent
    assert "f/103-gone" not in w.branches()


def test_dry_run_does_not_fetch_when_the_remote_has_news(w: World) -> None:
    # The tip of the subagent worktree is on the server, but the clone's tracking refs do not
    # know it (pushed by URL), so judging "is the tip on a remote branch" could tempt a fetch.
    wt = w.worktree("worktree-agent-news", ".claude/worktrees/agent-news", inside=True)
    git(wt, "push", str(w.remote), "worktree-agent-news:refs/heads/f/110-saved")
    # And a closed PR whose branch exists on the server only.
    other = w.worktree("f/111-closed", "wt-111", push=True)
    w.pr("f/111-closed", "CLOSED")
    git(other, "update-ref", "-d", "refs/remotes/origin/f/111-closed")
    set_age(wt, 8 * 3600)
    before = refs(w.repo)
    out = ok(w.run("--dry-run", "--pass-start", iso(3600)))
    assert refs(w.repo) == before, "a dry run changed refs (a fetch ran)"
    assert not (w.repo / ".git" / "FETCH_HEAD").exists(), "a dry run fetched"
    assert w.line(out, "agent-news").startswith("REMOVED"), out
    assert w.line(out, "wt-111").startswith("REMOVED"), out


def test_dry_run_leaves_every_index_untouched(w: World) -> None:
    merged = w.worktree("f/120-idx", "wt-120")
    w.pr("f/120-idx", "MERGED")
    sub = w.worktree("worktree-agent-idx", ".claude/worktrees/agent-idx", push=True, inside=True)
    set_age(sub, 8 * 3600)
    indexes = []
    for wt in (merged, sub):
        # Same content, newer file time: a plain `git status` refreshes and rewrites the index.
        f = wt / "work.txt"
        os.utime(f, (time.time() - 100, time.time() - 100))
        idx = gitdir(wt) / "index"
        old = time.time() - 7200
        os.utime(idx, (old, old))
        indexes.append((idx, idx.stat().st_mtime_ns))
    out = ok(w.run("--dry-run", "--pass-start", iso(3600)))
    for idx, mtime in indexes:
        assert idx.stat().st_mtime_ns == mtime, f"a dry run rewrote {idx}"
    assert w.line(out, "wt-120").startswith("REMOVED"), out


# ---- review finding 1: a finished worktree that holds other work ----------------------------


def _nest_worktree(w: World, parent: Path) -> tuple[Path, str]:
    nested = parent / ".claude" / "worktrees" / "agent-b"
    git(w.repo, "worktree", "add", "-b", "worktree-agent-b", str(nested), "main")
    (nested / "README.md").write_text("precious edit of the nested worktree\n")
    return nested, ".claude/worktrees/agent-b"


def _nest_repo(w: World, parent: Path) -> tuple[Path, str]:
    nested = parent / "vendor" / "lib"
    nested.mkdir(parents=True)
    git(nested, "init", "-b", "main")
    (nested / "lib.py").write_text("unpushed = True\n")
    git(nested, "add", "lib.py")
    git(nested, "commit", "-m", "unpushed work of a nested repository")
    return nested, "vendor/lib"


def _nest_git_file(w: World, parent: Path) -> tuple[Path, str]:
    nested = parent / "docs" / "sub"
    nested.mkdir(parents=True)
    (nested / ".git").write_text("gitdir: " + (w.tmp / "elsewhere.git").as_posix() + "\n")
    (nested / "notes.txt").write_text("belongs to somebody\n")
    return nested, "docs/sub"


@pytest.mark.parametrize("flags", [[], ["--dry-run"], ["--issue", "11"]])
@pytest.mark.parametrize("nest", [_nest_worktree, _nest_repo, _nest_git_file])
def test_a_finished_worktree_holding_nested_work_is_kept_and_names_the_path(
    w: World, nest, flags: list[str]
) -> None:
    wt = w.worktree("f/11-merged", "wt-11")
    w.pr("f/11-merged", "MERGED")
    nested, rel = nest(w, wt)
    before = {p: p.read_bytes() for p in nested.rglob("*") if p.is_file() and ".git" not in p.parts}
    out = ok(w.run(*flags))
    line = w.line(out, "wt-11")
    assert line.startswith("KEPT"), out
    assert rel in norm(line), f"the reason must name the nested path {rel}: {line}"
    assert wt.exists() and nested.exists()
    assert "f/11-merged" in w.branches()
    after = {p: p.read_bytes() for p in nested.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before, "the nested work was touched"
    assert (nested / ".git").exists()


def test_nested_work_does_not_keep_its_siblings_from_being_removed(w: World) -> None:
    wt = w.worktree("f/12-merged", "wt-12")
    w.pr("f/12-merged", "MERGED")
    _nest_repo(w, wt)
    other = w.worktree("f/13-merged", "wt-13")
    w.pr("f/13-merged", "MERGED")
    out = ok(w.run())
    assert wt.exists() and not other.exists(), out
    assert w.line(out, "wt-13").startswith("REMOVED"), out


def test_a_subagent_worktree_holding_a_nested_repository_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-host", ".claude/worktrees/agent-host", push=True, inside=True)
    nested, rel = _nest_repo(w, wt)
    set_age(wt, 8 * 3600)
    for p in [nested, *nested.rglob("*")]:
        os.utime(p, (time.time() - 8 * 3600,) * 2)
    out = ok(w.run("--pass-start", iso(3600)))
    line = w.line(out, "agent-host")
    assert wt.exists() and nested.exists(), out
    assert line.startswith("KEPT") and rel in norm(line), out


# ---- review finding 2: --repo must be the clone's own repository ----------------------------


@pytest.mark.parametrize("flags", [[], ["--issue", "30"], ["--dry-run"]])
def test_repo_that_does_not_match_origin_is_refused_and_removes_nothing(
    w: World, flags: list[str]
) -> None:
    wt = w.worktree("f/30-live", "wt-30")
    w.pr("f/30-live", "MERGED")
    sub = w.worktree("worktree-agent-x", ".claude/worktrees/agent-x", push=True, inside=True)
    set_age(sub, 8 * 3600)
    empty = w.repo / ".claude" / "worktrees" / "agent-empty-refused"
    empty.mkdir(parents=True)
    set_origin_url(w, "https://github.com/Somebody/else.git")
    before = w.snapshot()
    r = w.run(*flags, "--pass-start", iso(3600))  # --repo Shashkist/factory is added by run()
    assert r.returncode != 0, "a mismatching --repo must be an error:\n" + r.stdout + r.stderr
    assert wt.exists() and sub.exists() and empty.exists()
    assert {"f/30-live", "worktree-agent-x"} <= set(w.branches())
    assert w.snapshot() == before
    assert not any(ln.startswith("REMOVED") for ln in r.stdout.splitlines()), r.stdout
    assert "Somebody/else" in r.stdout + r.stderr or "Shashkist/factory" in r.stdout + r.stderr, (
        "the error says which repositories disagree"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Shashkist/factory.git",
        "https://github.com/Shashkist/factory",
        "git@github.com:Shashkist/factory.git",
        "https://github.com/shashkist/Factory.git",
    ],
)
def test_repo_that_matches_origin_is_accepted(w: World, url: str) -> None:
    wt = w.worktree("f/31-ok", "wt-31")
    w.pr("f/31-ok", "MERGED")
    set_origin_url(w, url)
    out = ok(w.run())
    assert not wt.exists(), out
    assert w.line(out, "wt-31").startswith("REMOVED"), out


def test_skill_says_to_run_the_prune_from_each_repositorys_own_clone() -> None:
    text = SKILL.read_text(encoding="utf-8")
    for start, end in (("## 0 - Orient", "\n## 1 "), ("## 7 - Close with evidence", "\n## 8 ")):
        section = text.split(start, 1)[1].split(end, 1)[0]
        at = section.index("worktrees prune")
        window = section[max(0, at - 400) : at + 600].lower()
        assert "clone" in window, f"{start}: the prune must be run from the repository's own clone"
        assert "own" in window or "that repository" in window or "each repository" in window, (
            f"{start}: say that it is the clone of the repository the issue belongs to"
        )


# ---- Windows consoles ----------------------------------------------------------------------


def test_a_non_ascii_path_does_not_crash_the_output_or_stop_the_sweep(w: World) -> None:
    first = w.worktree("f/40-first", "wt-39-first")
    odd = w.worktree("f/41-odd", "wt-40-שלום")
    last = w.worktree("f/42-last", "wt-41-last")
    for b in ("f/40-first", "f/41-odd", "f/42-last"):
        w.pr(b, "MERGED")
    w.env["PYTHONIOENCODING"] = "cp1252"  # a Windows console: Hebrew cannot be printed as is
    r = w.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert not first.exists() and not odd.exists() and not last.exists(), r.stdout
    assert "f/41-odd" not in w.branches()
    removed = [ln for ln in r.stdout.splitlines() if ln.startswith("REMOVED") and "wt-40-" in ln]
    assert removed, "the REMOVED line of the non-ASCII worktree is missing:\n" + r.stdout
    assert w.line(r.stdout, "wt-41-last").startswith("REMOVED"), r.stdout


def test_non_ascii_untracked_file_names_count_as_recent_activity(w: World) -> None:
    wt = w.worktree("worktree-agent-heb", ".claude/worktrees/agent-heb", push=True, inside=True)
    set_age(wt, 8 * 3600)
    name = "הערות-café.txt"
    (wt / name).write_text("being written right now\n", encoding="utf-8")  # mtime is now
    old = time.time() - 8 * 3600
    os.utime(wt, (old, old))  # creating the file touched the folder: only the file is recent
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and (wt / name).exists(), out
    assert w.line(out, "agent-heb").startswith("KEPT"), out
    assert "worktree-agent-heb" in w.branches()


def test_a_non_ascii_tracked_file_name_is_reported_as_tracked_change(w: World) -> None:
    wt = w.worktree("f/43-heb", "wt-43")
    name = "עברית.txt"
    (wt / name).write_text("v1\n", encoding="utf-8")
    git(wt, "add", name)
    git(wt, "commit", "-m", "hebrew name")
    w.pr("f/43-heb", "MERGED")
    (wt / name).write_text("v2\n", encoding="utf-8")
    out = ok(w.run())
    line = w.line(out, "wt-43")
    assert wt.exists() and (wt / name).read_text(encoding="utf-8") == "v2\n"
    assert line.startswith("KEPT") and "tracked" in line.lower(), out


# ---- optional: a worktree-agent-* branch that is not in .claude/worktrees --------------------


def test_a_worktree_agent_branch_outside_the_subagent_folder_is_kept(w: World) -> None:
    wt = w.worktree("worktree-agent-elsewhere", "wt-agent-elsewhere", push=True)
    set_age(wt, 8 * 3600)
    out = ok(w.run("--pass-start", iso(3600)))
    assert wt.exists() and "worktree-agent-elsewhere" in w.branches()
    assert not w.line(out, "wt-agent-elsewhere").startswith("REMOVED"), out

# ---- links and bare repositories inside a finished worktree ----------------------------------


def make_dir_link(link: Path, target: Path) -> None:
    """A directory junction on Windows, a directory symlink elsewhere; skip if neither works."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                pytest.skip("cannot create a junction: " + r.stderr + r.stdout)
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"cannot create a directory link: {e}")


def drop_link(link: Path) -> None:
    """Remove a link without touching its target (test cleanup)."""
    try:
        os.rmdir(link) if sys.platform == "win32" else os.unlink(link)
    except OSError:
        pass


def outside_folder(w: World) -> Path:
    outside = w.tmp / "outside-data"
    outside.mkdir()
    (outside / "precious.txt").write_text("not part of any worktree\n")
    (outside / "deep").mkdir()
    (outside / "deep" / "more.txt").write_text("also precious\n")
    return outside


@pytest.mark.parametrize("flags", [[], ["--dry-run"], ["--issue", "150"]])
def test_a_finished_worktree_with_a_link_to_an_outside_folder_is_kept(
    w: World, flags: list[str]
) -> None:
    wt = w.worktree("f/150-link", "wt-150")
    w.pr("f/150-link", "MERGED")
    outside = outside_folder(w)
    link = wt / "node_modules" / "pkg"
    make_dir_link(link, outside)
    try:
        out = ok(w.run(*flags))
        line = w.line(out, "wt-150")
        assert line.startswith("KEPT"), out
        assert "node_modules/pkg" in norm(line), f"the reason must name the link path: {line}"
        assert wt.exists() and "f/150-link" in w.branches()
        assert (outside / "precious.txt").read_text() == "not part of any worktree\n"
        assert (outside / "deep" / "more.txt").read_text() == "also precious\n"
    finally:
        drop_link(link)


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_a_link_pointing_back_into_its_own_worktree_is_kept_without_looping(
    w: World, flags: list[str]
) -> None:
    wt = w.worktree("f/151-loop", "wt-151")
    w.pr("f/151-loop", "MERGED")
    other = w.worktree("f/152-fine", "wt-152")
    w.pr("f/152-fine", "MERGED")
    link = wt / "loop"
    make_dir_link(link, wt)
    started = time.time()
    try:
        r = w.run(*flags)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Traceback" not in r.stderr, r.stderr
        assert time.time() - started < 60, "walking the self-link took far too long"
        line = w.line(r.stdout, "wt-151")
        assert line.startswith("KEPT") and "loop" in norm(line), r.stdout
        assert wt.exists() and (wt / "work.txt").exists()
        assert "f/151-loop" in w.branches()
        if flags:
            assert other.exists()
        else:
            assert not other.exists(), "one link stopped the sweep"
    finally:
        drop_link(link)


def test_a_nested_bare_repository_is_kept(w: World) -> None:
    wt = w.worktree("f/153-bare", "wt-153")
    w.pr("f/153-bare", "MERGED")
    bare = wt / "vendor" / "bare.git"
    bare.parent.mkdir(parents=True)
    git(wt, "init", "--bare", "-b", "main", str(bare))
    git(w.repo, "push", str(bare), "main")  # it holds a commit that exists nowhere else
    assert (bare / "HEAD").exists() and not (bare / ".git").exists()
    out = ok(w.run())
    line = w.line(out, "wt-153")
    assert line.startswith("KEPT"), out
    assert "vendor/bare.git" in norm(line), line
    assert wt.exists() and (bare / "HEAD").exists() and (bare / "objects").exists()
    assert "f/153-bare" in w.branches()


# ---- --repo is checked before anything is pruned --------------------------------------------


def test_a_refused_repo_mismatch_does_not_prune_a_worktree_whose_folder_is_gone(
    w: World,
) -> None:
    gone = w.worktree("f/140-gone", "wt-140")
    w.pr("f/140-gone", "MERGED")
    shutil.rmtree(gone)
    admin = w.repo / ".git" / "worktrees" / "wt-140"
    assert admin.exists()
    set_origin_url(w, "https://github.com/Somebody/else.git")
    r = w.run()
    assert r.returncode != 0, r.stdout + r.stderr
    assert admin.exists(), "the check must run before `git worktree prune`"
    assert "f/140-gone" in w.branches()

