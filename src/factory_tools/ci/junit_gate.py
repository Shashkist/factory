"""Fail when a pytest junit report has no tests, a skipped, failed or errored test.

Usage: python junit_gate.py <report.xml>

There is no way to accept an empty report: an exam run that collected nothing
is a broken gate, not a pass.
"""

import sys
import xml.etree.ElementTree as ET


def _count(root: ET.Element, attr: str, child: str) -> int:
    """Failed/errored cases, from the elements; attributes only as a larger fallback.

    Attributes are read from leaf suites and the root only, so a parent that
    sums its children is not counted twice.
    """
    cases = sum(1 for c in root.iter("testcase") if c.find(child) is not None)
    leaves = [s for s in root.iter("testsuite") if s.find("testsuite") is None]
    attrs = sum(int(s.get(attr, 0)) for s in leaves)
    return max(cases, attrs, int(root.get(attr, 0)))


def check(path: str) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return [f"cannot read report {path}: {exc}"]
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    skipped = max(
        sum(int(s.get("skipped", 0)) for s in suites),
        sum(1 for c in root.iter("testcase") if c.find("skipped") is not None),
    )
    failures = _count(root, "failures", "failure")
    errored = _count(root, "errors", "error")
    errors = []
    if tests == 0:
        errors.append("no acceptance tests ran")
    if skipped:
        errors.append(f"{skipped} acceptance tests were skipped")
    if failures:
        errors.append(f"{failures} acceptance tests failed")
    if errored:
        errors.append(f"{errored} acceptance tests errored")
    return errors


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: junit_gate.py <report.xml>")
        sys.exit(2)
    problems = check(sys.argv[1])
    for p in problems:
        print(f"FAIL: {p}")
    sys.exit(1 if problems else 0)
