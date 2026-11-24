"""Decide whether a failed workflow run should raise an incident.

A single failed *scheduled* `Factory dashboard` run is noise; it raises only when the previous
scheduled run failed too. Everything else raises. Prints `raise` or `skip`.
"""

import argparse

FAILING = ("failure", "timed_out", "startup_failure")


def decide(workflow: str, event: str, previous: str = "") -> str:
    if workflow == "Factory dashboard" and event == "schedule":
        return "raise" if previous.strip() in FAILING else "skip"
    return "raise"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workflow", required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--previous", default="")
    a = p.parse_args(argv)
    print(decide(a.workflow, a.event, a.previous))


if __name__ == "__main__":
    main()
