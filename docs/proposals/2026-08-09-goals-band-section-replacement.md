# PROPOSAL — replacement text for `supervisor/GOALS.md`'s context-band section

**Status: DRAFTED, PARKED, NOT APPLIED.** `supervisor/GOALS.md` is untouched and
`test_supervisor_context.py`'s `SURFACES` tuple is unchanged. This file is a proposal awaiting
Altai's approval on CONTENT. Drafted 2026-08-09 by the wave-47 supervisor
(`inc-20260808T173852Z-5dc6`) under the interface's instruction of the same day.

## Why this file exists at all

The operator ruled on 2026-08-08 that the band section be replaced **in full** rather than
numbers-only, naming three defects in the standing block. The ruling as relayed also ordered the
replacement pasted **verbatim** from `state/journals/w44-ceil.md` §8, and forbade any lane
originating GOALS.md content.

**That file does not exist.** Measured four ways: `state/journals/` holds 56 files and none is
`w44-ceil`; `git log --all -S"Context band (350"` returns empty, so the text was never committed on
any branch; the `w44-ceil` lane's own worktree has no `state/` directory at all; and no file on the
main tree carries the replacement heading. The pointer was real and was relayed four times — the
ARTIFACT is gone, because `state/` is gitignored and therefore per-worktree, so a lane report written
there dies with its worktree.

The interface has since corrected the provenance: **the "verbatim" and "no lane may originate"
clauses were the interface's own safeguard, not Altai's ruling.** What Altai ruled is the *in full*
disposition, the three defects as its reason, and YES to adding `supervisor/GOALS.md` to the pin's
`SURFACES`. So this draft needs approval on content, not on method.

**Nothing here is inherited.** Every number below is re-derived from shipped code and every
build-state claim is re-derived by grep at `HEAD`, because inheriting any of it would repeat the
exact class of defect this replacement exists to fix — a stale build-state tag copied forward by
someone who did not check it.

## The three defects in the standing text

The block currently reads:

> ## Context band (150–200k, supervisor AND workers — spec §11, §11.4)
>
> A freshness mechanism, not a budget (§11.5; third-docket cap doctrine 2026-07-23: no
> fleet-enforced token/USD ceilings for anyone).
>
> - Self-monitor context occupancy. Entering the band (150k) → hand off at the next wave boundary
>   (supervisor) / next task boundary (worker, via respawn).
> - 200k is the hard ceiling: no new work; finish only already-dispatched work (read-only
>   reconciliation) and hand off. Specified as a fleet-enforced dispatch refusal for the supervisor
>   claim-holder (§11.3, `[UNBUILT]`).
> - The supervisor enforces the worker arm: respawn an over-band worker at its next task boundary
>   (§11.4).

1. **The band numbers are superseded.** It states one 150–200k band for both tiers; the 2026-08-05
   ruling raised them and split them per tier.
2. **The `[UNBUILT]` tag on §11.3 is false.** The supervisor dispatch refusal shipped at `c6fde34`
   and widened at `d969de3`.
3. **It conflates the two arms.** The supervisor arm is built; the worker arm genuinely is not, and
   the text gives a reader no way to tell them apart — so correcting only the numbers would leave a
   false build-state claim standing under a pin that then blesses it.

## Derivations — every claim below, measured at `HEAD`

**Band numbers**, from the shipped module rather than from any document:

    band_thresholds('supervisor') = (350000, 400000)
    band_thresholds('worker')     = (250000, 300000)
    SUPERVISOR_BAND_SOFT_TOKENS = 350000    SUPERVISOR_BAND_HARD_TOKENS = 400000
    WORKER_BAND_SOFT_TOKENS     = 250000    WORKER_BAND_HARD_TOKENS     = 300000

**The supervisor arm IS built** — `_ceiling_refuses_dispatch` is defined once and called at five
sites across four verbs:

    bin/fleet.py:3285  def _ceiling_refuses_dispatch(verb, now=None)
    bin/fleet.py:5947  _ceiling_refuses_dispatch("spawn")
    bin/fleet.py:7228  _ceiling_refuses_dispatch("send")
    bin/fleet.py:7686  _ceiling_refuses_dispatch("respawn")     # cmd_respawn
    bin/fleet.py:7949  _ceiling_refuses_dispatch("respawn")     # _cmd_respawn_native
    bin/fleet.py:16705 _ceiling_refuses_dispatch("sup-spawn")

