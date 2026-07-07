# Spec: Intelligence layer (Phase 5) — the moat

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md. Interleaves with Phase 4 after Phase 3.

## Goal

The manager gets measurably better over time. Mostly doctrine + knowledge structure + small CLI additions — deliberately code-light; the compounding asset is the knowledge base, not features.

## Scope

In: trust ledger, plan-approval gate flow, definition-of-done contracts, session seeding (`spawn --from`), campaign templates, broadcast/named addressing, knowledge distillation routine. Out: any ML/scoring service, autonomous manager loops without human kickoff (that stays Telegram manager-on-call), cross-CLI workers (Phase 6).

## Fixed constraints

- Trust ledger and templates are git-tracked knowledge files (structured markdown or JSON in `knowledge/`) — readable/editable by human, written by manager turns, no database.
- DoD contracts enforce via the EXISTING Stop-hook mechanism (mailbox veto with feedback) — no new hook types.
- Salvaged kernel (IDEA-FORGE-REPORT §4): per-worker cumulative TOKEN ceiling checked in the Stop hook — token counts only, no $-conversion, no price table. Complements `--max-budget-usd` and works behind provider proxies where $ figures lie.
- Plan gate uses existing modes: spawn in `plan`, result = plan text, manager approves → respawn `accept` with plan in prompt. No new kernel machinery.
- Distillation is a manager turn on a schedule/trigger, not a daemon feature.

## Open questions (answer all)

1. Trust ledger schema: per (project, task-type) record — fields? (outcome, respawn count, cost, human-intervention count, mode used, date). Who writes it — manager doctrine (prose instruction) or `fleet done <name> --outcome ...` command that appends structured record? (Command = reliable; doctrine = flexible. Probably command.)
2. DoD contract format: checks embedded in task spec (e.g. "tests pass", "file X exists") — who evaluates at Stop time? Stop hook is dumb (python script, no LLM); options: (a) hook runs literal shell checks declared in a contract file, (b) manager reviews result and bounces via send. (a) is deterministic but limited; (b) costs a manager turn. Decide split.
3. Campaign templates: parameterized playbook format (frontmatter args + step list the manager instantiates)? How does a template invoke — manager reads and follows, or `fleet campaign <template> --args`? (Manager-follows keeps intelligence in Claude; command risks framework-building.)
4. Seeding (`spawn --from <name>`): journal only, or journal + last N result summaries? Cross-project seeding allowed?
5. Distillation trigger: knowledge file size threshold? Weekly? After each campaign? What's the compaction contract (never delete killing-numbers/decisions, compress narrative)?
6. Broadcast semantics: `send --all` = same message to every non-dead worker's mailbox — exclusions (attached workers?), and is there any fan-in (collect replies)?
7. Metrics of "measurably better": what do we actually track to know the loop works — human interventions per campaign? respawns per task? cost per completed task? Pick 2-3, have `fleet stats` report them from events + trust ledger.

## Done criteria

Trust ledger populated across ≥3 campaigns and demonstrably consulted (manager cites it in decisions); one premature-completion bounce caught by DoD contract in real use; distillation run keeps INDEX under control; `fleet stats` shows the chosen metrics trending.
