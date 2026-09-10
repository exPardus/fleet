# Operator changelog
- 2026-09-11 — `a1b04cb`: `fleet sup-guard` no longer pages on a healthy fleet — a seize is an event in the past, so a seized claim with a fresh heartbeat is an ordinary held claim; seized plus a stale heartbeat still pages.
- 2026-09-11 — `8a8d086`: `fleet wave-close` runs its floor through `uv` (no interpreter on this host has pytest importable) and now refuses a floor that produced no pytest summary, which previously read as a clean floor.

Newest first, ONE line per user-visible change. At landing the supervisor prepends
new lines with date and commit evidence; the interface quotes them at each wave
boundary alongside THROUGHPUT. Seeded from reachable git history at `708fa45`.

- 2026-09-11 — `6327ea9`: `fleet sup-guard` prints one two-live-body verdict (`DISPATCH` / `WAKE <body>` / `PAGE <reason>`) instead of the interface running five commands; a live idle body always yields `WAKE`, never a second spawn, and `--do` re-verifies before acting.
- 2026-09-11 — `b737c24`: `fleet wave-close --base <sha> --changelog @<file>` performs the whole wave boundary — guarded reap, two-interpreter fresh-clone floor, THROUGHPUT landing, journal roll, bounded push and interface relay — and aborts before landing if the floor's totals or failure set do not match.
- 2026-09-10 — `5d659ad`: the supervisor journal board now rolls itself — `sup-checkpoint` calls the new `fleet journal-roll`, so the committed board stays at three checkpoints instead of reddening the suite every fourth one.
- 2026-09-10 — `5d659ad`: `fleet interface-register` registers the interface's tmux pane in one idempotent command, and refuses clearly when there is no tmux instead of writing a nonsense pane id.
- 2026-09-10 — `f22a672`: supervisor boot, handoff completion and release reap eligible rows themselves through autoclean; boot reports `reaped: N rows` and carries the three-worker / 1.5 GB dispatch rule. Unread mail, live PIDs, the current claim and any ambiguous identity are protected, and a body never reaps its own rows on its way out.
- 2026-09-10 — `2f48827`: bare `fleet init` inside a repo now creates a fleet home there, accepted by a later `--fleet-home`; it deliberately does NOT register the home machine-globally, which stays `init --home`'s irreversible act.
- 2026-09-10 — `851e797`: the keeper can optionally wake an idle supervisor body instead of only paging about it — off unless the operator supplies both `--wake-socket` and `--wake-key`, and gated on open gate G-K8.
- 2026-09-10 — `395015c`: every ritual step in the supervisor, standing-brief and interface-profile documents is now classified CODE or MODEL in one 220-row table, the inventory the mechanise-rituals directive builds from.
- 2026-09-10 — `f0c8ebf`: the keeper finds the interface by its registered tmux pane, so a hand-resumed session no longer gets a duplicate window created beside it.
- 2026-09-10 — `72aa972`: research report on whether `bin/fleet.py` stays one file; recommends a bounded index/query pilot, pending operator ratification.
- 2026-09-10 — `708fa45` / `ba7fc40`: supervisor and keeper resolve the body's current and retired session IDs together, avoiding false missing-body pages after fork-steer.
- 2026-09-10 — `aee5fdf`: dogfood home appended to the homes list; the two-home proof showed both tags and armed the machine-wide wrong-home guard.
- 2026-09-10 — `245bdf1` (landed `1de9995`): the statusline nameplate identifies the fleet home.
- 2026-09-10 — `c6b6713` (landed `afa51a8`): keeper C pages `supervisor-stalled` for an alive supervisor that is not busy.
- 2026-09-10 — `7928a9f` (landed `6df3161`): Codex/mcx worker design and spike documented; native `fleet spawn --substrate codex` remains unbuilt at this pin.
- 2026-09-09 — `d25f1b2`: `fleet init --home <PATH>` creates another fleet home.
- 2026-09-09 — `803a9a3`: `fleet sup-notify` announces graceful supervisor succession to the interface; keeper pages say to relaunch.
