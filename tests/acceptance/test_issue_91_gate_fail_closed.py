"""Issue #91: the gate fails closed (criteria 7 to 9 of #67).

1. A passing report followed by an exam command that exits 1 leaves the gate red.
2. In junit-gate.yml and exam-integrity.yml the FIRST step of the gate job exits 1 when
   `job.workflow_repository` or `job.workflow_sha` is empty, before any actions/checkout
   (an empty value would make actions/checkout fall back to the caller's repository and ref).
3. docs/ci.md says that a caller-level `if:` that skips the whole call also skips the gate,
   and that a skipped required check passes.

Criteria 1 and 2 are behaviour cases: the run scripts are taken from the workflow YAML and
executed under bash with the Actions expressions filled in, the judge stubbed. Each checker
is a function of the workflow text, so mutation cases prove it rejects a weakened workflow
and accepts a safe respelling.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import ROOT, workflow_text

GATE = "junit-gate.yml"
INTEGRITY = "exam-integrity.yml"
GATE_JOB = {GATE: "gate", INTEGRITY: "exam-integrity"}
BOTH = [GATE, INTEGRITY]
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = "Shashkist/factory"
DOC = ROOT / "docs" / "ci.md"


def find_bash() -> str | None:
    cands = []
    if sys.platform == "win32":
        cands += [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ]
    found = shutil.which("bash")
    if found and not re.search(r"system32|windowsapps", found, re.I):
        cands.append(found)
    return next((c for c in cands if os.path.isfile(c)), None)


BASH = find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no bash on PATH")


# ---------------------------------------------------------------- helpers


def steps_of(text: str, job: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "not a YAML mapping"
    jobs = data.get("jobs") or {}
    assert job in jobs, f"no job {job!r}"
    steps = jobs[job].get("steps") or []
    assert steps, f"job {job!r} has no steps"
    return steps


def is_checkout(step: dict[str, Any]) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def substitute(value: str, values: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        return values.get(m.group(1).strip(), "x")

    return re.sub(r"\$\{\{(.*?)\}\}", repl, value)


def run_step(step: dict[str, Any], values: dict[str, str], workdir: Path, name: str) -> int:
    """Run one `run` step under bash the way Actions does (-e, pipefail), expressions
    filled from values, the judge's interpreter stubbed to exit 0."""
    assert BASH
    assert "run" in step, "the step is not a run step"
    (workdir / "fakebin").mkdir(exist_ok=True)
    fake = workdir / "fakebin" / "python3"
    fake.write_bytes(b"#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    script = substitute(step["run"], values).replace("/usr/bin/python3", "./fakebin/python3")
    path = workdir / f"{name}.sh"
    path.write_bytes(script.encode("utf-8").replace(b"\r\n", b"\n"))
    env = {k: v for k, v in os.environ.items() if k not in ("EXAM_RESULT", "TEST_COMMAND")}
    env.update({k: substitute(str(v), values) for k, v in (step.get("env") or {}).items()})
    done = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", path.name],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.returncode


def plain(step: dict[str, Any]) -> bool:
    """No condition that skips the step, no way to ignore its failure, default shell."""
    cond = step.get("if")
    return (
        (cond is None or str(cond).strip().lower() in ("true", "${{ true }}", "${{ always() }}"))
        and str(step.get("continue-on-error", "false")).lower() == "false"
        and step.get("shell") in (None, "bash")
    )


# ------------------------------------------------ criterion 2: the first step


def check_first_step_fails_closed(text: str, job: str, workdir: Path) -> None:
    steps = steps_of(text, job)
    first = steps[0]
    assert "run" in first and "uses" not in first, (
        f"the first step of job {job} is not a run step (a guard must come first)"
    )
    assert plain(first), "the guard step is conditional, shell-overridden or ignorable"
    checkouts = [i for i, s in enumerate(steps) if is_checkout(s)]
    assert checkouts, f"job {job} has no actions/checkout step"
    assert min(checkouts) > 0, "an actions/checkout runs before the guard"
    cases = {
        "empty_repository": {"job.workflow_repository": "", "job.workflow_sha": SHA},
        "empty_sha": {"job.workflow_repository": REPO, "job.workflow_sha": ""},
        "both_empty": {"job.workflow_repository": "", "job.workflow_sha": ""},
    }
    for label, values in cases.items():
        sub = workdir / label
        sub.mkdir()
        rc = run_step(first, values, sub, "guard")
        assert rc == 1, f"the guard exits {rc}, not 1, with {label}"
    ok = workdir / "control"
    ok.mkdir()
    values = {"job.workflow_repository": REPO, "job.workflow_sha": SHA}
    assert run_step(first, values, ok, "guard") == 0, "the guard fails with both values set"


@needs_bash
@pytest.mark.parametrize("wf", BOTH)
def test_criterion_2_first_gate_step_exits_1_on_an_empty_workflow_repository_or_sha(
    wf: str, tmp_path: Path
) -> None:
    check_first_step_fails_closed(workflow_text(wf), GATE_JOB[wf], tmp_path)


@pytest.mark.parametrize("wf", BOTH)
@pytest.mark.parametrize("field", ["repository", "sha"])
def test_criterion_2_guard_reads_each_field_before_any_checkout(wf: str, field: str) -> None:
    steps = steps_of(workflow_text(wf), GATE_JOB[wf])
    first = steps[0]
    expr = f"job.workflow_{field}"
    blob = str(first.get("run", "")) + str(first.get("env", ""))
    assert expr in blob, f"the first step of {wf} never reads {expr}"
    assert not is_checkout(first)


@pytest.mark.parametrize("wf", BOTH)
def test_criterion_2_the_judge_checkout_still_uses_the_workflow_ref(wf: str) -> None:
    steps = steps_of(workflow_text(wf), GATE_JOB[wf])
    judge = [s for s in steps if is_checkout(s) and "job.workflow_sha" in str(s.get("with"))]
    assert judge, f"{wf} no longer checks out the judge at job.workflow_sha"
    assert "job.workflow_repository" in str(judge[0]["with"])


# mutation cases on a synthetic workflow shaped like the shipped ones

GUARD_OK = (
    '      - name: Guard\n        env:\n          WF_REPO: ${{ job.workflow_repository }}\n'
    "          WF_SHA: ${{ job.workflow_sha }}\n        run: |\n"
    '          if [ -z "$WF_REPO" ] || [ -z "$WF_SHA" ]; then\n'
    '            echo "::error::empty workflow ref"\n            exit 1\n          fi\n'
)
CHECKOUT = (
    "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
    "        with:\n          repository: ${{ job.workflow_repository }}\n"
    "          ref: ${{ job.workflow_sha }}\n"
)


def synth(guard: str, before: str = "", after: str = CHECKOUT) -> str:
    return "on: x\njobs:\n  g:\n    runs-on: ubuntu-latest\n    steps:\n" + before + guard + after


GUARD_MUTANTS = {
    "exit_zero": synth(GUARD_OK.replace("exit 1", "exit 0")),
    "exit_two": synth(GUARD_OK.replace("exit 1", "exit 2")),
    "only_repository": synth(GUARD_OK.replace(' || [ -z "$WF_SHA" ]', "")),
    "only_sha": synth(GUARD_OK.replace('[ -z "$WF_REPO" ] || ', "")),
    "warning_only": synth(GUARD_OK.replace("exit 1", "true")),
    "after_checkout": synth(GUARD_OK, before=CHECKOUT, after=""),
    "conditional": synth(GUARD_OK.replace("        run: |", "        if: false\n        run: |")),
    "continue_on_error": synth(
        GUARD_OK.replace("        run: |", "        continue-on-error: true\n        run: |")
    ),
    "no_checkout_at_all": synth(GUARD_OK, after=""),
    "uses_step_first": synth(GUARD_OK, before="      - uses: astral-sh/setup-uv@abc\n"),
}


@needs_bash
def test_criterion_2_checker_accepts_a_correct_guard(tmp_path: Path) -> None:
    check_first_step_fails_closed(synth(GUARD_OK), "g", tmp_path)


@needs_bash
def test_criterion_2_checker_accepts_a_respelled_guard(tmp_path: Path) -> None:
    alt = GUARD_OK.replace(
        'if [ -z "$WF_REPO" ] || [ -z "$WF_SHA" ]; then',
        '[[ -n "$WF_REPO" && -n "$WF_SHA" ]] || {\n            echo bad',
    ).replace("            exit 1\n          fi\n", "            exit 1\n          }\n")
    check_first_step_fails_closed(synth(alt), "g", tmp_path)


@needs_bash
@pytest.mark.parametrize("name", sorted(GUARD_MUTANTS))
def test_criterion_2_checker_rejects_a_weakened_guard(name: str, tmp_path: Path) -> None:
    with pytest.raises(AssertionError):
        check_first_step_fails_closed(GUARD_MUTANTS[name], "g", tmp_path)


# ------------------------------------------ criterion 1: green report, exit 1


def exam_command_step(text: str) -> dict[str, Any]:
    cands = [s for s in steps_of(text, "exam") if "TEST_COMMAND" in str(s.get("run", ""))]
    assert len(cands) == 1, "the exam job needs exactly one step that runs TEST_COMMAND"
    return cands[0]


def gate_result_for(text: str, command: str, workdir: Path) -> tuple[int, int]:
    """Run the exam step with the command, then (as Actions does) hand the exam job's
    result to the gate job and run the gate's run steps with the report in place.
    Returns (exam exit code, gate exit code)."""
    exam_dir = workdir / "exam"
    exam_dir.mkdir()
    values = {
        "inputs.test-command": command,
        "inputs.junit-file": "acceptance.xml",
        "job.workflow_repository": REPO,
        "job.workflow_sha": SHA,
    }
    step = exam_command_step(text)
    assert plain(step), "the exam command step can be skipped or its failure ignored"
    exam_rc = run_step(step, values, exam_dir, "exam")
    result = "success" if exam_rc == 0 else "failure"
    gate_dir = workdir / "gate"
    gate_dir.mkdir()
    (gate_dir / "report").mkdir()
    # the report the exam wrote is uploaded (if: !cancelled()) and downloaded by the gate
    report = exam_dir / "acceptance.xml"
    assert report.is_file(), "the exam command did not write its report"
    shutil.copy(report, gate_dir / "report" / "acceptance.xml")
    values["needs.exam.result"] = result
    gate_rc = 0
    for n, s in enumerate(steps_of(text, "gate")):
        if "run" not in s:
            continue
        gate_rc = run_step(s, values, gate_dir, f"gate{n}")
        if gate_rc != 0:
            break
    return exam_rc, gate_rc


PASSING_REPORT = "printf '<testsuites><testsuite tests=\"1\"/></testsuites>' > acceptance.xml"


def check_green_report_then_exit_1_is_red(text: str, workdir: Path) -> None:
    exam_rc, gate_rc = gate_result_for(text, f"{PASSING_REPORT}; exit 1", workdir / "bad")
    assert exam_rc != 0, "the exam step does not fail when its command exits 1"
    assert gate_rc != 0, "the gate is green after a passing report and an exam command exit 1"
    exam_rc, gate_rc = gate_result_for(text, PASSING_REPORT, workdir / "ok")
    assert exam_rc == 0 and gate_rc == 0, "the gate is red for a passing report and exit 0"


@needs_bash
def test_criterion_1_passing_report_then_exam_exit_1_leaves_the_gate_red(tmp_path: Path) -> None:
    (tmp_path / "bad").mkdir()
    (tmp_path / "ok").mkdir()
    check_green_report_then_exit_1_is_red(workflow_text(GATE), tmp_path)


def test_criterion_1_the_gate_job_depends_on_the_exam_job() -> None:
    data = yaml.safe_load(workflow_text(GATE))
    needs = data["jobs"]["gate"].get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert "exam" in needs, "the gate job does not wait for the exam job"


CRIT1_MUTANTS = {
    "result_ignored": lambda t: t.replace('"$EXAM_RESULT" != "success"', '"$EXAM_RESULT" = "x"'),
    "exam_continue_on_error": lambda t: t.replace(
        '        run: bash -c "$TEST_COMMAND"',
        '        continue-on-error: true\n        run: bash -c "$TEST_COMMAND"',
    ),
    "exam_swallows_exit": lambda t: t.replace(
        'run: bash -c "$TEST_COMMAND"', 'run: bash -c "$TEST_COMMAND" || true'
    ),
}


@needs_bash
@pytest.mark.parametrize("name", sorted(CRIT1_MUTANTS))
def test_criterion_1_checker_rejects_a_weakened_workflow(name: str, tmp_path: Path) -> None:
    mutated = CRIT1_MUTANTS[name](workflow_text(GATE))
    assert mutated != workflow_text(GATE), "the mutation did not apply"
    (tmp_path / "bad").mkdir()
    (tmp_path / "ok").mkdir()
    with pytest.raises(AssertionError):
        check_green_report_then_exit_1_is_red(mutated, tmp_path)


# ------------------------------------------------ criterion 3: docs/ci.md


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip()]


