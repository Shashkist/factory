# factory-tools: the commands

`factory-tools` is the command line of the `factory_tools` package. Every command also runs as `python -m factory_tools <command>`. No command reads, prints or stores a token value; `gh` and git use the credentials already on the machine.

## `factory-tools profile`

The project profile (`.factory/factory.yaml`); see [profile.md](profile.md).

```
factory-tools profile check
```

### `factory-tools profile check`

Validate a profile. The optional argument is the path (default `.factory/factory.yaml`). Prints `ok` and exits 0, or one `<key path>: <message>` line per problem and exits 1 (2 when the file cannot be read).

```
factory-tools profile check .factory/factory.yaml
```

## `factory-tools methodology`

### `factory-tools methodology render`

Print the manager skill's project section (verify commands with their cwd, exam globs, limits, planning, label map, research hints, smoke, protected paths, required checks, decisions and owner files) filled from the profile. `--profile PATH` (default `.factory/factory.yaml`). A key the profile leaves out prints its documented default from [profile.md](profile.md): exam `**/tests/acceptance/**`, ci_rounds 5, review_rounds 2, parallel_issues 3. A missing or invalid profile prints one `<profile path>: <key path>: <message>` line per problem and exits 2 (unreadable) or 1 (invalid), with no traceback.

```
factory-tools methodology render --profile .factory/factory.yaml
```

## `factory-tools claim`

Take an issue, or fail if someone live holds it. Takes the issue number and `--session NAME`.

