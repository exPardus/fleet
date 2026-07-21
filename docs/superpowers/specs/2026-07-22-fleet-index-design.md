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

`fleet index build [--path DIR] [--force]`

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
| Index missing | `fleet q` prints the build command, exits non-zero. Spawn injects nothing and proceeds normally. |
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