NEGATION = re.compile(r"\b(not|fails?|blocks?|red)\b", re.I)


def check_caller_if_docs(text: str) -> None:
    sents = sentences(text)
    skips_gate = [
        s
        for s in sents
        if "if:" in s
        and re.search(r"caller", s, re.I)
        and re.search(r"\bskip", s, re.I)
        and re.search(r"\bgate\b", s, re.I)
        and re.search(r"\b(whole|entire|all of|the call)\b", s, re.I)
        and not NEGATION.search(s)
    ]
    assert skips_gate, (
        "docs/ci.md does not say that a caller-level `if:` that skips the whole call "
        "also skips the gate"
    )
    passes = [
        s
        for s in sents
        if re.search(r"skipped required (status )?check", s, re.I)
        and re.search(r"\b(passes|passed|pass)\b", s, re.I)
        and not NEGATION.search(s)
    ]
    assert passes, "docs/ci.md does not say that a skipped required check passes"


def test_criterion_3_docs_say_a_caller_level_if_skips_the_gate_too() -> None:
    assert DOC.is_file(), "docs/ci.md does not exist"
    check_caller_if_docs(DOC.read_text(encoding="utf-8"))


GOOD_DOC = (
    "A caller-level `if:` that skips the whole call also skips the gate. "
    "A skipped required check passes, so never put an `if:` on the caller job.\n"
)


def test_criterion_3_checker_accepts_a_correct_paragraph() -> None:
    check_caller_if_docs(GOOD_DOC)


def test_criterion_3_checker_accepts_a_respelled_paragraph() -> None:
    check_caller_if_docs(
        "If the caller job has an `if:` that skips the entire call, the gate\nis skipped as well.\n"
        "Branch protection counts a skipped required check as passed.\n"
    )


@pytest.mark.parametrize(
    "doc",
    [
        "A caller job skipped by its own `if:` shows as the bare caller job name.\n",
        "A caller-level `if:` that skips the whole call also skips the gate.\n",
        "A skipped required check passes.\n",
        "A caller-level `if:` that skips the whole call does not skip the gate. "
        "A skipped required check passes.\n",
        "A caller-level `if:` that skips the whole call also skips the gate. "
        "A skipped required check fails.\n",
        "",
    ],
    ids=["existing_line_only", "no_pass_statement", "no_if_statement", "gate_not_skipped",
         "skipped_fails", "empty"],
)
def test_criterion_3_checker_rejects_an_incomplete_paragraph(doc: str) -> None:
    with pytest.raises(AssertionError):
        check_caller_if_docs(doc)
