# Terminal Surface (Phase 1.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fleet visible and operable from inside the manager's Claude Code session — an always-on statusline, `/fleet:*` slash commands, a session-start briefing, packaged as a plugin.

**Architecture:** One new read-only derivation, `fleet.status_snapshot()`, reads `state/fleet.json` + `mailbox/*.md` and stops — no `fleet.lock`, no PID probe, no write. Four surfaces consume it (statusline, `fleet status --json`, SessionStart hook, future watchtower/web-UI). Mutating slash commands bypass it entirely and call the ordinary lock-guarded CLI.

**Tech Stack:** Python 3.13 (`py -3.13`) stdlib only; pytest; Claude Code plugin/commands/statusline/hooks surfaces.

**Spec:** `docs/specs/terminal-surface.md`. Read it before Task 1. Decisions are cited by ID (D1–D6) throughout.

## Global Constraints

- Python is `py -3.13`. `bin/fleet.py` is **stdlib-only, single file**. New scripts (`bin/fleet_statusline.py`, `bin/hooks/sessionstart_fleet.py`) are stdlib-only too.
- Python floor for new code: **3.10+** (SPEC §14). No 3.13-only syntax.
- **No new OS branching outside the platform adapter block** (invariant 8). `TestPlatformAdapterBoundary` scans for `os.name`, `sys.platform`, `platform.system`, `sys.getwindowsversion`, `os.uname`, `os.sep` outside the adapter. Do not introduce them.
- **No view writes.** Nothing built in Tasks 1–7 may write `state/fleet.json`, `state/events.jsonl`, or create `state/fleet.lock`. Only Task 8 (`fleet init --statusline`) writes anything, and only to `~/.claude/settings.json`.
- **No view probes.** Nothing built here may call `PLATFORM.get_process_info` or spawn a subprocess on a refresh path.
- Hook and statusline scripts **exit 0 on every path**, printing nothing on error (invariant 2, extended to the statusline by D-spec §4.3).
- Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored. `knowledge/`, `commands/`, `.claude-plugin/` are git-tracked.
- Hook commands in settings JSON use **forward slashes** (Git Bash `sh -c` eats backslashes).
- Tests: `py -3.13 -m pytest` from the repo root. Live tier (`FLEET_LIVE=1`) is untouched by this plan.
- Commit after every task. Never `--no-verify`.

## File Structure

| File | Responsibility |
|---|---|
| `bin/fleet.py` (modify) | `status_snapshot()` + `_read_registry_readonly()`; `--json`/`--stale-ok` on `status`; `FLEET_WORKER` env stamp in `launch_turn`; `init --statusline` |
| `bin/fleet_statusline.py` (create) | Render one ANSI line from `status_snapshot()`. Exit 0 always. |
| `bin/hooks/sessionstart_fleet.py` (create) | Emit `additionalContext` briefing. Suppress inside workers. Exit 0 always. |
| `commands/*.md` (create, 14 files) | Slash commands. Read-only inline `` !` ``; mutating are prompt templates. |
| `.claude-plugin/plugin.json` (create) | Plugin manifest. Ships commands + skill + hook. **No statusline** (not permitted). |
| `skills/fleet/SKILL.md` (move from `skill/SKILL.md`) | Plugin-standard skill location. |
| `hooks/hooks.json` (create) | SessionStart registration for the plugin. |
| `tests/test_terminal_surface.py` (create) | All Task 1–8 unit tests except the boundary-lint extension. |
| `tests/test_steering.py` (modify) | Extend `TestPlatformAdapterBoundary` to the new files. |

---

### Task 1: `status_snapshot()` — the single read-only derivation

**Files:**
- Modify: `bin/fleet.py` (add after `_worker_flags`, ~line 1635)
- Test: `tests/test_terminal_surface.py` (create)

**Interfaces:**
- Consumes: `FLEET_HOME`, `registry_path()`, `mailbox_dir()`, `_parse_iso()`, `now_iso()`, `_limit_reset_passed()`, `_registry_cost()` — all existing in `bin/fleet.py`.
- Produces: `fleet.status_snapshot(now=None) -> dict` and `fleet._read_registry_readonly() -> tuple[bool, str | None, dict]`. Tasks 2, 3, 5 all call `status_snapshot`.

**Critical constraint (D4):** `status_snapshot()` must NOT call the existing `load_registry()`. That function **quarantines** a corrupt registry (renames it to `fleet.json.corrupt.<ts>` and appends a `registry_corrupt` event) — both writes. A statusline refreshing every 10 s would quarantine in a loop and shred the operator's evidence. Read raw, report, do not repair.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_terminal_surface.py`:

```python
"""Phase 1.6 terminal surface (docs/specs/terminal-surface.md)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def _write_registry(home, workers):
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8"
    )


def _rec(**over):
    base = {
        "session_id": "sid-1", "cwd": "C:/proj", "task": "t", "mode": "dontask",
        "model": None, "max_budget_usd": None, "setting_sources": None,
        "created": "2026-07-09T12:00:00Z", "status": "working",
        "turn_pid": 123, "turn_pid_ctime": "2026-07-09T12:00:00Z",
        "attached_since": None, "limit_reset_at": None, "limit_kind": None,
        "turns": 3, "cost_baseline": 0.0, "cost_usd": 1.25,
        "last_activity": "2026-07-09T12:00:00Z",
    }
    base.update(over)
    return base


class TestStatusSnapshot:
    def test_missing_registry_reports_not_initialized(self, home):
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "not_initialized"
        assert snap["workers"] == []

    def test_corrupt_registry_reports_unreadable_and_does_not_quarantine(self, home):
        path = home / "state" / "fleet.json"
        path.write_text("{not json", encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"
        assert snap["workers"] == []
        # D4: the view reports; it never quarantines (that is a write).
        assert path.exists()
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []
        assert not (home / "state" / "events.jsonl").exists()

    def test_workers_not_an_object_reports_unreadable(self, home):
        (home / "state" / "fleet.json").write_text('{"workers": [1, 2]}', encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"

    def test_empty_registry_is_ok_with_zero_totals(self, home):
        _write_registry(home, {})
        snap = fleet.status_snapshot()
        assert snap["ok"] is True
        assert snap["reason"] is None
        assert snap["totals"]["workers"] == 0
        assert snap["totals"]["cost_usd"] == 0.0
        assert snap["totals"]["mail"] == 0

    def test_rows_carry_status_cost_turns_and_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("hi", encoding="utf-8")
        snap = fleet.status_snapshot()
        row = snap["workers"][0]
        assert row["name"] == "pmbot"
        assert row["status"] == "working"
        assert row["turns"] == 3
        assert row["cost_usd"] == 1.25
        assert row["mail"] == 1
        assert snap["totals"]["mail"] == 1
        assert snap["totals"]["cost_usd"] == 1.25

    def test_empty_mailbox_file_counts_as_no_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("", encoding="utf-8")
        assert fleet.status_snapshot()["workers"][0]["mail"] == 0

    def test_totals_count_every_status_generically(self, home):
        # Shipped code has statuses beyond SPEC's five (over_budget,
        # over_ceiling); totals must not hardcode a fixed set.
        _write_registry(home, {
            "a": _rec(status="working", session_id="s-a"),
            "b": _rec(status="idle", session_id="s-b"),
            "c": _rec(status="over_ceiling", session_id="s-c"),
        })
        totals = fleet.status_snapshot()["totals"]
        assert totals["workers"] == 3
        assert totals["by_status"] == {"working": 1, "idle": 1, "over_ceiling": 1}

    def test_stale_seconds_derived_from_last_activity(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="2026-07-09T12:00:00Z")})
        snap = fleet.status_snapshot(now=fleet._parse_iso("2026-07-09T12:05:00Z"))
        assert snap["workers"][0]["stale_seconds"] == pytest.approx(300.0)

    def test_unparseable_last_activity_yields_none_stale_seconds(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="garbage")})
        assert fleet.status_snapshot()["workers"][0]["stale_seconds"] is None

    def test_missing_additive_fields_default(self, home):
        # Additive-schema rule (SPEC §4): an old record lacking cost_baseline /
        # limit_reset_at / limit_kind reads as 0.0 / None / None, never raises.
        old = {"session_id": "s-old", "status": "idle", "turns": 1,
               "last_activity": "2026-07-09T12:00:00Z"}
        _write_registry(home, {"legacy": old})
        row = fleet.status_snapshot()["workers"][0]
        assert row["cost_usd"] == 0.0
        assert row["limit_reset_at"] is None
        assert row["limit_kind"] is None
        assert row["resume_eligible"] is False

    def test_limited_past_reset_is_flagged_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2020-01-01T00:00:00Z", limit_kind="session_5h")})
        row = fleet.status_snapshot()["workers"][0]
        assert row["status"] == "limited"
        assert row["resume_eligible"] is True

    def test_limited_before_reset_is_not_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2099-01-01T00:00:00Z")})
        assert fleet.status_snapshot()["workers"][0]["resume_eligible"] is False

    def test_workers_sorted_by_name(self, home):
        _write_registry(home, {"zed": _rec(session_id="s-z"), "abe": _rec(session_id="s-a")})
        assert [w["name"] for w in fleet.status_snapshot()["workers"]] == ["abe", "zed"]


class TestStatusSnapshotIsPure:
    def test_never_probes(self, home, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("status_snapshot must never probe a PID")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()

    def test_never_takes_the_lock(self, home):
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()
        assert not (home / "state" / "fleet.lock").exists()

    def test_never_writes_the_registry(self, home):
        _write_registry(home, {"pmbot": _rec()})
        path = home / "state" / "fleet.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        fleet.status_snapshot()
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -v`
Expected: FAIL — `AttributeError: module 'fleet' has no attribute 'status_snapshot'`

