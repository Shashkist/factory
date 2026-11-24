"""Redaction forms of `progress.scrub` (#22): URLs, paths, keys and encoded dots."""

import pytest

from factory_tools import progress

BS = chr(92)
KEY = "AKIA" + "ABCD" * 4
LISTED = "https://github.com/Shashkist/factory/pull/3"


@pytest.fixture(autouse=True)
def builtin_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LF_REPOS_FILE", raising=False)


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("ftp://zzhost/x", "zzhost"),
        ("FTP://zzhost/x", "zzhost"),
        ("//zzhost/x", "zzhost"),
        (BS * 2 + "zzhost" + BS + "share", "share"),
        ("/opt/zzapp/a.cfg", "zzapp"),
        ("/srv/zzdata/x", "zzdata"),
        (KEY, "ABCDABCD"),
        ("github.com/Shashkist/factory/%252e%252e/qqq", "qqq"),
        ("github.com/Shashkist/factory/%252E%252E/qqq", "qqq"),
        ("github.com/Shashkist/factory/．．/qqq", "qqq"),
        ("https://github.com/Shashkist/factory/&#46;&#46;/qqq", "qqq"),
    ],
)
def test_form_is_removed(text: str, gone: str) -> None:
    assert gone not in progress.scrub(f"see {text} ok")


@pytest.mark.parametrize(
    "text",
    [
        LISTED,
        "https://github.com/Shashkist/factory/blob/main/a.b.md",
        "tests ok, 3//4 and a//b",
        "AKIA is a prefix, AKIAshort",
    ],
)
def test_harmless_text_is_kept(text: str) -> None:
    assert progress.scrub(text) == text


def test_listed_link_survives_next_to_a_removed_form() -> None:
    out = progress.scrub(f"{LISTED} ftp://zzhost/x {LISTED}")
    assert out.count(LISTED) == 2 and "zzhost" not in out
