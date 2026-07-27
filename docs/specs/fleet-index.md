# fleet-index — cutting duplicate exploration cost

**Status:** ready-for-gate (M1+M2; M3 stays DRAFT). Author-flipped 2026-07-24 per the operator's full-M1+M2 build order (record of record: the `knowledge/lessons.md` day-3 entry ("2026-07-24 — operator morning queue cleared + autonomous day-3 opened", on `main`); the corresponding `docs/OPERATOR-GATES.md` settled row is still owed — §16); ratification is the operator's — an author never promotes its own spec.
**Code citations:** every `bin/fleet.py` and `bin/hooks/stop_outcome.py` citation below is derived against merge-base `3ccb2d5` (`git merge-base main spec/fleet-q`, re-derived 2026-07-24); `bin/fleet.py` there is 11,288 lines. Line numbers rot, so each citation names the symbol it points at — re-grep the symbol before trusting the number. **Prose citations are not receipts** — the pinned `# at <sha>` blocks below are, and they are re-executed by `tools/verify_receipts.py` against that commit's materialised tree (root `CLAUDE.md`). This document was `UNENFORCED` while it specced unbuilt behaviour; it moved to the enforced set on 2026-07-27, when M1 and M2's worker-facing surface shipped and there was finally something to re-run.
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

**What drives the build instead — the operator's value case (2026-07-24).** The operator deferred the economics go/no-go on the evidence above, then ordered a full M1+M2 build on a different ground: **smaller reads for long-term, multi-session work on one codebase.** `fleet q` — symbol lookup plus source slicing — hands a worker the ~40 lines it asked about instead of a Read-and-page pass over a large file (`bin/fleet.py` is 11,288 lines at `3ccb2d5`; orientation inside it is this repo's canonical case). That is useful per query, on the first session and the hundredth, independent of whether any *other* worker ever duplicates the read. The real cost target is the accumulated read volume of many sessions over one codebase's lifetime, not cross-worker duplication inside one night's campaign.

**Fewer-reads economics is demoted to a measured secondary.** Digest injection (`--context`, M1) stays in scope so its token effect can be A/B measured under §12's tokens-primary criterion — the operator chose the full M1+M2 build precisely so that measurement can happen — not because the duplication evidence supports it as a headline.

Two patterns in the harvest *do* fit the index's shape, recorded here as secondary rationale with their limits:

1. **Cold sessions over a stable file set.** The 16 cc-oracle probe sessions re-read one hook file 14×; 83% of probe Read payload was duplicate. Many short-lived cold sessions against stable files is where a digest pays; long-lived forked workers with warm caches are where it does not.
2. **Within-lineage respawn rebuild** (72.6k tokens upper bound) exceeded cross-worker duplication (40.9k) — a reset session re-learning its own files is the larger of the two fleet-side effects, and it is exactly the multi-session shape the operator's value case names.

## 2. What is not achievable, and why

**No mechanism shares tokens across worker sessions.** Workers are separate `claude` processes with separate context windows, billed separately.

The mechanism matters, and an earlier draft of this design got it wrong. Fleet does **not** pass the composed prompt as an argument. `dispatch_bg` writes `compose_prompt`'s entire output — preamble, mailbox, task, journal — to a task file, and hands `claude` a single sentence:

- `dispatch_bg` (`bin/fleet.py:8210`) writes the composed body to `task_file_path(name)` (`bin/fleet.py:8240`)
- the argv prompt (`tiny_prompt`, `bin/fleet.py:8244`) is `Read <task_path> and follow it exactly.`

So everything fleet injects reaches the model as a **tool result**, per worker, re-paid on every dispatch. It is per-worker by construction, independent of any caching behaviour.

This has a corollary the design must not lose: a byte-identical channel that reaches every worker in a project *does* exist — the target project's `CLAUDE.md`, which Claude Code loads without fleet's involvement. Whether bulk orientation material belongs there rather than in the task file is an open question (§12), not settled by this spec.

The achievable levers are exactly two:

- **Fewer reads** — the worker already knows it, so never issues the call.
- **Smaller reads** — the worker gets a symbol, not a file.

## 3. Milestone split

The review found the defensible component bundled with two undefensible ones. They ship separately.

| | Scope | Gate |
|---|---|---|
| **M1** | Indexer + shards + `--context` digest injection | Ready for gate — same state as the header; full M1+M2 build ordered by the operator 2026-07-24 (§1). |
| **M2** | `fleet q` (query + source slicing) | Ready for gate — permissions migration specified (§11.7); ships with the §11.9 adoption measurement and its revert trigger. Full M1+M2 build ordered by the operator 2026-07-24 (§1). |
| **M3** | `map.md` repo-wide orientation, opt-in per spawn | Blocked: needs the break-even measurement M1 produces |

**Why M1 alone is defensible:** it is opt-in twice over (per project via `init`, per spawn via `--context`), it adds no always-on cost, it needs no permissions change, and its value is measurable against §12.

**Why `fleet q` is not in M1:** it cannot execute for a default worker until §11.7's migration lands, and its acceptance is a separate measurement (§11.9). Same branch, separate gates.

