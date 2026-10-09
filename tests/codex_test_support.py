"""Test-only command adaptation for the hermetic Codex fixture."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


def hermetic_codex_argv(
    argv: Sequence[str], root: Path, *, platform: str | None = None,
    comspec: str | None = None,
) -> list[str]:
    """Return an argv that can launch the fixture with ``shell=False``.

    ``CreateProcess`` does not apply ``PATHEXT`` to a bare command, so a
    ``codex.cmd`` shim is not a valid target for Windows' shell-disabled
    subprocess path.  Route only the fixture's Codex command through the
    system command interpreter there.  POSIX keeps the original bare argv.
    """
    command = list(argv)
    if not command or (platform or os.name) != "nt":
        return command
    name = Path(command[0]).name.lower()
    if name not in {"codex", "codex.cmd"}:
        return command
    return [
        comspec or os.environ.get("COMSPEC") or "cmd.exe",
        "/d", "/c", str(root / "codex.cmd"), *command[1:],
    ]
