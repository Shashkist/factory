"""Issue #67: the exam pins the round-2 hardening of the reusable workflows.

Each criterion is a function check_X(yaml_text) that raises AssertionError on a
weakened workflow. A case runs it on the shipped file; a mutation case applies
the weakening the criterion names to a copy of the text and asserts that the
check rejects it, so the pin cannot go slack unnoticed.
"""

import re
from typing import Any

import pytest
import yaml
from helpers import workflow_text

GATE = "junit-gate.yml"
INTEGRITY = "exam-integrity.yml"
JUDGES = {GATE: "junit_gate", INTEGRITY: "exam_integrity"}


def parse(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "not a YAML mapping"
    return data


def job(text: str, name: str) -> dict[str, Any]:
    jobs = parse(text).get("jobs") or {}
    assert name in jobs, f"no job {name!r}"
    return jobs[name]


def script_lines(run: str) -> list[str]:
    """Commands of a run script: comments dropped, line continuations joined."""
    lines = [ln for ln in run.splitlines() if not ln.strip().startswith("#")]
    joined = re.sub(r"\\\n\s*", " ", "\n".join(lines))
    return [ln.strip() for ln in joined.splitlines() if ln.strip()]


def judge_step(text: str, fname: str) -> dict[str, Any]:
    wf = parse(text)
    found = [
        s
        for j in (wf.get("jobs") or {}).values()
        for s in (j.get("steps") or [])
        if JUDGES[fname] in str(s.get("run", ""))
    ]
    assert len(found) == 1, f"expected one step running {JUDGES[fname]}, got {len(found)}"
    return found[0]


# 1. the judge is the last command of its step and runs as /usr/bin/python3 -I
def check_judge_last_and_isolated(text: str, fname: str) -> None:
    step = judge_step(text, fname)
    assert not step.get("continue-on-error"), "judge step has continue-on-error"
    last = script_lines(step["run"])[-1]
    m = re.match(
        r"^/usr/bin/python3 -I\s+(\S*" + JUDGES[fname] + r"\.py)(?P<rest>.*)$", last
    )
    assert m, f"the judge is not the last command as '/usr/bin/python3 -I': {last!r}"
    rest = m.group("rest")
    assert not re.search(r"\|\||;|&|\|", rest), f"something follows the judge: {rest!r}"


@pytest.mark.parametrize("fname", [GATE, INTEGRITY])
def test_criterion_1_judge_is_last_command_and_runs_as_python3_dash_i(fname: str) -> None:
    check_judge_last_and_isolated(workflow_text(fname), fname)


JUDGE_LINE = {
    GATE: "/usr/bin/python3 -I .factory-tools/src/factory_tools/ci/junit_gate.py"
    ' "report/${JUNIT_FILE##*/}"',
    INTEGRITY: "/usr/bin/python3 -I .factory-tools/src/factory_tools/ci/exam_integrity.py"
    ' "origin/$BASE_REF" "$HEAD_SHA" "${args[@]}"',
}


@pytest.mark.parametrize("fname", [GATE, INTEGRITY])
@pytest.mark.parametrize("weaken", ["exit0", "or_true", "semi_true", "no_dash_i", "bare_python"])
def test_criterion_1_mutation_is_rejected(fname: str, weaken: str) -> None:
    text = workflow_text(fname)
    line = JUDGE_LINE[fname]
    assert line in text
    new = {
        "exit0": line + "; exit 0",
        "or_true": line + " || true",
        "semi_true": line + "; true",
        "no_dash_i": line.replace("python3 -I", "python3"),
        "bare_python": line.replace("/usr/bin/python3 -I", "python3 -I"),
    }[weaken]
    with pytest.raises(AssertionError):
        check_judge_last_and_isolated(text.replace(line, new), fname)


# 2. exam integrity still checks that origin/<base> exists
def check_base_ref_verified(text: str) -> None:
    step = judge_step(text, INTEGRITY)
    lines = script_lines(step["run"])
    idx = [
        i
        for i, ln in enumerate(lines)
        if "rev-parse" in ln and re.search(r"origin/\$\{?BASE_REF\}?", ln)
    ]
    assert idx, "no git rev-parse check of origin/$BASE_REF"
    judge = max(i for i, ln in enumerate(lines) if "exam_integrity" in ln)
    assert idx[0] < judge, "the origin/$BASE_REF check comes after the judge"
    after = lines[idx[0] + 1 : idx[0] + 4]
    assert any(re.search(r"\bexit 1\b", ln) for ln in after), "a missing base does not fail"


def test_criterion_2_exam_integrity_checks_that_origin_base_exists() -> None:
    check_base_ref_verified(workflow_text(INTEGRITY))


def test_criterion_2_mutation_is_rejected() -> None:
    text = workflow_text(INTEGRITY)
    block = re.search(r"          if ! git rev-parse --verify.*?\n          fi\n", text, re.S)
    assert block
    with pytest.raises(AssertionError):
        check_base_ref_verified(text.replace(block.group(0), ""))
    with pytest.raises(AssertionError):  # the check stays but no longer fails
        check_base_ref_verified(
            text.replace(block.group(0), block.group(0).replace("exit 1", "true"))
        )


# 3. the gate job runs always(), not !cancelled()
def check_gate_always(text: str) -> None:
    cond = job(text, "gate").get("if")
    assert isinstance(cond, str), "the gate job has no if"
    norm = re.sub(r"\s+", "", cond)
    m = re.fullmatch(r"\$\{\{(.*)\}\}", norm)
    if m:
        norm = m.group(1)
    assert norm == "always()", f"gate if is {cond!r}, not always()"


def test_criterion_3_gate_job_is_always() -> None:
    check_gate_always(workflow_text(GATE))


def test_criterion_3_mutation_is_rejected() -> None:
    text = workflow_text(GATE)
    good = "if: ${{ always() }}"
    assert good in text
    for weak in ("if: ${{ !cancelled() }}", "if: ${{ success() }}", "if: always() && false"):
        with pytest.raises(AssertionError):
            check_gate_always(text.replace(good, weak))
    with pytest.raises(AssertionError):
        check_gate_always(text.replace("    " + good + "\n", ""))
    check_gate_always(text.replace(good, "if: always()"))  # equivalent spelling stays green


# 4. the download name is never empty
def check_download_name_fallback(text: str) -> None:
    steps = job(text, "gate").get("steps") or []
    dl = [s for s in steps if "download-artifact" in str(s.get("uses", ""))]
    assert len(dl) == 1, "expected one download-artifact step in the gate"
    name = str((dl[0].get("with") or {}).get("name", ""))
    assert re.search(r"\|\|\s*'[^']+'\s*\}\}\s*$", name), f"no non-empty fallback: {name!r}"
    assert "needs.exam.outputs.artifact-name" in name


def test_criterion_4_download_name_has_non_empty_fallback() -> None:
    check_download_name_fallback(workflow_text(GATE))


def test_criterion_4_mutation_is_rejected() -> None:
    text = workflow_text(GATE)
    good = "${{ needs.exam.outputs.artifact-name || 'no-exam-report' }}"
    assert good in text
    for weak in (
        "${{ needs.exam.outputs.artifact-name }}",
        "${{ needs.exam.outputs.artifact-name || '' }}",
    ):
        with pytest.raises(AssertionError):
            check_download_name_fallback(text.replace(good, weak))


# 5. the gate fails unless needs.exam.result is success
def check_gate_requires_exam_success(text: str) -> None:
    for step in job(text, "gate").get("steps") or []:
        run = step.get("run")
        if not run:
            continue
        env = step.get("env") or {}
        names = [k for k, v in env.items() if "needs.exam.result" in str(v)]
        refs = [f"${k}" for k in names] + [f"${{{k}}}" for k in names]
        if "needs.exam.result" in run:
            refs.append("needs.exam.result")
        lines = script_lines(run)
        for i, ln in enumerate(lines):
            if not ln.startswith("if "):
                continue
            ok_ref = any(r in ln for r in refs)
            neg = re.search(r"!=\s*[\"']?success[\"']?", ln)
            fails = any(re.search(r"\bexit 1\b", x) for x in lines[i + 1 : i + 4])
            if ok_ref and neg and fails:
                return
    raise AssertionError("the gate does not fail unless needs.exam.result is success")


def test_criterion_5_gate_fails_unless_exam_result_is_success() -> None:
    check_gate_requires_exam_success(workflow_text(GATE))


def test_criterion_5_mutation_is_rejected() -> None:
    text = workflow_text(GATE)
    block = re.search(
        r'          if \[ "\$EXAM_RESULT" != "success" \]; then\n.*?\n          fi\n', text, re.S
    )
    assert block
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(text.replace(block.group(0), ""))
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(text.replace('!= "success"', '!= "failure"'))
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(
            text.replace(block.group(0), block.group(0).replace("exit 1", "true", 1))
        )
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(
            text.replace("${{ needs.exam.result }}", "success")
        )


# 6. PYTEST_DISABLE_PLUGIN_AUTOLOAD defaults on through the input
DEFAULT_TRUE = "        default: true" + chr(10)
AUTOLOAD_EXPR = "${{ inputs.disable-pytest-plugin-autoload && '1' || '' }}"


def check_autoload_default_on(text: str) -> None:
    wf = parse(text)
    on = wf["on"] if "on" in wf else wf.get(True)
    inp = on["workflow_call"]["inputs"].get("disable-pytest-plugin-autoload")
    assert inp, "no disable-pytest-plugin-autoload input"
    assert inp.get("type") == "boolean"
    assert inp.get("default") is True, "the input does not default to true"
    env = job(text, "exam").get("env") or {}
    value = str(env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", ""))
    assert "inputs.disable-pytest-plugin-autoload" in value, f"env not tied to input: {value!r}"
    assert "'1'" in value or '"1"' in value, "env never yields 1"


def test_criterion_6_pytest_plugin_autoload_is_disabled_by_default_through_the_input() -> None:
    check_autoload_default_on(workflow_text(GATE))


def test_criterion_6_mutation_is_rejected() -> None:
    text = workflow_text(GATE)
    assert AUTOLOAD_EXPR in text
    assert "        default: true\n" in text
    with pytest.raises(AssertionError):
        check_autoload_default_on(
            text.replace(DEFAULT_TRUE, DEFAULT_TRUE.replace("true", "false"))
        )
    for weak in ("''", "${{ inputs.disable-pytest-plugin-autoload }}"):
        with pytest.raises(AssertionError):
            check_autoload_default_on(text.replace(AUTOLOAD_EXPR, weak))
    with pytest.raises(AssertionError):
        check_autoload_default_on(
            text.replace("      disable-pytest-plugin-autoload:", "      other-input:")
        )
