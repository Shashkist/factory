"""Issue #109, items 2 and 3: every workflow is CI surface; pytest config in pyproject.toml is exam.

Item 1 (the pinned exam commit) is not part of this file.

Contract readings (the issue leaves these open; this file fixes them):
  Item 2
  - The CI surface is every path under `.github/workflows/` at the repository root, any
    file name, `.yml` and `.yaml` alike (the issue's glob `.github/workflows/**`). A
    nested path such as `.github/workflows/sub/x.yml` is also surface (the `**` reading);
    GitHub does not load it, but the conservative rule is the one the issue names.
  - The rule is anchored at the repository root: `docs/.github/workflows/x.yml` and
    `.github/workflowsx/x.yml` are plain code.
  - A PR that changes the exam (in any commit) and a workflow (in any commit) is refused
    with the existing reason "PR changes the exam together with the CI surface". A
    workflow change alone, or with code only, passes as before.
  - `--ci-paths` keeps replacing the default rule (D34): with it, `other.yml` is surface
    only when the given globs name it, and `--bootstrap` still waives the rule.
  Item 3
  - A `pyproject.toml` (the file name exactly, at any depth) is exam when the parsed
    `tool.pytest` table (the `ini_options` form and pytest 9's native form, for example
    `[tool.pytest]` with `addopts = ["-k", "not exam"]`) differs between the commit's
    parent and the commit (changed, added or removed; a file that is new in the commit
    counts as added when it has the table). A pyproject whose pytest table is the same
    (a `[tool.ruff]` edit, dependencies, comments elsewhere) is code as today.
    `pyproject.toml.bak` is code.
  - Being exam, it follows the exam rules: with code in one commit it is refused with
    "changes the exam and code together"; committed alone before code it passes;
    committed after code it is refused. Like conftest.py it stays exam under
    `--exam-paths`.
  - `pytest.toml` and `.pytest.toml` (pytest's own config files) are exam like
    `pytest.ini`, at any depth outside tests/unit/, also under `--exam-paths`.
  - A PR whose commits change a pytest table in pyproject.toml and a workflow (in any
    order) is refused with the CI-surface reason: the table change is exam.
"""

import subprocess
from pathlib import Path

import pytest
from test_issue_1_exam_integrity import Repo, bad, ok

CI_REASON = "PR changes the exam together with the CI surface"
TOGETHER = "changes the exam and code together"
EXAM = "tests/acceptance/test_a.py"
CODE = "src/app/main.py"

# The judge's modes: the defaults, and --exam-paths alone (no --ci-paths): the workflow
# default must still apply when only the exam paths are given (D41 amendment 1).
MODES = [(), ("--exam-paths", "tests/acceptance/**")]
MODE_IDS = ["defaults", "exam-paths-alone"]

PYPROJECT = "pyproject.toml"
NESTED_PYPROJECT = "labs/manager/pyproject.toml"
NO_TABLE = "labs/other/pyproject.toml"


def pp(addopts: str | None = "-q", ruff: str = "100", deps: str = "a", name: str = "x") -> str:
    out = f'[project]\nname = "{name}"\nversion = "0"\ndependencies = ["{deps}"]\n\n'
    out += f"[tool.ruff]\nline-length = {ruff}\n"
    if addopts is not None:
        out += f'\n[tool.pytest.ini_options]\naddopts = "{addopts}"\n'
    return out


def pn(addopts: str = '["-q"]') -> str:
    """A pyproject with the native pytest 9 table and no ini_options table."""
    out = '[project]\nname = "x"\nversion = "0"\ndependencies = ["a"]\n\n'
    return out + f"[tool.ruff]\nline-length = 100\n\n[tool.pytest]\naddopts = {addopts}\n"


