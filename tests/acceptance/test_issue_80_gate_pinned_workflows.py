"""Issue #80 (D29): the merge gate counts the exam gate and exam-integrity results only when
they come from the pinned reusable workflows, not by name.

The two protected checks are `acceptance / gate` (option `--exam-gate`) and `exam-integrity`
(a check named so or ending in ` / exam-integrity`). A SUCCESS counts only when
1. it is a check run (never a commit status),
2. its details URL is a run of the PR's repository whose path is `.github/workflows/ci.yml`
   and whose head_sha is the PR head,
3. that run's `referenced_workflows` has `<workflows repo>/.github/workflows/junit-gate.yml@<sha>`
   (respectively `exam-integrity.yml`) with a sha on the workflows repository's main
   (compare `behind` or `identical`); the workflows repository is `Shashkist/factory`, option
   `--workflows-repo`,
4. the head's `ci.yml` has exactly one job shown under the part of the check name before
   ` / `, that job's `uses:` is exactly the referenced path@sha, and no job is shown under the
   full check name.

Observable behaviour only: the real command against a fake `gh` (tests/acceptance/
fake_gh_merge_gate.py), which serves `actions/runs/<id>`, `contents/.github/workflows/ci.yml?ref=`
(JSON base64, or raw with an `Accept: ...raw` header) and `compare/main...<sha>`. The shared
world (merge_gate_world) backs every protected SUCCESS check by default with a valid run, so the
older exams keep testing their own rules; the cases here set `gh.runs`, `gh.ci_yml` and
`gh.compare` themselves and so own the whole picture.
"""

import re

import pytest
from helpers import ROOT
from merge_gate_world import (
    GATE_FILE,
    HEAD,
    HERE,
    INTEGRITY_FILE,
    OTHER,
    PIN,
    WF_REPO,
    Gate,
    caller,
    check,
    ci_yml,
    holds,
    job_url,
    plain_job,
    real_run,
    run_check,
    status_context,
    uses,
)

GATE = "acceptance / gate"
INTEGRITY = "exam-integrity / exam-integrity"
GATE_RUN, INT_RUN = "1001", "1002"
PIN2 = "b" * 40
PIN3 = "c" * 40
GATE_IF_FALSE = "false"
PR_ONLY = "github.event_name == 'pull_request'"

TARGETS = {
    # target: (check name, run id, reusable workflow, caller job shown name, other check name)
    "gate": (GATE, GATE_RUN, GATE_FILE, "acceptance", INTEGRITY),
    "integrity": (INTEGRITY, INT_RUN, INTEGRITY_FILE, "exam-integrity", GATE),
}


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def good_rollup(repo=HERE, shared=False, gate=GATE, gate_job="acceptance"):
    return [
        check("Lint, types, unit tests"),
        run_check("acceptance / exam", repo, GATE_RUN, "11"),
        run_check(gate, repo, GATE_RUN, "12"),
        run_check(INTEGRITY, repo, GATE_RUN if shared else INT_RUN, "13"),
    ]


def good_callers(wf_repo=WF_REPO, pin=PIN, gate_job="acceptance"):
    return [
        caller(gate_job, GATE_FILE, pin, wf_repo),
        caller("exam-integrity", INTEGRITY_FILE, pin, wf_repo, if_=PR_ONLY),
    ]


def world(
    tmp_path,
    *,
    rollup=None,
    callers=None,
    extra_jobs=(),
    runs=None,
    compare=None,
    wf_repo=WF_REPO,
    repo=HERE,
    shared=False,
    **pr,
):
    """A PR whose exam checks are backed by real runs, exactly as today's CI shows them."""
    pr.setdefault("url", "https://github.com/" + repo + "/pull/9")
    gh = Gate(tmp_path, statusCheckRollup=rollup or good_rollup(repo, shared), **pr)
    gh.exam_gate = None
    refs = [(uses(GATE_FILE, PIN, wf_repo), PIN), (uses(INTEGRITY_FILE, PIN, wf_repo), PIN)]
    default_runs = {GATE_RUN: real_run(refs=refs), INT_RUN: real_run(refs=refs)}
    gh.runs = runs if runs is not None else default_runs
    jobs = callers if callers is not None else good_callers(wf_repo)
    gh.ci_yml = ci_yml(*jobs, *extra_jobs)
    gh.compare = compare if compare is not None else {PIN: "behind"}
    gh.wf_repo = wf_repo
    gh.pr_repo = repo
    return gh


