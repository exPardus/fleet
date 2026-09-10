# Next session — operator board, 2026-09-10

Recorded against `08b34d0`; refresh at every wave boundary (≤30 lines).
Floor: **5216 collected, `6 failed, 5193 passed, 16 skipped, 1 xfailed`, IDENTICAL
on 3.10 and 3.12.** The six are host assumptions (4 drive-qualified-path escapes,
2 venv-shim re-execs), not fleet defects.

1. **Multi-fleet usable — DONE.** Bare `fleet init` in a repo creates a home there
   (`2f48827`). It does NOT append to the machine-global homes list; that stays
   `init --home`'s irreversible act. **G-K8's sibling question is drafted in
   `docs/lanes/w64-initrepo.md`** if you want registration automatic.
2. **Zero downtime** — G-K6 wave 2 landed OFF BY DEFAULT (`851e797`). **Blocked on
   new gate G-K8**: waking an idle body means writing to the Claude daemon's
   private socket, against standing goal 3's "zero writes to foreign surfaces".
   Nothing breaks while it sits — the feature is inert until you install it.
3. **Reaping is now a mechanism** (`f22a672`), not a supervisor chore: boot,
   handoff-complete and release run it and print `reaped: N rows`. The merged-tree
   floor caught it reaching around `sup-release`'s refusal to tombstone an
   ambiguous identity; fixed, and `sup-handoff-complete` had the same hole.
4. **Mechanise rituals** — the inventory exists: 220 rows, 167 CODE / 53 MODEL
   (`395015c`). Turn costs are honestly UNMEASURED: transcripts are not available
   to a lane and journal headers are record counts, not tool-call counts. **Batch 1
   remains: `fleet wave-close`, `sup-guard`, `interface-register`, and the journal
   board roll** — which is now a KNOWN LIVE DEFECT: `bin/fleet.py:17746` appends
   without rolling, so the board reddens at every fourth checkpoint. Hand-rolled
   this wave (`53b62d6`).
5. **fleet.py split** — report landed (`72aa972`), recommends D. Still yours to
   ratify; extraction not started.

Open gates: **G-K8 (new, this wave)**, plus G-K1/G-K2/G-K4/G-K5/G-K6/G-K7 as
recorded. G-K7 stays annotated DISCHARGED BY DOING, unticked — yours alone.
Constraints in force: **Claude worker freeze** (zero Claude workers, Opus
supervisor), **Codex budget** (default `gpt-5.6-luna`, astra by named exception),
**waves of 1–2 lanes**, **3 live workers host-wide, 1.5 GB available floor**.
