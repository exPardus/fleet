# Spec: Autoclean — staleness is cleaned up without anyone remembering

**Status:** **BUILT AND SHIPPED, WITH ITS TRIGGER RETIRED** (mc-autoclean, designed 2026-07-16;
shipped in M-C, POSIX backend added by the 2026-07-23 reconcile campaign). Status corrected
2026-07-27 by the `unbuilt-sweep` pass — it still read `ready-for-build` long after the verb, the
install flag and both scheduler backends landed. `docs/SPEC.md` §11 is the descriptive record; the
receipt is §"Build receipt" below.

> ### AMENDMENT 2026-07-27 — THE TIMER IS RETIRED (operator ruling). D1 is superseded.
>
> **`fleet autoclean` the verb is unchanged and still shipped.** What is gone is the OS scheduler
> that used to call it: `fleet init --autoclean`, `--autoclean-interval-hours`,
> `--autoclean-remove`, the `autoclean_task_install/query/remove` adapter methods on BOTH backends,
> the task-ownership predicate, and the machine-local Scheduled Task itself. **The sweep is now
> driven by the two live tiers** — the supervisor's watchtower beat (`skills/fleet/supervisor.md`)
> and the interface's startup ritual (`skills/fleet/SKILL.md`), both landed at `c318224`.
>
> **Why, and it is not the defect that prompted it.** The registered task carried
> `StartWhenAvailable=False`, so a missed occurrence was DROPPED rather than run at boot: measured
> 2026-07-27, a 9h14m power cut ate the 08:22Z sweep, nothing caught up when the machine returned,
> next fire 20:22Z — **an 18-hour gap in a 6-hourly guard, surfaced by nothing.** Setting that flag
> was the smaller fix and the worse one. **A timer sweeps when the CLOCK says so, which on a machine
> that loses power means it does not sweep at all. A beat sweeps when the FLEET IS ALIVE, which is
> the condition that makes sweeping necessary in the first place.** Retiring the timer deletes the
> whole class of problem — no scheduler, no machine-local install state, no missed-run policy to get
> wrong, nothing to re-verify per machine — instead of patching one instance of it. Note the defect
> was never Windows-specific: cron, the POSIX backend, has no catch-up concept at all.
>
> **This record is kept, not deleted.** D1's reasoning about *why a scheduler and not a piggyback*
> is still the reasoning that rejected piggybacking, and the F2/F3/F4 install-guard history is why
> any FUTURE scheduled task must carry full-identity ownership rather than a path-only predicate.
> The sections below are historical from the trigger's side and current from the verb's side; each
> superseded passage says so inline.
**Inherits:** SPEC.md invariants, terminal-surface views doctrine, native-agents pivot §5.1.2 (auto-archival, shipped as `fleet archive`), CLAUDE.md irreversibility doctrine (`fleet clean` is the only deleter).

## Problem

`fleet archive` (TTL sweep) and `fleet clean` exist but require someone to run them. Between campaigns nothing runs, so retired workers and daemon husks accumulate (observed 2026-07-16: 13 stale workers, 15 `m0-*` daemon husks sitting for days).

## Decisions

<!-- ac-trigger -->
**D1 — trigger is an OS scheduler running a new first-class command, `fleet autoclean`; no opportunistic piggyback.** The stated gap is *"between campaigns nothing runs"* — piggybacking on mutating commands cannot close that gap by definition (between campaigns, no mutating commands run either), while a scheduler closes both the between-campaigns case and the while-in-use case (it fires on its interval regardless). Piggyback would also add a roster fetch + best-effort `claude rm` subprocesses to every `spawn`/`send` hot path and mint a new failure-isolation surface inside commands that already carry delicate lock/commit choreography — the C4/M-B lesson that fix waves and riders mint new Criticals argues against it for no coverage gain. Views stay untouched: `fleet autoclean` is an ordinary *mutating* CLI command (terminal-surface doctrine unamended); it is invocable by the Windows Scheduled Task (`fleet init --autoclean` installs it), by a supervisor watchtower beat, or by hand — one code path, three callers.

Scheduler mechanics live in the platform adapter (`autoclean_task_install/query/remove` on `_WindowsPlatform`, `schtasks`-based; `_PosixPlatform` raises `UnsupportedPlatformError` — the clean seam invariant 8 requires; cron/systemd-timer fills it in Phase 1.5).

