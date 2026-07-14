# M-A Supervisor Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fleet supervisor's persistent identity layer (spec §4): journal checkpoint discipline, single-supervisor claim mechanics (`supervisor/INCARNATION`), one-code-path boot ritual, the id-verified handoff protocol, and the file-only nag — against TODAY's backend (no `--bg` worker-dispatch changes).

**Architecture:** All logic lands in `bin/fleet.py` (stdlib-only, single file) as a new "Supervisor (spec §4)" section: pure decision functions (claim/epoch — unit-testable without subprocess), atomic JSON state files under `supervisor/` (gitignored INCARNATION/HANDSHAKE; git-tracked GOALS/JOURNAL), and seven new flat CLI subcommands (`sup-boot`, `sup-checkpoint`, `sup-heartbeat`, `sup-status`, `sup-handoff-begin`, `sup-handoff-complete`, `sup-handoff-abort`). Views (SessionStart hook, `sup-status`, doctor nag) stay file-only per terminal-surface doctrine. The handoff successor is dispatched via `claude --bg` with task-file bootstrap (contract G8) — this is new supervisor machinery, not a change to fleet's worker spawn path.

**Tech Stack:** Python 3.13 stdlib only; pytest (unit tier); `claude` CLI (`agents --json --all`, `--bg`, `stop`) via injectable `subprocess.run`.

**Spec of record:** `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3 §4. Contract: `docs/specs/native-substrate.md` (M-0 verdicts — cite, never re-derive).

## Global Constraints

- Python is `py -3.13` (bare `python` is 3.10). `bin/fleet.py` stays stdlib-only, single file.
- Views (SessionStart hook, `/fleet:*`, `sup-status`, doctor nag line) never take `fleet.lock`, never probe a PID, never write, exit 0 (`docs/specs/terminal-surface.md`).
- Never raw-kill a session; `claude stop <id>` only (contract G10: raw `taskkill` triggers daemon auto-respawn under the same sid).
- `claude stop` on a not-naturally-ended session fires **no Stop hook** (contract G10) — never assume a stopped session journaled anything.
- Roster join is by **sid**; `name` is display-only (contract: ai-title can rewrite a forked session's name). `startedAt` is unstable — never key on it.
- A sid is "live in roster" iff its entry carries `status` or `pid` (contract roster table: those keys exist only while the backing process lives). Roster fetch always uses `claude agents --json --all`.
- Prompts of unbounded size go through task-file bootstrap (contract G8): tiny fixed argv prompt + body in a file; file paths rendered with forward slashes (`Path.as_posix()`).
- No reads/writes of `~/.claude/daemon/` or `~/.claude/jobs/` — CLI + `--json` only.
- Git-Bash `&` forbidden for background processes; all subprocess calls are direct `subprocess.run` argv lists (no shell).
- `supervisor/GOALS.md` is operator-owned: this plan never edits it.
- Journal is append-only, single-writer, claim-holder-only (spec §4). HANDSHAKE is a separate file precisely so a claimless successor never writes the journal.
- New constants (pin these exact values): `SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0` (S; > any sane beat period + margin — G7 observed ~173s beat cadence, supervisor beats are minutes-scale per GOALS frugality), `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0` (T), `SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0` (dispatch→roster-join window, G6 fallback).
- `sup-boot` exit codes: `0` = you hold the claim (fresh claim, seize, or handshake-written in handoff mode), `2` = refuse (read-only bystander), `3` = freeze (ambiguity — page operator). `1` = ordinary CLI error.
- Journal kinds (closed set): `BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT`.
- Tests: `tests/test_supervisor.py` auto-tags as `unit` tier (conftest tags by filename; anything not `test_hooks.py`/integration is unit). Never touch the real home — conftest's autouse fixture handles `Path.home()`; monkeypatch `fleet.FLEET_HOME` to `tmp_path` in every fixture.
- Run tests with: `py -3.13 -m pytest tests/test_supervisor.py -v` (full suite before each commit: `py -3.13 -m pytest -q`).

---

### Task 1: Supervisor state files — paths, constants, INCARNATION/HANDSHAKE IO, journal format

**Files:**
- Modify: `bin/fleet.py` — new section inserted immediately before the `# CLI: argparse wiring + main()` banner (currently line ~4537)
- Modify: `.gitignore` (repo root)
- Create: `supervisor/JOURNAL.md` (git-tracked seed)
- Test: `tests/test_supervisor.py` (new file)

**Interfaces:**
- Produces (later tasks consume exactly these):
  - `supervisor_dir() -> Path`, `goals_path() -> Path`, `incarnation_path() -> Path`, `handshake_path() -> Path`, `supervisor_journal_path() -> Path`, `handoff_abort_flag_path() -> Path`
  - `SUPERVISOR_CLAIM_STALE_SECONDS: float`, `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS: float`, `SUPERVISOR_ROSTER_VERIFY_SECONDS: float`, `SUPERVISOR_JOURNAL_KINDS: tuple`
  - `_write_json_atomic(path: Path, obj: dict) -> None`
  - `read_incarnation() -> dict | None` (lock-free-safe read), `write_incarnation(claim: dict) -> None` (atomic; caller must hold `fleet_lock`)
  - `read_handshake() -> dict | None`, `write_handshake(incarnation_id: str, session_id: str) -> None`
  - `mint_incarnation_id() -> str` (format `inc-<YYYYMMDDTHHMMSSZ>-<4hex>`)
  - `parse_supervisor_journal(text: str) -> list[dict]` (each: `{"ts","kind","inc","sid","body"}`), `supervisor_journal_entries() -> list[dict]`, `supervisor_journal_latest() -> dict | None`
  - `supervisor_journal_append(kind: str, inc: str, sid: str, body: str) -> None` (caller must hold `fleet_lock`; raises `ValueError` on unknown kind; creates JOURNAL.md with seed header if missing)
- INCARNATION schema: `{"incarnation_id": str, "session_id": str, "claimed_at": iso, "heartbeat_at": iso, "claimed_via": "fresh"|"seize"|"handoff"}`
- HANDSHAKE schema: `{"incarnation_id": str, "session_id": str, "written_at": iso}`
- Journal entry header (machine-parseable): `## <iso-ts> <KIND> inc=<id> sid=<sid>`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supervisor.py`:

```python
"""M-A supervisor identity tests (spec §4): state files, journal format,
claim/seizure/handshake state machine, boot ritual, handoff, nag."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with an active GOALS.md and seeded journal."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    return tmp_path


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class TestStateFiles:
    def test_incarnation_roundtrip_atomic(self, sup_home):
        claim = {"incarnation_id": "inc-20260714T110000Z-abcd", "session_id": "sid-1",
                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW), "claimed_via": "fresh"}
        fleet.write_incarnation(claim)
        assert fleet.read_incarnation() == claim
        # atomic: no .tmp litter left behind
        assert not list((sup_home / "supervisor").glob("*.tmp"))

    def test_read_incarnation_missing_and_corrupt(self, sup_home):
        assert fleet.read_incarnation() is None
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        assert fleet.read_incarnation() is None

    def test_handshake_roundtrip(self, sup_home):
        fleet.write_handshake("inc-x", "sid-9")
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-x" and hs["session_id"] == "sid-9"
        assert "written_at" in hs

    def test_mint_incarnation_id_format_and_uniqueness(self, sup_home):
        a, b = fleet.mint_incarnation_id(), fleet.mint_incarnation_id()
        assert a.startswith("inc-") and a != b
        import re
        assert re.fullmatch(r"inc-\d{8}T\d{6}Z-[0-9a-f]{4}", a)


class TestJournal:
    def test_append_creates_seed_and_parses_back(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "fresh claim")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "line one\nline two")
        text = fleet.supervisor_journal_path().read_text(encoding="utf-8")
        assert text.startswith("# Supervisor Journal")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["body"].strip() == "line one\nline two"
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT"

    def test_append_rejects_unknown_kind(self, sup_home):
        with pytest.raises(ValueError):
            fleet.supervisor_journal_append("SABOTAGE", "inc-a", "sid-1", "x")

    def test_parser_tolerates_prose_between_entries(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        with open(fleet.supervisor_journal_path(), "a", encoding="utf-8") as f:
            f.write("\nstray human note, not an entry header\n")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "next")
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["BOOT", "CHECKPOINT"]

    def test_empty_journal(self, sup_home):
        assert fleet.supervisor_journal_entries() == []
        assert fleet.supervisor_journal_latest() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_supervisor.py -v`
Expected: FAIL — `AttributeError: module 'fleet' has no attribute 'write_incarnation'` (and siblings).

- [ ] **Step 3: Implement in `bin/fleet.py`**

Insert immediately before the `# ---------------------------------------------------------------------------` / `# CLI: argparse wiring + main()` banner:

```python
# ---------------------------------------------------------------------------
# Supervisor identity (native-pivot spec §4, milestone M-A)
#
# Soul = git-tracked files (supervisor/GOALS.md operator-owned,
# supervisor/JOURNAL.md append-only). Body claim = supervisor/INCARNATION
# (machine-local, gitignored), written ONLY under fleet_lock, read lock-free
# (atomic os.replace writes make torn reads impossible). HANDSHAKE is a
# separate gitignored file so a claimless handoff successor never touches
# the journal (single-writer, claim-holder-only -- spec §4, no exceptions).
# ---------------------------------------------------------------------------

SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0   # T: handoff wait before abort (spec §4)
SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0   # dispatch -> roster-join window (contract G6 fallback)

SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)

_SUPERVISOR_JOURNAL_SEED = """# Supervisor Journal