**Why `map.md` is not in M1:** its economics are unproven at this repo's shape. `map.md` is file-granular — it answers "what files exist", which `Glob` answers for ~0 tokens — and does not answer "where is the symbol". `compose_prompt` is called on four paths, three of which are not spawns (at `3ccb2d5`: spawn `cmd_spawn` `bin/fleet.py:3224`; idle-send — `cmd_send`'s fork-steer engine `_cmd_send_native:4174`; resume-limited `_resume_one_limited_native:4319`; respawn `_cmd_respawn_native:4820`), and the idle-send path continues the *same* transcript (a fork-steer: `dispatch_bg(..., resume_sid=old_sid)` forks the session carrying its full history, G2b), so an always-on map is re-paid per **dispatch**, not per spawn. A steered worker would pay it repeatedly for zero new information.

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
fleet index update [--path DIR] --files P,...   refresh named files
fleet index status [--path DIR]            counts, stale shards
```

`update` resolves the index root exactly as `build`/`status` do — `--path DIR`, defaulting to cwd. Its file list is `--files` — renamed from an earlier draft's `--paths`, which gave the token `--path` three meanings across the CLI (index root here, file list on `update`, glob filter on `q`, §11.1). Rename recorded in §17.

**Opt-in per project.** `fleet index init` is the only command that creates `.fleet-index/`. `build`, `update`, `status` and (in M2) `q` all exit non-zero with "no index — run `fleet index init`" when it is absent. A project that never opts in is untouched; `fleet spawn` there behaves exactly as today.

Deterministic parse only — no model call, ever:

- **Python** — stdlib `ast`. Functions, classes, methods, module-level constants.
- **Markdown** — heading extraction, `kind=section`.
- **Everything else** — a shard with a header line and no symbols, so staleness still tracks.

Incremental: a file whose SHA-256 matches its shard header is skipped. `--force` rebuilds all.

**Writes are atomic.** Every shard is written to a temporary file in the same directory and `os.replace`d into position — the discipline fleet already applies to the mailbox. A torn shard is otherwise indistinguishable from a short one, which would silently yield wrong coordinates.

**Windows caveat: `os.replace` onto an open file is not unconditional.** On POSIX the rename always lands; on Windows, replacing a shard a concurrent reader holds open raises `PermissionError` (a sharing violation) — the same transient hazard this repo already documents and retries for the registry (`bin/fleet.py:2697`, "Windows sharing violations are transient", the registry-commit backoff). Shard writers take the same discipline: retry the replace with a short bounded backoff; on exhaustion, abandon the write and leave the old shard in place. That failure mode is safe by construction — the old shard is merely stale, the header hash detects it (§8), and the next read repairs it. §11.6 states the reader side.

**Unparseable files never abort a build.** They are recorded as a header-only shard.

## 7. Digest injection (M1)

`compose_prompt` (`bin/fleet.py:1182`) assembles four sources today — preamble, drained mailbox, task text, prior journal (`parts` assembly, `bin/fleet.py:1210, 1216, 1225, 1235`). M1 adds one, populated only when `--context` names files:

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

**Built 2026-07-27**, as a spawn-only flag:

```
# at 1844a1f
$ grep -n '"--context"' bin/fleet.py
15673:    p_spawn.add_argument("--context", default=None,
```

**What an uncapped digest costs, measured 2026-07-27.** §11.4's 400-line cap is `q --outline`'s alone and §11.1 states the two renderings differ only when that cap truncates, so the spawn-time digest is **not capped** — and an uncapped thing owes a measurement rather than an adjective. `--context bin/fleet.py` (16,075 source lines) renders **539 digest lines / 27,835 chars**; fifty distinct files of that size render **~1.39 MB** into a single prompt. There is no budget: **the manager's `--context` list is the budget.** No cap was added here — capping would silently impose `q`'s limit on a path this spec exempts, which is a spec decision, not a fix-wave one — so the cost is pinned by measurement instead (`tests/test_index_compose.py::test_the_uncapped_digest_cost_is_pinned_by_measurement`, which pins the *shape* of the growth: one row per indexed symbol, no truncation at any size, linear in distinct files).

**Duplicates are dropped, first spelling wins.** `--context a.py,a.py` used to render `a.py` twice, for zero additional information and 27,835 wasted chars in the worst case measured above. `parse_context_arg` now dedupes, order-preserving — §7's digests appear in the order the manager named them, and a manager reads the composed prompt. This is not a cap and does not touch the uncapped contract; it is the one size reduction available without changing what the digest promises.

**Journal ordering is preserved on the paths that carry one.** Digest material is inserted ahead of the task, never between journal and turn. Note the honest limit: the idle-send path (`_cmd_send_native`, `bin/fleet.py:4174`) composes with no `journal_path` at all, so there is no journal to order against there — `--context` is a spawn-time flag and M1 injects digests on spawn only.

## 8. Staleness — gitignored-only

Staleness is per shard: compare the source file's SHA-256 against the shard header.

**`.fleet-index/` is always gitignored.** `init` writes the `.gitignore` entry unconditionally, and committing `.fleet-index/` is **documented-unsupported** (operator sub-decision (a), 2026-07-23, council round 2 — `docs/OPERATOR-GATES.md`). An earlier draft of this section offered a second, `tracked` mode whose refuse-on-stale behaviour defended a query path that did not exist in M1, and whose dirty-worktree hazard existed only because tracked mode did. Staleness detection is mode-independent, so re-adding a `tracked` mode later is an additive config key — out of scope for M1 and M2.

**On a stale shard: refresh it, then answer.** Nothing is tracked, so nothing is dirtied; the index simply tracks the working tree. Refreshes are per-shard atomic writes (§6), so the write is as safe as the build's.

Configuration lives at `.fleet-index/config.toml` — created by `init` with the defaults below. It sits *inside* the gitignored `.fleet-index/` directory, so the one `.gitignore` entry `init` writes already covers it; it is never tracked and needs no entry of its own:

```toml
[index]
include = ["**/*.py", "**/*.md"]
exclude = ["**/node_modules/**", "**/.venv/**", "**/target/**"]
```

(No `mode` key. The key name is reserved for a future tracked-mode decision; an unknown key in `config.toml` is a config error, so an old `mode = "tracked"` line fails loud rather than being silently ignored.)

**A gitignored index does not travel through git.** A freshly created worktree has no `.fleet-index/` regardless of the parent checkout's state. The campaign worktree recipe therefore gains a manager-side step — `fleet index init --path <worktree>` before spawning into it (owed to the campaign template, §16) — and a worker in an index-less worktree gets the §9 no-index behaviour **because of §11.1's repository-boundary rule**: the walk-up stops at the worktree's own `.git` file, so it can never escape into the parent checkout's `.fleet-index/`, and the fallback is Read/Grep — never a silently wrong parent index.

**Why staleness may never be answered by guessing.** A stale line number does not error — it silently slices the wrong code and the worker cannot tell. Every read path therefore repairs before answering (or, under `fleet q --no-refresh`, §11.3, withholds); no path serves an unverified coordinate.

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| No index (never `init`ed) | Exit non-zero, "run `fleet index init`". Spawn injects nothing and proceeds. Expected state for most projects. |
| Unparseable source file | Header-only shard. Build continues. |
| Shard missing for a `--context` file | Warn, skip that digest, spawn proceeds. |
| Shard corrupt or truncated | Treated as stale: refreshed, then answered. Never parsed optimistically. |
| Stale shard | Refreshed, then answered (§8). |
| `--context` path unknown | Warn, skip, spawn proceeds. |
| `--context` path unusable for any other reason (rejected path shape, shard directory that cannot be created, source that dies between the header read and the parse) | Warn, skip, spawn proceeds. One path's problem is one path's cost. |
| The index's source enumeration cannot run at all | Warn, inject nothing, spawn proceeds — the no-index row's shape. |

**The compose-order invariant this table rests on (added 2026-07-27, after a measured defect).** Every row above says "spawn proceeds", and that sentence was enforced only by the return codes the digest path happened to check. It is now enforced structurally, in two places:

1. **`compose_prompt` runs BEFORE the spawn's pre-claim registry record is committed.** It used to run between the commit and the rollback `try:` that guards dispatch — a window with no rollback in it. Reproduced: with `--context` naming a file whose shard directory could not be created, a `FileExistsError` escaped `cmd_spawn` uncaught and left `{"status": "working", "session_id": null}` in the registry plus a `spawned` event: a live-looking worker that never existed, pinned there by the launch-in-flight guard. The control arm — the same spawn with no `--context` — was clean, which is what identified `--context` as the opener. Hoisting alone is **not** sufficient (measured: it converts the phantom into an uncaught traceback), so the call is also wrapped and any failure becomes a CLI error with nothing registered.
2. **The per-path digest body is wrapped**, so the failures in the table above are warnings rather than raises in the first place. The catch is typed by *meaning* — `FleetCliError`, `ValueError`, `OSError` — not by class name, so a path-shape guard added to `_index_posix_rel` later is caught whatever it is called, and a genuine bug in the renderer stays loud.

`_index_posix_rel` is **shared**, and that has a second consequence worth stating because it was missed the first time it was measured: `fleet index update --files ../x.py` normalises through it too, so a guard that raises there pre-empts `_index_files_arg`'s own `startswith("../")` refusal *with a different message*. Verified by injecting the guard: the compose path was the reported casualty, but `fleet index update`'s refusal wording changed as well. That escape is normalised back to §6's own "outside the index root" wording, so the verb's refusal reads the same whichever layer catches it.

**The safety property.** Grep and Read on the raw repo always still work. The index is strictly additive: delete `.fleet-index/` entirely and fleet degrades to today's behaviour with no errors. No fleet decision reads the index.

## 10. Graveyard answer — IDEA-FORGE §5 entry 5

ROADMAP is superseded history, not live law — retired per the settled "Two roadmaps" gate (2026-07-23, `docs/OPERATOR-GATES.md`). Its graveyard discipline — check the graveyard before proposing anything adjacent to a dead idea — is applied here on its merits. This has a direct ancestor: *"Knowledge-Aware Context Assembly at Spawn/Respawn (3.0) — right moat, wrong build."*

| Cause of death | Answer |
|---|---|
| grep-isn't-ranking | Nothing here ranks. Symbol lookup is exact; digests are deterministic renderings. The one ranking feature (`relevance` map degradation) is **cut** — it is not in M1/M2/M3 at all. |
| silently-rotting tag schema as load-bearing element | The load-bearing objection, since this *is* a tag schema. Answer: every shard is SHA-256 keyed and checked before use, so it cannot rot silently — it repairs or refuses (§8). The ancestor had no staleness detection. This is the single most important property in this spec. |
| stale cross-project lore ahead of journal replay | Not cross-project (the index lives inside the project it describes); not lore (line-anchored derived fact the worker can verify against the file); not ahead of the journal (§7). |
| duplicates CLAUDE.md/MEMORY.md | Those are hand-written prose doctrine; this is generated structural fact. Different content, lifecycle and failure mode. |
| sits in first-party's path | Conceded. Mitigations: the artifact is plain text usable by anything, and the halves are separable — if first-party ships code search, M2 is deleted and M1 survives, since first-party cannot know what fleet is about to spawn. |

## 11. M2 — `fleet q`: symbol lookup and source slicing

M2 is the **smaller reads** lever (§2) and the load-bearing half of the operator's §1 value case: the worker gets a symbol, not a file. Everything below reads the M1 shards (§5); M2 adds no artifact type.

### 11.1 CLI contract

```
fleet q <query> [--src] [--path GLOB] [--kind KIND] [--limit N] [--no-refresh]
fleet q --outline <path> [--no-refresh]
```

- **Index discovery:** walk up from the process cwd to the nearest directory containing `.fleet-index/`; that directory is the index root and all shard paths are relative to it. **The walk-up stops at the first repository boundary it meets: a directory containing a `.git` entry, whether directory OR file** (a linked worktree's `.git` is a *file*). If the boundary directory itself has no `.fleet-index/`, the result is the no-index exit 3 (§11.5) — the walk never continues past a boundary. Named example: a worker in a nested worktree `<repo>/.claude/worktrees/x` that was never `init`ed gets exit 3 and falls back to Read/Grep (§8); without the boundary rule the walk-up would escape the worktree and resolve the PARENT checkout's `.fleet-index/`, whose staleness checks pass against the parent's files while the worker's tree sits on a different branch — silently wrong slices, and a stale-shard refresh would write into the parent's index from inside a fenced worktree. No flag overrides discovery — a worker's cwd is its registered `--dir` by construction (invariant 5), and the walk-up covers a worker that has cd'd into a subdirectory. No `.fleet-index/` and no boundary by the filesystem root → exit 3.
- `--path GLOB` — restrict hits to source paths matching the glob (`fnmatch.fnmatchcase` against the shard's forward-slash source-relative path; §11.2's platform-invariant semantics). Note the deliberate asymmetry with the `fleet index` family, where `--path DIR` names the project root: `q` never takes a root argument, so the flag name is free for its filter role, which is what a querying worker actually needs.
- `--kind KIND` — restrict to one of `func | class | method | const | section` (§5).
- `--limit N` — cap printed hits (default 20). Truncation is reported on stderr with the count of suppressed hits and a hint to narrow with `--path`/`--kind`; a truncated result is still exit 0.
- `--src` — slice source (§11.4).
- `--outline <path>` — print the digest rendering (§7) of that one file's shard on demand mid-task — the same rendering `--context` injects at spawn, except that `--outline` output is additionally subject to §11.4's line cap (the spawn-time digest is not; the two outputs differ only when the cap truncates).
- `--no-refresh` — never write anything (§11.3).

### 11.2 Query semantics

Queries run against the `name` column of every shard under the index root, after `--path`/`--kind` filtering. Three forms, resolved in this order:

1. **Exact** — `fleet q compose_prompt` matches `name == "compose_prompt"`, case-sensitive.
2. **Dotted tail** — consulted **only when form 1 yields zero hits** (short-circuit: any exact hit means tail matching never runs, so exact and tail hits never mix in one result). A query with no `.` also matches the segment after the final `.`: `fleet q run` finds `Beta.run`. Workers usually know the method name, not its class qualification. Example outcome against §5's placeholder file plus a hypothetical top-level `run` function: `fleet q run` returns only the top-level `run` — `Beta.run` is not listed (exact tier hit, tail tier skipped); it stays reachable as `fleet q Beta.run` or via glob. Ambiguity *within* a tier is still ambiguity: two exact `run` hits in two files under `--src` exit 1 with pointers (§11.4) — the short-circuit never resolves ambiguity by falling through to the other tier.
3. **Glob** — a query containing `*` or `?` is an fnmatch pattern against the full name: `fleet q "Beta.*"`. Glob queries skip forms 1–2.

Within each form, hits sort by source path then line. Nothing ranks (§10): matching is exact or literal-glob, never scored. Substring hunting stays where it belongs — `grep -r <text> .fleet-index/symbols/` works today and needs no flag (§5).

**Platform-invariant matching semantics (win32 pinned).** Exact and dotted-tail matching are byte-wise **case-sensitive on every platform**. All glob matching — form 3 name globs and the `--path` filter (§11.1) — uses `fnmatch.fnmatchcase`, named deliberately against `fnmatch.fnmatch`, which case-folds via `os.path.normcase` on win32 and would make `fleet q "beta.*"` match `Beta.run` on Windows but not on Linux. Shard-relative source paths use **forward slashes on every platform** — in the shard tree layout (§5), in `--path` matching, and in `<path>:<line>-<end>` output (§11.4) — so §12's golden tests are byte-identical across OSes.

### 11.3 Staleness on the read path

Before answering from any shard, `q` re-hashes that shard's source file and compares against the header — the §8 check, applied per query. The shards are consulted **only after** this verification, so a hit is always a claim about the file as it exists now:

- **Stale, missing, corrupt, or truncated shard** → re-parse that one source file, atomically replace the shard (§6 discipline), then answer. If the replace fails after §6's bounded retries, the current invocation still answers from its own verified in-memory parse — only the on-disk shard stays stale, repaired by the next read. Gitignored-only (§8) is what makes this unconditional: there is no tracked file to dirty, so the refuse-on-stale branch the old two-mode design needed does not exist.
- **Source file deleted but shard present** (orphan) → the shard's hits are suppressed with a stderr note, and the refresh prunes the orphan shard.
- **`--no-refresh`** → suppress all writes. Stale or orphaned shards have their hits **withheld**, each with a stderr staleness note — never served. This is the flag for contexts where any write is unacceptable (read-only mounts, mid-`git bisect`); the §8 rule that no path serves an unverified coordinate binds it too.

The residual race is the gap between the hash check and the read inside one invocation. A write landing in that window can still yield a wrong slice — the same window a bare `Read` has, and closing it would take file locking (out of scope). The check narrows the wrong-coordinate exposure from "any time since the last index build" to "microseconds inside one call," and the only plausible writer inside a worker's worktree is that worker itself.

### 11.4 Output format

Default output is one pointer line per hit, tab-separated:

```
<path>:<line>-<end>	<kind>	<name>	<sig>
src/api.py:40-62	method	Beta.run	(self, y) -> bool
```

(Synthetic, continuing §5's placeholder file — per finding 6's disposition, no example in this spec makes a coordinate claim about any real file.)

**Token-density rationale.** A hit line is ~15–25 tokens: no repeated field names (the TSV argument of §5, carried to the output), no JSON envelope (2–3× the tokens for identical content), and the leading `path:line-end` is directly reusable — it is the exact argument shape for a windowed `Read` if the worker wants surrounding context, and the clickable reference format the harness already renders. Hits go to stdout; diagnostics (truncation, staleness notes) go to stderr, so a worker's tool result carries signal only.

With `--src`, the query must resolve to **exactly one** symbol after filters. Then `q` prints the pointer line followed by lines `line..end` read from the source file on disk, verbatim:

- **Coordinates from the index, bytes from the file** — source never comes from the shard; the index supplies the range, the file supplies truth. This is the token win: pointer-only output still leaves the worker to Read the file; the slice means it never does.
- **A multi-hit `--src` prints the pointer list instead and exits 1** with "ambiguous — narrow with `--path`/`--kind`" on stderr. Dumping N slices is a token blowout in the exact place this tool exists to prevent one, so ambiguity resolves to pointers, never to concatenated source.
- **Output cap.** A `--src` slice or `--outline` rendering is capped at **400 lines**. Beyond the cap, output is truncated at line 400 and ends with the trailer `[truncated N lines — narrow the query]` (N = suppressed line count). Truncation does not change the exit code — an oversized symbol is the query's problem to narrow, not an error.
- **`kind=section` end, defined.** For a markdown `section` symbol (§5), `end` is the line before the next heading of the same or higher level, or EOF — that range is what `--src` slices for a section. (This pins the `end` column's meaning for `kind=section` shards; the indexer computes it at parse time.)

### 11.5 Exit codes and failure modes

| Code | Meaning |
|---|---|
| 0 | ≥1 hit printed (including a `--limit`-truncated list, and `--outline` success). |
| 1 | Query understood, nothing served: no match; all matches withheld under `--no-refresh`; ambiguous `--src` (pointers printed instead); or `--outline` on an unknown path. stderr says which, and suggests `grep -r <query> .fleet-index/symbols/` then repo grep for the no-match case. |
| 2 | Usage error (argparse). |
| 3 | No index — no `.fleet-index/` found between cwd and the first repository boundary (§11.1). Message: `no index — run 'fleet index init'`. |

| Failure | Behaviour |
|---|---|
| No index | Exit 3. Worker falls back to Read/Grep — the §9 safety property, unchanged: `q` degrades to today's behaviour, never blocks work. |
| Stale / corrupt / missing shard | Refresh then answer; withhold under `--no-refresh` (§11.3). |
| Orphan shard (source deleted) | Hits suppressed, shard pruned on refresh (§11.3). |
| Symbol not found | Exit 1, grep suggestion on stderr. |
| Ambiguous `--src` | Pointer list, exit 1 (§11.4). |
| Unreadable source at slice time | That hit degrades to its pointer line plus a stderr note; exit stays 0 if any hit printed. |
| `--outline` unknown path (no shard for it) | Exit 1. stderr prints a candidate pointer list — shard source paths whose final segment matches the argument's basename — the same narrow-it hint shape as ambiguous `--src`. |
| `--outline` header-only shard (unparseable or symbol-free source, §6) | Empty outline, exit 0 — the shard exists and is current; having no symbols is a fact about the file, not a failure. |
| `--outline` stale shard | Same stale contract as any `q` read (§11.3): refresh then answer; withhold with a stderr note under `--no-refresh`. |
| Shard read fails mid-swap (vanished or Windows `PermissionError` between hash check and read) | Treated as a stale shard (§11.3): refresh then answer; withhold under `--no-refresh`. Readers never crash on a concurrent writer (§11.6). |

### 11.6 Concurrency posture

Sharding is the safety story (§4), restated against `q`'s read path:

- `q` reads only the shards its filters select, and writes only the single shard it found stale — via the same tmp-file-plus-`os.replace` the build uses (§6). A reader observes the old shard or the new shard, never a torn one.
- Two concurrent `q`s refreshing the same stale shard both parse the same source bytes and produce byte-identical shards (§12 criterion 2, reproducibility). On POSIX, whichever `os.replace` lands second overwrites with identical content. **On Windows that sentence is not enough:** `os.replace` onto a shard a concurrent reader holds open raises `PermissionError` — the sharing-violation hazard this repo already documents and retries for the registry (`bin/fleet.py:2697`, "Windows sharing violations are transient"). The writer retries the replace with a short bounded backoff (§6); on exhaustion it abandons the refresh and leaves the old shard in place — stale, detectable by the header hash, safe under §8's staleness contract, repaired by the next read. Readers never crash on the mirror-image race: a shard that fails to read mid-swap is treated as stale (§11.5). No lock is needed because the merge function is "last write of identical bytes wins" and every failed write degrades to staleness, never to corruption.
- Two workers in two worktrees have two independent `.fleet-index/` directories (gitignored, per-worktree; §8) and cannot interact at all.
- `q` never touches fleet state — no registry read or write, no `fleet.lock`, no mailbox, no PID probe (invariant 9, §14). It is a pure function of the target repo's working tree plus its gitignored index.

### 11.7 The permissions migration

`fleet q` cannot run for a default worker today, and this was the original reason M2 split from M1:

- Default spawn mode is `dontask` (`--mode` default, `bin/fleet.py:10985`), not bypass.
- `worker-settings.template.json` ships **no `permissions` block at all**.

An unauthorised tool call under a non-bypass headless worker hangs on a permission prompt nobody can answer — the documented failure that motivated `--add-dir` for task files (`bin/fleet.py:8252-8262`). M2 therefore ships, in one slice:

1. **The template gains its first non-hook key.** `worker-settings.template.json` adds:

   ```json
   "permissions": { "allow": ["Bash(fleet q:*)"] }
   ```

   Subcommand-scoped, **never `Bash(fleet:*)`**. The wide grant is a kill grant: `fleet kill` and `fleet clean` are irreversible (CLAUDE.md), and the recorded incident where a *read-only slash command* reached `fleet clean` is the standing proof that any surface granted `fleet` wholesale eventually exercises its destructive subcommands. `Bash(fleet q:*)` is the only fleet grant the template will ever carry for workers; it deliberately excludes `fleet index:*` — lifecycle (init/build/update) is manager-side (§8), least privilege for the worker.

   **Execution status: `[VERIFIED — live two-arm experiment, 2026-07-27]`.** The hard M2 build-gate item below is **closed, and it came back positive.**

   The claim it was raised against was a real one. No receipt used to show a `--settings`-file `allow` taking effect for a `--bg` `dontask` worker, and the evidence pointed the other way: the 2026-07-23 overnight incident record shows working allowlists only via a per-worktree `.claude/settings.local.json`, and `dispatch_bg`'s own comment marks `--setting-sources`' runtime effect under `--bg` **UNOBSERVED** (`bin/fleet.py:8265-8268`). The gate item was therefore: before M2 ships, a live experiment must prove a default-spawned `dontask` `--bg` worker executes a granted command via the template grant alone, with no per-worktree allowlist present.

   **The experiment, run 2026-07-27** (supervisor checkpoint G-B; the transcript is in the supervisor journal under the fleet home). Two arms, one variable — same task file, same cwd, same mode (`dontask`), same model, same everything except the grant. The cwd was a scratch directory with **no `.claude/` in it at all**, confirmed by `ls -a` showing only `./` and `../`:

```
# at 9f7fe26
$ sed -n '/^  ARM B, CONTROL/,/^    PROBE-EXECUTED/p' docs/specs/receipts/fleet-index-11.7-grant-experiment.txt
  ARM B, CONTROL (no grant anywhere), worker probe-nogrant, dontask, sonnet:
    PROBE-DENIED Permission to use Bash has been denied because Claude Code is running in don't ask mode.

  ARM A, TREATMENT (one subcommand-scoped allow added to state/worker-settings.json only), worker probe-grant, dontask, sonnet:
    PROBE-EXECUTED PROBE-OK-7748
```

   The grant was `"permissions": {"allow": ["Bash(py -3.13 -c:*)"]}` and the probed command was `py -3.13 -c "print('PROBE-OK-7748')"`. **The multi-token prefix was deliberate** so the grant has the same shape as the `Bash(fleet q:*)` this template carries; a one-token grant would have proven a weaker thing.

   **Why the control was not optional.** Without arm B, arm A proves only that the worker ran a command, not that the grant is why — `dontask` being quietly more permissive than doctrine believes was a live possibility. Arm B rules it out, and incidentally re-confirms the documented failure mode: under `dontask` an ungranted `Bash` call is denied outright with a clear message rather than hanging on an unanswerable prompt.

   **This receipt was `# volatile` and is no longer, and the reason is worth keeping.** As first landed it read a **live absolute path** — `/c/proga/claude-fleet/supervisor/JOURNAL.md` — and declared itself volatile because "the transcript lives outside this repo". Two of the three clauses in that reason were false, and the third was the real defect:

   - The fleet home is the **main worktree of this same repository**, not a different one, and `supervisor/JOURNAL.md` is git-tracked. Both halves of "a different repository, machine-local, gitignored runtime" were wrong.
   - The cited text was nonetheless **never committed** — present only as an uncommitted modification to that file. So the receipt reproduced *by accident*, was one `git stash` from evaporating, and its `# at <sha>` pin constrained nothing, because a block reading an absolute path never touches the materialised tree the pin names.
   - It was also machine-enforced far less than it looked: a volatile block is a WARN in `tools/verify_receipts.py` and is **not executed at all** by `tests/test_receipts.py` (`skip_volatile=True`, which is what keeps that suite hermetic). Measured at the time: corrupting the treatment arm to `PROBE-OK-9999` produced `VERDICT: pass -- 0 failure(s), 1 warning(s)` and left the suite green.

   The fix is **not** to commit the excerpt into `supervisor/JOURNAL.md`. That file is the supervisor's append-only working file — every `sup-checkpoint` appends to it, every incarnation appends more — so a spec receipt reading it would still rest on content that churns by design, and a branch committing into it conflicts with `main` on every future merge, at the end of a file both sides append to. Instead the excerpt is committed as **its own immutable artifact**, `docs/specs/receipts/fleet-index-11.7-grant-experiment.txt`, and this receipt is re-pinned repo-relative and non-volatile against it. It is now inside the tree its `# at` names, it is executed by both the CLI and `tests/test_receipts.py`, and changing it is a reviewable diff.

   **What that does and does not buy.** It makes the *citation* verifiable — which is the property the receipt convention is actually about. It does not make the *experiment* re-runnable: one machine, one moment, one `claude --version`, exactly as before. A committed excerpt is a durable record of evidence, not a reproduction of it, and this document should not be read as claiming otherwise.

   **What this receipt proves, and what it does not.** It proves the *mechanism*: an `allow` entry in the rendered `state/worker-settings.json` that `dispatch_bg` passes via `--settings` reaches a default-spawned `dontask` `--bg` worker with no per-worktree `.claude/` present, for a multi-token `Bash(<prefix>:*)` grant. It does **not** execute the literal string `Bash(fleet q:*)`, because `fleet q` did not exist when the experiment ran; the shape, not the subcommand, is what was measured. It is also a single machine at a single `claude --version` — the same standing caveat every vendor-behaviour fact in this repo carries (`docs/specs/native-substrate.md`).

   **The grant and the teach lines are one claim in three files, and the branch shipped two of them early.** The template grant (here), §11.8's teach lines, and the `fleet q` parser verb are the same statement written three times; a build carrying any two of them without the third hands a worker either a grant for a verb that exits 2 or a lesson about a verb it cannot run. That was live and is fixed in §11.8 — and `tests/test_index_compose.py::TestTheTaughtVerbMustExist::test_the_template_grant_names_exactly_the_taught_verb` pins the grant against the taught verbs as a *relation*, so a verb rename cannot separate them again.

   The tree-side half of the same claim is not volatile and is pinned here:

```
# at 1844a1f
$ grep -n '"permissions"' worker-settings.template.json
2:  "permissions": { "allow": ["Bash(fleet q:*)"] },
```

   …and the narrowness, which is the part a future edit is most likely to erode — `grep -c` exits 1 on zero matches, so the exit assertion is doing real work here:

```
# at 1844a1f
$ grep -c 'Bash(fleet:\*)' worker-settings.template.json
0
$ echo "exit $?"
exit 1
```

2. **Reaching existing installs.** The template is git-tracked; the rendered `state/worker-settings.json` is instance state, and the `instance-freshness` doctor check compares the two. Migration is: pull, re-run `fleet init`, confirmed by `fleet doctor`. No new mechanism — the freshness gate exists precisely so template changes propagate this way. Workers already running keep their old settings until their next respawn (settings are read at session start); the migration needs no fleet-wide restart, it arrives with normal worker churn. **Measured 2026-07-27** in an isolated `FLEET_HOME`: `fleet init` renders the new `permissions` key verbatim into the instance, a template edit flips the check to `[FAIL] instance-freshness: worker-settings.json instance is older than the template -- run 'fleet init'`, and a re-run clears it to `[PASS]`.

   **Correction, and the blind spot it exposes.** An earlier wording of this item said the check "diffs the two". It does not: `instance_freshness_info` compares **mtimes** — stale iff the instance is missing, or the template's mtime is newer. That is sufficient for the pull-then-`init` path this item specifies, and it was harmless while the template carried hooks only. It is less harmless now. An instance that is *newer* than the template but has been hand-edited reads `[PASS]`: deleting the `permissions` key from a rendered instance and running `fleet doctor` was measured to report `[PASS] instance-freshness: instance is up to date with the template`. The failure that produces is silent and lands squarely on §11.9 — a worker whose grant has quietly gone missing makes zero `fleet q` calls, which is the exact shape of the revert trigger, fired against a permission bug rather than against the tool. The limit itself is **still not fixed** (the check predates this spec and is core `doctor` surface, not M2's) and is pinned by `tests/test_index_compose.py::test_freshness_does_not_notice_a_hand_edited_instance` so it cannot be re-described as a diff.

   **What WAS fixed: doctor now says so (`instance-grants`).** Re-measured 2026-07-27: widening the rendered instance's grant to `Bash(fleet:*)` — the **kill grant**, reaching the irreversible `fleet kill` and `fleet clean` — left `instance-freshness` reporting `stale: False` and `[PASS]`, and a second `fleet init` really does repair it. So the finding was never that freshness is wrong; it was that **nothing told the operator the repair existed.** `_doctor_check_instance_grants` compares the instance's *fleet* grants against the template's **by content**, which is precisely what makes it immune to the mtime limit that produced the hole, and it names `fleet init` in the failure line. Both directions fail, and they fail differently: a widened grant is a privilege nobody issued reaching every worker on the machine; a missing one is silent and is the §11.9 false-negative above. It reads only *fleet* grants — an operator's own unrelated `allow` entries are their business, and a check that fires on those trains the operator to ignore it.

