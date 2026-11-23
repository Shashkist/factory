"""Open or update the incident issue for a failed workflow (DECISIONS D3).

Usage: python incident.py --workflow <name> --run-url <url>

Comments "Failed again: <url>" on the open issue titled "Incident: <name> failed"
labelled type:incident, or opens it. `gh` is called through the command prefix in
FACTORY_GH (a JSON array, default ["gh"]), so a test can point it at a fake.
The labels must already exist in the repository (creating them is not this
module's job); a missing label makes `gh issue create` fail and this exit 1.
"""

import argparse
import json
import os
import subprocess
import sys

LABELS = "type:incident,priority:p0,status:ready"


def _gh(*args: str) -> str:
    prefix = json.loads(os.environ.get("FACTORY_GH", '["gh"]'))
    return subprocess.run([*prefix, *args], check=True, capture_output=True, text=True).stdout


def report(workflow: str, run_url: str) -> str:
    title = f"Incident: {workflow} failed"
    issues = json.loads(
        _gh(
            "issue", "list", "--state", "open", "--label", "type:incident",
            "--json", "number,title,labels", "--limit", "200",
        )
    )
    for issue in issues:
        names = {label["name"] for label in issue.get("labels", [])}
        if issue["title"] == title and "type:incident" in names:
            _gh("issue", "comment", str(issue["number"]), "--body", f"Failed again: {run_url}")
            return f"commented on #{issue['number']}"
    _gh(
        "issue", "create", "--title", title, "--label", LABELS,
        "--body", f"The {workflow} workflow failed: {run_url}",
    )
    return "opened a new incident issue"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args(argv)
    try:
        print(report(args.workflow, args.run_url))
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        print(f"incident: failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
