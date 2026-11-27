"""Issue #120, review round 1 of PR #128: the rules the first exam left to unit tests.

Pins, through the judge CLI, the marker module and the workflow text:
  1. D43 amendment 2, the marker chain: a later marker supersedes an earlier one only with the
     same exam; the newest marker is the one judged and must be an ancestor of the head.
  2. python -m factory_tools.ci.exam_marker (JSON lines on stdin): trusted authors only, an
     edited trusted marker fails the run, bad format ignored, a trailing CR accepted, the
     counted SHAs printed oldest first. The workflow's marker step pipes through that module.
  3. The workflow loops over $EXAM_COMMITS into --exam-commit=, and the marker step runs with
     set -e and pipefail, so a failed API call fails the job.
  4. A pyproject.toml pytest-table change after the recorded exam commit is refused.
  5. Strict 40-hex: a prefix, upper-case hex and a ref name are refused.
  6. D45: an earlier marker commit missing from the checkout is fetched by SHA (an origin made
     with git clone --no-local, never the network); not fetchable fails closed.
  7. The token is `github.token` only (D43 amendment 1).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from helpers import ROOT, env, run_module, workflow_text
from test_issue_1_exam_integrity import CODE, EXAM, GIT_ENV, MOD, Repo, bad, ok

MARKER_MOD = "factory_tools.ci.exam_marker"
PYPROJECT = "pyproject.toml"
TOML_BASE = '[project]\nname = "x"\nversion = "1"\n[tool.pytest.ini_options]\naddopts = "-q"\n'


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "r")


def _out(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


def _amend(repo: Repo, msg: str) -> str:
    """A rebase in effect: the same tree under a new SHA."""
    old = repo.rev("HEAD")
    repo.git("commit", "-q", "--amend", "-m", msg)
    new = repo.rev("HEAD")
    assert new != old
    return new


def _chain(*shas: str) -> list[str]:
    args: list[str] = []
    for sha in shas:
        args += ["--exam-commit", sha]
    return args


# 1. two markers (D43 amendment 2)


def test_two_markers_same_exam_on_a_new_sha_pass_and_the_newest_is_used(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    e2 = _amend(repo, "exam, rebased")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check(*_chain(e1, e2))
    ok(r)
    out = _out(r)
    assert e1 in out and e2 in out, out  # every marker seen is logged
    used = [ln for ln in out.splitlines() if "used" in ln]
    assert any(e2 in ln for ln in used), out
    assert not any(e1 in ln for ln in used), out


def test_two_markers_the_oldest_alone_is_refused_so_the_newest_is_the_one_judged(
    repo: Repo,
) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    e2 = _amend(repo, "exam, rebased")
    repo.commit({CODE: "1\n"}, "code")
    bad(repo.check("--exam-commit", e1))  # e1 is no ancestor of the head
    ok(repo.check("--exam-commit", e2))


def test_a_later_marker_with_a_different_exam_is_refused_naming_both_shas(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    repo.commit({EXAM: "v2 weaker\n"}, "exam moved")
    e2 = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check("--exam-commit", e2))  # on its own the later marker is consistent
    r = repo.check(*_chain(e1, e2))
    bad(r)
    out = _out(r)
    assert e1 in out and e2 in out, out
    assert EXAM in out, out


def test_a_later_marker_that_adds_an_exam_file_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    repo.commit({"tests/acceptance/more.py": "1\n"}, "more exam")
    e2 = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check(*_chain(e1, e2))
    bad(r)
    assert "tests/acceptance/more.py" in _out(r)


def test_a_later_marker_that_differs_only_outside_the_exam_is_fine(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    repo.commit({"docs/notes.md": "x\n"}, "notes")
    e2 = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check(*_chain(e1, e2)))


def test_the_newest_marker_not_an_ancestor_of_the_head_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    e2 = _amend(repo, "exam, rebased")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check(*_chain(e1, e2)))  # control: the order e1, e2 is the passing one
    r = repo.check(*_chain(e2, e1))  # same exam, but the newest (e1) is not an ancestor
    bad(r)
    assert "ancestor" in _out(r).lower(), _out(r)


def test_three_markers_the_newest_decides(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    e2 = _amend(repo, "exam, rebased once")
    e3 = _amend(repo, "exam, rebased twice")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check(*_chain(e1, e2, e3))
    ok(r)
    assert any("used" in ln and e3 in ln for ln in _out(r).splitlines()), _out(r)
    bad(repo.check(*_chain(e1, e3, e2)))


def test_the_exam_cannot_move_between_two_markers_even_when_the_head_equals_the_later_one(
    repo: Repo,
) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    repo.commit({EXAM: "v2\n"}, "exam v2")
    e2 = repo.rev("HEAD")
    bad(repo.check(*_chain(e1, e2)))


# 2. the marker module, fed JSON lines on stdin

A, B, C = "a" * 40, "b" * 40, "c" * 40


def _c(
    cid: int,
    sha: str = A,
    assoc: str = "OWNER",
    first: str | None = None,
    edited: bool = False,
) -> dict:
    return {
        "id": cid,
        "author_association": assoc,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z" if edited else "2026-01-01T00:00:00Z",
        "first": f"exam-commit: {sha}" if first is None else first,
    }


def _marker_text(text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", MARKER_MOD],
        input=text,
        cwd=ROOT,
        env=env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _marker(comments: list[dict]) -> subprocess.CompletedProcess[str]:
    return _marker_text("".join(json.dumps(c) + "\n" for c in comments))


def _shas(r: subprocess.CompletedProcess[str]) -> list[str]:
    return r.stdout.split()


def test_marker_module_no_comments_prints_nothing_and_succeeds() -> None:
    r = _marker([])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [], r.stdout


@pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_marker_module_counts_a_marker_of_a_trusted_author(assoc: str) -> None:
    r = _marker([_c(1, A, assoc)])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [A], _out(r)


@pytest.mark.parametrize(
    "assoc", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "FIRST_TIME_CONTRIBUTOR", "MANNEQUIN", ""]
)
def test_marker_module_ignores_a_marker_of_an_untrusted_author(assoc: str) -> None:
    r = _marker([_c(1, B, assoc), _c(2, A, "OWNER")])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [A], _out(r)  # only the trusted one; the other is not printed
    assert r.stderr.strip(), "an ignored marker leaves a log line on stderr"


def test_marker_module_ignores_an_edited_marker_of_an_untrusted_author() -> None:
    r = _marker([_c(1, B, "NONE", edited=True), _c(2, A)])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [A], _out(r)


def test_marker_module_an_edited_trusted_marker_fails_the_run() -> None:
    r = _marker([_c(1, A, edited=True)])
    assert r.returncode == 1, _out(r)
    assert _shas(r) == [], r.stdout  # nothing is handed to the judge
    assert "FAIL" in r.stderr and "edited" in r.stderr, r.stderr


def test_marker_module_an_edited_trusted_marker_fails_even_among_good_ones() -> None:
    r = _marker([_c(1, A), _c(2, B, edited=True), _c(3, C)])
    assert r.returncode == 1, _out(r)
    assert _shas(r) == [], r.stdout


@pytest.mark.parametrize(
    "first",
    [
        "exam-commit:",
        "exam-commit: ",
        f"exam-commit: {A[:39]}",
        f"exam-commit: {A[:12]}",
        f"exam-commit: {'A' * 40}",
        f"exam-commit: {A} (exam)",
        f"exam-commit: {A} ",
        f"exam-commit:{A}",
        f"exam-commit:  {A}",
        f"exam-commit: {A}\r\r",
        f"exam-commit: {'g' * 40}",
        "exam-commit: HEAD",
    ],
)
def test_marker_module_ignores_a_trusted_marker_with_a_bad_format(first: str) -> None:
    r = _marker([_c(1, first=first), _c(2, B)])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [B], _out(r)
    assert "Traceback" not in r.stderr, r.stderr


def test_marker_module_accepts_a_trailing_carriage_return() -> None:
    r = _marker([_c(1, first=f"exam-commit: {A}\r")])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [A], _out(r)


def test_marker_module_prints_several_markers_oldest_first_in_comment_order() -> None:
    r = _marker([_c(10, C), _c(11, B, "NONE"), _c(12, A), _c(13, B)])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [C, A, B], _out(r)  # not sorted, not reversed


def test_marker_module_keeps_a_repeated_sha_in_the_chain() -> None:
    r = _marker([_c(1, A), _c(2, A)])
    assert r.returncode == 0, _out(r)
    assert _shas(r) == [A, A], _out(r)


def test_marker_module_rejects_input_that_is_not_json_instead_of_printing_a_sha() -> None:
    r = _marker_text("not json\n")
    assert r.returncode != 0, _out(r)
    assert r.stdout.strip() == "", r.stdout


# workflow helpers


def _wf() -> dict:
    return yaml.safe_load(workflow_text("exam-integrity.yml"))


def _steps() -> list[dict]:
    return _wf()["jobs"]["exam-integrity"]["steps"]


def _judge() -> dict:
    found = [s for s in _steps() if "exam_integrity" in str(s.get("run", ""))]
    assert len(found) == 1, found
    return found[0]


def _marker_step() -> dict:
    found = [
        s
        for s in _steps()
        if "gh api" in str(s.get("run", "")) and "comments" in str(s.get("run", ""))
    ]
    assert len(found) == 1, found
    return found[0]


def test_workflow_marker_step_pipes_the_api_output_through_the_marker_module() -> None:
    run = str(_marker_step()["run"])
    # gh api ... | python3 -I .factory-tools/.../exam_marker.py  (the pinned judge checkout)
    assert re.search(r"\|\s*\S*python3?\s+(?:-\S+\s+)*\.factory-tools/\S*exam_marker\.py", run), run
    assert run.index("gh api") < run.index("exam_marker"), run


def test_workflow_marker_step_hands_the_module_output_to_the_judge_step_as_exam_commits() -> None:
    run = str(_marker_step()["run"])
    assert re.search(r"EXAM_COMMITS=.*>>\s*\"?\$GITHUB_ENV", run), run
    assert "$markers" in run or "${markers}" in run, run  # what the module printed


# 3. the workflow wiring


def test_workflow_judge_step_loops_over_exam_commits_into_exam_commit_flags() -> None:
    run = str(_judge()["run"])
    m = re.search(r"for\s+(\w+)\s+in\s+\$\{?EXAM_COMMITS\}?\s*;\s*do(.*?)\bdone", run, re.S)
    assert m, f"no loop over $EXAM_COMMITS in the judge step:\n{run}"
    var, body = m.group(1), m.group(2)
    add = re.search(r"(\w+)\+=\(\s*\"--exam-commit=\$\{?" + var + r"\}?\"\s*\)", body)
    assert add, f"the loop must add --exam-commit=<each marker>:\n{body}"
    # the collected array reaches the judge command line
    judge_line = next(ln for ln in run.splitlines() if "exam_integrity" in ln)
    assert "${" + add.group(1) + "[@]}" in judge_line, judge_line


def test_workflow_judge_step_does_not_overwrite_exam_commits_from_its_own_env() -> None:
    step = _judge()
    assert "EXAM_COMMITS" not in (step.get("env") or {}), step.get("env")


def test_workflow_marker_step_runs_under_set_e_and_pipefail() -> None:
    run = str(_marker_step()["run"])
    m = re.search(r"(?m)^\s*set\s+(?:-[a-z]*e[a-z]*|-o\s+errexit)\b[^\n]*", run)
    assert m, f"set -e (not pipefail alone) is missing:\n{run}"
    assert "pipefail" in run, run  # a failed gh api in the pipe must fail the step
    assert m.start() < run.index("gh api"), "set -e must come before the API call"
    assert "set +e" not in run, run


def test_workflow_marker_step_runs_before_the_judge() -> None:
    steps = _steps()
    assert steps.index(_marker_step()) < steps.index(_judge())


# 4. pyproject.toml pytest table after the recorded exam commit


def _exam_with_pyproject(repo: Repo) -> str:
    repo.commit({EXAM: "v1\n", PYPROJECT: TOML_BASE}, "exam")
    return repo.rev("HEAD")


@pytest.mark.parametrize(
    "new",
    [
        TOML_BASE.replace('"-q"', '"-q -k nothing"'),
        '[project]\nname = "x"\nversion = "1"\n',
        TOML_BASE + '[tool.pytest]\naddopts = ["-p", "no:cacheprovider"]\n',
    ],
    ids=["table-changed", "table-removed", "native-table-added"],
)
def test_pyproject_pytest_table_change_after_the_exam_commit_is_refused(
    repo: Repo, new: str
) -> None:
    e = _exam_with_pyproject(repo)
    repo.commit({PYPROJECT: new}, "pytest config")  # an exam-only commit: the per-commit check
    repo.commit({CODE: "1\n"}, "code")  # sees no mix and no exam after code
    ok(repo.check())
    r = repo.check("--exam-commit", e)
    bad(r)
    assert PYPROJECT in _out(r), _out(r)


def test_pyproject_change_outside_the_pytest_table_after_the_exam_commit_is_fine(
    repo: Repo,
) -> None:
    e = _exam_with_pyproject(repo)
    other = TOML_BASE.replace('"1"', '"2"') + "[tool.ruff]\nline-length = 99\n"
    repo.commit({PYPROJECT: other}, "version bump")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check("--exam-commit", e))


def test_pyproject_pytest_table_change_between_two_markers_is_refused(repo: Repo) -> None:
    e1 = _exam_with_pyproject(repo)
    repo.commit({PYPROJECT: TOML_BASE.replace('"-q"', '"-x"')}, "pytest config")
    e2 = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check(*_chain(e1, e2))
    bad(r)
    assert PYPROJECT in _out(r), _out(r)


def test_unparsable_pyproject_after_the_exam_commit_is_refused(repo: Repo) -> None:
    e = _exam_with_pyproject(repo)
    repo.commit({PYPROJECT: "[tool.pytest\nbroken = \n"}, "broken toml")
    repo.commit({CODE: "1\n"}, "code")
    bad(repo.check("--exam-commit", e))


# 5. strict 40-hex


def test_a_12_character_prefix_of_a_real_exam_commit_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check("--exam-commit", e))
    r = repo.check(f"--exam-commit={e[:12]}")
    bad(r)
    assert "40" in _out(r) or "hex" in _out(r).lower(), _out(r)


def test_upper_case_hex_of_a_real_exam_commit_is_refused(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e = repo.rev("HEAD")
    repo.commit({CODE: "1\n"}, "code")
    bad(repo.check(f"--exam-commit={e.upper()}"))


@pytest.mark.parametrize("ref", ["HEAD", "main", "HEAD~0", "refs/heads/main"])
def test_a_ref_name_of_a_real_commit_is_refused(repo: Repo, ref: str) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    repo.commit({CODE: "1\n"}, "code")
    bad(repo.check(f"--exam-commit={ref}"))


def test_a_prefix_upper_case_or_ref_is_refused_as_a_marker_in_a_chain_too(repo: Repo) -> None:
    repo.commit({EXAM: "v1\n"}, "exam")
    e1 = repo.rev("HEAD")
    e2 = _amend(repo, "exam, rebased")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check(*_chain(e1, e2)))
    bad(repo.check(*_chain(e1[:12], e2)))
    bad(repo.check(*_chain(e1, e2.upper())))
    bad(repo.check(*_chain(e1, "HEAD")))


# 6. D45: the earlier marker commit is fetched by SHA from the origin


def _rebased_clone(tmp_path: Path, prune: bool) -> tuple[Path, str, str, str, str]:
    """A clone (git clone --no-local from a path, no network) lacking the pre-rebase exam commit.

    Returns the clone, the base, the earlier marker commit (on no branch of the origin), the
    later one (same exam, new SHA) and the head."""
    origin = Repo(tmp_path / "origin")
    origin.git("config", "uploadpack.allowAnySHA1InWant", "true")
    origin.commit({EXAM: "v1\n"}, "exam")
    e1 = origin.rev("HEAD")
    e2 = _amend(origin, "exam, rebased")
    origin.commit({CODE: "1\n"}, "code")
    head = origin.rev("HEAD")
    if prune:
        origin.git("reflog", "expire", "--expire=now", "--all")
        origin.git("gc", "-q", "--prune=now")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--no-local", str(origin.path), str(clone)],
        env=env(GIT_ENV),
        check=True,
        capture_output=True,
    )
    missing = subprocess.run(["git", "cat-file", "-e", f"{e1}^{{commit}}"], cwd=clone)
    assert missing.returncode != 0, "the earlier marker commit must be absent from the clone"
    return clone, origin.base, e1, e2, head


def _judge_in(clone: Path, base: str, head: str, *chain: str) -> subprocess.CompletedProcess[str]:
    return run_module(MOD, base, head, *_chain(*chain), cwd=clone)


def test_an_earlier_marker_commit_missing_from_the_checkout_is_fetched_by_sha(
    tmp_path: Path,
) -> None:
    clone, base, e1, e2, head = _rebased_clone(tmp_path, prune=False)
    r = _judge_in(clone, base, head, e1, e2)
    ok(r)
    assert e1 in _out(r) and e2 in _out(r), _out(r)
    assert any("used" in ln and e2 in ln for ln in _out(r).splitlines()), _out(r)


def test_an_earlier_marker_commit_that_cannot_be_fetched_fails_closed_and_says_what_to_do(
    tmp_path: Path,
) -> None:
    clone, base, e1, e2, head = _rebased_clone(tmp_path, prune=True)
    r = _judge_in(clone, base, head, e1, e2)
    bad(r)
    out = _out(r)
    assert e1 in out, out
    assert "delete" in out.lower() and "marker" in out.lower(), out


def test_a_lone_marker_missing_from_the_checkout_is_refused(tmp_path: Path) -> None:
    clone, base, e1, e2, head = _rebased_clone(tmp_path, prune=False)
    bad(_judge_in(clone, base, head, e1))


# 7. the token


def test_the_job_token_is_github_token_in_the_marker_steps_env_and_nowhere_else() -> None:
    text = workflow_text("exam-integrity.yml")
    step = _marker_step()
    env_block = step.get("env") or {}
    token = str(env_block.get("GH_TOKEN", ""))
    assert re.fullmatch(r"\$\{\{\s*github\.token\s*\}\}", token), env_block
    assert len(re.findall(r"github\.token", text)) == 1, "github.token appears once"
    assert "secrets." not in text
    assert "GITHUB_TOKEN" not in re.sub(r"\$GITHUB_(ENV|OUTPUT)", "", text)
    assert not re.search(r"(?m)^\s*secrets\s*:", text)
    for s in _steps():
        if s.get("name") != step.get("name"):
            assert "GH_TOKEN" not in yaml.safe_dump(s.get("env") or {}), s
    assert "GH_TOKEN" not in str(step["run"]), "gh reads the token from the env"
