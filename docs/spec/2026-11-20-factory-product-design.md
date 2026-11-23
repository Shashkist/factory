# Factory as a product: design

_Status: approved by the owner, 2026-11-23. Working name: **Factory**. Source of the idea: the Learning Factory (LF, `Shashkist/Learning_factory`) that built `labs.shashkist.com` autonomously in seven days (54 manager passes, 361 agent runs, ~$500 API-equivalent)._

## 1. Intent

Today's factory is welded to one repository: its skill, agents, hooks and scripts live inside Learning_factory and run from one laptop. The owner wants the factory to become a **product**:

- A client brings **their own repository with GitHub issues already written** (a prerequisite) and their own CI.
- The client **connects** the repository and their **compute** (their own Claude Code and subscription) to the Factory, and from then on development can run **autonomously**. The client only watches progress on the Factory page and answers what only they can answer.
- When one machine is not enough, the client invites a friend who connects **their** compute (their own subscription) to the same project, and the Factory runs more tracks in parallel (for example 5 + 5 = 10).
- The client can also work **by hand** with their agent on an issue; the Factory sees it and does not give that issue to anyone else.
- **The quality is the same no matter who or what did the work**, because everyone runs the same methodology and every result passes the same judges.

**Factory = the front and the work aggregator. All LLM usage and all compute belong to the client.** The Factory runs no model.

## 2. Goals, non-goals, anti-goals

**Goals (v1)**
- G1. Factory methodology lives in its own repository and works on any connected repository. Project rules are read from the client repository, modularly.
- G2. Two connectors: a **repo connector** (GitHub App) and a **compute connector** (a runner the client installs once).
- G3. Autonomous mode: the client presses Start on the page, sets the number of tracks, and only watches.
- G4. Human-led mode: a person working an issue in their own Claude Code session shows up as a lane and holds the issue.
- G5. Several runners from different people on one project, coordinated without collisions.
- G6. Running out of tokens parks a track and the work moves to a runner with capacity; nothing is lost.
- G7. Equal quality: exam before code, client CI green, independent review, deterministic merge gate.
- G8. Learning Factory becomes client #1 with no loss of what it does today.

**Non-goals (v1)**
- Turning an idea into a spec or issues (the client writes issues).
- Engines other than Claude Code (opencode is v2, Codex later; the runner is built for adapters from day one).
- Hosting compute for clients, billing, a marketplace, GitLab/Bitbucket.
- Deploying the client's product: that is the client's CI/CD. The Factory only reads its result.

**Anti-goals (a failure even if it works)**
- The Factory server can make a client machine run arbitrary commands.
- The Factory ever holds, proxies or sees a client's Claude login, API key or repository secrets.
- Two runners work the same issue unknowingly, or work is lost when a runner disappears.
- A result reaches `main` because one runner's local setup was weaker (old methodology, missing hook, different model).
- The client has to babysit: an autonomous project that stops and waits for questions the agent could decide.

## 3. Constraints

