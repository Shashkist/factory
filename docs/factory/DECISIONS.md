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

## D7 · #12 review round 1: no fallback to one owner's repository; rebuilt with an exam-first commit
in force · factory · 2026-11-23 · revertible

**Decision.** Review round 1 of #18 (#12) asked for changes. Fixes, all in the code commit:
- (a) With no `origin` and every repository unreadable, `status` and `stale` exit 1 (they printed "No issues are claimed." with exit 0, the false reassurance that invites a double claim).
- (b) No fallback to `Shashkist/Learning_factory` when there is no repository in the current directory: without an origin, only the list file's entries are used (no repository inserted, no warning); with no file and no `--repo`, exit 1 and say "pass --repo". `claimed()` uses the current repository, not LF's hard-coded one.
- (c) The default repository is the one `gh` itself targets (`gh repo view --json nameWithOwner`), so a fork checkout with an `upstream` remote never mislabels rows; `origin` is the fallback when that call fails.
- (d) With `--repo` and no explicit list file, the default list file is still read when it exists, silently, only for clone paths, so `stale` keeps printing LF's `git -C <clone>` take-over line (spec G8).
- (e) Repeated `--repo` values are de-duplicated case-insensitively, keeping order.
The exam gains cases that a wrong port passed: heartbeat and release on a repository that is not the fake's default; every named repository unreadable gives exit 1; `status` in a checkout with an origin and no `--repo` reads that repository. Because the exam changes after code was committed, #12 is rebuilt as `f/12-claims-2`: the original exam, an exam-only commit with the new cases, then the code (D4 amendment 1, LF D103). #18 is closed for the new PR.

**Why.** A tool every client installs must not read one owner's repository by default, and must never report "no claims" when it could read nothing.

**Revert.** Revert the #12 squash commit; LF's `scripts/issue_lock.py` is unchanged.

## D8 · #13 review round 1: plain-file run, watchdogs on every entry point, a distrustful repository list
in force · factory · 2026-11-23 · revertible