Append-only checkpoint log (spec §4). Single writer: the current claim
holder, via `fleet sup-*` commands only. Never edit or delete entries.
Entry header format: `## <utc-iso> <KIND> inc=<incarnation-id> sid=<session-id>`
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.

<!-- entries below -->
"""


def supervisor_dir() -> Path:
    return FLEET_HOME / "supervisor"


def goals_path() -> Path:
    return supervisor_dir() / "GOALS.md"


def incarnation_path() -> Path:
    return supervisor_dir() / "INCARNATION"


def handshake_path() -> Path:
    return supervisor_dir() / "HANDSHAKE"


def supervisor_journal_path() -> Path:
    return supervisor_dir() / "JOURNAL.md"


def handoff_abort_flag_path() -> Path:
    """Doctor-visible flag written by sup-handoff-abort (spec §4 timeout
    branch). Lives in state/ (gitignored runtime), cleared by the next
    sup-handoff-begin or manually by the operator."""
    return state_dir() / "supervisor-handoff-aborted.json"


def _write_json_atomic(path: Path, obj: dict) -> None:
    """Atomic JSON write (temp + os.replace) so lock-free readers (views,
    SessionStart hook) can never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_incarnation() -> dict | None:
    """The current claim, or None when absent/unreadable. Lock-free-safe
    (writes are atomic); mutating callers still re-read under fleet_lock."""
    try:
        data = json.loads(incarnation_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_incarnation(claim: dict) -> None:
    """Caller MUST hold fleet_lock (single-supervisor invariant, spec §4)."""
    _write_json_atomic(incarnation_path(), claim)


def read_handshake() -> dict | None:
    try:
        data = json.loads(handshake_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_handshake(incarnation_id: str, session_id: str) -> None:
    _write_json_atomic(handshake_path(), {
        "incarnation_id": incarnation_id,
        "session_id": session_id,
        "written_at": now_iso(),
    })


def mint_incarnation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"inc-{stamp}-{uuid.uuid4().hex[:4]}"


_SUPERVISOR_ENTRY_RE = re.compile(
    r"^## (?P<ts>\S+) (?P<kind>[A-Z][A-Z-]*) inc=(?P<inc>\S+) sid=(?P<sid>\S+)\s*$")


def parse_supervisor_journal(text: str) -> list:
    """Parse JOURNAL.md into entry dicts {ts, kind, inc, sid, body}. Prose
    outside entry headers is tolerated: lines before the first header are
    the seed doc; lines after a header up to the next header are that
    entry's body (stray human notes ride along in the preceding body)."""
    entries = []
    current = None
    for line in text.splitlines():
        m = _SUPERVISOR_ENTRY_RE.match(line)
        if m:
            if current is not None:
                current["body"] = "\n".join(current["body"]).strip("\n")
                entries.append(current)
            current = {**m.groupdict(), "body": []}
        elif current is not None:
            current["body"].append(line)
    if current is not None:
        current["body"] = "\n".join(current["body"]).strip("\n")
        entries.append(current)
    return entries


def supervisor_journal_entries() -> list:
    try:
        text = supervisor_journal_path().read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_supervisor_journal(text)


def supervisor_journal_latest():
    entries = supervisor_journal_entries()
    return entries[-1] if entries else None


def supervisor_journal_append(kind: str, inc: str, sid: str, body: str) -> None:
    """Append one checkpoint entry. Caller MUST hold fleet_lock and MUST be
    the verified claim holder (enforced by the cmd layer via
    _require_claim_holder) -- spec §4: append-only, single-writer."""
    if kind not in SUPERVISOR_JOURNAL_KINDS:
        raise ValueError(f"unknown journal kind {kind!r}; allowed: {', '.join(SUPERVISOR_JOURNAL_KINDS)}")
    path = supervisor_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_SUPERVISOR_JOURNAL_SEED, encoding="utf-8")
    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{body.rstrip()}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
```

- [ ] **Step 4: Create `supervisor/JOURNAL.md`** with exactly the content of `_SUPERVISOR_JOURNAL_SEED` above (so the tracked seed and the auto-created seed are identical).

- [ ] **Step 5: Append to `.gitignore`:**

```
supervisor/INCARNATION
supervisor/HANDSHAKE
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_supervisor.py -v` → all PASS.
Then full suite: `py -3.13 -m pytest -q` → no regressions.

- [ ] **Step 7: Commit**

```bash
git add bin/fleet.py tests/test_supervisor.py supervisor/JOURNAL.md .gitignore
git commit -m "feat(supervisor): M-A state files -- INCARNATION/HANDSHAKE IO, journal format (spec §4)"
```

---

### Task 2: Pure decision logic — epoch check + claim decision

**Files:**
- Modify: `bin/fleet.py` (same supervisor section, after Task 1's helpers)
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: `SUPERVISOR_CLAIM_STALE_SECONDS`, `_parse_iso` (fleet.py:593)
- Produces:
  - `_roster_live_sids(entries: list) -> set` — sids whose entry carries `status` or `pid`
  - `supervisor_epoch_check(roster_ok: bool, payload) -> tuple[bool, str]` — `payload` is the entry list when `roster_ok`, else the failure reason string
  - `supervisor_claim_decision(claim: dict | None, live_sids: set, latest_entry: dict | None, now: datetime | None = None, stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS) -> tuple[str, str]` — verdict in `{"claim","refuse","seize","freeze"}` + reason

- [ ] **Step 1: Write the failing tests** (append to `tests/test_supervisor.py`):

```python
def _claim(inc="inc-old", sid="sid-old", beat=None):
    beat = beat or NOW - timedelta(seconds=60)
    return {"incarnation_id": inc, "session_id": sid,
            "claimed_at": _iso(NOW - timedelta(hours=2)),
            "heartbeat_at": _iso(beat), "claimed_via": "fresh"}


class TestClaimDecision:
    def test_no_claim_file_claims(self):
        v, _ = fleet.supervisor_claim_decision(None, set(), None, now=NOW)
        assert v == "claim"

    def test_live_in_roster_refuses(self):
        v, _ = fleet.supervisor_claim_decision(_claim(), {"sid-old"}, None, now=NOW)
        assert v == "refuse"

    def test_roster_gone_stale_heartbeat_seizes(self):
        c = _claim(beat=NOW - timedelta(seconds=3601))
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "seize"

    def test_roster_gone_fresh_heartbeat_freezes(self):
        c = _claim(beat=NOW - timedelta(seconds=120))
        v, reason = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"
        assert "G9" in reason or "daemon" in reason.lower()

    def test_fresher_foreign_checkpoint_refuses(self):
        # journal's latest entry is a DIFFERENT incarnation, newer than the
        # claim's heartbeat -> mid-transition, bystander must refuse (spec §4)
        c = _claim(beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=30)), "kind": "CHECKPOINT",
                  "inc": "inc-newer", "sid": "sid-newer", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "refuse"

    def test_own_incarnation_checkpoint_does_not_block_seize(self):
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=7100)), "kind": "CHECKPOINT",
                  "inc": "inc-old", "sid": "sid-old", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"

    def test_unparseable_heartbeat_freezes_never_seizes(self):
        c = _claim()
        c["heartbeat_at"] = "garbage"
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"


class TestEpochCheck:
    def test_roster_fetch_failure_freezes(self):
        ok, reason = fleet.supervisor_epoch_check(False, "claude not on PATH")
        assert ok is False and "claude not on PATH" in reason

    def test_empty_roster_is_suspicious(self):
        # the booting session itself is a claude session -- an --all roster
        # with ZERO entries means the daemon lost its memory (G9 shape)
        ok, reason = fleet.supervisor_epoch_check(True, [])
        assert ok is False

    def test_populated_roster_passes(self):
        ok, _ = fleet.supervisor_epoch_check(True, [{"sessionId": "s1", "status": "idle"}])
        assert ok is True


