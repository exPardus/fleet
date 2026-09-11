# Operator changelog
THROUGHPUT wave 80 (c05d6c3..d6a06652e9bbe7282fc78b121acc784296e9b8cd): bin +79/-36, tests +33/-5, docs +126/-0, journal +25/-13, other +0/-0; workers: 1 (w84/homes-inventory: codex); tokens: 4186837; tokens_per_bin_line: 52997.94 (4186837 tokens / 79 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)
Wave 80 — the homes inventory counts what the guard counts

merge(w84/homes-inventory) 767564a. `fleet homes` showed one row while the
arming guard counted two, and `_refuse_wrong_home_destructive` built a single
message from both: it said "this machine runs 2 fleets", printed both paths
under "Homes counted:", and then embedded a view showing one. That message is
what an operator sees at the moment a command of theirs was refused.

The view now renders the resolution population, each row labelled as a listed
record or the install-root legacy term, and the refusal renders from the
arming snapshot so its count and its view cannot drift apart. A single-fleet
machine's output is deliberately unchanged: arming begins at a population of
two, so below that there is no disagreement to correct.

Measured live against the real install root, before and after: 1 row vs
2 rows, guard counting 2 throughout.

Four defects found at landing, none visible to the lane: `homes_population()`
lost its `ok` key; the lane's two view tests contradicted each other and it
ran neither; the listed-home reason test was never updated for the legacy
term; and the spec paragraph was inserted between steps 2 and 3 of the
numbered resolution order, terminating the list.

And the reason those lanes see nothing: a Codex lane has no DNS, and a brief
that names the warm uv cache without `UV_OFFLINE=1` makes uv try PyPI first
and die with the cache already complete. MEASURED on 3.10 and 3.12 with the
network blocked: with the flag, green; without it, unresolvable. w83 and w84
each shipped code they had never executed for want of one environment
variable in a brief I wrote. `docs/lanes/BRIEF-TEMPLATE.md` now names it.

Operator items advanced: item 1 (multi-fleet usable by the operator).
THROUGHPUT wave 79 (638878b..831f7f82cfbeb3d8fe0ac50814ef52ef44338ba8): bin +233/-22, tests +97/-0, docs +97/-0, journal +31/-20, other +0/-0; workers: 1 (w83/computed-board: codex); tokens: 2819275; tokens_per_bin_line: 12099.89 (2819275 tokens / 233 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)
Wave 79 — the supervisor's board computes itself, and batch 2 is discharged

merge(w83/computed-board) ca1732a. `sup-checkpoint` refuses a body over three
lines before it takes the lock — so a refusal neither rotates the nonce nor
files a false second-body row — and prints git identity, cleanliness, live
lanes and blockers it derives itself. The boot bundle gains a computed board:
pickup list, live lanes with their worktrees, undischarged standing
directives, dispatch gates. Every source is labelled, and an unreadable one
names itself rather than defaulting to a plausible value. Live bundle 9,377
chars against the 40,000 cap.

Four defects found at landing, none visible to the lane, whose sandbox had no
DNS and which therefore executed none of its own tests: an unanchored
`DISCHARGED` matched the words "not discharged" and silently dropped live
directives from the board; `RULED` was read as a discharge, though the batch-2
directive says RULED and still had an item in flight; both board helpers read
`Path.cwd()` instead of `FLEET_HOME`, so a different git repository would have
answered every question plausibly and wrongly; and the new liveness-shaped
reader was undeclared to the census in `tests/test_liveness_readers.py`.

The mechanise-batch-2 directive is now DISCHARGED, each clause carrying the
wave and merge that landed it: `fleet land` and the structured lane result
(w78), `fleet brief` (w80), the computed board (w83), knowledge caps (w79),
and the measurement itself (w82).
THROUGHPUT wave 78 (f19fa02..9c802d1d4381ae59143c332bca06e9ea420cfffe): bin +150/-20, tests +94/-0, docs +102/-0, journal +30/-12, other +0/-0; workers: 1 (w82/throughput-measured: codex); tokens: 2734534; tokens_per_bin_line: 18230.23 (2734534 tokens / 150 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)
Wave 78 — THROUGHPUT stops saying UNMEASURED

