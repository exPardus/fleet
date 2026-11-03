#!/usr/bin/env python3
"""Stand-in for bwrap: logs its argv, applies --chdir/--clearenv/--setenv, runs
the command after `--` unsandboxed. FLEET_PI_FAKE_BWRAP_LOG names the log;
FLEET_PI_FAKE_BWRAP_FAIL=1 makes every call exit 1 like a broken userns."""
import json
import os
import sys

argv = sys.argv[1:]
if os.environ.get("FLEET_PI_FAKE_BWRAP_FAIL") == "1":
    sys.stderr.write("bwrap: No permissions to create new namespace\n")
    sys.exit(1)
split = argv.index("--")
opts, cmd = argv[:split], argv[split + 1:]
with open(os.environ["FLEET_PI_FAKE_BWRAP_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"opts": opts, "cmd": cmd}) + "\n")
env, chdir, i = dict(os.environ), None, 0
while i < len(opts):
    if opts[i] == "--clearenv":
        env = {}
    elif opts[i] == "--setenv":
        env[opts[i + 1]] = opts[i + 2]
        i += 2
    elif opts[i] == "--chdir":
        chdir = opts[i + 1]
        i += 1
    i += 1
if cmd == ["/usr/bin/true"]:
    sys.exit(0)
if chdir:
    os.chdir(chdir)
os.execve(cmd[0], cmd, env)