class TestRosterLiveSids:
    def test_status_or_pid_means_live(self):
        entries = [
            {"sessionId": "a", "status": "busy", "pid": 1, "state": "working"},
            {"sessionId": "b", "state": "done"},              # dead: no status/pid
            {"sessionId": "c", "status": "idle"},             # interactive: live
            {"sessionId": "d", "state": "working"},           # wedged, no pid/status: NOT live
            {"no_sid": True, "status": "idle"},               # malformed: skipped
        ]
        assert fleet._roster_live_sids(entries) == {"a", "c"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_supervisor.py -k "ClaimDecision or EpochCheck or RosterLive" -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement** (append to the supervisor section):

```python
def _roster_live_sids(entries: list) -> set:
    """Sids whose backing process is LIVE. Contract rule
    (docs/specs/native-substrate.md, roster contract): `status`/`pid` keys
    exist only while the process lives; a lingering `state:"done"` entry
    (observed surviving >=3h21m) must NOT count as live, or a finished
    predecessor would block every successor claim for hours."""
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and e.get("sessionId") and ("status" in e or "pid" in e)
    }


def supervisor_epoch_check(roster_ok: bool, payload):
    """Roster-epoch sanity check, run BEFORE any claim decision (spec §4).
    A failed or empty roster freezes the decision -- a daemon restart (G9)
    must never let a fresh boot seize a claim whose holder is alive."""
    if not roster_ok:
        return (False, f"roster unavailable ({payload}) -- freeze, never decide blind")
    if not payload:
        return (False, "roster is EMPTY -- not even this session is listed; "
                       "daemon restart suspected (G9). Freeze + page operator.")
    return (True, f"roster holds {len(payload)} entr{'y' if len(payload) == 1 else 'ies'}")


def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS):
    """Claim rules at boot (spec §4, verbatim order). Returns (verdict, reason);
    verdict in {"claim","refuse","seize","freeze"}. Pure function -- no IO."""
    if now is None:
        now = datetime.now(timezone.utc)
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    holder_sid = claim.get("session_id")
    if holder_sid in live_sids:
        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "
                          f"(sid {holder_sid}) is live in the roster")
    try:
        beat = _parse_iso(claim["heartbeat_at"])
    except (KeyError, TypeError, ValueError):
        return ("freeze", "claim heartbeat unreadable -- ambiguous; never seize on ambiguity")
    if latest_entry is not None and latest_entry.get("inc") != claim.get("incarnation_id"):
        try:
            entry_ts = _parse_iso(latest_entry["ts"])
        except (KeyError, TypeError, ValueError):
            entry_ts = None
        if entry_ts is not None and entry_ts > beat:
            return ("refuse", f"journal's latest checkpoint is a fresher incarnation "
                              f"({latest_entry.get('inc')}) -- transition in flight")
    age = (now - beat).total_seconds()
    if age > stale_seconds:
        return ("seize", f"holder roster-gone, heartbeat stale ({age:.0f}s > {stale_seconds:.0f}s)")
    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")
```

- [ ] **Step 4: Run tests to verify they pass**, then full suite.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_supervisor.py
git commit -m "feat(supervisor): epoch check + claim decision pure functions (spec §4 claim rules)"
```

---

### Task 3: Boot ritual — roster fetch, `fleet sup-boot` (fresh/refuse/seize/freeze + handoff-handshake mode)

**Files:**
- Modify: `bin/fleet.py` — supervisor section + `build_parser()` + `main()` dispatch
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: Task 1 IO helpers, Task 2 decision functions, `fleet_lock`, `status_snapshot`, `resolve_claude_executable`, `_write_text_tolerating_console_encoding` (fleet.py:2189), `current_caller_session`, `FleetCliError`
- Produces:
  - `_fetch_agents_roster(which=shutil.which, run=subprocess.run) -> tuple[bool, list | str]` — always `["agents", "--json", "--all"]`, 30s timeout, utf-8/replace decoding
  - `_render_boot_bundle(roster_entries: list, snap: dict, journal_entries: list) -> str`
  - `cmd_sup_boot(args, which=shutil.which, run=subprocess.run) -> int` — args: `sid: str|None`, `handoff_inc: str|None`. Exit 0/2/3 per Global Constraints.
  - Boot output contract (later tasks + skill rely on it): last line is `VERDICT: <verdict> -- <reason>`; on claim/seize the line before it is `INCARNATION: <inc-id>`.

- [ ] **Step 1: Write the failing tests** (append):

```python
def _fake_run_roster(entries):
    """Injectable subprocess.run double returning a roster JSON payload."""
    def run(argv, **kw):
        assert "--json" in argv and "--all" in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


def _fake_which(name):
    return "C:/fake/claude.cmd"


class TestSupBoot:
    def _boot(self, sup_home, entries, sid="sid-me", handoff=None):
        args = SimpleNamespace(sid=sid, handoff_inc=handoff)
        return fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster(entries))

    def test_fresh_claim_writes_incarnation_and_boot_checkpoint(self, sup_home, capsys):
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "fresh"
        entries = fleet.supervisor_journal_entries()
        assert entries[-1]["kind"] == "BOOT"
        out = capsys.readouterr().out
        assert "VERDICT: claim" in out and "GOALS" in out and "entry one" in out

    def test_refuse_is_strictly_read_only(self, sup_home, capsys):
        live_holder = _claim(sid="sid-holder")
        fleet.write_incarnation(live_holder)
        before_journal = fleet.supervisor_journal_entries()
        fleet.write_handshake("inc-inflight", "sid-x")  # in-flight handoff artifact
        rc = self._boot(sup_home, [{"sessionId": "sid-holder", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}])
        assert rc == 2
        assert fleet.read_incarnation() == live_holder          # untouched
        assert fleet.read_handshake() is not None               # bystander never deletes (spec §4)
        assert fleet.supervisor_journal_entries() == before_journal
        assert "VERDICT: refuse" in capsys.readouterr().out

    def test_seize_rewrites_claim_deletes_handshake_journals_seized(self, sup_home, capsys):
        stale = _claim(inc="inc-dead", sid="sid-dead",
                       beat=datetime.now(timezone.utc) - timedelta(hours=3))
        fleet.write_incarnation(stale)
        fleet.write_handshake("inc-orphan", "sid-orphan")  # crash-mid-handoff orphan
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "seize"
        assert fleet.read_handshake() is None                   # stale-HANDSHAKE hygiene
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "SEIZED" and "inc-dead" in latest["body"]

    def test_freeze_on_fresh_heartbeat_roster_gone(self, sup_home, capsys):
        fresh = _claim(sid="sid-gone", beat=datetime.now(timezone.utc) - timedelta(seconds=30))
        fleet.write_incarnation(fresh)
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 3
        assert fleet.read_incarnation() == fresh
        assert "VERDICT: freeze" in capsys.readouterr().out

    def test_freeze_on_empty_roster_even_with_no_claim(self, sup_home, capsys):
        rc = self._boot(sup_home, [])
        assert rc == 3
        assert fleet.read_incarnation() is None  # epoch freeze blocks even a fresh claim

    def test_handoff_mode_writes_handshake_touches_nothing_else(self, sup_home, capsys):
        holder = _claim(sid="sid-old")
        fleet.write_incarnation(holder)
        before_journal = fleet.supervisor_journal_entries()
        rc = self._boot(sup_home, [{"sessionId": "sid-old", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}],
                        handoff="inc-successor")
        assert rc == 0
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-successor" and hs["session_id"] == "sid-me"
        assert fleet.read_incarnation() == holder
        assert fleet.supervisor_journal_entries() == before_journal
        assert "handshake-written" in capsys.readouterr().out

    def test_no_sid_available_is_cli_error(self, sup_home):
        args = SimpleNamespace(sid=None, handoff_inc=None)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster([]))
