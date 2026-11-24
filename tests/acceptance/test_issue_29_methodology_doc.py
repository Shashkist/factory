"""Issue #29: methodology plugin, slice 3 (docs/methodology.md and the README pointer).

The document must:
  - have a markdown heading naming every agent file and the skill found under plugin/
    (derived at test time, so a new agent without a section fails);
  - list, in backticks, every profile key the plugin reads: the keys slice 1 names per
    agent (PROFILE_KEYS of test_issue_27_plugin_agents) plus the keys slice 2's renderer
    and skill read (listed below, from the contract of test_issue_28_manager_skill);
  - describe the pass steps;
  - pass the same forbidden-words check as the plugin files;
  - be linked from README.md, which also gives the plugin install command.
"""

import dataclasses
import re

import pytest
from helpers import ROOT
from test_issue_27_plugin_agents import FORBIDDEN, PLUGIN, PROFILE_KEYS

from factory_tools.profile import Limits, OwnerFiles, Planning, Profile

DOC = ROOT / "docs" / "methodology.md"
README = ROOT / "README.md"

RENDERER = ROOT / "src" / "factory_tools" / "methodology.py"

# Keys read by the manager skill and the renderer (slice 2 contract); the renderer's own
# reads are also derived from its source at test time (see renderer_profile_keys).
SKILL_KEYS = [
    "methodology",
    "verify",
    "exam",
    "research_hints",
    "smoke",
    "owner_files",
    "limits",
]

# Nested profile keys, named as profile.py names them: parent -> sub-keys. Each sub-key must
# be listed as `parent.sub` or as `sub` in backticks.
NESTED = {
    "limits": [f.name for f in dataclasses.fields(Limits)],
    "planning": [f.name for f in dataclasses.fields(Planning)],
    "owner_files": [f.name for f in dataclasses.fields(OwnerFiles)],
}

PASS_STEPS = {
    "orient": r"orient",
    "fix the line": r"fix\s+the\s+line",
    "plan": r"\bplan",
    "pick and claim": r"pick\s+and\s+claim",
    "decide": r"\bdecide",
    "exam/build/check": r"exam\s*/\s*build\s*/\s*check|exam[^\n]{0,40}build[^\n]{0,40}check",
    "ship": r"\bship",
    "close": r"\bclose",
    "loop": r"\bloop",
}


def doc_text() -> str:
    assert DOC.is_file(), f"missing {DOC.relative_to(ROOT)}"
    return DOC.read_text(encoding="utf-8")


def headings() -> list[str]:
    return [
        ln.lstrip("#").strip().lower()
        for ln in doc_text().splitlines()
        if re.match(r"^#{1,6}\s+\S", ln)
    ]


def plugin_agent_names() -> list[str]:
    assert PLUGIN.is_dir(), "plugin/ directory does not exist"
    return sorted(p.stem for p in (PLUGIN / "agents").glob("*.md"))


def plugin_skill_names() -> list[str]:
    assert PLUGIN.is_dir(), "plugin/ directory does not exist"
    return sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))


def renderer_profile_keys() -> set[str]:
    fields = {f.name for f in dataclasses.fields(Profile)}
    used = set(re.findall(r"\bp\.([a-z_]+)", RENDERER.read_text(encoding="utf-8")))
    return used & fields


def plugin_profile_keys() -> list[str]:
    keys = {k for ks in PROFILE_KEYS.values() for k in ks}
    keys.update(SKILL_KEYS)
    keys.update(renderer_profile_keys())
    return sorted(keys)


def nested_keys() -> list[tuple[str, str]]:
    return [(parent, sub) for parent, subs in NESTED.items() for sub in subs]


# --- Criterion 1: a section per agent and the skill, every profile key listed ---


def test_methodology_document_exists() -> None:
    assert DOC.is_file(), "missing docs/methodology.md"
    assert doc_text().strip()


def test_plugin_has_agents_and_a_skill_to_document() -> None:
    assert plugin_agent_names(), "no agents under plugin/agents"
    assert plugin_skill_names(), "no skill under plugin/skills"


@pytest.mark.parametrize("name", plugin_agent_names() or ["<no agents found>"])
def test_every_agent_has_a_section_in_the_methodology_document(name: str) -> None:
    assert any(name.lower() in h for h in headings()), (
        f"docs/methodology.md has no heading naming the agent {name!r}"
    )


@pytest.mark.parametrize("name", plugin_skill_names() or ["<no skills found>"])
def test_the_skill_has_a_section_in_the_methodology_document(name: str) -> None:
    assert any(name.lower() in h for h in headings()), (
        f"docs/methodology.md has no heading naming the skill {name!r}"
    )


@pytest.mark.parametrize("key", plugin_profile_keys())
def test_every_profile_key_the_plugin_reads_is_listed_in_the_document(key: str) -> None:
    assert f"`{key}`" in doc_text(), f"profile key `{key}` is not listed (in backticks)"


def test_renderer_reads_profile_keys_so_the_derivation_is_not_empty() -> None:
    assert {"labels", "limits", "planning", "owner_files"} <= renderer_profile_keys()


@pytest.mark.parametrize(("parent", "sub"), nested_keys())
def test_every_nested_profile_key_is_listed_in_the_document(parent: str, sub: str) -> None:
    text = doc_text()
    assert f"`{parent}.{sub}`" in text or f"`{sub}`" in text, (
        f"nested key {parent}.{sub} is not listed (as `{parent}.{sub}` or `{sub}` in backticks)"
    )


def test_document_names_the_claude_md_sections_roles_read() -> None:
    assert "CLAUDE.md" in doc_text()


# --- Criterion 2: the pass steps are described ---


@pytest.mark.parametrize("step", sorted(PASS_STEPS))
def test_document_describes_pass_step_(step: str) -> None:
    assert re.search(PASS_STEPS[step], doc_text(), re.IGNORECASE), f"pass step {step!r} missing"


# --- Criterion 3: the forbidden-words test of slice 1 passes on the document ---


@pytest.mark.parametrize("term", FORBIDDEN)
def test_document_contains_no_project_specific_term(term: str) -> None:
    assert term.lower() not in doc_text().lower(), f"{term!r} found in docs/methodology.md"


# --- Criterion 4: README points to the document and the install command ---


def readme_text() -> str:
    assert README.is_file(), "missing README.md"
    return README.read_text(encoding="utf-8")


def test_readme_links_to_the_methodology_document() -> None:
    assert re.search(r"\]\((\./)?docs/methodology\.md(#[^)]*)?\)", readme_text()), (
        "README.md must link to docs/methodology.md"
    )


def test_readme_contains_the_plugin_install_command() -> None:
    assert re.search(r"(/plugin install|claude plugin install)\s+\S+", readme_text()), (
        "README.md must give the plugin install command (/plugin install <name>)"
    )
