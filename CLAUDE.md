# Factory: working in this repository

This repository is the **Factory**: a software factory that takes GitHub issues on connected repositories to merged, verified pull requests, with all LLM usage and compute on the members' own machines. What to build: `docs/spec/2026-11-20-factory-product-design.md` (the spec).

**How it is built.** Until v0 of the spec is done, this repository is built by the existing Learning Factory manager, which runs from `Shashkist/Learning_factory` (its `factory` skill, agents and scripts) and takes issues from here as a second repository. Its rules apply here as written below. After v0, the methodology in this repository runs itself and Learning Factory becomes client #1.

Read first:
- `docs/spec/2026-11-20-factory-product-design.md`: the spec. Section 11 is the migration plan (v0 to v3), section 17 the owner's start-of-development decisions.
- `docs/factory/DECISIONS.md`: every decision and assumption made while building this repository. **When two documents disagree, this one settles it.**
- `docs/factory/OWNER.md`: what is waiting for the owner.

## Rules that are never broken

1. **The owner's other services come first.** The production server also runs other people's and the owner's services. Never restart Docker, never edit another site's nginx block, never touch containers whose name does not start with `lf-`, `lab-` or `factory-`. Server changes happen only through reviewed GitHub workflows in the `production` environment and idempotent, validated scripts (`nginx -t` before reload; backup, then restore on failure; `systemctl reload docker`, never restart).
2. **Secrets are installed by the owner, never by an agent.** Agents wire the reference (`${{ secrets.NAME }}`, env names), make absence a supported state (degrade and log a line), and write the exact command for the owner into `docs/factory/OWNER.md`. Never print, commit, test with, or "verify" a secret value. Verify by behaviour.
3. **No attribution.** No `Co-Authored-By`, no "Generated with ...", no mention of Claude, AI or agents in commits, PR titles and bodies, or issue comments. Write as a normal engineering team.
4. **Never blocked.** If a decision is needed, decide it (research first), record it in `DECISIONS.md` as revertible, and continue. If only the owner can unblock (a secret, DNS, money, an account setting), add it to `OWNER.md`, comment on the issue, label it `status:needs-owner`, and move to another issue.
5. **Evidence before assertions.** Done means: CI green, merged, and, where the issue changes something that runs (a workflow, a published page, a runner), a check against the real thing says what you expected. Name what you expected to see, then check that it is there.
6. **Finishing means closing the issue in the same breath:** close with a comment that says how you know, flip the label to `status:done`.
7. **The Factory never holds a member's credentials.** No code path reads, stores, logs or sends a Claude login, an API key, a git credential or a repository secret (spec, sections 2 and 10).
8. **Learning Factory keeps working during the migration.** A change here that LF will run must not reduce what LF's passes do today (spec G8). LF switches to this repository's methodology only through an owner step.

## Git

- Commits, pushes, PR merges and branch cleanup in this repo are pre-approved by the owner.
- One issue = one branch `f/<issue>-<slug>` = one PR into `main`. Squash-merge when CI is green and the reviewer approved. Delete the branch.
- Never push straight to `main`, except `docs/factory/*` updates (journal commits).
- Commit by explicit path list only. Read a file before overwriting it.
- Commit messages: conventional (`feat(runner): ...`, `fix(plugin): ...`), with the issue number (`#12`).
- The exam (acceptance tests) is written before the code and never changed together with it; the CI exam-integrity check enforces this once it exists (issue: CI foundation).

## Verification commands

Defined by the CI foundation issue; until then there is no code here.
