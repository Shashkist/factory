"""Issue #86 (D29 amendment 2): a bound exam check must be a real Actions job of its run.

For each SUCCESS exam gate and exam-integrity check the gate reads
`repos/<repo>/actions/jobs/<job id from the details URL>` and holds with a reason line unless the
job's `run_id` is the URL's run, its `head_sha` is the PR head and its `name` is the check name;
an unreadable job holds. Each job is read once.

The spoof: the pinned caller kept with `if: false`, plus a plain job that creates a check run
through the Checks API under the protected name, with a details URL into the same run. The
run-level and file-level conditions of D29 all pass for it; only the job behind the URL tells.

The fake world (merge_gate_world) answers the jobs endpoint for every check run backed by a job
URL with a genuine job, so the older exams keep their verdicts; the cases here change one job
through `Gate.jobs`.
"""

import pytest
import test_issue_80_gate_pinned_workflows as w80
from merge_gate_world import (
    HEAD,
    HERE,
    INTEGRITY_FILE,
    JOB_ERROR,
    PIN,
    caller,
    check,
    holds,
    plain_job,
    run_check,
    uses,
)

GATE, INTEGRITY = w80.GATE, w80.INTEGRITY
GATE_RUN, INT_RUN = w80.GATE_RUN, w80.INT_RUN
PIN2, PIN3 = w80.PIN2, w80.PIN3
TARGETS = w80.TARGETS
# target: (check name, job id of the check in the good rollup, run id, other check name)
BOUND = {
    "gate": (GATE, "12", GATE_RUN, INTEGRITY),
    "integrity": (INTEGRITY, "13", INT_RUN, GATE),
}


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def read_count(gh, kind, ident):
    """How many `gh api` calls read `repos/.../actions/<kind>/<ident>` (kind: runs or jobs)."""
    tail = "/actions/" + kind + "/" + ident
    return sum(
        1
        for c in gh.calls()
        if c[0] == "api"
        and any(a.startswith("repos/") and a.split("?")[0].endswith(tail) for a in c)
    )


# ---- criteria 1 and 2: the spoof from the issue --------------------------------------

def spoof_world(tmp, target):
    """Pinned caller kept with `if: false`, a plain job that creates the protected check run.

    The check's details URL is job 14 of the same run, a real job of that run (the spoof job)
    whose name is not the check name.
    """
    if target == "gate":
        rollup = [
            check("Lint, types, unit tests"),
            run_check("acceptance", HERE, GATE_RUN, "11", "SKIPPED"),
            run_check(GATE, HERE, GATE_RUN, "14"),
            run_check(INTEGRITY, HERE, INT_RUN, "13"),
        ]
        callers = [caller("acceptance", w80.GATE_FILE, if_="false"), w80.good_callers()[1]]
    else:
        rollup = [
            check("Lint, types, unit tests"),
            run_check(GATE, HERE, GATE_RUN, "12"),
            run_check("ci", HERE, INT_RUN, "11", "SKIPPED"),
            run_check("ci / exam-integrity", HERE, INT_RUN, "14"),
        ]
        callers = [w80.good_callers()[0], caller("ci", INTEGRITY_FILE, if_="false")]
    gh = w80.world(tmp, rollup=rollup, callers=callers, extra_jobs=[plain_job("spoof")])
    gh.jobs["14"] = {"name": "spoof"}
    return gh


@pytest.mark.parametrize("target", ["gate", "integrity"])
def test_check_run_created_by_a_plain_job_with_a_details_url_into_the_run_holds(tmp, target):
    gh = spoof_world(tmp, target)
    name = "ci / exam-integrity" if target == "integrity" else GATE
    other = GATE if target == "integrity" else INTEGRITY
    code, lines = gh.run()
    assert code == 1 and "MERGE" not in lines, (code, lines)
    assert any(name.lower() in ln.lower() for ln in holds(lines)), (name, lines)
    assert not any(other.lower() in ln.lower() for ln in holds(lines)), (other, lines)


def test_spoof_job_that_really_belongs_to_the_run_and_head_still_holds_by_its_name(tmp):
    """The spoof job is a real job of the run and head; only its name is not the check's."""
    gh = spoof_world(tmp, "gate")
    gh.jobs["14"] = {"name": "spoof", "run_id": int(GATE_RUN), "head_sha": HEAD}
    w80.assert_holds_naming(gh.run(), GATE, INTEGRITY)


# ---- criterion 1: each field of the job on its own, for both checks ------------------

@pytest.mark.parametrize("target", ["gate", "integrity"])
class TestEachJobCondition:
    def hold(self, tmp, target, change):
        name, job_id, _, other = BOUND[target]
        gh = w80.broken(tmp, target)
        gh.jobs[job_id] = change
        w80.assert_holds_naming(gh.run(), name, other)

    def test_control_a_genuine_job_merges(self, tmp, target):
        gh = w80.broken(tmp, target)
        assert gh.run() == (0, ["MERGE"])
        assert read_count(gh, "jobs", BOUND[target][1]) >= 1

    def test_job_of_another_run_holds(self, tmp, target):
        self.hold(tmp, target, {"run_id": 4242})

    def test_job_of_the_other_exam_check_run_holds(self, tmp, target):
        other_run = INT_RUN if target == "gate" else GATE_RUN
        self.hold(tmp, target, {"run_id": int(other_run)})

    def test_job_without_a_run_id_holds(self, tmp, target):
        self.hold(tmp, target, {"run_id": None})

    def test_job_of_another_head_holds(self, tmp, target):
        self.hold(tmp, target, {"head_sha": "f" * 40})

    def test_job_without_a_head_sha_holds(self, tmp, target):
        self.hold(tmp, target, {"head_sha": None})

    def test_job_of_another_name_holds(self, tmp, target):
        self.hold(tmp, target, {"name": "some other job"})

    def test_job_named_by_the_called_job_only_holds(self, tmp, target):
        self.hold(tmp, target, {"name": BOUND[target][0].split(" / ")[1]})

    def test_job_without_a_name_holds(self, tmp, target):
        self.hold(tmp, target, {"name": None})

    def test_job_that_does_not_exist_holds(self, tmp, target):
        self.hold(tmp, target, None)

    def test_unreadable_jobs_endpoint_holds(self, tmp, target):
        self.hold(tmp, target, JOB_ERROR)


