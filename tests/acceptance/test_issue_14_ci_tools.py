"""Issue #14 (slice 3 of #3, D5): CI paths, incident gate and docs/tools.md.

Criterion 1 (the ported LF tests pass against the package) lives in tests/acceptance/ported/
(test_ci_paths.py). Learning Factory has no tests for scripts/incident_gate.py, so its
behaviour (documented in that script's docstring) is pinned here instead.

Contract for the implementer:
  - modules `factory_tools.pipeline.paths` and `factory_tools.pipeline.incident_gate`, stdlib only,
    runnable as `python -m <module>` and as a plain file with the same arguments as the LF scripts
    (`deploys <tag> <head>` / `heavy <base> <head>`; `--workflow --event [--previous]`).
  - `factory-tools ci-paths ...` and `factory-tools incident-gate ...` take the same arguments
    and print the same output (also via `python -m factory_tools ...`).
  - docs/tools.md follows the heading rule in `documented_sections` below.
"""

import argparse
import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import ROOT, SRC, module_file, run_module

PATHS = "factory_tools.pipeline.paths"
GATE = "factory_tools.pipeline.incident_gate"
CANARY = "EXAM-CANARY-NOT-A-TOKEN-9c41d2"
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_PAT")


def mod_path(module: str) -> Path:
    p = module_file(module)
    assert p is not None, f"{module} does not exist"
    return p


