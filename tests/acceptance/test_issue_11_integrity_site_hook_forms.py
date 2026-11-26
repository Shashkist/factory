"""Issue #11, D39 amendment 2: every form Python imports as a start hook is exam.

Package form (sitecustomize/__init__.py), compiled and extension modules (with or
without a cache or ABI tag), cached bytecode and the bare entry (a symlink to a
package directory, or a bare file) are judged like sitecustomize.py: refused
together with code and after code, accepted alone before any code (exam-first
order). Near-misses stay code. Run with the default rules and with exam-paths globs.
"""

import subprocess
from pathlib import Path

import pytest
from test_issue_1_exam_integrity import Repo, bad, ok

CODE = "src/factory_tools/app.py"
GLOBS = ("--exam-paths", "labs/*/tests/acceptance/**")
MODES = [(), GLOBS]
MODE_IDS = ["default", "exam-paths"]

SYMLINK = "src/sitecustomize"
HOOKS = [
    "src/sitecustomize/__init__.py",
    "usercustomize/a/b.py",
    "sitecustomize.pyc",
    "sitecustomize.pyw",
    "sitecustomize.pyd",
    "sitecustomize.so",
    "sitecustomize.cpython-312-x86_64-linux-gnu.so",
    "sitecustomize.cp312-win_amd64.pyd",
    "sitecustomize.abi3.so",
    "src/__pycache__/sitecustomize.cpython-312.pyc",
    "src/sitecustomize.cpython-312.pyc",
    "__pycache__/usercustomize.cpython-312.opt-1.pyc",
    "usercustomize",
    SYMLINK,
]
NEAR_MISSES = [
    "src/sitecustomizer",
    "src/sitecustomize.txt",
    "src/__pycache__/sitecustomize.cpython-312.pyc.txt",
]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def add_hook(repo: Repo, hook: str, msg: str, extra: dict[str, str] | None = None) -> None:
    """Commit the hook (and optional extra files). The symlink goes in through the
    index as mode 120000, so no OS symlink rights are needed."""
    if hook != SYMLINK:
        repo.commit({hook: "x = 1\n", **(extra or {})}, msg)
        return
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo.path,
        input="pkg_dir",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    repo.git("update-index", "--add", "--cacheinfo", f"120000,{blob},{hook}")
    for name, content in (extra or {}).items():
        p = repo.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        repo.git("add", "--", name)
    repo.git("commit", "-q", "-m", msg)


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_form_in_a_code_only_commit_after_code_is_refused(
    repo: Repo, hook: str, mode: tuple[str, ...]
) -> None:
    repo.commit({CODE: "1\n"}, "code")
    add_hook(repo, hook, "hook")
    bad(repo.check(*mode))


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_form_together_with_code_in_one_commit_is_refused(
    repo: Repo, hook: str, mode: tuple[str, ...]
) -> None:
    add_hook(repo, hook, "hook and code", {CODE: "1\n"})
    r = repo.check(*mode)
    bad(r)
    assert "FAIL:" in r.stdout, r.stdout


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("hook", HOOKS)
def test_site_hook_form_committed_alone_before_any_code_is_accepted(
    repo: Repo, hook: str, mode: tuple[str, ...]
) -> None:
    add_hook(repo, hook, "hook")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check(*mode))


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("name", NEAR_MISSES)
def test_near_miss_names_stay_code(repo: Repo, name: str, mode: tuple[str, ...]) -> None:
    repo.commit({name: "x = 1\n", CODE: "1\n"}, "both are code")
    ok(repo.check(*mode))
    exam = "labs/m/tests/acceptance/x.py" if mode else "tests/acceptance/x.py"
    repo.commit({exam: "1\n"}, "exam after code")
    bad(repo.check(*mode))