```

- [ ] **Step 2: Run to verify failure** (`AttributeError: cmd_sup_boot`).

- [ ] **Step 3: Implement** (append to supervisor section):

```python
def _fetch_agents_roster(which=shutil.which, run=subprocess.run):
    """(ok, entries|reason). Sanctioned surface only: `claude agents --json
    --all` (contract: roster contract). utf-8/replace decoding -- roster
    names may carry emoji/`·` that cp1252 consoles mangle."""
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError:
        return (False, "claude executable not found on PATH")
    try:
        proc = run([exe, "agents", "--json", "--all"], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception as exc:  # noqa: BLE001 -- any spawn failure is one verdict
        return (False, f"`claude agents --json --all` failed: {exc}")
    if proc.returncode != 0:
        return (False, f"`claude agents --json --all` exit {proc.returncode}: "
                       f"{(proc.stderr or '').strip()[:200]}")
    try:
        entries = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        return (False, f"roster JSON unparseable: {exc}")
    if not isinstance(entries, list):
        return (False, f"roster has unexpected shape: {type(entries).__name__}")
    return (True, entries)


def _render_boot_bundle(roster_entries: list, snap: dict, journal_entries: list) -> str:
    """The boot ritual's read set, one string (spec §4: GOALS + JOURNAL tail
    + knowledge INDEX + roster + fleet status). M-A interim reconciliation =
    today's registry verdicts via status_snapshot -- the outcome
    discriminator's inputs don't exist until M-B."""
    out = ["=== SUPERVISOR BOOT BUNDLE ==="]
    try:
        goals = goals_path().read_text(encoding="utf-8").rstrip()
    except OSError:
        goals = "(supervisor/GOALS.md missing)"
    out += ["", "--- supervisor/GOALS.md ---", goals]
    out += ["", "--- supervisor/JOURNAL.md tail (last 5) ---"]
    tail = journal_entries[-5:]
    if tail:
        for e in tail:
            out.append(f"## {e['ts']} {e['kind']} inc={e['inc']} sid={e['sid']}")
            if e["body"].strip():
                out.append(e["body"].rstrip())
    else:
        out.append("(no checkpoints yet)")
    out += ["", "--- knowledge/INDEX.md (first 20 non-blank lines) ---"]
    try:
        idx = [ln for ln in (knowledge_dir() / "INDEX.md")
               .read_text(encoding="utf-8").splitlines() if ln.strip()][:20]
    except OSError:
        idx = ["(missing)"]
    out += idx
    live = _roster_live_sids(roster_entries)
    out += ["", f"--- native roster: {len(roster_entries)} entries, {len(live)} live ---"]
    out += ["", "--- fleet status (M-A interim reconciliation: registry verdicts) ---"]
    if snap.get("ok"):
        t = snap["totals"]
        out.append(f"{t['workers']} worker(s), ${t['cost_usd']:.2f} lifetime, {t['mail']} pending mail")
        for w in snap["workers"]:
            mail = f", {w['mail']} mail" if w["mail"] else ""
            out.append(f"  {w['name']}: {w['status']}, {w['turns']} turns, ${w['cost_usd']:.2f}{mail}")
    else:
        out.append(f"(registry unreadable: {snap.get('reason')})")
    return "\n".join(out)


def cmd_sup_boot(args, which=shutil.which, run=subprocess.run) -> int:
    """`fleet sup-boot [--sid SID] [--handoff-inc INC]` -- the ONE boot code
    path (morning / post-reboot / post-handoff, spec §4). Epoch check runs
    BEFORE the claim decision; the roster subprocess runs OUTSIDE fleet_lock
    (F4 doctrine: never hold the lock across a subprocess)."""
    caller_sid = getattr(args, "sid", None) or current_caller_session()
    if not caller_sid:
        raise FleetCliError("sup-boot: caller session unknown -- run from a Claude "
                            "session or pass --sid")
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    epoch_ok, epoch_reason = supervisor_epoch_check(roster_ok, payload)
    entries = payload if roster_ok else []
    live_sids = _roster_live_sids(entries)

    inc_line = None
    if getattr(args, "handoff_inc", None):
        # Successor mode: claim-pending, holds NO claim, takes no actions
        # (spec §4). Writes HANDSHAKE only -- never the journal.
        with fleet_lock():
            write_handshake(args.handoff_inc, caller_sid)
        verdict = "handshake-written"
        reason = (f"successor {args.handoff_inc} awaiting claim transfer; "
                  f"take NO fleet actions until sup-status shows your incarnation")
        rc = 0
    else:
        with fleet_lock():
            claim = read_incarnation()
            latest = supervisor_journal_latest()
            if not epoch_ok:
                verdict, reason = "freeze", f"epoch check failed: {epoch_reason}"
            else:
                verdict, reason = supervisor_claim_decision(claim, live_sids, latest)
            if verdict == "claim":
                inc = mint_incarnation_id()
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": "fresh"})
                supervisor_journal_append("BOOT", inc, caller_sid, f"fresh claim: {reason}")
                inc_line = inc
            elif verdict == "seize":
                inc = mint_incarnation_id()
                dead = claim.get("incarnation_id", "?")
                try:
                    # Stale-HANDSHAKE hygiene (spec §4): an orphan from a crash
                    # mid-handoff must never receive a claim transfer.
                    handshake_path().unlink()
                except FileNotFoundError:
                    pass
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": "seize"})
                supervisor_journal_append("SEIZED", inc, caller_sid,
                                          f"seized from {dead}: {reason}")
                inc_line = inc
            # refuse / freeze: strictly read-only.
        rc = {"claim": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]

    bundle = _render_boot_bundle(entries, status_snapshot(), supervisor_journal_entries())
    lines = [bundle, "", f"EPOCH: {'ok' if epoch_ok else 'FAIL'} -- {epoch_reason}"]
    if inc_line:
        lines.append(f"INCARNATION: {inc_line}")
    lines.append(f"VERDICT: {verdict} -- {reason}")
    _write_text_tolerating_console_encoding("\n".join(lines) + "\n")
    return rc
```

- [ ] **Step 4: Wire argparse + dispatch.** In `build_parser()` add (before `return parser`):

```python
    p_supboot = sub.add_parser("sup-boot", help="supervisor boot ritual: epoch check, claim decision, boot bundle (spec §4)")
    p_supboot.add_argument("--sid", help="override caller session id (default: CLAUDE_CODE_SESSION_ID)")
    p_supboot.add_argument("--handoff-inc", dest="handoff_inc",
                           help="handoff-successor mode: write HANDSHAKE with this incarnation id; no claim action")
```

In `main()` add alongside the other dispatch lines:

```python
        if args.command == "sup-boot":
            return cmd_sup_boot(args)
```

- [ ] **Step 5: Run tests, then full suite. Commit:**

```bash
git add bin/fleet.py tests/test_supervisor.py
git commit -m "feat(supervisor): sup-boot -- one-path boot ritual with epoch-gated claim/seize/refuse/freeze"
```

---

### Task 4: Holder-guarded writes — `sup-checkpoint`, `sup-heartbeat`, `sup-status`

**Files:**
- Modify: `bin/fleet.py` — supervisor section + `build_parser()` + `main()`
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: Task 1 IO, `fleet_lock`, `current_caller_session`, `_read_task_arg` (fleet.py:1926), `FleetCliError`
- Produces:
  - `_require_claim_holder(sid_override=None) -> tuple[dict, str]` — `(claim, caller_sid)`; raises `FleetCliError` unless the caller IS the claim holder. **Caller must hold `fleet_lock`.**
  - `cmd_sup_checkpoint(args) -> int` — args: `body: str` (supports `@file` via `_read_task_arg`), `kind: "CHECKPOINT"|"PROPOSAL"`, `sid: str|None`. Journals + refreshes heartbeat.
  - `cmd_sup_heartbeat(args) -> int` — args: `sid`. Heartbeat only, no journal growth.
  - `cmd_sup_status(args) -> int` — args: `json: bool`. Read-only, **no lock** (view). JSON keys: `goals_active, incarnation, heartbeat_age_seconds, handshake, abort_flag, nag`.
- Note: in THIS task `cmd_sup_status` emits the JSON contract above **minus the `nag` key**; Task 6 adds `nag` (it owns `supervisor_status_line`). This task DOES implement `supervisor_goals_active()` (sup-status needs it); Task 6 consumes it.

- [ ] **Step 1: Write the failing tests** (append):

```python
class TestCheckpointHeartbeat:
    def _hold(self, sid="sid-me", inc="inc-me"):
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW),
                                 "claimed_via": "fresh"})

    def test_checkpoint_appends_and_refreshes_heartbeat(self, sup_home):
        self._hold()
        old_beat = fleet.read_incarnation()["heartbeat_at"]
        args = SimpleNamespace(body="did a thing", kind="CHECKPOINT", sid="sid-me")
        assert fleet.cmd_sup_checkpoint(args) == 0
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT" and latest["body"] == "did a thing"
        assert latest["inc"] == "inc-me"
        assert fleet.read_incarnation()["heartbeat_at"] >= old_beat

    def test_non_holder_refused_journal_untouched(self, sup_home):
        self._hold(sid="sid-holder")
        args = SimpleNamespace(body="intruder", kind="CHECKPOINT", sid="sid-intruder")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)
        assert fleet.supervisor_journal_entries() == []

    def test_checkpoint_without_any_claim_refused(self, sup_home):
        args = SimpleNamespace(body="x", kind="CHECKPOINT", sid="sid-me")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)

    def test_heartbeat_refreshes_without_journal_growth(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-me")
        assert fleet.cmd_sup_heartbeat(args) == 0
        assert fleet.supervisor_journal_entries() == []
        assert fleet.read_incarnation()["heartbeat_at"] is not None


class TestSupStatus:
    def test_json_shape(self, sup_home, capsys):
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": _iso(NOW), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        args = SimpleNamespace(json=True)
        assert fleet.cmd_sup_status(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["goals_active"] is True
        assert data["incarnation"]["incarnation_id"] == "inc-me"
        assert data["heartbeat_age_seconds"] < 60
        assert data["handshake"] is None and data["abort_flag"] is False

    def test_no_claim_human_output(self, sup_home, capsys):
        args = SimpleNamespace(json=False)
        assert fleet.cmd_sup_status(args) == 0
        assert "no claim" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement:**

```python
def _require_claim_holder(sid_override=None):
    """(claim, caller_sid) iff the caller holds the claim; FleetCliError
    otherwise. Enforces spec §4's journal single-writer rule at the only
    write chokepoint. Caller MUST already hold fleet_lock."""
    claim = read_incarnation()
    if claim is None:
        raise FleetCliError("no supervisor claim exists -- run `fleet sup-boot` first")
    caller = sid_override or current_caller_session()
    if not caller:
        raise FleetCliError("caller session unknown -- pass --sid or run from a Claude session")
    if caller != claim.get("session_id"):
        raise FleetCliError(
            f"caller sid {caller} does not hold the claim (holder: "
            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
            f"the journal is single-writer, claim-holder-only (spec §4)")
    return claim, caller


def cmd_sup_checkpoint(args) -> int:
    """`fleet sup-checkpoint <body|@file> [--kind CHECKPOINT|PROPOSAL] [--sid S]`.
    Every checkpoint refreshes the heartbeat (spec §4: 'the holder refreshes
    at every checkpoint/beat')."""
    body = _read_task_arg(args.body)
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        supervisor_journal_append(args.kind, claim["incarnation_id"], caller, body)
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"checkpointed ({args.kind}) as {claim['incarnation_id']}; heartbeat refreshed")
    return 0


def cmd_sup_heartbeat(args) -> int:
    """`fleet sup-heartbeat [--sid S]` -- beat without journal spam (GOALS
    frugality: a beat is not an event worth a checkpoint)."""
    with fleet_lock():
        claim, _ = _require_claim_holder(getattr(args, "sid", None))
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"heartbeat refreshed for {claim['incarnation_id']}")
    return 0


def cmd_sup_status(args) -> int:
    """`fleet sup-status [--json]` -- READ-ONLY VIEW (terminal-surface
    doctrine: no lock, no probe, no write). Safe lock-free reads: all
    supervisor state files are written atomically."""
    claim = read_incarnation()
    hs = read_handshake()
    beat_age = None
    if claim is not None:
        try:
            beat_age = (datetime.now(timezone.utc) - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            beat_age = None
    info = {
        "goals_active": supervisor_goals_active(),
        "incarnation": claim,
        "heartbeat_age_seconds": beat_age,
        "handshake": hs,
        "abort_flag": handoff_abort_flag_path().exists(),
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
    if claim is None:
        print("supervisor: no claim" + (" (GOALS active -- start one: `fleet sup-boot`)"
                                        if info["goals_active"] else ""))
    else:
        age = f"{beat_age:.0f}s ago" if beat_age is not None else "unreadable"
        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
              f"via {claim.get('claimed_via', '?')}, heartbeat {age}")
    if hs is not None:
        print(f"handshake: {hs.get('incarnation_id')} sid={hs.get('session_id')} (handoff in flight)")
    if info["abort_flag"]:
        print(f"WARNING: aborted-handoff flag present ({handoff_abort_flag_path()})")
    return 0
```

`cmd_sup_status` references `supervisor_goals_active` which Task 6 formally owns for the nag — to keep THIS task self-contained, implement it here (Task 6 consumes it):

```python
def supervisor_goals_active() -> bool:
    """GOALS.md exists and is not parked. Operator parks the nag by adding
    the literal token SUPERVISOR-DORMANT anywhere in GOALS.md."""
    try:
        text = goals_path().read_text(encoding="utf-8")
    except OSError:
        return False
    return "SUPERVISOR-DORMANT" not in text
```

- [ ] **Step 4: Wire argparse + dispatch:**

```python
    p_supckpt = sub.add_parser("sup-checkpoint", help="append a supervisor journal checkpoint (claim holder only) + refresh heartbeat")
    p_supckpt.add_argument("body", help="checkpoint text, or @file")
    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
    p_supckpt.add_argument("--sid", help="override caller session id")

    p_supbeat = sub.add_parser("sup-heartbeat", help="refresh the supervisor claim heartbeat (no journal write)")
    p_supbeat.add_argument("--sid", help="override caller session id")

    p_supstat = sub.add_parser("sup-status", help="read-only supervisor claim/handshake status")
    p_supstat.add_argument("--json", action="store_true")
```

`main()`:

```python
        if args.command == "sup-checkpoint":
            return cmd_sup_checkpoint(args)
        if args.command == "sup-heartbeat":
            return cmd_sup_heartbeat(args)
        if args.command == "sup-status":
            return cmd_sup_status(args)
```

- [ ] **Step 5: Run tests, full suite, commit:**

```bash
git add bin/fleet.py tests/test_supervisor.py
git commit -m "feat(supervisor): sup-checkpoint/sup-heartbeat (holder-guarded) + sup-status view"
```

---

### Task 5: Handoff protocol — `sup-handoff-begin` / `sup-handoff-complete` / `sup-handoff-abort`

**Files:**
- Modify: `bin/fleet.py` — supervisor section + `build_parser()` + `main()`
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: `_require_claim_holder`, journal/IO helpers, `resolve_claude_executable`, `_fetch_agents_roster`, `SUPERVISOR_ROSTER_VERIFY_SECONDS`, `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS`
- Produces:
  - `_render_successor_task(successor_inc: str, old_inc: str) -> str` — successor bootstrap prompt body (task-file bootstrap, G8)
  - `cmd_sup_handoff_begin(args, which, run, sleep=time.sleep) -> int` — args: `sid, model: str|None, permission_mode: str|None`. Prints `SUCCESSOR-INC: <inc>` and `SUCCESSOR-SID: <sid>` lines on success (the old supervisor feeds these to complete/abort).
  - `cmd_sup_handoff_complete(args) -> int` — args: `sid, expect_inc: str, expect_sid: str`
  - `cmd_sup_handoff_abort(args, which, run) -> int` — args: `sid, successor_sid: str`
- Dispatch argv (contract dispatch pattern; direct argv list, no shell — the Git-Bash backslash hazard does not apply, but the task-file path inside the PROMPT is rendered `.as_posix()`): `[claude, "--bg", "-n", f"sup|{inc}|successor", *optional --model/--permission-mode, f"Read {task_path.as_posix()} and follow it exactly."]`
- Successor sid join: by `-n` name match among entries whose sid was NOT in the pre-dispatch roster snapshot (name is display-only + join-by-sid rule; here the name IS the discriminator only against the pre-snapshot, within `SUPERVISOR_ROSTER_VERIFY_SECONDS`, per contract G6 fallback — no match ⇒ DOA report, exit 1).

- [ ] **Step 1: Write the failing tests** (append):

```python
class TestHandoff:
    def _hold(self, sid="sid-old", inc="inc-old"):
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW),
                                 "claimed_via": "fresh"})

    def _begin(self, run, sid="sid-old"):
        args = SimpleNamespace(sid=sid, model=None, permission_mode=None)
        return fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None)

    @staticmethod
    def _dispatch_then_roster(successor_sid="sid-new"):
        """run double. Call order in cmd_sup_handoff_begin is: pre-dispatch
        roster fetch, --bg dispatch, then roster polls -- so the fake is
        STATEFUL: the successor appears in the roster only after the
        dispatch call has been observed."""
        state = {"name": None}
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc123 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries.append({"sessionId": successor_sid, "status": "busy",
                                "name": state["name"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        run.calls = calls
        return run

    def test_begin_journals_writes_taskfile_joins_sid(self, sup_home, capsys):
        self._hold()
        run = self._dispatch_then_roster()
        rc = self._begin(run)
        assert rc == 0
        latest_kinds = [e["kind"] for e in fleet.supervisor_journal_entries()]
        assert "HANDOFF-BEGIN" in latest_kinds
        out = capsys.readouterr().out
        assert "SUCCESSOR-SID: sid-new" in out and "SUCCESSOR-INC: inc-" in out
        taskfiles = list((sup_home / "state").glob("supervisor-handoff-*.md"))
        assert len(taskfiles) == 1
        body = taskfiles[0].read_text(encoding="utf-8")
        assert "sup-boot --handoff-inc" in body and "NO spawn" in body
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert any(a.startswith("sup|inc-") for a in dispatch)

    def test_begin_doa_when_successor_never_appears(self, sup_home, capsys, monkeypatch):
        # shrink the verify window: with a no-op sleep the real 60s window
        # would busy-spin for a full minute of wall clock
        monkeypatch.setattr(fleet, "SUPERVISOR_ROSTER_VERIFY_SECONDS", 0.05)
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc · sup\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run)
        assert rc == 1
        assert "DOA" in capsys.readouterr().out

    def test_begin_refused_for_non_holder(self, sup_home):
        self._hold(sid="sid-holder")
        with pytest.raises(fleet.FleetCliError):
            self._begin(self._dispatch_then_roster(), sid="sid-imposter")

    def test_complete_transfers_on_dual_match(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        assert fleet.cmd_sup_handoff_complete(args) == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == "inc-succ" and claim["session_id"] == "sid-new"
        assert claim["claimed_via"] == "handoff"
        assert fleet.read_handshake() is None
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "HANDOFF-COMPLETE" and latest["inc"] == "inc-old"

    def test_complete_refuses_on_inc_mismatch(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-WRONG", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"
        assert fleet.read_handshake() is not None

    def test_complete_refuses_when_no_handshake(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)

    def test_abort_stops_successor_flags_and_resumes(self, sup_home, capsys):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        stopped = []
        def run(argv, **kw):
            stopped.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert stopped and stopped[0][-2:] == ["stop", "sid-new"]
        assert fleet.read_handshake() is None
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"  # old resumes duty

    def test_abort_reports_failed_stop_but_still_flags(self, sup_home, capsys):
        self._hold()
        def run(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="no such session")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-gone")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert "stop failed" in capsys.readouterr().out.lower()

    def test_begin_clears_previous_abort_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"stale": True})
        self._begin(self._dispatch_then_roster())
        assert not fleet.handoff_abort_flag_path().exists()

    def test_handoff_timeout_drill_end_to_end(self, sup_home):
        """Spec §4 failure branch: begin -> successor never handshakes ->
        complete refuses -> abort stops the limbo successor and old resumes."""
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        args = SimpleNamespace(sid="sid-old",
                               expect_inc="inc-whatever", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):   # no HANDSHAKE was written
            fleet.cmd_sup_handoff_complete(args)
        def stop_run(argv, **kw):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        abort = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(abort, which=_fake_which, run=stop_run) == 0
        assert fleet.read_incarnation()["session_id"] == "sid-old"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement:**

```python
def _render_successor_task(successor_inc: str, old_inc: str) -> str:
    """Successor bootstrap body (task-file bootstrap, contract G8 -- never
    argv for size-unbounded content). Paths rendered .as_posix()."""
    fleet_py = (FLEET_HOME / "bin" / "fleet.py").as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
Your predecessor ({old_inc}) dispatched you mid-handoff (spec docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §4).

Do exactly this, in order:
1. Run: py -3.13 {fleet_py} sup-boot --handoff-inc {successor_inc}
   This prints your boot bundle and writes supervisor/HANDSHAKE. You hold NO claim yet.
2. Take NO fleet actions (no spawn/respawn/send/kill/clean) before claim transfer -- spec §4's double-spawn guard.
3. Poll every ~30s (up to 10 minutes): py -3.13 {fleet_py} sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     py -3.13 {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}"
     then read your boot bundle output and continue the supervisor duty per skills/fleet/supervisor.md.
   - If 10 minutes pass without transfer: the handoff was aborted. STOP -- take no actions,
     end your turn with the final message: HANDOFF-ORPHAN {successor_inc}
"""


def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
                          sleep=time.sleep) -> int:
    """`fleet sup-handoff-begin [--model M] [--permission-mode P] [--sid S]`.
    Checkpoint-then-act: HANDOFF-BEGIN is journaled BEFORE dispatch so a
    crash mid-dispatch leaves evidence. Dispatch + roster polling run
    OUTSIDE fleet_lock (F4 doctrine)."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        successor_inc = mint_incarnation_id()
        task_path = state_dir() / f"supervisor-handoff-{successor_inc}.md"
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(_render_successor_task(successor_inc, claim["incarnation_id"]),
                             encoding="utf-8")
        supervisor_journal_append("HANDOFF-BEGIN", claim["incarnation_id"], caller,
                                  f"successor={successor_inc} task={task_path.as_posix()}")
        try:
            # A new attempt supersedes any previous aborted handoff.
            handoff_abort_flag_path().unlink()
        except FileNotFoundError:
            pass

    exe = resolve_claude_executable(which=which)
    pre_ok, pre_payload = _fetch_agents_roster(which=which, run=run)
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict)}
    name = f"sup|{successor_inc}|successor"
    argv = [exe, "--bg", "-n", name]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    if getattr(args, "permission_mode", None):
        argv += ["--permission-mode", args.permission_mode]
    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
    proc = run(argv, capture_output=True, text=True, encoding="utf-8",
               errors="replace", timeout=120)
    if proc.returncode != 0:
        raise FleetCliError(f"successor dispatch failed (exit {proc.returncode}): "
                            f"{(proc.stderr or '').strip()[:300]} -- no successor to stop; "
                            f"claim unchanged, duty continues")

    # G6 fallback: join by fresh `-n` match within the verify window.
    successor_sid = None
    deadline = time.monotonic() + SUPERVISOR_ROSTER_VERIFY_SECONDS
    while time.monotonic() < deadline:
        ok, payload = _fetch_agents_roster(which=which, run=run)
        if ok:
            fresh = [e for e in payload if isinstance(e, dict)
                     and e.get("name") == name and e.get("sessionId")
                     and e.get("sessionId") not in pre_sids]
            if fresh:
                successor_sid = fresh[0]["sessionId"]
                break
        sleep(3)
    if successor_sid is None:
        print(f"successor DOA: no roster entry named {name!r} appeared within "
              f"{SUPERVISOR_ROSTER_VERIFY_SECONDS:.0f}s (contract G6 fallback). "
              f"Claim unchanged -- duty continues; re-run sup-handoff-begin to retry.")
        return 1

    print(f"SUCCESSOR-INC: {successor_inc}")
    print(f"SUCCESSOR-SID: {successor_sid}")
    print(f"Next: wait for supervisor/HANDSHAKE (timeout "
          f"{SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:.0f}s), then run:\n"
          f"  fleet sup-handoff-complete --expect-inc {successor_inc} --expect-sid {successor_sid}\n"
          f"On timeout/failure instead run:\n"
          f"  fleet sup-handoff-abort --successor-sid {successor_sid}")
    return 0


