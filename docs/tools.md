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

## Reusable incident workflow

`.github/workflows/incident.yml` opens (or comments on) the issue `Incident: <workflow> failed`, labelled `type:incident`, `priority:p0`, `status:ready`, in the repository whose workflow failed. Here it runs on `workflow_run` of `CI` (a red push to `main`). A client repository calls it with `uses: Shashkist/factory/.github/workflows/incident.yml@<commit-sha>` from a job triggered by `workflow_run` and passes three inputs: `workflow-name` (the watched CI workflow, used in the title), `run-url` (the failed run) and `conclusion` (only `failure`, `timed_out` and `startup_failure` raise an incident). The calling job must grant `permissions: issues: write` (and `contents: read`), and the three labels must exist in the caller. The caller chooses which runs to send (branch, event).

The incident tool is fetched from the Factory at the pinned commit of the workflow into its own path, never from the caller's tree, and runs with the caller's `GITHUB_TOKEN` and `GH_REPO` set to the caller's repository. If the fetch or the tool fails, a plain `gh issue create` still files the incident.

## `factory-tools merge-gate`

Decide whether a pull request may merge, from facts only, read-only. Prints `MERGE` (exit 0) or one `HOLD: <reason>` line per reason (exit 1). Takes the PR number, `--session NAME` and, when not this repository, `--repo owner/name`; `--author LOGIN` is who may give the review verdict (default: the PR author); `--exam-gate NAME` renames the exam gate check (default `acceptance / gate`, exact name); `--workflows-repo owner/name` is the repository whose pinned `junit-gate.yml` and `exam-integrity.yml` must back the exam checks (default `Shashkist/factory`); `--exam-paths GLOB...` and `--ci-paths GLOB...` (repeatable, values split on white space, as in `exam_integrity`) replace the exam and CI-surface rules for nested layouts, and when either is given a PR that changes the exam together with the CI surface also holds (D34); `--decisions PATH` is the decision log (default `docs/factory/DECISIONS.md` from the current directory; a missing file has no D-entries) that lets a PR past the review-round limit (D36).

It holds unless: every check passed, `exam-integrity` succeeded and the exam gate check concluded SUCCESS (skipped, neutral, missing or any other conclusion holds, with a reason naming it; other checks may be neutral or skipped); the latest `Review round <k>: APPROVE at <sha>` verdict is for the current head and the review round is at most 2, or, past the limit (D36), every round above it has a D-entry (a `## D<n>` section of the decision log naming `#<pr>` or `#<closed issue>` and `round <k>`), every extra round but the latest is a CHANGES verdict, and the latest is APPROVE at the head (the gate then prints one `D<n> decides round <k>` line per matched entry before `MERGE`; otherwise `HOLD:` names each undecided round); at most 5 commits changed code; no commit changes `tests/acceptance/` together with code; the PR is not cross-repository; and the session holds the claim on every issue the PR closes.

The exam gate check and every `<caller> / exam-integrity` check count as SUCCESS only when they come from the pinned reusable workflows (D29), otherwise one `HOLD:` line names the check and the failed condition:

1. it is a check run, never a commit status (a bare `exam-integrity` has no caller part and never counts);
2. its details URL is a job of a workflow run of the PR's repository (`https://github.com/<repo>/actions/runs/<id>/job/<id>`) whose `path` is `.github/workflows/ci.yml` and whose `head_sha` is the PR head;
3. the run's `referenced_workflows` lists `<workflows repo>/.github/workflows/junit-gate.yml@<sha>` (respectively `exam-integrity.yml`) with a `sha` on the workflows repository's `main` (`compare/main...<sha>` is `behind` or `identical`);
4. the head's `ci.yml` has exactly one job shown (its `name:`, else its id) under the part of the check name before ` / `, its `uses:` is exactly that referenced `path@sha`, and no job is shown under the full check name; a `uses:` that is not a string holds. The file is read in its raw form and refused when a YAML key repeats.

The line names the first failed condition in this order. Because GitHub evaluates expressions in a job's `name:` and shows a job that calls a local workflow as `<caller> / <called job>`, the file itself also holds, with one line per job, when a job's `name:` contains `${{` or a job's shown name contains ` / ` (D29 amendment 1).

The gate reads each run, the head's `ci.yml` and each compare once per PR. Without `--repo` the run is read both in the checkout's repository and under the repository its URL names; run ids are unique on GitHub, so both succeed only when the URL names the PR's repository.

```
factory-tools merge-gate 9 --repo owner/name --session lf-a1b2
```

## Reusable workflow `exam-integrity.yml`

Called from a client's pull-request CI with `uses: Shashkist/factory/.github/workflows/exam-integrity.yml@<commit-sha>`. It refuses a PR in which one commit changes the exam together with code, the exam changes after code, or the PR changes the exam together with the CI surface. The judge is `python -m factory_tools.ci.exam_integrity <base> <head> [--bootstrap] [--exam-paths GLOB ...] [--ci-paths GLOB ...]`, standard library only, also runnable as a plain file.

Inputs (all strings, all optional):

- `base-ref`: the base branch; empty means the base of the calling PR.
- `exam-paths`: globs naming the exam files, replacing the default (top-level `tests/` except `tests/unit/`, plus pytest configuration files outside `tests/unit/`). For a nested layout: `labs/*/tests/acceptance/**`.
- `ci-paths`: globs naming the CI surface, replacing the default (`src/factory_tools/ci/` and `.github/workflows/ci.yml`). A client lists its own workflow and scripts here, for example `.github/workflows/lf-ci.yml`.

Several globs go in one string, separated by whitespace or newlines (a YAML `|` block with one glob per line). They are split without shell expansion, so a glob is never matched against the runner's files. Globs are fnmatch style against the repo-relative path, and `*` and `**` both match across `/`. Empty inputs mean the defaults, exactly as before.

Each input reaches the judge as one argument and is split on whitespace there, so an input can never become a flag. Globs are normalised: a leading `./` is dropped and a trailing `/` means `<dir>/**` (`tests/acceptance/` is `tests/acceptance/**`; a bare `tests/acceptance` matches only a file of that name). The pytest configuration files (`conftest.py`, `pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`) outside a `tests/unit/` path always count as exam, whatever `exam-paths` says (with the defaults only the top-level `tests/unit/` is exempt; with `exam-paths` any `tests/unit/` folder is, so the client's exam command must not collect a unit folder, or `exam-paths` must name that folder's `conftest.py`). `*.pth` files, `sitecustomize`/`usercustomize` modules (`.py`, `.pyw`, `.pyc`, `.pyd`, `.so`, with any cache or ABI tag in between, so `__pycache__/sitecustomize.cpython-312.pyc` too), a bare `sitecustomize` or `usercustomize` entry (a symlink to a package) and anything under a `sitecustomize/` or `usercustomize/` directory, at any path, always count as exam too. The "top-level `tests/` is never code" exception applies only with the default exam rules.

The caller workflow's inputs come from the PR's own tree, so a PR can edit `exam-paths` or `ci-paths` in the caller workflow itself. A client should therefore list its caller workflow in `ci-paths` (it then counts as a reviewed path: a PR cannot change it together with the exam) and have it reviewed like any CI file.

```
exam-integrity:
  uses: Shashkist/factory/.github/workflows/exam-integrity.yml@<commit-sha>
  with:
    exam-paths: "labs/*/tests/acceptance/**"
    ci-paths: |
      .github/workflows/lf-ci.yml
      ci/**
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
