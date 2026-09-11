# Lane w64-reap — automatic lifecycle reaping
DONE means: sup-boot, sup-handoff-complete and sup-release run the shared reap pass; boot prints its count, reap rule, three-session ceiling and 1.5 GB floor; supervisor instructions and owning docs agree; targeted 3.10/3.12 checks and a throwaway-home receipt are delivered.

Implemented in this worktree; no live fleet home was inspected or mutated, no live boot/archive occurred, no git ref moved. The supervisor owns landing and the live receipt. Model: gpt-6-astra, high. MCX_WORKER=1 retained; one native test/review subagent completed; no independent workers launched.

Reusing autoclean was cleaner: its archive writer already provides the conditional registry commit, resumable evidence moves, removal retries, ownership checks and diagnostics. The new criterion shares that writer instead of introducing another archiver.

- Successful claim-acquiring/resuming boots assemble the bundle, run maintenance, then print `reaped: N rows` and the policy paragraph. Refused/frozen boots and claim-pending successors retain their existing claim protocol and defer cleanup.
- Handoff completion and release run the same pass after the claim transition, outside the lock. Failed maintenance is visible without withholding the one-shot nonce or rolling back a completed transition.
- Autoclean ignores age for explicitly landed/abandoned idle workers, daemon-confirmed dead rows, and predecessor supervisor bodies outside the current claim. Daemon death needs an actual roster entry without status/pid, not mere roster absence. PID presence is conservatively protected even on a `state: done` row.
- The current holder/incarnation, busy sessions, unread/claimed mail and PID evidence protect the entire current/retired SID union in archive, crash-resume and husk cleanup. Automatic archive leaves mailbox files in place and checks again after evidence moves, so concurrent mail stays in the inbox and prevents removal.
- The legacy TTL fallback remains for older completed workers under the stronger protections. Manual archive retains its prior contract. `reaped` counts newly archived registry rows, not retry attempts or duplicate husk removals.
- The boot paragraph instructs **3 live worker sessions max across Claude and Codex**, a Codex lane counting as one, and **at least 1.5 GB available memory before dispatch**. This lane adds that boot context, not a new resource admission controller. Non-native Codex rows are outside the native archiver.

Prerequisite completed: explicit `lane_state: landed|abandoned` or matching latest outcome kinds now provide a structured completion criterion; this snapshot had no landing marker, and a result alone is intentionally not proof of landing. A still-idle finished worker without that marker remains protected until explicit landing/abandonment or daemon death. No landing-marker producer or new CLI verb was invented. The parent was asked whether another marker exists; no answer arrived before completion.

**The twelve incident rows.** The brief supplies counts and roles, not individual SIDs or landing records; the following maps every supplied row to its criterion without claiming a live per-SID measurement.

| Supplied rows | Criterion |
|---|---|
| Retired supervisor bodies 1, 2, 3, 4 | `predecessor-supervisor`, once outside the current claim and without unread mail/live PID. No TTL or outcome needed. |
| Finished workers 1, 2, 3, 4, 5, 6, 7, 8 | `daemon-dead` if the post-OOM daemon reports a dead row; otherwise `lane-landed` / `lane-abandoned` requires the explicit marker plus idle/no unread mail/no live PID. No TTL needed. |

This does **not** assert that all twelve live-host rows are currently eligible: actual roster PID/mail/landing evidence was neither supplied nor remeasured. A live PID or unread mail vetoes every listed criterion.

**Receipt.** `state/w64-reap/receipt.py` creates its own `/tmp/w64-reap-receipt-*` home and uses a mutable injected daemon. One real `cmd_sup_boot` invocation changes the synthetic roster **15 → 3**, prints **`reaped: 12 rows`**, and leaves the current claimant, unread-mail row and live-PID row. Its twelve removals exercise four predecessors, two landed lanes, two abandoned lanes, and four daemon-dead workers with stale stored status. Full before/after roster, daemon calls and redacted boot output are in `state/w64-reap/receipt.json`. Nonce plaintext existed only in memory; redaction occurred before writing the receipt. The boot bundle's own roster/status section is the pre-pass snapshot by the requested ordering.

Reproduce only the synthetic receipt:

```sh
env -u CLAUDE_CODE_SESSION_ID MCX_WORKER=1 python3 state/w64-reap/receipt.py > state/w64-reap/receipt.json
```

