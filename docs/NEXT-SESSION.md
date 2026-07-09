# Next-session handoff — fleet manager

**Written:** 2026-07-10, at the close of the C4 spec wave. Read this FIRST, then `docs/PLAN-PROGRESS.md` (the live wave cursor), then `knowledge/lessons.md` and `knowledge/playbooks/campaign-template.md` (**now v1.4 — the GREP-RECEIPT GATE is new and mandatory**).

---

## Where things stand

**Campaigns 1–2: closed and merged.** The fleet can safely modify itself (revert path exercised for real). `fleet doctor` = 18/18 PASS. 708 tests / 12 skipped.

**Phase 1.6 (terminal surface): built** — statusline, `/fleet:*` commands, SessionStart briefing, plugin package, `fleet init --statusline`, plus security fixes (a read-only slash command could run `fleet kill`/`fleet clean`; provenance guard on kill/clean/respawn).

**C4 spec wave: CLOSED 2026-07-10.** `docs/specs/portability.md` is **`ready-for-build`**. `docs/SPEC.md` is **v2.2** with appendix **F33** (boot identity) ratified. 7 workers, ~$80, 22 commits, **zero code touched**.

**External dogfood #1 (`stupidbox`): done.** Verdict recorded: *the fleet works in the wild.*

## THE GATE — unchanged, and only Altai signs it

C4's **build** waves (and all of C3+) are gated behind **Soak Gate 1**. Pass condition: **≥15 spawns across ≥3 distinct days** of real fleet use on ≥1 **non-fleet** project, `fleet doctor` clean at gate-close, zero incidents per the PLAN §Campaign-3 audit. Altai writes `SOAK GATE 1 SIGNED: <date> — Altai` in `knowledge/lessons.md`.

| | |
|---|---|
| **Day 1 (2026-07-09)** | 12 launches on `stupidbox`, doctor 17/17, 0 incidents |
| **2026-07-10** | 7 workers — but on the **fleet repo**, so they exercise the lifecycle and do **not** advance the non-fleet floor |
| **Remaining** | **≥2 more distinct days** of non-fleet use, then the gate-close audit |

**You may NOT:** start any C4+ BUILD wave; sign the soak gate yourself.
**You MAY:** run real external campaigns that generate soak usage; do housekeeping; run further *spec* tasks (`spec-watchtower`, `spec-providers` — PLAN permits spec tasks during soak).

## Read this before you write a single task file

**campaign-template v1.4 added the GREP-RECEIPT GATE.** It is not ceremony. It is the distilled cost of C4:

> An enumeration produced by inspection is wrong. In C4 it was wrong **five times**, in five artifacts, by five actors — fix wave 1, fix wave 2, the **ratified `PLAN.md` contract itself**, a LOW too small to seem worth a grep, and the **manager's own correction sweep**. Every one was invisible to two adversarial reviewers reading carefully. Every one took a single `grep` to find.

Any task whose output specifies a change to code it does not own **must** enumerate the call sites by `grep`, **paste the command and its output**, and pin it to a commit. A list without its receipt is a defect; the reviewer fails the task for it.

Corollaries (all in the template):
- **`[UNBUILT]` claims are grep-verifiable or they are false.** Seven false tags sat in `SPEC.md` from 2026-07-08 because C2 shipped `harden-fleet-b/-d/-e` and nobody re-tagged. A builder reading §12 would have rebuilt four working features.
- **Audit the prose, not just the tags.** `grep "[UNBUILT"` cannot see a *sentence* asserting a field is prescriptive.
- **Retire a stale pin by MOVING it**, never deleting it. A deleted pin is a silent regression wearing a cleanup's clothes.
- **No author promotes its own spec.** One tried; the manager reverted it (`87a85de`). The rule then bound the manager: having authored a correction, the manager spawned a fresh verifier — which **refused to promote** and found the 7 tags.
- **`SPURIOUS-FIX` is a required re-review verdict.** `DISPUTED: none` across N findings is a smell.
- **`ESCALATE` beats a third fix wave.** Two waves each closing their target and breaking a neighbour = the defect is structural.

## Hard constraints (unchanged — violating any is stop-and-ask)
- Code-touching workers run in a **git worktree**, NEVER in `C:\proga\claude-fleet`. At most ONE `bin/fleet.py` writer alive fleet-wide.
- No `launch_turn`/hook/parser change merges without a green `FLEET_LIVE=1` run executing the changed code.
- Never read `bin/fleet.py` end-to-end (grep named anchors). Same for workers via their task files.
- Every task under one of the three §0.4 permission mechanisms. Bare `accept` is headless-undeliverable.

