# Next session — M-C (deletion + SPEC v3), after M-B (native dispatch) shipped

Updated 2026-07-16, after M-B (T1-T12) landed. Previous handoff ("build M-B, starting with usage-limit continuity", 2026-07-14) is superseded — that plan was authored and fully executed.

## State

- **M-0 spike + M-A supervisor: COMPLETE** (unchanged from the last handoff — see git history for detail; not repeated here).
- **M-B native dispatch: COMPLETE (T1-T12), code-and-tests-green, LIVE VERIFICATION BLOCKED.** All twelve tasks landed via review-pair + fix-wave, each merged only after an adversarial re-review came back clean:
  - T1 registry v2 fields + outcome store, T2 Stop-hook outcome writer, T3 `dispatch_bg` (task-file bootstrap + short-id join), T4 native `spawn`, T5 outcome discriminator + epoch freeze, T6 usage-limit continuity (transcript scan + fork-steer resume), T7 fork-steer `send`, T8 `claude stop` + tombstone `interrupt`/`kill`, T9 auto-archive, T10 M-A fast-follows, T11 doctor pin-version gate + advisories.
  - Typical per-task shape: implement → spec review + adversarial review in parallel → fix wave → re-review clean (e.g. T7 needed two fix waves after its first introduced a new Critical — logged as "the C4 fix-wave lesson" in `.superpowers/sdd/progress.md`). 1142 unit/hook tests green as of T11 (+3 known pre-existing `sh`-on-PATH env failures, unrelated to native dispatch — see final-review roll-up below).
  - Spec of record: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3. Contract: `docs/specs/native-substrate.md` (13 G-rows, pin-tested at `claude --version` 2.1.207).
- **T12: pin-test tier written, docs truth sweep done — live tier was RED at T12, then fixed by the T12 fix wave (below). Pin suite green as of commit `76eca87` on `mb/t12`.**

### T12 result: `tests/integration/test_native_pin.py` — two critical live findings, both FIXED

