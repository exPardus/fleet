# Cross-vendor review — w101-codex-notify (DeepSeek supervisor, independent of the Codex author)

DONE means: an independent-vendor reviewer has read the sender diff, run the target suites and the
full fleet suite on both the changed tree and the base, and stated plainly which checks are green,
which are blocked, and whether the change may be merged.

Reviewer: `sup|inc-20260920T065313Z-4e9e|boot`, model deepseek-v4.1-flash — a different vendor
from the Codex `gpt-5.6-luna` worker that wrote the change. This is the cross-vendor review;
the worker's own report is `docs/lanes/w101-codex-notify.md`.

Base: `f8852278a55d7b2d5f54728558fa3ce8e61f195a`. Worktree: `/home/altai/proga/fleet-w101-codex-notify`.
Diff under review: `bin/fleet.py` (+9/-1), `tests/test_sup_notify.py` (+55/-2), `docs/SPEC.md`,
`docs/PLAN-PROGRESS.md`, lane records. No other file touched.

## Verdict: PASS at the unit/contract level; LIVE CLAIM UNPROVEN — merge held

The code change is exactly the change described, and it is correctly placed.

1. `type_interface_line` gains `settle_seconds=INTERFACE_PASTE_SETTLE_SECONDS` (0.5) and an
   injectable `sleep_fn=time.sleep` (`bin/fleet.py:4036-4042`). `import time` is already present
   at `bin/fleet.py:27`, so the default is not a NameError.
2. The settle happens **between** the literal send and the single Enter, and **after** the
   literal-send failure return: `bin/fleet.py:4044-4050`. A failed literal send therefore still
   cannot submit — the inherited C3 contract holds unchanged.
3. Exactly one Enter is sent. No `extraEnter`, no retry, no second `send-keys` added.
4. Sanitisation is untouched: `one_line`/`interface_line` and `INTERFACE_LINE_LIMIT` are not in
   the diff; only a new module constant was added above `_ANSI_CSI_RE`.
5. Sole production caller is `sup-notify` (`bin/fleet.py:14400`); no worker-send path changes
   behaviour.

## Checks I ran myself (not the worker's numbers)

- `python3 -m pytest -q tests/test_sup_notify.py tests/test_interface_state.py` → **42 passed**,
  0 failed, rc 0 (system CPython 3.12.3).
- `git diff --check` → rc 0, clean.
- Reviewer-side reading of the new tests: `test_immediate_enter_is_consumed_but_settled_enter_submits`
  drives a fake composer that swallows an Enter arriving inside the quiet period and submits after
  it — it fails on the base by signature (no `settle_seconds`), and it is a genuine behavioural
  model, not a tautology. `test_enter_failure_returns_false_after_settle` and the unchanged
  literal-failure test both keep the False-on-failure contract. Default-argument callers do not
  incur a real 0.5 s sleep on the failure path (early return precedes the sleep).

## What is NOT proven (blocker, stated plainly)

- **The behavioural premise is assumed, not demonstrated.** The tests encode "an Enter inside a
  0.5 s quiet period is consumed as paste"; they do not show that Codex 0.155.1 does this or that
  0.5 s is enough. Only the live scratch-Codex `/status` repro can show that, and it **could not be
  run**: every Codex turn on this host now fails at turn start with
  `You've hit your usage limit ... try again at 3:21 PM` (reproduced on this lane at 2026-09-20T11:57Z
  and on `pm-eth5m-alloc-1-fix-2` at 12:00Z).
- **The prescribed interpreter gates did not run.** `python3.10` and `python3.12` on this host have
  no `pytest`, and `uv run --with pytest` cannot fetch it (no network). Only system CPython 3.12.3
  was exercised. The worker recorded this honestly; I reproduce it.
- Therefore: `tmux rc 0` remains sender success only, not proof the interface consumed the line.
  No claim that notifications now arrive submitted may be made from this evidence.

## Merge decision

**Held, not merged.** The manager's landing condition is "after green checks"; the live
scratch-Codex `/status` validation is one of them and is blocked by the host-wide Codex usage
limit until ~15:21 local. The fix is local-only and reversible, but merging it and reporting a
green runtime fix would claim more than the evidence supports. Merge on the first Codex turn
after the limit resets, with the scratch `/status` repro run first. The interface-reserved slot
is free now — this lane's worker is dead, not running.

## Full-suite regression found after the first verdict (this is the decisive finding)

The worker ran only the two target files. I ran the whole fleet suite on both trees, same command,
same interpreter (system CPython 3.12.3, `python3 -m pytest -q --tb=no`):

| tree | result |
|---|---|
| base `f885227` (scratch worktree) | **9 failed**, 5488 passed, 16 skipped, 3 xfailed (472.8s) |
| changed `a9beefc` (lane worktree) | **16 failed**, 5485 passed, 16 skipped, 3 xfailed (475.1s) |

Seven failures are new, and six of them are **caused by this change**:

- `tests/test_self_citations.py` (4 tests) — the doc-citation gate resolves line numbers cited in
  the docs against `bin/fleet.py`. The insert shifts every line below it; the gate names it exactly:
  `fleet.py:823 cites :12317 as being in _identity_abstention_note, which spans 12318-12337`, and
  `quarantine-artifact readers: cited [5122, 8357, 9252, 9502, 12317, 12443, 13735], but the source
  has [5129, 8364, 9259, 9509, 12324, 12450, 13742]` — a uniform +7.
- `tests/test_retired_sid_citations.py` (2 tests) — same cause, same +7 shift.

So the change is **not mergeable as it stands**: it lands green on the two files the worker ran and
red on six gates it never ran. The fix-forward is mechanical but must be done and re-verified —
update the cited line numbers in the citing docs (or re-anchor them), then re-run the full suite and
show the changed tree back at the base's 9 failures.

The seventh new failure was **mine, not the worker's**: this review file is a new lane document and
the docs-currency gate requires a `DONE means:` line after the title. Fixed in this file.

## Revised verdict

- Sender change itself: **pass at unit/contract level** (unchanged from above).
- Whole-repo: **FAIL** — six new citation-gate failures caused by the line shift.
- Merge into the persistent fleet home: **HELD**, on two counts — the citation regressions above, and
  the live scratch-Codex `/status` repro that the host-wide Codex usage limit (reset ~15:21 local)
  still blocks. Do not merge `a9beefc` until both are green.
