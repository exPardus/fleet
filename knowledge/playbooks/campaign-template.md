# Campaign template — the reusable fleet-campaign instrument

**Version 1.9 (2026-07-23)** — M-F three-tier re-draft amendments. (1) **RULING-LANDS-FIRST gate** — a binding operator ruling is citable by a wave only once its dated record is a commit **on the branch the wave writes to**; a mid-turn steer is delivery, never provenance. The manager steered a ruling whose commit sat only on `main`; the spec declared the question "SETTLED" against a record its tree could not witness — a manager-owned CRITICAL (ND5) that reversed a fit-for-ratification verdict for a round. Merge the record in, then steer (§3 f). (2) **Receipt-shape evasion is the silent-drop class, third recurrence** — `tools/verify_receipts.py` now errors under `--strict` on receipt-shaped text it cannot classify anywhere in a scanned file (gutters, tabs, tilde fences, inline spans, stray directives, unterminated fences); the founding-artifact replay found 16 evasions where the review's probe knew of 4 — *the artifact knows more than the probe* (§2 receipts gate). (3) **Mutation-test a hardened detector**: the H1 review ran 20 mutations and the new detector's suite survived 6 including a compound suite-green blinding; every surviving mutation needs a named catching test re-proven by re-running that exact mutation (§3 e). (4) **Operator-amendment waves do not count toward the ≤3 reviewer-wave escalation budget** — they are new scope, first-reviewed in the next gate round; say so explicitly in the wave brief so the count stays honest (§3 f). See `lessons.md#2026-07-23-three-tier-ratified`.
**Version 1.8 (2026-07-21)** — M-E amendments (9th live catch + 5 dual-lens gates + 12 fix waves). (1) **VANTAGE gate, extending PROBE-CONTEXT** — a receipt must state *where* it ran (which worktree, which `FLEET_HOME`, which commit), not only *who* ran it. The manager filed a live regression measured from inside a worktree, where an ownership predicate correctly refuses the canonical home's task; the "regression" was `True` before and after the wave and never existed (§2, §3 g). (2) **FOUNDING-INCIDENT gate** — a detector must be replayed against the real artifact of the incident it was built from, before it is believed. A shipped wedge check PASSED on the exact 16h outage it existed to catch, because the test claiming to pin that incident **fabricated two evidence lines that never happened**. Corollary: *when the real artifact exists, the fixture IS the real artifact* (§5). (3) **Demand-driven evidence never carries a count/span threshold** — if evidence exists only because someone retried, a threshold measures the operator, not the system ("adding evidence made the verdict weaker": 1 refusal detected, 2 at 29s missed) (§3 f). (4) **A reviewer-ordered remedy is a fix wave** — re-review it like one; the new-defect hunt has now fired on 6/6 waves, and the one on `me/ul` was minted by the reviewer's own prescribed `skipif`, which could silently disable 17 tests with a green suite (§3 f). (5) **Receipts are executable claims** — `tools/verify_receipts.py` re-runs every pasted receipt in `docs/specs/**`, bound by `tests/test_receipts.py`, resolving each block at its `# at <sha>` pin (a receipt is a claim about a commit, not about HEAD). A verifier needs its own **seed test** before its output is trusted, and *a tool that only DETECTS a class does not prevent it* (§2, §8). (6) **A new shared-suite gate is tested against the tree it will MEET, not the tree it was written on** — the receipt binding was correct in isolation and turned the suite red at the merge gate because two unrelated branches landed first (§5). (7) **`commit only — never push, never open a PR`** belongs in every task file: workers opened draft PRs unbidden in two consecutive campaigns (§2). (8) **The `RESULT:` line is exempt from the token-efficiency clause** — mark it so explicitly; the terseness clause ate it in 3 of 4 first-turn reports (§2). See `lessons.md#2026-07-21-me`.
**Version 1.7 (2026-07-18)** — M-D amendments (2.1.212 vendor break + design gate): (1) **PROBE-CONTEXT gate** — a live-behavior finding must state WHO ran the probe (interactive vs `--bg` worker); a `--bg` worker cannot observe the dead-daemon path (it is itself a live daemon client), so daemon-lifecycle claims from a bg session are structurally incomplete — the post-merge FLEET_LIVE run from the manager's interactive session is the standing verification (§5). (2) **VENDOR-BUMP gate** — run the live pin tier on every `claude` version bump, not just at merge; the 8th live catch was a vendor change (transient daemon), invisible to a review-clean tree (§5). (3) **new-defect-hunt held at 4/4 waves again** and `ESCALATE-beats-3rd-wave` held (both branches closed in 2 waves + final gate); the builder-named error class *"a fix at one call site not its twin; a fallback in a comment not the code"* is a grep-every-call-site + assert-comment-against-code check (§3 f). (4) **design-review-first** for an operator-originated design proposal: no build before a dual-lens design gate; the three-tier gate caught a foundational claim/sid collision a build campaign would have hit only after writing the scheduler (§3 b). See `lessons.md#2026-07-18-md`.
**Version 1.6 (2026-07-17)** — token-efficiency clause (operator ask 2026-07-16, M-D item 2): every task file carries the compressed-output contract (§2 checklist item); tier-boundary messages terse, artifacts full-precision. Companion amendment in `spawn-etiquette.md` (which also corrects the stale `--max-budget-usd` bullet to `--token-ceiling`, refused-at-spawn under native G3).
**Version 1.5 (2026-07-17)** — imported prior art (not campaign scar): exPardus knowledge-librarian safety doctrine folded in — evidence-gated knowledge retirement + per-pass retirement cap (§2 corollaries), source-anchor + verified-date convention for code-asserting knowledge entries (§8). Full design adopted in `docs/specs/phase-5-intelligence.md`; provenance in `docs/PRIOR-ART.md` §"Local prior art".
**Version 1.4 (2026-07-10)** — C4 spec-wave amendments, all one lesson: **an enumeration produced by inspection is wrong.** New §2 GREP-RECEIPT GATE (mandatory for any task specifying a change to code it does not own); authors may never promote their own spec (§3); re-reviews must carry a `SPURIOUS-FIX` verdict (§3); `[UNBUILT]` claims must be grep-verifiable at a stated commit, and prose claims *about* tags must be audited too (§2). See `lessons.md#2026-07-10-c4-spec-portability`.
**Version 1.3 (2026-07-09)** — External dogfood #1 (`stupidbox`) amendments: `fleet respawn` ignores task-file edits — re-pass `--task @file` to change scope (§3 f); own-vs-foreign worker discipline on a shared fleet install before any bulk kill/clean (§1). See `lessons.md#2026-07-09-dogfood-stupidbox`.
**Version 1.2 (2026-07-09)** — Campaign-2 amendments (first code campaign): merge-gate demo-skip + fixture-restore + revert-the-revert sequence (§5), git-log-is-truth verification checkpoint (§3 g), hook-source demo-test task convention (§2). See `lessons.md#2026-07-09-c2`.
**Version 1.1 (2026-07-08)** — Campaign-1 amendments (descriptive/prescriptive tagging §2; doc-campaign truth gate §4).
**Version 1.0 (2026-07-08)** — first cut, distilled from `docs/PLAN.md` §0 + Campaign-0/Campaign-1 lessons.