**Live receipt handoff — SUPERVISOR ONLY; not executed by this lane.** At an authorized boot, set `SUPERVISOR_SID` to that body's actual SID and `SUPERVISOR_NONCE` to its current generation (for a fresh authorized successor with no generation, omit the `--nonce` pair). This command deliberately targets the live home and can claim it. It prints the nonce once to the supervisor while saving only a redacted bundle. Bash/zsh syntax:

```sh
receipt_dir=$(mktemp -d /tmp/fleet-reap-live-XXXXXX)
env -u CLAUDE_CODE_SESSION_ID claude agents --json --all > "$receipt_dir/before.json"
set -o pipefail
env -u CLAUDE_CODE_SESSION_ID python3 /home/altai/proga/fleet/bin/fleet.py \
  --fleet-home /home/altai/proga/fleet sup-boot \
  --sid "${SUPERVISOR_SID:?set the booting body SID}" \
  --nonce "${SUPERVISOR_NONCE:?set its current generation}" \
  | tee >(sed 's/^NONCE: .*/NONCE: [REDACTED]/' > "$receipt_dir/boot.txt")
env -u CLAUDE_CODE_SESSION_ID claude agents --json --all > "$receipt_dir/after.json"
```

**Checks.** Predicted before execution: young eligible rows begin archiving; manual archive TTL behavior stays green; current claims, live PIDs and unread mail remain protected; lifecycle call ordering and nonce publication stay intact. Final results: **Python 3.10 — 695 passed, 1 deselected (26.01s); Python 3.12 — 695 passed, 1 deselected (25.84s)**. `git diff --check` is clean. Final logs: `state/w64-reap/pytest-3.10-final.log` and `state/w64-reap/pytest-3.12-final.log`. Full suite was not run.

The selected paths were `tests/test_lifecycle_reap.py`, `tests/test_autoclean.py`, `tests/test_archive_exemption.py`, `tests/test_supervisor.py`, `tests/test_sup_release_tombstone.py`, `tests/test_identity_fixwave.py`, `tests/test_load_registry_callers.py`, and these `tests/test_native.py` classes: `TestArchiveEligible`, `TestCmdArchive`, `TestCmdArchiveEpochFreeze`, `TestCmdArchiveForeignRosterUntouched`, `TestCmdArchiveConcurrentMutation`, `TestCmdArchiveCrashResume`. Commands used `env -u CLAUDE_CODE_SESSION_ID MCX_WORKER=1 PATH=/tmp/w64-reap-safe-bin:$PATH UV_OFFLINE=1 UV_CACHE_DIR=/tmp/w64-reap-uv-cache uv run --no-project --python 3.1x --with pytest python -m pytest -q <paths> -k 'not test_committed_journal_board_has_at_most_three_checkpoints'`.

The one deselection is an existing snapshot defect: the checked-in supervisor journal has six checkpoints, while that test permits three. Initial failure is preserved in the initial log. The journal is append-only landing material and outside this lane's rewrite authority. The supervisor must reconcile its board on the merged tree. Other initial failures were corrected fixture assumptions and test-helper mistakes; the final logs retain the actual outcome.

Prerequisite completed: reused the prior lane's offline uv cache via a writable `/tmp/w64-reap-uv-cache` copy; a fake `claude` first on test PATH prevented old fixture defaults from reaching the real daemon. No new host quirk was discovered. `/tmp/w64-reap-docs.py`, `/tmp/w64-reap-safe-bin/claude`, the cache copy and receipt homes are disposable validation artifacts.

**APPEND-ONLY HANDOFF: DO NOT REPLACE LIVE docs/CHANGELOG.md FROM THIS SNAPSHOT.** Its exact line to append is in `docs/lanes/w64-reap-changelog-append.md`; the supervisor re-derives it against the live changelog at landing. `supervisor/JOURNAL.md` and `knowledge/lessons.md` were not edited. No keeper, cmd_init or gate box changes. Docs updated: SPEC §11/§12 context, PLAN-PROGRESS row, autoclean spec, server standing brief and supervisor skill.

**PATH LIST — every created or modified worktree deliverable (including ignored logs):**

