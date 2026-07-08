# C2 code review — spec conformance + correctness (`c2-review-code`)

**Reviewer:** fleet worker `c2-review-code` (Campaign 2, Wave 2C).
**Scope:** full C2 increment `git diff fleet-impl...c2-hardening` (merge base `5c950ea`; 8 commits) —
hook kernels, live harness, and the `fleet.py` harden chain.
**Contract:** `docs/specs/phase1-hardening-kernels.md` items 1–11 + SPEC v2.1 §4/§5/§7/§12.
**Method:** read all of `bin/fleet.py` diff, all three hooks in full, the live-harness test module, and the
resilience/CLI/steering test suites; ran `py -3.13 -m pytest` (496 passed, 14.2s).

---

## (1) Verdict

**Spec-conformant enough to proceed to the merge gate.** All 11 kernels are built and match their contract;
the additive-schema, single-writer, one-live-claude, and exit-0-hook invariants are preserved; the UL1 signal is
honestly DEFERRED-TO-KERNEL-PROBE (no invented verified signal). No HIGH/critical finding.

Findings are **non-blocking**: one MEDIUM (a missing under-lock status re-check in the UL1 resume path that every
other launch path implements — a real invariant-7 consistency gap, low-probability under the single-manager model),
plus four LOW/cosmetic and two informational notes. Recommend fixing the MEDIUM before Soak; the rest are follow-ups.

**Spec follow-up (note only, do not edit SPEC):** the v2.1 `[UNBUILT — owned by C2 kernel]` tags for the three-way
probe, budget/setting-sources persistence, token ceiling, and UL1 are all now BUILT and matching the spec end-state —
those tags can drop in a subsequent SPEC pass.

---

## (2) Findings

### F-1 (MEDIUM) — `_resume_one_limited` never re-checks `status=="limited"` under its own lock

`bin/fleet.py::_resume_one_limited` (the UL1 per-worker launch path):

```python
with fleet_lock():
    data = load_registry()
    rec = data["workers"][name]
    rec["status"] = "working"
    rec["turn_pid"] = None
    ...
```

`cmd_resume_limited` snapshots eligibility under one lock, **releases it**, then loops calling
`_resume_one_limited`, which re-acquires a fresh lock but **unconditionally** pre-claims `working` with no
re-check that the record is still `limited`. Every other launch path re-validates status under the claiming lock —
`cmd_send`'s idle-resume branches on `if status == "idle":` (status recomputed under that same lock), `cmd_respawn`
re-reads and guards. This one omits it.

**Why it matters:** two concurrent `fleet resume-limited` invocations both snapshot `limited`, both call
`_resume_one_limited`; the second re-reads a record the first already flipped to `working`/`turn_pid=<pid>` and
clobbers it back to `working`/`turn_pid=None`, launching a **second** `claude` on the same sid — a one-live-claude
(invariant 7) violation. Low-probability under the single-manager model, but it is exactly the protection the rest of
the file applies religiously, and the launch-in-flight guard in `recompute_status` cannot save it because this code
never branches on status.

Secondary: `rec = data["workers"][name]` is an unguarded subscript — if the worker vanished between the snapshot and
this lock it raises a raw `KeyError` (uncaught traceback), not a clean `FleetCliError`.

