# M-B Native Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebase fleet's worker lifecycle onto the native `claude --bg` substrate (spec §5): task-file launch contract with short-id join, Stop-hook outcome records + outcome discriminator, usage-limit continuity rehomed to transcript-tail scanning (§5.1.1, operator ASAP directive), fork-steer per ratified G2(b), kill/interrupt via `claude stop` with tombstones, auto-archival (§5.1.2), agents-menu categories (§5.1.3), legacy coexistence, pin tests, and doctor checks — plus the four M-A handoff fast-follows.

**Architecture:** All logic stays in `bin/fleet.py` (stdlib-only, single file), one new hook script `bin/hooks/stop_outcome.py`. New machinery: an **outcome store** (`state/outcomes/<name>.jsonl`, written by the Stop hook and by fleet-side tombstones) is the discriminator's data source; a **native dispatch helper** (`dispatch_bg`) is the single choke point for spawn/steer/respawn/resume (task-file bootstrap per G8, short-id capture per G6 fallback, roster join by sid-prefix); a **native recompute** (`recompute_worker_native`) replaces PID probing for `dispatch_kind: "bg"` records, with the limit-wall transcript scan riding its no-fresh-outcome branch. Legacy (pre-pivot) records keep today's read paths but refuse mutation. `launch_turn` and the PID-probe chain stay in the file untouched for legacy reads — deletion is M-C.

**Tech Stack:** Python 3.13 stdlib; pytest (unit + hooks tiers, `FLEET_LIVE` integration tier); `claude` CLI 2.1.207 surface per `docs/specs/native-substrate.md`.

