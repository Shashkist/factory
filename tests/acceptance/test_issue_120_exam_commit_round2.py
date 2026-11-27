"""Issue #120, review round 2 of PR #128: what the first two exam files left open.

  1. The scope addition of review round 2 of #119: a commit that deletes a pyproject.toml with a
     pytest table together with code, and an unparsable pyproject.toml changed together with
     code, are both refused (per commit, and for the exam files between the exam commit and the
     head). A deleted file or an unparsable one must not read as "no pytest table".
  2. The jq projection that feeds the marker module in exam-integrity.yml keeps the five
     fields the module needs, and the first line of the body only.
  3. The marker module also runs the way the workflow runs it: as a plain file under
     `python -I`, with no PYTHONPATH and no package on the path, and it imports stdlib only.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from helpers import ROOT, workflow_text
from test_issue_1_exam_integrity import CODE, Repo, bad, ok

PYPROJECT = "pyproject.toml"
NESTED = "labs/manager/pyproject.toml"
NO_TABLE = "labs/other/pyproject.toml"
BAD_ONE = "labs/bad/pyproject.toml"
WITH_TABLE = '[project]\nname = "x"\nversion = "0"\n\n[tool.pytest.ini_options]\naddopts = "-q"\n'
WITHOUT_TABLE = '[project]\nname = "x"\nversion = "0"\n'
BROKEN = '[project\nname = "x"\n[tool.pytest.ini_options\naddopts = -q\n'
BROKEN_2 = "this is = = not toml [[[\n"
MARKER_FILE = ROOT / "src" / "factory_tools" / "ci" / "exam_marker.py"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path / "r")
    r.commit(
        {PYPROJECT: WITH_TABLE, NESTED: WITH_TABLE, NO_TABLE: WITHOUT_TABLE, BAD_ONE: BROKEN},
        "pyprojects",
    )
    r.base = r.rev("HEAD")
    return r


def _delete(repo: Repo, files: list[str], extra: dict[str, str], msg: str) -> None:
    repo.git("rm", "-q", "--", *files)
    for name, content in extra.items():
        p = repo.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    if extra:
        repo.git("add", "--", *extra)
    repo.git("commit", "-q", "-m", msg)


def _refused_together(r: subprocess.CompletedProcess[str]) -> None:
    bad(r)
    assert "FAIL:" in r.stdout and "together" in r.stdout, r.stdout


# 1. deleted and unparsable pyproject.toml, per commit


@pytest.mark.parametrize("path", [PYPROJECT, NESTED], ids=["root", "nested"])
def test_deleting_a_pyproject_with_a_pytest_table_together_with_code_is_refused(
    repo: Repo, path: str
) -> None:
    _delete(repo, [path], {CODE: "1\n"}, "delete pyproject and add code")
    _refused_together(repo.check())


def test_deleting_a_pyproject_with_a_pytest_table_with_code_is_refused_with_exam_paths(
    repo: Repo,
) -> None:
    _delete(repo, [PYPROJECT], {CODE: "1\n"}, "delete pyproject and add code")
    _refused_together(repo.check("--exam-paths", "tests/acceptance/**"))


def test_deleting_a_pyproject_with_a_pytest_table_after_code_is_refused(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    _delete(repo, [PYPROJECT], {}, "delete pyproject")
    bad(repo.check())


def test_deleting_a_pyproject_with_a_pytest_table_before_code_passes(repo: Repo) -> None:
    _delete(repo, [PYPROJECT], {}, "delete pyproject")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_deleting_a_pyproject_without_a_pytest_table_with_code_is_code(repo: Repo) -> None:
    _delete(repo, [NO_TABLE], {CODE: "1\n"}, "delete pyproject without table and add code")
    ok(repo.check())


def test_deleting_an_unparsable_pyproject_with_code_is_refused(repo: Repo) -> None:
    # nothing can say what the file held: fail closed
    _delete(repo, [BAD_ONE], {CODE: "1\n"}, "delete broken pyproject and code")
    _refused_together(repo.check())


@pytest.mark.parametrize(
    "before",
    [WITH_TABLE, WITHOUT_TABLE, BROKEN],
    ids=["had-table", "had-no-table", "was-unparsable"],
)
def test_a_pyproject_made_unparsable_together_with_code_is_refused(
    repo: Repo, before: str
) -> None:
    repo.commit({"labs/z/pyproject.toml": before}, "pyproject")
    repo.base = repo.rev("HEAD")
    repo.commit({"labs/z/pyproject.toml": BROKEN_2, CODE: "1\n"}, "break it and add code")
    _refused_together(repo.check())


@pytest.mark.parametrize("after", [WITHOUT_TABLE, WITH_TABLE], ids=["no-table", "table"])
def test_an_unparsable_pyproject_fixed_together_with_code_is_refused(
    repo: Repo, after: str
) -> None:
    repo.commit({BAD_ONE: after, CODE: "1\n"}, "fix and code")
    _refused_together(repo.check())


def test_an_unparsable_pyproject_changed_together_with_code_is_refused(repo: Repo) -> None:
    repo.commit({BAD_ONE: BROKEN_2, CODE: "1\n"}, "still broken, and code")
    _refused_together(repo.check())


def test_an_unparsable_pyproject_changed_alone_before_code_passes(repo: Repo) -> None:
    repo.commit({BAD_ONE: BROKEN_2}, "still broken")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check())


def test_an_unparsable_pyproject_changed_after_code_is_refused(repo: Repo) -> None:
    repo.commit({CODE: "1\n"}, "code")
    repo.commit({BAD_ONE: BROKEN_2}, "still broken")
    bad(repo.check())


# 1b. the same two rules between the recorded exam commit and the head


def _recorded(repo: Repo) -> str:
    repo.commit({"tests/acceptance/x.py": "1\n"}, "exam")
    return repo.rev("HEAD")


def test_after_the_exam_commit_deleting_a_pyproject_with_a_pytest_table_is_refused(
    repo: Repo,
) -> None:
    exam = _recorded(repo)
    _delete(repo, [PYPROJECT], {}, "delete pyproject")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check("--exam-commit", exam)
    bad(r)
    assert PYPROJECT in r.stdout and "differs between exam commit" in r.stdout, r.stdout


def test_after_the_exam_commit_making_a_pyproject_unparsable_is_refused(repo: Repo) -> None:
    exam = _recorded(repo)
    repo.commit({NO_TABLE: BROKEN_2}, "break a pyproject")
    repo.commit({CODE: "1\n"}, "code")
    r = repo.check("--exam-commit", exam)
    bad(r)
    assert NO_TABLE in r.stdout and "differs between exam commit" in r.stdout, r.stdout


def test_after_the_exam_commit_deleting_a_pyproject_without_a_pytest_table_is_fine(
    repo: Repo,
) -> None:
    exam = _recorded(repo)
    _delete(repo, [NO_TABLE], {}, "delete pyproject without table")
    repo.commit({CODE: "1\n"}, "code")
    ok(repo.check("--exam-commit", exam))


# 2. the jq projection of the marker step


def _marker_run() -> str:
    steps = yaml.safe_load(workflow_text("exam-integrity.yml"))["jobs"]["exam-integrity"]["steps"]
    found = [
        s for s in steps if "gh api" in str(s.get("run", "")) and "exam_marker" in str(s["run"])
    ]
    assert len(found) == 1, found
    return str(found[0]["run"])


def _jq() -> str:
    m = re.search(r"--jq\s+'([^']*)'", _marker_run(), re.S)
    assert m, _marker_run()
    return m.group(1)


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_jq_projection_keeps_exactly_the_five_fields_the_marker_module_reads() -> None:
    m = re.search(r"\|\s*\{(.*)\}\s*$", _jq().strip(), re.S)
    assert m, _jq()
    keys = set(re.findall(r"(?:^|,)\s*(\w+)\s*(?=[:,]|$)", m.group(1)))
    assert keys == {"id", "author_association", "created_at", "updated_at", "first"}, m.group(1)


@pytest.mark.parametrize("field", ["id", "author_association", "created_at", "updated_at"])
def test_jq_projection_carries_each_field_through_unchanged(field: str) -> None:
    flat = _flat(_jq())
    # a bare key (shorthand for .<key>) or an explicit key: .<key>
    assert re.search(rf"[{{,]{field}(?::\.{field})?[,}}]", flat), flat


def test_jq_projection_takes_only_the_first_line_of_the_body_as_first() -> None:
    flat = _flat(_jq())
    assert re.search(r'first:\(?\.body\|split\("\\n"\)\[0\]\)?[,}]', flat), flat
    assert not re.search(r"first:\.body[,}]", flat), flat


def test_jq_projection_selects_only_comments_that_start_with_the_marker_prefix() -> None:
    assert 'select(.body|startswith("exam-commit:"))' in _flat(_jq()), _jq()


# 3. the marker module as a plain file under -I, the way the workflow runs it


def _plain(text: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    e["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-I", str(MARKER_FILE)],
        input=text,
        cwd=cwd,
        env=e,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _line(cid: int, first: str, edited: bool = False) -> str:
    return json.dumps(
        {
            "id": cid,
            "author_association": "OWNER",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z" if edited else "2026-01-01T00:00:00Z",
            "first": first,
        }
    )


def test_marker_module_runs_as_a_plain_file_under_isolated_mode(tmp_path: Path) -> None:
    a, b = "a" * 40, "b" * 40
    text = _line(1, f"exam-commit: {a}") + "\n" + _line(2, f"exam-commit: {b}") + "\n"
    r = _plain(text, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.split() == [a, b], r.stdout + r.stderr
    assert "Traceback" not in r.stderr, r.stderr


def test_marker_module_as_a_plain_file_still_fails_on_an_edited_marker(tmp_path: Path) -> None:
    r = _plain(_line(1, f"exam-commit: {'a' * 40}", edited=True) + "\n", tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.strip() == "", r.stdout
    assert "edited" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_marker_module_as_a_plain_file_with_no_input_prints_nothing(tmp_path: Path) -> None:
    r = _plain("", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "", r.stdout


def test_marker_module_imports_the_standard_library_only() -> None:
    # The job has no installed package and no third-party modules; -I alone cannot show that
    # where site-packages are present, so the imports are read from the source.
    tree = ast.parse(MARKER_FILE.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import cannot work in a plain file"
            names.append((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
            pytest.fail("__import__ is not allowed in the marker module")
    assert names, "the module imports nothing: the check is not looking at the right file"
    outside = sorted(set(names) - set(sys.stdlib_module_names))
    assert outside == [], f"marker module imports non-stdlib modules: {outside}"
