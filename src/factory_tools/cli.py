"""The ``factory-tools`` command line: an argparse subcommand tree, one group per area."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from factory_tools import claims, profile, progress
from factory_tools.pipeline import incident_gate, paths


def _profile_check(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    root = path.parent.parent if path.parent.name == ".factory" else Path.cwd()
    _, problems = profile.load_profile(path, root=root)
    if not problems:
        print("ok")
        return 0
    for p in problems:
        print(f"{p.path or '(file)'}: {p.message}")
    return 2 if any(p.fatal for p in problems) else 1


def _incident_gate(args: argparse.Namespace) -> int:
    print(incident_gate.decide(args.workflow, args.event, args.previous))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Each later slice adds its own group here with ``groups.add_parser`` and ``set_defaults``."""
    parser = argparse.ArgumentParser(prog="factory-tools")
    groups = parser.add_subparsers(dest="group", required=True)

    prof = groups.add_parser("profile", help="the project profile")
    prof_cmds = prof.add_subparsers(dest="command", required=True)
    check = prof_cmds.add_parser("check", help="validate a profile")
    check.add_argument("path", nargs="?", default=profile.DEFAULT_PATH)
    check.set_defaults(func=_profile_check)
    claims.add_commands(groups)

    prog = groups.add_parser("progress", help="live progress and the crew view", add_help=False)
    prog.add_argument("args", nargs=argparse.REMAINDER)
    prog.set_defaults(func=lambda a: progress.run(a.args))

    cp = groups.add_parser("ci-paths", help="CI path rules: docs-only deploys, heavy PRs")
    cp_cmds = cp.add_subparsers(dest="command", required=True)
    for name, first, helptext in (
        ("deploys", "tag", "true or false: may a green CI for <tag> deploy (main is <head>)"),
        ("heavy", "base", "true or false: does the PR touch a heavy path"),
    ):
        sp = cp_cmds.add_parser(name, help=helptext)
        sp.add_argument(first)
        sp.add_argument("head")
        sp.set_defaults(func=lambda a, n=name, f=first: paths.main([n, getattr(a, f), a.head]))

    ig = groups.add_parser("incident-gate", help="should a failed workflow run raise an incident")
    ig.add_argument("--workflow", required=True)
    ig.add_argument("--event", required=True)
    ig.add_argument("--previous", default="")
    ig.set_defaults(func=_incident_gate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
