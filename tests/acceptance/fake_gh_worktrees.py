"""A fake `gh` for the worktree prune exam: pull requests per branch and issue claim comments.

Run as: python fake_gh_worktrees.py <gh args>, with FAKE_GH_STATE pointing at a JSON state file:

    {"prs": {"<branch>": [{"number": 1, "state": "MERGED", "mergedAt": "...",
                           "headRefOid": "..."}]},
     "claims": {"<issue number>": ["<comment body>", ...]},
     "fail": ["all" | "pr" | "issue"], "calls": []}

* `pr list --head <branch> --state all --json ...` returns the stored list for the branch (the
  full objects, whatever fields were asked for); an unknown branch has no PR (an empty list).
* `issue view <n> --json comments` returns {"comments": [{"body", "url"}]} like the real one.
* A trailing `-R <repo>` is accepted and recorded; the call is recorded in `calls` as given.
* Anything else (a write, `auth`, ...) is refused with exit 1: pruning only reads GitHub.
"""

import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]

with open(STATE, encoding="utf-8") as f:
    state = json.load(f)
state["calls"].append(args)
with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f)

a = list(args)
if "-R" in a:
    i = a.index("-R")
    del a[i : i + 2]
fail = state.get("fail", [])
if "all" in fail or (a and a[0] in fail):
    sys.stderr.write("fake gh: boom\n")
    sys.exit(1)
if a[:2] == ["pr", "list"] and "--head" in a:
    print(json.dumps(state["prs"].get(a[a.index("--head") + 1], [])))
elif a[:2] == ["issue", "view"]:
    bodies = state["claims"].get(a[2], [])
    comments = [
        {"body": b, "url": "https://github.com/o/r/issues/" + a[2] + "#issuecomment-" + str(i + 1)}
        for i, b in enumerate(bodies)
    ]
    print(json.dumps({"comments": comments}))
else:
    sys.stderr.write("fake gh: unsupported " + " ".join(args) + "\n")
    sys.exit(1)
