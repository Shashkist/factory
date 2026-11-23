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

