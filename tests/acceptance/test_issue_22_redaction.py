"""Issue #22: the live page is public, so every free-text field `render` writes goes through scrub.

Review of #19 (#13), D8, spec section 5.1. Checked through the command line and the live.json the
`render` command writes. All values are synthetic: fake hosts, fake paths, a fake key id.

The project's repository list is supplied the way test_issue_13_progress.py does it: a YAML list in
the format of docs/factory/repos.yaml, whose path comes from $LF_REPOS_FILE. The exam uses the short
names a/b and e/f so that even the 40-character pass result can carry a link to a listed repository.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers import env

LISTED = "https://github.com/a/b/pull/3"
REPOS_YAML = "- repo: a/b\n  default: true\n- repo: e/f\n  default: false\n"

# The fields that carry free text from a person or an agent. `note` is the runner note, `result` the
# result of a pass; both reach live.json without going through scrub on main.
FIELDS = ["detail", "log detail", "title", "runner note", "pass result"]
FIELDS_WITH_ROOM = ["detail", "log detail", "title", "runner note"]  # pass result is capped at 40

BACKSLASH = chr(92)
FAKE_KEY = "AKIA" + "FAKE" * 4  # 20 characters, obviously not a real access key id
assert len(FAKE_KEY) == 20


class Box:
    """An events file, a repository list and a scratch dir, passed to every child process."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.events = base / "progress.jsonl"
        repos = base / "repos.yaml"
        repos.write_text(REPOS_YAML, encoding="utf-8")
        self.repos = repos

    def cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        e = env({"LF_PROGRESS_FILE": str(self.events), "LF_REPOS_FILE": str(self.repos)})
        e.pop("LF_CREW_DIR", None)
        return subprocess.run(
            [sys.executable, "-m", "factory_tools", "progress", *args],
            cwd=self.base,
            env=e,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def render(self) -> dict[str, Any]:
        out = self.base / "live.json"
        r = self.cli("render", "--out", str(out))
        assert r.returncode == 0, r.stderr
        assert out.exists(), "render wrote no file"
        data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
        return data

    def put(self, field: str, text: str) -> None:
        """Record `text` in the field, through the command that fills it."""
        assert self.cli("pass-start", "--pass-no", "1").returncode == 0
        if field in ("detail", "log detail", "title"):
            a = ["add", "--issue", "3", "--agent", "impl-3", "--role", "implementer"]
            a += ["--station", "build", "--substep", "unit tests", "--status", "start"]
            if field == "title":
                a += ["--title", text]
                r = self.cli(*a)
            else:
                r = self.cli(*a, "--detail-file", "-", stdin=text)
        elif field == "runner note":
            r = self.cli("runner-state", "--state", "paused", f"--note={text}")
        elif field == "pass result":
            r = self.cli("pass-end", f"--result={text}")
        else:
            raise AssertionError(field)
        assert r.returncode == 0, r.stderr

    def get(self, field: str) -> str:
        """What the page shows in the field."""
        live = self.render()
        if field == "detail":
            return str(live["agents"][0]["substeps"][0]["detail"])
        if field == "log detail":
            return str(live["log"][0]["detail"])
        if field == "title":
            return str(live["issues"][0]["title"])
        if field == "runner note":
            return str(live["runner"]["note"])
        if field == "pass result":
            return str(live["runner"]["result"])
        raise AssertionError(field)


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def shown(box: Box, field: str, text: str) -> str:
    box.put(field, text)
    return box.get(field)


# ---- 2. each form is removed, in every free-text field -----------------------------------------
# (form, what must not appear in the output)

FORMS = {
    "ftp-url": ("ftp://zzhost.example/x", ["zzhost", "ftp://"]),
    "scheme-relative": ("//zzhost.example/x", ["zzhost"]),
    "unc-path": (BACKSLASH * 2 + "zzhost" + BACKSLASH + "share", ["zzhost", "share"]),
    "opt-path": ("/opt/zzprivate/app.cfg", ["zzprivate"]),
    "srv-path": ("/srv/zzdata/x", ["zzdata"]),
    "access-key-id": (FAKE_KEY, [FAKE_KEY, "FAKEFAKE"]),
    "double-encoded-dots": ("github.com/a/b/%252e%252e/qqq", ["qqq", "%252e"]),
    "double-encoded-dots-https": ("https://github.com/a/b/%252e%252e/qqq", ["qqq", "%252e"]),
    "double-encoded-dots-upper": ("github.com/a/b/%252E%252E/qqq", ["qqq", "%252E"]),
    "fullwidth-dots": ("github.com/a/b/．．/qqq", ["qqq", "．"]),
    "fullwidth-dots-https": ("https://github.com/a/b/．．/qqq", ["qqq", "．"]),
    "html-entity-dots": ("github.com/a/b/&#46;&#46;/qqq", ["qqq", "&#46;"]),
    "html-entity-dots-https": ("https://github.com/a/b/&#46;&#46;/qqq", ["qqq", "&#46;"]),
}


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_form_is_removed_from_the_rendered_output(box: Box, form: str, field: str) -> None:
    text, banned = FORMS[form]
    out = shown(box, field, f"saw {text} here")
    for piece in banned:
        assert piece not in out, f"{form} survives in {field}: {out!r}"
    blob = json.dumps(box.render(), ensure_ascii=False)
    for piece in banned:
        assert piece not in blob, f"{form} survives somewhere in live.json"


# ---- 1. the runner note and the pass result go through scrub (the existing forms too) ----------

OLD_FORMS = {
    "foreign-url": ("https://evil.example/a", ["evil.example"]),
    "email": ("me@x.example", ["me@x.example"]),
    "ip": ("10.1.2.3", ["10.1.2.3"]),
    "home-path": ("/home/zzuser/.env", ["zzuser"]),
    "windows-path": ("C:" + BACKSLASH + "Users" + BACKSLASH + "zzuser", ["zzuser"]),
}


@pytest.mark.parametrize("field", ["runner note", "pass result"])
@pytest.mark.parametrize("form", sorted(OLD_FORMS))
def test_runner_note_and_pass_result_are_scrubbed_like_the_other_fields(
    box: Box, form: str, field: str
) -> None:
    text, banned = OLD_FORMS[form]
    out = shown(box, field, f"saw {text}")
    for piece in banned:
        assert piece not in out, f"{form} survives in {field}: {out!r}"


def test_every_free_text_field_of_a_hand_written_event_is_scrubbed(box: Box) -> None:
    """The events file can hold anything (hand edits, older versions): render scrubs every
    free-text field it copies, not only the ones the add command already limits."""
    leak = "ftp://zzhost.example/x"
    t = "2999-01-01T00:00:00+00:00"
    events = [
        {"kind": "pass-start", "at": t, "pass_no": 1, "budget": 5},
        {
            "kind": "step",
            "at": t,
            "issue": 3,
            "repo": "",
            "agent": f"impl {leak}",
            "role": "implementer",
            "station": "build",
            "substep": f"tests {leak}",
            "status": "start",
            "detail": f"d {leak}",
            "title": f"t {leak}",
        },
        {"kind": "runner-state", "at": t, "state": "paused", "note": f"n {leak}"},
        {"kind": "pass-end", "at": t, "result": f"r {leak}"},
    ]
    box.events.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    blob = json.dumps(box.render())
    assert "zzhost" not in blob and "ftp://" not in blob


def test_hand_written_event_with_a_free_text_role_station_or_state_is_scrubbed(box: Box) -> None:
    leak = "//zzhost.example/x"
    t = "2999-01-01T00:00:00+00:00"
    events = [
        {"kind": "pass-start", "at": t, "pass_no": 1, "budget": 5},
        {
            "kind": "step",
            "at": t,
            "issue": 3,
            "repo": "",
            "agent": "impl-3",
            "role": f"role {leak}",
            "station": f"station {leak}",
            "substep": "x",
            "status": "start",
            "detail": "",
            "title": "",
        },
        {"kind": "runner-state", "at": t, "state": f"state {leak}", "note": ""},
    ]
    box.events.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert "zzhost" not in json.dumps(box.render())


# ---- 2. links to listed repositories are still kept ---------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
def test_link_to_a_listed_repository_is_kept(box: Box, field: str) -> None:
    out = shown(box, field, f"see {LISTED}")
    assert out == f"see {LISTED}", f"over-redacted in {field}: {out!r}"


@pytest.mark.parametrize("field", FIELDS)
def test_link_to_the_second_listed_repository_is_kept(box: Box, field: str) -> None:
    url = "https://github.com/e/f/issues/7"
    out = shown(box, field, f"see {url}")
    assert out == f"see {url}", f"over-redacted in {field}: {out!r}"


@pytest.mark.parametrize("field", FIELDS_WITH_ROOM)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_listed_link_next_to_a_removed_form_is_kept(box: Box, form: str, field: str) -> None:
    text, banned = FORMS[form]
    out = shown(box, field, f"{LISTED} and {text} and {LISTED}")
    assert out.count(LISTED) == 2, f"listed link lost in {field}: {out!r}"
    for piece in banned:
        assert piece not in out, f"{form} survives in {field}: {out!r}"


@pytest.mark.parametrize("field", FIELDS)
def test_a_dotted_path_inside_a_listed_link_is_not_mistaken_for_dot_segments(
    box: Box, field: str
) -> None:
    # not a traversal: a file name with dots after the listed repository stays readable
    url = "https://github.com/a/b/x/a.b.md"
    out = shown(box, field, f"see {url}")
    assert out == f"see {url}", f"over-redacted in {field}: {out!r}"


@pytest.mark.parametrize("field", FIELDS)
def test_plain_text_without_any_listed_form_is_untouched(box: Box, field: str) -> None:
    out = shown(box, field, "tests ok")
    assert out == "tests ok", f"{field}: {out!r}"
