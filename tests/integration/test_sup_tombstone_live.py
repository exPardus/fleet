"""three-tier §10.4 -- the ONE end-to-end integration test the decision record
asks for (docs/proposals/sup-tombstone-choreography.md §7, "Integration"):

  spawn a real gen-0 supervisor body -> `fleet kill supervisor` -> assert the
  graceful arm (`SUP-KILL-RELEASED`) -> boot a successor -> assert the
  claim-nonce §6.1 rule-1b `BOOT` journal entry (fresh claim, no `SEIZED`, no
  freeze window).

WHY THIS CANNOT BE A UNIT TEST. Every other §10.4 contract is pinned in
tests/test_sup_tombstone.py with fixtures. This one is not, because the whole
point of arm 1 is that FLEET CANNOT RELEASE THE CLAIM (B5) -- a real body must
receive the steer, run `fleet sup-release` with a nonce only it holds, and
exit. A fixture that writes the released claim itself proves the poll loop and
nothing about the contract the poll loop exists to serve.

GATING: tests/conftest.py auto-marks everything under tests/integration/ as
`live` and skips it unless FLEET_LIVE=1. This file never runs in an ordinary
`pytest -q`.

MODEL COMPLIANCE IS PART OF WHAT IS UNDER TEST, and it is also the flake
surface: the body must actually obey a steer. A failure here means either the
choreography is broken OR the model ignored an instruction, so every assertion
below reports the supervisor journal + claim state, which distinguishes the
two (a released claim with no `SUP-KILL-RELEASED` line = fleet's bug; no
`RELEASED` entry at all = the body never ran the verb).

CONTAINMENT: throwaway FLEET_HOME + throwaway project, exactly like
tests/integration/test_native_pin.py. The `claude` daemon is NOT scoped by
FLEET_HOME, so every sid this file dispatches is tracked and
`claude stop`+`claude rm`'d in teardown -- and never a sid it did not itself
dispatch. This suite never runs `claude daemon stop`/`uninstall`.

Budget: two haiku supervisor bodies, a handful of trivial turns -- cents.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import fleet          # repo copy, for pure helpers only (name_fs_stem)

pytestmark = pytest.mark.live

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("FLEET_LIVE_MODEL", "haiku").strip()

SPAWN_TIMEOUT = 420
# `fleet kill supervisor` blocks for at most SUPERVISOR_RELEASE_TIMEOUT_SECONDS
# (300s) inside arm 1, plus the stop + roster work. The subprocess ceiling must
# sit ABOVE fleet's own bound or the harness would fail the very "never blocks
# indefinitely" contract it is checking.
KILL_TIMEOUT = 420
CLI_TIMEOUT = 60
BOOT_WAIT = 240

CAMPAIGN = (
    "This is an automated integration test of the fleet lifecycle. After your "
    "boot ritual completes, take NO fleet actions of any kind: do not spawn, "
    "send, kill, or clean anything. Simply report that you have booted and then "
    "wait. If you later receive a FLEET LIFECYCLE STEER message, follow its "
    "instructions exactly and then end your turn."
)


def _claude(*args, timeout=30):
    return subprocess.run(["claude", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


class Sandbox:
    def __init__(self, home: Path, project: Path):
        self.home = home
        self.project = project
        self.fleet_py = home / "bin" / "fleet.py"
        self.dispatched_short_ids = []

    def env(self) -> dict:
        e = dict(os.environ)
        e["FLEET_HOME"] = str(self.home)
        e["PYTHONIOENCODING"] = "utf-8"
        # Run as a HUMAN SHELL: a sid inherited from the session that launched
        # pytest would arm `_supervisor_gate` against every verb here.
        e.pop("CLAUDE_CODE_SESSION_ID", None)
        e.pop("FLEET_WORKER", None)
        return e

    def fleet(self, *args, timeout=CLI_TIMEOUT, check=True):
        r = subprocess.run([sys.executable, str(self.fleet_py), *args],
                           env=self.env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        if check and r.returncode != 0:
            raise AssertionError(
                f"`fleet {' '.join(args)}` exited {r.returncode}\n"
                f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}\n"
                f"{self.diagnostics()}")
        return r

    def registry(self) -> dict:
        path = self.home / "state" / "fleet.json"
        if not path.exists():
            return {"workers": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def claim(self):
        path = self.home / "supervisor" / "INCARNATION"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def journal(self) -> str:
        path = self.home / "supervisor" / "JOURNAL.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def outcomes(self, key: str) -> list:
        p = self.home / "state" / "outcomes" / f"{key}.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()
                if ln.strip()]

    def supervisor_records(self) -> dict:
        return {n: r for n, r in self.registry()["workers"].items() if n.startswith("sup|")}

    def track_short(self, short_id):
        if short_id and short_id not in self.dispatched_short_ids:
            self.dispatched_short_ids.append(short_id)

    def track_all(self):
        for rec in self.registry()["workers"].values():
            self.track_short(rec.get("native_short_id"))
            for retired in rec.get("retired_sids", []) or []:
                self.track_short(retired[:8])

    def diagnostics(self) -> str:
        """Printed on EVERY failure: the two artifacts that separate "fleet's
        choreography is broken" from "the model ignored the steer"."""
        return (f"--- claim ---\n{json.dumps(self.claim(), indent=2)}\n"
                f"--- supervisor journal ---\n{self.journal()}\n"
                f"--- supervisor records ---\n"
                f"{json.dumps(self.supervisor_records(), indent=2)}\n")


