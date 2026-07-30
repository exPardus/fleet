# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: **drafting v8 — SEVEN GATE ROUNDS COMPLETE, AWAITING OPERATOR RULING** (2026-07-30,
interface tier; docket entry filed in `docs/OPERATOR-GATES.md` the same day). History: v1→v2
RESTRUCTUREs (marker, §9); v3 registry-lookup core (held ever since); v4–v5 mechanics; v6
deleted `adopt`; v7 deleted the miss-refusal and the class predicate, tiering the guard on
irreversibility; round 7 (`mf-rb7`/`mf-rs7`, both GATING) killed v7's one-line destructive
criterion (it did not generate its own list — failed on `kill`), omitted supervisor tier,
undefined terminus, and DISCOVERED two shipped defects (global-position `--fleet-home`
silently clobbered by `autoclean`'s subparser; `doctor --repair` unenumerated). v8 folds all
of it: the verb-effect table, the terminus, the supervisor tier + successor argv, the
measured pre-claim windows. Reports: `state/journals/mf-r{b,s}{,2,3}.md`, `mf-r{b,s}4.md`,
`mf-r{b,s}5.md`, `mf-r{b,s}6.md`, `mf-r{b,s}7.md`. Code references by symbol.

## Why this exists

Operator launch goal (2026-07-29): independent fleets per session/repo/dir instead of exactly
one. Today there is one fleet because `FLEET_HOME` is two variables wearing one name: the home
(data plane) and the install locator. Measured repeatedly: a data-only home yields four dead
hooks, silently. **The split is the work.**

Incident receipt: 2026-07-29T22:58:39Z — fleet code run from inside the repo with no
`FLEET_HOME` overwrote the real registry + INCARNATION with fixture data. **Honest scope
(rb6 CRITICAL-3): the §1.4 legacy fallback means this class closes only for callers that name
a home, plus the §7 pins for the suite; full closure is §8's exit, not M1's.** A lens body
measured its own import resolving to its own worktree this round — the class is live until §8.

## Definitions

- **Install** — code plane. `INSTALL_ROOT = Path(__file__).resolve().parent.parent`, never
  overridable. Plugin-cache copies are structurally indistinguishable from installs; §4
  membership governs.
- **Home** — one fleet's soul and state. Install == home stays legal forever.
- **The two-media model, structural (rb6 CRITICAL-2, measured):** a daemon-hosted (`--bg`)
  session's environment is the daemon's frozen first-dispatch environment **plus a per-session
  `CLAUDE_CODE_SESSION_ID` override**. Proof by counting: the daemon is a singleton (its lock
  says so), one frozen env holds exactly one sid, and four live bodies read four distinct
  correct sids. Consequences: **the sid is trustworthy; every other env var on a hosted body
  is evidence about the daemon's cold-starter, not the body**; the previously-OPEN sid-donation
  question is **closed in the safe direction** (CONFIRM-A) — the audit row and open question
  carrying it are retired this revision, and the docketed identity gate gains this receipt.
  v6's hosted/interactive env-soundness *classification* is retired with them: `claude attach`
  makes a hosted session interactive-driven, so the class boundary was never decidable at
  runtime (rb6 MAJOR-10, rs6 C-5) — **v7 no longer needs it anywhere**.
- The four worker hooks each carry a standalone `_fleet_home()`; slice 0 unifies them plus the
  statusline's import-time conflation.
- **Home-path comparison**: `samefile` when both exist, exception-wrapped, never raising out
  of resolution; `normcase(resolve())` fallback for nonexistent; identity values never
  persisted.
- **Initialized home, defined** (rs6 C-3 — v6 used the term undefined): a directory whose
  `state/fleet.json` exists and parses as a registry by the tolerant reader. The no-`mkdir`
  rule binds **resolution and read paths**; verbs whose contract is creation (`init --home`)
  create, and mutating verbs on a resolved-but-uninitialized home refuse before any write
  layer (shipped `save_registry` mkdirs — the refusal must sit above it).

## M1 — scope

Not a flag. M1 = slice 0, the homes list, resolution, the destructive-verb tier, `init
--home`, `fleet homes` (view/`--add`/`--retire`), pins. Zero cross-home writes. Zero runtime
session classification. Build reality: **the tolerant path-parameterized reader is NEW work**
— rs6 C-4 corrects v6's "zero raises": that property was driven on a round-3 *prototype*; the
shipped reader raises, and `read_registry_at` must be built to the driven contract, with the
prototype's 12 corruption shapes as its RED-first fixture set.

**Binding slice constraint (both round-5 lenses, unchanged):** the global `--fleet-home` flag
ships in or before the arming slice.

### Slice 0 — the install/home split

Re-point by symbol: `template_settings_path`, `statusline_script_path`, the lifecycle-steer
render, the two doctor hook-smoke checks, `_render_sup_spawn_task`, `_render_successor_task`,
the `render_worker_settings_template` call, the template's hook-command placeholder
(`{{FLEET_INSTALL}}/...`). Doctor legacy-settings check stays home-plane. Re-grep before
touching.

## §4. The homes list

`~/.claude/fleet-homes.list`. Append-only forever (rewrite reading measured 95–100% loss;
no-rewrite lint). Records: home path, or `!<home path>` retirement; **sequence fold, last
record wins per identity** — `add·retire·add` = member. Writers: `fleet init --home`,
`fleet homes --add`, `fleet homes --retire`; never hooks, never dispatch, never
session-implicit. Appends via adapter `atomic_append_bytes` (precedent `851e15f`, `a4f0079`);
read-side verify verifies the **folded membership**, not the line. Read grammar: tolerant
decode (`EF BB BF`/`FF FE`/`FE FF`; no-BOM non-UTF-8 → `mbcs`/`latin-1` + doctor NOTE);
absolute by the spec's own grammar (drive-letter/UNC on Windows, leading `/` POSIX — never
`os.path.isabs`, floor-divergent); no `..`; must name an initialized home at read time (also
retires torn prefixes). Invalid lines never invalidate others. **Unreadable list ⇒ treated as
armed-with-unknown-population: destructive verbs require the flag; nothing falls silently to
single-fleet behavior** (the round-6 arming-fails-open family, closed in the arming paragraph
below). Search-space-not-authority argument and honesty items unchanged from v6.

