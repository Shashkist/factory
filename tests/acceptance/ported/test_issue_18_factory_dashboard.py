# Ported from LF at 29e3bf3 (labs/factory-dashboard/tests/acceptance), factory#42.
# The nine static-page cases, plus three snapshot cases (in-progress claim over in-review, in-review fallback,
# open incident count). Adapted: the package builder is `python -m factory_tools.dashboard build --repos --fixtures`
# with fixtures under <fixtures>/<owner>__<name>/ (fixtures/issue18 holds LF's files, STATE.md left out).
# Other snapshot cases and the workflow cases are not ported.
"""Issue #18 page cases (file level, no browser) and snapshot claim and incident cases."""
# ruff: noqa: E501
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "issue18"
NOW = "2026-11-14T12:00:00Z"
REPO_NAME = "Shashkist/factory"
COMPONENT = Path(__file__).resolve().parents[3] / "src" / "factory_tools" / "dashboard" / "static"


def _shipped_files() -> list[Path]:
    skip = {"tests", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    out = []
    for p in COMPONENT.rglob("*"):
        rel = p.relative_to(COMPONENT)
        if not p.is_file() or rel.parts[0] in skip:
            continue
        if (p.name == "index.html" and len(rel.parts) == 1) or p.suffix in {".css", ".js"}:
            out.append(p)
    return out


def _page() -> str:
    return (COMPONENT / "index.html").read_text(encoding="utf-8")


def _shipped_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _shipped_files())


def test_index_html_exists():
    assert (COMPONENT / "index.html").is_file()


def test_page_ships_under_150_kb():
    assert (COMPONENT / "index.html").is_file()
    total = sum(p.stat().st_size for p in _shipped_files())
    assert total < 150 * 1024, f"{total} bytes"


def test_page_reads_snapshot_json():
    assert "snapshot.json" in _shipped_text()


def test_page_refetches_snapshot_periodically():
    text = _shipped_text()
    assert "setInterval" in text
    assert "snapshot.json" in text


def test_page_names_the_five_stations_in_order():
    page = _page()
    positions = [page.find(name) for name in ["Plan", "Exam", "Build", "Check", "Ship"]]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)


def test_page_uses_data_theme_and_has_a_theme_toggle():
    assert "data-theme" in _shipped_text()
    assert re.search(r"<button[^>]*theme", _page(), re.I), (
        "no <button> with 'theme' in its attributes"
    )


def test_page_references_poppins():
    assert "poppins" in _shipped_text().lower()


def test_page_has_viewport_meta():
    assert re.search(r'<meta[^>]+name=["\']viewport["\']', _page(), re.I)


def test_page_is_noindex():
    page = _page()
    assert re.search(r'<meta[^>]+name=["\']robots["\'][^>]*content=["\']noindex', page, re.I) \
        or re.search(r'<meta[^>]+content=["\']noindex[^>]*name=["\']robots["\']', page, re.I)


# ---- snapshot.json (the package builder) -----------------------------------

def run_snapshot(tmp_path: Path, fixtures: Path = FIXTURES) -> dict:
    fx = tmp_path / "fx"
    shutil.copytree(fixtures, fx / REPO_NAME.replace("/", "__"))
    repos = tmp_path / "repos.yaml"
    repos.write_text(f"- repo: {REPO_NAME}\n", encoding="utf-8")
    out = tmp_path / "site"
    env = {"PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8", "PATH": ""}
    for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "HOME"):
        if k in os.environ:
            env[k] = os.environ[k]
    proc = subprocess.run(
        [sys.executable, "-m", "factory_tools.dashboard", "build", "--repos", str(repos), "--out", str(out),
         "--fixtures", str(fx), "--now", NOW],
        capture_output=True, text=True, encoding="utf-8", cwd=tmp_path, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads((out / "snapshot.json").read_text(encoding="utf-8"))


def _fx(tmp_path: Path) -> Path:
    fx = tmp_path / "src_fx"
    shutil.copytree(FIXTURES, fx)
    return fx


def test_in_progress_claim_wins_over_in_review_claim(tmp_path):
    fx = _fx(tmp_path)
    shutil.copy(fx / "comments-16-live.json", fx / "comments-16.json")
    claim = run_snapshot(tmp_path, fixtures=fx)["claim"]
    assert claim["issue"] == 18
    assert claim["session"] == "lf-k7m2"


def test_claim_falls_back_to_in_review_issue_when_none_is_in_progress(tmp_path):
    fx = _fx(tmp_path)
    issues = json.loads((fx / "issues.json").read_text(encoding="utf-8"))
    for issue in issues:
        if issue["number"] == 18:  # no issue is status:in-progress any more
            issue["labels"] = [
                {"name": "status:ready"} if lb["name"] == "status:in-progress" else lb
                for lb in issue["labels"]
            ]
    (fx / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
    shutil.copy(fx / "comments-16-live.json", fx / "comments-16.json")
    claim = run_snapshot(tmp_path, fixtures=fx)["claim"]
    assert claim["issue"] == 16
    assert claim["session"] == "lf-r9x1"
    assert claim["step"] == "waiting for review"
    assert claim["branch"] == "f/16-in-review-one"
    assert claim["heartbeat"] == "2026-11-14T11:45:00+00:00"


def test_throughput_open_incident_count(tmp_path):
    assert run_snapshot(tmp_path)["throughput"]["open_incidents"] == 1