This was the FIRST time any M-B task exercised `dispatch_bg` against the real `claude` CLI end-to-end (T1-T11's own tests all mocked `run=`). It found two bugs that meant **native dispatch had never actually completed a real headless spawn in production**. The T12 fix wave (commit `76eca87`) fixed both, plus a third bug it found live-verifying them:

1. **FIXED (`76eca87`). Task-file bootstrap (G8) hung forever under any non-`bypass` mode.** `dispatch_bg` writes the composed prompt to `state/tasks/<name>.md` (`task_file_path`, under `FLEET_HOME`) and tells the worker `"Read <path> and follow it exactly."` — but that path is virtually always OUTSIDE the worker's `--dir` cwd. The G8 spike (`spike/m0/VERDICTS.md`) only ever tested a task file placed INSIDE the project cwd — this exact gap was never probed pre-T12. Live repro (2/2, both `pin-w1` and `pin-w2`): the worker's first and only action was a `Read` tool call on the out-of-cwd task file; the session sat forever in roster `status:"waiting"`/`waitingFor:"permission prompt"`. **Fix:** `dispatch_bg` now passes `--add-dir <tasks_dir().as_posix()>` on every `--bg` launch (`fleet.py`, `dispatch_bg`) — pre-authorizes `tasks_dir()` specifically, never `FLEET_HOME` wholesale (least privilege). Live-confirmed: the pin suite's `test_1`/`test_4` spawns (the exact failing case) now complete under `--mode accept`.
2. **FIXED (`76eca87`). `claude stop`/`claude rm` required the SHORT id (`id`, 8 hex chars), not the full `session_id` fleet.py stores and passes everywhere.** Confirmed empirically, 2/2: `claude stop <full-uuid>` / `claude rm <full-uuid>` both returned `No job matching '<uuid>'` (exit 1); the identical call with the short id succeeded. `_stop_native_session` and `_rm_native_session` both called `[exe, "stop"/"rm", sid]` with the caller's full `session_id`, and both swallowed a nonzero exit as best-effort failure while the caller's OWN registry bookkeeping committed unconditionally — every `fleet interrupt`/`kill`/`archive`/`respawn --force`/`sup-handoff-abort` in production had silently left the real daemon session running/lingering, invisible to fleet's own status view. **Fix:** new `_native_job_ref(sid)` derives the short id (first hyphen-delimited segment — matches every observed short id, uniformly, including retired sids that have no stored `native_short_id`); both helpers try the short id first and retry once with the full sid on a nonzero exit (belt-and-braces). Callers unchanged — still pass full sids, conversion is internal. Live-confirmed: pin suite steps 4 (interrupt tombstone) and 5 (archive rm) go green.
3. **FIXED (`76eca87`, new finding, discovered live-verifying 1+2).** `_parse_bg_short_id` didn't strip ANSI escape codes: a color-forcing env var (`FORCE_COLOR`) in the dispatching shell makes the daemon colorize the short id in `--bg` stdout even though it's piped (not a tty) — `\S+` in the parse regex greedily swallowed the CSI codes, corrupting the captured short id so it never prefix-matched the real `sessionId`, manifesting as a fake "no roster entry joined -- possible DOA" on every dispatch in an environment with color forced. **Fix:** `_parse_bg_short_id` now strips `\x1b\[[0-9;]*[A-Za-z]` before matching.
- Both original findings reproduced live, twice each, at T12; the fix wave re-reproduced live, then live-verified the fixes: **`FLEET_LIVE=1 pytest tests/integration/test_native_pin.py` — 6/6 green, three consecutive runs** (one had an unrelated 197s `fleet wait` flake mid-diagnostics, almost certainly the fix wave's own heavy live-dispatch churn while root-causing finding 3, not a code defect — reproduced clean immediately before and after).
- `tests/integration/test_native_pin.py` also got two test-only fixes during the same live verification (not fleet.py bugs): `test_5`'s gate-3 wait now explicitly `claude stop`s the sid(s) first (an idle `--bg` session does not self-clear roster liveness within any short window on its own — live-confirmed it stays live 75+s with no sign of self-expiry; production TTLs are hours, long enough for the real process to have exited on its own by then, but the pin suite's compressed timeline needs the same effect simulated), and its post-archive assertion no longer false-positives on `cmd_archive`'s own literal `"skipped 0"` in the success summary line.
- **`fleet doctor`'s pin-version check works** (`record_pin_pass` + the doctor check exercised standalone, live, and pass) — confirmed again as part of the now-green suite (step 6).
- **Do not run a real campaign on native dispatch if the dispatching shell forces color** (`FORCE_COLOR`/`CLICOLOR_FORCE` set) **against a fleet.py older than `76eca87`** — finding 3 above blocks 100% of dispatches in that environment, independent of findings 1/2.

### Docs truth sweep (T12 Part B) — done, grep receipts

- `grep -rn "stream-json\|turn_pid\|stderr tail\|max-budget-usd" README.md docs/README.md skills/ commands/`: zero hits for `stream-json`, `turn_pid`, or `stderr tail` in any of the four scoped locations (nothing to reconcile there). `max-budget-usd` hit in `README.md:16,85`, `skills/fleet/SKILL.md:23,52`, `commands/spawn.md:3,12` — all six fixed: native spawn refuses `--max-budget-usd` outright (contract G3; `cmd_spawn` raises `FleetCliError`), so every doc example/flag list now shows `--token-ceiling` instead, with a one-line note that native dispatch carries no dollar cost field. `README.md`'s `fleet status` example cost column (`0.41`) was showing a fabricated nonzero cost for a native worker — changed to `0.00` (native `cost_usd` is never populated).
- `skills/fleet/supervisor.md`: same 4-term grep, zero hits — left untouched.
- `docs/README.md`: zero hits; its claims are doc-index pointers, not technical usage claims — left untouched.
- `README.md`'s "Status" section ("In flight: a pivot...") was deliberately left as-is rather than declared "shipped" at T12 time: that session's own live run had just proved native dispatch did not yet complete a real headless spawn end-to-end. The T12 fix wave (`76eca87`) has since fixed all three findings and the pin suite is green — this section is still due a re-word (not yet done as of the fix wave, which was scoped to `fleet.py` + tests, not docs).
- `docs/SPEC.md` and `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md`: untouched per the task's explicit instruction (banner/SPEC-v3 rewrite is M-C's job, not T12's).

## The job: M-C — deletion + SPEC v3

Per `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §6/§8. **The T12 pin suite is green as of `76eca87`** (the three findings above are fixed) — M-C's own done-criteria (§8) still calls for a soak campaign (real usage, not just the pin suite) before deleting the legacy fallback path native dispatch used to silently depend on.

**§6 Deletions:**
- Dies: detached-Popen launch machinery, `probe_liveness` + probe-ctime code, PID-liveness registry fields, per-turn stdout log pipeline (`logs/*.jsonl`).
- Cancelled, never built, do not list as a deletion: F33 `turn_pid_boot_id`.
- Stays: mailbox, journal, budget/token-ceiling hooks, knowledge loop, corrupt-registry quarantine; `spawn`/`respawn`/`send`/`status`/`kill`/`peek`/`result` remain but as wrappers over the native surface + overlay + hook-journaled events.
- Legacy coexistence code (`refuse_if_legacy` and every site that calls it) can retire once no legacy (`dispatch_kind` absent) records remain reachable — confirm the operator's own fleet is native-only or explicitly acknowledges a mixed fleet before deleting (spec §5.1, "M-B deploy requires an empty fleet or explicitly acknowledges the mix" — same rule applies in reverse at M-C's deletion point).

**§3 "Superseded prior-spec surface" — banner, MOVE never delete** (`[SUPERSEDED — native-substrate pivot 2026-07-13]`):
- `docs/specs/portability.md` (probe-matrix/`boot_identity`/`killpg` — daemon now owns this).
- `docs/SPEC.md` v2.2 §6 "Worker turn launch (Windows detail)" — detached-spawn plumbing, PID-based liveness verdicts.
- `docs/specs/phase-2-watchtower.md` — PID-liveness polling premise; watchtower duties fold into the supervisor's beat.
- `docs/specs/terminal-surface.md` — rules stay binding (views read-only, no locks, exit 0, quarantine, worker-suppression); only its probe-premised prose gets banners.
- `docs/SPEC.md` §4 hook write boundary — amend (not silently contradict): add the Stop hook's terminal-outcome-record write to the sanctioned hook-write list.
- Unaffected, no banner needed: mailbox protocol, budget-hook design, knowledge loop, campaign-template doctrine, corrupt-registry quarantine.

**§8 milestone text:** "M-C — deletion + SPEC v3. Retire per §6, banner superseded sections (§3 list), soak campaign before done." A soak campaign (real usage, not just the pin suite) is explicitly part of M-C's own done-criteria — plan for it after the pin suite is green, not instead of it.

## Final-review / fix-wave roll-up (accumulated debt, M-C-or-fix-wave inputs)

Grepped from `.superpowers/sdd/progress.md` (`grep "final review\|final wave"`) — every item below was explicitly deferred at the time its task shipped, not forgotten:

M-B-era (T1-T11), still open unless noted:
- T2-era: `postcompact_journal.py` has the same wrong-shape-registry gap T2 fixed elsewhere in the Stop path — repro-confirmed, never patched.
- T3-era: unhashable `sessionId` in a pre-snapshot set comprehension, `fleet.py` ~4823, plus the SAME latent pattern in `cmd_sup_handoff_begin` ~5324.
- T4-era: non-lock `OSError` escapes `_commit_launched_turn` at 4 sites, including 3 legacy ones (`fleet.py:3104/3196/3939`) — a cross-cutting fix once, not per-site.
- T5-era: persist-freeze prints a stale poll verdict (pre-existing, cosmetic).
- T8-era: `test_never_deletes_idle` is test-theater — needs a genuine-idle repro ported from the adversarial re-review that found this.
- T9-era: live-retired-sid file-move split-history (self-heals via `fleet clean`, cosmetic); archive summary bucket wording is cosmetic.
- T10-era: `None==None` guard in abort equality is unreachable via the CLI (`required=True`) — dead code, safe to simplify or drop.
- **T12 (CRITICAL, FIXED in `76eca87` — see above):** task-file bootstrap hung outside `--dir`; `claude stop`/`rm` silently no-op'd on a full-sid argument across every native kill/interrupt/archive/respawn-force/handoff-abort call site; a third finding (ANSI-escape corruption of the parsed short id under `FORCE_COLOR`) surfaced live-verifying the first two. All three fixed, pin suite green.

Pre-M-B (M-A-era or earlier), still real, lower priority:
- `fleet_lock` disk-full fd-leak edge (LOW).
- `importlib.reload` fragile test.
- `TestCollaboratorInstall` needs `sh` on PATH — fails on the base env too; matches T11's "+3 known sh-env fails". Skip-guard candidate rather than a real bug.
- T3-era (M-A) script duplication note; `INDEX.md` extra line — both cosmetic.

## Standing rules

- CLAUDE.md rules bind (py -3.13, forward slashes in hook commands, no Git-Bash `&`, views read-only).
- Per-task adversarial review of evidence AND code both — the M-0 spike caught overclaims in 5/8 tasks, M-B's own T7 caught a fix wave introducing a new Critical; keep the bar.
- Never trust a mocked `run=` test as proof a real CLI call works — T12 is the second time in this project a live run found something every unit test missed (T7/T8/T9's own `_stop_native_session`/`_rm_native_session` unit tests all pass today, mocking away the exact bug T12 found).
- Push `fleet-impl` and fast-forward `main` at every green milestone (operator standing directive) — NOT done automatically by worker sessions inside `.claude/worktrees/`; the controller/operator does this at merge time.
- Supervisor GOALS.md binds the manager session too (cost frugality: cheapest-capable models, no idle polling; handoff at 300-500k context).

## Cleanup owed (cheap, any session)

- `claude rm` any leftover `pin-w*`/`m0-*` husks if `claude agents --json --all` shows any (both the T12 and T12-fix-wave teardowns should have left none — spot-check; confirmed clean after the fix wave's own runs).
- Done: the T12 fix wave (`76eca87`) fixed all three findings and confirmed `FLEET_LIVE=1 py -3.13 -m pytest tests/integration/test_native_pin.py -v` 6/6 green (three consecutive live runs) and `record_pin_pass` for real. Still owed: re-word `README.md`'s "Status" section off "in flight" now that this is confirmed working end-to-end.
