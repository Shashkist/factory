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
    """Logical lines of a run script: comments dropped, continuations joined, a
    `then` on its own line appended to the line above it, and a multi-line
    `|| {` / `&& {` group folded into one line."""
    joined = re.sub(r"\\\n\s*", " ", run)
    out: list[str] = []
    group: list[str] | None = None
    for raw in joined.splitlines():
        ln = strip_comment(raw.strip()).strip()
        if not ln:
            continue
        if group is not None:
            if ln == "}":
                out[-1] += " " + "; ".join(group) + "; }"
                group = None
            else:
                group.append(ln.rstrip(";"))
        elif re.search(r"(?:\|\||&&)\s*\{$", ln):
            out.append(ln)
            group = []
        elif ln == "then" and out:
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


def depth_before(stmts: list[str], k: int) -> int:
    """Nesting (if/case/loops, brace groups, function bodies) open before stmts[k]."""
    depth = 0
    for st in stmts[:k]:
        u = unquote(st)
        if CLOSERS.match(st):
            depth -= 1
        elif OPENERS.match(st):
            depth += 1
        depth += len(re.findall(r"(?<!\S)\{(?!\S)", u)) - len(re.findall(r"(?<!\S)\}(?!\S)", u))
        assert depth >= 0, "closing token without an opener"
    return depth


def top_level_exits(stmts: list[str], k: int) -> list[tuple[int, int]]:
    """(index, code) of statements that run unconditionally in the main branch of the
    `if` at index k: nested if/case/loops and elif/else branches are skipped."""
    depth, alt, found = 1, False, []
    for idx in range(k + 1, len(stmts)):
        st = stmts[idx]
        if CLOSERS.match(st):
            depth -= 1
            if depth == 0:
                return found
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
                found.append((idx, int(m.group(1) or 0)))
    raise AssertionError("an if without its fi")


def swallows_before(chunks: list[str]) -> str | None:
    """A trap, `exit 0` or bare `exit` in the given script text (or None)."""
    for ch in chunks:
        flat = unquote(ch)
        if re.search(r"\btrap\b", flat):
            return f"trap before the check: {ch!r}"
        if re.search(r"(?<![\w-])exit(?:\s+0+\b|\s*(?:;|$|\}|&|\|))", flat):
            return f"an exit 0 or bare exit before the check: {ch!r}"
    return None


def guard_at(stmts: list[str], k: int) -> bool:
    """The `if` at k is reached on every run (depth 0, no early exit before it), and
    its main branch ends the script with a non-zero exit, with no exit 0 before it."""
    if depth_before(stmts, k) != 0:
        return False
    exits = top_level_exits(stmts, k)
    bad = [i for i, c in exits if c != 0]
    if not bad or any(c == 0 for _, c in exits):
        return False
    return swallows_before(stmts[: bad[0]]) is None


def tail_exits_nonzero(tail: str) -> bool:
    t = unquote(tail).strip()
    if re.fullmatch(r"exit\s+[1-9]\d*", t):
        return True
    m = re.fullmatch(r"\{\s*(?:(.*?);\s*)?exit\s+[1-9]\d*\s*;?\s*\}", t)
    return bool(m) and swallows_before([m.group(1) or ""]) is None


def line_guard_at(lines: list[str], i: int, tail: str) -> bool:
    """An `A || tail` line at index i is a guard: depth 0 and no swallow before it."""
    before = statements(lines[:i])
    return (
        depth_before(before, len(before)) == 0
        and swallows_before(before) is None
        and tail_exits_nonzero(tail)
    )


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
    ref = r"\"?(?:refs/remotes/)?origin/\$(?:BASE_REF|\{BASE_REF\})(?:\^\{commit\})?\"?"
    git = r"git\s+(?:rev-parse|show-ref)(?:\s+(?:--verify|-q|--quiet))*\s+" + ref
    redirs = r"(?:\s*(?:&>|[12]?>)\s*/dev/null|\s*2>&1)*"
    if_form = re.compile(r"if\s+!\s+" + git + redirs)
    or_form = re.compile(git + redirs + r"\s*\|\|\s*(.*)")
    for i, st in enumerate(stmts[:judge]):
        if if_form.fullmatch(st) and guard_at(stmts, i):
            return
    judge_line = max(i for i, x in enumerate(lines) if "exam_integrity.py" in x)
    for i, ln in enumerate(lines[:judge_line]):
        m = or_form.fullmatch(ln)
        if m and line_guard_at(lines, i, m.group(1)):
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


