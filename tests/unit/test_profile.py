from pathlib import Path

from factory_tools.cli import main
from factory_tools.profile import load_profile


def load(tmp_path: Path, text: str):  # type: ignore[no-untyped-def]
    f = tmp_path / "p.yaml"
    f.write_text(text, encoding="utf-8")
    return load_profile(f)


def paths(tmp_path: Path, text: str) -> list[str]:
    return [p.path for p in load(tmp_path, text)[1]]


def test_non_mapping_document(tmp_path: Path) -> None:
    assert paths(tmp_path, "- a\n") == [""]


def test_empty_file_is_reported(tmp_path: Path) -> None:
    assert paths(tmp_path, "") == [""]


def test_verify_group_requires_run(tmp_path: Path) -> None:
    assert paths(tmp_path, 'methodology: "1"\nverify:\n  m: {cwd: x}\n') == ["verify.m.run"]


def test_list_item_paths(tmp_path: Path) -> None:
    text = 'methodology: "1"\nverify:\n  m:\n    run: [a, 1]\n'
    assert paths(tmp_path, text) == ["verify.m.run[1]"]


def test_limits_must_be_positive(tmp_path: Path) -> None:
    assert paths(tmp_path, 'methodology: "1"\nlimits: {ci_rounds: 0}\n') == ["limits.ci_rounds"]


def test_methodology_must_be_string(tmp_path: Path) -> None:
    assert paths(tmp_path, "methodology: 1\n") == ["methodology"]


def test_smoke_workflow_rejects_cwd(tmp_path: Path) -> None:
    text = 'methodology: "1"\nsmoke: {workflow: a.yml, cwd: x}\n'
    assert paths(tmp_path, text) == ["smoke.cwd"]


def test_areas_empty_list_is_a_problem(tmp_path: Path) -> None:
    assert paths(tmp_path, 'methodology: "1"\nareas: {a: []}\n') == ["areas.a"]


def test_glob_with_root_reports_item_index(tmp_path: Path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text('methodology: "1"\nareas:\n  a: ["x/**", "y/**"]\n', encoding="utf-8")
    (tmp_path / "x").mkdir()
    _, problems = load_profile(f, root=tmp_path)
    assert [p.path for p in problems] == ["areas.a[1]"]


def test_duplicate_key_in_nested_mapping(tmp_path: Path) -> None:
    text = 'methodology: "1"\nverify:\n  m:\n    run: [a]\n    cwd: x\n    cwd: y\n'
    assert paths(tmp_path, text) == ["verify.m.cwd"]


def test_invalid_glob_is_a_problem_not_a_traceback(tmp_path: Path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text('methodology: "1"\nareas:\n  a: [""]\n', encoding="utf-8")
    _, problems = load_profile(f, root=tmp_path)
    assert [(p.path, p.message) for p in problems] == [("areas.a[0]", "invalid glob")]


def test_invalid_yaml_is_fatal(tmp_path: Path) -> None:
    prof, problems = load(tmp_path, "a: [unclosed\n")
    assert prof is None
    assert problems[0].fatal


def test_main_returns_codes(tmp_path: Path, capsys: object) -> None:
    f = tmp_path / "p.yaml"
    f.write_text('methodology: "1"\n', encoding="utf-8")
    assert main(["profile", "check", str(f)]) == 0
    assert main(["profile", "check", str(tmp_path / "none.yaml")]) == 2
