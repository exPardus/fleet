# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v3 (2026-07-30, interface tier). History: v1 gated same-day → RESTRUCTURE
(`mf-rb`/`mf-rs`); v2 gated same-day → RESTRUCTURE again (`mf-rb2` B1–B14 / `mf-rs2` 48-of-60,
reports under `state/journals/`); v3 follows a fresh-context design consult and **replaces v2's
central mechanism** — the `.fleet-home` marker is deleted (§9 records why). GATE THEN BUILD:
v3 takes a round-3 gate before any operator docket entry. All code references are **by symbol**
— v2's line anchors were measured stale 35 minutes after it was written, suite green (mf-rs2).

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
per session, per repo, or per directory — instead of exactly one. Today there is one fleet
because `FLEET_HOME` is **two variables wearing one name**: the *data plane* (the home) and the
*install locator* that finds hook scripts, `fleet.py`, the statusline and the worker-settings
template. Measured at v1's gate: `fleet init` against a data-only home refuses; after
hand-patching, `fleet doctor` emits five FAILs including both hook smoke tests — a fleet-B
worker would run with four dead hooks, silently, because hooks exit 0. **The split is the work.**

Incident receipt for the coupling: 2026-07-29T22:58:39Z, something ran fleet code from inside
the repo with no `FLEET_HOME` set and overwrote the real `state/fleet.json` +
`supervisor/INCARNATION` with fixture data (quarantine: `state/*.testpollution.20260729T225839Z`;
the rename was manual). The forensics lane ran in wave 13; the isolation pins are §7.

## Definitions

- **Install** — the code plane: `bin/fleet.py`, `bin/hooks/`, `bin/fleet_statusline.py`,
  `worker-settings.template.json`, `docs/`, `tests/`. `INSTALL_ROOT =
  Path(__file__).resolve().parent.parent`, **never overridable** by flag, env, or list.
  A marketplace plugin-cache copy is structurally indistinguishable from an install (measured,
  mf-rs2: the cache dir on this machine is a full install *and* a full home with 5 worker
  records) — so no "cache refusal" exists; what governs is home-list membership (§4), and a
  cache copy's home simply is not listed.
- **Home** — one fleet's soul and state: `state/`, `logs/`, `mailbox/`, `knowledge/`,
  `supervisor/GOALS.md` + `JOURNAL.md` + `INCARNATION`. One per fleet. Install == home stays
  legal forever (the dogfood fleet today); it stops being required.
- The four worker hooks each carry a standalone `_fleet_home()` (quadruplicated; the
  `stop_outcome.py` copy already diverges — `Path.resolve()` vs `os.path.abspath`). Slice 0
  unifies four copies plus the statusline's import-time conflation.
- **Path comparison rule, everywhere a home path is compared**: compare
  `os.path.normcase(str(Path(p).resolve()))` on both sides. pathlib equality is a hidden OS
  branch (mf-rb2 B7: case-insensitive match on Windows, case-sensitive miss on POSIX/APFS —
  a refusal predicate must not give per-platform answers to identical input).

## M1 — scope

Honest sizing: not a flag. The v1 "mechanism already works" premise was measured false and the
flag-not-subsystem re-vet failed on the merits. M1 = the split (slice 0), the homes list, the
resolution order, `init --home`, `adopt`, and pins. Still excluded: federation views, cross-home
operations of any kind (§10).

### Slice 0 — the install/home split