```
# at 9f7fe26
$ grep -n 'def _doctor_check_instance_grants\|_doctor_check_instance_grants),' bin/fleet.py
8301:def _doctor_check_instance_grants():
9368:        functools.partial(_doctor_check_instance_grants),
```

3. **Interaction with the per-worktree `.claude/settings.local.json` doctrine** (spawn-etiquette, 2026-07-23). **The fallback re-spec this item used to hold open is NOT needed** — item 1's experiment came back positive, so the template channel is the channel and `settings.local.json` is not being promoted to carry the fleet grant. What follows is the unchanged division of labour, not a fallback. Under `dontask` — auto-deny-everything-unlisted — task-specific allowlists live in a `settings.local.json` dropped into the worker's cwd, with **deny rules as hard fences** (`Bash(git push:*)`). Permission sources union their allows and deny always wins, so the split of responsibilities is clean: the fleet-owned template carries exactly the one fleet-owned grant (`fleet q` works in every indexed project with zero per-spawn setup), per-task grants stay in the worktree file, and a worktree deny rule can still fence `q` off for a specific task — the template grant cannot override a local fence. Nothing in the doctrine moves; the template just stops shipping permissions-empty.

### 11.8 Teaching the worker the tool exists

A worker cannot call a tool it has never heard of, and `compose_prompt`'s preamble is fleet's only worker-facing channel. M2 adds **at most 4 preamble lines** teaching `fleet q` (name, one-line contract, `--src`, `--outline`) — rendered **only when the dispatch target's `--dir` contains `.fleet-index/`** at compose time. The check runs wherever compose runs, so the teach lines render on **all four compose paths** — spawn, idle-send (fork-steer), resume-limited, respawn (§3's call sites) — i.e. per **dispatch**, consistent with §3's re-paid-per-dispatch analysis: a respawned or steered worker in an indexed project is re-taught, and a worker in a non-indexed project pays zero tokens and sees no mention of a tool that would exit 3.

