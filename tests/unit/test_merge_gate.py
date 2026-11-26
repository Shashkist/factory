"""Unit tests of the merge gate's pure parts and its gh call shapes."""

import json

import pytest

from factory_tools.pipeline import merge_gate

SHORT = "a1b2c3d"
EXAM = {"name": "exam-integrity", "conclusion": "SUCCESS"}


GATE = {"name": "acceptance / gate", "conclusion": "SUCCESS"}


def test_check_reasons_pass_and_hold():
    assert merge_gate._check_reasons([{"name": "u", "conclusion": "NEUTRAL"}, EXAM, GATE]) == []
    assert merge_gate._check_reasons([]) == ["no checks have run on this PR"]
    assert merge_gate._check_reasons([EXAM, GATE, {"name": "u", "status": "QUEUED"}]) == [
        "u is pending"
    ]
    skipped = [{"name": "exam-integrity", "conclusion": "SKIPPED"}, GATE]
    assert merge_gate._check_reasons(skipped) == ["exam-integrity ended in skipped"]


@pytest.mark.parametrize("state", ["SKIPPED", "NEUTRAL", "FAILURE"])
def test_exam_gate_must_succeed(state):
    gate = {"name": "acceptance / gate", "conclusion": state}
    expected = [f"acceptance / gate ended in {state.lower()}"]
    assert merge_gate._check_reasons([EXAM, gate]) == expected


def test_exam_gate_missing_holds_and_option_renames_it():
    assert merge_gate._check_reasons([EXAM]) == ["acceptance / gate has not run"]
    other = {"name": "ci / gate", "conclusion": "SUCCESS"}
    assert merge_gate._check_reasons([EXAM, other], "ci / gate") == []
    assert merge_gate._check_reasons([EXAM, GATE], "ci / gate") == ["ci / gate has not run"]


def test_verdicts_use_first_line_and_author_only():
    def c(who: str, body: str, at: str) -> dict:
        return {"author": {"login": who}, "body": body, "createdAt": at}

    comments = [
        c("a", f"Review round 2: APPROVE at {SHORT}\nmore", "2"),
        c("b", f"Review round 1: CHANGES at {SHORT}", "1"),
        c("a", f"see Review round 3: APPROVE at {SHORT}", "3"),
    ]
    assert merge_gate._verdicts(comments, "a") == [(2, "APPROVE", SHORT)]


def test_commit_files_names_the_repository_in_the_path_never_dash_r():
    calls: list[list[str]] = []

    def run(args: list[str]) -> str:
        calls.append(args)
        return json.dumps({"files": []})

    assert merge_gate._commit_files(run, "o/r", "abc") == {"files": []}
    assert merge_gate._commit_files(run, None, "abc") == {"files": []}
    assert calls == [
        ["api", "--paginate", "repos/o/r/commits/abc"],
        ["api", "--paginate", "repos/{owner}/{repo}/commits/abc"],
    ]


def test_commit_files_without_repo_raises_on_failure():
    def run(args: list[str]) -> str:
        raise RuntimeError("no")

    with pytest.raises(RuntimeError):
        merge_gate._commit_files(run, None, "abc")


def test_commit_files_merges_concatenated_pages_and_gate_holds_on_page_two():
    page1 = {"files": [{"filename": f"src/f{i}.py"} for i in range(300)]}
    page2 = {"files": [{"filename": "tests/acceptance/test_x.py"}, {"filename": "src/g.py"}]}

    def run(args: list[str]) -> str:
        return json.dumps(page1) + json.dumps(page2)

    assert len(merge_gate._commit_files(run, "o/r", "abc")["files"]) == 302
    pr = {"commits": [{"oid": "abcdef0123"}]}
    reasons = merge_gate._commit_reasons(pr, run, "o/r")
    assert len(reasons) == 1 and "tests/acceptance" in reasons[0]


@pytest.mark.parametrize("name", ["exam-integrity", "exam-integrity / exam-integrity"])
def test_exam_integrity_names_count(name):
    assert merge_gate._check_reasons([{"name": name, "conclusion": "SUCCESS"}, GATE]) == []
    skipped = [{"name": name, "conclusion": "SKIPPED"}, GATE]
    assert merge_gate._check_reasons(skipped) == [f"{name} ended in skipped"]


@pytest.mark.parametrize(
    "name", ["exam-integrity-lint", "exam-integrity / other", "x / exam-integrity-2"]
)
def test_exam_integrity_lookalikes_do_not_count(name):
    reasons = merge_gate._check_reasons([{"name": name, "conclusion": "SUCCESS"}, GATE])
    assert reasons == ["exam-integrity has not run"]


# ---- D29 (#80): the exam checks are bound to the pinned reusable workflows ----------