> **SUPERSEDED 2026-07-27 (see the amendment above).** D1's *trigger* choice is retired: there is no OS
> scheduler and no adapter scheduling seam on any platform. Both backends' `autoclean_task_*` methods
> are deleted, not stubbed. **Callers are now two, both of them alive fleet tiers** (supervisor beat,
> interface startup ritual), plus an operator by hand — still one code path. D1's *rejection of the
> opportunistic piggyback* stands unamended and is why the beat is an explicit step in a ritual rather
> than a hook riding on other verbs. `fleet autoclean` remains structurally exempt from §7's claim
> gate, which is now load-bearing rather than incidental: both new callers are sessions WITH a session
> id, so an exemption that had rested on "the scheduled task has no sid" would have silently gated the
> sweep behind the very claim it exists to clean up around.

<!-- ac-tiers -->
**D2 — three tiers; only the reversible two are default-on.**

- **Tier 1 (default-on): archive TTL pass.** `cmd_autoclean` invokes the existing `cmd_archive` full pass (all workers, TTL default 24 h, `--ttl-hours` forwarded). Every T9 gate rides along unchanged: terminal status only, roster-live skip, no-outcome ⇒ never archived, `limited` never archived, conditional commit under lock, G9 epoch freeze.
- **Tier 2 (default-on): daemon-husk removal.** `claude rm` of roster sessions that fleet spawned but no longer tracks live. **Ownership discriminator (precise, sid-based, default-deny):**
  - *owned(sid)* ⇔ sid appears in ≥1 of: (a) any registry record's `session_id` or `retired_sids` (tombstones included), (b) a sid-shaped (UUID) filename under `logs/archive/*/` (evidence files are sid-named; survives tombstone deletion), (c) any `session_id` field in `state/events.jsonl` (fleet stamps `turn_started`/`archived`/`cleaned` events with sids; survives `fleet clean`).
  - *protected(sid)* ⇔ sid is the `session_id` or a retired sid of a **non-archived** registry record — a live worker's history is `fleet archive`'s territory, swept at retirement, never out from under a tracked record.
  - *husk* ⇔ roster sid where owned ∧ ¬protected ∧ roster entry not live (no `status`/`pid` keys — the same liveness test archive/status use) ∧ no pending `mailbox/<sid>.md`.
  - **No registry = no sweep (F1, adversarial fix wave).** Default-deny includes the registry's absence: a corrupt `fleet.json` is quarantine-*renamed* by whichever tier loads it first, so the next load would see a missing file, empty the protected set, and rm every idle/limited/interrupted worker's resumable session while events/archive evidence still vouches them owned. `_sweep_husks` refuses (like the G9 epoch refusal) whenever the registry file is absent but owned-evidence is non-empty; a genuinely fresh home still proceeds. `RegistryCorruptError` anywhere in the run is a **run-abort**, never a tier-skip.
  - **Quarantine artifact = no sweep (NEW-1, re-review).** Absence alone has two bypasses (a routine spawn recreates `fleet.json` with one record; an operator recreates an empty one) — either way the file is present, the protected set is thin, and pre-quarantine workers' sessions become rm-eligible. Tier 2 therefore refuses while any `state/fleet.json.corrupt.*` exists, registry present or not; the operator restores the quarantined data and removes the artifact to re-arm. Presence-only rather than an mtime comparison, deliberately: rename preserves mtime, so a recreated registry is always newer than the artifact and a "newer-than" test would never fire on the spawn-recreation bypass. Refusal messages say *restore the quarantined file* — never "recreate".
  - **Names can never be sids (F6).** `validate_name`/`dispatch_bg` refuse uuid-shaped worker names, so a name-keyed archive file's stem can never impersonate a foreign session id in the owned-evidence harvest.
  - Everything else — foremost the operator's own interactive sessions — is *foreign* and untouchable. A sid fleet has no record of is **never** selected, even if its name matches fleet's `cat|name|hint` convention (names are ai-title-mutable — 5.1.3 hazard — and convention-matching would be exactly the "touch sessions fleet didn't spawn" failure the directive forbids).
  - Consequence, accepted: husks whose sids fleet never recorded (M-0 hand-spike sessions, pin-test runs against temp `FLEET_HOME`s) stay foreign; they need one manual `claude rm` pass and cannot recur for fleet-spawned sessions.
