# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v7 (2026-07-30, interface tier). History: v1→v2 RESTRUCTUREs (marker, §9);
v3 registry-lookup core (held ever since); v4–v5 mechanics; v6 deleted `adopt` (§6); round 6
(`mf-rb6`/`mf-rs6`, both GATING, convergent): **the miss-refusal refused the manager class the
deletion was supposed to serve, and the hosted/interactive predicate it forced is not decidable
by the resolver** (rb6 C-1/C-2, rs6 C-1/C-5). v7 removes both: no miss-refusal, no runtime
class predicate — **the guard tiers on irreversibility instead**. Round 6 also delivered
CONFIRM-A: the sid-donation question is CLOSED in the safe direction by counting, so the core
lookup is *sounder* than v6 claimed. Reports: `state/journals/mf-r{b,s}{,2,3}.md`, `mf-rb4.md`,
`mf-rs4.md`, `mf-r{b,s}5.md`, `mf-r{b,s}6.md`. GATE THEN BUILD: round-7 gate before the
operator docket. Code references by symbol.

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
   — which is exactly why step 4's tier exists instead of a class predicate.
4. **Legacy install-root default** (until §8).

**The destructive tier (replaces both the miss-refusal and the class predicate; discharges
mfgate-read N4):** verbs are *destructive* when their effect is not recoverable by a respawn
or a re-run — `kill`, `clean`, `archive`, `autoclean` (tier 2+), `respawn --force`; the spec
enumerates and a lint keeps the list exhaustive against `_confirm_destructive` call sites.
**When armed, a destructive verb whose home resolved via env or legacy requires the flag.**
Ordinary mutations (`spawn`, `send`, bare `respawn`, `init`) proceed on env — a wrong-home
spawn is recoverable and visible; a wrong-home clean is neither. Guard grounded on the
EFFECT, not on caller configuration — the standard three council rulings in this repo's
gates already demand. Accepted residual, stated: on an armed machine, a hosted body in the
pre-claim window could spawn into the donor fleet's home until its row lands; the window is
seconds, the effect is recoverable and evented, and closing it costs the predicate round 6
proved undecidable.

**Arming — fails ARMED in every direction (rb6 CRITICAL-3 family, rs6 J-1/J-9):** armed when
the population holds ≥2 distinct homes counting valid AND unreadable; **an unreadable list, an
unreadable home, or any indeterminate population state arms** — indeterminacy never selects
the permissive branch. With a determinate population of <2: byte-identical to today
(baseline `12c6521`).

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

## Sequencing

1. v7 → **round-7 gate**: fresh dual lens, all twelve prior reports fenced by file name.
   Priority: the destructive tier's enumeration (is any irreversible verb outside the list?
   is `send` to a wrong home truly recoverable?); the pre-claim-window residual's real width
   (drive a dispatch and measure seconds-to-row); arming's indeterminacy clause against a
   population that is *empty because the list is unreadable AND legacy is retired* (post-§8
   state); and the two-media model's counting argument (find a fifth body that breaks it).
2. Fold → **operator docket entry** (also carries: `fix/b6-interface-release` ratification,
   the CONFIRM-A update to the identity gate, WSL scoping).
3. Build slices, disjoint, flag in/before arming: (0) split; (a) `read_registry_at` + list +
   lookup + arming + destructive tier + `fleet homes` + global flag; (b) `init --home`;
   (c) hook argv + witness; (d) statusline (capture-gated); (e) pins.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
destructive-verb enumeration is drafted from memory of `_confirm_destructive` call sites and
the lint is what makes it honest — grep before build; "the window is seconds" in the §5
residual is asserted, not measured (round 7 is asked to measure it); and the claim that
ordinary wrong-home mutations are "visible and evented" assumes the wrong home's operator
reads their own events — true of fleets with supervisors, vacuous for an abandoned home.