- [ ] **Step 3: Implement**

Insert into `bin/fleet.py` immediately after `_worker_flags` (before `hook_events_present`):

```python
# ---------------------------------------------------------------------------
# Phase 1.6 terminal surface (docs/specs/terminal-surface.md): the single
# read-only derivation every view consumes -- statusline, `status --json
# --stale-ok`, the SessionStart hook, and (later) watchtower / web UI.
#
# D1: no fleet_lock, no PLATFORM.get_process_info, no write. This runs on a
# statusline hot path that refires after every assistant message.
# D4: it must NOT call load_registry() -- that quarantines a corrupt registry
# (a write, and a 10s-refresh loop would shred operator evidence). Views
# report corruption; the next real fleet command quarantines it.
# ---------------------------------------------------------------------------

def _read_registry_readonly() -> tuple:
    """(ok, reason, data). Never writes, never quarantines, never raises.

    reason is None when ok, else "not_initialized" | "unreadable"."""
    path = registry_path()
    if not path.exists():
        return (False, "not_initialized", {"workers": {}})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return (False, "unreadable", {"workers": {}})
    if not isinstance(data, dict):
        return (False, "unreadable", {"workers": {}})
    workers = data.get("workers", {})
    if not isinstance(workers, dict) or not all(isinstance(v, dict) for v in workers.values()):
        return (False, "unreadable", {"workers": {}})
    return (True, None, {"workers": workers})


def status_snapshot(now=None) -> dict:
    """Read-only fleet snapshot. See the module comment above for why this
    exists alongside cmd_status rather than reusing it."""
    if now is None:
        now = datetime.now(timezone.utc)
    ok, reason, data = _read_registry_readonly()
    snap = {
        "ok": ok,
        "reason": reason,
        "generated_at": now_iso(),
        "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}},
        "workers": [],
    }
    if not ok:
        return snap

    rows = []
    by_status: dict = {}
    total_mail = 0
    total_cost = 0.0
    for name in sorted(data["workers"]):
        rec = data["workers"][name]
        sid = rec.get("session_id") or ""
        mail = _pending_mail_count(sid) if sid else 0
        cost = _registry_cost(rec.get("cost_usd"))
        try:
            stale = (now - _parse_iso(rec["last_activity"])).total_seconds()
        except (ValueError, TypeError, KeyError):
            stale = None
        status = rec.get("status", "?")
        by_status[status] = by_status.get(status, 0) + 1
        total_mail += mail
        total_cost += cost
        rows.append({
            "name": name,
            "status": status,
            "turns": rec.get("turns", 0),
            "cost_usd": cost,
            "mail": mail,
            "stale_seconds": stale,
            "limit_reset_at": rec.get("limit_reset_at"),
            "limit_kind": rec.get("limit_kind"),
            "resume_eligible": status == "limited" and _limit_reset_passed(rec),
            "attached_since": rec.get("attached_since"),
        })

    snap["workers"] = rows
    snap["totals"] = {
        "workers": len(rows),
        "mail": total_mail,
        "cost_usd": round(total_cost, 6),
        "by_status": by_status,
    }
    return snap
```

Check `_registry_cost` handles `None` → `0.0` (it does; `bin/fleet.py:1325`). Check `_limit_reset_passed` tolerates a missing/None `limit_reset_at` (it does; `:1505`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -v`
Expected: PASS, 16 tests.

Then the full suite, to prove nothing regressed:
Run: `py -3.13 -m pytest -q`
Expected: PASS (same count as before, +16).

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): status_snapshot() read-only derivation

Reads fleet.json + mailbox and stops: no lock, no probe, no write (D1).
Deliberately does not call load_registry(), which quarantines a corrupt
registry -- a statusline refreshing every 10s would loop on that and
destroy operator evidence (D4). Views report; the writer quarantines.

Totals count statuses generically: shipped code has over_budget and
over_ceiling beyond SPEC's five.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `fleet status --json [--stale-ok]`

**Files:**
- Modify: `bin/fleet.py` — `cmd_status` (~line 2020), `build_parser` (~line 4088)
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: `fleet.status_snapshot()` from Task 1.
- Produces: CLI flags `--json`, `--stale-ok` on `fleet status`. Task 6's read-only commands shell out to `fleet status`.

Bare `fleet status` behaviour — the human table, the recompute, the anomaly flags — is unchanged. `--stale-ok` selects the probe-free path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
import argparse


class TestStatusJsonFlags:
    def _args(self, **over):
        base = {"name": None, "json": False, "stale_ok": False}
        base.update(over)
        return argparse.Namespace(**base)

    def test_stale_ok_json_prints_snapshot_and_never_probes(self, home, capsys, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("--stale-ok must never probe")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})

        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["workers"][0]["name"] == "pmbot"
        assert not (home / "state" / "fleet.lock").exists()

    def test_stale_ok_on_corrupt_registry_exits_zero_and_reports(self, home, capsys):
        (home / "state" / "fleet.json").write_text("{bad", encoding="utf-8")
        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["reason"] == "unreadable"
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []

    def test_stale_ok_without_json_prints_the_table(self, home, capsys):
        _write_registry(home, {"pmbot": _rec()})
        rc = fleet.cmd_status(self._args(stale_ok=True))
        assert rc == 0
        assert "pmbot" in capsys.readouterr().out

    def test_parser_accepts_the_flags(self):
        args = fleet.build_parser().parse_args(["status", "--json", "--stale-ok"])
        assert args.json is True and args.stale_ok is True

    def test_parser_defaults_both_flags_off(self):
        args = fleet.build_parser().parse_args(["status"])
        assert args.json is False and args.stale_ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestStatusJsonFlags -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'stale_ok'` inside `cmd_status`, and `unrecognized arguments: --json` from the parser tests.

- [ ] **Step 3: Implement**

In `bin/fleet.py`, at the very top of `cmd_status` (immediately after the docstring, before `with fleet_lock():`), insert the stale-ok short-circuit:

```python
    # Phase 1.6 (D1/D2): --stale-ok is the probe-free, lock-free, write-free
    # read path every view uses. Returns last-COMMITTED status plus
    # stale_seconds; it never asserts liveness it did not probe for.
    if getattr(args, "stale_ok", False):
        snap = status_snapshot()
        if getattr(args, "json", False):
            print(json.dumps(snap, indent=2))
        else:
            _print_snapshot_table(snap, args.name)
        return 0
```

Then, at the end of `cmd_status` (replace the existing `_print_status_table(...)` + hook-error block tail), add `--json` support for the authoritative path. Change:

```python
    _print_status_table({"workers": display}, names)
```

to:

```python
    if getattr(args, "json", False):
        print(json.dumps(status_snapshot(), indent=2))
    else:
        _print_status_table({"workers": display}, names)
```

(The authoritative path has already persisted its verdicts before this line, so re-deriving the snapshot from disk yields exactly the recomputed state.)

Add the snapshot table printer next to `_print_status_table`:

```python
def _print_snapshot_table(snap: dict, name=None) -> None:
    """Human table for `fleet status --stale-ok` (D2): last-committed status
    with an age column, never a probed one."""
    if not snap["ok"]:
        print("fleet: not initialized" if snap["reason"] == "not_initialized"
              else "fleet: registry unreadable")
        return
    rows = [w for w in snap["workers"] if name is None or w["name"] == name]
    if name is not None and not rows:
        raise FleetCliError(f"unknown worker: {name!r}")
    print(f"{'NAME':<20}{'STATUS':<12}{'TURNS':>6}{'COST':>9}{'AGE':>9}{'MAIL':>6}  FLAGS")
    for w in rows:
        age = "?" if w["stale_seconds"] is None else f"{w['stale_seconds'] / 60:.0f}m"
        flags = []
        if w["status"] == "idle" and w["mail"]:
            flags.append("idle+mail")
        if w["resume_eligible"]:
            flags.append("resume-eligible")
        print(
            f"{w['name']:<20}{w['status']:<12}{w['turns']:>6}{w['cost_usd']:>9.2f}"
            f"{age:>9}{w['mail']:>6}  {','.join(flags) or '-'}"
        )
    print("(stale-ok: last-committed state, not probed)")
