#!/usr/bin/env python3
"""Mark directories trusted for Claude Code so a dispatched lane never sits on
the trust dialog it cannot answer (fleet queue item 30).

Usage: trust-worktree.py PATH [PATH ...]
"""
import json, os, pathlib, shutil, sys

def main(paths):
    cfg = pathlib.Path(os.path.expanduser("~/.claude.json"))
    data = json.loads(cfg.read_text(encoding="utf-8"))
    projects = data.setdefault("projects", {})
    changed = []
    for raw in paths:
        p = str(pathlib.Path(raw).resolve())
        entry = projects.setdefault(p, {})
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            changed.append(p)
    if changed:
        shutil.copy(cfg, str(cfg) + ".bak")
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"trusted {len(changed)} new path(s)")
    for p in changed:
        print(" ", p)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or [os.getcwd()]))
