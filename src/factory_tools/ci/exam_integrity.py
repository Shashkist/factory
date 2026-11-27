"""Exam integrity check (DECISIONS D3).

Usage: python exam_integrity.py <base> <head> [--bootstrap] [--exam-commit SHA]
           [--exam-paths GLOB [GLOB ...]] [--ci-paths GLOB [GLOB ...]]

The exam is every file under tests/ except tests/unit/, plus pytest
configuration files (conftest.py, pytest.ini, .pytest.ini, pytest.toml, .pytest.toml,
tox.ini, setup.cfg) anywhere outside tests/unit/, plus the interpreter start hooks at
any path (Python runs them before the exam does): *.pth; a sitecustomize or usercustomize module
(.py, .pyw, .pyc, .pyd, .so, with any cache or ABI tag in between such as
__pycache__/sitecustomize.cpython-312.pyc or sitecustomize.cp312-win_amd64.pyd);
a bare sitecustomize or usercustomize entry (a symlink to a package); and
anything under a directory named sitecustomize or usercustomize (package form).
A file named pyproject.toml at any depth is exam in a commit whose parsed
tool.pytest table (the ini_options form and pytest 9's native form) differs from
the parent's (changed, added or removed; an unparsable file counts as changed);
otherwise it is code. It stays exam under
--exam-paths. Judging that needs file content, so only the CI check does it; the merge
gate works on file names and treats pyproject.toml as code.
Code is every path outside tests/ that is not the exam.
Fails when:
- the range contains merge commits;
- one commit changes the exam and code together;
- the exam changes after the first commit that changed code;
- the PR changes the exam together with the CI surface
  (src/factory_tools/ci/** or any file under .github/workflows/); skipped with --bootstrap,
  used when the base branch has no copy of this script yet.

--exam-commit SHA (DECISIONS D43) is the recorded exam commit. The judge also fails when SHA
is not a full 40-hex id of a commit, is not an ancestor of head, or when any file that is exam
under the rules above differs between SHA and head. Without it the per-commit check runs
alone and one line says so.

--exam-paths replaces the tests/ part of the exam rule with the given globs; the
pytest configuration files outside tests/unit/ and the start hooks are always exam, and
the "top-level tests/ is never code" exception applies only without --exam-paths. --ci-paths
replaces the CI surface. A value may hold several whitespace-separated globs.
A leading ./ is dropped and a trailing / means <dir>/**.
Globs are fnmatch style, matched against the whole repo-relative path, and `*`
and `**` both match across `/`. Both are optional; the defaults are as above.
"""

import argparse
import re
import subprocess
import sys
import tomllib
from fnmatch import fnmatchcase

MERGE_MSG = "merge commits are not allowed on a PR branch; rebase onto main"
PYTEST_CONFIG = {
    "conftest.py",
    "pytest.ini",
    ".pytest.ini",
    "pytest.toml",
    ".pytest.toml",
    "tox.ini",
    "setup.cfg",
}
SITE_HOOKS = {"sitecustomize", "usercustomize"}
SITE_SUFFIXES = {"py", "pyw", "pyc", "pyd", "so"}


def _norm_glob(g: str) -> str:
    while g.startswith("./"):
        g = g[2:]
    if g.endswith("/"):
        g += "**"
    return g


def _globs(values: list[str] | None) -> list[str] | None:
    """Split each value on whitespace and normalise; None when nothing was given."""
    if values is None:
        return None
    return [_norm_glob(g) for v in values for g in v.split()] or None


def _matches(path: str, globs: list[str]) -> bool:
    return any(fnmatchcase(path, _norm_glob(g)) for g in globs)


def _in_unit(parts: list[str]) -> bool:
    return any(parts[i : i + 2] == ["tests", "unit"] for i in range(len(parts) - 1))


