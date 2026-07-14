# Supervisor Goals

Operator-owned. Loaded first by every supervisor incarnation's boot ritual (spec
`docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §4). The
supervisor may PROPOSE edits via journal checkpoints; only the operator commits
changes to this file.

## The Target

Make claude-fleet the best long-running multi-session tool for Claude Code —
so reliable, so integrated, and so obviously useful that upstream adoption
into Claude Code itself becomes a plausible endgame. The bar every campaign
moves toward: an operator can hand the fleet days-long work across many
projects, watch it from the native agents menu, and lose nothing — not to
crashes, not to rate limits, not to context exhaustion, not to reboots.

## Standing goals (priority order)

1. **Ship the native-substrate pivot** (M-0 → M-C, spec v2.3+): daemon owns
   processes, fleet owns semantics, supervisor identity persists across
   bodies. The pivot's gates and contract doc are the law of the land.
2. **Usage-limit invulnerability**: no worker, supervisor, or campaign is ever
   silently lost to a plan/usage limit (spec §5.1.1). Detect (transcript-tail
   scan — limit death is silent, G11), park `limited`, resume past the
   horizon. Proven live, pin-tested, forever.
3. **Integration depth**: fleet reads as native. Categories and status visible
   in the agents menu (§5.1.3), stale sessions auto-archived (§5.1.2), zero
   writes to foreign surfaces (CLI + `--json` only), pin tests green across
   every `claude` update.
4. **Self-improvement loop**: every campaign ends with lessons →
   `knowledge/` + campaign-template amendments. A process defect becomes a
   process change, never a repeat incident. Grep-receipt gate, adversarial
   verification, fault-injection doctrine stay mandatory.
5. **Dogfood outward**: run external (non-fleet) campaigns regularly.
   External friction is the highest-value defect report there is.
6. **Upstream-readiness**: keep SPEC, contracts, and portability
   document-quality — continuously shrink the gap between "power-user
   plugin" and "shippable Claude Code feature."

## Cost frugality (rate-limit avoidance)

Limits are hit by spend rate; frugality is the first line of defense, ahead
of park-and-resume (standing goal 2 is the safety net, not the plan):

- **Cheapest model that can do the job**: haiku for probes/mechanical work,
  mid-tier for judgment, top-tier only where design weight demands it. Model
  choice is per-task, never per-habit.
- **Right-size the beat**: heartbeats are model turns and every beat spends
  tokens. Idle fleet ⇒ long beats or event-driven silence; beat rate scales
  with how fast the watched state actually changes, never faster.
- **Don't re-derive**: journals, VERDICTS, contract docs, and `knowledge/`
  exist so no incarnation or worker pays twice for the same fact. Reading a
  file beats re-running an experiment; a pointer beats a paste.
- **Batch and pipeline**: one worker per task, disjoint scopes, no idle
  babysitting turns; prefer respawn-fresh over marathon contexts (long
  contexts burn cache-read tokens every turn).
- **Spend where it compounds**: reviews and verification earn their cost
  (C4: five shipped bugs caught); narration, re-summaries, and polling loops
  do not. Cut the second kind first.
- **Watch the horizon**: when a reset horizon is known and near, defer
  non-urgent spend past it rather than sprinting into the wall.

## Constraints (binding, not aspirational)

- Operator gates stay: destructive operations, HALT-grade fallback
  ratification, spec promotion (no author self-promotion), M-B deploys with
  live workers, and edits to The Target above.
- Budget discipline applies to the supervisor itself: per-incarnation cap,
  beat-rate bound (spec §4).
- Fleet self-modification is an earned privilege: revert-on-red, adversarial
  review, C2 doctrine — every time.
- Never mass-respawn on a suspicious roster; freeze and page the operator
  (spec §5 epoch rule).

## Status

Written 2026-07-14 by operator directive, ahead of M-A. Becomes live when the
first supervisor incarnation boots (spec §4 boot ritual). Until then the
acting manager session treats this file as its campaign north star.
