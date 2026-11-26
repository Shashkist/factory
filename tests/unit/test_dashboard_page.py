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


def render(tmp_path: Path, runner: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    node = shutil.which("node")
    assert node
    live = {"generated_at": "2026-11-24T11:59:30+00:00", "schema": 1, "runner": runner or {"state": "running"},
            "issues": [{"issue": 7, "repo": "", "title": "host lane", "station": "build"}],
            "agents": [], "workers": [], "crew": [], "log": []}
    live.update(extra)
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


def test_an_idle_runner_without_a_pass_end_still_shows_the_lanes_as_last_pass(tmp_path: Path) -> None:
    live = text(render(tmp_path, {"state": "idle"})["live"])
    assert "Last pass:" in live and "#7 host lane" in live
    assert "working" not in live.lower()


ENDED = {"state": "idle", "pass_ended": "2026-11-24T09:25:00+00:00", "result": "shipped 1, paused 2"}
BUSY_CREW = [{"id": "c0", "kind": "session", "type": "manager", "title": "manager pass", "state": "busy", "model": "m",
              "started": "2026-11-24T08:55:00+00:00", "last": "2026-11-24T09:24:00+00:00", "tool": "Bash", "label": "x",
              "children": [{"id": "c1", "kind": "subagent", "type": "reviewer", "title": "review #7", "state": "busy",
                            "model": "m", "started": "2026-11-24T09:00:00+00:00", "last": "2026-11-24T09:24:00+00:00",
                            "tool": "Read", "label": "", "children": []}]}]


def classes(n: Any) -> set[str]:
    return set(str(n["a"].get("class", "")).split())


def nodes(step: dict[str, Any], cls: str) -> list[Any]:
    return [n for n in walk(step["live"]) if cls in classes(n)]


@pytest.mark.parametrize("runner", [
    {"state": "budget", "pass_ended": "2026-11-24T09:25:00+00:00", "result": "ok"},
    {"state": "paused", "pass_ended": "2026-11-24T09:25:00+00:00", "result": "ok"}])
def test_a_budget_or_paused_runner_after_a_pass_end_is_still_between_passes(tmp_path: Path, runner: dict[str, Any]) -> None:
    step = render(tmp_path, runner, crew=BUSY_CREW)
    mgr = text(nodes(step, "lane-manager")[0]).lower()
    assert "working" not in mgr and "now:" not in mgr and "last pass: ok" in mgr
    assert nodes(step, "lane") and all(n["a"]["data-running"] == "0" for n in nodes(step, "lane"))


def test_an_ended_pass_lane_ignores_the_crew_of_that_pass(tmp_path: Path) -> None:
    crew = [{**BUSY_CREW[0], "children": [{**BUSY_CREW[0]["children"][0], "title": "review #7"}]}]
    step = render(tmp_path, ENDED, crew=crew)
    lane = nodes(step, "lane")[0]
    body = text(lane)
    assert "reviewer" not in body and "working" not in body.lower() and "now:" not in body
    assert not [b for b in walk(lane) if b["t"] == "button" and b["a"].get("data-mark") == "active"]


def test_an_idle_runner_without_a_pass_end_ignores_busy_crew_too(tmp_path: Path) -> None:
    step = render(tmp_path, {"state": "idle"}, crew=BUSY_CREW)
    assert "working" not in text(nodes(step, "lanes")[0]).lower() and "0 working" in text(step["live"])


def test_titles_are_inside_the_lane_nodes_in_the_last_pass_fold(tmp_path: Path) -> None:
    step = render(tmp_path, ENDED)
    fold = nodes(step, "fold")[0]
    assert "Last pass" in text(fold)
    lanes = [n for n in walk(fold) if "lane" in classes(n)]
    assert lanes and "#7 host lane" in text(lanes[0])


def test_a_lane_with_a_failed_station_is_failed_not_paused(tmp_path: Path) -> None:
    agent = {"id": "a1", "role": "implementer", "state": "ended", "station": "build", "last": "2026-11-24T09:20:00+00:00",
             "substeps": [{"issue": 7, "repo": "", "title": "host lane", "station": "build", "substep": "x", "status": "fail",
                           "at": "2026-11-24T09:20:00+00:00", "started": "2026-11-24T09:19:00+00:00", "detail": ""}]}
    step = render(tmp_path, ENDED, agents=[agent])
    head = text(nodes(step, "lane-head")[0])
    assert "failed" in head and "paused" not in head
    assert "1 failed" in text(nodes(step, "fold")[0]) and "0 paused" in text(nodes(step, "fold")[0])


def test_the_crew_of_an_ended_pass_is_not_counted_as_working(tmp_path: Path) -> None:
    step = render(tmp_path, ENDED, crew=BUSY_CREW)
    live = text(step["live"])
    assert "0 working" in live and "1 working" not in live and "2 working" not in live
    assert "now:" not in live.lower()


def test_a_live_pass_keeps_its_crew_working(tmp_path: Path) -> None:
    step = render(tmp_path, {"state": "running", "pass_started": "2026-11-24T08:55:00+00:00"}, crew=BUSY_CREW)
    assert "2 working" in text(step["live"])