**Spec of record:** `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3 §3, §5, §5.1. Contract: `docs/specs/native-substrate.md` (cite, never re-derive). Both ratified — do not re-litigate G-verdicts.

## Build-order note (operator directive reconciliation)

The operator directive is "§5.1.1 usage-limit continuity FIRST after the launch contract itself." The limit-wall detection predicate is *"no fresh outcome record for the latest turn"* (spec §5.1.1, G11) — so the outcome record store and the native recompute that evaluates that predicate are **part of the launch contract's plumbing**, not features that jump the queue ahead of UL continuity. Task order: T1–T5 = launch contract + discriminator substrate, **T6 = UL continuity** (the first feature), then steering/kill/archival/etc. Nothing in T7+ lands before T6.

## Global Constraints

- Python is `py -3.13` (bare `python` resolves to 3.10). `bin/fleet.py` stays stdlib-only, single file.
- Never raw-kill a session; `claude stop <sid>` only (contract G10: raw `taskkill` triggers daemon auto-respawn under the same sid).
- `claude stop` on a not-naturally-ended session fires **no Stop hook** (contract G10) — every fleet-initiated stop writes its own tombstone outcome record.
- A limit wall is **silent**: no Stop hook, roster unchanged (contract G11). Detection = transcript-tail scan on the no-fresh-outcome path, never a hook.
- `--session-id` does not compose with `--bg` (contract G6, REFUTED): sid capture = short id from `--bg` stdout, joined to the full sid via `claude agents --json --all` **sid-prefix match** within a verify window. Never re-derive sid by polling roster for a name match (ai-title hazard).
- Prompts of unbounded size go through **task-file bootstrap** (contract G8): tiny fixed argv prompt "Read `<file>` and follow it exactly.", body in a fleet-written file. Never argv for size-unbounded content; never stdin as a prompt channel (stdin-dispatch wedge).
- Idle-worker steering = **fork** via `--bg --resume <sid>` (RATIFIED G2(b)): new sid minted, overlay restamps it as canonical, fresh `-n` rendered, old sid appended to `retired_sids`.
- Roster join is by **sid**; `name` is display-only. `startedAt` is unstable — never key on it. A sid is "live in roster" iff its entry carries `status` or `pid` (`_roster_live_sids`, already shipped). `state` and `status` are disjoint axes — never inspect `state` alone.
- USD cost is REFUTED-for-contract under `--bg` (G3): native records get **no** `--max-budget-usd` (refuse the flag), budget enforcement = token-ceiling hook only. Show tokens, not dollars, for native workers.
- No reads/writes of `~/.claude/daemon/` or `~/.claude/jobs/` — CLI + `--json` only. Reading `~/.claude/projects/*/<sid>.jsonl` transcripts IS sanctioned (contract Result/cost section; the G11 design requires it).
- Views (statusline `status_snapshot`, SessionStart hook, `sup-status`, doctor nag) never take `fleet.lock`, never spawn subprocesses, never write (`docs/specs/terminal-surface.md`) — **roster fetches happen only in authoritative commands** (`status`, `wait`, `send`, `spawn`, `archive`, `sup-boot`).
- Registry mutations + `append_event` under the same `with fleet_lock():`; subprocess work (dispatch, roster fetch, `claude stop`) outside the lock (F4 doctrine).
- Never auto-respawn on `dead-suspected` (never-demote-unknown; respawn is non-idempotent). Never mass-anything on a suspicious roster — freeze + surface (G9 epoch rule). `limited` is a sticky park: never demoted, never auto-respawned before the horizon, never archived.
- Legacy records (`dispatch_kind` absent) are **read-only**: `send`/`respawn`/`resume-limited`/`interrupt`/`attach` refuse with "pre-pivot worker — kill or clean via legacy path"; `kill`/`clean`/`status`/`peek`/`result` still work.
- Transcript JSONL keys (`message.usage`, `message.content[].text`, `isApiErrorMessage`, `apiErrorStatus`) are pin-tested observations at CLI 2.1.207, not a stable API — every parser feature-detects and fails soft.
- New constants (exact values): `NATIVE_JOIN_VERIFY_SECONDS = 60.0`, `NATIVE_JOIN_POLL_SECONDS = 3.0`, `NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0`, `OUTCOME_FRESH_SLACK_SECONDS = 5.0`, `ARCHIVE_TTL_HOURS_DEFAULT = 24.0`, `DEFAULT_CATEGORY = "fleet"`, `NATIVE_NAME_HINT_MAX = 40`, `OUTCOME_RESULT_TEXT_MAX = 20000`.
- New status literals (closed additions): `dead-suspected` (re-computable verdict, never sticky, never auto-respawned), `interrupted` (sticky; respawn-eligible).
- Path style: every path handed to the `claude` CLI or rendered into a prompt uses `Path.as_posix()` (Git-Bash backslash lesson, contract dispatch caveat). All subprocess calls are argv lists, no shell.
- Tests: unit/hooks tiers as today (`tests/conftest.py` tags by filename; autouse fixtures guard the real `~/.claude`). Full suite before each commit: `py -3.13 -m pytest -q`. Live tier: `FLEET_LIVE=1 py -3.13 -m pytest tests/integration/ -v`.
- Push `fleet-impl` and fast-forward `main` at every green milestone (operator standing directive).

## Shared test scaffolding (referenced by many tasks)

Tasks below use these fixtures — Task 1 creates them in `tests/test_native.py`; later tasks import from there (`from tests.test_native import ...` is NOT possible under pytest path rules, so later tasks that need them in other files copy the fixture — each task shows its own copy inline).

```python
# tests/test_native.py (created in Task 1)
"""M-B native-substrate tests: registry v2 fields, outcome store, dispatch
helper, discriminator, limit rehome, steering, stop/tombstones, archival."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with state/ and a rendered instance settings file."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="fleet|w1|task", state="working",
                      status="busy", pid=1234, kind="background"):
    """Roster entry per the contract field-presence table. Pass status=None /
    pid=None to model dead entries (keys OMITTED, not null)."""
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def seed_native_worker(home, name="w1", sid="aaaabbbb-1111-2222-3333-444455556666",
                       status="working", last_dispatch_at=None, **overrides):
    rec = fleet.new_worker_record(sid, "C:/proj", "do the thing", "accept",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = last_dispatch_at or _iso(NOW - timedelta(minutes=5))
    rec.update(overrides)
    data = {"workers": {name: rec}}
    fleet.save_registry(data)
    return rec
```

---

### Task 1: Registry v2 — native fields, new status literals, outcome record store, tombstones

**Files:**
- Modify: `bin/fleet.py` — `new_worker_record` (`:510`), new path helpers next to `journals_dir()` (`:72`), new "Outcome store (M-B)" section inserted immediately before the `# Supervisor (spec §4)` banner (`:4540`)
- Modify: `tests/test_core.py:111-134` (the 20-key schema pin)
- Create: `tests/test_native.py`
- Modify: `.gitignore` — confirm `state/` already covers `state/outcomes/` and `state/tasks/` (it does; no edit expected — verify only)

**Interfaces:**
- Consumes: `save_registry`/`load_registry`, `now_iso()`, `_write_json_atomic` (`:4597`), `state_dir()`, `logs_dir()`.
- Produces (every later task consumes these exactly):
  - `new_worker_record(..., dispatch_kind=None, category=None)` — two new keyword params; new record keys `dispatch_kind` (None|"bg"), `category` (str|None), `native_short_id` (str|None), `last_dispatch_at` (iso|None), `retired_sids` (list), `archived_at` (iso|None). Total schema = 26 keys.
  - `is_native(record: dict) -> bool` — `record.get("dispatch_kind") == "bg"`.
  - `refuse_if_legacy(name: str, record: dict, action: str) -> None` — raises `FleetCliError(f"{name}: pre-pivot worker -- {action} unavailable; kill or clean via legacy path")` when not native.
  - `outcomes_dir() -> Path` (`state/outcomes`), `outcome_path(key: str) -> Path` (`outcomes/<key>.jsonl`), `tasks_dir() -> Path` (`state/tasks`), `task_file_path(name: str) -> Path`, `archive_root() -> Path` (`logs/archive`), `pin_pass_path() -> Path` (`state/pin-pass.json`).
  - `append_outcome(key: str, record: dict) -> None` — one-line JSON append, parents created, `ensure_ascii=False`.
  - `read_outcomes(name: str, sid: str | None = None) -> list[dict]` — reads `outcomes/<name>.jsonl` **plus** `outcomes/<sid>.jsonl` (hook fallback when name-resolution failed), tolerant of junk lines; filtered to `session_id == sid` when sid given; sorted by `ts`.
  - `latest_outcome(name: str, sid: str) -> dict | None`.
  - `has_fresh_outcome(name: str, sid: str, since_iso: str) -> bool` — any record with matching sid and `ts >= since_iso` minus `OUTCOME_FRESH_SLACK_SECONDS`.
  - `write_tombstone_outcome(name: str, sid: str, kind: str) -> None` — kind ∈ `{"killed", "interrupted", "stopped"}`, appends `{"ts", "session_id", "kind", "result_text": None}`.
  - Outcome record schema (closed): `{"ts": iso, "session_id": str, "kind": "result"|"killed"|"interrupted"|"stopped", "result_text": str|None, "input_tokens": int|None, "output_tokens": int|None, "model": str|None, "transcript_path": str|None}`.
  - Constants: all values from Global Constraints.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_native.py` with the shared scaffolding above, then:

```python
class TestRegistryV2:
    def test_new_record_native_fields_default_off(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept")
        assert rec["dispatch_kind"] is None
        assert rec["category"] is None
        assert rec["native_short_id"] is None
        assert rec["last_dispatch_at"] is None
        assert rec["retired_sids"] == []
        assert rec["archived_at"] is None

    def test_new_record_bg_kind(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept",
                                      dispatch_kind="bg", category="camp5")
        assert rec["dispatch_kind"] == "bg" and rec["category"] == "camp5"

    def test_is_native_and_legacy_refusal(self, native_home):
        native = {"dispatch_kind": "bg"}
        legacy = {"session_id": "old"}  # pre-pivot record: key absent entirely
        assert fleet.is_native(native) is True
        assert fleet.is_native(legacy) is False
        with pytest.raises(fleet.FleetCliError, match="pre-pivot"):
            fleet.refuse_if_legacy("w1", legacy, "send")
        fleet.refuse_if_legacy("w1", native, "send")  # no raise


class TestOutcomeStore:
    def test_append_and_read_roundtrip(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1",
                                    "kind": "result", "result_text": "done ✓"})
        recs = fleet.read_outcomes("w1")
        assert recs[0]["result_text"] == "done ✓"

    def test_read_merges_sid_fallback_file_and_skips_junk(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        fleet.append_outcome("s1", {"ts": _iso(NOW + timedelta(seconds=9)),
                                    "session_id": "s1", "kind": "result"})
        fleet.outcome_path("w1").open("a", encoding="utf-8").write("{not json\n")
        recs = fleet.read_outcomes("w1", sid="s1")
        assert len(recs) == 2
        assert recs[-1]["ts"] > recs[0]["ts"]  # sorted by ts

    def test_read_filters_by_sid(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-sid", "kind": "result"})
        assert fleet.read_outcomes("w1", sid="new-sid") == []

    def test_has_fresh_outcome_boundary_and_slack(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        # record 3s OLDER than since still counts (5s slack)
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=3)))
        assert not fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=30)))
        assert not fleet.has_fresh_outcome("w1", "other", _iso(NOW))

    def test_tombstone_shape(self, native_home):
        fleet.write_tombstone_outcome("w1", "s1", "interrupted")
        rec = fleet.read_outcomes("w1", sid="s1")[-1]
        assert rec["kind"] == "interrupted" and rec["result_text"] is None
        with pytest.raises(ValueError):
            fleet.write_tombstone_outcome("w1", "s1", "exploded")
```

Update `tests/test_core.py` schema pin: extend the expected key set with `dispatch_kind, category, native_short_id, last_dispatch_at, retired_sids, archived_at` (26 keys total).

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_native.py tests/test_core.py -q`
Expected: FAIL — `TypeError: new_worker_record() got an unexpected keyword argument 'dispatch_kind'`, `AttributeError: module 'fleet' has no attribute 'is_native'`, schema-pin mismatch.

- [ ] **Step 3: Implement**

In `new_worker_record` add params `dispatch_kind=None, category=None` and append to the returned dict (after `limit_kind`):

```python
        # --- M-B native-substrate fields (spec §5; None/[] on legacy records) ---
        "dispatch_kind": dispatch_kind,      # "bg" = daemon-hosted; None = pre-pivot Popen
        "category": category,                # agents-menu category (spec §5.1.3)
        "native_short_id": None,             # short id from --bg stdout (G6 fallback)
        "last_dispatch_at": None,            # stamped at every dispatch/steer/resume;
                                             # anchor for the fresh-outcome predicate
        "retired_sids": [],                  # prior sids retired by fork-steer/respawn
        "archived_at": None,                 # set by auto-archival; hides from status
```

New section before the Supervisor banner:

```python
# --------------------------------------------------------------------------
# Outcome store (M-B, spec §5): terminal-outcome records per worker.
# Written by the Stop hook (kind="result") and by fleet-side tombstones
# (kill/interrupt/stop -- G10: an operator stop fires NO Stop hook).
# The outcome discriminator's only data source. JSONL, name-keyed, with a
# sid-keyed fallback file for hooks that could not resolve the name.
# --------------------------------------------------------------------------

OUTCOME_FRESH_SLACK_SECONDS = 5.0
OUTCOME_RESULT_TEXT_MAX = 20000
TOMBSTONE_KINDS = ("killed", "interrupted", "stopped")


def outcomes_dir() -> Path:
    return state_dir() / "outcomes"


def outcome_path(key: str) -> Path:
    return outcomes_dir() / f"{key}.jsonl"


def tasks_dir() -> Path:
    return state_dir() / "tasks"


def task_file_path(name: str) -> Path:
    return tasks_dir() / f"{name}.md"


def archive_root() -> Path:
    return logs_dir() / "archive"


def pin_pass_path() -> Path:
    return state_dir() / "pin-pass.json"


def is_native(record: dict) -> bool:
    return record.get("dispatch_kind") == "bg"


def refuse_if_legacy(name: str, record: dict, action: str) -> None:
    if not is_native(record):
        raise FleetCliError(
            f"{name}: pre-pivot worker -- {action} unavailable; "
            "kill or clean via legacy path"
        )


def append_outcome(key: str, record: dict) -> None:
    outcomes_dir().mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with outcome_path(key).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_outcomes(name: str, sid: str | None = None) -> list:
    records = []
    paths = [outcome_path(name)]
    if sid and sid != name:
        paths.append(outcome_path(sid))
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict):
                records.append(rec)
    if sid is not None:
        records = [r for r in records if r.get("session_id") == sid]
    records.sort(key=lambda r: str(r.get("ts", "")))
    return records


def latest_outcome(name: str, sid: str):
    recs = read_outcomes(name, sid=sid)
    return recs[-1] if recs else None


def has_fresh_outcome(name: str, sid: str, since_iso: str) -> bool:
    since = _parse_iso(since_iso)
    if since is None:
        return False
    threshold = since - timedelta(seconds=OUTCOME_FRESH_SLACK_SECONDS)
    for rec in read_outcomes(name, sid=sid):
        ts = _parse_iso(str(rec.get("ts", "")))
        if ts is not None and ts >= threshold:
            return True
    return False


def write_tombstone_outcome(name: str, sid: str, kind: str) -> None:
    if kind not in TOMBSTONE_KINDS:
        raise ValueError(f"unknown tombstone kind: {kind}")
    append_outcome(name, {"ts": now_iso(), "session_id": sid, "kind": kind,
                          "result_text": None})
```

(`timedelta` is already imported at the top of fleet.py; verify, add if missing.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_native.py tests/test_core.py -q` then full `py -3.13 -m pytest -q`
Expected: PASS, no regressions (the 26-key pin updated).

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_native.py tests/test_core.py
git commit -m "feat(native): registry v2 fields + outcome record store (M-B T1)"
```

---

### Task 2: Stop-hook outcome writer

**Files:**
- Create: `bin/hooks/stop_outcome.py`
- Modify: `worker-settings.template.json` — Stop hooks array gains a second command entry (outcome writer FIRST, mailbox blocker second — a block must not prevent the record)
- Test: `tests/test_hooks.py` (new class `TestStopOutcome`), `tests/test_hooks.py::TestTemplate` (template shape pin update)

**Interfaces:**
- Consumes: Stop-hook stdin payload — `session_id`, `transcript_path` (present 6/6 per contract), `last_assistant_message` (present 6/6, **value shape UNOBSERVED — feature-detect**).
- Produces: one JSONL record appended to `state/outcomes/<name>.jsonl` (name resolved read-only from `state/fleet.json` by matching `session_id`, exactly like `postcompact_journal._resolve_name`), fallback key = sid. Record schema per Task 1. Errors → one line to `state/hook-errors.log`, always `sys.exit(0)`.
- The script is standalone (no `import fleet`) like the other worker hooks; it duplicates the tiny helpers (`_fleet_home`, `_log_hook_error`, `_resolve_name`) per the established pattern in `bin/hooks/stop_mailbox.py` / `postcompact_journal.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_hooks.py` (uses existing helpers `run_hook`, `make_registry`, `make_transcript`, `read_hook_errors`):

```python
STOP_OUTCOME = HOOKS_DIR / "stop_outcome.py"


class TestStopOutcome:
    def _payload(self, home, sid="sid-1", last_msg="All done.", transcript=None):
        p = {"session_id": sid, "hook_event_name": "Stop"}
        if transcript is not None:
            p["transcript_path"] = str(transcript)
        if last_msg is not None:
            p["last_assistant_message"] = last_msg
        return json.dumps(p)

    def test_writes_result_record_named_by_registry(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        t = make_transcript(tmp_path, [
            {"type": "assistant",
             "message": {"model": "claude-haiku-4-5-20251001",
                         "usage": {"input_tokens": 11, "output_tokens": 7},
                         "content": [{"type": "text", "text": "All done."}]}},
            {"type": "system", "subtype": "bookkeeping"},
        ])
        run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=t), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["kind"] == "result"
        assert rec["session_id"] == "sid-1"
        assert rec["result_text"] == "All done."
        assert rec["output_tokens"] == 7 and rec["input_tokens"] == 11
        assert rec["model"] == "claude-haiku-4-5-20251001"

    def test_missing_last_assistant_message_falls_back_to_transcript(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        t = make_transcript(tmp_path, [
            {"type": "assistant",
             "message": {"content": [{"type": "text", "text": "from transcript"}]}},
            {"type": "attachment"},
        ])
        run_hook(STOP_OUTCOME, self._payload(tmp_path, last_msg=None, transcript=t), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["result_text"] == "from transcript"

    def test_unresolvable_name_falls_back_to_sid_key(self, tmp_path):
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)  # no registry
        run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=None), tmp_path)
        assert (tmp_path / "state" / "outcomes" / "sid-1.jsonl").exists()

    def test_truncates_huge_result_text(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        run_hook(STOP_OUTCOME, self._payload(tmp_path, last_msg="x" * 50000), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert len(rec["result_text"]) == 20000

    def test_garbage_stdin_logs_error_and_exits_zero(self, tmp_path):
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        proc = run_hook(STOP_OUTCOME, "{not json", tmp_path)
        assert proc.returncode == 0
        assert "stop_outcome" in read_hook_errors(tmp_path)
```

Also update `TestTemplate` to pin the Stop array = `[stop_outcome.py, stop_mailbox.py]` in that order.

- [ ] **Step 2: Run to verify fail** — `py -3.13 -m pytest tests/test_hooks.py -q` → FAIL (script missing).

- [ ] **Step 3: Implement `bin/hooks/stop_outcome.py`**

```python
"""Stop hook: append a terminal-outcome record (M-B, spec §5 outcome
discriminator). Result text = payload last_assistant_message (feature-detect;
value shape UNOBSERVED at 2.1.207) with transcript-tail fallback (last
type=="assistant" record's message.content[].text -- contract Result/cost).
Never blocks, never prints to stdout, always exits 0. Writes ONLY the outcome
file and hook-errors.log (sanctioned list, spec §3 amendment)."""
import json
import os
import sys
import time
from pathlib import Path

RESULT_TEXT_MAX = 20000


def _fleet_home() -> Path:
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def _log_hook_error(home: Path, message: str) -> None:
    try:
        state = home / "state"
        state.mkdir(parents=True, exist_ok=True)
        flat = " ".join(str(message).split())
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with (state / "hook-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"{ts} stop_outcome: {flat}\n")
    except OSError:
        pass


def _resolve_name(home: Path, sid: str):
    """READ-ONLY registry lookup (invariant 6: hooks never write fleet.json)."""
    try:
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        for name, rec in data.get("workers", {}).items():
            if isinstance(rec, dict) and rec.get("session_id") == sid:
                return name
    except (OSError, ValueError):
        pass
    return None


def _transcript_result(transcript_path):
    """(text, input_tokens, output_tokens, model) from the LAST assistant
    record -- the tail is bookkeeping, never 'read last line' (contract)."""
    text = tokens_in = tokens_out = model = None
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return text, tokens_in, tokens_out, model
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        parts = [c.get("text") for c in msg.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if parts:
            text = "\n".join(parts)
        usage = msg.get("usage")
        if isinstance(usage, dict):
            tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("output_tokens")
        if msg.get("model"):
            model = msg.get("model")
    return text, tokens_in, tokens_out, model


def main() -> int:
    home = _fleet_home()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        sid = payload.get("session_id")
        if not sid:
            return 0
        transcript_path = payload.get("transcript_path")
        text = payload.get("last_assistant_message")
        if not isinstance(text, str):
            text = None
        tokens_in = tokens_out = model = None
        if transcript_path:
            t_text, tokens_in, tokens_out, model = _transcript_result(transcript_path)
            if text is None:
                text = t_text
        if isinstance(text, str) and len(text) > RESULT_TEXT_MAX:
            text = text[:RESULT_TEXT_MAX]
        key = _resolve_name(home, sid) or sid
        out_dir = home / "state" / "outcomes"
        out_dir.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "session_id": sid, "kind": "result", "result_text": text,
                  "input_tokens": tokens_in, "output_tokens": tokens_out,
                  "model": model, "transcript_path": transcript_path}
        with (out_dir / f"{key}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 -- hooks never crash the turn
        _log_hook_error(home, repr(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In `worker-settings.template.json`, the Stop entry becomes two commands (outcome first):

```json
"Stop": [{"hooks": [
  {"type": "command", "command": "{{PYTHON}} {{FLEET_HOME}}/bin/hooks/stop_outcome.py"},
  {"type": "command", "command": "{{PYTHON}} {{FLEET_HOME}}/bin/hooks/stop_mailbox.py"}
]}]
```

(Match the template's exact existing JSON shape — copy the current structure and add the entry; placeholders stay quoted per the T8 quoting lesson.)

- [ ] **Step 4: Run** — `py -3.13 -m pytest tests/test_hooks.py -q` → PASS; full suite green.

- [ ] **Step 5: Re-render the live instance settings and commit**

Run: `py -3.13 bin/fleet.py init` (re-renders `state/worker-settings.json` — standing post-merge check, do it now so the working copy is truthful), then:

```bash
git add bin/hooks/stop_outcome.py worker-settings.template.json tests/test_hooks.py
git commit -m "feat(native): Stop-hook outcome record writer (M-B T2)"
```

---

### Task 3: Native dispatch helper — task-file bootstrap, `--bg` argv, short-id parse, roster join

**Files:**
- Modify: `bin/fleet.py` — new "Native dispatch (M-B)" section after the outcome store section
- Test: `tests/test_native.py`

**Interfaces:**
- Consumes: `mode_flags` (`:1104`), `resolve_claude_executable` (`:1131`), `_worker_env` (`:1220`), `_fetch_agents_roster` (`:4759`), `instance_settings_path` (`:136`), `task_file_path` (T1).
- Produces:
  - `class NativeDispatchError(Exception)` — message carries the short id when known (manual recovery).
  - `render_native_name(category, name, hint) -> str` — `f"{category}|{name}|{clean_hint}"`; hint sanitized (newlines→space, collapsed whitespace) and clipped to `NATIVE_NAME_HINT_MAX`; category defaults `DEFAULT_CATEGORY`.
  - `_parse_bg_short_id(stdout_text: str) -> str | None` — parses `backgrounded · <short-id> · <name>` tolerating surrounding hint lines; returns None if absent.
  - `_roster_entry_for(entries, sid) -> dict | None` — exact `sessionId` match.
  - `_join_roster_by_short_id(short_id, roster_fetch, sleep, verify_seconds) -> str | None` — polls roster every `NATIVE_JOIN_POLL_SECONDS`, returns the full `sessionId` that `.startswith(short_id)`; None on window expiry. Matches ANY entry incl. `state:"done"` — a fast worker completes before verify (spec §3 DOA rule).
  - `dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None, hint="", resume_sid=None, settings_path=None, run=subprocess.run, which=shutil.which, sleep=time.sleep, roster_fetch=None) -> dict` — returns `{"session_id", "short_id", "rendered_name"}`; raises `NativeDispatchError` on: missing claude exe, dispatch timeout/nonzero exit, unparseable stdout, join-window expiry. Writes `task_file_path(name)` with `prompt_body`; argv prompt is exactly `f"Read {task_file_path(name).as_posix()} and follow it exactly."`.
  - argv shape: `[exe, "--bg"] + (["--resume", resume_sid] if resume_sid else []) + ["-n", rendered_name, "--settings", settings_posix] + mode_flags(mode) + (["--model", model] if model) + [tiny_prompt]`; `run(..., cwd=str(cwd), env=_worker_env(name), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=NATIVE_DISPATCH_TIMEOUT_SECONDS)`.

- [ ] **Step 1: Write the failing tests**

```python
class TestRenderNativeName:
    def test_format_and_hint_clip(self):
        n = fleet.render_native_name("camp5", "w1", "port the parser\nto rust " + "x" * 60)
        cat, name, hint = n.split("|", 2)
        assert (cat, name) == ("camp5", "w1")
        assert "\n" not in hint and len(hint) <= 40

    def test_defaults(self):
        assert fleet.render_native_name(None, "w1", "") == "fleet|w1|"


class TestParseBgShortId:
    def test_parses_backgrounded_line(self):
        out = "some hint\nbackgrounded · deadbeef · fleet|w1|task\nattach hint\n"
        assert fleet._parse_bg_short_id(out) == "deadbeef"

    def test_missing_line_returns_none(self):
        assert fleet._parse_bg_short_id("error: whatever") is None


def _fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        import types
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


SID = "aaaabbbb-1111-2222-3333-444455556666"


def _roster_with(sid=SID, **kw):
    def fetch(**_):
        return True, [make_roster_entry(sid, **kw)]
    return fetch


class TestDispatchBg:
    def test_happy_path_returns_sid_and_writes_task_file(self, native_home):
        calls = []
        out = fleet.dispatch_bg("w1", "C:/proj", "BODY-1234", "accept",
                                model="haiku", category="camp5", hint="port it",
                                run=_fake_run_factory(calls=calls),
                                which=lambda _: "claude",
                                sleep=lambda s: None, roster_fetch=_roster_with())
        assert out["session_id"] == SID and out["short_id"] == "aaaabbbb"
        assert fleet.task_file_path("w1").read_text(encoding="utf-8") == "BODY-1234"
        argv, kwargs = calls[0]
        assert argv[:2] == ["claude", "--bg"]
        assert "--resume" not in argv
        assert argv[argv.index("-n") + 1].startswith("camp5|w1|")
        assert argv[-1] == f"Read {fleet.task_file_path('w1').as_posix()} and follow it exactly."
        assert "--model" in argv and "haiku" in argv
        assert kwargs["env"].get("FLEET_WORKER")
        assert "CLAUDE_CODE_SESSION_ID" not in kwargs["env"]
        assert kwargs["cwd"] == "C:/proj"

    def test_resume_sid_inserts_resume_flag(self, native_home):
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "steer", "accept", resume_sid="old-sid",
                          run=_fake_run_factory(calls=calls), which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv = calls[0][0]
        assert argv[argv.index("--resume") + 1] == "old-sid"

    def test_nonzero_exit_raises(self, native_home):
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(rc=1), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_unparseable_stdout_raises(self, native_home):
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(stdout="garbage"),
                              which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_join_window_expiry_raises_with_short_id(self, native_home):
        def empty_fetch(**_):
            return True, []
        with pytest.raises(fleet.NativeDispatchError, match="aaaabbbb"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=empty_fetch)

    def test_join_matches_done_entry_fast_completion(self, native_home):
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                                run=_fake_run_factory(), which=lambda _: "claude",
                                sleep=lambda s: None,
                                roster_fetch=_roster_with(state="done", status=None, pid=None))
        assert out["session_id"] == SID
```

- [ ] **Step 2: Run to verify fail** — `py -3.13 -m pytest tests/test_native.py -q` → FAIL (`NativeDispatchError` missing etc.).

- [ ] **Step 3: Implement**

```python
# --------------------------------------------------------------------------
# Native dispatch (M-B, spec §5): single choke point for every --bg launch.
# Task-file bootstrap (G8), short-id capture + sid-prefix roster join (G6
# fallback), fresh -n render per dispatch (G13 / spec §5.1.3).
# --------------------------------------------------------------------------

NATIVE_JOIN_VERIFY_SECONDS = 60.0
NATIVE_JOIN_POLL_SECONDS = 3.0
NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0
DEFAULT_CATEGORY = "fleet"
NATIVE_NAME_HINT_MAX = 40

_BG_SHORT_ID_RE = re.compile(r"backgrounded\s*[··]\s*(\S+)\s*[··]")


class NativeDispatchError(Exception):
    pass


def render_native_name(category, name: str, hint: str) -> str:
    cat = category or DEFAULT_CATEGORY
    clean = " ".join((hint or "").split())[:NATIVE_NAME_HINT_MAX]
    return f"{cat}|{name}|{clean}"


def _parse_bg_short_id(stdout_text: str):
    m = _BG_SHORT_ID_RE.search(stdout_text or "")
    return m.group(1) if m else None


def _roster_entry_for(entries, sid):
    for e in entries:
        if isinstance(e, dict) and e.get("sessionId") == sid:
            return e
    return None


def _join_roster_by_short_id(short_id, roster_fetch, sleep,
                             verify_seconds=NATIVE_JOIN_VERIFY_SECONDS):
    """Full sid whose prefix is the dispatch-printed short id. Matches done
    entries too -- a fast worker finishes before verify (spec §3)."""
    deadline = time.monotonic() + verify_seconds
    while True:
        ok, payload = roster_fetch()
        if ok:
            for e in payload:
                sid = e.get("sessionId") if isinstance(e, dict) else None
                if isinstance(sid, str) and sid.startswith(short_id):
                    return sid
        if time.monotonic() >= deadline:
            return None
        sleep(NATIVE_JOIN_POLL_SECONDS)


def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
                hint="", resume_sid=None, settings_path=None,
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
                roster_fetch=None):
    if roster_fetch is None:
        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    exe = resolve_claude_executable(which)
    settings = Path(settings_path) if settings_path else instance_settings_path()
    tasks_dir().mkdir(parents=True, exist_ok=True)
    task_path = task_file_path(name)
    task_path.write_text(prompt_body, encoding="utf-8")
    rendered = render_native_name(category, name, hint)
    tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
    argv = [exe, "--bg"]
    if resume_sid:
        argv += ["--resume", resume_sid]
    argv += ["-n", rendered, "--settings", settings.as_posix()]
    argv += mode_flags(mode)
    if model:
        argv += ["--model", model]
    argv.append(tiny_prompt)
    try:
        proc = run(argv, cwd=str(cwd), env=_worker_env(name),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=NATIVE_DISPATCH_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeDispatchError(f"--bg dispatch failed: {exc}") from exc
    if proc.returncode != 0:
        raise NativeDispatchError(
            f"--bg dispatch exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
    short_id = _parse_bg_short_id(proc.stdout or "")
    if not short_id:
        raise NativeDispatchError(
            f"could not parse short id from --bg stdout: {(proc.stdout or '').strip()[:400]}")
    sid = _join_roster_by_short_id(short_id, roster_fetch, sleep)
    if sid is None:
        raise NativeDispatchError(
            f"dispatched (short id {short_id}) but no roster entry joined "
            f"within {NATIVE_JOIN_VERIFY_SECONDS:.0f}s -- possible DOA; "
            f"recover manually via claude agents")
    return {"session_id": sid, "short_id": short_id, "rendered_name": rendered}
```

- [ ] **Step 4: Run** — targeted then full suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_native.py
git commit -m "feat(native): dispatch_bg -- task-file bootstrap, short-id join (M-B T3)"
```

---

### Task 4: `cmd_spawn` goes native

**Files:**
- Modify: `bin/fleet.py` — `cmd_spawn` (`:2261-2364`), argparse spawn parser (add `--category`; make `--max-budget-usd` refuse)
- Test: `tests/test_native.py` (new class), migrate spawn tests in `tests/test_cli.py` / `tests/test_core.py` that stub `popen` for `cmd_spawn` to stub `run`+roster instead

**Interfaces:**
- Consumes: `dispatch_bg` (T3), `new_worker_record(dispatch_kind="bg", category=...)` (T1), `read_outcomes` (T1), `compose_prompt` (`:1050`) — called with `sid=None` (see below), `_write_ceiling_file`, `fleet_lock`, `append_event`.
- Produces:
  - `compose_prompt(name, cwd, task, sid, journal_path=None)` gains: `sid=None` ⇒ skip the mailbox claim entirely, return `(prompt, None)` (fresh native spawn has no sid until join).
  - `cmd_spawn` native flow (this REPLACES the Popen path for all new spawns; the old body's launch code is deleted from `cmd_spawn` only — `launch_turn` itself stays for send/respawn until their tasks):
    1. `_require_instance_settings()`, dir/task validation as today; `args.max_budget_usd` set ⇒ `FleetCliError("no USD budget under native dispatch (contract G3) -- use --token-ceiling")`.
    2. Pre-claim under `fleet_lock`: `new_worker_record(session_id=None, ..., dispatch_kind="bg", category=args.category)`, `status="working"`, `last_dispatch_at=now_iso()`; `append_event("spawned", ...)`.
    3. Outside lock: `compose_prompt(name, cwd, task, None)` → `dispatch_bg(...)` with `hint=task`.
    4. On `NativeDispatchError` where a short id WAS captured (join expiry): before rollback, fetch roster once more and `read_outcomes(name)` — **fast-completion check**: if an outcome record exists whose sid starts with the short id, stamp that sid and commit as `idle` instead of rolling back. Otherwise rollback: re-lock, pop record, `append_event("spawn_failed", short_id=...)`, re-raise as `FleetCliError`.
    5. On success: re-lock, stamp `session_id`, `native_short_id`, `turns=1`, `last_activity`; `append_event("turn_started")`. Then `_write_ceiling_file(sid, token_ceiling)` (post-join by necessity — G6; the seconds-wide ceiling gap is accepted and documented in the docstring).
    6. Print `f"{name} {sid} (native bg, short id {short_id})"`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_native.py`)

```python
def _spawn_args(name="w1", d="C:/proj", task="do it", **kw):
    from types import SimpleNamespace
    base = dict(name=name, dir=d, task=task, mode="accept", model=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None,
                category=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestCmdSpawnNative:
    def test_spawn_native_stamps_sid_and_short_id(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(SID)]))
        rc = fleet.cmd_spawn(_spawn_args(), run=_fake_run_factory(),
                             which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["dispatch_kind"] == "bg"
        assert rec["session_id"] == SID and rec["native_short_id"] == "aaaabbbb"
        assert rec["status"] == "working" and rec["turns"] == 1
        assert rec["last_dispatch_at"] is not None

    def test_spawn_refuses_usd_budget(self, native_home):
        with pytest.raises(fleet.FleetCliError, match="token-ceiling"):
            fleet.cmd_spawn(_spawn_args(max_budget_usd=5.0),
                            run=_fake_run_factory(), which=lambda _: "claude",
                            sleep=lambda s: None)

    def test_dispatch_failure_rolls_back_preclaim(self, native_home, monkeypatch):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(_spawn_args(), run=_fake_run_factory(rc=1),
                            which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}

    def test_join_expiry_with_fast_completion_outcome_commits_idle(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        fleet.append_outcome("w1", {"ts": fleet.now_iso(),
                                    "session_id": SID, "kind": "result",
                                    "result_text": "already done"})
        rc = fleet.cmd_spawn(_spawn_args(), run=_fake_run_factory(),
                             which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle" and rec["session_id"] == SID

    def test_join_expiry_without_outcome_is_doa_rollback(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.FleetCliError, match="aaaabbbb"):
            fleet.cmd_spawn(_spawn_args(), run=_fake_run_factory(),
                            which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}
```

Note for the implementer: `cmd_spawn`'s signature changes from `(args, popen=..., get_process_info=None, which=..., sleep=...)` to `(args, run=subprocess.run, which=shutil.which, sleep=time.sleep)`. Grep for every existing caller/test of `cmd_spawn` (`grep -n "cmd_spawn" bin/ tests/`) and migrate each — the grep-receipt gate applies: list every hit in the task report.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** per the Interfaces block. `compose_prompt` change is 3 lines (guard the mailbox claim on `sid`). Keep the docstring's launch-contract comment updated: pre-claim now holds `session_id=None` + `last_dispatch_at` as the in-flight marker (the analog of `turn_pid=None`; `_launch_claim_expired` continues to bound it via `last_activity`).

- [ ] **Step 4: Run full suite** — migrate any spawn tests that broke; PASS.

- [ ] **Step 5: Commit** — `feat(native): cmd_spawn dispatches via --bg with DOA/fast-completion verdict (M-B T4)`

---

### Task 5: Outcome discriminator — native recompute, epoch freeze, `status`/`wait` integration

**Files:**
- Modify: `bin/fleet.py` — new `recompute_worker_native` beside `recompute_worker` (`:1604`); `cmd_status` (`:2388`), `wait_for_workers` (`:2596`), `_worker_flags` (`:1684`), `_print_status_table`/`_print_snapshot_table` (native rows show tokens not `$`; `archived` rows hidden unless `--all`)
- Test: `tests/test_native.py`

**Interfaces:**
- Consumes: roster entries (fetched ONCE per command via `_fetch_agents_roster`), `has_fresh_outcome`, `_roster_entry_for`, `transcript_limit_scan` — **stubbed in this task** as a module-level hook `_limit_scan_hook = None` (T6 replaces it with the real scan; when None, the branch resolves to `dead-suspected`).
- Produces:
  - `recompute_worker_native(name, record, roster_entries) -> dict` — verdict table (evaluated in order):
    1. Sticky statuses pass through: `dead`, `over_ceiling`, `limited`, `interrupted`, `attached`, `over_budget`.
    2. `session_id is None` (dispatch in flight): keep `working` while `not _launch_claim_expired(last_activity)`, else `dead`.
    3. Roster entry present and live (`status` or `pid` key): `status=="busy"` ⇒ `working`; `status=="waiting"` ⇒ `working` (flag `waiting-permission` via `_worker_flags`); `status=="idle"` ⇒ fresh-outcome check against `last_dispatch_at`: fresh ⇒ `idle`; not fresh ⇒ **investigate**: limit scan ⇒ `limited` (+ horizon fields + `limited_suspected` event at the caller) else `dead-suspected`.
    4. Roster entry present but dead (`state` only): fresh outcome ⇒ `idle`; not fresh ⇒ investigate (same as 3; covers `stopped`/`failed`/`done`-reaped).
    5. Roster-gone entirely: fresh outcome ⇒ `idle`; not fresh ⇒ investigate.
  - `native_epoch_suspicious(roster_ok, entries, workers) -> bool` — roster fetch failed, OR entries empty while any native record has `status=="working"` and a non-None `session_id`. When true, callers **freeze**: no native record is recomputed or written; a `EPOCH: roster suspicious -- ...` warning line prints (G9 rule; mirrors `supervisor_epoch_check` wording).
  - `cmd_status`: fetches roster once (outside lock), splits workers native/legacy; legacy rows keep today's `recompute_worker` probe path; native rows go through `recompute_worker_native`; conditional-commit pattern unchanged. `dead-suspected` is written back (it is a verdict, re-evaluated every run — an outcome record arriving later flips it to `idle`).
  - `wait_for_workers`: per poll, one roster fetch feeds all native names; terminal set for native = `{"idle", "dead", "dead-suspected", "limited", "over_ceiling", "interrupted"}`.

- [ ] **Step 1: Write the failing tests**

```python
class TestNativeRecompute:
    def _rec(self, native_home, status="working", **kw):
        return seed_native_worker(native_home, status=status, **kw)

    def test_roster_busy_stays_working(self, native_home):
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="busy")])
        assert out["status"] == "working"

    def test_roster_idle_with_fresh_outcome_goes_idle(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "idle"

    def test_roster_idle_without_outcome_is_dead_suspected(self, native_home):
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"

    def test_stale_outcome_from_prior_dispatch_does_not_vouch(self, native_home):
        rec = self._rec(native_home, last_dispatch_at=_iso(NOW))
        fleet.append_outcome("w1", {"ts": _iso(NOW - timedelta(hours=2)),
                                    "session_id": SID, "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"

    def test_predecessor_sid_record_does_not_vouch(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-dead-sid",
                                    "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "dead-suspected"

    def test_roster_gone_with_fresh_outcome_is_completed(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "idle"

    def test_sticky_statuses_pass_through(self, native_home):
        for sticky in ("dead", "limited", "over_ceiling", "interrupted"):
            rec = self._rec(native_home, status=sticky)
            out = fleet.recompute_worker_native("w1", rec, [])
            assert out["status"] == sticky

    def test_dead_suspected_is_reversible(self, native_home):
        rec = self._rec(native_home, status="dead-suspected",
                        last_dispatch_at=_iso(NOW - timedelta(minutes=5)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "idle"


class TestEpochFreeze:
    def test_fetch_failure_is_suspicious(self):
        assert fleet.native_epoch_suspicious(False, "no claude", {}) is True

    def test_empty_roster_with_live_native_worker_is_suspicious(self, native_home):
        rec = seed_native_worker(native_home)
        assert fleet.native_epoch_suspicious(True, [], {"w1": rec}) is True

    def test_empty_roster_with_no_native_workers_is_fine(self):
        assert fleet.native_epoch_suspicious(True, [], {}) is False
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**

```python
_limit_scan_hook = None  # T6 installs transcript_limit_scan here


NATIVE_TERMINAL_STATUSES = {"idle", "dead", "dead-suspected", "limited",
                            "over_ceiling", "interrupted"}
_NATIVE_STICKY = ("dead", "over_budget", "over_ceiling", "limited",
                  "interrupted", "attached")


def _investigate_no_outcome(name, record, updated):
    """No fresh outcome record for the current sid: limit wall (silent, G11)
    or genuinely dead. Scan the transcript tail; limit-shaped => park limited,
    else dead-suspected (surfaced, NEVER auto-respawned)."""
    scan = _limit_scan_hook
    if scan is not None:
        is_limit, reset_at, kind = scan(record.get("session_id"))
        if is_limit:
            updated["status"] = "limited"
            updated["limit_reset_at"] = reset_at
            updated["limit_kind"] = kind
            return updated
    updated["status"] = "dead-suspected"
    return updated


def recompute_worker_native(name, record, roster_entries):
    updated = dict(record)
    status = record.get("status")
    if status in _NATIVE_STICKY and status != "dead-suspected":
        pass_through = status
        if status != "dead-suspected":
            updated["status"] = pass_through
            return updated
    sid = record.get("session_id")
    if sid is None:
        if not _launch_claim_expired(record.get("last_activity")):
            updated["status"] = "working"
        else:
            updated["status"] = "dead"
        return updated
    since = record.get("last_dispatch_at") or record.get("created")
    entry = _roster_entry_for(roster_entries, sid)
    live = entry is not None and ("status" in entry or "pid" in entry)
    if live:
        rstatus = entry.get("status")
        if rstatus in ("busy", "waiting"):
            updated["status"] = "working"
            return updated
        # idle: turn ended -- did the Stop hook record an outcome?
        if has_fresh_outcome(name, sid, since):
            updated["status"] = "idle"
            return updated
        return _investigate_no_outcome(name, record, updated)
    # dead entry or roster-gone
    if has_fresh_outcome(name, sid, since):
        updated["status"] = "idle"
        return updated
    return _investigate_no_outcome(name, record, updated)


def native_epoch_suspicious(roster_ok, entries, workers) -> bool:
    if not roster_ok:
        return True
    if entries:
        return False
    return any(
        is_native(rec) and rec.get("status") == "working"
        and rec.get("session_id")
        for rec in workers.values() if isinstance(rec, dict)
    )
```

(Fix the sticky-guard logic when writing for real — the snippet above shows intent; implement as a clean early-return: `if status in _NATIVE_STICKY: updated["status"] = status; return updated`. `dead-suspected` is deliberately NOT in the sticky tuple.)

Wire `cmd_status`: after the existing snapshot-names-under-lock step, fetch roster once if any native workers exist; `native_epoch_suspicious` ⇒ print `EPOCH: roster suspicious -- native verdicts frozen (G9); legacy rows only` and skip native recompute entirely; else per-name dispatch to `recompute_worker_native` (native) / `recompute_worker` (legacy). When a native verdict flips to `limited`, `append_event("limited_suspected", ...)`; to `dead-suspected`, `append_event("dead_suspected", name)` (once per transition, not per rerun — guard on `record.get("status") != updated["status"]`). Update `_worker_flags`: `dead-suspected` → flag `investigate: no outcome record`; native `working` with roster `waiting` → `waiting-permission` (pass the roster entry in, or set a transient `waiting_for` field on the updated record).

Status table: for native rows render the `COST` column as `-` (USD dead per G3) and add tokens from `latest_outcome` if present.

- [ ] **Step 4: Run full suite; migrate broken status/wait tests.**

- [ ] **Step 5: Commit** — `feat(native): outcome discriminator + epoch freeze in status/wait (M-B T5)`

---

### Task 6: §5.1.1 usage-limit continuity — transcript-tail scan, park, fork-steer resume  ⟵ FIRST FEATURE

**Files:**
- Modify: `bin/fleet.py` — transcript helpers + `transcript_limit_scan` next to the UL1 block (`:1530-1601`); install `_limit_scan_hook`; `_resume_one_limited` (`:2914`) + `cmd_resume_limited` (`:3004`) native branch
- Modify: `skills/fleet/supervisor.md` — watchtower beat duties gain the limit-scan sweep
- Test: `tests/test_native.py`, plus keep every existing `tests/test_resilience.py` UL test green (legacy path untouched)

**Interfaces:**
- Consumes: `_parse_limit_signal` (`:1547` — reused verbatim for horizon/kind extraction), `_read_tail_lines` (`:662`), `read_outcomes` (transcript_path capture), `dispatch_bg` (T3), `_limit_reset_passed` (`:1578`).
- Produces:
  - `find_transcript_path(sid) -> Path | None` — prefer `transcript_path` from the latest outcome record of ANY kind for this sid (captured by the Stop hook on earlier turns); else glob `Path.home() / ".claude" / "projects" / "*" / f"{sid}.jsonl"`; None if nothing exists. (Reading transcripts is sanctioned — contract Result/cost; the G11 design requires path derivation because the limit turn fired no hook.)
  - `transcript_limit_scan(sid, transcript_path=None) -> tuple[bool, str|None, str|None]` — `(is_limit, reset_at_iso_or_None, kind)`. A record is limit-shaped **iff** it is a parseable JSON object with `isApiErrorMessage` truthy AND (`apiErrorStatus == 429` or `error == "rate_limit"`) — the structured gate observed verbatim in the G7 evidence (spike/m0/VERDICTS.md transcript record 201: `"error":"rate_limit","isApiErrorMessage":true,"apiErrorStatus":429`, message text `"You've hit your session limit — resets 4:40am (Asia/Qyzylorda)"`). Scans the last `_TAIL_READ_BYTES` window via `_read_tail_lines`, newest-first, stops at the first limit-shaped record. Horizon/kind extracted from the record's `message.content[].text` via the existing `_parse_limit_signal` — note the observed text carries a LOCAL-format time, not ISO, so `reset_at` will usually be None ⇒ park with null horizon, `resume-limited --force-now` is the realistic resume path. Never raises; any read/parse failure ⇒ `(False, None, None)`.
  - Module wiring: `_limit_scan_hook = transcript_limit_scan` (installed at definition, after both exist).
  - `_resume_one_limited` native branch: when `is_native(rec)` — re-validate `limited` under lock (FIX-1 guard stays), pre-claim `working`, then outside the lock: drain mailbox for the OLD sid into a steer body (`compose_prompt(name, cwd, "", old_sid)` — its mailbox claim machinery reused), body prefixed with `"The usage-limit reset horizon has passed. Continue the task from where you left off."`, then `dispatch_bg(..., resume_sid=old_sid, hint="resume past limit")` — **fork-steer per RATIFIED G2(b)**. Commit: restamp `session_id`/`native_short_id`, append old sid to `retired_sids`, `last_dispatch_at=now_iso()`, `turns += 1`, clear `limit_reset_at`/`limit_kind`, event `limit_resumed`. Rollback on failure → back to `limited` (existing pattern). Ceiling file re-pointed: `_write_ceiling_file(new_sid, token_ceiling)`.
  - `cmd_resume_limited` horizon gate unchanged (`_limit_reset_passed` / `--force-now`) — it now fronts both branches.

- [ ] **Step 1: Write the failing tests**

```python
def _write_native_transcript(home, sid, records):
    proj = home / ".claude" / "projects" / "C--proj"
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return p


LIMIT_RECORD = {
    "type": "assistant",
    "message": {"model": "<synthetic>", "role": "assistant",
                "content": [{"type": "text",
                             "text": "You've hit your session limit — resets 4:40am (Asia/Qyzylorda)"}]},
    "error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429,
}


class TestTranscriptLimitScan:
    def test_synthetic_429_record_detected(self, native_home, tmp_path):
        t = _write_native_transcript(tmp_path, SID,
                                     [{"type": "user"}, LIMIT_RECORD])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert is_limit is True
        assert reset_at is None  # observed text is local-format, not ISO
        assert kind == "session_5h"

    def test_iso_reset_in_text_is_parsed(self, native_home, tmp_path):
        rec = json.loads(json.dumps(LIMIT_RECORD))
        rec["message"]["content"][0]["text"] = \
            "Weekly limit reached. It resets at 2026-07-16T09:00:00Z."
        t = _write_native_transcript(tmp_path, SID, [rec])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert (is_limit, reset_at, kind) == (True, "2026-07-16T09:00:00Z", "weekly")

    # The load-bearing negatives (port of TestFix2): conversation text about
    # rate limits, MCP-tool 429s, infra errors -- none carry isApiErrorMessage.
    @pytest.mark.parametrize("rec", [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "the API returned 429 rate limit, retrying"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "usage limit exceeded on disk quota EDQUOT"}]}},
        {"type": "system", "subtype": "error", "text": "try again later"},
    ])
    def test_non_synthetic_shapes_do_not_park(self, native_home, tmp_path, rec):
        t = _write_native_transcript(tmp_path, SID, [rec])
        assert fleet.transcript_limit_scan(SID, transcript_path=t)[0] is False

    def test_missing_transcript_is_not_limit(self, native_home):
        assert fleet.transcript_limit_scan("no-such-sid")[0] is False


class TestLimitParkViaDiscriminator:
    def test_idle_no_outcome_limit_transcript_parks_limited(self, native_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        rec = seed_native_worker(native_home)
        _write_native_transcript(tmp_path, SID, [LIMIT_RECORD])
        out = fleet.recompute_worker_native("w1", rec,
                                            [make_roster_entry(SID, status="idle")])
        assert out["status"] == "limited"
        assert out["limit_kind"] == "session_5h"

    def test_limited_stays_parked_never_dead_suspected(self, native_home):
        rec = seed_native_worker(native_home, status="limited")
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "limited"


class TestNativeResumeLimited:
    def test_resume_fork_steers_and_restamps_sid(self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z")
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(new_sid)]))
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(
            args, run=_fake_run_factory(
                stdout=f"backgrounded · ccccdddd · fleet|w1|resume\n", calls=calls),
            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert old_sid in rec["retired_sids"]
        assert rec["status"] == "working"
        assert rec["limit_reset_at"] is None
        argv = calls[0][0]
        assert argv[argv.index("--resume") + 1] == old_sid

    def test_resume_failure_rolls_back_to_limited(self, native_home):
        seed_native_worker(native_home, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z")
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        fleet.cmd_resume_limited(args, run=_fake_run_factory(rc=1),
                                 which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"]["w1"]["status"] == "limited"
```

(`cmd_resume_limited`'s injectable params change from `popen`/`get_process_info` to `run`; legacy branch keeps working via the old machinery — thread both. Grep every caller.)

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**

```python
def find_transcript_path(sid):
    if not sid:
        return None
    # Prefer the path the Stop hook captured on an earlier turn of this sid.
    for rec in reversed(read_outcomes(sid, sid=sid) or []):
        tp = rec.get("transcript_path")
        if tp and Path(tp).exists():
            return Path(tp)
    try:
        candidates = sorted(Path.home().glob(f".claude/projects/*/{sid}.jsonl"))
    except OSError:
        return None
    return candidates[0] if candidates else None