**Fix (anchored to the function's role as the lock-guarded pre-claim):** inside the lock, re-read and
`if rec.get("status") != "limited": return` (skip, mirroring `cmd_send`'s idle re-check) before pre-claiming;
use `data["workers"].get(name)` and bail cleanly on `None`. A concurrency test (two overlapping resume-limited /
resume racing respawn) would close the untested edge.

### F-2 (LOW) — token-ceiling boundary is inconsistent between the two halves

Hook `bin/hooks/stop_mailbox.py::main`: `if current is not None and current >= ceiling: return` — ALLOWS stop
**at** the ceiling. Fleet `bin/fleet.py::cmd_send` (idle branch): `if used > tc:` — refuses resume only **above**
the ceiling. At exactly `tokens == ceiling` the halves disagree (hook allows the stop, fleet still permits a resume).
Cosmetic; pick one boundary (`>=` on both, or `>` on both) so the "over ceiling" definition is single-valued.

### F-3 (LOW) — `_sum_result_tokens` docstring overclaims agreement with the hook

`bin/fleet.py::_sum_result_tokens` docstring: *"Basis matches the Stop hook's `_current_tokens` (input+output) so
the two halves agree on what 'over ceiling' means."* They share the `input_tokens`/`output_tokens` keys but **not**
the record scope or source: the fleet half sums only `type=="result"` events in `logs/<name>.jsonl`; the hook
(`_current_tokens`) sums **every** usage record (`message.usage` or top-level `usage`) in the CLI `transcript_path`.
Those are different files with different accounting, so the two counts can diverge materially. No safety break —
the hook only ALLOWS, fleet hard-enforces — but the docstring should say "same token keys, best-effort, different
source/scope; the two halves need not agree numerically" rather than asserting agreement.

### F-4 (LOW) — orphaned ceiling files accumulate; no cleanup, no doctor check

`bin/fleet.py::cmd_respawn` calls `_write_ceiling_file(new_sid, token_ceiling)` and leaves the previous sid's
`state/ceilings/<old_sid>` file behind (docstring: "the old sid's is now stale/harmless"). Correct for the hook
(it reads by current sid), but there is no unlink on respawn and no `doctor` orphaned-ceiling surface, so
`state/ceilings/` grows unbounded across a worker's respawns. Mirror the orphaned-mailbox treatment: unlink the old
sid's file on a successful respawn, or add a note-only doctor check.

### F-5 (INFORMATIONAL) — `mail_drained` audit is partial by construction

Only `compose_prompt` (launch-time drain) emits `mail_drained`; the PostToolUse/Stop hooks drain mid-turn/at-stop
but emit no event (invariant 6 forbids hooks writing `events.jsonl`). So `mail_sent` vs `mail_drained` cannot be
fully reconciled from the event stream — hook-drained mail has no drain record. This is inherent to the single-writer
constraint and consistent with the contract ("fleet.py as the sole writer"); noting only so a Soak-1 audit does not
assume drain-event completeness.

### F-6 (INFORMATIONAL) — UL1 limit regex is broad; pin it when the probe lands

`bin/fleet.py::_LIMIT_STDERR_RE` matches `rate limit`, `try again later`, `quota` — phrases that also appear in
non-plan errors (a tool's HTTP 429, a generic network-retry message). A genuine crash whose stderr contains such a
phrase would be parked `limited` rather than crash-dead. This is **within contract**: it is the specced conservative
`limited-suspected` fallback (park + surface for operator confirmation), and it is NOT silent — `limited_suspected`
event + `_doctor_check_limited_parks` + the `status` flag all surface it, and the code is explicitly
DEFERRED-TO-KERNEL-PROBE. Recommend narrowing the pattern once the real wall confirms the signal (the code already
says so). Honest-deferral check passes: `claude --help` (2.1.204) has no usage/reset surface, no invented verified
signal, fallback governs.

---

## (3) Per-kernel conformance checklist (items 1–11)

| # | Kernel | Verdict | Evidence |
|---|--------|---------|----------|
| 1 | Swallowed-hook exception log | **conformant** | `_log_hook_error` in all 3 hooks, own try/except so logging failure never changes exit code; `hook_errors_path`, `_hook_error_count` → `cmd_status` prints total when nonzero; `_doctor_check_hook_errors` shows tail. |
| 2 | Static hook-registration lint | **conformant** | `_doctor_check_hook_registration`: known-event set `{PostToolUse,Stop,PostCompact}`, command-path existence, JSON shape; tolerant of hooks-less instance (PASS). Learned the new `PostCompact` name. |
| 3 | Fail-silent PostCompact journal landmark | **conformant** | `postcompact_journal.py`: read-only sid→name via `_resolve_name` (never writes registry), sid-keyed fallback or SKIP on failure, never guesses a name. Registered in `worker-settings.template.json` (F11); event name pinned to CLI 2.1.204; kernel-2 lint knows it. |
| 4 | Abnormal-turn note + cwd preflight | **conformant** | `launch_turn` raises `TurnLaunchError` on `not os.path.isdir(cwd)` before Popen (all launch paths funnel through it); `_append_abnormal_turn_note` fires only on the `working`(real pid)→`dead` transition (once per crash, since `dead` is sticky). |
| 5 | Spawn-time model echo | **conformant** | `cmd_spawn` prints `model: …` + `CLAUDE_CODE_SUBAGENT_MODEL` when set. (Nit: echoes `args.model`, not `record.get("model")`; identical at spawn, harmless.) |
| 6 | Scripted live-integration harness | **conformant** | `tests/integration/test_live_smoke.py`: `FLEET_LIVE=1` gate, haiku, mkdtemp `FLEET_HOME` + throwaway git repo, `RUN_BUDGET_CEILING_USD=0.25` asserted (`test_zz_budget_ceiling_and_manifest`), hook-source param (`FLEET_HOOK_SOURCE` main/worktree, `test_hook_source_render`), captures sanitized stream-json into the fixture corpus. Launches turns it owns — not exit-code capture of orphans. |
| 7 | Budget / setting-sources persistence | **conformant** | `new_worker_record` persists `max_budget_usd`/`setting_sources` (additive, default None); re-passed from the persisted record on spawn, idle-resume, and respawn (carry-forward-or-override); `cmd_send` cumulative-cost check refuses resume + sticky `over_budget`. Every launch path re-emits. |
| 8 | Send-lock + orphaned-mailbox doctor + mail events | **conformant** | `cmd_send` appends the working/attached mailbox UNDER the same `fleet_lock` (sid read + append atomic w.r.t. respawn swap; deterministic RED/GREEN interleaving test); `mail_sent`/`mail_drained` events, fleet.py sole writer (not a DLQ); `_doctor_check_orphaned_claims(workers=…)` EXTENDS the claim check with orphaned-mailbox (sid + first line). See F-5 (partial drain audit, by construction). |
| 9 | Three-way PID probe | **conformant** | `_WindowsPlatform.get_process_info` returns `(name, None)` on `ACCESS_DENIED` (CIM fallback first); `probe_liveness` → alive/unknown/gone; `recompute_status` keeps alive+unknown `working`, retries once before demoting a gone+no-result `working` turn to dead; `_doctor_check_unreadable_starttime` note-only surface. Alive-unknown never reaped. |
| 10 | Token-ceiling kernel | **conformant** | Hook side ALLOWS stop over ceiling (returns before touching mailbox — mail stays for next launch; never blocks, invariant 2); fleet side writes sid-keyed ceiling file on spawn/respawn, `cmd_send` cumulative-token check refuses resume + sticky `over_ceiling`; ceiling is a token count, not a $-table. See F-2 (boundary `>=` vs `>`), F-3 (basis wording), F-4 (orphaned ceiling files). |
| 11 | Usage-limit resilience (UL1) | **conformant (with F-1)** | `recompute_worker` parks `limited` on a limit-shaped errored turn only (empty stderr → crash-dead, never swallowed); `limit_reset_at`/`limit_kind` additive; `recompute_status` keeps `limited` sticky (never demoted to dead); `cmd_resume_limited`/`_resume_one_limited` relaunch through the lock-guarded pre-claim path with rollback-to-`limited` on failure; null horizon needs `--force-now` (never resumed blind). Signal honestly DEFERRED-TO-KERNEL-PROBE. **F-1**: `_resume_one_limited` omits the under-lock status re-check the other launch paths have. See also F-6 (regex breadth, within contract). |

### UL1 extra-scrutiny verdict
- **Detection fallback never swallows a genuine crash as a park:** PASS — `_stderr_is_limit_shaped("")→False` routes silent crashes to the crash-dead/abnormal-note path; a limit-shaped crash is parked but SURFACED (`limited_suspected` + doctor + flag), never silently lost. Regex breadth (F-6) is within the specced conservative fallback.
- **`limited` recompute-exemption can't strand/resurrect:** PASS — sticky in `recompute_status`, never auto-demoted; resume only via `resume-limited` (reset passed) or `respawn --force`; null horizon requires `--force-now` (no blind resurrection).
- **resume-limited obeys lock/pre-claim:** PASS with **F-1** — lock-guarded pre-claim + `BaseException` rollback to `limited` are present; the missing status re-check under the per-worker lock is the one gap.
- **Signal honestly DEFERRED, not invented:** PASS — DEFERRED-TO-KERNEL-PROBE stated in code; `claude --help` has no usage surface; conservative `limited-suspected` fallback governs until a real wall confirms.

---

## Summary of counts
- MEDIUM: 1 (F-1, resume-limited under-lock status re-check).
- LOW: 3 (F-2 ceiling boundary, F-3 docstring overclaim, F-4 orphaned ceiling files).
- INFORMATIONAL: 2 (F-5 partial drain audit, F-6 UL1 regex breadth).
- Per-kernel: 11/11 conformant (kernel 11 carries F-1).
- Tests: 496 passed; F9 interleaving is a genuine deterministic RED/GREEN; per-kernel coverage present.