@pytest.fixture(scope="module")
def sandbox():
    home = Path(tempfile.mkdtemp(prefix="fleet-tomb-home-"))
    project = Path(tempfile.mkdtemp(prefix="fleet-tomb-proj-"))
    sb = Sandbox(home, project)
    try:
        shutil.copytree(WORKTREE_ROOT / "bin", home / "bin")
        shutil.copy2(WORKTREE_ROOT / "worker-settings.template.json",
                     home / "worker-settings.template.json")
        for sub in ("state", "logs", "mailbox", "supervisor"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        (project / "README.md").write_text("tombstone-test throwaway\n", encoding="utf-8")

        init = sb.fleet("init", timeout=30)
        assert "wrote" in init.stdout, init.stdout

        # An ACTIVE GOALS with the §10.2/§13 bypass acknowledgement, so the
        # supervisor surfaces are live and sup-spawn does not warn.
        (home / "supervisor" / "GOALS.md").write_text(
            "# Supervisor GOALS\n\nstatus: active\n\n"
            "Bypass permissions acknowledged for this throwaway integration "
            "sandbox (three-tier §10.2/§13).\n\n"
            "## Goal\nRun the §10.4 tombstone integration test and nothing else.\n",
            encoding="utf-8")
        yield sb
    finally:
        sb.track_all()
        for short_id in sb.dispatched_short_ids:
            try:
                _claude("stop", short_id, timeout=30)
            except Exception:      # noqa: BLE001 -- teardown is best-effort
                pass
            try:
                _claude("rm", short_id, timeout=30)
            except Exception:      # noqa: BLE001
                pass
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def _wait_for_claim(sb, timeout=BOOT_WAIT, poll=5):
    """Poll until a LIVE (non-released) claim exists -- the body has run
    `sup-boot` and taken the claim."""
    deadline = time.monotonic() + timeout
    while True:
        claim = sb.claim()
        if isinstance(claim, dict) and claim.get("state") != "released" \
                and claim.get("session_id"):
            return claim
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"no live supervisor claim after {timeout}s -- the gen-0 body "
                f"never completed its boot ritual.\n{sb.diagnostics()}")
        time.sleep(poll)


