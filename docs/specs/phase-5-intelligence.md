# Spec: Intelligence layer (Phase 5) — the moat

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md. Interleaves with Phase 4 after Phase 3.

## Goal

The manager gets measurably better over time. Mostly doctrine + knowledge structure + small CLI additions — deliberately code-light; the compounding asset is the knowledge base, not features.

## Scope

In: trust ledger, plan-approval gate flow, definition-of-done contracts, session seeding (`spawn --from`), campaign templates, broadcast/named addressing, knowledge distillation routine, knowledge librarian (automated staleness detection: ref-check + judged re-verification of knowledge entries). Out: any ML/scoring service, autonomous manager loops without human kickoff (that stays Telegram manager-on-call), cross-CLI workers (Phase 6).

<!-- flag-sizing -->
**Flag-sized scope (code vs doctrine).** Phase 5 is deliberately code-light: the entire v1 code surface = `fleet done --outcome`, `spawn --from` (journal-only), `send --all --except`, 2-metric `fleet stats`. Everything else — campaign templates, definition-of-done contracts, the distillation routine — is DOCTRINE (git-tracked markdown files the manager reads and follows), not code. The compounding asset is the knowledge base; new CLI is kept to those four flags to avoid framework-building.

## Fixed constraints

- Trust ledger and templates are git-tracked knowledge files (structured markdown or JSON in `knowledge/`) — readable/editable by human, written by manager turns, no database.
- DoD contracts enforce via the EXISTING Stop-hook mechanism (mailbox veto with feedback) — no new hook types.
<!-- F12 -->
- Salvaged kernel (IDEA-FORGE-REPORT §4): per-worker cumulative TOKEN ceiling — token counts only, no $-conversion, no price table. Complements `--max-budget-usd` and works behind provider proxies where $ figures lie. **The token-ceiling kernel ships early: it is delivered in the C2 hardening chain (`harden-hooks` + `harden-fleet-d`), not first in Phase 5** — Phase 5 consumes the shipped kernel as doctrine, it is not built here.
  - **Enforcement lever (F12 — inverted-enforcement fix).** The Stop hook's only active lever is `{"decision":"block"}`, and **block means the turn CONTINUES (spends MORE tokens) — so blocking on over-ceiling is enforcement inverted.** The lever is therefore split so that over ceiling, the Stop hook ALLOWS stop even with mail pending (mail stays visible via idle+mail), never block; hard enforcement lives in fleet.py launch paths (send-when-idle / respawn refuse or warn when cumulative tokens > ceiling), where registry access is legitimate.
  - **Where the counts live.** The Stop hook computes THIS turn's tokens from `transcript_path` in its stdin JSON (the field verified against the current hook contract at kernel-build time), or spawn writes a sid-keyed ceiling file next to the mailbox. Cumulative-across-respawn counts live in the registry keyed by NAME, written only by fleet.py — the hook has only `session_id`, so it never writes the registry or events.
- Plan gate uses existing modes: spawn in `plan`, result = plan text, manager approves → respawn `accept` with plan in prompt. No new kernel machinery.
- Distillation is a manager turn on a schedule/trigger, not a daemon feature.

<!-- librarian: adopted prior art, exPardus knowledge-librarian design (see docs/PRIOR-ART.md §"Local prior art") -->
**Knowledge-librarian safety architecture (adopted, not open).** Any automated pass that mutates `knowledge/` inherits these rules wholesale from the exPardus librarian design (built + reviewed there; C:\proga\exPardus\expardus_knowledge\tools\knowledge\librarian\ and its design doc). They are fixed constraints of this spec, not open questions:

1. **Evidence-gated destruction.** An LLM verdict alone never retires knowledge. Retirement (entry → superseded/stale-pin moved) requires an independent deterministic signal — a ref-check showing the entry's source anchor missing/moved, i.e. exactly the grep-receipt gate mechanized. A "dead" verdict on an entry whose anchors still resolve is downgraded to "stale" (flag, don't destroy). This is the C4 lesson ("an enumeration produced by inspection is wrong") applied to the maintenance loop itself.
2. **Supersede, never delete.** Retired entries flip status/move sections; content remains. Matches the existing MOVE-stale-pins-never-delete doctrine (campaign-template §2).
3. **Circuit breaker on destructive churn.** Per-run cap = `min(abs_cap, fraction × active_entries)`; NO destructive automation on a small graph (below a min-active floor); plus a trailing-window cumulative ledger cap (defeats split-across-runs runaway). On trip: safe changes (date bumps, index rebuild) still apply, destructive ones dropped, a visible "librarian halted (<reason>)" note lands in the index.
4. **Mass ref-miss = config error, not drift.** If more than an abort-fraction of entries have missing anchors, the checkout/paths are broken — abort the whole pass, touch nothing, never feed the judge. (Defends against one moved file mass-retiring real knowledge.)
5. **Untrusted-data fencing.** Entry bodies and source slices enter any judge prompt only inside per-run randomized fence tokens (`secrets.token_hex` style) with an explicit evaluate-never-obey instruction. Applies equally to fleet review pipelines that embed worker output in judge prompts.
6. **Judge-empty alerting.** Zero parseable verdicts from a scheduled pass is a recorded failure; two consecutive empty runs alert (doctor note) — an unattended loop must not silently rot.
7. **Metadata minimums.** Staleness is only detectable if entries carry `last_verified` (date) and `source` anchors (file[:line] or explicit non-code provenance markers, which are exempt from ref-checking). New knowledge entries/pins that assert claims about code carry anchors; freeform narrative (lessons.md campaign entries) is not force-atomized.
8. **Deterministic writes.** All file mutation is plain Python (write-if-changed, LF-normalized, no-op-skipping); the LLM only returns structured verdicts.