def step_if_is_safe(value: Any) -> bool:
    m = re.fullmatch(r"\$\{\{(.*)\}\}", squash(value))
    return (m.group(1) if m else squash(value)) in ("always()", "success()")


def rewrites_variable(stmts: list[str], var: str) -> bool:
    for st in stmts:
        u = unquote(st)
        if re.search(r"(?:^|&&|\|\||\{|\()\s*(?:\(\(\s*)?" + var + r"\+?=", u):
            return True
        if re.match(r"(?:unset|export|read|declare|local|typeset|readonly|for)\b.*\b" + var, u):
            return True
        if re.match(r"printf\s+-v\s+" + var + r"\b", u):
            return True
    return False


def case_guard_at(stmts: list[str], k: int) -> bool:
    """`case $RESULT in success) ;; *) ...; exit N ;; esac` at depth 0."""
    if depth_before(stmts, k) != 0:
        return False
    arms: list[tuple[str, list[str]]] = []
    for idx in range(k + 1, len(stmts)):
        st = stmts[idx]
        if st == "esac":
            break
        if OPENERS.match(st) or CLOSERS.match(st):
            return False
        m = re.fullmatch(r"\(?([^\s()]+)\)\s*(.*)", st)
        if m:
            arms.append((m.group(1).strip("\"'"), []))
            st = m.group(2)
        if st and arms:
            arms[-1][1].append(st)
    else:
        return False
    if [a for a, _ in arms] != ["success", "*"]:
        return False
    ok_body, bad_body = arms[0][1], arms[1][1]
    if exit_codes_of(ok_body):
        return False
    codes = exit_codes_of(bad_body)
    if not codes or codes[0] == 0 or 0 in codes:
        return False
    first = next(i for i, st in enumerate(bad_body) if exit_codes_of([st]))
    return swallows_before(stmts[:k] + bad_body[:first]) is None


def exit_codes_of(body: list[str]) -> list[int]:
    out = []
    for st in body:
        chain = [c.strip() for c in unquote(st).split("&&")]
        m = re.fullmatch(r"exit(?:\s+(\d+))?", chain[-1])
        if m:
            out.append(int(m.group(1) or 0))
    return out


