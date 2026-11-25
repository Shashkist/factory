"""Issue #1, criteria 2 and 3: exam integrity on a real temporary git repo."""

import subprocess
import sys
from pathlib import Path

import pytest
from helpers import env, module_file, run_module

MOD = "factory_tools.ci.exam_integrity"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.commit({"README.md": "base\n"}, "base")
        self.base = self.rev("HEAD")

    def git(self, *args: str) -> str:
        r = subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env(GIT_ENV),
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip()

    def rev(self, ref: str) -> str:
        return self.git("rev-parse", ref)

    def commit(self, files: dict[str, str], msg: str) -> None:
        for name, content in files.items():
            p = self.path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
        self.git("add", "--", *files)
        self.git("commit", "-q", "-m", msg)

    def check(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return run_module(MOD, self.base, "HEAD", *extra, cwd=self.path)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def ok(r: subprocess.CompletedProcess[str]) -> None:
    assert r.returncode == 0, r.stdout + r.stderr


def bad(r: subprocess.CompletedProcess[str]) -> None:
    assert r.returncode != 0, r.stdout + r.stderr
    assert "No module named" not in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, r.stderr


EXAM = "tests/acceptance/x.py"
CODE = "src/factory_tools/y.py"


def test_one_commit_changing_exam_and_code_together_fails(repo: Repo) -> None:
    repo.commit({EXAM: "1\n", CODE: "1\n"}, "both")
    bad(repo.check())


def test_exam_commit_first_then_separate_code_commit_passes(repo: Repo) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_exam_change_after_a_code_commit_fails(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({EXAM: "1\n"}, "exam")
    bad(repo.check())


def test_pytest_ini_counts_as_exam(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({"pytest.ini": "[pytest]\n"}, "ini")
    bad(repo.check())


def test_conftest_outside_unit_tests_counts_as_exam(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({"conftest.py": "\n"}, "conftest")
    bad(repo.check())


def test_conftest_in_acceptance_dir_counts_as_exam(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({"tests/acceptance/conftest.py": "\n"}, "conftest")
    bad(repo.check())


def test_unit_tests_do_not_count_as_exam(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({"tests/unit/test_y.py": "\n"}, "unit")
    repo.commit({"tests/unit/conftest.py": "\n"}, "unit conftest")
    ok(repo.check())


def test_unit_tests_and_code_together_pass(repo: Repo) -> None:
    repo.commit({"tests/unit/test_y.py": "\n", CODE: "1\n"}, "both")
    ok(repo.check())


def test_merge_commit_in_range_fails(repo: Repo) -> None:
    repo.git("checkout", "-q", "-b", "side")
    repo.commit({"side.txt": "s\n"}, "side")
    repo.git("checkout", "-q", "main")
    repo.commit({"main.txt": "m\n"}, "main work")
    repo.base = repo.rev("HEAD")
    repo.git("checkout", "-q", "-b", "pr")
    repo.commit({"pr.txt": "p\n"}, "pr work")
    repo.git("merge", "-q", "--no-ff", "-m", "merge", "side")
    bad(repo.check())


SURFACES = ["src/factory_tools/ci/gate.py", ".github/workflows/ci.yml"]


@pytest.mark.parametrize("surface", SURFACES)
def test_exam_together_with_ci_surface_fails_without_bootstrap(
    repo: Repo, surface: str
) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({surface: "1\n"}, "ci")
    bad(repo.check())


@pytest.mark.parametrize("surface", SURFACES)
def test_exam_together_with_ci_surface_passes_with_bootstrap(
    repo: Repo, surface: str
) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({surface: "1\n"}, "ci")
    ok(repo.check("--bootstrap"))


def test_bootstrap_does_not_waive_the_exam_then_code_order(repo: Repo) -> None:
    repo.commit({EXAM: "1\n", CODE: "1\n"}, "both")
    bad(repo.check("--bootstrap"))


def test_module_file_runs_as_a_plain_script(repo: Repo) -> None:
    path = module_file(MOD)
    assert path is not None, f"{MOD} not found"
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({CODE: "1\n"}, "code")
    good = subprocess.run(
        [sys.executable, str(path), repo.base, "HEAD"],
        cwd=repo.path,
        env=env(),
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0, good.stdout + good.stderr
    repo.commit({EXAM: "2\n"}, "exam again")
    failing = subprocess.run(
        [sys.executable, str(path), repo.base, "HEAD"],
        cwd=repo.path,
        env=env(),
        capture_output=True,
        text=True,
    )
    assert failing.returncode != 0, failing.stdout + failing.stderr
# scratch check for #61, do not merge