def cmd_sup_handoff_complete(args) -> int:
    """`fleet sup-handoff-complete --expect-inc I --expect-sid S [--sid ...]`.
    Dual verification (spec §4): the HANDSHAKE must carry EXACTLY the
    incarnation id the old side minted AND the sid it dispatched. Journal
    HANDOFF-COMPLETE first (old is still holder), then transfer."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        hs = read_handshake()
        if hs is None:
            raise FleetCliError("no supervisor/HANDSHAKE -- successor not ready; wait, "
                                "or sup-handoff-abort past the timeout")
        if (hs.get("incarnation_id") != args.expect_inc
                or hs.get("session_id") != args.expect_sid):
            raise FleetCliError(
                f"HANDSHAKE mismatch: found inc={hs.get('incarnation_id')} "
                f"sid={hs.get('session_id')}, expected inc={args.expect_inc} "
                f"sid={args.expect_sid} -- NOT transferring (spec §4 id verification)")
        supervisor_journal_append("HANDOFF-COMPLETE", claim["incarnation_id"], caller,
                                  f"claim -> {args.expect_inc} sid={args.expect_sid}")
        write_incarnation({"incarnation_id": args.expect_inc,
                           "session_id": args.expect_sid,
                           "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                           "claimed_via": "handoff"})
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
    print(f"claim transferred to {args.expect_inc}. This (old) incarnation must now "
          f"EXIT: end the session, take no further fleet actions.")
    return 0


def cmd_sup_handoff_abort(args, which=shutil.which, run=subprocess.run) -> int:
    """`fleet sup-handoff-abort --successor-sid S [--sid ...]` -- spec §4
    timeout branch: old resumes duty, stops the limbo successor (`claude
    stop`, NEVER raw kill -- G10 zombie hazard), removes HANDSHAKE, raises
    the doctor-visible flag. Note contract G10: `claude stop` fires NO Stop
    hook -- nothing will have journaled on the successor's behalf."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
        supervisor_journal_append("HANDOFF-ABORT", claim["incarnation_id"], caller,
                                  f"stopping limbo successor sid={args.successor_sid}")
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "successor_sid": args.successor_sid,
            "holder": claim["incarnation_id"],
        })
        claim["heartbeat_at"] = now_iso()   # old resumes duty
        write_incarnation(claim)
    exe = resolve_claude_executable(which=which)
    proc = run([exe, "stop", args.successor_sid], capture_output=True, text=True,
               encoding="utf-8", errors="replace", timeout=60)
    if proc.returncode != 0:
        print(f"WARNING: `claude stop {args.successor_sid}` stop failed "
              f"(exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}) -- "
              f"successor may still be live; stop it manually via the agents menu. "
              f"Abort flag is set either way.")
    else:
        print(f"limbo successor {args.successor_sid} stopped; duty resumed by "
              f"{claim['incarnation_id']}. Doctor will flag until the abort flag is cleared.")
    return 0
