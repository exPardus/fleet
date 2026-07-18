# SDD / drift-control subsystem — design (M-E candidate)

**Status:** DRAFT v2 — folded round-1 adversarial review (4 lenses: correctness, doctrine, simplicity, feasibility; 2026-07-18). Not spec-of-record until a re-review clears the fold and the operator ratifies.
**Author:** manager session (supervisor claim-holder). Promotion is operator-gated — the author never self-promotes.
**Parent spec:** `docs/SPEC.md` v3 (§4 registry, §5 verdict engine, §6 dispatch choke point / `compose_prompt`, §8 hook boundary, §12 supervisor, §14 views, §16 invariants, §17 tests).
**Prior art scanned:** spec-kit, AWS Kiro, OpenSpec, Tessl, BMAD, Cline/Cursor; EARS, Gherkin, design-by-contract, ADR; Claude Code compaction surfaces, LangGraph/CrewAI/Swarm/AutoGen, OpenHands/Devin, arXiv 2601.04170 "Agent Drift". Summary in §11.

**Round-1 receipts that reshaped this draft (grep-verified against `bin/fleet.py`):** `compose_prompt` @887 is the composer (params `name, cwd, task, sid, journal_path`); `dispatch_bg` @6621 only writes the finished `prompt_body` @6645 and appends one unconditional `--add-dir tasks_dir()` @6659. `_cmd_respawn_native`/`cmd_respawn` @3959 rebuilds via `new_worker_record` @591 (fixed key set @606-659, no `**kwargs`) and hand-copies only enumerated fields @3794-3861 — **any field not explicitly copied is lost.** `_restamp_after_steer` @6331 mutates in place (preserves other fields). `postcompact_journal.py` appends a journal-file line @176-179 and **emits nothing to stdout** (no context injection); the only context-injecting hook is `posttooluse_mailbox.py` @122-128. `stop_mailbox.py` blocks via `print(json.dumps({"decision":"block","reason":…}))` @194 then `sys.exit(0)` @203, capped by Claude Code's native 8-block force-allow @11-13. `_write_json_atomic` + `pin_pass_path`/`record_pin_pass` @110-130 = the reusable atomic-stamp pattern. `sys.executable` is the in-module Python-subprocess doctrine @5248/@5256/@5562. 21 doctor checks, note-only = `ok=True` always @5366-5373. `tomllib` is stdlib in 3.13 but **read-only** (no `dump`).

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

Locked by operator brainstorming (2026-07-18): (1) built subsystem + doctrine, ships as M-E; (2) drift detection = deterministic tier decides, judge tier advisory-only; (3) one campaign spec, per-worker slices; (4) hybrid enforcement (cheap scope-fence blocks in a hook; full verify at the gate); (5) spec is gated `proposed → review → accepted`, workers refuse a non-accepted spec.

Resolved after review (were sub-decisions / open questions; rationale inline in the sections):