```

In `build_parser`, extend the `status` subparser (currently `p_status = sub.add_parser("status", ...)` at ~line 4088):

```python
    p_status.add_argument("--json", action="store_true",
                          help="print the status snapshot as JSON")
    p_status.add_argument("--stale-ok", dest="stale_ok", action="store_true",
                          help="read-only fast path: no PID probe, no lock, no write "
                               "(last-committed state; used by the statusline)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -v`
Expected: PASS, 21 tests.

Run: `py -3.13 -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): fleet status --json --stale-ok

--stale-ok short-circuits to status_snapshot(): no probe, no lock, no
write. Bare \`fleet status\` keeps its authoritative recompute. The
stale-ok table prints an AGE column and says so, per D2: never assert
liveness that was not probed for.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `bin/fleet_statusline.py`

**Files:**
- Create: `bin/fleet_statusline.py`
- Modify: `tests/test_steering.py` — `TestPlatformAdapterBoundary`
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: `fleet.status_snapshot()` (Task 1), imported — **not** shelled out to, so registry-schema knowledge stays in one module.
- Produces: `render_statusline(snap, color=True, stale_after=300) -> str` (importable, pure) and a `main()` that reads stdin, discards it, prints one line, exits 0.

Rendering contract:
- `⚑ 3●working 1◐idle+mail 1⏸limited  $2.14`
- Absent states omitted. `limited` appends ` resets <HH:MM>` from `limit_reset_at`, or ` reset?` when null; past-reset appends ` resume-eligible` — **a flag, never a launch** (invariant 1).
- Any worker with `stale_seconds > 300` renders dimmed with a `~<age>` suffix (D2).
- `NO_COLOR` set (or a non-tty) → plain ASCII, no escapes.
- Exit 0 on every path. Any exception → print nothing, exit 0.
- < 20 ms, zero subprocesses.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
import subprocess


@pytest.fixture
def statusline(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
    import fleet_statusline
    return fleet_statusline


class TestStatuslineRender:
    def test_not_initialized(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "not_initialized", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: not initialized"

    def test_unreadable_registry(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "unreadable", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: registry unreadable"

    def test_no_workers(self, statusline):
        snap = {"ok": True, "reason": None, "workers": [],
                "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}}}
        assert statusline.render_statusline(snap, color=False) == "⚑ fleet: no workers"

    def _snap(self, workers):
        by_status = {}
        for w in workers:
            by_status[w["status"]] = by_status.get(w["status"], 0) + 1
        return {"ok": True, "reason": None, "workers": workers,
                "totals": {"workers": len(workers),
                           "mail": sum(w["mail"] for w in workers),
                           "cost_usd": sum(w["cost_usd"] for w in workers),
                           "by_status": by_status}}

    def _w(self, **over):
        base = {"name": "w", "status": "working", "turns": 1, "cost_usd": 1.0,
                "mail": 0, "stale_seconds": 5.0, "limit_reset_at": None,
                "limit_kind": None, "resume_eligible": False, "attached_since": None}
        base.update(over)
        return base

    def test_counts_and_cost(self, statusline):
        snap = self._snap([
            self._w(name="a", status="working", cost_usd=1.02),
            self._w(name="b", status="idle", cost_usd=0.41),
            self._w(name="c", status="dead", cost_usd=0.71),
        ])
        line = statusline.render_statusline(snap, color=False)
        assert "1 working" in line and "1 idle" in line and "1 dead" in line
        assert "$2.14" in line

    def test_idle_with_mail_renders_as_idle_plus_mail(self, statusline):
        snap = self._snap([self._w(name="b", status="idle", mail=1)])
        assert "idle+mail" in statusline.render_statusline(snap, color=False)

    def test_limited_shows_reset_time(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2026-07-09T14:20:00Z")])
        assert "resets 14:20" in statusline.render_statusline(snap, color=False)

    def test_limited_without_reset_shows_unknown(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at=None)])
        assert "reset?" in statusline.render_statusline(snap, color=False)

    def test_limited_past_reset_flags_resume_eligible_only(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2020-01-01T00:00:00Z",
                                   resume_eligible=True)])
        line = statusline.render_statusline(snap, color=False)
        assert "resume-eligible" in line

    def test_stale_worker_gets_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "~40m" in statusline.render_statusline(snap, color=False)

    def test_fresh_worker_has_no_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=299.0)])
        assert "~" not in statusline.render_statusline(snap, color=False)

    def test_color_false_emits_no_escapes(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "\x1b" not in statusline.render_statusline(snap, color=False)

    def test_color_true_emits_escapes(self, statusline):
        snap = self._snap([self._w(status="working")])
        assert "\x1b" in statusline.render_statusline(snap, color=True)


class TestStatuslineMain:
    def test_main_exits_zero_and_prints_a_line(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", __import__("io").StringIO('{"model":{}}'))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0
        assert "⚑" in capsys.readouterr().out

    def test_main_swallows_every_exception_and_prints_nothing(self, statusline, capsys, monkeypatch):
        def boom():
            raise RuntimeError("registry exploded")
        monkeypatch.setattr(statusline.fleet, "status_snapshot", boom)
        monkeypatch.setattr(statusline.sys, "stdin", __import__("io").StringIO(""))
        assert statusline.main() == 0
        assert capsys.readouterr().out == ""

    def test_main_tolerates_garbage_stdin(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {})
        monkeypatch.setattr(statusline.sys, "stdin", __import__("io").StringIO("not json at all"))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0

    def test_main_spawns_no_subprocess(self, home, statusline, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("the statusline must spawn no subprocess")
        monkeypatch.setattr(subprocess, "Popen", boom)
        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(statusline.sys, "stdin", __import__("io").StringIO("{}"))
        _write_registry(home, {"pmbot": _rec()})
        assert statusline.main() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -k Statusline -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet_statusline'`

- [ ] **Step 3: Implement**

Create `bin/fleet_statusline.py`:

```python
#!/usr/bin/env python3
"""claude-fleet statusline (docs/specs/terminal-surface.md §4.3).

Renders one line under the operator's input box in Claude Code. Installed
into ~/.claude/settings.json by `fleet init --statusline` -- a plugin cannot
ship a statusLine (plugin settings.json accepts only `agent` and
`subagentStatusLine`).

Contract, all four points load-bearing:
  * imports fleet.status_snapshot() rather than shelling out, so registry
    schema knowledge lives in exactly one module (invariant 9);
  * no lock, no PID probe, no subprocess, no write (D1);
  * never asserts liveness it did not probe for -- stale rows carry an age
    suffix and are dimmed (D2);
  * exits 0 on every path, printing nothing on error. This is the statusline
    analogue of invariant 2 (exit-0 hooks): a traceback here would render
    under the input box on every refresh.
"""
import json
import os
import sys
from pathlib import Path

_FLEET_HOME = (
    Path(os.environ["FLEET_HOME"]) if os.environ.get("FLEET_HOME")
    else Path(__file__).resolve().parent.parent
)
sys.path.insert(0, str(_FLEET_HOME / "bin"))

import fleet  # noqa: E402

FLAG = "⚑"
STALE_AFTER_SECONDS = 300

_DIM = "\x1b[2m"
_RESET = "\x1b[0m"
_STATUS_COLOR = {
    "working": "\x1b[32m",      # green
    "idle": "\x1b[36m",         # cyan
    "attached": "\x1b[35m",     # magenta
    "limited": "\x1b[33m",      # yellow
    "over_budget": "\x1b[33m",
    "over_ceiling": "\x1b[33m",
    "dead": "\x1b[31m",         # red
}
_STATUS_GLYPH = {
    "working": "●", "idle": "○", "idle+mail": "◐",
    "attached": "◆", "limited": "⏸", "dead": "✗",
}


def _fmt_age(seconds) -> str:
    if seconds is None:
        return "?"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.0f}h"


def _reset_clock(iso) -> str:
    """'2026-07-09T14:20:00Z' -> '14:20'. Any other shape -> the raw value."""
    if not iso:
        return ""
    try:
        return fleet._parse_iso(iso).strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return str(iso)


def _bucket(worker: dict) -> str:
    if worker["status"] == "idle" and worker["mail"]:
        return "idle+mail"
    return worker["status"]


def render_statusline(snap: dict, color: bool = True, stale_after: int = STALE_AFTER_SECONDS) -> str:
    if not snap.get("ok"):
        if snap.get("reason") == "not_initialized":
            return f"{FLAG} fleet: not initialized"
        return f"{FLAG} fleet: registry unreadable"

    workers = snap["workers"]
    if not workers:
        return f"{FLAG} fleet: no workers"

    def paint(text, code):
        return f"{code}{text}{_RESET}" if color and code else text

    buckets: dict = {}
    for w in workers:
        buckets.setdefault(_bucket(w), []).append(w)

    parts = []
    for bucket in sorted(buckets, key=lambda b: (-len(buckets[b]), b)):
        group = buckets[bucket]
        glyph = _STATUS_GLYPH.get(bucket, "○")
        chunk = f"{len(group)}{glyph}{bucket}"

        # D2: a bucket where every worker is stale is rendered dimmed with the
        # freshest age, never silently presented as live.
        stalest = [w["stale_seconds"] for w in group if w["stale_seconds"] is not None]
        if stalest and min(stalest) > stale_after:
            chunk = paint(f"{chunk}~{_fmt_age(min(stalest))}", _DIM)
        else:
            chunk = paint(chunk, _STATUS_COLOR.get(bucket.split("+")[0], ""))

        if bucket == "limited":
            resets = {_reset_clock(w["limit_reset_at"]) for w in group}
            chunk += f" resets {sorted(resets)[0]}" if all(resets) else " reset?"
            if any(w["resume_eligible"] for w in group):
                # invariant 1: a view flags resume-eligibility, it never launches.
                chunk += " resume-eligible"
        parts.append(chunk)

    cost = snap["totals"].get("cost_usd", 0.0)
    return f"{FLAG} " + " ".join(parts) + f"  ${cost:.2f}"


def _want_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return True


def main() -> int:
    try:
        # Claude Code passes a session JSON blob on stdin. Fleet needs none of
        # it today; read and discard so the writer never blocks on a full pipe.
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
        line = render_statusline(fleet.status_snapshot(), color=_want_color())
        print(line)
    except BaseException:  # noqa: BLE001 -- a statusline never surfaces a traceback
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note on `except BaseException`:** deliberate and matched to the hook scripts' exception-proof convention (SPEC §7). A `KeyboardInterrupt` or `SystemExit` escaping here would paint a traceback under the input box on the next refresh.

- [ ] **Step 4: Extend the platform-adapter boundary lint**

The lint currently scans only `fleet.py`. Extend it so invariant 8 stays enforced as the file set grows. In `tests/test_steering.py`, inside `TestPlatformAdapterBoundary`, add:

```python
    def test_new_surface_scripts_have_no_os_branches(self):
        root = Path(fleet.__file__).resolve().parent.parent
        for rel in ("bin/fleet_statusline.py", "bin/hooks/sessionstart_fleet.py"):
            path = root / rel
            if not path.exists():
                continue  # added by a later task in this plan
            source = path.read_text(encoding="utf-8")
            for needle in ("os.name", "sys.platform", "platform.system",
                           "sys.getwindowsversion", "os.uname", "os.sep"):
                assert needle not in source, f"found {needle!r} in {rel}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py tests/test_steering.py -v`
Expected: PASS. 21 + 17 new terminal-surface tests, plus the extended boundary lint.

Then eyeball the real thing:
Run: `echo '{}' | py -3.13 bin/fleet_statusline.py`
Expected: one line beginning `⚑`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add bin/fleet_statusline.py tests/test_terminal_surface.py tests/test_steering.py
git commit -m "feat(terminal-surface): fleet_statusline.py

Imports status_snapshot() rather than shelling out, so registry schema
knowledge stays in one module (invariant 9). No lock, no probe, no
subprocess, no write. Stale buckets dim with an age suffix (D2). A
past-reset limited worker is FLAGGED resume-eligible, never resumed
(invariant 1: views do not start turns).

Exits 0 on every path printing nothing -- the statusline analogue of the
exit-0 hooks invariant; a traceback here renders under the input box on
every refresh.

Boundary lint extended to the new script.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `FLEET_WORKER` env stamp in `launch_turn`

**Files:**
- Modify: `bin/fleet.py` — `launch_turn` (~line 1216, the `popen(...)` call)
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Produces: every worker turn's child process carries `FLEET_WORKER=<name>` in its environment. Task 5's SessionStart hook reads it to suppress itself.

**Why (D5):** a globally-enabled fleet plugin fires its SessionStart hook in **every** Claude Code session on the machine — including every worker turn. Without this stamp, each worker turn gets a fleet briefing injected into its context: wasted tokens, and a worker confused about whether it is the manager.

`launch_turn` currently passes no `env=` to `popen`, so the child inherits the parent's environment. Adding `env=` means we must copy `os.environ` explicitly — omitting it would strip `PATH` and break the launch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
class TestLaunchTurnEnvStamp:
    def _fake_popen_factory(self, captured):
        class _Proc:
            def __init__(self):
                self.stdin = __import__("io").BytesIO()
                self.pid = 4321
            def poll(self):
                return None
        def fake_popen(argv, **kwargs):
            captured.update(kwargs)
            return _Proc()
        return fake_popen

    def test_child_env_carries_fleet_worker_name(self, home, tmp_path, monkeypatch):
        captured = {}
        monkeypatch.setattr(fleet, "resolve_claude_executable", lambda which=None: "claude")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info",
                            lambda pid: ("claude", fleet.datetime.now(fleet.timezone.utc)))
        proj = tmp_path / "proj"
        proj.mkdir()

        fleet.launch_turn("pmbot", proj, "sid-1", "prompt", "dontask", first=True,
                          popen=self._fake_popen_factory(captured))

        assert captured["env"]["FLEET_WORKER"] == "pmbot"

    def test_child_env_preserves_the_parent_environment(self, home, tmp_path, monkeypatch):
        captured = {}
        monkeypatch.setenv("FLEET_TEST_SENTINEL", "kept")
        monkeypatch.setattr(fleet, "resolve_claude_executable", lambda which=None: "claude")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info",
                            lambda pid: ("claude", fleet.datetime.now(fleet.timezone.utc)))
        proj = tmp_path / "proj"
        proj.mkdir()

        fleet.launch_turn("pmbot", proj, "sid-1", "prompt", "dontask", first=True,
                          popen=self._fake_popen_factory(captured))

        assert captured["env"]["FLEET_TEST_SENTINEL"] == "kept"
        assert "PATH" in captured["env"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestLaunchTurnEnvStamp -v`
Expected: FAIL — `KeyError: 'env'` (the current `popen` call passes no `env`).

If these tests error out before reaching the assertion (fake-`Proc` shape mismatch against the real DOA-window loop), adjust `_Proc` to satisfy the loop — it needs `.poll()` and a writable `.stdin` only. Do not weaken the assertions.

- [ ] **Step 3: Implement**

In `bin/fleet.py`, in `launch_turn`, change the `popen(...)` call:

```python
            proc = popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=out_f,
                stderr=err_f,
                env=_worker_env(name),
                **PLATFORM.detached_popen_kwargs(),
            )
