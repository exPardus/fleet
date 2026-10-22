#!/usr/bin/env python3
"""One file-only Fleet snapshot for Codex's cached native footer item.

This entrypoint does not consume Claude statusLine JSON or chain delegates.
The Codex TUI controls refresh, timeout, and output length.
"""

import argparse
import os
from pathlib import Path

import fleet
import fleet_statusline


class _ViewParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None) -> int:
    try:
        parser = _ViewParser(
            description="Read a Fleet home for Codex's footer", add_help=False
        )
        parser.add_argument("--fleet-home")
        args = parser.parse_args(argv)
        selected = args.fleet_home or os.environ.get("FLEET_HOME")
        if not selected:
            raise ValueError("Fleet home must be explicit")
        home = Path(selected).expanduser().resolve(strict=True)
        if not home.is_dir():
            raise ValueError("Fleet home is not a directory")
        fleet.FLEET_HOME = home
        line = fleet_statusline.render_statusline(
            fleet.status_snapshot(), color=False
        )
        print(line.splitlines()[0][:160] if line else "fleet unavailable")
    except Exception:  # noqa: BLE001 -- a view must degrade, never mutate or trace
        print("fleet unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
