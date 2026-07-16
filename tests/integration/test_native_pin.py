"""Pin-test tier (M-B T12, docs/specs/native-substrate.md "Re-verification"):
re-verifies the native `--bg` contract against a REAL, LIVE `claude` install
before fleet trusts it for a campaign. Six-step ordered sequence against two
real haiku `--bg` workers in a throwaway temp FLEET_HOME:

  1. dispatch + roster contract (closed 9-key schema, field-presence)
  2. Stop-hook outcome record (result text, tokens, model)
  3. fork-steer (G2b): idle `send` mints a new sid, old retires, hooks fire
     in the fork
  4. `claude stop` + fleet tombstone on a mid-turn interrupt (G10: no Stop
     hook fires on an external stop -- fleet's own tombstone is the only
     record)
  5. auto-archive (spec §5.1.2): TTL-eligible worker's sids get `claude rm`'d
     and its files moved
  6. `record_pin_pass` + `fleet doctor`'s pin-version check goes green

GATING: tests/conftest.py auto-marks every test under tests/integration/ as
`live` and skips the whole file unless FLEET_LIVE=1 is set -- this file
never runs in ordinary `pytest -q`.

CONTAINMENT: FLEET_HOME is a throwaway temp dir (state/logs/mailbox/outcomes
never touch the real fleet at C:/proga/claude-fleet or C:/proga/fleet-mb-t12).
The `claude` DAEMON ITSELF IS NOT SANDBOXED BY FLEET_HOME, though -- every
`--bg` dispatch here creates a REAL entry in the operator's real `claude
agents` roster. The module-scoped `sandbox` fixture tracks every sid this
run dispatches and `claude stop`+`claude rm`s each one in its teardown
(best-effort, idempotent per contract G12) -- it NEVER touches a sid it did
not itself dispatch.

Budget: two haiku workers, a handful of trivial turns -- cents (mirrors
tests/integration/test_live_smoke.py's per-run ceiling discipline, but this
suite has no dollar assertion of its own since native dispatch carries no
cost field at all, contract G3).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet

pytestmark = pytest.mark.live

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("FLEET_LIVE_MODEL", "haiku").strip()

# Closed roster schema per docs/specs/native-substrate.md "Roster contract".
ROSTER_SCHEMA_KEYS = {"pid", "id", "cwd", "kind", "startedAt",
                      "sessionId", "name", "status", "state"}

# Generous ceilings for a live daemon on a possibly-busy machine -- these are
# NOT the pin suite's actual expected latency (haiku turns here are trivial),
# just an outer bound so a genuinely wedged dispatch fails loud instead of
# hanging the suite.
# M2 (mc/pinfix review): a spawn that hits the never-attach wedge retry adds
# up to ~1 attach window (30s) + bounded cleanup (2x10s) + a second
# dispatch/join/attach pass on top of the ordinary path; theoretical
# worst-case with every subprocess at max timeout stacks toward ~570s but
# needs three simultaneous 60-120s stalls -- realistic wedge retries add
# 40-80s. 420s covers the realistic retry path with margin while still
# failing loud on a genuinely hung dispatch.
SPAWN_TIMEOUT = 420
WAIT_TIMEOUT = 220
CLI_TIMEOUT = 60


def _claude(*args, timeout=30):
    """Direct, unsandboxed `claude` CLI call (roster/version checks/teardown
    rm+stop) -- the daemon is global, never scoped by FLEET_HOME."""
    return subprocess.run(["claude", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _roster():
    r = _claude("agents", "--json", "--all", timeout=30)
    assert r.returncode == 0, f"claude agents --json --all failed: {r.stderr}"
    entries = json.loads(r.stdout)
    assert isinstance(entries, list), f"roster has unexpected shape: {type(entries)}"
    return entries


def _roster_entry(sid):
    for e in _roster():
        if isinstance(e, dict) and e.get("sessionId") == sid:
            return e
    return None


def _assert_roster_contract(entry):
    """docs/specs/native-substrate.md "Roster contract": closed 9-key schema
    (an unknown key is a live contract-drift FAIL, named explicitly) and the
    status/pid co-occurrence invariant read off the field-presence table --
    every observed state/status combination in that table has `status` and
    `pid` either BOTH present or BOTH absent, never one without the other."""
    unknown = set(entry) - ROSTER_SCHEMA_KEYS
    assert not unknown, (
        f"ROSTER CONTRACT DRIFT: unknown key(s) {sorted(unknown)} on entry "
        f"{entry} -- docs/specs/native-substrate.md needs re-verification"
    )
    assert entry.get("kind") == "background", entry
    assert ("status" in entry) == ("pid" in entry), (
        f"status/pid presence mismatch (contract field-presence table): {entry}"
    )
    assert entry.get("sessionId"), entry


_SHORT_ID_FROM_STDERR_RE = re.compile(r"short id ([0-9a-f]+)")


class Sandbox:
    def __init__(self, home: Path, project: Path):
        self.home = home
        self.project = project
        self.fleet_py = home / "bin" / "fleet.py"
        # Every SHORT id (8-char `id`, never the full session_id) this run
        # dispatches -- teardown target. `claude stop`/`claude rm` are
        # confirmed (this suite's own live run, test_1/test_4) to require
        # the SHORT id: `claude stop <full-uuid>` returns "No job matching"
        # (exit 1), while the same call with the 8-char short id succeeds.
        # bin/fleet.py's own `_stop_native_session`/`_rm_native_session`
        # pass the full session_id everywhere (see task-12-report.md finding
        # 2) -- this harness does NOT repeat that bug in its own cleanup.
        self.dispatched_short_ids = []

    def env(self) -> dict:
        e = dict(os.environ)
        e["FLEET_HOME"] = str(self.home)
        e["PYTHONIOENCODING"] = "utf-8"
        return e

    def fleet(self, *args, timeout=SPAWN_TIMEOUT, check=True):
        r = subprocess.run([sys.executable, str(self.fleet_py), *args],
                           env=self.env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        if check and r.returncode != 0:
            # A spawn can fail AFTER a real --bg session was already
            # dispatched (e.g. the roster-join window expiring) -- recover
            # the short id from fleet's own error message so teardown still
            # cleans up the orphaned live session instead of leaking it.
            m = _SHORT_ID_FROM_STDERR_RE.search(r.stderr or "")
            if m:
                self.track_short(m.group(1))
            raise AssertionError(
                f"`fleet {' '.join(args)}` exited {r.returncode}\n"
                f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
            )
        return r

    def registry(self) -> dict:
        path = self.home / "state" / "fleet.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def worker(self, name: str) -> dict:
        return self.registry()["workers"][name]

    def outcomes(self, key: str) -> list:
        p = self.home / "state" / "outcomes" / f"{key}.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def track_short(self, short_id):
        if short_id and short_id not in self.dispatched_short_ids:
            self.dispatched_short_ids.append(short_id)

    def track_worker_sids(self, name):
        """Track every short id a worker record carries (current + any
        retired-by-fork-steer) -- reads native_short_id directly since
        retired_sids only stores full session_ids."""
        try:
            rec = self.worker(name)
        except KeyError:
            return
        self.track_short(rec.get("native_short_id"))
        for retired_sid in rec.get("retired_sids", []) or []:
            self.track_short(retired_sid[:8])


def _wait_for_roster_gone_or_dead(sid, timeout=60, poll=3):
    """Poll until the roster shows `sid` as dead (state-only, no status/pid)
    or entirely absent -- the archive-eligibility gate 3 window
    (docs/specs/native-substrate.md: "process still briefly live" after a
    turn ends). Returns the last-seen entry (or None)."""
    deadline = time.monotonic() + timeout
    last = "not polled"
    while True:
        entry = _roster_entry(sid)
        last = entry
        dead_or_gone = entry is None or not ("status" in entry or "pid" in entry)
        if dead_or_gone:
            return entry
        if time.monotonic() >= deadline:
            return last
        time.sleep(poll)


@pytest.fixture(scope="module")
def sandbox():
    home = Path(tempfile.mkdtemp(prefix="fleet-pin-home-"))
    project = Path(tempfile.mkdtemp(prefix="fleet-pin-proj-"))
    sb = Sandbox(home, project)
    try:
        shutil.copytree(WORKTREE_ROOT / "bin", home / "bin")
        shutil.copy2(WORKTREE_ROOT / "worker-settings.template.json",
                     home / "worker-settings.template.json")
        for sub in ("state", "logs", "mailbox"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        (project / "README.md").write_text("pin-test throwaway project\n", encoding="utf-8")

        init = sb.fleet("init", timeout=30)
        assert "wrote" in init.stdout, init.stdout

        yield sb
    finally:
        # Teardown: stop (best-effort) then rm every SHORT id this run
        # dispatched. `claude rm` is idempotent on an already-gone id
        # (contract G12) -- never raises the suite's own exit code on a
        # partial cleanup. Also sweep any sid still tagged with our own
        # `fleet|pin-w*|` name prefix that isn't already tracked (belt and
        # braces against a tracking gap this run's own findings suggest
        # bin/fleet.py itself is prone to) -- NEVER touches a sid outside
        # that name prefix.
        try:
            extra = [e.get("id") for e in _roster()
                    if isinstance(e, dict)
                    and str(e.get("name", "")).startswith("fleet|pin-w")
                    and e.get("id")]
        except Exception:
            extra = []
        for short_id in extra:
            sb.track_short(short_id)

        for short_id in sb.dispatched_short_ids:
            try:
                _claude("stop", short_id, timeout=15)
            except Exception:
                pass
            try:
                _claude("rm", short_id, timeout=15)
            except Exception:
                pass
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


# ===========================================================================
# Step 1+2: dispatch, roster contract, Stop-hook outcome record
# ===========================================================================
def test_1_pin_dispatch_and_roster_contract(sandbox: Sandbox):
    r = sandbox.fleet("spawn", "pin-w1", "--dir", str(sandbox.project),
                      "--model", MODEL, "--mode", "accept",
                      "--task", "Reply with exactly: PIN-OK")
    rec = sandbox.worker("pin-w1")
    sid = rec.get("session_id")
    assert sid, f"pin-w1 has no session_id stamped after spawn:\n{r.stdout}"
    assert rec.get("native_short_id"), rec
    assert sid in r.stdout or rec.get("native_short_id") in r.stdout, r.stdout
    sandbox.track_worker_sids("pin-w1")

    entry = _roster_entry(sid)
    assert entry is not None, f"sid {sid} not found in claude agents --json --all"
    _assert_roster_contract(entry)


def test_2_pin_stop_hook_outcome(sandbox: Sandbox):
    sid = sandbox.worker("pin-w1")["session_id"]
    w = sandbox.fleet("wait", "pin-w1", "--timeout", "180", check=False)

    outcomes = sandbox.outcomes("pin-w1")
    matching = [o for o in outcomes if o.get("session_id") == sid and o.get("kind") == "result"]
    assert matching, (
        f"no 'result' outcome record for pin-w1/{sid} after `fleet wait` "
        f"(180s):\nwait stdout: {w.stdout}\nwait stderr: {w.stderr}\n"
        f"all outcomes: {outcomes}"
    )
    rec = matching[-1]
    assert rec.get("result_text") and "PIN-OK" in rec["result_text"], rec
    assert rec.get("input_tokens") is not None, rec
    assert rec.get("output_tokens") is not None, rec
    assert rec.get("model") and "haiku" in rec["model"].lower(), rec


# ===========================================================================
# Step 3: fork-steer (RATIFIED G2b) -- idle send mints a new sid
# ===========================================================================
def test_3_pin_fork_steer(sandbox: Sandbox):
    before = sandbox.worker("pin-w1")
    old_sid = before["session_id"]
    assert before["status"] == "idle", (
        f"pin-w1 must be idle before a fork-steer can fire: {before}"
    )

    s = sandbox.fleet("send", "pin-w1", "Reply with exactly: STEER-OK")
    assert "fork-steered" in s.stdout, s.stdout

    after = sandbox.worker("pin-w1")
    new_sid = after["session_id"]
    assert new_sid != old_sid, "fork-steer did not mint a new session_id"
    assert old_sid in after.get("retired_sids", []), after
    sandbox.track_worker_sids("pin-w1")

    # original session's roster entry survives untouched (G2b: fork, not
    # same-session mutation)
    old_entry = _roster_entry(old_sid)
    assert old_entry is not None, (
        f"original sid {old_sid} vanished from the roster after a fork-steer "
        "-- G2b says the original session is left untouched"
    )

    w = sandbox.fleet("wait", "pin-w1", "--timeout", "180", check=False)
    outcomes = sandbox.outcomes("pin-w1")
    matching = [o for o in outcomes
               if o.get("session_id") == new_sid and o.get("kind") == "result"]
    assert matching, (
        f"no 'result' outcome for the FORKED sid {new_sid} -- hooks did not "
        f"fire in the fork (settings did not survive --bg --resume):\n"
        f"wait stdout: {w.stdout}\nall outcomes: {outcomes}"
    )
    assert "STEER-OK" in matching[-1].get("result_text", ""), matching[-1]


# ===========================================================================
# Step 4: claude-stop + fleet tombstone (G10) -- no Stop hook on external stop
# ===========================================================================
def _spawn_pending_bash_worker(sandbox: Sandbox, name: str, sleep_seconds: int):
    sandbox.fleet(
        "spawn", name, "--dir", str(sandbox.project), "--model", MODEL,
        "--mode", "accept",
        "--task", f"Use the Bash tool to run: sleep {sleep_seconds}. "
                  "Then reply with exactly: DONE",
    )
    rec = sandbox.worker(name)
    sid = rec.get("session_id")
    assert sid, f"{name} has no session_id after spawn"
    sandbox.track_worker_sids(name)
    # cmd_spawn commits status="working" unconditionally on a successful
    # dispatch (never recomputed until something calls status/wait/send) --
    # under --mode accept (acceptEdits), a Bash tool call is never
    # auto-approved (docs/specs/native-substrate.md dispatch contract), so
    # this worker cannot finish on its own before the interrupt below lands.
    assert rec["status"] == "working", rec
    return sid


def test_4_pin_stop_no_hook_tombstone(sandbox: Sandbox):
    name = "pin-w2"
    sid = _spawn_pending_bash_worker(sandbox, name, sleep_seconds=60)

    i = sandbox.fleet("interrupt", name)
    assert "interrupted" in i.stdout.lower(), i.stdout

    rec = sandbox.worker(name)
    assert rec["status"] == "interrupted", rec

    outcomes = sandbox.outcomes(name)
    sid_outcomes = [o for o in outcomes if o.get("session_id") == sid]
    assert sid_outcomes, f"no tombstone written for {name}/{sid}: {outcomes}"
    assert sid_outcomes[-1]["kind"] == "interrupted", sid_outcomes
    assert sid_outcomes[-1]["result_text"] is None, sid_outcomes
    result_kinds = [o for o in sid_outcomes if o.get("kind") == "result"]
    assert not result_kinds, (
        f"G10 pin broken: a 'result' outcome exists for an externally-"
        f"stopped sid ({name}/{sid}) -- claude stop is documented to fire "
        f"NO Stop hook: {result_kinds}"
    )


# ===========================================================================
# Step 5: auto-archive (spec 5.1.2)
# ===========================================================================
def test_5_pin_archive_rm(sandbox: Sandbox):
    rec = sandbox.worker("pin-w1")
    assert rec["status"] == "idle", f"pin-w1 must be idle before archive: {rec}"
    sid = rec["session_id"]
    retired = list(rec.get("retired_sids", []))

    # gate 3 (docs/specs/native-substrate.md-derived _archive_eligible): the
    # roster entry for the CURRENT sid must be gone-or-dead. Live-verification
    # finding (T12 fix wave): an idle `--bg` session does NOT self-clear its
    # roster liveness (status+pid) within any short window on its own --
    # live-confirmed it stays fully live (status="idle", pid present) for
    # 75+ seconds with no sign of self-expiry. In real usage this is a
    # non-issue (archive only runs against workers idle for HOURS past the
    # TTL, by which point the real daemon session has long since exited on
    # its own); the pin suite's own compressed timeline is the only reason
    # it's visible here -- last_activity is fast-forwarded 25h below, but
    # the REAL daemon session backing it is only seconds old. Simulate what
    # 25 real hours would have already done to the process: stop every sid
    # (current + retired -- the fork-steer in test_3 left the OLD sid's
    # roster entry live per G2b, so it needs the same treatment) directly.
    for s in [sid, *retired]:
        _claude("stop", s[:8], timeout=15)
        _wait_for_roster_gone_or_dead(s, timeout=60)

    # Force last_activity back past the TTL (test-only direct registry
    # edit, as the task instructs -- recompute_worker_native never rewrites
    # last_activity for a native record, so this sticks through everything
    # else in this test).
    reg_path = sandbox.home / "state" / "fleet.json"
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["workers"]["pin-w1"]["last_activity"] = old_ts
    reg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    dry = sandbox.fleet("archive", "pin-w1", "--dry-run", check=False)
    assert "eligible" in dry.stdout, f"pin-w1 not archive-eligible:\n{dry.stdout}"

    a = sandbox.fleet("archive", "pin-w1")
    # cmd_archive's own summary line unconditionally reads "archived N
    # worker(s), skipped M" (bin/fleet.py:6337) -- a blanket "skipped" not
    # in stdout check can never pass even on full success (M=0). Live
    # verification (T12 fix wave) is the first real exercise of this exact
    # message; check for the PER-WORKER skip line ("pin-w1: skipped --
    # <reason>", fleet.py:6283) instead of the always-present summary word.
    assert "pin-w1: skipped" not in a.stdout, a.stdout
    assert "epoch" not in a.stdout.lower(), a.stdout

    after = sandbox.worker("pin-w1")
    assert after.get("archived_at"), after

    dest = sandbox.home / "logs" / "archive" / "pin-w1"
    assert dest.exists() and any(dest.iterdir()), (
        f"archive did not move any files into {dest}"
    )

    all_archived_sids = {sid, *retired}
    roster_after = _roster()
    for s in all_archived_sids:
        entry = next((e for e in roster_after if e.get("sessionId") == s), None)
        assert entry is None, (
            f"sid {s} still present in claude agents --json --all after "
            f"archive (rm did not work): {entry}"
        )


# ===========================================================================
# Step 6: record_pin_pass + fleet doctor pin-version check
# ===========================================================================
def test_6_pin_record_pass(sandbox: Sandbox):
    v = _claude("--version", timeout=15)
    assert v.returncode == 0, v.stderr
    version_text = (v.stdout or "") + (v.stderr or "")
    assert version_text.strip(), "claude --version produced no output"

    bin_dir = str(sandbox.home / "bin")
    script = (
        "import sys\n"
        f"sys.path.insert(0, {bin_dir!r})\n"
        "import fleet\n"
        f"fleet.record_pin_pass({version_text!r})\n"
    )
    r = subprocess.run([sys.executable, "-c", script], env=sandbox.env(),
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, f"record_pin_pass failed:\n{r.stdout}\n{r.stderr}"
    assert (sandbox.home / "state" / "pin-pass.json").exists()

    d = sandbox.fleet("doctor", check=False)
    combined = d.stdout + d.stderr
    assert "[PASS] pin-version" in combined, (
        f"fleet doctor pin-version check did not PASS after record_pin_pass:\n{combined}"
    )
