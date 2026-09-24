# w103 registry hygiene

DONE means: a pin per defect that fails at base `04ef7b9` and passes after, on 3.10 and 3.12; full-suite failure set compared to base; views doctrine green; no claim/nonce or guard-verdict change.

1. Live lanes. `_supervisor_lane_partition` counts a lane as live only while it is working, attached, or has unread mail. The board prints `live_lane_count` and `idle_lane_count`. The boot bundle lists 12 idle rows, then `+N idle`, so idle rows no longer grow it.
2. Native Codex kill/archive. `kill` on a `codex-app-server` row marks it dead with `dead_reason` when its host is gone, its pid is dead, or the host is a newer generation. A live host gets `turn/interrupt` first. While a native launch is in flight (`adapter_state` is `preclaim` or `bound`, and the launch claim has not expired), kill refuses with `launch in flight`. If it did not, spawn's turn/start commit would set the killed row back to `working`. An unverified stop still marks the row dead and exits 1. `archive` retires Codex rows by TTL, with no `claude rm`.
3. `clean` skips sid-keyed files for null sids and reports the row.
4. `sup-reconcile` is in `UNCLASSIFIED_BY_THE_RATIFIED_TABLE`: it writes a claim, may start a host and may finalize a release, so its tier is not obvious.

Pins: `tests/test_w103_registry_hygiene.py` (12 fail at base. Two pass at base: one protection control, and the bound-window pin. At base, kill refused every native row as `launch in flight`, so the bound-window pin guards against a regression this lane would otherwise introduce).

## Results

Pins, `tests/test_w103_registry_hygiene.py`, 13 tests. Base is a detached worktree of `04ef7b9` with only the pin file copied in:

| tree | 3.10 | 3.12 |
| --- | --- | --- |
| base `04ef7b9` | 12 failed, 1 passed | 12 failed, 1 passed |
| head (this lane) | 13 passed | 13 passed |

The one pass at base is the control `TestNativeCodexArchive::test_ttl_and_running_and_unread_mail_still_protect`. Each of the 12 fails at base for its own defect:

- D1: `live_lane_count=66` counts idle rows; `SUPERVISOR_IDLE_ROWS_LISTED` is missing; the boot bundle exceeds 20000 characters (30704).
- D2 kill: all five fail with `launch in flight for cx-native`.
- D2 archive: no tombstone is written (`assert None is not None`).
- D3: `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'`.

Full suite on 3.12, run one at a time under `nice -n 19` without xdist:

- Base `04ef7b9`: 22 failed, 5719 passed, 18 skipped, 3 xfailed.
- Head: 21 failed, 5732 passed, 18 skipped, 3 xfailed.

Failure-set diff (head against base):

- New: none.
- Fixed: `tests/test_round7_defect_pins.py::TestEveryShippedVerbHasAnEffectDisposition::test_every_shipped_verb_is_classified_or_declared_unclassified`. This is D4, `sup-reconcile`.
- Unchanged: 21 base failures. Their `-rfE` summary lines are byte-identical at base and head: docs_currency, fleet_index path containment ×3, fleet_q outline containment, index_split stdlib, liveness census, load_registry_callers ×2, retired_sid_citations ×2, self_citations ×7, steering OS branches, terminal_surface ×2.

Views doctrine: `tests/test_views_doctrine.py` gives 17 passed and 2 skipped on both 3.10 and 3.12.

## Review fix (fleet-w103-review, MEDIUM)

Kill in the native `bound` window: spawn sets `adapter_state=bound` after thread/start and commits after turn/start, but only while the row is still `bound`. A kill in that gap marked the row dead, and the commit then set it back to `working`. Fix: the native in-flight check covers `bound` as well as `preclaim`. New pin: `TestNativeCodexKill::test_kill_in_the_bound_window_is_refused_as_launch_in_flight`. Without the fix it fails with `DID NOT RAISE FleetCliError`; with the fix it passes. `tests/test_w103_registry_hygiene.py` and `tests/test_round7_defect_pins.py` on 3.12: 80 passed.

## Follow-ups (LOW, from the review, not fixed here)

- The boot bundle's handling of dead rows and supervisor rows.
- How Codex rows show mail.
- The handoff checks when a Codex row is archived.
