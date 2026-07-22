# fleet-index — cutting duplicate exploration cost

**Status:** design, approved 2026-07-22
**Problem owner:** Altai
**Scope:** one milestone. Indexer + `fleet q` + spawn-time injection, shipped together.

---

## 1. Problem

Fleet's dominant cost is workers re-reading the same code. Five surfaces contribute:

1. **Exploration reads** — every worker Reads/Greps the same files to orient before doing any work.
2. **Subagent fan-out** — each worker's subagents repeat that orientation from scratch, multiplying it.
3. **Manager-side review** — the manager re-reads `SPEC.md`, diffs, and review docs across turns.
4. **Respawn** — `fleet respawn` resets context, so the fresh session re-learns what it already knew.
5. **Incidental reads** — reading files for reasons other than orientation.

`bin/fleet.py` is 7832 lines. A worker that Reads it to find one function pays for all of it.

## 2. What is not achievable

**No mechanism shares tokens across sessions.** Workers are separate `claude` processes with separate context windows, billed separately. Prompt caching does not bridge them: the cache is prefix-keyed, and every worker's prefix differs (name, task text, journal), so file content sitting mid-context never hits a shared entry.

This was checked before design, and it rules out the intuitive framing ("let workers share what they've read"). The achievable levers are exactly two:

- **Fewer reads** — the worker already knows the thing, so it never issues the call.
- **Smaller reads** — the worker gets 40 lines instead of 7832.

Every component below serves one of those. Anything claiming cross-session dedup is wrong.

## 3. Design decisions

| Decision | Choice | Why |
|---|---|---|
| Delivery of pre-known context | Always-on repo map + task-scoped digests | Cheap floor for every worker; targeted top-up when the manager knows the blast radius |
| Digest generation | Deterministic parse (stdlib `ast` + per-language heuristics) | Zero token cost, zero hallucination, offline, reproducible. A wrong digest is worse than none. |
| Staleness handling | Content-hash keyed, regenerate on demand | Always correct; cost proportional to churn |
| Query interface | CLI subcommand, `fleet q` | MCP tool schemas are resident in every worker's context whether used or not (~600–1000 tok/worker/session). A CLI costs zero until invoked, and workers already have Bash. |
| Index format | Plain-text TSV | Greppable with no tooling, hand-editable, git-diffable, no opaque store |
| Query language | None — flags over a text index | Rejected GraphQL (schema must live in context; model must compose valid queries) and SQL/SQLite (opaque, not hand-editable) |
| Index location | `<project>/.fleet-index/` | Travels with the repo, reviewable in PRs, correctable by hand |

### 3.1 Why an index at all, given grep beats RAG

Recent results favour agents with plain search over embedding-retrieval pipelines. The mechanism is **exactness**: grep returns line-anchored, verifiable hits; RAG returns approximate chunks with semantic drift.

This design does not contradict that finding — it applies it:

- **No embeddings, no semantic chunking, no similarity search.** Anywhere.
- The index stores **exact derived facts** — real signatures, real line numbers — never summaries treated as truth.
- Grep on the raw repo keeps working, untouched. The index is strictly additive.

Plain grep's weakness was never accuracy; it is that grepping a 7832-line file returns heavy surrounding context and workers do many rounds. The fix is to **give grep a denser corpus**, not to replace it. `symbols.tsv` is that corpus, and it is itself a grep target.

Prior art: this is a `tags` file. Line-oriented, plain-text, portable, ~40 years of use across every OS.

## 4. Architecture

```
indexer (deterministic parse, stdlib-only)
   │
   ├─→ .fleet-index/files.tsv        path  hash  lines  lang
   ├─→ .fleet-index/symbols.tsv      name  path  line  end  kind  sig
   ├─→ .fleet-index/digests/<p>.md   per-file outline
   └─→ .fleet-index/map.md           repo map, budget-capped
         │
         ├─→ compose_prompt()   injected at spawn   → fewer reads
         └─→ fleet q            queried on demand   → smaller reads
```

