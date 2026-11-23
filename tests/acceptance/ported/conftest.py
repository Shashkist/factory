"""Support for the ported LF tests: the package source is importable, also in child processes."""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ["PYTHONPATH"] = str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")
