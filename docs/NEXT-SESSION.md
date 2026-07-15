# Next session — M-C (deletion + SPEC v3), after M-B (native dispatch) shipped

Updated 2026-07-16, after M-B (T1-T12) landed. Previous handoff ("build M-B, starting with usage-limit continuity", 2026-07-14) is superseded — that plan was authored and fully executed.

## State

- **M-0 spike + M-A supervisor: COMPLETE** (unchanged from the last handoff — see git history for detail; not repeated here).
- **M-B native dispatch: COMPLETE (T1-T12), code-and-tests-green, LIVE VERIFICATION BLOCKED.** All twelve tasks landed via review-pair + fix-wave, each merged only after an adversarial re-review came back clean:
  - T1 registry v2 fields + outcome store, T2 Stop-hook outcome writer, T3 `dispatch_bg` (task-file bootstrap + short-id join), T4 native `spawn`, T5 outcome discriminator + epoch freeze, T6 usage-limit continuity (transcript scan + fork-steer resume), T7 fork-steer `send`, T8 `claude stop` + tombstone `interrupt`/`kill`, T9 auto-archive, T10 M-A fast-follows, T11 doctor pin-version gate + advisories.
  - Typical per-task shape: implement → spec review + adversarial review in parallel → fix wave → re-review clean (e.g. T7 needed two fix waves after its first introduced a new Critical — logged as "the C4 fix-wave lesson" in `.superpowers/sdd/progress.md`). 1142 unit/hook tests green as of T11 (+3 known pre-existing `sh`-on-PATH env failures, unrelated to native dispatch — see final-review roll-up below).
  - Spec of record: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3. Contract: `docs/specs/native-substrate.md` (13 G-rows, pin-tested at `claude --version` 2.1.207).
- **T12 (this session): pin-test tier written, docs truth sweep done — live tier is RED. Do not treat M-B as production-ready until the two findings below are fixed and the suite goes green.**

### T12 result: `tests/integration/test_native_pin.py` — BLOCKED, two critical live findings