One store, two consumers. Pre-injection covers what a worker needs *before* it knows to ask; `fleet q` covers what it discovers it needs mid-task.

## 5. Artifacts

All under `<project>/.fleet-index/`. The indexer adds `.fleet-index/` to the project's `.gitignore` only if the user opts in via config; default is git-tracked, since reviewability was the reason for choosing a text format.

### 5.1 `files.tsv`

One line per indexed file. Tab-separated, no header, sorted by path.

```
path	hash	lines	lang
bin/fleet.py	a3f21c8e	7832	python
docs/SPEC.md	91b4de07	275	markdown
```

`hash` is the first 8 hex chars of SHA-256 over file bytes. It is the staleness key (§8).

### 5.2 `symbols.tsv`

One line per symbol. Tab-separated, no header, sorted by name then path.

```
name	path	line	end	kind	sig
compose_prompt	bin/fleet.py	887	946	func	(name, task, sid) -> str
dispatch_bg	bin/fleet.py	6621	6702	func	(worker, prompt_body) -> int
mailbox_dir	bin/fleet.py	69	71	func	() -> Path
```

- `kind` ∈ `func` | `class` | `method` | `const` | `section` (markdown headings)
- `end` enables source slicing without re-parsing
- Hash lives in `files.tsv`, not here — repeating it per symbol would bloat every grep hit
- Literal tabs in `sig` are escaped `\t`; newlines are stripped

Density is the point: no repeated field names, so a grep hit is nearly all signal. This is why TSV beat JSONL (2–3× the tokens for identical information, paid on every hit).

### 5.3 `digests/<path>.md`

Per-file outline, mirroring source directory structure (`digests/bin/fleet.py.md`). Generated, but hand-editable — an edited digest survives until its source file's hash changes.

```markdown
## bin/fleet.py (7832 lines, python)

- L69 `mailbox_dir() -> Path`
- L887 `compose_prompt(name, task, sid) -> str`
- L2237 `cmd_spawn(args)`
- L6621 `dispatch_bg(worker, prompt_body) -> int`
```

### 5.4 `map.md`

Repo-wide orientation: directory tree plus one line per file. Budget-capped (§7). This is the artifact injected into **every** worker, so its size is a fixed per-spawn cost and must stay bounded.

## 6. Components

### 6.1 Indexer

```
fleet index init   [--path DIR]           # opt in: create .fleet-index/, first build
fleet index build  [--path DIR] [--force] # rebuild an existing index
fleet index update [--paths P,...]        # refresh named files (post-review gate)
fleet index status [--path DIR]           # counts, stale files, map token estimate
```

**Indexing is opt-in per project.** `fleet index init` is the only command that creates `.fleet-index/`; nothing else does, ever. `build`, `update`, and `q` all fail with "no index — run `fleet index init`" if the directory is absent. A project that never runs `init` is untouched by this feature, and `fleet spawn` there behaves exactly as it does today.

Deterministic parse only. Per language:

- **Python** — `ast` module. Functions, classes, methods, module constants, first docstring line.
- **Markdown** — heading extraction, `kind=section`.
- **JSON/TOML** — top-level keys.
- **Everything else** — recorded in `files.tsv` with path and line count; no symbols.

Incremental by default: files whose hash matches `files.tsv` are skipped. `--force` rebuilds all.

`fleet index status` reports file count, symbol count, stale-file count, map token estimate.

### 6.2 `fleet q`

Never writes source files and never touches fleet state (registry, mailboxes, journals). It *does* write `.fleet-index/` when it detects a stale entry (§8) — so it is read-only with respect to everything that matters for safety, but not literally side-effect-free. `--no-refresh` suppresses the write and reports staleness instead, for contexts where any write is unacceptable.

```
fleet q <symbol> [--src] [--path GLOB] [--kind KIND] [--limit N]
fleet q --outline <path>       # print that file's digest
```

Default output — pointers, one line per hit:

```
$ fleet q compose_prompt
bin/fleet.py:887  func  compose_prompt(name, task, sid) -> str
```

