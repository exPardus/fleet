# Next-session handoff — fleet manager

**Written:** 2026-07-09, at the readiness boundary (Campaign 2 merge gate passed). Read this FIRST, then `docs/PLAN-PROGRESS.md` (the live wave cursor).

---

## Where things stand

The self-build is through its **readiness boundary**: Campaign 1 (SPEC v2.1 amendment pass) and Campaign 2 (self-build safety — live-integration harness + 11 hardening kernels) are **both closed and merged to `fleet-impl`** (merge `9e4ec9c`). The live install is healthy: **`fleet doctor` = 17/17 PASS**. ~60 commits since baseline `b920102`; ~$135 spend across both campaigns.

**Proven in C2:** the fleet can safely modify itself — worktree firewall, pre/post-merge live tiers, and the **revert path exercised for real** (a post-merge red → clean revert → worktree fix → re-merge green). Two new features shipped: **UL1** (usage-limit park + `fleet resume-limited` auto-resume) and **UL2** (worker subagents, documentation-only). Both ratified by Altai.

**New CLI/behaviors now live:** `fleet resume-limited`, `--token-ceiling` (spawn/respawn), statuses `over_budget`/`over_ceiling`/`limited`, spawn-time model echo, doctor checks (hook-registration, unreadable-starttime, limited-parks, ceiling-file sweep, hook-errors).

## THE GATE — do not cross without a signature

Campaign 3+ (feature phases) are **gated behind Soak Gate 1**, which only Altai signs. Soak Gate 1 pass condition (PLAN §Campaign 3): **≥15 spawns across ≥3 distinct days** of real day-to-day fleet use on ≥1 **non-fleet** project, `fleet doctor` clean at gate-close, zero incidents per the defined audit. Altai writes `SOAK GATE 1 SIGNED: <date> — Altai` in `knowledge/lessons.md`; the C4 spec task's first line greps for it.

**You (next session) may NOT:** start any C3+ BUILD wave; issue the soak sign-off yourself. **You MAY:** run real external campaigns that GENERATE the soak usage (see below); run the C4 portability **spec task only** (docs-only) during the soak; do housekeeping.

## Hard constraints (unchanged — violating any is stop-and-ask)
- Code-touching workers run in a **git worktree**, NEVER in `C:\proga\claude-fleet`. At most ONE `bin/fleet.py` writer alive fleet-wide.
- No `launch_turn`/hook/parser change merges without a green `FLEET_LIVE=1` run executing the changed code.
- Never read `bin/fleet.py` end-to-end (grep named anchors). Same for workers via their task files.
- Every task under one of the three §0.4 permission mechanisms (bypass / bypass-with-containment / accept+allowlist) — bare `accept` is headless-undeliverable.

## Fleet operating notes (learned this build)
- Call the CLI by full path from the MAIN install: `py -3.13 bin/fleet.py <cmd>` (cwd `C:\proga\claude-fleet`). Running it from the worktree points at the wrong registry ("unknown worker").
- **`fleet result`/`peek` crash on unicode output** (Windows cp1252, e.g. `→`): prefix `PYTHONIOENCODING=utf-8`. Known bug, fix candidate in `knowledge/projects/claude-fleet.md`.
- **A worker's turn is "done" only if `git log` shows its commit** — `fleet result`/`cost_usd` are unreliable after a transient API 529 (turn goes idle, cost frozen, no commit). Re-sending a git-committed fix task is safe.
- Check-in via `fleet wait <names> --timeout 300` in **background Bash (`run_in_background: true`)**, never Git-Bash `&`, never sleep-loop. On each wake: `fleet status` + `fleet peek` cost-watch.
- The live harness **overwrites the committed fixture corpus on every run** — `git checkout -- tests/fixtures/streams/` before any git-state check.
- Read `knowledge/playbooks/campaign-template.md` (v1.2) — the (a)–(h) gate pipeline + merge gate + all the checklists, amended with C1/C2 lessons.

## Housekeeping left open
- ~10 idle doc/review worker records from C1/C2 remain (a bulk-clean loop mis-parsed long names). Clean them: `fleet kill <name>` each, then `fleet clean`. Non-blocking.
- Worktree `C:\proga\claude-fleet-wt\c2` still exists (merged). Remove with `git worktree remove C:/proga/claude-fleet-wt/c2` when done, or keep for reference.

---

## Your first job next session — dogfood fleet on a small sample project (documentation)

Altai's request: **test fleet in the wild on a small sample project — a documentation campaign.** This is a genuine external campaign that ALSO feeds Soak Gate 1's usage floor (≥15 spawns / ≥3 days). Run it from the `campaign-template.md` checklist — its first real external instantiation.

**Suggested shape (adapt to what Altai names as the target project):**
1. Ask Altai which small non-fleet project to document (a candidate: one of the expardus repos, or any repo Altai points at). If none named, propose picking a small local repo and confirm before touching it.
2. Decompose into worker-sized doc tasks on **disjoint files** (safe parallelism, proven to 7-wide): e.g. one worker per module/dir writing/refreshing a README or docstring pass; one worker building a top-level architecture overview; one worker on a quickstart. Give each a task file per §0.2 (write set, anchors, done-criteria, RESULT line, permission mechanism — `bypass` in a trusted repo, or `accept+allowlist` if unfamiliar).
3. Exercise the full lifecycle deliberately (this is the soak evidence): **≥3 workers, at least one `respawn`, one mid-turn `send` steer**, background `fleet wait`, harvest `result`, `fleet doctor` clean at the end.
4. Keep it cheap: haiku/default model, small caps ($3–5/task), doc-only so no worktree needed on the sample repo (workers edit the sample repo directly on a branch there — NOT the fleet repo).
5. Spread spawns across ≥3 distinct days to satisfy the soak-day floor. A slow day extends the gate, never passes it on elapsed time.
6. After: write a `knowledge/projects/<sample>.md` + a lessons entry with friction found, and any `campaign-template.md` amendments. This is real dogfood data on fleet's ergonomics.

**Goal of the exercise:** prove fleet manages a real multi-worker job on an unfamiliar repo end-to-end, surface ergonomic friction, and accumulate the Soak Gate 1 spawn/day count. Report the results to Altai; the sign-off stays Altai's.

---

## Copy-paste continuation prompt

> You are the fleet manager. Trigger the `fleet` skill and operate per its doctrine. Read `docs/NEXT-SESSION.md` first, then `docs/PLAN-PROGRESS.md` (the wave cursor), `knowledge/lessons.md`, and `knowledge/playbooks/campaign-template.md`. Confirm `fleet status` (clean up leftover idle workers) and `fleet doctor` (expect 17/17) before anything.
>
> The self-build is at its readiness boundary: Campaigns 1–2 are merged and verified; Campaign 3+ is GATED behind Soak Gate 1, which only Altai signs — do NOT start any C3+ build wave or self-issue the sign-off.
>
> Your job this session: **dogfood fleet on a small sample project by running a real documentation campaign** (per docs/NEXT-SESSION.md "Your first job"). Ask Altai which project to document (propose one if none given). Run it from the campaign-template checklist: ≥3 workers on disjoint files, at least one respawn and one mid-turn steer, background waits, doctor clean at close. This is a genuine external campaign that also feeds Soak Gate 1's usage floor (≥15 spawns / ≥3 days). Keep it cheap (haiku, small caps, doc-only). Write up friction found in knowledge/. Honor all hard constraints in docs/NEXT-SESSION.md. The soak sign-off stays Altai's — you generate the usage and report, you do not sign.