- **Format = fenced ```json block** (not TOML). `tomllib` is read-only stdlib — the mutating verbs need a writer; `json` round-trips in stdlib. (doctrine-1)
- **Two criteria kinds: `files` + `pytest`.** `grep` dropped — a grep assertion *is* a pytest node, and §17 already mandates a unit test per feature. (simplicity-4)
- **Enforcement is staged inside M-E: Phase 1 = gate-first (no hook); Phase 2 = the live Stop-hook fence.** The fence is the riskiest, most-defect-dense piece and catches over-reach only; the gate catches the same over-reach plus under-delivery with zero hook-boundary risk. Phase 2 ships once its speced-out fixes (§6a) are built and pinned. This honors decision (4) while sequencing risk. (adversarial-1/3/6/7/10, simplicity-1/5)
- **Slices are optional.** Default = one whole-spec scope; named per-worker slices when a campaign runs >1 worker — the coordination-drift mechanism ("between workers"). `verify` errors if two slices' `scope_allow` globs intersect. (simplicity-6, open-Q6, the operator's "between workers" ask)
- **Judge tier-2 = pure doctrine, zero new code.** No `--judge` flag in fleet.py; tier-2 is a campaign-template step — the manager spawns its existing adversarial reviewer against the diff + spec body. (decision-2 kept as advisory; simplicity-2 satisfied — no code)

## 3. Spec artifact

`state/specs/<campaign>.md` — one file per campaign. Runtime dir (gitignored, like `tasks/`/`journals/`/`outcomes/`); moved to `logs/archive/<campaign>/` on close by `archive`/`autoclean` with the other evidence. Two halves.

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
  "project_root": "C:/proga/claude-fleet",   // the tree all scope/nodes/globs resolve against (§5)
  "verify": { "runner": ["{{PYTHON}}", "-m", "pytest"] },  // {{PYTHON}} -> sys.executable; per-project override
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
| `files` | the change's touched-path set may include only paths matching `scope_allow` and none matching `scope_deny`, resolved against `project_root` | **touched-path union** (§6a) + `fnmatch` |
| `pytest` | every node in `nodes` must pass, run from `project_root` via the resolved `verify.runner` | `subprocess.run(runner + [node], cwd=project_root)`, exit code |

Executable fields carry **no free prose** — that keeps the verdict deterministic. Prose lives in `ears` + the body.

**Zero-candidate = FAIL, never satisfiable-absent.** If a `pytest` node collects nothing, or a `files` scope glob resolves against a `project_root` where it matches no path, `verify` exits 2 (loud, infra) — it never treats "no files" as a passed check. (adversarial-4)

**pytest error class ≠ test failure.** Runner exit for a collection/import/interpreter error (pytest exit codes 2–5, or runner-not-found) → `verify` exit 2 (infra, "cannot verify here" — do not merge-block on *drift* grounds). Genuine assertion failure (pytest exit 1) → criterion FAIL, `verify` exit 1. (adversarial-5)

**Interpreter is `sys.executable`, resolved per-project.** `verify.runner`'s `{{PYTHON}}` token renders to `sys.executable` (the in-module doctrine @5248), overridable per spec for a project with its own venv/tox. Never a hardcoded `py -3.13` (that governs the human shell, not in-module argv). (doctrine-3, feasibility-3)

## 5. Verifier — `fleet spec verify`

`fleet spec verify <campaign> [--worker <name>]` (`cmd_spec_verify`):

1. Load + parse the machine block (`json.loads` of the first ```json fence). Malformed → exit 2, loud (never a false PASS).
2. **Resolve `project_root`** from the spec (fallback: the bound worker's registered `cwd`). All `scope`/`nodes`/globs resolve against it — the same tree the Phase-2 hook fences (`git -C <cwd>`), so the two enforcement halves never disagree. (adversarial-4)
3. Criteria set: all `criteria`, or — with `--worker` — only that slice's ids + its `files` scope check. Slice-overlap guard: if any two slices' `scope_allow` globs intersect, exit 2 (coordination-drift is *prevented*, and a broken partition is surfaced). (open-Q6)
4. Run each by kind; unknown kind → FAIL. Collect `{id: PASS|FAIL, detail}`.
5. **Atomic stamp** to `state/specs/<campaign>.verify.json` via `_write_json_atomic` (@130 pattern — temp + `os.replace`, atomic on NTFS): `{ts, spec_status, per_criterion, per_slice, overall}`. Includes the spec's current `status` so the view/doctor read it here and never parse the spec file. Concurrent verifies last-writer-win atomically; a torn read is impossible. (doctrine-5, adversarial-8)
6. Print per-criterion table; **exit 1 iff any deterministic criterion FAILs; exit 2 on any infra/cannot-verify; exit 0 all-pass.** No lock held across the pytest subprocess (F4). `verify` is an authoritative command, never a view.

Tier-2 judge is not a flag here — it is the campaign-template step where the manager spawns its existing adversarial reviewer against the diff + spec body (advisory; never gates). (decision-2, simplicity-2)

## 6. Enforcement — staged

### Phase 1 (MVP) — the gate

`fleet spec verify` (§5) at the manager's merge gate: `files` scope-fence (touched-path union, §6a) + `pytest` criteria, deterministic, stamped, exit-coded. This is the acceptance gate and the whole worker↔supervisor sync guarantee for v1. No new hook, no new writer in the exit-0 Stop chain.

### Phase 2 (fast-follow inside M-E) — the live Stop-hook fence

A new `stop_specfence.py`, wired **`[stop_outcome, stop_specfence, stop_mailbox]`** — after `stop_outcome` so the outcome record always lands before any block continuation (SPEC §8 ordering, @196), before `stop_mailbox`. (doctrine-4) If the worker's record carries `spec`, run **only** the `files` scope-fence for its slice and emit `{"decision":"block","reason":"<SPEC DRIFT> …"}` (the verified stop-block shape @194) on an out-of-scope touch, exit 0 on every path.

- **Touched-path enumeration (the fix that makes the fence real):** union of `git -C <cwd> diff --name-only <base>` + `git -C <cwd> diff --cached --name-only <base>` + `git -C <cwd> ls-files --others --exclude-standard`, and evaluate `scope_deny` by globbing the actual worktree (gitignored runtime dirs included). Plain `git diff --name-only` alone is blind to new/untracked/gitignored files — the textbook "dropped a file in the wrong dir" and every `state/**`/`logs/**` deny. (adversarial-1)
- **Baseline lifecycle:** `spec_baseline_sha` is re-stamped to `HEAD` at each **respawn** (context reset) and at each **fresh bind**; **preserved** across fork-steer/resume (same task continuing). Never carried stale into a respawn — a stale base diffs already-merged work and false-blocks the fresh session on files it never touched. (adversarial-2/3, doctrine-7, feasibility-5)
- **Advisory, not absolute — and loudly so:** the block is capped by Claude Code's native 8-block force-allow (@11-13), and the hook fails **open** when cwd is not a clean repo (worktree without the base, detached subdir, git absent). A silently-unfenced bound worker is therefore surfaced as a **`drift-fence-disabled`** flag on `status` + a doctor infra-warning — never buried in `hook-errors.log` alone. The gate (Phase 1) remains the real acceptance stop; the hook is live self-correction, not egress prevention. (adversarial-7)
- **Blocked-turn outcomes:** `stop_outcome` writes a `result` record on every Stop, unaware of a later block. The fence tags its block so a blocked-then-retried turn's outcome is not counted by the fresh-outcome predicate as a real completion. (adversarial-10)
- **Write boundary (SPEC §8, unchanged):** reads registry + spec read-only; writes nothing but `hook-errors.log`; exit 0 always. Command shape `"{{PYTHON}}" ".../stop_specfence.py"` (forward slashes); git via `subprocess` list-args (no `sh -c`).

### 6c. Surfacing (views stay probe-free)

`status` shows `drift` / `spec:proposed` / `spec:superseded` / `drift-fence-disabled`, all read from the atomic `.verify.json` stamp + registry `spec` field — **never a live spec-file parse, never verify, never lock/roster** (SPEC §14). A partial/missing stamp is treated as "no stamp" (fall through, never raise), the tolerate-and-ignore discipline the hooks already use. `_doctor_check_spec_drift` (note-only, @5366 convention): workers bound to a `proposed`/`superseded` spec, a stale/failing stamp, a disabled fence; infra-red only if a bound spec file is missing/unparseable.

## 7. Binding + durability

- **Registry additions (additive, tolerate-and-ignore on old records, round-tripped by `save_registry` @562/@569):** `spec` (campaign | null), `spec_slice` (slice name | null; only meaningful when slices used), `spec_baseline_sha` (Phase-2; the fence diff base). Added to `new_worker_record`'s returned dict (@606) so they persist; pre-SDD records get them via reader `.get()` defaults. (feasibility-6 verified)
- **Composition is in `compose_prompt` (@887), not `dispatch_bg`.** `compose_prompt` gains a `spec_section=None` param, threaded from each caller (spawn @2321, respawn @3875, steer, resume). When set, it injects `## BINDING SPEC` into `state/tasks/<name>.md`: the spec path + the worker's scope + owned criteria `ears` lines + an explicit **"re-read your BINDING SPEC (state/specs/<campaign>.md) at the start of every turn"** instruction. `dispatch_bg` still only writes the finished body (@6645). (feasibility-1)
- **`--add-dir state/specs` is conditional** — added (via a new `specs_dir()` helper) only when the worker is spec-bound, alongside the unconditional `tasks_dir()` `--add-dir` @6659 (least privilege; a spec flag threads to `dispatch_bg`). The bound worker re-reads the whole contract under any mode. (feasibility-6)
- **Respawn explicitly carries the binding.** `_cmd_respawn_native` copies `spec`/`spec_slice` from `before` (like it hand-copies cost/retired_sids @3858-3860) and **re-stamps** `spec_baseline_sha = HEAD`. Without this, respawn — the reset lever §9 names — silently unbinds the worker. A unit test asserts a spec-bound worker is still bound after a plain `respawn`. (adversarial-2, feasibility-5)
- **Compaction: no re-injection hook in v1.** Durability rests on `--add-dir state/specs` (the contract is a file the worker re-reads) + the per-turn re-read instruction, mirroring how the journal/task-file already survive as on-disk state. `postcompact_journal.py` emits no context today (@176-179, disk-append only), PostCompact `additionalContext` support is unverified, and adding a context-injecting emission is net-new hook capability. Deferred to a v2 investigation gated on empirically confirming PostCompact stdout injection. (adversarial-6, feasibility-2, simplicity-5)

## 8. Lifecycle verbs

| verb | behavior |
|---|---|
| `spec new <campaign> [--from-goals] [--project-root PATH]` | scaffold `state/specs/<campaign>.md`, `status="proposed"`, `author=<durable actor>`. `--from-goals` seeds Context from `supervisor/GOALS.md`; `project_root` defaults to the manager's cwd. |
| `spec accept <campaign>` | `proposed → accepted`, single-writer under `fleet.lock`. **Refuses if `accepted_by == author`** where identity is the **durable actor** (claim-holder / operator), not a per-session incarnation, **and** if `reviewed_by` is empty or names the author. `reviewed_by` must reference a review doc whose reviewer ≠ author. (doctrine-2) |
| `spec verify <campaign> [--worker N]` | §5. |
| `spec supersede <old> <new>` | mark `<old>` `superseded`, set `superseded_by`; **emits a `spec_superseded` event and surfaces every worker still bound to `<old>` loudly** (status flag + doctor), so a bound worker isn't left fencing a dead contract (Phase-2 fence re-reads live status each turn → superseded injects "halt, await re-bind"). (adversarial-9) |
| `spawn/respawn --spec <campaign> [--slice <name>]` | bind at launch; slice omitted → whole-spec scope; refuses a non-accepted spec (`dispatch_bg` guard, loud, no launch). |

`spec bind` (bind an already-spawned worker) is **cut** — `respawn --spec` covers it and gives the clean reset §9 wants. `spec status` is **cut** — the `status` table flag + doctor read the same stamp. (simplicity-3)

**Slash commands:** any `/fleet:spec-*` command is a **prompt template, never inline `` !`cmd` ``** (CLAUDE.md; `tests/test_terminal_surface.py` lint extended). `spec verify` is classified authoritative (writes the stamp), not a read-only view. (doctrine-6/8)

## 9. Supervisor ↔ worker sync (the core ask)

One shared spec authored from `GOALS.md` → every worker sees the same contract; optional slices partition scope so >1 worker cannot collide (coordination-drift). The stamp + status flag are the supervisor's at-a-glance "who is on contract." The spec is a file → survives supervisor handoff/seizure (soul-is-files, SPEC §12); the successor reads `state/specs/` + the stamp like the journal. When a worker drifts past self-correction, `respawn --spec <same>` is the DAR-style hard reset onto the unchanged contract — **and now actually stays bound** (§7).

## 10. Testing

- **Unit (`tests/test_spec.py`, `tests/test_hooks.py`):** JSON machine-block parse (+ malformed → exit 2); `files` scope check over a **synthesized touched-path union** incl. an untracked new file and a gitignored deny path (the adversarial-1 trap); `pytest` kind via injected runner seam (@5555 precedent) — pass→PASS, assert-fail→exit1, collection-error→exit2, zero-collect→exit2; unknown-kind fail-closed; slice-overlap → exit2; `spec accept` refuses self-promotion (durable-actor identity across an incarnation change) + empty/author `reviewed_by`; `dispatch_bg` refuses a `proposed` spec; **spec-bound worker still bound after plain `respawn` + baseline re-stamped**; view reads a partial stamp without raising; Phase-2 fence emits a block on out-of-scope, passes in-scope, fails-open + sets `drift-fence-disabled` on non-repo cwd.
- **New live pin (`tests/integration/test_native_pin.py`, `FLEET_LIVE=1`, haiku):** spawn a worker bound to a 2-criterion spec; Phase-1 — touch an out-of-scope file, `spec verify --worker` FAILs on the `files` union (incl. the new-file case), in-scope + criteria pass → green + atomic stamp. Phase-2 adds the Stop-hook block assertion. Runs on every `claude` bump (vendor-bump gate). *(Adds to the existing six pins in SPEC §17 — update that count on ratification.)*

## 11. Prior-art fit

- **Deterministic spec→code enforcement is rare** — of 6 frameworks only Tessl (capability↔test) ties spec to code behavior deterministically; OpenSpec/BMAD gate artifact structure/presence; the rest LLM-judge. Kiro's "mathematical property verification" is unverified marketing. Fleet's `pytest`+`files` deterministic gate + per-worker slices would be ahead of the surveyed field.
- **Universal drift primitive:** written versioned artifact on disk, re-read each phase, never chat history — all 6 converge; fleet already lives here (journal, task file, mailbox). This is the durability lever (§7), not a re-injection hook.
- **Format:** single markdown file = machine block + human body; kinds + fail-closed + EARS + ADR — directly from the format survey (JSON block chosen over TOML for the stdlib write path).
- **Compaction:** only CLAUDE.md is deterministically re-injected; PostCompact/SessionStart are the *unverified* escape hatch — hence v1 relies on `--add-dir` + re-read instruction, not a claimed tail-injection.
- **Drift taxonomy + reset:** arXiv 2601.04170 (semantic/coordination/behavioral); DAR "reset a drifting agent" = fleet `respawn`; deterministic gating only where an oracle exists (OpenHands "re-run tests before finish") = the `pytest` kind.

## 12. Invariant + doctrine additions

- **SPEC.md new § "Spec-driven development / drift control"** (prescriptive), plus **10th invariant:** *every campaign worker binds to an accepted spec; drift is deterministically verified at a gate (scope + criteria), judged advisorily (intent), and reset by respawn (DAR); the live Stop-fence is advisory self-correction, never the acceptance stop.*
- **Campaign-template:** a campaign opens `spec new → dual-lens review → spec accept` before workers spawn; `spec verify` at the merge gate; the tier-2 judge is the manager's existing adversarial reviewer; the spec archives with the campaign evidence.
- **Hook boundary (SPEC §8):** the Phase-2 scope-fence hook is added to the sanctioned Stop-chain writers (writes only `hook-errors.log`; reads registry+spec read-only; ordering `[stop_outcome, stop_specfence, stop_mailbox]`).

## 13. Milestone

**M-E: SDD / drift-control**, built in dependency order:
1. **Artifact + verifier + criteria kinds** (`spec new/accept/verify/supersede`, JSON block, `files`+`pytest`, project-root anchoring, atomic stamp, durable-actor promotion guard). — the deterministic gate, the core value.
2. **Binding + carry-forward** (`spawn/respawn --spec`, `compose_prompt` spec_section, conditional `--add-dir`, `specs_dir()`, respawn carry + baseline re-stamp, refuse-proposed).
3. **Surfacing** (`status` flags + `_doctor_check_spec_drift`, all stamp-read).
4. **Phase-2 live Stop-fence** (`stop_specfence.py`, touched-path union, baseline lifecycle, fail-open surfacing, blocked-outcome tagging) — after 1–3 are green and pinned.
5. **Docs + 10th invariant + campaign-template + terminal-surface lint.**

Path: this spec-task → dual-lens review (adversarial + doctrine) → operator ratification → build. Gated on operator ratification like every fleet milestone.

## 14. Residual operator decisions (surfaced by review; author's rec in bold)

1. **Enforcement staging:** **Phase-1 gate ships first; Phase-2 live fence as fast-follow within M-E.** (Alternative the operator may prefer: build both together, or defer Phase-2 to a separate later milestone.) The live fence honors decision (4) but is the defect-dense piece; staging de-risks it.
2. **Slices default:** **whole-spec by default, named slices only for >1-worker campaigns.** (Alternative: always require a slice per worker.)
3. **Judge tier-2:** **doctrine-only, no fleet.py code** (manager spawns its existing reviewer). (Alternative: build a `--judge` auto-dispatch.)
4. **Spec file home:** **`state/specs/` runtime, archived on close.** (Alternative: `docs/specs/` git-tracked from birth — a campaign contract is arguably worth versioning; costs a git-write path and loses the runtime-hygiene story.)