```

And add, immediately above `launch_turn`:

```python
def _worker_env(name: str) -> dict:
    """Child environment for a worker turn: the parent's, plus FLEET_WORKER.

    Phase 1.6 D5: a globally-enabled fleet plugin fires its SessionStart hook
    in EVERY Claude Code session on this machine, including every worker turn.
    The hook reads FLEET_WORKER and suppresses itself, so a worker never gets
    the manager's fleet briefing injected into its context.

    os.environ is copied explicitly -- passing env= at all replaces the whole
    inherited environment, and a child without PATH cannot launch."""
    env = dict(os.environ)
    env["FLEET_WORKER"] = name
    return env
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestLaunchTurnEnvStamp -v`
Expected: PASS, 2 tests.

Run the launch-path regressions, which are the ones this could break:
Run: `py -3.13 -m pytest tests/test_steering.py tests/test_cli.py tests/test_resilience.py -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): stamp FLEET_WORKER into worker turn env

A globally-enabled fleet plugin fires SessionStart in every Claude Code
session on the machine, workers included. The hook reads FLEET_WORKER and
suppresses itself (D5), so a worker never receives the manager briefing.

env= replaces the whole inherited environment, so os.environ is copied
explicitly; a child without PATH cannot launch.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `bin/hooks/sessionstart_fleet.py`

**Files:**
- Create: `bin/hooks/sessionstart_fleet.py`
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: `fleet.status_snapshot()` (Task 1), `FLEET_WORKER` (Task 4).
- Produces: a hook that prints `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}` and exits 0. Task 7's `hooks/hooks.json` registers it.

**Note:** existing fleet hooks (`posttooluse_mailbox.py`, `stop_mailbox.py`) never import `fleet.py` — they duplicate `_fleet_home()` standalone, because they run inside worker turns where `fleet.py` may not be importable. This hook is **manager-side** and may import `fleet.py`; it resolves `FLEET_HOME` the same way and degrades to empty output if the import fails.

