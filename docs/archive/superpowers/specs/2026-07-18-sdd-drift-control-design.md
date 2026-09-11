# SDD / drift-control subsystem — design (M-F candidate)

**Status:** v4 — operator-ratified 2026-07-20 (R1–R4, §2/§14); build-ready pending the M-F slot. Folded round-1 (4 lenses: correctness, doctrine, simplicity, feasibility) + round-2 new-defect-hunt (8 findings incl. 1 CRITICAL RCE the round-1 fold introduced; 2026-07-18). Decisions ratified; folds into `docs/SPEC.md` as a first-class § when built (R4).
**Author:** manager session (supervisor claim-holder). Promotion is operator-gated — the author never self-promotes.
**Parent spec:** `docs/SPEC.md` v3 (§4 registry, §5 verdict engine, §6 dispatch choke point / `compose_prompt`, §8 hook boundary, §12 supervisor, §14 views, §16 invariants, §17 tests).
**Prior art scanned:** spec-kit, AWS Kiro, OpenSpec, Tessl, BMAD, Cline/Cursor; EARS, Gherkin, design-by-contract, ADR; Claude Code compaction surfaces, LangGraph/CrewAI/Swarm/AutoGen, OpenHands/Devin, arXiv 2601.04170 "Agent Drift". Summary in §11.

**Round-1 receipts that reshaped this draft (grep-verified against `bin/fleet.py`):** `compose_prompt` @887 is the composer (params `name, cwd, task, sid, journal_path`); `dispatch_bg` @6621 only writes the finished `prompt_body` @6645 and appends one unconditional `--add-dir tasks_dir()` @6659. `_cmd_respawn_native`/`cmd_respawn` @3959 rebuilds via `new_worker_record` @591 (fixed key set @606-659, no `**kwargs`) and hand-copies only enumerated fields @3794-3861 — **any field not explicitly copied is lost.** `_restamp_after_steer` @6331 mutates in place (preserves other fields). `postcompact_journal.py` appends a journal-file line @176-179 and **emits nothing to stdout** (no context injection); the only context-injecting hook is `posttooluse_mailbox.py` @122-128. `stop_mailbox.py` blocks via `print(json.dumps({"decision":"block","reason":…}))` @194 then `sys.exit(0)` @203, capped by Claude Code's native 8-block force-allow @11-13. `pin_pass_path`/`record_pin_pass` @110-130 + `_write_json_atomic` @6879 (temp + `os.replace`, atomic on NTFS) = the reusable atomic-stamp pattern. `sys.executable` is the in-module Python-subprocess doctrine @5248/@5256/@5562. 21 doctor checks, note-only = `ok=True` always @5366-5373. `tomllib` is stdlib in 3.13 but **read-only** (no `dump`).

---

## 1. Problem

The fleet runs N workers per campaign across long horizons with context compaction, fork-steer (sid rotation), and respawn (context reset). Three drift surfaces (arXiv 2601.04170 taxonomy):

- **Semantic drift** — a worker's output deviates from intent (scope creep, wrong impl, under-delivery).
- **Coordination drift** — N workers on one campaign diverge from each other / collide on the same files.
- **Worker↔supervisor drift** — a worker's understanding diverges from the supervisor's intent after compaction/respawn.

Today the fleet's anti-drift discipline lives in the campaign-template + knowledge doctrine, **enforced only by the manager's judgment** — nothing in `bin/fleet.py` binds a worker to a contract or detects when it has left one. SDD moves the contract into a machine-checkable artifact every worker binds to and the manager verifies deterministically at a gate.

**The genuinely-new machine value (what fleet cannot do today):** (a) a *deterministic acceptance gate* the manager currently eyeballs, and (b) an *on-disk shared contract* every worker re-reads and that survives handoff/compaction. Everything else in the surrounding doctrine (adversarial review, no-self-promotion, grep receipts, respawn-as-reset) the manager already executes; SDD encodes only the two new things and leans on existing doctrine for the rest.

**Non-goal:** replacing `docs/SPEC.md` or the durable design-spec flow. A campaign spec is a *runtime binding contract for one fleet run* against a *target project*; it `links:` back to the durable design spec it implements.

## 2. Decisions

