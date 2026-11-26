"""#117: `python -m factory_tools progress hook` skips the CLI; other commands do not."""

import pytest

from factory_tools import __main__ as entry_mod
from factory_tools import cli, progress


def test_progress_hook_goes_straight_to_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(progress, "run", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(cli, "main", lambda: pytest.fail("the CLI must not run for the hook"))
    assert entry_mod.entry(["progress", "hook"]) == 0
    assert calls == [["hook"]]


@pytest.mark.parametrize("argv", [["progress", "add"], ["--help"], ["progress"], []])
def test_everything_else_goes_through_the_cli(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr(progress, "run", lambda a: pytest.fail("not the hook"))
    monkeypatch.setattr(cli, "main", lambda: 7)
    assert entry_mod.entry(argv) == 7
