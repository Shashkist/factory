"""The project profile (``.factory/factory.yaml``): model, loader and validator.

The file is data only. It is read with ``yaml.safe_load`` and nothing in it is ever executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = ".factory/factory.yaml"


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a profile. ``path`` is the dotted key path, ``[i]`` for list items."""

    path: str
    message: str
    fatal: bool = False  # the file could not be read or is not valid YAML


@dataclass(frozen=True)
class VerifyGroup:
    run: tuple[str, ...]
    cwd: str = "."


@dataclass(frozen=True)
class Limits:
    ci_rounds: int = 5
    review_rounds: int = 2
    parallel_issues: int = 3


@dataclass(frozen=True)
class Smoke:
    run: str | None = None
    cwd: str = "."
    workflow: str | None = None


@dataclass(frozen=True)
class Planning:
    spec: str
    keep_ready: int = 5


@dataclass(frozen=True)
class OwnerFiles:
    decisions: str = ".factory/DECISIONS.md"
    owner: str = ".factory/OWNER.md"


@dataclass(frozen=True)
class Profile:
    methodology: str
    verify: dict[str, VerifyGroup] = field(default_factory=dict)
    exam: tuple[str, ...] = ("**/tests/acceptance/**",)
    protected_paths: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)
    models: dict[str, str] = field(default_factory=dict)
    smoke: Smoke | None = None
    research_hints: tuple[str, ...] = ()
    areas: dict[str, tuple[str, ...]] = field(default_factory=dict)
    planning: Planning | None = None
    owner_files: OwnerFiles = field(default_factory=OwnerFiles)