def _is_site_hook(parts: list[str]) -> bool:
    if any(d in SITE_HOOKS for d in parts[:-1]):  # package form: sitecustomize/__init__.py
        return True
    bits = parts[-1].split(".")
    if bits[-1] == "pth" and len(bits) > 1:
        return True
    if bits[0] not in SITE_HOOKS:
        return False
    # a bare name is a symlink or file Python can import as the hook; any middle parts
    # are a cache or ABI tag (sitecustomize.cpython-312.pyc, sitecustomize.cp312-win_amd64.pyd)
    return len(bits) == 1 or bits[-1] in SITE_SUFFIXES


def _is_exam(
    path: str, exam_paths: list[str] | None = None, pytest_toml: frozenset[str] = frozenset()
) -> bool:
    """pytest_toml: pyproject.toml paths of this commit whose pytest table changed."""
    parts = path.split("/")
    if _is_site_hook(parts) or path in pytest_toml:
        return True
    # pytest configuration outside tests/unit/ can skip or rewrite exam results,
    # whatever the exam globs say; the defaults exempt only the top-level tests/unit/
    in_unit = _in_unit(parts) if exam_paths is not None else parts[:2] == ["tests", "unit"]
    if parts[-1] in PYTEST_CONFIG and not in_unit:
        return True
    if exam_paths is not None:
        return _matches(path, exam_paths)
    return parts[0] == "tests" and parts[:2] != ["tests", "unit"]


def _is_code(
    path: str, exam_paths: list[str] | None = None, pytest_toml: frozenset[str] = frozenset()
) -> bool:
    if _is_exam(path, exam_paths, pytest_toml):
        return False
    # top-level tests/ is never code, with the default exam rules only
    return exam_paths is not None or path.split("/")[0] != "tests"


def _is_ci_surface(path: str, ci_paths: list[str] | None = None) -> bool:
    if ci_paths is not None:
        return _matches(path, ci_paths)
    return path.startswith(("src/factory_tools/ci/", ".github/workflows/"))


def check(
    commits: list[list[str]],
    bootstrap: bool = False,
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
    pytest_toml: list[frozenset[str]] | None = None,
) -> list[str]:
    """commits: changed paths per commit, oldest first. Returns error messages.

    pytest_toml: per commit, the pyproject.toml paths whose pytest table changed."""
    errors: list[str] = []
    code_seen = False
    toml = pytest_toml or [frozenset()] * len(commits)
    for i, files in enumerate(commits):
        exam = any(_is_exam(f, exam_paths, toml[i]) for f in files)
        code = any(_is_code(f, exam_paths, toml[i]) for f in files)
        if exam and code:
            errors.append(f"commit {i} changes the exam and code together")
        elif exam and code_seen:
            errors.append(f"commit {i} changes the exam after code was added")
        code_seen = code_seen or code
    if (
        not bootstrap
        and any(_is_exam(f, exam_paths, toml[i]) for i, fs in enumerate(commits) for f in fs)
        and any(_is_ci_surface(f, ci_paths) for fs in commits for f in fs)
    ):
        errors.append("PR changes the exam together with the CI surface")
    return errors


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, encoding="utf-8", errors="replace"
    ).stdout


