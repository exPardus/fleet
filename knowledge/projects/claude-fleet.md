# Project: claude-fleet (the self-build)

Facts learned live while the fleet builds itself. Amended in each campaign's knowledge wave. See `knowledge/playbooks/campaign-template.md` for the campaign instrument **and the live home of PLAN §0 campaign doctrine**; `docs/SPEC.md` (§18 M-track) for the plan of record and design. `docs/PLAN.md` / `docs/ROADMAP.md` were **retired to superseded history (2026-07-24)** — read them for the C1→C8 record, not as a live contract. The "Bootstrap hazard" section below is the live home of the worktree-isolation doctrine.

## Interpreter & CLI invocation
- Python is **`py -3.13`**. Bare `python` resolves to **3.10** — never use it.
- `bin/fleet.py` is **stdlib-only, single file** (~3000 lines). Grep named anchors; never read end-to-end.
- The `fleet` CLI is **NOT on PATH** in the manager's PowerShell. Call it by full path — `C:\proga\claude-fleet\bin\fleet.cmd` — or `py -3.13 bin/fleet.py`.

## Known live bugs
- **`fleet result` / `peek` crashes on the Windows console (cp1252)** when output contains unicode (e.g. the `→` arrow): a stdout-encoding bug in `bin/fleet.py`. Workaround: set `PYTHONIOENCODING=utf-8`. **STILL LIVE after C2** — C2 did NOT fix it (out of scope). Keep the workaround; still a fix candidate for a future worktree task (fleet.py stdout should force utf-8, not inherit the console codepage).
- **Transient Anthropic API 529 (Overloaded) leaves an empty turn:** a worker can die mid-turn to a 529 → goes idle, `cost_usd` stays FROZEN, no commit, journal unchanged, and `fleet result` may itself 529. **`git log` in the worktree is the ONLY reliable "did the turn land" signal** — not `fleet result`/cost. Re-sending a git-committed fix task is safe; revert partial uncommitted artifacts (e.g. dirtied fixtures) before re-send. (C2, 2×.)

## Bootstrap hazard (the reason for worktrees)
- The manager and all workers execute via the **live** install at `C:\proga\claude-fleet` (registry + hooks resolved through `state/worker-settings.json`).
- **Code-touching workers NEVER run in `C:\proga\claude-fleet`.** One git worktree per code campaign (`C:\proga\claude-fleet-wt\<campaign>`); worktree edits to `bin/fleet.py`/`bin/hooks/*` cannot hot-swap the live CLI/hooks — this is the version-pin.
- **At most ONE `bin/fleet.py` writer alive fleet-wide** at any moment, across all campaigns. Same-file work must serialize; `tests/*`, `bin/hooks/*`, `docs/*` are separate write sets.
- Doc/spec-only workers **may** run in the main repo on strictly disjoint files.

## Parallelism facts (proven live)
- **A SECOND GROUND FOR THE SAME RULE, measured 2026-09-09 (wave 55, kz-work).** The section above argues worktree isolation from the *bootstrap hazard* — worktree edits cannot hot-swap the live CLI and hooks. There is a second, independent ground: **measurement contamination.** Wave 55 ran three lanes in the live repo with genuinely disjoint EDIT targets, and the lane whose deliverable was a full-suite run came back with `10 failed` on 3.12 against `6 failed` on 3.10 plus an ERROR on both — every anomaly caused by a sibling lane's uncommitted `bin/fleet.py` edit landing *between* the two interpreter runs (`conftest.py`'s install-plane hash guard firing correctly; four `test_self_citations` / `test_retired_sid_citations` line-drift failures). **A suite run reads the whole tree, so it is disjoint from nothing.** Disjointness is a property of WRITES; a measuring lane's dependency is on READS, so the disjointness test can pass while the measurement is destroyed. *A lane whose deliverable is a measurement of the tree runs alone or in its own worktree — including a docs-only lane, which still has to run the suite to prove it moved nothing.* Re-run clean once the tree was quiescent: 4776 collected, identical on both interpreters, six pre-existing failures, no ERROR.
- **Disjoint-file parallelism is safe** — proven to **7-wide** with exact-path staging + index.lock retry (Campaign-0/1).
- **Same-file parallelism is not** — serialize all `bin/fleet.py` work into a chain with the per-link truth gate.

## SPEC v2.1 landmarks
- Numbered **9-invariant section** (added by C1 `spec-amend-3-testing`; ROADMAP + stubs cite it by number).
- Appendix **F1–F16 are SETTLED** — never relitigate them. **F17–F32 are the v2.1 amendments** (incl. UL1 usage-limit resilience, UL2 worker-subagents).
- **Prescriptive amendments tagged `[UNBUILT — owned by <kernel>]`** — spec text describing behavior a later code kernel must build, not behavior true of the code today. Do not demand green tests for `[UNBUILT]` items.