def broken(tmp_path, target, **kw):
    """The good world with one thing wrong for one protected check (`target`).

    Keywords: url (details URL of the target), run (changes to the target's run), ref (the
    target's referenced workflow entry as (path@sha, sha), or None to drop it), caller_pin,
    caller_repo (what the head's ci.yml `uses:` for the target says), no_caller, extra_jobs,
    compare.
    """
    name, run_id, workflow, shown, _ = TARGETS[target]
    rollup = good_rollup()
    idx = next(i for i, c in enumerate(rollup) if c["name"] == name)
    if "url" in kw:
        rollup[idx] = dict(rollup[idx], detailsUrl=kw["url"])
    default_ref = (uses(workflow), PIN)
    ref = kw.get("ref", default_ref)
    other_workflow = INTEGRITY_FILE if workflow == GATE_FILE else GATE_FILE
    refs = [r for r in (ref, (uses(other_workflow), PIN)) if r is not None]
    run = real_run(refs=refs)
    run.update(kw.get("run", {}))
    runs = {GATE_RUN: real_run(), INT_RUN: real_run()}
    runs[run_id] = run
    callers = good_callers()
    pos = 0 if target == "gate" else 1
    if kw.get("no_caller"):
        callers[pos] = caller("unrelated", other_workflow)
    else:
        callers[pos] = caller(
            shown, workflow, kw.get("caller_pin", PIN), kw.get("caller_repo", WF_REPO),
            **({"if_": PR_ONLY} if target == "integrity" else {}),
        )
    return world(
        tmp_path, rollup=rollup, callers=callers, runs=runs,
        extra_jobs=kw.get("extra_jobs", ()),
        compare=kw.get("compare", {PIN: "behind", PIN3: "behind"}),
    )


def assert_holds_naming(result, name, other):
    """HOLD (exit 1, no MERGE), a line naming `name`, and none naming the unbroken check."""
    code, lines = result
    assert code == 1, result
    assert "MERGE" not in lines, lines
    assert lines and all(ln.startswith("HOLD: ") for ln in lines), lines
    assert any(name.lower() in ln.lower() for ln in holds(lines)), (name, lines)
    assert not any(other.lower() in ln.lower() for ln in holds(lines)), (other, lines)


# ---- criterion 3, part one: today's green PRs still merge ----------------------------

def test_green_pr_backed_by_runs_of_the_pinned_workflows_merges(tmp):
    assert world(tmp).run() == (0, ["MERGE"])


def test_green_pr_with_both_checks_in_one_ci_run_merges(tmp):
    """Real CI: one ci.yml run holds both calls and lists both reusable workflows."""
    gh = world(tmp, shared=True)
    gh.runs = {GATE_RUN: real_run()}
    assert gh.run() == (0, ["MERGE"])


def test_green_pr_matches_this_repositorys_own_ci_yml(tmp):
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins = re.findall(r"uses: Shashkist/factory/\.github/workflows/(\S+)@([0-9a-f]{40})", text)
    assert {w for w, _ in pins} == {GATE_FILE, INTEGRITY_FILE}, pins
    refs = [(uses(w, p), p) for w, p in pins]
    gh = world(tmp)
    gh.ci_yml = text
    gh.runs = {GATE_RUN: real_run(refs=refs), INT_RUN: real_run(refs=refs)}
    gh.compare = {p: "behind" for _, p in pins}
    assert gh.run() == (0, ["MERGE"])


@pytest.mark.parametrize("status", ["behind", "identical"])
def test_pinned_sha_behind_or_identical_to_main_is_accepted(tmp, status):
    gh = world(tmp, compare={PIN: status})
    assert gh.run() == (0, ["MERGE"])


