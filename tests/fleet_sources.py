"""Shared source population for safety detectors after the index extraction.

Concatenation is for AST/text census only; physical line citations must read
individual files. Missing implementation files are errors, never exclusions.
"""
from pathlib import Path

import fleet


IMPLEMENTATION_FILES = ("fleet.py", "fleet_index.py", "fleet_errors.py",
                        "fleet_land.py")


def fleet_implementation_paths():
    directory = Path(fleet.__file__).resolve().parent
    return tuple(directory / name for name in IMPLEMENTATION_FILES)


def fleet_implementation_source():
    return "\n\n".join(path.read_text(encoding="utf-8")
                       for path in fleet_implementation_paths())