## Operational facts
- `fleet doctor` **`wt`-absent is a known-fine fallback** (detached PowerShell attach) — not a failure.
- **`dead` is sticky** (operator kill survives recompute); `respawn` is the only recovery lever.
- **Respawn re-executes a completed task** — the journal carries context, not idempotence. Respawn is for stuck/long-context workers, not to preserve a finished worker's state.
- Cost per worker = `cost_baseline` (respawn carry) + sum of the current log's result events. `cost_usd` reflects only *completed* turns — a runaway resume turn shows $0 until it ends.
- `--max-budget-usd` **overshoots ~3×** on tiny caps — circuit breaker, not a precise ceiling.
- **Stop-block race is real:** a `send` in a turn's last seconds queues to the mailbox (idle+mail) instead of same-turn delivery — by design (universal drain rule). Check `idle+mail` in status; don't assume same-turn.

## C2 facts (self-modification proven — 2026-07-09)
- **The revert path WORKS and was exercised end-to-end:** merge → post-merge gate RED → `git revert -m 1 <merge>` (known-good install restored, stayed live) → worktree fix → re-merge → green. The C2 checkpoint claim **"the fleet can safely modify itself" is EARNED**, not theoretical.
- **Re-merge after a reverted merge:** a plain re-merge is a **no-op** (git sees the branch as already merged). Sequence: `git revert <the-revert>` (restores the reverted code) then `git merge <branch>` (picks up the new fix commit).
- **The `FLEET_LIVE` harness is non-idempotent on the tracked fixture corpus:** it re-captures `tests/fixtures/streams/*.jsonl` every run. Restore with `git checkout -- tests/fixtures/streams/` before any git-state check. (Backlog: gate corpus capture behind `FLEET_CAPTURE_CORPUS=1`, else write to temp.)
- **Hook-source-specific live demo tests must `pytest.skip` (not hard-assert) under the merge-gate default `FLEET_HOOK_SOURCE=main`** — a `assert HOOK_SOURCE == "worktree"` turns the post-merge gate RED (cost C2 a full revert cycle for a one-line scoping bug).

## New CLI surface (C2)
- `fleet resume-limited` — restart workers parked by a usage limit (UL1).
- `--token-ceiling` on `spawn`/`respawn`; new statuses `over_budget` / `over_ceiling` / `limited`; spawn echoes the resolved model.
- **New standing post-merge live checks:** FLEET_LIVE integration tier (default = main hooks); `fleet init` re-render when `worker-settings.template.json` changes (PostCompact hook added in C2); `fleet doctor` now also checks hook-registration, unreadable-starttime, limited-parks, ceiling-file-sweep, hook-errors; live hook-smoke.

## kz-work host: memory, and the mcx substrate (2026-09-10)
- **The host is RAM-bound and it has already cost a supervisor.** 8 GB total, **~1.7 GB of it the
  claude daemon's pre-warm pool**. At **15:18:08Z the OOM killer hit the daemon scope**: it shut down
  (`cause=signal`, `live_workers=12`) and **every Claude session on the box died, the supervisor body
  included** — the next generation booted by SEIZE, not handoff. The 12 were mostly corpses: **4
  retired supervisor bodies + 8 idle finished workers at ~350 MB each**, plus mcx lanes at ~170 MB per
  lane across 3–4 node processes.
- **`fleet autoclean` is 0-for-30 on exactly those rows** — measured post-OOM: `archived 0 worker(s),
  skipped 30`, `husks_removed=0`. Cause: `--ttl-hours` defaults to 24 and every corpse was younger.
  *An age-based sweeper cannot reap a fresh corpse, which is the only kind that can OOM you.*
- **Ceiling, operator ruling: at most 3 live worker sessions on the host at once, Claude and Codex
  counted together (a Codex lane counts as one); do not dispatch under 1.5 GB available** (`free -m`).
  **The metric is the `available` column, NEVER `free`** — corrected by the interface 2026-09-10 after
  this supervisor raised a host warning leading with `506 MB free` while `available` read 4783 MB and
  PSI was zero. `free` excludes reclaimable page cache and on this box runs low as a matter of course;
  a warning keyed on it is a false alarm. Check PSI before escalating. **There is no swap on this
  box**, which is why the OOM killer arrives with no warning shoulder once `available` really does
  run out.
  Note the ceiling is about the HOST, not about one fleet: lanes running in the operator's other
  projects count against the same 8 GB, and are not visible in `fleet status`.