Budget: `additionalContext` is capped at 10,000 chars. Truncate worker rows first, then INDEX lines.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
@pytest.fixture
def sshook():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin" / "hooks"))
    import sessionstart_fleet
    return sessionstart_fleet


class TestSessionStartHook:
    def test_suppressed_inside_a_worker(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setenv("FLEET_WORKER", "pmbot")
        monkeypatch.setattr(sshook.sys, "stdin",
                            __import__("io").StringIO('{"source":"startup"}'))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_emits_briefing_in_a_manager_session(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin",
                            __import__("io").StringIO('{"source":"startup"}'))
        assert sshook.main() == 0
        payload = json.loads(capsys.readouterr().out)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "pmbot" in ctx and "working" in ctx

    def test_includes_knowledge_index_lines(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {})
        (home / "knowledge").mkdir()
        (home / "knowledge" / "INDEX.md").write_text("- pmbot.md — quirks\n", encoding="utf-8")
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", __import__("io").StringIO("{}"))
        sshook.main()
        assert "pmbot.md" in capsys.readouterr().out

    def test_flags_idle_plus_mail(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"expardus": _rec(status="idle", session_id="s-e")})
        (home / "mailbox" / "s-e.md").write_text("do the thing", encoding="utf-8")
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", __import__("io").StringIO("{}"))
        sshook.main()
        assert "idle+mail" in capsys.readouterr().out

    def test_missing_registry_emits_empty_object_and_exits_zero(self, home, sshook, capsys, monkeypatch):
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", __import__("io").StringIO("{}"))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_any_exception_exits_zero_with_empty_object(self, home, sshook, capsys, monkeypatch):
        def boom():
            raise RuntimeError("kaboom")
        monkeypatch.setattr(sshook.fleet, "status_snapshot", boom)
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", __import__("io").StringIO("{}"))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_context_truncated_to_ten_thousand_chars(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {
            f"worker-{i:03d}": _rec(session_id=f"s-{i}") for i in range(400)})
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", __import__("io").StringIO("{}"))
        sshook.main()
        ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
        assert len(ctx) <= 10_000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -k SessionStart -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sessionstart_fleet'`

- [ ] **Step 3: Implement**

Create `bin/hooks/sessionstart_fleet.py`:

```python
#!/usr/bin/env python3
"""claude-fleet SessionStart hook (docs/specs/terminal-surface.md §4.6).

Injects the fleet briefing into a MANAGER session's context at startup --
the SPEC §10 startup ritual, automated.

Two guards, both load-bearing:
  * D5: suppressed when FLEET_WORKER is set. A globally-enabled fleet plugin
    fires this hook in every Claude Code session on the machine, workers
    included; without the guard, every worker turn burns tokens on a fleet
    briefing it must ignore.
  * invariant 2: exits 0 on every path, printing `{}` on any failure. It
    writes nothing at all -- not even state/hook-errors.log. This is a
    manager-side hook; its failures are invisible-by-design, and the
    operator's own `fleet doctor` is the alarm.

Unlike posttooluse_mailbox.py / stop_mailbox.py -- which run INSIDE worker
turns and therefore never import fleet.py -- this hook is manager-side and
imports it, degrading to `{}` if the import fails.
"""
import json
import os
import sys
from pathlib import Path

MAX_CONTEXT_CHARS = 10_000

_FLEET_HOME = (
    Path(os.environ["FLEET_HOME"]) if os.environ.get("FLEET_HOME")
    else Path(__file__).resolve().parent.parent.parent
)
sys.path.insert(0, str(_FLEET_HOME / "bin"))

try:
    import fleet
except Exception:  # noqa: BLE001 -- degrade silently, never break a session start
    fleet = None


def _emit(context: str = "") -> int:
    if not context:
        print("{}")
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context[:MAX_CONTEXT_CHARS],
    }}))
    return 0


def _worker_line(w: dict) -> str:
    flags = []
    if w["status"] == "idle" and w["mail"]:
        flags.append("idle+mail")
    if w["resume_eligible"]:
        flags.append("resume-eligible")
    if w["status"] == "limited" and w["limit_reset_at"]:
        flags.append(f"resets {w['limit_reset_at']}")
    if w["stale_seconds"] is not None and w["stale_seconds"] > 300:
        flags.append(f"~{w['stale_seconds'] / 60:.0f}m since activity")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    return f"  {w['name']}: {w['status']}, {w['turns']} turns, ${w['cost_usd']:.2f}{suffix}"


def _index_lines(limit: int = 20) -> list:
    path = _FLEET_HOME / "knowledge" / "INDEX.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][:limit]


def _build_context() -> str:
    snap = fleet.status_snapshot()
    if not snap["ok"]:
        return ""

    out = []
    totals = snap["totals"]
    if totals["workers"]:
        out.append(f"FLEET: {totals['workers']} worker(s), ${totals['cost_usd']:.2f} lifetime spend.")
        # Budget: worker rows are truncated FIRST (spec §4.6), so a large
        # fleet never crowds out the knowledge index.
        rows = [_worker_line(w) for w in snap["workers"]]
        room = MAX_CONTEXT_CHARS - 1_500
        kept = []
        used = 0
        for row in rows:
            if used + len(row) + 1 > room:
                kept.append(f"  ... and {len(rows) - len(kept)} more (run `fleet status`)")
                break
            kept.append(row)
            used += len(row) + 1
        out.extend(kept)
    else:
        out.append("FLEET: no workers registered.")

    index = _index_lines()
    if index:
        out.append("")
        out.append("knowledge/INDEX.md:")
        out.extend(f"  {ln}" for ln in index)

    return "\n".join(out)


def main() -> int:
    try:
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
        # D5: never brief a worker about the fleet it belongs to.
        if os.environ.get("FLEET_WORKER"):
            return _emit()
        if fleet is None:
            return _emit()
        return _emit(_build_context())
    except BaseException:  # noqa: BLE001 -- invariant 2: exit 0, always
        try:
            print("{}")
        except BaseException:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py tests/test_steering.py -q`
Expected: PASS. The boundary lint from Task 3 now also scans this file and must stay green.

Run: `py -3.13 -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/hooks/sessionstart_fleet.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): SessionStart briefing hook

Automates the SPEC §10 startup ritual for manager sessions. Suppresses
itself when FLEET_WORKER is set (D5) so a globally-enabled plugin never
injects a fleet briefing into a worker's context.

Exits 0 printing {} on every failure path (invariant 2) and writes nothing
at all, not even hook-errors.log -- it is manager-side, and doctor is the
operator's alarm.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `commands/` — the slash-command set

**Files:**
- Create: `commands/fleet.md`, `commands/status.md`, `commands/peek.md`, `commands/result.md`, `commands/doctor.md` (read-only, inline exec)
- Create: `commands/spawn.md`, `commands/send.md`, `commands/interrupt.md`, `commands/respawn.md`, `commands/kill.md`, `commands/clean.md`, `commands/attach.md`, `commands/release.md`, `commands/resume-limited.md` (mutating, prompt templates)
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: the `fleet` CLI on PATH (via `bin/fleet.cmd`).
- Produces: 14 command files. Task 7's `plugin.json` points at this directory.

**D3, the rule the lint enforces:** `` !`cmd` `` substitutes at prompt-expansion time — before the model sees the prompt, with no permission prompt and no undo. `fleet kill` is terminal (only `respawn` exits `dead`) and `fleet clean` deletes logs, journals and mailboxes. So read-only commands inline; **mutating commands are prompt templates the model executes via Bash**, which routes them through the ordinary permission prompt. Direct control is preserved; the confirmation step is not skipped.

- [ ] **Step 1: Write the failing lint test**

Append to `tests/test_terminal_surface.py`:

```python
COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"