**This is a LIVING instrument.** Every campaign runs against it and **amends it in that campaign's knowledge wave** (§8 below): bump the version, date the change, record the friction that forced it. Do not treat it as frozen doctrine — treat it as the accumulated scar tissue of every campaign before yours.

**Plan of record + doctrine home (2026-07-24).** The plan of record is the **M-track — `docs/SPEC.md` §18 (M-0…M-G)**. `docs/PLAN.md` (the C1→C8 campaign contract) and `docs/ROADMAP.md` (Phase 1→6) were **retired to superseded history on 2026-07-24** by the settled operator gate *"Two roadmaps, no crosswalk"* (`docs/OPERATOR-GATES.md`). **This file is now the live home of PLAN §0's still-binding campaign doctrine** — the (a)–(h) pipeline, merge gate + revert-on-red, chain-link truth gate, task-file convention, permission mechanisms, W-V discipline, dual-lens and RESULT-contract gates, soak-gate and demand-check checklists all live here, not in the retired PLAN. The inline `PLAN §…` citations below are **historical provenance only** — resolvable in the retained history file, never a live dependency. Companion live homes: worktree/bootstrap isolation → `knowledge/projects/claude-fleet.md` "Bootstrap hazard"; respawn/permission/token-ceiling doctrine → `skills/fleet/SKILL.md` + `knowledge/playbooks/spawn-etiquette.md`; nine invariants / testing tiers / spec-drift → `docs/SPEC.md` §16/§17/§17a. The mutable cursor is `docs/PLAN-PROGRESS.md` (also historical, per its own banner).

