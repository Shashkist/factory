# Ported from Shashkist/Learning_factory labs/factory-dashboard/tests/acceptance/test_issue_551_redaction_gaps.py at 29e3bf3 (factory#42).
# Only the two crew-title cases (page). The redaction cases test the reducer and are not ported.
"""Exam for issue #551 (review leftovers of #543, D143): redaction gaps and crew titles.

Observable contract, from the issue only:
  * The published live.json (the real renderer's output) contains no foreign URL: backslash dot segments under
    an allowed github.com/Shashkist/factory/ or .../Learning_factory/ prefix, an allowed URL containing a
    backslash, "/..", "%2e" or "%5c" (any case), an uppercase scheme, and a scheme-less github.com/someone/else/...
    are all redacted, in the title, the detail, the sub-step and the agent.
  * Plain allowed URLs (pull requests of this repository and of Shashkist/factory) are still published unchanged.
  * A crew node titled "PR#547" or "Build issue#1" attaches to this repository's lane #547 / #1 (the page, run
    in node through the #68 fake browser); "factory#1" still attaches to the other repository's lane.
No network, no machine environment (LF_CREW_DIR is unset); events are built in memory.
"""
# ruff: noqa: E501
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exam551_lanes", HERE / "test_issue_68_live_view_lanes.py")
assert _spec and _spec.loader
lanes_exam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lanes_exam)
base = lanes_exam.base

FOREIGN = "Shashkist/factory"
@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("LF_CREW_DIR", raising=False)
    monkeypatch.delenv("LF_PROGRESS_FILE", raising=False)


# ---- crew titles ---------------------------------------------------------------------------------

def _steps(issue: int, repo: str, title: str, agent: str) -> dict:
    return {"kind": "step", "at": base.ago(1), "issue": issue, "repo": repo, "title": title, "agent": agent,
            "role": "implementer", "station": "build", "substep": "tests", "status": "done", "detail": ""}


def crew_page(tmp_path: Path, crew_title: str) -> dict:
    live = base.render([base.start_pass(45), _steps(1, "", "Local one", "impl-l1"),
                        _steps(1, FOREIGN, "Foreign one", "impl-f1"), _steps(547, "", "Local 547", "impl-l547")])
    live = copy.deepcopy(live)
    live["crew"] = [{"id": "root", "type": "manager", "state": "busy", "tool": "Bash", "label": "pass", "title": "pass",
                     "last": base.ago(0.1), "children": [
                         {"id": "kid", "type": "implementer", "state": "busy", "tool": "CrewTool", "label": "x",
                          "title": crew_title, "last": base.ago(0.1), "children": []}]}]
    return lanes_exam.run_page(tmp_path, live)


def attached(root, lane_key: str) -> bool:
    got = [n for n in lanes_exam.by_class(root, "lane") if n["a"].get("data-lane") == lane_key]
    assert got, f"no lane {lane_key!r}"
    return "CrewTool" in base.text(got[0])


KEYS = ["1", "547", FOREIGN + "#1"]


@pytest.mark.parametrize("title,lane", [("PR#547", "547"), ("Build issue#1", "1"), ("#547", "547"), ("Learning_factory#1", "1")])
def test_crew_title_attaches_to_this_repositorys_lane(tmp_path, title, lane):
    root = crew_page(tmp_path, title)
    assert attached(root, lane), f"crew {title!r} did not attach to lane {lane}"
    assert [k for k in KEYS if k != lane and attached(root, k)] == [], "attached to more than one lane"


def test_crew_title_factory_hash_1_still_attaches_to_the_other_repositorys_lane(tmp_path):
    root = crew_page(tmp_path, "factory#1")
    assert attached(root, FOREIGN + "#1")
    assert not attached(root, "1") and not attached(root, "547")