HEAD = "a" * 40
PIN = "b" * 40
RUN = {
    "path": ".github/workflows/ci.yml",
    "head_sha": HEAD,
    "referenced_workflows": [
        {"path": f"Shashkist/factory/.github/workflows/junit-gate.yml@{PIN}", "sha": PIN},
    ],
}
CI = (
    "jobs:\n  acceptance:\n"
    f"    uses: Shashkist/factory/.github/workflows/junit-gate.yml@{PIN}\n"
)
BOUND = {
    "__typename": "CheckRun",
    "name": "acceptance / gate",
    "conclusion": "SUCCESS",
    "detailsUrl": "https://github.com/o/r/actions/runs/7/job/8",
}


def reads(repo: str | None = "o/r", run: dict | None = None, ci: str = CI, status: str = "behind"):
    calls: list[list[str]] = []

    def gh(args: list[str]) -> str:
        calls.append(args)
        path = args[-1]
        if "/actions/runs/" in path:
            return json.dumps(run or RUN)
        if "/actions/jobs/" in path:
            return json.dumps(_job())
        if "/contents/" in path:
            return ci
        if "/compare/main..." in path:
            return json.dumps({"status": status})
        raise RuntimeError("unexpected " + path)

    return merge_gate._Reads(gh, repo, "Shashkist/factory", HEAD), calls


def test_bound_gate_check_passes_and_each_read_is_made_once():
    r, calls = reads()
    twice = [BOUND, dict(BOUND, name="acceptance / gate")]
    assert merge_gate._binding_reasons(twice, "acceptance / gate", r) == []
    assert len(calls) == 4
    assert calls[2][:3] == ["api", "-H", merge_gate.RAW]
    assert calls[3][-1].endswith("/actions/jobs/8")
    assert calls[2][3].endswith(f"/contents/.github/workflows/ci.yml?ref={HEAD}")


def test_without_repo_the_run_is_also_read_under_the_url_repository():
    r, calls = reads(repo=None)
    assert merge_gate._binding_reason(BOUND, "junit-gate.yml", r) is None
    runs = [c[-1] for c in calls if "/actions/runs/" in c[-1]]
    assert runs == ["repos/{owner}/{repo}/actions/runs/7", "repos/o/r/actions/runs/7"]


def test_ci_yml_as_base64_json_is_not_read():
    import base64

    wrapped = json.dumps({"encoding": "base64", "content": base64.b64encode(CI.encode()).decode()})
    r, _ = reads(ci=wrapped)
    reason = merge_gate._binding_reason(BOUND, "junit-gate.yml", r)
    assert reason and "cannot read" in reason


def test_ci_yml_with_a_duplicate_key_holds_and_anchors_still_merge():
    r, _ = reads(ci=CI + "  acceptance:\n    runs-on: x\n")
    reason = merge_gate._binding_reason(BOUND, "junit-gate.yml", r)
    assert reason and "unique keys" in reason
    anchored = (
        "base: &b\n  runs-on: x\njobs:\n  acceptance:\n    <<: *b\n"
        f"    uses: Shashkist/factory/.github/workflows/junit-gate.yml@{PIN}\n"
    )
    r, _ = reads(ci=anchored)
    assert merge_gate._binding_reason(BOUND, "junit-gate.yml", r) is None


@pytest.mark.parametrize("value", ["{path: x}", "[x]", "1"])
def test_non_string_uses_holds_with_a_reason(value):
    r, _ = reads(ci="jobs:\n  acceptance:\n    uses: " + value + "\n")
    reason = merge_gate._binding_reason(BOUND, "junit-gate.yml", r)
    assert reason and "not a string" in reason


@pytest.mark.parametrize(
    ("job", "words"),
    [
        ("  g:\n    name: \"${{ 'acceptance / gate' }}\"\n", "named by an expression"),
        ("  g:\n    name: x / y\n    uses: ./.github/workflows/l.yml\n", "shown as 'x / y'"),
        ("  x / y:\n    uses: ./.github/workflows/l.yml\n", "shown as 'x / y'"),
        # D29 amendment 2 (review round 2 of #84): GitHub may trim the shown name.
        ("  g:\n    name: \" acceptance\"\n    uses: ./.github/workflows/l.yml\n", "white space"),
        ("  g:\n    name: \"acceptance \"\n    uses: ./.github/workflows/l.yml\n", "white space"),
        ("  g:\n    name: \"accept  ance\"\n", "white space"),
    ],
)
def test_expression_or_slashed_job_names_hold_once_for_the_file(job, words):
    r, _ = reads(ci=CI + job)
    twice = [BOUND, dict(BOUND, name="acceptance / gate")]
    reasons = merge_gate._binding_reasons(twice, "acceptance / gate", r)
    assert len(reasons) == 1 and words in reasons[0], reasons