READ_ONLY_COMMANDS = {"fleet", "status", "peek", "result", "doctor"}
MUTATING_COMMANDS = {"spawn", "send", "interrupt", "respawn", "kill", "clean",
                     "attach", "release", "resume-limited"}


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: missing frontmatter"
    _, fm, _body = text.split("---\n", 2)
    out = {}
    for line in fm.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _body(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---\n", 2)[2]


class TestCommandFiles:
    def test_every_expected_command_exists(self):
        found = {p.stem for p in COMMANDS_DIR.glob("*.md")}
        assert found == READ_ONLY_COMMANDS | MUTATING_COMMANDS

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS | MUTATING_COMMANDS))
    def test_every_command_has_a_description(self, name):
        assert _frontmatter(COMMANDS_DIR / f"{name}.md").get("description")

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS))
    def test_read_only_commands_inline_exec_and_declare_allowed_tools(self, name):
        path = COMMANDS_DIR / f"{name}.md"
        assert "!`" in _body(path), f"{name}: read-only command should inline its CLI output"
        assert "Bash" in _frontmatter(path).get("allowed-tools", "")

    @pytest.mark.parametrize("name", sorted(MUTATING_COMMANDS))
    def test_mutating_commands_never_inline_exec(self, name):
        # D3: !`cmd` runs at prompt-expansion time with no permission prompt
        # and no undo. `fleet kill` is terminal; `fleet clean` deletes journals.
        assert "!`" not in _body(COMMANDS_DIR / f"{name}.md"), (
            f"{name} is a mutating command and must not use inline !`` exec"
        )

    @pytest.mark.parametrize("name", sorted(MUTATING_COMMANDS - {"clean"}))
    def test_mutating_commands_declare_an_argument_hint(self, name):
        assert _frontmatter(COMMANDS_DIR / f"{name}.md").get("argument-hint")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestCommandFiles -v`
Expected: FAIL — `FileNotFoundError` / empty set mismatch (no `commands/` dir).

- [ ] **Step 3: Create the read-only commands**

`commands/fleet.md`:

```markdown
---
description: Fleet overview — status table, health warnings, and the knowledge index in one screen.
allowed-tools: Bash(fleet:*)
---

# Fleet overview

## Status

!`fleet status`

## Health

!`fleet doctor`

## Knowledge

!`cat "$FLEET_HOME/knowledge/INDEX.md" 2>/dev/null || cat C:/proga/claude-fleet/knowledge/INDEX.md`

---

Summarize the fleet's state in three lines or fewer: what is running, what needs
attention, and what the operator should do next. If `doctor` reported nothing and
every worker is healthy, say so plainly and stop.
```

`commands/status.md`:

```markdown
---
description: Compact fleet status table — every worker's status, turns, cost, idle time, pending mail.
allowed-tools: Bash(fleet:*)
---

!`fleet status`

Report anomalies only (`idle+mail`, stale attach, `dead`, `limited`, `resume-eligible`).
If there are none, say "fleet healthy" and stop.
```

`commands/peek.md`:

```markdown
---
description: ~20-line digest of a worker's current or last turn. Works mid-turn.
argument-hint: <worker-name> [-n 20]
allowed-tools: Bash(fleet:*)
---

!`fleet peek $ARGUMENTS`

Summarize what this worker is doing right now in two sentences. Do not speculate
beyond what the digest shows.
```

`commands/result.md`:

```markdown
---
description: Final result text of a worker's last completed turn, nothing else.
argument-hint: <worker-name>
allowed-tools: Bash(fleet:*)
---

!`fleet result $1`

Relay the result. If it reports a blocker, say what would unblock it.
```

`commands/doctor.md`:

```markdown
---
description: Fleet health check — claude version, hook wiring, stale PIDs and attaches, orphaned mailboxes, log sizes.
allowed-tools: Bash(fleet:*)
---

!`fleet doctor`

For each reported problem, give the one command that fixes it. Do not run any
of them without being asked.
```

- [ ] **Step 4: Create the mutating commands**

Each is a prompt template. The model runs the CLI via Bash, so the permission prompt applies.

`commands/spawn.md`:

```markdown
---
description: Spawn a new fleet worker on a task in a project directory.
argument-hint: <name> --dir <path> --task <text|@file> [--mode bypass|accept|dontask|plan|omit] [--max-budget-usd x]
---

Spawn a fleet worker with these arguments: `$ARGUMENTS`

Run `fleet spawn $ARGUMENTS` via Bash.

Before running it:
- If `--mode` is absent, it defaults to `dontask` (auto-deny outside the allowlist). Do not silently substitute `bypass`.
- If the task looks unbounded, say so and suggest `--max-budget-usd`.
- If `--dir` does not exist, stop and say so rather than spawning.

After it succeeds, report the worker name, session id, and log path. Do not
immediately peek — the first turn needs time.
```

`commands/send.md`:

```markdown
---
description: Steer a worker — mid-turn message delivered at the next tool boundary, or a new turn if idle.
argument-hint: <worker-name> <message|@file>
---

Send a message to a fleet worker: `$ARGUMENTS`

Run `fleet send $ARGUMENTS` via Bash.

If the worker is mid-turn the message lands at its next tool boundary (seconds).
If it is idle, this starts a new turn. If it is attached, the message queues until
the next headless turn — say so, because fleet hooks do not fire during attach.
```

`commands/interrupt.md`:

```markdown
---
description: Kill a worker's currently running turn. The transcript survives; the worker does not die.
argument-hint: <worker-name>
---

Interrupt the running turn of fleet worker `$1`.

Run `fleet interrupt $1` via Bash.

This kills the turn's process tree. The transcript up to the kill persists and the
worker can be resumed with `fleet send` or continued with `fleet respawn`. Confirm
what the worker was doing (via `fleet peek $1`) before interrupting it.
```

`commands/respawn.md`:

```markdown
---
description: Fresh session for a worker — same name, cwd, mode; journal and drained mailbox carried over. The context-reset lever.
argument-hint: <worker-name> [--task <text>] [--force]
---

Respawn fleet worker: `$ARGUMENTS`

Run `fleet respawn $ARGUMENTS` via Bash.

This mints a new session id and rebuilds context from the worker's journal plus its
drained mailbox — lossless if the journal is current. It refuses while a turn is
running unless `--force` (which interrupts first), and refuses a launch-in-flight
claim even with `--force`.

It also rotates the log. If rotation fails because a follower holds the log handle,
the respawn fails cleanly with no session swap — report that verbatim rather than retrying blindly.
```

`commands/kill.md`:

```markdown
---
description: Interrupt a worker if running, then mark it dead. Terminal — only respawn brings it back.
argument-hint: <worker-name>
---

Kill fleet worker `$1`.

**This is terminal.** A `dead` worker is sticky: no log line and no recompute
resurrects it, and the only exit is `fleet respawn $1`.

Before running anything, confirm with the operator that they mean this worker and
not `fleet interrupt $1` (which kills only the current turn and leaves the worker
alive). Once confirmed, run `fleet kill $1` via Bash.
```

`commands/clean.md`:

```markdown
---
description: Remove dead workers and their logs, mailboxes, and journals. Destructive and irreversible.
---

Clean dead fleet workers.

**This deletes files.** It removes every `dead` worker's registry entry, its
`.jsonl` and `.err` logs plus rotated `.jsonl.1`/`.err.1`, its mailbox and any
orphaned claim files, and its journal.

First run `fleet status` via Bash and show the operator exactly which workers are
`dead` and will be swept. Ask for confirmation. Only then run `fleet clean`.

A journal is the only record of what a worker learned. If any dead worker's journal
looks worth keeping, say so before sweeping it.
```

`commands/attach.md`:

```markdown
---
description: Open an interactive terminal on a worker's session — full TUI, whole history.
argument-hint: <worker-name> [--force]
---

Attach an interactive terminal to fleet worker: `$ARGUMENTS`

Run `fleet attach $ARGUMENTS` via Bash.

This opens a real Claude Code TUI in a separate window (Windows Terminal, or a
PowerShell fallback). It refuses while a turn is running unless `--force`, which
interrupts the turn first.

Two things the operator must know: the attached TUI runs **without** fleet's
`--settings`, so fleet hooks do not fire and any mail queues until the next headless
turn; and closing the tab does not detach — they must run `fleet release $1`.
```

`commands/release.md`:

```markdown
---
description: Hand an attached worker back to the fleet — attached → idle.
argument-hint: <worker-name>
---

Release fleet worker `$1` back to idle.

Run `fleet release $1` via Bash.

Attach status is sticky and TUI-close detection is unreliable on Windows, so this
explicit release is the only exit. If the worker has mail queued from while it was
attached, `fleet status` will show `idle+mail` afterwards; the next turn drains it.
```

`commands/resume-limited.md`:

```markdown
---
description: Resume workers parked on a Claude plan usage limit whose reset horizon has passed.
argument-hint: [worker-name] [--force-now]
---

Resume usage-limit-parked fleet workers: `$ARGUMENTS`

Run `fleet resume-limited $ARGUMENTS` via Bash.

This relaunches only `limited` workers whose `limit_reset_at` has passed, through
the ordinary lock-guarded launch path with their mailbox and journal drained into
the prompt. It skips workers still before their reset horizon, and workers whose
reset horizon is unknown (`limit_reset_at: null`) unless `--force-now` names them.

A `weekly` park can last days. Do not `--force-now` past an unknown horizon without
the operator explicitly asking — it will just hit the wall again.
```

- [ ] **Step 5: Run the lint to verify it passes**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestCommandFiles -v`
Expected: PASS, 33 tests (1 + 14 + 5 + 9 + 8 parametrized).

- [ ] **Step 6: Commit**