def check_gate_requires_exam_success(text: str) -> None:
    for step in job(text, "gate").get("steps") or []:
        if not step.get("run"):
            continue
        env = step.get("env") or {}
        names = [k for k, v in env.items() if squash(v) == "${{needs.exam.result}}"]
        if not names or truthy(step.get("continue-on-error")):
            continue
        if "if" in step and not step_if_is_safe(step["if"]):
            continue
        lines = script_lines(step["run"])
        stmts = statements(lines)
        for var in names:
            if rewrites_variable(stmts, var):
                continue
            ref = r"\"?\$(?:" + var + r"|\{" + var + r"\})\"?"
            val = r"[\"']?success[\"']?"

            def cmp(op: str, ref: str = ref, val: str = val) -> str:
                return (
                    "(?:" + ref + r"\s+" + op + r"\s+" + val + "|"
                    + val + r"\s+" + op + r"\s+" + ref + ")"
                )

            def forms(op: str, cmp: Any = cmp) -> str:
                return "|".join(
                    (
                        r"\[\s+" + cmp(op) + r"\s+\]",
                        r"\[\[\s+" + cmp(op) + r"\s+\]\]",
                        r"test\s+" + cmp(op),
                    )
                )

            neg = re.compile(r"if\s+(?:" + forms("!=") + ")")
            inv = re.compile(r"(?:" + forms("==?") + r")\s*\|\|\s*(.*)")
            case = re.compile(r"case\s+" + ref + r"\s+in")
            for i, st in enumerate(stmts):
                if neg.fullmatch(st) and guard_at(stmts, i):
                    return
                if case.fullmatch(st) and case_guard_at(stmts, i):
                    return
            for i, ln in enumerate(lines):
                m = inv.fullmatch(ln)
                if m and line_guard_at(lines, i, m.group(1)):
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
    ["mismatched_close", "mismatched_open", "step_if_failure"],
)
def test_criterion_5_other_round_2_mutations_are_rejected(name: str) -> None:
    text = workflow_text(GATE)
    mutated = {
        "mismatched_close": text.replace(RESULT_COND, cond('[ "$EXAM_RESULT" != "success" ]]')),
        "mismatched_open": text.replace(RESULT_COND, cond('[[ "$EXAM_RESULT" != "success" ]')),
        "step_if_failure": text.replace(RESULT_STEP, RESULT_STEP + "        if: failure()\n"),
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


# ------------------------------------------------ round 3: behaviour and depth

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


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

KNOWN_EXPRESSIONS = {
    "inputs.junit-file": "acceptance.xml",
    # #91: the gate's first step fails closed on an empty workflow ref; the harness
    # gives it realistic non-empty values so that guard passes through.
    "job.workflow_repository": "Shashkist/factory",
    "job.workflow_sha": "0123456789abcdef0123456789abcdef01234567",
}


def substitute(value: str, result: str) -> str:
    def repl(m: re.Match[str]) -> str:
        expr = m.group(1).strip()
        if expr == "needs.exam.result":
            return result
        assert expr in KNOWN_EXPRESSIONS, f"the exam cannot evaluate an expression: {expr}"
        return KNOWN_EXPRESSIONS[expr]

    return re.sub(r"\$\{\{(.*?)\}\}", repl, value)


def run_gate_steps(text: str, result: str, workdir: Path) -> int:
    """Run the gate job's run steps in order under bash, as Actions does (stop at the
    first failing step), with the judge stubbed to exit 0 ("the report passes") and a
    passing report in place. Returns the exit code of the gate."""
    assert BASH
    (workdir / "report").mkdir(exist_ok=True)
    (workdir / "report" / "acceptance.xml").write_text("<testsuites/>", encoding="utf-8")
    (workdir / "fakebin").mkdir(exist_ok=True)
    fake = workdir / "fakebin" / "python3"
    fake.write_bytes(b"#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    for n, step in enumerate(run_steps(text, "gate")):
        script = substitute(step["run"], result).replace("/usr/bin/python3", "./fakebin/python3")
        path = workdir / f"step{n}.sh"
        path.write_bytes(script.encode("utf-8").replace(b"\r\n", b"\n"))
        env = {k: v for k, v in os.environ.items() if k != "EXAM_RESULT"}
        env.update({k: substitute(str(v), result) for k, v in (step.get("env") or {}).items()})
        done = subprocess.run(
            [BASH, "--noprofile", "--norc", "-eo", "pipefail", path.name],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if done.returncode != 0:
            return done.returncode
    return 0


NOT_SUCCESS = ["failure", "cancelled", "skipped"]


def check_gate_behaviour(text: str, workdir: Path) -> None:
    for result in NOT_SUCCESS:
        sub = workdir / result
        sub.mkdir()
        rc = run_gate_steps(text, result, sub)
        assert rc != 0, f"the gate step exits 0 with a passing report and exam result {result}"
    ok = workdir / "success"
    ok.mkdir()
    assert run_gate_steps(text, "success", ok) == 0, "the gate step fails on a green exam"


@needs_bash
def test_criterion_5_behaviour_gate_step_fails_on_a_failed_exam_result(tmp_path: Path) -> None:
    check_gate_behaviour(workflow_text(GATE), tmp_path)


MISSING_IF = '          if [ ! -f "report/${JUNIT_FILE##*/}" ]; then\n'


def weakened_gate(name: str, text: str) -> str:
    blk = result_block(text)
    no_block = text.replace(blk, "")
    assert MISSING_IF in no_block
    strict_open = IND + 'if [ -n "$STRICT" ]; then\n'
    brace_tail = (
        IND
        + '[ "$EXAM_RESULT" = success ] || { [ "$EXAM_RESULT" = skipped ] && exit 0; exit 1; }\n'
    )
    return {
        "nested_in_missing_report_check": no_block.replace(MISSING_IF, MISSING_IF + blk),
        "opt_in_wrapper": text.replace(blk, strict_open + blk + IND + "fi\n"),
        "uncalled_function": text.replace(blk, IND + "gate_check() {\n" + blk + IND + "}\n"),
        "loop": text.replace(blk, IND + "for i in 1; do\n" + blk + IND + "done\n"),
        "body_exits_0_first": text.replace(blk, blk.replace("exit 1", "exit 0", 1)),
        "brace_tail_exits_0_first": text.replace(blk, brace_tail),
    }[name]


BEHAVIOUR_WEAKENED = [
    "nested_in_missing_report_check",
    "opt_in_wrapper",
    "body_exits_0_first",
    "brace_tail_exits_0_first",
]


@needs_bash
@pytest.mark.parametrize("name", BEHAVIOUR_WEAKENED)
def test_criterion_5_behaviour_case_fails_a_weakened_gate(name: str, tmp_path: Path) -> None:
    mutated = weakened_gate(name, workflow_text(GATE))
    with pytest.raises(AssertionError):
        check_gate_behaviour(mutated, tmp_path)


STATIC_WEAKENED = [*BEHAVIOUR_WEAKENED, "uncalled_function", "loop"]


@pytest.mark.parametrize("name", STATIC_WEAKENED)
def test_criterion_5_static_check_rejects_a_not_always_reached_check(name: str) -> None:
    mutated = weakened_gate(name, workflow_text(GATE))
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(mutated)


def test_criterion_5_static_check_rejects_opt_out_and_case_wrappers() -> None:
    text = workflow_text(GATE)
    blk = result_block(text)
    for wrap in (
        IND + 'if [ -z "$SKIP" ]; then\n' + blk + IND + "fi\n",
        IND + 'case "$MODE" in\n' + IND + "  strict)\n" + blk + IND + "  ;;\n" + IND + "esac\n",
        IND + 'if [ "$MODE" = a ]; then\n' + blk + IND + "else\n" + IND + "  true\n" + IND + "fi\n",
    ):
        with pytest.raises(AssertionError):
            check_gate_requires_exam_success(text.replace(blk, wrap))
    nested = IND2 + '[ "$EXAM_RESULT" = skipped ] && exit 0\n' + IND2 + "exit 1\n"
    with pytest.raises(AssertionError):
        check_gate_requires_exam_success(text.replace(blk, swap_exit(blk, nested)))


@pytest.mark.parametrize("name", ["wrapper", "function", "opt_in", "exit0_first", "early_exit"])
def test_criterion_2_depth_and_early_exit_are_rejected(name: str) -> None:
    text = workflow_text(INTEGRITY)
    blk = base_block(text)
    early = IND2 + '[ -n "$CI" ] && exit 0\n' + IND2 + "exit 1\n"
    mutated = {
        "wrapper": text.replace(blk, IND + 'if [ -z "$SKIP" ]; then\n' + blk + IND + "fi\n"),
        "function": text.replace(blk, IND + "check_base() {\n" + blk + IND + "}\n"),
        "opt_in": text.replace(blk, IND + 'if [ -n "$STRICT" ]; then\n' + blk + IND + "fi\n"),
        "exit0_first": text.replace(blk, blk.replace("exit 1", "exit 0", 1)),
        "early_exit": text.replace(blk, swap_exit(blk, early)),
    }[name]
    with pytest.raises(AssertionError):
        check_base_ref_verified(mutated)


def test_criterion_2_or_form_under_a_wrapper_is_rejected() -> None:
    text = workflow_text(INTEGRITY)
    blk = base_block(text)
    git = IND + 'git rev-parse --verify -q "origin/$BASE_REF" > /dev/null'
    line = git + " || exit 1\n"
    check_base_ref_verified(text.replace(blk, line))
    with pytest.raises(AssertionError):
        check_base_ref_verified(
            text.replace(blk, IND + 'if [ -n "$STRICT" ]; then\n' + line + IND + "fi\n")
        )
    tail = ' || { [ -n "$CI" ] && exit 0; exit 1; }\n'
    with pytest.raises(AssertionError):
        check_base_ref_verified(text.replace(blk, git + tail))


# round 3 safe spellings

CASE_ON_RESULT = (
    IND + 'case "$EXAM_RESULT" in\n' + IND + "  success) ;;\n"
    + IND + "  *) echo bad; exit 1 ;;\n" + IND + "esac\n"
)
MULTI_LINE_GROUP = (
    IND + '[ "$EXAM_RESULT" = success ] || {\n'
    + IND2 + "echo bad\n" + IND2 + "exit 1\n" + IND + "}\n"
)


@pytest.mark.parametrize(
    "respell",
    [
        lambda t, b: t.replace(b, MULTI_LINE_GROUP),
        lambda t, b: t.replace(RESULT_COND, cond('[ success != "$EXAM_RESULT" ]')),
        lambda t, b: t.replace(b, IND + '[ success = "$EXAM_RESULT" ] || exit 1\n'),
        lambda t, b: t.replace(b, CASE_ON_RESULT),
        lambda t, b: t.replace(b, IND + "echo EXAM_RESULT=$EXAM_RESULT\n" + b),
        lambda t, b: t.replace(RESULT_STEP, RESULT_STEP + "        if: success()\n"),
        lambda t, b: t.replace(RESULT_STEP, RESULT_STEP + "        if: ${{ success() }}\n"),
    ],
    ids=[
        "multi-line-brace-group",
        "reversed-operands",
        "reversed-inverted",
        "case-on-result",
        "echo-not-assignment",
        "step-if-success",
        "step-if-success-expr",
    ],
)
def test_criterion_5_round_3_safe_spelling_stays_green(respell: Any) -> None:
    text = workflow_text(GATE)
    mutated = respell(text, result_block(text))
    assert mutated != text
    check_gate_requires_exam_success(mutated)


@pytest.mark.parametrize(
    "new_cond",
    [
        'if ! git rev-parse --verify -q "origin/$BASE_REF^{commit}" > /dev/null',
        'if ! git rev-parse --verify -q "origin/$BASE_REF" &> /dev/null',
        'if ! git rev-parse --verify -q "origin/$BASE_REF" 2> /dev/null >/dev/null',
    ],
    ids=["peel-commit", "ampersand-redirect", "two-redirects"],
)
def test_criterion_2_round_3_safe_spelling_stays_green(new_cond: str) -> None:
    text = workflow_text(INTEGRITY)
    check_base_ref_verified(text.replace(BASE_COND, IND + new_cond + "; then\n"))


@needs_bash
@pytest.mark.parametrize(
    "respell",
    [
        lambda t, b: t.replace(RESULT_COND, cond('[[ "$EXAM_RESULT" != "success" ]]')),
        lambda t, b: t.replace(b, IND + '[ "$EXAM_RESULT" = success ] || exit 1\n'),
        lambda t, b: t.replace(b, CASE_ON_RESULT),
        lambda t, b: t.replace(b, MULTI_LINE_GROUP),
    ],
    ids=["dbl-bracket", "inverted", "case", "multi-line-group"],
)
def test_criterion_5_behaviour_case_passes_safe_spellings(respell: Any, tmp_path: Path) -> None:
    text = workflow_text(GATE)
    check_gate_behaviour(respell(text, result_block(text)), tmp_path)
