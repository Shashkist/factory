"""CI path rules (#271): which commits are docs-only, which PRs need the heavy jobs.

  paths.py deploys <tag> <head>     true or false: may a green CI for <tag> deploy (main is <head>)
  paths.py heavy <base> <head>      true or false: does the PR touch a heavy path
"""

import os
import subprocess
import sys

# Directories and root files whose changes alone never need CI or a Deploy (keep in step with
# ci.yml paths-ignore: "<dir>/**" for a directory, the bare name for a root file).
DOCS_DIRS = ("docs", "courses", ".claude")
DOCS_FILES = ("history.md",)
DOCS_ONLY = (*DOCS_DIRS, *DOCS_FILES)


def check_docs_names(names: tuple[str, ...]) -> None:
    # Every name becomes a glob pathspec below, so a glob character or a backslash would change
    # its meaning (the "history.m[d]" trick does not escape them).
    for n in names:
        if any(c in n for c in "*?[\\"):
            raise ValueError(f"docs name {n!r} must not contain * ? [ or a backslash")

# Directory prefixes whose changes need the docker and image jobs.
HEAVY = (
    "labs/images/",
    "labs/manager/",
    "labs/deploy/",
    "labs/content/",
    # The docker job's browser exam drives the built web app and reads its labels; the
    # manager image builds it from these files (#312, D99).
    "labs/web/src/",
    "labs/web/tests/acceptance/",
    "labs/web/package.json",
    "labs/web/package-lock.json",
    "labs/web/vite.config.ts",
    ".github/workflows/",
)


PATHSPEC_ENV = (
    "GIT_LITERAL_PATHSPECS",
    "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
    "GIT_ICASE_PATHSPECS",
)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    # GIT_LITERAL_PATHSPECS=1 would read the ":(top)" and ":(exclude)" specs as file names, and
    # GIT_ICASE_PATHSPECS=1 would exclude "Docs/" while ci.yml paths-ignore is case-sensitive.
    env = {k: v for k, v in os.environ.items() if k not in PATHSPEC_ENV}
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        check=check,
        capture_output=True,
        env=env,
    )


def code_spec() -> list[str]:
    # Pathspec exclusion: git decides what is docs-only, no path text is parsed here. Same
    # meaning as ci.yml paths-ignore: "<dir>/**" is the contents of a root directory (a root file
    # of that name is code); a bare name is the root file only (a directory of that name is code).
    # A glob spec with no wildcard also matches a directory, so the last character of a file
    # name goes in a character class ("history.m[d]"), which git matches against the whole path.
    check_docs_names(DOCS_DIRS)
    check_docs_names(DOCS_FILES)
    files = (f[:-1] + "[" + f[-1] + "]" for f in DOCS_FILES)
    return [
        ":(top)",
        *(f":(exclude,top,glob){d}/**" for d in DOCS_DIRS),
        *(f":(exclude,top,glob){f}" for f in files),
    ]


def deploys(tag: str, head: str) -> bool:
    # A green CI for <tag> may deploy when <tag> is on main and main's code is the same tree as
    # <tag>'s: only docs changed since. This is the comparison GitHub's push paths-ignore makes
    # (start and end of a push), so a push whose net change is docs-only never strands a code
    # commit. Different code on main (newer, or a revert of <tag>) means another CI deploys.
    on_main = git("merge-base", "--is-ancestor", tag, head, check=False).returncode
    if on_main not in (0, 1):
        raise SystemExit(f"git merge-base failed for {tag} and {head}")
    if on_main == 1:
        return False
    same = git("diff", "--quiet", tag, head, "--", *code_spec(), check=False).returncode
    if same not in (0, 1):
        raise SystemExit(f"git diff failed between {tag} and {head}")
    return same == 0


def is_heavy(base: str, head: str) -> bool:
    names = git("diff", "--name-only", "-z", f"{base}...{head}").stdout.decode("utf-8").split("\0")
    return any(n.startswith(HEAVY) for n in names if n)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "deploys":
        print("true" if deploys(argv[1], argv[2]) else "false")
        return 0
    if len(argv) == 3 and argv[0] == "heavy":
        print("true" if is_heavy(argv[1], argv[2]) else "false")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