**Four compose paths, FIVE dispatch paths — and the difference is not a rounding error.** "All four compose paths" is a claim about `compose_prompt`'s call sites, and it is true. It is *not* a claim about every worker session fleet launches: `_dispatch_supervisor_body` renders its own body through `_render_sup_spawn_task` and has never called `compose_prompt`, so the supervisor's gen-0 body gets no teach lines and no census over compose call sites can ever see it. That is a deliberate scope boundary (the supervisor body is a fixed boot ritual, not a task prompt), recorded here because it was previously invisible: the test that called itself "the only thing that fails if a FIFTH dispatch path is added" enumerated `compose_prompt` callers only. There are now **two censuses** — one over `compose_prompt` call sites (pinned at four) and one over `dispatch_bg` call sites (pinned at five) — so the next dispatch path has to be assigned to one of them rather than falling between both.

**Built 2026-07-27.** The cap and the two call-site facts are pinned rather than asserted. Four lines, counted off the constant's own continuation strings; the check inside `compose_prompt` (so every compose path gets it by construction, which is what makes "all four paths" a property rather than four coincidences); and the digest's single read, which goes through §11.3's choke point:

```
# at 1844a1f
$ sed -n '/^INDEX_TEACH_LINES = ($/,/^)$/p' bin/fleet.py | grep -c '\\n"$'
4
$ echo "exit $?"
exit 0
```