This is the FIRST time any M-B task exercised `dispatch_bg` against the real `claude` CLI end-to-end (T1-T11's own tests all mocked `run=`). It found two bugs that mean **native dispatch has never actually completed a real headless spawn in production**:

1. **Task-file bootstrap (G8) hangs forever under any non-`bypass` mode.** `dispatch_bg` writes the composed prompt to `state/tasks/<name>.md` (`task_file_path`, under `FLEET_HOME`) and tells the worker `"Read <path> and follow it exactly."` — but that path is virtually always OUTSIDE the worker's `--dir` cwd. The G8 spike (`spike/m0/VERDICTS.md`) only ever tested a task file placed INSIDE the project cwd (`"Use the Read tool to read task.md in this directory"`) — this exact gap was never probed. Live repro (2/2, both `pin-w1` and `pin-w2`): the worker's first and only action is a `Read` tool call on the out-of-cwd task file; the session sits forever in roster `status:"waiting"`/`waitingFor:"permission prompt"` (confirmed by reading the live transcript directly — no `PostToolUse`, no `tool_result`, ever). Nobody is present to click "allow" in headless `--bg` mode, so the worker never proceeds. **Fix direction:** `claude --help` confirms `--add-dir <directories...>` ("Additional directories to allow tool [use in]") exists; `dispatch_bg`'s argv never passes it. Pre-authorizing `tasks_dir()` (or `FLEET_HOME`) via `--add-dir` at dispatch time is the likely one-line fix — untested by this session (out of scope for T12: implementer writes tests, a fix-wave applies the fix).
2. **`claude stop`/`claude rm` require the SHORT id (`id`, 8 hex chars), not the full `session_id` fleet.py stores and passes everywhere.** Confirmed empirically, 2/2: `claude stop <full-uuid>` / `claude rm <full-uuid>` both return `No job matching '<uuid>'` (exit 1); the identical call with the short id succeeds (`stopped ...` / `removed ...`). `_stop_native_session` (`bin/fleet.py:7142`) and `_rm_native_session` (`:6121`) both call `[exe, "stop"/"rm", sid]` with the caller's full `session_id` — every caller (`_cmd_interrupt_native`, `_cmd_kill_native`, `_archive_move_and_rm`, `cmd_respawn --force`, `cmd_sup_handoff_abort`) passes the full sid. Both helpers treat a nonzero exit as **best-effort failure and swallow it silently** — the caller's own registry-side bookkeeping (status flip to `interrupted`/`dead`, tombstone write, `archived_at` stamp) commits unconditionally regardless of whether the real `claude stop`/`rm` succeeded. **Net effect: every `fleet interrupt`/`kill`/`archive`/`respawn --force`/`sup-handoff-abort` in production has silently left the real daemon session running/lingering forever, invisible to fleet's own status view**, while fleet's bookkeeping reports success. This is a resource-hygiene and (mildly) security-relevant silent-failure gap, not just a test nit. **Fix direction:** pass `record["native_short_id"]` (already stored on every native record since T3) instead of `session_id` at both call sites — untested by this session, same fix-wave scope note as above.
- Both findings reproduced live, twice each, this session; the orphaned sessions created during discovery were manually stopped/removed (short-id form) before the suite's own teardown was hardened.
- `tests/integration/test_native_pin.py` is otherwise complete and believed correct for all 6 steps (dispatch+roster-contract, Stop-hook outcome, fork-steer, stop-no-hook tombstone, auto-archive, `record_pin_pass`+doctor pin check) — it is expected to go green once the two bugs above are fixed. Its own teardown now tracks and cleans up by SHORT id (not the bug pattern above) and recovers a short id even from a failed spawn, so re-runs against an unfixed `fleet.py` do not leak live daemon sessions.
- **`fleet doctor`'s pin-version check itself works** (`record_pin_pass` + the doctor check were exercised standalone, live, and passed) — only the roster-dispatch-dependent steps are blocked.

### Docs truth sweep (T12 Part B) — done, grep receipts

- `grep -rn "stream-json\|turn_pid\|stderr tail\|max-budget-usd" README.md docs/README.md skills/ commands/`: zero hits for `stream-json`, `turn_pid`, or `stderr tail` in any of the four scoped locations (nothing to reconcile there). `max-budget-usd` hit in `README.md:16,85`, `skills/fleet/SKILL.md:23,52`, `commands/spawn.md:3,12` — all six fixed: native spawn refuses `--max-budget-usd` outright (contract G3; `cmd_spawn` raises `FleetCliError`), so every doc example/flag list now shows `--token-ceiling` instead, with a one-line note that native dispatch carries no dollar cost field. `README.md`'s `fleet status` example cost column (`0.41`) was showing a fabricated nonzero cost for a native worker — changed to `0.00` (native `cost_usd` is never populated).
- `skills/fleet/supervisor.md`: same 4-term grep, zero hits — left untouched.
- `docs/README.md`: zero hits; its claims are doc-index pointers, not technical usage claims — left untouched.
- `README.md`'s "Status" section ("In flight: a pivot...") was deliberately left as-is rather than declared "shipped": this session's own T12 live run just proved native dispatch does not yet complete a real headless spawn end-to-end (see findings above), so claiming the pivot is production-ready would be a fresh doc-truth violation, not a fix. Re-word once the two findings above are fixed and the pin suite is actually green.
- `docs/SPEC.md` and `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md`: untouched per the task's explicit instruction (banner/SPEC-v3 rewrite is M-C's job, not T12's).

## The job: M-C — deletion + SPEC v3

Per `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §6/§8. **Before starting, fix and green the T12 pin suite** (the two findings above) — M-C deletes the legacy fallback path these bugs currently make native dispatch depend on for real usability; deleting it while native dispatch is silently non-functional would leave fleet unable to spawn anything for real work.

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
- **T12 (new, this session, CRITICAL — see above):** task-file bootstrap hangs outside `--dir`; `claude stop`/`rm` silently no-op on a full-sid argument across every native kill/interrupt/archive/respawn-force/handoff-abort call site.

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

- `claude rm` any leftover `pin-w*`/`m0-*` husks if `claude agents --json --all` shows any (T12's own teardown should have left none — spot-check).
- Fix the two T12 findings, re-run `FLEET_LIVE=1 py -3.13 -m pytest tests/integration/test_native_pin.py -v`, and call `record_pin_pass` for real before trusting native dispatch for any real campaign.