def test_caller_job_shown_under_a_name_key_is_found_by_that_name(tmp):
    callers = [
        caller("exam-gate", GATE_FILE, name="acceptance"),
        caller("integrity", INTEGRITY_FILE, name="exam-integrity", if_=PR_ONLY),
    ]
    assert world(tmp, callers=callers).run() == (0, ["MERGE"])


# ---- criteria 1 and 3: spoof 1, renamed caller plus a plain job of the full name -----

def test_renamed_exam_caller_with_a_fake_gate_job_holds(tmp):
    rollup = [
        check("Lint, types, unit tests"),
        # a skipped reusable-workflow call shows as one check named after the caller job
        run_check("acceptance-real", HERE, GATE_RUN, "11", "SKIPPED"),
        run_check(GATE, HERE, GATE_RUN, "14"),
        run_check(INTEGRITY, HERE, INT_RUN, "13"),
    ]
    callers = [
        caller("acceptance-real", GATE_FILE, if_=GATE_IF_FALSE),
        good_callers()[1],
    ]
    gh = world(tmp, rollup=rollup, callers=callers, extra_jobs=[plain_job("gate", GATE)])
    assert_holds_naming(gh.run(), GATE, INTEGRITY)


def test_renamed_exam_integrity_caller_with_a_fake_job_holds(tmp):
    rollup = [
        check("Lint, types, unit tests"),
        run_check("acceptance / exam", HERE, GATE_RUN, "11"),
        run_check(GATE, HERE, GATE_RUN, "12"),
        run_check("exam-integrity-real", HERE, INT_RUN, "13", "SKIPPED"),
        run_check(INTEGRITY, HERE, INT_RUN, "14"),
    ]
    callers = [
        good_callers()[0],
        caller("exam-integrity-real", INTEGRITY_FILE, if_=GATE_IF_FALSE),
    ]
    gh = world(tmp, rollup=rollup, callers=callers, extra_jobs=[plain_job("fake", INTEGRITY)])
    assert_holds_naming(gh.run(), INTEGRITY, GATE)


def test_plain_job_named_like_the_gate_without_any_caller_holds(tmp):
    gh = world(tmp, callers=[good_callers()[1]], extra_jobs=[plain_job("gate", GATE)])
    assert_holds_naming(gh.run(), GATE, INTEGRITY)


# ---- criteria 1 and 3: spoof 2, a commit status -------------------------------------

def status_world(tmp, context, state="SUCCESS"):
    """The exam checks other than `context` are real check runs; `context` is a status."""
    rollup = [c for c in good_rollup() if c["name"] != context]
    rollup.append(status_context(context, state))
    return world(tmp, rollup=rollup)


def test_commit_status_named_like_the_exam_gate_holds(tmp):
    assert_holds_naming(status_world(tmp, GATE).run(), GATE, INTEGRITY)


def test_commit_status_named_exam_integrity_holds(tmp):
    assert_holds_naming(status_world(tmp, "exam-integrity").run(), "exam-integrity", GATE)


def test_commit_status_in_the_suffixed_exam_integrity_name_holds(tmp):
    assert_holds_naming(status_world(tmp, INTEGRITY).run(), "exam-integrity", GATE)


def test_commit_status_does_not_stand_in_even_when_a_check_run_of_that_name_is_skipped(tmp):
    rollup = [c for c in good_rollup() if c["name"] != GATE]
    rollup += [run_check(GATE, HERE, GATE_RUN, "12", "SKIPPED"), status_context(GATE)]
    assert_holds_naming(world(tmp, rollup=rollup).run(), GATE, INTEGRITY)


# ---- criterion 2: every D29 condition on its own ------------------------------------