Locked by operator brainstorming (2026-07-18): (1) built subsystem + doctrine (M-E has since shipped; this is now the M-F candidate); (2) drift detection = deterministic tier decides, judge tier advisory-only; (3) one campaign spec, per-worker slices; (4) hybrid enforcement (cheap scope-fence blocks in a hook; full verify at the gate); (5) spec is gated `proposed → review → accepted`, workers refuse a non-accepted spec.

**Ratified by the operator 2026-07-20** (closing the §14 residuals; these are now binding, not recommendations):

- **(R1) Phase-1 gate ships first, behind an on/off feature flag.** `sdd.enabled` (default **off**) gates the whole subsystem so it can be tested without touching existing campaigns; Phase-2's live fence lands behind the same flag once Phase-1 is proven in a real campaign. A flagged-off fleet behaves exactly as today — no spec fields consulted, no verb effects, no hook.
- **(R2) Both scopes: a whole-spec scope AND per-worker slices.** Not either/or — the spec always carries a minor whole-spec `scope_allow`/`scope_deny` (the campaign-wide floor every worker is bound by) and slices layer a narrower per-worker fence on top. Effective scope = slice ∩ whole-spec; a slice can only *narrow*, never widen (a slice glob escaping the whole-spec scope → exit 2).
- **(R3) Both judge paths.** Keep the doctrine step (manager spawns its adversarial reviewer) **and** build `spec verify --judge` to auto-dispatch a reviewer subagent. Still advisory in both forms — the judge never changes the exit code (decision 2 stands).
- **(R4) Specs are git-tracked from birth** in `docs/specs/campaigns/<campaign>.md`, not runtime `state/`. Once SDD ships, **it folds into `docs/SPEC.md` fully** as a first-class section, not a pointer.

Resolved after review (were sub-decisions / open questions; rationale inline in the sections):

- **Format = fenced ```json block** (not TOML). `tomllib` is read-only stdlib — the mutating verbs need a writer; `json` round-trips in stdlib. (doctrine-1)
- **Two criteria kinds: `files` + `pytest`.** `grep` dropped — a grep assertion *is* a pytest node, and §17 already mandates a unit test per feature. (simplicity-4)
- **Enforcement is staged: Phase 1 = gate-first (no hook); Phase 2 = the live Stop-hook fence** — both behind `sdd.enabled` (R1). The fence is the riskiest, most-defect-dense piece and catches over-reach only; the gate catches the same over-reach plus under-delivery with zero hook-boundary risk. Phase 2 ships once Phase-1 is proven in a real campaign and the §6a fixes are built and pinned. This honors decision (4) while sequencing risk. (adversarial-1/3/6/7/10, simplicity-1/5)
- **Both scopes (R2).** Whole-spec `scope_allow`/`scope_deny` is always present (the campaign floor); per-worker slices narrow it. Effective scope = slice ∩ whole-spec; a slice glob escaping the whole-spec scope → exit 2, as does a pattern-domain intersection between two slices' `scope_allow`. (simplicity-6, open-Q6, the operator's "between workers" ask)
- **Both judge paths (R3).** `spec verify --judge` auto-dispatches a reviewer subagent **and** the campaign-template doctrine step stands. Advisory in both forms — the judge never moves the exit code. (decision-2)
- **No author-supplied executable input** (round-2 F1, CRITICAL). The machine block carries only *data* the verifier interprets — criteria `nodes`, scope globs. The runner (`sys.executable -m pytest`) and the tree (`project_root` = the bound worker's `cwd`) are **derived, never author-set**, and `spec accept` signs an `accepted_digest` over the executable fields that `verify` re-checks — because a bound worker has write access to the spec dir (`--add-dir`) and could otherwise rewrite the contract that gates it into an RCE at the manager's gate. **Git-tracking the spec (R4) adds a second, independent tamper surface: a worker edit dirties the fleet worktree and shows up in `git diff`.**

## 3. Spec artifact

`docs/specs/campaigns/<campaign>.md` — one file per campaign, **git-tracked from birth** (R4). Not a runtime artifact: a campaign contract is durable history worth versioning, its edits are reviewable in `git diff` (a second tamper surface over `accepted_digest`, §5), and it survives machine loss and supervisor handoff without an archive step. No `logs/archive/` move on close — git *is* the archive; `spec supersede` marks the lifecycle transition and the file stays. Two halves.

### 3a. Machine block — a fenced ```json block

