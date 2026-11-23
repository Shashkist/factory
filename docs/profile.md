# Project profile: `.factory/factory.yaml`

A project tells the Factory how it works through one file, `.factory/factory.yaml`. The Factory reads and validates it; commands in it are data and are never run by the loader. Unknown keys and duplicate keys are errors at every level. Strings that name something (`methodology`, commands, workflow, spec, owner files) must not be empty. Check a file with:

```
factory-tools profile check [path]
```

The default path is `.factory/factory.yaml`. Each problem prints as `<key path>: <message>` (list items as `[i]`); a problem with the document itself prints as `(file): <message>`; exit 0 means ok, 1 means problems, 2 means the file cannot be read, is not valid YAML or is nested too deeply. Area globs are checked against the repository root (the parent of `.factory/`, else the current directory).

Only `methodology` is required.

## `methodology`

String, required. The version of the Factory methodology the project follows.

```yaml
methodology: "0.1"
```

## `verify`

Mapping of area name to a command group `{cwd, run}`. `run` is a non-empty list of command strings; `cwd` is a string, default `"."`. Default: `{}`.

```yaml
verify:
  manager:
    cwd: labs/manager
    run: [uv run pytest -q, uv run ruff check .]
```

## `exam`

Non-empty list of globs: the acceptance tests. Default: `["**/tests/acceptance/**"]`.

```yaml
exam:
  - "labs/**/tests/acceptance/**"
```

## `protected_paths`

List of globs the Factory must not change on its own. Default: `[]`.

```yaml
protected_paths:
  - ".github/workflows/**"
```

## `required_checks`

List of CI check names that gate a merge. Default: `[]`.

```yaml
required_checks: [manager, web]
```

## `labels`

Mapping of the Factory's label name to the project's label name. Default: `{}` (the Factory's own names). The keys are open for now (the Factory's label set is fixed later), so a typo in a key is not caught yet.

```yaml
labels:
  ready: "status:ready"
```

## `limits`

Mapping of positive integers (a boolean is not an integer). Defaults: `ci_rounds: 5`, `review_rounds: 2`, `parallel_issues: 3`.

```yaml
limits:
  ci_rounds: 6
  review_rounds: 3
  parallel_issues: 4
```

## `models`

Mapping of role (`manager`, `exam-writer`, `implementer`, `reviewer`, `researcher`) to a non-empty model id. Any other key is an error. Default: `{}`.

```yaml
models:
  manager: opus
  implementer: sonnet
```

## `smoke`

Optional. `null` by default. A mapping with exactly one of `run` (string, with optional `cwd`, default `"."`) or `workflow` (string, a workflow file name).

```yaml
smoke:
  workflow: smoke.yml
```

## `research_hints`

List of strings: places to look when a design question needs research. Default: `[]`.

```yaml
research_hints: [KodeKloud, Killercoda]
```

## `areas`

Mapping of area name to a non-empty list of path globs. Each glob must be relative (no leading `/`, `\` or drive letter) and have no `..` segment; `.` means the whole repository. Each glob must match something under the repository root. Default: `{}`.

```yaml
areas:
  manager: ["labs/manager/**"]
  web: ["labs/web/**"]
```

## `planning`

Optional. `null` by default (planning off). A mapping with `spec` (string, required) and `keep_ready` (positive integer, default 5).

```yaml
planning:
  spec: docs/spec.md
  keep_ready: 5
```

## `owner_files`

Mapping with `decisions` (default `.factory/DECISIONS.md`) and `owner` (default `.factory/OWNER.md`): the decisions and owner files.

```yaml
owner_files:
  decisions: docs/factory/DECISIONS.md
  owner: docs/factory/OWNER.md
```

# Full example

```yaml
methodology: "0.1"
verify:
  manager:
    cwd: labs/manager
    run: [uv run pytest -q, uv run ruff check ., uv run mypy app]
  web:
    cwd: labs/web
    run: [npm test -- --run, npm run build]
exam: ["labs/**/tests/acceptance/**"]
protected_paths: ["scripts/laptop/**", ".github/workflows/**"]
required_checks: [manager, web, exam-integrity]
labels:
  ready: "status:ready"
  done: "status:done"
limits:
  ci_rounds: 6
  review_rounds: 3
  parallel_issues: 4
models:
  manager: opus
  implementer: sonnet
smoke:
  workflow: smoke.yml
research_hints: [KodeKloud, Killercoda, iximiuz Labs, Instruqt]
areas:
  manager: ["labs/manager/**"]
  web: ["labs/web/**"]
planning:
  spec: docs/superpowers/specs/2026-11-14-lab-platform-design.md
  keep_ready: 5
owner_files:
  decisions: docs/factory/DECISIONS.md
  owner: docs/factory/OWNER.md
```
