"""repos.yaml reading, per-repository counts and the gh fallback of the dashboard builder."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from factory_tools.dashboard import snapshot
from factory_tools.dashboard.snapshot import Source, build, read_repos


def issue(n: int, labels: list[str], state: str = "OPEN") -> dict[str, object]:
    return {"number": n, "title": f"t{n}", "state": state, "url": "u",
            "createdAt": "2026-11-01T00:00:00Z", "closedAt": None,
            "labels": [{"name": x} for x in labels]}


def test_read_repos_keeps_order_and_ignores_other_keys(tmp_path: Path) -> None:
    f = tmp_path / "repos.yaml"
    f.write_text("- repo: a/b\n  x: 1\n- note: no repo\n- repo: c/d\n", encoding="utf-8")
    assert read_repos(f) == ["a/b", "c/d"]
    f.write_text("", encoding="utf-8")
    assert read_repos(f) == []


def test_build_counts_per_repository_and_totals(tmp_path: Path) -> None:
    data = {
        "o/a": [issue(1, ["status:ready", "priority:p1"])],
        "o/b": [issue(1, ["status:ready", "priority:p2"]), issue(2, [], "CLOSED")],
    }
    for repo, issues in data.items():
        d = tmp_path / repo.replace("/", "__")
        d.mkdir()
        (d / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
    snap = build([Source(tmp_path, "o/a"), Source(tmp_path, "o/b")],
                 datetime(2026, 11, 24, tzinfo=UTC))
    assert snap["repos"]["o/a"]["issues"]["open"] == 1
    assert snap["repos"]["o/b"]["issues"]["closed"] == 1
    assert snap["issues"]["open"] == 2 and snap["issues"]["by_status"] == {"ready": 2}
    assert [(q["repo"], q["number"]) for q in snap["queue"]] == [("o/a", 1), ("o/b", 1)]


def test_a_missing_doc_through_gh_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(args: list[str]) -> str:
        raise RuntimeError("gh failed")

    monkeypatch.setattr(snapshot, "gh_run", boom)
    assert Source(None, "o/a").doc("OWNER.md") == ""


def test_gh_calls_name_the_repository_and_read_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(args: list[str]) -> str:
        seen.append(args)
        return "[]"

    monkeypatch.setattr(snapshot, "gh_run", fake)
    src = Source(None, "o/a")
    src.issues()
    src.prs()
    src.doc("DECISIONS.md")
    assert seen[0][:3] == ["issue", "list", "-R"] and seen[0][3] == "o/a"
    assert seen[1][:4] == ["pr", "list", "-R", "o/a"]
    assert seen[2][1] == "repos/o/a/contents/docs/factory/DECISIONS.md"
    assert "application/vnd.github.raw" in seen[2][-1]
