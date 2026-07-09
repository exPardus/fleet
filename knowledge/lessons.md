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