@pytest.mark.parametrize("target", ["gate", "integrity"])
class TestEachCondition:
    def hold(self, tmp, target, **kw):
        name, _, _, _, other = TARGETS[target]
        gh = broken(tmp, target, **kw)
        assert_holds_naming(gh.run(), name, other)

    def test_control_the_unbroken_world_merges(self, tmp, target):
        assert broken(tmp, target).run() == (0, ["MERGE"])

    def test_details_url_of_a_run_in_another_repository_holds(self, tmp, target):
        run_id = TARGETS[target][1]
        self.hold(tmp, target, url=job_url("Evil/other", run_id, "99"))

    def test_details_url_that_is_not_an_actions_run_holds(self, tmp, target):
        self.hold(tmp, target, url="https://example.invalid/checks/123")

    def test_missing_details_url_holds(self, tmp, target):
        self.hold(tmp, target, url="")

    def test_run_of_another_workflow_file_holds(self, tmp, target):
        self.hold(tmp, target, run={"path": ".github/workflows/other.yml"})

    def test_run_whose_head_is_not_the_pr_head_holds(self, tmp, target):
        self.hold(tmp, target, run={"head_sha": "f" * 40})

    def test_run_that_does_not_list_the_workflow_holds(self, tmp, target):
        self.hold(tmp, target, ref=None)

    def test_workflow_referenced_from_another_repository_holds(self, tmp, target):
        workflow = TARGETS[target][2]
        self.hold(
            tmp, target,
            ref=(uses(workflow, PIN, "Evil/factory"), PIN),
            caller_repo="Evil/factory",
        )

    @pytest.mark.parametrize("status", ["ahead", "diverged"])
    def test_referenced_sha_not_on_main_holds(self, tmp, target, status):
        workflow = TARGETS[target][2]
        self.hold(
            tmp, target,
            ref=(uses(workflow, PIN2), PIN2),
            caller_pin=PIN2,
            compare={PIN: "behind", PIN2: status},
        )

    def test_caller_uses_another_sha_than_the_run_references_holds(self, tmp, target):
        self.hold(tmp, target, caller_pin=PIN3)

    def test_head_ci_yml_without_a_caller_job_of_that_name_holds(self, tmp, target):
        self.hold(tmp, target, no_caller=True)

    def test_second_job_shown_under_the_full_check_name_holds(self, tmp, target):
        name = TARGETS[target][0]
        self.hold(tmp, target, extra_jobs=[plain_job("fake", name)])

    def test_second_job_shown_under_the_caller_name_holds(self, tmp, target):
        shown = TARGETS[target][3]
        self.hold(tmp, target, extra_jobs=[plain_job("second", shown)])


def test_caller_that_uses_a_local_workflow_instead_of_the_pinned_one_holds(tmp):
    callers = ["  acceptance:\n    uses: ./.github/workflows/junit-gate.yml\n", good_callers()[1]]
    assert_holds_naming(world(tmp, callers=callers).run(), GATE, INTEGRITY)


# ---- options -------------------------------------------------------------------------

def test_workflows_repo_option_changes_the_expected_host_repository(tmp):
    host = "Someone/ci-workflows"
    gh = world(tmp, wf_repo=host)
    assert gh.run("--workflows-repo", host) == (0, ["MERGE"])


def test_without_the_option_a_run_of_another_host_repository_holds(tmp):
    gh = world(tmp, wf_repo="Someone/ci-workflows")
    code, lines = gh.run()
    assert code == 1 and "MERGE" not in lines, lines
    assert any(GATE in ln for ln in holds(lines)), lines
    assert any("exam-integrity" in ln for ln in holds(lines)), lines


def test_option_naming_another_host_holds_for_the_default_workflows(tmp):
    code, lines = world(tmp).run("--workflows-repo", "Someone/ci-workflows")
    assert code == 1 and "MERGE" not in lines, lines
    assert any(GATE in ln for ln in holds(lines)), lines
    assert any("exam-integrity" in ln for ln in holds(lines)), lines


def exam_gate_world(tmp, callers, extra_jobs=()):
    name = "ci / exam gate"
    rollup = [
        check("Lint, types, unit tests"),
        run_check(name, HERE, GATE_RUN, "12"),
        run_check(INTEGRITY, HERE, INT_RUN, "13"),
    ]
    return world(tmp, rollup=rollup, callers=callers, extra_jobs=extra_jobs)


