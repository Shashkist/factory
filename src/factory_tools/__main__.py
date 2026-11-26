import sys


def entry(argv: list[str]) -> int:
    """`progress hook` runs on every tool call, so it skips the CLI tree (YAML, profile, claims,
    worktrees, pipeline) and loads only the progress module. Everything else is the full CLI."""
    if argv[:2] == ["progress", "hook"]:
        from factory_tools import progress

        return progress.run(argv[1:])
    from factory_tools.cli import main

    return main()


if __name__ == "__main__":
    sys.exit(entry(sys.argv[1:]))
