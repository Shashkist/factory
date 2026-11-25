"""Issue #65: exam and CI-surface paths as inputs, for clients with nested layouts.

Names the implementer follows (chosen here, the issue does not fix them):
  judge CLI:  python -m factory_tools.ci.exam_integrity <base> <head>
                  [--bootstrap] [--exam-paths GLOB [GLOB ...]] [--ci-paths GLOB [GLOB ...]]
              Each option takes one or more globs (fnmatch style, `*` and `**` match
              across `/`). Both are optional; the defaults are today's values
              (exam = top-level tests/ except tests/unit, CI surface =
              src/factory_tools/ci/ and .github/workflows/ci.yml). Positionals come
              first in these cases.
  workflow:   exam-integrity.yml `workflow_call` inputs `exam-paths` and `ci-paths`
              (type string, described), handed to the judge through `env:`.
When --exam-paths is given it names the exam files (the tests/unit and pytest
configuration rules of the defaults are not exercised here).
"""

import subprocess
from pathlib import Path

import pytest
import yaml
from helpers import workflow_text
from test_issue_1_exam_integrity import Repo, bad, ok

NESTED_EXAM = "labs/manager/tests/acceptance/test_issue_9_x.py"
NESTED_CODE = "labs/manager/app/main.py"
NESTED_GLOBS = ["labs/*/tests/acceptance/**"]
CALLER_WF = ".github/workflows/lf-ci.yml"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def nested(repo: Repo, *extra: str) -> subprocess.CompletedProcess[str]:
    return repo.check(*extra, "--exam-paths", *NESTED_GLOBS)


# 1. the judge takes the globs as CLI options


def test_nested_exam_and_code_in_one_commit_is_refused_with_exam_paths(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n", NESTED_CODE: "1\n"}, "both")
    r = nested(repo)
    bad(r)
    assert "unrecognized" not in r.stderr and "usage:" not in r.stderr, r.stderr


def test_nested_exam_after_a_code_commit_is_refused_with_exam_paths(repo: Repo) -> None:
    repo.commit({NESTED_CODE: "1\n"}, "code")
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    bad(nested(repo))


def test_nested_exam_first_then_code_passes_with_exam_paths(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    repo.commit({NESTED_CODE: "1\n"}, "code")
    ok(nested(repo))


def test_several_exam_globs_are_all_honoured(repo: Repo) -> None:
    repo.commit({"e2e/spec_a.py": "1\n", NESTED_CODE: "1\n"}, "both")
    bad(repo.check("--exam-paths", "labs/*/tests/acceptance/**", "e2e/**"))


def test_exam_paths_option_does_not_make_unrelated_files_exam(repo: Repo) -> None:
    repo.commit({"labs/manager/tests/unit/test_a.py": "1\n", NESTED_CODE: "1\n"}, "both")
    ok(nested(repo))


def test_nested_layout_passes_with_the_defaults_today_gap_documented(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n", NESTED_CODE: "1\n"}, "both")
    ok(repo.check())


# CI-surface globs


def test_caller_workflow_named_in_ci_paths_is_ci_surface(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    repo.commit({CALLER_WF: "1\n"}, "caller workflow")
    bad(nested(repo, "--ci-paths", CALLER_WF))


def test_caller_workflow_is_plain_code_without_ci_paths(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    repo.commit({CALLER_WF: "1\n"}, "caller workflow")
    ok(nested(repo))


def test_ci_paths_surface_is_waived_by_bootstrap(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    repo.commit({CALLER_WF: "1\n"}, "caller workflow")
    ok(nested(repo, "--bootstrap", "--ci-paths", CALLER_WF))


def test_ci_paths_accepts_several_globs(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "1\n"}, "exam")
    repo.commit({"ci/run.sh": "1\n"}, "script")
    bad(nested(repo, "--ci-paths", CALLER_WF, "ci/**"))


# defaults keep today's behaviour


def test_defaults_top_level_tests_are_exam(repo: Repo) -> None:
    repo.commit({"tests/acceptance/x.py": "1\n", "src/factory_tools/y.py": "1\n"}, "both")
    bad(repo.check())


def test_defaults_tests_unit_is_not_exam(repo: Repo) -> None:
    repo.commit({"tests/unit/test_y.py": "1\n", "src/factory_tools/y.py": "1\n"}, "both")
    ok(repo.check())


@pytest.mark.parametrize("surface", ["src/factory_tools/ci/gate.py", ".github/workflows/ci.yml"])
def test_defaults_ci_surface_with_exam_is_refused(repo: Repo, surface: str) -> None:
    repo.commit({"tests/acceptance/x.py": "1\n"}, "exam")
    repo.commit({surface: "1\n"}, "ci")
    bad(repo.check())


def test_defaults_do_not_treat_a_caller_workflow_as_ci_surface(repo: Repo) -> None:
    repo.commit({"tests/acceptance/x.py": "1\n"}, "exam")
    repo.commit({CALLER_WF: "1\n"}, "caller workflow")
    ok(repo.check())


# 2. the reusable workflow


def _wf() -> dict:
    return yaml.safe_load(workflow_text("exam-integrity.yml"))


def _inputs() -> dict:
    wf = _wf()
    on = wf.get("on", wf.get(True))
    return on["workflow_call"]["inputs"]


@pytest.mark.parametrize("name", ["exam-paths", "ci-paths"])
def test_workflow_declares_the_input_with_a_description(name: str) -> None:
    spec = _inputs()[name]
    assert str(spec.get("description", "")).strip(), f"{name} needs a description"
    assert spec.get("type") == "string"
    assert spec.get("required") is not True


def _judge_step() -> dict:
    steps = _wf()["jobs"]["exam-integrity"]["steps"]
    return next(s for s in steps if "exam_integrity.py" in s.get("run", ""))


@pytest.mark.parametrize("name", ["exam-paths", "ci-paths"])
def test_workflow_passes_the_input_through_env_not_into_the_script(name: str) -> None:
    step = _judge_step()
    assert "inputs." + name not in step["run"], "never interpolate inputs into run:"
    assert "${{" not in step["run"]
    holders = [k for k, v in step.get("env", {}).items() if f"inputs.{name}" in str(v)]
    assert holders, f"env: must carry inputs.{name}"
    assert any(f"${h}" in step["run"] or "${" + h in step["run"] for h in holders)


def test_workflow_hands_both_options_to_the_judge() -> None:
    run = _judge_step()["run"]
    assert "--exam-paths" in run and "--ci-paths" in run
