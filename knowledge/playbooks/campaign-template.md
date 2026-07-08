# Campaign template — the reusable fleet-campaign instrument

**Version 1.2 (2026-07-09)** — Campaign-2 amendments (first code campaign): merge-gate demo-skip + fixture-restore + revert-the-revert sequence (§5), git-log-is-truth verification checkpoint (§3 g), hook-source demo-test task convention (§2). See `lessons.md#2026-07-09-c2`.
**Version 1.1 (2026-07-08)** — Campaign-1 amendments (descriptive/prescriptive tagging §2; doc-campaign truth gate §4).
**Version 1.0 (2026-07-08)** — first cut, distilled from `docs/PLAN.md` §0 + Campaign-0/Campaign-1 lessons.

**This is a LIVING instrument.** Every campaign runs against it and **amends it in that campaign's knowledge wave** (§8 below): bump the version, date the change, record the friction that forced it. Do not treat it as frozen doctrine — treat it as the accumulated scar tissue of every campaign before yours. The immutable contract is `docs/PLAN.md`; the mutable cursor is `docs/PLAN-PROGRESS.md`; this file is the *how-to* that sits between them.

Each section is a checklist. Copy the relevant ones into your campaign log and tick them; a `[ ]` you cannot honestly tick is a gate you have not passed. Section relevance: doc-only campaigns skip §5 (merge gate) and use the §4 doc-campaign variant; code campaigns run every section.

---

## 1. Turn-one / resume checklist (PLAN §0.5)

Do these in order before any task file is written or any worker spawns:

- [ ] **Read `docs/PLAN-PROGRESS.md` FIRST** (before doctrine load). A non-empty ledger means you are a *resuming* manager — jump to the first non-`done` row; do not restart the campaign fresh.
- [ ] `fleet status` — confirm live-worker baseline (usually zero); note it.
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

**C1 amendment — spec-amendment task files (added Campaign 1):**
- [ ] Tag each folded finding `[UNBUILT — owned by <kernel>]` when its fix is **not yet in shipped code** (prescriptive spec text describing behavior a later code kernel must build). This distinguishes descriptive amendments (true of the code today) from prescriptive ones (a promise the kernel owns).
- [ ] Split the task's "required regressions" into two lists: **"passes today"** (assertions true against current `bin/fleet.py`) vs **"pins unbuilt fixes"** (assertions that will only pass once the owning kernel ships). This prevents the descriptive/prescriptive fix wave C1 hit — a reviewer must not demand green tests for behavior no one has built yet.

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
- [ ] **`knowledge/projects/<project>.md` updated** — capture project-specific facts learned live (bugs, interpreter quirks, landmarks).
- [ ] **Advance `docs/PLAN-PROGRESS.md`** — mark this campaign's rows `done` with commit/evidence refs; committed as part of this step.
- [ ] **Amend THIS template with the campaign's friction** — bump the version line, date it, and fold in whatever this campaign proved that the template did not yet say. This is the mechanism that keeps the instrument alive.
- [ ] Commit everything (`knowledge/` is git-tracked; commit prefix `knowledge:` or `docs:`).