Both respawn sites are guarded by `if getattr(args, "task", None):` — armed only when `--task` is
supplied, because a bare respawn is §11.4 recovery of an over-band worker and must stay permitted
over the ceiling.

**The worker arm is NOT built.** `WORKER_BAND_SOFT_TOKENS` / `WORKER_BAND_HARD_TOKENS` appear at
exactly three lines: their two definitions (2591–2592) and one consumer, `band_thresholds` (2651),
which *reports*. Nothing refuses or respawns an over-band worker. `_ceiling_refuses_dispatch`'s own
docstring settles it: the predicate is gated on caller-is-the-claim-holder, so *"a worker reaching
here is exempt by identity long before any threshold is compared."*

*(Line numbers above are a claim about `HEAD` at drafting time and `bin/fleet.py` is being moved by
two lanes this wave. Re-derive by name, not by number, if you read this later.)*

## PROPOSED REPLACEMENT TEXT

```markdown
## Context band (supervisor 350–400k, worker 250–300k — spec §11.3, §11.4)

A freshness mechanism, not a budget (§11.5; third-docket cap doctrine
2026-07-23: no fleet-enforced token/USD ceilings for anyone). Both tiers
observe the same mechanism at different numbers, raised and split by
operator ruling 2026-08-05 from the single 150–200k band this section used
to state.

- **Supervisor: 350k soft, 400k hard.** Self-monitor occupancy — `fleet
  sup-context` names your tier and measures it, so use it rather than
  estimating. At 350k the hand-off directive is standing: finish the current
  wave, then hand off. At 400k the only permitted work is finishing work
  already dispatched (read-only reconciliation — `status`/`wait`/`result`/
  `peek`) plus the handoff verbs.
- **The 400k ceiling is BUILT and enforced**, not a rule the supervisor
  keeps by hand: `_ceiling_refuses_dispatch` refuses dispatch for the
  supervisor claim-holder at five call sites across four verbs — `spawn`,
  `send`, `sup-spawn`, and `respawn` in both `cmd_respawn` and
  `_cmd_respawn_native`. The respawn arm is armed **only when `--task` is
  supplied**: a bare respawn is §11.4 recovery of an over-band worker and
  stays permitted over the ceiling. Do not read a verb's silence as
  permission, and do not read this list as smaller than it is.
- **Worker: 250k soft, 300k hard** — the same mechanism, different numbers.
  A worker entering its band hands off or is respawned at its next task
  boundary; journals make that lossless.
- **The worker arm is NOT built, and that asymmetry is deliberate to state.**
  The worker constants are consumed only by `band_thresholds`, which
  reports; no code refuses or respawns an over-band worker, and the ceiling
  predicate is gated on caller-is-the-claim-holder, so a worker is exempt by
  identity before any threshold is compared. Enforcement of the worker arm
  is the supervisor's own act, via `fleet respawn` at a task boundary.
```

## What changes, in one line each

- Heading carries both bands and points at §11.3/§11.4 rather than the whole of §11.
- `[UNBUILT]` is **removed from the supervisor arm** and replaced with the measured call-site census.
- The worker arm is stated as unbuilt **explicitly**, with the mechanism (identity exemption) that
  makes it so — the reader can now tell the two arms apart, which is the ruling's stated reason for
  full replacement over numbers-only.
- The read-only reconciliation verbs are named, matching `skills/fleet/supervisor.md`.

## The `SURFACES` question — ruled YES, and NOT executed here

Altai ruled that `supervisor/GOALS.md` joins `test_supervisor_context.py`'s `SURFACES` tuple. **That
is deliberately not done in this draft.** Adding the file to `SURFACES` while its text still states
the superseded band would turn the pin RED with the operator away and nobody permitted to repair it —
GOALS.md is operator-owned. The two edits must land in one commit, in this order within it: replace
the text, then add the surface, watching the pin RED before and GREEN after on both interpreters.

## Recommended landing procedure, when approved

1. Apply the replacement block to `supervisor/GOALS.md` verbatim from this file.
2. Add `"supervisor/GOALS.md"` to `SURFACES` in `tests/test_supervisor_context.py`.
3. Watch `test_no_superseded_band_is_stated_as_current` RED with step 2 alone and GREEN after step 1,
   on `py -3.13` and `py -3.10`. A pin that has only ever passed proves nothing.
4. Re-derive every number in the block against shipped code at the landing commit — not against this
   file, which is a claim about 2026-08-09.