def test_exam_gate_option_still_renames_the_exam_gate_check(tmp):
    callers = [caller("ci", GATE_FILE), good_callers()[1]]
    gh = exam_gate_world(tmp, callers)
    assert gh.run("--exam-gate", "ci / exam gate") == (0, ["MERGE"])


def test_renamed_exam_gate_check_is_bound_to_the_workflow_too(tmp):
    callers = [caller("ci-real", GATE_FILE, if_=GATE_IF_FALSE), good_callers()[1]]
    gh = exam_gate_world(tmp, callers, extra_jobs=[plain_job("fake", "ci / exam gate")])
    assert_holds_naming(gh.run("--exam-gate", "ci / exam gate"), "ci / exam gate", INTEGRITY)


def test_renamed_exam_gate_check_as_a_commit_status_holds(tmp):
    gh = world(tmp, rollup=[
        check("Lint, types, unit tests"),
        status_context("ci / exam gate"),
        run_check(INTEGRITY, HERE, INT_RUN, "13"),
    ], callers=[good_callers()[1]])
    assert_holds_naming(gh.run("--exam-gate", "ci / exam gate"), "ci / exam gate", INTEGRITY)


# ---- the gate stays read-only and names the repository -------------------------------

def test_gate_stays_read_only_and_reads_the_run_the_file_and_main(tmp):
    gh = world(tmp)
    assert gh.run() == (0, ["MERGE"])
    assert gh.state()["writes"] == []
    api = [c for c in gh.calls() + gh.workflow_calls() if c[0] == "api"]
    flat = [" ".join(c) for c in api]
    assert any("/actions/runs/" in c for c in flat), flat
    assert any("/contents/.github/workflows/ci.yml" in c and HEAD in c for c in flat), flat
    assert any("/compare/main..." in c and PIN in c for c in flat), flat
    for c in api:
        assert not {"-X", "--method", "-f", "-F", "--field", "--input"} & set(c), c


def test_repo_option_reads_runs_and_files_of_that_repository_and_main_of_the_host(tmp):
    gh = world(tmp, repo=OTHER)
    assert gh.run("--repo", OTHER) == (0, ["MERGE"])
    api = [c for c in gh.calls() if c[0] == "api"]
    assert api
    for c in api:
        paths = [a for a in c if a.startswith("repos/")]
        assert paths and all(p.startswith("repos/" + OTHER + "/") for p in paths), c
    assert any("/actions/runs/" in " ".join(c) for c in api)
    compares = gh.workflow_calls()
    assert compares
    for c in compares:
        paths = [a for a in c if a.startswith("repos/")]
        prefix = "repos/" + WF_REPO + "/compare/main..."
        assert paths and all(p.startswith(prefix) for p in paths), c


def test_details_url_of_another_repository_than_the_repo_option_holds(tmp):
    """With --repo the PR's repository is that one: a run URL naming the default checkout's
    repository is a run of another repository, though the fake would serve it."""
    gh = world(tmp, repo=OTHER, rollup=good_rollup(HERE))
    assert_holds_naming(gh.run("--repo", OTHER), GATE, "unit")



# ---- D29 amendment 1: names GitHub evaluates, slashed shown names, odd YAML ----------

def test_plain_job_named_by_an_expression_like_the_gate_with_a_skipped_caller_holds(tmp):
    """`name: "${{ 'acceptance / gate' }}"` is shown as the gate check; the file cannot tell."""
    rollup = [
        check("Lint, types, unit tests"),
        run_check("acceptance", HERE, GATE_RUN, "11", "SKIPPED"),
        run_check(GATE, HERE, GATE_RUN, "14"),
        run_check(INTEGRITY, HERE, INT_RUN, "13"),
    ]
    callers = [caller("acceptance", GATE_FILE, if_=GATE_IF_FALSE), good_callers()[1]]
    fake = plain_job("gate", "\"${{ 'acceptance / gate' }}\"")
    gh = world(tmp, rollup=rollup, callers=callers, extra_jobs=[fake])
    assert_holds_naming(gh.run(), GATE, INTEGRITY)


