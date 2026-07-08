# C2 adversarial break review — `c2-review-adversarial`

**Scope:** full C2 diff `git diff fleet-impl...c2-hardening` (hook kernels,
live harness, fleet.py harden chain). Read-only; both lenses (spec-conformance
+ adversarial break). Repros live in `state/scratch/c2-adv/` (not the repo).

## Verdict: **BREAKS FOUND — not safe to merge as-is.**

One HIGH break violates the central one-live-claude invariant (SPEC inv. 6/7).
One MEDIUM break inverts UL1's own stated crash-vs-park contract. Both are
reproduced deterministically below. Everything else attacked held.

---

## Findings (ranked by severity)

### F-A1 (HIGH) — `_resume_one_limited` pre-claims with NO under-lock re-validation → double-launch, one-live-claude violation

**Where:** `bin/fleet.py::_resume_one_limited` (the pre-claim block, ~L2497–2507),
reached from `cmd_resume_limited` (~L2572–2599).

**Defect.** Every other launch path in the module observes the launch-guard
status *and* writes its pre-claim **inside the same `fleet_lock`**:
- `cmd_send` idle-resume recomputes and checks `status == "idle"` under the
  lock it then pre-claims in (L2332–2387);
- `cmd_respawn` checks `after["status"]` under its lock before pre-claiming
  (L3085–3132).

`cmd_resume_limited` instead snapshots eligibility under **one** lock
(L2572–2582), **releases it**, then per worker calls `_resume_one_limited`,
which acquires a **fresh** lock and *unconditionally* overwrites
`status="working"/turn_pid=None` — it never re-reads or re-checks that the
record is still `limited`:

```python
with fleet_lock():
    data = load_registry()
    rec = data["workers"][name]
    rec["status"] = "working"      # <-- no `if rec["status"] != "limited": abort`
    rec["turn_pid"] = None
    ...
```

The F1 launch-in-flight guard does **not** save this path: that guard only
stops a concurrent reader from *demoting* a `working`+`turn_pid=None` claim; it
does nothing to stop `_resume_one_limited` itself from *blindly writing* that
claim over a record another actor already moved on.

**Repro** (`repro_resume_double_launch.py`, exits 1 = break):
Inputs — worker `probe-1` currently `status=working`, `turn_pid=4321` (a live
turn a concurrent actor already started), same `session_id`. Call
`_resume_one_limited("probe-1", ...)` as `cmd_resume_limited` would for a name
it snapshotted as `limited`.
```
BEFORE: status=working turn_pid=4321 (a live turn)
AFTER : status=working turn_pid=9999
launches (new claude --resume processes started): 1
*** BREAK CONFIRMED *** second claude --resume on the same session; 4321 orphaned
```
Wrong output: a **second** `claude --resume <sid>` is launched on a session
that already has a live turn, and the tracked `turn_pid` 4321 is overwritten to
9999 → the first process becomes an untracked orphan. **One-live-claude
invariant broken.**

**Realistic trigger (no artificial injection needed):** two `fleet
resume-limited` invocations racing (operator re-runs an apparently-hung sweep,
or a `/loop`/cron drives it); or a `resume-limited` sweep racing a
`respawn --force` / `send` idle-resume of the same worker. Both invocations
snapshot the worker while still `limited`; whichever calls `_resume_one_limited`
second clobbers the first.

**Fix (anchored to role):** `_resume_one_limited`'s job is "relaunch a *still-
limited* worker through the guarded launch path." It must therefore, inside its
own pre-claim lock, re-read the record and **abort if it is no longer
`limited`** (raise a `FleetCliError` / return a skip signal that
`cmd_resume_limited` records as `skipped`), exactly mirroring `cmd_send`'s
observe-idle-then-claim-in-the-same-lock discipline. The eligibility snapshot in
`cmd_resume_limited` is advisory; the authoritative decision must be re-made
under the launch lock. (Add a test seeding the worker `working`/real-pid and
asserting `_resume_one_limited` launches nothing and leaves the live pid intact.)

---

### F-A2 (MEDIUM) — UL1 `_LIMIT_STDERR_RE` over-matches → genuine crash mis-parked `limited`, inverting its own contract

**Where:** `bin/fleet.py::_LIMIT_STDERR_RE` (L1444–1447), consumed by
`_stderr_is_limit_shaped` → `recompute_worker`'s crash branch (L1556–1564).

**Defect.** The regex
`usage limit|rate limit|plan limit|resets?\s+at|try again (?:later|in)|quota`
is documented as "deliberately conservative — a genuine crash must never be
swallowed as a park." It is not: bare `quota`, `rate limit`, and
`try again later` are common in ordinary error output. When an errored turn
(no trailing `result` event) has a stderr tail containing any of these, the
crash branch parks the worker `limited` (null horizon when no ISO instant is
present) **instead of** the crash-dead path — and skips
`_append_abnormal_turn_note`, so the crash leaves no journal landmark.