def test_expressions_outside_job_names_are_fine():
    ci = CI + "  docs:\n    if: ${{ true }}\n    steps:\n      - run: echo ${{ github.sha }}\n"
    r, _ = reads(ci=ci)
    assert merge_gate._binding_reasons([BOUND], "acceptance / gate", r) == []


def test_not_on_main_is_named_before_a_ci_yml_condition():
    r, calls = reads(ci=CI.replace(PIN, "c" * 40), status="ahead")
    reason = merge_gate._binding_reason(BOUND, "junit-gate.yml", r)
    assert reason and "not on main" in reason, reason
    assert not any("/contents/" in c[-1] for c in calls)


@pytest.mark.parametrize(
    ("check", "kw", "words"),
    [
        ({"__typename": "StatusContext", "context": "acceptance / gate"}, {}, "commit status"),
        ({"name": "gate"}, {}, "no caller job part"),
        ({"detailsUrl": "https://example.invalid/x"}, {}, "not a job of a workflow run"),
        ({"detailsUrl": "https://github.com/x/y/actions/runs/7/job/8"}, {}, "run of x/y"),
        ({}, {"run": dict(RUN, path=".github/workflows/x.yml")}, "is of .github/workflows/x.yml"),
        ({}, {"run": dict(RUN, head_sha="c" * 40)}, "not for head"),
        ({}, {"run": dict(RUN, referenced_workflows=[])}, "does not call"),
        ({}, {"ci": CI + "  other:\n    name: acceptance\n"}, "2 jobs named"),
        ({}, {"ci": CI + "  g:\n    name: acceptance / gate\n"}, "full check name"),
        ({}, {"ci": CI.replace(PIN, "c" * 40)}, "does not use"),
        ({}, {"status": "ahead"}, "not on main"),
    ],
)
def test_each_d29_condition_holds_with_a_reason(check, kw, words):
    r, _ = reads(**kw)
    c = {**BOUND, **check}
    if "context" in c:
        del c["name"]
    reason = merge_gate._binding_reason(c, "junit-gate.yml", r)
    assert reason and words in reason, reason


def test_unreadable_run_or_ci_yml_holds():
    def gh(args: list[str]) -> str:
        raise RuntimeError("404")

    r = merge_gate._Reads(gh, "o/r", "Shashkist/factory", HEAD)
    reason = merge_gate._binding_reason(BOUND, "junit-gate.yml", r)
    assert reason and "not a readable workflow run" in reason


def test_only_successful_protected_checks_are_bound():
    r, calls = reads()
    others = [
        {"name": "unit", "conclusion": "SUCCESS"},
        dict(BOUND, conclusion="FAILURE"),
        {"name": "exam-integrity", "conclusion": "SUCCESS", "__typename": "CheckRun"},
    ]
    assert merge_gate._binding_reasons(others, "acceptance / gate", r) == [
        "exam-integrity has no caller job part (`<caller> / <job>`)"
    ]
    assert calls == []


def _job(**over):
    job = {
        "run_id": 7,
        "head_sha": HEAD,
        "name": "acceptance / gate",
        "status": "completed",
        "conclusion": "success",
    }
    job.update(over)
    return job


def test_job_reason_genuine_job_passes():
    assert merge_gate.job_reason("acceptance / gate", "7", "9", _job(), HEAD) is None


@pytest.mark.parametrize(
    ("job", "words"),
    [
        (None, "not a readable"),
        (_job(run_id=8), "belongs to run 8"),
        (_job(run_id="7"), "no run_id"),
        (_job(run_id=None), "no run_id"),
        (_job(name=None), "has no name"),
        (_job(conclusion="failure"), "not completed with success"),
        (_job(conclusion=None), "not completed with success"),
        (_job(status="in_progress"), "not completed with success"),
        (_job(status=None), "not completed with success"),
        (_job(head_sha=None), "no head sha"),
        (_job(head_sha="b" * 40), "not for head"),
        (_job(name="gate"), "not the check name"),
    ],
)
def test_job_reason_holds(job, words):
    reason = merge_gate.job_reason("acceptance / gate", "7", "9", job, HEAD)
    assert reason and words in reason


def _commits_run(files_by_oid: dict[str, list[str]]):
    def run(args: list[str]) -> str:
        files = files_by_oid[args[-1].split("/")[-1]]
        return json.dumps({"files": [{"filename": f} for f in files]})

    return run


def test_commit_reasons_exam_paths_classify_nested_exam_and_code():
    pr = {"commits": [{"oid": "a1"}]}
    run = _commits_run({"a1": ["labs/x/tests/acceptance/t.py", "labs/x/app.py"]})
    assert merge_gate._commit_reasons(pr, run, "o/r") == []
    reasons = merge_gate._commit_reasons(pr, run, "o/r", ["labs/*/tests/acceptance/**"])
    assert len(reasons) == 1 and "together" in reasons[0]