- **Anthropic terms (must confirm before any rollout beyond the owner and friends).** The Agent SDK overview says that, unless previously approved, Anthropic does not allow third-party developers to offer claude.ai login or rate limits for their products. Design response: the runner **never** logs in for the user and never touches credentials; it starts the user's own installed `claude` CLI, which the user logged in to themselves. Whether a distributed runner that drives a user's own subscription is acceptable must be **confirmed with Anthropic** (owner action). If not, the fallback is API-key-only runners (each client pays per token) plus cloud sessions under the user's own account.
- **No documented way to drive Claude Code Desktop from outside.** Desktop cannot be the runner. The supported programmatic path is headless `claude -p` (stream-json output, `--settings`, `--resume`, `--permission-mode`). Desktop remains fine for human-led work.
- **Usage-limit signals are not a documented API.** Detection relies on non-zero exit plus limit text ("You've hit your session/weekly limit") and on `CLAUDE_CODE_RETRY_WATCHDOG` where waiting is acceptable. Must be verified on a real limit hit.
- **GitHub is the source of truth.** Issues, branches, PRs, CI results and comments live in the client repository. The Factory server can be lost without losing work.
- Learning Factory rules stay valid for LF as a client (owner's other services first, secrets by owner only, no attribution, evidence before assertions).

## 4. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | **Factory Hub server + runners on client machines (pull model, like GitHub Actions self-hosted runners). GitHub stays the source of truth.** | A real product: accounts, one-click connectors, atomic job assignment, live page, budgets. Costs a server to build and run. | **Chosen by the owner.** |
| B | No server: GitHub is the coordinator (labels as queue, claim comments as locks, page built from the GitHub API), as LF does today. | Almost nothing new to build, but no atomic claim (collisions only become visible), GitHub API rate limits, no accounts or connectors; hard to make a product. | Rejected; its proven parts (claims with branch, exam integrity, merge gate) move into A. |
| C | The Factory runs agents in its own cloud on the client's key. | Contradicts "all compute belongs to the client"; holds client credentials. | Dropped. |

## 5. The pieces

```
 client repo (GitHub)            Factory Hub (our server)                client machines
 ┌──────────────────┐   App    ┌──────────────────────────┐  HTTPS   ┌───────────────────┐
 │ issues, PRs, CI  │◀────────▶│ projects, connectors     │◀─────────│ runner (owner)    │
 │ CLAUDE.md        │ webhooks │ scheduler + job queue    │  pull    │  ├ track 1 claude │
 │ .factory/        │          │ claims, budgets, gate    │          │  ├ track 2 claude │
 │   factory.yaml   │          │ page (live)              │◀─────────│ runner (friend)   │
 └──────────────────┘          └──────────────────────────┘          │  └ track 3 claude │
                                                                      └───────────────────┘
 methodology repo (factory/): plugin (skills, agents), runner, reusable CI checks
```

### 5.1 Methodology repository (the "factory repo")
A separate repository, versioned and released. Contains:
- **Claude Code plugin**: the role skills (`work-issue`, `write-exam`, `implement`, `review`, `decide`), subagent definitions (exam writer, implementer, reviewer, researcher) and a `take` command for human-led mode. Generalised from LF's `SKILL.md` and `.claude/agents/*.md` (only ~10 % of today's text is LF-specific).
- **Runner** (see 5.4).
- **Reusable CI checks** the client adds to their CI: exam integrity (from `scripts/ci/exam_integrity.py`), the no-skip test gate (`junit_gate.py`), the incident gate.
- Methodology changes ship as versions. A project pins a version in its profile, so all runners on a project run the **same** methodology version; a runner with a different version is refused jobs for that project.