- **DO NOT background `mcx spawn --wait` ON THIS HOST — it loses the lane. MEASURED 2026-09-10.**
  `--wait` is documented to stop its run and children when the waiter is cancelled, and this host's
  HARNESS kills background commands on its own low-memory guard, which appears keyed on `free` (253 MB
  at the time) rather than `available` (4147 MB, PSI zero). The two compose into a lane that is
  spawned and then immediately `stopped`: lane `mImoA8QT` died that way seconds after dispatch. The
  same guard killed two full floor runs within seconds each.
  **RULE (operator, 2026-09-10T20:4xZ): DETACHED LANE + OBSERVER.** Spawn detached (no `--wait`),
  then arm one harness-backgrounded observer per lane that owns nothing:
  `while :; do mcx result "$id" >/dev/null 2>&1; rc=$?; [ "$rc" -eq 2 ] || break; sleep 30; done`.
  If the guard kills the observer you get a `killed` notification and re-arm; the lane survives.
  **Proven 2026-09-11:** the guard killed the observer for lane `yT3qCJAa` at 3526 MB available and
  the lane was still `running` afterwards. The same event under a backgrounded `mcx spawn --wait`
  kills the lane, which is how `mImoA8QT` was lost.
  Re-arm after every `mcx steer`. **MEASURED exit codes — break on NOT-2, never on 0:** `mcx result`
  is **2** while live, **0** when finished, **1** for a stopped lane or an unknown id — all four
  confirmed on this host, rc=2 against a running lane on 2026-09-10. An
  `until mcx result …` loop therefore spins forever on a guard-killed lane and on a typo'd id, which
  are two of the three endings it exists to report. A `tail --pid` waiter was the first remedy and works, but a
  waiter you do not need is a shell you are paying for on a box that kills shells. Same reasoning for
  long test runs: **run the floor in the FOREGROUND, split into halves** to stay inside the tool
  timeout — and note `ls tests/test_*.py` silently misses `tests/integration` (9 skips).
- **mcx 0.2.0** (installed 2026-09-10T16:4xZ): `mcx spawn --wait` prints the ID, stays alive for that
  one run and exits with its status — sound on a host without a background-kill guard, but see the
  entry above for why it is not used here. **Poll loops
  (`mcx list` + `sleep`) are retired**: each costs a shell and they are what a low-memory kill reaches
  first. `mcx steer --wait ID` tracks a resumed run, one waiter per run; TERM/INT/HUP on a waiter
  stops its run and children, so never `&` or `nohup` one. Approval modes `never` (default,
  workspace-write) / `auto` / `unrestricted`; keep `never` for lanes. `.mcx/config` accepts only
  `approval=`; `.mcx/` is gitignored, worktrees included; mcx state lives in `<cwd>/.mcx/`, so spawn
  FROM the lane's worktree.
- **Model budget, operator ruling 16:5xZ: default `gpt-5.6-luna` (omit `-m`), `-r medium`.** `-r high`
  only for a build lane touching `bin/fleet.py`; `gpt-6-astra` only for a task whose failure on 5.6
  can be NAMED IN ADVANCE, with the reason in the dispatch line — never for docs, tests, receipts,
  reports or folds. **Both plans are constrained at once: Claude 77%, Codex 75%, both resetting around
  2026-09-15**, so waves are 1–2 lanes.
- **The supervisor must never export `MCX_WORKER=1`** — it is the lane-side recursion guard, and
  setting it on yourself gets `mcx: workers cannot launch or steer workers`.
- **Codex cannot commit**: its sandbox makes git metadata read-only. Every lane ends with the
  supervisor committing on its behalf, so every brief must say so and ask for a PATH LIST.
- **A Codex lane works on a SNAPSHOT** — anything mutating a live append-only file (`JOURNAL.md`,
  `lessons.md`, `CHANGELOG.md`) must be re-derived at landing, never merged.

## Keeper wake transport on kz-work (2026-09-10)
- MEASURED from installed Claude 2.1.267 binary: local daemon protocol-1 `reply` targets an existing handle; the higher-level vendor reply helper may bootstrap a daemon, so keeper B uses the direct socket. `list` binds daemon-local short ID to the observed session ID/PID before `reply`; there is no atomic compare-and-deliver API. See `docs/operator/keeper-wake.md` for explicit socket/key opt-in and config-root path derivation. Never log the key or full daemon list (which contains nonces).
- MEASURED source limitation: normal idle retirement uses eight hours, but low-memory retirement can use 60 seconds. Fifteen-minute keeper ticks beat the ordinary timeout, not every retirement cause. Actual wake/model progress and real plan-limit refusal remain unmeasured by this fenced lane.
- MEASURED lane sandbox: creating/binding AF_UNIX sockets returns EPERM, including socketpair; deterministic transport tests run, while the isolated real-wire test explicitly skips. Full logs: `state/receipts/w64-waker/` in the w64-waker worktree, not the live fleet home.