With `--src` — resolves the symbol, then reads the real file and prints lines `line..end`:

```
$ fleet q compose_prompt --src
bin/fleet.py:887-946
<actual source of those 60 lines>
```

**The slicing is the token win.** Pointer-only output still leaves the worker to Read the file; slicing means it never does. Source always comes from the file on disk, never from the index — the index supplies coordinates, the file supplies truth.

Invoked as a subcommand of the existing CLI, so it inherits the launcher and install path already made portable across Git Bash / macOS / Linux. Permission grants stay subcommand-scoped per the CLAUDE.md rule (`Bash(fleet q:*)` is read-only and safe to allowlist broadly; granting `Bash(fleet:*)` is not, and a prior incident had a read-only slash command run `fleet clean`).

### 6.3 Spawn-time injection

`compose_prompt` (`bin/fleet.py:887`) today assembles four sources: preamble → drained mailbox → task text → prior journal. It gains a fifth, and the preamble gains a pointer to the tool.

```
preamble               (+ ~4 lines teaching `fleet q`)
REPO MAP               (always, budget-capped)
DIGEST <file>          (per --context file)
mailbox                (unchanged)
task text              (unchanged)
journal                (unchanged)
```

```
fleet spawn foo --dir /c/proj --task @task.md --context bin/fleet.py,docs/SPEC.md
```

The preamble addition is load-bearing and easy to forget: **a worker cannot use a tool it does not know exists**, and `compose_prompt` is the only channel that reaches workers. Without it the CLI ships and goes unused.

`--context` accepts paths or globs. Unknown paths warn and are skipped; they never fail the spawn.

### 6.4 Index lifecycle — who updates it, and when

The index is a **build artifact committed alongside the code it describes**, so its git history matches the code's. That forces a rule about when it may be written.

Two writes exist, and conflating them is the failure this section prevents:

| Write | Trigger | Scope | Committed? |
|---|---|---|---|
| **Staleness refresh** | `fleet q` sees a hash mismatch (§8) | The one queried file | No — working-tree only |
| **Gated update** | Worker's change passes its review gate and merges | All files in the merge | Yes — same commit as the code |

**Staleness refresh exists purely for correctness.** A worker mid-task has edited files; a query against one of them must not return a stale line number. The refresh keeps the answer honest. It does *not* mean the index now describes reviewed code — it describes the working tree, which is exactly what that worker needs.

**The gated update is what lands in git.** A worker's edits reach the shared index only after the change passes review and merges. Index churn is then reviewable in the same diff as the code that caused it, which is the reason the format is plain text.

Ordering in the campaign flow:

```
worker edits code
  → review gate
  → PASS
  → merge
  → fleet index update --paths <files touched by the merge>
  → commit index alongside (or amend into) the merge
```

The manager owns this step, consistent with it owning merges today. It goes into the campaign template as a standing post-merge action alongside the existing post-merge checks.

**Why not a git hook or a `PostToolUse` hook.** A `post-merge` hook fires on every merge including ones that bypassed review, and `PostToolUse` fires on every file write — both would index unreviewed code into the shared artifact, defeating the gate. The manager-side step is the only place that knows a review actually passed.

**Failure is non-blocking.** If `fleet index update` fails, the merge stands and the index is stale until the next update. A stale index degrades to today's behaviour (§9); it never blocks a landing.

## 7. Configuration

Optional `<project>/.fleet-index.toml`, read with stdlib `tomllib`. Absent = defaults, zero setup.

```toml
[map]
max_tokens = 2000        # hard cap on map.md
degrade = "tree"         # "tree" | "relevance"

[index]
include = ["**/*.py", "**/*.md"]
exclude = ["**/node_modules/**", "**/.venv/**", "**/target/**"]
gitignore = false        # true → add .fleet-index/ to project .gitignore
```

**Degradation** applies when the map exceeds `max_tokens`:

- `tree` (default) — drop per-file one-liners, keep the directory tree and top-level entry points. Predictable, never wrong.
- `relevance` — keep detail for directories the task text mentions, collapse the rest. Better targeting, but the relevance pass can mis-pick.