**Repro** (`repro_ul1_falsepark.py`):
```
[crash-0] stderr="OSError: [Errno 122] Disk quota exceeded: '/out.jsonl'"
        -> status=limited  (MIS-PARKED); abnormal-turn note dropped=False; horizon=None
[crash-1] stderr='requests.exceptions.HTTPError: 429 rate limit (upstream MCP server)'
        -> status=limited  (MIS-PARKED); abnormal-turn note dropped=False; horizon=None
[crash-2] stderr='AssertionError: retry budget drained, try again later'
        -> status=limited  (MIS-PARKED); abnormal-turn note dropped=False; horizon=None
```
Wrong output: three genuine crashes classified `limited`. A null-horizon
`limited` park is **not** auto-resumed (`_limit_reset_passed` → False; needs
`--force-now`) **and** is not surfaced as a crash — so a real infra failure
(disk-full `EDQUOT`/`ENOSPC` from the `claude` CLI's own stderr, an upstream
MCP 429, a worker assertion) is masked as a plan wall and the abnormal-turn
journal note is suppressed.

**Honest vector note:** the outer `claude -p` process's stderr carries the
Claude Code CLI's *own* diagnostics, not the worker's task-tool output — so the
realistic hits are CLI/infra failures (disk-full, MCP server errors, network
`try again later`), not arbitrary task text. That still includes exactly the
class of failure you least want mislabeled as a benign plan-limit park.

**Fix (anchored to role):** the classifier's role is "recognize a *plan usage-
limit wall*, never a crash." Tighten toward that: (a) require the signal to be
anchored to Claude's actual limit phrasing (e.g. co-occurrence of a limit noun
*and* a reset/again clause, or a leading `Claude`/`Anthropic`/HTTP-429-limit
marker), not any single generic substring; (b) drop bare `quota`; (c) until the
DEFERRED-TO-KERNEL-PROBE real signal is pinned, prefer parking only when the
horizon is *also* parseable, and route ambiguous errored turns to crash-dead
(the note is cheap; a missed park costs only an explicit `resume-limited`, a
false park hides a crash). Add a regression asserting the three stderr tails
above stay crash-dead.

---

## Attacked and held (tried, correctly resisted)

- **F9 send-under-lock vs respawn drain+sid-swap** — closed. `cmd_send` reads
  `sid` and `append_mailbox`s it under the *same* `fleet_lock` for
  working/attached (L2390–2402); `cmd_respawn` swaps the sid under its lock.
  Lock-serialized, so no send can read the old sid outside a lock, and any
  message a send lands under the lock is either drained by respawn's
  `compose_prompt(old_sid)` or already sits in the post-swap sid's mailbox for
  its own hooks. The idle-resume out-of-lock `append_mailbox` (L2427) is
  protected: its pre-claim `working`/`turn_pid=None` makes a concurrent respawn
  refuse (`turn is running` / `launch in flight`, L3086–3100), so the sid can't
  be swapped under it.
- **`mail_sent`/`mail_drained` single-writer** — held. `mail_drained` is emitted
  only in `compose_prompt` (L1031), called only by fleet.py launch paths;
  `mail_sent` only in `cmd_send`. `events.jsonl` is a best-effort audit log,
  not the authoritative registry (invariant 6 is about the registry).
- **Retry-once PID probe re-probes** — held. `recompute_status` L828–834 issues a
  *fresh* `probe_liveness` (fresh `get_process_info`) after the sleep, not a
  cached verdict; alive/unknown both keep `working` (never reap on a hiccup),
  only a second `gone`+no-result demotes.
- **alive-unknown demotion** — held. `probe_liveness` returns `unknown` for
  exists-but-unreadable-StartTime and `recompute_status` maps unknown→working
  unconditionally (L820, L831). (Residual, already documented by F20/F-CMD: a
  reused PID landing on a node/cmd/claude process whose StartTime is
  unreadable stays `working` — accepted, not introduced by C2.)
- **Rotation clean-fail rollback** — held. `LogRotationError` path un-rotates and
  restores the pre-respawn snapshot, guarded on the record still being the exact
  unlaunched claim (`session_id==new_sid`, `working`, `turn_pid is None`)
  (L3193–3206); the launch-failure path un-rotates *before* restoring the
  snapshot (L3236–3244). Both partial-rename paths roll back.
- **Hooks on hostile/malformed stdin** — held. `printf 'not json{{{'`,
  `{"session_id":"../evil"}`, and `{}` all exit 0 across
  stop/postcompact/posttooluse; the `..` sid is rejected by `_valid_token`
  (skips, never traverses).
- **Ceiling read never inverts the ALLOW-only rule** — held. `_read_ceiling`
  returns None on any failure (missing/non-numeric) → falls through to the
  existing block-on-mail behavior; the hook only ever *returns early to ALLOW*
  when `ceiling is not None and current >= ceiling`, never blocks because of the
  ceiling.
- **PostCompact wrong-journal** — held. sid→name resolution failure falls back to
  a sid-keyed journal (sid already `_valid_token`-checked); it never guesses a
  different worker's NAME. `_resolve_name` is read-only and returns None on
  locked/corrupt/missing registry.
- **`restore_mailbox_claim` target reconstruction** — held. `split(".md.claimed.")`
  reconstructs `<sid>.md` correctly for uuid sids; newer-mail-arrived branch
  prepends the older claimed content rather than dropping it.

---

## Repro artifacts
`C:\proga\claude-fleet\state\scratch\c2-adv\` (throwaway, not committed):
- `repro_resume_double_launch.py` — F-A1 (exits 1 on break)
- `repro_ul1_falsepark.py` — F-A2
