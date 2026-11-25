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

## D21 · #54: a crew title moves to another repository only when the short name stands right before the reference
in force · factory · 2026-11-25 · revertible

**Decision.** Review round 1 of PR #58 (CHANGES at 5847b49) showed that criterion 2 read literally ("a title that names a repository short name as a whole word") moves host crew nodes into the factory view whenever a Learning Factory title mentions the factory ("Implement #583 factory package pin", "Fix #26 Factory dashboard incident", "Learning-factory #4"), a mixed view as common as the one it fixes. A crew title is placed in another repository's view only when that repository's short name stands directly before the reference, optionally with `PR` or `issue` between: `factory #53`, `factory PR #53`, `factory issue #53` (case-insensitive, whole word on the left). An empty short name never matches. As in D20, exam integrity refuses an exam commit after code, so the PR is rebuilt as `f/54-dashboard-repo-followups-2`: the #54 exam, an exam-only commit with the new cases (host titles that mention the factory elsewhere stay in the host view; `Learning-factory #4` stays in the host view; an empty short name in live data does not capture titles), then the code. The unrepositoried workers row (round-1 finding 2) goes to a follow-up issue.
**Why.** The spec allows no mixed view; the adjacent form is how the factory's own titles name a second repository's item, and it keeps every exam case of #54 as strict as written ("Review round 2 of factory PR #53" still moves).
**Alternatives.** Whole word anywhere in the title (the PR's first version; misplaces host work about the factory); require the `owner/name#n` prefix only (breaks the #54 criterion 2 case).
**Revert.** Return `crewRef` to the whole-word match and drop the new exam cases.

## D22 · #5: reusable CI workflows ship in four slices, and the judge code is fetched at `job.workflow_sha`
in force · factory · 2026-11-25 · revertible

**Decision.** #5 is sliced into four issues of one PR each: (A) #5, the reusable `exam-integrity.yml` and `junit-gate.yml` (`on: workflow_call`); (B) #61, this repository's `ci.yml` calls them; (C) #62, the reusable incident workflow; (D) #63, `docs/ci.md` and the tag `v0.1.0`. A reusable workflow fetches the judge code (`factory-tools`) from `job.workflow_repository` at `job.workflow_sha`, the GitHub contexts for the workflow that defines the running job (GitHub changelog, August 2026), so a caller pinned to a tag or SHA runs exactly that commit's judge and never `main` or its own PR's code. Dogfooding (B) calls the workflows by a full SHA of `main`, which the #1 pinning case requires and Dependabot keeps current; on a PR this runs main's judge, the same "base branch copy decides" property `ci.yml` has today.
**Why.** One PR for all of #5 is well over the ~400-line limit, and a PR cannot call a reusable workflow that is not on `main` yet, so A must land before B. `job.workflow_sha` needs no extra input from the caller and no `id-token: write`; a caller-supplied ref input could drift from the pinned `uses:` ref.
**Alternatives.** A required `factory-ref` input the caller sets to its pin (can disagree with the `uses:` ref); the OIDC `job_workflow_sha` claim (needs `id-token: write` in every client); a local `uses: ./.github/workflows/...` for dogfooding (runs the PR's own copy of the judge).
**Revert.** Merge the four issues back into #5, and replace `job.workflow_sha` with a `factory-ref` input.

## D23 · #5 review round 1: the JUnit gate runs in its own job, exam paths become #65, and the PR is rebuilt
in force · factory · 2026-11-25 · revertible

**Decision.** Review round 1 of PR #64 (CHANGES at 6ebc057) found that PR code run by the caller's exam command can replace the JUnit judge or its interpreter before the gate step, that exam integrity's extra `git fetch` fails on private callers, that the exam misses several weakened versions, and that the issue's exam-paths input is missing. (1) `junit-gate.yml` becomes two jobs: `exam` (caller checkout, the exam command, report uploaded as an artifact with a per-call name) and `gate` (`needs: exam`, `if: ${{ !cancelled() }}`; checks out only the judge at `job.workflow_sha`, downloads the report, runs `/usr/bin/python3 -I`). (2) Exam integrity verifies `origin/<base>` exists (full-history checkout) instead of fetching, and refuses a non-PR event loudly. (3) The exam-paths input and the judge change it needs are split into #65; the workflow header states the top-level `tests/` limit until then. (4) As in D17, D19 and D20, exam integrity refuses an exam commit after code, so the PR is rebuilt as `f/5-reusable-exam-workflows-2`: the #5 exam (a978b10), an exam-only commit for the round-1 exam gaps, then the code. `timeout-minutes` becomes an input.
**Residual risk (accepted).** PR code still writes the report, so it can forge the report's content; no design closes that while the report comes from a process running PR code. The split guarantees that the pinned judge, not PR code, reads it.
**Why.** A judge that shares a job with the code it judges can be rewritten by it (files, `$GITHUB_PATH`, `$GITHUB_ENV`); a separate job starts clean. Most clients are private repositories.
**Alternatives.** Check out the judge after the tests in the same job (PR code can still plant `.git` hooks and `$GITHUB_ENV` lines); add exam paths in this PR (a judge change on top of two workflows, over the size limit).
**Revert.** Fold the two jobs back into one and restore the fetch; close #65 into #5.

## D24 · #5 review round 2: the manager's fixes close the round, each verified narrowly; exam cases for them go to #67
in force · factory · 2026-11-25 · revertible

**Decision.** Review round 2 of PR #66 (CHANGES at 76b7366) asked for one line (`gate` job `if: ${{ always() }}`) and two nits. The manager fixed them on the branch (Learning Factory D145), and each fresh verifier found one more small hole in the same job: an empty download name fetches every artifact of the run (fixed with a `'no-exam-report'` fallback, dcc725b) and the gate ignored `needs.exam.result` (fixed: the gate is red unless the exam job succeeded, e2ff05f). Round 2 closes after a verifier that checks only the e2ff05f diff and the whole `gate` job once more; any further item becomes a follow-up issue, not another round. The exam cases for all round-2 hardening (judge last and `/usr/bin/python3 -I`, `always()`, non-empty name, exam result, autoload default) are #67, because exam integrity refuses an exam commit after code on this branch (D23).
**Why.** The fixes are one to six lines each and only tighten the gate; a third rebuild of the branch for exam-before-code costs a pass and protects nothing that #67 does not.
**Alternatives.** Rebuild as `-3` with the new exam cases first (another full CI and review cycle); leave the holes for #67 (ships a gate that can pass a red exam).
**Revert.** Reopen the review with a round 3 on PR #66, or move #67's cases into a rebuilt branch.

## D25 · #61: CI calls the reusable workflows by a full SHA of `main`, the inline jobs and bootstrap go, and the gates accept `<caller> / exam-integrity`
in force · factory · 2026-11-25 · revertible

**Decision.** (1) `ci.yml` keeps its `checks` job and replaces the inline `acceptance` and `exam-integrity` jobs with calls to `Shashkist/factory/.github/workflows/junit-gate.yml@<sha>` (job `acceptance`, the same exam command and runtime defences as today) and `.../exam-integrity.yml@<sha>` (job `exam-integrity`, `if: github.event_name == 'pull_request'`), `<sha>` a full commit of `main` (34f9188 to start). No inline fallback stays: the pinned judge is main's commit, which is the stronger form of today's "the base branch copy decides", and bootstrap mode is no longer needed because `main` already has the judge. (2) The #1 exam cases that read `ci.yml` are corrected by the exam-writer in an exam-only commit before any code, case by case: `test_ci_workflow_runs_all_checks` keeps ruff, mypy, pytest, `tests/unit` and `tests/acceptance`, `--junitxml`, and reads `junit_gate`/`exam_integrity` as calls to `junit-gate.yml@<40 hex>` and `exam-integrity.yml@<40 hex>`; `test_ci_workflow_exam_integrity_runs_on_pull_requests` reads the calling job's `pull_request` condition; `test_bootstrap_mode_is_a_fallback_documented_in_a_comment` (loosened, named) is replaced by "the judge is not run from the PR's tree: both calls are pinned to a full SHA and `ci.yml` runs no `exam_integrity.py`/`junit_gate.py` from the checkout". (3) Check names become `acceptance / exam`, `acceptance / gate` and `exam-integrity / exam-integrity`. The merge gate (Learning Factory #605, which ships first, and this repository's `factory_tools.pipeline.merge_gate` copy in this PR) counts a check named `exam-integrity` or ending in ` / exam-integrity` as exam integrity, with the same SUCCESS rule. Branch protection is off on `main`, so nothing else names the checks.
**Why.** Issue #61 criteria 2 and 3; a reusable-workflow check is always named `<caller job> / <called job>`, so no caller name keeps the bare `exam-integrity`.
**Alternatives.** Keep the inline jobs as a fallback (two judges to keep in step); a local `uses: ./...` call (runs the PR's own judge, D22); require the exact new name only (breaks every caller that names its job differently).
**Revert.** Restore the inline jobs from 34f9188's `ci.yml` and the #1 cases from before the exam commit; the gates' suffix match can stay (harmless).

## D26 · #61 ships as three PRs, because one PR may not change the exam and `ci.yml` together
in force · factory · 2026-11-25 · revertible

**Decision.** Amends D25 point 2. Exam integrity refuses a PR that changes the exam together with the CI surface (`ci.yml`), and the #1 cases pin today's inline `ci.yml`, so #61 cannot ship as one PR. It ships as three, each `Part of #61` except the last: (A) exam only: the three #1 cases named in D25 accept either today's inline form or the SHA-pinned reusable calls (a transitional loosening for the window between A and C, named here); (B) code and CI only: `ci.yml` calls the reusable workflows, the merge gate counts `<caller> / exam-integrity` (no exam change, so no exam-integrity conflict); (C) exam only, `Closes #61`: the #61 exam (`test_issue_61_dogfood_ci.py`) and the #1 cases in their final D25 form, which only the reusable form passes. The first build (`f/61-dogfood-reusable-ci`, exam 929c184 and code ff57dac/a2cff55) is the source: B and C reuse its commits.
**Why.** The rule is right: a PR must not move the exam and the CI that runs it at the same time. Splitting keeps every PR within it, and after C the exam is as strict as D25 says.
**Alternatives.** Run with `--bootstrap` (not possible: the reusable judge has no bypass, and it would weaken the rule); keep the old strings in `ci.yml` comments so the old cases pass (games the exam); drop the three #1 cases in A (looser than accept-either for the window).
**Revert.** Merge C's cases back into A's form, or restore 34f9188's `ci.yml` and #1 cases.

## D27 · #65 ships as two PRs: the judge change first, then its exam unchanged
in force · factory · 2026-11-25 · revertible

**Finding.** #65 changes `src/factory_tools/ci/exam_integrity.py`, which D3 makes CI surface, and its exam (`tests/acceptance/test_issue_65_exam_path_inputs.py`, written first as ff7fa47 on `f/65-exam-path-inputs`, 10 cases red against main) cannot ride in the same PR: `exam_integrity origin/main HEAD` says `PR changes the exam together with the CI surface`. Unlike D9 the code cannot move out of `ci/`: the change is the judge itself. An exam-only PR first cannot merge either: its new cases are red until the judge changes, and the JUnit gate refuses skips.
**Decision.** Keep the #1 rule as strict as it is. (A) PR `f/65-judge-globs`, `Part of #65`: the code commit only (judge options `--exam-paths`/`--ci-paths`, `exam-integrity.yml` inputs `exam-paths`/`ci-paths` through `env:`, docs, unit cases). The exam stays the one written first: the reviewer runs ff7fa47's exam file against A's head and the PR body shows the result. (B) PR `f/65-exam-path-inputs`, `Closes #65`: the exam commit ff7fa47 unchanged, rebased onto main after A. Exam-first holds in authorship (the exam was committed before the code and the code was built against it); only the merge order is code first.
**Alternatives.** Narrow the CI surface to exclude `exam_integrity.py` (loosens the #1 rule); `--bootstrap` (the reusable judge has no bypass); mark the new cases xfail until A (the gate refuses skipped and xfail is a weaker exam).
**Revert.** Revert A's squash commit; B is exam only.

## D28 · #76: the merge gate requires the exam gate check to succeed; `--exam-gate` names it
in force · factory · 2026-11-25 · revertible

**Decision.** The merge gate holds unless the exam gate check concluded SUCCESS. Its name is `acceptance / gate` by default (the `junit-gate.yml` call in `ci.yml`, D25) and is set with a new CLI option `--exam-gate "<name>"`, next to `--author` and `--repo`; the match is exact. SKIPPED, NEUTRAL, any other conclusion or a missing check holds with a `HOLD:` line naming the check. Every other check keeps today's rule (SUCCESS, NEUTRAL and SKIPPED pass) and exam integrity keeps its own. The #61 case `test_exam_integrity_call_does_not_steer_the_checked_range` is tightened: this repository's `exam-integrity` call has an empty `with:` block, so a `ci.yml`-only change can no longer add `exam-paths`/`ci-paths` (criterion 3; stricter, nothing loosened). The #76 exam harness adds a SUCCESS `acceptance / gate` to every non-empty #35 world that lacks one, so the #35 and ported cases keep testing their own rules unchanged.
**Why.** #76 criteria 1 to 3: a PR that skips its own `acceptance` job skips both the exam and the JUnit gate, and the exam that pins `ci.yml` runs inside that skipped job. The gate runs outside the PR, so it is the place to refuse it. The check *name* is not outside the PR's control: a `ci.yml` change can add a job named `acceptance / gate` that always succeeds, or a commit status of that name; that gap (also for `exam-integrity`) is #80, which ties the result to the pinned reusable workflow. An option, not a profile value, because the gate already takes its configuration on the command line.
**Alternatives.** Require every check to be SUCCESS (breaks path-scoped jobs a client skips by design, Learning Factory D98); a suffix match (`* / gate`) (a lookalike job could stand in for it); a profile field (no profile reaches the gate today).
**Revert.** Drop the exam-gate rule and the option from `merge_gate.py`; the #61 case may stay strict.

## D29 · #80: the gate binds the exam gate and exam-integrity checks to the pinned reusable workflow by the run, the head's `ci.yml` and `main`
in force · factory · 2026-11-25 · revertible

**Finding.** A workflow run's `referenced_workflows` lists every reusable workflow its file calls, also from a job that was skipped (main CI run 45624202389 lists `exam-integrity.yml@34f9188` while its `exam-integrity` job is skipped). A run-level check alone therefore does not stop spoof 1 of #80 (caller renamed to `acceptance-real` with `if: false`, a plain job named `acceptance / gate`). No jobs or check-run API field names the called workflow of a job.
**Decision.** For each of the two protected checks (the exam gate, default `acceptance / gate`, option `--exam-gate`; exam integrity, a check named `exam-integrity` or ending in ` / exam-integrity`), the gate counts a SUCCESS only when all hold, otherwise `HOLD:` with a line naming the check and the failed condition:
1. it is a check run of the status rollup (`__typename` `CheckRun`), never a commit status (`StatusContext`);
2. its details URL names a workflow run of the PR's repository (`/actions/runs/<id>/job/<id>`); that run (`gh api repos/<repo>/actions/runs/<id>`) has `path` `.github/workflows/ci.yml` and `head_sha` equal to the PR head;
3. the run's `referenced_workflows` has `<workflows repo>/.github/workflows/junit-gate.yml@<sha>` (respectively `exam-integrity.yml`) whose `sha` is on the workflows repository's `main` (`gh api repos/<workflows repo>/compare/main...<sha>` says `behind` or `identical`); the workflows repository is `Shashkist/factory` by default, option `--workflows-repo`;
4. the head's `ci.yml` (`gh api repos/<repo>/contents/.github/workflows/ci.yml?ref=<head>`) has exactly one job whose shown name (`name:` or the job id) is the part of the check name before ` / `, that job's `uses:` is exactly the referenced `path@sha` of point 3, and no job of the file is shown under the full check name.
**Why.** #80 criteria 1 to 3. Points 2 and 3 tie the check to a real run of the pinned judge at a reviewed commit; point 4 ties the job to the caller, which the run-level data cannot. The file read is the head's own, which is what ran.
**Out of scope.** A caller that keeps the pinned `uses:` but passes a `test-command` that writes a fake JUnit file (the judge's inputs, tracked by #10); matrix names.
**Alternatives.** Run-level `referenced_workflows` only (fails spoof 1, see Finding); hold every PR that changes `ci.yml` (blocks every pin move); a required-workflow ruleset on the repository (owner setting, and the gate must work without it).
**Revert.** Drop the four conditions from `merge_gate.py`; D28's exact-name rule stays.

**Amendment 1 (2026-11-25, review round 1 of PR #83).** GitHub evaluates expressions in `jobs.<id>.name`, and a job that calls a local workflow shows as `<caller> / <called job>`, so a shown name in the file is not always the name of the check. Point 4 also holds when (a) any job of the head's `ci.yml` has a `name:` containing `${{`, or (b) any job's shown name contains ` / `; and when (c) a job's `uses:` is not a string (a HOLD line, never a traceback). Today neither repository's `ci.yml` has such a name, so no real PR is held. The `ci.yml` read takes only the raw form (no base64 branch) and refuses duplicate YAML keys; the PR's repository comes from `pr["url"]`; the HOLD line names the first failed condition in the order 1 to 4, "on main" being part of 3. Delivered by a rebuilt branch `f/80-gate-pinned-workflows-2` (D103 of Learning Factory: exam commits first, then code), which replaces PR #83.

**Amendment 2 (2026-11-25, review round 2 of PR #84; manager decision after two rounds).** (a) Point 4 also holds when a job's shown name has leading, trailing or repeated white space (GitHub may show it trimmed, as another job's name); unit cases in `tests/unit/test_merge_gate.py` (commit 05d671b), no exam edit, as in Learning Factory D145. (b) Point 2 is tied by the details URL only: a PR that adds a job creating a check run through the Checks API with a details URL into the same run can pass, if GitHub keeps a caller-supplied `details_url` (not confirmed). The fix, reading `actions/jobs/<id>` and requiring the run, head and name to match, needs an exam case first, so it goes to #86 (p1, next in this repository). #84 merges without it because it is strictly stronger than `main` (which checks the name only), the route needs a visible Checks API job in the PR's own `ci.yml` diff, and a third rebuilt branch costs more than it finds now. (c) The "PR's repository from `pr["url"]`" part of amendment 1 is not in #84; it moved to #85 (two ported fixtures name another repository). (d) Round 2 nit 3 (the exam pins the HOLD order and the expression cases by the job id) goes to #86 with (b).
**Revert of amendment 2.** Drop the white-space hold; (b) to (d) are scope notes and end when #85 and #86 close.

**Amendment 3 (#86, closes 2(b) and 2(d)).** Point 2 also holds unless the Actions job named by the details URL (`gh api repos/<repo>/actions/jobs/<job id>`, read once per job id, cached like the run reads; without `--repo` under both the placeholder and the URL's repository) has an integer `run_id` equal to the URL's run, a `head_sha` equal to the PR head and a `name` equal to the check name. An unreadable job (404, error, missing or mistyped fields) holds. The job is checked after points 2 to 4, so the HOLD line still names the first failed condition in the order of amendment 1. This stops a check run created through the Checks API whose details URL points into a real run of the pinned caller. Criterion 5 of #86: whether GitHub overrides a caller-supplied `details_url` for check runs created with `GITHUB_TOKEN` is not confirmed; the job read stays as defence in depth either way.
Review round 1 of PR #88 added: the job must also have `status` `completed` and `conclusion` `success`, otherwise a forged SUCCESS check pointing at the real but failed (or skipped, or unfinished) job would pass. A missing `run_id` and a missing `name` are separate HOLD lines.
**Revert of amendment 3.** Drop `job_reason` and its call from `merge_gate.py`.

## D30 · #63: `v0.1.0` is today's green `main` (95753bb), and its existence is checked at close, not in the exam
in force · factory · 2026-11-25 · revertible

**Decision.** The tag `v0.1.0` points at 95753bb (`main` with #61, #62, #65 and #76 merged; main CI 45624202389 green). It is created at the start of #63, so `docs/ci.md` can pin every example to `95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0`. The exam checks criterion 1 offline (every input each reusable workflow declares under `on.workflow_call.inputs` is named in its section of `docs/ci.md`, every `uses: Shashkist/factory/.github/workflows/...` line in the document is pinned by a 40-hex SHA with a `# v<semver>` comment); criterion 2 (the tag exists and its commit's CI is green) is checked with `gh` by the manager and cited in the closing comment, because the exam runs offline and a CI checkout has no tags.
**Why.** #63 criteria 1 and 2; an exam that calls the network would be flaky and could not run in a cloud session.
**Alternatives.** Tag the merge commit of the docs PR (the docs could not name its SHA before it exists); a release workflow that tags (more surface than one tag needs).
**Revert.** `git push origin :refs/tags/v0.1.0` and re-tag; the document's pins follow the tag.
