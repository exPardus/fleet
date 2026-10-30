#!/usr/bin/env python3
"""Scripted stand-in for the pi CLI: no network, no model.

FLEET_PI_FAKE_SCENARIO names a JSON file: {"runs": [run, ...]}. Invocation N (counted
in FLEET_PI_FAKE_STATE) plays runs[min(N, len-1)]. A run is
{"events": [event | {"sleep": seconds} | {"text": "..."}], "exit": 0}.
Every invocation appends {"argv", "agent_dir", "has_key"} to FLEET_PI_FAKE_LOG; the
key value itself is never recorded.
"""
import json
import os
import sys
import time

scenario = json.load(open(os.environ["FLEET_PI_FAKE_SCENARIO"], encoding="utf-8"))
state_path = os.environ["FLEET_PI_FAKE_STATE"]
try:
    n = int(open(state_path, encoding="utf-8").read())
except OSError:
    n = 0
open(state_path, "w", encoding="utf-8").write(str(n + 1))
with open(os.environ["FLEET_PI_FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({
        "argv": sys.argv[1:],
        "agent_dir": os.environ.get("PI_CODING_AGENT_DIR"),
        "has_key": bool(os.environ.get("OPENROUTER_API_KEY")),
        "env_keys": sorted(os.environ),
        "cwd": os.getcwd()}) + "\n")
run = scenario["runs"][min(n, len(scenario["runs"]) - 1)]
for event in run["events"]:
    if "sleep" in event:
        time.sleep(event["sleep"])
        continue
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()
sys.exit(run.get("exit", 0))
