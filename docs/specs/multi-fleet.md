# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v4 (2026-07-30, interface tier). History: v1 → RESTRUCTURE (`mf-rb`/`mf-rs`);
v2 → RESTRUCTURE (`mf-rb2`/`mf-rs2`, marker killed); v3 (post-consult, registry-lookup core) →
round 3: break RESTRUCTURE on **mechanics**, verify FIX-LIST — and the core held on both
(`mf-rb3`: reader sound, exclusions' *direction* correct, "no D4 violation"; `mf-rs3`: D4 driven
through 7 corruption paths, 0 quarantines). v4 folds both round-3 reports; the architecture is
unchanged from v3. Reports: `state/journals/mf-r{b,s}{,2,3}.md`. GATE THEN BUILD: round-4 gate
before the operator docket. Code references by symbol only.

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
per session, per repo, or per directory — instead of exactly one. Today there is one fleet
because `FLEET_HOME` is **two variables wearing one name**: the *data plane* (the home) and the
*install locator* that finds hook scripts, `fleet.py`, the statusline and the worker-settings
template. Measured at v1's gate and re-driven at round 3: `fleet init` against a data-only home
refuses; after copying the template in, the rendered hook commands point at
`<home>/bin/hooks/*.py`, which does not exist — a fleet-B worker runs with four dead hooks,
silently, because hooks exit 0 (doctor shows 4 FAILs on the minimal repro; the earlier "five"
depended on an undefined patch recipe and is retired as unfalsifiable — mf-rs3). **The split is
the work.**

Incident receipt for the coupling: 2026-07-29T22:58:39Z — fleet code run from inside the repo
with no `FLEET_HOME` set overwrote the real `state/fleet.json` + `supervisor/INCARNATION` with
fixture data (quarantine: `state/*.testpollution.20260729T225839Z`). Isolation pins are §7.

## Definitions

- **Install** — the code plane: `bin/fleet.py`, `bin/hooks/`, `bin/fleet_statusline.py`,
  `worker-settings.template.json`, `docs/`, `tests/`. `INSTALL_ROOT =
  Path(__file__).resolve().parent.parent`, **never overridable**. A marketplace plugin-cache
  copy is structurally indistinguishable from an install (measured: the cache dir on this
  machine is a full install *and* a home with worker records) — no "cache refusal" exists; what
  governs is §4 membership, and a cache copy's home simply is not listed.
- **Home** — one fleet's soul and state: `state/`, `logs/`, `mailbox/`, `knowledge/`,
  `supervisor/GOALS.md` + `JOURNAL.md` + `INCARNATION`. Install == home stays legal forever
  (the dogfood fleet today); it stops being required.
