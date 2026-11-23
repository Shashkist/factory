import json

import pytest

from factory_tools.ci import incident


class FakeGh:
    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        return ""


def _issue(number: int, title: str, label: str = "type:incident") -> dict[str, object]:
    return {"number": number, "title": title, "labels": [{"name": label}]}


def test_opens_issue_when_none_open(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGh([])
    monkeypatch.setattr(incident, "_gh", gh)
    incident.report("CI", "u1")
    create = gh.calls[-1]
    assert create[:2] == ("issue", "create")
    assert "Incident: CI failed" in create
    assert incident.LABELS in create


def test_comments_on_matching_open_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGh([_issue(7, "Incident: CI failed")])
    monkeypatch.setattr(incident, "_gh", gh)
    incident.report("CI", "u2")
    assert gh.calls[-1] == ("issue", "comment", "7", "--body", "Failed again: u2")


def test_ignores_other_titles_and_unlabelled_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGh([_issue(1, "Incident: Deploy failed"), _issue(2, "Incident: CI failed", "bug")])
    monkeypatch.setattr(incident, "_gh", gh)
    incident.report("CI", "u3")
    assert gh.calls[-1][:2] == ("issue", "create")


def test_gh_prefix_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACTORY_GH", json.dumps(["python", "-c", "print('[]')"]))
    assert incident._gh("issue", "list").strip() == "[]"


def test_main_returns_1_when_gh_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FACTORY_GH", json.dumps(["python", "-c", "raise SystemExit(3)"]))
    assert incident.main(["--workflow", "CI", "--run-url", "u"]) == 1
    assert "incident: failed" in capsys.readouterr().err