Re-point the install-locator sites at `INSTALL_ROOT` — by symbol: `template_settings_path`,
`statusline_script_path`, the lifecycle-steer render, the two doctor hook-smoke checks
(`_doctor_check_*` hook rows), `_render_sup_spawn_task`, `_render_successor_task`, the
`render_worker_settings_template` call, and the template's own hook-command placeholder (becomes
`{{FLEET_INSTALL}}/bin/hooks/...`). Correction from mf-rs2 carried forward: the doctor
*legacy-settings* check is **home-plane** and must NOT be re-pointed; the list above is the
gate-measured set minus that row — the build slice re-greps `FLEET_HOME /` before touching
anything (v2's list was wrong in both directions once already).

## §4. The homes list

`~/.claude/fleet-homes.list`: one absolute home path per line, UTF-8, append-only, atomic line
append, deduplicated on `normcase(resolve())`. Written by exactly two verbs — `fleet init
--home` (registration is part of scaffolding) and `fleet adopt` (§6) — **never by session
plumbing, hooks, or dispatch.**

**Why this is not the deleted corpse** (`~/.claude/fleet-home`, deleted 2026-07-22): the corpse
was an *authority* — a mutable pointer whose stale value would have redirected `clean`/`kill` at
another fleet's registry, which is exactly why giving it a reader was refused. The list is a
**search space**: a hit requires the caller's sid to be present in that home's live registry
(§5), so a stale, wrong, or malicious line can only produce a *miss* or an *ambiguity refusal*
— there is no input that turns a bad line into a wrong-home resolution. Failure modes, enumerated
at the consult: dead/moved line → miss (harmless — a re-inited path has a sid-disjoint registry);
copied home present in the list → sid in two registries → **loud ambiguity refusal naming both**
(fail-closed; remedied via the `fleet homes` view + dedupe + a doctor NOTE row); unreadable list
→ **refusal for sid-carrying mutating callers, never a fall-through to env** (that fall-through
is v2's B12 returning).

Honesty item: this is a second fleet-written file outside any home. The shipped claim that
`~/.claude/settings.json` is "the ONLY file outside FLEET_HOME that fleet writes"
(`user_settings_path` docstring) is restated in the same slice.

## §5. Resolution

**Sid-carrying callers** (workers, supervisors, and adopted interface sessions — any process
holding `CLAUDE_CODE_SESSION_ID`):

1. **`--fleet-home` flag** (global; applied in `main()` before dispatch; validation = resolve,
   `is_dir`, **initialized** — an existing-but-empty dir is a refusal, not a phantom home; v2's
   gate demonstrated today's autoclean flag creating `state/` under `--dry-run` and reporting
   `rc=0`, byte-identical to a clean fleet). If the flag disagrees with the lookup's answer,
   mutating verbs refuse without `--yes` and write a witness line.
2. **sid→home lookup** over the list (plus the legacy install-root home while §8 lives): probe
   each listed home's registry with the quarantine-free tolerant reader — **never
   `load_registry`**, whose corrupt-registry quarantine rename against a *foreign* home would be
   a cross-fleet mutation from a read path (views doctrine, pinned by
   `tests/test_views_doctrine.py`). Match against **live records' current `session_id` plus the
   `INCARNATION` holder's sid — nothing else.** Excluding `retired_sids` is what closes the
   stale-identity channel (a live session cannot legitimately present a retired sid — that match
   is a *forensic refusal*, not a resolution); excluding `spawned_by` is what keeps a manager
   from being ambiguous across every fleet it manages. **This membership set is pinned by a
   dedicated test.** Exactly one hit → resolved. Two-plus hits → refusal naming all (accepted
   cost: an operator who `adopt`s one session into two fleets flags per call). Miss → mutating
   verbs refuse; read verbs fall through to (3) **with the resolution provenance rendered in
   their output**.
3. **Validated env → legacy default** (reads only, per above): `FLEET_HOME` must resolve to an
   initialized home directory (same validation as the flag, minus list membership — an unlisted
   temp home is the test suite's and any ad-hoc probe's legitimate shape). Once the list holds
   ≥2 homes, destructive verbs resolved via env additionally require the flag.
4. **TOCTOU closed mechanically**: every mutating verb, after taking the resolved home's
   `fleet.lock`, re-asserts caller sid ∈ that home's membership set before acting.

**Sid-less callers** (a human at a plain shell): flag → validated env → install-root legacy
default (§8). This class keeps today's ergonomics entirely; `_confirm_destructive`'s deliberate
sid-less early-out stays as-is because the channels this class can use are both explicit.

**Hooks**: `--fleet-home` argv baked per-home into the rendered worker-settings (survived both
gates unchanged; exactly two `--settings` construction sites exist — `dispatch_bg` and
`cmd_sup_handoff_begin` — and the build touches both or pins the second separately). Witness on
argv/env disagreement: argv wins, one line to `hook-errors.log`; env absent is the *normal* case
and logs nothing.

**Statusline**: takes its sid from the vendor stdin blob — not from its (donated) env — and runs
the same lookup; renders words, exits 0, never quarantines, resolver is a pure function under
unit test (its `BaseException` swallow makes the render path unpinnable). Whether the blob
carries `session_id` and `cwd` is **unverified** — the capture experiment (temporary delegate
dumps payload + `os.getcwd()` from two directories) **gates this slice**; v2 stating "cwd is
reachable" while scheduling the experiment to find out was caught as self-contradiction (mf-rs2
K3).

**Arming**: multi-fleet resolution activates only when the list holds a **second** home (the
repo's gate-arm precedent). With zero or one listed home, every caller class resolves exactly as
today — single-fleet installs and the dogfood fleet cannot regress.

**Refusal texts print facts and the `fleet homes` view — never a paste-ready command with a
chosen home.** v2's destruction guard died partly by printing its own bypass with the wrong home
pre-filled; a remedy that trains flag-by-habit permanently disarms the disagreement check in (1).

## §6. `fleet adopt`

Registers the calling session into a home: writes the caller's sid into that home's registry
under its `fleet.lock` (a first-class membership record, not a worker), and appends the home to
the list if absent. The fleet skill's startup ritual runs it once per session; operators run it
explicitly. This makes membership a **registry fact for every caller class** — the lookup
becomes total, and the manager tier stops being the coverage hole (the consult's Q1.7: an
interface session's sid otherwise lives only in `spawned_by`, which the membership set must
exclude). One verb, no new subsystem; without it the manager class would fall through to env
forever, which is the hole v1 died of.

## §7. Test isolation pins

- Autouse conftest fixture exports `FLEET_HOME=<tmp>` into `os.environ` (subprocess-inheriting;
  the founding incident proves the subprocess path). Function-scoped override available — a
  session-scoped-only fixture makes the §5 "not initialized" rendering untestable after the
  first `init` (mf-rb2 B13). Env stays a valid read channel for sid-less test subprocesses
  (§5.3), so this fence is not defeated by the lookup — and with the marker deleted, v2's B2
  (marker-beats-fixture) is structurally gone.
- Founding-incident guard: a **content-hash canary**, not an mtime window — the watched files
  belong to a live fleet that writes in bursts on a minutes cadence, so an mtime pin is
  intermittently RED with no test at fault, which is how fences get xfail'd (mf-rb2's measured
  165s/240s/558s ages against a 219s suite). Watches every **listed** home plus the legacy
  install-root home — anchoring at `INSTALL_ROOT/state/` alone would make §8's completion
  (moving the dogfood home out) silently disarm the guard forever (mf-rb2 B6a). Landed RED
  first.
- The §5.2 membership-set pin (live `session_id` + INCARNATION holder, nothing else).
- The §5 arming pin: in a ≥2-home config, a sid-less, flag-less, env-less mutating invocation
  from inside the install **refuses** rather than resolving to install-root — falsifiable,
  unlike v2's "no path silently falls back to `parent.parent`" criterion, whose forbidden
  expression is also `INSTALL_ROOT`'s correct definition (mf-rb2 B6b).
- "Not initialized" is a **rendered word** on every read surface, pinned (today: header row then
  silence, measured).

## §8. The legacy default's exit criteria

Install-root fallback (sid-less class, and the lookup's legacy probe) is kept in M1 and
removable when ALL of: (1) slice 0 done — no code path uses `FLEET_HOME` to find code; (2) the
dogfood home physically moves out of the install and is **listed** — the §7 canary follows the
list, so the watch moves with it; (3) the shims, statusline, and skill pass a **plane-naming
lint** (an enumerable artifact: each `$FLEET_HOME`/`fleet home` consumer is tagged
install-plane or home-plane in a checked table — v2's "audited" had no falsifiable artifact);
(4) the §7 arming pin extended to the sid-less class. Removal is an operator decision against
these criteria.

## §9. The marker, deleted — record

v2's `.fleet-home` marker + bounded walk-up died at round 2 on four demonstrated findings: the
dogfood configuration made the dispatch-written marker invalid by the marker's own rules (B1);
"stops at the enclosing git root" is two mutually exclusive designs that disagree on 65 of 66
checkouts here, and the git-semantics-correct reading makes parent markers unreachable — the
walk-up did no work at all (B3); "write if absent" silently serves fleet A's stale marker to
fleet B's worker (B9); and dispatch would plant untracked files in 66 project trees, in a repo
with documented untracked-add accidents (B10). The residual audience — a sid-less human wanting
per-directory scope — is served by flag and validated env. Anyone re-proposing a
marker-in-the-tree answers B1/B3/B9/B10 first; this section exists so they are answered once.

## Cross-fleet interference audit

| Surface | Status |
|---|---|
| `claude` session namespace | Shared. Husk-sweep ownership stays per-home evidence, default-deny; `doctor` fleet-unknown check stays NOTE-only, wording gains "or another fleet's". |
| Daemon env donation | Substitution model (docketed 2026-07-30, `docs/OPERATOR-GATES.md`). Env demoted to read-only fall-through with validation; hooks on argv; statusline on blob sid; CLI on registry lookup. **Inherited residual, stated**: the lookup keys on `CLAUDE_CODE_SESSION_ID`, and sid-donation is recorded OPEN in the shipped code's own comment (`_record_sids` block) — bounded because `_worker_env` pops the sid (a fleet-started daemon has none to donate) and every measured body shows the vendor stamping each session's own sid; a daemon cold-started by a non-fleet sid-holding launcher is unmeasured. This spec inherits the docketed premise; it does not open a new one. Mitigation in-design: retired/dead-sid matches refuse forensically. |
| Homes list | New fleet-written global file: search-space-not-authority (§4); written only by two explicit verbs; a bad line can only miss. |
| Statusline settings entry | Unchanged; `init --statusline` still refuses to clobber a foreign one. |
| Plugin/skill | Pull-only (D7). Ritual gains `fleet adopt` (§6) and the install-vs-home split for its step-1/step-3 reads (SKILL.md currently reads `docs/` — install-plane — through `$(fleet home)`). |
| `fleet.lock`, registry, mailbox, claims | Home-relative; N homes = N single-writer domains. Lookup reads foreign registries lock-free with the tolerant reader and never writes them; the F26/M25 refusal ("never a shared writable `fleet.json`") transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; §16's tenth is UNBUILT/M-F-owned, untouched)

1. **daemonless** — preserved; a home is directories, the list is a text file.
2. **exit-0 hooks** — preserved (argv + witness line; hooks refuse nothing).
6. **single-writer registry** — preserved per home. The lookup **reads** foreign registries
   (lock-free, tolerant, quarantine-free — the established views pattern); the only cross-home
   *write* surface in the whole design is `adopt`, which writes exactly one home under exactly
   that home's lock.
7. **one live session per name** — preserved per home; sids are the daemon-facing key.
8. **platform-adapter-only OS branching** — the Definitions comparison rule (`normcase` +
   `resolve` both sides) is stated once and used everywhere precisely so no refusal predicate
   hides a per-platform branch (the v2 defect class). No new adapter seam.
9. **one-state-many-views** — preserved; the lookup and `fleet homes` are derivations over
   registries, never a second source of truth.

## Graveyard check

Corpse re-check for the list is §4's paragraph (search space vs authority — the axis that made
the 2026-07-22 deletion right is absent here by construction). Corpse 10's "brittle sniffing":
resolution consults no `--help`, no version strings, no heuristics — a registry hit is a fact
dispatch wrote under a lock.

## M2 — read-only federation view (demand-gated, NOT M1)

`fleet status --all-fleets` over the same list, views only. Unchanged from v2.

## Open questions

1. **`adopt` record shape**: a first-class membership record vs a zero-turn pseudo-worker row —
   pick at build gate; the membership-set pin constrains either.
2. **Sid-donation residual** (audit table): closes only with the docketed identity-clause
   ruling; if the operator orders a re-measure, the decisive experiment is a cold daemon started
   by a non-fleet sid-holding launcher.
3. **WSL/Windows dual-view** of one filesystem: two runtimes, two `~/.claude` dirs, two lists —
   effectively two machines sharing homes. Cross-runtime home sharing is out of M1 scope; say so
   in the operator docket (the v2 marker had the same problem unstated).
4. **`knowledge/` for non-repo homes**: scaffolded plain; learning-loop commits apply when the
   home is a repo. Accepted for M1.

## Sequencing

1. v3 → **round-3 gate**: fresh dual lens, no shared context, no access to prior rounds'
   verdicts. Priority attack surface: §4 list mechanics (append/dedupe/unreadable), the §5
   membership set and its exclusions, the arming rule's single-fleet no-regression claim, §6
   `adopt` (does registering the manager create a new hazard class?), and the §5.2 tolerant
   reader against a corrupt foreign registry.
2. Findings folded → **operator docket entry**: scope, resolution order, `adopt`, §8 criteria,
   and the two accepted costs (ambiguity refusals for dual-adopted sessions; no cross-runtime
   sharing).
3. Build slices, disjoint: (0) split; (a) list + lookup + arming + `fleet homes` view;
   (b) `init --home` + `adopt`; (c) hook argv + witness; (d) statusline (gated on the capture
   experiment); (e) pins. RED-then-GREEN, both floors, serially.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
slice-0 symbol list is inherited from a gate one merge queue back (re-grep before build); the
"vendor stamps each session's own sid" premise rides a docketed, unratified replacement clause;
and §5's claim that read-verb fall-through renders provenance assumes every read surface HAS a
provenance line to render — the compact status table may not.
