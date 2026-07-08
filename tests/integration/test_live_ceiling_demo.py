"""Tier-3 LIVE demo for kernel 10 (F12=M24) -- the token-ceiling SPLIT kernel,
BOTH halves proven end-to-end against a real haiku turn (C2 Wave 2B link 4/5).

Additive to test_live_smoke.py (its Sandbox + helpers are reused, its file is
NOT rewritten). Same containment as the harness: throwaway temp FLEET_HOME +
throwaway git repo + haiku + a HARD per-run ceiling assert; only harness-spawned
PIDs are ever touched. Gated on FLEET_LIVE=1 (tests/conftest.py); RUN with
FLEET_HOOK_SOURCE=worktree so the chain's OWN worktree hooks execute.

The split kernel has two halves that MUST both be observed:
  (i)  FLEET-SIDE hard refusal -- a `send` resume launch for an over-ceiling
       worker is REFUSED and the worker is flagged over_ceiling (enforcement
       lives fleet-side; the Stop hook never blocks -- invariant 2).
  (ii) HOOK-SIDE allow-stop -- an over-ceiling worker WITH pending mail is
       ALLOWED to stop by the worktree Stop hook despite the mail, and the
       mailbox artifact SURVIVES for the next launch to drain.
A demo proving only one half is NOT done, so this single test asserts + prints
both, sharing one worker so the sequence is coherent.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import fleet
# reuse the harness machinery verbatim -- do not re-implement it
from test_live_smoke import (
    Sandbox,
    HOOK_SOURCE,
    HOOK_SOURCE_HOME,
    MODEL,
    PER_TURN_BUDGET_USD,
    WORKTREE_ROOT,
)

pytestmark = pytest.mark.live

_RUN_CEILING_USD = 0.25  # containment: summed spend asserted below


@pytest.fixture(scope="module")
def sandbox():
    """A throwaway temp FLEET_HOME (worktree bin/ + rendered worktree hooks) and
    a throwaway git repo -- the SAME construction test_live_smoke's fixture uses,
    so the live run exercises the chain's own edits."""
    home = Path(tempfile.mkdtemp(prefix="fleet-live-ceil-home-"))
    repo = Path(tempfile.mkdtemp(prefix="fleet-live-ceil-repo-"))
    try:
        shutil.copytree(WORKTREE_ROOT / "bin", home / "bin")
        shutil.copy2(WORKTREE_ROOT / "worker-settings.template.json",
                     home / "worker-settings.template.json")
        for sub in ("state", "logs", "mailbox", "state/journals"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        template_text = (home / "worker-settings.template.json").read_text(encoding="utf-8")
        rendered = fleet.render_worker_settings_template(
            template_text, sys.executable, HOOK_SOURCE_HOME)
        (home / "state" / "worker-settings.json").write_text(rendered, encoding="utf-8")
        os.utime(home / "state" / "worker-settings.json", None)

        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "harness@example.com"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "harness"],
                       check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("throwaway ceiling-demo repo\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"],
                       check=True, capture_output=True, text=True)
        yield Sandbox(home, repo)
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(repo, ignore_errors=True)


def test_token_ceiling_both_halves(sandbox: Sandbox, capsys):
    assert HOOK_SOURCE == "worktree", (
        "run this demo with FLEET_HOOK_SOURCE=worktree so the chain's OWN Stop "
        f"hook executes (got {HOOK_SOURCE!r})"
    )
    name = "ceil-demo"
    # A ceiling of 1 token guarantees any real turn is provably over it -- the
    # cheapest possible way to exercise both enforcement paths.
    r = sandbox.fleet(
        "spawn", name, "--dir", str(sandbox.repo),
        "--task", "Do NOT use any tools. Reply with only the word READY and stop.",
        "--mode", "bypass", "--model", MODEL,
        "--max-budget-usd", str(PER_TURN_BUDGET_USD),
        "--token-ceiling", "1",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    sid = sandbox.worker(name)["session_id"]

    # the fleet side wrote the sid-keyed ceiling file the worktree Stop hook reads
    ceiling_file = sandbox.home / "state" / "ceilings" / sid
    assert ceiling_file.read_text(encoding="utf-8").strip() == "1", "ceiling file not written on spawn"

    # seed mail BEFORE the turn stops (no tool call -> only the Stop hook can
    # find it). WITHOUT the ceiling the worktree Stop hook would block+drain;
    # over the ceiling it must ALLOW the stop and LEAVE the mail.
    mail_text = "Steering update from manager: this mail must SURVIVE the over-ceiling stop."
    sandbox.seed_mailbox(sid, mail_text)

    sandbox.fleet("wait", name, "--timeout", "240", check=False)
    sandbox.fleet("status", name, check=False)

    # ---- HALF (ii): hook-side allow-stop-with-mail ------------------------
    rec = sandbox.worker(name)
    assert rec["status"] in ("idle", "over_ceiling"), (
        f"turn did not end cleanly (hook did not allow the stop): status={rec['status']}")
    mbox = sandbox.mailbox_path(sid)
    surviving = mbox.read_text(encoding="utf-8") if mbox.exists() else ""
    assert mail_text in surviving, (
        "HALF (ii) FAILED: the Stop hook drained the mail instead of allowing the "
        "over-ceiling stop -- the mailbox artifact did not survive")
    status_ii = sandbox.fleet("status", name, check=False)

    print("\n================ HALF (ii): HOOK-SIDE ALLOW-STOP-WITH-MAIL ================")
    print(f"worker status after over-ceiling turn: {rec['status']} (turn ended; hook allowed stop)")
    print(f"SURVIVING mailbox artifact ({mbox}):\n  {surviving.strip()}")
    print("status table (idle+mail flag -> mail preserved for next-launch drain):")
    print(status_ii.stdout.rstrip())

    # ---- HALF (i): fleet-side resume launch refusal -----------------------
    send = sandbox.fleet("send", name, "please continue the task", check=False)
    refused_out = (send.stdout + send.stderr)
    assert send.returncode != 0, f"HALF (i) FAILED: resume was NOT refused:\n{refused_out}"
    assert "ceiling" in refused_out.lower(), f"refusal did not cite the ceiling:\n{refused_out}"
    after = sandbox.worker(name)
    assert after["status"] == "over_ceiling", f"worker not flagged over_ceiling: {after['status']}"
    status_i = sandbox.fleet("status", name, check=False)
    assert "over-ceiling" in status_i.stdout or "over_ceiling" in status_i.stdout

    print("\n================ HALF (i): FLEET-SIDE RESUME REFUSAL ================")
    print(f"`fleet send {name} ...` exit={send.returncode}; CLI output:")
    print("  " + refused_out.strip().replace("\n", "\n  "))
    print("status table (over-ceiling flag):")
    print(status_i.stdout.rstrip())

    # containment: bounded spend
    total = sum(w.get("cost_usd", 0.0) for w in sandbox.registry()["workers"].values())
    assert total <= _RUN_CEILING_USD, f"per-run ceiling exceeded: ${total:.4f}"
    print(f"\n[demo] run spend ${total:.4f} (ceiling ${_RUN_CEILING_USD:.2f}) hook_source={HOOK_SOURCE}")

    # retire the worker (no live turn is left running at end of test)
    sandbox.fleet("kill", name, check=False)