```bash
git add commands/ tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): /fleet:* slash commands

Read-only commands (fleet, status, peek, result, doctor) inline their CLI
output via !\`cmd\`. Mutating commands (spawn, send, interrupt, respawn,
kill, clean, attach, release, resume-limited) are prompt templates the
model executes via Bash, so the permission prompt applies.

D3: inline exec substitutes at prompt-expansion time with no confirmation
and no undo, and \`fleet kill\` is terminal while \`fleet clean\` deletes
journals. A lint enforces the split rather than trusting convention.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Plugin packaging

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Move: `skill/SKILL.md` → `skills/fleet/SKILL.md`
- Modify: `README.md` (install one-liner)
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: `commands/` (Task 6), `bin/hooks/sessionstart_fleet.py` (Task 5).
- Produces: an installable plugin. **It ships no statusline** — plugin `settings.json` accepts only `agent` and `subagentStatusLine`. That is Task 8's job.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
REPO = Path(__file__).resolve().parent.parent


class TestPluginPackaging:
    def test_manifest_exists_and_names_the_plugin(self):
        manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["name"] == "claude-fleet"
        assert manifest["description"]

    def test_manifest_does_not_ship_a_statusline(self):
        # A plugin CANNOT ship a statusLine; plugin settings.json accepts only
        # `agent` and `subagentStatusLine`. fleet init --statusline installs it.
        raw = (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        assert "statusLine" not in raw

    def test_skill_lives_at_the_plugin_standard_path(self):
        assert (REPO / "skills" / "fleet" / "SKILL.md").exists()
        assert not (REPO / "skill").exists()

    def test_hooks_json_registers_sessionstart(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        entries = hooks["hooks"]["SessionStart"]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        assert any("sessionstart_fleet.py" in c for c in commands)

    def test_hook_commands_use_forward_slashes(self):
        # Git Bash sh -c eats backslashes in unquoted strings.
        raw = (REPO / "hooks" / "hooks.json").read_text(encoding="utf-8")
        assert "\\\\" not in raw
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestPluginPackaging -v`
Expected: FAIL — `FileNotFoundError: .claude-plugin/plugin.json`

- [ ] **Step 3: Move the skill**

```bash
mkdir -p skills/fleet
git mv skill/SKILL.md skills/fleet/SKILL.md
rmdir skill 2>/dev/null || true
```

- [ ] **Step 4: Create the manifest**

`.claude-plugin/plugin.json`:

```json
{
  "name": "claude-fleet",
  "displayName": "claude-fleet",
  "description": "Spawn, steer, monitor and hand off multiple Claude Code worker sessions across projects from one manager session.",
  "version": "0.1.0",
  "author": "Altai",
  "keywords": ["fleet", "orchestration", "sessions", "workers"],
  "commands": "./commands",
  "skills": "./skills",
  "hooks": "./hooks/hooks.json"
}
```