def plain(path: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a module file as a plain script: isolated, no site-packages, no PYTHONPATH."""
    return subprocess.run(
        [sys.executable, "-S", "-I", str(path), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
    )


def cli(
    *args: str, cwd: Path | None = None, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return run_module("factory_tools", *args, cwd=cwd, extra_env=extra)


# --- a throwaway git repo: code, then docs on top -----------------------------------------


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        [
            "git",
            "-c", "user.name=t",
            "-c", "user.email=t@example.com",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return out.stdout.strip()


def commit(repo: Path, name: str) -> str:
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(name + "\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c " + name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "labs/manager/app.py")
    return tmp_path


# --- criterion 2: module, plain file and CLI ------------------------------------------------


def test_both_modules_exist_in_the_package() -> None:
    assert mod_path(PATHS).name == "paths.py"
    assert mod_path(GATE).name == "incident_gate.py"


def test_paths_runs_as_python_dash_m(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "docs/x.md")
    r = run_module(PATHS, "deploys", code, head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true"
    r = run_module(PATHS, "heavy", code, head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "false"


def test_paths_runs_as_a_plain_file_without_site_packages(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    docs = commit(repo, "docs/x.md")
    head = commit(repo, "labs/web/b.ts")
    r = plain(mod_path(PATHS), "deploys", code, docs, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true"
    r = plain(mod_path(PATHS), "deploys", code, head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "false"
    r = plain(mod_path(PATHS), "heavy", "main~1", head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() in ("true", "false")


def test_paths_without_arguments_prints_usage_and_fails(repo: Path) -> None:
    r = run_module(PATHS, cwd=repo)
    assert r.returncode != 0
    assert r.stderr.strip()


def test_gate_runs_as_python_dash_m() -> None:
    r = run_module(GATE, "--workflow", "CI", "--event", "push")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "raise"


def test_gate_runs_as_a_plain_file_without_site_packages() -> None:
    path = mod_path(GATE)
    base = ["--workflow", "Factory dashboard", "--event", "schedule"]
    r = plain(path, *base, "--previous", "failure")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "raise"
    r = plain(path, *base, "--previous", "success")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "skip"


@pytest.mark.parametrize("module", [PATHS, GATE])
def test_modules_import_only_the_standard_library(module: str) -> None:
    tree = ast.parse(mod_path(module).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import: not runnable as a plain file"
            names.add((node.module or "").split(".")[0])
    outside = sorted(n for n in names if n and n not in sys.stdlib_module_names)
    assert outside == [], f"non-stdlib imports in {module}: {outside}"


def test_paths_through_the_cli(repo: Path) -> None:
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "docs/x.md")
    r = cli("ci-paths", "deploys", code, head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true"
    r = cli("ci-paths", "heavy", code, head, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "false"
    code2 = commit(repo, "labs/manager/b.py")
    r = cli("ci-paths", "deploys", code, code2, cwd=repo)
    assert r.stdout.strip() == "false"


def test_cli_ci_paths_fails_loudly_on_an_unknown_tag(repo: Path) -> None:
    r = cli("ci-paths", "deploys", "0" * 40, git(repo, "rev-parse", "HEAD"), cwd=repo)
    assert r.returncode != 0
    assert r.stderr.strip()


def test_incident_gate_through_the_cli() -> None:
    base = ["--workflow", "Factory dashboard", "--event", "schedule"]
    r = cli("incident-gate", *base, "--previous", "failure")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "raise"
    r = cli("incident-gate", *base, "--previous", "none")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "skip"


# --- incident gate behaviour (LF has no tests for it; pinned from its docstring) --------------


def decide(workflow: str, event: str, previous: str | None = None) -> str:
    args = ["--workflow", workflow, "--event", event]
    if previous is not None:
        args += ["--previous", previous]
    r = run_module(GATE, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("previous", ["failure", "timed_out", "startup_failure", " failure\n"])
def test_gate_second_scheduled_dashboard_failure_raises(previous: str) -> None:
    assert decide("Factory dashboard", "schedule", previous) == "raise"


@pytest.mark.parametrize("previous", ["success", "none", "", "cancelled", None])
def test_gate_first_scheduled_dashboard_failure_is_noise(previous: str | None) -> None:
    assert decide("Factory dashboard", "schedule", previous) == "skip"


@pytest.mark.parametrize(
    ("workflow", "event"),
    [
        ("CI", "push"),
        ("CI", "schedule"),
        ("Deploy", "workflow_run"),
        ("Factory dashboard", "push"),
        ("Factory dashboard", "workflow_dispatch"),
    ],
)
def test_gate_everything_else_raises(workflow: str, event: str) -> None:
    assert decide(workflow, event, "success") == "raise"
    assert decide(workflow, event) == "raise"


@pytest.mark.parametrize("missing", ["--workflow", "--event"])
def test_gate_requires_workflow_and_event(missing: str) -> None:
    args = {"--workflow": "CI", "--event": "push"}
    del args[missing]
    flat = [x for kv in args.items() for x in kv]
    r = run_module(GATE, *flat)
    assert r.returncode != 0
    assert r.stderr.strip()


# --- criterion 3: docs/tools.md names every command --------------------------------------------


def discover_commands() -> list[tuple[tuple[str, ...], list[str]]]:
    """Every `factory-tools` command, from the CLI's own argparse tree at test time.

    Returns (path, long options) for each top-level command and each subcommand of a group,
    for example (("profile",), []), (("profile", "check"), []), (("ci-paths",), [...]).
    """
    sys.path.insert(0, str(SRC))
    try:
        parser = importlib.import_module("factory_tools.cli").build_parser()
    finally:
        sys.path.remove(str(SRC))

    found: list[tuple[tuple[str, ...], list[str]]] = []

    def walk(p: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if path:
            opts = sorted(
                {
                    o
                    for a in p._actions
                    for o in a.option_strings
                    if o.startswith("--") and o != "--help"
                }
            )
            found.append((path, opts))
        for s in subs:
            for name, child in s.choices.items():
                walk(child, (*path, name))

    walk(parser, ())
    return found


def documented_sections() -> dict[tuple[str, ...], str]:
    """HEADING RULE for docs/tools.md.

    A command `C` (top level) or `C S` (subcommand S of group C) is documented when the file
    has a markdown heading line (`#` to `######`) that contains the text `factory-tools C`
    or `factory-tools C S` (words separated by single spaces, not followed by a letter, digit,
    `-` or `_`; backticks around it are fine). Its SECTION is the text from that heading to the
    next heading of the same or a higher level (so subsections belong to it). The section must
    contain, inside a fenced code block, at least one example line that contains
    `factory-tools C S` (or `factory_tools C S` as in `python -m factory_tools C S`), and, for a
    leaf command, every long option the CLI accepts for it (`--flag`, not `--help`).
    """
    text = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    heads = [
        (i, len(m.group(1)), m.group(2))
        for i, ln in enumerate(lines)
        if (m := re.match(r"^(#{1,6})\s+(.*\S)\s*$", ln))
    ]
    out: dict[tuple[str, ...], str] = {}
    for cmd, _ in discover_commands():
        pattern = re.compile(r"factory-tools " + re.escape(" ".join(cmd)) + r"(?![\w-])")
        for n, (i, level, title) in enumerate(heads):
            if not pattern.search(title):
                continue
            end = len(lines)
            for j, lvl, _t in heads[n + 1 :]:
                if lvl <= level:
                    end = j
                    break
            out[cmd] = "\n".join(lines[i:end])
            break
    return out


def fenced_lines(section: str) -> list[str]:
    inside, found = False, []
    for ln in section.splitlines():
        if ln.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            found.append(ln)
    return found


def test_tools_doc_exists() -> None:
    assert (ROOT / "docs" / "tools.md").is_file(), "docs/tools.md is missing"


def test_the_cli_exposes_the_ci_commands() -> None:
    names = {c[0][0] for c in discover_commands()}
    assert {"ci-paths", "incident-gate"} <= names, sorted(names)


def test_every_cli_command_has_a_heading_in_tools_doc() -> None:
    sections = documented_sections()
    missing = [" ".join(c) for c, _ in discover_commands() if c not in sections]
    assert missing == [], "no heading for: " + ", ".join(f"factory-tools {m}" for m in missing)


def test_every_documented_command_has_an_example_line() -> None:
    sections = documented_sections()
    bad = []
    for cmd, _ in discover_commands():
        if cmd not in sections:
            continue
        name = " ".join(cmd)
        ok = any(
            f"factory-tools {name}" in ln or f"factory_tools {name}" in ln
            for ln in fenced_lines(sections[cmd])
        )
        if not ok:
            bad.append(name)
    assert bad == [], "no example in a code block for: " + ", ".join(bad)


def test_every_leaf_command_section_names_its_options() -> None:
    sections = documented_sections()
    cmds = discover_commands()
    bad = []
    for cmd, opts in cmds:
        is_group = any(c[0][: len(cmd)] == cmd and len(c[0]) > len(cmd) for c in cmds)
        if is_group or cmd not in sections:
            continue
        bad += [f"{' '.join(cmd)} {o}" for o in opts if o not in sections[cmd]]
    assert bad == [], "options not documented: " + ", ".join(bad)


# --- criterion 4: no token read, printed or stored --------------------------------------------

SECRETISH = re.compile(
    r"token|secret|password|passwd|credential|authorization|bearer|ghp_|gho_|ghs_|github_pat",
    re.IGNORECASE,
)


def code_strings(source: str) -> list[str]:
    """String literals (docstrings excluded) and identifiers in the code."""
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docs.add(id(first.value))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs:
                found.append(node.value)
        elif isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, ast.arg):
            found.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            found.append(node.arg)
    return found


@pytest.mark.parametrize("module", [PATHS, GATE])
def test_source_holds_no_token_handling(module: str) -> None:
    src = mod_path(module).read_text(encoding="utf-8")
    hits = [x for x in code_strings(src) if SECRETISH.search(x)]
    assert hits == [], f"token or credential handling in {module}: {hits!r}"
    for name in TOKEN_VARS:
        assert name not in src
    assert "auth token" not in src.replace("\n", " ")


def test_no_ci_command_echoes_or_stores_a_token(repo: Path) -> None:
    tokens = {name: f"{CANARY}-{i}" for i, name in enumerate(TOKEN_VARS)}
    code = commit(repo, "labs/web/a.ts")
    head = commit(repo, "docs/x.md")
    before = {p for p in repo.rglob("*") if ".git" not in p.parts}
    results = [
        cli("ci-paths", "deploys", code, head, cwd=repo, extra=tokens),
        cli("ci-paths", "heavy", code, head, cwd=repo, extra=tokens),
        cli("incident-gate", "--workflow", "CI", "--event", "push", cwd=repo, extra=tokens),
        run_module(PATHS, "deploys", code, head, cwd=repo, extra_env=tokens),
        run_module(GATE, "--workflow", "CI", "--event", "push", cwd=repo, extra_env=tokens),
        run_module(PATHS, "bogus", cwd=repo, extra_env=tokens),
    ]
    for r in results:
        for value in tokens.values():
            assert value not in r.stdout + r.stderr
    after = {p for p in repo.rglob("*") if ".git" not in p.parts}
    assert after == before, "a command wrote files: " + repr(sorted(after - before))
    for p in after:
        if p.is_file():
            assert CANARY not in p.read_text(encoding="utf-8", errors="replace")


def test_cli_help_never_shows_the_environment() -> None:
    tokens = {name: f"{CANARY}-h" for name in TOKEN_VARS}
    r = cli("--help", extra=tokens)
    assert r.returncode == 0, r.stderr
    assert CANARY not in r.stdout + r.stderr
