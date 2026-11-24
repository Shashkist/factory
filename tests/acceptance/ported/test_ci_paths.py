# Ported from Learning Factory scripts/test_ci_paths.py (#271 and later fixes). Changes versus LF:
#   - path: `SCRIPT = Path(__file__).with_name("ci_paths.py")` became the package file
#     `src/factory_tools/pipeline/paths.py` (ci_paths.py moved into the package); the plain-file runs
#     in `run()` are unchanged.
#   - import: `load_ci_paths()` imports `factory_tools.pipeline.paths` (with src/ on sys.path) instead
#     of `import ci_paths` from the scripts folder.
#   - fixture: `test_paths_ignore_matches_docs_by_kind` read LF's `.github/workflows/ci.yml`; it now
#     reads `fixtures/lf_ci_paths_ignore.yml` (LF ci.yml lines 1-13 verbatim, with a header naming
#     the source commit), because this repository's ci.yml has no paths-ignore block. The
#     assertions are unchanged and the test never skips.
#   - lint: a file-level ruff noqa comment for E501, UP017 and I001 (LF code is not held to this
#     repo's ruff rules). A comment only; no code line altered.
#   - package: the modules live in `factory_tools.pipeline` (not `factory_tools.ci`), per decision D9;
#     module paths, imports and `-m` names follow; the CLI names `ci-paths` and `incident-gate` stay.
#   Nothing else changed: every case and assertion is as in LF.
# ruff: noqa: E501, UP017, I001
"""Tests for factory_tools.pipeline.paths (LF scripts/ci_paths.py), on throwaway git repos."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_CI = Path(__file__).resolve().parent / "fixtures" / "lf_ci_paths_ignore.yml"
SCRIPT = REPO_ROOT / "src" / "factory_tools" / "pipeline" / "paths.py"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        [
            "git",
            "-c", "user.name=t",
            "-c", "user.email=t@example.com",
            "-c", "commit.gpgsign=false",
            "-c", "core.quotePath=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return out.stdout.strip()


def commit(repo: Path, *files: str) -> str:
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{f}\n{git(repo, 'rev-list', '--all', '--count')}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c " + ",".join(files))
    return git(repo, "rev-parse", "HEAD")


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "labs/manager/app.py")
    return tmp_path


def deploys(repo: Path, tag: str, head: str) -> str:
    r = run(repo, "deploys", tag, head)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# Path classes, through the rule Deploy uses: code below, <files> on top, may the code's CI deploy?
def test_docs_only_on_top_deploys(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    commit(repo, "docs/factory/STATE.md")
    head = commit(repo, "courses/x.md", ".claude/s.json")
    assert deploys(repo, code, head) == "true"


def test_mixed_commit_counts_as_code(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "docs/a.md", "labs/web/b.ts")
    assert deploys(repo, code, head) == "false"


def test_lab_content_markdown_is_code(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "labs/content/x/task.he.md")
    assert deploys(repo, code, head) == "false"


def test_root_readme_is_code(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "README.md")
    assert deploys(repo, code, head) == "false"


def test_non_ascii_lab_content_is_code(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "labs/content/x/שלב.md")
    assert deploys(repo, code, head) == "false"


def test_hebrew_name_under_courses_is_docs_only(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "courses/שיעור.md")
    assert deploys(repo, code, head) == "true"


def test_unknown_tag_fails_loudly(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    r = run(repo, "deploys", "0" * 40, head)
    assert r.returncode != 0
    assert r.stderr.strip()


def test_deploys_when_only_docs_landed_after(repo: Path) -> None:
    code = commit(repo, "labs/manager/b.py")
    head = commit(repo, "docs/factory/STATE.md")
    assert deploys(repo, code, head) == "true"


def test_deploys_the_docs_head_of_a_mixed_push(repo: Path) -> None:
    commit(repo, "labs/manager/b.py")
    head = commit(repo, "docs/factory/STATE.md")
    assert deploys(repo, head, head) == "true"


def test_older_code_never_deploys(repo: Path) -> None:
    old = commit(repo, "labs/manager/b.py")
    commit(repo, "docs/a.md")
    head = commit(repo, "labs/web/c.ts")
    assert deploys(repo, old, head) == "false"


def test_code_then_revert_then_docs_still_deploys(repo: Path) -> None:
    # One push [X, revert X, docs] is docs-only for GitHub's paths-ignore: no CI, so the code
    # commit below must still deploy (review of #278, finding 4).
    c1 = commit(repo, "labs/manager/b.py")
    commit(repo, "labs/web/a.ts")
    git(repo, "revert", "--no-edit", "HEAD")
    head = commit(repo, "docs/y.md")
    assert deploys(repo, c1, head) == "true"


def test_a_tag_off_main_never_deploys(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, "docs/a.md")
    git(repo, "checkout", "-q", "main")
    git(repo, "reset", "-q", "--hard", base)
    head = commit(repo, "docs/b.md")
    assert deploys(repo, side, head) == "false"


def load_ci_paths():  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from factory_tools.pipeline import paths as ci_paths
    finally:
        sys.path.pop(0)
    return ci_paths


def test_paths_ignore_matches_docs_by_kind() -> None:
    mod = load_ci_paths()
    ci = FIXTURE_CI.read_text(encoding="utf-8")
    block = ci.split("paths-ignore:", 1)[1].split("\n\n", 1)[0]
    entries = [ln.strip()[2:].strip() for ln in block.splitlines() if ln.strip().startswith("- ")]
    # Every entry must have the one shape the script understands, so no extra rule hides here.
    # Two shapes only: "<dir>/**" for a directory, "<name>" for an exact root file.
    shape = r'"[^"*/]+(/\*\*)?"'
    assert entries and all(re.fullmatch(shape, e) for e in entries), entries
    dirs = [e[1:-4] for e in entries if e.endswith('/**"')]
    files = [e[1:-1] for e in entries if not e.endswith('/**"')]
    # The kind matters: "docs/**" is a directory's contents, "docs" is a root file.
    assert sorted(dirs) == sorted(mod.DOCS_DIRS)
    assert sorted(files) == sorted(mod.DOCS_FILES)


BAD_NAMES = ["*.md", "history?.md", "[h]istory.md", "history.md\\", "hist\\ory.md"]


@pytest.mark.parametrize("kind", ["DOCS_FILES", "DOCS_DIRS"])
@pytest.mark.parametrize("name", BAD_NAMES)
def test_docs_names_refuse_glob_characters(
    name: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The check runs where the names become pathspecs, so it cannot be skipped by a refactor.
    mod = load_ci_paths()
    monkeypatch.setattr(mod, kind, (name,))
    with pytest.raises(ValueError):
        mod.code_spec()


def test_code_spec_accepts_the_real_names() -> None:
    assert load_ci_paths().code_spec()


@pytest.mark.parametrize("var", ["GIT_LITERAL_PATHSPECS", "GIT_ICASE_PATHSPECS"])
def test_ignores_pathspec_variables(
    repo: Path, monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    # GIT_LITERAL_PATHSPECS=1 would turn the ":(top)" and ":(exclude...)" specs into file names;
    # GIT_ICASE_PATHSPECS=1 would treat "Docs/" as docs, but ci.yml paths-ignore is case-sensitive.
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "docs/x.md")
    assert deploys(repo, code, head) == "true"
    monkeypatch.setenv(var, "1")
    assert deploys(repo, code, head) == "true"
    # Each case starts from its own code commit, so only the one new path is in the diff.
    for path in ("labs/web/b.ts", "Courses/run.py", "HISTORY.md"):
        code = commit(repo, f"labs/web/{len(path)}.ts")
        assert deploys(repo, code, commit(repo, path)) == "false", path


def test_root_history_after_code_still_deploys(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "history.md")
    assert deploys(repo, code, head) == "true"


def test_history_with_docs_is_docs_only(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "history.md", "docs/x.md")
    assert deploys(repo, code, head) == "true"


@pytest.mark.parametrize(
    "path", ["a/history.md", "history.md.bak", "docs-history.md", "history.mdx"]
)
def test_lookalike_history_is_code(repo: Path, path: str) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, path)
    assert deploys(repo, code, head) == "false"


@pytest.mark.parametrize(
    "path", ["history.md/x.py", "docs", "courses", ".claude"]
)
def test_directory_or_file_of_the_wrong_kind_is_code(repo: Path, path: str) -> None:
    # GitHub's paths-ignore "history.md" is the root file only and "docs/**" is the contents of a
    # directory: a directory named history.md, or a root file named docs, is code (#408).
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, path)
    assert deploys(repo, code, head) == "false"


def test_docs_commit_before_newer_code_does_not_deploy(repo: Path) -> None:
    docs = commit(repo, "docs/a.md")
    head = commit(repo, "labs/web/c.ts")
    assert deploys(repo, docs, head) == "false"


def heavy(repo: Path, base: str, head: str = "HEAD") -> str:
    r = run(repo, "heavy", base, head)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def branch_with(repo: Path, *files: str) -> str:
    git(repo, "checkout", "-q", "-b", "pr")
    commit(repo, *files)
    return "main"


@pytest.mark.parametrize(
    "path",
    ["docs/a.md", "README.md", "labs/web/x.md", "labs/web/index.html", "labs/managerial/x.py"],
)
def test_heavy_false(repo: Path, path: str) -> None:
    base = branch_with(repo, path)
    assert heavy(repo, base) == "false"


@pytest.mark.parametrize(
    "path",
    [
        "labs/images/term/Dockerfile",
        "labs/manager/app/x.py",
        "labs/deploy/compose.yml",
        "labs/content/x/lab.yaml",
        ".github/workflows/ci.yml",
        "labs/content/x/שלב.md",
        "labs/web/src/a.ts",
        "labs/web/tests/acceptance/x.pw.ts",
        "labs/web/package.json",
        "labs/web/package-lock.json",
        "labs/web/vite.config.ts",
    ],
)
def test_heavy_true(repo: Path, path: str) -> None:
    base = branch_with(repo, path)
    assert heavy(repo, base) == "true"


def test_heavy_uses_merge_base(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "pr")
    commit(repo, "labs/web/a.ts")
    git(repo, "checkout", "-q", "main")
    commit(repo, "labs/manager/new.py")
    git(repo, "checkout", "-q", "pr")
    assert heavy(repo, "main") == "false"