- The four worker hooks each carry a standalone `_fleet_home()` (quadruplicated;
  `stop_outcome.py`'s copy diverges). Slice 0 unifies them plus the statusline's import-time
  conflation.
- **Home-path comparison rule**: compare by **filesystem identity** — `os.path.samefile` (stat
  identity) when both paths exist, which lets the filesystem itself answer case (Windows,
  APFS) and normalization (NFC/NFD) questions instead of any string predicate; fall back to
  `normcase(resolve())` string comparison only for nonexistent paths, and say which was used in
  any refusal that turned on it. v3's `normcase`-everywhere rule was itself a hidden per-platform
  branch and left the APFS false-MISS open (mf-rb3 F5).

## M1 — scope

Not a flag (the re-vet failed on measured merits at round 1 and stays failed). M1 = slice 0
(split), the homes list, resolution, `init --home`, `adopt`, pins. Excluded: federation views,
cross-home operations (§10). Named build reality from round 3 (mf-rs3): **no shipped registry
reader takes a path** — all bind the process-global `FLEET_HOME` — so slice (a) explicitly
contains `read_registry_at(home)`, the tolerant path-parameterized reader; no existing component
serves §5.2.

### Slice 0 — the install/home split

Re-point the install-locator sites at `INSTALL_ROOT` — by symbol: `template_settings_path`,
`statusline_script_path`, the lifecycle-steer render, the two doctor hook-smoke checks,
`_render_sup_spawn_task`, `_render_successor_task`, the `render_worker_settings_template` call,
and the template's hook-command placeholder (becomes `{{FLEET_INSTALL}}/bin/hooks/...`). The
doctor *legacy-settings* check is home-plane — NOT re-pointed. The build slice re-greps
`FLEET_HOME /` before touching anything; every prior enumeration of this list has been wrong in
at least one direction.

## §4. The homes list

`~/.claude/fleet-homes.list`: one absolute home path per line, UTF-8. Written by exactly two
verbs — `fleet init --home` and `fleet adopt` — **never by hooks or dispatch** (v3 said "session
plumbing", which collided with §6's ritual step; the binding rule is: no write path that fires
without an operator- or tier-issued explicit verb).

**Write mechanism (mf-rb3 F1, measured: naive `open(...,"a")` loses whole lines under 8-writer
contention on win32, 6 of 19 trials, both floors):** appends go through the platform adapter's
`atomic_append_bytes` (`_WindowsPlatform`: single-syscall `FILE_APPEND_DATA` — the exact
mechanism this repo adopted for the same defect class on 2026-07-16, which v3 failed to cite),
each record newline-terminated by the writer. POSIX side: `O_APPEND` single `write()`. The
writer re-reads after append and dedupes by filesystem identity; a lost-line append is thereby
detected and retried, not silently absorbed.

**Read grammar (mf-rb3 F7):** strip a leading BOM at file level; per line: strip whitespace,
skip empty; a line that is not an absolute path is **invalid** — skipped with a `doctor` NOTE
naming it, never allowed to invalidate other lines and never re-interpreted relative to
anything. A final unterminated line is one invalid line, not corruption of the file.

**Why this is not the deleted corpse** (`~/.claude/fleet-home`, deleted 2026-07-22): the corpse
was an *authority* — a stale pointer would redirect `clean`/`kill`. The list is a **search
space**: a hit requires the caller's sid live in that home's registry (§5), so a stale, wrong,
or duplicated line can only produce a miss, a skipped line, or an ambiguity refusal — never a
wrong-home resolution. Copied-home-in-list → ambiguity refusal naming both (remedy: `fleet
homes` view + identity-dedupe + doctor NOTE). Unreadable list → refusal for sid-carrying
mutating callers, never fall-through to env.

Honesty item: a second fleet-written file outside any home; the `user_settings_path` "ONLY file
outside FLEET_HOME" docstring is restated in the same slice.

## §5. Resolution

**Sid-carrying callers** (any process holding `CLAUDE_CODE_SESSION_ID`):

1. **`--fleet-home` flag** — global, applied in `main()` before dispatch (**to be built**:
   today the flag exists on `autoclean` only; every prior draft that said "exists" or "lift
   verbatim" overstated). Validation: resolve, `is_dir`, **initialized** — refusal otherwise,
   and **no code path may `mkdir` into an uninitialized target as a side effect** (round 3
   found `state/` scaffolding from `--dry-run` and three in-the-wild empty `state/` dirs;
   mf-rs3 V7). Flag/lookup disagreement → mutating verbs refuse without `--yes` + witness line.
2. **sid→home lookup.** Population: **listed homes ∪ the legacy install-root home** (the
   dogfood home needs no listing to count — v3 arming counted the list alone, so the one-listed-
   home + unlisted-dogfood case, i.e. the first real second fleet, disarmed it; convergent
   mf-rb3 F3 / mf-rs3 V2). Per home, ONE lock-free snapshot read via `read_registry_at` with
   tri-state outcome (mf-rb3 F6): **hit / miss / unreadable** — "cannot read this home" is
   never rendered as "your sid isn't here". From that snapshot: `LIVE(h)` = current
   `session_id` of non-dead records ∪ the `INCARNATION` holder's sid; `RETIRED(h)` = that
   home's retired sids. **Precedence, explicit (convergent mf-rb3 F2 / mf-rs3 V3):**
   - sid ∈ `LIVE(h)` → member of `h`, **regardless of whether it also appears in
     `RETIRED(h)`** — dual presence is the *ordinary* fork-steer restamp window that shipped
     doctrine already documents (ND4a; `_record_sids`' union is "THE ONE IDENTITY CONCEPT"
     precisely because of it). v3's unordered member/forensic rules alarmed on every respawn.
   - sid ∈ `RETIRED(h)` and ∉ `LIVE(any home)` → **forensic refusal** (a session presenting
     only a retired identity, everywhere, is the stale-identity channel).
   - Exclusions unchanged and pinned: `spawned_by` never grants membership (a manager must not
     be ambiguous across the fleets it manages).
   Exactly one member-home → resolved. Two+ → refusal naming all. Miss everywhere → mutating
   verbs refuse (refusal lists any *unreadable* homes — membership may be there); read verbs
   fall through to (3) with provenance rendered where the surface has a provenance line
   (the compact status table gains a one-line header; that is the render site).
3. **Validated env → legacy default** (reads, and — until the machine is actually multi-fleet —
   everything, see Arming): `FLEET_HOME` must resolve to an initialized home (flag validation
   minus list membership; unlisted temp homes are the suite's legitimate shape). Once ≥2 valid
   homes are visible, destructive verbs resolved via env additionally require the flag.
4. **TOCTOU**: every mutating verb, after taking the resolved home's `fleet.lock`, re-asserts
   caller sid ∈ `LIVE(home)` before acting (`adopt` exempted — §6).

**Sid-less callers**: flag → validated env → install-root legacy default (§8). Today's
ergonomics unchanged; `_confirm_destructive`'s sid-less early-out stays.

**Hooks**: `--fleet-home` argv baked per-home into rendered worker-settings (survived all three
rounds; two `--settings` construction sites — `dispatch_bg`, `cmd_sup_handoff_begin` — both
touched or the second pinned). Witness on argv/env disagreement: argv wins, one
`hook-errors.log` line; env-absent is normal and silent.

**Statusline**: sid from the vendor stdin blob, same lookup; renders words, exits 0, never
quarantines; resolver is a pure function under unit test. Blob schema is **unverified** — the
capture experiment gates the slice.

**Arming (re-grounded on effect — convergent round-3 gating):** multi-fleet resolution activates
per invocation when the lookup's population contains **≥2 distinct valid homes** — distinct by
filesystem identity, valid = readable + initialized. Not on list length (dupes and dead lines
inflate it; an unlisted second fleet deflates it — both measured hazards). With <2 valid homes
visible, behavior is byte-identical to today (mf-rs3 captured the 0/1/2-entry baseline at
`12c6521` as the post-build no-regression fixture — the claim is falsifiable only against that
baseline, and the pin is §7's).

**Refusal texts print facts and the `fleet homes` view — never a paste-ready command with a
chosen home** (the v2 guard died training its own bypass).

## §6. `fleet adopt`

Registers the calling session into a home: writes the caller's sid into that home's registry
under its `fleet.lock` as a first-class membership record, and appends the home to the list if
absent. **Exempt from §5's miss-refusal and §5.4's re-assert by the repo's own ratified rule: a
verb that clears a state must not be gated on that state** (mf-rb3 F4 measured the bootstrap
deadlock this exemption dissolves). `fleet adopt --remove` deletes the membership record (and is
the un-adopt path the design owed). The skill ritual runs `adopt` as an explicit documented
step — an operator-initiated session running a named verb, which is exactly the write class §4
permits; hooks and dispatch still never touch the list. Cost accepted and stated: an operator
who adopts one session into two fleets gets per-call ambiguity refusals and flags explicitly.

## §7. Test isolation pins

- Autouse conftest fixture exports `FLEET_HOME=<tmp>` into `os.environ` (subprocess-inheriting),
  function-scope override available. Env stays a valid channel for sid-less test subprocesses,
  so the fence is not defeated by the lookup.
- Founding-incident guard: **content-hash canary** over every home in the §5 population (list ∪
  legacy) — not an mtime window (live fleets write in bursts inside one suite duration,
  measured), and not anchored at `INSTALL_ROOT` alone (else §8's completion disarms it). RED
  first.
- The §5.2 membership pin: `LIVE` ∪-membership + precedence over `RETIRED` + both exclusions,
  driven through a real fork-steer restamp window (the ND4a state), asserting *member, no
  alarm*.
- The arming pin: with 2 valid homes visible, a sid-less/flag-less/env-less mutating invocation
  from inside the install **refuses**; with <2, output is byte-identical to the captured
  `12c6521` baseline.
- The §4 writer pin: N concurrent appenders, zero lost homes (the mf-rb3 F1 harness is the
  test, inverted).
- "Not initialized" is a rendered word on every read surface; no verb `mkdir`s into a non-home.

## §8. The legacy default's exit criteria

Install-root fallback kept in M1; removable when ALL of: (1) slice 0 done; (2) the dogfood home
physically moves out of the install **and is listed** (the §7 canary follows the population, so
the watch moves with it); (3) the plane-naming lint passes (each `$FLEET_HOME`/`fleet home`
consumer tagged install-plane or home-plane in a checked table); (4) the arming pin extended to
the sid-less class. Operator decision against these criteria. Note the interlock: the legacy
home is IN the §5 population regardless of listing, so retiring §1.4 changes the *sid-less*
class only — workers never depended on it.

## §9. The marker, deleted — record (unchanged from v3)

v2's `.fleet-home` marker + walk-up died at round 2 on four demonstrated findings: dogfood
config made the dispatch-written marker invalid by its own rules (B1); "enclosing git root" is
two designs disagreeing on all-but-one checkout here, and the git-correct reading makes parent
markers unreachable (B3); "write if absent" serves fleet A's stale marker to fleet B (B9);
dispatch would plant untracked files in ~69 project trees (B10). Anyone re-proposing a
marker-in-the-tree answers those first.

## Cross-fleet interference audit

| Surface | Status |
|---|---|
| `claude` session namespace | Shared; husk-sweep ownership per-home, default-deny; doctor fleet-unknown stays NOTE-only + "or another fleet's". |
| Daemon env donation | Substitution model (docketed 2026-07-30). Env = validated read fall-through; hooks argv; statusline blob sid; CLI registry lookup. **Inherited residual, stated:** the lookup keys on `CLAUDE_CODE_SESSION_ID`; sid-donation is OPEN in shipped code's own comment (`_record_sids` block) — bounded (fleet pops the sid pre-dispatch; every measured body shows the vendor stamping the session's own sid); a daemon cold-started by a non-fleet sid-holding launcher is unmeasured. Ties to the docketed identity gate; opens nothing new. Retired-only matches refuse forensically. |
| Homes list | Fleet-written global file: search space, not authority; two explicit writer verbs; adapter atomic append; a bad line can only miss/skip/refuse. |
| Statusline settings entry | Unchanged; `init --statusline` refuses to clobber foreign. |
| Plugin/skill | Pull-only (D7). Ritual gains the explicit `adopt` step and the install-vs-home split for its step-1/step-3 reads. |
| `fleet.lock`, registry, mailbox, claims | Home-relative; N single-writer domains; lookup reads foreign registries via `read_registry_at` (lock-free, tolerant, quarantine-free — driven through 12 corruption shapes round 3, zero quarantines); only cross-home write is `adopt`, under that home's own lock. F26/M25 refusal transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; the tenth is UNBUILT/M-F-owned, untouched)

1. **daemonless** — preserved. 2. **exit-0 hooks** — preserved. 6. **single-writer registry** —
preserved per home; foreign reads lock-free and write-free; `adopt` writes one home under that
home's lock. 7. **one live session per name** — preserved per home. 8. **platform-adapter-only
OS branching** — the list writer goes THROUGH the adapter's `atomic_append_bytes` seam (win32 /
POSIX halves already exist for exactly this defect class); the comparison rule delegates
platform semantics to the filesystem via `samefile`. 9. **one-state-many-views** — preserved;
lookup and `fleet homes` are derivations, never a second truth.

## Graveyard check

§4's corpse paragraph (search space vs authority). Corpse 10 "brittle sniffing": resolution
consults no help text, no versions, no heuristics — a registry hit is a fact dispatch wrote
under a lock.

## M2 — read-only federation view (demand-gated, NOT M1)

`fleet status --all-fleets` over the same list, views only.

## Open questions

1. **`adopt` record shape** — first-class membership record vs pseudo-worker row; build-gate
   choice; the membership pin constrains either.
2. **Sid-donation residual** — closes with the docketed identity ruling; the decisive
   experiment if a re-measure is ordered: cold daemon started by a non-fleet sid-holding
   launcher.
3. **WSL/Windows dual-view** — two runtimes, two `~/.claude`, two lists = two machines sharing
   homes; out of M1; named in the docket.
4. **`knowledge/` for non-repo homes** — scaffolded plain; accepted for M1.

## Sequencing

1. v4 → **round-4 gate**: fresh dual lens, prior rounds' reports fenced out. Priority: the §5
   precedence rules against live fork-steer/respawn states; the §4 writer under contention on
   BOTH floors; the arming population's filesystem-identity dedupe; §6's exemption scope (is
   miss-refusal-exempt `adopt` abusable as a resolution bypass?); the §7 canary's stability on
   a live fleet.
2. Fold → **operator docket entry**: scope, resolution order, `adopt` + its exemption, §8
   criteria, accepted costs (dual-adopt ambiguity; no cross-runtime sharing).
3. Build slices, disjoint: (0) split; (a) `read_registry_at` + list + lookup + arming +
   `fleet homes`; (b) `init --home` + `adopt`/`--remove`; (c) hook argv + witness;
   (d) statusline (gated on capture experiment); (e) pins. RED-then-GREEN, both floors,
   serially.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
slice-0 symbol list is gate-inherited (re-grep at build); the fork-steer LIVE/RETIRED precedence
is designed against ND4a as *documented* — drive the actual restamp timing before trusting it;
the POSIX `O_APPEND` single-write claim is asserted from doctrine, not measured on a POSIX box;
and the worktree population on this machine has been counted 64, 65, 66, and 69 by four
measurers — treat any count as a timestamp.
