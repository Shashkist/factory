"""A fake `gh` for the merge gate exam: pull requests, commit files and issue comments.

Run as: python fake_gh_merge_gate.py <gh args>, with FAKE_GH_STATE pointing at a JSON state file:

    {"default": "owner/name", "calls": [], "writes": [],
     "repos": {"owner/name": {
         "prs": {"9": {<pull request fields>}},
         "commits": {"<oid>": ["path", ...]},
         "issues": {"5": [<comment objects>]}}}}

* `pr view <n> ... --json <fields>` returns ONE object with every stored field, whatever
  fields were asked for (the gate must not depend on --jq or on the field list).
* `api repos/<owner>/<repo>/commits/<oid>` returns {"files": [{"filename": ...}]}; the
  `{owner}/{repo}` placeholder resolves to the -R repository (gh does this itself).
* `issue view <n> --json comments` returns {"comments": [...]} (empty for an unknown issue).
* Anything that writes (pr merge, comment, review, edit, close, api -X ...) is recorded in
  `writes` and refused: the gate is read-only.
Every call is recorded in `calls`.
"""

import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
WRITES = {"merge", "comment", "review", "edit", "close", "reopen", "ready", "create"}

with open(STATE, encoding="utf-8") as f:
    s = json.load(f)
s["calls"].append(args)


def save() -> None:
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def fail(msg: str, code: int = 1) -> None:
    save()
    sys.stderr.write("fake gh: " + msg + "\n")
    sys.exit(code)


scope = None
for flag in ("-R", "--repo"):
    if flag in args:
        scope = args[args.index(flag) + 1]
repo = scope or s["default"]
known = {k.lower(): v for k, v in s["repos"].items()}
state = known.get(repo.lower())
if state is None:
    fail("Could not resolve to a Repository with the name '" + repo + "'")

group = args[0] if args else ""
second = args[1] if len(args) > 1 else ""
if (
    group in WRITES
    or second in WRITES
    or "-X" in args
    or "--method" in args
    or "-f" in args
    or "-F" in args
    or "--field" in args
    or group == "auth"
):
    s["writes"].append(args)
    fail("the merge gate is read-only: refused " + " ".join(args), 3)

if args[:2] == ["pr", "view"]:
    pr = state["prs"].get(args[2])
    if pr is None:
        fail("no pull request " + args[2])
    save()
    print(json.dumps(pr))
elif group == "api":
    path = next((a for a in args[1:] if a.startswith("repos/")), None)
    if path is None or "/commits/" not in path:
        fail("unsupported api call: " + " ".join(args))
    path = path.replace("{owner}/{repo}", repo)
    if not path.lower().startswith("repos/" + repo.lower() + "/commits/"):
        fail("api path reaches another repository: " + path)
    oid = path.rsplit("/commits/", 1)[1].split("?")[0]
    if oid not in state["commits"]:
        fail("no commit " + oid)
    save()
    print(json.dumps({"files": [{"filename": f} for f in state["commits"][oid]]}))
elif args[:2] == ["issue", "view"]:
    save()
    print(json.dumps({"comments": state["issues"].get(args[2].lstrip("#"), [])}))
else:
    fail("unsupported " + " ".join(args), 2)