## §5. Resolution — one order for every caller, guard tiered by irreversibility

1. **`--fleet-home` flag** — global, applied in `main()` before dispatch (**to be built**).
   Validation: resolve, `is_dir`, initialized; no side-effect `mkdir`. Flag/lookup
   disagreement → mutating verbs refuse without `--yes` + witness line.
2. **sid→home lookup** (sid-carrying callers). Population: folded list ∪ legacy install-root
   home while §8 lives (§8 completion removes the term). Per home, one lock-free snapshot via
   `read_registry_at`, tri-state hit/miss/unreadable. Membership: the home-level union this
   spec defines — per-record `session_id` ∪ `retired_sids` over the home's records;
   `spawned_by` never grants membership (pinned). Exactly one member-home → resolved (TOCTOU:
   mutating verbs re-assert membership under that home's `fleet.lock`). Two+ → refuse naming
   all. **Miss → fall through, for every verb class.** v6's miss-refusal is DELETED: it
   refused the manager class in flat contradiction with the step below (rb6 C-1 traced eight
   of fourteen slash commands dead), it refused every freshly dispatched body in the pre-claim
   window (`session_id=None` until the roster join — rs6 C-2), and repairing it required a
   hosted/interactive predicate nothing can compute (rs6 C-5). Unreadable homes: reported in
   provenance, counted by arming, and any lookup that *would* have matched only an unreadable
   home is indistinguishable from a miss — which is why the destructive tier below exists.
3. **Validated env** — `FLEET_HOME` resolving to an initialized home. Serves the manager
   (interactive sessions set it or inherit it from their shell), the suite (tmp homes), and
   the pre-claim window. On a hosted body this value is the daemon donor's (two-media model)
   — which is exactly why step 5's tier exists instead of a class predicate.
4. **Legacy install-root default** (until §8).
5. **Terminus, defined (rs7 C-1 — v7 had none):** when no step resolves — post-§8 with no
   flag, no membership, no valid env; or pre-§8 when step 4 yields an uninitialized directory
   (a plugin-cache copy is exactly this) — **mutating verbs refuse with the named remedy
   (`--fleet-home` or `FLEET_HOME`), and views render `[fleet]: no home` and exit 0.** No
   step falls off the end of the list silently, on any surface.

**The verb-effect table (replaces v7's one-line criterion, which did not generate its own
list — rs7 C-2 killed it on `kill`, this repo's own contract for which is respawn-recoverable):**
verbs classify by their **worst irreversible effect in the wrong home**, enumerated per verb:

| Class | Verbs | Wrong-home effect |
|---|---|---|
| **destructive** — destroys evidence or sessions; nothing recovers it | `clean` (journals, outcomes, records), `archive` + `autoclean` tier 2+/3 (`claude rm`, tombstone drop), `doctor --repair` (registry renamed aside — rb7 C-3), `sup-handoff-abort` (stops a successor session), any future verb whose implementation calls `claude rm`, deletes evidence files, or renames registry/claim state — **the lint keys on those effect sites** (`claude rm` invocations, unlink/rename of `state/`/`supervisor/`/`logs/` paths), NOT on `_confirm_destructive`, which is an ownership guard whose call sites neither contain nor are contained by this list (rs7 C-3 measured the disjointness) |
| **disruptive** — recoverable but harms a live foreign fleet | `kill`, `interrupt`, `send`, `respawn` (all forms), `release` |
| **ordinary** | `spawn`, `init`, `status`/`peek`/`result`/views, `homes --add/--retire` (list-reversible) |

**When armed: destructive via env/legacy requires the flag; disruptive via env/legacy
proceeds but renders its resolution provenance in output** (a wrong-home kill is loud where a
wrong-home clean would have been fatal); ordinary flows. Lookup-hit resolutions are exempt
from both — membership is affirmative evidence. Guard grounded on the EFFECT, not on caller
configuration.

**The supervisor tier is in scope (rb7 C-1 — v7 named it once, in passing):** `supervisor/`
is home-relative, claim seizure + HANDSHAKE overwrite/unlink are irreversible, and the
**successor class has the widest measured pre-claim window** (33.0–63.1s, 7 of 7 over 30s, vs
0.7s median for workers) while its task render carries **no `--fleet-home`** — so
`_render_successor_task` gains the same baked argv the hooks have, in slice (c). The
`handoff_boot_refusal` fail-open (`if not entries: return None`, its own docstring admits it)
is filed to the absence-keyed lane, not this spec.

Accepted residual, now MEASURED (wave-26 live drive, n=3, + two lenses read-only n=316/286,
agreeing): a hosted body's registry row holds `session_id=None` for **6.8–10.6s** (worker
class) after dispatch — during which, on an armed machine, it could spawn into the donor
fleet's home. Recoverable, evented, accepted. NOT accepted silently for the successor class:
its 33–63s window plus an unenumerated irreversible first act is exactly why the tier above
now covers it. The bound is **unbounded when `last_activity` is missing** — that shape joins
the absence-keyed lane.

**Arming — fails ARMED in every direction (rb6 CRITICAL-3 family, rs6 J-1/J-9):** armed when
the population holds ≥2 distinct homes counting valid AND unreadable; **an unreadable list, an
unreadable home, or any indeterminate population state arms** — indeterminacy never selects
the permissive branch. With a determinate population of <2: byte-identical to today
(baseline `12c6521`). **§4's unreadable-list sentence defers to this paragraph** — one
normative rule (destructive via env/legacy requires the flag; a lookup hit stays exempt);
rs7 C-4 measured v7's two statements disagreeing on the lookup-hit case, and this one wins.

**Shipped-defect slice condition (rb7 C-2, measured both interpreters):** argparse's subparser
namespace copy CLOBBERS a global-position `--fleet-home` when the verb also defines one —
`['--fleet-home','H','autoclean'] → None` today. The flag-promotion slice must either share
one parser object or reconcile the two dests explicitly, and its pin drives the exact
global-position invocation that silently dropped the flag.

**Hooks**: `--fleet-home` argv baked per-home (survived six rounds; both `--settings` sites).
**Statusline**: blob sid → same lookup; single-home short-circuit; words, exit 0; resolver
pure-function; capture experiment gates the slice. **Refusals print facts + the `fleet homes`
view, never a paste-ready command with a chosen home.**

## §6. `adopt` and the class predicate, deleted — record

v5's `adopt` died at round 5 (foreign husk-sweep ownership of the operator's manager session —
GATE-1; unshippable member-kind; ambiguity for existing members; claim-holder lockout; silent
retire-shadowing). v6's replacement — a hosted/interactive env-soundness split behind a
miss-refusal — died at round 6: the refusal refused the manager before the sound channel could
serve it, and the predicate it forced is undecidable (`claude attach` is a hosted session
driven interactively; `FLEET_WORKER` is unusable in both directions per the two-media model).
v7 serves every class with one order and tiers the guard by irreversibility. Anyone
re-proposing session registration answers GATE-1; anyone re-proposing a class predicate
answers MAJOR-10/C-5.

