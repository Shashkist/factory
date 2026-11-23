"""Issue #1, criterion 5: an incident issue is opened once, later red runs comment."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import run_module, workflow_text

TITLE = "Incident: CI failed"
FAKE = Path(__file__).resolve().parent / "fake_gh.py"


class Fake:
    def __init__(self, tmp: Path) -> None:
        self.state = tmp / "state.json"
        self.state.write_text(json.dumps({"issues": [], "calls": []}), encoding="utf-8")
        self.env = {
            "FACTORY_GH": json.dumps([sys.executable, str(FAKE)]),
            "FAKE_GH_STATE": str(self.state),
        }

    def data(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def close_all(self) -> None:
        d = self.data()
        for it in d["issues"]:
            it["state"] = "closed"
        self.state.write_text(json.dumps(d), encoding="utf-8")

    def report(
        self, url: str, workflow: str = "CI"
    ) -> subprocess.CompletedProcess[str]:
        return run_module(
            "factory_tools.ci.incident",
            "--workflow",
            workflow,
            "--run-url",
            url,
            extra_env=self.env,
        )


@pytest.fixture
def fake(tmp_path: Path) -> Fake:
    return Fake(tmp_path)


def test_first_red_run_opens_one_incident_issue(fake: Fake) -> None:
    r = fake.report("https://example.invalid/runs/U1")
    assert r.returncode == 0, r.stdout + r.stderr
    issues = fake.data()["issues"]
    assert len(issues) == 1
    it = issues[0]
    assert it["title"] == TITLE
    assert it["state"] == "open"
    assert {"type:incident", "priority:p0"} <= set(it["labels"])
    assert "https://example.invalid/runs/U1" in it["body"]


def test_second_red_run_comments_on_the_same_open_issue(fake: Fake) -> None:
    assert fake.report("https://example.invalid/runs/U1").returncode == 0
    r = fake.report("https://example.invalid/runs/U2")
    assert r.returncode == 0, r.stdout + r.stderr
    issues = fake.data()["issues"]
    assert len(issues) == 1
    assert any("https://example.invalid/runs/U2" in c for c in issues[0]["comments"])


def test_red_run_after_the_incident_was_closed_opens_a_new_one(fake: Fake) -> None:
    assert fake.report("https://example.invalid/runs/U1").returncode == 0
    fake.close_all()
    r = fake.report("https://example.invalid/runs/U3")
    assert r.returncode == 0, r.stdout + r.stderr
    issues = fake.data()["issues"]
    assert len(issues) == 2
    assert [i["state"] for i in issues] == ["closed", "open"]
    assert issues[1]["title"] == TITLE


def test_other_workflow_names_get_their_own_incident(fake: Fake) -> None:
    assert fake.report("https://example.invalid/runs/U1").returncode == 0
    other = fake.report("https://example.invalid/runs/V1", workflow="Deploy")
    assert other.returncode == 0, other.stdout + other.stderr
    titles = sorted(i["title"] for i in fake.data()["issues"])
    assert titles == [TITLE, "Incident: Deploy failed"]


def test_incident_workflow_file_triggers_on_ci_completion_on_main_push() -> None:
    t = workflow_text("incident.yml")
    assert "workflow_run" in t
    assert "completed" in t
    assert "CI" in t
    assert "failure" in t
    assert "main" in t
    assert "push" in t
    assert "factory_tools.ci.incident" in t