Each section is a checklist. Copy the relevant ones into your campaign log and tick them; a `[ ]` you cannot honestly tick is a gate you have not passed. Section relevance: doc-only campaigns skip §5 (merge gate) and use the §4 doc-campaign variant; code campaigns run every section.

---

## 1. Turn-one / resume checklist (PLAN §0.5)

Do these in order before any task file is written or any worker spawns:

- [ ] **Read `docs/PLAN-PROGRESS.md` FIRST** (before doctrine load). A non-empty ledger means you are a *resuming* manager — jump to the first non-`done` row; do not restart the campaign fresh.
- [ ] `fleet status` — confirm live-worker baseline (usually zero); note it. **Dogfood-1 amendment — own-vs-foreign discipline:** the fleet install is **system-wide/shared**, so a *concurrent foreign campaign* (another project's workers, in their own worktrees) can appear in your `status`/`doctor` at any time. Record which names YOU spawn; before any bulk `kill`/`clean`, **retire only names you spawned** — never blanket-retire the registry (you may kill another live campaign's workers). Foreign workers in isolated worktrees are not your concern and keep `doctor` clean.
- [ ] `fleet doctor` — must be clean before anything spawns. (`wt`-absent is a known-fine fallback — detached PowerShell attach; not a failure.)
- [ ] **Doctrine load:** read `knowledge/INDEX.md`, `knowledge/lessons.md` (postmortems), `knowledge/projects/<this-project>.md`, and this template.
- [ ] Pre-flight the tree: `git status`. Commit or stash any authoritative campaign input that is untracked **before** writing task files, or fresh workers cannot read it. Never start a campaign on a dirty tree — ask the human (one message) to commit or stash.
- [ ] **Batch the human touchpoints into one message:** campaign budget envelope (sum-of-caps ceiling including max fix/re-review loops, expected spend noted separately) + any pre-campaign decisions (e.g. POSIX exercise box, GitHub remote authorization). Record every answer as a dated line in `lessons.md` — never session memory.
- [ ] **Seed or advance the ledger (final action of turn one):** write/update `docs/PLAN-PROGRESS.md` with the wave skeleton (`<campaign> | <wave/task> | pending|dispatched|done|blocked|deferred | <commit/evidence> | <date>`); mark this campaign's first wave `dispatched`; commit it before returning to the check-in loop.
- [ ] **Check-in loop, never sleep-loop:** `fleet wait <names...> --all --timeout 300` in a background Bash loop (names are positional-required; there is no bare `--all` form). On each wake: `fleet status` + cost-watch + `fleet peek` proxies (§0.1.8), `fleet result` for finished tasks, verify RESULT lines, per-link pytest where §0.1.9 applies.

---

## 2. Task-file authoring checklist (PLAN §0.2)

Every `--task` is a file at `state/tasks/<name>.md` (gitignored runtime dir). Fill in each line:

