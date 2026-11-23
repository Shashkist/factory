# Decisions

Every decision and assumption made while building the Factory. When two documents disagree, this file settles it. Each entry: number, title, status line, the decision, why, alternatives, how to revert. Take the next number only right after `git pull --rebase origin main`.

## D1 · Home, builder and migration order (owner, 2026-11-23)
in force · owner · 2026-11-23

**Decision.** The Factory lives in this public repository. Until v0 is done it is built by the Learning Factory manager, which takes issues from here as a second repository (its first multi-repository step, made in `Shashkist/Learning_factory`). v0 moves LF's methodology here; LF keeps only its project profile and continues labs development through this repository's methodology. `factory.shashkist.com` moves here as well. Spec section 17.

**Why.** The owner wants the factory as its own product with LF as client #1; a public repository keeps CI free at the factory's pace.

**Alternatives.** A private repository (paid Actions minutes); a `factory/` folder inside LF, extracted later.

**Revert.** Archive this repository; LF keeps its own copy of the methodology until the switch issue ships.

## D2 · Owner pre-approvals for #6 (dashboard publish) and #7 (runner switch)
in force · owner · 2026-11-23

**Decision.** #6: the owner approves giving this repository's `production` environment what it needs to publish `factory.shashkist.com`, with no value read, printed or committed. GitHub secrets cannot be read back, so LF's values are not copied. Instead an owner script generates a new key `factory-dashboard`, limited on the server by a forced command to writing the dashboard's web root, and sets the environment secrets by piping. The owner runs it; the factory never does. #7: the owner pre-approves switching LF's laptop runner to this repository's plugin and tools. The factory prepares the exact change and the switch-back step; an interactive owner session applies it.

**Why.** The owner's answer on 2026-11-23. Least privilege: a second public repository gets no root key to a shared server.

**Alternatives.** Reuse LF's root deploy key (impossible to read back, and it widens what this repository can do on the server).

**Revert.** Remove the `factory-dashboard` key line from the server and the environment secrets; the runner switch has its own documented switch-back.


## D3 · CI foundation layout: what is the exam, where the gates live, how the incident step is faked (#1)
assumption · manager · 2026-11-23

**Decision.**
- The exam is every file under `tests/acceptance/**`, plus pytest configuration files (`conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg`) anywhere outside `tests/unit/`. Pytest is configured in a root `pytest.ini` (part of the exam), never in `pyproject.toml`, so a code commit cannot change how the exam runs. Code is every path outside `tests/` that is not the exam (`src/**`, `pyproject.toml`, workflows, ...). The CI surface (changed together with the exam only in bootstrap mode) is `src/factory_tools/ci/**` and `.github/workflows/ci.yml`.
- The gates are stdlib-only modules: `src/factory_tools/ci/exam_integrity.py`, `src/factory_tools/ci/junit_gate.py`, `src/factory_tools/ci/incident.py`, each runnable as `python -m factory_tools.ci.<name>` and as a plain file (`python path/to/file.py`), so CI can run the base branch's copy of `exam_integrity.py` with `git show`, as LF does. With no copy on the base branch, CI runs the PR's copy with `--bootstrap` (this first PR); every later PR runs the base copy normally.
- `python -m factory_tools.ci.incident --workflow <name> --run-url <url>` comments `Failed again: <url>` on the open issue titled `Incident: <name> failed` labelled `type:incident`, or opens it with labels `type:incident,priority:p0,status:ready`. It calls `gh` through the command prefix in the environment variable `FACTORY_GH` (a JSON array, default `["gh"]`), so a test can point it at a fake written in Python on any OS.

**Why.** The issue leaves the gate location and the fake `gh` open. Keeping the gates stdlib-only keeps LF's "run the base copy" trick; a root `pytest.ini` closes the gap where `[tool.pytest.ini_options]` in `pyproject.toml` could skip exam cases from a code commit.

