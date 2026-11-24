"""Review round 1 of #22: cut before scrub, any scheme, typed event fields, more forms."""

import json
from pathlib import Path

import pytest

from factory_tools import progress

BS = chr(92)
KEY = "AKIA" + "ABCD" * 4
LISTED = "https://github.com/Shashkist/factory/pull/3"


@pytest.fixture(autouse=True)
def builtin_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)


@pytest.mark.parametrize(
    ("secret", "heads", "limit"),
    [
        (KEY, ["AKIAABCD"], 120),
        ("ghp_" + "a1B2" * 7, ["ghp_a1B2"], 120),
        ("10.20.30.40", ["10.20.30"], 120),
        ("name@corp.example", ["name@corp"], 120),
        (KEY, ["AKIAABCD"], 40),
        ("10.20.30.40", ["10.20.30"], 40),
        ("name@corp.example", ["name@corp"], 40),
    ],
)
def test_clean_never_leaves_a_head_of_a_secret(secret: str, heads: list[str], limit: int) -> None:
    for pad in range(limit - len(secret) - 6, limit + 1):
        text = "x " * (pad // 2) + secret + " tail words"
        out = progress.scrub(progress.clean(text, limit))
        for head in heads:
            assert head not in out, (limit, pad, out)


def test_clean_cuts_at_a_word_boundary_with_an_ellipsis() -> None:
    assert progress.clean("aaa bbb ccc ddd", 10) == "aaa bbb…"
    assert progress.clean("aaa bbb ccc", 8) == "aaa bbb…"
    assert progress.clean("xyz" * 5, 10) == "…"
    assert progress.clean("short", 10) == "short"


@pytest.mark.parametrize(
    "scheme",
    ["sftp://zzhost/x", "ftps://zzhost/x", "smb://zzhost/share", "file:///zzpriv/x"]
    + ["s3://zzbucket/k", "s" + "sh://user@zzhost", "redis://:zzpw@zzhost", "gopher://zzhost"],
)
def test_any_scheme_url_is_removed(scheme: str) -> None:
    out = progress.scrub(f"{LISTED} {scheme} {LISTED}")
    assert "zz" not in out and out.count(LISTED) == 2


def test_own_https_link_is_kept() -> None:
    assert progress.scrub("see https://live.shashkist.com/x") == "see https://live.shashkist.com/x"


@pytest.mark.parametrize("key", ["ASIA" + "ABCD" * 4, KEY + "é", "é" + KEY, "(" + KEY + ")"])
def test_access_key_forms(key: str) -> None:
    assert "ABCDABCD" not in progress.scrub(f"k {key} k")


@pytest.mark.parametrize(
    "dots",
    ["%25252e", "%25%32%65", "&#x2e;", "&#X2E;", "&#046;", "&#0046;", "%c0%ae", "%C0%AE"],
)
def test_more_dot_encodings_after_a_listed_link(dots: str) -> None:
    assert "qqq" not in progress.scrub(f"github.com/Shashkist/factory/{dots}{dots}/qqq")


@pytest.mark.parametrize("stop", ["。", "．", "｡"])
def test_ideographic_stop_after_a_listed_link_keeps_the_link(stop: str) -> None:
    assert progress.scrub(f"see {LISTED}{stop}") == f"see {LISTED}{stop}"


@pytest.mark.parametrize(
    "unc", [BS + "/zzhost/share", "/" + BS + "zzhost" + BS + "share", BS * 2 + "zzhost" + BS + "s"]
)
def test_mixed_slash_unc_is_removed(unc: str) -> None:
    assert "zzhost" not in progress.scrub(f"see {unc} ok")


def test_hand_written_events_are_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "p.jsonl"
    monkeypatch.setenv("LF_PROGRESS_FILE", str(f))
    monkeypatch.delenv("LF_CREW_DIR", raising=False)
    t = "2999-01-01T00:00:00+00:00"
    step = {"kind": "step", "at": t, "repo": "", "agent": "a", "role": "implementer"}
    step |= {"station": "build", "substep": "s", "detail": ""}
    evs = [
        {"kind": "pass-start", "at": t, "pass_no": "zzhost", "budget": [1]},
        {**step, "issue": "zzhost", "status": "start"},
        {**step, "issue": 2, "substep": "s2", "status": "zzstatus"},
        {
            "kind": "worker",
            "at": t,
            "worker": "zz worker",
            "role": "zzrole",
            "event": "tool-start",
            "tool": "zztool",
            "call": "c",
        },
    ]
    f.write_text("\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")
    out = progress.render(progress.read_events())
    assert "zz" not in json.dumps(out)
    assert out["runner"]["pass_no"] is None and out["runner"]["budget"] is None