def transcript_limit_scan(sid, transcript_path=None):
    """(is_limit, reset_at, kind) from the native transcript tail. Limit wall
    = synthetic 429 assistant record (G11): isApiErrorMessage + apiErrorStatus
    429 / error 'rate_limit'. Structured gate only -- conversation text about
    rate limits must never park (TestFix2 negatives). Fails soft."""
    path = Path(transcript_path) if transcript_path else find_transcript_path(sid)
    if path is None or not path.exists():
        return False, None, None
    try:
        lines = _read_tail_lines(path)
    except OSError:
        return False, None, None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not rec.get("isApiErrorMessage"):
            continue
        if rec.get("apiErrorStatus") == 429 or rec.get("error") == "rate_limit":
            msg = rec.get("message") or {}
            parts = [c.get("text", "") for c in (msg.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text"]
            reset_at, kind = _parse_limit_signal("\n".join(parts))
            return True, reset_at, kind
    return False, None, None


_limit_scan_hook = transcript_limit_scan
```

Note on `find_transcript_path`'s outcome lookup: the record may live under the NAME key, not the sid key — the real implementation takes `(name, sid)`: `find_transcript_path(name, sid)` reading `read_outcomes(name, sid=sid)`; `_investigate_no_outcome` passes both. Adjust the signature accordingly (tests above call the sid-glob path, which stands either way).

Then the `_resume_one_limited` native branch + `cmd_resume_limited` param migration per Interfaces. Also `skills/fleet/supervisor.md`: beat duties add — "each watchtower beat: `fleet status` (runs the outcome discriminator + silent-limit transcript scan; a limit wall shows as `limited`, G11), then `fleet resume-limited` when any horizon passed, then `fleet archive`". Boot-ritual section: `limited` workers are parked — the boot reconcile and the epoch freeze never demote them (both facts hold by construction: `limited` is sticky in `recompute_worker_native`, and the freeze path writes nothing).

- [ ] **Step 4: Run full suite** — `tests/test_resilience.py` must stay 100% green (legacy path untouched).

- [ ] **Step 5: Commit** — `feat(native): usage-limit continuity rehomed to transcript scan + fork-steer resume (M-B T6, spec 5.1.1)`

---

### Task 7: Steering — `send` fork-steer + native `respawn`

**Files:**
- Modify: `bin/fleet.py` — `cmd_send` (`:2703`), `cmd_respawn` (`:3437`)
- Test: `tests/test_native.py`; migrate native-relevant send/respawn tests

**Interfaces:**
- Consumes: `dispatch_bg`, `refuse_if_legacy`, `write_tombstone_outcome`, `_stop_native_session` (defined HERE, consumed also by T8): `_stop_native_session(sid, run=subprocess.run, which=shutil.which) -> bool` — `run([exe, "stop", sid], capture_output=True, text=True, timeout=30)`, True iff returncode 0; never raises.
- Produces:
  - Shared: `_restamp_after_steer(record, new_sid, short_id) -> None` (mutates in place: retire old sid to `retired_sids`, set `session_id`, `native_short_id`, `last_dispatch_at=now_iso()`, `turns += 1`).
  - `cmd_send` native flow: `refuse_if_legacy` first. Roster fetched once. Roster-live-busy/waiting ⇒ mailbox append (unchanged — hooks fire inside `--bg`, G1). Status idle ⇒ token-ceiling refusal check (USD check skipped for native), pre-claim `working` under lock, then outside: `append_mailbox(old_sid, message)` → `compose_prompt(name, cwd, "", old_sid)` (drains it) → steer body = that prompt → `dispatch_bg(..., resume_sid=old_sid, hint=message)` → commit restamp + ceiling re-point + event `steered` (fields: old/new sid). Print states the path taken: `"w1: fork-steered (new session <sid-prefix>) -- fork carries full transcript (G2b)"`. Rollback → `idle` + `restore_mailbox_claim`.
  - `cmd_send` on `dead-suspected` ⇒ refuse: `"w1: dead-suspected -- no outcome record for its last turn; inspect (fleet peek/result), then kill or respawn"`.
  - `cmd_respawn` native flow: fresh dispatch, NOT a resume (context reset is the point). Old roster-live session: refuse without `--force`; with `--force` ⇒ `_stop_native_session(old_sid)` + `write_tombstone_outcome(name, old_sid, "stopped")`. Then: `compose_prompt(name, cwd, task, old_sid, journal_path=journals_dir()/f"{name}.md")` (journal carry + old-sid mailbox drain — unchanged semantics) → `dispatch_bg` (plain) → new record via `new_worker_record(dispatch_kind="bg", category=carried)` preserving carried fields exactly as today minus `max_budget_usd` (native: always None) → old sid appended to `retired_sids` on the NEW record. No log rotation for native (no `logs/<name>.jsonl` exists); skip `_rotate_worker_log` when `is_native`.

- [ ] **Step 1: Write the failing tests** — mirror the resume-limited test shapes: `test_send_busy_native_appends_mailbox`, `test_send_idle_native_fork_steers_and_restamps` (assert `--resume old_sid` in argv, mailbox file drained, `retired_sids`), `test_send_dead_suspected_refuses`, `test_send_legacy_refuses`, `test_respawn_native_fresh_dispatch_carries_journal` (journal text present in task-file body; argv has NO `--resume`), `test_respawn_live_native_without_force_refuses`, `test_respawn_force_stops_old_and_tombstones` (fake run records `["claude","stop",old_sid]` call; tombstone kind `stopped` present). Full test code follows the established `_fake_run_factory` + `monkeypatch _fetch_agents_roster` pattern from T4/T6 — write each assertion explicitly, no shortcuts.

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement per Interfaces.** Grep-receipt gate: `grep -n "cmd_send\|cmd_respawn" bin/ tests/ skills/` — every caller/test migrated or confirmed legacy-scoped.
- [ ] **Step 4: Full suite green.**
- [ ] **Step 5: Commit** — `feat(native): fork-steer send + native respawn with journal carry (M-B T7)`

---

### Task 8: Kill/interrupt via `claude stop`, tombstone duty, `peek`/`result` rehome, utf-8 stdout

**Files:**
- Modify: `bin/fleet.py` — `cmd_kill` (`:3749`), `cmd_interrupt` (`:3134`), `cmd_result`/`cmd_peek` (near `:2557-2617`), `main()` (utf-8 reconfigure), `cmd_attach` (`:3213` — native refusal)
- Modify: `skills/fleet/` command docs for interrupt (grep `interrupt` under `skills/` and the plugin command dir; update every hit — the old contract line "The transcript survives; the worker does not die" is unsatisfiable under daemon sessions, spec §5)
- Test: `tests/test_native.py`

**Interfaces:**
- Consumes: `_stop_native_session` (T7), `write_tombstone_outcome`, `latest_outcome`, `find_transcript_path`.
- Produces:
  - `cmd_kill` native: launch-in-flight guard (`session_id is None` + claim fresh ⇒ refuse), `_confirm_destructive`, `_stop_native_session(sid)`, `write_tombstone_outcome(name, sid, "killed")`, status `dead`, event `killed`. Stop failure still marks dead + warns (parity with today).
  - `cmd_interrupt` native: `_stop_native_session(sid)`, tombstone kind `interrupted`, status `interrupted` (NOT `idle` — spec §5: an interrupted task is definitionally started; auto-anything forbidden), event `interrupted`. Print: `"w1: stopped via claude stop; marked interrupted. Respawn is a separate decision (fleet respawn w1)."`
  - `cmd_result` native: print `latest_outcome(name, sid)` of kind `result` — result_text + token/model line; no record ⇒ exit 1 with `"no outcome record for current session -- worker may be dead-suspected"`. Legacy records keep the old log-reading path.
  - `cmd_peek` native: parse `find_transcript_path(name, sid)` tail — render the last ~20 substantive records (assistant text first 200 chars, tool_use names, user text) — reuse `_read_tail_lines`; tolerant parsing.
  - `main()` gains, first statements: `for s in (sys.stdout, sys.stderr): try: s.reconfigure(encoding="utf-8", errors="replace") except Exception: pass` — kills the standing cp1252 crash (knowledge C2 ops entry).
  - `cmd_attach` native: refuse with `"native worker -- attach via the agents menu (Ctrl+T in claude) or: claude attach <sid>"` (M-B scope fence; native attach integration is M-C-or-later).

- [ ] **Step 1: Tests** — `test_kill_native_stops_and_tombstones`, `test_interrupt_native_marks_interrupted_not_idle`, `test_interrupt_tombstone_prevents_dead_suspected` (after interrupt, `recompute_worker_native` keeps `interrupted`, never flips), `test_result_native_prints_outcome`, `test_result_native_no_record_exit_1`, `test_peek_native_renders_transcript_tail`, `test_attach_native_refuses`, `test_main_reconfigures_stdout_utf8` (invoke `fleet.main(["status","--stale-ok"])` after seeding, assert no exception with a worker name containing `✓`... simplest: assert `sys.stdout.encoding.lower().startswith("utf")` after main ran — acceptable as a smoke). Full code per established patterns.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.** Doc updates in the same commit; grep receipts in the task report.
- [ ] **Step 4: Full suite green.**
- [ ] **Step 5: Commit** — `feat(native): claude-stop kill/interrupt + tombstones, peek/result rehome, utf-8 stdout (M-B T8)`

---

### Task 9: §5.1.2 auto-archival

**Files:**
- Modify: `bin/fleet.py` — new `cmd_archive` + `_archive_eligible`; argparse `archive` parser; `status_snapshot` + status tables hide `archived_at` rows unless `--all`
- Modify: `skills/fleet/supervisor.md` (beat duty already referenced in T6 — confirm wording), `skills/fleet/SKILL.md` command table
- Test: `tests/test_native.py`

**Interfaces:**
- Consumes: roster fetch, `read_outcomes`, `_stop_native_session` NOT used (archival never stops live sessions), `run` for `claude rm <id>` (G12 CONFIRMED — clean single-entry removal; UNOBSERVED against live sessions, hence the terminal-state gate below).
- Produces:
  - `ARCHIVE_TTL_HOURS_DEFAULT = 24.0`.
  - `_archive_eligible(record, roster_entries, now) -> tuple[bool, str]` — ALL must hold: `is_native`; status ∈ `{"idle", "dead", "interrupted"}`; roster entry for current sid is absent OR dead (no `status`/`pid` keys — never rm a live-process entry, G12 gap); an outcome record exists for the current sid (`read_outcomes(name, sid)` non-empty — a worker with NO record is `dead-suspected`, operator-decided, never auto-archived); `now - last_activity >= ttl`; status != `limited` (implied by the allowed set — assert anyway); `archived_at` is None. Returns `(False, reason)` naming the failed gate.
  - `cmd_archive(args, run, which)` — `fleet archive [name] [--ttl-hours F] [--dry-run]`: roster fetched once; per eligible worker: move `state/journals/<name>.md`, `state/outcomes/<name>.jsonl`, `state/tasks/<name>.md` into `logs/archive/<name>/` (`shutil.move`, collision-suffix `.1`); `claude rm <sid>` for the current sid AND every `retired_sids` entry (each failure non-fatal, reported); under lock set `archived_at=now_iso()`, event `archived`. Auto-DELETE stays forbidden: the registry entry SURVIVES as a tombstone (readable history); `fleet clean` remains the only deleter (CLAUDE.md irreversibility doctrine).
  - `--dry-run` prints the eligibility verdict per worker, mutates nothing.
  - `status_snapshot` / `_print_status_table`: rows with `archived_at` excluded by default; `--all` includes them flagged `archived`.
  - Interactive/foreign roster sessions: never touched — archival only ever `rm`s sids recorded in fleet's own registry.

- [ ] **Step 1: Tests** — `test_eligible_all_gates_pass`, parametrized `test_ineligible_reasons` (working; limited; no outcome record; ttl not elapsed; roster-live entry; legacy record; already archived), `test_archive_moves_files_and_rms_all_sids` (fake run collects `["claude","rm",...]` calls incl. retired sids; files land under `logs/archive/w1/`; registry entry survives with `archived_at`), `test_archive_dry_run_mutates_nothing`, `test_status_hides_archived_by_default`. Full code.
- [ ] **Step 2: Verify fail.** — **Step 3: Implement.** — **Step 4: Full suite.** 
- [ ] **Step 5: Commit** — `feat(native): auto-archival via claude rm, tombstoned overlay (M-B T9, spec 5.1.2)`

---

### Task 10: M-A handoff fast-follows

**Files:**
- Modify: `bin/fleet.py` — `cmd_sup_handoff_begin` (`:4991`), `cmd_sup_handoff_abort` (`:5095`)
- Test: `tests/test_supervisor.py`

**Interfaces (all four review findings, agreed deferrals from the M-A gate):**
1. **Abort flag on dispatch failure AND DOA** — `cmd_sup_handoff_begin`: both failure paths (`:5023-5032` dispatch fail; `:5047-5051` DOA) write `_write_json_atomic(handoff_abort_flag_path(), {"aborted_at": now_iso(), "reason": "dispatch-failed"|"successor-doa", "successor_sid": <sid-or-None>, "holder": inc})` before raising/returning — `_doctor_check_supervisor_handoff` (`:5187`) already FAILs on the flag; no doctor change needed.
2. **Abort sid cross-check** — `cmd_sup_handoff_abort`: when a HANDSHAKE exists and `handshake["session_id"] != args.successor_sid` ⇒ `FleetCliError("--successor-sid does not match HANDSHAKE sid <hs-sid> -- refusing to stop an unrelated session")`.
3. **Successor cwd** — the `run(argv, ...)` at `:5024` gains `cwd=str(FLEET_HOME)` (roster legibility).
4. **Short-id join** — replace the name-match join (`:5034-5045`) with: capture `short_id = _parse_bg_short_id(proc.stdout)` (T3 helper); join via `_join_roster_by_short_id(short_id, ...)`; keep the `pre_sids` exclusion as a belt-and-braces cross-check (joined sid must not be in `pre_sids`); fall back to the old name-join ONLY when stdout was unparseable (G6 fallback of the fallback — log it in the printed output).

- [ ] **Step 1: Tests** — `test_handoff_begin_dispatch_failure_writes_abort_flag`, `test_handoff_begin_doa_writes_abort_flag`, `test_handoff_abort_refuses_on_handshake_sid_mismatch`, `test_handoff_abort_proceeds_on_matching_or_absent_handshake`, `test_successor_dispatch_passes_fleet_home_cwd` (inspect fake `run` kwargs), `test_successor_join_uses_short_id_prefix` (roster has TWO fresh entries with the target name — ai-title collision scenario; the short-id prefix picks the right one). Follow the existing `TestHandoff` fixture patterns in `tests/test_supervisor.py:342`.
- [ ] **Step 2–4: fail → implement → full suite.**
- [ ] **Step 5: Commit** — `fix(supervisor): handoff abort-flag on both failure paths, sid cross-check, FLEET_HOME cwd, short-id join (M-B T10)`

---

### Task 11: Doctor + coexistence

**Files:**
- Modify: `bin/fleet.py` — new checks registered in `cmd_doctor`'s list (`:4508-4529`); `_doctor_check_stale_pids` (`:4206`) + `_doctor_check_unreadable_starttime` (`:4218`) skip native records; `_doctor_check_claude_agents` (`:4346`) learns overlay sids; `record_pin_pass(version)` helper
- Test: `tests/test_native.py` (doctor classes), `tests/test_supervisor.py` untouched

**Interfaces:**
- Produces:
  - `record_pin_pass(claude_version: str) -> None` — `_write_json_atomic(pin_pass_path(), {"claude_version": v, "passed_at": now_iso()})`. Called by the pin-test suite (T12).
  - `_doctor_check_pin_version(which, run)` — reads `pin_pass_path()`; no file ⇒ PASS-note `"no pin-test pass recorded -- run FLEET_LIVE=1 pytest tests/integration/test_native_pin.py"`; version mismatch vs live `claude --version` ⇒ **FAIL** `"claude <cur> != <pinned> at last pin pass -- transcript/roster contract unverified (contract §Re-verification)"`; match ⇒ PASS.
  - `_doctor_check_legacy_mix(workers)` — advisory PASS-note listing legacy (non-native, non-archived) worker names: `"N pre-pivot worker(s): ... -- read-only; kill or clean (spec §5.1 coexistence)"`; silent PASS when none.
  - `_doctor_check_stale_pids` / `_doctor_check_unreadable_starttime`: iterate legacy records only (`not is_native(rec)`).
  - `_doctor_check_claude_agents`: known sids = every registry `session_id` + all `retired_sids` — untracked report shrinks accordingly.
  - `_doctor_check_dead_suspected(workers)` — advisory: names any `dead-suspected` workers with the investigate hint.
- [ ] **Steps: tests (each check: PASS/FAIL/note shapes, native-skip proven by a native record with a bogus dead pid not flagging) → fail → implement → full suite → commit** — `feat(native): doctor pin-version gate, legacy-mix + dead-suspected advisories (M-B T11)`

---

### Task 12: Pin tests (FLEET_LIVE tier) + docs truth sweep

**Files:**
- Create: `tests/integration/test_native_pin.py`
- Modify: `skills/fleet/SKILL.md`, `skills/fleet/supervisor.md`, `docs/README.md`, `README.md` (native dispatch is now real — keep public docs true, standing rule), `docs/NEXT-SESSION.md` (rewrite for M-C)
- Test: the file itself, gated by `FLEET_LIVE` via the existing conftest integration-dir rule

**Interfaces:**
- Consumes: real `claude` CLI, haiku model, temp FLEET_HOME with rendered settings (`fleet init` against the temp home), `record_pin_pass`.
- Produces: the contract re-verification tier (contract §Re-verification is BINDING: run before any campaign; doctor T11 enforces version drift).

Test sequence (single module, ordered, each step asserts then feeds the next; total live cost ≈ one haiku worker, cents):
1. `test_pin_dispatch_and_roster_contract` — `fleet spawn pin-w1 --dir <tmp-proj> --model haiku --task "Reply exactly: PIN-OK"`; assert sid stamped; fetch roster; assert the closed 8-9-key schema on our entry (no unknown keys beyond the contract's set) and field-presence for its state.
2. `test_pin_stop_hook_outcome` — `fleet wait pin-w1 --timeout 180`; assert outcome record exists, `kind=="result"`, `result_text` contains `PIN-OK`, tokens present ⇒ transcript keys survived this CLI version.
3. `test_pin_fork_steer` — `fleet send pin-w1 "Reply exactly: STEER-OK"`; assert new sid ≠ old, old in `retired_sids`, roster still holds the old entry untouched (G2b), new outcome arrives with `STEER-OK`; assert hooks fired in the FORKED session (outcome record exists ⇒ Stop fired ⇒ settings survived the resume — the T3 UNOBSERVED flag, now pinned).
4. `test_pin_stop_no_hook_tombstone` — dispatch a slow worker (`"Use Bash to sleep 60 then reply DONE"` — under acceptEdits Bash sits pending ⇒ roster `waiting`), `fleet interrupt`; assert tombstone kind `interrupted`, status `interrupted`, and NO `result` record for that sid (G10 pinned).
5. `test_pin_archive_rm` — force `last_activity` back 25h, `fleet archive`; assert `claude agents --json --all` no longer lists the sids, files moved, registry tombstone survives.
6. `test_pin_record_pass` — all green ⇒ `record_pin_pass(<live claude --version>)`; assert `fleet doctor` pin check PASSes.

- [ ] **Step 1: Write the module** (full code at execution time — it is 90% fleet-CLI invocations via `subprocess.run([sys.executable, "bin/fleet.py", ...], env={FLEET_HOME: tmp})` following `tests/integration/test_live_smoke.py`'s harness patterns — read that file first and mirror its env/temp-home discipline).
- [ ] **Step 2: Run live**: `FLEET_LIVE=1 py -3.13 -m pytest tests/integration/test_native_pin.py -v` — expected PASS on this machine (claude 2.1.207+; if the CLI has drifted, the pin suite failing IS the deliverable — report exactly which contract fact broke, do not paper over).
- [ ] **Step 3: Docs truth sweep** — grep receipts required for each claim removed/added: `grep -rn "stream-json\|turn_pid\|stderr" skills/ README.md docs/README.md` and reconcile every hit that describes worker mechanics with the native reality (worker logs/`--max-budget-usd` mentions → token-ceiling + outcome records). `docs/NEXT-SESSION.md` rewritten: M-B complete → M-C (deletion + SPEC v3) next, with the M-C §6 deletion list and any deferred M-B residuals.
- [ ] **Step 4: Full suite + live tier green; `fleet doctor` clean.**
- [ ] **Step 5: Commit** — `test(native): pin-test tier + docs truth sweep; M-B complete (T12)`

---

## Coexistence deploy note (operator-facing, execute at merge time)

Spec §5.1: "M-B deploy requires an empty fleet or explicitly acknowledges the mix." Current fleet is EMPTY (0 workers at plan time) — the clean case. If workers exist at merge time: they render flagged `legacy`, all mutation refuses except kill/clean, doctor advises. No migration code is written — legacy records age out via kill/clean.

## Self-review record (skill checklist, run at authoring time)

- **Spec coverage:** §5 launch contract → T3/T4; outcome discriminator → T1/T2/T5; result/peek/cost → T2/T8; steering G2(b) → T7; kill/interrupt → T8; §5.1.1 → T6 (first feature after substrate, operator directive reconciled in header); §5.1.2 → T9; §5.1.3 → T3 (render) + T4 (`--category`) + T5 (display); coexistence → Global Constraints + T11 + every `refuse_if_legacy` site; §7 pin tests → T12; §7 doctor checks → T11; M-A fast-follows → T10. Epoch/G9 → T5. G8 task-file → T3. G10 tombstones → T7/T8. Gap check: `fleet clean` sweeping native artifacts (task files, outcome files) — folded into T9's file-move inventory; implementer extends `_remove_worker_files` in T9.
- **Placeholder scan:** T7 Step 1 and T12 Step 1 describe tests by name with required assertions rather than full listings — deliberate: their shapes are exact copies of fully-listed T4/T6 patterns and the live harness respectively; every named test lists its load-bearing assertions. No TBDs remain.
- **Type consistency:** `dispatch_bg` return dict keys (`session_id`/`short_id`/`rendered_name`) consistent across T3/T4/T6/T7/T10; outcome record schema fixed in T1 and used verbatim in T2/T5/T6/T8/T9/T12; `run=subprocess.run` replaces `popen` uniformly in migrated commands (T4 spawn, T6 resume-limited, T7 send/respawn, T9 archive, T10 handoff).