**Alternatives.** Gates under `scripts/ci/` as in LF (outside the package, not type-checked by `mypy src`); the incident logic inline in the workflow shell (untestable with a fake `gh` on Windows).

**Revert.** Move the modules and update `ci.yml`; nothing else depends on the paths yet.

**D3 amendment 1 (2026-11-23, review of #9).** (a) The exam is every path under `tests/` outside `tests/unit/` (as in LF), plus the pytest configuration files (`conftest.py`, `pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`) anywhere outside `tests/unit/`; round 1 showed a `tests/.pytest.ini` from a code commit deselecting exam cases. (b) CI runs the exam with `-c pytest.ini -o addopts="" --confcutdir=tests` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and the JUnit gate from the base branch's copy. (c) Correction: a code commit cannot change how the exam runs *through pytest configuration*; code that runs inside the pytest process (for example `src/sitecustomize.py`) still can, and review stays the guard (#11 closes the known case).

## D4 · Project profile schema, loader and CLI (#2)
in force · factory · 2026-11-23 · revertible

**Decision.** The spec leaves the exact `factory.yaml` schema to the builder (section 14). For #2:
- **Parser and model.** `yaml.safe_load` from PyYAML, the package's first runtime dependency (`types-PyYAML` in dev); never `yaml.load`. The model is frozen dataclasses in `src/factory_tools/profile.py` with a hand-written validator, so every problem carries its key path (`verify.manager.run`) and no further dependency is needed.
- **API.** `load_profile(path, root=None) -> tuple[Profile | None, list[Problem]]`; a `Problem` has `path` (dotted key path, list items as `[i]`, the empty string for the document itself) and `message`. Area globs are checked against `root` only when a root is given; the CLI passes the repository root (the parent of `.factory/` when the file sits there, else the current directory).
- **CLI.** `factory-tools profile check [path]` (console script `factory-tools = "factory_tools.cli:main"`, also `python -m factory_tools profile check`); default path `.factory/factory.yaml`. One line per problem, `<key path>: <message>`, exit 1 when there is any; `ok` and exit 0 when there is none; exit 2 when the file cannot be read or is not valid YAML.
- **Fields and defaults.** `methodology` (string, required). `verify`: mapping area name to `{cwd: string = ".", run: non-empty list of strings}`, default `{}`. `exam`: list of globs, default `["**/tests/acceptance/**"]`. `protected_paths`: list of globs, default `[]`. `required_checks`: list of strings, default `[]`. `labels`: mapping of the Factory's label name to the project's label name, default `{}` (the same names). `limits`: `{ci_rounds: 5, review_rounds: 2, parallel_issues: 3}`, positive integers (a boolean is not an integer). `models`: mapping role (`manager`, `exam-writer`, `implementer`, `reviewer`, `researcher`) to a model id, default `{}`. `smoke`: `null` (default) or a mapping with exactly one of `run` (string, with optional `cwd`, default ".") or `workflow` (string). `research_hints`: list of strings, default `[]`. `areas`: mapping name to a non-empty list of globs, default `{}`. `planning`: `null` (default, off) or `{spec: string (required), keep_ready: positive integer = 5}`. `owner_files`: `{decisions: ".factory/DECISIONS.md", owner: ".factory/OWNER.md"}`. Unknown keys are errors at every level.
- **Docs.** `docs/profile.md` has one `## \`<field>\`` heading per top-level field, in model order, each with its type, default and an example; a full example closes the page.
- The Learning Factory example profile is `tests/fixtures/learning_factory.yaml` (part of the exam under D3 amendment 1).

**Why.** Key paths need a validator that walks the document; dataclasses keep the model typed for `mypy --strict` without pydantic. PyYAML is the common YAML reader and `safe_load` constructs only plain data, which is what criterion 4 asks.

**Alternatives.** pydantic (error paths built in, a heavy dependency for one file); TOML through the standard library `tomllib` (no dependency, but the spec names `factory.yaml`).

**Revert.** Revert the #2 squash commit; nothing else reads the profile yet.

## D5 · #3 is sliced into three issues; module and command names of the tools package
in force · factory · 2026-11-23 · revertible

**Decision.** #3 ports five scripts and their tests (several thousand lines), far over one reviewable PR. It is sliced, each slice one PR, and #3 closes when all three are merged:
- **#12 claims**: `issue_lock.py` → `src/factory_tools/claims.py`, command `factory-tools claim|release|heartbeat|status|stale` (criteria 1, 2 and 5 of #3 for claims).
- **#13 progress and crew**: `factory_progress.py`, `_hook_io.py`, `factory_crew.py` → `src/factory_tools/progress.py`, `hook_io.py`, `crew.py`, command `factory-tools progress add|hook|pass-start|pass-end|runner-state|render|publish` (criteria 1, 3, 4 and 5 for progress). The port starts from LF's copy after LF #558 (bounded publish, LF D147).
- **#14 CI paths, incident gate and docs**: `ci_paths.py`, `incident_gate.py` → `src/factory_tools/ci/paths.py`, `ci/incident_gate.py` (stdlib-only, runnable as files, like the D3 gates); `docs/tools.md` for every command of the three slices.
All commands hang off the one CLI `factory_tools.cli:main` that #2 creates (`factory-tools profile check`), so each slice depends on #2. LF's tests for a ported script are ported by the exam-writer, with only import and path changes, into `tests/acceptance/ported/` (they are that slice's exam); every other change to a test is listed in the PR. LF keeps its own copies until #7 switches it over (spec G8).

**Why.** A port of this size cannot be reviewed in one PR; three slices follow the scripts' own seams (claims, live view, CI). One CLI module avoids three PRs racing to create it.

**Alternatives.** One PR for all of #3 (too large to review); one CLI per module (three console scripts instead of one `factory-tools`).

**Revert.** Close #12 to #14 and reopen #3 as one piece.

**D4 amendment 1 (2026-11-23, review round 1 of #15).** (a) `models` keys must be one of the five roles; an unknown role is an error at `models.<key>`. (b) An area glob that is absolute (`/x`, `C:/x`) or has a `..` segment is an error at `areas.<name>[i]`, with or without a root; `.` and `./` mean the whole repository and match when the root exists; a glob the path library cannot handle is reported (`invalid glob`), never a traceback. (c) A duplicate key in any mapping is an error at its path; input nested too deeply is a fatal problem (exit 2). (d) `exam` must be a non-empty list, and `methodology`, every `verify` command, `smoke.run`, `smoke.workflow`, `planning.spec` and both `owner_files` values must be non-empty strings. (e) A problem with the document itself prints as `(file): <message>`. (f) `labels` keys stay open for now (the Factory's own label set is fixed by the plugin issue, #4), so a typo there is not caught yet. (g) The exam must be harmless even when the code under test is wrong: its "nothing runs" strings only create marker files, never delete. Because (g) and the new cases change the exam after code was committed, #2 is rebuilt as `f/2-project-profile-2`: an exam-only commit first, then the code commit with the fixes (LF D103).

## D6 · #2 merges after review round 2 on the manager's own fix
in force · factory · 2026-11-23 · revertible

**Decision.** Review round 2 of #16 had one blocking finding: the duplicate-key walk followed YAML aliases with no visited set, so a 354-byte file took 54 s to load. The manager fixed it (e2a6962: each container is visited once, plus a unit test where an 8-level alias file loads in under 5 s), CI passed, and #16 merges without a third round, as Learning Factory does after two rounds (LF D145). The round-2 non-blocking findings go to a follow-up issue: compare constructed keys, not raw text (`1` vs `"1"`, `yes` vs `true`); backslash area globs behave differently on Windows and Linux; an empty glob is reported only with a root; Windows absolute globs only in unit tests, not the exam.
**Revert.** Revert the #2 squash commit.
