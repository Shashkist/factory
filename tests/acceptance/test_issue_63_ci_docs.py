"""Issue #63 (slice D of #5): docs/ci.md, the guide to the reusable workflows.

The exam reads the reusable workflows (those with an on.workflow_call trigger)
and docs/ci.md as data, offline. That the tag v0.1.0 exists and its commit has a
green CI run is checked with gh when the issue is closed (D30), not here.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import ROOT

WF_DIR = ROOT / ".github" / "workflows"
DOC = ROOT / "docs" / "ci.md"
REQUIRED = {"exam-integrity.yml", "junit-gate.yml", "incident.yml"}

# Every `uses:` line naming a .github/workflows/ file: quoted or not, any case, any
# owner/repo, or local (./.github/workflows/x.yml, which has no @ref: ref is "").
USES = re.compile(
    r"""uses:\s*(?P<q>['"]?)(?:\./|[\w.-]+/[\w.-]+/)\.github/workflows/"""
    r"""(?P<file>[\w.-]+)(?:@(?P<ref>[^\s'"]*))?(?P=q)(?P<rest>.*)$""",
    re.IGNORECASE,
)
PINNED = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*(v\d+\.\d+\.\d+)\s*$")


def _load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _trigger(wf: dict[Any, Any]) -> Any:
    # PyYAML reads the key `on` as boolean True.
    return wf.get("on", wf.get(True))


def _call_block(wf: dict[Any, Any]) -> dict[str, Any] | None:
    trig = _trigger(wf)
    if isinstance(trig, dict) and "workflow_call" in trig:
        return trig["workflow_call"] or {}
    return None


def _discover() -> dict[str, dict[Any, Any]]:
    found: dict[str, dict[Any, Any]] = {}
    for p in sorted(WF_DIR.glob("*.yml")):
        wf = _load(p)
        if _call_block(wf) is not None:
            found[p.name] = wf
    return found


WORKFLOWS = _discover()
NAMES = sorted(WORKFLOWS)


def _permission_keys(wf: dict[Any, Any]) -> set[str]:
    keys: set[str] = set()
    top = wf.get("permissions")
    if isinstance(top, dict):
        keys |= set(top)
    for job in (wf.get("jobs") or {}).values():
        perms = job.get("permissions") if isinstance(job, dict) else None
        if isinstance(perms, dict):
            keys |= set(perms)
    return keys


def _doc_text() -> str:
    assert DOC.is_file(), "docs/ci.md does not exist"
    return DOC.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Map workflow file name to its section text.

    A section starts at a heading naming the file and runs to the next heading
    of the same or a higher level (sub-headings belong to it).
    """
    lines = text.splitlines()
    heads: list[tuple[int, int, str]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and not in_fence:
            heads.append((i, len(m.group(1)), m.group(2)))
    out: dict[str, str] = {}
    for idx, (start, level, title) in enumerate(heads):
        end = len(lines)
        for nxt_start, nxt_level, _ in heads[idx + 1 :]:
            if nxt_level <= level:
                end = nxt_start
                break
        for name in NAMES:
            if name in title and name not in out:
                out[name] = "\n".join(lines[start:end])
    return out


def _section(name: str) -> str:
    sections = _sections(_doc_text())
    assert name in sections, f"docs/ci.md has no heading naming {name}"
    return sections[name]


def _uses_lines(text: str) -> list[tuple[str, str, str]]:
    return [
        (m.group("file"), m.group("ref") or "", m.group("rest"))
        for m in map(USES.search, text.splitlines())
        if m
    ]


def _is_valid_pin(ref: str, rest: str) -> bool:
    return bool(PINNED.match(ref)) and bool(VERSION_COMMENT.match(rest))


def test_the_three_reusable_workflows_are_found() -> None:
    assert REQUIRED <= set(NAMES), f"found only {NAMES}"


def test_ci_doc_exists() -> None:
    assert DOC.is_file(), "docs/ci.md does not exist"


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_ci_doc_has_one_section_per_reusable_workflow(name: str) -> None:
    text = _doc_text()
    headings = [
        ln for ln in text.splitlines() if re.match(r"^#{1,6}\s+", ln) and name in ln
    ]
    assert len(headings) == 1, f"expected exactly one heading naming {name}, got {headings}"


@pytest.mark.parametrize("name", NAMES)
def test_every_declared_input_and_secret_is_documented_in_its_section(name: str) -> None:
    call = _call_block(WORKFLOWS[name]) or {}
    declared = list(call.get("inputs") or {}) + list(call.get("secrets") or {})
    section = _section(name)
    missing = [d for d in declared if f"`{d}`" not in section]
    assert not missing, f"{name}: not named as code in its section: {missing}"


@pytest.mark.parametrize("name", NAMES)
def test_each_section_states_the_permissions_the_caller_must_grant(name: str) -> None:
    keys = _permission_keys(WORKFLOWS[name])
    section = _section(name)
    missing = [
        k for k in sorted(keys) if not re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", section)
    ]
    assert not missing, f"{name}: permissions not stated in its section: {missing}"


def test_every_uses_line_is_pinned_by_full_sha_with_version_comment() -> None:
    uses = _uses_lines(_doc_text())
    assert uses, "docs/ci.md has no `uses: .../.github/workflows/...` example"
    bad = [f"{f}@{r}{rest}" for f, r, rest in uses if not _is_valid_pin(r, rest)]
    assert not bad, f"not pinned by a 40-hex SHA followed by a '# v<semver>' comment: {bad}"


@pytest.mark.parametrize("name", NAMES)
def test_each_section_has_a_pinned_example_for_its_workflow(name: str) -> None:
    uses = _uses_lines(_section(name))
    good = [u for u in uses if u[0] == name and _is_valid_pin(u[1], u[2])]
    assert good, f"{name}: no pinned example `uses: ...{name}@<sha> # v<semver>` in its section"


def test_all_pinned_examples_use_one_sha_and_one_version() -> None:
    uses = [u for u in _uses_lines(_doc_text()) if _is_valid_pin(u[1], u[2])]
    assert uses, "docs/ci.md has no pinned example"
    shas = {u[1] for u in uses}
    versions = {VERSION_COMMENT.match(u[2]).group(1) for u in uses}  # type: ignore[union-attr]
    assert len(shas) == 1, f"examples pin different SHAs: {sorted(shas)}"
    assert len(versions) == 1, f"examples name different versions: {sorted(versions)}"


SHA = "0123456789abcdef0123456789abcdef01234567"
WF = ".github/workflows/exam-integrity.yml"


def _bad(line: str) -> list[str]:
    return [f for f, r, rest in _uses_lines(line) if not _is_valid_pin(r, rest)]


@pytest.mark.parametrize(
    "line",
    [
        f"    uses: Shashkist/factory/{WF}@{SHA} # v0.1.0",
        f"    - uses: Shashkist/factory/{WF}@{SHA} # v0.1.0",
        f'    uses: "Shashkist/factory/{WF}@{SHA}" # v0.1.0',
        f"    uses: 'Shashkist/factory/{WF}@{SHA}' # v0.1.0",
        f"    uses: SHASKIST/Factory/.GitHub/Workflows/exam-integrity.yml@{SHA} # v0.1.0",
        f"    uses: other-org/other.repo/{WF}@{SHA} # v0.1.0",
    ],
)
def test_parser_collects_and_accepts_a_pinned_line(line: str) -> None:
    assert len(_uses_lines(line)) == 1, f"line not collected: {line}"
    assert _bad(line) == [], f"pinned line rejected: {line}"


@pytest.mark.parametrize("quote", ["", '"', "'"])
@pytest.mark.parametrize(
    "ref,comment",
    [
        (SHA[:7], " # v0.1.0"),
        (SHA[:12], " # v0.1.0"),
        ("v0.1.0", ""),
        ("v0.1.0", " # v0.1.0"),
        ("main", ""),
        (SHA, ""),
        (SHA, " # main"),
        (SHA.upper(), " # v0.1.0"),
        (SHA + "0", " # v0.1.0"),
    ],
)
def test_parser_collects_and_rejects_an_unpinned_line(quote: str, ref: str, comment: str) -> None:
    line = f"    uses: {quote}Shashkist/factory/{WF}@{ref}{quote}{comment}"
    assert len(_uses_lines(line)) == 1, f"line not collected: {line}"
    assert len(_bad(line)) == 1, f"unpinned line accepted: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "    uses: ./.github/workflows/exam-integrity.yml",
        '    uses: "./.github/workflows/exam-integrity.yml"',
        "    uses: './.github/workflows/exam-integrity.yml'",
        f"    uses: ./.github/workflows/exam-integrity.yml # {SHA} v0.1.0",
        "    uses: ./.GITHUB/workflows/exam-integrity.yml",
    ],
)
def test_parser_collects_and_rejects_a_local_workflow_line(line: str) -> None:
    assert len(_uses_lines(line)) == 1, f"local line not collected: {line}"
    assert len(_bad(line)) == 1, f"local line accepted as pinned: {line}"


def test_parser_collects_another_owners_workflow_and_rejects_it_unpinned() -> None:
    line = f"    uses: acme/ci/{WF}@main"
    assert len(_uses_lines(line)) == 1
    assert len(_bad(line)) == 1


def test_parser_reports_the_workflow_file_name() -> None:
    line = f'    uses: "Shashkist/factory/{WF}@{SHA}" # v0.1.0'
    assert _uses_lines(line) == [("exam-integrity.yml", SHA, " # v0.1.0")]


@pytest.mark.parametrize(
    "line",
    [
        "    uses: actions/checkout@v4",
        "    uses: Shashkist/factory/actions/thing@main",
        "    run: echo uses nothing",
    ],
)
def test_parser_ignores_lines_not_naming_a_workflow_file(line: str) -> None:
    assert _uses_lines(line) == []
