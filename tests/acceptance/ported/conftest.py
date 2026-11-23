"""Makes `factory_tools` importable from the ported tests without an installed package."""

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[3] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
