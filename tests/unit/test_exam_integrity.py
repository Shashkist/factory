import subprocess
from pathlib import Path

import pytest

from factory_tools.ci import exam_integrity
from factory_tools.ci.exam_integrity import check

EXAM = "tests/acceptance/test_issue_1.py"
CODE = "src/factory_tools/main.py"
UNIT = "tests/unit/test_main.py"
CI = "src/factory_tools/ci/exam_integrity.py"


def test_exam_first_then_code_passes() -> None:
    assert check([[EXAM], [CODE], [UNIT, CODE]]) == []


def test_no_exam_changes_passes() -> None:
    assert check([[CODE], [".github/workflows/ci.yml"]]) == []


def test_same_commit_exam_and_code_fails() -> None:
    errors = check([[EXAM, CODE]])
    assert len(errors) == 1 and "commit 0" in errors[0]


def test_exam_and_src_in_one_commit_fails() -> None:
    assert len(check([[EXAM, "src/factory_tools/__init__.py"]])) == 1


def test_exam_edit_after_code_fails() -> None:
    errors = check([[CODE], [EXAM]])
    assert len(errors) == 1 and "commit 1" in errors[0]


def test_unit_tests_are_free() -> None:
    assert check([[EXAM], [CODE], [UNIT]]) == []
    assert check([[CODE], [UNIT]]) == []


@pytest.mark.parametrize("cfg", ["conftest.py", "pytest.ini", "tox.ini", "setup.cfg"])
def test_pytest_config_outside_unit_is_exam(cfg: str) -> None:
    assert len(check([[CODE], [cfg]])) == 1


def test_unit_conftest_is_free() -> None:
    assert check([[CODE], ["tests/unit/conftest.py"]]) == []


def test_exam_with_ci_surface_fails_unless_bootstrap() -> None:
    commits = [[EXAM], [CI]]
    assert len(check(commits)) == 1
    assert check(commits, bootstrap=True) == []


def test_merge_commit_in_range_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def git(*a: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("branch", "side")
    git("commit", "-q", "--allow-empty", "-m", "a")
    git("checkout", "-q", "side")
    git("commit", "-q", "--allow-empty", "-m", "b")
    git("merge", "-q", "--no-ff", "-m", "m", "main")
    monkeypatch.chdir(tmp_path)
    assert exam_integrity.main("main~1", "HEAD", False) == 1
    assert "merge commits are not allowed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "path", ["tests/.pytest.ini", "tests/pyproject.toml", "tests/other/x.py", "src/.pytest.ini"]
)
def test_pytest_config_and_other_tests_paths_are_exam(path: str) -> None:
    assert len(check([[CODE], [path]])) == 1
    assert len(check([[path, CODE]])) == 1


def test_root_pyproject_stays_code() -> None:
    assert check([["pyproject.toml"], [EXAM]]) != []
    assert check([[EXAM], ["pyproject.toml"]]) == []


def test_non_ascii_exam_path_is_classified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def git(*a: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    for name in ("src/שלום.py", "tests/acceptance/שלום.py"):
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "both")
    monkeypatch.chdir(tmp_path)
    assert exam_integrity.main("HEAD~1", "HEAD", False) == 1


def test_globs_replace_the_defaults_and_cross_slashes() -> None:
    nested = "labs/m/tests/acceptance/a/b.py"
    assert check([[nested, CODE]], exam_paths=["labs/*/tests/acceptance/**"])
    assert check([[nested, CODE]]) == []
    assert check([[EXAM], [CODE]], exam_paths=["labs/**"]) == []


def test_ci_paths_replace_the_default_surface() -> None:
    assert check([[EXAM], [CI]], ci_paths=["ci/**"]) == []
    assert check([[EXAM], ["ci/run.sh"]], ci_paths=["ci/**"])


def test_parse_takes_several_globs_per_option() -> None:
    argv = ["b", "h", "--exam-paths", "x/**", "y", "--bootstrap", "--ci-paths", "z"]
    a = exam_integrity._parse(argv)
    assert (a.base, a.head, a.bootstrap) == ("b", "h", True)
    assert (a.exam_paths, a.ci_paths) == (["x/**", "y"], ["z"])
    assert exam_integrity._parse(["b", "h"]).exam_paths is None