## Fleet operating notes
- Call the CLI by full path from the MAIN install: `py -3.13 bin/fleet.py <cmd>` (cwd `C:\proga\claude-fleet`).
- **`fleet result`/`peek` crash on unicode** (cp1252): prefix `PYTHONIOENCODING=utf-8`. Still unfixed.
- **`git log` is the ONLY truth a turn landed.** A transient **403** killed a turn mid-flight exactly as a **529** did in C2: `fleet result` returned the auth error as the worker's "answer", `cost_usd` froze, **zero commits landed**. Generalizes past overload errors.
- A worker at/over its cumulative `max_budget_usd` **refuses `send`**. Use `respawn --task @file --max-budget-usd <higher>` — journal survives; the registry stores the task **TRUNCATED**, so always re-pass `--task @file`.
- **WSL Ubuntu exists on this box** and is real repro authority for Linux claims. **Grant it explicitly in the task file** — a worker that doesn't know it has a POSIX box correctly tags claims `[UNVERIFIED]` rather than inventing results. 7 C4 workers, **zero fabrications**, verified by re-running every pasted receipt at its stated commit.
- **The install is system-wide.** A concurrent foreign campaign shows up in your `status`/`doctor` — during this very session another session committed to `fleet-impl` (`d7cf5b0`, `1534b87`, `bc781c0`). **Retire only names you spawned.** Never blanket-`kill`.
- The live harness overwrites `tests/fixtures/streams/` — `git checkout -- tests/fixtures/streams/` before any git-state check.

## Your job next session

1. **Accrue Soak Gate 1 usage — day 2 of ≥3, on a NON-FLEET project.** Extend `C:\proga\stupidbox`, or whatever Altai points at. Same recipe: haiku, `bypass`, small caps, disjoint files, background `fleet wait`, doctor clean at close, knowledge entry after.
2. When the floor is met (≥15 spawns / ≥3 distinct days), dispatch the **gate-close audit** per `campaign-template.md` §7 — doctor clean, mail-ledger reconciliation, phantom-live audit, dated incident-log section — and hand it to Altai. **You do not sign it.**
3. Optional during soak (docs-only, PLAN-permitted): `spec-watchtower` or `spec-providers`. Apply the v1.4 receipt gate from the first line.

## Open, carried forward
- **Phase 1.6 done-criteria never verified live:** D5 (a real spawned worker receives **no** SessionStart briefing) and statusline-survives-corrupt-registry. Tracked `pending` in PLAN-PROGRESS. Worth a real haiku spawn + fault injection before 1.6 is called done.
- **F23 (LOW):** `--token-ceiling` ships, but the *provider-side* enforcement half does not. Precisely tagged, not flattened.
- Worktree `C:\proga\claude-fleet-wt\c2` still exists (merged). `git worktree remove` when convenient.

---

## Copy-paste continuation prompt

> You are the fleet manager. Trigger the `fleet` skill and operate per its doctrine. Read `docs/NEXT-SESSION.md` first, then `docs/PLAN-PROGRESS.md`, `knowledge/lessons.md`, and `knowledge/playbooks/campaign-template.md` (**v1.4 — the GREP-RECEIPT GATE is mandatory: any task specifying a change to code it does not own must enumerate call sites by grep, paste the command + output, and pin it to a commit**). Confirm `fleet status` and `fleet doctor` (expect 18/18) before anything.
>
> The C4 spec wave is CLOSED: `docs/specs/portability.md` is `ready-for-build`, `docs/SPEC.md` is v2.2 with F33 ratified, zero code was touched. C4's **build** waves and all of C3+ remain **GATED behind Soak Gate 1**, which only Altai signs — do NOT start a build wave or self-issue the sign-off.
>
> Your job: **accrue Soak Gate 1 usage — day 2 of ≥3, on a NON-FLEET project** (extend `C:\proga\stupidbox`, or whatever Altai points at). haiku, `bypass`, small caps, disjoint files, background waits, doctor clean at close, knowledge entry after. Remember: `fleet respawn` ignores task-file edits — re-pass `--task @file`; a worker over its budget ceiling refuses `send`; `git log` is the only truth a turn landed (a transient 403 or 529 freezes `result`/`cost` with zero commits); retire only the worker names you spawned — the install is shared and foreign campaigns appear in your `status`. When the floor is met (≥15 spawns / ≥3 distinct days), dispatch the gate-close audit per §7 and hand it to Altai. **You do NOT sign the soak gate, and you do NOT start any build wave.**
