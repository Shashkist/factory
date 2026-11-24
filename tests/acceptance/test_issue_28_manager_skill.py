"""Issue #28: methodology plugin, slice 2 (the manager skill and the profile renderer).

Contract chosen for the renderer (narrow, so it stays implementable):
  command   `factory-tools methodology render [--profile PATH]` (default PATH is
            `.factory/factory.yaml`, like `profile check`); run here as
            `python -m factory_tools methodology render ...` (same entry point).
  output    the skill's project section on stdout, exit 0. It has a markdown heading
            containing the word "project" and states every fact it was given:
            each verify command and its cwd, each exam glob, each research hint, the
            smoke workflow and the owner files (decisions and owner paths). Exact
            layout is free; the tests only look for the values as substrings.
  defaults  with a profile that holds only `methodology`, exit 0 and, per documented
            default of docs/profile.md: the exam glob `**/tests/acceptance/**` and the
            limits ci_rounds 5, review_rounds 2, parallel_issues 3 (each limit's key
            name and its number on one line). No value of the LF example leaks in.
  errors    a missing profile file exits non-zero (2, as `profile check`) with no
            traceback on stdout.
The skill file is `plugin/skills/factory/SKILL.md`; rules are looked up by robust
case-insensitive patterns, one test per rule of the issue's scope.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from helpers import ROOT, env
from test_issue_27_plugin_agents import FORBIDDEN, MANIFEST, PLUGIN, frontmatter, plugin_files

SKILL = PLUGIN / "skills" / "factory" / "SKILL.md"
LF_PROFILE = ROOT / "tests" / "fixtures" / "learning_factory.yaml"


def render(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "factory_tools", "methodology", "render", *args],
        cwd=cwd or ROOT,
        env=env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def skill_text() -> str:
    assert SKILL.is_file(), f"missing {SKILL.relative_to(ROOT)}"
    return SKILL.read_text(encoding="utf-8")


def lf_values() -> list[str]:
    data = yaml.safe_load(LF_PROFILE.read_text(encoding="utf-8"))
    values: list[str] = []
    for group in data["verify"].values():
        values.append(group["cwd"])
        values.extend(group["run"])
    values.extend(data["exam"])
    values.extend(data["research_hints"])
    values.append(data["smoke"]["workflow"])
    values.extend(data["owner_files"].values())
    return values


# --- Criterion 1: the renderer ---


def test_render_with_lf_profile_exits_zero_and_has_a_project_section() -> None:
    r = render("--profile", str(LF_PROFILE))
    assert r.returncode == 0, r.stderr
    assert re.search(r"^#+ .*project", r.stdout, re.IGNORECASE | re.MULTILINE), r.stdout


@pytest.mark.parametrize("value", lf_values())
def test_render_with_lf_profile_prints_every_verify_command_and_exam_path(value: str) -> None:
    r = render("--profile", str(LF_PROFILE))
    assert r.returncode == 0, r.stderr
    assert value in r.stdout, f"{value!r} missing from the rendered project section"


def test_render_reads_the_default_profile_path_when_no_flag_is_given(tmp_path: Path) -> None:
    (tmp_path / ".factory").mkdir()
    (tmp_path / ".factory" / "factory.yaml").write_text(
        LF_PROFILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    r = render(cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "uv run pytest -q" in r.stdout


def test_render_with_minimal_profile_prints_the_documented_defaults(tmp_path: Path) -> None:
    p = tmp_path / "min.yaml"
    p.write_text('methodology: "0.1"\n', encoding="utf-8")
    r = render("--profile", str(p), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert re.search(r"^#+ .*project", r.stdout, re.IGNORECASE | re.MULTILINE), r.stdout
    assert "**/tests/acceptance/**" in r.stdout
    for key, number in (("ci_rounds", 5), ("review_rounds", 2), ("parallel_issues", 3)):
        assert re.search(rf"{key}\b[^\n]*\b{number}\b", r.stdout), f"no default for {key}"


def test_render_with_minimal_profile_does_not_leak_lf_values(tmp_path: Path) -> None:
    p = tmp_path / "min.yaml"
    p.write_text('methodology: "0.1"\n', encoding="utf-8")
    r = render("--profile", str(p), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    for leaked in ("uv run pytest -q", "labs/manager", "KodeKloud", "server-smoke.yml"):
        assert leaked not in r.stdout


def test_render_with_a_missing_profile_fails_cleanly(tmp_path: Path) -> None:
    r = render("--profile", str(tmp_path / "nope.yaml"), cwd=tmp_path)
    assert r.returncode != 0
    assert "Traceback" not in r.stdout
    assert "nope.yaml" in r.stdout + r.stderr, "the error must name the missing file"


# --- Criterion 2: the forbidden-words test of slice 1 covers the skill ---


def test_skill_file_exists_under_plugin_skills_factory() -> None:
    assert SKILL in plugin_files()


@pytest.mark.parametrize("term", FORBIDDEN)
def test_skill_contains_no_project_specific_term(term: str) -> None:
    assert term.lower() not in skill_text().lower()


# --- Criterion 3: the plugin still validates ---


def test_plugin_manifest_still_valid_with_the_skill_present() -> None:
    import json

    assert SKILL.is_file()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data.get("name") == "factory"
    assert isinstance(data.get("version"), str) and data["version"].strip()


def test_skill_frontmatter_has_name_factory_and_a_description() -> None:
    text = skill_text()
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    assert m, "SKILL.md has no YAML frontmatter"
    fm = yaml.safe_load(m.group(1))
    assert fm.get("name") == "factory"
    assert isinstance(fm.get("description"), str) and fm["description"].strip()


@pytest.mark.parametrize("name", ["exam-writer", "implementer", "reviewer", "researcher"])
def test_the_four_agents_still_validate(name: str) -> None:
    assert SKILL.is_file()
    assert frontmatter(name).get("name") == name


def test_skill_calls_tools_as_factory_tools_with_repo_and_names_the_renderer() -> None:
    text = skill_text()
    assert re.search(r"factory-tools [a-z-]+ [^\n]*--repo", text)
    assert "factory-tools methodology render" in text
    assert re.search(r"repositories", text, re.IGNORECASE)


# --- Criterion 4: each rule of the scope appears in the skill ---

RULES = {
    "exam_before_code": r"exam[^\n]{0,60}before[^\n]{0,20}(code|build|implement)",
    "exam_integrity": r"exam[\s-]integrity|acceptance[^\n]{0,80}together with",
    "contradicting_exams": r"contradict",
    "d_entries": r"\bD-entr(y|ies)\b|\bD-number",
    "owner_only_blockers": r"owner[\s-]only",
    "evidence_before_close": r"evidence[^\n]{0,40}(before|close|clos)|clos[^\n]{0,40}evidence",
    "no_attribution": r"no attribution|co-authored-by",
    "three_issues_in_flight": (
        r"(up to|at most|max(imum)?)[^\n]{0,15}\b(3|three)\b[^\n]{0,30}in flight"
        r"|in flight[^\n]{0,40}\b(3|three)\b"
    ),
    "ninety_minute_budget": r"(~|about |around )?\b90\b[^\n]{0,3}(-|\s)?minute",
    "verdict_lines": r"Review round[^\n]{0,20}APPROVE\s*\|\s*CHANGES",
    "merge_gate": r"merge[\s-]gate|\bMERGE\b[^\n]{0,40}\bHOLD\b",
}


@pytest.mark.parametrize("rule", sorted(RULES))
def test_skill_states_rule_(rule: str) -> None:
    assert re.search(RULES[rule], skill_text(), re.IGNORECASE), f"rule {rule!r} missing"