The first fenced ```json block in the file is the machine contract; `json.loads` parses it, `json.dumps` + `_write_json_atomic` rewrites it (the read+write path the mutating verbs need). Prose-free executable fields only.

````markdown
```json
{
  "spec": "md-sdd",
  "status": "proposed",
  "author": "altai",                     // durable actor, NOT a rotating incarnation id (§8)
  "accepted_by": "",                     // set by `spec accept`; MUST differ from author
  "reviewed_by": "",                     // review-doc ref naming a reviewer != author
  "superseded_by": "",
  "links": ["docs/SPEC.md#16", "supervisor/GOALS.md"],
  "accepted_digest": "",                 // sha256 of executable fields, stamped by `spec accept`; verify refuses on mismatch (F1)
  // NO author-supplied project_root or runner: project_root is derived from the bound worker's cwd,
  // the runner is fixed to `sys.executable -m pytest` — free author argv/path is RCE at the gate (F1).
  "slices": {                            // OPTIONAL; omit for a single whole-spec scope
    "md-verifier": { "scope_allow": ["bin/fleet.py", "tests/test_spec.py"],
                     "scope_deny": ["state/**", "logs/**", "mailbox/**"], "criteria": ["C1"] },
    "md-hook":     { "scope_allow": ["bin/hooks/**", "worker-settings.template.json", "tests/test_hooks.py"],
                     "scope_deny": ["state/**", "logs/**"], "criteria": ["C2"] }
  },
  "scope_allow": ["bin/fleet.py", "bin/hooks/**", "tests/**"],  // used when no slice applies
  "scope_deny":  ["state/**", "logs/**", "mailbox/**"],
  "criteria": [
    { "id": "C1", "ears": "The fleet CLI SHALL expose `spec verify`.",
      "kind": "pytest", "nodes": ["tests/test_spec.py::test_verify_exists"] },
    { "id": "C2", "ears": "WHERE a criterion kind is unknown, verify SHALL fail closed.",
      "kind": "pytest", "nodes": ["tests/test_spec.py::test_unknown_kind_fails_closed"] }
  ]
}
```
````

### 3b. Human block — markdown body

ADR-shaped `## Context` / `## Decision` / `## Consequences`, plus `## Requirements` in **EARS** (`WHEN <event> the fleet SHALL <behavior>` / `WHERE <feature> …` / `IF <unwanted> THEN …`). Each EARS line anchors one criterion `id`. Human/judge-reviewed, never executed.

## 4. Criteria kinds — two, all pure-stdlib

`verify` dispatches on `kind`. **Unknown kind → hard FAIL (fail-closed).**

| kind | check | receipt |
|---|---|---|
| `files` | the change's touched-path set may include only paths matching `scope_allow` and none matching `scope_deny`, resolved against the bound worker's `cwd` | **touched-path union** (§6a) + `fnmatch` |
| `pytest` | every node in `nodes` must pass, run from the worker's `cwd` via the fixed runner | `subprocess.run([sys.executable,"-m","pytest",node], cwd=worker_cwd)`, exit code |

Executable fields carry **no free prose** — that keeps the verdict deterministic. Prose lives in `ears` + the body.

**Zero-collect = FAIL (under-delivery), never infra.** A `pytest` node that resolves but collects zero tests, or a `files` scope glob matching no path under the worker `cwd`, → criterion FAIL, `verify` exit 1 — never a satisfiable absent-check, and **never downgraded to non-blocking infra**. Else a worker dodges a real FAIL by deleting/renaming the target test until it "can't be verified." (adversarial-4, round-2 F4)

**exit 2 is reserved for genuine harness failure only** — runner/interpreter absent, a project-wide collection crash unrelated to a node's own assertions, malformed spec, or an `accepted_digest` mismatch (tamper). A *missing/renamed target* is under-delivery → exit 1, not infra. **When the class is ambiguous, `verify` resolves toward exit 1** — drift must never masquerade as a broken harness (round-2 F4). (adversarial-5)