- [ ] **Precondition line** (soak-gated campaigns only): first line greps the prior soak gate's signature — *"Verify `SOAK GATE <n> SIGNED: <date> — Altai` exists in `knowledge/lessons.md`; if absent, output `BLOCKED: missing soak sign-off` and stop."*
- [ ] **Goal** — one paragraph.
- [ ] **Exact paths owned** (the write set) + named function/line anchors. NEVER instruct a worker to read `bin/fleet.py` end-to-end (~3000 lines) — Grep the named anchors, read only those regions.
- [ ] **Quoted authority text:** verbatim excerpts of (a) the SPEC/stub section built against AND (b) for every finding folded, the **full finding text + agreed fix quoted from the review doc** — never the plan's one-line parentheticals (Campaign-0: ONE binding fix list, no re-interpretation).
- [ ] **Plan-ID → review-ID mapping embedded** in the file (plan's B/F IDs → review-doc item IDs + quoted text). Workers never grep for a plan-numbered ID; SPEC's appendix carries a *different, settled* F1–F16 series.
- [ ] **Invariants touched** — which of the 9 named invariants, and why each is preserved.
- [ ] **Verbatim done-criteria** — copied from the plan's task table, not paraphrased.
- [ ] **Repo rules block:** `py -3.13`; `bin/fleet.py` stdlib-only single file; forward slashes in hook commands; never Git-Bash `&`; runtime dirs gitignored / `knowledge/` tracked; pytest for unit/hook tests; test-first (paste failing-then-passing output in journal); commit early/small with exact-path staging + index.lock retry; commit-prefix rule.
- [ ] **Permission-mechanism line** (§6 below): states `bypass` / `bypass-with-containment` / `accept+allowlist`; for allowlist, quotes the exact `permissions.allow` entries.
- [ ] **RESULT contract line** required: `RESULT: files=<paths> tests=<N>/<M> spec=<§-ref | no-drift> criteria=<one-line proof per criterion>` + `git log --oneline -3`. Malformed RESULT = task not done. The `spec=` field is mandatory for build tasks (mechanically inherits the anti-drift clause; the merge gate audits it).
- [ ] **BLOCKED-with-evidence rule** stated for environment-dependent kernels: if a probed contract (e.g. an installed-CLI hook event) fails, report `BLOCKED:` with the probe evidence — never build against a guessed contract.
- [ ] **Token-efficiency clause (v1.6, operator ask 2026-07-16):** the task file states "final message terse — the artifact/commits carry the substance" next to the RESULT contract. Tier-boundary messages (brief→supervisor, supervisor→worker steers, worker final messages) are compressed: no narration, no restated task, pointers over pastes. **Full-precision zones exempt, never compressed:** code, commit messages, specs, review verdict files, quoted error text. The clause lives in the task file, never delegated to a plugin (a plugin absent from the worker repo is a silent no-op; a task-file clause always arrives).

**C1 amendment — spec-amendment task files (added Campaign 1):**
- [ ] Tag each folded finding `[UNBUILT — owned by <kernel>]` when its fix is **not yet in shipped code** (prescriptive spec text describing behavior a later code kernel must build). This distinguishes descriptive amendments (true of the code today) from prescriptive ones (a promise the kernel owns).
- [ ] Split the task's "required regressions" into two lists: **"passes today"** (assertions true against current `bin/fleet.py`) vs **"pins unbuilt fixes"** (assertions that will only pass once the owning kernel ships). This prevents the descriptive/prescriptive fix wave C1 hit — a reviewer must not demand green tests for behavior no one has built yet.

**C4 amendment — THE GREP-RECEIPT GATE (added Campaign 4; the most expensive lesson yet):**

Any task whose output **specifies a change to code the task does not own** (a spec, a review, a plan
amendment, a schema proposal) MUST enumerate the affected call sites **by `grep`**, and:
- [ ] **paste the grep command AND its output** into the artifact, in a fenced block;
- [ ] **pin it to a stated commit** (`# at <sha>`);
- [ ] specify against that pasted list, never against a list built by reading.

A call-site list without its receipt is a defect, and the reviewer must fail the task for it.

*Why this is a hard gate.* In C4 an enumeration built by inspection was wrong **five times**: fix
wave 1 (broke F1 → double-launch), fix wave 2 (broke FW2-R1 → every Linux worker born dead), the
`PLAN.md` contract itself (a 3-edit list that was really 11 — written by a reviewer, ratified by the
human, believed by the manager), a LOW too small to seem worth a grep (which reintroduced the exact
F20 drift the paragraph it edited was warning about), and the manager's own correction sweep (fixed
1 line, left 7 false `[UNBUILT]` tags standing). Every one was invisible to two adversarial
reviewers reading carefully, and every one took a single `grep` to find. **Reading a document does
not verify a claim about code.**