- **Tier 3 (default-OFF, opt-in flag): tombstone expiry.** `fleet autoclean --expire-tombstones-hours N` removes registry tombstone entries whose `archived_at` is older than N **and** whose evidence move is complete (`_archive_resume_pending` false). It deletes **no files** — `logs/archive/<name>/` stays on disk, so no journal that isn't preserved is ever destroyed and `fleet clean` remains the only file-deleter (doctrine intact). Trade-off, accepted and deliberate: an expired tombstone's archive dir becomes invisible to `fleet clean`'s tombstone sweep — history-on-disk outlives registry hygiene; deleting it stays a manual act. Absent the flag — **and no caller passes it**: tier 3 is opt-in, and neither of the two tiers that actually invoke `autoclean` (the supervisor's watchtower beat, the interface's startup ritual) supplies it — tombstones live forever until an operator runs `fleet clean`. *(This previously read "and the scheduled task never passes it". Corrected 2026-07-30: that grounded the guarantee on the configuration of a task retired on 2026-07-27, so it went void the day the timer died even though the behaviour it describes did not change. The invariant is "no caller passes it", which is a fact about callers and survives any change of trigger — cf. the 2026-07-28 lesson that an exemption resting on "the scheduled task has no sid" would have silently gated itself.)*

**`fleet clean` tiering split (finding from today):** `clean` gains mutually exclusive `--dead-only` (spare tombstones — sweep only confirmed-dead workers) and `--tombstones` (sweep only archived tombstones — no probing, no legacy recompute). Default stays today's behavior (both).

<!-- ac-safety -->
**D3 — safety rails.**
- Never sweep pending mail or a live turn: tier 1 inherits archive's status/roster/outcome gates; tier 2 skips roster-live entries, protected sids, and any sid with a non-empty mailbox file.
- Lock discipline: registry snapshots under `fleet.lock`, roster fetch and every `claude rm` outside it (F4 doctrine); no lock held across subprocesses.
- Tier isolation: each tier runs in its own try/except — a tier-1 failure never blocks tier 2; errors are printed, recorded in the run stamp, and reflected in exit code 1 (the scheduler ignores exit codes; events carry the signal). Exception (F1): `RegistryCorruptError` aborts the whole run — isolation is for environmental hiccups, and a quarantined registry makes every later tier's input untrustworthy.
- Concurrency: two racing autocleans — registry writes are conditional-commit under lock (archive) or pop-under-lock (tier 3); `claude rm` is idempotent best-effort. Sweep racing a spawn: a just-dispatched sid is either roster-live (skipped) or not yet in any fleet record (unowned ⇒ default-deny skipped).
- Epoch: tier 2 refuses when the roster fetch fails or `native_epoch_suspicious` fires (same G9 line archive/clean use).

<!-- ac-observability -->
**D4 — observability.** Per-item events already exist (`archived`) or are added (`husk_removed` with sid, `tombstone_expired`); every run appends one `autoclean_run` summary event and rewrites `state/autoclean-last-run.json` (timestamp + counts + errors). `fleet doctor` gains a note-only `autoclean` check: scheduled task installed/missing (via the adapter query), and "installed but last run > 48 h ago" staleness from the stamp — note-only per doctor doctrine (only broken infrastructure turns doctor red).

> **AMENDED 2026-07-27.** The stamp and the `autoclean_run` event are unchanged. The doctor check no
> longer asks *"is the task installed"* — that stopped being a question anyone can ask — and asks
> **"when did `autoclean` last run"** instead, which is strictly more informative: an installed task
> said nothing about whether it ever fired, and that is exactly how a dropped occurrence read as
> green for 18 hours. **The threshold comes from the BEAT CADENCE, not the retired 6h timer**: a
> supervisor keeps its heartbeat younger than 60 min and sweeps once per beat, so the window is
> `AUTOCLEAN_STALE_RUN_HOURS = 3.0` — three missed beats, down from 48h. A stamp older than that means
> **the beat is not beating**, and the message names which tiers were supposed to be running it,
> because "stale" is only actionable if the reader knows whose job it was. Still note-only in every
> arm, per the same doctrine and per the 2026-07-27 lesson that *a permanently-red doctor is a
> disabled doctor*: a fleet nobody is running is a fact about the operator's day, not broken plumbing.

