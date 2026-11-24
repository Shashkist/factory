# Factory

A software factory: it takes GitHub issues on your repositories to merged, verified pull requests. Exam (acceptance tests) before code, your own CI, an independent review and a deterministic merge gate, the same for every contributor.

- **Your repository, your compute.** You connect a repository and a runner on your own machine, which drives your own coding agent (Claude Code first). The Factory is the front and the work aggregator; it runs no model and holds no credentials.
- **Several people, one project.** Friends connect their runners to the same project and the Factory runs more tracks in parallel without collisions.
- **Autonomous or by hand.** Press Start and watch, or take an issue in your own session; both go through the same judges.

## Methodology plugin

The method (the pass, the role agents and the profile keys they read) is a Claude Code plugin in `plugin/`. It is described in [`docs/methodology.md`](docs/methodology.md). The install commands are:

```
/plugin marketplace add Shashkist/factory
/plugin install factory@factory
```

These commands work once #7 adds the marketplace manifest (`.claude-plugin/marketplace.json`). Until then the plugin loads from a clone with `claude --plugin-dir plugin`.

Status: early development. The design is in [`docs/spec/2026-11-20-factory-product-design.md`](docs/spec/2026-11-20-factory-product-design.md). The first client is [Learning Factory](https://github.com/Shashkist/Learning_factory), whose factory this project grows out of. Progress: https://factory.shashkist.com