## §7. Test isolation pins

Unchanged from v6 (env fixture + homes-list path helper monkeypatch + real-list-untouched pin;
quiescent-home canary with loud skip, delete-if-never-quiescent; membership + fold pins;
writer contention pin; no-rewrite lint; rendered "not initialized") plus: the **destructive
tier pin** — armed machine, env-resolved `clean` refuses naming the flag; env-resolved `spawn`
proceeds; and the **arming indeterminacy pin** — unreadable list arms. The arming pin's <2
baseline comparison stays.

## §8. Legacy default exit criteria — unchanged from v6

(1) slice 0; (2) dogfood home moves out + listed, completion removes the legacy population
term; (3) plane-naming lint; (4) arming pin extended to sid-less class. Operator decision.

## §9. The marker, deleted — record (unchanged)

## Cross-fleet interference audit

| Surface | Status |
|---|---|
| `claude` session namespace | Shared; per-home default-deny ownership; nothing can add a foreign sid to a home's ownership evidence. |
| Daemon env | **Two-media model, structural** (Definitions): frozen donor env + per-session sid override. Sid trustworthy — CONFIRM-A closes the donation question in the safe direction (docketed gate updated with the receipt). Hosted bodies' other env vars are donor facts; fenced by hook argv, blob sid, the lookup, and the destructive tier. |
| Homes list | Search space, not authority; append-only + retirements, sequence fold; adapter atomic append; tolerant decode; unreadable ⇒ arms. |
| Cross-home READS | `read_registry_at` (to be built to the driven tolerant contract — rs6 C-4): lock-free, write-free, quarantine-free, pinned. Cross-home writes: none. |
| Statusline settings entry | Unchanged. |
| Plugin/skill | Pull-only (D7); ritual gains the install-vs-home split for step-1/step-3 reads. |
| `fleet.lock`, registry, mailbox, claims | Home-relative; N single-writer domains; F26/M25 refusal transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; tenth UNBUILT/M-F-owned, untouched)

