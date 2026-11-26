# CI: the reusable workflows

The Factory publishes three reusable GitHub Actions workflows. A client repository calls them from its own workflows to get the same checks the Factory runs on itself:

- `exam-integrity.yml`: the exam comes first; no commit of a pull request may change the exam together with the code, and no pull request may change the exam and the CI that judges it.
- `junit-gate.yml`: runs the exam and fails on a missing, empty, skipped, failed or errored report.
- `incident.yml`: opens or updates an "Incident: <workflow> failed" issue when a workflow goes red.

## Pin by full SHA

Call every workflow by the full 40-character commit SHA of a release, with the release tag in a comment:

```yaml
uses: Shashkist/factory/.github/workflows/junit-gate.yml@95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0
```

Never use a branch or a tag as the ref. To move to a newer release, change the SHA and the comment in a pull request.

Why: a pull request must never run its own judge ([D25](factory/DECISIONS.md)). The pin stops the PR's own copy of the judge from running: the workflows check out their tools at the pinned commit, never from the caller's tree.

The pin does not protect itself. It lives in the caller's workflow file, which a PR can edit: repoint the SHA, add `if: false`, rename the job. The guard is the merge gate. At `v0.1.0` it requires the exam gate check (`acceptance / gate`, [D28](factory/DECISIONS.md)) and the exam integrity check to succeed, but it matches both by name only: a PR that edits its own workflow file can still stand in a lookalike job of the same name, or a commit status with that name, and pass. Issue #80 (open, not in `v0.1.0`) binds both checks to the pinned reusable workflow at a commit of this repository's `main`. Until a release has it, review every pull request that changes a workflow file by hand.

This guide and the examples below document release `v0.1.0`, commit `95753bb72e9c5d885376311efea91db7272f9d16`. The workflow files at that tag are the same as on `main` at the time of writing.

## Check names

A called workflow shows up in the caller as `<caller job> / <called job>`. The merge gate reads these names ([D25](factory/DECISIONS.md), [D28](factory/DECISIONS.md)), so name the caller job and keep it stable. The names are given in each section. A caller job skipped by its own `if:` shows as the bare caller job name (for example `exam-integrity`, skipped on push), not `<caller> / <called>`.

A caller-level `if:` that skips the whole call also skips the gate, so the gate's check never runs. A skipped required check passes, because GitHub counts it as passing, so a caller must keep any `if:` off the call it relies on.

The merge gate's default exam gate is `acceptance / gate`. `factory-tools merge-gate --exam-gate "<job> / gate"` names another.

## `exam-integrity.yml`

**What it does.** It checks the commits of a pull request (`origin/<base>..<head>`) against one rule: the exam is written first and never changes together with the code or the CI that judges it. The judge is checked out from the Factory at the pinned commit.

It fails when:

- the range contains a merge commit (rebase onto the base branch);
- one commit changes the exam and code together;
- the exam changes in a commit after the first commit that changed code (exam first);
- the PR as a whole changes the exam and the CI surface. This is judged over all changed files of the PR, not per commit: a PR with one exam-only commit and one `ci.yml`-only commit fails;
- it is not run on a `pull_request` event (no head SHA or base ref), or `origin/<base>` is missing from the checkout.

What counts as what:

