"""Test bootstrap: make bin/fleet.py importable as `fleet` without turning bin/
into a package (fleet.py must stay a standalone single-file CLI)."""
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))
