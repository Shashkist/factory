"""Page behaviour the exam does not pin: LF's live.json writes repo "" for the host repository's lanes."""
# ruff: noqa: E501

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "factory_tools" / "dashboard" / "static"
HARNESS = ROOT / "tests" / "acceptance" / "dashboard" / "dom_harness_6.js"
LF = "Shashkist/Learning_factory"
FA = "Shashkist/factory"
TP = {"closed_per_day": [0] * 14, "median_lead_time_hours": 0, "open_incidents": 0}
COUNTS = {"open": 1, "closed": 0, "by_status": {}, "by_phase": {}, "by_priority": {}}


def snapshot() -> dict[str, Any]:
    return {
        "generated_at": "2026-11-24T11:59:00+00:00",
        "issues": COUNTS,
        "repos": {LF: {"issues": COUNTS, "claim": None, "throughput": TP}, FA: {"issues": COUNTS, "claim": None, "throughput": TP}},
        "lanes": [], "queue": [], "claim": None,
        "prs": {"open": [], "merged": [
            {"repo": FA, "number": 99, "title": "feat: factory thing (#7)", "url": "https://x/99",
             "merged_at": "2026-11-23T09:00:00Z"}]},
        "runs": {LF: {"CI": {"repo": LF, "status": "completed", "conclusion": "success", "url": "u"}},
                 FA: {}},
        "server": None,
        "decisions": [{"repo": LF, "id": f"D{i}", "title": f"lf decision {i}"} for i in range(1, 9)]
        + [{"repo": FA, "id": f"D{i}", "title": f"fa decision {i}"} for i in range(1, 3)],
        "owner_open": [{"repo": FA, "id": "O3", "title": "fa owner"}],
        "throughput": {"closed_per_day": [0] * 14, "median_lead_time_hours": 0, "open_incidents": 0},
    }


def render(tmp_path: Path) -> dict[str, Any]:
    node = shutil.which("node")
    assert node
    live = {"generated_at": "2026-11-24T11:59:30+00:00", "schema": 1, "runner": {"state": "running"},
            "issues": [{"issue": 7, "repo": "", "title": "host lane", "station": "build"}],
            "agents": [], "workers": [], "crew": [], "log": []}
    sc = tmp_path / "s.json"
    sc.write_text(json.dumps({"now": "2026-11-24T12:00:00Z", "snapshot": snapshot(),
                              "steps": [{"now": "2026-11-24T12:00:00Z", "live": live}]}), encoding="utf-8")
    p = subprocess.run([node, str(HARNESS), str(STATIC / "index.html"), str(STATIC / "app.js"), str(sc)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["steps"][0]


def text(n: Any) -> str:
    return n if isinstance(n, str) else "".join(text(c) for c in n["c"])


def walk(n: Any) -> Any:
    if isinstance(n, str):
        return
    yield n
    for c in n["c"]:
        yield from walk(c)


def by_id(step: dict[str, Any], i: str) -> str:
    return text(next(n for n in walk(step["page"]) if n["a"].get("id") == i))


@pytest.fixture(scope="module")
def step(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return render(tmp_path_factory.mktemp("page"))


def test_a_lane_with_empty_repo_belongs_to_the_host_view_and_shows_the_number_only(step: dict[str, Any]) -> None:
    live = text(step["live"])
    assert "#7 host lane" in live and "Learning_factory#7" not in live
    assert "(PR #99)" not in live, "a lane never takes another repository's pull request"


def test_decisions_are_the_newest_six_of_the_selected_repository(step: dict[str, Any]) -> None:
    d = by_id(step, "decisions")
    assert "D8" in d and "D3" in d and "D2" not in d
    assert "fa decision" not in d


def test_owner_rows_of_another_repository_are_not_shown(step: dict[str, Any]) -> None:
    assert "fa owner" not in by_id(step, "owner")


def test_counts_and_health_are_the_selected_repositorys(step: dict[str, Any]) -> None:
    assert by_id(step, "counts").startswith("1 open")
    h = by_id(step, "health")
    assert "CI" in h and "Deploy" not in h and "Smoke" not in h


def test_the_bar_has_one_tab_per_repository_with_the_host_selected(step: dict[str, Any]) -> None:
    nav = next(n for n in walk(step["page"]) if n["t"] == "nav")
    tabs = [n for n in walk(nav) if n["t"] == "a"]
    assert [text(t) for t in tabs] == ["Learning_factory 1", "factory 1"]
    assert [t["a"].get("aria-current") for t in tabs] == ["page", None]
    assert [t["a"]["href"] for t in tabs] == ["#/Learning_factory", "#/factory"]