**Interpreter is fixed `sys.executable -m pytest`** (in-module doctrine @5248) — **not author-supplied.** A free `runner` argv is arbitrary-command-execution at the manager's gate (round-2 F1); a project needing its own venv is a vetted-allowlist v2 concern, not free spec input. Never a hardcoded `py -3.13` (that governs the human shell, not in-module argv). (doctrine-3, feasibility-3)

## 5. Verifier — `fleet spec verify`

`fleet spec verify <campaign> [--worker <name>]` (`cmd_spec_verify`):

1. Load + parse the machine block (`json.loads` of the first ```json fence). Malformed → exit 2, loud. If `accepted_digest` is set, recompute the sha256 over the canonicalized executable fields (criteria `nodes`, `scope_allow`/`scope_deny`, slice scopes) and refuse on mismatch (exit 2, tamper) — a bound worker has write access to the spec dir, so verify must catch a spec whose executable fields were edited after `accept` signed them (round-2 F1).
2. **Anchor to the bound worker's registered `cwd`** (`before['cwd']` @3794 / `new_worker_record` cwd @608) — **never an author-supplied path.** All `scope`/`nodes`/globs resolve against it, the same tree the Phase-2 hook fences with `git -C <cwd>`, so the two enforcement halves provably resolve identically (round-2 F3). A spec whose fields try to escape `cwd` is rejected (round-2 F1).
3. Criteria set: all `criteria`, or — with `--worker` — only that slice's ids + its `files` scope check. Slice-overlap guard: reject (exit 2) if two slices' `scope_allow` patterns intersect in the **glob-pattern domain** (prefix / `**` containment reasoning over the pattern strings) — never a filesystem match, which is blind to not-yet-created files that could later collide (round-2 F5, open-Q6).
4. Run each by kind; unknown kind → FAIL. Collect `{id: PASS|FAIL, detail}`.
5. **Atomic stamp** to `state/spec-verify/<campaign>.json` (the stamp stays runtime/gitignored — it is derived, regenerated by every verify) via `_write_json_atomic` (@6879 — temp + `os.replace`, atomic on NTFS): `{ts, spec_status, per_criterion, per_slice, overall}`. Includes the spec's current `status` so the view/doctor read it here and never parse the spec file. Concurrent verifies last-writer-win atomically; a torn read is impossible. (doctrine-5, adversarial-8)
6. Print per-criterion table; **exit 0 all-pass; exit 1 on any criterion FAIL (incl. zero-collect / missing target = under-delivery); exit 2 only on genuine harness failure (runner/interpreter absent, tamper-digest mismatch, malformed spec). Ambiguity resolves toward exit 1** — drift must never hide as infra (round-2 F4). No lock held across the pytest subprocess (F4 lock shape). `verify` is an authoritative command, never a view.

**Tier-2 judge, both paths (R3):** `--judge` auto-dispatches a reviewer subagent over the diff + spec body and prints its NOTES; the campaign-template doctrine step (manager spawns its own adversarial reviewer) stands alongside it. Both are **advisory — neither moves the exit code**, and a judge failure/timeout is never a gate failure. (decision-2)

## 6. Enforcement — staged

### Phase 1 (MVP) — the gate

`fleet spec verify` (§5) at the manager's merge gate: `files` scope-fence (touched-path union, §6a) + `pytest` criteria, deterministic, stamped, exit-coded. This is the acceptance gate and the whole worker↔supervisor sync guarantee for v1. No new hook, no new writer in the exit-0 Stop chain.

### Phase 2 (fast-follow inside M-E) — the live Stop-hook fence

A new `stop_specfence.py`, wired **`[stop_outcome, stop_specfence, stop_mailbox]`** — after `stop_outcome` so the outcome record always lands before any block continuation (SPEC §8 ordering, @196), before `stop_mailbox`. (doctrine-4) If the worker's record carries `spec`, run **only** the `files` scope-fence for its slice and emit `{"decision":"block","reason":"<SPEC DRIFT> …"}` (the verified stop-block shape @194) on an out-of-scope touch, exit 0 on every path.

- **Touched-path enumeration (four commands, not one):** union of `git -C <cwd> diff --name-only <base>` + `diff --cached --name-only <base>` (tracked mods, staged) + `ls-files --others --exclude-standard` (new non-ignored) + `ls-files --others --ignored --exclude-standard` (new **ignored**). The ignored query is **mandatory**: `--exclude-standard` alone *omits* exactly the gitignored `state/**`/`logs/**` deny targets, so my round-1 three-command union was blind to the very violation it claimed to catch (round-2 F2). Evaluate `scope_allow`/`scope_deny` over this real union — never a bare worktree glob (which can't attribute a path to this turn). Caveat: a *pre-existing* ignored file matching a deny glob can't be distinguished from a turn-created one by git alone — documented, and rare in a worker's own project tree. (adversarial-1, round-2 F2)
- **Baseline lifecycle:** `spec_baseline_sha` is re-stamped to `HEAD` at each **respawn** (context reset) and at each **fresh bind**; **preserved** across fork-steer/resume (same task continuing). Never carried stale into a respawn — a stale base diffs already-merged work and false-blocks the fresh session on files it never touched. (adversarial-2/3, doctrine-7, feasibility-5)
- **Advisory, not absolute — and loudly so:** the block is capped by Claude Code's native 8-block force-allow (@11-13), and the hook fails **open** when cwd is not a clean repo (worktree without the base, detached subdir, git absent). A silently-unfenced bound worker is therefore surfaced as a **`drift-fence-disabled`** flag on `status` + a doctor infra-warning — never buried in `hook-errors.log` alone. The gate (Phase 1) remains the real acceptance stop; the hook is live self-correction, not egress prevention. (adversarial-7)
- **Blocked-turn outcomes:** `stop_outcome` (ordered first) has **already** appended a `result` record before the fence runs, and `has_fresh_outcome` (@1544) keys on sid + freshness — it would count the blocked turn as complete. The fence writes a distinct block-tag record, and **`has_fresh_outcome` is amended in `fleet.py` (not the hook) to void a `result` superseded by a newer same-sid block-tag.** Exception: a block force-allowed by the native 8-block cap is a *genuine* stop — the fence marks that terminal case so the predicate **keeps** the result (else a done worker reads as still-working). (adversarial-10, round-2 F6)
- **Write boundary (SPEC §8, unchanged):** reads registry + spec read-only; writes nothing but `hook-errors.log`; exit 0 always. Command shape `"{{PYTHON}}" ".../stop_specfence.py"` (forward slashes); git via `subprocess` list-args (no `sh -c`).

### 6c. Surfacing (views stay probe-free)

`status` shows `drift` / `spec:proposed` / `spec:superseded` / `drift-fence-disabled`, all read from the atomic `.verify.json` stamp + registry `spec` field — **never a live spec-file parse, never verify, never lock/roster** (SPEC §14). A partial/missing stamp is treated as "no stamp" (fall through, never raise), the tolerate-and-ignore discipline the hooks already use. `_doctor_check_spec_drift` (note-only, @5366 convention): workers bound to a `proposed`/`superseded` spec, a stale/failing stamp, a disabled fence; infra-red only if a bound spec file is missing/unparseable.

## 7. Binding + durability

- **Registry additions (additive, tolerate-and-ignore on old records, round-tripped by `save_registry` @562/@569):** `spec` (campaign | null), `spec_slice` (slice name | null; only meaningful when slices used), `spec_baseline_sha` (Phase-2; the fence diff base). Added to `new_worker_record`'s returned dict (@606) so they persist; pre-SDD records get them via reader `.get()` defaults. (feasibility-6 verified)
- **Composition is in `compose_prompt` (@887), not `dispatch_bg`.** `compose_prompt` gains a `spec_section=None` param, threaded from each caller (spawn @2321, respawn @3875, steer, resume). When set, it injects `## BINDING SPEC` into `state/tasks/<name>.md`: the spec path + the worker's scope + owned criteria `ears` lines + an explicit **"re-read your BINDING SPEC (docs/specs/campaigns/<campaign>.md) at the start of every turn"** instruction. `dispatch_bg` still only writes the finished body (@6645). (feasibility-1)
- **`--add-dir <FLEET_HOME>/docs/specs/campaigns` is conditional** — added (via a new `specs_dir()` helper) only when the worker is spec-bound, alongside the unconditional `tasks_dir()` `--add-dir` @6659 (least privilege; a spec flag threads to `dispatch_bg`). The bound worker re-reads the whole contract under any mode. `--add-dir` grants **read+write**, so a bound worker can edit its own spec file; the `accepted_digest` re-check at verify (§5/§8) is the defense — a tampered executable field fails the gate loudly rather than silently re-scoping the worker or injecting a malicious runner (round-2 F1). (feasibility-6)
- **Respawn explicitly carries the binding.** `_cmd_respawn_native` copies `spec`/`spec_slice` from `before` (like it hand-copies cost/retired_sids @3858-3860) and **re-stamps** `spec_baseline_sha = HEAD`. Without this, respawn — the reset lever §9 names — silently unbinds the worker. A unit test asserts a spec-bound worker is still bound after a plain `respawn`. (adversarial-2, feasibility-5)
- **Compaction: no re-injection hook in v1.** Durability rests on `--add-dir` of the git-tracked spec dir (the contract is a file the worker re-reads) + the per-turn re-read instruction, mirroring how the journal/task-file already survive as on-disk state. `postcompact_journal.py` emits no context today (@176-179, disk-append only), PostCompact `additionalContext` support is unverified, and adding a context-injecting emission is net-new hook capability. Deferred to a v2 investigation gated on empirically confirming PostCompact stdout injection. (adversarial-6, feasibility-2, simplicity-5)

## 8. Lifecycle verbs

| verb | behavior |
|---|---|
| `spec new <campaign> [--from-goals]` | scaffold `docs/specs/campaigns/<campaign>.md` (git-tracked, R4), `status="proposed"`, `author=<durable actor>`. `--from-goals` seeds Context from `supervisor/GOALS.md`. No `--project-root`: the verify/fence tree is always the bound worker's registered `cwd` (round-2 F1/F3), resolved at verify time, not stored in the spec. |
| `spec accept <campaign>` | `proposed → accepted`, single-writer under `fleet.lock`. **Refuses if `accepted_by == author`** where identity is the **durable actor** (claim-holder / operator), not a per-session incarnation, **and** if `reviewed_by` is empty or names the author. `reviewed_by` must reference a review doc whose reviewer ≠ author. On accept, stamps `accepted_digest` = sha256 of the canonicalized executable fields, so post-accept tampering by a bound worker is caught at verify (round-2 F1). (doctrine-2) |
| `spec verify <campaign> [--worker N]` | §5. |
| `spec supersede <old> <new>` | mark `<old>` `superseded`, set `superseded_by`; **emits a `spec_superseded` event and surfaces every worker still bound to `<old>` loudly** (status flag + doctor), so a bound worker isn't left fencing a dead contract (Phase-2 fence re-reads live status each turn → superseded injects "halt, await re-bind"). (adversarial-9) |
| `spawn/respawn --spec <campaign> [--slice <name>]` | bind at launch; slice omitted → whole-spec scope; refuses a non-accepted spec (`dispatch_bg` guard, loud, no launch). |

`spec bind` (bind an already-spawned worker) is **cut** — `respawn --spec` covers it and gives the clean reset §9 wants. `spec status` is **cut** — the `status` table flag + doctor read the same stamp. (simplicity-3)

**Slash commands:** any `/fleet:spec-*` command is a **prompt template, never inline `` !`cmd` ``** (CLAUDE.md; `tests/test_terminal_surface.py` lint extended). `spec verify` is classified authoritative (writes the stamp), not a read-only view. (doctrine-6/8)

## 9. Supervisor ↔ worker sync (the core ask)

One shared spec authored from `GOALS.md` → every worker sees the same contract; optional slices partition scope so >1 worker cannot collide (coordination-drift). The stamp + status flag are the supervisor's at-a-glance "who is on contract." The spec is a file → survives supervisor handoff/seizure (soul-is-files, SPEC §12); the successor reads `docs/specs/campaigns/` + the stamp like the journal — and because it is git-tracked, it survives machine loss too. When a worker drifts past self-correction, `respawn --spec <same>` is the DAR-style hard reset onto the unchanged contract — **and now actually stays bound** (§7).

## 10. Testing

- **Unit (`tests/test_spec.py`, `tests/test_hooks.py`):** JSON machine-block parse (+ malformed → exit 2); `files` scope check driving the **real four git commands in a temp repo** — a tracked mod, a staged add, a new non-ignored file, and a new **ignored** file under a `scope_deny` glob (round-2 F2; a synthesized union would mask the `--exclude-standard` bug); `accepted_digest` tamper → verify exit 2; a `pytest` node collecting zero → exit 1 (not infra, round-2 F4); slice-overlap in the pattern domain → exit 2; `pytest` kind via injected runner seam (@5555 precedent) — pass→PASS, assert-fail→exit1, collection-error→exit2, zero-collect→exit2; unknown-kind fail-closed; slice-overlap → exit2; `spec accept` refuses self-promotion (durable-actor identity across an incarnation change) + empty/author `reviewed_by`; `dispatch_bg` refuses a `proposed` spec; **spec-bound worker still bound after plain `respawn` + baseline re-stamped**; view reads a partial stamp without raising; Phase-2 fence emits a block on out-of-scope, passes in-scope, fails-open + sets `drift-fence-disabled` on non-repo cwd.
- **New live pin (`tests/integration/test_native_pin.py`, `FLEET_LIVE=1`, haiku):** spawn a worker bound to a 2-criterion spec; Phase-1 — touch an out-of-scope file, `spec verify --worker` FAILs on the `files` union (incl. the new-file case), in-scope + criteria pass → green + atomic stamp. Phase-2 adds the Stop-hook block assertion. Runs on every `claude` bump (vendor-bump gate). *(Adds to the existing six pins in SPEC §17 — update that count on ratification.)*

## 11. Prior-art fit

- **Deterministic spec→code enforcement is rare** — of 6 frameworks only Tessl (capability↔test) ties spec to code behavior deterministically; OpenSpec/BMAD gate artifact structure/presence; the rest LLM-judge. Kiro's "mathematical property verification" is unverified marketing. Fleet's `pytest`+`files` deterministic gate + per-worker slices would be ahead of the surveyed field.
- **Universal drift primitive:** written versioned artifact on disk, re-read each phase, never chat history — all 6 converge; fleet already lives here (journal, task file, mailbox). This is the durability lever (§7), not a re-injection hook.
- **Format:** single markdown file = machine block + human body; kinds + fail-closed + EARS + ADR — directly from the format survey (JSON block chosen over TOML for the stdlib write path).
- **Compaction:** only CLAUDE.md is deterministically re-injected; PostCompact/SessionStart are the *unverified* escape hatch — hence v1 relies on `--add-dir` + re-read instruction, not a claimed tail-injection.
- **Drift taxonomy + reset:** arXiv 2601.04170 (semantic/coordination/behavioral); DAR "reset a drifting agent" = fleet `respawn`; deterministic gating only where an oracle exists (OpenHands "re-run tests before finish") = the `pytest` kind.

## 12. Invariant + doctrine additions

- **SPEC.md new § "Spec-driven development / drift control"** (prescriptive), plus **10th invariant:** *every campaign worker binds to an accepted spec; drift is deterministically verified at a gate (scope + criteria), judged advisorily (intent), and reset by respawn (DAR); the live Stop-fence is advisory self-correction, never the acceptance stop.*
- **Campaign-template:** a campaign opens `spec new → dual-lens review → spec accept` before workers spawn; `spec verify` at the merge gate; the tier-2 judge runs both ways (`--judge` + the manager's own reviewer); the spec is git-tracked, so it needs no archive step.
- **Hook boundary (SPEC §8):** the Phase-2 scope-fence hook is added to the sanctioned Stop-chain writers (writes only `hook-errors.log`; reads registry+spec read-only; ordering `[stop_outcome, stop_specfence, stop_mailbox]`).

## 13. Milestone

**M-F: SDD / drift-control** (M-E shipped 2026-07-21 — daemon-wedge detection, shipped-defect fixes, claim-nonce spec). Built in dependency order, **all of it behind `sdd.enabled` (default off, R1)**:

0. **Feature flag** (`sdd.enabled`) + its off-path test: a flagged-off fleet consults no spec field, changes no verb behavior, wires no hook — byte-identical dispatch to today. This lands *first* so every later slice is testable in isolation without risking live campaigns.
1. **Artifact + verifier + criteria kinds** (`spec new/accept/verify/supersede`, JSON block, `files`+`pytest`, worker-cwd anchoring, atomic stamp, durable-actor promotion guard, `accepted_digest`). — the deterministic gate, the core value.
2. **Binding + carry-forward** (`spawn/respawn --spec`, `compose_prompt` spec_section, conditional `--add-dir`, `specs_dir()`, respawn carry + baseline re-stamp, refuse-proposed).
3. **Surfacing** (`status` flags + `_doctor_check_spec_drift`, all stamp-read).
4. **`--judge` auto-dispatch** (R3) — advisory NOTES only, never moves the exit code; a judge failure/timeout is not a gate failure.
5. **Phase-2 live Stop-fence** (`stop_specfence.py`, touched-path union incl. the ignored query, baseline lifecycle, fail-open surfacing, blocked-outcome tagging) — only after 1–3 are green, pinned, **and proven in one real flagged-on campaign**.
6. **Fold into `docs/SPEC.md` fully** (R4): a first-class § plus the 10th invariant, campaign-template, and terminal-surface lint — not a pointer to this file. This design doc becomes history once folded, like the v2 body.

Path: this spec-task → dual-lens review (done, 2 rounds) → operator ratification (R1–R4 given 2026-07-20) → build. The flag is what makes "gate it first in order to test it" real: SDD ships dark, is exercised on one campaign, and only then earns default-on.

## 14. Operator decisions — RESOLVED 2026-07-20

All four §14 residuals are closed; see §2 R1–R4 for the binding text.

| # | Question | Ruling |
|---|---|---|
| 1 | Enforcement staging | **Phase-1 gate first, behind an on/off feature flag** (`sdd.enabled`, default off) so it can be tested before it binds anything. Phase-2 fence follows once Phase-1 is proven. |
| 2 | Slices | **Both** — a minor whole-spec scope *and* per-worker slices layered on it (slice ∩ whole-spec; a slice may only narrow). |
| 3 | Judge tier-2 | **Both** — build `--judge` auto-dispatch *and* keep the doctrine step. Advisory either way. |
| 4 | Spec home | **Git-tracked** (`docs/specs/campaigns/`) from birth; once SDD ships it folds into `docs/SPEC.md` fully. |

## 15. Out of scope for M-F — raised 2026-07-20, needs its own spec

Two asks arrived from a teammate after ratification. Neither is folded here; both are recorded so they are not lost, and both are **milestone-sized, not M-F amendments**.

- **Cross-platform agent runtimes** (Hermes, OpenCode, Claude Code, Codex, Cursor). Fleet is `claude --bg` all the way down — the native-substrate contract (`docs/specs/native-substrate.md`, G1–G13), the roster join, the outcome store, and every hook are Claude-Code-shaped. Supporting other runtimes is an **agent-runtime adapter layer**, a peer of the platform adapter (invariant 8), and a larger change than the native pivot itself. **Relevant to SDD:** the split already in this design is the portable seam — the **Phase-1 gate is runtime-agnostic** (markdown + git + a test runner; nothing Claude-specific), while the **Phase-2 Stop-hook fence is Claude-Code-only**. A cross-runtime fleet would keep the gate and re-implement the fence per runtime, or ship gate-only on runtimes without a hook boundary. Building SDD gate-first (R1) therefore *helps* this later work rather than blocking it.
- **Agent↔agent verification / an isolated oracle.** The concern: with no human in the loop, an agent's only evidence about another agent's work is that agent's own claim — so a compromised or merely deranged worker can propagate bad state, and workers can spiral passing tasks to each other. This is the same threat model this design already answers in three places — the deterministic tier *decides* and the judge is only advisory (decision 2), `accepted_digest` catches a worker rewriting the contract that gates it (round-2 F1), and git-tracking adds a second tamper surface (R4). What is **not** yet designed is a *standalone oracle process* that independently re-derives task + output + context and is not itself an agent in the chain. That is a real gap and a good candidate for the milestone after M-F; the SDD verifier is its natural substrate (it is already non-agentic and deterministic), but the isolation, the trust boundary, and the loop-detection are unspeced.
