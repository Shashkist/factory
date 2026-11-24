"""Review round 2 of #22: ASCII lookarounds, typed worker id, event times, clean at a boundary."""

import pytest

from factory_tools import progress

HE = "א"


@pytest.fixture(autouse=True)
def builtin_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)


@pytest.mark.parametrize(
    "text", ["x_smb://fileserver/share", "1sftp://host/x", HE + "smb://fileserver/share"]
)
def test_scheme_after_a_non_ascii_or_digit_char_is_scrubbed(text: str) -> None:
    out = progress.scrub(text)
    assert "fileserver" not in out and "host/x" not in out


def test_token_and_ip_next_to_non_ascii_letters_are_scrubbed() -> None:
    tok = "a1B2" * 8
    assert tok not in progress.scrub(HE + tok + HE)
    assert "10.20.30.40" not in progress.scrub(HE + "10.20.30.40" + HE)
    assert progress.scrub("1.2.3.4.5") == "1.2.3.4.5"


@pytest.mark.parametrize("wid", ["name.surname", "ghp_abc", "ABCDEF01", "abcdefghijklm", "a_b", ""])
def test_worker_id_outside_the_allowlist_is_hashed(wid: str) -> None:
    out = progress._typed_worker_event({"worker": wid})["worker"]
    assert out == progress.short_id(wid) and out != wid


def test_worker_id_short_lowercase_is_kept() -> None:
    assert progress._typed_worker_event({"worker": "early"})["worker"] == "early"


@pytest.mark.parametrize("bad", ["AKIAABCDABCDABCDABCD", "me@corp.example 10.1.2.3", None, 5, ""])
def test_events_with_a_bad_at_are_dropped(bad: object) -> None:
    start = {"kind": "pass-start", "at": "2026-11-24T10:00:00+00:00"}
    out = progress.render([start, {"kind": "pass-end", "at": bad, "result": "ok"}])
    assert out["runner"]["pass_ended"] is None
    assert out["runner"]["state"] == "running"


def test_good_at_is_written_back_normalised() -> None:
    out = progress.render([{"kind": "pass-start", "at": "2026-11-24T10:00:00Z", "pass_no": 1}])
    assert out["runner"]["pass_started"] == "2026-11-24T10:00:00+00:00"


def test_clean_keeps_whole_words_when_cut_follows_a_space() -> None:
    assert progress.clean("aaa bbb ccc", 9) == "aaa bbb…"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("server 10.0.0.5.", "server <ip>."),
        ("host 10.0.0.5. Then", "host <ip>. Then"),
    ],
)
def test_ip_before_a_full_stop_is_scrubbed(text: str, want: str) -> None:
    assert progress.scrub(text) == want


def test_naive_event_times_are_taken_as_utc_and_render_never_raises() -> None:
    start = {"kind": "pass-start", "at": "2026-11-24T10:00:00+00:00", "pass_no": 1}
    end = {"kind": "pass-end", "at": "2026-11-24T10:05:00", "result": "ok"}
    out = progress.render([start, end])
    assert out["runner"]["pass_ended"] == "2026-11-24T10:05:00+00:00"
    naive = {"kind": "pass-start", "at": "2026-11-24T10:00:00", "pass_no": 1}
    worker = {"kind": "worker", "at": "2026-11-24T10:01:00", "worker": "early", "event": "idle"}
    progress.render([naive, worker])


@pytest.mark.parametrize("text", [HE + "://fileserver/share", "1://host/x", "_://host/x"])
def test_non_letter_scheme_does_not_let_the_host_through(text: str) -> None:
    out = progress.scrub(text)
    assert "fileserver" not in out and "host" not in out