## Command surface

- `fleet autoclean [--ttl-hours F] [--expire-tombstones-hours F] [--dry-run] [--fleet-home P]` — tier 1 + tier 2; tier 3 only with its flag. `--dry-run` previews all tiers, mutates nothing, rm's nothing. `--fleet-home` explicitly overrides the home (F2: Task Scheduler provides no operator environment, so the env-var route doesn't exist for the scheduled run).
- `fleet init --autoclean [--autoclean-interval-hours N]` — idempotent install/update of Scheduled Task `claude-fleet-autoclean` (`schtasks /Create /F /SC HOURLY /MO N`, default every 6 h, valid 1–23) running `"<python>" "<fleet.py>" autoclean --fleet-home "<home>"` (F2: home embedded in the command, never inferred from script location at trigger time). **Install guards (F2, `--force` overrides):** refuses when the resolved fleet.py is not the target home's own copy, when the home is a linked git worktree (`.git` is a file — the task dies with the worktree), or when `~/.claude/fleet-home` points at a different home. **Ownership + fail-closed query (F3/F4):** a same-named task is fleet-owned iff its command carries the **full identity** — our resolved fleet.py path **and** the `autoclean` subcommand as the token immediately after it **and** `--fleet-home <this home>` — matched on whole, quote-stripped, slash/case-normalized tokens (`_fleet_task_is_ours`), never a substring match. An absent `--fleet-home` is not ours (a pre-F2 task lands here; `--force` recovers). **Path-only ownership is the defect, not the design:** it answers "ours" for *every* fleet-owned task regardless of verb or home, so the day a second one exists — `fleet init --supervisor-beat` is the near-term case — `/Create /F` silently overwrites it. Any new scheduled task must go through `_fleet_task_is_ours(command, <its own subcommand>)`, never a fresh path-only predicate. Task existence is established via the locale-safe `schtasks /Query /FO CSV` listing, and a query that *errors* refuses the install rather than reading as "absent" and `/Create /F`-ing over a foreign task. Doctor flags an installed task pinned to a fleet.py path that no longer exists. Composable with `--statusline`. **Guards run before init writes (N1, re-review):** `cmd_init` evaluates the worktree/marker guards *before* stamping anything — with `--autoclean` a guard problem refuses the whole init (marker and settings untouched); plain `fleet init` on a guarded home still renders the worktree-local settings but skips the global `~/.claude/fleet-home` marker stamp, loudly. Otherwise a worktree init repoints the marker first and the install-time marker-mismatch guard compares against a marker the same invocation just wrote — unfireable on the real path.
- `fleet init --autoclean-remove` — uninstall (`schtasks /Delete /TN claude-fleet-autoclean /F`). Manual equivalent documented for operators without fleet at hand.

> **BOTH BULLETS ABOVE ARE RETIRED, 2026-07-27 — the flags no longer exist.** They are kept as the
> record of what was installed and of the F2/F3/F4 guard reasoning any future scheduled task must
> inherit. The flags were **removed outright rather than accepted as no-ops**: a flag that silently
> does nothing is how an operator comes to believe a sweep is installed when none is — the same
> failure shape as the dropped occurrence. **Order of operations, for anyone doing this again:** the
> live task was uninstalled with `fleet init --autoclean-remove` *while that flag still existed*, and
> verified absent, BEFORE the install and remove paths were deleted together. Deleting the remove
> path first strands an installed task with no supported uninstall — on that machine and on everyone
> else's. **An existing install elsewhere does not self-repair:** a machine that still carries
> `claude-fleet-autoclean` keeps firing a `fleet.py` that no longer has the flag to remove it. Such an
> operator should run `schtasks /Delete /TN claude-fleet-autoclean /F` (Windows) or drop the
> `# claude-fleet-autoclean`-tagged crontab line (POSIX) by hand. Left alone it is not dangerous — the
> `autoclean` verb it calls still exists and still works — merely a timer nobody is watching.
- `fleet clean [--dead-only | --tombstones]` — manual tiering split.

## Build receipt (2026-07-27, `unbuilt-sweep`)