Corollaries, each earned:
- [ ] **`[UNBUILT]` claims are grep-verifiable or they are false.** Any spec text tagging a fix
      `[UNBUILT — owned by <kernel>]` must reproduce as no-matches against `bin/fleet.py` at a stated
      commit. Seven false tags survived in `SPEC.md` from 2026-07-08 (C2 shipped the kernels; nobody
      re-tagged) — a `port-adapter-a` builder reading §12 would have rebuilt four working features.
      This is F20's failure, seven more times.
- [ ] **Audit the prose, not just the tags.** A `grep "[UNBUILT"` misses a *sentence* asserting a
      field is prescriptive. Also grep `PRESCRIPTIVE`, `not shipped`, lowercase `unbuilt`. A false
      sentence about a tag misleads a builder exactly as well as a false tag.
- [ ] **Retire a stale pin by MOVING it**, not deleting it. A §12 regression moved from "pins unbuilt
      fixes" to "passes today" keeps protecting its fix; a deleted pin is a silent regression wearing
      a cleanup's clothes.
- [ ] **Retirement is evidence-gated and capped** (v1.5, exPardus librarian doctrine). No knowledge
      entry, pin, or `[UNBUILT]` tag is retired/moved on a verdict alone — a reviewer's, a judge
      model's, or the manager's own reading. Retirement needs its deterministic receipt (grep at a
      stated commit showing the anchor gone/moved), pasted where the retirement happens. Cap
      retirements per pass (a sweep proposing to retire many entries at once is more likely a broken
      premise than mass drift — C4's 7 false tags came from exactly one unswept assumption); over the
      cap, flag for review instead of retiring.
- [ ] **A fix wave's failure mode is a new defect one call site away.** Both C4 fix waves closed
      their target finding and broke an adjacent thing, in the same direction, for the same reason.
      Budget a re-review for every fix wave; never merge a fix wave on the author's own report.

**C4 amendment — spec review authority + verdict vocabulary:**
- [ ] **An author may NEVER promote its own spec.** Put "leave `Status:` at `drafting`" in the
      author's task file and the promotion authority in the reviewer's. Check the `Status:` line after
      every author turn — one author set its own spec `ready-for-build` and the manager reverted it
      (`87a85de`). A spec cannot ratify itself. The same rule bound the manager: having authored a
      correction, the manager spawned a fresh verifier rather than certify it.
- [ ] **Every re-review must carry a `SPURIOUS-FIX` verdict** alongside `FIXED`/`NOT-FIXED`/
      `REGRESSED`. `DISPUTED: none` across N findings is a smell, not a virtue: an author who accepts
      everything may "fix" something never broken, baking the reviewer's error into the contract. (C4
      checked; found none; all 19 findings were real. Worth the check anyway.)
- [ ] **Grant WSL/repro authority explicitly in the task file.** A worker that doesn't know it has a
      POSIX box correctly tags claims `[UNVERIFIED]` instead of inventing results — which is right, but
      leaves evidence on the table. Seven C4 workers, zero fabricated experiments, verified by
      re-running every pasted receipt at its stated commit. Keep that record: state that fabricating a
      result is unforgivable, and then actually re-run the receipts.
- [ ] **`ESCALATE` beats a third fix wave.** The ≤3-loop rule is real. When two consecutive fix waves
      each close their target and break a neighbour, the defect is structural (in C4: a portability
      spec was specifying *core* plumbing, and the plumbing kept growing). Escalate to the human with
      a named restructuring, not a third list of findings.

**C2 amendment — hook-source-specific live demo tests (added Campaign 2):**
- [ ] Any task that writes a `FLEET_HOOK_SOURCE=worktree` demonstration test MUST instruct the worker to **`pytest.skip` under the default `main` hook-source, never hard-assert** the source. A `assert HOOK_SOURCE == "worktree"` is correct only for a pre-merge worktree run; it turns the post-merge merge gate (which defaults to `FLEET_HOOK_SOURCE=main`) RED and cost C2 a full revert+refix+re-merge for a one-line scoping bug. Require the RESULT line to show the test **collects-and-skips** in the default `main` run.

---

## 3. The (a)–(h) quality-gate pipeline checklist (PLAN §0.3)

Instantiate per phase; every gate is a distinct wave:

