"""A fake `gh` for the merge gate exam: pull requests, commit files and issue comments.

Run as: python fake_gh_merge_gate.py <gh args>, with FAKE_GH_STATE pointing at a JSON state file:

    {"default": "owner/name", "calls": [], "writes": [],
     "repos": {"owner/name": {
         "prs": {"9": {<pull request fields>}},
         "commits": {"<oid>": ["path", ...]},
         "issues": {"5": [<comment objects>]}}}}

* `pr view <n> ... --json <fields>` (`<n>` may also be `#<n>` or a pull request URL) returns ONE
  object with every stored field plus `number`, whatever fields were asked for
  (the gate must not depend on --jq or on the field list).
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
* `api repos/<o>/<r>/actions/runs/<id>` returns the run stored under `runs` for that repository
  (`{"runs": {"o/r": {"<id>": {...}}}}`; a missing one is a 404). `api repos/<o>/<r>/contents/
  <path>?ref=<sha>` returns the file stored under `contents` (`{"o/r": {"<path>@<sha>": text}}`):
  JSON with base64 `content` by default, the raw text when a `-H Accept: ...raw` header is
  given; the ref is required. `api repos/<o>/<r>/compare/main...<sha>` returns {"status": ...}
  from `compare` (`{"o/r": {"<sha>": "behind"}}`; a base other than `main` or an unknown sha is a
  404). Actions runs and contents are only served for the repository the pull request is in; the
  workflows repository's compare is served for any known repository.
* `api repos/<o>/<r>/actions/jobs/<id>` returns the job stored under `jobs` for that repository
  (`{"jobs": {"o/r": {"<id>": {...}}}}`; a missing one is a 404; an entry `{"__error__": "<text>"}`
  fails with that text, as a server error would). Served like the runs (#86).
* `api` accepts `--paginate` and returns the whole list in one object (the gate may use it).
* `issue view <n> --json comments` returns {"comments": [...]} (empty for an unknown issue).
* Anything that writes (pr merge, comment, review, edit, close, api -X ...) is recorded in
  `writes` and refused: the gate is read-only.
Every call is recorded in `calls`, except compare calls (`workflow_calls`).
"""

import base64
import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
WRITES = {"merge", "comment", "review", "edit", "close", "reopen", "ready", "create"}

with open(STATE, encoding="utf-8") as f:
    s = json.load(f)
# A compare call reads the workflows repository, not the pull request's: it is recorded in
# `workflow_calls`, so `calls` keeps listing only reads of the pull request's own repository.
is_compare = len(args) > 1 and args[0] == "api" and any("/compare/" in a for a in args)
s.setdefault("workflow_calls", [])
s["calls" if not is_compare else "workflow_calls"].append(args)


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
    # Like the real gh: `9`, `#9` and a pull request URL name the same pull request (#102).
    key = args[2].rstrip("/").rsplit("/", 1)[-1].lstrip("#")
    pr = state["prs"].get(key)
    if pr is None:
        fail("no pull request " + args[2])
    s["resolved"] = repo
    save()
    print(json.dumps({"number": int(key), **pr}))
elif group == "api":
    path = next((a for a in args[1:] if a.startswith("repos/")), None)
    if path is None:
        fail("unsupported api call: " + " ".join(args))
    if path.startswith("repos/{owner}/{repo}/"):
        path = "repos/" + repo + path[len("repos/{owner}/{repo}"):]
    parts = path.split("?")[0].split("/")
    target = "/".join(parts[1:3])
    kind = parts[3] if len(parts) > 3 else ""
    state = lookup(target)
    if kind not in ("commits", "actions", "contents", "compare"):
        fail("unsupported api call: " + " ".join(args))
    # Only the workflows repository (compare) may differ from the pull request's repository.
    if kind != "compare" and s.get("resolved") and target.lower() != s["resolved"].lower():
        fail("api read " + target + " but the pull request is in " + s["resolved"])
    if kind == "commits":
        oid = path.rsplit("/commits/", 1)[1].split("?")[0]
        if oid not in state["commits"]:
            fail("no commit " + oid)
        save()
        entries = [{"filename": f} if isinstance(f, str) else f for f in state["commits"][oid]]
        print(json.dumps({"files": entries}))
    elif kind == "compare":
        base, _, sha = "/".join(parts[4:]).partition("...")
        status = s.get("compare", {}).get(target.lower(), {}).get(sha)
        if base != "main" or status is None:
            fail("404 compare " + "/".join(parts[4:]))
        save()
        print(json.dumps({"status": status, "ahead_by": 0, "behind_by": 0}))
    elif kind == "actions":
        if len(parts) != 6 or parts[4] not in ("runs", "jobs"):
            fail("unsupported api call: " + " ".join(args))
        what = "workflow run" if parts[4] == "runs" else "job"
        found = s.get(parts[4], {}).get(target.lower(), {}).get(parts[5])
        if found is None:
            fail("404 no " + what + " " + parts[5])
        if "__error__" in found:
            fail(found["__error__"])
        save()
        print(json.dumps(found))
    else:
        file_path = "/".join(parts[4:])
        query = path.split("?", 1)[1] if "?" in path else ""
        ref = next((q[4:] for q in query.split("&") if q.startswith("ref=")), "")
        text = s.get("contents", {}).get(target.lower(), {}).get(file_path + "@" + ref)
        if text is None:
            fail("404 no file " + file_path + " at ref '" + ref + "'")
        save()
        headers = [args[i + 1] for i, a in enumerate(args) if a in ("-H", "--header")]
        if any("raw" in h for h in headers):
            sys.stdout.write(text)
        else:
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            chunks = [b64[i : i + 60] for i in range(0, len(b64), 60)]
            wrapped = "\n".join(chunks) + "\n"
            print(json.dumps({"path": file_path, "encoding": "base64", "content": wrapped}))
elif args[:2] == ["issue", "view"]:
    state = lookup(repo)
    save()
    print(json.dumps({"comments": state["issues"].get(args[2].lstrip("#"), [])}))
else:
    fail("unsupported " + " ".join(args), 2)
