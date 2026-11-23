"""A fake `gh` for the incident exam. Keeps issues and comments in a JSON file.

Run as: python fake_gh.py <gh args>, with FAKE_GH_STATE pointing at the state file.

It deliberately ignores --jq and returns the full JSON list: the module under
test must filter in Python and must not depend on gh's --jq.
"""

import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]


def load() -> dict:
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(s: dict) -> None:
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def opt(name: str, multi: bool = False):
    vals = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == name and i + 1 < len(args):
            vals.append(args[i + 1])
            i += 2
            continue
        if a.startswith(name + "="):
            vals.append(a.split("=", 1)[1])
        i += 1
    if multi:
        return vals
    return vals[-1] if vals else None


def body() -> str:
    b = opt("--body")
    if b is None and opt("--body-file"):
        f = opt("--body-file")
        b = sys.stdin.read() if f == "-" else open(f, encoding="utf-8").read()
    return b or ""


for flag in ("-R", "--repo"):
    while flag in args:
        i = args.index(flag)
        del args[i : i + 2]

s = load()
s["calls"].append(args)
if args[:2] == ["issue", "list"]:
    want = (opt("--state") or "open").lower()
    out = []
    for it in s["issues"]:
        if want != "all" and it["state"].lower() != want:
            continue
        out.append(
            {
                "number": it["number"],
                "title": it["title"],
                "state": it["state"].upper(),
                "body": it["body"],
                "labels": [{"name": n} for n in it["labels"]],
            }
        )
    save(s)
    print(json.dumps(out))
elif args[:2] == ["issue", "create"]:
    labels: list[str] = []
    for v in opt("--label", True) + opt("--labels", True):
        labels += [x for x in v.split(",") if x]
    n = len(s["issues"]) + 1
    s["issues"].append(
        {
            "number": n,
            "title": opt("--title") or "",
            "state": "open",
            "body": body(),
            "labels": labels,
            "comments": [],
        }
    )
    save(s)
    print(f"https://example.invalid/issues/{n}")
elif args[:2] == ["issue", "comment"]:
    n = int(args[2].lstrip("#"))
    for it in s["issues"]:
        if it["number"] == n:
            it["comments"].append(body())
    save(s)
else:
    save(s)
    sys.stderr.write("fake gh: unsupported " + " ".join(args) + "\n")
    sys.exit(2)
