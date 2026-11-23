"""Exam integrity check (DECISIONS D3).

Usage: python exam_integrity.py <base> <head> [--bootstrap]

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
"""

import subprocess
import sys

MERGE_MSG = "merge commits are not allowed on a PR branch; rebase onto main"
PYTEST_CONFIG = {"conftest.py", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg"}


def _is_exam(path: str) -> bool:
    parts = path.split("/")
    if parts[:2] == ["tests", "unit"]:
        return False
    # pytest configuration outside tests/unit/ can skip or rewrite exam results
    return parts[-1] in PYTEST_CONFIG or parts[0] == "tests"


def _is_code(path: str) -> bool:
    return not _is_exam(path) and path.split("/")[0] != "tests"


def _is_ci_surface(path: str) -> bool:
    return path.startswith("src/factory_tools/ci/") or path == ".github/workflows/ci.yml"


def check(commits: list[list[str]], bootstrap: bool = False) -> list[str]:
    """commits: changed paths per commit, oldest first. Returns error messages."""
    errors: list[str] = []
    code_seen = False
    for i, files in enumerate(commits):
        exam = any(_is_exam(f) for f in files)
        code = any(_is_code(f) for f in files)
        if exam and code:
            errors.append(f"commit {i} changes the exam and code together")
        elif exam and code_seen:
            errors.append(f"commit {i} changes the exam after code was added")
        code_seen = code_seen or code
    allf = [f for files in commits for f in files]
    if not bootstrap and any(_is_exam(f) for f in allf) and any(_is_ci_surface(f) for f in allf):
        errors.append("PR changes the exam together with the CI surface")
    return errors


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, encoding="utf-8", errors="replace"
    ).stdout


def main(base: str, head: str, bootstrap: bool) -> int:
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
    errors = check(commits, bootstrap)
    for err in errors:
        print(f"FAIL: {err}")
    print(f"checked {len(shas)} commits: {'FAILED' if errors else 'ok'}")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: exam_integrity.py <base> <head> [--bootstrap]")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2], "--bootstrap" in sys.argv[3:]))
