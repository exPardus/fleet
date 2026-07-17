# Three-tier command: interface / supervisor / workers — DRAFT PROPOSAL

Status: **PROPOSAL — RESTRUCTURE REQUIRED (dual-lens design gate, 2026-07-17).** Both
independent reviews (`docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-{break,spec}.md`)
returned `restructure`; the binding merged list + sequencing is
`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md`. Root cause: the claim protocol is
keyed on the session id, which fork-steer (the draft's own beat mechanism) rotates —
per-body claim nonce is a hard prerequisite, its own slice. Do NOT spec or build from
this draft as written. Operator-originated (2026-07-16, mid-M-C conversation); this
draft was written by the acting supervisor session (no author self-promotion).

## The operator's model (verbatim intent)

> CEO (human-facing session) takes input from the investors (human), translates it
> down to the staff manager (supervisor session) who slices up the task, gives it
> to employees (worker sessions) and makes sure the task is completed. The top
> session saves its context for talking, interpreting, and long-term ideas; the
> lower tiers get respawned and killed constantly for fresh context.

## What exists today (M-C reality)

- **Two tiers, merged at the top.** The session the human talks to IS the
  supervisor (holds the claim, runs the beats, dispatches workers, does merges and
  reviews). Its context carries both the human conversation AND the campaign
  mechanics — the expensive mix the operator wants split.
- Supervisor **identity** already survives bodies (GOALS.md + JOURNAL.md +
  INCARNATION claim + seize/handoff rituals, spec §4). What does NOT exist: a body
  that acts without a human-attached session driving it.
- Workers are native `--bg` sessions: durable, survive host restarts (proven
  2026-07-16 — two host process deaths mid-campaign, zero loss), but they only run
  when a turn is dispatched. Nothing self-continues.
- The autoclean scheduled-task plumbing (`fleet init --autoclean`, M-C) is the
  first OS-scheduler → fleet-command bridge. It generalizes.

## Proposed shape

1. **Interface session ("CEO")** — the only tier the human talks to. Thin context:
   conversation, long-horizon intent, spec/brief authoring. It writes task briefs
   as files (@file contract artifacts, not chat paraphrase — the telephone-game
   mitigation) and hands them to the supervisor via `fleet send supervisor
   @brief.md`. It reads `sup-status --json` + journal tail, never worker
   transcripts, never code. It holds NO claim.
2. **Supervisor as a fleet worker** — a native `--bg` session named `supervisor`,
   spawned by `fleet sup-spawn` (new), holding the claim via the existing sup-boot
   ritual inside its first turn. Beats arrive two ways:
   - event-driven: interface sends briefs; worker Stop-hook outcomes could enqueue
     a "reconcile" mail (design question: hook write boundary allows outcome
     records today, not mailbox writes — needs a sanctioned-list amendment or a
     poll-on-beat instead);
   - time-driven: a scheduled task (`fleet init --supervisor-beat N`) runs
     `fleet send supervisor "beat"` every N hours — same schtasks pattern as
     autoclean, same install guards (N1 lessons apply verbatim).
3. **Workers** — unchanged. Respawn-fresh doctrine already binding.

## Why this is plausibly cheap

- No new substrate: durable sessions, mailbox, fork-steer, claim rituals, and the
  scheduler bridge all shipped in M-B/M-C. The delta is one spawn verb, one
  scheduled-task variant, and doctrine.
- Context economics: the interface session's context grows with human conversation
  only (slow); the supervisor respawns/handoffs on the existing 300–500k band
  without losing the human thread (it never had it); workers already churn.

## Known hazards (write the review brief from these)

- **Operator gates.** Destructive ops, HALT ratification, GOALS edits stay human.
  A background supervisor MUST route those to the interface tier and park, never
  self-approve. Today that routing surface does not exist (proposal: a
  `NEEDS-OPERATOR` journal kind + interface-tier nag on read).
- **Two-manager confusion is real, observed today**: the operator steered workers
  directly while the acting supervisor also steered — duplicate scope, phantom
  titles (AI-generated roster titles ≠ message text — do not treat titles as
  evidence), one husk left blocked on a permission prompt. Doctrine needed: humans
  talk to the interface tier; direct `fleet send` to a claimed fleet's workers is
  an incident, not a convenience. (The agents-menu "requires input" nag on a
  RETIRED fork predecessor is a separate cosmetic bug worth filing.)
- **Beat cost.** A scheduled supervisor beat is a model turn every N hours
  forever. GOALS frugality: long beats, event-driven silence, cheapest-capable
  model for the beat turn (a beat that finds nothing should cost cents).
- **Permission mode.** A background supervisor doing merges/pushes needs bypass in
  the fleet repo — acceptable (C2 earned-privilege doctrine) but must be explicit
  in GOALS before it ever runs unattended.
- **Token efficiency tie-in** (same conversation): compressed output contracts
  ("Final message = ..." + caveman-style terse prose) become MANDATORY at every
  tier boundary — brief→supervisor, supervisor→worker, worker→result. Code,
  commits, specs, and review verdicts stay full-precision. Candidate: fold a
  compression clause into campaign-template + spawn-etiquette rather than a
  plugin prerequisite (a plugin the worker repo doesn't have installed is a
  silent no-op; a task-file clause always arrives).

## Non-goals

- Not replacing the human. The interface tier interprets; it does not invent
  mandates.
- Not building during M-C. Candidate slot: M-D, after SPEC v3 lands, as its own
  campaign with adversarial design review first.
