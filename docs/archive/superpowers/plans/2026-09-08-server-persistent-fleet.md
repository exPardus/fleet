# Server Persistent Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one persistent fleet on the kz-work server, steered from Telegram through the existing ccgram-bound tmux window, with a page-only keeper timer that turns every silent-death mode into a Telegram message.

**Architecture:** Three layers. (1) A tmux window `work:fleet` running an interactive `claude` session is the interface tier; ccgram gives it a Telegram topic for free. (2) The fleet itself is unchanged except that `sup-spawn` gains `--setting-sources` so supervisor bodies stop tripping the user-level ccgram hooks. (3) `bin/fleet_keeper.py`, run by a systemd user timer every 15 minutes, observes fleet state read-only and types one-line pages into `work:fleet`; it never dispatches anything.

**Tech Stack:** Python stdlib only (floor 3.10), pytest, tmux 3.4, systemd user units, Ansible role in `~/china-infra`.

**Spec:** `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`

> **⛔ SUPERSEDED IN PART — 2026-09-09, and this banner exists because this document PASTES WHOLE FILES.**
> Task 8 and Task 10 below carry verbatim copies of `docs/operator/server-interface-profile.md` and
> `supervisor/briefs/server-standing.md` as they were written on 2026-09-08. Both **live files have since
> been rewritten** by the 2026-09-09 succession ruling and its amendment: the interface no longer waits
> for the operator's `revive`, it dispatches on a `KEEPER: … relaunch` page after a two-live-body guard,
> and a supervisor at its band runs a four-step graceful end. **Read the live files, never these copies.**
> The plan is kept unedited below as the record of what was built and in what order. Sources:
> `state/tasks/20260909-succession-ruling.md` (with its `## AMENDMENT`),
> `knowledge/lessons.md#2026-09-09-keeper-revives`, the design spec's own 2026-09-09 amendment section,
> and `docs/lanes/w58-docs.md` for the corrections the ruling earned.

## Global Constraints