- [ ] **(a) Spec task** — claim the stub (`Status: drafting (<date>)`, commit immediately); answer *every* open question (mark resolved, delete none); add the mandatory `## Invariants touched` section; check the IDEA-FORGE §5 graveyard for every addition.
- [ ] **(b) Adversarial spec review** — independent worker (strongest model) attacks the draft; findings carry exact quotes; ends with a disposition appendix. **Dual-lens per Campaign-0:** run the spec lens AND the break lens — the adversarial lens finds what the spec lens approves (4/5 C0 tasks got "Approved" from spec while break returned proven BREAKS). `Status: ready-for-build` only after disposition.
- [ ] **(c) Build tasks** — test-first (paste red-then-green); worktree for code; chained if same-file; per-link truth gate (§4).
- [ ] **(d) Code review** — independent worker reviews the **full campaign diff** for spec conformance.
- [ ] **(e) Adversarial break review** — separate worker actively tries to break the increment: lock races, kill-mid-launch, spaced/CRLF paths, handle-in-use on Windows, hook crash paths. BOTH lenses.
- [ ] **(f) Adjudication + fix waves** — manager merges (d)+(e) into **ONE binding fix list anchored to function roles, not line numbers**. Fixes go to the **ORIGINAL builder via `fleet send`** (respawn first if past ~30 turns; a fresh fixer only if the session is dead/cleaned) — preserves context, avoids re-interpretation. **Re-review after EVERY wave** (each wave introduces ~1 new issue). Max 3 waves, then escalate to the human.
  - [ ] **Dogfood-1 amendment — respawn does NOT re-read the task file.** `fleet respawn <name>` re-prompts with the **original task snapshot stored in the registry (TRUNCATED), or a `--task` override** — editing `state/tasks/<name>.md` after spawn has **zero effect** on a plain respawn (verified against `cmd_respawn`). To change a worker's scope on respawn, always re-pass **`fleet respawn <name> --task @state/tasks/<name>.md`** (respawn `--task` accepts `@file`). For any long `@file` task, re-pass `--task @file` on respawn regardless, so the truncated registry snapshot does not silently drop task detail.
- [ ] **(g) Verification checkpoint — W-V discipline:** the manager **personally re-runs** `pytest`, `fleet doctor`, and each done-criterion, evidence pasted into the campaign log. A phase never closes on worker say-so.
  - [ ] **C2 amendment — `git log` is the only truth for "did the turn land":** a worker's turn is "done" ONLY if `git log` in its worktree shows the expected commit. `fleet result` / `cost_usd` are **unreliable when the turn errored** (transient Anthropic **529 Overloaded** mid-turn leaves the worker idle, cost FROZEN, no commit, journal unchanged — and `fleet result` itself may 529). Re-sending a git-committed fix task is safe (idempotent-ish); **revert any partial uncommitted artifacts** (e.g. dirtied fixtures) before re-send.
- [ ] **(h) Knowledge loop** — the `*-knowledge` task appends to `lessons.md` + updates INDEX + `knowledge/projects/` + commits. **Anti-ritual check:** the lessons entry MUST name ≥1 concrete process change ("what to do differently" — normally an amendment to THIS template). A lessons entry with no process change is rejected.

---

## 4. Chain-link truth gate checklist (PLAN §0.1.9)

For any same-file (`bin/fleet.py`) chain, between every link:

