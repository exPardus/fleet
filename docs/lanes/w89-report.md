# Lane w89 — full report

(Overflow from `docs/lanes/w89.md`, which stays under the 40-line cap.)

## The defect

`_reap_eligible`'s lane arm (`bin/fleet.py`) reaches its landed/abandoned
branch only if `record["lane_state"]` or the latest outcome's `kind` is
`landed`/`abandoned`. Neither was ever written: `lane_state` had readers
only, and `append_outcome`'s one caller (`write_tombstone_outcome`) is
gated by `TOMBSTONE_KINDS = ("killed", "interrupted", "stopped")`, which
never includes `landed`/`abandoned`. So the arm has never fired; every
row ever reaped went through `predecessor-supervisor` or `daemon-dead`.

## Design question, answered

Three options were posed: (a) `fleet land` marks it, (b) `wave-close`
marks it, (c) both with different values. Chose **(b)**.

`fleet_land.py`'s own module docstring: *"Fleet state is not a source of
lane identity, so this module deliberately has no dependency on the fleet
kernel or its parser globals."* `cmd_land` never calls `apply_resolved_home`
or touches `FLEET_HOME` — pinned by
`test_parser_registers_land_and_dispatches_without_home_resolution` in
`tests/test_fleet_land.py`. Measured directly in this worktree: `FLEET_HOME`
is unset in its environment, so `state_dir()` defaults to
`Path(__file__).resolve().parent.parent` — the *worktree's own* root, not
the real fleet home. If `cmd_land` took `fleet_lock()`/`load_registry()` it
would lock and read/write a nonexistent `state/fleet.json` inside the
worktree, not the real registry `_reap_eligible` reads. Land cannot safely
take the lock from a worktree, so (a) and (c)'s land-side half are both
out. `wave-close` already holds `fleet.lock` (two `with fleet_lock():`
blocks already bracket its registry-adjacent writes) and already computes
`_wave_landed_lanes` — the merge-commit branches landed this wave — so it
is the natural, already-locked writer. No `abandoned` write was added:
wave-close has no sound way to distinguish an abandoned lane from one
simply still in flight, and the task scope is "writing the lane's terminal
state" for lanes it actually observed landing.

## The writer

`_wave_mark_landed_lanes(repo, lanes, run)` joins each landed lane branch
to its worktree via `_wave_lane_worktree` (git worktree list), then to a
registry record by `record["cwd"] == worktree` — the same join
`_wave_record_substrate` already uses for THROUGHPUT accounting. It reads
the registry with `load_registry()`/writes with `save_registry()` (the
FLEET_HOME-scoped registry `_reap_eligible` actually reads), skips lanes
with no resolvable worktree or no matching record, and skips records
already `landed`/`abandoned`. Called from `cmd_wave_close`'s second
`with fleet_lock():` block, after `roll_supervisor_journal` and before
`write_incarnation`.

## A shift-of-line-numbers hazard, found and fixed

`bin/fleet.py` carries several test-checked self-citations: hand-written
comments naming an exact line number for another function/site, verified
by `tests/test_self_citations.py` and `tests/test_retired_sid_citations.py`
against the live AST on every run. Inserting the 36-line writer function
shifted every citation whose *target* sits after the insertion point,
without the citation text itself moving. Five such citations went stale
(`_quarantine_artifacts` readers' `_tombstone_releasing_body` bullet, the
"sid-union sites" enumeration's four post-insertion numbers, and both
copies of the "OWN prior sid alone" `retired_sids` writer citation). All
five were corrected to their new line numbers and reverified.

Separately, two static allowlist detectors (`tests/test_load_registry_callers.py`,
`tests/test_unlocked_quarantine.py`) correctly flagged `_wave_mark_landed_lanes`
as an unallowlisted `load_registry()` caller outside a lexical
`with fleet_lock():`. Both were updated with an allowlist entry, following
the existing `_holder_is_limited` precedent (lock-held by its one caller,
proven from the AST rather than trusted from a comment) plus a new AST pin,
`test_wave_mark_landed_lanes_really_is_lock_held_by_its_caller`, mirroring
`test_holder_is_limited_really_is_lock_held_by_its_caller`.

## Full test/claim list

See `docs/lanes/w89.json` for the exact commands and pass/fail counts.
Both interpreters (3.10, 3.12) were run against the targeted suites; the
full `pytest tests/` floor was run once on 3.10 as a claim (not a gate)
and returned exactly the six documented pre-existing host-venv failures
(`test_fleet_index.py::TestPathContainment` x3,
`test_fleet_q.py::TestOutlinePathContainment` x1,
`test_terminal_surface.py::TestCollaboratorInstall` x2), 5353 passed.

## Docs

`docs/SPEC.md` §11's wave-close row was updated since described behaviour
changed (the new write, and that the marked row reaps on the *next*
boot/wave-close rather than this one). `product.md`'s "Rituals are code"
line is a philosophy-level statement unaffected by this change; no update
needed there.
