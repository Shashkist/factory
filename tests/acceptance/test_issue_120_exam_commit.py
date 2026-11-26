"""Issue #120 (item 1 of #109): a recorded exam commit, so a history rewrite cannot move the exam.

Design settled in DECISIONS D43. Names the exam relies on:
  judge CLI:  python -m factory_tools.ci.exam_integrity <base> <head> [--exam-commit SHA] ...
              With --exam-commit the judge also refuses when SHA is not an ancestor of the
              head and when any file that is exam under the current rules (defaults or
              --exam-paths) differs between SHA and the head. A malformed or unknown SHA is
              refused (fail closed). Without it: the per-commit check as before plus one log
              line, `no exam-commit marker: per-commit check only`.
  workflow:   exam-integrity.yml reads the PR comments in a step before the judge and passes
              --exam-commit when a marker was found; an API failure fails the job.
  docs:       docs/ci.md names the `exam-commit:` marker comment and says the manager writes
              it after the exam commit.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml
from helpers import ROOT, workflow_text
from test_issue_1_exam_integrity import CODE, EXAM, Repo, bad, ok

NO_MARKER_LINE = "no exam-commit marker: per-commit check only"
OTHER_CODE = "src/factory_tools/z.py"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def _exam_then_code(repo: Repo) -> str:
    repo.commit({EXAM: "v1\n"}, "exam")
    exam_sha = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    return exam_sha


def _out(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


# 1. plain case and the judge option


def test_plain_exam_commit_then_code_commits_passes_with_exam_commit(repo: Repo) -> None:
    e = _exam_then_code(repo)
    repo.commit({OTHER_CODE: "1\n"}, "more code")
    r = repo.check("--exam-commit", e)
    ok(r)
    assert "unrecognized" not in r.stderr and "usage:" not in r.stderr, r.stderr
    assert NO_MARKER_LINE not in _out(r)


def test_exam_commit_equals_form_is_accepted(repo: Repo) -> None:
    e = _exam_then_code(repo)
    ok(repo.check(f"--exam-commit={e}"))


def test_exam_commit_may_be_a_later_exam_only_commit_when_the_exam_is_unchanged_after_it(
    repo: Repo,
) -> None:
    repo.commit({EXAM: "v1\n"}, "exam part 1")
    repo.commit({"tests/acceptance/y.py": "1\n"}, "exam part 2")
    e = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check("--exam-commit", e))


# 2. a rewrite that changes the exam after the recorded commit is refused


def test_exam_only_commit_editing_the_exam_after_the_exam_commit_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({EXAM: "v2 weaker\n"}, "fixup of the exam")  # per-commit check sees no mix
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())  # the per-commit check alone passes: that is the gap
    r = repo.check("--exam-commit", e)
    bad(r)
    out = _out(r)
    assert EXAM in out, out
    assert e in out or e[:7] in out, out


def test_exam_file_deleted_after_the_exam_commit_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n", "tests/acceptance/y.py": "1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.git("rm", "-q", "--", "tests/acceptance/y.py")
    repo.git("commit", "-q", "-m", "drop an exam file")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check("--exam-commit", e)
    bad(r)
    assert "tests/acceptance/y.py" in _out(r)


def test_exam_change_after_code_is_still_refused_with_exam_commit(repo: Repo) -> None:
    e = _exam_then_code(repo)
    repo.commit({EXAM: "v2\n"}, "exam again")
    bad(repo.check("--exam-commit", e))


# 3. the recorded commit must be an ancestor of the head


def test_exam_commit_rewritten_by_a_rebase_is_not_an_ancestor_and_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    old = repo.rev("HEAD")
    repo.git("commit", "-q", "--amend", "-m", "exam, reworded")  # new SHA, same tree
    assert repo.rev("HEAD") != old
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check("--exam-commit", old)
    bad(r)
    assert "ancestor" in _out(r).lower(), _out(r)


def test_exam_commit_on_another_branch_is_not_an_ancestor_and_is_refused(repo: Repo) -> None:
    repo.git("checkout", "-q", "-b", "side")
    repo.commit({"tests/acceptance/side.py": "1\n"}, "side exam")
    side = repo.rev("HEAD")
    repo.git("checkout", "-q", "main")
    _exam_then_code(repo)
    r = repo.check("--exam-commit", side)
    bad(r)
    assert "ancestor" in _out(r).lower(), _out(r)


# 4. a malformed or unknown SHA fails closed


@pytest.mark.parametrize(
    "sha",
    ["zzzz", "not-a-sha", "0" * 40, "deadbeef" * 5, "-1", "HEAD~1x"],
    ids=["short-junk", "words", "all-zero", "unknown-hex", "dash", "bad-rev"],
)
def test_malformed_or_unknown_exam_commit_is_refused(repo: Repo, sha: str) -> None:
    _exam_then_code(repo)
    r = repo.check(f"--exam-commit={sha}")
    bad(r)
    assert "unrecognized" not in r.stderr, r.stderr


def test_empty_exam_commit_is_refused(repo: Repo) -> None:
    _exam_then_code(repo)
    r = repo.check("--exam-commit=")
    bad(r)
    assert "unrecognized" not in r.stderr, r.stderr


# 5. without a marker: the per-commit behaviour plus one log line


def test_without_exam_commit_a_clean_pr_passes_and_logs_the_no_marker_line_once(
    repo: Repo,
) -> None:
    _exam_then_code(repo)
    r = repo.check()
    ok(r)
    assert _out(r).count(NO_MARKER_LINE) == 1, _out(r)


def test_without_exam_commit_a_mixed_commit_is_still_refused(repo: Repo) -> None:
    repo.commit({EXAM: "1\n", CODE: "1\n"}, "both")
    r = repo.check()
    bad(r)
    assert "FAIL:" in r.stdout, r.stdout


def test_without_exam_commit_the_exam_edit_gap_is_not_closed(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    repo.commit({EXAM: "v2\n"}, "exam edit")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


# 6. the differing files are judged with the current exam rules


def test_non_exam_file_changing_after_the_exam_commit_is_fine(repo: Repo) -> None:
    e = _exam_then_code(repo)
    repo.commit({CODE: "2\n", "docs/notes.md": "x\n", "tests/unit/test_a.py": "1\n"}, "code 2")
    ok(repo.check("--exam-commit", e))


def test_pytest_config_after_the_exam_commit_is_refused(repo: Repo) -> None:
    e = _exam_then_code(repo)
    repo.commit({"conftest.py": "x = 1\n"}, "config")  # exam under the default rules
    bad(repo.check("--exam-commit", e))


GLOBS = ["labs/*/tests/acceptance/**"]
NESTED_EXAM = "labs/manager/tests/acceptance/test_issue_9_x.py"
NESTED_CODE = "labs/manager/app/main.py"


def test_exam_paths_exam_commit_plain_case_passes(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({NESTED_CODE: "1\n", "tests/top.py": "1\n"}, "code")
    ok(repo.check("--exam-commit", e, "--exam-paths", *GLOBS))


def test_exam_paths_exam_edit_after_the_exam_commit_is_refused(repo: Repo) -> None:
    repo.commit({NESTED_EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({NESTED_EXAM: "v2\n"}, "exam edit")
    repo.commit({NESTED_CODE: "1\n"}, "code")
    r = repo.check("--exam-commit", e, "--exam-paths", *GLOBS)
    bad(r)
    assert NESTED_EXAM in _out(r)


def test_a_file_that_is_exam_only_under_the_defaults_is_not_judged_with_exam_paths(
    repo: Repo,
) -> None:
    repo.commit({NESTED_EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({NESTED_CODE: "1\n"}, "code")
    # tests/acceptance/x.py is not exam under these globs: it is code and may change after E
    repo.commit({EXAM: "1\n"}, "code under tests/")
    ok(repo.check("--exam-commit", e, "--exam-paths", *GLOBS))


# 7. the workflow


def _wf() -> dict:
    return yaml.safe_load(workflow_text("exam-integrity.yml"))


def _steps() -> list[dict]:
    return _wf()["jobs"]["exam-integrity"]["steps"]


def _judge_index() -> int:
    for i, s in enumerate(_steps()):
        if "exam_integrity" in str(s.get("run", "")):
            return i
    raise AssertionError("no step runs the judge")


def _marker_steps() -> list[tuple[int, dict]]:
    return [
        (i, s)
        for i, s in enumerate(_steps())
        if "exam-commit" in str(s.get("run", "")) and i != _judge_index()
    ]


def test_workflow_permissions_are_read_only_with_pull_requests_read() -> None:
    wf = _wf()
    perms = [wf.get("permissions")] + [j.get("permissions") for j in wf["jobs"].values()]
    perms = [p for p in perms if isinstance(p, dict)]
    assert perms, "permissions must be declared"
    merged: dict = {}
    for p in perms:
        merged.update(p)
    assert merged.get("contents") == "read", merged
    assert merged.get("pull-requests") == "read", merged
    for p in perms:
        assert all(v in ("read", "none") for v in p.values()), p


def test_a_step_before_the_judge_reads_the_pr_comments() -> None:
    steps = _marker_steps()
    assert steps, "no step handles the exam-commit marker"
    i, s = steps[0]
    assert i < _judge_index()
    run = str(s["run"])
    assert "gh api" in run and "--paginate" in run, run
    assert "comments" in run, run
    assert "exam-commit:" in run, run


def test_the_judge_invocation_passes_exam_commit_when_a_marker_was_found() -> None:
    judge = str(_steps()[_judge_index()]["run"])
    assert "--exam-commit" in judge, judge


def test_the_marker_step_hands_its_result_to_the_judge_step() -> None:
    i, s = _marker_steps()[0]
    text = str(s["run"])
    assert "GITHUB_ENV" in text or "GITHUB_OUTPUT" in text, text
    judge_step = _steps()[_judge_index()]
    assert "steps." in yaml.safe_dump(judge_step.get("env", {})) or "EXAM_COMMIT" in str(
        judge_step
    ), judge_step


def test_the_marker_step_fails_the_job_when_the_api_call_fails() -> None:
    i, s = _marker_steps()[0]
    run = str(s["run"])
    assert s.get("continue-on-error") in (None, False), "an API failure must not be swallowed"
    assert "|| true" not in run and "|| :" not in run, run
    assert re.search(r"set -[a-z]*e|pipefail|\bif ! |\|\| *(exit|\{)|\$\?", run), run


def test_the_marker_step_has_a_token_for_the_api_call() -> None:
    i, s = _marker_steps()[0]
    env = yaml.safe_dump(s.get("env", {}))
    assert "GH_TOKEN" in env or "GITHUB_TOKEN" in env, s
    assert "github.token" in env or "secrets.GITHUB_TOKEN" in env, env


# 8. docs


def _ci_doc() -> str:
    return (ROOT / "docs" / "ci.md").read_text(encoding="utf-8")


def test_docs_name_the_exam_commit_marker() -> None:
    assert "exam-commit:" in _ci_doc()


def test_docs_say_the_manager_writes_the_marker_as_a_pr_comment_after_the_exam_commit() -> None:
    doc = _ci_doc()
    assert re.search(r"manager[^\n]*comment|comment[^\n]*manager", doc, re.I), "manager + comment"
    assert re.search(r"exam commit", doc, re.I)


def test_docs_name_the_extra_permission_callers_must_grant() -> None:
    assert "pull-requests: read" in _ci_doc()
