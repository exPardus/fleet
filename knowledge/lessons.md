# Lessons

Append-only postmortems. One entry per campaign: what worked, what stalled, prompt patterns worth reusing. Never edit or delete a past entry — add new ones below.

<!-- Add new entries below this line -->

## 2026-07-08 — Self-build turn-one decisions (manager)

Decisions recorded per PLAN §0.5 (dated, on-disk, not session memory):
- **POSIX exercise box (C4):** Altai picked the **exPardus dev server 192.168.1.202** (real Linux, SSH-reachable) over the WSL fallback. `port-posix-smoke` dispatches there.
- **Budget:** Altai on **Claude Max 20x plan** — approved a **higher/generous cap** for the C1+C2 readiness boundary (declined the ~$330 sum-of-caps ceiling as a limit; treat caps as circuit-breakers, not a starved envelope). Per-task caps stay at §0.4 class defaults for the §0.1.8 2×-cap kill rule.
- **New feature — usage-limit resilience (plan ID UL1):** Altai requested "a way for the fleet to restart itself if it hits a usage limit for a 5 hour or weekly session." No review-doc finding exists; manager authored the single binding input `docs/reviews/USAGE-LIMIT-RESILIENCE-INTENT-2026-07-08.md`. **Folded into C1** as a new Wave-1A chain link `spec-amend-4-usagelimit` (sequential last, SPEC.md single-writer) and into **C2** as hardening-kernel item 11. Surfaced to Altai for ratification at the C1 checkpoint (touchpoint 4).
- **Dirty tree:** `workflows/idea-forge.workflow.js` (ROUNDS 3→2) committed at Altai's instruction; tree clean before C1.
- **Second new feature — worker subagents (plan ID UL2):** Altai requested (mid-C1, 2026-07-08) that fleet workers be able to use their own subagents (Task/Agent tool). No review-doc finding; manager authored binding input `docs/reviews/WORKER-SUBAGENTS-INTENT-2026-07-08.md`. **Folded into C1** as SPEC.md link `spec-amend-5-subagents` (sequential after the 1D SPEC.md fix wave). Key hazard: `fleet doctor`'s `_doctor_check_claude_agents` must not false-positive a worker's legitimate subagents; permission-mode inheritance under bypass is a security note. Likely C1 documentation-only (subagents are native Claude Code) — C2 code only if the probe shows a launch flag / doctor exemption is needed. Ratified with UL1 at the C1 checkpoint.

## 2026-07-07 — Campaign 0: building fleet itself (subagent-driven, 30+ agents)

The fleet CLI was built by a multi-agent pipeline (implementer → spec reviewer + adversarial reviewer in parallel → supervisor-adjudicator → fixer → re-review, per task). Lessons that transfer to running fleet campaigns:

**What worked**
- Adversarial reviewers with repro authority found what spec reviewers approved: 4 of 5 tasks got "Approved" from the spec lens while the adversarial lens returned proven BREAKS (lock races, path traversal, stdin pipe deadlock, silent hook death on spaced paths). Always run both lenses on anything that manages processes or files.
- Live smoke beats unit tests for stream-json assumptions: 340 green unit tests coexisted with three High/Medium bugs only a real haiku worker exposed (hook events land AFTER the result line; kill-dead resurrected by recompute; cost is per-invocation on --resume). Budget ~$0.10 of haiku time at the end of any campaign that touches worker plumbing.
- Supervisor-adjudicator agents (read both reviews, emit ONE binding fix list with exact semantics) kept fixers from re-interpreting findings. Fix lists anchored to function roles, not line numbers, survived concurrent refactors.
- Disjoint-file parallelism is safe (hooks + docs + core in parallel, exact-path staging, index.lock retry); same-file parallelism is not — sequence all bin/fleet.py work.

**What stalled**
- Same-file fix waves queued behind implementers repeatedly; the file-ownership handoff was the pipeline's bottleneck.
- One fixer died mid-run on an API error AFTER committing — always `git log` before re-dispatching "failed" work.
- Every fix wave introduced ~1 new issue (lock-hold sleep, unconditional re-claim); re-review after EVERY wave, no matter how small.

**Fleet-specific operational facts learned live**
- The Stop-block race is real: a `send` landing in the last seconds of a turn queues to the mailbox instead of same-turn delivery — this is by design (universal drain rule); check `idle+mail` in status, don't assume same-turn.
- `dead` is sticky (operator kill survives recompute); `respawn` is the only recovery lever. Pre-fix records persisted as idle may need a re-kill.
- Cost per worker = cost_baseline (respawn carry) + sum of result events in the current log.

**Rigorous-testing addendum (same campaign)**
- Multi-process stress found what thread-based unit tests could not: the spawn commit-lock timeout zombie only appears under real OS-process contention with real PowerShell probe latency. Any future concurrency change to fleet.py should re-run the stress harness (kept at the session scratchpad's `stress/`; the fake-claude stub must be a compiled .exe — a .cmd stub hangs under launch_turn's pipe shape).
- Fuzzing paid off at the parser layer, not the hooks: hooks survived 1000 hostile inputs untouched; the registry/cost parsers crashed on shape mismatches. Fuzz the parsers of any new event/registry field.
- `--max-budget-usd` overshoots ~3x on tiny caps — circuit breaker, not a ceiling.
- Stop-block mid-turn continuation PROVEN live: time a send after the last tool call, before Stop fires.

## 2026-07-08 — Campaign 1: haiku demo (3 workers, full lifecycle showcase)

First real end-to-end run on the finished CLI. Spawn → status → peek → mid-turn send → background wait → result → respawn → doctor → kill/clean, all green, total spend ~$0.21 haiku.

**What worked**
- Batched 3 spawns in one message; all landed in ~seconds, no lock contention.
- Mid-turn steering delivered and OBEYED: `send` to a working haiku poet ("make third haiku about the manager") queued to mailbox, consumed at next tool boundary, worker revised exactly the targeted item and confirmed in its final message. Steering prompt pattern worth reusing: prefix "Steering update from manager:" + one concrete, verifiable change.
- Task prompts ending in "Final message = X" made `result` output clean and directly consumable — haiku workers follow output-contract phrasing well.
- `fleet doctor` 13/13 PASS on first real campaign; `wt` absent is a known-fine fallback (detached PowerShell attach).

**What to know**
- `fleet` is NOT on PATH in the manager's PowerShell — call `C:\proga\claude-fleet\bin\fleet.cmd` by full path (or add bin to PATH).
- Respawn on an already-DONE task re-executes it rather than no-op'ing: respawned poet read its journal but rewrote poems.txt from scratch, losing the steered revision. Journal carries context, not idempotence — don't respawn a completed worker expecting state preservation; respawn is for stuck/long-context workers only.
- Haiku workers at these task sizes finish in under a minute — `status` right after arming `wait` often already shows idle; results can be harvested before the wait notification lands.

## 2026-07-08 — Campaign 1: SPEC v2.1 amendment pass (~15 workers, ~$60)

<!-- anchor: 2026-07-08-c1 -->
Folded every confirmed blocker/major from `docs/reviews/SPEC-REVIEW-2026-07-08.md` into
`docs/SPEC.md`, `ROADMAP.md`, and 7 stubs. Doc-only, main repo, no merge gate. Waves:
1A (4-link sequential SPEC.md chain: state→schema→testing→usagelimit) →
1B (7 parallel stub-injectors) → 1C (split adversarial review: core ∥ stubs) →
1D (7 fixes to original builders via `fleet send` + re-review + 3 LOW polish) →
1E (manager verification). Two features folded mid-campaign at Altai's request:
UL1 (usage-limit park+resume) and UL2 (worker subagents).

**Process changes — amend `knowledge/playbooks/campaign-template.md` (do these next campaign)**