```
# at 1844a1f
$ grep -n 'index_teach_lines(cwd)\|verified_shard_rows(root, rel, sleep=sleep)' bin/fleet.py
1354:             + index_teach_lines(cwd)]
15379:def index_teach_lines(cwd) -> str:
15458:        result = verified_shard_rows(root, rel, sleep=sleep)
```

**The second gate, added 2026-07-27: the verb must exist.** The paragraph above justifies the index check with "a worker in a non-indexed project … sees no mention of a tool that would exit 3". That argument does not stop at the index. Measured on the slice that first shipped these lines: `fleet q foo` exited **2** with an argparse `invalid choice: 'q'` — the verb was not registered at all — while the teach lines taught it and the template granted `Bash(fleet q:*)`. A worker had been handed a lesson and a permission for something this build did not have.

So `index_teach_lines` renders **only when both gates pass**: the dispatch target carries `.fleet-index/`, **and** every `fleet <verb>` the teach lines name is a registered subcommand. The verb list is **derived from `INDEX_TEACH_LINES` itself**, not written down twice, so a fifth line naming a new verb cannot slip past because a hand-written tuple was not extended. The gate reads `build_parser()`, so it is **unconditional and self-correcting**: it needs no flag, no branch check and no knowledge of which slice landed, and the lines light up on their own the moment `fleet q` is registered. The two gates are AND, not OR — a registered verb is not an opt-in.

