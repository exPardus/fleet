# Supervisor Journal

Append-only checkpoint log (spec §4). Single writer: the current claim
holder, via `fleet sup-*` commands only. Never edit or delete entries.
Entry header format: `## <utc-iso> <KIND> inc=<incarnation-id> sid=<session-id>`
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.

<!-- entries below -->

## 2026-07-15T11:46:55Z BOOT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

fresh claim: no existing claim -- fresh claim

## 2026-07-15T11:48:48Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B plan authoring started per NEXT-SESSION.md handoff: spec v2.3 s5/s5.1 + native-substrate contract read; 3 code-map explorers running over bin/fleet.py (UL1 limit machinery, spawn lifecycle, hooks+supervisor+doctor); plan lands at docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md
