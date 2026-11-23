# Decisions

Every decision and assumption made while building the Factory. When two documents disagree, this file settles it. Each entry: number, title, status line, the decision, why, alternatives, how to revert. Take the next number only right after `git pull --rebase origin main`.

## D1 · Home, builder and migration order (owner, 2026-11-23)
in force · owner · 2026-11-23

**Decision.** The Factory lives in this public repository. Until v0 is done it is built by the Learning Factory manager, which takes issues from here as a second repository (its first multi-repository step, made in `Shashkist/Learning_factory`). v0 moves LF's methodology here; LF keeps only its project profile and continues labs development through this repository's methodology. `factory.shashkist.com` moves here as well. Spec section 17.

**Why.** The owner wants the factory as its own product with LF as client #1; a public repository keeps CI free at the factory's pace.

**Alternatives.** A private repository (paid Actions minutes); a `factory/` folder inside LF, extracted later.

**Revert.** Archive this repository; LF keeps its own copy of the methodology until the switch issue ships.