- [ ] Manager personally runs `py -3.13 -m pytest tests/` **in the worktree** before dispatching the next link.
- [ ] Manager confirms the finished link's RESULT-line pass count **matches the actual run**. Mismatch = the link is NOT done; the discrepancy goes back to the original builder via `fleet send`.
- [ ] (Suite runs ~8s — a per-link check is free vs a same-file fix wave discovered three links later, Campaign-0's documented bottleneck.)

**Doc-campaign variant (added Campaign 1 — the truth gate for doc campaigns with no pytest):**
- [ ] **Anchor + witness grep per finding:** each injected block carries an HTML anchor comment (`<!-- F## -->`) AND a **witness sentence** — one load-bearing sentence quoted verbatim from the review-doc's agreed fix. Manager greps anchor + witness per file; a hollow anchor above vacuous prose fails the witness match. Presence of the anchor alone does not pass.
- [ ] **Manager spot-checks any spec-vs-code claim** against `bin/fleet.py` before ordering a fix. A reviewer asserting "the spec contradicts the code" must be verified against the actual source — do not order a fix wave on an unverified spec-vs-code claim (Campaign-1's descriptive/prescriptive trap).
- [ ] **Read blocker-class injections in full** (not by grep) against their review-doc text before closing.

---

## 5. Merge gate checklist (code campaigns only — PLAN §0.1.3)

At the campaign boundary. Pre-merge FIRST, explicit red-path AFTER:

- [ ] **Pre-merge, on the worktree branch:** `fleet status` shows **zero turns in flight**.
- [ ] **C2 amendment — restore the committed fixture corpus before EVERY git-state check:** `git checkout -- tests/fixtures/streams/`. The `FLEET_LIVE` harness is **non-idempotent on the corpus** — it re-captures `tests/fixtures/streams/*.jsonl` on every run, dirtying the tree and poisoning any pre/post-merge git-state gate. (Phase-6/quality backlog: make the harness write captured streams to a temp dir unless `FLEET_CAPTURE_CORPUS=1` is set.)
- [ ] Full `py -3.13 -m pytest tests/` (unit + hooks) green **in the worktree**.
- [ ] **C2 amendment — hook-source demo tests collect-and-skip under default `main`:** in the pre-merge default run (`FLEET_HOOK_SOURCE=main`), confirm every `FLEET_HOOK_SOURCE=worktree` demonstration test **SKIPS**, does not FAIL. A hard-asserted worktree source turns the post-merge gate RED (C2 paid a full revert cycle for this). If any such test fails under `main`, fix the test scoping in the worktree **before** merging.
- [ ] **Additive-schema diff check** — registry/`state/fleet.json` changes are additive (readers default missing fields, writers preserve unknown); no migration that breaks the live `state/fleet.json` mid-campaign.
- [ ] **Spec-vs-code drift check** — manager diffs the campaign's code changes against SPEC/stub sections; confirms every task's RESULT `spec=` field is consistent with the diff. Any red = no merge; fix task in the worktree.
- [ ] **Merge** worktree branch → `fleet-impl`. Then, **with no fleet command other than the gate checks between merge and green**, run in order: `FLEET_LIVE=1` integration tier → `fleet doctor` → `fleet init` re-run iff `worker-settings.template.json` changed → post-merge hook-smoke.
- [ ] **Post-merge hook-smoke** (standing rule) if hooks/template touched: spawn one throwaway haiku worker in a temp dir (budget ≤$0.50); confirm via its journal/mailbox that **both** hook events fired on the new hooks **before dispatching any real worker**.
- [ ] **Revert-on-red (explicit):** any post-merge red → the manager's **next action is `git revert -m 1 <merge>` of the merge commit** on `fleet-impl` (restoring the known-good live install), then a fix task in the worktree. **Never fix-forward on the live branch; never dispatch any worker between a red gate check and the revert.** *(C2 exercised this end-to-end and it worked — the known-good install stayed live the whole time; the revert lever is proven, not theoretical.)*
- [ ] **C2 amendment — revert-path re-merge sequence:** after a `git revert -m 1 <merge>` you **cannot plain-re-merge** the fixed branch — git sees it as already merged and no-ops. The exact sequence: **(1) `git revert <the-revert>`** (restores the reverted code) **then (2) `git merge <branch>`** (picks up the new fix commit). Follow this so the next revert→refix→re-merge does not stall.

---

## 6. Permission-mechanism decision checklist (PLAN §0.4)

Fleet workers are detached headless `claude -p` sessions — **there is no human at a prompt.** `--permission-mode acceptEdits` auto-approves *file edits only*; print mode **auto-denies** un-allowlisted Bash/network/MCP. So bare `accept` is headless-undeliverable for any command-running task. Pick exactly one, justified in the task file:

- [ ] **`bypass`** — one-line test: *trusted grind in this known repo, no live processes/network/secrets.* (Doc tasks, in-repo edits.)
- [ ] **`bypass-with-containment`** — one-line test: *must run arbitrary live processes / kill PIDs / spend money, and an allowlist is impractical.* Requires written containment in the task file: temp FLEET_HOME, throwaway repo, worktree isolation, per-run budget ceiling, kill-targets restricted to harness-spawned PIDs. (Live-integration harness, watch-accept-tests, prov-live-demo.)
- [ ] **`accept+allowlist`** — one-line test: *network/secrets argue for a narrow, named capability.* Mode `accept` PLUS a manager-provisioned scoped `permissions.allow` block written to `<worktree>/.claude/settings.json` **before spawn** (exact entries quoted in the task file; settings file excluded from the merge). (port-ci, tg-live, web-live-check.)
- [ ] **Reminder:** bare `accept` is never a sanctioned mechanism for a command-running task — it auto-denies headlessly. `plan` first turn is fine for genuinely unfamiliar territory.

---

## 7. Soak-gate checklist (PLAN §0.2.1 + soak-gate definitions)

> **Note (2026-07-24):** the **specific C-campaign soak gates** (Soak 1 / 1.5 / 2 / …) were **retired with the C/soak framing** (settled gate, `docs/OPERATOR-GATES.md`); the M-track (`docs/SPEC.md` §18) carries no soak gates, so **no live milestone gates on a `SOAK GATE <n> SIGNED` line today**. This section survives as **generic doctrine** for any *future* usage-denominated gate the operator may introduce — do not read it as an active blocker on current work.

Soak gates are **usage-denominated, never calendar-denominated** — a slow week extends the gate, it never passes on elapsed time:

- [ ] **Pass condition is a usage floor** (spawn count / pushed-commit count / workday count across ≥N distinct days) fed by the human's named workload queue — never "a week elapsed."
- [ ] **Audit against independently known ground truth** at gate-close (dispatched audit task, never the detector grading itself): `fleet doctor` clean; mail-ledger reconciliation (`mail_sent` → `mail_drained`/stream-log/operator-disposition); phantom-live audit (`status_changed` history vs journal evidence); a mandatory dated incident-log section in `lessons.md` ("0 incidents observed" if clean).
- [ ] **§0.2.1 precondition-grep enforcement:** the next phase's build task files carry the precondition line that greps the signature. This converts the gate from manager memory into a machine-checkable precondition.
- [ ] **Human signs `SOAK GATE <n> SIGNED: <date> — Altai`** in `lessons.md` against the audit section (not vibes).
- [ ] **Spec-during-soak allowed, build-not:** a next-phase *spec task* (docs-only) may run during the prior phase's soak; the *build* may not.
- [ ] **Demand-check gates BUILD only:** before a demand-gated build wave, ask the human one question — *"Do you feel the friction this phase removes, today?"* The spec task and its review always run on schedule; only the build waves park in the backlog on a "no." Record the answer either way in `lessons.md`.

---

## 8. Knowledge-wave checklist (PLAN §0.3 h + §0.6)

The campaign's closing wave. Every item is required to close:

- [ ] **`lessons.md` entry** — what worked / what stalled / prompt patterns, AND **≥1 concrete process change** (the anti-ritual gate; normally an amendment to THIS template). No process change = entry rejected.
- [ ] **`INDEX.md` updated** with pointers to the new lessons.
- [ ] **Anchor code-asserting entries** (v1.5): any new knowledge entry/pin whose claim is about code
      (a function's behavior, a flag, a tag's truth) names its source anchor (`file:function` or
      `file:line`-ish) and its verified-at date/commit, so a later mechanical ref-check (Phase 5
      librarian, `docs/specs/phase-5-intelligence.md`) can grade it ok/moved/missing instead of a
      human re-reading everything. Narrative lessons (what-happened prose) are exempt — do not
      atomize them.
- [ ] **`knowledge/projects/<project>.md` updated** — capture project-specific facts learned live (bugs, interpreter quirks, landmarks).
- [ ] **Advance `docs/PLAN-PROGRESS.md`** — mark this campaign's rows `done` with commit/evidence refs; committed as part of this step.
- [ ] **Amend THIS template with the campaign's friction** — bump the version line, date it, and fold in whatever this campaign proved that the template did not yet say. This is the mechanism that keeps the instrument alive.
- [ ] Commit everything (`knowledge/` is git-tracked; commit prefix `knowledge:` or `docs:`).
