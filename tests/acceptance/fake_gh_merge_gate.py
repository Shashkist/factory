"""A fake `gh` for the merge gate exam: pull requests, commit files and issue comments.

Run as: python fake_gh_merge_gate.py <gh args>, with FAKE_GH_STATE pointing at a JSON state file:

    {"default": "owner/name", "calls": [], "writes": [],
     "repos": {"owner/name": {
         "prs": {"9": {<pull request fields>}},
         "commits": {"<oid>": ["path", ...]},
         "issues": {"5": [<comment objects>]}}}}

* `pr view <n> ... --json <fields>` returns ONE object with every stored field, whatever
  fields were asked for (the gate must not depend on --jq or on the field list).
* `api repos/<owner>/<repo>/commits/<oid>` returns {"files": [{"filename": ...}]}. Like the
  real `gh api` (which has no -R flag), a full path resolves to the repository named in the
  path (case-insensitive, with or without -R); an unknown repository fails. Only the
  `{owner}/{repo}` placeholder resolves to the -R repository or the default (gh fills it
  from the current checkout itself).
* The repository a `pr view` call resolved to is remembered (`resolved` in the state file).
  A later `api` call whose repository (named in the path, or the placeholder's default)
  differs from it is refused, as the real `gh` would read another repository's commits. So
  a gate that reads `repos/<other>/commits/...` for a PR in `<repo>`, or that uses the
  placeholder while `--repo` points elsewhere, fails.
* A commit entry is a path (served as {"filename": path}) or a full file object (served as is,
  e.g. {"status": "renamed", "filename": new, "previous_filename": old}).
* `api` accepts `--paginate` and returns the whole list in one object (the gate may use it).
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


def lookup(name: str) -> dict:
    found = known.get(name.lower())
    if found is None:
        fail("Could not resolve to a Repository with the name '" + name + "'")
    return found


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
    state = lookup(repo)
    pr = state["prs"].get(args[2])
    if pr is None:
        fail("no pull request " + args[2])
    s["resolved"] = repo
    save()
    print(json.dumps(pr))
elif group == "api":
    path = next((a for a in args[1:] if a.startswith("repos/")), None)
    if path is None or "/commits/" not in path:
        fail("unsupported api call: " + " ".join(args))
    if path.startswith("repos/{owner}/{repo}/"):
        path = "repos/" + repo + path[len("repos/{owner}/{repo}"):]
    parts = path.split("/")
    target = "/".join(parts[1:3])
    state = lookup(target)
    if s.get("resolved") and target.lower() != s["resolved"].lower():
        fail("api read " + target + " but the pull request is in " + s["resolved"])
    oid = path.rsplit("/commits/", 1)[1].split("?")[0]
    if oid not in state["commits"]:
        fail("no commit " + oid)
    save()
    entries = [{"filename": f} if isinstance(f, str) else f for f in state["commits"][oid]]
    print(json.dumps({"files": entries}))
elif args[:2] == ["issue", "view"]:
    state = lookup(repo)
    save()
    print(json.dumps({"comments": state["issues"].get(args[2].lstrip("#"), [])}))
else:
    fail("unsupported " + " ".join(args), 2)