Options: `--session` (this session's name), `--repo` (owner/name, when not this repository), `--branch` (required), `--worktree`, `--step`, `--steal` (take a held claim; needs `--reason`), `--reason`, `--stale-after` (minutes before a claim counts as quiet).

```
factory-tools claim 12 --session lf-a1b2 --branch f/12-claims --step build
```

## `factory-tools heartbeat`

Say you are still here and what you are doing.

Options: `--session`, `--repo`, `--step`, `--blocked` (waiting on someone off this machine; `stale` will not offer a steal), `--unblocked` (the wait is over).

```
factory-tools heartbeat 12 --session lf-a1b2 --step check
```

## `factory-tools release`

Hand the issue back.

Options: `--session`, `--repo`, `--reason`, `--force` (release a claim that is another session's).

```
factory-tools release 12 --session lf-a1b2 --reason merged
```

## `factory-tools status`

Who holds what, across repositories.

Options: `--json` (machine-readable rows), `--repo` (owner/name, repeatable: only these), `--repos-file` (a list file with `- repo: owner/name` lines).

```
factory-tools status --repo Shashkist/factory --json
```

## `factory-tools stale`

Claims whose session has gone quiet, with the branch to continue from.

Options: `--older-than` (minutes of silence), `--repo` (repeatable), `--repos-file`.

```
factory-tools stale --older-than 60 --repo Shashkist/factory
```

## `factory-tools progress`

Live progress of the factory. The sub-commands below take their own options; the events file is `$LF_PROGRESS_FILE`, else `~/.lf-factory/progress.jsonl`. Nothing here fails the caller.

```
factory-tools progress add --issue 14 --agent implementer-14 --role implementer --station build --substep "unit tests" --status start
```

### `factory-tools progress add`

Record one sub-step. Required: `--agent`, `--role`, `--station`, `--substep`, `--status`. Optional: `--issue`, `--repo` (owner/name), `--title`, `--detail-file` (a file, or `-` for stdin).

```
factory-tools progress add --issue 14 --agent implementer-14 --role implementer --station build --substep lint --status done
```

### `factory-tools progress hook`

Record a Claude Code hook event read from stdin (allowlisted fields only). Does nothing unless `$LF_PROGRESS_FILE` is set.

```
factory-tools progress hook < hook-event.json
```

### `factory-tools progress pass-start`

Mark the start of a manager pass. Options: `--pass-no`, `--budget`.

```
factory-tools progress pass-start --pass-no 3 --budget 40
```

### `factory-tools progress pass-end`

Mark the end of a manager pass. Option: `--result` (default `done`).

```
factory-tools progress pass-end --result done
```

### `factory-tools progress runner-state`

Set the runner state. Options: `--state` (required: `idle`, `paused`, `budget` or `running`), `--note`.

```
factory-tools progress runner-state --state idle --note "nothing ready"
```

### `factory-tools progress render`

Build the public live view from the events. Option: `--out` (required, the output file).

```
factory-tools progress render --out live.json
```

### `factory-tools progress publish`

Push the rendered live view with a key that can write only that file. Options: `--key` (required, the key file), `--host` (required), `--force`, `--min-age` (seconds since the last push).

```
factory-tools progress publish --key KEYFILE --host root@HOST --min-age 30
```

## `factory-tools ci-paths`

CI path rules: which commits are docs-only and which pull requests need the heavy jobs. Runs as `python -m factory_tools.pipeline.paths` and as a plain file with the same arguments. Prints `true` or `false`; fails loudly on an unknown revision.

```
factory-tools ci-paths deploys TAG HEAD
```

### `factory-tools ci-paths deploys`

`true` when a green CI for `<tag>` may deploy: the tag is on `<head>` (main) and only docs changed since.

```
factory-tools ci-paths deploys v1.2.0 origin/main
```

### `factory-tools ci-paths heavy`

`true` when the pull request (`<base>...<head>`) touches a heavy path.

```
factory-tools ci-paths heavy origin/main HEAD
```

## `factory-tools incident-gate`

Decide whether a failed workflow run should raise an incident. Prints `raise` or `skip`: a single failed scheduled `Factory dashboard` run is noise and raises only when the previous scheduled run failed too; everything else raises. Runs as `python -m factory_tools.pipeline.incident_gate` and as a plain file.

Options: `--workflow` (required, the workflow name), `--event` (required, the triggering event), `--previous` (the previous run's conclusion; default empty).

```
factory-tools incident-gate --workflow "Factory dashboard" --event schedule --previous failure
```

## `factory-tools merge-gate`

Decide whether a pull request may merge, from facts only, read-only. Prints `MERGE` (exit 0) or one `HOLD: <reason>` line per reason (exit 1). Takes the PR number, `--session NAME` and, when not this repository, `--repo owner/name`; `--author LOGIN` is who may give the review verdict (default: the PR author).

It holds unless: every check passed and `exam-integrity` succeeded; the latest `Review round <k>: APPROVE at <sha>` verdict is for the current head and the review round is at most 2; at most 5 commits changed code; no commit changes `tests/acceptance/` together with code; the PR is not cross-repository; and the session holds the claim on every issue the PR closes.

```
factory-tools merge-gate 9 --repo owner/name --session lf-a1b2
```

## `factory-tools worktrees`

The local worktrees and branches of finished work.

```
factory-tools worktrees prune
```

### `factory-tools worktrees prune`

Remove the worktrees, and their local branches, whose work is finished: the PR merged and nothing was committed after the merge, or the PR closed and the branch tip is on the server; a subagent worktree (`.claude/worktrees/agent-*`) idle longer than 90 minutes and older than this pass whose tip is on a remote branch; empty leftover folders under `.claude/worktrees/`. A worktree that holds another worktree or any `.git` file or folder below its top level is kept, with the nested path named. Anything with tracked changes, a live claim, an open PR, no PR, a lock, or an unreadable `git status` is kept. Untracked and ignored top-level names are printed before a worktree is removed. The main worktree and the one the command runs from are never touched. A folder the OS reports busy is skipped, never forced. `gh` is only read.

One line per worktree or folder: `<STATUS> <path> <reason>`, STATUS `REMOVED`, `KEPT` or `SKIPPED`. Exit 0 whenever the command could do its job. Run it from the clone of the repository named by `--repo`: when `origin` is a GitHub URL naming another repository it exits 2 with both names and removes nothing, also under `--dry-run`. A local-path `origin` is accepted.

Options: `--dry-run` (print the same lines, change nothing), `--issue` (only the worktree of `f/<n>-...`, no leftover sweep), `--pass-start` (ISO 8601 start of this pass; subagent worktrees are kept without it), `--repo` (owner/name `gh` is aimed at).

```
factory-tools worktrees prune --pass-start 2026-11-25T08:00:00Z --repo owner/name --dry-run
```
