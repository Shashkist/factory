"""Shared helpers for the CI foundation exam (stdlib only)."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def env(extra: dict[str, str] | None = None) -> dict[str, str]:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
    e["PYTHONIOENCODING"] = "utf-8"
    if extra:
        e.update(extra)
    return e


def run_module(
    module: str,
    *args: str,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd or ROOT,
        env=env(extra_env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def module_file(module: str) -> Path | None:
    sys.path.insert(0, str(SRC))
    try:
        importlib.invalidate_caches()
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:
        return None
    finally:
        sys.path.remove(str(SRC))
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin)


def workflow_text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
