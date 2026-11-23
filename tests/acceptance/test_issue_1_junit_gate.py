"""Issue #1, criterion 1: the JUnit gate rejects bad or empty reports."""

from pathlib import Path

import pytest
from helpers import run_module

GATE = "factory_tools.ci.junit_gate"

PASS = '<testcase classname="a" name="ok"/>'
FAIL = '<testcase classname="a" name="bad"><failure message="boom"/></testcase>'
ERROR = '<testcase classname="a" name="bad"><error message="boom"/></testcase>'
SKIP = '<testcase classname="a" name="bad"><skipped message="why"/></testcase>'


def report(tmp_path: Path, cases: str, wrapped: bool = True) -> Path:
    n = cases.count("<testcase")
    suite = f'<testsuite name="pytest" tests="{n}">{cases}</testsuite>'
    xml = f"<testsuites>{suite}</testsuites>" if wrapped else suite
    p = tmp_path / "report.xml"
    p.write_text('<?xml version="1.0" encoding="utf-8"?>' + xml, encoding="utf-8")
    return p


def test_all_passed_report_is_accepted(tmp_path: Path) -> None:
    r = run_module(GATE, str(report(tmp_path, PASS + PASS)))
    assert r.returncode == 0, r.stdout + r.stderr


def test_all_passed_report_with_bare_testsuite_root_is_accepted(tmp_path: Path) -> None:
    r = run_module(GATE, str(report(tmp_path, PASS, wrapped=False)))
    assert r.returncode == 0, r.stdout + r.stderr


IDS = ["failed", "errored", "skipped"]


@pytest.mark.parametrize("bad", [FAIL, ERROR, SKIP], ids=IDS)
def test_report_with_failed_errored_or_skipped_case_is_rejected(
    tmp_path: Path, bad: str
) -> None:
    r = run_module(GATE, str(report(tmp_path, PASS + bad)))
    assert r.returncode != 0, r.stdout + r.stderr
    assert "No module named" not in r.stderr


def test_report_with_zero_tests_is_rejected(tmp_path: Path) -> None:
    r = run_module(GATE, str(report(tmp_path, "")))
    assert r.returncode != 0, r.stdout + r.stderr
    assert "No module named" not in r.stderr


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    r = run_module(GATE, str(tmp_path / "nope.xml"))
    assert r.returncode != 0
    assert "No module named" not in r.stderr
