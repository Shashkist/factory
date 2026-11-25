"""Issue #62 (slice C of #5): reusable incident workflow for client repositories.

Criterion 1 reads the workflow as data. Criterion 2 runs the incident tool the
way the workflow calls it, with a recording fake `gh`, and checks which
repository every gh call targets. Criterion 3 is covered by the existing #1
incident cases, which this exam does not touch.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import ROOT, env

WF_DIR = ROOT / ".github" / "workflows"
INCIDENT = "incident.yml"
TOOL = ROOT / "src" / "factory_tools" / "ci" / "incident.py"
CLIENT = "some-client/repo"
FACTORY = "Shashkist/factory"

FAKE_GH = """
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
repo = os.environ.get("GH_REPO", "")
for flag in ("-R", "--repo"):
    while flag in args:
        i = args.index(flag)
        repo = args[i + 1]
        del args[i : i + 2]
s = json.load(open(state_path, encoding="utf-8"))
s["calls"].append({"repo": repo, "args": args})

def opt(name):
    return args[args.index(name) + 1] if name in args else ""

if args[:2] == ["issue", "list"]:
    out = [
        {"number": i["number"], "title": i["title"], "state": "OPEN",
         "body": i["body"], "labels": [{"name": n} for n in i["labels"]]}
        for i in s["issues"] if i["repo"] == repo
    ]
    print(json.dumps(out))
elif args[:2] == ["issue", "create"]:
    n = len(s["issues"]) + 1
    s["issues"].append({"number": n, "repo": repo, "title": opt("--title"),
                        "body": opt("--body"), "comments": [],
                        "labels": [x for x in opt("--label").split(",") if x]})
    print("https://example.invalid/issues/%d" % n)
elif args[:2] == ["issue", "comment"]:
    for i in s["issues"]:
        if i["number"] == int(args[2].lstrip("#")) and i["repo"] == repo:
            i["comments"].append(opt("--body"))
else:
    json.dump(s, open(state_path, "w", encoding="utf-8"))
    sys.stderr.write("fake gh: unsupported " + " ".join(args) + "\\n")
    sys.exit(2)
