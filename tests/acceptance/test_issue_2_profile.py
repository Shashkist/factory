"""Issue #2: the project profile (.factory/factory.yaml), loader and check command."""

import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers import ROOT, env, run_module

FIXTURE = ROOT / "tests" / "fixtures" / "learning_factory.yaml"
DOC = ROOT / "docs" / "profile.md"

AREA_FILES = [
    "labs/manager/app/main.py",
    "labs/web/src/App.tsx",
    "labs/content/lab1/lab.yaml",
    "labs/deploy/compose.yml",
    ".github/workflows/ci.yml",
]


def profile_api() -> Any:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import factory_tools.profile as mod  # noqa: PLC0415
    finally:
        sys.path.remove(str(ROOT / "src"))
    return mod


def tree(base: Path, files: list[str] | None = None) -> Path:
    t = base / "tree"
    for f in AREA_FILES if files is None else files:
        p = t / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    t.mkdir(parents=True, exist_ok=True)
    return t


def write(base: Path, text: str, name: str = "p.yaml") -> Path:
    base.mkdir(parents=True, exist_ok=True)
    p = base / name
    p.write_text(text, encoding="utf-8")
    return p


def check(path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return run_module("factory_tools", "profile", "check", str(path), cwd=cwd)


MIN = 'methodology: "1"\n'
GOOD_VERIFY = "verify:\n  manager:\n    run: [echo hi]\n"


def problem_paths(problems: list[Any]) -> list[str]:
    return [p.path for p in problems]


# ---- criterion 1: the LF example loads and matches the file -------------------


def test_c1_lf_profile_loads_without_problems(tmp_path: Path) -> None:
    prof, problems = profile_api().load_profile(FIXTURE, root=tree(tmp_path))
    assert problems == []
    assert prof is not None


def test_c1_lf_profile_loads_without_root() -> None:
    prof, problems = profile_api().load_profile(FIXTURE)
    assert problems == []
    assert prof is not None


def test_c1_cli_ok_on_lf_profile(tmp_path: Path) -> None:
    r = check(FIXTURE, cwd=tree(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok" in r.stdout


def load_fixture() -> Any:
    prof, problems = profile_api().load_profile(FIXTURE)
    assert problems == []
    return prof


def test_c1_methodology() -> None:
    assert load_fixture().methodology == "0.1"


def test_c1_verify_groups() -> None:
    v = load_fixture().verify
    assert set(v) == {"manager", "web", "tooling"}
    assert v["manager"].cwd == "labs/manager"
    assert list(v["manager"].run) == [
        "uv run pytest -q",
        "uv run ruff check .",
        "uv run mypy app",
    ]
    assert v["web"].cwd == "labs/web"
    assert list(v["web"].run) == [
        "npm test -- --run",
        "npx tsc --noEmit",
        "npm run lint",
        "npm run build",
    ]
    assert v["tooling"].cwd == "."
    assert list(v["tooling"].run) == ["uvx pytest scripts -q"]


def test_c1_exam() -> None:
    assert list(load_fixture().exam) == ["labs/**/tests/acceptance/**"]


def test_c1_protected_paths() -> None:
    assert list(load_fixture().protected_paths) == [
        "scripts/laptop/**",
        "scripts/factory_guard.py",
        "scripts/test_factory_guard.py",
        ".github/workflows/**",
        "labs/deploy/**",
    ]


def test_c1_required_checks() -> None:
    assert list(load_fixture().required_checks) == ["manager", "web", "exam-integrity"]


def test_c1_labels() -> None:
    assert dict(load_fixture().labels) == {
        "ready": "status:ready",
        "in-progress": "status:in-progress",
        "done": "status:done",
        "needs-owner": "status:needs-owner",
        "p0": "priority:p0",
        "p1": "priority:p1",
        "feature": "type:feature",
        "incident": "type:incident",
    }


def test_c1_limits() -> None:
    lim = load_fixture().limits
    assert (lim.ci_rounds, lim.review_rounds, lim.parallel_issues) == (6, 3, 4)


def test_c1_models() -> None:
    assert dict(load_fixture().models) == {
        "manager": "opus",
        "exam-writer": "sonnet",
        "implementer": "sonnet",
        "reviewer": "opus",
        "researcher": "sonnet",
    }


def test_c1_smoke() -> None:
    assert load_fixture().smoke.workflow == "smoke.yml"


def test_c1_research_hints() -> None:
    assert list(load_fixture().research_hints) == [
        "KodeKloud",
        "Killercoda",
        "iximiuz Labs",
        "Instruqt",
    ]


def test_c1_areas() -> None:
    a = load_fixture().areas
    assert {k: list(v) for k, v in a.items()} == {
        "manager": ["labs/manager/**"],
        "web": ["labs/web/**"],
        "content": ["labs/content/**"],
        "deploy": ["labs/deploy/**"],
        "ci": [".github/**"],
    }


def test_c1_planning() -> None:
    p = load_fixture().planning
    assert p.spec == "docs/superpowers/specs/2026-11-14-lab-platform-design.md"
    assert p.keep_ready == 5


def test_c1_owner_files() -> None:
    o = load_fixture().owner_files
    assert o.decisions == "docs/factory/DECISIONS.md"
    assert o.owner == "docs/factory/OWNER.md"


# ---- criterion 2: problems are reported with their key path -------------------


def assert_reported(tmp_path: Path, text: str, path: str) -> None:
    f = write(tmp_path / "proj", text)
    _, problems = profile_api().load_profile(f)
    assert any(p.path == path or p.path.startswith(path + "[") for p in problems), (
        problem_paths(problems)
    )
    assert all(isinstance(p.message, str) and p.message for p in problems)
    r = check(f, cwd=tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert path in r.stdout


def test_c2_unknown_top_level_key(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "bogus: 1\n", "bogus")


def test_c2_misspelled_key_is_not_silent(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "protected_path: []\n", "protected_path")


def test_c2_unknown_nested_key(tmp_path: Path) -> None:
    text = MIN + "verify:\n  manager:\n    run: [echo hi]\n    cmd: x\n"
    assert_reported(tmp_path, text, "verify.manager.cmd")


def test_c2_unknown_key_in_limits(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "limits:\n  ci_round: 3\n", "limits.ci_round")


def test_c2_wrong_type_scalar_for_list(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "exam: not-a-list\n", "exam")


def test_c2_wrong_type_string_for_integer(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + 'limits:\n  ci_rounds: "five"\n', "limits.ci_rounds")


def test_c2_wrong_type_boolean_is_not_an_integer(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "limits:\n  review_rounds: true\n", "limits.review_rounds")


def test_c2_wrong_type_list_item(tmp_path: Path) -> None:
    assert_reported(tmp_path, MIN + "research_hints: [a, 3]\n", "research_hints[1]")


def test_c2_empty_verify_command_list(tmp_path: Path) -> None:
    text = MIN + "verify:\n  manager:\n    cwd: labs/manager\n    run: []\n"
    assert_reported(tmp_path, text, "verify.manager.run")


def test_c2_area_glob_matching_nothing(tmp_path: Path) -> None:
    t = tree(tmp_path, ["labs/manager/app/main.py"])
    text = MIN + 'areas:\n  manager: ["labs/manager/**"]\n  web: ["labs/web/**"]\n'
    f = write(tmp_path / "proj", text)
    _, problems = profile_api().load_profile(f, root=t)
    paths = problem_paths(problems)
    assert any(p.startswith("areas.web") for p in paths), paths
    assert not any(p.startswith("areas.manager") for p in paths), paths
    r = check(f, cwd=t)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "areas.web" in r.stdout
    assert "areas.manager" not in r.stdout


def test_c2_area_globs_not_checked_without_root(tmp_path: Path) -> None:
    f = write(tmp_path, MIN + 'areas:\n  web: ["nowhere/**"]\n')
    _, problems = profile_api().load_profile(f)
    assert problems == []


def test_c2_each_problem_is_one_line_with_path(tmp_path: Path) -> None:
    f = write(tmp_path / "proj", MIN + "bogus: 1\nexam: x\n")
    r = check(f, cwd=tmp_path)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert r.returncode == 1
    assert len(lines) == 2
    assert any(ln.startswith("bogus:") for ln in lines)
    assert any(ln.startswith("exam:") for ln in lines)


def test_c2_missing_methodology_is_reported(tmp_path: Path) -> None:
    f = write(tmp_path / "proj", "exam: []\n")
    _, problems = profile_api().load_profile(f)
    assert "methodology" in problem_paths(problems)
    assert check(f, cwd=tmp_path).returncode == 1


def test_c2_invalid_yaml_exits_2(tmp_path: Path) -> None:
    f = write(tmp_path / "proj", "a: [unclosed\n  b: : :\n")
    assert check(f, cwd=tmp_path).returncode == 2


def test_c2_unreadable_file_exits_2(tmp_path: Path) -> None:
    assert check(tmp_path / "missing.yaml", cwd=tmp_path).returncode == 2


def test_c2_default_path_is_dot_factory_factory_yaml(tmp_path: Path) -> None:
    (tmp_path / ".factory").mkdir()
    (tmp_path / ".factory" / "factory.yaml").write_text(MIN, encoding="utf-8")
    r = run_module("factory_tools", "profile", "check", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok" in r.stdout


# ---- criterion 3: a minimal profile gets the documented defaults ---------------


def test_c3_minimal_profile_loads_with_documented_defaults(tmp_path: Path) -> None:
    f = write(tmp_path, MIN)
    prof, problems = profile_api().load_profile(f)
    assert problems == []
    assert prof.methodology == "1"
    assert dict(prof.verify) == {}
    assert list(prof.exam) == ["**/tests/acceptance/**"]
    assert list(prof.protected_paths) == []
    assert list(prof.required_checks) == []
    assert dict(prof.labels) == {}
    assert (prof.limits.ci_rounds, prof.limits.review_rounds) == (5, 2)
    assert prof.limits.parallel_issues == 3
    assert dict(prof.models) == {}
    assert prof.smoke is None
    assert list(prof.research_hints) == []
    assert dict(prof.areas) == {}
    assert prof.planning is None
    assert prof.owner_files.decisions == ".factory/DECISIONS.md"
    assert prof.owner_files.owner == ".factory/OWNER.md"


def test_c3_minimal_profile_cli_ok(tmp_path: Path) -> None:
    r = check(write(tmp_path / "proj", MIN), cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok" in r.stdout


def test_c3_partial_defaults_inside_sections(tmp_path: Path) -> None:
    text = (
        MIN
        + GOOD_VERIFY
        + "limits:\n  ci_rounds: 9\n"
        + "planning:\n  spec: s.md\n"
        + "smoke:\n  run: echo smoke\n"
    )
    prof, problems = profile_api().load_profile(write(tmp_path, text))
    assert problems == []
    assert prof.verify["manager"].cwd == "."
    assert (prof.limits.ci_rounds, prof.limits.review_rounds) == (9, 2)
    assert prof.limits.parallel_issues == 3
    assert prof.planning.keep_ready == 5
    assert prof.smoke.run == "echo smoke"
    assert prof.smoke.cwd == "."


def test_c3_smoke_with_both_run_and_workflow_is_a_problem(tmp_path: Path) -> None:
    text = MIN + "smoke:\n  run: echo hi\n  workflow: smoke.yml\n"
    _, problems = profile_api().load_profile(write(tmp_path, text))
    assert any(p.path.startswith("smoke") for p in problems)


def test_c3_planning_requires_spec(tmp_path: Path) -> None:
    _, problems = profile_api().load_profile(
        write(tmp_path, MIN + "planning:\n  keep_ready: 4\n")
    )
    assert any(p.path.startswith("planning") for p in problems)


# ---- criterion 4: loading never executes anything ------------------------------

EVIL = 'rm -rf "$HOME"; touch PWNED && $(id) | `x` > out.txt & echo $((1+1)) ; touch PWNED2'


def listing(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


def two_dirs(tmp_path: Path) -> tuple[Path, Path]:
    proj = tmp_path / "proj"
    cwd = tmp_path / "work"
    proj.mkdir()
    cwd.mkdir()
    return proj, cwd


def test_c4_metacharacters_are_stored_verbatim_and_nothing_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, cwd = two_dirs(tmp_path)
    text = MIN + "verify:\n  manager:\n    run:\n      - " + json.dumps(EVIL) + "\n"
    f = write(proj, text)
    monkeypatch.chdir(cwd)
    prof, problems = profile_api().load_profile(f)
    assert problems == []
    assert list(prof.verify["manager"].run) == [EVIL]
    assert listing(cwd) == []
    assert listing(proj) == ["p.yaml"]


def test_c4_cli_check_does_not_run_commands(tmp_path: Path) -> None:
    proj, cwd = two_dirs(tmp_path)
    text = (
        MIN
        + "verify:\n  manager:\n    run:\n      - "
        + json.dumps(EVIL)
        + "\nsmoke:\n  run: "
        + json.dumps(EVIL)
        + "\n"
    )
    f = write(proj, text)
    r = check(f, cwd=cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert listing(cwd) == []
    assert listing(proj) == ["p.yaml"]


def test_c4_python_yaml_tag_is_refused_and_not_executed(tmp_path: Path) -> None:
    proj, cwd = two_dirs(tmp_path)
    f = write(proj, 'methodology: !!python/object/apply:os.system ["touch PWNED"]\n')
    r = check(f, cwd=cwd)
    assert r.returncode in (1, 2), r.stdout + r.stderr
    assert listing(cwd) == []


def test_c4_python_yaml_tag_via_api_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, cwd = two_dirs(tmp_path)
    tag = '!!python/object/apply:os.system ["touch PWNED"]'
    f = write(proj, MIN + "verify:\n  m:\n    run: [" + tag + "]\n")
    monkeypatch.chdir(cwd)
    mod = profile_api()
    try:
        prof, problems = mod.load_profile(f)
    except Exception:  # noqa: BLE001 - refusing by raising is allowed
        prof, problems = None, ["raised"]
    assert problems
    assert prof is None
    assert listing(cwd) == []


def test_c4_cli_runs_with_repo_interpreter(tmp_path: Path) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "factory_tools", "profile", "check", str(FIXTURE)],
        cwd=tree(tmp_path),
        env=env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ---- criterion 5: docs/profile.md covers every model field --------------------


def doc_headings() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return re.findall(r"^## `([^`]+)`\s*$", text, flags=re.MULTILINE)


def test_c5_every_model_field_has_a_heading_and_no_extra() -> None:
    names = {f.name for f in dataclasses.fields(profile_api().Profile)}
    assert names, "Profile has no fields"
    assert set(doc_headings()) == names


def test_c5_headings_follow_model_order() -> None:
    names = [f.name for f in dataclasses.fields(profile_api().Profile)]
    assert doc_headings() == names


def test_c5_model_has_the_spec_fields() -> None:
    names = {f.name for f in dataclasses.fields(profile_api().Profile)}
    assert names == {
        "methodology",
        "verify",
        "exam",
        "protected_paths",
        "required_checks",
        "labels",
        "limits",
        "models",
        "smoke",
        "research_hints",
        "areas",
        "planning",
        "owner_files",
    }
