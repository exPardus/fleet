# fleet-index — cutting duplicate exploration cost

**Status:** ready-for-build (M1 only). M2 and M3 are `[DRAFT — not ready]`.
**Owner:** Altai
**Design doc:** `docs/superpowers/specs/2026-07-22-fleet-index-design.md`
**Adversarial review:** `docs/reviews/IDX-ADVERSARIAL-2026-07-22.md` (10 defects — 2 CRITICAL, 5 HIGH, 2 MED, 1 LOW). Disposition in §13.
**Economics evidence:** `docs/mf-oracle-m1-evidence.md` (2026-07-23 M-F dogfood read-duplication harvest). §1 is grounded on it.
**Operator decisions folded:** `docs/OPERATOR-GATES.md` fleet-index sub-decisions (a) gitignored-only bundle and (b) tokens-primary acceptance (both 2026-07-23); full M1+M2 build ordered 2026-07-24 on the value case stated in §1.
**Parent spec:** `docs/SPEC.md` v3 (§16 invariants).

---

## 1. Problem

An earlier draft of this section opened: *"Fleet's dominant recurring cost is workers re-reading the same code."* That claim has since been measured, and **for parallel fleet workers it is refuted** by the 2026-07-23 M-F dogfood harvest (`docs/mf-oracle-m1-evidence.md` — 3 workers, 27 transcripts, reads deduped across fork copies, token totals deduped by requestId):

- Cross-worker duplicated Read payload: **≤41k tokens = 2.5% of the campaign's fresh input.**
- All duplicated Read payload (cross-worker ∪ within-lineage rebuild, no double count): 55.7k–94.8k tokens = 3.5–5.9% of fresh input, and ~0.27% of total input processed.
- The dominant recurring cost of that run was conversation-prefix re-transmission (33.9M cache-read tokens, 21× the entire fresh-input volume), driven by long fork lineages — not file re-reads.

Evidence grade per the harvest's own limits: suggestive, not conclusive (n=3 workers, one night, small repos, deliberately overlapping tasks). But the burden has flipped: read-duplication is a **single-digit percentage of fresh input in the only run ever measured**, and this spec may not re-assert it as dominant without new measurement.

**What drives the build instead — the operator's value case (2026-07-24).** The operator deferred the economics go/no-go on the evidence above, then ordered a full M1+M2 build on a different ground: **smaller reads for long-term, multi-session work on one codebase.** `fleet q` — symbol lookup plus source slicing — hands a worker the ~40 lines it asked about instead of a Read-and-page pass over a large file (`bin/fleet.py` is 8,706 lines; orientation inside it is this repo's canonical case). That is useful per query, on the first session and the hundredth, independent of whether any *other* worker ever duplicates the read. The real cost target is the accumulated read volume of many sessions over one codebase's lifetime, not cross-worker duplication inside one night's campaign.

**Fewer-reads economics is demoted to a measured secondary.** Digest injection (`--context`, M1) stays in scope so its token effect can be A/B measured under §12's tokens-primary criterion — the operator chose the full M1+M2 build precisely so that measurement can happen — not because the duplication evidence supports it as a headline.

Two patterns in the harvest *do* fit the index's shape, recorded here as secondary rationale with their limits:

1. **Cold sessions over a stable file set.** The 16 cc-oracle probe sessions re-read one hook file 14×; 83% of probe Read payload was duplicate. Many short-lived cold sessions against stable files is where a digest pays; long-lived forked workers with warm caches are where it does not.
2. **Within-lineage respawn rebuild** (72.6k tokens upper bound) exceeded cross-worker duplication (40.9k) — a reset session re-learning its own files is the larger of the two fleet-side effects, and it is exactly the multi-session shape the operator's value case names.

## 2. What is not achievable, and why

**No mechanism shares tokens across worker sessions.** Workers are separate `claude` processes with separate context windows, billed separately.

The mechanism matters, and an earlier draft of this design got it wrong. Fleet does **not** pass the composed prompt as an argument. `dispatch_bg` writes `compose_prompt`'s entire output — preamble, mailbox, task, journal — to a task file, and hands `claude` a single sentence:

- `bin/fleet.py:7381` — the composed body is written to `task_file_path(name)`
- `bin/fleet.py:7385` — the argv prompt is `Read <task_path> and follow it exactly.`

So everything fleet injects reaches the model as a **tool result**, per worker, re-paid on every dispatch. It is per-worker by construction, independent of any caching behaviour.

