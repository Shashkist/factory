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
COUNTS = {"open": 1, "closed": 0, "by_status": {}, "by_phase": {}, "by_priority": {}}


def snapshot() -> dict[str, Any]:
    return {
        "generated_at": "2026-11-24T11:59:00+00:00",
        "issues": COUNTS,
        "repos": {LF: {"issues": COUNTS}, FA: {"issues": COUNTS}},
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


def test_a_lane_with_empty_repo_is_tagged_with_the_host_repository(step: dict[str, Any]) -> None:
    live = text(step["live"])
    assert "Learning_factory#7 host lane" in live
    assert "(PR #99)" not in live, "a lane never takes another repository's pull request"


def test_decisions_are_the_newest_six_per_repository_with_a_repository_tag(step: dict[str, Any]) -> None:
    d = by_id(step, "decisions")
    assert "Learning_factory D8" in d and "Learning_factory D3" in d and "Learning_factory D2" not in d
    assert "factory D2" in d and "factory D1" in d


def test_owner_rows_carry_the_repository(step: dict[str, Any]) -> None:
    assert "factory O3" in by_id(step, "owner")


def test_counts_per_repository_and_only_present_workflows(step: dict[str, Any]) -> None:
    c = by_id(step, "repo-counts")
    assert "Learning_factory: 1 open" in c and "factory: 1 open" in c
    h = by_id(step, "health")
    assert "Learning_factory CI" in h and "Deploy" not in h and "Smoke" not in h