- `bin/fleet.py`
- `docs/SPEC.md`
- `docs/PLAN-PROGRESS.md`
- `docs/specs/autoclean.md`
- `docs/lanes/w64-reap.md`
- `docs/lanes/w64-reap-changelog-append.md`
- `skills/fleet/supervisor.md`
- `supervisor/briefs/server-standing.md`
- `tests/test_lifecycle_reap.py`
- `tests/test_autoclean.py`
- `tests/test_sup_release_tombstone.py`
- `state/journals/w64-reap.md`
- `state/w64-reap/pytest-3.10-archive.log`
- `state/w64-reap/pytest-3.10-before-review.log`
- `state/w64-reap/pytest-3.10-final.log`
- `state/w64-reap/pytest-3.10-fixture-fix.log`
- `state/w64-reap/pytest-3.10-initial.log`
- `state/w64-reap/pytest-3.10.log`
- `state/w64-reap/pytest-3.12-before-review.log`
- `state/w64-reap/pytest-3.12-final.log`
- `state/w64-reap/pytest-3.12.log`
- `state/w64-reap/receipt.json`
- `state/w64-reap/receipt.py`

## Regression follow-up — stand-down caller and ambiguous ownership

The merged-tree floor at `53b62d6` found a real regression: release correctly
abstained from tombstoning an ambiguous caller, then the reap pass treated that
same body as a predecessor because its claim was already released. Handoff
completion had the same self-reaping hole after transferring the claim. These
are two related missing protections at one destructive boundary: caller safety
must survive the claim transition, and ambiguous ownership must veto removal
independently of who invokes cleanup.

**Protection added:** `_reap_protection` now vetoes the calling body's entire
current/retired SID union and any overlapping SID ownership, so fresh archives,
archive resumes and husk removal all honor the same identity protection.
Lifecycle verbs explicitly pass the validated caller SID, including when supplied
through `--sid` with no caller environment. Ownership overlap includes dead or
archived rows; preferring a live identity candidate is not evidence that another
row's shared SID can be removed. The caller veto lasts only for its own pass;
a subsequent body can reap a uniquely owned dead predecessor.

The original ambiguous-identity test was **not edited**. The previous empty-roster
test stub masked the defect by triggering G9 before reaping. A nonempty synthetic
roster reproduced the original failure plus 12 new regression cases before the
fix: **13 failed**. This covers release and handoff, current/retired caller SIDs,
ambiguous twins, ordinary overlapping worker rows, crash-resumes and husks.
Unrelated terminal work still reaps during stand-down, and successor cleanup
remains possible. No live daemon or live fleet home was used.

Final targeted checks, no skips/deselections: **85 passed** in the two complete
requested files on **each of Python 3.10 and 3.12**; **152 additional targeted
autoclean/archive tests passed on each**. `git diff --check` is clean. Commands
used `env -u CLAUDE_CODE_SESSION_ID MCX_WORKER=1`,
`PATH=/tmp/w64-reap-regression-bin:$PATH`, `UV_OFFLINE=1`,
`UV_CACHE_DIR=/tmp/w64-reap-uv-cache`, and the mandated
`uv run --no-project --python 3.1x --with pytest python -m pytest -q` invocation.
The fake executable in `/tmp/w64-reap-regression-bin/claude` returns only a
synthetic nonempty roster or a synthetic missing-session response. Full logs
are listed below. No subagents were launched for this follow-up, no commit was
attempted, and no implementation blocker remains. Supervisor commit and merged
floor are still required. Changelog append handoff for landing:
`2026-09-10 — Reaping preserves the releasing/handoff caller and ambiguous SID ownership across archive, resume and husk cleanup.`
Do not rewrite a live append-only file from this snapshot.

**PATH LIST — regression follow-up:**

- `bin/fleet.py`
- `tests/test_lifecycle_reap.py`
- `docs/SPEC.md`
- `docs/specs/autoclean.md`
- `docs/PLAN-PROGRESS.md`
- `docs/lanes/w64-reap.md`
- `state/journals/w64-reap.md`
- `state/w64-reap/regression-before-3.10.log`
- `state/w64-reap/regression-reproduced-3.10.log`
- `state/w64-reap/regression-fixed-3.10.log`
- `state/w64-reap/regression-fixed-3.12.log`
- `state/w64-reap/regression-final-3.10.log`
- `state/w64-reap/regression-final-3.12.log`
- `state/w64-reap/regression-archive-3.10.log`
- `state/w64-reap/regression-archive-3.12.log`
- `/tmp/w64-reap-regression-bin/claude` (disposable test guard)
