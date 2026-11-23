# Ported from Learning Factory scripts/test_issue_lock_repos.py (spec G8). Changes versus LF:
#   - import: `import issue_lock` became `from factory_tools import claims as issue_lock`
#     (the script moved into the package as factory_tools.claims).
#   - lint: a file-level ruff noqa comment for E501 and UP017 (LF code is not held to this
#     repo's ruff rules: long lines, timezone.utc). A comment only; no code line altered.
#   Nothing else changed: every case and assertion is as in LF.
# ruff: noqa: E501, UP017
"""Unit tests for the repository handling of issue_lock (#542): take-over line,
-R rules, failed default read, status/stale --repo, repos.yaml parsing."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from factory_tools import claims as issue_lock

HERE = issue_lock.HERE_REPO
OTHER = "Shashkist/factory"


def iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(
        microsecond=0
    ).isoformat()


def comment():
    body = issue_lock.render(
        {"session": "s1", "branch": "f/5-x", "worktree": "C:/wt", "claimed": iso(300),
         "heartbeat": iso(200), "step": "idle"}
    )
    return {"body": body, "url": "https://github.com/o/r/issues/5#issuecomment-1"}


class Gh:
    """Fake gh: one claimed #5 per repository; `broken` repos fail."""

    def __init__(self, broken=(), fail_view=()):
        self.broken, self.fail_view = set(broken), set(fail_view)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        repo = argv[argv.index("-R") + 1] if "-R" in argv else HERE
        if repo in self.broken or (argv[:2] == ["issue", "view"] and repo in self.fail_view):
            raise RuntimeError("gh failed")
        if argv[:2] == ["issue", "view"]:
            return json.dumps({"comments": [comment()]})
        if argv[:2] == ["issue", "list"]:
            return json.dumps([{"number": 5, "title": "Five " + repo, "updatedAt": iso(1)}])
        return ""


def ns(**over):
    base = dict(json=False, older_than=0.0, repos=[HERE, OTHER], default_repo=HERE,
                clones={OTHER: "C:\\projects\\factory"}, repo=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_take_over_line_names_the_other_repository_and_clone(capsys):
    assert issue_lock.cmd_stale(ns(), Gh()) == 0
    out = capsys.readouterr().out
    fac = next(b for b in out.split("\n#") if "Five " + OTHER in b)
    here = next(b for b in out.split("\n#") if "Five " + HERE in b)
    assert "--repo Shashkist/factory --steal" in fac
    assert "git -C 'C:/projects/factory' fetch origin && git -C 'C:/projects/factory' log" in fac
    assert "--repo" not in here.split("take over")[1]
    assert "git -C" not in here and "continue   git fetch origin" in here


def test_failed_default_repository_exits_nonzero_without_reassurance(capsys):
    gh = Gh(broken=[HERE])
    assert issue_lock.cmd_status(ns(), gh) == 1
    assert issue_lock.cmd_stale(ns(), gh) == 1
    assert issue_lock.cmd_status(ns(json=True), gh) == 1
    cap = capsys.readouterr()
    assert "No issues" not in cap.out and "No claim" not in cap.out and "[]" not in cap.out


def test_failed_repo_filter_exits_nonzero_without_reassurance(capsys):
    gh = Gh(broken=[OTHER])
    assert issue_lock.cmd_status(ns(repo=OTHER), gh) == 1
    assert issue_lock.cmd_status(ns(repo=OTHER, json=True), gh) == 1
    assert issue_lock.cmd_stale(ns(repo=OTHER), gh) == 1
    cap = capsys.readouterr()
    assert "No issues" not in cap.out and "No claim" not in cap.out and "[]" not in cap.out


def test_failed_other_repository_is_one_line_and_exit_zero(capsys):
    assert issue_lock.cmd_status(ns(), Gh(broken=[OTHER])) == 0
    cap = capsys.readouterr()
    assert cap.err.count(OTHER) == 1 and "s1" in cap.out


def test_repository_failing_partway_shows_no_partial_rows(capsys):
    assert issue_lock.cmd_status(ns(json=True), Gh(fail_view=[OTHER])) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["repo"] for r in rows] == [HERE]


def test_status_repo_filter_reads_only_that_repository(capsys):
    gh = Gh()
    assert issue_lock.cmd_status(ns(json=True, repo=OTHER), gh) == 0
    assert [r["repo"] for r in json.loads(capsys.readouterr().out)] == [OTHER]
    assert all("-R" in c for c in gh.calls)


def test_filter_on_this_repository_uses_todays_call_shape(capsys):
    gh = Gh()
    assert issue_lock.cmd_stale(ns(repo=HERE), gh) == 0
    assert gh.calls and not any("-R" in c for c in gh.calls)


def test_parser_accepts_repo_on_status_and_stale():
    p = issue_lock.build_parser()
    assert p.parse_args(["status", "--repo", OTHER]).repo == OTHER
    assert p.parse_args(["stale", "--repo", OTHER]).repo == OTHER


def test_scoped_rewrites_only_the_api_path():
    seen = []
    run = issue_lock.scoped(lambda a: seen.append(a) or "", OTHER)
    run(["api", "repos/{owner}/{repo}/issues/comments/1", "-f", "body={owner}/{repo} text"])
    assert seen[0] == ["api", "repos/Shashkist/factory/issues/comments/1", "-f",
                       "body={owner}/{repo} text"]


def test_scoped_with_a_repo_always_adds_dash_R_even_for_this_repository():
    seen = []
    run = issue_lock.scoped(lambda a: seen.append(a) or "", HERE)
    run(["issue", "view", "5"])
    assert seen[0] == ["issue", "view", "5", "-R", HERE]


def write(tmp_path, text):
    f = tmp_path / "repos.yaml"
    f.write_bytes(text.encode("utf-8"))
    return f


def test_repos_parser_bom_quotes_yes_and_duplicates(tmp_path):
    f = write(tmp_path, "\ufeff- repo: \"" + HERE + "\"\n  default: yes\n  clone: 'C:\\x'\n"
              "- repo: " + OTHER + "\n- repo: " + OTHER.lower() + "\n")
    repos, default, clones = issue_lock.read_repos(f)
    assert repos == [HERE, OTHER] and default == HERE
    assert clones == {HERE: "C:\\x"}


def test_default_is_always_this_repository_with_one_warning(tmp_path, capsys):
    f = write(tmp_path, "- repo: " + OTHER + "\n  default: true\n- repo: " + HERE + "\n")
    repos, default, _ = issue_lock.read_repos(f)
    assert default == HERE and repos == [OTHER, HERE]
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def test_file_without_this_repository_adds_it_with_one_warning(tmp_path, capsys):
    f = write(tmp_path, "- repo: " + OTHER + "\n")
    repos, default, _ = issue_lock.read_repos(f)
    assert default == HERE and repos == [HERE, OTHER]
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
