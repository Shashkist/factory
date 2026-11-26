"""Issue #11: sitecustomize.py, usercustomize.py and *.pth count as exam surface.

Python imports these at interpreter start, from any directory on sys.path (the
editable install puts src/ there), so a code commit carrying one can rewrite the
exam run (for example PYTEST_ADDOPTS) while integrity stays green. They are
exam at any path, with the default rules, and are judged like every other exam
file: not together with code, not after code, not together with the CI surface
(unless --bootstrap).

Scope item 2 of the issue (PR-copy fallback of the gate) no longer exists: the
reusable workflows check the judge out at the pinned commit and fail when
origin/$BASE_REF is missing. Scope item 3 (incident.yml comment) is documentation.
"""

import subprocess
from pathlib import Path

import pytest
from test_issue_1_exam_integrity import Repo, bad, ok

CODE = "src/factory_tools/app.py"
CI_FILE = "src/factory_tools/ci/exam_integrity.py"

HOOKS = [
    "sitecustomize.py",
    "usercustomize.py",
    "src/sitecustomize.py",
    "src/usercustomize.py",
    "tests/unit/sitecustomize.py",
    "tests/unit/usercustomize.py",
    "x.pth",
    "src/foo.pth",
    "a/b/c/deep.pth",
]
NEAR_MISSES = [
    "my_sitecustomize.py",
    "src/my_sitecustomize.py",
    "src/pth.py",
    "src/foo.pth.txt",
    "src/sitecustomize.pyi.txt",
    "src/usercustomize_helper.py",
]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def check(repo: Repo, *extra: str) -> subprocess.CompletedProcess[str]:
    return repo.check(*extra)


@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_together_with_code_in_one_commit_is_refused(repo: Repo, hook: str) -> None:
    repo.commit({hook: "x = 1\n", CODE: "1\n"}, "hook and code")
    r = check(repo)
    bad(r)
    assert "FAIL:" in r.stdout, r.stdout


@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_added_after_a_code_commit_is_refused(repo: Repo, hook: str) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({hook: "x = 1\n"}, "hook")
    bad(check(repo))


@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_together_with_the_ci_surface_is_refused_without_bootstrap(
    repo: Repo, hook: str
) -> None:
    repo.commit({hook: "x = 1\n"}, "hook")
    repo.commit({CI_FILE: "1\n"}, "ci surface")
    bad(check(repo))


@pytest.mark.parametrize("hook", ["src/sitecustomize.py", "src/foo.pth"])
def test_bootstrap_still_allows_a_site_hook_with_the_ci_surface(repo: Repo, hook: str) -> None:
    repo.commit({hook: "x = 1\n"}, "hook")
    repo.commit({CI_FILE: "1\n"}, "ci surface")
    ok(check(repo, "--bootstrap"))


@pytest.mark.parametrize("hook", ["src/sitecustomize.py", "src/usercustomize.py", "src/foo.pth"])
def test_site_hook_first_then_code_is_judged_like_any_exam_file(repo: Repo, hook: str) -> None:
    repo.commit({hook: "x = 1\n"}, "hook")
    repo.commit({CODE: "1\n"}, "code")
    ok(check(repo))


@pytest.mark.parametrize("name", NEAR_MISSES)
def test_near_miss_names_stay_code(repo: Repo, name: str) -> None:
    repo.commit({name: "x = 1\n", CODE: "1\n"}, "both are code")
    ok(check(repo))
    repo.commit({"tests/acceptance/x.py": "1\n"}, "exam after code")
    bad(check(repo))


def test_site_hook_with_exam_paths_globs_still_counts_as_exam(repo: Repo) -> None:
    repo.commit({"labs/manager/sitecustomize.py": "x = 1\n", "labs/manager/app.py": "1\n"}, "both")
    bad(check(repo, "--exam-paths", "labs/*/tests/acceptance/**"))
