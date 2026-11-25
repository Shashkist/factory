"""Exam integrity check (DECISIONS D3).

Usage: python exam_integrity.py <base> <head> [--bootstrap]
           [--exam-paths GLOB [GLOB ...]] [--ci-paths GLOB [GLOB ...]]

The exam is every file under tests/ except tests/unit/, plus pytest
configuration files (conftest.py, pytest.ini, .pytest.ini, tox.ini, setup.cfg)
anywhere outside tests/unit/. Code is every path outside tests/ that is not the exam.
Fails when:
- the range contains merge commits;
- one commit changes the exam and code together;
- the exam changes after the first commit that changed code;
- the PR changes the exam together with the CI surface
  (src/factory_tools/ci/** or the CI workflow); skipped with --bootstrap,
  used when the base branch has no copy of this script yet.

--exam-paths replaces the exam rule (tests/ except tests/unit/, plus the pytest
configuration files) with the given globs; --ci-paths replaces the CI surface.
Globs are fnmatch style, matched against the whole repo-relative path, and `*`
and `**` both match across `/`. Both are optional; the defaults are as above.
"""

import argparse
import subprocess
import sys
from fnmatch import fnmatchcase

MERGE_MSG = "merge commits are not allowed on a PR branch; rebase onto main"
PYTEST_CONFIG = {"conftest.py", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg"}


def _matches(path: str, globs: list[str]) -> bool:
    return any(fnmatchcase(path, g) for g in globs)


def _is_exam(path: str, exam_paths: list[str] | None = None) -> bool:
    if exam_paths is not None:
        return _matches(path, exam_paths)
    parts = path.split("/")
    if parts[:2] == ["tests", "unit"]:
        return False
    # pytest configuration outside tests/unit/ can skip or rewrite exam results
    return parts[-1] in PYTEST_CONFIG or parts[0] == "tests"


def _is_code(path: str, exam_paths: list[str] | None = None) -> bool:
    return not _is_exam(path, exam_paths) and path.split("/")[0] != "tests"


def _is_ci_surface(path: str, ci_paths: list[str] | None = None) -> bool:
    if ci_paths is not None:
        return _matches(path, ci_paths)
    return path.startswith("src/factory_tools/ci/") or path == ".github/workflows/ci.yml"


def check(
    commits: list[list[str]],
    bootstrap: bool = False,
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
) -> list[str]:
    """commits: changed paths per commit, oldest first. Returns error messages."""
    errors: list[str] = []
    code_seen = False
    for i, files in enumerate(commits):
        exam = any(_is_exam(f, exam_paths) for f in files)
        code = any(_is_code(f, exam_paths) for f in files)
        if exam and code:
            errors.append(f"commit {i} changes the exam and code together")
        elif exam and code_seen:
            errors.append(f"commit {i} changes the exam after code was added")
        code_seen = code_seen or code
    allf = [f for files in commits for f in files]
    if (
        not bootstrap
        and any(_is_exam(f, exam_paths) for f in allf)
        and any(_is_ci_surface(f, ci_paths) for f in allf)
    ):
        errors.append("PR changes the exam together with the CI surface")
    return errors


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, encoding="utf-8", errors="replace"
    ).stdout


def main(
    base: str,
    head: str,
    bootstrap: bool,
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
) -> int:
    if _git("rev-list", "--merges", f"{base}..{head}").split():
        print(f"FAIL: {MERGE_MSG}")
        return 1
    shas = _git("rev-list", "--topo-order", "--reverse", f"{base}..{head}").split()
    commits = [
        [
            f
            for f in _git(
                "-c", "core.quotePath=false", "diff-tree", "-z", "--no-commit-id",
                "--name-only", "-r", "--root", sha,
            ).split("\0")
            if f
        ]
        for sha in shas
    ]
    errors = check(commits, bootstrap, exam_paths, ci_paths)
    for err in errors:
        print(f"FAIL: {err}")
    print(f"checked {len(shas)} commits: {'FAILED' if errors else 'ok'}")
    return 1 if errors else 0


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="exam_integrity.py")
    ap.add_argument("base")
    ap.add_argument("head")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--exam-paths", nargs="+", metavar="GLOB")
    ap.add_argument("--ci-paths", nargs="+", metavar="GLOB")
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = _parse(sys.argv[1:])
    sys.exit(main(a.base, a.head, a.bootstrap, a.exam_paths, a.ci_paths))
