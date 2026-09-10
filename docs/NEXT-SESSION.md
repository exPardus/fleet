# Next session — operator board, 2026-09-10

Recorded against `a43331a`; refresh at every wave boundary (≤30 lines).
Floor: **5245 collected, `6 failed, 5222 passed, 16 skipped, 1 xfailed`, IDENTICAL
on 3.10 and 3.12** — the six are host assumptions, not fleet defects.

1. **Multi-fleet — DONE** (`2f48827`). Bare `fleet init` creates a cwd home; it
   does NOT register it machine-globally (drafted in `docs/lanes/w64-initrepo.md`).
2. **Zero downtime** — the keeper wake landed OFF BY DEFAULT (`851e797`), **blocked
   on new gate G-K8**: waking an idle body means writing to the Claude daemon's
   private socket, against goal 3's "zero writes to foreign surfaces". Nothing
   breaks while it sits; the feature is inert until installed.
3. **Reaping is a mechanism** (`f22a672`) — boot, handoff-complete and release run
   it and print `reaped: N rows`.
4. **Mechanise rituals** — inventory is 220 rows, 167 CODE / 53 MODEL (`395015c`),
   turn costs honestly UNMEASURED. **BATCH 1 IS COMPLETE**: the board
   roll and `interface-register` (`5d659ad`), then `sup-guard` and `wave-close`
   (`a43331a`). **`wave-close` is built but has never run for real — its first
   use is the next wave's close, and its commit/push arm was never exercised
   end-to-end in the sandbox. Watch it.** Its effect-table class is deliberately
   UNCLASSIFIED and fail-closed until you ratify it.
5. **fleet.py split** — report landed (`72aa972`), recommends D; yours to ratify.

Open gates: **G-K8**, plus G-K1/G-K2/G-K4/G-K5/G-K6/G-K7 (G-K7 unticked, yours).
In force: **Claude worker freeze** (zero Claude workers, Opus supervisor),
**Codex budget** (default `gpt-5.6-luna`; astra by named exception), **waves of
1–2 lanes**, **3 live workers host-wide / 1.5 GB available floor**, and **mcx
lanes stay DETACHED** — no `--wait`, no waiter, no poll loop: the harness kills
background commands on `free`, and killing a `--wait` waiter killed lane
`mImoA8QT` outright.
