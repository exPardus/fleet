# Lane w63-doctrine — operator efficiency doctrine and currency lint
DONE means: the governing docs state the adopted rules, seeded pins pass, and this report and changes are committed on w63/doctrine.

MEASURED — Model: Codex `gpt-6-astra`, mcx worker; `MCX_WORKER=1` retained; no workers or subagents launched.
MEASURED — Result: edits and targeted checks complete; DONE is NOT MET because linked Git metadata is read-only, so the report and branch changes cannot be committed from this sandbox.
MEASURED — Branch remains `w63/doctrine` at `708fa45`; no push, merge, ref movement, `bin/` change, or `docs/OPERATOR-GATES.md` change.
MEASURED — Read all three source rulings from `/home/altai/proga/fleet/state/tasks/`; this worktree has no `state/` directory.

docs updated: CLAUDE.md, docs/lanes/BRIEF-TEMPLATE.md, skills/fleet/supervisor.md, docs/operator/server-interface-profile.md, docs/CHANGELOG.md, docs/SPEC.md, docs/NEXT-SESSION.md, docs/PLAN-PROGRESS.md, docs/lanes/w63-doctrine.md (MEASURED)

## Changes and evidence

MEASURED — Currency doctrine requires the owning SPEC section and progress row in the surface-changing commit, host-quirk knowledge when applicable, or `Docs: n/a -- <why>` for unchanged described behaviour.
MEASURED — Rules 3–12 are in their owning procedures: board/history, gate batching, model routing, one feature offer, DONE placement, changelog, spawn budgets, one priority per wave, targeted-only lanes and one merged floor per interpreter, 40k boot-read cap.
MEASURED — The interface's stale `sup-notify` UNSHIPPED inference was removed; `803a9a3` is the measured landing evidence.
MEASURED — `wc -l bin/fleet.py` = 23100 at `708fa45`; SPEC §0 and §3 now agree while historical receipt pins remain historical.
MEASURED — NEXT-SESSION is 24 lines (was 194); stale sections were deleted, not re-labelled historical.
MEASURED — Changelog seed commits were checked with git log/show: `708fa45`, `aee5fdf`, `245bdf1`/`1de9995`, `c6b6713`/`afa51a8`, `7928a9f`/`6df3161`, `d25f1b2`, `803a9a3`.
MEASURED — No new host quirk was introduced and no receipt was pasted under `docs/specs/`; strict receipt replay is not applicable to this lane.

## Journal split

MEASURED — Pure byte split: **12715 before = 256 board + 12459 rolled** into `supervisor/journal-history/2026-07-to-09.md`.
MEASURED — Concatenating history then board exactly reconstructs `git show 708fa45:supervisor/JOURNAL.md`; SHA-256 is `2c4852c61d0207673f5090456aa3cf465a630ff0602c966688decd27e607d100` on both.
MEASURED — The board has exactly three CHECKPOINT headers; retained checkpoint sizes are **115, 94, 47 lines**. No checkpoint was rewritten, re-ordered or truncated. New entries must obey ≤40 lines.
MEASURED — `tests/test_supervisor.py` gained the requested board pin; a synthetic fourth header made it RED (`1 failed, 440 deselected`), byte-exact restoration made it GREEN (`1 passed, 440 deselected`).

## Currency lint: RED then GREEN

MEASURED — `tests/test_docs_currency.py` audits the last **20 non-merge commits after `708fa45246ca957263b3ce299add6f13efb8c330`**; all ancestors of that adoption base are excluded. This explicit graph cutoff avoids retroactively failing inherited commits; a missing cutoff object fails rather than skips.
MEASURED — Direct `bin/*.py` edits require `docs/` in the SAME commit or a `Docs: n/a` line; failures identify the full commit. Nested bin paths are outside the requested lint population.
MEASURED — The seed used a temporary Git repository and amended its sole offending change with docs, preserving the RED output below. No live branch history was changed.

```text
COMMAND: python tests/test_docs_currency.py /tmp/w63-currency-seed-ugc9u68u --cutoff e03f339218aa1881187846e348f01806eb70f992
RED commit: 1558b3335c789256ae28d50ee457a3ad542a9e2f
1558b3335c789256ae28d50ee457a3ad542a9e2f: bin/*.py changed without docs/ or Docs: n/a
exit=1
GREEN after amending the same synthetic commit with docs/example.md:
PASS: docs currency (last 20 non-merge commits after cutoff)
exit=0
```