NATIVE_SKIP = '["-k", "not exam"]'
CI_YML = ".github/workflows/ci.yml"
TOML = '[pytest]\naddopts = ["-k", "not exam"]\n'


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path / "r")
    r.commit({PYPROJECT: pp(), NESTED_PYPROJECT: pp()}, "pyprojects with a pytest table")
    r.commit({NO_TABLE: pp(None)}, "pyproject without a pytest table")
    r.base = r.rev("HEAD")
    return r


def refused(r: subprocess.CompletedProcess[str], reason: str) -> None:
    bad(r)
    assert "FAIL:" in r.stdout and reason in r.stdout, r.stdout


# Item 2: workflows


@pytest.mark.parametrize(
    "wf",
    [
        ".github/workflows/other.yml",
        ".github/workflows/other.yaml",
        ".github/workflows/deploy-prod.yml",
        ".github/workflows/sub/nested.yml",
    ],
    ids=["other-yml", "other-yaml", "dashed-name", "nested-path"],
)
@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_workflow_changed_together_with_an_exam_file_is_refused(
    repo: Repo, wf: str, mode: tuple[str, ...]
) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({wf: "on: push\n"}, "workflow")
    refused(repo.check(*mode), CI_REASON)


def test_workflow_and_exam_in_one_commit_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "1\n", ".github/workflows/other.yml": "on: push\n"}, "both")
    refused(repo.check(), CI_REASON)


def test_workflow_first_then_exam_is_refused(repo: Repo) -> None:
    repo.commit({".github/workflows/other.yaml": "on: push\n"}, "workflow")
    repo.commit({EXAM: "1\n"}, "exam")
    refused(repo.check(), CI_REASON)


def test_modified_existing_workflow_with_exam_is_refused(repo: Repo) -> None:
    wf = ".github/workflows/release.yml"
    repo.commit({wf: "on: push\n"}, "add workflow")
    repo.base = repo.rev("HEAD")
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({wf: "on: pull_request\n"}, "edit workflow")
    refused(repo.check(), CI_REASON)


def test_workflow_change_alone_passes(repo: Repo) -> None:
    repo.commit({".github/workflows/other.yml": "on: push\n"}, "workflow")
    ok(repo.check())


@pytest.mark.parametrize("together", [True, False], ids=["same-commit", "separate-commits"])
def test_workflow_change_with_code_only_passes(repo: Repo, together: bool) -> None:
    wf = ".github/workflows/other.yml"
    if together:
        repo.commit({wf: "on: push\n", CODE: "1\n"}, "workflow and code")
    else:
        repo.commit({wf: "on: push\n"}, "workflow")
        repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_ci_yml_with_exam_is_still_refused(repo: Repo) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({".github/workflows/ci.yml": "on: push\n"}, "ci")
    refused(repo.check(), CI_REASON)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflowsx/other.yml",
        "docs/.github/workflows/x.yml",
        ".github/workflow/other.yml",
        ".github/actions/setup/action.yml",
    ],
    ids=["workflowsx", "not-at-root", "singular-dir", "actions-dir"],
)
def test_near_miss_paths_are_not_ci_surface(repo: Repo, path: str) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({path: "x: 1\n"}, "near miss")
    ok(repo.check())


def test_custom_ci_paths_replace_the_default_workflow_rule(repo: Repo) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({".github/workflows/other.yml": "on: push\n"}, "workflow")
    ok(repo.check("--ci-paths", "scripts/ci/**"))


def test_custom_ci_paths_naming_the_workflow_still_refuse(repo: Repo) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({".github/workflows/other.yml": "on: push\n"}, "workflow")
    refused(repo.check("--ci-paths", ".github/workflows/other.yml"), CI_REASON)


def test_bootstrap_still_waives_the_workflow_rule(repo: Repo) -> None:
    repo.commit({EXAM: "1\n"}, "exam")
    repo.commit({".github/workflows/other.yml": "on: push\n"}, "workflow")
    ok(repo.check("--bootstrap"))


# Item 3: pyproject.toml