def test_plain_job_named_by_an_expression_like_exam_integrity_with_a_skipped_caller_holds(tmp):
    rollup = [
        check("Lint, types, unit tests"),
        run_check("acceptance / exam", HERE, GATE_RUN, "11"),
        run_check(GATE, HERE, GATE_RUN, "12"),
        run_check(INTEGRITY, HERE, INT_RUN, "14"),
    ]
    callers = [good_callers()[0], caller("exam-integrity", INTEGRITY_FILE, if_=GATE_IF_FALSE)]
    fake = plain_job("fake", "\"x / ${{ 'exam-integrity' }}\"")
    gh = world(tmp, rollup=rollup, callers=callers, extra_jobs=[fake])
    assert_holds_naming(gh.run(), "exam-integrity", GATE)


def test_job_shown_with_a_slash_calling_a_local_workflow_with_a_skipped_caller_holds(tmp):
    """Job `x / y` calls a local workflow whose job is `exam-integrity`: the check is shown as
    `x / y / exam-integrity`, though the pinned caller is skipped."""
    shown = "x / y / exam-integrity"
    rollup = [
        check("Lint, types, unit tests"),
        run_check("acceptance / exam", HERE, GATE_RUN, "11"),
        run_check(GATE, HERE, GATE_RUN, "12"),
        run_check(shown, HERE, INT_RUN, "13"),
    ]
    local = "  local:\n    name: x / y\n    uses: ./.github/workflows/local.yml\n"
    skipped = caller("exam-integrity", INTEGRITY_FILE, if_=GATE_IF_FALSE)
    callers = [good_callers()[0], skipped, local]
    gh = world(tmp, rollup=rollup, callers=callers)
    assert_holds_naming(gh.run(), "exam-integrity", GATE)


@pytest.mark.parametrize(
    "value",
    [
        "\n      path: Shashkist/factory/.github/workflows/junit-gate.yml\n",
        "\n      - junit-gate.yml\n",
    ],
    ids=["mapping", "list"],
)
@pytest.mark.parametrize("target", ["gate", "integrity"])
def test_job_whose_uses_is_not_a_string_holds_without_a_traceback(tmp, target, value):
    shown = TARGETS[target][3]
    bad = "  " + shown + ":\n    uses:" + value
    callers = good_callers()
    callers[0 if target == "gate" else 1] = bad
    proc = world(tmp, callers=callers).command("merge-gate", "9", "--session", "lf-pass-1")
    out = proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert "Traceback" not in out, out
    assert proc.returncode == 1, (proc.returncode, out)
    assert "MERGE" not in lines, lines
    assert holds(lines), lines


def test_ci_yml_with_a_duplicate_job_key_holds(tmp):
    """The same job key twice: YAML loaders keep the last one, so the file is refused."""
    callers = good_callers()
    callers.append(callers[0])
    code, lines = world(tmp, callers=callers).run()
    assert code == 1 and "MERGE" not in lines, (code, lines)
    assert holds(lines), lines


def test_ci_yml_with_a_duplicate_job_key_that_hides_a_skipped_caller_holds(tmp):
    """The first `acceptance` is the pinned caller, the second (the one a loader keeps) is a
    plain job: the file is refused rather than read one way."""
    callers = good_callers()
    callers.append(plain_job("acceptance"))
    code, lines = world(tmp, callers=callers).run()
    assert code == 1 and "MERGE" not in lines, (code, lines)
    assert holds(lines), lines


def test_control_real_shaped_green_pr_merges_with_expressions_elsewhere_in_ci_yml(tmp):
    """No `${{` in any job name and no ` / ` in any shown name: nothing new fires. Expressions
    in steps and conditions are fine."""
    extra = (
        "  docs:\n    name: Docs\n    runs-on: ubuntu-latest\n"
        "    if: ${{ github.event_name == 'pull_request' }}\n"
        "    steps:\n      - run: echo ${{ github.sha }}\n"
    )
    gh = world(tmp, extra_jobs=[extra])
    assert gh.run() == (0, ["MERGE"])