def _pytest_table(sha: str, path: str) -> object:
    """The tool.pytest table of path at sha (ini_options and the native form); None when absent.

    An unparsable file returns a unique sentinel, so it differs from any other state:
    fail closed, an exam change we cannot read is treated as one."""
    try:
        text = _git("show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None
    try:
        return tomllib.loads(text).get("tool", {}).get("pytest")
    except (tomllib.TOMLDecodeError, AttributeError):
        return object()


def _changed_pytest_tomls(
    sha: str, files: list[str], before_ref: str | None = None
) -> frozenset[str]:
    out = set()
    for f in files:
        if f.rsplit("/", 1)[-1] != "pyproject.toml":
            continue
        # no parent (root commit): git fails, None
        before = _pytest_table(before_ref or f"{sha}^", f)
        after = _pytest_table(sha, f)
        if before != after:
            out.add(f)
    return frozenset(out)


def _check_exam_commit(sha: str, head: str, exam_paths: list[str] | None) -> list[str]:
    """Errors for a recorded exam commit: fails closed on anything it cannot confirm."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return [f"exam commit {sha!r} is not a full 40-hex commit id"]
    try:
        _git("cat-file", "-e", f"{sha}^{{commit}}")
    except subprocess.CalledProcessError:
        return [f"exam commit {sha} is not a commit of this checkout"]
    anc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, head], capture_output=True, check=False
    )
    if anc.returncode != 0:
        return [f"exam commit {sha} is not an ancestor of the head (history rewritten?)"]
    diff = _exam_files_between(sha, head, exam_paths)
    if isinstance(diff, str):
        return [diff]
    return [f"exam file {f} differs between exam commit {sha} and the head" for f in diff]


def _exam_files_between(sha: str, other: str, exam_paths: list[str] | None) -> list[str] | str:
    """Exam files that differ between two commits, or an error text when git cannot say."""
    try:
        files = [
            f
            for f in _git(
                "-c", "core.quotePath=false", "diff", "--no-renames", "-z", "--name-only",
                sha, other,
            ).split("\0")
            if f
        ]
        toml = _changed_pytest_tomls(other, files, before_ref=sha)
    except subprocess.CalledProcessError as e:
        return f"cannot compare {other} with exam commit {sha}: git exited {e.returncode}"
    return [f for f in files if _is_exam(f, exam_paths, toml)]


def _is_commit(sha: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return False
    return subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, check=False
    ).returncode == 0


def _check_marker_chain(chain: list[str], head: str, exam_paths: list[str] | None) -> list[str]:
    """D43 amendment 2: a later marker supersedes an earlier one only with an identical exam."""
    for sha in chain:
        print(f"exam-commit marker seen: {sha}")
    for earlier, later in zip(chain, chain[1:], strict=False):
        bad = [
            f"exam-commit marker {s} is not a commit of this checkout"
            for s in (earlier, later)
            if not _is_commit(s)
        ]
        if bad:
            return bad
        diff = _exam_files_between(earlier, later, exam_paths)
        if isinstance(diff, str):
            return [diff]
        if diff:
            return [
                f"exam-commit marker {later} supersedes {earlier} but the exam differs "
                f"({', '.join(diff)}): the exam cannot move after it was recorded"
            ]
    print(f"exam-commit marker used: {chain[-1]}")
    return _check_exam_commit(chain[-1], head, exam_paths)


def main(
    base: str,
    head: str,
    bootstrap: bool,
    exam_paths: list[str] | None = None,
    ci_paths: list[str] | None = None,
    exam_commit: list[str] | None = None,
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
    toml = [_changed_pytest_tomls(sha, files) for sha, files in zip(shas, commits, strict=True)]
    errors = check(commits, bootstrap, exam_paths, ci_paths, toml)
    if not exam_commit:
        print("no exam-commit marker: per-commit check only")
    else:
        errors += _check_marker_chain(exam_commit, head, exam_paths)
    for err in errors:
        print(f"FAIL: {err}")
    print(f"checked {len(shas)} commits: {'FAILED' if errors else 'ok'}")
    return 1 if errors else 0


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="exam_integrity.py", allow_abbrev=False)
    ap.add_argument("base")
    ap.add_argument("head")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--exam-commit", action="append", default=None, metavar="SHA")
    ap.add_argument("--exam-paths", nargs="+", action="extend", metavar="GLOB")
    ap.add_argument("--ci-paths", nargs="+", action="extend", metavar="GLOB")
    a = ap.parse_args(argv)
    # each value may hold several whitespace-separated globs (one value per workflow input)
    a.exam_paths = _globs(a.exam_paths)
    a.ci_paths = _globs(a.ci_paths)
    return a


if __name__ == "__main__":
    a = _parse(sys.argv[1:])
    sys.exit(main(a.base, a.head, a.bootstrap, a.exam_paths, a.ci_paths, a.exam_commit))
