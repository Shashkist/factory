# The methodology

The plugin in `plugin/` is the Factory's working method: one skill that runs a pass, and four role agents that do the work. It is project-neutral. Every project fact comes from two places: the project profile `.factory/factory.yaml` and the project's `CLAUDE.md`.

At the start of a pass the manager skill runs `factory-tools methodology render`. It prints a "This project" section filled from the profile, with a documented default for every key the profile leaves out. Where the skill says "the limit", it means the number printed there.

## The pass

One pass is one run of the manager skill. It works over every repository in the repositories list and resumes from the state file.

1. **Orient.** Work in an isolated worktree. Render the profile, fetch, read the state file, list open issues, pull requests and CI runs, and run `factory-tools status` and `factory-tools stale`. Handle a dependency-update pull request first. Resume the issue the state file names, unless a live session holds its claim. Un-park issues whose owner item is ticked.
2. **Fix the line.** A red CI on the default branch, a failed deploy or a failed smoke run comes first, as an incident issue with top priority.
3. **Plan.** Only when planning is on (the profile has `planning`). If fewer issues are ready than `planning.keep_ready`, slice more from `planning.spec`: one pull request of about 400 lines or less per issue, with testable acceptance criteria and `Depends on #n`. With no `planning`, slice nothing.
4. **Pick and claim.** Take the highest priority ready issue whose dependencies are closed: incident p0, then p0, p1, p2, p3, oldest first. Claim it with `factory-tools claim`, branch `f/<n>-<slug>`, and commit the state file. Keep up to `limits.parallel_issues` issues in flight, and claim the next independent one while another waits.
5. **Decide.** For every open question: the spec says, then the decisions file says, then research with the `researcher`, then the simplest option that keeps the guardrails. Write the decision down with how to revert it. Only an owner-only blocker (a secret, DNS, money) goes to the owner file. Then pick another issue.
6. **Exam, build, check.** The `exam-writer` commits the acceptance tests first. The `implementer` makes them pass in a worktree. Open a pull request, wait for CI (at most `limits.ci_rounds` rounds), then the `reviewer` reviews it in fresh context (at most `limits.review_rounds` rounds). The manager posts the reviewer's verdict as `Review round <k>: APPROVE|CHANGES at <head sha>`.
7. **Ship.** Check what you are shipping, run `factory-tools merge-gate`, and squash-merge only when it prints `MERGE`. Shipped means the deploy and the `smoke` check when the project has them, otherwise green CI on the default branch.
8. **Close.** Comment with the evidence, close the issue, flip its label to done, release the claim, update the state file.
9. **Loop.** Go back to fix the line until about 90 minutes of work or 3 merged pull requests. Then stop cleanly, so the state file says where the next session continues.

## Profile keys at a glance

| Key | What it holds | Default when absent |
| --- | --- | --- |
| `methodology` | the methodology version (required) | none |
| `verify` | per area, the commands to run and their `cwd` | use the commands in `CLAUDE.md` |
| `exam` | globs of the acceptance tests | `**/tests/acceptance/**` |
| `protected_paths` | globs the implementer must not edit | none |
| `required_checks` | CI checks that must be green | none |
| `labels` | the Factory's label names mapped to the project's | the Factory's own names |
| `limits` | `limits.ci_rounds` (5), `limits.review_rounds` (2), `limits.parallel_issues` (3) | those numbers |
| `smoke` | a `run` command with `cwd`, or a `workflow` | none configured |
| `research_hints` | products and sources to look at first | none |
| `areas` | area name to path globs, to pick the `verify` group | none |
| `planning` | `planning.spec` (required when set) and `planning.keep_ready` (5) | planning off |
| `owner_files` | `owner_files.decisions` and `owner_files.owner` | `.factory/DECISIONS.md`, `.factory/OWNER.md` |

## factory (skill)

The manager. It runs the pass above, reports live progress with `factory-tools progress add`, dispatches the four agents, and decides, merges and closes. It never blocks: it decides, records the decision and moves on.

Profile keys it reads:
- `methodology`, through the render step, which prints the version.
- `verify`, `exam`, `limits`, `planning`, `labels`, `research_hints`, `smoke`, `protected_paths`, `required_checks` and `owner_files`, all through the render step.
- `limits.ci_rounds`, `limits.review_rounds` and `limits.parallel_issues` set the loop bounds.
- `planning.spec` and `planning.keep_ready` drive the plan step.
- `owner_files.decisions` and `owner_files.owner` name the decisions file and the owner file.

CLAUDE.md sections it reads: the project rules and what is off limits, the name of the state file, and the verification commands when `verify` is empty.

## exam-writer

Writes the acceptance tests for one issue from the spec and the issue only, before any code exists. It checks observable behaviour, gives every acceptance criterion at least one test, and confirms the tests fail for the right reason before it commits. It lints each exam file and never weakens an existing exam.

Profile keys it reads:
- `planning` and `planning.spec`, for the spec path. With no `planning` it uses the spec sections the issue names.
- `exam`, for where the tests go.
- `verify`, for the lint commands CI runs.

CLAUDE.md sections it reads: the test framework and file naming, and the marker or tag for tests that need infrastructure the session lacks.

## implementer

Makes the exam pass with the minimum code, in a worktree. It follows red, green, refactor for logic the exam does not cover, searches for existing code before writing a helper, and commits in small steps with the issue number.

Profile keys it reads:
- `exam`, whose paths it never edits.
- `protected_paths`, which it does not edit unless the issue names them.
- `verify` and `areas`, to run the verify group of each area its changed paths fall in; with no match it runs every group.

CLAUDE.md sections it reads: where unit tests live, what counts as exam, the verification commands, and the guardrails.

## reviewer

Reviews one pull request in fresh context and tries to refute it. It cannot edit files. The order is guardrails, correctness against the acceptance criteria and the spec, the exam, then simplicity. The output is `APPROVE` or `CHANGES` with numbered findings that cite file and line.

Profile keys it reads:
- `protected_paths`, to name each protected file the diff touches and say whether the issue allows it.
- `required_checks`, which must be green on the pull request head.
- `exam`, because any change to an exam path is a finding by itself.
- `planning` and `planning.spec`, for the spec path.
- `owner_files.decisions`, for the decisions file.

CLAUDE.md sections it reads: every rule marked as never to be broken (isolation, shared infrastructure, secrets, personal data).

## researcher

Answers one design question with evidence and a recommendation. It first checks whether the spec or the decisions file already answers it. It never invents a source; without evidence it says so.

Profile keys it reads:
- `research_hints`, the products to look at first.
- `planning` and `planning.spec`, for the spec path.
- `owner_files.decisions`, for the decisions file.

CLAUDE.md sections it reads: the guardrails, for the "risks for our guardrails" part of its answer.