```

- [ ] **Step 4: Wire argparse + dispatch:**

```python
    p_suphb = sub.add_parser("sup-handoff-begin", help="dispatch a handoff successor (claim holder only)")
    p_suphb.add_argument("--model", help="model for the successor session")
    p_suphb.add_argument("--permission-mode", dest="permission_mode", help="permission mode for the successor session")
    p_suphb.add_argument("--sid", help="override caller session id")

    p_suphc = sub.add_parser("sup-handoff-complete", help="verify HANDSHAKE and transfer the claim")
    p_suphc.add_argument("--expect-inc", dest="expect_inc", required=True)
    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
    p_suphc.add_argument("--sid", help="override caller session id")

    p_supha = sub.add_parser("sup-handoff-abort", help="abort a handoff: stop the limbo successor, resume duty")
    p_supha.add_argument("--successor-sid", dest="successor_sid", required=True)
    p_supha.add_argument("--sid", help="override caller session id")
```

`main()`:

```python
        if args.command == "sup-handoff-begin":
            return cmd_sup_handoff_begin(args)
        if args.command == "sup-handoff-complete":
            return cmd_sup_handoff_complete(args)
        if args.command == "sup-handoff-abort":
            return cmd_sup_handoff_abort(args)
```

- [ ] **Step 5: Run tests, full suite, commit:**

```bash
git add bin/fleet.py tests/test_supervisor.py
git commit -m "feat(supervisor): id-verified handoff protocol -- begin/complete/abort with timeout drill (spec §4)"
```

---

### Task 6: Nag predicate — status line, doctor checks, SessionStart hook line

**Files:**
- Modify: `bin/fleet.py` — supervisor section, `cmd_doctor` checks list (fleet.py:4508-4527), `cmd_sup_status` (add `nag` key)
- Modify: `bin/hooks/sessionstart_fleet.py` — `_build_context` (line ~100)
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: `supervisor_goals_active` (Task 4), `read_incarnation`, `SUPERVISOR_CLAIM_STALE_SECONDS`, `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS`, `handoff_abort_flag_path`, `handshake_path`
- Produces:
  - `supervisor_status_line(now=None) -> str | None` — file-only (NO lock, NO roster, NO probe, never raises); None when GOALS absent/dormant
  - `_doctor_check_supervisor_claim() -> tuple[str, bool, str]` — always ok=True (nag is advisory, spec §4)
  - `_doctor_check_supervisor_handoff() -> tuple[str, bool, str]` — FAIL on abort flag or stale HANDSHAKE (older than T)
  - `cmd_sup_status` JSON gains key `nag: str | None`

- [ ] **Step 1: Write the failing tests** (append):

```python
class TestNag:
    def test_none_when_goals_absent(self, sup_home):
        fleet.goals_path().unlink()
        assert fleet.supervisor_status_line() is None

    def test_none_when_dormant_token(self, sup_home):
        fleet.goals_path().write_text("# Goals\nSUPERVISOR-DORMANT\n", encoding="utf-8")
        assert fleet.supervisor_status_line() is None

    def test_nags_when_no_claim(self, sup_home):
        line = fleet.supervisor_status_line()
        assert line is not None and "no claim" in line

    def test_nags_when_heartbeat_stale(self, sup_home):
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": _iso(stale), "heartbeat_at": _iso(stale),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "stale" in line

    def test_informational_when_fresh(self, sup_home):
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "inc-x" in line and "stale" not in line and "no claim" not in line