```
# at 9f7fe26
$ grep -n 'def index_teach_verbs\|def registered_cli_verbs\|if any(verb not in available' bin/fleet.py
15491:def index_teach_verbs() -> tuple:
15502:def registered_cli_verbs() -> frozenset:
15548:    if any(verb not in available for verb in index_teach_verbs()):
```

The honest adoption risk, unchanged from the review: these lines arrive inside a tool result (the task-file Read), competing against `Read`/`Grep`, which sit in the system region and need no learning. That is why §11.9 exists and why it carries a revert trigger, not a hope.

### 11.9 Adoption measurement and revert criterion

M2 is accepted or reverted on measurement, under the tokens-primary doctrine (operator sub-decision (b), §12):

- **Primary metric:** `input_tokens` from Stop-hook outcome records, on a fixed task run as **≥3 paired A/B runs** — arm A: indexed project, teach lines present; arm B: same task, no index. Success = arm A's median total input tokens lower.
- **Adoption check (diagnostic, volatile):** the §12 `tools/` transcript diagnostic additionally counts `fleet q` invocations per session. It is sunset-marked and decides nothing by itself — except one thing: **zero `fleet q` calls across all A-arm runs voids the token comparison** (whatever moved, it wasn't `q`) and is itself a revert trigger.
- **Ordering gate: SATISFIED 2026-07-27.** Adoption counts only after §11.7's execution receipt exists — the live proof that a default-spawned `dontask` `--bg` worker can execute a granted command via the template grant alone. That receipt is now landed in §11.7 item 1, so **runs recorded from 2026-07-27 onward count toward both prongs; anything earlier is void.** The gate was never about a date, it was about the confound: zero adoption under an unproven grant would fire the revert against a permission bug rather than against the tool. That confound is now measured away, with one residual named in §11.7 — the experiment proved the grant *shape*, not the literal `Bash(fleet q:*)` string, so an A-arm run showing zero `fleet q` calls must still rule out a plain typo in the template before it counts as non-adoption.
- **Revert criterion** (counting only runs recorded on or after 2026-07-27, when §11.7's grant-execution receipt landed — both prongs): zero adoption across ≥3 A-arm runs, **or** no median input-token reduction across ≥3 pairs → revert M2's worker-facing surface: remove the preamble teach lines and the template `permissions` entry (one more `fleet init` propagation), and record the revert as a dated `knowledge/lessons.md` entry. The `fleet q` subcommand itself may stay as manager-side tooling — it costs nothing per worker once the teach lines and grant are gone.

## 12. Testing and acceptance

Per SPEC §17, pytest for unit tests.

- Indexer: golden-file per language (including `kind=section` `end` = next same-or-higher heading or EOF, §11.4); unparseable handling; incremental skip; atomic-replace under an injected crash between write and rename, and under an injected Windows-style `PermissionError` on the replace (bounded retry, then leave-stale — §6). Goldens use forward-slash shard paths and are byte-identical on win32 and POSIX (§11.2).
- Sharding: two disjoint source edits produce two disjoint shard writes and merge cleanly.
- Staleness: a stale shard is refreshed then answered; corrupt and truncated shards take the same path; no path serves an unverified coordinate.
- `compose_prompt`: composition order, `--context` resolution against `--dir`, unknown-path tolerance, and that absent `--context` changes the prompt not at all.
- Config: absent config = defaults; `init` always writes the `.gitignore` entry; an unrecognised key (including the reserved `mode`) is a loud config error.
- `fleet q` (M2): golden tests for the three query forms and their **short-circuit order** (an exact hit suppresses tail matching; ambiguity within a tier still exits 1 under `--src` — §11.2); matching-semantics goldens that run unchanged on win32 and POSIX: exact/tail byte-wise case-sensitive, glob via `fnmatchcase` (a `beta.*` glob matches `Beta.run` on no platform), and `<path>:<line>-<end>` output uses forward slashes on Windows (§11.2); `--src` slice byte-exact against the source file; the 400-line `--src`/`--outline` cap with its `[truncated N lines — narrow the query]` trailer and unchanged exit code (§11.4); stale/corrupt/missing shard refreshed before answering; a mid-swap read failure treated as stale (§11.5); `--outline` failure rows — unknown path exits 1 with a candidate list, header-only shard exits 0 empty, stale shard takes the stale contract (§11.5); `--no-refresh` withholds and writes nothing (assert directory mtimes untouched); orphan-shard suppression and pruning; exit-code contract 0/1/2/3 including ambiguous `--src`; index-root walk-up from a subdirectory, **stopping at a `.git` boundary — a nested worktree without its own index exits 3, never resolves the parent's** (§11.1); truncation via `--limit` still exits 0 with a stderr count.

**Acceptance for M1 — tokens-primary** (operator sub-decision (b), 2026-07-23, `docs/OPERATOR-GATES.md`). The metric is the `input_tokens` delta already recorded per turn by the Stop-hook outcome record (usage parsed at `bin/hooks/stop_outcome.py:186-189`, written into the record at `:231-233`) — zero new parsing of the unversioned transcript format, and the token delta is what M3's go/no-go economically turns on. The criterion is:

1. On a fixed task run as **≥3 paired A/B runs** — each pair once with `--context`, once without (a single pair is swamped by run-to-run variance) — the `--context` arm's median total input tokens are lower.
2. `fleet index build` is byte-reproducible: two runs on an unchanged tree produce identical shards.
3. A mutated source file never yields a stale coordinate.
4. Deleting `.fleet-index/` returns fleet to baseline behaviour with no errors.

The transcript tool-call counter an earlier draft made criterion 1's instrument is **demoted to a diagnostic**: a volatile, sunset-marked script under `tools/` that counts Read/Grep (and, for M2, `fleet q`) calls per session by parsing transcripts. It carries no receipt pins, adds no `bin/fleet.py` surface, and is delete-eligible with a dated record after M3's go/no-go. It explains *why* a token delta moved; it never decides acceptance.

Result (1) is the input to M3's go/no-go: without a measured saving from targeted digests, an always-on map cannot be justified.

## 13. Review disposition

All 10 findings from `docs/reviews/IDX-ADVERSARIAL-2026-07-22.md`. Manager spot-checked every code citation against `bin/fleet.py` before accepting.

| # | Finding | Sev | Disposition |
|---|---|---|---|
| 1 | §2's prefix-keyed-cache mechanism false; composed prompt is delivered as a tool result | MED | **Accepted.** §2 rewritten to the mechanism provable from this repo (`dispatch_bg` task-file write + tiny prompt, `bin/fleet.py:8240,8244` at `3ccb2d5`). The `CLAUDE.md` shared-channel question is recorded as open, not silently resolved. |
| 2a | Name-sorted global `symbols.tsv` conflicts at N=2, retiring 7-wide parallelism | CRITICAL | **Accepted, restructured.** Sharded per source file; sorted by line. No global file exists, so the conflict cannot arise. `files.tsv` deleted (it had the same defect); digests and map became on-demand renderings. |
| 2b | Query-time refresh dirties a tracked file, breaking `git worktree remove` | HIGH | **Accepted; re-dispositioned 2026-07-23** (operator sub-decision (a), council round 2). Tracked mode is removed entirely: committing `.fleet-index/` is **documented-unsupported** (§8), so the dirty-tracked-file hazard cannot arise. The refuse-on-stale branch this finding originally produced is deleted with the mode; per the dissent's binding process note, this row — not deleted text — is the record. |
| 3 | Always-on map has no net-positive task mix here; per-dispatch not per-spawn | HIGH | **Accepted.** Map removed from M1 entirely; M3 is opt-in and gated on M1's measurement. The per-dispatch correction is stated in §3. |
| 4 | `fleet q` blocked — default mode `dontask`, template has no permissions block | CRITICAL | **Accepted.** Moved to M2 behind an explicit permissions-migration gate (§11). |
| 5 | No lock or atomic write; §9's "corrupt = skip malformed lines" contradicts §8 | HIGH | **Accepted.** Atomic `os.replace` per shard (§6); corrupt shards are treated as stale, never parsed optimistically (§9). Sharding also shrinks each write to one small file. |
| 6 | Six of eight code citations wrong — and they were the worked example | HIGH | **Accepted.** Every repo citation re-derived and manager-verified at acceptance (against the 2026-07-22 8,706-line tree), then **re-derived 2026-07-24 at merge-base `3ccb2d5`** (11,288 lines — every line-number citation had rotted; fix wave 1, header note). All format examples replaced with synthetic placeholders that make no claim about any real file. |
| 7 | Two fenced blocks parse as executable receipts and fail | HIGH | **Accepted; superseded 2026-07-27.** The original disposition was "no `$ `-prefixed lines in this document, so it contains no receipts", declared `UNENFORCED` in `tests/test_receipts.py` because it specced unbuilt behaviour. M1 and M2's worker-facing surface are now built, so the document carries real pinned receipts (§11.7 item 1, §11.8) and has moved to the **enforced** set with a `RECEIPT_FLOOR` entry. The finding's actual lesson — a fenced block that *looks* like a transcript must either be one or not look like one — is what the format examples' synthetic placeholders (finding 6) and the pinned blocks now jointly satisfy. |
| 8a | §5.4 "fixed per-spawn cost" false | MED | **Accepted** — corrected in §3, and moot for M1 since the map is gone. |
| 8b | Invariant-4 argument does not hold on the idle-send path | MED | **Accepted.** §7 states the limit explicitly rather than generalising from respawn. |
| 8c | Success criterion 1 not measurable with shipped telemetry | LOW | **Accepted; re-dispositioned 2026-07-23** (operator sub-decision (b)). Criterion 1 is re-based onto the `input_tokens` delta the Stop-hook outcome record already ships, over ≥3 paired A/B runs; the transcript counter survives only as a volatile sunset-marked `tools/` diagnostic (§12). |
| 8d | `--context` path resolution unspecified | — | **Accepted.** §7 fixes resolution to the worker's `--dir`. |
| 8e | Section numbering | — | **Accepted** — renumbered in this document. |

Not adopted: nothing. All findings were accepted; the CRITICALs forced the restructure into M1/M2/M3 and the shard layout.

## 14. Invariants touched

Citing `docs/SPEC.md` §16. (The invariants-touched discipline originated in ROADMAP, which is superseded history per the settled "Two roadmaps" gate, 2026-07-23, `docs/OPERATOR-GATES.md` — the discipline is kept on its merits, the ROADMAP cite is not live law.)

| # | Invariant | Status |
|---|---|---|
| 1 | daemonless launch | **Preserved.** `fleet index` and `fleet q` are short-lived CLI invocations. No resident process, no scheduler. |
| 2 | exit-0 hooks | **Preserved.** No hook added or modified. Index updates are explicit CLI calls, not hooks — a `PostToolUse` or `post-merge` hook would index on every write regardless of review state. |
| 4 | journal-injection-at-respawn | **Touched, preserved.** `compose_prompt` gains a source; the journal is still composed and retains final position on every path that carries one (§7). |
| 5 | cwd-scoped dispatch | **Preserved.** `--context` resolves against the worker's `--dir`, introducing no second cwd frame (§7). |
| 8 | platform-adapter-only OS branching | **Preserved.** All index paths go through `pathlib`; no OS branch, no new adapter method. |
| 9 | one-state-many-views | **Touched, argued preserved.** The index is not fleet state: it derives from a target repo's source, not from the registry, and no fleet decision reads it. `fleet q` likewise reads no registry, takes no `fleet.lock`, and probes no PID (§11.6). The registry remains the single state with `status_snapshot()` its one derivation. |
| 10 | spec-bound work (`[PRESCRIPTIVE — UNBUILT]`) | **Untouched.** fleet-index binds no worker to a spec and adds no verifier or gate surface. Its outputs are compatible with invariant 10's corollaries by construction — a shard and a `q` answer are deterministic functions of the working tree's bytes, never interpretations of agent prose, and nothing here executes author-supplied input — but no verdict derives from them. |

Invariants 3 (mailbox), 6 (single-writer registry) and 7 (one live session per name) are untouched — no registry write, no dispatch-path change, no session lifecycle change. The §16 carried post-pivot rules (never-demote-unknown, G9 epoch freeze, tombstone obligation, no daemon/jobs-file access) are likewise untouched: the index reads no roster, writes no outcome record, and touches no daemon file.

## 15. Out of scope

- **Call graph / `callers()`** — a natural addition over the same shards; deliberately deferred.
- **`relevance` map degradation** — cut. It is ranking, and ranking is what killed the ancestor (§10).
- **Cross-session token sharing** — impossible (§2).
- **Embeddings, semantic chunking, similarity search** — excluded by design (§10).
- **GraphQL or SQL query layers** — possible later over the same shards; rejected now (schema-in-context cost; opacity).
- **Auto-selecting `--context` from task text** — the manager names files explicitly.

## 16. Doc-sync owed

Edits this spec obligates in **other** documents. Enumerated so the gate can check them off; deliberately **not** made on this branch — this branch edits `docs/specs/fleet-index.md` only.

1. `docs/SPEC.md` §18 — fleet-index milestone entry (§18 currently stops at M-C; the §16 fleet-index paragraph there also still cites the rotted `@8478` dontask default — now `:10985` at `3ccb2d5`).
2. `knowledge/playbooks/spawn-etiquette.md` — the "template carries hooks only, no permissions" line rots when §11.7 lands its `permissions` key.
3. Campaign worktree recipe / campaign template — add the manager-side `fleet index init --path <worktree>` step (§8).
4. ~~`tests/test_receipts.py` — this file's `UNENFORCED` reason string still says "M1 ready-for-build"~~ — **done 2026-07-27.** The string did rot, exactly as predicted, the moment anything built. Resolved by removing the entry rather than rewording it: this document now carries pinned receipts, so it belongs in the enforced set with a `RECEIPT_FLOOR` entry, and the reason string has nothing left to rot.
5. `docs/PLAN-PROGRESS.md` lines 147 and 156 — both fleet-index rows still say "design-approved / gate-row owed" and "ready-for-build (M1 only), operator-gated"; superseded by the 2026-07-24 full-M1+M2 order.
6. `docs/NEXT-SESSION.md` items 4 and 8 — the "M1 go/no-go with the fresh evidence" decision item and the evidence note are resolved by the 2026-07-24 order (§1).
7. `docs/OPERATOR-GATES.md` — settled row recording the 2026-07-24 full-M1+M2 build order (until it lands, the `knowledge/lessons.md` day-3 entry ("2026-07-24 — operator morning queue cleared + autonomous day-3 opened", on `main`) is the record of record — header).
8. Root `CLAUDE.md` — "pytest for unit/hook tests (SPEC §12)": the testing tiers now live at SPEC §17.

## 17. Changelog

- **2026-07-27 — M2 fix wave (gate `GATE-TEACH-RB ESCALATE`, four CRITICALs settled by execution).** §9 gains the **compose-order invariant**: `compose_prompt` runs before the spawn's pre-claim registry commit, and the per-path digest body warns and skips instead of raising — a `--context` file whose shard directory could not be created used to leave `{"status": "working", "session_id": null}` plus a `spawned` event behind, a live-looking worker that never existed. §11.8 gains a **second gate**: the teach lines render only when every `fleet <verb>` they name is registered on the parser, because the slice that shipped them taught `fleet q` while `fleet q foo` exited **2**. §11.8 also records that there are **five** dispatch paths, not four — `_dispatch_supervisor_body` renders its own body and is invisible to a census over `compose_prompt` callers, and that census's walk-back matched `def ` at column zero only, so a line-count-neutral fifth path added as a class method left the whole suite green. §11.7 item 2 gains the **`instance-grants` doctor check** — widening the instance to the kill grant `Bash(fleet:*)` read `[PASS]` and a second `fleet init` repairs it; doctor now says so. §7 discloses the **measured** cost of the uncapped digest (539 lines / 27,835 chars for `bin/fleet.py`; ~1.39 MB for fifty such files) and dedupes repeated `--context` paths; **no cap was added**, because §11.1's "the two renderings differ only when the cap truncates" makes that a spec decision. §11.7 item 1's experiment receipt **is no longer `# volatile`**: it read a live absolute path into the supervisor's uncommitted working journal, so its `# at` pin constrained nothing and it reproduced by accident; the transcript is now committed as an immutable artifact (`docs/specs/receipts/fleet-index-11.7-grant-experiment.txt`) and the receipt is re-pinned repo-relative and enforced. It is **not** committed into `supervisor/JOURNAL.md` — that is the supervisor's append-only working file and would conflict with `main` on every future merge while still churning by design.
- **2026-07-27 — M2 worker-facing surface built; the owed receipt landed.** §11.7 item 1's `[UNVERIFIED — live receipt owed]` is flipped to `[VERIFIED — live two-arm experiment, 2026-07-27]`: the hard M2 build-gate item was run (supervisor checkpoint G-B) and came back **positive**, so the template channel works and item 3's fallback re-spec is **not needed** — item 3 now says so rather than standing as a live branch. §11.9's ordering gate is marked **satisfied**, with the residual named (the experiment proved the grant *shape*, `Bash(py -3.13 -c:*)`, not the literal `Bash(fleet q:*)`). The experiment receipt landed `# volatile` — *superseded by the 2026-07-27 fix wave above, which found the stated reason false and re-pinned the block against a committed excerpt.* This document consequently leaves `tests/test_receipts.py`'s `UNENFORCED` set (finding 7's disposition superseded, §16 item 4 closed) and gains a `RECEIPT_FLOOR`. Also built and receipted: §7's `--context` flag (spawn-only) and §11.8's teach lines on all four compose paths.
- **2026-07-24 — fix wave 1 (dual-lens gate).** All `bin/fleet.py` / `stop_outcome.py` citations re-derived at merge-base `3ccb2d5` (header note; the 2026-07-22 line numbers had all rotted). §11.1 gains the repository-boundary rule (walk-up stops at the first `.git` entry, file or dir — nested worktrees can no longer resolve a parent index). §11.7's template-grant mechanism marked `[UNVERIFIED — live receipt owed]` with a hard M2 gate item; §11.9 revert now gated on that receipt. Windows `os.replace` sharing-violation contract specified (§6, §11.5, §11.6). win32 matching semantics pinned — case-sensitive exact/tail, `fnmatchcase` globs, forward-slash paths everywhere (§11.2). `fleet index update` file-list flag renamed `--paths` → `--files` and `update` gains `--path DIR` root resolution (§6). `--src`/`--outline` 400-line cap, `kind=section` end definition, `--outline` failure rows, teach-lines-on-all-compose-paths, and §12 golden-test coverage for all of the above.
