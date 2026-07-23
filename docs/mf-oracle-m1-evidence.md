# M-F dogfood — fleet-index M1 economics evidence (2026-07-23)

Read-duplication analysis of tonight's Claude Code session transcripts, harvested post-run.
Campaign: `mf-oracle-stophook` (`C:\proga\oracle-wt-stophook`), `mf-oracle-config`
(`C:\proga\oracle-wt-config`), `int-docs-1` (`C:\proga\fleet-int-docs`), ~03:50Z–04:43Z.

Question under test: fleet-index M1's hypothesis that **repeated file reads across workers and
across respawned sessions are the dominant recurring token cost** of a fleet run.

## Methodology

- Source: per-session JSONL transcripts under `C:\Users\Techn\.claude\projects\<munged-cwd>\<sid>.jsonl`
  for the three cwds, mtime after 2026-07-23 03:30Z. 27 transcript files found; all read-only.
- Parser: `harvest.py` + `pass2.py` in the session scratchpad
  (`...\scratchpad\harvest.py`, `...\scratchpad\pass2.py`), run with `py -3.13`. No hand-counting.
- Extracted per line: `tool_use` blocks for Read/Grep/Glob, `message.usage` on assistant records,
  `agent-name`, `cwd`, record `uuid`, `requestId`, timestamps.
- **Session classification.** 11 files carry a `fleet|<worker>|...` agent-name — these are the fleet
  worker sessions. The other 16 files are small (2–7 API calls), unnamed, model `claude-opus-4-7`,
  and their first user message is "Review this change for security vulnerabilities…" — they are
  **cc-oracle probe sessions spawned by the hook under test**, not fleet workers. They are reported
  separately ("probes") because they are workload of the artifact being built, not fleet overhead —
  but they turn out to be the strongest M1-shaped signal (see Reading).
- **Fork/respawn dedupe.** Fork-steered sessions copy the parent transcript into the new sid file:
  5 stophook files share ≥150 record uuids (one fork family descending from the post-respawn
  parent), 2 config files share 150. Replayed `tool_use` ids (52 of 155 Read entries) were
  deduplicated — only 103 Read executions actually happened. Usage records are likewise copied
  with their original `requestId`; token totals below are **globally deduped by requestId**
  (the naive per-file sum would double the campaign to ~64.4M cache-read tokens vs the real 33.9M).
- **Path normalization.** Relative `file_path` values resolved against the record's `cwd`. The two
  oracle workers share one repo via separate worktrees; paths were reduced to repo-relative keys
  (`oracle::hooks\oracle_hook.py`) so the same file counts once across worktrees. int-docs paths
  likewise (`int-docs::…`). A handful of `\home\user\…` unix-style paths from oracle test fixtures
  resolved to nothing on disk (265 B of error results total — negligible, kept under `abs::`).
- **Cost measure.** Primary metric is the **actual injected `tool_result` payload** (chars of the
  paired tool_result, ÷4 for a rough token estimate) — not disk size × reads, because 36 of 103
  Reads were partial (`offset`/`limit`). Disk sizes (read from disk now) are shown for reference
  only. Duplication is reported as a **range**:
  - *upper bound* = all payload beyond the first read of a file (treats every re-read as waste);
  - *lower bound* = payload beyond max(first read, one full file pass) (treats paging through a
    file in slices as legitimate first-read cost).
- Every Read had a paired tool_result (0 missing).

### Limits (read before quoting)

- 4 bytes/token is a rough heuristic; tool_result payloads include `cat -n` line-number prefixes.
- Disk sizes have drift: files were edited during the run — `three-tier-command.md` was being
  *written by* int-docs-1, so tonight's reads saw smaller intermediate versions than the 105,942 B
  now on disk.
- "Duplication" counts payload only. It does not model what an index would actually save (an index
  summary also costs tokens to build and read).
- Sample: 3 workers, 2 small repos, one night, tasks that deliberately share one artifact
  (cc-oracle). Nothing here generalizes on its own.

## Session inventory

