# Next session — operator board, 2026-09-10

Recorded against `b2ba94a`; refresh at every wave boundary (≤30 lines).
Floor: **5228 collected, `6 failed, 5205 passed, 16 skipped, 1 xfailed`, IDENTICAL
on 3.10 and 3.12** — the six are host assumptions, not fleet defects.

1. **Multi-fleet — DONE.** Bare `fleet init` in a repo creates a home there
   (`2f48827`). It does NOT register it machine-globally; that stays `init --home`'s
   irreversible act, and the question is drafted in `docs/lanes/w64-initrepo.md`.
2. **Zero downtime** — the keeper wake landed OFF BY DEFAULT (`851e797`), **blocked
   on new gate G-K8**: waking an idle body means writing to the Claude daemon's
   private socket, against goal 3's "zero writes to foreign surfaces". Nothing
   breaks while it sits; the feature is inert until installed.
3. **Reaping is a mechanism** (`f22a672`) — boot, handoff-complete and release run
   it and print `reaped: N rows`. The floor caught it reaching around
   `sup-release`'s refusal to tombstone an ambiguous identity; fixed, and
   `sup-handoff-complete` had the same hole.
4. **Mechanise rituals** — inventory is 220 rows, 167 CODE / 53 MODEL (`395015c`),
   turn costs honestly UNMEASURED. **The journal board roll and
   `interface-register` LANDED (`5d659ad`)**: the board now rolls itself from
   `sup-checkpoint`. **`fleet wave-close` and `fleet sup-guard` remain.**
5. **fleet.py split** — report landed (`72aa972`), recommends D. Yours to ratify;
   extraction not started.

Open gates: **G-K8 (new)**, plus G-K1/G-K2/G-K4/G-K5/G-K6/G-K7. G-K7 stays
DISCHARGED BY DOING, unticked — yours alone.
In force: **Claude worker freeze** (zero Claude workers, Opus supervisor),
**Codex budget** (default `gpt-5.6-luna`; astra by named exception), **waves of
1–2 lanes**, **3 live workers host-wide / 1.5 GB available floor**, and **mcx
lanes stay DETACHED** — no `--wait`, no waiter, no poll loop: the harness kills
background commands on `free`, and killing a `--wait` waiter killed lane
`mImoA8QT` outright.