json.dump(s, open(state_path, "w", encoding="utf-8"))
"""


def load() -> dict[str, Any]:
    assert (WF_DIR / INCIDENT).is_file(), f"{INCIDENT} does not exist"
    data = yaml.safe_load((WF_DIR / INCIDENT).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def on_block(wf: dict[str, Any]) -> Any:
    # YAML 1.1 parses the bare key `on` as boolean True.
    return wf["on"] if "on" in wf else wf.get(True)


def all_steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for job in (wf.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def inputs(wf: dict[str, Any]) -> dict[str, Any]:
    on = on_block(wf)
    assert isinstance(on, dict) and "workflow_call" in on, "no on: workflow_call"
    return (on["workflow_call"] or {}).get("inputs") or {}


def tool_fetches(wf: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in all_steps(wf)
        if "checkout" in str(s.get("uses", ""))
        and "job.workflow_sha" in json.dumps(s.get("with") or {})
    ]


# --- criterion 1: the workflow file -------------------------------------


def test_incident_workflow_has_workflow_call_trigger() -> None:
    on = on_block(load())
    assert isinstance(on, dict) and "workflow_call" in on


def test_workflow_call_inputs_are_all_described() -> None:
    ins = inputs(load())
    assert len(ins) >= 3, f"expected at least 3 inputs, got {list(ins)}"
    for name, spec in ins.items():
        desc = (spec or {}).get("description")
        assert isinstance(desc, str) and desc.strip(), f"input {name} has no description"


@pytest.mark.parametrize(
    "meaning",
    ["workflow", "url", "conclusion"],
    ids=["workflow-name", "run-url", "conclusion"],
)
def test_workflow_call_has_an_input_for(meaning: str) -> None:
    ins = inputs(load())
    hits = [
        n
        for n, spec in ins.items()
        if re.search(meaning, n, re.I)
        or re.search(meaning, str((spec or {}).get("description")), re.I)
    ]
    assert hits, f"no input about '{meaning}' among {list(ins)}"


def test_incident_tool_is_fetched_at_job_workflow_sha_from_this_repository() -> None:
    fetch = [
        s
        for s in tool_fetches(load())
        if "job.workflow_repository" in json.dumps(s.get("with") or {})
    ]
    assert fetch, "no checkout of job.workflow_repository at job.workflow_sha"


def test_tool_run_comes_from_the_fetched_copy_not_the_callers_tree() -> None:
    wf = load()
    fetch = tool_fetches(wf)
    assert fetch, "no tool checkout at job.workflow_sha"
    path = str((fetch[0].get("with") or {}).get("path", "")).strip("./")
    assert path, "the tool must be checked out into its own path, not over the caller"
    runs = [str(s.get("run", "")) for s in all_steps(wf)]
    assert any(path in r and "incident" in r for r in runs), (
        f"no run step calls the incident tool from {path}"
    )


def test_gh_repo_is_the_callers_repository() -> None:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "GH_REPO":
                    found.append(str(v))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(load())
    assert found, "GH_REPO is not set"
    for v in found:
        assert "github.repository" in v, f"GH_REPO={v!r} is not the caller's repository"
        assert FACTORY not in v


def test_this_repositorys_own_incident_path_is_kept() -> None:
    on = on_block(load())
    own_trigger = isinstance(on, dict) and "workflow_run" in on
    thin_caller = False
    pattern = r"uses:\s*(\./|Shashkist/factory/)\.github/workflows/incident\.yml"
    for f in WF_DIR.glob("*.yml"):
        if f.name != INCIDENT and re.search(pattern, f.read_text(encoding="utf-8")):
            thin_caller = True
    assert own_trigger or thin_caller, "no workflow_run trigger and no thin caller"


def test_fail_open_plain_gh_issue_create_fallback_remains() -> None:
    runs = [str(s.get("run", "")) for s in all_steps(load())]
    assert any("gh issue create" in r and "||" in r for r in runs), (
        "the tool run must fall back to a plain `gh issue create` with ||"
    )


def test_fetching_the_tool_cannot_hide_an_incident() -> None:
    fetch = tool_fetches(load())
    assert fetch, "no tool checkout at job.workflow_sha"
    assert all(s.get("continue-on-error") in (True, "true") for s in fetch), (
        "a failed tool fetch must not stop the fallback (continue-on-error)"
    )


# --- criterion 2: the tool, called as the workflow calls it -------------


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"issues": [], "calls": []}), encoding="utf-8")
    return {"dir": tmp_path, "state": state}


def report(world: dict[str, Any], url: str) -> subprocess.CompletedProcess[str]:
    # The workflow runs the file directly: python3 <tools>/src/factory_tools/ci/incident.py
    e = env(
        {
            "GH_REPO": CLIENT,
            "GH_TOKEN": "placeholder",
            "FACTORY_GH": json.dumps([sys.executable, str(world["dir"] / "fake_gh.py")]),
            "FAKE_GH_STATE": str(world["state"]),
        }
    )
    return subprocess.run(
        [sys.executable, str(TOOL), "--workflow", "CI", "--run-url", url],
        cwd=world["dir"],
        env=e,
        capture_output=True,
        text=True,
        timeout=120,
    )


def data(world: dict[str, Any]) -> dict[str, Any]:
    return json.loads(world["state"].read_text(encoding="utf-8"))


def test_tool_opens_the_incident_in_the_calling_repository(world: dict[str, Any]) -> None:
    r = report(world, "https://example.invalid/client/runs/1")
    assert r.returncode == 0, r.stdout + r.stderr
    d = data(world)
    assert len(d["issues"]) == 1
    issue = d["issues"][0]
    assert issue["repo"] == CLIENT
    assert issue["title"] == "Incident: CI failed"
    assert "https://example.invalid/client/runs/1" in issue["body"]


def test_tool_comments_on_the_calling_repositorys_open_incident(
    world: dict[str, Any],
) -> None:
    assert report(world, "https://example.invalid/client/runs/1").returncode == 0
    r = report(world, "https://example.invalid/client/runs/2")
    assert r.returncode == 0, r.stdout + r.stderr
    d = data(world)
    assert len(d["issues"]) == 1
    assert any("runs/2" in c for c in d["issues"][0]["comments"])


def test_tool_never_targets_the_factory_repository(world: dict[str, Any]) -> None:
    assert report(world, "https://example.invalid/client/runs/1").returncode == 0
    assert report(world, "https://example.invalid/client/runs/2").returncode == 0
    d = data(world)
    assert d["calls"], "gh was never called"
    for call in d["calls"]:
        assert call["repo"] == CLIENT, f"gh call targeted {call['repo']!r}: {call['args']}"
        assert call["repo"] != FACTORY