| lineage | class | sessions | notes |
|---|---|---|---|
| mf-oracle-stophook | fleet | 6 | 1 initial + 5-file fork family (respawn then fork-steers, all first_ts 03:56:49Z) |
| mf-oracle-config | fleet | 3 | 1 initial + 2-file fork pair |
| int-docs-1 | fleet | 2 | respawn at 03:56Z, no fork copies |
| (stophook dir) | oracle probes | 12 | claude-opus-4-7, 2–5 API calls each, 03:56–04:43Z |
| (config dir) | oracle probes | 4 | claude-opus-4-7 |

## Per-worker reads and searches (deduped executions)

| worker | sessions | Reads | distinct files | re-reads (n>1) | Read payload (B) | ≈tokens | Grep | Glob |
|---|---|---|---|---|---|---|---|---|
| mf-oracle-stophook | 6 | 24 | 12 | 12 | 174,667 | 43.7k | 12 | 8 |
| mf-oracle-config | 3 | 12 | 7 | 5 | 112,355 | 28.1k | 5 | 5 |
| int-docs-1 | 2 | 38 | 13 | 25 | 300,087 | 75.0k | 11 | 0 |
| **fleet total** | **11** | **74** | — | **42** | **587,109** | **146.8k** | **28** | **13** |
| stophook probes | 12 | 20 | 7 | 13 | 220,734 | 55.2k | 2 | 0 |
| config probes | 4 | 9 | 4 | 5 | 79,155 | 19.8k | 4 | 0 |
| **probe total** | **16** | **29** | — | **18** | **299,889** | **75.0k** | **6** | **0** |

Most-read files: `three-tier-command.md` 15× (int-docs-1, all partial/paged),
`oracle_hook.py` 5× across the two oracle workers (plus 14× by probes),
each worker's own `state\tasks\<name>.md` dispatch file 3–7×.

## Cross-worker duplication (fleet workers only; oracle worktrees normalized to one file)

Files read by ≥2 of the 3 workers. Only the two oracle workers overlap — int-docs-1 works in a
different repo and shares nothing with them.

| file (repo-relative) | stophook × config reads | disk B (now) | payload B | dup tokens (upper) |
|---|---|---|---|---|
| `docs\plans\2026-07-23-oracle-plugin.md` | 2 × 1 | 48,019 | 152,196 | 25,366 |
| `hooks\oracle_hook.py` | 3 × 2 | 19,727 | 38,532 | 7,283 |
| `docs\specs\2026-07-23-oracle-plugin-design.md` | 1 × 2 | 12,597 | 31,320 | 5,220 |
| `tests\test_stop_entry.py` | 2 × 1 | 10,450 | 17,490 | 2,915 |
| `hooks\hooks.json` | 1 × 1 | 606 | 1,296 | 162 |
| **total** | **13 reads / 5 files** | — | — | **40,946** |

Cross-worker duplicated payload ≈ **41k tokens upper bound** — 2.5% of the campaign's fresh input
(see token table). The plan doc alone is 62% of it: both workers read the full 48 KB plan.

## Within-lineage rebuild (same worker, same file, ≥2 of its sessions)

This is the respawn/fork context-rebuild cost. Note it overlaps the cross-worker table (a file can
be both): the two tables must not be summed; the union is given below.

| worker | file | sessions | reads | payload B | rebuild tokens (upper) |
|---|---|---|---|---|---|
| int-docs-1 | `three-tier-command.md` | 2 | 15 | 125,858 | 29,851 (lower ≈5.0k: 15 partial reads sum to only 1.19× file size — mostly paging, not re-reading) |
| int-docs-1 | `docs\spec.md` | 2 | 2 | 22,286 | 2,785 |
| int-docs-1 | `docs\specs\autoclean.md` | 2 | 2 | 24,250 | 3,031 |
| int-docs-1 | `skills\fleet\skill.md` | 2 | 3 | 17,701 | 3,039 |
| int-docs-1 | 4 more files | 2 | 9 | 43,975 | 5,044 |
| **int-docs-1 subtotal** | | | | | **43,750** |
| mf-oracle-stophook | `docs\plans\2026-07-23-oracle-plugin.md` | 2 | 2 | 101,464 | 12,683 |
| mf-oracle-stophook | `state\tasks\mf-oracle-stophook.md` | 2 | 7 | 15,207 | 3,601 |
| mf-oracle-stophook | `hooks\oracle_hook.py` | 2 | 3 | 19,734 | 2,583 |
| mf-oracle-stophook | 2 test files | 2 | 4 | 19,246 | 2,405 |
| **mf-oracle-stophook subtotal** | | | | | **21,272** |
| mf-oracle-config | 4 files | 2–3 | 9 | 55,145 | **7,539** |
| **lineage total** | | | | | **72,561** |