This has a corollary the design must not lose: a byte-identical channel that reaches every worker in a project *does* exist — the target project's `CLAUDE.md`, which Claude Code loads without fleet's involvement. Whether bulk orientation material belongs there rather than in the task file is an open question (§12), not settled by this spec.

The achievable levers are exactly two:

- **Fewer reads** — the worker already knows it, so never issues the call.
- **Smaller reads** — the worker gets a symbol, not a file.

## 3. Milestone split

The review found the defensible component bundled with two undefensible ones. They ship separately.

| | Scope | Gate |
|---|---|---|
| **M1** | Indexer + shards + `--context` digest injection | Ready for build |
| **M2** | `fleet q` (query + source slicing) | Blocked: needs a `worker-settings.template.json` permissions migration (§11) |
| **M3** | `map.md` repo-wide orientation, opt-in per spawn | Blocked: needs the break-even measurement M1 produces |

**Why M1 alone is defensible:** it is opt-in twice over (per project via `init`, per spawn via `--context`), it adds no always-on cost, it needs no permissions change, and its value is measurable against §12.

**Why `fleet q` is not in M1:** it cannot execute for a default worker today (§11).

**Why `map.md` is not in M1:** its economics are unproven at this repo's shape. `map.md` is file-granular — it answers "what files exist", which `Glob` answers for ~0 tokens — and does not answer "where is the symbol". `compose_prompt` is called on four paths, three of which are not spawns (`bin/fleet.py:2470` spawn, `3408` idle-send, `3545` respawn, `4028` fork-steer), and the idle-send path resumes the *same* session, so an always-on map is re-paid per **dispatch**, not per spawn. A steered worker would pay it repeatedly for zero new information.

## 4. Architecture

```
indexer (deterministic parse, stdlib-only)
   |
   +--> .fleet-index/symbols/<source-path>.tsv     one shard per source file
              |
              +--> digest rendering  --> compose_prompt()   [M1] fewer reads
              +--> symbol lookup     --> fleet q            [M2] smaller reads
              +--> tree rollup       --> map                [M3] orientation
```

**One artifact type. No global files.** Everything else is a rendering computed on demand.

This is the central structural decision, and it is what makes the index safe under fleet's concurrency. Earlier drafts had a global `symbols.tsv`, a global `files.tsv`, stored per-file digests and a stored `map.md`. Every global file is a conflict surface: two workers editing *disjoint* source files both rewrite it. Sharding per source file means disjoint source edits touch disjoint index files, so the conflict cannot arise at any N.

## 5. The shard

Path mirrors the source path: source `bin/fleet.py` indexes to `.fleet-index/symbols/bin/fleet.py.tsv`.

Line 1 is a header carrying the staleness key; remaining lines are one symbol each. Tab-separated, no quoting, sorted by line number.

```
#	<sha256-8>	<line-count>	<lang>
<name>	<line>	<end>	<kind>	<sig>
```

Illustrative only — synthetic names, making no claim about any real file:

```
#	a3f21c8e	120	python
alpha	12	28	func	(x: int) -> str
Beta	31	95	class	
Beta.run	40	62	method	(self, y) -> bool
GAMMA	97	97	const	
```

- The source path is the shard's own path, so it is not a column.
- `kind` is `func` | `class` | `method` | `const` | `section` (markdown headings).
- `end` enables source slicing (M2) without re-parsing.
- Literal tabs in `sig` are escaped as `\t`; newlines stripped.
- Sorted by line, not by name: a source edit perturbs a contiguous region rather than scattering hunks.

Grep still works across the whole index — `grep -r <name> .fleet-index/symbols/` — and the matching shard's path *is* the source path, so the file field comes back for free.