### 5.2 Project profile (in the client repository)
Everything specific to the project, read by the runner at job start and layered on top of the methodology:
- `CLAUDE.md` (or `AGENTS.md`): the project's rules, as today.
- `.factory/factory.yaml`: methodology version; verify commands per area (e.g. `uv run pytest -q`); exam paths (`**/tests/acceptance/**`); protected paths the agent must not touch; required CI checks for the merge gate; labels mapping; review rounds and CI rounds limits; models per role; optional smoke command; optional research hints (LF: "KodeKloud, Killercoda…").
- Optional `.factory/skills/` and `.factory/agents/` that add to or override methodology parts for this project (LF's server-safety rules, for example).
- `.factory/DECISIONS.md`, `.factory/OWNER.md`: the project's memory, as LF's `docs/factory/*` today. `STATE.md` disappears: the Hub holds live state; the page replaces it.

### 5.3 Factory Hub (server)
- **Accounts and projects.** Sign in with GitHub. A project = one repository + its members.
- **Repo connector**: a GitHub App installed on the repository (least privilege: issues, pull requests, contents, checks, comments). Webhooks keep the Hub's view of issues/PRs/CI fresh. The App token never leaves the Hub; runners push with the user's own git credentials.
- **Compute connector registry**: runners register with a one-time code from the page, get a runner token scoped to the projects their owner allows, and declare capacity (5.6).
- **Scheduler and job queue** (deterministic, no LLM): picks `ready` issues by priority and dependencies (`Depends on #n` closed), cuts them into jobs, hands each job to one runner atomically. Detects dead runners by missed heartbeats and re-queues their jobs on the same branch.
- **Merge gate** (LF #84 made generic): MERGE only when all required checks on the PR head are green, the latest review verdict for that head is APPROVE, the exam was not changed together with code, rounds are within limits. On MERGE the Hub squash-merges via the App. Nothing else merges.
- **Page**: per project, lanes per issue with station and sub-step (as factory.shashkist.com today), runners with capacity and paused-until, the owner inbox (needs-owner items and decisions to read), history and cost per runner. Controls: Start/Pause/Stop project, tracks per runner, issue priority, re-run a job.

### 5.4 Runner (compute connector)
A small background program the client installs once (Windows, macOS, Linux).
- **Outbound only**: long-polls the Hub over HTTPS for jobs; no listening port.
- **Jobs are data, not commands**: `{project, repo, issue, job type, branch, methodology version}`. What to do for a job type comes from the runner's local methodology and the project profile, never from the Hub. A compromised Hub can at worst assign the wrong issue.
- **One track = one job = one git worktree** (container recommended), only in repositories the owner connected.
- **Engine adapter** starts the agent for the job and reads its event stream. v1 adapter: Claude Code (`claude -p --output-format stream-json --model <role model> --permission-mode auto --settings <factory hooks>` with the plugin enabled). Adapter interface: `start(job) → events`, `detect_limit(event|exit) → reset_at?`, `stop()`.
- **Engine-neutral guards live in the runner, not in engine hooks**: progress reporting to the Hub, the guard against protected paths and dangerous commands, heartbeats, usage-limit detection. That keeps them identical for every engine and makes later adapters small.
- **Local stop** always works (tray icon / `factory stop`), even with the Hub down.
- Never reads, prints or sends credentials; the user logs in to Claude Code themselves.

## 6. How an issue flows

Each step is a **job** a runner can take; different steps of one issue may run on different runners (which gives the reviewer a fresh context for free).

1. **Pick.** Scheduler takes the highest-priority `ready` issue with closed dependencies; the claim is held in the Hub and mirrored as a label and a comment on the issue (so humans and LF's tooling still see it).
2. **Exam job** (exam writer, `write-exam` skill): acceptance tests from the issue and the profile only, committed first on branch `f/<n>-<slug>`.
3. **Build job** (implementer): code until exam, unit tests, lint and types pass locally (profile commands); push; open PR (`Closes #n`).
4. **CI** (client's own CI, with the Factory's reusable checks): the Hub watches it. Red → a fix job with the failure (max CI rounds from the profile).
5. **Review job** (reviewer, preferably a different runner than the builder, larger model): posts a verdict comment whose first line is `Verdict: APPROVE` or `Verdict: CHANGES` plus findings. Changes → fix job (max 2 rounds, then the deciding job records a decision and splits leftovers into a follow-up issue).
6. **Merge gate** in the Hub → squash-merge.
7. **Close** after the client's deploy/smoke result if the profile defines one, otherwise after merge; closing comment carries the evidence (PR, CI run, smoke output).
8. **Decide, don't wait**: any open question inside a job is decided by the agent and recorded in `.factory/DECISIONS.md`; only owner-only blockers (secrets, money, DNS, access) go to the owner inbox, the issue is parked, and the scheduler moves on.

## 7. Human-led mode

In any Claude Code session (CLI, IDE or Desktop) in the repository, the user runs the plugin command `/factory:take #n` (or `factory take #n` from a shell). The Hub claims the issue for that user, the page shows a lane marked **human-led**, autonomous runners skip it, and progress sub-steps are reported by the same plugin. The same judges apply: the PR still goes through CI, review job and merge gate. `/factory:release` hands it back to the queue with the branch.

## 8. Capacity and running out of tokens

- **Each runner declares its budget**: max parallel tracks; share of the subscription kept for the owner's own use (e.g. stop taking jobs once a local estimate passes 80 %); quiet hours; which roles it accepts (e.g. a small subscription takes exam and build jobs, a large one also takes reviews on the bigger model).
- **Limit hit → park, don't fail.** The adapter detects the limit; the runner commits work in progress to the branch, writes a "where I stopped" note to the job, and reports `paused until <reset time>` (or "unknown, retry in 30 min"). The Hub re-queues the job on the same branch for a runner with capacity. LF's claim-with-branch recovery is the basis.
- **Routing by strength**: the scheduler prefers runners that accept the job's role and have the most headroom; reviews go to runners allowed to use the review model.
- **Visible fairness**: the page shows per runner: jobs done, tokens (from the agent's own usage reports), paused time.

## 9. Engines

| Engine | Status | Notes |
|---|---|---|
| Claude Code CLI | **v1** | Headless `claude -p`; plugin carries skills and agents; runner carries guards. |
| Claude Code Desktop | human-led only | No documented external control; fine for `/factory:take`. |
| Claude Code cloud sessions / scheduled tasks | later | Could become a "cloud compute connector" on the user's own account (`claude --cloud`, API-triggered scheduled tasks; minimum 1 h schedule; plan required). Not v1. |
| opencode | **v2** | Reads `CLAUDE.md` (without `AGENTS.md`) and `.claude/skills`; agents and hooks need translation (hooks are moot: guards live in the runner). Works on API keys of many providers and local models, which adds capacity when subscriptions run out and gives the cross-company "second opinion" review (LF #16). Using a Claude subscription inside opencode is likely not allowed; verify. |
| OpenAI Codex | later | Reads `AGENTS.md` (CLAUDE.md via `project_doc_fallback_filenames`), skills from `.agents/skills`, agents as TOML in `.codex/agents`, hooks in `.codex/hooks.json`. Driven by the Codex SDK or `codex exec --json`; native Windows sandbox. The runner would compile the Claude-format methodology into this layout at job start. |

## 10. Security and trust

- Outbound-only runners; jobs are data; per-track worktree or container; a runner works only in repositories its owner connected; local kill switch.
- The Hub stores no client credentials: GitHub App installation tokens stay server-side; runners push with the user's git credentials; model logins stay on the user's machine.
- Project members are GitHub collaborators with branch protection on `main` (required checks, merges only by the App), so a member's runner cannot bypass the gate. Fork PRs are not used (they get no secrets, so review and CI cannot run).
- Autonomous mode on a person's computer is that person's risk: the runner recommends containers and refuses to start in auto-permission mode outside a worktree.
- Secrets of the client's product are installed by the client only (LF rule 2, now a Factory rule); the owner inbox carries the exact command to run.
- Prompt-injection surface: issue texts and PR comments from non-members are data, never instructions; the scheduler only takes issues labelled ready by a member (or created by an enabled `plan` job).
- Merges to `main` only by the App (branch protection); decisions travel inside PRs (section 13).

## 11. Migration of Learning Factory

1. **v0, extraction (no server yet).** Create the methodology repository; move and generalise the skill, agents and scripts; LF keeps only its profile (`CLAUDE.md`, `.factory/factory.yaml`, its server-safety skill, `DECISIONS.md`, `OWNER.md`). LF's laptop poller now runs the plugin from the methodology repo. Done when LF passes work as well as before (same merge rate, CI green).
2. **v1, Hub + Claude Code runner.** GitHub App, scheduler, merge gate, page; the laptop poller is replaced by the runner; factory.shashkist.com becomes the Hub page. Done when LF runs a full day through the Hub with no laptop script.
3. **v2, many runners.** Invites, capacity, park-and-requeue on limits, human-led mode. Done when the owner and a friend run LF (or the friend's repo) with two runners and 10 tracks without a collision.
4. **v3, opencode adapter**, then Codex.

## 12. Decided by the owner
- Approach A; client writes the issues; Claude Code first, opencode next; compute and LLM belong to the client; connectors with autonomous start from the page; human-led work alongside autonomous work.

## 13. My calls (correct any)
- The Hub decides deterministically (no LLM on the server); planning-like thinking happens inside jobs on runners.
- No manager session: today's manager loop is split into Hub logic (pick, claim, gate, merge, close) and jobs (exam, build, review, decide). `STATE.md` is replaced by the Hub's live state.
- Methodology version pinned per project; mismatched runners get no jobs.
- Guards and progress reporting move from engine hooks into the runner.
- Review verdict as a PR comment with a machine-readable first line.
- Hub stack: same as LF's manager (FastAPI, Postgres, React) to reuse code and skills; v1 hosted on the existing server behind `factory.shashkist.com` through the `labs/deploy` scripts.
- ~~Design documents stay out of the public LF repository.~~ Superseded by the owner on 2026-11-23: the spec is public in `Shashkist/factory` (section 17).
- **Trust model (from the builder check).** The gate assumes a member's *machine* may be misconfigured or modified, not only that setups differ. So: runners submit results (exam done, review verdict) to the Hub with their runner token, and **the Hub posts the verdict comment through the App**; the gate accepts only App-posted verdicts, never a comment a person typed. The Hub prefers a reviewer runner owned by a different member than the builder; on a solo project it uses a different runner and a fresh session, and the page says "self-reviewed". Version and model reported by a runner are checked against the pinned versions, and the review job's model is recorded with the verdict.
- **Collisions (G5).** The Hub prevents two jobs on one issue (atomic claim). Code overlap: issues may carry `area:<name>` labels, with areas mapped to paths in `factory.yaml`; the scheduler never runs two build jobs of the same area at once. Issues without an area run freely; a merge conflict turns into a **rebase job** on a fresh `-2` branch (LF's rule, since force-push is not used). Ten tracks are realistic only with areas declared; the page shows that.
- **Project memory once only the App merges.** Decisions go **inside the PR** as one file per decision (`.factory/decisions/D-<n>-<slug>.md`, numbered by the Hub, so no merge conflicts) and land with the merge. The owner inbox lives in the Hub and is mirrored as GitHub issues labelled `needs-owner` (GitHub stays the record); `OWNER.md` is dropped.
- **Planning and incidents (keeps G8).** An optional `plan` job type, off by default, enabled per project in `factory.yaml` (`planning: {spec: <path>, keep_ready: 5}`): when fewer ready issues remain than `keep_ready`, a runner slices more from the spec and labels them ready. LF turns it on. Incidents: the methodology repository ships a reusable CI workflow that opens a `type:incident` `priority:p0` issue when `main` CI, deploy or smoke fails (LF's incident workflow, generalised); the scheduler always takes p0 first.

## 14. Left to the builder
Hub schema and API shape; long-poll vs WebSocket; runner packaging per OS; page design; exact `factory.yaml` schema; how tokens per job are counted from stream-json; container image for tracks.

## 15. Audience of v1 and v2 (owner, 2026-11-20)

**The owner and invited friends only.** Consequences:
- A private GitHub App; sign-in with GitHub; members invited by the project owner. No public sign-up, no per-client data isolation beyond projects, no abuse controls in v1-v2.
- The Hub may run on the existing server next to labs, under the server-safety rules (its own `lf-`/`factory-` containers, deployed only through the `labs/deploy` scripts). Moving to separate hosting is a precondition for any client outside this circle.
- Runners use each member's own Claude subscription for repositories they are members of. The adapter also supports an API-key mode from v1 (one setting), so the answer from Anthropic about distributing a subscription-driven runner (owner action, before any outside client) cannot block the product.

## 16. Open questions for the owner
None at the moment.

## 17. Owner decisions, 2026-11-23 (start of development)

- **Home.** The Factory lives in its own **public** repository, `Shashkist/factory` (free CI; a private repository would exceed the free Actions minutes at the factory's pace).
- **Built by the factory itself.** Until v0 is done, the existing Learning Factory manager (running from `Shashkist/Learning_factory` on the owner's laptop) builds this repository through issues here. Its first change, made in LF, is to take issues from a second repository: the first multi-repository step, used on itself.
- **LF migrates as client #1 and labs development continues from here.** v0 moves the current methodology (skill, agents, scripts, reusable CI checks) into this repository; LF keeps only its project profile. After the switch, LF's laptop runner runs the methodology from this repository and works both `Shashkist/Learning_factory` (labs) and `Shashkist/factory`.
- **`factory.shashkist.com` migrates too.** The live dashboard (today `labs/factory-dashboard/` and the `factory-dashboard.yml` workflow in LF) moves here, shows every connected repository, and is published from this repository. In v1 it becomes the Hub page.
