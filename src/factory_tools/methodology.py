"""``factory-tools methodology render``: the skill's project section, filled from the profile."""

from __future__ import annotations

from pathlib import Path

from factory_tools.profile import Profile, load_profile


def _smoke(p: Profile) -> str:
    s = p.smoke
    if s is None:
        return "none configured"
    if s.workflow:
        return f"workflow `{s.workflow}`"
    return f"command `{s.run}` (cwd `{s.cwd}`)"


def render_profile(p: Profile) -> str:
    """The project section as markdown; every default is the one documented in docs/profile.md."""
    out = ["## This project", "", f"Methodology version: {p.methodology}", ""]
    out.append("### Verify (run before reporting done)")
    if not p.verify:
        out.append("- none configured: use the commands named in the project's CLAUDE.md")
    for area, group in p.verify.items():
        out.append(f"- {area} (cwd `{group.cwd}`):")
        out += [f"  - `{cmd}`" for cmd in group.run]
    out += ["", "### Exam globs (never edited by the implementer)"]
    out += [f"- `{g}`" for g in p.exam]
    lim = p.limits
    out += ["", "### Limits"]
    out += [
        f"- ci_rounds: {lim.ci_rounds}",
        f"- review_rounds: {lim.review_rounds}",
        f"- parallel_issues: {lim.parallel_issues}",
    ]
    out += ["", "### Research hints"]
    out += [f"- {h}" for h in p.research_hints] or ["- none configured"]
    out += ["", "### Ship", f"- smoke: {_smoke(p)}"]
    if p.protected_paths:
        out.append("- protected paths: " + ", ".join(f"`{g}`" for g in p.protected_paths))
    if p.required_checks:
        out.append("- required checks: " + ", ".join(p.required_checks))
    out += [
        "",
        "### Memory files",
        f"- decisions: `{p.owner_files.decisions}`",
        f"- owner: `{p.owner_files.owner}`",
    ]
    return "\n".join(out) + "\n"


def run(path: str) -> int:
    """Print the project section; exit codes follow ``profile check`` (1 problems, 2 unreadable)."""
    prof, problems = load_profile(Path(path))
    if prof is None:
        for q in problems:
            print(f"{q.path or '(file)'}: {q.message}")
        return 2 if any(q.fatal for q in problems) else 1
    print(render_profile(prof), end="")
    return 0