def test_commit_reasons_ci_surface_hold_only_when_a_glob_is_given():
    pr = {"commits": [{"oid": "a1"}, {"oid": "b2"}]}
    run = _commits_run({"a1": ["tests/acceptance/t.py"], "b2": ["labs/ci/p.yml"]})
    assert merge_gate._commit_reasons(pr, run, "o/r") == []
    reasons = merge_gate._commit_reasons(pr, run, "o/r", ci_paths=["labs/ci/**"])
    assert len(reasons) == 1 and "exam" in reasons[0] and "CI surface" in reasons[0]


# ---- D36 (#102): the decision log ----


def test_d_entries_run_to_the_next_level_two_heading(tmp_path):
    log = tmp_path / "D.md"
    log.write_text(
        "# Log\nPR #9 round 3\n\n## D1 a\nPR #9 round 3\n### sub\nmore\n"
        "## Other\nround 4\n## D2 b\nx\n",
        encoding="utf-8",
    )
    entries = merge_gate._d_entries(str(log))
    assert [n for n, _ in entries] == [1, 2]
    assert "more" in entries[0][1] and "round 4" not in entries[0][1]


def test_missing_log_has_no_entries(tmp_path):
    assert merge_gate._d_entries(str(tmp_path / "none.md")) == []


def test_only_a_decides_line_binds_a_round():
    entries = [
        (1, "## D1\nDecides: #9 round 3"),
        (2, "## D2\nPR #9 round 3 is mentioned in prose"),
        (3, "## D3\nDecides: #9 round 30\nDecides: #5 round 3. Why."),
        (4, "## D4\nDecides: #90 round 3\n  Decides: #9 round 3\nDecides: #9 round 3x"),
        (5, "## D5\nDecides: #9 round 3 and 4"),
    ]
    assert merge_gate._decided_rounds(entries, {9, 5}, [3]) == {3: [1, 3, 5]}


R_HEAD = "9" * 40
R_OLD = "8" * 40


def _decide_rounds(monkeypatch, tmp_path, rounds):
    """decide() on review verdicts only: every other rule passes; D1 decides rounds 3 and 4."""
    log = tmp_path / "DECISIONS.md"
    log.write_text("## D1\nDecides: #9 round 3\nDecides: #9 round 4\n", encoding="utf-8")
    for name in ("_check_reasons", "_binding_reasons", "_commit_reasons", "_claim_reasons"):
        monkeypatch.setattr(merge_gate, name, lambda *a, **k: [])
    comments = [
        {"author": {"login": "me"}, "createdAt": f"2026-01-01T00:00:{i:02d}Z",
         "body": f"Review round {k}: {verdict} at {sha}"}
        for i, (k, verdict, sha) in enumerate(rounds)
    ]
    pr = {"number": 9, "author": {"login": "me"}, "body": "", "headRefOid": R_HEAD,
          "comments": comments, "closingIssuesReferences": []}
    return merge_gate.decide("9", "s", run=lambda args: json.dumps(pr), decisions=str(log))


@pytest.mark.parametrize("rounds", [
    # an APPROVE past the limit was followed by more verdicts, even one numbered within the limit
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (3, "APPROVE", R_OLD), (1, "APPROVE", R_HEAD)],
    # a number going back after the first round past the limit
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (3, "CHANGES", R_OLD), (2, "APPROVE", R_HEAD)],
    [(3, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (4, "APPROVE", R_HEAD)],
    # a verdict labelled below the limit just before the first extra round
    [(1, "APPROVE", R_OLD), (3, "APPROVE", R_HEAD)],
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (1, "APPROVE", R_OLD), (3, "APPROVE", R_HEAD)],
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (0, "APPROVE", R_OLD), (3, "APPROVE", R_HEAD)],
    # four reviews with only round 3 decided
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (3, "APPROVE", R_HEAD)],
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (1, "CHANGES", R_OLD), (3, "APPROVE", R_HEAD)],
])
def test_rounds_past_the_limit_hold_on_a_late_approve_or_a_backward_number(
    monkeypatch, tmp_path, rounds
):
    assert _decide_rounds(monkeypatch, tmp_path, rounds) != []


@pytest.mark.parametrize("rounds", [
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (3, "APPROVE", R_HEAD)],
    [(1, "CHANGES", R_OLD), (2, "CHANGES", R_OLD), (3, "CHANGES", R_OLD), (4, "APPROVE", R_HEAD)],
    [(1, "CHANGES", R_OLD), (3, "APPROVE", R_HEAD)],
    [(3, "APPROVE", R_HEAD)],
])
def test_decided_rounds_past_the_limit_merge(monkeypatch, tmp_path, rounds):
    assert _decide_rounds(monkeypatch, tmp_path, rounds) == []