**Format rationale.** TSV over JSONL because JSONL repeats every key on every line (~2–3× the tokens for identical content, paid on every grep hit that lands in a worker's context). TSV over SQLite because a database is opaque, not hand-editable, and unmergeable. The format is not what makes concurrency safe — sharding is; the format is chosen for token density and editability.

## 6. Indexer

```
fleet index init   [--path DIR]            opt in: create .fleet-index/, first build
fleet index build  [--path DIR] [--force]  rebuild an existing index
fleet index update [--paths P,...]         refresh named files
fleet index status [--path DIR]            counts, stale shards
```

**Opt-in per project.** `fleet index init` is the only command that creates `.fleet-index/`. `build`, `update`, `status` and (in M2) `q` all exit non-zero with "no index — run `fleet index init`" when it is absent. A project that never opts in is untouched; `fleet spawn` there behaves exactly as today.

Deterministic parse only — no model call, ever:

- **Python** — stdlib `ast`. Functions, classes, methods, module-level constants.
- **Markdown** — heading extraction, `kind=section`.
- **Everything else** — a shard with a header line and no symbols, so staleness still tracks.

Incremental: a file whose SHA-256 matches its shard header is skipped. `--force` rebuilds all.

**Writes are atomic.** Every shard is written to a temporary file in the same directory and `os.replace`d into position — the discipline fleet already applies to the mailbox. A torn shard is otherwise indistinguishable from a short one, which would silently yield wrong coordinates.

**Unparseable files never abort a build.** They are recorded as a header-only shard.

## 7. Digest injection (M1)

`compose_prompt` (`bin/fleet.py:917`) assembles four sources today — preamble, drained mailbox, task text, prior journal (`bin/fleet.py:945, 951, 960, 970`). M1 adds one, populated only when `--context` names files:

```
preamble
DIGEST <path>          per --context file, rendered from its shard
mailbox
task text
journal
```

```
fleet spawn foo --dir /c/proj --task @task.md --context src/api.py,docs/DESIGN.md
```

A digest is a rendering of the shard, not a stored artifact:

```
## src/api.py (120 lines, python)
- L12 alpha(x: int) -> str
- L31 class Beta
- L40   Beta.run(self, y) -> bool
```

**`--context` path resolution:** paths resolve against the worker's `--dir`, never the manager's cwd. This preserves invariant 5 (cwd-scoped dispatch) by keeping a single cwd frame. Unknown paths warn and are skipped; they never fail a spawn.

**Journal ordering is preserved on the paths that carry one.** Digest material is inserted ahead of the task, never between journal and turn. Note the honest limit: the idle-send path (`bin/fleet.py:3408`) composes with no `journal_path` at all, so there is no journal to order against there — `--context` is a spawn-time flag and M1 injects digests on spawn only.

## 8. Staleness and the two modes

Staleness is per shard: compare the source file's SHA-256 against the shard header.

A project picks **one of two modes** in `.fleet-index.toml`. The key selects a coherent bundle, not two independent knobs — this is deliberate, to hold the cost of supporting both to two well-defined paths rather than a matrix.

| Mode | `.fleet-index/` in git | On stale shard | Rationale |
|---|---|---|---|
| **`ignored`** (default) | gitignored, added by `init` | refresh it, then answer | Nothing tracked, so nothing to dirty. Index simply tracks the working tree. |
| **`tracked`** | committed | **refuse and exit non-zero**, telling the caller to run `fleet index update` | Queries never write, so no tracked file is dirtied and `git worktree remove` keeps working. Index churn is reviewable in PRs. |

```toml
mode = "ignored"          # "ignored" | "tracked"

[index]
include = ["**/*.py", "**/*.md"]
exclude = ["**/node_modules/**", "**/.venv/**", "**/target/**"]
```

**Why `tracked` must fail loud rather than refresh.** Refreshing a *tracked* file at query time leaves it dirty, and `git worktree remove` refuses a worktree containing modified tracked files — which breaks the campaign-3/4 worktree recipe (`knowledge/lessons.md:251`) at teardown. Failing loud costs friction; refreshing costs the recipe.

**Why staleness may never be answered by guessing.** A stale line number does not error — it silently slices the wrong code and the worker cannot tell. Both modes therefore either repair or refuse; neither serves an unverified coordinate.

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| No index (never `init`ed) | Exit non-zero, "run `fleet index init`". Spawn injects nothing and proceeds. Expected state for most projects. |
| Unparseable source file | Header-only shard. Build continues. |
| Shard missing for a `--context` file | Warn, skip that digest, spawn proceeds. |
| Shard corrupt or truncated | Treated as stale: repaired (`ignored`) or refused (`tracked`). Never parsed optimistically. |
| Stale shard | Per §8, by mode. |
| `--context` path unknown | Warn, skip, spawn proceeds. |

**The safety property.** Grep and Read on the raw repo always still work. The index is strictly additive: delete `.fleet-index/` entirely and fleet degrades to today's behaviour with no errors. No fleet decision reads the index.

## 10. Graveyard answer — IDEA-FORGE §5 entry 5

ROADMAP requires checking the graveyard before proposing anything adjacent to a dead idea. This has a direct ancestor: *"Knowledge-Aware Context Assembly at Spawn/Respawn (3.0) — right moat, wrong build."*

| Cause of death | Answer |
|---|---|
| grep-isn't-ranking | Nothing here ranks. Symbol lookup is exact; digests are deterministic renderings. The one ranking feature (`relevance` map degradation) is **cut** — it is not in M1/M2/M3 at all. |
| silently-rotting tag schema as load-bearing element | The load-bearing objection, since this *is* a tag schema. Answer: every shard is SHA-256 keyed and checked before use, so it cannot rot silently — it repairs or refuses (§8). The ancestor had no staleness detection. This is the single most important property in this spec. |
| stale cross-project lore ahead of journal replay | Not cross-project (the index lives inside the project it describes); not lore (line-anchored derived fact the worker can verify against the file); not ahead of the journal (§7). |
| duplicates CLAUDE.md/MEMORY.md | Those are hand-written prose doctrine; this is generated structural fact. Different content, lifecycle and failure mode. |
| sits in first-party's path | Conceded. Mitigations: the artifact is plain text usable by anything, and the halves are separable — if first-party ships code search, M2 is deleted and M1 survives, since first-party cannot know what fleet is about to spawn. |

## 11. M2 gate — the permissions migration

`fleet q` cannot run for a default worker today, and this is why M2 is not in M1:

- Default spawn mode is `dontask` (`bin/fleet.py:8478`), not bypass.
- `worker-settings.template.json` ships **no `permissions` block at all**.

An unauthorised tool call under a non-bypass headless worker hangs on a permission prompt nobody can answer — the documented failure that motivated `--add-dir` for task files (`bin/fleet.py:7390-7395`). M2 therefore requires:

1. `worker-settings.template.json` gains `permissions.allow: ["Bash(fleet q:*)"]` — subcommand-scoped, never `Bash(fleet:*)`, per the CLAUDE.md rule and the incident where a read-only slash command reached `fleet clean`.
2. A `fleet init` re-run for every existing install, since that template is git-tracked and gated by the `instance-freshness` doctor check.

M2 also carries the adoption risk: the preamble reaches the worker inside a tool result, competing against `Read`/`Grep`, which are in the system region and need no learning. M2 should ship with a measurement of whether workers actually call `fleet q`, and be reverted if they do not.

## 12. Testing and acceptance

Per SPEC §17, pytest for unit tests.

- Indexer: golden-file per language; unparseable handling; incremental skip; atomic-replace under an injected crash between write and rename.
- Sharding: two disjoint source edits produce two disjoint shard writes and merge cleanly.
- Staleness: both modes — `ignored` repairs, `tracked` refuses with a non-zero exit.
- `compose_prompt`: composition order, `--context` resolution against `--dir`, unknown-path tolerance, and that absent `--context` changes the prompt not at all.
- Config: absent config defaults to `ignored`; `init` writes the `.gitignore` entry only in that mode.

**Acceptance for M1** — the headline claim needs an instrument that does not exist yet. Fleet's outcome record carries `input_tokens`/`output_tokens` and a `transcript_path` (`bin/hooks/stop_outcome.py:203-206`) but no tool-call data, so "fewer orientation reads" is not currently measurable by any fleet command. M1 ships with a small transcript-parsing script that counts Read/Grep calls per session, and the criterion is:

1. On a fixed task run twice — once with `--context`, once without — the `--context` run issues strictly fewer Read/Grep calls, and its total input tokens are lower.
2. `fleet index build` is byte-reproducible: two runs on an unchanged tree produce identical shards.
3. A mutated source file never yields a stale coordinate in either mode.
4. Deleting `.fleet-index/` returns fleet to baseline behaviour with no errors.

Result (1) is the input to M3's go/no-go: without a measured saving from targeted digests, an always-on map cannot be justified.

## 13. Review disposition

All 10 findings from `docs/reviews/IDX-ADVERSARIAL-2026-07-22.md`. Manager spot-checked every code citation against `bin/fleet.py` before accepting.

| # | Finding | Sev | Disposition |
|---|---|---|---|
| 1 | §2's prefix-keyed-cache mechanism false; composed prompt is delivered as a tool result | MED | **Accepted.** §2 rewritten to the mechanism provable from this repo (`bin/fleet.py:7381,7385`). The `CLAUDE.md` shared-channel question is recorded as open, not silently resolved. |
| 2a | Name-sorted global `symbols.tsv` conflicts at N=2, retiring 7-wide parallelism | CRITICAL | **Accepted, restructured.** Sharded per source file; sorted by line. No global file exists, so the conflict cannot arise. `files.tsv` deleted (it had the same defect); digests and map became on-demand renderings. |
| 2b | Query-time refresh dirties a tracked file, breaking `git worktree remove` | HIGH | **Accepted.** `tracked` mode refuses on stale instead of refreshing (§8); `ignored` is the default and has nothing tracked to dirty. |
| 3 | Always-on map has no net-positive task mix here; per-dispatch not per-spawn | HIGH | **Accepted.** Map removed from M1 entirely; M3 is opt-in and gated on M1's measurement. The per-dispatch correction is stated in §3. |
| 4 | `fleet q` blocked — default mode `dontask`, template has no permissions block | CRITICAL | **Accepted.** Moved to M2 behind an explicit permissions-migration gate (§11). |
| 5 | No lock or atomic write; §9's "corrupt = skip malformed lines" contradicts §8 | HIGH | **Accepted.** Atomic `os.replace` per shard (§6); corrupt shards are treated as stale, never parsed optimistically (§9). Sharding also shrinks each write to one small file. |
| 6 | Six of eight code citations wrong — and they were the worked example | HIGH | **Accepted.** Every repo citation re-derived and manager-verified; all format examples replaced with synthetic placeholders that make no claim about any real file. |
| 7 | Two fenced blocks parse as executable receipts and fail | HIGH | **Accepted.** No `$ `-prefixed lines in this document, so it contains no receipts. Declared in `tests/test_receipts.py` `UNENFORCED` with the reason that it specs unbuilt behaviour. |
| 8a | §5.4 "fixed per-spawn cost" false | MED | **Accepted** — corrected in §3, and moot for M1 since the map is gone. |
| 8b | Invariant-4 argument does not hold on the idle-send path | MED | **Accepted.** §7 states the limit explicitly rather than generalising from respawn. |
| 8c | Success criterion 1 not measurable with shipped telemetry | LOW | **Accepted.** §12 ships a transcript-parsing counter and defines the criterion against it. |
| 8d | `--context` path resolution unspecified | — | **Accepted.** §7 fixes resolution to the worker's `--dir`. |
| 8e | Section numbering | — | **Accepted** — renumbered in this document. |

Not adopted: nothing. All findings were accepted; the CRITICALs forced the restructure into M1/M2/M3 and the shard layout.

## 14. Invariants touched

Per ROADMAP, citing `docs/SPEC.md` §16.

| # | Invariant | Status |
|---|---|---|
| 1 | daemonless launch | **Preserved.** `fleet index` is a short-lived CLI invocation. No resident process, no scheduler. |
| 2 | exit-0 hooks | **Preserved.** No hook added or modified. Index updates are explicit CLI calls, not hooks — a `PostToolUse` or `post-merge` hook would index on every write regardless of review state. |
| 4 | journal-injection-at-respawn | **Touched, preserved.** `compose_prompt` gains a source; the journal is still composed and retains final position on every path that carries one (§7). |
| 5 | cwd-scoped dispatch | **Preserved.** `--context` resolves against the worker's `--dir`, introducing no second cwd frame (§7). |
| 8 | platform-adapter-only OS branching | **Preserved.** All index paths go through `pathlib`; no OS branch, no new adapter method. |
| 9 | one-state-many-views | **Touched, argued preserved.** The index is not fleet state: it derives from a target repo's source, not from the registry, and no fleet decision reads it. The registry remains the single state with `status_snapshot()` its one derivation. |

Invariants 3 (mailbox), 6 (single-writer registry) and 7 (one live session per name) are untouched — no registry write, no dispatch-path change, no session lifecycle change.

## 15. Out of scope

- **Call graph / `callers()`** — a natural addition over the same shards; deliberately deferred.
- **`relevance` map degradation** — cut. It is ranking, and ranking is what killed the ancestor (§10).
- **Cross-session token sharing** — impossible (§2).
- **Embeddings, semantic chunking, similarity search** — excluded by design (§10).
- **GraphQL or SQL query layers** — possible later over the same shards; rejected now (schema-in-context cost; opacity).
- **Auto-selecting `--context` from task text** — the manager names files explicitly.