def test_both_checks_with_a_broken_job_hold_with_a_line_each(tmp):
    gh = w80.world(tmp)
    gh.jobs["12"] = {"name": "spoof"}
    gh.jobs["13"] = {"head_sha": "f" * 40}
    code, lines = gh.run()
    assert code == 1 and "MERGE" not in lines, (code, lines)
    assert any(GATE.lower() in ln.lower() for ln in holds(lines)), lines
    assert any("exam-integrity" in ln.lower() for ln in holds(lines)), lines


def test_the_gate_reads_the_job_of_each_bound_check_and_writes_nothing(tmp):
    gh = w80.world(tmp)
    assert gh.run() == (0, ["MERGE"])
    assert gh.state()["writes"] == []
    assert read_count(gh, "jobs", "12") >= 1, gh.calls()
    assert read_count(gh, "jobs", "13") >= 1, gh.calls()


# ---- criterion 3: two D29 conditions broken at once, the first in order is named -----

TWO = {
    # id: (token only the first condition's line carries, token of the second's, if any)
    "run-path-and-not-on-main": ("other.yml", PIN2[:7]),
    "run-path-and-caller-pin": ("other.yml", None),
    "not-on-main-and-caller-pin": (PIN2[:7], None),
}


def two_broken(case, workflow):
    if case == "run-path-and-not-on-main":
        return {
            "run": {"path": ".github/workflows/other.yml"},
            "ref": (uses(workflow, PIN2), PIN2),
            "caller_pin": PIN2,
            "compare": {PIN: "behind", PIN2: "ahead"},
        }
    if case == "run-path-and-caller-pin":
        return {"run": {"path": ".github/workflows/other.yml"}, "caller_pin": PIN3}
    return {
        "ref": (uses(workflow, PIN2), PIN2),
        "caller_pin": PIN3,
        "compare": {PIN: "behind", PIN2: "ahead", PIN3: "behind"},
    }


@pytest.mark.parametrize("target", ["gate", "integrity"])
@pytest.mark.parametrize("case", sorted(TWO))
def test_two_broken_conditions_hold_naming_the_first_in_order_two_three_four(tmp, target, case):
    """The HOLD line names the first failed condition (D29 amendment 1: order 1 to 4, `on main`
    being part of 3): 2 (the run) before 3 (the workflow on main) before 4 (the head's file)."""
    first_token, later_token = TWO[case]
    name, _, _, other = BOUND[target]
    gh = w80.broken(tmp, target, **two_broken(case, TARGETS[target][2]))
    code, lines = gh.run()
    assert code == 1 and "MERGE" not in lines, (code, lines)
    mine = [ln for ln in holds(lines) if name.lower() in ln.lower()]
    assert len(mine) == 1, lines
    assert first_token in mine[0], (first_token, mine)
    if later_token:
        assert later_token not in mine[0], (later_token, mine)
    assert not any(other.lower() in ln.lower() for ln in holds(lines)), (other, lines)


# ---- criterion 4: one read per job ---------------------------------------------------

def test_two_bound_checks_read_each_job_once_with_the_repo_option(tmp):
    gh = w80.world(tmp)
    assert gh.run("--repo", HERE) == (0, ["MERGE"])
    assert read_count(gh, "jobs", "12") == 1, gh.calls()
    assert read_count(gh, "jobs", "13") == 1, gh.calls()
    assert read_count(gh, "runs", GATE_RUN) == 1, gh.calls()
    assert read_count(gh, "runs", INT_RUN) == 1, gh.calls()


def test_two_bound_checks_in_one_run_read_each_job_once(tmp):
    gh = w80.world(tmp, shared=True)
    gh.runs = {GATE_RUN: w80.real_run()}
    assert gh.run("--repo", HERE) == (0, ["MERGE"])
    assert read_count(gh, "jobs", "12") == 1, gh.calls()
    assert read_count(gh, "jobs", "13") == 1, gh.calls()
    assert read_count(gh, "runs", GATE_RUN) == 1, gh.calls()


def test_a_check_listed_twice_reads_its_job_once(tmp):
    rollup = w80.good_rollup() + [run_check(GATE, HERE, GATE_RUN, "12")]
    gh = w80.world(tmp, rollup=rollup)
    assert gh.run("--repo", HERE) == (0, ["MERGE"])
    assert read_count(gh, "jobs", "12") == 1, gh.calls()
    assert read_count(gh, "jobs", "13") == 1, gh.calls()


def test_without_the_repo_option_a_job_is_read_no_more_often_than_its_run(tmp):
    """Without --repo the run is read under the placeholder and under the URL's repository; the
    job read may do the same, but never more often than the run read."""
    gh = w80.world(tmp)
    assert gh.run() == (0, ["MERGE"])
    for job_id, run_id in (("12", GATE_RUN), ("13", INT_RUN)):
        jobs = read_count(gh, "jobs", job_id)
        runs = read_count(gh, "runs", run_id)
        assert 1 <= jobs <= max(runs, 1), (job_id, jobs, runs, gh.calls())