## Open questions (answer all)

1. Trust ledger schema: per (project, task-type) record — fields? (outcome, respawn count, cost, human-intervention count, mode used, date). Who writes it — manager doctrine (prose instruction) or `fleet done <name> --outcome ...` command that appends structured record? (Command = reliable; doctrine = flexible. Probably command.)
2. DoD contract format: checks embedded in task spec (e.g. "tests pass", "file X exists") — who evaluates at Stop time? Stop hook is dumb (python script, no LLM); options: (a) hook runs literal shell checks declared in a contract file, (b) manager reviews result and bounces via send. (a) is deterministic but limited; (b) costs a manager turn. Decide split.
3. Campaign templates: parameterized playbook format (frontmatter args + step list the manager instantiates)? How does a template invoke — manager reads and follows, or `fleet campaign <template> --args`? (Manager-follows keeps intelligence in Claude; command risks framework-building.)
4. Seeding (`spawn --from <name>`): journal only, or journal + last N result summaries? Cross-project seeding allowed?
5. Distillation trigger: knowledge file size threshold? Weekly? After each campaign? What's the compaction contract (never delete killing-numbers/decisions, compress narrative)? The librarian constraints block answers the *safety* half (evidence-gated, breaker-capped, supersede-only); still open is the trigger + what "compress narrative" preserves.
6. Broadcast semantics: `send --all` = same message to every non-dead worker's mailbox — exclusions (attached workers?), and is there any fan-in (collect replies)?
7. Metrics of "measurably better": what do we actually track to know the loop works — human interventions per campaign? respawns per task? cost per completed task? Pick 2-3, have `fleet stats` report them from events + trust ledger.
8. Librarian delivery shape: (a) `fleet knowledge check` — deterministic ref-checker/validator only (stdlib, doctor-pattern: grades entry anchors ok/moved/missing, mass-miss abort), runnable by hand and cheap — vs (b) the full judged loop (headless `claude -p` judge over stale-windowed candidates, scheduled via schtasks like autoclean, doctor note on failure). (a) first is the obvious ramp; is (b) worth its unattended-LLM surface at fleet's knowledge-base size (the breaker's min-active floor may say "flag-only" for a long time)?
9. Librarian scope of mutation: which files may an automated pass touch? INDEX.md pointer lines + §12 pin sections + `[UNBUILT]`-tag audits are anchor-checkable; lessons.md narrative is not (constraint 7). Does the pass annotate in place, or only emit a "needs review" report for the next manager turn (zero-write v0)?
10. Candidate windowing: `last_verified` recheck window (exPardus: 14d) and per-run cap (40) — fleet equivalents, given knowledge waves already re-verify at campaign close? Maybe window = "untouched by any campaign in N weeks."

## Done criteria

Trust ledger populated across ≥3 campaigns and demonstrably consulted (manager cites it in decisions); one premature-completion bounce caught by DoD contract in real use; distillation run keeps INDEX under control; `fleet stats` shows the chosen metrics trending; knowledge ref-check runs clean (or its findings triaged) with at least one real stale anchor caught mechanically that a manual read missed — the C4 false-`[UNBUILT]`-tag class, detected by tooling instead of a $36 spec wave.

## Invariants touched

Cites the SPEC.md numbered "Architectural invariants" section.

- **2 — exit-0 hooks.** The token-ceiling lever (F12) runs the ceiling check inside the Stop hook, and the hook ALLOWS stop over ceiling (never `block`, never errors) — it always exits 0 and surfaces nothing into the worker transcript. Preserved because the hook is a passive signal only; the block-continues-the-turn inversion is avoided by keeping all refuse/warn behavior out of the hook.
- **6 — single-writer registry.** Cumulative-across-respawn token counts live in `fleet.json` keyed by NAME and are written ONLY by fleet.py under `fleet.lock`; the Stop hook has only `session_id` and reads its own turn's tokens from `transcript_path` (or a sid-keyed ceiling file), never writing the registry or events. Preserved because hard enforcement was moved to fleet.py launch paths (send-when-idle / respawn), where registry access is legitimate, instead of the hook.
