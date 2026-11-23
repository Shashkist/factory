from pathlib import Path

from factory_tools.ci.junit_gate import check


def _xml(tmp_path: Path, body: str) -> str:
    p = tmp_path / "x.xml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def _report(tmp_path: Path, tests: int, skipped: int, failures: int = 0, errors: int = 0) -> str:
    return _xml(
        tmp_path,
        f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
        f'failures="{failures}" errors="{errors}"/></testsuites>',
    )


def test_all_ran_passes(tmp_path: Path) -> None:
    assert check(_report(tmp_path, 3, 0)) == []


def test_skipped_fails(tmp_path: Path) -> None:
    assert len(check(_report(tmp_path, 3, 1))) == 1


def test_empty_fails(tmp_path: Path) -> None:
    assert len(check(_report(tmp_path, 0, 0))) == 1


def test_failures_and_errors_named(tmp_path: Path) -> None:
    assert check(_report(tmp_path, 5, 0, failures=2)) == ["2 acceptance tests failed"]
    assert check(_report(tmp_path, 5, 0, errors=3)) == ["3 acceptance tests errored"]
    assert len(check(_report(tmp_path, 5, 0, failures=1, errors=1))) == 2


def test_missing_report_is_reported_not_raised(tmp_path: Path) -> None:
    assert len(check(str(tmp_path / "nope.xml"))) == 1


def test_unparsable_report_is_reported(tmp_path: Path) -> None:
    assert len(check(_xml(tmp_path, "<testsuite"))) == 1


def test_multiple_testsuites_are_summed(tmp_path: Path) -> None:
    r = _xml(
        tmp_path,
        '<testsuites><testsuite tests="2" failures="0"/>'
        '<testsuite tests="2" failures="1"/></testsuites>',
    )
    assert check(r) == ["1 acceptance tests failed"]


def test_failures_only_on_testsuites_root(tmp_path: Path) -> None:
    r = _xml(tmp_path, '<testsuites failures="2"><testsuite tests="3"/></testsuites>')
    assert check(r) == ["2 acceptance tests failed"]


def test_failure_and_error_elements_without_counts(tmp_path: Path) -> None:
    r = _xml(
        tmp_path,
        '<testsuites><testsuite tests="3"><testcase name="a"><failure/></testcase>'
        '<testcase name="b"><error/></testcase><testcase name="c"/></testsuite></testsuites>',
    )
    assert check(r) == ["1 acceptance tests failed", "1 acceptance tests errored"]


def test_skipped_element_without_count(tmp_path: Path) -> None:
    r = _xml(
        tmp_path,
        '<testsuite tests="2"><testcase name="a"><skipped/></testcase>'
        '<testcase name="b"/></testsuite>',
    )
    assert check(r) == ["1 acceptance tests were skipped"]


def test_nested_parent_sums_children_not_double_counted(tmp_path: Path) -> None:
    r = _xml(
        tmp_path,
        '<testsuites failures="1"><testsuite tests="2" failures="1">'
        '<testsuite tests="2" failures="1"><testcase name="a"><failure/></testcase>'
        '<testcase name="b"/></testsuite></testsuite></testsuites>',
    )
    assert check(r) == ["1 acceptance tests failed"]