## Probe duplication (cc-oracle security-review sessions — reported separately)

| file | probe sessions | reads | payload B | dup tokens (upper) |
|---|---|---|---|---|
| `hooks\oracle_hook.py` | 13 | 14 | 213,013 | 48,021 |
| `tests\test_config.py` | 4 | 4 | 43,213 | 9,661 |
| `tests\test_stop_entry.py` | 3 | 3 | 23,258 | 3,042 |
| `tests\test_detection.py` | 2 | 2 | 15,782 | 1,728 |
| fixture path (errors) | 3 | 3 | 265 | 44 |
| **total** | | | | **62,496** (lower 59,154) |

83% of all probe Read payload is duplicated: every cold probe session re-reads the same hook file.

## Token totals (usage fields, globally deduped by requestId)

| scope | uncached input | cache_creation | cache_read | output |
|---|---|---|---|---|
| fleet sessions (11) | 687 | 1,240,224 | 31,597,784 | 227,221 |
| probe sessions (16) | 142 | 371,825 | 2,318,573 | 70,051 |
| **campaign total** | **829** | **1,612,049** | **33,916,357** | **297,272** |

"Fresh input" below = uncached + cache_creation ≈ **1.61M tokens**. The naive per-session sum
(before requestId dedupe) reads 64.4M cache-read tokens — the 5-way stophook fork family carries
copies of its shared prefix in every file; per-session numbers are context *carried*, not tokens
*billed twice*, and are available in the scratchpad `out.json`.

Biggest single sessions (deduped within file): stophook fork `001c7d7a` — 127 API calls, 18.3M
cache-read, 718k cache-creation; fork `cb51279f` — 103 calls, 13.2M cache-read.

## Reading: does this support the M1 "dominant recurring cost" hypothesis?

**For the fleet workers in this run: undercut.** Headline ratios:

- All Read payload injected across the 3 workers: ~147k tokens = **9.1%** of fresh input.
- Duplicated Read payload (union of cross-worker + within-lineage, no double count):
  **55.7k–94.8k tokens = 3.5%–5.9% of fresh input**, and **~0.27% of total input processed**
  (35.5M incl. cache reads). Cross-worker duplication specifically is ≤41k tokens (2.5% of fresh).
- The dominant recurring cost of this run was **conversation-prefix re-transmission** (33.9M
  cache-read tokens; cheap per token but 21× the entire fresh-input volume), driven by long fork
  lineages — not file re-reads. An index addressing file reads addresses a single-digit percentage
  of fresh input here.

**But one M1-shaped pattern is real in the data:** the cc-oracle probe sessions. 16 cold sessions
re-read `oracle_hook.py` 14 times — 83% of probe Read payload was duplicate (~62k tokens, 17% of
probe fresh input). Many short-lived cold sessions over a stable file set is exactly where a
shared index/digest would pay; long-lived forked workers with warm caches are where it would not.
Within-lineage rebuild (72.6k upper) also exceeds cross-worker duplication (40.9k) — respawn
context rebuild is the bigger of the two fleet-side effects, and int-docs-1 is the worst lineage
(43.8k upper, dominated by paging its own work-in-progress spec).

**Caveats on the verdict:** n=3 workers on deliberately overlapping tasks; small repos (biggest
duplicated file 48 KB); one night; token estimates are payload-chars/4; disk sizes drifted during
the run; and the upper bounds treat every re-read of an edited file as waste even when the file
had genuinely changed. Evidence-grade: suggestive, not conclusive.