MEASURED — DONE pin cutoff: existing tracked lane documents at `708fa45` are grandfathered; the template and every new lane document are checked. Runtime `.md`/`.txt` tasks written from **2026-09-10T11:54:00Z** are checked by mtime under `FLEET_HOME` when supplied (else the tested checkout); generated `.boot-bundle.txt` output is excluded. Rewriting an old task brings it into scope.
MEASURED — The live dispatch home currently has zero post-cutoff tasks; that population is not claimed as non-vacuous proof. Synthetic tests prove new/rewritten tasks are selected and missing/empty/late DONE lines fail. Run this pin against the dispatch home before dispatch.

## Checks and suite floor

MEASURED — Targeted command: `UV_CACHE_DIR=/tmp/w63-uv-cache UV_LINK_MODE=copy uv run --offline --no-project --python 3.12 --with pytest python -m pytest -q --color=no tests/test_docs_currency.py tests/test_supervisor.py tests/test_lane_report_durability.py` → **467 passed in 6.92s**.
MEASURED — Prerequisite resolved: default uv cache was read-only and network DNS unavailable; copied existing cached pytest dependencies to a writable cache and ran offline.
MEASURED — Final pins after writing this report: `tests/test_docs_currency.py tests/test_supervisor.py -k "docs_currency or committed_journal_board"` → **12 passed, 440 deselected in 6.56s**; log `final-pins.log`.
MEASURED — Other changed paths: `tests/test_docs_currency.py`, `tests/test_supervisor.py`, `supervisor/JOURNAL.md`, `supervisor/journal-history/2026-07-to-09.md`.
MEASURED — Added **12 tests** (11 in the new lint file, one board pin); the previous `tests/test_supervisor.py` is an exact byte prefix of the edited file, and no other existing tests were changed.
BELIEVED — Against the supplied 5058 collected baseline, expected merged collection is **5070** absent sibling changes. No full suite or full collection was run; the supervisor owns the once-per-interpreter merged floor.
MEASURED — `git diff --check` passed; no fleet CLI verbs were run, no operator gate boxes edited, and no application code changed.

## WHERE THIS BRIEF WAS WRONG

MEASURED — Rule 12 exists: measure a fresh supervisor's pre-first-dispatch read tokens after the roll lands and cap them at 40k. Doctrine is written; no such fresh supervisor has booted in this worker's scope, so there is no honest measured token number yet.
MEASURED — Rule 5's source text says luna/terra after the native adapter, Sonnet until then; the supplied task explicitly overrides docs routing to Astra via mcx now. That override and the assigned docs-lane lint exception are stated, not attributed to the original ruling.
MEASURED — Rule 11's source also requires a fresh `git clone --no-local`; the brief's shortened summary omitted that condition and the doctrine includes it.
MEASURED — The standing throughput directive retains authorization for irreversible acts outside existing rulings; “DECIDED — overturnable” does not authorize those acts. Both gate sections preserve this distinction.
MEASURED — The journal split is possible, but retaining the last three byte-exact checkpoints cannot also make each ≤40 lines; preservation wins for these inherited entries.
MEASURED — The stale 7378 line-count literal is in SPEC §3; §0 had a later but still stale 9091 count. Both current-tree statements were corrected.
MEASURED — Native Codex workers are not a shipped landing at the base: `7928a9f` explicitly says DESIGN + SPIKE, build nothing. The changelog describes that actual result; mcx execution of this lane does not prove a shipped fleet adapter.
MEASURED — PLAN-PROGRESS was headed as a retired cursor; a current operator-wave table now precedes the preserved historical ledger so the new currency requirement has an active row to update.

## Blockers and handoff

MEASURED — `git add` failed: `Unable to create '/home/altai/proga/fleet/.git/worktrees/fleet-w63-doctrine/index.lock': Read-only file system`. Approval policy is never; no permission escalation is available. No commit was created.
MEASURED — The requested `/home/altai/proga/fleet/state/journals/w63-doctrine.md` append likewise failed with read-only filesystem. Fallback working journal: `/tmp/w63-doctrine-logs/journal.md`.
MEASURED — Full logs are in `/tmp/w63-doctrine-logs/`: `targeted.log`, `currency-red-green.log`, `board-red-green.log`, `journal-split.json`, `invariants.log`, `landing-history.log`, `blockers.log` and the working journal.
BELIEVED — Parent must commit these worktree files and this report on `w63/doctrine` from its writable Git context, copy the working journal to the requested path, and record the fresh supervisor's boot-read token measurement after landing. Preserve any newer live journal checkpoints when merging this historical split.