@pytest.mark.parametrize("path", [PYPROJECT, NESTED_PYPROJECT], ids=["root", "nested"])
def test_pytest_table_changed_with_code_in_one_commit_is_refused(repo: Repo, path: str) -> None:
    repo.commit({path: pp("-q --maxfail=1"), CODE: "1\n"}, "pytest config and code")
    refused(repo.check(), TOGETHER)


def test_pytest_table_added_with_code_is_refused(repo: Repo) -> None:
    repo.commit({NO_TABLE: pp("-q"), CODE: "1\n"}, "add pytest table and code")
    refused(repo.check(), TOGETHER)


def test_pytest_table_removed_with_code_is_refused(repo: Repo) -> None:
    repo.commit({PYPROJECT: pp(None), CODE: "1\n"}, "drop pytest table and code")
    refused(repo.check(), TOGETHER)


def test_new_pyproject_with_pytest_table_and_code_is_refused(repo: Repo) -> None:
    repo.commit({"labs/new/pyproject.toml": pp("-q"), CODE: "1\n"}, "new project and code")
    refused(repo.check(), TOGETHER)


def test_pytest_table_changed_with_code_is_refused_with_exam_paths(repo: Repo) -> None:
    repo.commit({PYPROJECT: pp("-q -x"), CODE: "1\n"}, "pytest config and code")
    refused(repo.check("--exam-paths", "tests/acceptance/**"), TOGETHER)