- `bin/fleet.py` is stdlib-only, single file. `bin/fleet_keeper.py` is a second stdlib-only file beside it, following the `bin/fleet_statusline.py` precedent.
- Interpreter floor is `fleet.MIN_PYTHON_VERSION == (3, 10)`. Every change runs green on both 3.10 and 3.12 (this box has no 3.13). Run commands: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider --ignore=tests/integration` and the same with `--python 3.10`.
- Baseline before any change (measured 2026-09-08 with the commands above): see the numbers recorded in Task 0. A task is green only when its own tests pass AND the totals move by exactly the tests it added.
- Views never take `fleet.lock`, never probe, never write, never quarantine. The keeper is a view plus two tmux actions.
- The keeper contains no call to `dispatch_bg`, `cmd_spawn`, `cmd_sup_spawn`, `_dispatch_supervisor_body`, `cmd_send`, `cmd_respawn`, `fleet_lock`. Pinned by AST.
- No background processes via shell `&`. The keeper runs subprocesses synchronously with `timeout=`.
- Receipts pasted into `docs/specs/**` carry `# at <sha>`; this plan's host receipts go to `docs/operator/keeper-soak-2026-09.md` marked `# volatile: host state`, not into `docs/specs/`.
- Host config files under `~/.config/systemd/user` are rendered by Ansible from `~/china-infra`; never hand-edit them on the host. Hand-run the keeper only from the repo path during rehearsal.
- Git identity is not configured globally on this box. Commit with the repo's existing author: `git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit …`. Do not push unless the operator says so.
- Bash on this box is zsh: never use `echo ===` as a separator (zsh `=cmd` expansion); use `printf '--- %s ---\n' NAME`; quote every glob.
- `docs/OPERATOR-GATES.md` open lines are questions ending in `?`; settled lines move under `## Settled` with date and answer. Neither the implementer nor a worker ticks a box.

---

### Task 0: Record the baseline and the runner

**Files:**
- Create: `docs/operator/keeper-soak-2026-09.md`

**Interfaces:**
- Produces: the baseline pass/fail/skip totals every later task compares against.

- [ ] **Step 1: Run the suite on both interpreters and capture totals**

Run:
```bash
cd /home/altai/proga/fleet
uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider --ignore=tests/integration 2>&1 | tail -3
uv run --python 3.10 --with pytest -q python -m pytest -q -p no:cacheprovider --ignore=tests/integration 2>&1 | tail -3
```
Expected: a `N passed, M failed, K skipped` line per interpreter. Measured 2026-09-08 at `09819e1`, identical on both interpreters: `6 failed, 4638 passed, 7 skipped, 1 xfailed`. The six pre-existing failures are all Windows-path or spaces-in-`FLEET_PYTHON` cases (`tests/test_fleet_index.py::TestPathContainment` ×3, `tests/test_fleet_q.py::TestOutlinePathContainment::test_an_absolute_path_outside_the_root_is_refused_too`, `tests/test_terminal_surface.py::TestCollaboratorInstall` ×2). Record whatever you measure; do not fix them in this plan.

- [ ] **Step 2: Write the soak file header with the numbers**

```markdown
# Keeper soak — September 2026

Host receipts for `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
Every block here is `# volatile: host state` — evidence lives on kz-work, not in the tree.

## Baseline (before Task 1)

```text
# volatile: host state — measured <YYYY-MM-DD>, commit <sha of HEAD>
3.12: <paste tail line>
3.10: <paste tail line>
pre-existing failures (6, same set on both): tests/test_fleet_index.py::TestPathContainment x3, tests/test_fleet_q.py::TestOutlinePathContainment x1, tests/test_terminal_surface.py::TestCollaboratorInstall x2
```

## Pages observed

| when (UTC) | rule | text | true/false page | action taken |
|---|---|---|---|---|
```

- [ ] **Step 3: Commit**

```bash
git add docs/operator/keeper-soak-2026-09.md
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "docs(operator): open the keeper soak log with the suite baseline"
```

---

### Task 1: `fleet sup-spawn --setting-sources`

**Files:**
- Modify: `bin/fleet.py` — `cmd_sup_spawn` (~line 17585), `_dispatch_supervisor_body` (~line 17619, its `dispatch_bg` call ~17678 and `new_worker_record` call ~17654), the `sup-spawn` argparse block (~line 21581)
- Test: `tests/test_sup_spawn_setting_sources.py`

**Interfaces:**
- Consumes: `dispatch_bg(..., setting_sources=None, ...)` already accepts the kwarg and appends `["--setting-sources", value]` after `--settings`. `tests/test_sup_spawn.py` provides the fixture shape (`native_home`, `_fake_run_factory`, `_roster_with`).
- Produces: `fleet sup-spawn --task … --setting-sources project,local` dispatches with the flag and persists `setting_sources` on the supervisor's registry record so `respawn`/`send` forward it like they do for workers.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sup_spawn_setting_sources.py`:

```python
"""sup-spawn carries --setting-sources through to the dispatched body.

On a host where ~/.claude/settings.json registers foreign Stop hooks (the
kz-work ccgram bridge), a supervisor body dispatched without
--setting-sources runs those hooks with an environment inherited from the
daemon's first dispatch and gets attributed to the wrong tmux window.
`spawn` already has the passthrough; this pins the same flag on `sup-spawn`.
"""
from types import SimpleNamespace

import pytest

import fleet
from tests.test_sup_spawn import (  # noqa: F401  (fixtures re-exported)
    _fake_run_factory,
    _roster_with,
    _the_one_worker,
    native_home,
)


def _args(setting_sources=None):
    return SimpleNamespace(task="boot and report", model=None,
                           permission_mode=None, nonce=None,
                           setting_sources=setting_sources)


def _spawn(native_home, monkeypatch, args, calls):
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
    run = _fake_run_factory(stdout="", rc=0, calls=calls)
    return fleet.cmd_sup_spawn(args, run=run, which=lambda _: "/usr/bin/claude",
                               sleep=lambda *_: None, clock=lambda: 0.0)


def test_the_flag_reaches_the_argv_after_settings(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args("project,local"), calls) == 0
    argv = calls[0][0]
    i = argv.index("--setting-sources")
    assert argv[i + 1] == "project,local"
    assert i > argv.index("--settings")


def test_the_flag_is_persisted_on_the_supervisor_record(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args("project,local"), calls) == 0
    _, rec = _the_one_worker()
    assert rec["setting_sources"] == "project,local"


def test_without_the_flag_nothing_changes(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args(None), calls) == 0
    assert "--setting-sources" not in calls[0][0]
    _, rec = _the_one_worker()
    assert rec.get("setting_sources") is None


def test_the_parser_accepts_the_flag():
    parser = fleet.build_parser()
    ns = parser.parse_args(["sup-spawn", "--task", "x",
                            "--setting-sources", "project"])
    assert ns.setting_sources == "project"
```

If `tests/test_sup_spawn.py` names its helpers differently from `_fake_run_factory` / `_roster_with` / `_the_one_worker` / `native_home`, open it (lines 41–110) and import the real names; do not duplicate the fixture. If `fleet.build_parser` does not exist, grep `bin/fleet.py` for `argparse.ArgumentParser(` and use the function that returns the parser (or drop the parser test and instead assert on `SimpleNamespace` handling only).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_sup_spawn_setting_sources.py -v`
Expected: the first two tests FAIL (`ValueError: '--setting-sources' is not in list` / `KeyError: 'setting_sources'`), the parser test FAILS with `unrecognized arguments`.

- [ ] **Step 3: Add the argparse flag**

In `bin/fleet.py`, inside the `sup-spawn` parser block (after the `--nonce` line):

```python
    # Same raw passthrough `spawn` has (SPEC §6): a host whose user-level
    # settings register foreign Stop hooks (kz-work's ccgram bridge) needs
    # the supervisor body dispatched without them, or every body's hook
    # events land on the tmux window that first launched the daemon.
    p_supspawn.add_argument("--setting-sources", dest="setting_sources", default=None)
```

- [ ] **Step 4: Thread the value through `cmd_sup_spawn` → `_dispatch_supervisor_body` → record + `dispatch_bg`**

In `cmd_sup_spawn`, change the return to:

```python
    return _dispatch_supervisor_body(campaign, mode, getattr(args, "model", None),
                                     setting_sources=getattr(args, "setting_sources", None),
                                     run=run, which=which, sleep=sleep, clock=clock)
```

Change `_dispatch_supervisor_body`'s signature to:

```python
def _dispatch_supervisor_body(campaign, mode, model, *, setting_sources=None,
                              run=subprocess.run, which=shutil.which,
                              sleep=time.sleep, clock=time.monotonic) -> int:
```

Add `setting_sources=setting_sources,` to its `new_worker_record(...)` call (mirror `cmd_spawn` at ~line 6623, which passes `setting_sources=args.setting_sources`). Add `setting_sources=setting_sources,` to its `dispatch_bg(...)` call. Do not add a new `dispatch_bg` call site — `tests/test_index_compose.py::test_the_dispatch_census_reflects_five_paths` counts them.

- [ ] **Step 5: Run the new tests and the neighbours**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_sup_spawn_setting_sources.py tests/test_sup_spawn.py tests/test_index_compose.py tests/test_resilience.py -v 2>&1 | tail -5`
Expected: all PASS.

- [ ] **Step 6: Run the full suite on both interpreters**

Run both baseline commands from Task 0. Expected: passed count = baseline + 4 on each; failed/skipped unchanged.

- [ ] **Step 7: Commit**

```bash
git add bin/fleet.py tests/test_sup_spawn_setting_sources.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(sup-spawn): carry --setting-sources to the supervisor body like spawn does"
```

---

### Task 2: Keeper rules as pure functions

**Files:**
- Create: `bin/fleet_keeper.py`
- Test: `tests/test_keeper_rules.py`

**Interfaces:**
- Produces:
  - `Page = namedtuple("Page", "rule fingerprint text")`
  - `evaluate(obs: dict, now: float) -> list[Page]` — pure.
  - Observation dict shape (built by Task 4's `collect`):
    ```python
    {
      "goals_active": bool,
      "claim_state": "none" | "held" | "released" | "unknown",
      "heartbeat_age_seconds": float | None,
      "pending_decision": str | None,
      "sup_sessions": ["sup|inc-…|boot", ...],     # names from `claude agents --json`
      "agents_ok": bool,                            # `claude agents --json` exited 0
      "registry_ok": bool, "registry_reason": str | None,
      "workers": [{"name": str, "status": str, "mail": int, "limit_kind": str | None}, ...],
      "unpushed": int, "oldest_unpushed_ts": float | None,
      "hook_error_lines": int, "prev_hook_error_lines": int,
    }
    ```
  - Constants: `HEARTBEAT_STALE_SECONDS = 3600`, `UNPUSHED_PAGE_SECONDS = 6 * 3600`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keeper_rules.py`:

```python
"""The keeper's rules are pure: one observation in, zero or more pages out.

Each rule is tested with a known-firing and a known-silent observation so a
rule that never fires (or always fires) cannot pass.
"""
import fleet_keeper as k

NOW = 1_800_000_000.0


def _obs(**over):
    base = {
        "goals_active": True,
        "claim_state": "held",
        "heartbeat_age_seconds": 120.0,
        "pending_decision": None,
        "sup_sessions": ["sup|launch-1|boot"],
        "agents_ok": True,
        "registry_ok": True,
        "registry_reason": None,
        "workers": [],
        "unpushed": 0,
        "oldest_unpushed_ts": None,
        "hook_error_lines": 0,
        "prev_hook_error_lines": 0,
    }
    base.update(over)
    return base


def _rules(pages):
    return sorted(p.rule for p in pages)


def test_a_healthy_fleet_pages_nothing():
    assert k.evaluate(_obs(), NOW) == []


def test_released_claim_with_goals_active_pages_supervisor_dead():
    pages = k.evaluate(_obs(claim_state="released", sup_sessions=[]), NOW)
    assert _rules(pages) == ["supervisor-dead"]
    assert pages[0].text.startswith("KEEPER: supervisor dead")
    assert "await operator" in pages[0].text


def test_absent_claim_with_goals_active_pages_supervisor_dead():
    pages = k.evaluate(_obs(claim_state="none", sup_sessions=[],
                            heartbeat_age_seconds=None), NOW)
    assert _rules(pages) == ["supervisor-dead"]


def test_stale_heartbeat_with_no_sup_session_pages_supervisor_dead():
    pages = k.evaluate(_obs(heartbeat_age_seconds=k.HEARTBEAT_STALE_SECONDS + 1,
                            sup_sessions=[]), NOW)
    assert _rules(pages) == ["supervisor-dead"]


def test_stale_heartbeat_with_a_live_sup_session_is_silent():
    # A body mid-turn can miss a beat; a live roster entry means not dead.
    pages = k.evaluate(_obs(heartbeat_age_seconds=k.HEARTBEAT_STALE_SECONDS + 1,
                            sup_sessions=["sup|launch-1|boot"]), NOW)
    assert pages == []


def test_goals_inactive_never_pages_supervisor_dead():
    pages = k.evaluate(_obs(goals_active=False, claim_state="none",
                            sup_sessions=[]), NOW)
    assert "supervisor-dead" not in _rules(pages)


def test_pending_decision_pages_supervisor_frozen():
    pages = k.evaluate(_obs(pending_decision="ship M-F?"), NOW)
    assert _rules(pages) == ["supervisor-frozen"]
    assert "ship M-F?" in pages[0].text


def test_worker_anomalies_page_once_with_all_names():
    workers = [
        {"name": "a", "status": "dead-suspected", "mail": 0, "limit_kind": None},
        {"name": "b", "status": "limited", "mail": 0, "limit_kind": "usage"},
        {"name": "c", "status": "idle", "mail": 2, "limit_kind": None},
        {"name": "d", "status": "working", "mail": 0, "limit_kind": None},
    ]
    pages = k.evaluate(_obs(workers=workers), NOW)
    assert _rules(pages) == ["worker-anomaly"]
    text = pages[0].text
    assert "3 worker anomalies" in text
    for name in ("a", "b", "c"):
        assert name in text
    assert "d" not in text.split(":")[-1]


def test_unpushed_pages_only_after_the_window():
    young = _obs(unpushed=3, oldest_unpushed_ts=NOW - 3600)
    old = _obs(unpushed=3, oldest_unpushed_ts=NOW - k.UNPUSHED_PAGE_SECONDS - 1)
    assert k.evaluate(young, NOW) == []
    pages = k.evaluate(old, NOW)
    assert _rules(pages) == ["unpushed"]
    assert "3 commits unpushed" in pages[0].text


def test_agents_failure_pages_login_expired():
    pages = k.evaluate(_obs(agents_ok=False, sup_sessions=[]), NOW)
    assert "login-expired" in _rules(pages)
    # and it must NOT also claim the supervisor is dead on evidence it lacks
    assert "supervisor-dead" not in _rules(pages)


def test_hook_errors_growth_pages_with_the_delta():
    pages = k.evaluate(_obs(hook_error_lines=12, prev_hook_error_lines=10), NOW)
    assert _rules(pages) == ["hook-errors"]
    assert "grew by 2 lines" in pages[0].text


def test_unreadable_registry_pages_and_repairs_nothing():
    pages = k.evaluate(_obs(registry_ok=False, registry_reason="quarantined"), NOW)
    assert _rules(pages) == ["registry-unreadable"]
    assert "quarantined" in pages[0].text


def test_fingerprints_change_when_the_situation_changes():
    a = k.evaluate(_obs(unpushed=3, oldest_unpushed_ts=NOW - 8 * 3600), NOW)[0]
    b = k.evaluate(_obs(unpushed=4, oldest_unpushed_ts=NOW - 8 * 3600), NOW)[0]
    assert a.rule == b.rule and a.fingerprint != b.fingerprint


def test_every_page_is_one_line():
    obs = _obs(claim_state="released", sup_sessions=[], pending_decision="q?",
               workers=[{"name": "a", "status": "dead-suspected", "mail": 0,
                         "limit_kind": None}],
               unpushed=1, oldest_unpushed_ts=NOW - 9 * 3600,
               hook_error_lines=1, prev_hook_error_lines=0)
    for p in k.evaluate(obs, NOW):
        assert "\n" not in p.text and p.text.startswith("KEEPER: ")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_rules.py`
Expected: `ModuleNotFoundError: No module named 'fleet_keeper'` (conftest already puts `bin/` on `sys.path`).

- [ ] **Step 3: Write the rules module**

Create `bin/fleet_keeper.py`:

```python
#!/usr/bin/env python3
"""fleet keeper -- a page-only liveness timer for a headless fleet.

Runs from a systemd user timer every 15 minutes (`--once`). It OBSERVES
fleet state read-only and TYPES one-line pages into the dedicated tmux
interface window (`work:fleet`), whose Claude session relays them to
Telegram through the ccgram bridge. It never takes `fleet.lock`, never
writes fleet state, and never dispatches a session -- revival is a human
message from the phone (operator ruling 2026-09-08, spec
docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md).

stdlib only; floor is fleet.MIN_PYTHON_VERSION.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT / "bin"))

import fleet  # noqa: E402

Page = namedtuple("Page", "rule fingerprint text")

HEARTBEAT_STALE_SECONDS = 3600
UNPUSHED_PAGE_SECONDS = 6 * 3600
REPAGE_SECONDS = 6 * 3600
ANOMALOUS_STATUSES = ("dead-suspected", "limited")


# --------------------------------------------------------------------- rules

def _sup_alive(obs) -> bool:
    return any(str(n).startswith("sup|") for n in obs.get("sup_sessions", []))


def rule_registry_unreadable(obs, now):
    if obs.get("registry_ok", True):
        return None
    reason = obs.get("registry_reason") or "unknown"
    return Page("registry-unreadable", reason,
                f"KEEPER: registry unreadable ({reason}). Report it; do not repair.")


def rule_login_expired(obs, now):
    if obs.get("agents_ok", True):
        return None
    return Page("login-expired", "agents-failed",
                "KEEPER: claude login appears expired (`claude agents` failed). "
                "Operator must /login on the box.")


def rule_supervisor_dead(obs, now):
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None  # cannot tell dead from unlisted; login rule covers it
    if _sup_alive(obs):
        return None
    state = obs.get("claim_state")
    beat = obs.get("heartbeat_age_seconds")
    if state in ("released", "none", "unknown"):
        reason = f"claim {state}"
    elif beat is not None and beat > HEARTBEAT_STALE_SECONDS:
        reason = f"heartbeat {int(beat // 60)} min stale, no sup session"
    else:
        return None
    return Page("supervisor-dead", f"{state}:{reason}",
                f"KEEPER: supervisor dead ({reason}). Report state; "
                "await operator before sup-spawn.")


def rule_supervisor_frozen(obs, now):
    q = obs.get("pending_decision")
    if not q:
        return None
    return Page("supervisor-frozen", str(q),
                f"KEEPER: supervisor parked on decision: {q} "
                "Carry it to the operator.")


def rule_worker_anomaly(obs, now):
    names = []
    for w in obs.get("workers", []):
        status = w.get("status")
        if status in ANOMALOUS_STATUSES:
            names.append(f"{w.get('name')}({status})")
        elif status == "idle" and (w.get("mail") or 0) > 0:
            names.append(f"{w.get('name')}(idle+mail)")
    if not names:
        return None
    joined = ", ".join(sorted(names))
    return Page("worker-anomaly", joined,
                f"KEEPER: {len(names)} worker anomalies: {joined}. "
                "Summarise for the operator.")


def rule_unpushed(obs, now):
    n = obs.get("unpushed") or 0
    oldest = obs.get("oldest_unpushed_ts")
    if n <= 0 or oldest is None:
        return None
    age = now - oldest
    if age < UNPUSHED_PAGE_SECONDS:
        return None
    hours = int(age // 3600)
    return Page("unpushed", f"{n}:{int(oldest)}",
                f"KEEPER: {n} commits unpushed for {hours}h. Push or explain.")


def rule_hook_errors(obs, now):
    cur = obs.get("hook_error_lines") or 0
    prev = obs.get("prev_hook_error_lines") or 0
    if cur <= prev:
        return None
    return Page("hook-errors", f"{prev}->{cur}",
                f"KEEPER: hook-errors.log grew by {cur - prev} lines. Read it.")


RULES = (
    rule_registry_unreadable,
    rule_login_expired,
    rule_supervisor_dead,
    rule_supervisor_frozen,
    rule_worker_anomaly,
    rule_unpushed,
    rule_hook_errors,
)


def evaluate(obs, now) -> list:
    pages = []
    for rule in RULES:
        page = rule(obs, now)
        if page is not None:
            pages.append(page)
    return pages
```

- [ ] **Step 4: Run the tests**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_rules.py -v`
Expected: 14 PASS. If `test_worker_anomalies_page_once_with_all_names` fails on the `"d" not in …` line, the split is on the last colon of the text — adjust the test to `assert "d(" not in text` instead; the intent is that healthy workers are not named.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet_keeper.py tests/test_keeper_rules.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(keeper): page-only rules over one fleet observation"
```

---

### Task 3: Keeper dedup state

**Files:**
- Modify: `bin/fleet_keeper.py`
- Test: `tests/test_keeper_dedup.py`

**Interfaces:**
- Consumes: `Page`, `REPAGE_SECONDS` from Task 2.
- Produces:
  - `dedup(pages: list[Page], state: dict, now: float) -> tuple[list[Page], dict]` — returns the pages to send and the new state. State shape: `{"<rule>": {"fingerprint": str, "at": float}}`.
  - `load_state(path: Path) -> dict` (missing/corrupt → `{}`), `save_state(path: Path, state: dict) -> None` (atomic: write `path.with_suffix(".tmp")` then `os.replace`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keeper_dedup.py`:

```python
import json

import fleet_keeper as k

NOW = 1_800_000_000.0
P = k.Page("supervisor-dead", "released", "KEEPER: supervisor dead")


def test_first_page_is_sent_and_recorded():
    send, state = k.dedup([P], {}, NOW)
    assert send == [P]
    assert state == {"supervisor-dead": {"fingerprint": "released", "at": NOW}}


def test_same_fingerprint_inside_the_window_is_suppressed():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + 900)
    assert send == []
    assert state2 == state  # untouched, so the window does not slide


def test_same_fingerprint_after_the_window_repages():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + k.REPAGE_SECONDS + 1)
    assert send == [P]
    assert state2["supervisor-dead"]["at"] == NOW + k.REPAGE_SECONDS + 1


def test_changed_fingerprint_repages_immediately():
    _, state = k.dedup([P], {}, NOW)
    p2 = P._replace(fingerprint="none")
    send, _ = k.dedup([p2], state, NOW + 60)
    assert send == [p2]


def test_a_rule_that_stops_firing_is_forgotten():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([], state, NOW + 60)
    assert send == [] and state2 == {}


def test_state_roundtrip_and_corrupt_file(tmp_path):
    path = tmp_path / "keeper" / "last-page.json"
    k.save_state(path, {"x": {"fingerprint": "f", "at": 1.0}})
    assert k.load_state(path) == {"x": {"fingerprint": "f", "at": 1.0}}
    path.write_text("{not json", encoding="utf-8")
    assert k.load_state(path) == {}
    assert k.load_state(tmp_path / "absent.json") == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_dedup.py`
Expected: `AttributeError: module 'fleet_keeper' has no attribute 'dedup'`.

- [ ] **Step 3: Implement**

Append to `bin/fleet_keeper.py` after `evaluate`:

```python
# --------------------------------------------------------------------- dedup

def dedup(pages, state, now):
    """Send a page when its rule is new, its fingerprint changed, or the
    re-page window elapsed. Rules that stopped firing drop out of state."""
    send = []
    new_state = {}
    for page in pages:
        prev = state.get(page.rule)
        if (prev is None or prev.get("fingerprint") != page.fingerprint
                or now - float(prev.get("at", 0)) > REPAGE_SECONDS):
            send.append(page)
            new_state[page.rule] = {"fingerprint": page.fingerprint, "at": now}
        else:
            new_state[page.rule] = prev
    return send, new_state


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_dedup.py tests/test_keeper_rules.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet_keeper.py tests/test_keeper_dedup.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(keeper): per-rule dedup with a 6h re-page window"
```

---

### Task 4: Keeper observation (`collect`) through an injected runner

**Files:**
- Modify: `bin/fleet_keeper.py`
- Test: `tests/test_keeper_collect.py`

**Interfaces:**
- Consumes: `fleet.status_snapshot(now=None)` → `{"ok", "reason", "workers": [rows with name/status/mail/limit_kind], "supervisor": {"goals_active", "state", "incarnation_id", "heartbeat_age_seconds"}}`; `fleet.hook_errors_path()`; `bin/fleet.py sup-status --json` → `{"goals_active", "incarnation": {...,"state"}, "heartbeat_age_seconds", "pending_decision", ...}`; `claude agents --json` → list of `{"name", "kind", "status", ...}`.
- Produces: `collect(home: Path, *, now: float, run, snapshot_fn, prev_state: dict) -> dict` in the Task 2 observation shape. `run` has the `subprocess.run` signature and is always called with `capture_output=True, text=True, timeout=<seconds>`. Git is read with `cwd=home`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keeper_collect.py`:

```python
"""collect() turns four read-only sources into one observation dict.
Every subprocess goes through the injected `run`; nothing here touches a
real fleet, git, tmux, or claude."""
import json
import subprocess
from pathlib import Path

import pytest

import fleet_keeper as k

NOW = 1_800_000_000.0


def _cp(argv, rc=0, out=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")


def _runner(table):
    """table: list of (predicate(argv) -> bool, rc, stdout). First match wins."""
    calls = []

    def run(argv, **kw):
        calls.append((list(argv), kw))
        assert kw.get("capture_output") and kw.get("text") and kw.get("timeout")
        for pred, rc, out in table:
            if pred(argv):
                return _cp(argv, rc, out)
        raise AssertionError(f"unexpected subprocess: {argv}")
    run.calls = calls
    return run


def _snapshot(**over):
    snap = {"ok": True, "reason": None,
            "workers": [{"name": "w1", "status": "idle", "mail": 1, "limit_kind": None,
                         "turns": 3, "tier": "worker"}],
            "supervisor": {"goals_active": True, "state": "held",
                           "incarnation_id": "inc-x", "heartbeat_age_seconds": 30.0}}
    snap.update(over)
    return snap


SUP_STATUS = json.dumps({"goals_active": True, "incarnation": {"state": "held"},
                         "heartbeat_age_seconds": 30.0, "pending_decision": None})
AGENTS = json.dumps([{"name": "sup|l1|boot", "kind": "background", "status": "busy"},
                     {"name": "w1", "kind": "background", "status": "idle"}])


def _table(sup=SUP_STATUS, agents=AGENTS, agents_rc=0, count="2\n", oldest="1799990000\n"):
    return [
        (lambda a: "sup-status" in a, 0, sup),
        (lambda a: a[:2] == ["claude", "agents"], agents_rc, agents),
        (lambda a: a[:2] == ["git", "rev-list"], 0, count),
        (lambda a: a[:2] == ["git", "log"], 0, oldest),
    ]


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir()
    return tmp_path


def test_happy_path_observation(home):
    (home / "state" / "hook-errors.log").write_text("a\nb\n", encoding="utf-8")
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=lambda: _snapshot(),
                    prev_state={"_hook_error_lines": 1})
    assert obs["goals_active"] is True
    assert obs["claim_state"] == "held"
    assert obs["heartbeat_age_seconds"] == 30.0
    assert obs["pending_decision"] is None
    assert obs["sup_sessions"] == ["sup|l1|boot"]
    assert obs["agents_ok"] is True
    assert obs["registry_ok"] is True and obs["registry_reason"] is None
    assert obs["workers"] == [{"name": "w1", "status": "idle", "mail": 1, "limit_kind": None}]
    assert obs["unpushed"] == 2 and obs["oldest_unpushed_ts"] == 1799990000.0
    assert obs["hook_error_lines"] == 2 and obs["prev_hook_error_lines"] == 1


def test_git_is_run_in_the_fleet_home(home):
    run = _runner(_table())
    k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    git_calls = [kw for a, kw in run.calls if a[0] == "git"]
    assert git_calls and all(kw["cwd"] == str(home) for kw in git_calls)


def test_agents_failure_is_reported_not_raised(home):
    run = _runner(_table(agents="", agents_rc=1))
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["agents_ok"] is False and obs["sup_sessions"] == []


def test_sup_status_garbage_falls_back_to_the_snapshot(home):
    run = _runner(_table(sup="not json"))
    obs = k.collect(home, now=NOW, run=run,
                    snapshot_fn=lambda: _snapshot(supervisor={
                        "goals_active": True, "state": "released",
                        "incarnation_id": None, "heartbeat_age_seconds": None}),
                    prev_state={})
    assert obs["claim_state"] == "released" and obs["pending_decision"] is None


def test_unreadable_registry_is_an_observation_not_an_exception(home):
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run,
                    snapshot_fn=lambda: {"ok": False, "reason": "quarantined",
                                         "workers": [], "supervisor": {
                                             "goals_active": True, "state": "unknown",
                                             "incarnation_id": None,
                                             "heartbeat_age_seconds": None}},
                    prev_state={})
    assert obs["registry_ok"] is False and obs["registry_reason"] == "quarantined"
    assert obs["workers"] == []


def test_no_unpushed_when_rev_list_is_zero(home):
    run = _runner(_table(count="0\n", oldest=""))
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None


def test_missing_hook_errors_log_counts_as_zero(home):
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["hook_error_lines"] == 0


def test_a_subprocess_timeout_degrades_to_not_ok(home):
    def run(argv, **kw):
        if argv[:2] == ["claude", "agents"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return _runner(_table())(argv, **kw)
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["agents_ok"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_collect.py`
Expected: `AttributeError: module 'fleet_keeper' has no attribute 'collect'`.

- [ ] **Step 3: Implement `collect`**

Append to `bin/fleet_keeper.py`:

```python
# ------------------------------------------------------------------- collect

SUBPROCESS_TIMEOUT = 30


def _run_text(run, argv, *, cwd=None):
    """(rc, stdout) with every failure class folded into rc != 0."""
    try:
        cp = run(argv, capture_output=True, text=True,
                 timeout=SUBPROCESS_TIMEOUT, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return cp.returncode, cp.stdout or ""


def _sup_status(home, run):
    argv = [sys.executable, str(Path(home) / "bin" / "fleet.py"),
            "sup-status", "--json", "--fleet-home", str(home)]
    rc, out = _run_text(run, argv)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _agents(run):
    rc, out = _run_text(run, ["claude", "agents", "--json"])
    if rc != 0:
        return False, []
    try:
        rows = json.loads(out)
    except ValueError:
        return False, []
    names = [str(r.get("name", "")) for r in rows if isinstance(r, dict)]
    return True, [n for n in names if n.startswith("sup|")]


def _git_unpushed(home, run):
    rc, out = _run_text(run, ["git", "rev-list", "--count", "origin/main..main"],
                        cwd=str(home))
    try:
        n = int(out.strip()) if rc == 0 else 0
    except ValueError:
        n = 0
    if n <= 0:
        return 0, None
    rc, out = _run_text(run, ["git", "log", "--format=%ct", "--reverse",
                              "origin/main..main"], cwd=str(home))
    first = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    try:
        return n, float(first)
    except ValueError:
        return n, None


def _count_lines(path):
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def collect(home, *, now, run=subprocess.run, snapshot_fn=fleet.status_snapshot,
            prev_state=None):
    home = Path(home)
    prev_state = prev_state or {}
    snap = snapshot_fn()
    sup = snap.get("supervisor") or {}
    status = _sup_status(home, run)
    if status is not None:
        claim_state = (status.get("incarnation") or {}).get("state") or (
            "none" if status.get("incarnation") is None else "unknown")
        goals_active = bool(status.get("goals_active"))
        beat = status.get("heartbeat_age_seconds")
        pending = status.get("pending_decision")
    else:
        claim_state = sup.get("state") or "unknown"
        goals_active = bool(sup.get("goals_active"))
        beat = sup.get("heartbeat_age_seconds")
        pending = None
    agents_ok, sup_sessions = _agents(run)
    unpushed, oldest = _git_unpushed(home, run)
    workers = [{"name": w.get("name"), "status": w.get("status"),
                "mail": w.get("mail") or 0, "limit_kind": w.get("limit_kind")}
               for w in (snap.get("workers") or [])]
    return {
        "goals_active": goals_active,
        "claim_state": claim_state,
        "heartbeat_age_seconds": beat,
        "pending_decision": pending,
        "sup_sessions": sup_sessions,
        "agents_ok": agents_ok,
        "registry_ok": bool(snap.get("ok", True)),
        "registry_reason": snap.get("reason"),
        "workers": workers,
        "unpushed": unpushed,
        "oldest_unpushed_ts": oldest,
        "hook_error_lines": _count_lines(home / "state" / "hook-errors.log"),
        "prev_hook_error_lines": int(prev_state.get("_hook_error_lines", 0) or 0),
    }
```

Check `fleet sup-status` accepts `--fleet-home`: run `python3 bin/fleet.py sup-status --help`. If it does not, drop that pair from `argv` and set `env={**os.environ, "FLEET_HOME": str(home)}` on the call instead (keep `cwd=None`), and adjust the collect test's `sup-status` predicate — it matches on the verb, so it still passes.

- [ ] **Step 4: Run the tests**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_collect.py tests/test_keeper_rules.py tests/test_keeper_dedup.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet_keeper.py tests/test_keeper_collect.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(keeper): collect one read-only observation from fleet, claude agents, git, hook log"
```

---

### Task 5: Keeper tmux actions and `main`

**Files:**
- Modify: `bin/fleet_keeper.py`
- Test: `tests/test_keeper_main.py`

**Interfaces:**
- Consumes: `collect`, `evaluate`, `dedup`, `load_state`, `save_state`.
- Produces:
  - `window_alive(run, target: str) -> bool` — `tmux list-panes -t <target> -F '#{pane_current_command}'` exits 0 and prints `claude`.
  - `ensure_window(run, *, session: str, window: str, cwd: str, launch: str) -> bool` — creates `session:window` when `window_alive` is False; returns True if it created one. If a window of that name exists but its pane is not `claude`, it is killed first (`tmux kill-window -t session:window`) and recreated.
  - `page(run, target: str, text: str) -> bool` — `tmux send-keys -t <target> -l <text>` then `tmux send-keys -t <target> Enter`; True when both exit 0.
  - `main(argv: list[str] | None = None, *, run=subprocess.run, now_fn=time.time, snapshot_fn=fleet.status_snapshot, out=sys.stdout) -> int` with flags `--once` (required), `--dry-run`, `--fleet-home PATH` (default `_INSTALL_ROOT`), `--tmux-session NAME` (default `work`), `--window NAME` (default `fleet`), `--profile PATH` (default `<home>/docs/operator/server-interface-profile.md`). State file: `<home>/state/keeper/last-page.json`. The state dict also carries `_hook_error_lines` (the last observed count) so the hook-errors rule has a previous value.
  - Launch command string: `claude --permission-mode bypassPermissions "Read <profile> and follow it exactly."`
  - Exit code 0 always, except 2 for usage errors. A tmux failure prints `keeper: tmux failed: <argv>` and continues (the timer unit's journal is the only reader).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keeper_main.py`:

```python
import io
import json
import subprocess

import pytest

import fleet_keeper as k

NOW = 1_800_000_000.0


def _cp(argv, rc=0, out=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")


class Runner:
    """Scripted subprocess.run. tmux calls are recorded; everything else is
    answered from `table` like tests/test_keeper_collect.py."""

    def __init__(self, *, pane_cmd="claude", tmux_rc=0, agents_rc=0):
        self.calls = []
        self.pane_cmd = pane_cmd
        self.tmux_rc = tmux_rc
        self.agents_rc = agents_rc

    def __call__(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "tmux":
            if argv[1] == "list-panes":
                return _cp(argv, 0 if self.pane_cmd else 1, (self.pane_cmd or "") + "\n")
            return _cp(argv, self.tmux_rc)
        if "sup-status" in argv:
            return _cp(argv, 0, json.dumps({"goals_active": True,
                                            "incarnation": None,
                                            "heartbeat_age_seconds": None,
                                            "pending_decision": None}))
        if argv[:2] == ["claude", "agents"]:
            return _cp(argv, self.agents_rc, "[]")
        if argv[:2] == ["git", "rev-list"]:
            return _cp(argv, 0, "0\n")
        if argv[:2] == ["git", "log"]:
            return _cp(argv, 0, "")
        raise AssertionError(argv)

    def tmux(self, verb):
        return [a for a in self.calls if a[:2] == ["tmux", verb]]


def _snapshot():
    return {"ok": True, "reason": None, "workers": [],
            "supervisor": {"goals_active": True, "state": "none",
                           "incarnation_id": None, "heartbeat_age_seconds": None}}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "fleet.py").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "operator").mkdir(parents=True)
    (tmp_path / "docs" / "operator" / "server-interface-profile.md").write_text(
        "# profile\n", encoding="utf-8")
    return tmp_path


def _main(home, runner, *extra):
    out = io.StringIO()
    rc = k.main(["--once", "--fleet-home", str(home), *extra],
                run=runner, now_fn=lambda: NOW, snapshot_fn=_snapshot, out=out)
    return rc, out.getvalue()


def test_once_is_required():
    with pytest.raises(SystemExit) as e:
        k.main([], run=Runner(), now_fn=lambda: NOW, snapshot_fn=_snapshot,
               out=io.StringIO())
    assert e.value.code == 2


def test_dead_supervisor_is_paged_into_the_window(home):
    r = Runner()
    rc, out = _main(home, r)
    assert rc == 0
    sends = r.tmux("send-keys")
    assert len(sends) == 2
    assert sends[0][2:] == ["-t", "work:fleet", "-l", sends[0][-1]]
    assert sends[0][-1].startswith("KEEPER: supervisor dead")
    assert sends[1][-1] == "Enter"
    state = json.loads((home / "state" / "keeper" / "last-page.json").read_text())
    assert "supervisor-dead" in state and state["_hook_error_lines"] == 0


def test_second_tick_inside_the_window_sends_nothing(home):
    r = Runner()
    _main(home, r)
    n = len(r.tmux("send-keys"))
    _main(home, r)
    assert len(r.tmux("send-keys")) == n


def test_missing_window_is_created_before_paging(home):
    r = Runner(pane_cmd=None)
    _main(home, r)
    new = r.tmux("new-window")
    assert len(new) == 1
    argv = new[0]
    assert argv[argv.index("-t") + 1] == "work"
    assert argv[argv.index("-n") + 1] == "fleet"
    assert argv[argv.index("-c") + 1] == str(home)
    launch = argv[-1]
    assert launch.startswith("claude --permission-mode bypassPermissions ")
    assert "server-interface-profile.md" in launch
    # created first, paged second
    assert r.calls.index(new[0]) < r.calls.index(r.tmux("send-keys")[0])


def test_window_with_a_dead_shell_is_recycled(home):
    r = Runner(pane_cmd="zsh")
    _main(home, r)
    assert len(r.tmux("kill-window")) == 1 and len(r.tmux("new-window")) == 1


def test_dry_run_performs_no_tmux_action_and_writes_no_state(home):
    r = Runner(pane_cmd=None)
    rc, out = _main(home, r, "--dry-run")
    assert rc == 0
    assert not [a for a in r.calls if a[0] == "tmux" and a[1] != "list-panes"]
    assert "KEEPER: supervisor dead" in out
    assert not (home / "state" / "keeper" / "last-page.json").exists()


def test_tmux_failure_is_reported_and_exit_stays_zero(home):
    r = Runner(tmux_rc=1)
    rc, out = _main(home, r)
    assert rc == 0 and "keeper: tmux failed" in out


def test_window_and_session_flags(home):
    r = Runner()
    _main(home, r, "--tmux-session", "s2", "--window", "ops")
    assert r.tmux("send-keys")[0][3] == "s2:ops"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_main.py`
Expected: `AttributeError: module 'fleet_keeper' has no attribute 'main'`.

- [ ] **Step 3: Implement tmux actions and `main`**

Append to `bin/fleet_keeper.py`:

```python
# ---------------------------------------------------------------------- tmux

def _tmux(run, out, *args):
    argv = ["tmux", *args]
    rc, _ = _run_text(run, argv)
    if rc != 0:
        print(f"keeper: tmux failed: {argv}", file=out)
    return rc == 0


def window_alive(run, target):
    rc, text = _run_text(run, ["tmux", "list-panes", "-t", target,
                               "-F", "#{pane_current_command}"])
    return rc == 0 and "claude" in text.split()


def _window_exists(run, target):
    rc, _ = _run_text(run, ["tmux", "list-panes", "-t", target])
    return rc == 0


def ensure_window(run, *, session, window, cwd, launch, out=sys.stdout):
    target = f"{session}:{window}"
    if window_alive(run, target):
        return False
    if _window_exists(run, target):
        _tmux(run, out, "kill-window", "-t", target)
    _tmux(run, out, "new-window", "-d", "-t", session, "-n", window,
          "-c", cwd, launch)
    return True


def page(run, target, text, out=sys.stdout):
    ok = _tmux(run, out, "send-keys", "-t", target, "-l", text)
    ok = _tmux(run, out, "send-keys", "-t", target, "Enter") and ok
    return ok


# ---------------------------------------------------------------------- main

def _parser():
    p = argparse.ArgumentParser(prog="fleet_keeper",
                                description="page-only liveness tick for a headless fleet")
    p.add_argument("--once", action="store_true", required=True,
                   help="run one tick and exit (the only mode; a timer supplies cadence)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be paged; touch neither tmux nor state")
    p.add_argument("--fleet-home", default=str(_INSTALL_ROOT))
    p.add_argument("--tmux-session", default="work")
    p.add_argument("--window", default="fleet")
    p.add_argument("--profile", default=None,
                   help="interface profile the window's claude is told to read")
    return p


def main(argv=None, *, run=subprocess.run, now_fn=time.time,
         snapshot_fn=fleet.status_snapshot, out=sys.stdout):
    args = _parser().parse_args(argv)
    home = Path(args.fleet_home).resolve()
    profile = Path(args.profile) if args.profile else (
        home / "docs" / "operator" / "server-interface-profile.md")
    launch = ('claude --permission-mode bypassPermissions '
              f'"Read {profile} and follow it exactly."')
    target = f"{args.tmux_session}:{args.window}"
    state_path = home / "state" / "keeper" / "last-page.json"
    now = float(now_fn())

    state = load_state(state_path)
    obs = collect(home, now=now, run=run, snapshot_fn=snapshot_fn, prev_state=state)
    pages = evaluate(obs, now)
    rule_state = {k_: v for k_, v in state.items() if not k_.startswith("_")}
    send, rule_state = dedup(pages, rule_state, now)

    if args.dry_run:
        for p in pages:
            print(f"[dry-run] {p.rule}: {p.text}", file=out)
        if not window_alive(run, target):
            print(f"[dry-run] would create {target}: {launch}", file=out)
        return 0

    created = ensure_window(run, session=args.tmux_session, window=args.window,
                            cwd=str(home), launch=launch, out=out)
    if created:
        print(f"keeper: created {target}", file=out)
    for p in send:
        page(run, target, p.text, out=out)
        print(f"keeper: paged {p.rule}", file=out)

    rule_state["_hook_error_lines"] = obs["hook_error_lines"]
    save_state(state_path, rule_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the keeper tests**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_main.py tests/test_keeper_collect.py tests/test_keeper_rules.py tests/test_keeper_dedup.py -v 2>&1 | tail -5`
Expected: all PASS. If `test_dead_supervisor_is_paged_into_the_window` fails on `sends[0][2:]`, print `sends[0]` — the expected argv is `["tmux","send-keys","-t","work:fleet","-l","<text>"]`.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet_keeper.py tests/test_keeper_main.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(keeper): --once tick that ensures the interface window and types pages into it"
```

---

### Task 6: Doctrine pins — the keeper never dispatches, never locks, runs at the floor

**Files:**
- Test: `tests/test_keeper_doctrine.py`

**Interfaces:**
- Consumes: `bin/fleet_keeper.py` source; the AST-scan style of `tests/test_load_registry_callers.py` (`_callers`, planted-source non-vacuity tests).

- [ ] **Step 1: Write the tests (they must pass immediately, and fail on a planted mutant)**

Create `tests/test_keeper_doctrine.py`:

```python
"""The keeper is a reader plus two tmux actions. These pins make the
spec's 'never dispatches, never locks' claim mechanical, and prove the
detector can see a violation by planting one."""
import ast
from pathlib import Path

import fleet
import fleet_keeper

SRC = Path(fleet_keeper.__file__).read_text(encoding="utf-8")

FORBIDDEN = {
    "dispatch_bg", "cmd_spawn", "cmd_sup_spawn", "_dispatch_supervisor_body",
    "cmd_send", "_cmd_send_native", "cmd_respawn", "_cmd_respawn_native",
    "fleet_lock", "load_registry", "cmd_kill", "cmd_clean", "cmd_archive",
    "cmd_autoclean", "cmd_init", "_quarantine_registry",
}


def _referenced_names(source):
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_the_keeper_references_no_dispatching_or_locking_name():
    hits = sorted(FORBIDDEN & _referenced_names(SRC))
    assert hits == [], (
        f"fleet_keeper.py references {hits}. The keeper pages; it never "
        "dispatches, locks, or repairs (spec §3.3, operator ruling 2026-09-08).")


def test_the_detector_sees_a_planted_dispatch():
    planted = SRC + "\n\ndef _mutant():\n    return fleet.dispatch_bg('x', '.', '', 'bypass')\n"
    assert "dispatch_bg" in _referenced_names(planted)


def test_the_only_fleet_attributes_used_are_read_only_ones():
    tree = ast.parse(SRC)
    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "fleet"}
    assert used <= {"status_snapshot", "MIN_PYTHON_VERSION"}, used


def test_the_keeper_writes_only_under_state_keeper():
    # Every open(..., 'w'|'x'|'a') / write_text / os.replace target in the
    # module is the keeper's own state file. Audited by name: the module
    # has exactly one writer, save_state.
    tree = ast.parse(SRC)
    writers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr in ("write_text", "replace")]
    for w in writers:
        fn = next(p for p in ast.walk(tree)
                  if isinstance(p, ast.FunctionDef)
                  and any(c is w for c in ast.walk(p)))
        assert fn.name == "save_state", (fn.name, w.attr)


def test_the_keeper_parses_at_the_interpreter_floor():
    # 3.10 floor: no `match`, no PEP 695 generics, no `except*`.
    feature_version = fleet.MIN_PYTHON_VERSION
    ast.parse(SRC, feature_version=feature_version)
```

- [ ] **Step 2: Run them**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_keeper_doctrine.py -v`
Expected: 5 PASS. If `test_the_only_fleet_attributes_used_are_read_only_ones` fails, the offending attribute is printed — either it is read-only (add it to the allowed set with a comment) or it is a bug in Task 4/5.

- [ ] **Step 3: Run the full suite on BOTH interpreters**

Run the two Task 0 commands. Expected: passed = baseline + 4 (Task 1) + 14 + 6 + 8 + 8 + 5; failed/skipped unchanged on both. The 3.10 run is the one that matters for the keeper — `str | None` in annotations is fine under `from __future__ import annotations`, but a runtime `X | Y` outside annotations is not.

- [ ] **Step 4: Commit**

```bash
git add tests/test_keeper_doctrine.py
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "test(keeper): pin never-dispatch, never-lock, single-writer, and the 3.10 floor"
```

---

### Task 7: Operator documents — interface profile, standing brief, gates, lessons

**Files:**
- Create: `docs/operator/server-interface-profile.md`
- Create: `supervisor/briefs/server-standing.md`
- Modify: `docs/OPERATOR-GATES.md` (`## Open` and `## Settled`)
- Modify: `knowledge/lessons.md` (append), `knowledge/INDEX.md` (one line)
- Modify: `skills/fleet/SKILL.md` — one row in the CLI table for the keeper
- Test: existing `tests/test_supervisor.py::TestOperatorGatesFile` (gates format), `tests/test_terminal_surface.py` (docs lint)

**Interfaces:**
- Consumes: the keeper's launch line reads `docs/operator/server-interface-profile.md`; the interface dispatches `supervisor/briefs/server-standing.md`.
- Produces: the two prose surfaces the running system reads, and the record of the three rulings.

- [ ] **Step 1: Write the interface profile**

Create `docs/operator/server-interface-profile.md`:

```markdown
# Server interface profile (kz-work, tmux window `work:fleet`)

You are the **interface tier** of claude-fleet on a headless server (`docs/specs/three-tier-command.md`). The keeper timer launched you in tmux window `work:fleet`; the ccgram bridge relays everything you print to the operator's Telegram topic and everything they type back to you. You hold no nonce, you never run `fleet sup-boot`, and you never drive a worker directly.

## On launch

1. Activate the `fleet` skill and run its startup ritual steps 1–4: read `docs/OPERATOR-GATES.md`; run `fleet status`, `fleet sup-status`, `fleet autoclean`; read `knowledge/INDEX.md`; load the project files you will touch.
2. Report in ONE message, under 1500 characters: open gates (if any), supervisor state, worker table summary, unpushed commits, anything from `state/hook-errors.log`.
3. **Do not revive the fleet.** If the supervisor is dead, say so and name the brief you would dispatch (`supervisor/briefs/server-standing.md`). Dispatch only after the operator replies with the word `revive` in this topic. This replaces ritual step 5 on this host (operator ruling 2026-09-08: the timer pages, a human revives).
4. Then wait. Each incoming line is either the operator or the keeper.

## Lines that start with `KEEPER:`

They come from `bin/fleet_keeper.py`, not from a person. Investigate with read-only verbs (`fleet status`, `fleet sup-status`, `fleet peek`, `fleet doctor`, `git status`), then write one short message for the operator: what the keeper saw, what you confirmed, what you recommend. Never act on a KEEPER line with a mutating verb unless the operator has already asked for that action.

## Operator messages

- `revive` — `fleet sup-spawn --task @supervisor/briefs/server-standing.md --setting-sources project,local`, then report the launch id and `fleet sup-status`.
- A task description — write it to `state/tasks/<yyyymmdd>-<slug>.md` (or `state/inbox/` when no supervisor is live), then `fleet send sup|<launch>|boot @that-file` if a supervisor is live; otherwise say it is queued.
- `status` — `fleet status` and `fleet sup-status`, summarised.
- `recycle interface` — acknowledge, then exit this session (`/exit`). The keeper recreates the window on its next tick.
- Anything else: answer from fleet state; ask before any destructive verb (`kill`, `clean`, `archive`, `sup-release`).

## Never

- Never `fleet sup-boot`. Never `--dangerously-skip-permissions` on a worker without an explicit operator sentence naming that worker.
- Never tick a box in `docs/OPERATOR-GATES.md`.
- Never run `fleet doctor --repair` unasked.
```

- [ ] **Step 2: Write the standing brief**

Create `supervisor/briefs/server-standing.md`:

```markdown
# Standing brief — kz-work server supervisor

You are a supervisor body dispatched by the interface tier on a headless Linux server after the operator said `revive`. Your identity is the incarnation, not this body: the plan is in `supervisor/JOURNAL.md`, not in this file.

## Boot

1. `fleet sup-boot`, redirected to the boot bundle file exactly as the rendered task instructs: grep the VERDICT/INCARNATION/NONCE lines from that file, then read the rest -- GOALS, journal tail, knowledge index, roster, fleet status -- in the bounded slices the rendered task orders, never in one read (a redirect protects the stream, not the reader; a tool that persists a large read re-creates the plaintext copy the redirect exists to avoid), then delete the file. The last CHECKPOINT in the journal tail is your plan.
2. `fleet autoclean`.
3. Drain `state/inbox/*.md`: each file is a task the operator queued while no supervisor was live. Turn each into a campaign entry in your plan, move the file to `state/inbox/done/<name>.md` with a `campaign:` line appended, and checkpoint.

## Every wave

- Spawn every worker with `--setting-sources project,local` (this host's user-level settings carry a foreign Stop hook that misattributes fleet sessions to a tmux window).
- Workers are Opus or Sonnet per `supervisor/GOALS.md` tier policy; cwd is the target repo under `/home/altai/proga/`.
- At the wave boundary: `fleet sup-checkpoint @file`, fold lessons (`knowledge/lessons.md`, the project file, one `knowledge/INDEX.md` line), commit, then `git push`; on rc≠0 retry three times over five minutes, then checkpoint the failure. Unpushed work is what the keeper pages about after six hours.
- Check `fleet sup-context`; hand off at 350k via `sup-handoff-begin`, and if the handoff is stillborn, `sup-release` cleanly. A released claim is what the keeper pages the operator about; that is correct behaviour, not a failure to hide.

## Operator gates

Raise with `fleet sup-decision --raise` and park. The interface tier carries it to the phone.

## Never

- Never mass-respawn on a suspicious roster; freeze and raise.
- Never edit `supervisor/GOALS.md` (propose via `sup-checkpoint --kind PROPOSAL`).
- Never dispatch a second supervisor body.
```

- [ ] **Step 3: Record the gates**

In `docs/OPERATOR-GATES.md`, under `## Open` (keep the existing italic paragraph, add after it):

```markdown
- [ ] **Keeper typing `KEEPER:` lines into the dedicated `work:fleet` window — inside D7's pull-only intent (one opt-in window the keeper itself launched), or does D7 need an explicit amendment naming it?**
- [ ] **Under the notify-only-via-ccgram ruling, two failures stay silent — a login expiry that also kills the interface window, and a failed `fleet-keeper` unit. Accept both as known blind spots, or permit one out-of-band alert path later?**
- [ ] **`supervisor/briefs/` becomes a git-tracked home for standing briefs (dispatched by `sup-spawn --task @…`) — approve the directory, or keep briefs under gitignored `state/tasks/`?**
```

Under `## Settled`, at the top:

```markdown
- [x] **kz-work server fleet — revival actor, notification path, and interface permission mode?** *(2026-09-08 by Altai, in-session.)* Answer: **the keeper timer PAGES ONLY and never dispatches; outbound notification goes ONLY through the ccgram-bound `work:fleet` window (no direct Bot API, no second bot); the server interface session runs `bypassPermissions`.** Design: `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
```

- [ ] **Step 4: Record the lesson and the index line**

Append to `knowledge/lessons.md`:

```markdown
## 2026-09-08 — server fleet rulings {#2026-09-08-server-rulings}

**Operator decisions (kz-work, in-session):** (1) a liveness timer may observe and PAGE but never dispatch a supervisor — the 2026-07-27 "the operator relaunching IS the trigger" doctrine narrows to "a human message IS the trigger"; (2) outbound notification only through the ccgram-bound tmux window `work:fleet`, no second Telegram path; (3) the server interface runs bypass. **Measured hazard that shaped the build:** the `claude daemon` freezes `TMUX_PANE` from its first dispatch, so every `--bg` session's user-level hooks resolve to the pane that launched the daemon — `--setting-sources project,local` on every fleet dispatch is the remedy, and `sup-spawn` had no such flag until today. Spec: `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
```

Prepend one line to `knowledge/INDEX.md` after its header comment:

```markdown
- `lessons.md#2026-09-08-server-rulings` — **kz-work server fleet: keeper timer PAGES ONLY, notify only via the ccgram window, interface bypass; `claude daemon` freezes `TMUX_PANE` so every fleet dispatch needs `--setting-sources project,local`.**
```

- [ ] **Step 5: Add the keeper row to the skill's CLI table**

In `skills/fleet/SKILL.md`, after the `fleet doctor` row:

```markdown
| `python bin/fleet_keeper.py --once [--dry-run] [--fleet-home P]` | **Headless-host liveness tick, page-only.** Run by a systemd user timer every 15 min on kz-work; observes `status_snapshot()`, `sup-status --json`, `claude agents --json`, git, `hook-errors.log`, and types one-line `KEEPER:` pages into the tmux window `work:fleet` (the interface tier, relayed to Telegram by ccgram). Never locks, never dispatches, never repairs — revival is the operator's `revive` message (ruling 2026-09-08). |
```

- [ ] **Step 6: Run the docs-facing tests**

Run: `uv run --python 3.12 --with pytest -q python -m pytest -q -p no:cacheprovider tests/test_supervisor.py tests/test_terminal_surface.py tests/test_receipts.py 2>&1 | tail -3`
Expected: PASS. If `TestOperatorGatesFile` fails, the open line does not end in `?` or the settled line lacks the bold question — fix the punctuation, not the test.

- [ ] **Step 7: Commit**

```bash
git add docs/operator/server-interface-profile.md supervisor/briefs/server-standing.md docs/OPERATOR-GATES.md knowledge/lessons.md knowledge/INDEX.md skills/fleet/SKILL.md
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "docs(server): interface profile, standing brief, three rulings recorded, three gates filed"
```

---

### Task 8: Ansible role `fleet_keeper` in `~/china-infra`

**Files (all under `/home/altai/china-infra`):**
- Create: `roles/fleet_keeper/defaults/main.yml`, `roles/fleet_keeper/meta/main.yml`, `roles/fleet_keeper/handlers/main.yml`, `roles/fleet_keeper/tasks/main.yml`, `roles/fleet_keeper/tasks/units.yml`, `roles/fleet_keeper/tasks/verify.yml`, `roles/fleet_keeper/templates/fleet-keeper.service.j2`, `roles/fleet_keeper/templates/fleet-keeper.timer.j2`, `roles/fleet_keeper/README.md`
- Modify: `roles/README.md` (one table row), `playbooks/work.yml` (append role after `telegram_bridge`), `tests/render.yml` (append a play)

**Interfaces:**
- Consumes: `devbox` role facts (`devbox_uid`, linger), `telegram_bridge` unit pattern (`scope: user`, `XDG_RUNTIME_DIR`, `flush_handlers`).
- Produces: `~/.config/systemd/user/fleet-keeper.service` + `.timer`, enabled and started.

- [ ] **Step 1: defaults, meta, handlers**

`roles/fleet_keeper/defaults/main.yml`:
```yaml
---
fleet_keeper_user: altai
fleet_keeper_home: "/home/{{ fleet_keeper_user }}"
fleet_keeper_repo: "{{ fleet_keeper_home }}/proga/fleet"
fleet_keeper_systemd_user_dir: "{{ fleet_keeper_home }}/.config/systemd/user"
fleet_keeper_service: fleet-keeper.service
fleet_keeper_timer: fleet-keeper.timer
fleet_keeper_interval: 15min
fleet_keeper_boot_delay: 2min
fleet_keeper_tmux_session: "{{ devbox_tmux_session | default('work') }}"
fleet_keeper_tmux_unit: "{{ devbox_tmux_unit | default('tmux-work.service', true) }}"
fleet_keeper_window: fleet
fleet_keeper_claude_env_file: "{{ fleet_keeper_home }}/.config/china-infra/claude.env"
fleet_keeper_path: "{{ fleet_keeper_home }}/.local/bin:{{ fleet_keeper_home }}/.local/share/fnm/aliases/default/bin:/usr/local/bin:/usr/bin:/bin"
fleet_keeper_verify_retries: 6
fleet_keeper_verify_delay: 5
```

`roles/fleet_keeper/meta/main.yml`:
```yaml
---
galaxy_info:
  role_name: fleet_keeper
  author: Altai
  description: Page-only liveness timer for claude-fleet on the devbox
  license: MIT
  min_ansible_version: "2.17"
  platforms:
    - name: Ubuntu
      versions: [noble]
dependencies:
  - role: devbox
```

`roles/fleet_keeper/handlers/main.yml`:
```yaml
---
- name: Reload the user systemd manager for fleet-keeper
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.systemd_service:
    scope: user
    daemon_reload: true
  environment:
    XDG_RUNTIME_DIR: "/run/user/{{ devbox_uid }}"

- name: Restart fleet-keeper timer
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.systemd_service:
    scope: user
    name: "{{ fleet_keeper_timer }}"
    state: restarted
  environment:
    XDG_RUNTIME_DIR: "/run/user/{{ devbox_uid }}"
```

- [ ] **Step 2: templates**

`roles/fleet_keeper/templates/fleet-keeper.service.j2`:
```ini
[Unit]
# Managed by Ansible — roles/fleet_keeper. DO NOT EDIT ON THE HOST.
#
# One page-only tick of the claude-fleet keeper. It reads fleet state and
# types a line into tmux window {{ fleet_keeper_tmux_session }}:{{ fleet_keeper_window }};
# it never dispatches a session (operator ruling 2026-09-08). Cadence comes
# from {{ fleet_keeper_timer }}; this unit is oneshot on purpose.
Description=claude-fleet keeper tick (page-only)
Documentation=file://{{ fleet_keeper_repo }}/docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md
Wants={{ fleet_keeper_tmux_unit }}
After={{ fleet_keeper_tmux_unit }}

[Service]
Type=oneshot
EnvironmentFile=-{{ fleet_keeper_claude_env_file }}
Environment=PATH={{ fleet_keeper_path }}
Environment=HOME={{ fleet_keeper_home }}
WorkingDirectory={{ fleet_keeper_repo }}
ExecStart=/bin/sh {{ fleet_keeper_repo }}/bin/hooks/run_py.sh {{ fleet_keeper_repo }}/bin/fleet_keeper.py --once --fleet-home {{ fleet_keeper_repo }} --tmux-session {{ fleet_keeper_tmux_session }} --window {{ fleet_keeper_window }}
TimeoutStartSec=120
NoNewPrivileges=true
```

`roles/fleet_keeper/templates/fleet-keeper.timer.j2`:
```ini
[Unit]
# Managed by Ansible — roles/fleet_keeper. DO NOT EDIT ON THE HOST.
Description=Run the claude-fleet keeper tick every {{ fleet_keeper_interval }}

[Timer]
OnBootSec={{ fleet_keeper_boot_delay }}
OnUnitActiveSec={{ fleet_keeper_interval }}
# A missed tick (box asleep, power cut) runs at the next boot instead of
# waiting a full interval — the 2026-07-27 outage was found 3h38m late.
Persistent=true
Unit={{ fleet_keeper_service }}

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: tasks**

`roles/fleet_keeper/tasks/main.yml`:
```yaml
---
- name: Install the keeper units
  ansible.builtin.include_tasks: units.yml

- name: Verify the keeper timer
  ansible.builtin.include_tasks: verify.yml
```

`roles/fleet_keeper/tasks/units.yml`:
```yaml
---
- name: Refuse to install the keeper when the fleet checkout is missing
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.stat:
    path: "{{ fleet_keeper_repo }}/bin/fleet_keeper.py"
  register: fleet_keeper_script

- name: Assert the keeper script exists
  ansible.builtin.assert:
    that: fleet_keeper_script.stat.exists
    fail_msg: "{{ fleet_keeper_repo }}/bin/fleet_keeper.py is missing — clone claude-fleet there first (the role never clones)."

- name: Ensure the user unit directory exists
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.file:
    path: "{{ fleet_keeper_systemd_user_dir }}"
    state: directory
    mode: "0755"

- name: Render the keeper service and timer
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.template:
    src: "{{ item }}.j2"
    dest: "{{ fleet_keeper_systemd_user_dir }}/{{ item }}"
    mode: "0644"
  loop:
    - "{{ fleet_keeper_service }}"
    - "{{ fleet_keeper_timer }}"
  notify:
    - Reload the user systemd manager for fleet-keeper
    - Restart fleet-keeper timer

- name: Apply a pending user daemon-reload before enabling the timer
  ansible.builtin.meta: flush_handlers

- name: Enable and start the keeper timer
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.systemd_service:
    scope: user
    name: "{{ fleet_keeper_timer }}"
    enabled: true
    state: started
  environment:
    XDG_RUNTIME_DIR: "/run/user/{{ devbox_uid }}"
```

`roles/fleet_keeper/tasks/verify.yml`:
```yaml
---
- name: Wait for the keeper timer to be active
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.command:
    cmd: systemctl --user is-active {{ fleet_keeper_timer }}
  environment:
    XDG_RUNTIME_DIR: "/run/user/{{ devbox_uid }}"
  register: fleet_keeper_active
  changed_when: false
  failed_when: false
  retries: "{{ fleet_keeper_verify_retries }}"
  delay: "{{ fleet_keeper_verify_delay }}"
  until: fleet_keeper_active.stdout | trim == 'active'

- name: Assert the keeper timer is active
  ansible.builtin.assert:
    that: fleet_keeper_active.stdout | trim == 'active'
    fail_msg: "fleet-keeper.timer is not active: journalctl --user -u {{ fleet_keeper_service }} -n 50"

- name: Run one dry keeper tick so a broken interpreter fails the play, not the night
  become: true
  become_user: "{{ fleet_keeper_user }}"
  ansible.builtin.command:
    cmd: /bin/sh {{ fleet_keeper_repo }}/bin/hooks/run_py.sh {{ fleet_keeper_repo }}/bin/fleet_keeper.py --once --dry-run --fleet-home {{ fleet_keeper_repo }}
  environment:
    PATH: "{{ fleet_keeper_path }}"
    HOME: "{{ fleet_keeper_home }}"
  changed_when: false
```

- [ ] **Step 4: README, roles table, playbook, render play**

`roles/fleet_keeper/README.md`:
```markdown
# fleet_keeper

Installs `fleet-keeper.service` (oneshot) and `fleet-keeper.timer` (every 15 min, `Persistent=true`) as **user** units for the devbox owner. The tick runs `bin/fleet_keeper.py --once` from the claude-fleet checkout at `fleet_keeper_repo`; it reads fleet state and types `KEEPER:` pages into tmux window `work:fleet`, which the ccgram bridge relays to Telegram. It never dispatches a Claude session — revival is a human message (operator ruling 2026-09-08).

The role never clones the fleet repo; it asserts the script exists. Depends on `devbox` (linger, `devbox_uid`, the `work` tmux session). Design: `<fleet repo>/docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
```

Add to `roles/README.md`'s table: `| fleet_keeper | page-only liveness timer for claude-fleet (user units) |` in the same column shape as the existing rows.

In `playbooks/work.yml`, append to the second play's `roles:` list after `telegram_bridge`:
```yaml
    - role: fleet_keeper
      tags: [fleet_keeper]
```

Append a play to `tests/render.yml`, copying the shape of the `telegram_bridge` play (line ~2148) — `hosts: localhost`, `connection: local`, `gather_facts: false`, `vars_files` for `inventory/group_vars/all/vars.yml` and `roles/fleet_keeper/defaults/main.yml`, `vars: { devbox_uid: 1000, devbox_tmux_session: work, devbox_tmux_unit: tmux-work.service }`, render both templates into `{{ lookup('env','RENDER_OUT') }}/fleet_keeper/`, then `slurp` + `assert`:
```yaml
    - name: Assert the keeper unit is oneshot, user-scoped, and page-only by argv
      ansible.builtin.assert:
        that:
          - "'Type=oneshot' in svc"
          - "'--once' in svc"
          - "'--dry-run' not in svc"
          - "'sup-spawn' not in svc"
          - "'OnUnitActiveSec=15min' in tmr"
          - "'Persistent=true' in tmr"
          - "'WantedBy=timers.target' in tmr"
      vars:
        svc: "{{ fleet_keeper_svc_rendered.content | b64decode }}"
        tmr: "{{ fleet_keeper_tmr_rendered.content | b64decode }}"
```

- [ ] **Step 5: Run the repo's checks**

Run:
```bash
cd /home/altai/china-infra && make check 2>&1 | tail -20
```
Expected: yamllint, ansible-lint, syntax-check, render-check all green. Common ansible-lint hits: a var without the `fleet_keeper_` prefix, `become` on an include, a missing `mode`. Fix at the source.

- [ ] **Step 6: Commit in china-infra**

```bash
cd /home/altai/china-infra
git add roles/fleet_keeper roles/README.md playbooks/work.yml tests/render.yml
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "feat(fleet_keeper): page-only systemd user timer for claude-fleet on kz-work"
```

---

### Task 9: Host rollout S0 — install fleet on this box and prove the hooks land here

**Files:**
- Modify: `docs/operator/keeper-soak-2026-09.md` (append receipts)

**Interfaces:**
- Consumes: `docs/operator/fleet-init-recipe.md` §2 and §4; Task 1's `--setting-sources`.
- Produces: `state/worker-settings.json`, the fleet plugin installed, and two host receipts: the canary outcome file and the ccgram-events check.

- [ ] **Step 1: Init and install the plugin (plain shell — no `CLAUDE_CODE_SESSION_ID`)**

Run from a tmux shell pane, not from a Claude session:
```bash
cd /home/altai/proga/fleet
export PATH="$PWD/bin:$PATH"
fleet home
env -u CLAUDE_CODE_SESSION_ID fleet init
fleet doctor 2>&1 | grep -E '^\[FAIL\]' ; printf 'doctor rc=%s\n' $?
claude plugin marketplace add /home/altai/proga/fleet
claude plugin install fleet@claude-fleet
```
Expected: `fleet home` prints `/home/altai/proga/fleet`; `fleet init` writes `state/worker-settings.json`; the grep prints nothing (grep rc=1 means zero `[FAIL]` rows); the plugin installs.

- [ ] **Step 2: Canary worker, spawned WITH `--setting-sources`**

```bash
fleet spawn canary-srv --dir /home/altai/proga/fleet --setting-sources project,local \
  --task "Print the current date and stop. Do not edit any file."
sleep 60
tail -n 1 state/outcomes/canary-srv.jsonl
fleet result canary-srv
```
Expected: the last line carries `"kind": "result"`; `fleet result` prints a date.

- [ ] **Step 3: The ccgram-events check (the hazard from spec §2.2)**

```bash
SID=$(python3 - <<'EOF'
import json;print(json.load(open('state/fleet.json'))['workers']['canary-srv']['session_id'])
EOF
)
grep -c "$SID" /home/altai/.ccgram/events.jsonl || printf 'no ccgram events for %s\n' "$SID"
```
Expected: `0` (or the "no ccgram events" line). If the count is non-zero, `--setting-sources project,local` did not exclude the user-level hooks on this `claude` version — stop, record it in the soak file, and raise it with the operator before Task 10; the interface topic would otherwise receive every worker's Stop events.

- [ ] **Step 4: Dispose and record**

```bash
fleet kill canary-srv --yes
```
Append to `docs/operator/keeper-soak-2026-09.md` a `## S0 — install` section with the three command blocks and their real output, each block headed `# volatile: host state — <date>`.

- [ ] **Step 5: Commit**

```bash
git add docs/operator/keeper-soak-2026-09.md
git -c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)" commit -m "docs(operator): S0 receipts -- fleet init, canary outcome, ccgram-events clean"
```

---

### Task 10: Host rollout S2–S3 — interface window by hand, keeper dry-run, timer via Ansible

**Files:**
- Modify: `docs/operator/keeper-soak-2026-09.md`

- [ ] **Step 1: Create the window by hand and confirm ccgram binds a topic**

```bash
tmux new-window -d -t work -n fleet -c /home/altai/proga/fleet \
  'claude --permission-mode bypassPermissions "Read /home/altai/proga/fleet/docs/operator/server-interface-profile.md and follow it exactly."'
sleep 20
tmux list-windows -t work -F '#{window_name} #{pane_current_command}'
python3 -c "import json;d=json.load(open('/home/altai/.ccgram/state.json'));print(d['window_display_names'])"
```
Expected: a `fleet claude` row; the display-name map gains an entry for the new window id. On the phone: a new topic appears and receives the ritual report from step 2 of the profile. Send `status` from the phone; expect a reply.

- [ ] **Step 2: Keeper dry-run from the repo**

```bash
cd /home/altai/proga/fleet
sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --dry-run --fleet-home "$PWD"
```
Expected: `[dry-run] supervisor-dead: KEEPER: supervisor dead (claim none). …` (no supervisor is live yet) and no `would create` line (the window exists). Nothing typed into the window.

- [ ] **Step 3: One real tick by hand**

```bash
sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --fleet-home "$PWD"
cat state/keeper/last-page.json
```
Expected: `keeper: paged supervisor-dead`; the interface session receives the line, investigates, and posts one message to the topic. A second run prints nothing (dedup).

- [ ] **Step 4: Deploy the timer with Ansible**

```bash
cd /home/altai/china-infra
ansible-playbook playbooks/work.yml --tags fleet_keeper 2>&1 | tail -15
systemctl --user list-timers fleet-keeper.timer
journalctl --user -u fleet-keeper.service -n 20 --no-pager
```
Expected: play green including the dry-tick verify task; the timer lists a `NEXT` time; the journal shows the dry tick's output.

- [ ] **Step 5: Record receipts and commit**

Append `## S2/S3 — window, dry-run, timer` to the soak file with the real outputs (`# volatile`). Commit in the fleet repo as in Task 9.

---

### Task 11: Host rollout S5 — first revival from the phone and one wave

**Files:**
- Modify: `docs/operator/keeper-soak-2026-09.md`

- [ ] **Step 1: Queue a small real task via the inbox**

Write `state/inbox/20260908-first-wave.md`:
```markdown
# First server wave

Project: /home/altai/proga/fleet. Task: run the full test suite on 3.10 and 3.12 with
`uv run --python <v> --with pytest -q python -m pytest -q -p no:cacheprovider --ignore=tests/integration`,
record both tail lines in docs/operator/keeper-soak-2026-09.md under "## S5 — first wave",
commit, push. One worker, Sonnet is enough. Then checkpoint and hand off or release.
```

- [ ] **Step 2: Revive from the phone**

In the Telegram topic send `revive`. Expected: the interface runs `fleet sup-spawn --task @supervisor/briefs/server-standing.md --setting-sources project,local` and reports a launch id; within one keeper tick no `supervisor-dead` page (the rule sees a `sup|` session). Watch:
```bash
fleet sup-status
fleet status
tail -n 5 supervisor/JOURNAL.md
```

- [ ] **Step 3: Watch the wave complete**

Expected within the hour: a worker appears and finishes; the journal gains a CHECKPOINT; `git log origin/main..main` is empty (the brief pushed); `state/inbox/done/20260908-first-wave.md` exists; the supervisor either handed off or released. On release the next keeper tick pages `supervisor-dead` and the interface reports it — that is the system working end to end.

- [ ] **Step 4: Record and commit**

Append `## S5 — first wave` observations (times, the page, what the interface said) to the soak file; commit. Then start the one-week soak: every page goes in the table in the soak file, and a false page is a rule fix in `bin/fleet_keeper.py` with a test in `tests/test_keeper_rules.py`.

---

## Self-review

**Spec coverage.** §3.1 interface window and profile → Tasks 5 (launch line), 7 (profile), 10. §3.2 `sup-spawn --setting-sources` → Task 1; standing brief and inbox drain → Task 7, exercised in Task 11. §3.3 keeper rules (six rules plus registry-unreadable) → Task 2; dedup and state file → Task 3; observation sources → Task 4; ensure-window and page → Task 5; doctrine pins → Task 6; timer unit → Task 8. §3.4 intake paths → profile (Task 7) and inbox (Task 11). §4 sequencing S0–S5 → Tasks 9–11; S6 soak → Task 11 step 4 and the soak file from Task 0. §5 failure modes: the two blind spots are filed as a gate in Task 7. §7 gates G-K1, G-K2, G-K4 open, G-K3 settled → Task 7. The spec's "newest outcome is an auth error" arm of the login-expired rule is not built — `claude agents` failing is the signal used; noted here so the soak can decide whether the second arm is needed.

**Placeholders.** None: every step carries its command, code, or file body. The one conditional (`sup-status --fleet-home` support in Task 4) states both branches.

**Type consistency.** `Page(rule, fingerprint, text)` is used identically in Tasks 2, 3, 5. `collect(home, *, now, run, snapshot_fn, prev_state)` matches its call in `main`. `dedup(pages, state, now) -> (send, state)` matches Task 5's unpacking. `_run_text(run, argv, *, cwd=None)` is the single subprocess seam used by `_sup_status`, `_agents`, `_git_unpushed`, `_tmux`, `window_alive`. State keys starting with `_` are filtered before `dedup` and re-added after, so `test_a_rule_that_stops_firing_is_forgotten` and `test_dead_supervisor_is_paged_into_the_window` agree.