1 daemonless — preserved. 2 exit-0 hooks — preserved. 6 single-writer — preserved per home;
lockless list append-only with lint; no cross-home writes. 7 one-live-per-name — preserved.
8 adapter-only OS branching — list rides `atomic_append_bytes`; path semantics via wrapped
`samefile`; grammar the spec's own. 9 one-state-many-views — preserved.

## Graveyard check

§4 corpse paragraph; §6 and §9 are in-document graveyard entries. No sniffing: a registry hit
is a fact dispatch wrote under a lock.

## M2 — read-only federation view (demand-gated, NOT M1)

## Open questions

1. **WSL/Windows dual-view** — two runtimes, two lists = two machines; out of M1; docketed.
2. **`knowledge/` for non-repo homes** — scaffolded plain; accepted for M1.
(The sid-donation question is closed — CONFIRM-A — and removed from this list.)

## Sequencing — with failure outcomes (rs7 C-5: v7's arrows had none)

1. **Seven gate rounds are COMPLETE** (v1→v8; reports enumerated in the Status line). Rounds
   6 and 7 killed enumeration mechanics and DISCOVERED two shipped defects, while every
   architectural element has held since round 5 and three contested folds were vindicated by
   later rounds' failed attacks. **The gate's terminus is the operator, not a lens loop that
   structurally always returns findings** — v8 goes to the docket as-is. Failure outcome: if
   the operator orders a round 8, its verdict routes back here; if the operator rejects the
   architecture, the record above is the map of what was tried.
2. **Operator docket entry (BLOCKING for step 3)** — carries the spec, the two accepted
   residuals (pre-claim window 6.8–10.6s worker / 33–63s successor, dual-adopt-era ambiguity
   costs), the destructive/disruptive table, §8's criteria, WSL out-of-scope,
   `fix/b6-interface-release` ratification, and the CONFIRM-A identity-gate update. **No
   build slice dispatches before the operator rules.** The §8 exit is a second, later
   operator decision, separately blocking for the retirement it governs.
3. Build slices, disjoint, flag in/before arming, each RED-then-GREEN both floors serially,
   any slice failing its gate returns here rather than proceeding: (0) split;
   (a) `read_registry_at` + list + lookup + arming + verb-effect table + `fleet homes` +
   global flag (with the rb7 C-2 argparse pin); (b) `init --home`; (c) hook argv + witness +
   `_render_successor_task` argv; (d) statusline (capture-gated); (e) pins.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
verb-effect table's rows are drafted against wave-26-era shipped verbs — the lint against
effect sites is what keeps it honest as verbs are added; the successor-window numbers are
n=7 from one machine's history plus one live n=3 drive; and the "views render `[fleet]: no
home`" terminus assumes every view has a render path that reaches the resolver's answer —
the compact status table and the statusline do, `fleet result`'s error path is unchecked.