def test_pytest_table_changed_alone_before_code_passes(repo: Repo) -> None:
    repo.commit({PYPROJECT: pp("-q --maxfail=1")}, "pytest config")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_pytest_table_changed_after_code_is_refused(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({PYPROJECT: pp("-q --maxfail=1")}, "pytest config")
    refused(repo.check(), "after code was added")


def test_pytest_table_change_with_an_exam_file_in_one_commit_passes(repo: Repo) -> None:
    repo.commit({PYPROJECT: pp("-q -x"), EXAM: "1\n"}, "exam and pytest config")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


@pytest.mark.parametrize(
    "content",
    [pp(ruff="120"), pp(deps="b"), pp(name="y")],
    ids=["ruff-only", "dependencies-only", "project-name-only"],
)
def test_pyproject_change_outside_the_pytest_table_is_code(repo: Repo, content: str) -> None:
    repo.commit({PYPROJECT: content, CODE: "1\n"}, "pyproject and code")
    ok(repo.check())


def test_pyproject_change_outside_the_pytest_table_stays_code_after_code(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({PYPROJECT: pp(ruff="120")}, "ruff")
    ok(repo.check())


def test_pyproject_without_a_pytest_table_changed_with_code_is_code(repo: Repo) -> None:
    repo.commit({NO_TABLE: pp(None, ruff="90"), CODE: "1\n"}, "ruff and code")
    ok(repo.check())


def test_pyproject_bak_with_pytest_table_is_code(repo: Repo) -> None:
    repo.commit({"pyproject.toml.bak": pp("-q -x"), CODE: "1\n"}, "backup and code")
    ok(repo.check())


def test_other_toml_file_with_pytest_table_is_code(repo: Repo) -> None:
    repo.commit({"my-pyproject.toml": pp("-q -x"), CODE: "1\n"}, "other toml and code")
    ok(repo.check())


# Native [tool.pytest] table (pytest 9), pytest.toml and .pytest.toml


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("path", [PYPROJECT, NESTED_PYPROJECT], ids=["root", "nested"])
def test_native_pytest_table_replacing_ini_options_with_code_is_refused(
    repo: Repo, path: str, mode: tuple[str, ...]
) -> None:
    repo.commit({path: pn(NATIVE_SKIP), CODE: "1\n"}, "native pytest config and code")
    refused(repo.check(*mode), TOGETHER)


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_native_pytest_table_added_with_code_is_refused(repo: Repo, mode: tuple[str, ...]) -> None:
    repo.commit({NO_TABLE: pn(NATIVE_SKIP), CODE: "1\n"}, "add native table and code")
    refused(repo.check(*mode), TOGETHER)


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_native_pytest_table_edited_with_code_is_refused(
    repo: Repo, mode: tuple[str, ...]
) -> None:
    repo.commit({PYPROJECT: pn()}, "native table")
    repo.base = repo.rev("HEAD")
    repo.commit({PYPROJECT: pn(NATIVE_SKIP), CODE: "1\n"}, "edit native table and code")
    refused(repo.check(*mode), TOGETHER)


def test_native_pytest_table_removed_with_code_is_refused(repo: Repo) -> None:
    repo.commit({PYPROJECT: pn()}, "native table")
    repo.base = repo.rev("HEAD")
    repo.commit({PYPROJECT: pp(None), CODE: "1\n"}, "drop native table and code")
    refused(repo.check(), TOGETHER)


def test_native_pytest_table_alone_before_code_passes(repo: Repo) -> None:
    repo.commit({PYPROJECT: pn(NATIVE_SKIP)}, "native pytest config")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_native_pytest_table_after_code_is_refused(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({PYPROJECT: pn(NATIVE_SKIP)}, "native pytest config")
    refused(repo.check(), "after code was added")


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize(
    "path",
    ["pytest.toml", ".pytest.toml", "labs/manager/pytest.toml", "labs/manager/.pytest.toml"],
    ids=["pytest-toml", "dot-pytest-toml", "nested-pytest-toml", "nested-dot-pytest-toml"],
)
def test_pytest_toml_added_with_code_is_refused(
    repo: Repo, path: str, mode: tuple[str, ...]
) -> None:
    repo.commit({path: TOML, CODE: "1\n"}, "pytest toml and code")
    refused(repo.check(*mode), TOGETHER)


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_both_pytest_toml_files_added_with_code_are_refused(
    repo: Repo, mode: tuple[str, ...]
) -> None:
    repo.commit({"pytest.toml": TOML, ".pytest.toml": TOML, CODE: "1\n"}, "both tomls and code")
    refused(repo.check(*mode), TOGETHER)


def test_pytest_toml_files_alone_before_code_pass(repo: Repo) -> None:
    repo.commit({"pytest.toml": TOML, ".pytest.toml": TOML}, "pytest config")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_pytest_toml_after_code_is_refused(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({"pytest.toml": TOML}, "pytest config")
    refused(repo.check(), "after code was added")


# A pytest-table change followed by a workflow change


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_pytest_table_change_then_workflow_change_is_refused_as_ci_surface(
    repo: Repo, mode: tuple[str, ...]
) -> None:
    repo.commit({PYPROJECT: pp("-q --maxfail=1")}, "pytest config")
    repo.commit({CI_YML: "on: push\n"}, "ci workflow")
    refused(repo.check(*mode), CI_REASON)


def test_native_pytest_table_change_then_workflow_change_is_refused_as_ci_surface(
    repo: Repo,
) -> None:
    repo.commit({PYPROJECT: pn(NATIVE_SKIP)}, "native pytest config")
    repo.commit({CI_YML: "on: push\n"}, "ci workflow")
    refused(repo.check(), CI_REASON)


def test_workflow_change_then_pytest_table_change_is_refused_as_ci_surface(repo: Repo) -> None:
    repo.commit({CI_YML: "on: push\n"}, "ci workflow")
    repo.commit({PYPROJECT: pp("-q --maxfail=1")}, "pytest config")
    refused(repo.check(), CI_REASON)


def test_pyproject_change_outside_the_pytest_table_then_workflow_change_passes(
    repo: Repo,
) -> None:
    repo.commit({PYPROJECT: pp(ruff="120")}, "ruff")
    repo.commit({CI_YML: "on: push\n"}, "ci workflow")
    ok(repo.check())