`hooks/hooks.json` (note: `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin directory; forward slashes throughout):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "py -3.13 ${CLAUDE_PLUGIN_ROOT}/bin/hooks/sessionstart_fleet.py"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: Update the README install section**

Replace the skill-install one-liner in `README.md` with both paths — read the file first, then edit the install section to read:

```markdown
## Install

```powershell
py -3.13 bin\fleet.py init          # render state\worker-settings.json
py -3.13 bin\fleet.py init --statusline   # optional: fleet statusline in Claude Code
```

Add `bin\` to PATH so `fleet` resolves, then load the plugin for `/fleet:*` commands
and the SessionStart briefing:

```
claude --plugin-dir C:/proga/claude-fleet
```

The statusline is installed separately (`init --statusline`) because a Claude Code
plugin cannot ship one.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestPluginPackaging -v`
Expected: PASS, 5 tests.

Run the whole suite — the skill move may have broken a path assertion somewhere:
Run: `py -3.13 -m pytest -q`
Expected: PASS. If a test references `skill/SKILL.md`, update it to `skills/fleet/SKILL.md`.

- [ ] **Step 7: Commit**

```bash
git add .claude-plugin/ hooks/ skills/ README.md tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): package fleet as a Claude Code plugin

Bundles commands/, skills/fleet/, and the SessionStart hook. Ships NO
statusline: plugin settings.json accepts only \`agent\` and
\`subagentStatusLine\`, so the statusline is installed separately by
\`fleet init --statusline\`.

skill/SKILL.md moves to the plugin-standard skills/fleet/SKILL.md.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `fleet init --statusline`

**Files:**
- Modify: `bin/fleet.py` — `cmd_init` (~line 1867), `build_parser` (~line 4065)
- Test: `tests/test_terminal_surface.py`

**Interfaces:**
- Consumes: `bin/fleet_statusline.py` (Task 3).
- Produces: `fleet init --statusline [--force]`. The one write in this phase, and it lands outside `state/`.

**Contract (D6):** back up, merge only the `statusLine` key, **refuse a foreign statusline** unless `--force`. Operators commonly run `ccusage`; silently clobbering it is unacceptable. Plain `fleet init` never touches user settings.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_surface.py`:

```python
class TestInitStatusline:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        path = tmp_path / "dot-claude" / "settings.json"
        monkeypatch.setattr(fleet, "user_settings_path", lambda: path)
        return path

    def _args(self, **over):
        base = {"statusline": False, "force": False}
        base.update(over)
        return argparse.Namespace(**base)

    def test_plain_init_never_touches_user_settings(self, home, settings, monkeypatch, capsys):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args())
        assert not settings.exists()

    def test_statusline_creates_settings_when_absent(self, home, settings, capsys):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        assert fleet.cmd_init(self._args(statusline=True)) == 0
        payload = json.loads(settings.read_text(encoding="utf-8"))
        assert "fleet_statusline.py" in payload["statusLine"]["command"]
        assert payload["statusLine"]["type"] == "command"

    def test_statusline_command_uses_forward_slashes(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args(statusline=True))
        cmd = json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert "\\" not in cmd

    def test_statusline_backs_up_and_preserves_siblings(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"model": "opus", "env": {"A": "1"}}), encoding="utf-8")

        fleet.cmd_init(self._args(statusline=True))

        payload = json.loads(settings.read_text(encoding="utf-8"))
        assert payload["model"] == "opus"
        assert payload["env"] == {"A": "1"}
        assert payload["statusLine"]["type"] == "command"
        assert list(settings.parent.glob("settings.json.bak.*"))

    def test_statusline_refuses_a_foreign_statusline(self, home, settings, capsys):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "ccusage statusline"}}), encoding="utf-8")

        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_init(self._args(statusline=True))
        assert "ccusage" in str(exc.value)
        # Untouched.
        assert "ccusage" in settings.read_text(encoding="utf-8")

    def test_force_overwrites_a_foreign_statusline(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "ccusage statusline"}}), encoding="utf-8")

        assert fleet.cmd_init(self._args(statusline=True, force=True)) == 0
        assert "fleet_statusline.py" in settings.read_text(encoding="utf-8")

    def test_reinstall_over_fleets_own_statusline_is_idempotent(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args(statusline=True))
        first = json.loads(settings.read_text(encoding="utf-8"))
        assert fleet.cmd_init(self._args(statusline=True)) == 0
        assert json.loads(settings.read_text(encoding="utf-8")) == first

    def test_corrupt_user_settings_refuses_rather_than_clobbering(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text("{not json", encoding="utf-8")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_init(self._args(statusline=True))
        assert settings.read_text(encoding="utf-8") == "{not json"

    def test_parser_accepts_statusline_and_force(self):
        args = fleet.build_parser().parse_args(["init", "--statusline", "--force"])
        assert args.statusline is True and args.force is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestInitStatusline -v`
Expected: FAIL — `AttributeError: module 'fleet' has no attribute 'user_settings_path'`

- [ ] **Step 3: Implement**

In `bin/fleet.py`, add next to the other path helpers (after `instance_settings_path`, ~line 143):

```python
def user_settings_path() -> Path:
    """~/.claude/settings.json -- the ONLY file outside FLEET_HOME that fleet
    ever writes, and only via `fleet init --statusline` (D6). Separate helper
    so tests can redirect it without touching a developer's real settings."""
    return Path.home() / ".claude" / "settings.json"


def statusline_script_path() -> Path:
    return FLEET_HOME / "bin" / "fleet_statusline.py"
```

Add the installer above `cmd_init`:

```python
def _install_statusline(force: bool = False) -> None:
    """Merge fleet's statusLine into ~/.claude/settings.json (D6).

    A Claude Code plugin cannot ship a statusLine -- plugin settings.json
    accepts only `agent` and `subagentStatusLine` -- so this explicit,
    opt-in step is the only way to install one. It backs up first, merges
    ONLY the statusLine key, and refuses a foreign statusline (an operator
    running ccusage or similar must not lose it silently)."""
    path = user_settings_path()
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise FleetCliError(
                f"refusing to touch an unreadable {path}: {exc} -- fix or move it, then re-run"
            ) from exc
        if not isinstance(settings, dict):
            raise FleetCliError(f"refusing to touch {path}: not a JSON object")

    script = statusline_script_path().resolve().as_posix()
    existing = settings.get("statusLine")
    if isinstance(existing, dict) and "fleet_statusline.py" not in str(existing.get("command", "")):
        if not force:
            raise FleetCliError(
                f"statusLine already set to {existing.get('command')!r} in {path} -- "
                "re-run with --force to overwrite"
            )

    if path.exists():
        backup = path.with_name(f"settings.json.bak.{now_iso().replace(':', '').replace('-', '')}")
        shutil.copy2(path, backup)
        print(f"  backup:      {backup}")

    settings["statusLine"] = {
        "type": "command",
        # Forward slashes: this command string is executed through a shell.
        "command": f"{Path(sys.executable).resolve().as_posix()} {script}",
        "refreshInterval": 10,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"fleet init: installed statusLine into {path}")
    print("  restart Claude Code to see it")
```

In `cmd_init`, append before `return 0`:

```python
    if getattr(args, "statusline", False):
        _install_statusline(force=getattr(args, "force", False))
```

In `build_parser`, replace the bare `sub.add_parser("init", ...)` line with:

```python
    p_init = sub.add_parser("init", help="render the machine-local worker-settings.json instance from the template")
    p_init.add_argument("--statusline", action="store_true",
                        help="also install fleet's statusline into ~/.claude/settings.json")
    p_init.add_argument("--force", action="store_true",
                        help="with --statusline: overwrite an existing foreign statusline")
```

Confirm `shutil` is already imported in `fleet.py` (it is — `resolve_claude_executable` uses `shutil.which`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py::TestInitStatusline -v`
Expected: PASS, 9 tests.

Run: `py -3.13 -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Verify by hand, on the real machine**

Run: `py -3.13 bin/fleet.py init --statusline`
Expected: prints a backup path and `installed statusLine into ...`. Inspect `~/.claude/settings.json` and confirm your other keys survived.

Run it again. Expected: idempotent, same result, no error.

- [ ] **Step 6: Commit**

```bash
git add bin/fleet.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): fleet init --statusline

Opt-in, backs up ~/.claude/settings.json, merges only the statusLine key,
and refuses a foreign statusline unless --force (D6) -- an operator
running ccusage must not lose it silently. Plain \`fleet init\` never
touches user settings.

Exists because a plugin cannot ship a statusLine at all.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Documentation

**Files:**
- Modify: `docs/ROADMAP.md` (add Phase 1.6 after Phase 1.5)
- Modify: `docs/SPEC.md` (§3 repo layout; new §15)
- Modify: `CLAUDE.md` (surface rules a future session needs)

**Interfaces:**
- Consumes: everything built in Tasks 1–8.
- Produces: no code.

- [ ] **Step 1: Add Phase 1.6 to ROADMAP.md**

Insert immediately after the "Phase 1.5 — Portability" section and before "Phase 2 — Watchtower":

```markdown
## Phase 1.6 — Terminal surface (fleet inside the Claude Code TUI)

Spec: `docs/specs/terminal-surface.md`. Independent of watchtower; buildable any time after Phase 1.

Pure UX and packaging — no new capability, no new state, no daemon. One read-only derivation (`fleet.status_snapshot()`: reads `fleet.json` + `mailbox/`, takes no lock, spawns no probe, writes nothing) feeds four views:

- **statusline** — always-on one-line fleet readout under the input box. Dims stale rows rather than asserting liveness it never probed for.
- **`/fleet:*` slash commands** — read-only commands inline their CLI output; mutating ones route through the model so the permission prompt applies (`fleet kill` is terminal, `fleet clean` deletes journals).
- **SessionStart briefing** — the SPEC §10 startup ritual, automated. Suppresses itself inside workers via a `FLEET_WORKER` env stamp.
- **plugin package** — commands + skill + hook. Cannot ship the statusline (Claude Code forbids it); `fleet init --statusline` installs that separately, refusing to clobber a foreign one.

Done when: fleet state is visible without typing a command, and `/fleet` answers "where am I" in one screen.
```

- [ ] **Step 2: Update SPEC.md §3 repo layout**

In the ```` ``` ```` block under "## 3. Repo layout", replace the `skill\SKILL.md` line and add the new paths:

```
  bin\
    fleet.py              # single-file CLI, py -3.13, stdlib only
    fleet_statusline.py   # Phase 1.6 statusline renderer (imports fleet.py; read-only)
    fleet.cmd             # shim: @py -3.13 C:\proga\claude-fleet\bin\fleet.py %*  (dir added to PATH)
    hooks\
      posttooluse_mailbox.py   # mid-turn mailbox injection
      stop_mailbox.py          # turn-end mailbox drain / stop-block
      sessionstart_fleet.py    # Phase 1.6 manager-session briefing (suppressed in workers)
  .claude-plugin\plugin.json   # Phase 1.6 plugin manifest (ships NO statusline -- not permitted)
  commands\               # Phase 1.6 /fleet:* slash commands
  hooks\hooks.json        # Phase 1.6 plugin SessionStart registration
  skills\fleet\SKILL.md   # manager skill (plugin-standard path; was skill\SKILL.md)
```

- [ ] **Step 3: Add SPEC §15**

Append to `docs/SPEC.md`, after §14 and before the appendices:

```markdown
## 15. Terminal surface (Phase 1.6)

Full spec: `docs/specs/terminal-surface.md`. A statusline, `/fleet:*` slash commands, a SessionStart briefing, and a plugin package — four DERIVED views over one read-only derivation, `fleet.status_snapshot()`.

The three rules the rest of the spec implies but never had to state, now that a view refreshes on a hot path:

- **A view never takes `fleet.lock`, never probes a PID, and never writes.** `status_snapshot()` reads `fleet.json` + `mailbox/` and stops. `fleet status` (no flag) keeps its authoritative recompute; `fleet status --stale-ok` is the view path (invariants 6, 9).
- **A view reports registry corruption; it does not quarantine.** §11's quarantine (`fleet.json.corrupt.<ts>` + `registry_corrupt` event + exit 1) is a WRITE and belongs to the single writer. A statusline refreshing every 10 s would loop on it, destroying operator evidence. Views print "registry unreadable" and exit 0.
- **A view flags, it never launches.** A `limited` worker past its reset horizon renders `resume-eligible`; the resume itself stays the explicit `fleet resume-limited` sweep (invariant 1).

Nothing in §1–§14 changes. Every surface is optional: the CLI works fully with the statusline uninstalled, the plugin absent, and the hook unregistered.
```

- [ ] **Step 4: Update CLAUDE.md**

Append to the Rules list in `CLAUDE.md`:

```markdown
- Views (statusline, `/fleet:*`, SessionStart hook) never take `fleet.lock`, never probe a PID, never write, and never quarantine a corrupt registry — they read `fleet.status_snapshot()` and exit 0. See `docs/specs/terminal-surface.md`.
- Mutating slash commands are prompt templates, never inline `` !`cmd` `` — inline exec skips the permission prompt, and `fleet kill`/`fleet clean` are irreversible. A lint in `tests/test_terminal_surface.py` enforces this.
- A plugin cannot ship a `statusLine`. It is installed by `fleet init --statusline`.
```

- [ ] **Step 5: Verify nothing broke**

Run: `py -3.13 -m pytest -q`
Expected: PASS.

Run: `py -3.13 bin/fleet.py status --stale-ok`
Expected: the stale-ok table, or `fleet: not initialized`.

- [ ] **Step 6: Commit**

```bash
git add docs/ROADMAP.md docs/SPEC.md CLAUDE.md
git commit -m "docs: Phase 1.6 terminal surface in ROADMAP, SPEC §3/§15, CLAUDE.md

Records the three rules a hot-path view must obey, which the spec implied
but never had to state: a view never locks/probes/writes; a view reports
registry corruption without quarantining it; a view flags resume-eligible
without launching.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Deferred (explicitly out of scope)

- **SPEC F20 drift.** SPEC §4/§12 tag the three-way PID probe `[UNBUILT — C2 hardening kernel item 9]`; it has shipped (`probe_liveness` at `bin/fleet.py:556`, `ACCESS_DENIED` marker + `Get-CimInstance` fallback at `:199-237`, never-demote at `:816`, doctor check at `:3772`). A doc-only pass should reclassify it from prescriptive to descriptive. This plan depends on none of it.
- **Interactive TUI inside Claude Code.** Not supported by the platform: no click handling, no keyboard events, no widgets. Verified against CC 2.1.202+ docs.
- **`subagentStatusLine`.** A plugin *can* ship one; fleet has no subagent rows to render. Revisit if worker subagents (UL2) ever need per-row display.