`wave-close` reads Codex usage from the landed lane's own worktree instead of
the main checkout's `.mcx`, which is not where lane jobs write. Claude usage
falls back from the token-less agents roster to `state/outcomes/*.jsonl`,
bounded to the landed lanes' current sessions. `tokens_per_bin_line` and
`external_lines` now print in this line and in the CHANGELOG header; each
names its denominator or its missing source rather than defaulting to zero.

merge(w82/throughput-measured) dafc707.

Measured live before landing: 2,734,534 Codex tokens for lane w82 alone —
the number three waves reported as `UNMEASURED (mcx result files missing)`.

`docs/lanes/BRIEF-TEMPLATE.md` now names what `fleet land` actually reads:
`<name>` is the branch's first path component, the JSON `lane` field is that
same component and not the lane KIND, and `blockers` is a landing gate rather
than a notes field. Three consecutive landing refusals, all taught by the
template.
- 2026-09-11 — `b2a8dc7`: entering the 350k supervisor context band now REFUSES `spawn`, `send`, `respawn` and `sup-spawn` with a one-line reason, instead of relying on the supervisor to remember. `--force-band` clears that soft refusal for one call and cannot clear the 400k hard ceiling; the handoff verbs are never refused, because a gate that blocks the remedy is worse than no gate.
- 2026-09-11 — `b2a8dc7`: `fleet sup-checkpoint` reports the caller's context occupancy and band verdict in its header line.
- 2026-09-11 — `67c874b`: `fleet brief <item>` emits a brief — DONE line, base sha, file list, test command, structured-result contract, blank judgement — and refuses when the `Serves:` citation is absent or when its phrase does not occur under the `product.md` section it names. Checking the section as well as the phrase catches a phrase that moves between sections, which is a real change to what a feature serves.
- 2026-09-11 — `67c874b`: every dispatched task file from 2026-09-11T21:00Z names the `product.md` line it serves; wave 75 and earlier are grandfathered and nothing is retrofitted.
- 2026-09-11 — `730bb2a`: the docs-currency lint accepts `docs/`, `skills/` and `knowledge/` — a `bin/` change documented in the operating manual or in a project's host-fact note is documented, and used to fail.
- 2026-09-11 — `062fcd9`: `fleet land <lane>` validates a lane's structured result, commits exactly the paths it lists when the lane could not commit, rebases it on the source tip, runs its named tests plus the docs-currency and receipt checks, and prints ten lines ending GREEN or RED — so a failing lane reaches you as an exit code, never as prose.
- 2026-09-11 — `062fcd9`: `docs/lanes/<lane>.json` is the lane result contract — files changed, tests with their rc and counts, claims each tied to a proving command, blockers — and a claim with no command behind it is refused.
- 2026-09-11 — `dd6c271`: `tools/knowledge_index.py` generates and checks `knowledge/INDEX.md`, fails a stale index or an over-cap boot entry, and rolls lessons older than 30 days to the archive verbatim; notes loaded on demand are reported over cap, never moved.
- 2026-09-11 — `46b80e8`: the fleet skill's CLI list names every verb that accepts `--nonce` — it showed 6 where `build_parser()` has 21, and omitting the flag is refused as a second-body continuity failure, which reads like an incident and is not one.
- 2026-09-11 — `4def0a9`: the documentation tree drops to 19,542 live lines — lane reports, reviews, decisions and superpowers move verbatim into `docs/archive/`, which nothing loads and no audit reads as a claim about the current tree.
- 2026-09-11 — `c47f75a`: `bin/fleet.py` carries no history narrative — 12,268 docstring and comment lines become 3,001 with the executable code unchanged.
- 2026-09-11 — `581e3f3`: the `bin/fleet.py` split contract is fixed — 80 index/query definitions, their dependencies and the import direction — and records why the boundary needed one more leaf than the ruling scoped.
- 2026-09-11 — `123f84e`: `bin/fleet_index.py` now holds the index and query cluster and `bin/fleet_errors.py` holds `FleetCliError` alone; `bin/fleet.py` keeps state and the CLI, and exception identity is unchanged for every caller.
- 2026-09-11 — `1d9920d`: one keeper tick watches every home it is given — `--fleet-home` repeats, pages and wakes carry a `[home-tag]`, and each home keeps its own dedup state.
- 2026-09-11 — `8a7af00`: `fleet sup-guard` gains an `OK` verdict, so a healthy supervisor — fresh heartbeat with a live body, busy or idle — no longer produces a page; `PAGE` is reserved for genuinely ambiguous states, `WAKE` for a stale idle body with a live process, and `DISPATCH` only when a stale claim has no live body at all.
- 2026-09-11 — `613da18`: retiring a supervisor's pre-steer process now requires a fork that has actually taken over, not merely one that is reachable.
- 2026-09-11 — `7e5a0c9`: `fleet sup-guard` treats a roster row with a live pid as live even when the daemon reports `state: done`, so a supervisor hosted on an adopted bg-spare is woken rather than paged about.
- 2026-09-11 — `d205e4d`: `fleet wave-close` refreshes the claim heartbeat, so a supervisor that closes waves no longer looks stale to the keeper for the length of the wave.
- 2026-09-11 — `f1dcbf3`: the interface the keeper launches no longer inherits the inference-only OAuth token, which blocked Remote Control.
- 2026-09-11 — `1a58339`: the keeper wakes an idle supervisor by sending it a wake brief through `fleet send` instead of writing to the Claude daemon's private socket, which is removed; it asks `fleet sup-guard --do` for the verdict rather than judging liveness itself, still never spawns a supervisor, and pages once for a limited body without retrying before its reset horizon.
- 2026-09-11 — `502f3f7`: THROUGHPUT reads a lane's substrate from its record (`unknown` when none exists) instead of defaulting to `claude`, and `state/interface/board.md` lists a task file as a pending ruling only while it carries no `RULED:` line.
- 2026-09-11 — `196e3de`: the keeper pages only a pane actually running `claude` — a pane that has dropped to a shell falls back to the window path, which recreates `work:fleet` — and `fleet wave-close` removes lane worktrees whose branch is merged, skipping unmerged or dirty ones.
- 2026-09-11 — `1587302`: `fleet wave-close` refuses to close when a merge since base has no CHANGELOG line, resolves `--base` to the previous close commit, counts lanes merged rather than registry rows, sums Claude and Codex tokens with `UNMEASURED` naming the missing source, and prints `protected: N (unread mail)`.
- 2026-09-11 — `1587302`: `state/interface/board.md` counts a ruling pending only while its task file carries no `RULED:` line.
- 2026-09-11 — `853f72e`: supervisor and worker output is compressed by rule, in the fleet skill and the sup-boot bundle.
- 2026-09-11 — `cadbad0`: `fleet sup-guard` treats a seize as settled once the seizing body has heartbeated, so an old seizure no longer pages a healthy supervisor.
- 2026-09-11 — `314ea3e`: `skills/fleet/` is now a 160-line operating manual covering the three tiers, every verb, dispatch rules and the wave boundary; `supervisor.md` and `docs/operator/server-interface-profile.md` are deleted, their current content absorbed.
- 2026-09-11 — `efc4b5c`: the context-loaded documents are under cap with no history narrative, lessons older than 30 days are archived, and `tests/test_prose_caps.py` pins every cap — including the ones later waves must close.
- 2026-09-11 — `b0b5370`: the interface is a role any session can take — `state/interface/board.md` and `log.md` live in the home, bare `fleet init` registers the calling session, and the §7 gate is evaluated against the home being initialised so a claim elsewhere no longer blocks `init` in an unrelated repo.
- 2026-09-11 — `1ab7f3e`: the keeper still pages when no interface is registered instead of exiting silently, and its `--profile` default names a file that exists.
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