class TestSupervisorDoctorChecks:
    def test_claim_check_is_always_advisory_pass(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_claim()
        assert name == "supervisor-claim" and ok is True
        assert "no claim" in msg

    def test_handoff_check_fails_on_abort_flag(self, sup_home):
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"aborted_at": "x"})
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "abort" in msg.lower()

    def test_handoff_check_fails_on_stale_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        import os as _os, time as _time
        old = _time.time() - fleet.SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS - 60
        _os.utime(fleet.handshake_path(), (old, old))
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "stale" in msg.lower()

    def test_handoff_check_passes_on_fresh_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True and "in flight" in msg

    def test_handoff_check_passes_clean(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True


class TestSessionStartLine:
    def test_build_context_includes_supervisor_nag(self, sup_home, monkeypatch):
        import importlib.util
        hook_path = (fleet.Path(fleet.__file__).resolve().parent / "hooks"
                     / "sessionstart_fleet.py")
        spec = importlib.util.spec_from_file_location("sessionstart_fleet", hook_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "fleet", fleet)   # hook resolves its own fleet import
        ctx = mod._build_context()
        assert "SUPERVISOR:" in ctx
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement in `bin/fleet.py`:**

```python
def supervisor_status_line(now=None):
    """One-line supervisor status/nag for VIEWS (SessionStart hook, doctor,
    sup-status). File-only by mandate (spec §4 nag predicate + terminal-
    surface doctrine): no lock, no roster read, no subprocess -- the
    heartbeat timestamp alone carries liveness, so this may false-fire on a
    live idle supervisor (accepted: the nag is advisory; seizure stays
    gated on roster-gone in sup-boot). Never raises; None = GOALS absent
    or dormant."""
    try:
        if not supervisor_goals_active():
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        claim = read_incarnation()
        if claim is None:
            return ("SUPERVISOR: GOALS active, no claim -- boot one "
                    "(`fleet sup-boot`; see skills/fleet/supervisor.md).")
        inc = claim.get("incarnation_id", "?")
        try:
            age = (now - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
        if age > SUPERVISOR_CLAIM_STALE_SECONDS:
            return (f"SUPERVISOR: claim {inc} heartbeat stale (~{age / 60:.0f}m > "
                    f"{SUPERVISOR_CLAIM_STALE_SECONDS / 60:.0f}m) -- boot a new incarnation.")
        return f"SUPERVISOR: {inc} live, heartbeat {age / 60:.0f}m ago."
    except Exception:  # noqa: BLE001 -- view: never raises
        return None


def _doctor_check_supervisor_claim():
    """Spec §4 nag, doctor surface. ALWAYS ok=True -- the nag is advisory
    (an absent supervisor is a prompt, not a health failure)."""
    line = supervisor_status_line()
    if line is None:
        return ("supervisor-claim", True, "GOALS absent or dormant -- no supervisor expected")
    return ("supervisor-claim", True, line)


def _doctor_check_supervisor_handoff():
    """FAIL on handoff residue needing an operator: the aborted-handoff flag
    (sup-handoff-abort wrote it) or a HANDSHAKE older than the handoff
    timeout (orphan from a crash mid-handoff -- the seize path will delete
    it, but doctor should not wait for a seize to notice)."""
    parts = []
    ok = True
    if handoff_abort_flag_path().exists():
        ok = False
        parts.append(f"aborted-handoff flag present ({handoff_abort_flag_path().name}) -- "
                     f"review supervisor/JOURNAL.md, delete the flag once resolved")
    if handshake_path().exists():
        try:
            age = time.time() - handshake_path().stat().st_mtime
        except OSError:
            age = None
        if age is None or age > SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:
            ok = False
            parts.append("stale supervisor/HANDSHAKE (older than the handoff timeout) -- "
                         "orphan from a crashed handoff; safe to delete manually")
        else:
            parts.append("HANDSHAKE present (handoff in flight)")
    if not parts:
        parts.append("no handoff in flight, no aborted-handoff flag")
    return ("supervisor-handoff", ok, " | ".join(parts))
```

Register both in `cmd_doctor`'s `checks` list, after `_doctor_check_hook_errors()`:

```python
        _doctor_check_supervisor_claim(),
        _doctor_check_supervisor_handoff(),
```

Add the `nag` key to `cmd_sup_status`'s `info` dict:

```python
        "nag": supervisor_status_line(),
```

- [ ] **Step 4: Edit `bin/hooks/sessionstart_fleet.py`.** In `_build_context()`, after the `else: out.append("FLEET: no workers registered.")` block and before the `index = _index_lines()` line, insert:

```python
    try:
        sup_line = fleet.supervisor_status_line()
    except Exception:  # noqa: BLE001 -- invariant 2: the briefing must never break
        sup_line = None
    if sup_line:
        out.append(sup_line)
```

- [ ] **Step 5: Run tests, full suite** (`test_terminal_surface.py` exercises this hook — watch it), **commit:**

```bash
git add bin/fleet.py bin/hooks/sessionstart_fleet.py tests/test_supervisor.py
git commit -m "feat(supervisor): file-only nag -- status line, doctor checks, SessionStart briefing line"
```

---

### Task 7: Supervisor skill doc, SKILL.md wiring, handoff docs, final green

**Files:**
- Create: `skills/fleet/supervisor.md`
- Modify: `skills/fleet/SKILL.md` (CLI reference table + startup ritual pointer)
- Modify: `docs/NEXT-SESSION.md` (mark M-A built; point at M-B)
- Test: full suite (no new tests; this task is docs + verification gate)

**Interfaces:**
- Consumes: every CLI command name and exit code defined in Tasks 3–6 (verify each against `py -3.13 bin/fleet.py --help` output before writing docs — the doc must not drift from the built surface).

- [ ] **Step 1: Create `skills/fleet/supervisor.md`:**

```markdown
# Fleet supervisor — persistent identity, disposable body

Spec: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §4.
Soul = `supervisor/GOALS.md` (operator-owned) + `supervisor/JOURNAL.md`
(append-only) + `knowledge/`. Body = whichever Claude session holds
`supervisor/INCARNATION`.

## Boot ritual (every incarnation, one path — morning / post-reboot / post-handoff)

1. Run `fleet sup-boot`. Read the ENTIRE bundle it prints (GOALS, journal
   tail, knowledge index, roster, fleet status).
2. Act on the VERDICT line:
   - `claim` / `seize` (exit 0): you hold the claim. Continue the duty.
   - `refuse` (exit 2): another supervisor is live. Report read-only and STOP.
   - `freeze` (exit 3): ambiguity (daemon restart? G9). PAGE THE OPERATOR.
     Never seize, never mass-respawn.
3. Reconcile workers from the bundle's fleet-status section (M-A interim:
   registry verdicts; the outcome discriminator arrives in M-B).

## Checkpoint discipline

- `fleet sup-checkpoint "<what changed / decided / learned>"` after every
  meaningful unit of work. Checkpoints refresh the heartbeat.
- `fleet sup-heartbeat` when working long stretches without a checkpointable
  event — keep the heartbeat younger than 60 min (S = 3600s) or the nag
  fires and a stale-claim seizure becomes possible once your session dies.
- `--kind PROPOSAL` for suggested GOALS.md edits (only the operator commits
  changes to GOALS.md).

## Handoff (context-exhaustion succession)

Trigger band (operator-set 2026-07-14): BEGIN handoff at ~300k tokens of
context; hard-latest at 500k. Never ride to the compaction wall.

Old incarnation:
1. `fleet sup-checkpoint "handoff prep: <state summary for successor>"`
2. `fleet sup-handoff-begin` — note the `SUCCESSOR-INC:` / `SUCCESSOR-SID:` lines.
3. Wait for `supervisor/HANDSHAKE` (successor writes it via its own
   `sup-boot --handoff-inc`). Timeout T = 300s.
4. On handshake: `fleet sup-handoff-complete --expect-inc <INC> --expect-sid <SID>`,
   then EXIT the session. No further fleet actions.
5. On timeout / dispatch failure: `fleet sup-handoff-abort --successor-sid <SID>`
   — you resume duty; doctor flags the abort until the operator clears
   `state/supervisor-handoff-aborted.json`.

Successor: driven entirely by the task file `sup-handoff-begin` wrote — it
boots claim-pending, writes HANDSHAKE, polls `fleet sup-status --json`, and
takes NO fleet actions until the claim shows its incarnation id.

## Rules that bind every incarnation

- GOALS.md binds you, including cost frugality (cheapest-capable models, no
  idle polling, long beats).
- Journal is append-only, single-writer, claim-holder-only. Write it via
  `fleet sup-checkpoint` only.
- Never two live supervisors over one GOALS.md. When in doubt: refuse or
  freeze — never act on an ambiguous claim.
- `claude stop` fires NO Stop hook (contract G10) — a stopped session never
  journaled its own death; the stopping side owns the record.
- Park the nag by adding the literal token `SUPERVISOR-DORMANT` to GOALS.md
  (operator action).
```

- [ ] **Step 2: Update `skills/fleet/SKILL.md`.** Append these rows to the CLI reference table:

```markdown
| `fleet sup-boot [--handoff-inc <id>]` | Supervisor boot ritual: epoch check → claim/seize/refuse/freeze + boot bundle. Exit 0=hold, 2=refuse, 3=freeze. See `skills/fleet/supervisor.md`. |
| `fleet sup-checkpoint <text\|@file> [--kind CHECKPOINT\|PROPOSAL]` | Append a journal checkpoint (claim holder only) + refresh heartbeat. |
| `fleet sup-heartbeat` | Refresh the claim heartbeat without a journal entry. |
| `fleet sup-status [--json]` | Read-only supervisor claim/handshake/nag view. |
| `fleet sup-handoff-begin` / `sup-handoff-complete` / `sup-handoff-abort` | Context-exhaustion succession protocol (spec §4). Trigger band: begin ~300k tokens, hard-latest 500k. |
```

And add to the startup ritual section, as item 4: `4. If supervisor/GOALS.md is active and you are (or should become) the supervisor: run the boot ritual in skills/fleet/supervisor.md.`

- [ ] **Step 3: Update `docs/NEXT-SESSION.md`:** replace the "The job" section body with M-A-built status + M-B pointer (usage-limit continuity FIRST per spec §5.1.1), keeping the Standing rules section intact.

- [ ] **Step 4: Verification gate (whole milestone):**

Run: `py -3.13 -m pytest -q` → 0 failures.
Run: `py -3.13 bin/fleet.py sup-status` → prints "no claim" line, exit 0.
Run: `py -3.13 bin/fleet.py doctor` → `supervisor-claim` line present (advisory), `supervisor-handoff` PASS.
Run: `py -3.13 bin/fleet.py sup-boot --sid test-sid-manual` in a shell → VERDICT line prints (then `git checkout -- supervisor/JOURNAL.md` and delete `supervisor/INCARNATION` to undo the manual smoke's claim).

- [ ] **Step 5: Commit + push (operator standing directive: push `fleet-impl`, fast-forward `main` at green milestones):**

```bash
git add skills/fleet/supervisor.md skills/fleet/SKILL.md docs/NEXT-SESSION.md
git commit -m "docs(supervisor): M-A skill doc, SKILL.md wiring, next-session handoff"
git push origin fleet-impl
git checkout main && git merge --ff-only fleet-impl && git push origin main && git checkout fleet-impl
```

---

## Non-goals (scope fence, spec §4)

- No outcome discriminator, no Stop-hook result capture, no `--bg` worker dispatch, no usage-limit rehoming — all M-B.
- No heartbeat scheduler automation (ScheduleWakeup usage is session behavior, documented in the skill; the CLI only records beats).
- No supervisor budget-cap enforcement (spec constraint noted; lands with M-B's token plumbing).
- No auto-restart after reboot (stated limitation; nag + doctor are the recovery surface).
- No standing-goals/self-improvement layer.
