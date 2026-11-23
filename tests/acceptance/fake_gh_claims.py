"""A fake `gh` for the claims exam: several repositories, issues with comments and labels.

Run as: python fake_gh_claims.py <gh args>, with FAKE_GH_STATE pointing at a JSON state file:

    {"default": "owner/name", "next_id": 1000, "calls": [],
     "repos": {"owner/name": {"issues": {"5": {"title": "...", "labels": [], "comments": []}}}}}

A bare call (no -R/--repo) reaches the origin of the git checkout it runs in (so `gh repo view`
agrees with `git remote get-url origin`); outside a checkout it reaches `default` and
`gh repo view` fails. Repository names match case-insensitively, like GitHub. It deliberately
ignores --jq and returns the full JSON, so the module under test must filter in Python.
Every call is recorded in `calls`; a call to `gh auth ...` is recorded and refused.
"""

import json
import os
import re
import sys
from datetime import UTC, datetime

STATE = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]


def load() -> dict:
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(s: dict) -> None:
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def values(name: str, short: str | None = None) -> list[str]:
    out = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in (name, short) and i + 1 < len(args):
            out.append(args[i + 1])
            i += 2
            continue
        if a.startswith(name + "="):
            out.append(a.split("=", 1)[1])
        i += 1
    return out


def fail(msg: str, code: int = 1) -> None:
    sys.stderr.write("fake gh: " + msg + "\n")
    sys.exit(code)


s = load()
s["calls"].append(args)
save(s)

if args[:1] == ["auth"]:
    fail("gh auth is not available here", 4)

def checkout_repo() -> str | None:
    """The repository gh itself would target here: the origin of a git checkout, if any."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=30
        )
    except OSError:
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", out.stdout.strip())
    return m.group(1) if out.returncode == 0 and m else None


scope = values("--repo", "-R")
here = checkout_repo()
repo = scope[-1] if scope else (here or s["default"])


def repo_state(name: str) -> dict:
    for known, state in s["repos"].items():
        if known.lower() == name.lower():
            return state
    fail("Could not resolve to a Repository with the name '" + name + "'")
    raise AssertionError


def labels_of(issue: dict) -> list[dict]:
    return [{"name": n} for n in issue["labels"]]


if args[:2] == ["repo", "view"]:
    if not scope and here is None:
        fail("not a git repository (or no origin): no repository to view")
    print(json.dumps({"nameWithOwner": repo}))
elif args[:2] == ["issue", "view"]:
    issue = repo_state(repo)["issues"].get(args[2])
    if issue is None:
        fail("issue not found")
    print(json.dumps({"comments": issue["comments"], "labels": labels_of(issue)}))
elif args[:2] == ["issue", "list"]:
    wanted = values("--label")
    out = []
    for n, it in repo_state(repo)["issues"].items():
        if wanted and not all(w in it["labels"] for w in wanted):
            continue
        out.append(
            {
                "number": int(n),
                "title": it["title"],
                "updatedAt": it.get("updatedAt", now()),
                "labels": labels_of(it),
            }
        )
    print(json.dumps(out))
elif args[:2] == ["issue", "comment"]:
    issue = repo_state(repo)["issues"][args[2].lstrip("#")]
    body = (values("--body") or [""])[-1]
    if values("--body-file"):
        f = values("--body-file")[-1]
        body = sys.stdin.read() if f == "-" else open(f, encoding="utf-8").read()
    cid = s["next_id"]
    s["next_id"] += 1
    num = args[2].lstrip("#")
    url = "https://github.com/" + repo + "/issues/" + num + "#issuecomment-" + str(cid)
    issue["comments"].append({"id": cid, "body": body, "url": url})
    issue["updatedAt"] = now()
    save(s)
elif args[:2] == ["issue", "edit"]:
    issue = repo_state(repo)["issues"][args[2].lstrip("#")]
    for v in values("--add-label"):
        for name in v.split(","):
            if name and name not in issue["labels"]:
                issue["labels"].append(name)
    for v in values("--remove-label"):
        issue["labels"] = [x for x in issue["labels"] if x not in v.split(",")]
    issue["updatedAt"] = now()
    save(s)
elif args[:1] == ["api"]:
    path = next((a for a in args[1:] if a.startswith("repos/")), "")
    m = re.fullmatch(r"repos/([^/]+/[^/]+|\{owner\}/\{repo\})/issues/comments/(\d+)", path)
    if not m or "PATCH" not in args:
        fail("unsupported api call: " + " ".join(args), 2)
    target = s["default"] if m.group(1) == "{owner}/{repo}" else m.group(1)
    fields = [a.split("=", 1)[1] for a in args if a.startswith("body=")]
    for flag in ("-f", "-F", "--raw-field", "--field"):
        fields += [v.split("=", 1)[1] for v in values(flag) if v.startswith("body=")]
    if not fields:
        fail("PATCH without a body", 2)
    done = False
    for issue in repo_state(target)["issues"].values():
        for c in issue["comments"]:
            if c["id"] == int(m.group(2)):
                c["body"] = fields[-1]
                issue["updatedAt"] = now()
                done = True
    if not done:
        fail("comment not found")
    save(s)
    print("{}")
else:
    fail("unsupported " + " ".join(args), 2)