Token estimate is characters/4 — an approximation, deliberately not an API call. The cap is a guardrail against runaway injection, not an accounting boundary.

## 8. Staleness

`fleet q` re-hashes the source file before answering and compares against `files.tsv`. On mismatch it reindexes that one file, then answers.

This matters more than it appears: **a stale line number does not error.** It silently slices the wrong code, and the worker has no way to detect it. Correctness here is worth the per-query hash.

Cost is one file hash per query, and a single-file reparse only on actual change.

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| Unparseable file | Recorded in `files.tsv` with path + line count, no symbols. Never aborts the build. |
| No index (never `init`ed) | `fleet q` prints "run `fleet index init`", exits non-zero. Spawn injects nothing and proceeds normally. Expected state for most projects. |
| `fleet index update` fails post-merge | Merge stands, index goes stale, next update repairs it. Never blocks a landing. |
| Index corrupt | Same as missing — malformed lines are skipped, not fatal. |
| Symbol not found | Exit non-zero with a message suggesting `grep`. |
| Ambiguous symbol | All matches printed; `--path` narrows. |
| `--context` path unknown | Warn, skip, spawn continues. |

**The safety property:** grep on the raw repo always still works. The index is additive — if all of it breaks, workers fall back to Read/Grep and lose ergonomics, not capability. Nothing in fleet becomes dependent on the index being present or correct.

## 10. Testing

Per SPEC §12 — pytest for unit and hook tests.

- Indexer: golden-file tests per language; unparseable-file handling; incremental skip via hash
- `fleet q`: symbol resolution, `--src` slicing correctness (byte-exact against source), ambiguity, not-found exit codes
- Staleness: mutate a file, confirm reindex-and-correct-answer rather than stale slice
- `compose_prompt`: composition order, `--context` expansion, unknown-path tolerance
- Config: cap enforcement, both degradation modes, absent-config defaults

Live tier: spawn a haiku worker in a temp repo with an index present; confirm it reaches for `fleet q` over `Read`. Per the M-D lesson on probe context, uncontrolled-context checks belong in the manager's interactive run, not a `--bg` worker.

## 10a. Graveyard answer — IDEA-FORGE §5 entry 5

ROADMAP's speccing discipline requires checking `docs/IDEA-FORGE-REPORT.md` §5 before proposing anything adjacent to a dead idea. **This design has a direct ancestor there**, and it must answer each cause of death or it is a re-proposal of a rejected idea.

> **5. Knowledge-Aware Context Assembly at Spawn/Respawn (3.0)** — right moat, wrong build: grep-isn't-ranking, silently-rotting tag schema as load-bearing element, stale cross-project lore injected ahead of grounded journal replay is a fleet-wide prompt-poisoning vector, duplicates CLAUDE.md/MEMORY.md and sits in first-party's path.

| Cause of death | Answer |
|---|---|
| **grep-isn't-ranking** | Mostly avoided by construction: `fleet q` is exact symbol lookup, and `map.md`/digests are deterministic structure. Nothing is ranked or scored. **Except `degrade = "relevance"` (§7), which is ranking and re-imports the exact flaw.** Resolution: `tree` is the default; `relevance` is opt-in, documented as carrying the ancestor's failure mode, and a candidate for deletion if it does not prove itself. |
| **silently-rotting tag schema as load-bearing element** | This design *is* a tag file, so this is the load-bearing objection. The answer is §8: every entry is content-hash keyed and re-checked per query, so the index cannot rot silently — it detects and repairs. The ancestor had no staleness detection; that is the difference, and it is the single most important property in this document. |
| **stale cross-project lore ahead of journal replay = prompt poisoning** | Three structural differences. (a) **Not cross-project** — the index lives inside the project it describes and never crosses repo boundaries. (b) **Not lore** — derived structural facts (signatures, line numbers) that the worker can verify against the file, not prose assertions about how things work. (c) **Not ahead of the journal** — §6.3 keeps the journal in final position, the strongest recency slot; index material sits ahead of the task, never displacing grounded predecessor experience. |
| **duplicates CLAUDE.md/MEMORY.md** | Those are hand-written prose doctrine ("Python is `py -3.13`"); this is generated structural fact ("`compose_prompt` is at `bin/fleet.py:887`"). Different content, different lifecycle, different failure mode. No overlap in what they assert. |
| **sits in first-party's path** | Conceded — Anthropic may ship code indexing in Claude Code. Mitigations: the artifact is a plain text file usable by anything, and the two halves are separable. If first-party ships equivalent search, `fleet q` is deleted and the spawn-injection half (which first-party cannot do — it requires knowing what fleet is spawning) survives intact. Sizing the tool half small is deliberate for exactly this reason. |