- Exam, by default: every file under the top-level `tests/` except `tests/unit/`. `conftest.py`, `pytest.ini`, `.pytest.ini`, `tox.ini` and `setup.cfg` always count as exam, also when `exam-paths` is set, except inside the top-level `tests/unit/` (by default) or inside any `tests/unit/` directory (when `exam-paths` is set).
- `*.pth` files, `sitecustomize`/`usercustomize` modules (`.py`, `.pyw`, `.pyc`, `.pyd`, `.so`, with an optional ABI tag) and anything under a `sitecustomize/` or `usercustomize/` directory, at any path, always count as exam, also inside `tests/unit/` and when `exam-paths` is set: Python runs them at interpreter start, before the exam.
- Code: every path that is not exam. By default the top-level `tests/` is never code. With `exam-paths` set, that exemption goes: a file under `tests/` that the globs do not match is code.
- CI surface, by default: `src/factory_tools/ci/` and `.github/workflows/ci.yml` (the Factory's own layout). `ci-paths` replaces it.

A client with another layout sets `exam-paths` and `ci-paths`.

**Inputs**

| Name | Required | Default | Meaning |
| --- | --- | --- | --- |
| `base-ref` | no | `""` | Base branch to compare against. Empty means the base branch of the calling pull request. |
| `exam-paths` | no | `""` | Globs, separated by whitespace or newlines, naming the exam files, for example `labs/*/tests/acceptance/**`. Empty means the default rule. Globs are fnmatch style against the repo-relative path; `*` and `**` match across `/`. |
| `ci-paths` | no | `""` | Globs naming the CI surface that must not change together with the exam. Empty means the default. |

No secrets.

**Permissions the caller must grant.** `contents: read` (the workflow declares `contents`, nothing else).

**Example** (a `pull_request` workflow):

```yaml
name: CI
on:
  pull_request:

permissions:
  contents: read

jobs:
  exam-integrity:
    uses: Shashkist/factory/.github/workflows/exam-integrity.yml@95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0
    with:
      exam-paths: "labs/*/tests/acceptance/**"
      ci-paths: |
        .github/workflows/ci.yml
        ci/**
```

**Check name.** `exam-integrity / exam-integrity` (when the caller job is called `exam-integrity`).

## `junit-gate.yml`

**What it does.** Two jobs. `exam` checks out the caller, runs `test-command` and uploads the JUnit report. `gate` never checks out the caller: it downloads the report and fails when it is missing, empty, or contains a skipped, failed or errored test, or when the `exam` job did not end with `success` (a passing report from a command that then exited non-zero is not a pass). `gate` runs even when `exam` is cancelled, because a skipped required check counts as passed.

The exam job sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` by default, so a code commit cannot auto-register an installed pytest plugin that rewrites results. A caller whose exam needs an installed plugin either loads it explicitly (`pytest -p <plugin>`) or passes `disable-pytest-plugin-autoload: false` and accepts the risk.

**Inputs**

| Name | Required | Default | Meaning |
| --- | --- | --- | --- |
| `test-command` | yes | none | Shell command that runs the exam and writes the JUnit report to `junit-file`. |
| `junit-file` | no | `acceptance.xml` | Path of the JUnit XML report, relative to the repository root. |
| `timeout-minutes` | no | `10` | Time limit of the `exam` job, in minutes. |
| `disable-pytest-plugin-autoload` | no | `true` | Set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` in the exam job. |

No secrets.

**Permissions the caller must grant.** `contents: read` (the workflow declares `contents`, nothing else).

**Example:**

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  acceptance:
    uses: Shashkist/factory/.github/workflows/junit-gate.yml@95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0
    with:
      test-command: uv run pytest tests/acceptance -q --junitxml=acceptance.xml
```

**Check names.** `acceptance / exam` and `acceptance / gate` (when the caller job is called `acceptance`). The merge gate must require `acceptance / gate`; it is the job that judges the report.

## `incident.yml`

**What it does.** Opens the issue "Incident: <workflow> failed" in the calling repository, or comments on it if it is already open. It acts only when `conclusion` is `failure`, `timed_out` or `startup_failure`; otherwise the job is skipped. The caller decides which runs count (branch, event). The caller's `GITHUB_TOKEN` is used and every `gh` call targets the caller's repository, never the Factory. If fetching the tool fails, the job still files a plain issue.

The labels `type:incident`, `priority:p0` and `status:ready` must exist in the calling repository. If one is missing, `gh issue create` fails and the job goes red.

**Inputs**

| Name | Required | Default | Meaning |
| --- | --- | --- | --- |
| `workflow-name` | yes | none | Name of the CI workflow that was watched. It becomes the issue title, "Incident: <name> failed". |
| `run-url` | yes | none | URL of the failed run, written into the issue or comment. |
| `conclusion` | yes | none | Conclusion of the watched run. Only `failure`, `timed_out` and `startup_failure` raise an incident. |

No secrets.

**Permissions the caller must grant.** `contents: read` and `issues: write` on the calling job (the workflow declares both; `issues: write` is needed because the issue is opened in the caller).

**Example** (a workflow that reacts to a finished CI run on `main`):

```yaml
name: Incident
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

jobs:
  incident:
    if: github.event.workflow_run.head_branch == 'main' && github.event.workflow_run.event == 'push'
    permissions:
      contents: read
      issues: write
    uses: Shashkist/factory/.github/workflows/incident.yml@95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0
    with:
      workflow-name: ${{ github.event.workflow_run.name }}
      run-url: ${{ github.event.workflow_run.html_url }}
      conclusion: ${{ github.event.workflow_run.conclusion }}
```

**Check name.** `incident / incident` (when the caller job is called `incident`). It is skipped, not failed, when the watched run succeeded.