The verb, both scheduler backends, and the adapter seam all exist — which is why the status line above
no longer reads `ready-for-build`:

```
# at 0e8d7ca
$ grep -n "def cmd_autoclean" bin/fleet.py
7634:def cmd_autoclean(args, run=subprocess.run, which=shutil.which) -> int:
```

```
# at 0e8d7ca
$ grep -n "class _WindowsPlatform\|class _PosixPlatform" bin/fleet.py
391:class _WindowsPlatform:
522:class _PosixPlatform:
```

```
# at 0e8d7ca
$ grep -c "raise UnsupportedPlatformError" bin/fleet.py
0
```

The §7.2 supervisor exemption below shipped too:

```
# at 0e8d7ca
$ grep -n "def _record_is_supervisor_claim_holder\|supervisor claim-holder -- protected" bin/fleet.py
2087:def _record_is_supervisor_claim_holder(record, claim=None):
6799:        return (False, "supervisor claim-holder -- protected while live (§7.2)")
```

The two tags this document keeps — the `scheduled_task_*` rename and the combined-flag `fleet init`
wiring — are both still absent, and the adapter methods still carry their autoclean-shaped names:

```
# at 0e8d7ca
$ grep -cE "scheduled_task_|\"--supervisor-beat\"" bin/fleet.py
0
```

```
# at 0e8d7ca
$ grep -n "def autoclean_task_install" bin/fleet.py
446:    def autoclean_task_install(self, task_name: str, command: str,
604:    def autoclean_task_install(self, task_name: str, command: str,
```

## Three-tier interactions (doc-sync 2026-07-23, per `docs/specs/three-tier-command.md` §12)

The ratified three-tier spec (2026-07-23) touches this spec in three places:

- **The scheduler adapter now serves a second task family** (three-tier §6.1). The adapter methods (`autoclean_task_install/query/remove`) are already generic over `task_name`/`command`/`interval_hours`, and the planned supervisor-beat task installs through the same seam (`task_name="claude-fleet-supervisor-beat"`). The `autoclean_task_*` naming is now a misnomer for a generic scheduler seam; a rename to `scheduled_task_*` is `[UNBUILT]` cosmetic cleanup, not a blocker.
- **Per-task ownership, exactly as the F4 doctrine above demands** (three-tier §6.2). The beat task's ownership predicate is `_fleet_task_is_ours(command, "beat")` — the full-identity match, never a fresh path-only predicate — so the beat and autoclean tasks coexist without either `/Create /F`-ing the other. The multi-flag `fleet init` wiring (`--autoclean` + `--supervisor-beat` in one invocation) is `[UNBUILT]`.
- **The supervisor record becomes exempt from tier 1 and tier 2, keyed on the live claim-holder, never a static name** (three-tier §7.2). **[BUILT `5a8860b`]** — receipt below. The archive TTL (24 h) vs the schtasks interval clamp (≤23 h) means an idle supervisor record would otherwise be archived/rm'd out from under a running campaign. The predicate: a record is protected iff its `session_id` (or a member of its `retired_sids`) is the current `supervisor/INCARNATION` claim-holder's — **holder alone**, which protects a successor under any name (`sup|<inc>|successor`) and never protects a dead husk (three-tier B1/B9). *(Correction, 2026-07-27 `unbuilt-sweep`: this bullet previously read "**and** that body is roster-live". That conjunct was removed by the 2026-07-24 operator amendment before the build — it made the gate a no-op, since `_archive_eligible` gate 3 already refuses every roster-live record, and it failed to close §7.2's own disaster case. The shipped predicate is holder-alone; this bullet was describing a design that was never built.)*

## Testing

Unit: ownership discriminator table incl. **fault-inject** (a foreign roster sid must never be selected — the test seeds a foreign session alongside a genuine husk and fails if the owned-set filter is bypassed); protected sids of live records spared; tombstone/events/archive-dir sid sources each recognized; live-entry and pending-mail gates; tier isolation (tier-1 crash ⇒ tier 2 still sweeps); tier-3 default-off (ancient tombstone untouched without the flag) + pending-move tombstone never expired + files untouched; dry-run mutates nothing; clean `--dead-only`/`--tombstones` semantics; init install/refuse-foreign/force/idempotent/remove via injected fake `run`; doctor check note-only on every path.