def _join(base: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{base}[{key}]"
    return f"{base}.{key}" if base else key


class _Validator:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def err(self, path: str, message: str) -> None:
        self.problems.append(Problem(path, message))

    def mapping(self, value: Any, path: str, allowed: set[str]) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.err(path, "must be a mapping")
            return None
        for key in value:
            if key not in allowed:
                self.err(_join(path, str(key)), "unknown key")
        return {k: v for k, v in value.items() if k in allowed}

    def string(self, value: Any, path: str) -> str | None:
        if isinstance(value, str):
            return value
        self.err(path, "must be a string")
        return None

    def integer(self, value: Any, path: str) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        self.err(path, "must be a positive integer")
        return None

    def strings(self, value: Any, path: str, non_empty: bool = False) -> tuple[str, ...] | None:
        if not isinstance(value, list):
            self.err(path, "must be a list of strings")
            return None
        if non_empty and not value:
            self.err(path, "must not be empty")
            return None
        out = [self.string(item, _join(path, i)) for i, item in enumerate(value)]
        return tuple(s for s in out if s is not None) if None not in out else None

    def str_map(self, value: Any, path: str) -> dict[str, str] | None:
        if not isinstance(value, dict):
            self.err(path, "must be a mapping of strings")
            return None
        out: dict[str, str] = {}
        for k, v in value.items():
            s = self.string(v, _join(path, str(k)))
            if s is not None:
                out[str(k)] = s
        return out

    def verify(self, value: Any, path: str) -> dict[str, VerifyGroup] | None:
        if not isinstance(value, dict):
            self.err(path, "must be a mapping of area name to command group")
            return None
        out: dict[str, VerifyGroup] = {}
        for name, raw in value.items():
            p = _join(path, str(name))
            m = self.mapping(raw, p, {"cwd", "run"})
            if m is None:
                continue
            if "run" not in m:
                self.err(_join(p, "run"), "is required")
                continue
            run = self.strings(m["run"], _join(p, "run"), non_empty=True)
            cwd = self.string(m["cwd"], _join(p, "cwd")) if "cwd" in m else "."
            if run is not None and cwd is not None:
                out[str(name)] = VerifyGroup(run=run, cwd=cwd)
        return out

    def limits(self, value: Any, path: str) -> Limits | None:
        keys = ("ci_rounds", "review_rounds", "parallel_issues")
        m = self.mapping(value, path, set(keys))
        if m is None:
            return None
        got = {k: self.integer(m[k], _join(path, k)) for k in keys if k in m}
        return Limits(**{k: n for k, n in got.items() if n is not None})

    def smoke(self, value: Any, path: str) -> Smoke | None:
        if value is None:
            return None
        m = self.mapping(value, path, {"run", "cwd", "workflow"})
        if m is None:
            return None
        if ("run" in m) == ("workflow" in m):
            self.err(path, "needs exactly one of run or workflow")
            return None
        if "workflow" in m:
            if "cwd" in m:
                self.err(_join(path, "cwd"), "only applies to run")
            wf = self.string(m["workflow"], _join(path, "workflow"))
            return Smoke(workflow=wf) if wf is not None else None
        run = self.string(m["run"], _join(path, "run"))
        cwd = self.string(m["cwd"], _join(path, "cwd")) if "cwd" in m else "."
        return Smoke(run=run, cwd=cwd) if run is not None and cwd is not None else None

    def areas(self, value: Any, path: str) -> dict[str, tuple[str, ...]] | None:
        if not isinstance(value, dict):
            self.err(path, "must be a mapping of area name to a list of globs")
            return None
        out: dict[str, tuple[str, ...]] = {}
        for name, raw in value.items():
            globs = self.strings(raw, _join(path, str(name)), non_empty=True)
            if globs is not None:
                out[str(name)] = globs
        return out

    def planning(self, value: Any, path: str) -> Planning | None:
        if value is None:
            return None
        m = self.mapping(value, path, {"spec", "keep_ready"})
        if m is None:
            return None
        if "spec" not in m:
            self.err(_join(path, "spec"), "is required")
            return None
        spec = self.string(m["spec"], _join(path, "spec"))
        keep = self.integer(m["keep_ready"], _join(path, "keep_ready")) if "keep_ready" in m else 5
        return Planning(spec=spec, keep_ready=keep) if spec is not None and keep else None

    def owner_files(self, value: Any, path: str) -> OwnerFiles | None:
        m = self.mapping(value, path, {"decisions", "owner"})
        if m is None:
            return None
        d = OwnerFiles()
        decisions = d.decisions
        owner = d.owner
        if "decisions" in m:
            decisions = self.string(m["decisions"], _join(path, "decisions")) or ""
        if "owner" in m:
            owner = self.string(m["owner"], _join(path, "owner")) or ""
        return OwnerFiles(decisions=decisions, owner=owner)

    def profile(self, data: Any) -> Profile | None:
        names = {f.name for f in fields(Profile)}
        m = self.mapping(data, "", names)
        if m is None:
            return None
        kw: dict[str, Any] = {}
        if "methodology" not in m:
            self.err("methodology", "is required")
        else:
            kw["methodology"] = self.string(m["methodology"], "methodology")
        sections: dict[str, Any] = {
            "verify": self.verify,
            "exam": self.strings,
            "protected_paths": self.strings,
            "required_checks": self.strings,
            "labels": self.str_map,
            "limits": self.limits,
            "models": self.str_map,
            "smoke": self.smoke,
            "research_hints": self.strings,
            "areas": self.areas,
            "planning": self.planning,
            "owner_files": self.owner_files,
        }
        for key, fn in sections.items():
            if key in m:
                kw[key] = fn(m[key], key)
        if self.problems:
            return None
        optional = ("smoke", "planning")
        return Profile(**{k: v for k, v in kw.items() if v is not None or k in optional})


def _glob_matches(root: Path, pattern: str) -> bool:
    try:
        return next(root.glob(pattern), None) is not None
    except (ValueError, NotImplementedError, OSError):
        return False


def load_profile(
    path: str | Path, root: Path | None = None
) -> tuple[Profile | None, list[Problem]]:
    """Read and validate a profile. Never executes anything from it.

    Area globs are checked against ``root`` only when a root is given.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Problem("", f"cannot read {path}: {exc}", fatal=True)]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        first = (str(exc).splitlines() or [type(exc).__name__])[0]
        return None, [Problem("", f"invalid YAML: {first}", fatal=True)]
    v = _Validator()
    prof = v.profile(data)
    problems = v.problems
    if root is not None and isinstance(data, dict) and isinstance(data.get("areas"), dict):
        for name, globs in data["areas"].items():
            if isinstance(globs, list):
                for i, g in enumerate(globs):
                    if isinstance(g, str) and not _glob_matches(root, g):
                        msg = f"glob {g!r} matches nothing"
                        problems.append(Problem(f"areas.{name}[{i}]", msg))
    if problems:
        return None, problems
    return prof, []
