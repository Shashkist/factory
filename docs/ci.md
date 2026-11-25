# CI: the reusable workflows

The Factory publishes three reusable GitHub Actions workflows. A client repository calls them from its own workflows to get the same checks the Factory runs on itself:

- `exam-integrity.yml`: no commit of a pull request may change the exam together with the code or CI that judges it.
- `junit-gate.yml`: runs the exam and fails on a missing, empty, skipped, failed or errored report.
- `incident.yml`: opens or updates an "Incident: <workflow> failed" issue when a workflow goes red.

## Pin by full SHA

Call every workflow by the full 40-character commit SHA of a release, with the release tag in a comment:

```yaml
uses: Shashkist/factory/.github/workflows/junit-gate.yml@95753bb72e9c5d885376311efea91db7272f9d16 # v0.1.0
```

Never use a branch or a tag as the ref. To move to a newer release, change the SHA and the comment in a pull request.

Why: a pull request must never run its own judge (D25). With a full SHA, a PR runs the judge as it was on `main` when the pin was set, so a PR cannot weaken the check it is judged by. The workflows also check out their tools at that same pinned commit, never from the caller's tree.

This guide and the examples below document release `v0.1.0`, commit `95753bb72e9c5d885376311efea91db7272f9d16`. The workflow files at that tag are the same as on `main` at the time of writing.

## Check names

A called workflow shows up in the caller as `<caller job> / <called job>`. The merge gate reads these names (D25, D28), so name the caller job and keep it stable. The names are given in each section.

## `exam-integrity.yml`

**What it does.** For every commit of a pull request, it checks that the commit does not change exam files together with code or the CI surface. The judge is checked out from the Factory at the pinned commit. It fails when a commit mixes exam and code, and when it is not run on a `pull_request` event (no head SHA or base ref), or when `origin/<base>` is missing from the checkout.

By default the exam is the caller's top-level `tests/` except `tests/unit`, and the CI surface is the Factory's own `src/factory_tools/ci/` and `.github/workflows/ci.yml`. A client with another layout sets `exam-paths` and `ci-paths`.

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