def _spawn_supervisor(sb):
    r = sb.fleet("sup-spawn", "--task", CAMPAIGN, "--model", MODEL,
                 timeout=SPAWN_TIMEOUT)
    sb.track_all()
    return r


class TestGracefulKillEndToEnd:
    """One ordered sequence; each step depends on the previous one's live
    state, so they share the module-scoped sandbox and run in file order."""

    def test_1_gen0_body_boots_and_claims(self, sandbox):
        out = _spawn_supervisor(sandbox)
        assert "sup|" in out.stdout, out.stdout
        claim = _wait_for_claim(sandbox)
        assert claim["claimed_via"] == "fresh", sandbox.diagnostics()
        assert "BOOT" in sandbox.journal(), sandbox.diagnostics()

    def test_2_kill_supervisor_takes_the_graceful_arm(self, sandbox):
        """The contract under test: fleet steers, the BODY releases (B5), and
        only then is the body stopped and tombstoned."""
        before = sandbox.claim()
        holder_sid = before["session_id"]
        holder_name = next(n for n, r in sandbox.registry()["workers"].items()
                           if r.get("session_id") == holder_sid)
        sandbox.killed_incarnation = before["incarnation_id"]

        r = sandbox.fleet("kill", "supervisor", "--yes", timeout=KILL_TIMEOUT)
        combined = r.stdout + r.stderr

        # If the body ignored the steer, fleet correctly falls through to arm 2
        # -- a real and documented outcome, but NOT the contract this test
        # exists to prove, so it fails with the distinguishing evidence.
        assert "SUP-KILL-FROZEN" not in combined, (
            "kill fell through to arm 2 -- the body never released within "
            f"T_release.\n{combined}\n{sandbox.diagnostics()}")
        assert "SUP-KILL-RELEASED" in combined, f"{combined}\n{sandbox.diagnostics()}"

        claim = sandbox.claim()
        assert claim["state"] == "released", sandbox.diagnostics()
        assert "RELEASED" in sandbox.journal(), sandbox.diagnostics()

        rec = sandbox.registry()["workers"][holder_name]
        assert rec["status"] == "dead", sandbox.diagnostics()
        # G10: `claude stop` fires no Stop hook, so fleet's own tombstone is
        # the only record that this turn ended.
        # read_outcomes' dual-file shape: name-keyed (via the fs stem, since a
        # pipe is an invalid Windows filename) plus the sid-keyed fallback.
        kinds = {o["kind"] for o in sandbox.outcomes(holder_sid)} | \
                {o["kind"] for o in sandbox.outcomes(fleet.name_fs_stem(holder_name))}
        assert "killed" in kinds, (kinds, sandbox.diagnostics())

    def test_3_successor_boots_on_rule_1b(self, sandbox):
        """A released record is the ONE non-pathological door a fresh body
        has: rule 1b claims fresh, journals `BOOT`, writes no `SEIZED`, and
        pays no freeze window."""
        journal_before = sandbox.journal()
        assert "SEIZED" not in journal_before, sandbox.diagnostics()

        _spawn_supervisor(sandbox)
        claim = _wait_for_claim(sandbox)

        assert claim["claimed_via"] == "fresh", sandbox.diagnostics()
        # A NEW incarnation, not a resurrection of the killed one: the old
        # generation died with the released record (CN §6.3's key set), and
        # the successor mints its own at boot.
        assert claim["incarnation_id"] != sandbox.killed_incarnation, \
            sandbox.diagnostics()
        # The successor's BOOT entry is APPENDED after the predecessor's
        # RELEASED -- the two-entry shape §2 step 10 promises, with zero new
        # journal kinds.
        journal_after = sandbox.journal()
        assert len(journal_after) > len(journal_before), sandbox.diagnostics()
        tail = journal_after[len(journal_before):]
        assert "BOOT" in tail, sandbox.diagnostics()
        assert "SEIZED" not in journal_after, sandbox.diagnostics()
