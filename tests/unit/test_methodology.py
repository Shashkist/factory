"""Unit tests for the methodology renderer."""

from pathlib import Path

import pytest

from factory_tools import methodology
from factory_tools.profile import Limits, OwnerFiles, Profile, Smoke, VerifyGroup


def test_defaults_are_the_documented_ones() -> None:
    text = methodology.render_profile(Profile(methodology="0.1"))
    assert "**/tests/acceptance/**" in text
    assert "ci_rounds: 5" in text and "review_rounds: 2" in text and "parallel_issues: 3" in text
    assert "smoke: none configured" in text
    assert ".factory/DECISIONS.md" in text and ".factory/OWNER.md" in text


def test_given_values_are_printed() -> None:
    p = Profile(
        methodology="0.1",
        verify={"api": VerifyGroup(run=("make test",), cwd="svc")},
        exam=("svc/tests/acc/**",),
        limits=Limits(ci_rounds=7),
        smoke=Smoke(workflow="smoke.yml"),
        research_hints=("a docs site",),
        protected_paths=("ci/**",),
        required_checks=("unit",),
        owner_files=OwnerFiles(decisions="d.md", owner="o.md"),
    )
    text = methodology.render_profile(p)
    wanted = [
        "api (cwd `svc`)",
        "`make test`",
        "svc/tests/acc/**",
        "ci_rounds: 7",
        "workflow `smoke.yml`",
        "a docs site",
        "`ci/**`",
        "required checks: unit",
        "`d.md`",
        "`o.md`",
    ]
    for want in wanted:
        assert want in text


def test_smoke_command_form() -> None:
    p = Profile(methodology="0.1", smoke=Smoke(run="./smoke.sh", cwd="ops"))
    assert "command `./smoke.sh` (cwd `ops`)" in methodology.render_profile(p)


def test_run_missing_file_exits_2_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert methodology.run(str(tmp_path / "gone.yaml")) == 2
    assert "gone.yaml" in capsys.readouterr().out


def test_run_invalid_profile_exits_1(tmp_path: Path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text("methodology: '0.1'\nbogus: 1\n", encoding="utf-8")
    assert methodology.run(str(f)) == 1
