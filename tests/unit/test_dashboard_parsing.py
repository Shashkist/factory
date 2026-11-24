from datetime import UTC, datetime

from factory_tools.dashboard.snapshot import (
    current_claim,
    parse_claim,
    parse_decisions,
    parse_owner_open,
    throughput,
)


def test_parse_claim_ignores_plain_comments_and_bad_json():
    assert parse_claim("hello") is None
    assert parse_claim("<!-- pulsesign-issue-claim\nnot json\n-->") is None
    assert parse_claim('<!-- pulsesign-issue-claim\n{"session": "a"}\n-->') == {"session": "a"}


def test_current_claim_first_live_wins_and_released_is_skipped():
    a = {"body": '<!-- pulsesign-issue-claim\n{"session": "a", "step": "x"}\n-->'}
    b = {"body": '<!-- pulsesign-issue-claim\n{"session": "b", "step": "y"}\n-->'}
    rel = {"body": '<!-- pulsesign-issue-claim\n{"released": "t"}\n-->'}
    claim = current_claim(1, [a, b])
    assert claim is not None and claim["session"] == "a"
    assert current_claim(1, [rel, b])["session"] == "b"  # type: ignore[index]
    assert current_claim(1, [rel]) is None
    assert current_claim(1, []) is None


def test_decisions_and_owner_parsing():
    assert parse_decisions("## D3 · Title here\n## Other") == [
        {"id": "D3", "title": "Title here"}
    ]
    text = "- [x] **O1 · Done.** x\n- [ ] **O2 · Open one.** y"
    assert parse_owner_open(text) == [{"id": "O2", "title": "Open one"}]


def test_throughput_without_closed_issues():
    t = throughput([], datetime(2026, 11, 14, tzinfo=UTC))
    assert t["closed_per_day"] == [0] * 14 and t["median_lead_time_hours"] == 0


def test_throughput_skips_issues_closed_as_not_planned():
    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    base = {"state": "CLOSED", "labels": [], "createdAt": "2026-11-14T00:00:00Z",
            "closedAt": "2026-11-14T10:00:00Z"}
    issues = [{**base, "stateReason": "COMPLETED"}, {**base, "stateReason": "NOT_PLANNED"}, base]
    assert throughput(issues, now)["closed_per_day"][-1] == 2
