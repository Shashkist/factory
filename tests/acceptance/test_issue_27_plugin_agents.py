"""Issue #27: methodology plugin, slice 1 (plugin manifest and the four role agents).

Profile keys each agent must name (in backticks, e.g. `exam`), real keys of the profile loader:
  exam-writer: exam, planning
  implementer: verify
  reviewer:    protected_paths, required_checks
  researcher:  research_hints
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from helpers import ROOT

PLUGIN = ROOT / "plugin"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
AGENTS = ["exam-writer", "implementer", "reviewer", "researcher"]
FORBIDDEN = [
    "labs.shashkist.com",
    "207.154.193.238",
    "KodeKloud",
    "Killercoda",
    "labs/manager",
    "labs/web",
    "Learning_factory",
]
PROFILE_KEYS = {
    "exam-writer": ["exam", "planning"],
    "implementer": ["verify"],
    "reviewer": ["protected_paths", "required_checks"],
    "researcher": ["research_hints"],
}


def agent_path(name: str) -> Path:
    return PLUGIN / "agents" / f"{name}.md"


def read_agent(name: str) -> str:
    path = agent_path(name)
    assert path.is_file(), f"missing {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def frontmatter(name: str) -> dict:
    text = read_agent(name)
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    assert m, f"{name}.md has no YAML frontmatter"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{name}.md frontmatter is not a mapping"
    return data


def plugin_files() -> list[Path]:
    assert PLUGIN.is_dir(), "plugin/ directory does not exist"
    files = [p for p in PLUGIN.rglob("*") if p.is_file()]
    assert files, "plugin/ is empty"
    return files


# --- Criterion 1: the plugin validates (schema test) ---


def test_plugin_json_parses_with_name_factory_and_a_version() -> None:
    assert MANIFEST.is_file(), "missing plugin/.claude-plugin/plugin.json"
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("name") == "factory"
    version = data.get("version")
    assert isinstance(version, str) and version.strip()


@pytest.mark.parametrize("name", AGENTS)
def test_agent_frontmatter_has_name_description_and_tools(name: str) -> None:
    fm = frontmatter(name)
    assert fm.get("name") == name, "frontmatter name must equal the file stem"
    for key in ("description", "tools"):
        value = fm.get(key)
        assert value, f"{name}.md frontmatter needs a non-empty {key}"
        if isinstance(value, str):
            assert value.strip(), f"{name}.md frontmatter {key} is blank"


def test_plugin_has_exactly_the_four_role_agents() -> None:
    assert PLUGIN.is_dir(), "plugin/ directory does not exist"
    found = sorted(p.stem for p in (PLUGIN / "agents").glob("*.md"))
    assert found == sorted(AGENTS)


# --- Criterion 2: no project-specific text under plugin/ ---


@pytest.mark.parametrize("term", FORBIDDEN)
def test_no_file_under_plugin_contains_project_specific_term(term: str) -> None:
    offenders = []
    for path in plugin_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if term.lower() in text.lower():
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"{term!r} found in {offenders}"


# --- Criterion 3: agents are profile-driven ---


@pytest.mark.parametrize(
    ("name", "key"), [(n, k) for n, keys in PROFILE_KEYS.items() for k in keys]
)
def test_agent_names_the_profile_keys_it_reads(name: str, key: str) -> None:
    text = read_agent(name)
    assert f"`{key}`" in text, f"{name}.md must name the profile key `{key}` (in backticks)"


@pytest.mark.parametrize("name", AGENTS)
def test_agent_tells_the_reader_to_read_the_project_claude_md(name: str) -> None:
    assert "CLAUDE.md" in read_agent(name)


@pytest.mark.parametrize("name", AGENTS)
def test_agent_names_the_project_profile_file(name: str) -> None:
    assert ".factory/factory.yaml" in read_agent(name)


@pytest.mark.parametrize("name", AGENTS)
def test_agent_progress_calls_use_factory_tools_with_repo(name: str) -> None:
    text = read_agent(name)
    calls = [ln for ln in text.splitlines() if "factory-tools progress add" in ln]
    assert calls, f"{name}.md has no `factory-tools progress add` call"
    block = "\n".join(
        text[text.index("factory-tools progress add") :].splitlines()[:6]
    )
    assert "--repo" in block, f"{name}.md progress call must pass --repo"