## 10b. Flag, not subsystem

ROADMAP requires re-vetting every proposed subsystem for a flag-sized alternative delivering 80% of the value.

The flag-sized alternative is **`fleet spawn --context <files>` that inlines raw file contents, with no index at all.** It is genuinely cheaper, and it delivers a real share of the value — a worker that gets the two files it needs does skip its orientation reads.

Why the subsystem is still justified, and where the line falls:

- Raw inlining does not scale to orientation. A worker that needs to know *where* things are cannot be handed `bin/fleet.py` (7832 lines) — that costs more than the exploration it replaces. Digesting is what makes injection affordable, and digesting requires a parser.
- `fleet q --src` has no flag-sized equivalent: slicing a symbol out of a file requires knowing its line range, which requires the index.

**Honest scope reduction this implies:** if the milestone must shrink, the order to cut is `relevance` degradation first, then `map.md`, then `fleet q`, keeping digest injection last — it is the piece with the clearest ratio and no flag-sized substitute.

## 10c. Invariants touched

Per ROADMAP, citing `docs/SPEC.md` §16's numbered nine.

| # | Invariant | Status |
|---|---|---|
| 1 | daemonless launch | **Preserved.** `fleet index` and `fleet q` are short-lived CLI invocations. No resident process, no scheduled task. |
| 2 | exit-0 hooks | **Preserved, deliberately.** §6.4 rejects `PostToolUse` and `post-merge` hooks for the gated update. No hook is added or modified. |
| 4 | journal-injection-at-respawn | **Touched.** `compose_prompt` gains a source. The journal is still composed into every respawn and retains final position; index material is inserted ahead of the task, never between the journal and the turn. |
| 8 | platform-adapter-only OS branching | **Preserved.** All index paths go through `pathlib`; no OS branch is introduced. No new adapter methods, so the POSIX-parity obligation is not engaged. |
| 9 | one-state-many-views | **Touched, argued preserved.** The index is *not* fleet state — it derives from a target repo's source code, not from the registry, and no fleet decision reads it. The registry remains the single state with `status_snapshot()` its one derivation. The index is a cache of somebody else's files, closer to `logs/` than to `fleet.json`. |

Invariants 3 (mailbox), 5 (cwd-scoped dispatch), 6 (single-writer registry), and 7 (one live session per name) are untouched — this milestone adds no registry write, no dispatch path, and no session lifecycle change.

## 11. Out of scope

- **Call-graph / `callers()`** — a `refs.tsv` (caller → callee edges) is a natural phase-2 addition over the same store. Deferred to keep this milestone shippable.
- **Cross-session token sharing** — impossible (§2).
- **Embeddings or semantic search** — deliberately excluded (§3.1).
- **GraphQL** — remains possible later over the same index if fixed flags prove limiting; not a rewrite.
- **Auto-selecting `--context` from task text** — manager names files explicitly for now.

## 12. Success criteria

1. A worker spawned with a repo map and one digest issues measurably fewer orientation Reads than the same task without.
2. `fleet q <sym> --src` returns byte-exact source for the named symbol.
3. A mutated file never yields a stale slice.
4. Deleting `.fleet-index/` entirely degrades fleet to today's behaviour, with no errors.
5. Map injection stays under the configured cap on every repo tested.