**Decision.** Review round 1 of #19 (#13) asked for changes. Fixes for the code commit:
- (a) `progress.py` runs as a plain file with only the standard library, as LF's script does: the `src` path is set before the package imports when run as a script, PyYAML is imported only when `LF_REPOS_FILE` is set, and `crew` is imported lazily inside the crew render, as in LF.
- (b) The hook watchdog (LF #230) and the publish watchdog (LF #558, LF D147) start on every entry point: a `run(argv)` starts them for `hook` and `publish` and then calls `main`; the plain-file `__main__`, `python -m factory_tools.progress` and `factory-tools progress` all go through `run`. `main()` itself starts no watchdog, so in-process tests are not killed.
- (c) The repository list is not trusted: a file over 64 KB is refused; only string `repo` values matching `owner/name` (`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`) count, deduplicated without regard to case; any parse problem, including `RecursionError` and `MemoryError`, falls back to the built-in pair with one stderr line. Values are never expanded with `str()` on arbitrary objects (alias bombs).
- (d) The list is loaded once per process, keyed on path, size and modification time.
- (e) Events store the full canonical repository name (the default's name when no `--repo` is given); only `render` maps the default repository to the `""` lane. If a ported LF test pins the stored `""`, the implementer keeps LF's stored form and the manager amends this entry.
The exam gains cases that wrong code passed: a listed name with a dot (`re.escape` dropped), the lookalike `Shashkist/factory.evil.com`, both watchdogs through `python -m factory_tools progress`, the plain-file run under an interpreter without the package or PyYAML (`-S`), and bad repository files (alias bomb, deep nesting, oversized, invalid entries) that must fall back within seconds. #13 is rebuilt as `f/13-progress-2`: the original exam, an exam-only commit with the new cases, then the code (D4 amendment 1, LF D103). #19 is closed for the new PR. Scrub gaps carried over unchanged from LF (unscrubbed runner note and pass result, `ftp://`, `//host`, UNC paths, short `AKIA` keys, double-encoded dots) go to a follow-up issue in both repositories; they are not regressions.

**Why.** The live page is public: its publisher must stay bounded on every entry point and must not let a malformed list widen what it publishes.

**Revert.** Revert the #13 squash commit; LF's scripts are unchanged.

**D7 amendment 1 (2026-11-24, review round 2 of #20).** Round 2 had one blocking finding: in-process calls of `cmd_status`, `cmd_stale` and `claimed()` asked the real `gh` for the default repository, ignoring the injected runner (16 real calls from the ported "no network" tests; 12 ported tests failed outside a git checkout). Fixed in 6ae19f3: only the command-line handlers resolve the scope; a direct call keeps LF's behaviour; `claimed()` names every repository with `-R`; an explicitly named unreadable `--repos-file` warns; the `origin` fallback drops `scheme://userinfo@` before matching (rule 7). The ported exam passes from an exported copy outside any checkout (185 passed). As in D6, #20 merges on green CI without a third round. The remaining exam gap (the fake's `gh repo view` always equals `origin`) is #21.

## D9 · #14: the CI path classifier and the incident gate live in `factory_tools.pipeline`, not under `factory_tools.ci`
in force · factory · 2026-11-24 · revertible

**Finding.** #14's scope names `src/factory_tools/ci/paths.py` and `src/factory_tools/ci/incident_gate.py`, and its exam (first try, branch `f/14-ci-tools`, exam c920fc2) imports `factory_tools.ci.paths` and `factory_tools.ci.incident_gate`. D3 makes all of `src/factory_tools/ci/**` the CI surface, and exam integrity refuses a PR that changes the exam together with the CI surface (the #1 exam pins this with `src/factory_tools/ci/gate.py`). So no PR can carry #14's exam and its code: `exam_integrity origin/main HEAD` says `PR changes the exam together with the CI surface`.
**Decision.** Keep the #1 rule as strict as it is. The two modules go to a new package `src/factory_tools/pipeline/` (`paths.py`, `incident_gate.py`), run as `python -m factory_tools.pipeline.<name>` and as plain files; CLI commands stay `factory-tools ci-paths` and `factory-tools incident-gate`. The exam is corrected in an exam-only commit on a fresh branch `f/14-ci-tools-2` (module paths only; every case stays), then the code follows. The first branch `f/14-ci-tools` (pushed, no PR) is deleted.
**Alternatives.** Narrow the CI surface to the gate scripts (`exam_integrity.py`, `junit_gate.py`, `incident.py`): loosens an older exam's rule. Land the code before its exam: breaks exam-first.
**Revert.** Move the modules back under `ci/` once the CI surface is narrowed by its own decision.

## D10 · #4 is sliced into three issues
in force · factory · 2026-11-24 · revertible

**Decision.** #4 (the methodology as a Claude Code plugin) ports one skill and four agents, adds a profile-driven renderer and a methodology document: more than one reviewable PR. It is sliced, each slice one PR, and #4 closes when all three are merged:
- **#27** `plugin/.claude-plugin/plugin.json` and the four role agents, generic (criteria 1 and 2 of #4, and criterion 3 for the agents).
- **#28** the manager skill with project facts rendered from the profile (`factory-tools methodology render`), criterion 4, and criterion 3 for the skill. Depends on #27.
- **#29** `docs/methodology.md`. Depends on #28.
**Why.** The agents are small and self-contained and establish the plugin layout and the validation test; the skill depends on that layout and needs the renderer; the document describes both.
**Alternatives.** One PR for #4 (skill, agents, renderer, docs and the paragraph checklist together are too large to review well); skill first (the validation and forbidden-words tests would land with the larger piece).
**Revert.** Close #27 to #29 and build #4 as one piece.

## D11 · #22: issue titles on the live page are capped at 120 characters, not 90
in force · factory · 2026-11-24 · revertible

**Finding.** #22's exam keeps a listed repository link on both sides of each removed form in the issue title. For the longer forms that is about 105 characters; with the 90-character cap the second link is cut mid-URL and redacted to `<url>`, so no implementation can pass the exam.
**Decision.** `progress add` caps the title at 120 characters (as the runner note already is). Scrubbing runs in `render` on the stored, already capped text, so a cut can only remove more, never leak a half form. No older exam pins 90.
**Alternatives.** Shorten the exam's cases (weakens the "listed link next to a removed form" guard for titles); scrub before the cut (a cut could then split a listed link anyway).
**Revert.** Set the cap back to 90 in `progress.py` and drop the six title cases of `test_a_listed_link_next_to_a_removed_form_is_kept` in an exam-only commit.

**D11 amendment 1 (review round 1 of #30, 2026-11-24).** "A cut can only remove more" was wrong: cutting at the cap before scrubbing left the head of a form that its rule no longer matched (a 19-character key id, a 31-character token, three IP octets). `clean` now scrubs the whole text first, then cuts, and a cut inside a word drops that partial word before the ellipsis (a cut that lands right after whitespace, or right before it, keeps every whole word); `render` scrubs again. The 120-character title cap stays.

## D12 · #6 publishes through Learning Factory's existing publisher: no new key, no owner step (owner, 2026-11-24)
in force · owner · 2026-11-24 · revertible · supersedes the #6 half of D2

**Decision.** The owner asked for #6 sooner and without an owner step. This repository gets **no** production secrets and no server key, and the owner script from D2 is not written. The dashboard's code moves here: the page, the snapshot builder for every connected repository, and their tests. Learning Factory's existing `factory-dashboard.yml` keeps the only publish credentials and publishes, split in two:
- a **build job with no secrets** checks out this repository at a commit SHA pinned in LF (a pin change is an LF PR), reads both repositories' public GitHub data, and builds the site as an artifact;
- the **publish job** (LF's `production` environment) only downloads that artifact and copies its files. It runs no code from this repository, so nothing here can reach LF's key.

**Why.** No new key on a shared server and no owner step; the owner's request of 2026-11-24. Running this repository's code only without secrets keeps D2's least-privilege intent.

**Alternatives.** The D2 owner script (a new forced-command key and environment secrets here): needs the owner. A reusable workflow called with `secrets: inherit`: hands LF's root key to code from another repository.

**Revert.** Go back to D2: the owner script, this repository's own `production` environment, and LF stops publishing.

## D13 · #6: the dashboard is the package `factory_tools.dashboard`, built by `python -m factory_tools.dashboard build`
in force · factory · 2026-11-24 · revertible

**Decision.** The factory-side half of #6 (criteria 1, 3 and 4) is one PR; the Learning Factory half (criteria 2 and 5: the pinned checkout in LF's `factory-dashboard.yml`) is a paired LF issue that depends on #6.
- Code: `src/factory_tools/dashboard/` holds the snapshot builder ported from LF's `labs/factory-dashboard/build_snapshot.py` and the page (`index.html`, `app.js`, `styles.css`, `theme.js`) under `static/` as package data.
- Entry point: `python -m factory_tools.dashboard build --repos <repos.yaml> --out <dir> [--fixtures <dir>] [--now <iso>]` writes `<dir>/snapshot.json` and copies the page next to it. `--repos` reads LF's `docs/factory/repos.yaml` format (a list of `- repo: owner/name`; other keys ignored). It needs no secret: only public GitHub data through `gh` with the token the job already has.
- Per repository, `DECISIONS.md` and `OWNER.md` are read from `docs/factory/` of that repository's default branch through the public contents API (in fixtures mode from `<fixtures>/<owner>__<name>/`). `STATE.md` is never read: the public build never published it (LF D14).
- The snapshot keeps LF's current shape, and every lane, issue row, PR, run, decision and owner item carries `repo`; counts are also given per repository. The page shows a repository tag on every lane and issue row.
- The PR is larger than the ~400-line guide because most of it is LF code moved as is; the reviewer compares it with LF's source.

**Why.** One importable package with its page as package data is what a pinned checkout can run in a job with no secrets (D12); the contents API keeps the build to public data without checking out every repository.

**Alternatives.** A top-level `dashboard/` folder outside the package (the page and builder would version apart); checking out every connected repository in the build job (more checkout steps in LF's workflow for two small files each); splitting the page and the builder into two PRs (the page test needs the new snapshot shape).

**Revert.** Delete `src/factory_tools/dashboard/`; LF keeps building from `labs/factory-dashboard/`.

## D14 · #22: round-2 findings are fixed by the implementer and verified by a fresh reviewer, no third full round
in force · factory · 2026-11-24 · revertible

**Decision.** Review round 2 of PR #30 (at 2a050b6) found four blocking items (Unicode-aware lookarounds in the scheme, token and IP rules; a raw worker id; event `at` copied raw and able to crash `render`) and one nit. Each has a concrete failing input and a one- or two-line fix. The implementer applies them, adds each failing input as a unit test (not an exam change), and a fresh reviewer checks only those fixes; its verdict is posted as `Review round 2: APPROVE|CHANGES at <new head>` (as LF D148 amendment 3). On CHANGES, the leftovers become a follow-up issue and #30 waits.
**Why.** The findings are narrow and mechanical; a third full review round would re-read 600 lines to check five regexes. The limit of two rounds stays.
**Alternatives.** Merge now and open a follow-up (ships known leaks to a public page); a third full round (breaks the two-round limit).
**Revert.** Close the fix commit's PR head back to 2a050b6 and treat the five items as a follow-up issue.

**D14 amendment 1 (2026-11-24).** Round-2 finding 3 asked to keep a worker id only when it is exactly 8 hex characters. The older ported exam `test_pass_start_compared_as_datetimes_not_strings` uses the ids `early` and `late` and expects them shown as is, so that rule would weaken nothing but would break an older exam. The id is kept when it is 1 to 12 lowercase ASCII letters or digits (`[a-z0-9]{1,12}`), and hashed with `short_id` otherwise. That still hashes the round-2 leaks (`name.surname`, a `ghp_` value: a dot, an underscore or more than 12 characters). The scheme lookbehind is `(?<![a-z+.-])` (no digits), so `1sftp://host/x` is redacted too.

**D14 amendment 2 (2026-11-24).** The verification of ab981da found a regression the fix itself introduced (an IP followed by a full stop passes whole) and the rest of finding 9 (a naive event time still makes `render` raise). Merging #30 and fixing later would ship the regression to the public page, so the leftovers (A, B and nit C of the verification comment) are fixed on #30's own branch, each failing input as a unit test, and one more fresh reviewer verifies only them. #30 merges only on that APPROVE.

**D13 amendment 1 (review round 1 of #32, 2026-11-24).** `snapshot.json` keeps `lanes` (in-progress and in-review issues per repository: repository, number, title) although the page draws its lanes from the laptop's `live.json`: #6's exam requires it, and every field in it is already shown on the page in the queue and issue rows. This is the one named exception to LF D14's "only what the page shows". `repos` (per-repository counts) is rendered in the counts card.

## D15 · #29: the README's install command assumes the marketplace name `factory` until #7 adds the manifest
assumption · factory · 2026-11-24 · revertible

**Decision.** The repository has `plugin/.claude-plugin/plugin.json` (plugin `factory`) but no `marketplace.json`. #29 asks for the install command in the README, so it reads `/plugin marketplace add Shashkist/factory` then `/plugin install factory@factory`, with one line saying the marketplace manifest arrives with the plugin switch (#7). #29 adds no manifest.
**Why.** A manifest decides how clients install and update the plugin; that belongs to #7, where the first client switches and can test it end to end.
**Alternatives.** Add a minimal `marketplace.json` in #29 (untested install path in a docs PR); leave the command out (fails #29's criterion).
**Revert.** #7 writes the real marketplace name into the README; if it differs, the README line changes there.

## D16 · #35: a PR that closes an issue in another repository holds, as in Learning Factory
in force · factory · 2026-11-24 · revertible

**Decision.** #35 says the session must hold "the claim on every issue the PR closes, in every repository". The port keeps LF's gate behaviour: a closing keyword naming an issue in another repository holds with the reason "another repository", and every same-repository issue the PR closes needs this session's claim.
**Why.** GitHub closes only same-repository issues on merge, so a cross-repository `Closes` line is a mistake or an attempt to borrow another repository's claim; holding is the stricter reading and matches the ported exam.
**Alternatives.** Look up the claim in the other repository and merge if held (more `gh` reads, and the issue still would not close on merge).
**Revert.** Teach `merge-gate` to read the claim in the named repository and drop the hold.

## D17 · #35: the exam's fake `gh api` resolves a full repository path without `-R`, as the real `gh` does
in force · factory · 2026-11-24 · revertible

**Decision.** The real `gh api` has no `-R`/`--repo` flag; it takes the repository from the path (`repos/<owner>/<repo>/commits/<oid>`) or fills the `{owner}/{repo}` placeholder from the current checkout (or `GH_REPO`). The first exam of #35 (`tests/acceptance/fake_gh_merge_gate.py`) only resolved a commit when the call carried `-R`, so the first build had to call the full path and then fall back to the placeholder plus `-R`, a call that fails on the real `gh`. The exam-writer corrects only the fake in an exam-only commit: an `api` call with a full `repos/<owner>/<repo>/...` path resolves to that repository with or without `-R`; the placeholder still resolves to `-R` or the default repository. The `-R` in the criteria stays on `pr view` and `issue view`, which have it. The code then calls the full path only, with no fallback. #35 is rebuilt as `f/35-merge-gate-2` (exam commit, exam-only fix, code), because exam integrity refuses an exam commit after code (LF D103).
**Why.** An exam that rewards a call the real tool rejects proves nothing; the fix makes the fake match the real `gh` and does not loosen any case (no case asserts `-R` on `api`).
**Alternatives.** Keep the fallback (dead code on the real `gh`, and a hidden second read path); pass `GH_REPO` in the environment (the fake ignores it, the same exam change is needed).
**Revert.** Restore the fake's `-R`-only resolution and the fallback call.

## D18 · #42: how Learning Factory's page exams are ported, and which cases stay behind
in force · factory · 2026-11-24 · revertible

**Decision.** The page cases LF removed in #571 (LF D150) are ported to `tests/acceptance/ported/` from LF commit 29e3bf3, changing only paths and names, with these adaptations and omissions:
1. **Harness.** The #51, #68 state and #68 lanes cases run on `tests/acceptance/dashboard/dom_harness_6.js` (the #68 harness plus snapshot and page output). #481 keeps a copy of LF's `dom_harness_481.js`, which serves `snapshot.json` per step. Node is required, never skipped.
2. **Worker ids in the #51 fixtures.** The package reducer hashes a worker id that does not match `[a-z0-9]{1,12}` (D14 amendment 1), LF's did not. The fixture ids `w-mgr`, `w-exam`, `w-impl`, `w-rev` become `wmgr`, `wexam`, `wimpl`, `wrev`; every assertion is unchanged.
3. **Reducer-only and script-only cases are not ported** (#68 state: 9; #68 lanes: 2; #487: 2; #504: 4; #551: 3 redaction cases): the reducer is checked by `ported/test_factory_progress.py` and #22's redaction exam. Deploy cases (#51: 3 nginx cases; #19 and #18: installer, nginx, builder and workflow cases) test LF's deployment, not this page.
4. **Three LF #18 builder cases are added** (LF D150 amendment 1): in-progress claim wins over in-review, fallback to an in-review claim, open-incident throughput. They run `python -m factory_tools.dashboard build --repos --fixtures --now` on LF's `issue18` fixtures copied to `ported/fixtures/issue18/`; assertions unchanged (the package adds `repo` to the claim, which they ignore).
5. **Repository tags.** No case needed adapting: with no `repos` in the snapshot the page falls back to an empty repository prefix, so lane labels stay `#86`. The `factory#7` form stays covered by #6 c3.
Every ported file starts with a "Ported from ... 29e3bf3" comment listing what was left out. The page passed every ported case, so no page fix follows.
**Why.** The live page at factory.shashkist.com had no behaviour exam since LF #571; the cases are ported where the page lives.
**Alternatives.** Port LF's #51 and #68 harnesses as well (three near-identical fake browsers); port the reducer cases a second time (duplicates `ported/test_factory_progress.py`).
**Revert.** Delete the ported page files and `dom_harness_481.js`.

## D19 · #45: how the per-repository dashboard is addressed and split
in force · factory · 2026-11-24 · revertible

**Decision.** The exam of #45 (a683711) fixes these choices:
- The bar is a `<nav>` with one tab per repository in data order; the selected tab carries `aria-current`; each tab shows a count.
- The address is the hash `#/<short name>` (for example `#/factory`); a click sets it, a reload keeps it, back returns. No hash, or an unknown name, opens the host repository, which is the first repository listed in the data (the data names no host; the page already took the first key as host).
- The laptop runner's state (running or idle, pass, last check) sits outside `<main>`, on every view.
- Every block inside `<main>` shows the selected repository only, including throughput (lead time per repository) and the pipeline claim (per repository). The snapshot keeps its top-level `claim` for the older #6 exam and adds the per-repository data next to it.
- #44 (an idle runner still shows live lanes) is not folded in; it stays its own issue.
**Why.** A hash address works on a static page with no server routing; the first-listed host matches today's page; per-repository throughput and claim follow from "every block shows only the selected repository".
**Alternatives.** `?repo=` (a reload refetches the page, no gain); a host flag in `repos.yaml` (a data change for one bit the order already gives); fold #44 (a larger PR for a separate defect).
**Revert.** Drop the bar and the hash routing; the page shows both repositories mixed as before #45.

**D19 amendment 1 (build of #45, 2026-11-24).** Four #6 exam cases assert the mixed page #45 replaces: `test_c3_every_queue_row_shows_its_repository`, `test_c3_every_lane_shows_its_repository`, `test_c3_every_issue_row_in_the_stations_view_shows_its_repository` (each wants both repositories' rows on one page, tagged `factory#7`) and `test_c3_the_two_repository_snapshot_renders_without_errors_or_unsafe_markup` (renders the mixed page). The owner's issue #45 says the per-repository view "replaces today's one page that mixes both repositories (#6)" and drops the prefix inside a view, so these cases are loosened as the issue requires: an exam-only commit rewrites them to the per-repository form (each repository's view shows every one of its own queue rows, lanes and station rows, and none of the other's; every repository's view renders without errors or unsafe markup). No other #6 case changes. Exam integrity refuses an exam commit after code, so the PR is built as `f/45-repo-tabs-2`: the #45 exam a683711, the exam-only rewrite, then the code 6276b51.

**D19 amendment 2 (review round 1 of #51, 2026-11-24).** The SHAs above are from before the rebase: on PR #51 the #45 exam is 8127e13, the #6 rewrite 6cc3c6e, the code c7e31b5. Round 1 (CHANGES at c7e31b5) found two blocking defects the exam missed: a malformed address (`#/%`) throws and leaves a blank page that mixes both repositories, and the Live block keeps the other repository's agent sub-steps, log rows and crew nodes with the prefix dropped. Exam integrity refuses an exam commit after code, so the PR is rebuilt as `f/45-repo-tabs-3`: the two exam commits, an exam-only commit for findings 1-4 (malformed address opens the host; shared live data is split per repository; per-repository counts; a repository entry without `throughput` still renders), then c7e31b5 with the fixes for findings 1-5, 7 and the nits. Two repositories with the same short name under different owners share one address; that limit is accepted for now (each member sees only their own projects), and `#/owner/name` is the fix if it ever happens.

**D19 amendment 3 (merge of #45, 2026-11-25).** The rebuilt PR is #53 (squash c28cd6d): exams ed7a11c, 0852da0, the round-1 exam-only commit f266cf5, then the code e8752dc (cherry-pick of c7e31b5) with the round-1 fixes b4ac815 and 3a82b1f. An agent's earlier sub-step details, which the #45 exam requires in `<main>`, are shown in its lane, because the ported #481 case keeps the agent card unchanged. Review round 2 APPROVE at 3a82b1f; its non-blocking findings (worker matching, crew titles, lane detail length, the view with no snapshot, unused code) are #54. Learning Factory's live page shows #45 only after its pin moves (LF #583).

## D20 · #47: the round-1 fixes are rebuilt on a new branch, and the prune refuses a `--repo` that is not the clone's `origin`
in force · factory · 2026-11-25 · revertible

**Decision.** Review round 1 of PR #55 (CHANGES at 49a57e0) found two blocking defects the exam missed: removing a finished worktree also deletes a worktree or repository nested inside it, and `--repo` is never checked against the clone the command runs in. Exam integrity refuses an exam commit after code, so the PR is rebuilt as `f/47-worktree-prune-2` (as D17, D19): the #47 exam b5289ec, an exam-only commit for the review's exam gaps 8-12 (dry run with a prunable worktree, dry run that would need a fetch, index mtime under dry run, nested worktree or `.git` below the top level is kept with a reason naming it, `--repo` not matching `origin` exits non-zero and removes nothing), then the three code commits with the fixes for findings 1-6. A worktree is kept when another `git worktree list` entry, or any `.git` file or directory below its top level, lies inside it. The skill says to run the prune from each repository's own clone. #55 is closed pointing at the new PR.
**Why.** A nested worktree holds another session's uncommitted work; keeping the parent is the only safe choice without inspecting every level. Refusing a mismatched `--repo` prevents judging a live worktree by another repository's claims.
**Alternatives.** Recurse into nested worktrees and judge each (more code, same outcome for the parent); infer the repository from `origin` and drop `--repo` (breaks the shared CLI shape with `issue_lock`).
**Revert.** Drop the nested check and the `origin` comparison; the PR returns to 49a57e0's behaviour.

**D20 amendment 1 (before the PR, 2026-11-25).** The review of Learning Factory's twin script (LF #586 round 1, LF D153) reproduced data loss on Windows: removing a worktree that holds a directory junction empties the junction's target outside the worktree. Since `f/47-worktree-prune-2` was not pushed yet, its exam gained two more exam-only commits before the code: fe2fa02 (the round-2 gone-folder case no longer requires git to keep an empty `.git/worktrees`, which git deletes with the last entry) and one for links (junction or symlink inside a finished worktree, a link back into its own worktree, a nested bare repository, and a `--repo` mismatch with a prunable worktree present). The code keeps a worktree when any entry below its top level is a link, a `.git` entry or a bare repository, or cannot be read.