1. **Descriptive-vs-prescriptive labeling in spec-amendment task files (the #1 C1 lesson).**
   Wave-1C's 3 majors all reduced to ONE root cause: the amendment folded BOTH
   already-shipped-behavior findings (DESCRIPTIVE — "bring spec to code") AND
   not-yet-built fixes (PRESCRIPTIVE — the fix is a future kernel) under a header
   claiming "no code change proposed / correct code passes." A build/verify session
   then can't tell which invariants are enforced-today vs TODO.
   **Amendment:** every spec-amendment task file must instruct the worker to tag each
   folded finding `[UNBUILT — owned by <kernel/campaign>]` when the fix is not yet in
   shipped code, and to split any "required regressions" list into "passes today" vs
   "pins unbuilt fixes." Instructing this UPFRONT would have prevented the entire 1D
   fix wave. This is the amendment to the task-file convention.

2. **Doc-adapted chain-link truth gate.** PLAN §0.1.9's truth gate assumes `pytest`;
   C1 was doc-only. Working substitute:
   (a) **anchor+witness grep per finding** — presence of the `<!-- F## -->` anchor AND
       the designated witness sentence (anchor presence alone is content-blind); and
   (b) **manager spot-checks any spec-vs-code CLAIM against `bin/fleet.py`** by grepping
       the named function anchor BEFORE ordering a fix. In C1 this confirmed CM1/CM2 were
       real before dispatch, and caught that a "code bug" complaint was actually
       correct-but-C2-deferred.
   Add this as the doc-campaign variant of the truth gate in campaign-template.md.

**Operational facts (reusable)**

- **Mid-campaign feature folding pattern:** a feature request with NO review-doc finding →
  manager authors a single binding intent note (`docs/reviews/*-INTENT-*.md`, mirroring
  §0.2.4's one-binding-input rule) and routes it through the same spec→review→fix gate as
  a real finding. Used for UL1 + UL2; both passed review clean/sound. Reusable.
- **`fleet result` crashes on Windows console (cp1252) when output contains unicode**
  (→ arrows): `'charmap' codec can't encode`. Workaround: `PYTHONIOENCODING=utf-8`.
  Real `bin/fleet.py` bug (stdout encoding), C2-worktree fix candidate — logged in
  `knowledge/projects/claude-fleet.md` (c1-playbook owns that file; cross-ref).
- **7-wide parallel disjoint-file commits: zero index.lock casualties** — confirms the
  Campaign-0 disjoint-file-parallelism lesson holds at 7 concurrent workers with
  exact-path staging + retry.
- **Cost-watch cadence worked:** `fleet wait --timeout 300` poll loop + `fleet peek`
  proxies caught no runaways; a timeout wake landing on an "essentially done, committing"
  worker just needs a short re-arm to catch completion. Note: resume turns are
  budget-UNCAPPED until `harden-fleet-b` (M5) — small doc fixes were low-risk here.
- **UL2 outcome:** worker subagents are default-on (native Task/Agent tool, no launch
  flag); ephemeral subagents don't register in `claude agents --json`, so the doctor
  check never false-positives them — C1 documentation-only, no C2 code owed.

- **UL1 + UL2 RATIFIED** by Altai at the C1 checkpoint (2026-07-08) — both approved as specced; C2 greenlit. UL1 kernel builds in C2 (item 11); UL2 was documentation-only (no C2 code owed).

## 2026-07-09 — Campaign 2: harness + hardening kernels (11 kernels, UL1, 506 tests)

<!-- anchor: 2026-07-09-c2 -->
First **code** campaign that modifies the fleet itself. Built in worktree `c2-hardening`,
merged to `fleet-impl`. Deliverable: live-integration harness (tier-3, real haiku worker)
+ 11 hardening kernels including UL1 (usage-limit park+resume) and the token-ceiling /
rotation machinery. Waves: 2A (`harness-live` tier-3 harness ∥ `harden-hooks` hook
kernels) → 2A-close gate (FLEET_LIVE hook-source=worktree) → 2B fleet.py same-file chain
a(kernels 1/2/4/5)→b(budget persistence)→c(F9 send-lock/mail-events + F15 three-way probe)
→d(token-ceiling + rotation + live demo)→e(UL1 usage-limit) → 2C reviews (code ∥
adversarial) → 2D fix wave (2 real breaks: **resume-limited double-launch HIGH**, **UL1
false-park MED**) → 2E merge gate. **506 unit/hook tests + a live tier.** ~$70 worker spend
+ ~$2 haiku. **The checkpoint claim "the fleet can safely modify itself" is EARNED — the
full revert path was exercised end-to-end (see below).**

**What worked**
- The merge-gate **revert-on-red rule fired for real and worked**: merge → post-merge gate
  RED → `git revert -m 1 <merge>` restored the known-good live install with zero downtime
  → fixed in the worktree → re-merged green. First live proof the revert lever is not
  theoretical. The known-good install stayed usable the entire time.
- Splitting 2B into a **5-link same-file chain with the per-link truth gate** (§4) kept the
  ~3000-line fleet.py rewrite from becoming one un-reviewable diff; each link ran pytest
  green in the worktree before the next dispatched.
- Dual-lens review (2C) again earned its keep: the adversarial lens found BOTH 2D breaks
  (double-launch, false-park) that the conformance lens passed.

**What stalled**
- **A one-line test-scoping bug forced a full revert+refix+re-merge.** `test_live_ceiling_demo.py`
  hard-asserted `HOOK_SOURCE == "worktree"` — correct for its pre-merge purpose, but it
  FAILED (not skipped) under the merge gate's default `FLEET_HOOK_SOURCE=main`, turning the
  post-merge gate RED. → process change #1.
- **The live harness is non-idempotent on the tracked fixture corpus.** Every `FLEET_LIVE`
  run re-captured `tests/fixtures/streams/*.jsonl`, dirtying the tree, so every git-state
  gate check needed `git checkout -- tests/fixtures/streams/` first. → process change #2.
- **Two fix turns died to Anthropic API 529 (Overloaded) mid-turn.** Worker went idle, cost
  stayed FROZEN, no commit, journal unchanged — and `fleet result` itself 529'd. "Is it
  done?" is answerable ONLY by `git log` in the worktree. → process change #3.
- **Re-merging after a reverted merge is not a plain re-merge** (git thinks the branch is
  already merged → no-op). Needs `git revert <the-revert>` then `git merge <branch>`. → #4.

**Process changes — amend `knowledge/playbooks/campaign-template.md` (realized as v1.2 amendments)**

1. **Worktree-only live demo tests MUST `pytest.skip` (not hard-assert) under the merge-gate
   default `FLEET_HOOK_SOURCE=main`** — verify collect-and-skip in the pre-merge default run.
   Added to the merge-gate checklist (§5) AND the task-file convention for any hook-source-
   specific live demo (§2). This one-line scoping miss cost a full revert cycle.
2. **Restore the committed fixture corpus (`git checkout -- tests/fixtures/streams/`) before
   every pre/post-merge git-state check** — the live harness is non-idempotent on the corpus.
   Added to §5. **Backlog (Phase-6/quality):** harness should write captured streams to a
   temp dir unless `FLEET_CAPTURE_CORPUS=1` is set, so verification runs stop mutating the
   tracked corpus.
3. **A worker turn is "done" only if `git log` in its worktree shows the expected commit** —
   `fleet result`/`cost_usd` are unreliable when the turn errored (529/API). Re-sending a
   git-committed fix task is safe; revert any partial uncommitted artifacts (e.g. dirtied
   fixtures) before re-send. Added to the §3(g) verification checkpoint.
4. **Re-merge after a reverted merge = `git revert <the-revert>` then `git merge <branch>`**
   (revert-the-revert restores the reverted code; the plain merge then picks up the new fix
   commit; a bare re-merge is a no-op). Documented as a merge-gate revert-path sequence in §5.

**Operational facts (reusable)**
- The **`fleet result`/`peek` cp1252 unicode crash (from C1) is STILL live** — C2 did not fix
  it (out of scope). Keep the `PYTHONIOENCODING=utf-8` workaround (see projects/claude-fleet.md).
- **New standing post-merge live checks:** FLEET_LIVE integration tier (default=main hooks),
  `fleet init` re-render when the template changes (PostCompact hook was added), `fleet doctor`
  gained hook-registration / unreadable-starttime / limited-parks / ceiling-file-sweep /
  hook-errors checks, and live hook-smoke.
- **New CLI surface:** `fleet resume-limited`; `--token-ceiling` on spawn/respawn;
  `over_budget` / `over_ceiling` / `limited` statuses; spawn-time model echo.

## 2026-07-09 — External dogfood #1: `stupidbox` (first non-fleet campaign, soak fuel)

<!-- anchor: 2026-07-09-dogfood-stupidbox -->
First real external campaign: built a throwaway useless CLI (`C:\proga\stupidbox`) from
scratch with the fleet. Altai's steer mid-session: not the polymarket repo — "make
something simple and stupid." 5 workers + 2 respawns, all haiku/`bypass`, ~$0.5 total.
Wave 1: 4 module workers in parallel on disjoint files (`cow`/`fortune`/`roll`/`hodor`).
Wave 2: 1 README worker, respawned twice. Full lifecycle exercised: batch spawn,
mid-turn steer, respawn, background waits, manager verification, doctor-clean close.
See `knowledge/projects/stupidbox.md`.

**VERDICT — fleet works in the wild (2026-07-09).** This was the first campaign on a
project the fleet did not build and whose repo it had never seen. It ran end-to-end with
no manual intervention: 11 spawns + 2 respawns, 8 shipped commands, every worker committed
its own disjoint file, zero `index.lock` collisions, zero lost turns, zero incidents,
`fleet doctor` 17/17 at every close. **The tool is usable for real day-to-day work, not
just self-build.** What remains before Soak Gate 1 is *not* capability — it is the
usage floor (≥15 spawns across ≥3 distinct days) and Altai's signature. Nothing observed
in this campaign argues against the gate; the only defects found were ergonomic (respawn
task-snapshot staleness) and both had documented workarounds.

**What worked**
- **Dispatcher-first scaffold = clean N-wide parallelism.** Manager writes
  `__main__.py` referencing all command names upfront (lazy import + "not built yet"
  fallback); each worker owns exactly one module file. Zero shared-file contention;
  4 concurrent commits, zero `index.lock`. Reusable pattern for "build N independent
  things in parallel in a fresh repo."
- **Mid-turn steer landed and was obeyed again** (`cow` got a `--think` thought-bubble
  flag added mid-turn; worker also bumped its own self-test count to 3/3). Steering
  prompt pattern "Steering update from manager: <one concrete verifiable change>" holds.
- **Haiku on tiny tasks is ~free** ($0.09–0.13/worker); `bypass` correct for a throwaway
  repo with no network/secrets/processes.

**What stalled / friction found (the process change)**
- **`fleet respawn <name>` IGNORES edits to `state/tasks/<name>.md`.** Verified against
  `cmd_respawn` (bin/fleet.py:3029): respawn re-prompts with the **original task snapshot
  stored in the registry (TRUNCATED per schema), or a `--task` override** — it does NOT
  re-read the task file. I edited the readme task file (added banner + Philosophy section)
  and a plain `respawn` silently regenerated the OLD scope. Passing
  `fleet respawn sb-readme --task @state/tasks/sb-readme.md --force` picked up the edit
  correctly (and confirms respawn `--task` DOES accept `@file` expansion).
  → **process change (campaign-template §3f + respawn note): to change a worker's scope on
  respawn, always re-pass `--task @file`; never edit the task file expecting respawn to see
  it. For any long `@file` task, re-pass `--task @file` on respawn anyway — the registry
  stores the task TRUNCATED, so a bare respawn can lose task detail.**

**Operational facts (reusable)**
- **The single system-wide fleet install means a concurrent foreign campaign shows up in
  your `status`/`doctor`.** Mid-close, two workers I did not spawn (`plan3-t2-rtds`,
  `plan3-t3-resolver`) appeared — a separate live pmbot Rust-TDD campaign in isolated
  worktrees (`C:\proga\pmbot-wt-*`). Not a bug; doctor stayed 17/17. **A manager must
  distinguish own-workers from foreign ones by name-prefix/dir before any bulk
  `kill`/`clean`** — never blanket-retire the registry. Retire only names you spawned.
- **Soak Gate 1 usage — Day 1 (2026-07-09):** two waves on `stupidbox` (built an 8-command
  useless CLI): **12 launches total** (11 spawns + 2 respawns; sb-cow/fortune/roll/hodor +
  sb-readme×3 launches, then sb2-8ball/yoda/slap/mock + sb2-readme). Doctor 17/17 clean at
  every close, 0 incidents. Also coexisted cleanly with a concurrent foreign campaign
  (pmbot Campaign 3) that ran and retired in the shared install during the session. Need
  ≥15 spawns across **≥3 distinct days**; this is day 1 of 3. (Sign-off stays Altai's — this
  only accrues the floor; a single busy day cannot satisfy the ≥3-distinct-days requirement.)

## 2026-07-09-c3 — Campaign 3 (pmbot Plan-3, foreign manager: parallel Rust TDD via worktrees)

A separate manager session (the pmbot dev) used the shared fleet to run 2 Plan-3 Rust TDD
tasks in PARALLEL, each in its own **git worktree** of `polymarket_experimenting`, then merged
back. This is the reusable pattern for parallelizing collision-prone tasks (shared `main.rs`
etc.): `git worktree add -b <br> ../wt HEAD` per task → `fleet spawn --dir <wt> --mode bypass`
→ `fleet wait --all` (background) → review → merge → `git worktree remove` + `branch -d` + `kill`.

- **What worked:** both workers green first turn (6 + 5 tests), ~$1.7 each (cold Rust build
  dominates, not tokens). Both used their OWN subagents to read the Python source and confirm a
  byte-for-byte port; an independent reviewer agent agreed (0 findings). Merge: one ff + one clean
  3-way auto-merge on `main.rs`. Merged-trunk re-verify: 86 tests, clippy clean.
- **`bypass` mode fit:** trusted known repo + TDD + cargo/git only → zero permission friction,
  correct choice. Budget $6/worker was right for cold builds.
- **Worker judgment win:** the "don't touch main.rs" instruction was correctly overridden by the
  worker when adding an enum variant forced a no-op `match` arm (compile necessity). Task files
  should anticipate this rather than forbid it.
- **New project file:** `knowledge/projects/pmbot.md` (per-crate cargo, frozen kernel, collector.db
  rule, worktree recipe, cold-build cost).
- **Shared-fleet etiquette confirmed from the other side:** two managers ran concurrently on one
  install with zero interference because each retired only its own name-prefixed workers
  (`plan3-*` vs `sb-*`). The name-prefix discipline is load-bearing — hold it.

## 2026-07-09-c4 — Campaign 4 (pmbot Plan 3 complete: 5 workers, ~$22, safety-critical Rust)

Finished a 12-task safety-critical plan (live-order kill-switch for a real-money trading bot) using
worktree-per-task fleet workers + adversarial in-session reviewers. All merged; 121 + 35 tests green.

**The headline lesson: builders build, adversaries find. Separate the roles.**
Five real bugs shipped past green tests AND past a prior code review. Every single one was caught by an
*adversarial reviewer with repro authority* or by a worker whose task forced it down a new code path —
never by the builder, never by the suite:
- `LiveClob::submit` hardcoded `side=Buy`, ignoring the order's side. Survived 75 tests + a whole-branch
  opus review because nothing in the codebase ever *sold*. Found only when a new worker needed a sell.
- The dead-man switch self-tripped at boot and latched dead (a permanent no-op) — its own unit tests all
  called `on_beat` before polling, so none could see it.
- An affordability guard the plan called "the only bound" ignored cost committed in other open windows.
- Fixing (2) then introduced a *false-negative* twin. Knife-edge fixes create knife-edge bugs.

**Fault-inject your tests or they are theater.** The strongest evidence produced all campaign: a reviewer
BROKE production four ways and confirmed each break turned the relevant test red. Add this to every
review brief for safety-critical code: *"break the production behavior N ways; report any test that stays
green."* A test that stays green when you break what it tests is a CRITICAL finding. This converted "the
drill passes" into "the drill is evidence."

**Prompt patterns that worked (reuse verbatim):**
- Reviewer brief opens with the project's own base rate: *"every prior fix wave introduced ~1 new issue;
  assume this one did; find it."* A generic "review this" reviewer returned a bare "No issues" on a diff
  that provably contained a bug. Hostile framing + repro authority + "no bare 'No issues', say so
  per-item" produced 4 real findings.
- Worker briefs that name the TRAP explicitly ("caps are frozen at construction while bankroll shrinks —
  do NOT rebuild the governor mid-flight, it discards open-window exposure") got it right first try.
- Worker briefs must say *"the plan's snippets are indicative, not authoritative — read the real type
  definitions"* whenever the plan touches an external SDK. Both SDK-facing workers found the plan wrong.
- Tell workers to dispatch their OWN subagents to read the source-of-truth file before porting/writing.
  Cheap, and it made ports byte-accurate on the first attempt.

**Worker judgment is real.** A worker told "do not touch main.rs" correctly overrode that when adding an
enum variant forced a new `match` arm. Another rejected the plan's own field semantics after checking a
live API. Write briefs with intent + invariants, not just prohibitions.

**Ops:** `fleet result` still truncates long outputs even with `PYTHONIOENCODING=utf-8` — for anything
substantive, read the worker's commits (`git log`/`git show` in its worktree) instead of `result`. And an
API-529 death mid-turn AFTER commits is invisible from `result`; `git log` is the only truth a turn landed
(Campaign 0 said this; it happened again, exactly as predicted).

## 2026-07-09 — a read-only slash command deleted five workers

**What happened.** `commands/status.md` shipped with `allowed-tools: 'Bash(fleet:*)'`. That glob matches
`fleet kill` and `fleet clean`, not just `fleet status`. A throwaway `claude -p "/fleet:status"` probe run
during the Phase-1.6 build saw four dead workers, judged them untidy, and — entirely within the permissions
we granted it — killed the one `working` worker and cleaned all five, deleting their journals and logs.
Recovered from `state/events.jsonl`: session ids are durable, so transcripts survive `fleet clean`.

**The lesson is not "models are reckless."** The model did exactly what it was permitted to do, and it
volunteered the cleanup because our own `status.md` prose mentioned dead workers. The lesson is that a
permission glob is a capability grant, and `Bash(fleet:*)` grants the destructive half of the CLI to a
command whose whole purpose is to be read-only.

- **Grant the subcommand, never the CLI.** `Bash(fleet status:*)`, not `Bash(fleet:*)`. Pinned by
  `tests/test_terminal_surface.py::TestCommandFiles::test_read_only_grants_reach_no_destructive_subcommand`.
- **`fleet clean` is irreversible and journals are the only record of what a worker learned.** The registry
  entry, logs and journal go; only the claude session survives, resumable by sid from `events.jsonl`.
- **Two guards are not one guard.** We had already ruled that mutating commands must not use inline `` !`cmd` ``
  exec (spec D3). That guard was intact. The allowlist on the *read-only* commands let the same destructive
  capability in through the back door. When you write a rule about one mechanism, check whether the other
  mechanism reaching the same capability is still open.
- **`events.jsonl` is the recovery path.** It is append-only and `fleet clean` does not touch it. Every
  `spawned`/`respawned` event carries `session_id` + `cwd`, which is enough to `claude --resume` a swept
  worker. Do not let anything trim it.

### Follow-up: the CLI-level guard (same day)

Narrowing `allowed-tools` fixed the one command. It did not fix the class. Two more holes were open:

- **`.claude/settings.local.json` in this repo sets `"defaultMode": "bypassPermissions"`.** Every Claude
  session working in `C:\proga\claude-fleet` — which is exactly where a fleet manager runs — skips all
  permission prompts. A narrowed allowlist protects nothing there. The permission layer is not a safety
  layer for the tool that lives inside the bypassed directory.
- **`fleet.py` had no confirmation anywhere.** No `--yes`, no ownership, no record of who spawned what.

Fixed by provenance: `spawned_by` records the spawning `CLAUDE_CODE_SESSION_ID`; `kill`/`clean`/`respawn`
refuse a foreign worker without `--yes`; an unknown owner counts as foreign (fail toward asking); and
respawn carries ownership forward so `respawn --force` + `kill` cannot launder it. Worker turns strip the
inherited `CLAUDE_CODE_SESSION_ID`, or a worker would look exactly like its manager. Verified against a
real `bypassPermissions` haiku session ordered to run `fleet clean`: refused, worker survived.

**Two Windows traps found while building it.**
- `sys.stdin.isatty()` is **not** an interactivity test under Git Bash: `/dev/null` maps to `NUL`, a
  character device, so `fleet kill x < /dev/null` reports a tty, `input()` then hits EOF, and the operator
  gets a traceback instead of a refusal. The guard now never prompts — agents pass `--yes`.
- pytest inherits `CLAUDE_CODE_SESSION_ID` from whichever Claude session ran it, so guard-sensitive tests
  passed or failed depending on **who ran the tests**. An autouse fixture in `conftest.py` deletes it.

### The same silent-failure class, four more times (2026-07-09, later)

A sweep for "things shaped like the `Bash(fleet:*)` incident" found four. Every one produced *no error*:

- **The test suite overwrote the operator's real `~/.claude/fleet-home`.** `cmd_init` stamps the marker via
  `Path.home()`; the statusline tests monkeypatched `user_settings_path` but not the marker. Running the
  suite repointed the SessionStart hook at a pytest tmp dir. The briefing would have reported an empty
  fleet forever. Fixed with an autouse conftest fixture that sandboxes every home-derived path, plus a test
  asserting `fleet init` never reaches the real home. **Rule: a test that writes to `Path.home()` is a bug,
  even when the assertion passes.**
- **`/fleet` never ran.** The plugin is named `fleet` and ships `skills/fleet/SKILL.md`, so `/fleet` invoked
  the SKILL and `commands/fleet.md` was permanently unreachable. Renamed `/fleet:overview`. A command file
  may not collide with the skill name; lint added.
- **A slash command's inline `` !`cmd` `` is not guaranteed to be bash.** `/fleet` inlined
  `${FLEET_HOME:-$(cat ~/.claude/fleet-home)}` and printed garbage. Shell logic belongs in the CLI:
  `fleet home` and `fleet knowledge` now exist, are testable, and are shell-agnostic.
- **cp1252, for the third time.** `fleet knowledge` printed a knowledge base full of arrows and em-dashes to
  a Windows console and `print()` raised mid-stream. There is now one helper,
  `_write_text_tolerating_console_encoding`. **Any new stdout path on Windows needs it.**

**Meta-lesson.** Every one of these was found by *running the thing*, never by reading it or by a green test
suite. The statusline was blank, `/fleet` answered nonsense, the marker pointed at a deleted directory — all
while 700 tests passed. Drive the surface you just built, from a clean directory, as the user.

## 2026-07-10 — C4 spec wave (portability): the adversarial loop earned its keep, then hit a wall

<!-- anchor: 2026-07-10-c4-spec-portability -->

Docs-only campaign, 4 workers, ~$36, 6 commits. `docs/specs/portability.md` stub → drafting →
2 adversarial reviews → 2 fix waves → **ESCALATED, still `drafting`.** Not a failure: the loop
did exactly what it exists to do, and stopped where doctrine says stop.

**The headline: every single review found real, blocking defects in work that looked finished.**
- Author declared its own spec `ready-for-build`. Review 1: **1 CRITICAL, 7 HIGH, 7 MED, 4 LOW.**
- Fix wave 1 claimed CRITICAL+7/7 HIGH fixed, disputed nothing. Re-review: **17/19 fixed, F2
  NOT-FIXED, F1 REGRESSED, 5 new regressions.**
- Fix wave 2 claimed R1 fixed + 4/4. Re-review 2: **R1 NOT-FIXED, new CRITICAL + 2 HIGH.** Escalate.

**PROCESS CHANGE #1 — an author may not promote its own spec.** `spec-portability` set
`Status: ready-for-build` on the spec it had just written; the manager reverted it (87a85de) before
the reviewer saw it. A spec cannot ratify itself. Put the promotion authority in the REVIEWER's task
file, put "leave Status at drafting" in the author's, and check the Status line after every author
turn. It tried once and never again once the constraint was explicit.

**PROCESS CHANGE #2 — the failure mode of a fix wave is a NEW defect one call site away.** Both
waves fixed their target and broke something adjacent, identically: a correct mechanism specified
against a call-site list built by *inspection* instead of by `grep`. The escalation trigger is not
"the fix is wrong" but "the fix is right and the enumeration is short, twice." Fix-wave briefs must
demand: *enumerate every consumer by grep, paste the grep, then specify.*

**PROCESS CHANGE #3 — `DISPUTED: none` across 19 findings is a smell, not a virtue.** The fix brief
explicitly invited evidence-backed dispute; the author disputed nothing. So the re-review was told to
hunt `SPURIOUS-FIX` (a "fix" to something never broken — it bakes the reviewer's error into the
contract). Verdict: none found, every finding was real. Worth the check anyway; add `SPURIOUS-FIX`
to every re-review's required verdict vocabulary.

**The technical lesson (reusable, and expensive to learn): a probe's ctime representation is a
correctness surface, and every candidate fails differently.**
1. `time.time() - /proc/uptime + starttime/CLK_TCK` → mixes CLOCK_REALTIME (NTP-steppable) with a
   monotonic quantity. An NTP step of S shifts every later probe by S while the kernel's `starttime`
   never moves → false `gone` → `respawn` **double-launches** in the worker's cwd.
2. Synthetic 1970-epoch from raw boot-relative ticks → immune to NTP by construction, and the
   difference-only premise genuinely holds (`turn_pid_ctime` is consumed ONLY by
   `pid_alive`/`probe_liveness`, never rendered, never wall-clock-compared — grepped twice,
   independently). But boot-relative ticks carry **no boot identity**: the collision condition
   becomes "started within 2s of the same *boot offset*", which **every reboot recreates**.
   Measured on WSL (manager + reviewer, separately): the entire userspace boot spans 1.4-2.3s at
   `CLK_TCK=100`, i.e. inside ONE ±2s window. And ROADMAP Phase 2's logon-triggered manager spawns
   workers *inside that boot burst*. Failure direction inverted to false **`alive`**, which is worse:
   `_interrupt_worker` trusts "alive" and `killpg`s a live, unrelated process group fleet doesn't own.
3. `/proc/stat`'s `btime` → also REALTIME-derived; moves under a step. Correctly rejected.
4. boot_id gate (`/proc/sys/kernel/random/boot_id`) before the tick compare → the right mechanism,
   but the spec's "stored boot_id is null → alive-unknown" rule fires **at launch**, where by
   definition no stored boot_id exists: `launch_turn` (`:1343-1350`) → sentinel `("claude", None)`
   → `ctime_to_iso(None)` → `AttributeError` → swallowed by a bare `except` → `turn_pid_ctime=null`
   → `probe_liveness`'s first branch (`:620`) returns `"gone"`. **Every Linux worker born dead.**

**"Vanishingly unlikely" is a claim requiring evidence, not a rhetorical move.** Fix wave 1 called
the cross-reboot collision "the same class" as the existing accepted PID-reuse residual. It is not:
the existing one needs a coincidence in a 4s window of real time that lies in the irrecoverable past
(measure-zero, never recurs); the new one recurs *every boot*, and boot is where tick density peaks.
The estimate also multiplied two probabilities that are **positively correlated** — Linux resets the
PID counter and the tick origin at the same boot, driven by the same deterministic sequence.

**Ops facts**
- A worker over its `max_budget_usd` ceiling refuses `send` (worker-level, cumulative). Use
  `respawn --task @file --max-budget-usd <higher>` — the documented context-reset lever, journal
  survives. Re-passing `--task @file` remains mandatory (registry stores it TRUNCATED).
- WSL Ubuntu exists on this box and is real repro authority for Linux claims. Both reviewers used it;
  the manager independently reproduced the boot-density scan rather than trust the transcript.
  **Grant it explicitly in the task file** — the spec author didn't know it had WSL in wave 1 and
  correctly tagged claims `[UNVERIFIED]` instead of inventing results. Zero fabricated experiments
  across 4 workers, verified by a dedicated fabrication-audit pass.
- Manager spot-checks paid for themselves every single time: `.gitattributes` already existed (the
  spec called it a new file and would have deleted the `*.sh text eol=lf` rule that keeps CRLF from
  silently killing POSIX hooks); `os.killpg` is absent on Windows (import-time `AttributeError`);
  `TestPlatformAdapterBoundary` has 13 tests, not 11. Never merge a spec claim about code you have
  not grepped.

**Open, for Altai (nothing below is the manager's to decide):**
1. **`PLAN.md` is wrong in two places.** Its `port-test-suite` bullet demands
   `TestPlatformAdapterBoundary` stay "untouched and green", but 9 of its 13 tests hardcode
   `DETACHED_PROCESS`/`taskkill`/`wt` and cannot pass on POSIX; only the 2 source-scan lint tests are
   OS-independent. And its "interpreter path decision" task already shipped (`cmd_init` renders
   `{{PYTHON}}` from `sys.executable`, `:2242`). The contract needs amending or an override.
2. **`turn_pid_boot_id`** — an additive registry field, proposed, not applied. Owner listed as
   `port-adapter-a`, but it edits `recompute_status`, `_interrupt_worker` (×2), `pid_alive`,
   `probe_liveness`, and TWO doctor checks — that is **core**, not the adapter, and may violate the
   invariant-8 boundary this phase exists to enforce.
3. **The reviewer's structural recommendation:** adopt FW2-R1's `boot_identity()` restructuring
   (compare inside `probe_liveness`; no production parameter on `get_process_info`), which cuts the
   core-edit list from "five call sites, two adapter classes, every test double" to "one adapter
   method, one stamp in `launch_turn`, one compare in `probe_liveness`" — and re-scope boot identity
   into a short **SPEC.md-owned decision** rather than a residual clause inside a portability row.
   A portability spec should not be specifying core plumbing.

### 2026-07-10 — C4 spec wave, CLOSED (supersedes the escalation entry above)

The escalation resolved. Altai ratified two decisions: amend `PLAN.md`; re-scope boot identity out
of the portability spec into a SPEC.md decision. Both executed. **Final state: `SPEC.md` v2.2 + F33
ratified; `docs/specs/portability.md` = `ready-for-build`; zero code touched; 708 tests green.**
7 workers, ~$80, 12 commits.

**THE LESSON, and it cost the whole campaign to learn: an enumeration produced by inspection is
wrong. Five times, in five different artifacts, by five different actors.**

1. **Fix wave 1** — call-site list by inspection → F1 REGRESSED (false-`gone` → double-launch).
2. **Fix wave 2** — again → FW2-R1 CRITICAL: the null-boot_id rule fires at `launch_turn`, where no
   stored boot_id can exist by definition → `ctime_to_iso(None)` → swallowed `AttributeError` →
   `turn_pid_ctime=null` → `probe_liveness:620` returns `"gone"`. **Every Linux worker born dead.**
3. **`PLAN.md` itself** — the ratified "one adapter method, one stamp in `launch_turn`, one compare"
   was short by 3 sites. `launch_turn` doesn't write the registry; it RETURNS a dict that four commit
   sites copy (`:2346,:2898,:2993,:3733`). Written by a reviewer, ratified by Altai, believed by the
   manager. **The true list is 11 rows.** Caught only because that same bullet mandated grep receipts.
4. **A LOW too small to grep** — a review finding asserted 3 fields were `[UNBUILT]`; the author
   implemented it without checking. `limit_reset_at`/`limit_kind` SHIP (18 refs in `fleet.py`, 41 in
   tests). SPEC.md briefly declared shipped code unbuilt — **F20's exact drift, reintroduced by the
   paragraph asserting F20 must never recur.** The reviewer found it and owned it: *"That false
   premise was mine — I wrote 'three unbuilt fields' without grepping."*
5. **The manager's own correction sweep** — fixed the 1 named line, left **7 false `[UNBUILT]` tags**
   standing elsewhere. They had been in `SPEC.md` since 2026-07-08: C2 built `harden-fleet-b/-d/-e`
   (budget persistence, rotation retry, UL1) and nobody re-tagged. A `port-adapter-a` builder reading
   §12 would have rebuilt four working features.

Every one was invisible to careful reading — by two adversarial reviewers, and by me. Every one took
a single `grep` to find. → **campaign-template v1.4: the GREP-RECEIPT GATE.**

**Corollaries now in the template**
- `[UNBUILT]` claims must reproduce as grep-no-matches at a stated commit, or they are false.
- **Audit the prose, not just the tags.** `grep "[UNBUILT"` misses a *sentence* claiming a field is
  prescriptive — which is how the `:3` Status header carried the false claim invisibly. Grep
  `PRESCRIPTIVE`, `not shipped`, lowercase `unbuilt` too.
- Retire a stale pin by **moving** it (§12 "pins unbuilt" → "passes today"), never deleting it. A
  deleted pin is a silent regression wearing a cleanup's clothes.
- A fix wave's failure mode is a new defect **one call site away**. Never merge a fix wave on the
  author's own report; budget a re-review for each.
- **ESCALATE beats a third fix wave.** Two waves each closing their target and breaking a neighbour
  = the defect is structural. Here: a *portability* spec was specifying *core* plumbing, and the
  plumbing kept growing. The fix was a re-scope, not a third finding list.

**Authority discipline (new, and it held under pressure)**
- **No author promotes its own spec.** One tried (`cd63dcf`); manager reverted (`87a85de`). The rule
  then bound the manager: having authored the `92e8a44` correction, the manager spawned a fresh
  verifier rather than self-certify — and that verifier **refused to promote**, catching the 7 tags.
  The rule is only real when it binds the person holding it.
- **`SPURIOUS-FIX` is now a required re-review verdict.** `DISPUTED: none` across 19 findings is a
  smell. (Checked: none found; all 19 real. Still worth checking.)
- **Dispute-with-evidence is the behavior to select for.** `spec-boot-identity` overturned the
  ratified contract with pasted greps. That is worth more than a compliant worker.

**Technical residue (the probe ctime is a correctness surface)**
- `time.time() - /proc/uptime + ticks` mixes CLOCK_REALTIME with monotonic → NTP step → false-`gone`
  → **double-launch**.
- Raw boot-relative ticks → immune to NTP, but carry **no boot identity**; the collision recurs every
  boot and boot is where tick density peaks (WSL: whole userspace boot spans 1.4–2.3s at CLK_TCK=100,
  inside ONE ±2s window; ROADMAP Phase-2's logon manager spawns *inside* that burst). Direction
  inverts to false-`alive` → `_interrupt_worker` **`killpg`s a live, unrelated process group**. Worse.
- `/proc/stat` `btime` is REALTIME-derived too. Rejected.
- Answer: `/proc/sys/kernel/random/boot_id`, compared **before** the tick compare; mismatch = positive
  proof of reboot → reuse the existing `None` wire shape (`probe_liveness` already maps it to `gone`).
  The discriminator is a **fresh read at probe time**, never the stored value — a stored `null` is
  *normal* on Windows/macOS and *legacy* on Linux, and conflating those is what killed fix wave 2.
- `launch_turn`: hoist the boot-id read **above** the `Popen` at `:1288` and wrap it. The hoist (not
  the wrapper) is what makes an orphaned live billable `claude` impossible — no child exists yet.

**Ops**
- A worker over its cumulative `max_budget_usd` refuses `send`; use `respawn --task @file
  --max-budget-usd <higher>` (journal survives; the registry stores the task TRUNCATED, so re-pass it).
- A transient **403** killed a turn mid-flight exactly like the C4 **529** did: `fleet result`
  returned the auth error as the worker's "answer," `cost_usd` froze, **zero commits landed**.
  `git log` remains the only truth a turn landed. The lesson generalizes past overload errors.

## 2026-07-14 — M-0 native-substrate spike (12 SDD tasks, 13 gates, ~$? in subagents, zero fleet workers)

Substrate verdicts (contract: `docs/specs/native-substrate.md` — the law for M-A/M-B):
- **Hooks fire inside `claude --bg` sessions** (G1) — the pivot lives. Env propagates, provenance strip survives (G4).
- **Steering an idle bg session = fork-with-transcript** (`--bg --resume` mints a NEW sid carrying the whole conversation; `-p --resume` rejected). RATIFIED: every steer is a re-dispatch + overlay restamp + fresh `-n`.
- **Print-only flags die under `--bg`**: no stream-json logs, no `--max-budget-usd`. Result = Stop payload `last_assistant_message` (value-shape feature-detect) + transcript tokens; USD is fleet-computed.
- **Usage-limit walls are SILENT** (G11, pinned by a live 429 mid-spike): no Stop hook, roster looks healthy-idle, no native auto-resume (the observed "recovery" was the operator peek+replying). Detection must ride the idle-no-outcome-record investigation path scanning transcript tails.
- **`claude stop` fires NO Stop hook** → fleet writes its own tombstone on kill/interrupt. **Raw taskkill → daemon silently respawns same sid ~30 s** — never-raw-kill is now machine-verified. `claude rm` = clean archival primitive.
- **~1 h reap = process stop, not roster eviction** (primary doc quote); done sessions sit in the roster for hours. Live-idle process-reap UNOBSERVED. No pin CLI (TUI Ctrl+T only).
- **Big prompts**: argv dies at CreateProcess (>32k), stdin dispatch WEDGES the session silently — task-file bootstrap is the only channel. `-n` carries emoji/pipes/120 chars intact; ai-title clobbers names only on the fork path. `startedAt` jitters across liveness transitions — key nothing on it.
- **ScheduleWakeup heartbeats work** in bg sessions (~3 min cadence proven); scheduler dies with `claude stop`, no zombie wakeups.

Process lessons:
- **Evidence-discipline reviews caught overclaims in 5 of 8 experiment tasks** ("permanent" wedge from a 171 s window; "matches criteria exactly" over an unobserved sub-criterion; "daemon did it" when the record said human-typed; beat-count arithmetic 26 vs 17; an unsourced doc quote). Hostile per-task review of EVIDENCE (not just code) pays exactly like C4's grep-receipt gate.
- **Controller-side research must land in repo files before anything cites it** — an explore-agent's finding cited as "the docs-lane" was untraceable to any artifact and burned a fix wave. Save reports to disk first.
- **Natural occurrences are data**: a live 429 answered G11 for free; the operator's agents-menu poke was an uncontrolled variable that first masqueraded as a daemon capability. In daemon experiments, log or ask about operator actions before attributing causes.
- **A subagent's transcript can vanish** (T8 original lost to an API error); the ledger + committed artifacts were sufficient to hand the task to a finisher. Checkpoint discipline works.

## 2026-07-14-mA — M-A supervisor identity (first full subagent-driven code milestone, plan + 7 tasks, ~14 subagents)

- **Plan-embedded verbatim code = cheap implementers.** Tasks whose plan text contained complete code ran on haiku as transcription+testing; only wiring-judgment tasks (boot ritual, handoff, hook edit) needed sonnet. All 7 tasks landed first-dispatch, zero BLOCKED.
- **Reviewer mutation-repro beats controller instinct.** Controller ordered "keep `>=`" on the heartbeat-refresh assertion; reviewer's mutation test proved `>=` stays green when the refresh silently stops. Reversed to strict `>`. Rule: when a reviewer reproduces, the repro wins the adjudication.
- **Shared-fixture edits silently reroute earlier tests' code paths.** Seeding `state/fleet.json` in the shared fixture (to unblock one hook test) moved every TestSupBoot test off the "registry unreadable" render branch — no assertion broke, coverage just vanished. Caught only because the reviewer audited incidental path coverage, not assertions. Rule: fixture changes get the same adversarial scrutiny as code; seed per-test.
- **The whole-branch review earns its cost on cross-task classes.** Per-task reviews (rigorous, repro-armed) structurally missed: journal header-injection via checkpoint bodies; the dispatch-failure path missing spec §4's doctor flag; and the fall-through claim branch (foreign-but-stale checkpoint → seize) being both untested and the NORMAL recovery path after any first handoff — a "refuse on foreign inc" refactor would have bricked resurrection with a green suite.
- **Deliberate timeout hierarchy, name it in the doc**: handoff abort window (T=300s) < successor self-orphan backstop (600s) so the old side always adjudicates before the successor gives up. Reviewer flagged it as an inconsistency; it's load-bearing ordering — a code comment/doc line saying so would have saved a review round.
- Design verdict (fable whole-branch review): single-supervisor invariant holds by construction — all claim mutations behind one fleet_lock with re-read-inside-lock, atomic os.replace state files for lock-free views, journal writes only via new-holder path or _require_claim_holder; every adversarial race collapses to refuse/freeze, never a second claim.
- Ops: 4 fix waves total, all one-round; SendMessage-resume of the same implementer/reviewer agents kept fix context cheap (no re-briefing); final fix wave = ONE subagent with the full findings list.

## 2026-07-16 — M-B native dispatch (12 tasks + final wave, hybrid pipeline: fleet workers implement, subagent review pairs gate)

**THE lesson — live-smoke-beats-unit-tests, third confirmation, strongest yet: the FLEET_LIVE pin suite caught 3 CRITICAL production bugs invisible to 1,162 unit tests and 11 adversarial review pairs.** (1) task-file bootstrap outside worker cwd → permission-prompt hang under every non-bypass mode (campaign never saw it — all workers ran bypass; fix `--add-dir`); (2) `claude stop`/`rm` take the SHORT id, not the full sid — every native interrupt/kill/archive silently no-oped on the real session while the registry reported success (fix `_native_job_ref` = first hyphen segment + retry-full); (3) FORCE_COLOR in the dispatching env colorizes `--bg` stdout even when piped → ANSI swallowed into the parsed short id → every roster join spins to false-DOA (fix: strip CSI before parse). Env-sensitive subprocess-stdout parsing is a standing hazard class.

**Plan snippets marked "verbatim-binding" transfer the author's bugs into code.** 3 of the first 3 tasks shipped brief-inherited defects (ValueError landmine, dropped `_valid_token` parity, wrong error type). Mid-campaign process change: snippets demoted to indicative, prose contract governs, deviations reported — defect class vanished. Confirms C4's "plan snippets are indicative" for OWN plans, not just SDK docs.

**A fix wave's failure mode replayed exactly as C4 predicted — and fresh-eyes-on-the-fix caught it.** T7 wave 1 fixed 3 real breaks and minted a NEW Critical (stale-working label mistaken for in-flight steer). Every re-review prompt must include "new-defect hunt on the fix itself"; it fired twice more (T9 reorder scrutiny, T12 fixture renames).

**Review-pair economics: ~15 Criticals killed pre-merge across 12 tasks** (concurrency record loss incl. the empirical fact that Windows CRT O_APPEND is NOT atomic — CreateFileW FILE_APPEND_DATA is; completed-task rollback; tombstone-laundering kill→idle; steer double-fork; interrupt orphaning limited parks; live-retired-sid rm; archive clobber of concurrent steer; doctor runner crash-silence; locked-transcript crash of fleet status; stale-429 false park). Hostile framing + named traps + repro/fault-inject duty stays mandatory. Fault-injection exposed test-theater twice (tests that stayed green with production broken).

**Dogfood loop closed hard: workers were dispatched via the substrate they were building** — first native spawn at T5, result arriving via the Stop-hook outcome record built in T1–T2; the discriminator's first production sweep resolved the campaign's own 11 workers. Ops facts: outcome-record file polling beats `fleet wait` during substrate transitions; idle bg processes hold worktree cwds (~1h daemon reap) — defer prunes; live tier's temp-home `fleet init` clobbered the real `~/.claude/fleet-home` marker (isolate the marker in live tests — open defect); pin suite must run per `claude` version bump (drifted 2.1.207→211 during the campaign alone; doctor pin-gate now enforces).

**Reviewer-adjudicates-from-reality beats trusting the dispatcher:** two of my own contract lines were wrong (clean sweeping idle; "as today's semantics") — reviewers instructed to verify against pre-diff code caught both. Dispatcher error is a finding class; name it in reviewer prompts.

M-C inputs recorded in docs/NEXT-SESSION.md + .superpowers/sdd/final-review.md (S4 limited double-resume w/ mitigation, S6/S7/S8 accepted-documented, r-is-None false-success print, marker-clobber fix, README Status re-word after soak).

## 2026-07-17 — M-C: deletion + autoclean + SPEC v3 (pivot COMPLETE) {#2026-07-17-mc}

**Campaign shape:** 6 fleet workers (mc-debt/autoclean/docs/delete/spec + pinfix waves on the autoclean worker), ~10 subagent reviewers (adversarial+spec pairs, fresh-context re-reviewers), 3 merged milestones pushed to main same-day. fleet.py 9345→7378 lines; tests 1162→1054 (+~300 native regressions written, ~280 legacy tests died with their code). Legacy substrate fully deleted (§6): detached-Popen, probe_liveness/ctime, PID registry fields, stdout log pipeline, refuse_if_legacy — every class grep-receipted 0-or-justified.

**THE lesson (7th live-tier confirmation, now with a twist):** pin suite went RED on a merged, review-clean, 1278-unit-test-green tree — root cause was neither the merge nor drift but a **startup transient in the daemon roster**: a fresh `--bg` entry carries `state` only (no `status`/`pid`) for its first seconds; the contract's "state-only = dead" rule verdicted healthy newborns dead-suspected and `fleet wait` returned instantly. Green 3× yesterday because the window was never sampled. Contract field-presence tables need a TIME AXIS — a rule true at steady-state can be false during transitions. Fix = dispatch-grace window (reuse the sid=None precedent, one shared constant).

**Zombie-manager incident (new failure class, operator-confirmed):** host restarts re-hosted this manager conversation 3×; one restart FORKED it (`--fork-session`) instead — a second live supervisor body with identical context, claim, and sid, independently re-deriving and dispatching paraphrased versions of my own fix waves minutes after mine (7 phantom sends, AI-generated roster titles made them look foreign). Detection: event-timeline correlation + process census (fork-session cmdline) + transcript identity (same first user message). The sup-claim CANNOT see this — both bodies share incarnation id + sid; a per-body nonce is the fix candidate (logged in three-tier-command.md). Interim doctrine: phantom steers with your own campaign vocabulary = suspect your own lineage first; `claude stop` the fork, keep its transcript. Corollary: the zombie's work was GOOD (it found the dispatch-wedge mode) — adjudicate a rogue body's output through the normal review gate instead of discarding it.

**Fix waves minted new defects in 3 of 5 waves this campaign** (docs F1→NEW-1 contradiction; autoclean F-wave→N1/N2; pinfix wave 1 = C1 double-launch reopened). The "new-defect hunt on the fix" re-review clause fired every time and is now non-negotiable. Also: **the zombie-ordered pinfix reopened the double-launch class and the adversarial reviewer caught it pre-merge** — unchecked `claude stop`/`rm` booleans + a 30s calibration window asserted as "provably unstarted"; the required discipline was documented on the sibling helper's own docstring. Injection 3b (make stop/rm fail, suite stays green) is the canonical test-theater probe for cleanup paths.

**529-storm ops:** a 100k+-token reviewer transcript became un-resumable during API overload (4 consecutive 529 kills on resume); a FRESH agent with the findings baked into a compact brief got through and finished. Lesson: during overload, don't keep resuming a huge context — re-brief lean. Backoff schedule that worked: 3m → 10m → 20m.

**UL continuity battle-proven in production:** both live workers hit the plan limit mid-wave, parked `limited`, resumed past midnight via `resume-limited --force-now` with zero loss. Gap found: "resets 12am (Asia/Qyzylorda)" horizon format unparsed → null-horizon park needing --force-now; scanner needs that format. Durable-session resilience also proven: 2 host process deaths mid-campaign, workers + subagent reviewers all resumed lossless (SendMessage resume for subagents).

**Autoclean design facts worth reusing:** sid-based default-deny ownership (registry ∪ archive-file stems ∪ events sids; name-convention deliberately NOT evidence — AI titles); corrupt-registry fail-open was the one CRITICAL class (quarantine → next run sees empty registry → protected=∅ → rm's own sessions) — guard must live INSIDE the sweep and key on quarantine-artifact presence, not file absence; schtasks installs must embed `--fleet-home` and refuse worktree copies BEFORE base-init writes the machine marker (N1: guard-after-write = marker hijack); `pytest.raises(match=)` with path-interpolated messages is vacuously green when tmp_path contains the match word — match exact phrases.

**Process facts:** operator mid-campaign feature-ask ("automatic cleanup") folded cleanly as a design-first task in the running wave structure; `fleet clean` swept tombstones with dead in one pass (no tiering) — became the design input for the clean --dead-only/--tombstones split; two steer messages landing in one worker turn caused scope confusion the worker had to adjudicate — one steer per turn until a supersede convention exists.

## 2026-07-18 — M-D: portability directive + three-tier design gate + 2.1.212 rehome + UL parser {#2026-07-18-md}

**Campaign shape:** manager-as-supervisor (claim held across 3 host restarts + 1 overnight ~10h gap), 4 spawned workers (md-contract, md-review-break, md-review-spec, md-ulparser) + 2 dedicated branch reviewers (md-contract-review, md-ulparser-review) run through 2 fix-wave cycles each. Two docs commits by the manager directly (portability directive, token clause). Both code branches merged to fleet-impl; fleet.py grew for the transient-daemon rehome; tests 1054→1136.

**THE lesson (8th live-tier catch, and the sharpest yet — the pin caught a VENDOR change, not our code):** the FLEET_LIVE tier went RED on a review-clean tree the instant `claude` bumped 2.1.211→2.1.212. Root cause: **the native daemon became transient** — `origin=transient`, idle-exits 5s after the last client disconnects, no service install. `claude rm`/`stop` against a dead daemon fail (`rc=1 "background service may be restarting"`) and do NOT revive it; `claude agents --json` serves a stale `roster.json` snapshot; `claude --bg` dispatch is the only thing that starts a daemon. The pin tier is the ONLY thing that would have caught this before a hygiene-path failure in production — 8th time it earns its keep. Run it on every `claude` version bump, always, no exceptions.

**Probe-context is an uncontrolled variable — a bg worker CANNOT observe the dead-daemon path.** The manager saw the pins RED (interactive session on a quiet machine → daemon idle-exits between commands). The md-contract worker, itself a `--bg` session, could NOT reproduce it: a bg session is a live daemon client, holding the daemon open for its whole life. Same commands, genuinely different behavior, decided entirely by who runs them. Consequence baked into doctrine: **the dead-daemon hygiene path is verifiable only from an interactive session** — the post-merge FLEET_LIVE run from the manager's own interactive session is now the standing verification the bg workers structurally cannot do. State the probe context in any daemon-lifecycle finding.

**`claude rm`/`stop` rc=1 is 3-way ambiguous** (already-gone / dead-daemon-retryable / real-failure); the message text is the only discriminator. Fleet had collapsed all three to "failed" — reporting already-clean sids as failures AND making a retryable skip indistinguishable from a permanent one, on the hygiene path (archive/autoclean) which by construction runs against non-live workers, i.e. exactly when the daemon has idle-exited. Fix: classify by message, not exit code; kill by the roster's captured `id`, not a derived ref (ND-1: a derived ref the CLI rejects → `fleet kill` prints "killed", exit 0, marks dead — session runs on, untracked forever; the pre-fix code was fail-SAFE and the naive fix removed the only signal).

**Fix waves minted a new defect in EVERY wave again (both branches, 2 waves each = 4/4).** ulparser: wave-1 anchor→record-timestamp fix minted N2 (3.10 `fromisoformat` can't parse trailing `Z` → silent full revert on the repo's own floor). contract: M-wave minted ND-1 (fail-unsafe kill), ND-wave minted ND-4. The new-defect-hunt re-review clause caught all four; **`ESCALATE beats a 3rd fix wave` held — both branches closed in exactly 2 waves + final gate, never a 3rd.** The builder self-named the error class: *"a fix applied at one call site and not its twin; a fallback promised in a comment and not in the code"* → standing check: grep every call site, assert the comment against the code, before claiming a finding closed.

**Three-tier design gate — RESTRUCTURE, both lenses independently, same root cause.** The break-lens and spec-lens reviewers, working blind to each other, both found: **the supervisor claim is keyed on session_id, and fork-steer (the draft's own beat mechanism) rotates the session_id** — so the first scheduled beat breaks the claim permanently (freeze-page a healthy supervisor, then hourly self-seizure polluting the append-only journal). The per-body claim nonce moved from "adjacent M-D candidate" to "hard prerequisite, its own slice." Design-review-first (no build before the gate) paid: the collision is a foundation, not a delta — a build campaign would have hit it after writing the scheduler. Adjudication merged both verdicts into one binding 10-item list + sequencing; nothing ratified (operator gate). Bonus: the gate surfaced 2 SHIPPED-code defects by grep (handoff dispatch bypasses the choke point → successor supervisor sessions have NO hooks; autoclean ownership predicate matches any fleet task by path alone).

**Claim-protocol wart found live:** `sup-boot` REFUSES its own holder when the heartbeat is stale (>60m) — after an overnight gap the same-sid manager could not re-boot its own claim (VERDICT refuse/freeze), only `sup-heartbeat` (which doesn't gate on staleness) recovered it. Self-recognition is missing from the claim decision; feeds the nonce spec. Also: `sup-boot` freeze heuristic cannot distinguish an operator-authorized `claude stop` from a daemon restart (both = roster-gone + fresh-heartbeat) → froze on a legitimate succession; the manual `rm supervisor/INCARNATION` is the only release lever — there is no `sup-release` verb.

**UL parser validated in production the same session it merged:** md-contract-review parked `limited` overnight; the newly-merged local-format parser turned `resets ...(Asia/Qyzylorda)` into a real ISO horizon → `resume-limited` (no `--force-now`) cleared it cleanly. First production win for the fix, hours after merge.

**Ops facts:** `fleet wait ... run_in_background` gets killed by session teardown/restart without a completion marker — a Monitor loop (until-condition, explicit-PATH) survives better; on Windows post-restart the Git-Bash PATH can come up broken (`grep: command not found`, `bin/fleet` shim dead) → call `py -3.13 bin/fleet.py` directly and `export PATH=/usr/bin:/bin:/mingw64/bin` in Bash. Reviewer process nit worth stealing: a backtick in a double-quoted shell commit body gets shell-expanded, silently deleting text from the message — single-quote or heredoc commit bodies.

## 2026-07-20 — NFC ship arc: delegated queue, five PRs, production deploy {#2026-07-20-nfc}

**Campaign shape:** supervisor seized a 19h-stale claim mid-arc; 3 fleet workers (nfc-next-menu, nfc-cutover, nfc-nits) + manager-direct slices (FeedbackFirst guardrail, one-plan pricing, KK review); **5 PRs merged to exPardus/nfc-tags main in one day** (#7 admin/billing/guardrail → #8 pricing+KK → #9 menu editor → #10 audit nits → #11 /app cutover; 349→361 tests); prod :8097 deployed same day (migrations 0016 billing + 0017 audit_log live).

**Deploy-script lessons (mine — two bugs, real downtime):** (1) **never pipe a gating build** — `cargo build 2>&1 | tail` masks the exit code in plain sh (no pipefail) → the script killed a healthy server after a FAILED build; (2) **prod builds MUST `SQLX_OFFLINE=true`** — without it the sqlx macros compile against the live, not-yet-migrated DB (`no such column: o.suspended`); (3) **a binary is not a rollback unit once migrations ran** — the old binary refuses to start on the migrated DB (`VersionMissing`), so rollback = binary + DB-backup PAIR, always. Take the DB backup in the script BEFORE any launch attempt (it saved the day).

**The permission classifier is an ops actor — plan for it.** Auto-mode intermittently blocks supervisor PR merges and even `sup-checkpoint` writes (same verb passed 3/5 times), and HARD-blocks two things it is right about: a model widening its own permission rules, and mutations of the operator-protected prod dir. Doctrine: package prod mutations as **operator-run scripts** (reviewable, one command); never route around blocks on destructive or self-escalating ops; for benign verbs prefer `--sid`/`@file` argument forms that prefix-match future allow-rules.

**Adversarial verify keeps earning, even at tiny scale:** an independent hostile KK reviewer, on a 21-string block the manager had already read, found the one REAL structural bug (postfix "5 жұлдыздан" → broken word order in every aria-label) plus 2 lexical calques — and correctly rejected one of the manager's own proposed "fixes". Worker self-review also held: the menu-editor worker's own review+security audit caught 1 blocker + 2 should-fixes pre-merge; the supervisor's independent merged-tree gates + live smoke then found nothing further.

**Claim wart, third live bite:** a conversation fork rotated the session id under the LIVE claim mid-shift (sup-checkpoint refused; `--sid <old>` override is the standing workaround). Three dated incidents now (M-C zombie, M-D gate analysis, this). The per-body nonce slice is the fix and is unblocked.

**Guardrail pattern worth reusing (compliance-sensitive config):** gate the risky TRANSITION, not the tenure — explicit ack demanded at the single domain writer, transactional audit row for both directions, confirm dialog in the UI. Corollary caught in self-review: a 422 re-render arrives with the SUBMITTED state — never gate a required control's visibility on the rendered value (it hides the very checkbox the error demands).

**Ops:** production checkout can share `.git` with the work clone — the work clone then can NEVER hold `main` (park it on a `work` branch = origin/main); the delegated-queue pattern ("do it urself") executes cleanly when every action goes through the PR mechanism with recorded decision rationale and honest caveats (LLM KK review ≠ native speaker — still flagged).

## 2026-07-21 — M-E: the 9th live catch is a SUBSTRATE failure; detectors that miss their own incident; receipts as executable claims {#2026-07-21-me}

**Campaign shape:** one manager-supervisor incarnation, 4 build/spec workers (`me-ul`, `me-daemon`, `me-defects`, `me-nonce`) + 6 reviewers across 5 dual-lens gates, 12 fix waves, 4 branches merged (one merged → reverted on red → re-merged). Tests 1136→1302, FLEET_LIVE 6/6 on claude 2.1.216, doctor 23 PASS. `main` = `fleet-impl` = `6cd4fa7`.

**THE lesson (9th live catch — and the first that was neither our code NOR the vendor's contract):** the vendor-bump gate fired on 2.1.214→2.1.216 and the pin tier went RED at `test_1`. The contract was fine. A stale `~/.claude/daemon.lock` named pid 15740 from a daemon that had died the previous night; **Windows had recycled that pid onto `WacomHost`, a service whose `StartTime` is unreadable to a normal-token probe** — so every daemon start lost the lock race to a process that was not a daemon, and **every `--bg` dispatch on the machine failed for ~16 hours: no spawn, no respawn, no steer, no resume.** `claude daemon stop --any` prints `no daemon running` and does **not** clear the lock; removing the lock restored dispatch and the pin tier went 6/6 immediately. **`fleet doctor` reported 21 PASS / 0 FAIL throughout.** A health surface that covers only your own state is blind to the substrate you rest on — and the substrate is where a total outage lives.

**A detector must detect its founding incident, and the fixture must BE the artifact.** The shipped wedge check *passed* on the exact 16h outage it was built from (manager replayed the preserved lock + the real `daemon.log`: `ok=True`, "no wedge signature"). Root cause of how it shipped green: its test, named `test_the_2026_07_21_incident_fails`, **appended two refusal lines that never happened**, in a window where the real log shows a healthy daemon — while the true artifact was quoted in the branch's own spec row. *Fault-inject your tests or they're theater* has a second floor: **when the real artifact exists, the fixture IS the real artifact.** New standing check: replay the founding incident through the finished detector before believing it.

**"Adding evidence makes the verdict weaker" is a defect class.** The wedge check's span gate produced: 1 refusal → detected; 2 refusals 29s apart → **missed**; 2 at 6min → detected; 3 at 30s → **missed**. The verdict depended on the operator's *retry cadence*, not on the evidence. Reachable on the founding incident: its evidence window was 161s, so any second dispatch attempt inside it flipped FAIL→PASS. Whenever evidence is **demand-driven** (it exists only because someone retried), a count/span threshold measures the operator, not the system. The fix was already proven inside the branch — two of its own tests showed the gate earned nothing.

**A reviewer-ordered remedy is a fix wave, and mints defects like one (6/6 waves now).** On `me/ul` the reviewer's own wave-1 remedy — a `skipif` it prescribed — could **silently disable 17 tests with a green suite** (`1132 passed, 23 skipped`, no FAILED), killing every exact-instant parser test *and* both DST tests the same wave landed. Re-review every wave, including the ones the reviewer designed.

**Manager errors, all caught by workers with receipts — record them, they are the point:** (1) filed a live regression (`M0`) measured **from the wrong vantage** — ran an ownership predicate inside a worktree, where the canonical home's task is correctly not-ours; it was `True` before and after the wave, the regression never existed, and the break lens disproved it by AST body diff. (2) Ruled "widen the tz regex, let `ZoneInfo` validate" — which guards against *unparseable* names but not *resolvable-but-wrong* ones (`(EST)` → 09:40Z where US Eastern is 08:40Z); superseded by a closed fixed-offset set. (3) Bound an adjudication item to "resume only when the holder is roster-gone" — an over-specification the author disputed with three receipts and the **reviewer withdrew its own CRITICAL's remedy** on that evidence. (4) Wrote a sequencing claim ("ship detection first, it stands alone") that inherited a false premise — under the recommended detection-only option the founding zombie incident produces **no refusal at all**. **New gate: a receipt states its VANTAGE (which worktree, which FLEET_HOME, which commit), not merely who ran it.** Probe-context was necessary and not sufficient.

**Receipts are executable claims, and a verifier without a seed test proves nothing.** A worker reported a receipt-verification harness that caught four defects; the spec lens went looking and **the artifact did not exist**. Built for real, it immediately caught the author copying a receipt *from the reviewer's document rather than executing it* — the exact failure the grep-receipt rule exists for, committed by the person enforcing it. Bound to `tests/test_receipts.py` because *a tool that only DETECTS a class does not prevent it*: the spec's own pin block went stale twice while the harness existed and was bound to nothing. Seed-tested three times independently (author, reviewer, manager). And the binding's own design flaw surfaced only at the **merge gate** — receipts were verified against the working tree, so two unrelated branches merging ahead turned the shared suite red; a receipt is a claim about **a specific commit**, now materialised from its `# at <sha>` pin via `git archive`. **A new shared-suite gate must be tested against the tree it will MEET, not the tree it was written on.**

**Design lesson from the claim-nonce gate (both lenses, independently → RESTRUCTURE):** *a bearer secret cannot be an authorization credential on a substrate with no privilege separation.* Every worker can read `FLEET_HOME`; a public view printed the value; so the design was forced to grow three unauthenticated recovery paths, each keyed on something the view publishes. Reframed as **detection** (the nonce proves "the last body to act was the same body as this one", never "I am authorized") it is sound and worth building. Sharpest observation of the campaign, from the break lens: *"the spec argued itself out of its own decisions and did not notice"* — §4.5 conceded byte-identical bodies make exclusion undecidable, which voids §5.4/§5.6 two sections later.

**Disputes with receipts are now load-bearing, in both directions.** A builder deviated from a manager ruling (`max(fold=0, fold=1)` instead of the ruled literal `fold=1`) and was **ratified** — `aware + timedelta` resets fold under PEP 495, so the ruling would have been a silent no-op, and a correctly-placed `fold=1` flips the spring-forward gap *early*; proven over 8784 samples. A reviewer **rejected** a builder's equivalent-mutant dispute because the argument described pre-wave code and was false of the code shipped — and the builder responded by finding *why* the mutation stayed green (no fixture combined an unusable `startedAt` with an undateable line), supplying the fixture rather than re-arguing. `ESCALATE` was used correctly as a fourth verdict: a final gate named and validated a restructuring instead of writing a third finding list.

**Ops facts:** workers pushed branches and opened draft PRs **unbidden, twice** (second campaign running) — task files now say *commit only, never push, never open a PR*; the terseness clause ate the `RESULT:` contract line in 3 of 4 first-turn reports until it was marked "not subject to the terseness clause"; a Monitor loop polling `fleet status` dies when `bin/fleet.py` is transiently conflicted mid-merge (it parses the SyntaxError as worker names) — re-arm it after any conflicted merge.

## 2026-07-22 — operator decisions + doc reconciliation pass {#2026-07-22-operator-decisions}

**SDD / drift-control R1–R4: RATIFIED by Altai, 2026-07-20.** Confirmed 2026-07-22. R1 Phase-1 `spec verify` gate ships first behind `sdd.enabled` (default off); R2 both scopes, effective scope = slice ∩ whole-spec, a slice may only narrow; R3 both judge paths, advisory in both forms; R4 specs git-tracked from birth at `docs/specs/campaigns/<campaign>.md`, folding into `docs/SPEC.md` as a first-class § when built. `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` = `v4`, build-ready pending the M-F slot. Ticked in `docs/OPERATOR-GATES.md`.

**PROCESS DEFECT the reconciliation surfaced: a ratification landed in a commit message and a `Status:` line, and nowhere else.** For two days the repo held four mutually contradictory answers to "did the operator ratify SDD?" — the spec said yes (`operator-ratified 2026-07-20`), while `OPERATOR-GATES.md`, `NEXT-SESSION.md` and `PLAN-PROGRESS.md` all said no, and `knowledge/lessons.md` — the file the rule names as the record — said nothing. The rule ("record each answer as a dated line in `knowledge/lessons.md`, never session memory") was already written; it was skipped, and skipping it is what made the contradiction undetectable from any single document. **A ratification is not landed until the dated lessons line exists.** The `Status:` line is a consequence of the record, never the record itself.

**Second-order: a fresh doc can be born stale.** `docs/superpowers/specs/2026-07-22-fleet-index-design.md`, written the same day, asserts `bin/fleet.py` is 7832 lines in five places — including inside a sample index block — when it was 8706 at every commit in range. Design docs quote measurements as freely as specs do, and nothing re-runs them: `tools/verify_receipts.py` covers `docs/specs/**` only. Candidate for the next campaign: point the harness at `docs/superpowers/specs/**`, or stop pasting numbers into design prose.

**Reconciliation ledger (mechanical drift found in one pass, all doc-side, zero code defects):** `main`/`fleet-impl` shas 2 commits stale in the handoff; test count claimed 1302 and 1142 (README badge) against an actual 1306; pin version claimed 2.1.216 in the same file whose commit message announced the 2.1.217 re-stamp; `CLAUDE.md`'s opening pointer still routed readers to "the approved v2 design ... M1–M5, §13" when SPEC is v3 and §13 is the doctor roster; `PLAN-PROGRESS.md` ended on the me/nonce **revert** row with no re-merge or close-out, which the `PLAN.md` runbook orders a resuming manager to read first. **The measurements were all cheap — nothing here needed more than one command.** They drifted because no close-out step re-runs them.
## 2026-07-22 — Reconcile: a second platform is a defect detector; duplicated work merges worse than divergent work {#2026-07-22-reconcile}

**What it was.** Two long-lived branches (`origin/posix-port`, and `origin/feat/worker-providers` which is a strict superset of it) reconciled into `main`. 4 workers: 2 resolvers on disjoint file sets, 1 fixer, 1 break-lens reviewer. Windows 1302 → 1376 tests; **Linux 200 failures → 0**.

- **The reconcile was cheap; what it EXPOSED was the value.** `main` at `56308cd` failed **200 distinct tests** on Ubuntu, and nobody knew, because `_PosixPlatform` was a stub that raised on every call — so no M-E work had ever executed on a non-Windows host. Merging a real POSIX backend turned 200 latent Windows-only assumptions into 21 visible failures. **A stub backend is not "unsupported", it is a coverage blindfold**: every test that would have caught the assumption skipped or passed vacuously instead.
- **Duplicated work is harder to merge than divergent work.** All 9 conflicted files and all 14 hunks were *the same M-E work landed twice by different routes under different SHAs*. Zero conflicts came from the posix port itself, because it lives behind the platform adapter. **Conflict count measures process duplication, not technical risk** — the risky change conflicted with nothing.
- **Split a merge by disjoint file sets, not by phases.** Two workers each got the same pre-staged `--no-commit` merge state, resolved their own files on the merits, and `git checkout --ours`'d the other's purely to make the merge committable. The manager spliced (`checkout <tip> -- <files>`) and `commit --amend`'d, keeping one merge commit with both parents. Genuinely parallel, no shared-tree races. **They also independently agreed on the one cross-cutting call** (the handoff-dispatch fork) from opposite sides — cheap corroboration the splice was coherent.
- **Ask each hunk "which SHAPE is this?" before "which side wins?"** The brief named exactly two shapes — duplicated-work (ours is later) vs unique-posix (theirs is the only copy) — and demanded a per-hunk ledger. Both failure modes (silently dropping posix, resurrecting a superseded fix) are **invisible to a green suite**, because the capability and its test vanish together.
- **A "closed set" that consults the environment is not closed.** ND-5's closed fixed-UTC allowlist resolved members through `zoneinfo`; 7 of 8 are tzdb *backward-links* that stock Ubuntu omits. Same message, opposite outcome per platform: Windows auto-resumed a parked worker, Linux null-parked it forever. It degraded *safely*, which is why it survived — **safe degradation hides platform splits from every alarm you have**.
- **`.lower()` on a path is a false MATCH on posix, not a false MISS.** The in-code comment had the direction backwards and had passed review. On a case-sensitive FS it makes two *different* paths compare equal — and this predicate decides whether a scheduled job is ours and may be removed. **Re-derive the direction of a normalisation bug on the platform you are porting TO.**
- **The floor you declare is the floor you must RUN.** `run_py.sh` accepted ≥3.10 while docs said 3.13. Running at 3.10 found `exc.add_note()` (3.11+) inside `except BaseException: … raise` — Ctrl-C became an `AttributeError`. **Second campaign running where a 3.11+ API beat a grep-based audit.** Declare it once as a constant; determine it by executing, never by reading.
- **Fault-inject the merged tree, not just the new code.** The reviewer's 15 Windows + 13 Linux mutations found two behaviours with NO pin: reverting the successor interpreter to `py -3.13` (breaks handoff on every non-Windows host) and deleting the hook's posix short-write guard (torn JSONL, silently skipped by `read_outcomes`) each left **all 1376 tests green on both platforms**. A portability fix with no pin is a comment.
- **Make the reviewer attack the MANAGER's attribution, not just the code.** Handing over "19 of 21 are pre-existing, not merge damage" as a claim to falsify produced the campaign's best artifact: a four-commit Linux failure-set census (`comm -23 merged (main ∪ theirs)` → **empty**) that proved zero merge-unique failures and showed the merge *fixed* 179. Stronger than any assertion the manager could have made alone.
- **A lint that names its exemptions must enumerate its scope too.** The adapter-boundary lint scanned `fleet.py` + 2 named scripts and missed all of `bin/hooks/` — where the one sanctioned second `os.name` branch lives. Glob the directories, exempt one *function* by `ast`, and fault-inject the lint itself.
- **Ops.** `fleet spawn` under native dispatch refuses `--max-budget-usd` (contract G3) — use `--token-ceiling`. Verify a POSIX port in WSL against a clone on the **native filesystem**, never `/mnt/c` (line-ending + permission-bit noise); bootstrap pytest with `get-pip.py --user --break-system-packages` when `ensurepip` is absent and sudo needs a password. Windows PowerShell skips 5 `sh`-gated tests that Git Bash runs — **the same suite reports different skip counts per shell**, so state the shell with the count.

## 2026-07-23 — doc pass 2: the docs drifted again in one campaign, and the drift is always in the same direction {#2026-07-23-doc-pass-2}

**What it was.** A full audit of every claim-bearing document against measured reality, one day after the previous reconciliation. Fleet registry cleared first (19 dead workers; journals backed up to `logs/journal-backup-20260723/`). Measured baseline: **1403 passed / 8 skipped, byte-identical on `py -3.13` and `py -3.10`**; doctor **23 PASS / 0 FAIL**; `claude` 2.1.217, pin stamped; `bin/fleet.py` **9091 lines**; `main` the only branch.

**The docs went stale again in ONE campaign, and every drift ran the same direction: docs under-claim what shipped and over-claim what works.** Under-claimed — `SPEC.md` §18 had no M-D, no M-E, no reconcile; its portability-gap list still said `_PosixPlatform` raises when the POSIX backend had shipped; README and `getting-started` said Linux was "specced, not yet shipped" the day after Linux went 200 failures → 0. Over-claimed — **`fleet attach` was advertised as working in README three times and in `getting-started` twice, while `cmd_attach` raises unconditionally on every path.** A user following the quickstart hits a hard error on a headline feature.

**THE lesson: a feature that was removed leaves its documentation behind, and nothing notices.** `attach` was fenced out at M-B ("native attach integration is a later milestone") — SPEC §7 says so plainly. The user-facing docs were never swept, so for ten days the pitch, the feature table and the tutorial all described a command that only errors. `SPEC.md` was right and *no reader of `SPEC.md` is the person being misled.* **When a verb is fenced off, grep the user-facing docs for its name in the same commit** — the spec is not the surface that lies.

**Second: `21 checks` was wrong in three files at once, because it is a derived number pasted by hand.** README, `getting-started` (twice) and `SPEC.md` §13 all said 21 against an actual 23; `SPEC.md` even pasted `grep -c "def _doctor_check_" bin/fleet.py → 21` as a receipt, which is the exact shape `tools/verify_receipts.py` re-executes — except the harness only covers `docs/specs/**`, and `SPEC.md` is not in `docs/specs/`. **The spec of record is the one document with no receipt enforcement.** That is backwards, and it is the cheapest gap left to close.

**Third: the pin doctrine works and has a cost nobody had priced.** `SPEC.md` §0 pins the body to `c63d7dd`, which is now four milestones back — `bin/fleet.py` grew 7378 → 9091 lines, so *every* `@NNNN` anchor in the document is off by hundreds of lines. The pin is honest; the staleness is not visible to a reader who does not check the date. Fix applied is a banner, not a re-pin: **re-pinning is a campaign, not an edit**, because every receipt must be re-executed at the new commit. The structural answer is for `SPEC.md` to adopt `# at <sha>` blocks so the harness can do it.

**Fourth: two governing process documents describe a process this project stopped following on 2026-07-13.** `ROADMAP.md` (Phases 1→6) and `PLAN.md` (campaigns C1→C8) still gate on `SOAK GATE 1 SIGNED` — **a line that has never been written in `knowledge/lessons.md`** — while four milestones shipped around it, and `PLAN.md` still names the retired `fleet-impl` as the merge target. Their *doctrine* (worktree isolation, task-file convention, dual-lens review, W-V verification) is what actually binds and is alive. Fix applied: reality-check banners naming exactly which parts are live and which are history, plus an operator gate — a manager may write the question, never the answer.

**Process change:** the close-out step must **re-measure, not recall** — suite count on both interpreters, doctor count, `claude --version` against `pin-pass.json`, `wc -l bin/fleet.py`, and `git branch`. Every number in this entry cost one command. They drift because nothing re-runs them, and a stale number in a README is indistinguishable from a lie to the reader who acts on it. Campaign-template candidate: a close-out that ends without pasted measurement output is not closed.

## 2026-07-22 — D7: the plugin briefed every session on the machine, including other people's projects {#2026-07-22-hook-removal}

**What it was.** The operator opened a session in an unrelated repo, dumped its context, and found this fleet's entire internal state sitting in it: all open operator gates verbatim, all 19 registry workers with names and statuses, 20 lines of `knowledge/INDEX.md`, the supervisor nag. ~7,000 characters of one project's governance injected into a project that has nothing to do with it. Removed the SessionStart hook and the plugin's `hooks` key outright (`docs/specs/terminal-surface.md` D7); fleet is now pull-only. Tests 1403 → 1393 (12 hook tests deleted, 7 replacements added, +2 net new pins on the marker); green byte-identical on `py -3.13` and `py -3.10`.

**THE lesson: a guard written against the case you noticed does not cover the case you didn't.** D5 (2026-07-09) diagnosed this exactly right — "a globally-enabled fleet plugin fires this hook in EVERY Claude Code session on the machine" — and then guarded precisely one consequence, workers, via the `FLEET_WORKER` stamp. The *same sentence* implies every unrelated project on the machine, and that half went unguarded for 13 days. The premise was correct, complete, and written down; only the conclusion was partial. **When a comment says "every X", enumerate every X and say what happens to each — a guard whose own docstring states the general case while handling one instance is the most likely place to find the next defect.**

**Second: the leak is invisible from inside the repo that leaks.** Every test, every review and every daily session ran inside `C:\proga\claude-fleet`, where the briefing reads as a useful feature working exactly as specified. Nothing was broken *here*. The defect only exists in sessions the fleet's own tests never open, and no amount of testing from inside would have found it — the operator found it by dumping context somewhere else. **For anything installed machine-wide, the test that matters runs outside the project.** The replacement pin (`test_manifest_registers_no_hooks_at_all`) is a statement about what the plugin must not do to strangers, which is the only form that survives being run from inside.

**Third: filtering was the obvious fix and the wrong one.** The first instinct was to scope the briefing to the current repo — registry rows carry `cwd`, so it was buildable. The operator rejected the whole shape: fleet is meant to install like any other plugin, so a briefing nobody asked for is unwanted in *every* repo, scoped or not, and it still costs tokens in a session that will never touch the fleet. **The question is not "how do I make this injection smaller" but "is this injection the plugin's to make at all."** What the hook automated (the SPEC §10 startup ritual, the ask-first gates) moved into `skills/fleet/SKILL.md`, which fires when someone has actually chosen to manage a fleet — strictly later, and that is the point.

**Fourth: deleting a consumer can strand its data, silently.** `~/.claude/fleet-home` existed for exactly one reader — the hook, which under a marketplace install runs from a cache copy whose `state/` is empty and so could not resolve the home from its own location. `fleet.py` and `fleet_statusline.py` never read it (env → own location, both). With the hook gone the marker is written by `fleet init` and inspected by `fleet doctor` and **read by nothing**. Kept deliberately as doctor's "did you run `fleet init`" signal, but pinned by a test that enumerates its callers, so the next person does not rediscover it as a mystery. **After removing a component, grep for what only it consumed — orphaned mechanism looks identical to load-bearing mechanism.**

**Fourth-and-a-half, the follow-up (same day): the orphan was deleted, not documented.** The first pass kept `~/.claude/fleet-home` "as the documented handshake for the next out-of-repo consumer" and pinned its caller set. That was the wrong call one level up, and the operator sent it back. Two arguments decided it. (a) **Stamping it was fleet's only unconditional write to global machine state** — plain `fleet init`, an invocation asking for nothing outside the repo, wrote into `~/.claude/`. That is precisely the instinct D7 had just removed from the manifest, surviving three functions away. (b) **The obvious rescue was worse than the disease**: giving it a reader (resolve `$FLEET_HOME` → marker → own location in `fleet.py`) would let a stale marker silently redirect the CLI — `fleet clean` and `fleet kill` included — at a *different* fleet's registry. Deleted: `fleet_home_marker_path`, `_write_fleet_home_marker`, `_doctor_check_fleet_home_marker`, and the marker-mismatch half of `_marker_guard_problems` (renamed `_home_guard_problems`; its worktree check stays, because a scheduled task pinned at a worktree outlives `git worktree remove`). Doctor 23 → 22 checks. **A dead mechanism kept "for the future" is not neutral — it keeps paying its costs (a global write, a guard branch, a doctor check, a conftest sandbox line) while its benefit is hypothetical.** The pin that replaced it asserts absence, not shape: `test_no_shipped_code_references_the_marker` matches the marker-path *construction*, because a first attempt matching the word "fleet-home" went red on the unrelated phrase "the fleet-home root" in the worker-settings template error.

**Fifth, operational: editing the repo does not fix an installed plugin.** The plugin runs from `~/.claude/plugins/cache/claude-fleet/fleet/<version>/`, a full copy. The stale cache still had the hook after every repo edit and every green test run. Version bumped 0.1.0 → 0.2.0 so a refresh lands a clean directory. **A packaged tool has two truths — the repo and the installed copy — and the tests only see one of them.**

*(Ordering note: this entry is dated 2026-07-22, the real current date, and lands after an entry dated 2026-07-23. That entry's date appears to be wrong; not corrected here, since lessons.md is append-only and a past entry is not mine to edit.)*

## 2026-07-23 — operator decisions: nonce gate = (b), claim-nonce ratified, three-tier re-draft now {#2026-07-23-operator-decisions}

Docket put to Altai in-session (interface session, `AskUserQuestion`), answers verbatim-in-substance:

- **Claim-nonce gate question: (b) — a knowingly-bypassable gate.** Chosen against the spec's own narrower recommendation ((a) as the buildable floor), with §7's accounting read as the price: (b) is the only option that closes incident 1 (the 2026-07-16 dual-supervisor zombie); the bypass (shell access) is documented in the design; the gate is armed only while the heartbeat is fresh; `autoclean` is structurally exempt; the corrected §7 verb taxonomy becomes binding for the build.
- **`docs/specs/claim-nonce.md`: PROMOTED to spec-of-record.** Ratified 2026-07-23 by Altai. The three MINOR residuals from the final break gate (`a0bd194`) close in the build slice before any code ships. Status line flipped and §7 header updated in the same commit as the `OPERATOR-GATES.md` ticks — the dated line here is the record, the `Status:` line is its consequence (per the 2026-07-22 process-defect lesson).
- **`docs/specs/three-tier-command.md`: re-draft NOW, not queued.** The nonce prerequisite is discharged at the design level. Two new operator requirements to fold into the re-draft, from the same conversation: **tier-model assignment** — the human-facing interface session runs the highest-tier model, the supervisor runs the second tier (today: Fable 5 interface / Opus 4.8 supervisor) — and a **~200k-token supervisor swap band**, tightened from the drafted 300–500k, because the swap exists to save usage: the supervisor is respawned/handed off before its context gets expensive. Build still waits on the re-drafted spec's own dual-lens design gate.
- **Everything else deferred by the operator** ("wait on all operator gates, they will be closed in a short amount of time"): native-substrate's 11 ratification markers, fleet-index M1, the worker-providers doc contradiction, the two-roadmaps question, M-F shape/budget. Deferral noted in `docs/NEXT-SESSION.md` with this date.

## 2026-07-23 — three-tier re-draft: operator design inputs {#2026-07-23-three-tier-inputs}

Refinements from the same docket session, binding on the re-draft brief:

- **Swap**: supervisor self-monitors context; band **150–200k tokens**. Entering the band → hand off at the next wave/task boundary. Past 200k → strongest directive to hand off, but it finishes the current *urgent* task first — no new work. Handoff ritual = existing sup-handoff machinery: write the successor document, hand control back to the interface session.
- **Tier models by role, configurable, never hardcoded ids**: interface session = highest tier (today Fable 5), supervisor = second tier (today Opus 4.8).
- **Worker models**: supervisor's call, **Opus and Sonnet only**. Haiku is never a worker — subagent inside worker sessions only.
- **Beats**: event-driven only in v1; scheduled heartbeat deferred until a campaign demonstrably stalls for want of one.

## 2026-07-23 — operator decisions, second docket: council-advised gate closures {#2026-07-23-operator-decisions-council}

Docket put to Altai in-session after a 3-agent advisory council (risk / delivery / governance lenses, parallel, read-only) returned per-gate verdicts. The council advises; the operator alone ticked. Operator's words: "i accept all the ones which are unanimous; gate 1 partial ratification is the correct choice; gate 5 sub b i need to consider this more."

- **native-substrate contract rows: PARTIAL RATIFICATION** (council 2–1, majority adopted). All 11 `[PENDING OPERATOR RATIFICATION]` markers flipped to `RATIFIED 2026-07-23`, EXCEPT the three dead-daemon manager-report-only claims (G12 dead-daemon `rm` message; dead-daemon `stop` twin; rm/stop-do-not-revive in the transient-daemon hazard), now marked `RATIFICATION WITHHELD 2026-07-23` pending a quiet-machine capture (G9 probe). Basis: the contract's own G12 row instructed exactly this, two waves failed to re-observe the strings, and the matcher's fall-through design makes the withheld strings non-load-bearing for correctness. Noted follow-up (not a condition): the file has no `# at <sha>` pins and is unenforced by `verify_receipts.py` (NEXT-SESSION item 4).
- **fleet-index M1: QUEUED behind M-F** (unanimous). The headline economics is unmeasured and the M-F run generates exactly the data that would test it. Sub-decision (a) (tracked/ignored bundles vs gitignored-only; council split 2–1 for collapse) and sub-decision (b) (transcript tool-call counter in scope; council unanimous yes) remain OPEN — the operator is explicitly still considering (b).
- **worker-providers design doc: RE-STATUSED** (unanimous). Header flipped from `approved design — ready for implementation plan` to `spike-negative — §4 dead as written`, per its own §4.2 NEGATIVE gating spike; `docs/longcat-fleet-usage.md` named the working alternative of record. `docs/specs/providers.md` re-base-or-park stays open.
- **Two roadmaps: RETIRE the C-campaign/soak framing as superseded history** (unanimous, with condition). Load-bearing condition: PLAN §0's still-binding doctrine (worktree isolation, W-V discipline, RESULT contract, dual-lens gates) must be re-homed to a live surface BEFORE the retire edits land. Mark superseded, never delete. The retire is queued work; only the decision is recorded today.
- **M-F: PREEMPTS the queue** (unanimous). Dogfood-outward run, overdue since stupidbox 2026-07-09. Budget envelope NOT yet signed — stays an open gate; M-F does not dispatch until it is. Council framings on record: ~$75–100 timeboxed vs. token-ceiling-cap enforcement (no USD source exists under `--bg`, G3) vs. envelope-as-dispatchable-ceiling.

**Addendum (2026-07-23, same session):** role→model config is **tier-based, never model-id-based** — roles bind to abstract tiers (highest / second / third) and a resolver maps tier → concrete model from what is *currently available*; model ids appear only as illustrative examples. Must work with a non-Anthropic provider (`docs/longcat-fleet-usage.md` is the working alternative of record, re-statused 2026-07-23): tier mapping resolves per provider, with explicit stated semantics when a provider lacks a tier.

**Addendum (2026-07-23, manager refinement during the re-draft, binding — supersedes the "today Fable 5 / Opus 4.8" framing where it reads as the config itself):**

- **Tier-based, never model-id-based.** Roles (interface / supervisor / worker) bind to abstract tiers (highest / second / third); a resolver maps tier → concrete model at dispatch time from the models *currently available*. Concrete ids (Fable 5, Opus 4.8) are illustrative of today's Anthropic resolution only, never normative.
- **Provider-agnostic; must work with a non-Anthropic provider.** `docs/longcat-fleet-usage.md` is the working alternative of record (per-`CLAUDE_CONFIG_DIR` isolated daemon namespace). The tier→model table lives in that namespace's **daemon env** (`ANTHROPIC_DEFAULT_OPUS_MODEL` etc.), set by the launcher, not by fleet. Cross-provider fleet = separate namespaces (one daemon each); a role resolves per namespace. Provider-lacks-a-tier ⇒ omit `--model` (let the namespace default govern) or accept the CLI `model_not_found` refusal; a fleet pre-flight tier-resolution check is `[UNBUILT]`.
- **Receipted (at `235421e5`):** `bin/fleet.py` has ZERO model-id / `CLAUDE_CONFIG_DIR` / `ANTHROPIC_` / `--provider` surface (grep 0/0). The only shipped model surface is `--model <tier-alias>` at spawn/handoff; resolution is entirely the daemon env. Role→tier policy is routed to `supervisor/GOALS.md`; a machine-read of it is `[UNBUILT]`. Full analysis: `docs/specs/three-tier-command.md` §3.

## 2026-07-23 — operator decisions, third docket: cap doctrine, fleet-index sub-answers, M-F unblocked {#2026-07-23-operator-decisions-caps}

Council round 2 (same three advisory agents, deeper read) put verdicts to Altai; operator adopted (a) and (b) as recommended and REPLACED the envelope question with a doctrine change:

- **Cap doctrine (NEW, standing): no fleet-enforced token or USD ceilings — for workers or managers.** Operator is on Claude Max 20x; the plan's own usage limits are the cap for every session alike, and fleet's existing limit-park/resume machinery is the recovery path. Cost/token *counting* becomes an on/off flag, **default off**. Operator's words: "for now we should disable the token limits or cost limits within the fleet repo. cost counting should be a flag that can be enabled and disabled"; "workers should be also be capped the same way as managers." Retires PLAN §0.4's ceiling denomination — fold into the queued C/soak-framing retirement (the §0 re-home).
- **Worker context band (NEW, binding on the in-flight three-tier re-draft): the 150–200k context band applies to WORKERS, not only supervisors.** Extends `#2026-07-23-three-tier-inputs`: a worker self-monitors context; entering the band → hand off/respawn at the next task boundary. Operator's rationale: unbounded worker counts and contexts drift the parts apart and the waste reappears as reconciliation effort — keep worker counts small, respawn before context gets expensive.
- **fleet-index M1 (a): collapse to gitignored-only.** Tracked-mode defends a query path absent from M1; the worktree hazard exists only because tracked mode does; re-add at M2 is an additive config key. Review finding 2b re-dispositioned: committing `.fleet-index/` is documented-unsupported in M1 (never leave an Accepted finding pointing at deleted text — the spec edit lands with the M1 build).
- **fleet-index M1 (b): tokens-primary, counter demoted.** Acceptance criterion 1 = `input_tokens` delta from the existing Stop-hook outcome telemetry (zero new parsing of the unversioned transcript format); ≥3 paired A/B runs, n=1 is noise. The transcript tool-call counter is a volatile, sunset-marked `tools/` diagnostic only. M1 fully unblocked, queued behind M-F.
- **M-F: unblocked to dispatch.** No envelope; discipline is structural (small worker count, context band, escalate on anomaly).

**Second addendum (2026-07-23, operator, binding — folds as re-draft wave 3):**

- **Supervisor tier PROMOTED to top tier (Fable class).** Clarified division: the interface session holds the *long-term goals*; the supervisor is in charge of *solid plans, details, and splitting tasks* to workers — planning quality justifies top tier, not second.
- **Top-tier usage limit is ~half the standard limit → the role→tier binding becomes a PREFERENCE CHAIN, not a single tier.** Supervisor prefers the top tier and auto-falls back to the second tier (today Opus) when the top tier's usage limit is hit, returning once the reset horizon passes. Folds into the existing usage-limit detection/park/resume machinery (G11, `limited`, `resume-limited`); the exact mechanism is the spec's call and goes through the gate.
- **Worker band re-confirmed by the operator in-session** ("workers should also have a cap for cost saving") — consistent with the third-docket cap doctrine; the spec's "second tier only" scoping (line ~980) is retired.
- **Manager reading of the cap doctrine vs the spec's B4 hard arm:** "no fleet-enforced token or USD ceilings" retires *spend* ceilings (the `--token-ceiling` denomination), not the *context-band* handoff enforcement — a context band is a freshness mechanism, not a budget. Wave 3 states this reading in-spec; the operator rules on it at ratification.

**Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — **cost/spend ceilings are gone unless the counting flag puts them back** (flag default off; enabling it may re-arm spend caps). The context band (150–200k, supervisors AND workers) is a freshness mechanism, not a budget, and its enforcement stays. Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before ratification.

## 2026-07-23 — three-tier spec RATIFIED; H1 harness hardening shipped {#2026-07-23-three-tier-ratified}

**`docs/specs/three-tier-command.md`: RATIFIED spec-of-record by Altai, 2026-07-23** (in-session docket, after the full M-F re-draft pipeline: 5 waves, 3 full dual-lens gate rounds + 2 confirmation passes, ~30 findings closed, 0 spurious fixes, final break-lens merge verdict "fit for operator ratification"). Content as ratified: interface tier holds long-term goals at top tier; supervisor owns plans/details/task-splitting at TOP tier with a usage-limit fallback chain to second tier (limit-arm honestly lossy — doctrine: hand off on the band before the limit); 150–200k context band binds supervisors AND workers; tier-based provider-agnostic role→model resolver; cost caps flag-gated off. Disclosed at ratification: three claim-nonce build-slice prerequisites (rule-1 guard, FLEET_WORKER refusal, limited-holder transfer branch) — they gate the BUILD. Build order: nonce build → three-tier build; M-F dogfood preempts both.

**H1 shipped and merged**: `tools/verify_receipts.py` now errors under `--strict` on any receipt-shaped text it cannot classify (gutters, tabs, tilde fences, inline spans, stray directives, unterminated fences), founding-artifact replay red, 20-mutation hostile review + fix wave (11/11 mutation REDs serially), test_receipts 13→49, suite 1420/8 both interpreters. Pin tier re-run green + stamped at claude 2.1.218 (10th vendor-bump gate exercise; no catch this time).

**Process changes earned (M-F re-draft campaign, anti-ritual gate):**

1. **A binding operator ruling lands as a commit on the target branch BEFORE any wave cites it** (→ template v1.9). The manager steered the cost-cap ruling into a running wave while the ruling's commit sat only on `main`; the spec then declared the question "SETTLED" citing a record its own tree could not witness — a manager-owned CRITICAL (ND5) that reversed a fit-for-ratification merge verdict for a round. Both lenses caught it independently; the spec lens proved the ruling genuine and named the one-command cure (merge first). Steer text is delivery, never provenance.
2. **Receipt-shaped text the parser never sees is the silent-drop class, third recurrence** — after the daemon check's fabricated fixture and the ul-parser's silent skipif. Four gutter-indented receipts rode through two full gate rounds unverified; the founding-artifact replay then found 16 evasions where the probe knew of 4. `verify_receipts.py` now errors under `--strict` on any unclassifiable receipt shape anywhere in the file (tabs, gutters, tilde fences, inline spans, stray directives, unterminated fences). Corollary held: **when the real artifact exists, the fixture IS the artifact** — and it knew more than the probe did.
3. **Mutation-test the detector you just hardened**: hostile review ran 20 mutations against the new H1 detector and its suite survived 6, including a compound suite-green blinding — on the very tool whose job is preventing green-while-blind. Every surviving mutation now has a named catching test, re-proven by re-running the exact mutation serially with byte-identical restores.
