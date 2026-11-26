"""Issue #67: the exam pins the round-2 hardening of the reusable workflows.

Each criterion is a function check_X(yaml_text) that raises AssertionError on a
weakened workflow. A case runs it on the shipped file; a mutation case applies
the weakening to a copy of the text and asserts that the check rejects it; a
"stays green" case applies a safe respelling and asserts the check accepts it.
Run scripts are parsed statement by statement, not matched by proximity.
"""

import re
from typing import Any

import pytest
import yaml
from helpers import workflow_text

GATE = "junit-gate.yml"
INTEGRITY = "exam-integrity.yml"
JUDGES = {GATE: "junit_gate", INTEGRITY: "exam_integrity"}
BOTH = [GATE, INTEGRITY]


# ---------------------------------------------------------------- helpers


def parse(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "not a YAML mapping"
    return data


def job(text: str, name: str) -> dict[str, Any]:
    jobs = parse(text).get("jobs") or {}
    assert name in jobs, f"no job {name!r}"
    return jobs[name]


def truthy(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in ("", "false")


def squash(value: Any) -> str:
    return re.sub(r"\s+", "", str(value))


def strip_comment(line: str) -> str:
    """Drop a trailing shell comment (a # outside quotes, at a word start)."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line


def script_lines(run: str) -> list[str]:
    """Logical lines of a run script: comments dropped, continuations joined, and a
    `then` on its own line appended to the line above it."""
    joined = re.sub(r"\\\n\s*", " ", run)
    out: list[str] = []
    for raw in joined.splitlines():
        ln = strip_comment(raw.strip()).strip()
        if not ln:
            continue
        if ln == "then" and out:
            out[-1] += "; then"
        else:
            out.append(ln)
    return out


def unquote(s: str) -> str:
    """Quoted strings emptied, so echo text is never read as a command."""
    return re.sub(r"\"[^\"]*\"|'[^']*'", '""', s)


def split_semicolons(line: str) -> list[str]:
    parts, cur, quote = [], "", ""
    for ch in line:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ";":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def statements(lines: list[str]) -> list[str]:
    """Flat statements: split on `;`, `then`/`do` dropped from the front."""
    out = []
    for ln in lines:
        for part in split_semicolons(ln):
            part = re.sub(r"^(?:then|do)\b\s*", "", part)
            if part:
                out.append(part)
    return out


OPENERS = re.compile(r"(?:if|case|for|while|until)\b")
CLOSERS = re.compile(r"(?:fi|done|esac)\b")


def top_level_exit_codes(stmts: list[str], k: int) -> list[int]:
    """Exit codes of statements that run unconditionally in the main branch of the
    `if` at index k: nested if/case/loops and elif/else branches are skipped."""
    depth, alt, codes = 1, False, []
    for st in stmts[k + 1 :]:
        if CLOSERS.match(st):
            depth -= 1
            if depth == 0:
                return codes
            continue
        if depth == 1 and re.match(r"(?:elif|else)\b", st):
            alt = True
            continue
        if OPENERS.match(st):
            depth += 1
            continue
        if depth != 1 or alt:
            continue
        chain = [c.strip() for c in unquote(st).split("&&")]
        if all(re.match(r"(?:echo|printf|true)\b", c) for c in chain[:-1]):
            m = re.fullmatch(r"exit(?:\s+(\d+))?", chain[-1])
            if m:
                codes.append(int(m.group(1) or 0))
    raise AssertionError("an if without its fi")


def fails_at_top_level(stmts: list[str], k: int) -> bool:
    codes = top_level_exit_codes(stmts, k)
    return any(c != 0 for c in codes) and 0 not in codes


def tail_exits_nonzero(tail: str) -> bool:
    t = unquote(tail).strip()
    return bool(re.fullmatch(r"exit\s+[1-9]\d*|\{.*\bexit\s+[1-9]\d*\s*;?\s*\}", t))


def swallows_before(chunks: list[str]) -> str | None:
    """A trap, `exit 0` or bare `exit` in the given script text (or None)."""
    for ch in chunks:
        flat = unquote(ch)
        if re.search(r"\btrap\b", flat):
            return f"trap before the check: {ch!r}"
        if re.search(r"(?<![\w-])exit(?:\s+0+\b|\s*(?:;|$|\}|&|\|))", flat):
            return f"an exit 0 or bare exit before the check: {ch!r}"
    return None


def run_steps(text: str, jname: str | None = None) -> list[dict[str, Any]]:
    jobs = parse(text).get("jobs") or {}
    names = [jname] if jname else list(jobs)
    return [s for n in names for s in (jobs[n].get("steps") or []) if s.get("run")]


# ------------------------------------------- 1. the judge is last and isolated


def judge_step(text: str, fname: str) -> dict[str, Any]:
    pat = re.compile(r"\b" + JUDGES[fname] + r"\.py\b")
    found = [s for s in run_steps(text) if any(pat.search(ln) for ln in script_lines(s["run"]))]
    assert len(found) == 1, f"expected one step running {JUDGES[fname]}.py, got {len(found)}"
    return found[0]


def check_judge_last_and_isolated(text: str, fname: str) -> None:
    step = judge_step(text, fname)
    for key in ("if", "shell"):
        assert key not in step, f"judge step has {key}:"
    assert not truthy(step.get("continue-on-error")), "judge step has continue-on-error"
    lines = script_lines(step["run"])
    last = lines[-1]
    m = re.match(
        r"^(?:exec\s+)?/usr/bin/python3((?:\s+-[A-Za-z]+)*)\s+\S*"
        + JUDGES[fname]
        + r"\.py(?P<rest>.*)$",
        last,
    )
    assert m, f"the judge is not the last command, as /usr/bin/python3: {last!r}"
    assert any("I" in f for f in m.group(1).split()), f"python runs without -I: {last!r}"
    rest = re.sub(r"\s2>&1\b", "", m.group("rest"))
    assert not re.search(r"\|\||;|&|\|", rest), f"something follows the judge: {rest!r}"
    for ln in lines[:-1]:
        flat = unquote(ln)
        assert not re.search(r"\btrap\b", flat), f"trap before the judge: {ln!r}"
        assert not re.search(r"(?<![\w-])exit(?:\s+0+\b|\s*(?:;|$|\}))", flat), (
            f"an exit 0 or bare exit before the judge: {ln!r}"
        )


@pytest.mark.parametrize("fname", BOTH)
def test_criterion_1_judge_is_last_command_and_runs_as_python3_dash_i(fname: str) -> None:
    check_judge_last_and_isolated(workflow_text(fname), fname)


JUDGE_LINE = {
    GATE: "/usr/bin/python3 -I .factory-tools/src/factory_tools/ci/junit_gate.py"
    ' "report/${JUNIT_FILE##*/}"',
    INTEGRITY: "/usr/bin/python3 -I .factory-tools/src/factory_tools/ci/exam_integrity.py"
    ' "origin/$BASE_REF" "$HEAD_SHA" "${args[@]}"',
}
GATE_RUN = "        run: " + JUDGE_LINE[GATE]
INTEGRITY_RUN = '        run: |\n          if [ -z "$HEAD_SHA" ]; then\n'


def with_before_judge(text: str, fname: str, cmd: str) -> str:
    if fname == GATE:
        assert GATE_RUN in text
        return text.replace(GATE_RUN, "        run: |\n          " + cmd + "\n          "
                            + JUDGE_LINE[GATE])
    assert INTEGRITY_RUN in text
    return text.replace(
        INTEGRITY_RUN,
        "        run: |\n          " + cmd + '\n          if [ -z "$HEAD_SHA" ]; then\n',
    )


def with_step_key(text: str, fname: str, key: str) -> str:
    run = GATE_RUN if fname == GATE else INTEGRITY_RUN
    assert run in text
    return text.replace(run, "        " + key + "\n" + run, 1)


def respell_judge(text: str, fname: str, new: str) -> str:
    assert JUDGE_LINE[fname] in text
    return text.replace(JUDGE_LINE[fname], new)


@pytest.mark.parametrize("fname", BOTH)
@pytest.mark.parametrize(
    "weaken",
    ["exit0", "or_true", "semi_true", "no_dash_i", "bare_python", "and_true", "pipe_tee"],
)
def test_criterion_1_mutation_is_rejected(fname: str, weaken: str) -> None:
    text, line = workflow_text(fname), JUDGE_LINE[fname]
    new = {
        "exit0": line + "; exit 0",
        "or_true": line + " || true",
        "semi_true": line + "; true",
        "and_true": line + " && true",
        "pipe_tee": line + " | tee /dev/null",
        "no_dash_i": line.replace("python3 -I", "python3"),
        "bare_python": line.replace("/usr/bin/python3 -I", "python3 -I"),
    }[weaken]
    with pytest.raises(AssertionError):
        check_judge_last_and_isolated(respell_judge(text, fname, new), fname)


@pytest.mark.parametrize("fname", BOTH)
@pytest.mark.parametrize("cmd", ["exit 0", "exit", "trap 'exit 0' EXIT", "trap : EXIT"])
def test_criterion_1_early_exit_or_trap_is_rejected(fname: str, cmd: str) -> None:
    text = with_before_judge(workflow_text(fname), fname, cmd)
    with pytest.raises(AssertionError):
        check_judge_last_and_isolated(text, fname)


@pytest.mark.parametrize("fname", BOTH)
@pytest.mark.parametrize(
    "key",
    ["if: false", "if: ${{ always() && false }}", "shell: bash {0}", "continue-on-error: true"],
)
def test_criterion_1_step_level_swallow_is_rejected(fname: str, key: str) -> None:
    with pytest.raises(AssertionError):
        check_judge_last_and_isolated(with_step_key(workflow_text(fname), fname, key), fname)


@pytest.mark.parametrize("fname", BOTH)
@pytest.mark.parametrize(
    "respell",
    [
        lambda ln: ln + " 2>&1",
        lambda ln: "exec " + ln,
        lambda ln: ln.replace("python3 -I", "python3 -I -S"),
        lambda ln: ln.replace("python3 -I", "python3 -S -I"),
    ],
    ids=["stderr", "exec", "extra-flag", "flag-first"],
)
def test_criterion_1_safe_spelling_stays_green(fname: str, respell: Any) -> None:
    text = respell_judge(workflow_text(fname), fname, respell(JUDGE_LINE[fname]))
    check_judge_last_and_isolated(text, fname)


@pytest.mark.parametrize("fname", BOTH)
def test_criterion_1_comment_naming_the_judge_elsewhere_stays_green(fname: str) -> None:
    text = workflow_text(fname)
    if fname == GATE:
        marker = '          if [ ! -f "report/${JUNIT_FILE##*/}" ]; then'
        new = "          # junit_gate.py judges later\n" + marker
    else:
        marker = '          if [ -z "$HEAD_SHA" ]; then'
        new = "          # runs exam_integrity.py last\n" + marker
    assert marker in text
    check_judge_last_and_isolated(text.replace(marker, new, 1), fname)


# ------------------------------------ 2. exam integrity checks origin/<base>


def check_base_ref_verified(text: str) -> None:
    lines = script_lines(judge_step(text, INTEGRITY)["run"])
    stmts = statements(lines)
    judge = max(i for i, st in enumerate(stmts) if "exam_integrity.py" in st)
    ref = r"\"?(?:refs/remotes/)?origin/\$(?:BASE_REF|\{BASE_REF\})\"?"
    git = r"git\s+(?:rev-parse|show-ref)(?:\s+(?:--verify|-q|--quiet))*\s+" + ref
    redirs = r"(?:\s*>\s*/dev/null)?(?:\s*2>&1)?"
    if_form = re.compile(r"if\s+!\s+" + git + redirs)
    or_form = re.compile(git + redirs + r"\s*\|\|\s*(.*)")
    for i, st in enumerate(stmts[:judge]):
        if if_form.fullmatch(st) and fails_at_top_level(stmts, i):
            return
    for ln in lines[: max(i for i, x in enumerate(lines) if "exam_integrity.py" in x)]:
        m = or_form.fullmatch(ln)
        if m and tail_exits_nonzero(m.group(1)):
            return
    raise AssertionError("no check of origin/$BASE_REF that fails the step")


BASE_BLOCK = re.compile(r"          if ! git rev-parse --verify.*?\n          fi\n", re.S)


def base_block(text: str) -> str:
    m = BASE_BLOCK.search(text)
    assert m
    return m.group(0)


def test_criterion_2_exam_integrity_checks_that_origin_base_exists() -> None:
    check_base_ref_verified(workflow_text(INTEGRITY))


@pytest.mark.parametrize(
    "name",
    ["removed", "exit_to_true", "exit_to_warning", "exit_in_echo", "exit_zero", "after_judge"],
)
def test_criterion_2_mutation_is_rejected(name: str) -> None:
    text = workflow_text(INTEGRITY)
    blk = base_block(text)
    new = {
        "removed": "",
        "exit_to_true": blk.replace("exit 1", "true"),
        "exit_to_warning": blk.replace("exit 1", 'echo "::warning::no base"'),
        "exit_in_echo": blk.replace("            exit 1", '            echo "then exit 1"'),
        "exit_zero": blk.replace("exit 1", "exit 0"),
    }
    if name == "after_judge":
        # the check moved below the judge: it can no longer stop it
        mutated = text.replace(blk, "").rstrip("\n") + "\n" + blk
    else:
        mutated = text.replace(blk, new[name])
    assert mutated != text
    with pytest.raises(AssertionError):
        check_base_ref_verified(mutated)


@pytest.mark.parametrize(
    "respell",
    [
        lambda b: b.replace("exit 1", "exit 2"),
        lambda b: b.replace(
            'git rev-parse --verify -q "origin/$BASE_REF"',
            'git show-ref --verify -q "refs/remotes/origin/$BASE_REF"',
        ),
        lambda b: '          git rev-parse --verify -q "origin/$BASE_REF" > /dev/null || exit 1\n',
        lambda b: '          git rev-parse --verify -q "origin/$BASE_REF" > /dev/null'
        ' || { echo "::error::no base"; exit 3; }\n',
    ],
    ids=["exit2", "show-ref", "or-exit", "or-brace-exit"],
)
def test_criterion_2_safe_spelling_stays_green(respell: Any) -> None:
    text = workflow_text(INTEGRITY)
    blk = base_block(text)
    check_base_ref_verified(text.replace(blk, respell(blk)))


# ------------------------------------------ 3. the gate job runs always()


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


# ------------------------------------------ 4. the download name is never empty


def check_download_name_fallback(text: str) -> None:
    steps = job(text, "gate").get("steps") or []
    dl = [s for s in steps if "download-artifact" in str(s.get("uses", ""))]
    assert len(dl) == 1, "expected one download-artifact step in the gate"
    name = str((dl[0].get("with") or {}).get("name", ""))
    assert re.search(r"\|\|\s*'[^'\s][^']*'\s*\}\}\s*$", name), f"no non-empty fallback: {name!r}"
    assert "needs.exam.outputs.artifact-name" in name


def test_criterion_4_download_name_has_non_empty_fallback() -> None:
    check_download_name_fallback(workflow_text(GATE))


GOOD_NAME = "${{ needs.exam.outputs.artifact-name || 'no-exam-report' }}"


@pytest.mark.parametrize(
    "weak",
    [
        "${{ needs.exam.outputs.artifact-name }}",
        "${{ needs.exam.outputs.artifact-name || '' }}",
        "${{ needs.exam.outputs.artifact-name || ' ' }}",
    ],
    ids=["no-fallback", "empty-fallback", "blank-fallback"],
)
def test_criterion_4_mutation_is_rejected(weak: str) -> None:
    text = workflow_text(GATE)
    assert GOOD_NAME in text
    with pytest.raises(AssertionError):
        check_download_name_fallback(text.replace(GOOD_NAME, weak))


# ------------------------------------ 5. the gate fails unless the exam succeeded


def step_if_is_always(value: Any) -> bool:
    m = re.fullmatch(r"\$\{\{(.*)\}\}", squash(value))
    return (m.group(1) if m else squash(value)) == "always()"


def check_gate_requires_exam_success(text: str) -> None:
    for step in job(text, "gate").get("steps") or []:
        if not step.get("run"):
            continue
        env = step.get("env") or {}
        names = [k for k, v in env.items() if squash(v) == "${{needs.exam.result}}"]
        if not names or truthy(step.get("continue-on-error")):
            continue
        if "if" in step and not step_if_is_always(step["if"]):
            continue
        lines = script_lines(step["run"])
        stmts = statements(lines)
        for var in names:
            flat = unquote("\n".join(lines))
            if re.search(r"(?<![\w$])" + var + r"\+?=", flat):
                continue
            if re.search(
                r"\b(?:unset|export|read|declare|local|typeset|readonly|for)\b[^;\n]*\b"
                + var
                + r"\b",
                flat,
            ):
                continue
            if re.search(r"\bprintf\s+-v\s+" + var + r"\b", flat):
                continue
            ref = r"\"?\$(?:" + var + r"|\{" + var + r"\})\"?"
            val = r"[\"']?success[\"']?"
            tests = (  # a test that is false when the result is not success
                (r"\[\s+" + ref + r"\s+!=\s+" + val + r"\s+\]"),
                (r"\[\[\s+" + ref + r"\s+!=\s+" + val + r"\s+\]\]"),
                (r"test\s+" + ref + r"\s+!=\s+" + val),
            )
            ok_tests = (  # a test that is true when the result is success
                (r"\[\s+" + ref + r"\s+==?\s+" + val + r"\s+\]"),
                (r"\[\[\s+" + ref + r"\s+==?\s+" + val + r"\s+\]\]"),
                (r"test\s+" + ref + r"\s+==?\s+" + val),
            )
            neg = re.compile(r"if\s+(?:" + "|".join(tests) + ")")
            inv = re.compile(r"(?:" + "|".join(ok_tests) + r")\s*\|\|\s*(.*)")
            for i, st in enumerate(stmts):
                if neg.fullmatch(st) and fails_at_top_level(stmts, i):
                    if swallows_before(stmts[:i]) is None:
                        return
            for i, ln in enumerate(lines):
                m = inv.fullmatch(ln)
                if m and tail_exits_nonzero(m.group(1)) and swallows_before(lines[:i]) is None:
                    return
    raise AssertionError("the gate does not fail unless needs.exam.result is success")


def test_criterion_5_gate_fails_unless_exam_result_is_success() -> None:
    check_gate_requires_exam_success(workflow_text(GATE))


RESULT_BLOCK = re.compile(
    r'          if \[ "\$EXAM_RESULT" != "success" \]; then\n.*?\n          fi\n', re.S
)
RESULT_COND = '          if [ "$EXAM_RESULT" != "success" ]; then\n'
RESULT_STEP = "      - name: Require the report\n"
RESULT_ENV = "          EXAM_RESULT: ${{ needs.exam.result }}\n"


def result_block(text: str) -> str:
    m = RESULT_BLOCK.search(text)
    assert m
    return m.group(0)


def cond(new: str) -> str:
    return "          if " + new + "; then\n"


@pytest.mark.parametrize(
    "name",
    [
        "removed",
        "and_other_test",
        "and_false",
        "or_true",
        "warning_only",
        "exit_zero",
        "exit_in_echo",
        "inverted_wrong_value",
        "continue_on_error",
        "step_if_false",
        "env_expression",
        "env_hardcoded",
        "wrong_variable",
    ],
)
def test_criterion_5_mutation_is_rejected(name: str) -> None:
    text = workflow_text(GATE)
    blk = result_block(text)
    mutated = {
        "removed": text.replace(blk, ""),
        "and_other_test": text.replace(
            RESULT_COND, cond('[ "$EXAM_RESULT" != "success" ] && [ "$EXAM_RESULT" != "failure" ]')
        ),
        "and_false": text.replace(RESULT_COND, cond('[ "$EXAM_RESULT" != "success" ] && false')),
        "or_true": text.replace(RESULT_COND, cond('[ "$EXAM_RESULT" != "success" ] || true')),
        "warning_only": text.replace(blk, blk.replace("exit 1", "true", 1)),
        "exit_zero": text.replace(blk, blk.replace("exit 1", "exit 0", 1)),
        "exit_in_echo": text.replace(blk, blk.replace("exit 1", 'echo "exit 1"', 1)),
        "inverted_wrong_value": text.replace(
            blk, '          [ "$EXAM_RESULT" = failure ] || exit 1\n'
        ),
        "continue_on_error": text.replace(
            RESULT_STEP, RESULT_STEP + "        continue-on-error: true\n"
        ),
        "step_if_false": text.replace(RESULT_STEP, RESULT_STEP + "        if: false\n"),
        "env_expression": text.replace(
            RESULT_ENV,
            "          EXAM_RESULT: ${{ needs.exam.result == 'x' && 'f' || 'success' }}\n",
        ),
        "env_hardcoded": text.replace(RESULT_ENV, "          EXAM_RESULT: success\n"),
        "wrong_variable": text.replace(RESULT_COND, cond('[ "$JUNIT_FILE" != "success" ]')),
    }[name]
    assert mutated != text
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(mutated)


@pytest.mark.parametrize(
    "respell",
    [
        lambda t, b: t.replace(RESULT_COND, cond('[[ "$EXAM_RESULT" != "success" ]]')),
        lambda t, b: t.replace(RESULT_COND, cond("[ $EXAM_RESULT != success ]")),
        lambda t, b: t.replace(RESULT_COND, cond('[ "${EXAM_RESULT}" != "success" ]')),
        lambda t, b: t.replace(b, b.replace("exit 1", "exit 3", 1)),
        lambda t, b: t.replace(RESULT_ENV, "          EXAM_RESULT: ${{needs.exam.result}}\n"),
        lambda t, b: t.replace(
            b, '          [ "$EXAM_RESULT" = success ] || { echo bad; exit 1; }\n'
        ),
        lambda t, b: t.replace(b, "          [[ $EXAM_RESULT = success ]] || exit 1\n"),
    ],
    ids=["dbl-bracket", "unquoted", "braces", "exit3", "env-spacing", "inverted-brace", "inverted"],
)
def test_criterion_5_safe_spelling_stays_green(respell: Any) -> None:
    text = workflow_text(GATE)
    check_gate_requires_exam_success(respell(text, result_block(text)))


# ------------------------------ 6. plugin autoload is disabled by default

DEFAULT_TRUE = "        default: true" + chr(10)
AUTOLOAD_EXPR = "${{ inputs.disable-pytest-plugin-autoload && '1' || '' }}"
AUTOLOAD_VAR = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
TEST_ENV = "          TEST_COMMAND: ${{ inputs.test-command }}\n"
EXAM_CMD = '        run: bash -c "$TEST_COMMAND"\n'


def check_autoload_default_on(text: str) -> None:
    wf = parse(text)
    on = wf["on"] if "on" in wf else wf.get(True)
    inp = on["workflow_call"]["inputs"].get("disable-pytest-plugin-autoload")
    assert inp, "no disable-pytest-plugin-autoload input"
    assert inp.get("type") == "boolean"
    assert inp.get("default") is True, "the input does not default to true"
    exam = job(text, "exam")
    values = []
    if AUTOLOAD_VAR in (exam.get("env") or {}):
        values.append(exam["env"][AUTOLOAD_VAR])
    for step in exam.get("steps") or []:
        if AUTOLOAD_VAR in (step.get("env") or {}):
            values.append(step["env"][AUTOLOAD_VAR])
        for ln in script_lines(step.get("run") or ""):
            assert AUTOLOAD_VAR not in ln, f"the exam job's script touches the variable: {ln!r}"
    assert values, "PYTEST_DISABLE_PLUGIN_AUTOLOAD is not set in the exam job"
    for v in values:
        assert squash(v) == squash(AUTOLOAD_EXPR), f"env is not the input expression: {v!r}"


def test_criterion_6_pytest_plugin_autoload_is_disabled_by_default_through_the_input() -> None:
    check_autoload_default_on(workflow_text(GATE))


def step_env(value: str) -> str:
    return TEST_ENV + "          " + AUTOLOAD_VAR + ": " + value + "\n"


def script_before_exam(cmd: str) -> str:
    return "        run: |\n          " + cmd + '\n          bash -c "$TEST_COMMAND"\n'


@pytest.mark.parametrize(
    "name",
    [
        "default_false",
        "hardcoded_empty",
        "bare_input",
        "reversed_not",
        "reversed_values",
        "input_renamed",
        "step_override_empty",
        "step_override_reversed",
        "unset",
        "export_empty",
    ],
)
def test_criterion_6_mutation_is_rejected(name: str) -> None:
    text = workflow_text(GATE)
    assert AUTOLOAD_EXPR in text and DEFAULT_TRUE in text and EXAM_CMD in text
    reversed_not = "${{ !inputs.disable-pytest-plugin-autoload && '1' || '' }}"
    mutated = {
        "default_false": text.replace(DEFAULT_TRUE, DEFAULT_TRUE.replace("true", "false")),
        "hardcoded_empty": text.replace(AUTOLOAD_EXPR, "''"),
        "bare_input": text.replace(AUTOLOAD_EXPR, "${{ inputs.disable-pytest-plugin-autoload }}"),
        "reversed_not": text.replace(AUTOLOAD_EXPR, reversed_not),
        "reversed_values": text.replace(
            AUTOLOAD_EXPR, "${{ inputs.disable-pytest-plugin-autoload && '' || '1' }}"
        ),
        "input_renamed": text.replace(
            "      disable-pytest-plugin-autoload:", "      other-input:"
        ),
        "step_override_empty": text.replace(TEST_ENV, step_env("''")),
        "step_override_reversed": text.replace(TEST_ENV, step_env(reversed_not)),
        "unset": text.replace(EXAM_CMD, script_before_exam("unset " + AUTOLOAD_VAR)),
        "export_empty": text.replace(EXAM_CMD, script_before_exam("export " + AUTOLOAD_VAR + "=")),
    }[name]
    assert mutated != text
    with pytest.raises(AssertionError):
        check_autoload_default_on(mutated)


@pytest.mark.parametrize("name", ["whitespace", "step_level_same_expression", "step_level_only"])
def test_criterion_6_safe_spelling_stays_green(name: str) -> None:
    text = workflow_text(GATE)
    job_env = "      " + AUTOLOAD_VAR + ": " + AUTOLOAD_EXPR + "\n"
    assert job_env in text
    mutated = {
        "whitespace": text.replace(
            AUTOLOAD_EXPR, "${{inputs.disable-pytest-plugin-autoload&&'1'||''}}"
        ),
        "step_level_same_expression": text.replace(TEST_ENV, step_env(AUTOLOAD_EXPR)),
        "step_level_only": text.replace(job_env, "").replace(
            TEST_ENV, step_env(AUTOLOAD_EXPR)
        ),
    }[name]
    assert mutated != text
    check_autoload_default_on(mutated)


# ------------------------------- round 2: top-level exits, reassigned result, spellings

IND = "          "
IND2 = "            "


def swap_exit(blk: str, new: str) -> str:
    """The block with its `exit 1` line replaced by new (lines, already indented)."""
    return blk.replace(IND2 + "exit 1\n", new, 1)


NESTED_EXIT = {
    "nested_if": IND2 + 'if [ -n "$CI" ]; then\n' + IND2 + "  exit 1\n" + IND2 + "fi\n",
    "under_elif": IND2 + "true\n" + IND + 'elif [ -n "$CI" ]; then\n' + IND2 + "exit 1\n",
    "under_else": IND2 + "true\n" + IND + "else\n" + IND2 + "exit 1\n",
    "nested_case": IND2 + 'case "$CI" in\n' + IND2 + "  x) exit 1 ;;\n" + IND2 + "esac\n",
    "nested_loop": IND2 + "for i in 1; do\n" + IND2 + "  exit 1\n" + IND2 + "done\n",
}


@pytest.mark.parametrize("name", list(NESTED_EXIT))
def test_criterion_5_exit_that_is_not_top_level_is_rejected(name: str) -> None:
    text = workflow_text(GATE)
    blk = result_block(text)
    mutated = text.replace(blk, swap_exit(blk, NESTED_EXIT[name]))
    assert mutated != text
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(mutated)


RESULT_REWRITES = {
    "assign_before": IND + "EXAM_RESULT=success\n",
    "assign_quoted": IND + 'EXAM_RESULT="success"\n',
    "export_before": IND + "export EXAM_RESULT=success\n",
    "unset_before": IND + "unset EXAM_RESULT\n",
    "read_before": IND + "read -r EXAM_RESULT < /dev/null\n",
    "declare_before": IND + "declare EXAM_RESULT=success\n",
    "local_before": IND + "local EXAM_RESULT=success\n",
    "printf_v": IND + "printf -v EXAM_RESULT success\n",
}


@pytest.mark.parametrize("name", list(RESULT_REWRITES))
def test_criterion_5_reassigned_result_is_rejected(name: str) -> None:
    text = workflow_text(GATE)
    blk = result_block(text)
    mutated = text.replace(blk, RESULT_REWRITES[name] + blk)
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(mutated)
    after = text.replace(blk, blk + RESULT_REWRITES[name])  # anywhere in the script
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(after)


EARLY_EXITS = [
    "exit 0",
    "exit",
    "trap 'exit 0' EXIT",
    "trap : EXIT",
    '[ -n "$CI" ] && exit 0',
    'if [ -n "$CI" ]; then exit 0; fi',
    "true && exit 0",
]


@pytest.mark.parametrize("cmd", EARLY_EXITS)
def test_criterion_5_early_exit_or_trap_before_the_check_is_rejected(cmd: str) -> None:
    text = workflow_text(GATE)
    blk = result_block(text)
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(text.replace(blk, IND + cmd + "\n" + blk))


@pytest.mark.parametrize(
    "name",
    ["mismatched_close", "mismatched_open", "step_if_failure", "step_if_success"],
)
def test_criterion_5_other_round_2_mutations_are_rejected(name: str) -> None:
    text = workflow_text(GATE)
    mutated = {
        "mismatched_close": text.replace(RESULT_COND, cond('[ "$EXAM_RESULT" != "success" ]]')),
        "mismatched_open": text.replace(RESULT_COND, cond('[[ "$EXAM_RESULT" != "success" ]')),
        "step_if_failure": text.replace(RESULT_STEP, RESULT_STEP + "        if: failure()\n"),
        "step_if_success": text.replace(
            RESULT_STEP, RESULT_STEP + "        if: ${{ success() }}\n"
        ),
    }[name]
    assert mutated != text
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(mutated)


@pytest.mark.parametrize(
    "respell",
    [
        lambda t, b: t.replace(b, swap_exit(b, IND2 + "exit 1  # fail the gate\n")),
        lambda t, b: t.replace(b, swap_exit(b, IND2 + "echo bye && exit 1\n")),
        lambda t, b: t.replace(
            RESULT_COND, IND + 'if [ "$EXAM_RESULT" != "success" ]\n' + IND + "then\n"
        ),
        lambda t, b: t.replace(RESULT_COND, cond('test "$EXAM_RESULT" != success')),
        lambda t, b: t.replace(b, IND + '[ "$EXAM_RESULT" == success ] || exit 1\n'),
        lambda t, b: t.replace(b, IND + '[[ "$EXAM_RESULT" == success ]] || exit 1\n'),
        lambda t, b: t.replace(b, IND + 'test "$EXAM_RESULT" = success || exit 1\n'),
        lambda t, b: t.replace(RESULT_STEP, RESULT_STEP + "        if: always()\n"),
        lambda t, b: t.replace(RESULT_STEP, RESULT_STEP + "        if: ${{ always() }}\n"),
        lambda t, b: t.replace(
            b, swap_exit(b, IND2 + "if true; then echo hi; fi\n" + IND2 + "exit 1\n")
        ),
        lambda t, b: t.replace(
            b,
            swap_exit(
                b, IND2 + 'if [ -n "$CI" ]; then echo a; else echo b; fi\n' + IND2 + "exit 1\n"
            ),
        ),
    ],
    ids=[
        "comment",
        "echo-and-exit",
        "then-next-line",
        "test-builtin",
        "inverted-double-equals",
        "inverted-dbl-bracket-double-equals",
        "inverted-test",
        "step-if-always",
        "step-if-always-expr",
        "one-line-if",
        "one-line-if-else",
    ],
)
def test_criterion_5_round_2_safe_spelling_stays_green(respell: Any) -> None:
    text = workflow_text(GATE)
    mutated = respell(text, result_block(text))
    assert mutated != text
    check_gate_requires_exam_success(mutated)


# criterion 2, round 2

BASE_COND = '          if ! git rev-parse --verify -q "origin/$BASE_REF" > /dev/null; then\n'


@pytest.mark.parametrize("name", list(NESTED_EXIT))
def test_criterion_2_exit_that_is_not_top_level_is_rejected(name: str) -> None:
    text = workflow_text(INTEGRITY)
    blk = base_block(text)
    mutated = text.replace(blk, swap_exit(blk, NESTED_EXIT[name]))
    assert mutated != text
    with pytest.raises(AssertionError):
        check_base_ref_verified(mutated)


@pytest.mark.parametrize(
    "new_cond",
    [
        'if ! git rev-parse --verify -q "origin/$BASE_REF" > /dev/null && false',
        'if ! git rev-parse --verify -q "origin/$BASE_REF" > /dev/null || true',
        'if ! git rev-parse --verify -q "origin/$BASE_REF" > /dev/null | cat',
        'if ! git rev-parse --verify -q "origin/$OTHER_REF" > /dev/null',
        'if git rev-parse --verify -q "origin/$BASE_REF" > /dev/null',
        'if ! git log -q "origin/$BASE_REF" > /dev/null',
    ],
    ids=["and-false", "or-true", "piped", "other-ref", "not-negated", "other-git-command"],
)
def test_criterion_2_condition_must_fullmatch(new_cond: str) -> None:
    text = workflow_text(INTEGRITY)
    assert BASE_COND in text
    with pytest.raises(AssertionError):
        check_base_ref_verified(text.replace(BASE_COND, IND + new_cond + "; then\n"))


@pytest.mark.parametrize(
    "new_cond",
    [
        'if ! git rev-parse --verify -q "origin/${BASE_REF}" > /dev/null',
        'if ! git rev-parse --verify origin/$BASE_REF',
        'if ! git rev-parse --verify -q "origin/$BASE_REF" > /dev/null 2>&1',
        'if ! git show-ref --verify --quiet "refs/remotes/origin/$BASE_REF"',
    ],
    ids=["braces", "unquoted", "stderr", "show-ref-quiet"],
)
def test_criterion_2_round_2_safe_spelling_stays_green(new_cond: str) -> None:
    text = workflow_text(INTEGRITY)
    check_base_ref_verified(text.replace(BASE_COND, IND + new_cond + "; then\n"))
