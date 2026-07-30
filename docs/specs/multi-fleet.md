# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v6 (2026-07-30, interface tier). History: v1 → RESTRUCTURE; v2 → RESTRUCTURE
(marker deleted, §9); v3 registry-lookup core; round 3 held the core; round 4 (2 GATING) →
v5; round 5 (`mf-rb5` break / `mf-rs5` soundness, both GATING): **converged on §6 `adopt` as
the failure locus** — and vindicated v5's most contested fold (rb5 attempted the stale-identity
attack the withdrawn forensic arm supposedly enabled and **could not build it**, four reasons
checked against shipped code). v6 therefore **deletes `adopt`** (§6 is now a record, like §9)
and simplifies membership again. Reports: `state/journals/mf-r{b,s}{,2,3}.md`, `mf-rb4.md`,
`mf-rb5.md`, `mf-rs5.md`. GATE THEN BUILD: round-6 gate before the operator docket. Code
references by symbol.

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
per session, per repo, or per directory — instead of exactly one. Today there is one fleet
because `FLEET_HOME` is **two variables wearing one name**: the *data plane* (the home) and the
*install locator* that finds hook scripts, `fleet.py`, the statusline and the worker-settings
template. Measured at round 1 and re-driven since: a data-only home yields four dead hooks,
silently, because hooks exit 0. **The split is the work.**

Incident receipt for the coupling: 2026-07-29T22:58:39Z — fleet code run from inside the repo
with no `FLEET_HOME` set overwrote the real `state/fleet.json` + `supervisor/INCARNATION` with
fixture data (quarantine: `state/*.testpollution.20260729T225839Z`). Isolation pins are §7.

## Definitions

- **Install** — the code plane. `INSTALL_ROOT = Path(__file__).resolve().parent.parent`, never
  overridable. A plugin-cache copy is structurally indistinguishable from an install
  (measured); what governs is §4 membership.
- **Home** — one fleet's soul and state. Install == home stays legal forever.
- **Hosted vs interactive, load-bearing:** a *daemon-hosted* session (`--bg`) receives the
  daemon's substituted environment — its env is evidence about the daemon's first dispatch,
  not about itself (docketed substitution model). An *interactive* session's environment is
  its own: donation is a **daemon** property, and no measurement in five gate rounds has shown
  an interactive session with a substituted env. This split is what lets each caller class
  have a sound channel without `adopt` (§5, §6).
- The four worker hooks each carry a standalone `_fleet_home()` (quadruplicated; one copy
  diverges). Slice 0 unifies them plus the statusline's import-time conflation.
- **Home-path comparison**: filesystem identity (`samefile`) when both exist, exception-wrapped
  — never allowed to raise out of resolution; `normcase(resolve())` string fallback for
  nonexistent paths, named in refusals that turn on it; identity values compared within one
  process only, never persisted (`st_dev` differs across floors — measured).

## M1 — scope

Not a flag. M1 = slice 0, the homes list, resolution, `init --home`, `fleet homes`
(view + `--add`/`--retire`), pins. Excluded: federation views, cross-home operations (§10) —
and with `adopt` gone, **the design contains zero cross-home writes**. Build reality: no
shipped registry reader takes a path — slice (a) contains `read_registry_at(home)` (driven
through 12 corruption shapes at round 3: zero quarantines, zero raises).

**Sequencing constraint, binding (both round-5 lenses independently):** the global
`--fleet-home` flag ships **in or before the slice that ships arming** — arming is what makes
the flag mandatory, so a slice order that arms first strands every refusal it mints. Flag
before arming, not merely "flag before adopt".

### Slice 0 — the install/home split

Re-point the install-locator sites at `INSTALL_ROOT` — by symbol: `template_settings_path`,
`statusline_script_path`, the lifecycle-steer render, the two doctor hook-smoke checks,
`_render_sup_spawn_task`, `_render_successor_task`, the `render_worker_settings_template` call,
and the template's hook-command placeholder (`{{FLEET_INSTALL}}/bin/hooks/...`). The doctor
legacy-settings check is home-plane — NOT re-pointed. Re-grep `FLEET_HOME /` before touching
anything.

## §4. The homes list

`~/.claude/fleet-homes.list`. **Append-only, forever** — the file lives outside every home, no
`fleet.lock` can serialize a rewrite (the rewrite reading was measured at 95–100% loss under
contention), and a no-rewrite lint pins it. Records, one per line: a home path, or a
retirement `!<home path>`. **The fold is a sequence fold, last record wins per identity**
(stated because the set-difference reading makes retire-then-re-add unrecoverable — mf-rs5
MAJOR-6): `add A · retire A · add A` folds to member. Re-adding after retirement is
`fleet homes --add` (rb5 B2's re-list gap closes with the verb, not a special case).

**Writers**: `fleet init --home` (scaffold registers itself), `fleet homes --add <path>`
(validates initialized), `fleet homes --retire <path>` — never hooks, never dispatch, and with
`adopt` gone, never anything session-implicit. All appends via the adapter's
`atomic_append_bytes` (win32 `FILE_APPEND_DATA`; precedent `851e15f`, extended `a4f0079`),
newline-terminated; POSIX half `O_APPEND` single `write()`. **Read-side verify verifies the
FOLDED MEMBERSHIP, not the line** (a verify that greps its own line passes while a concurrent
retirement wins the fold — mf-rs5): after append, re-read, fold, assert the intended state.

**Read grammar**: decode tolerantly — `EF BB BF`, `FF FE`, `FE FF` honored; **no-BOM non-UTF-8
falls back to `mbcs` (Windows) / `latin-1` with a doctor NOTE naming the encoding** (an
ANSI-written non-ASCII path must not brick the list — the round-4 fix re-created its own
hazard one encoding over, mf-rs5 MAJOR-7); only truly undecodable refuses. Per line: strip,
skip empty; `!` prefix = retirement. A path line is valid iff (a) absolute by the spec's own
grammar — drive-letter root `X:\`/`X:/` or UNC `\\server\share` on Windows, leading `/` on
POSIX; never `os.path.isabs` (diverges between the declared floors — measured); (b) no `..`
segment; (c) naming an **initialized home** at read time (also retires torn-prefix lines).
Invalid lines never invalidate other lines.

**Why this is not the deleted corpse**: the corpse was an authority — a stale pointer would
redirect `clean`/`kill`. The list is a **search space**: a hit requires the caller's sid in
that home's registry (§5); a stale, wrong, duplicated or torn line can only miss, skip, or
refuse. Unreadable file → refusal for sid-carrying mutating callers, never fall-through to env.

Honesty items: a second fleet-written file outside any home (`user_settings_path`'s "ONLY
file" docstring restated in the same slice); resolution performs cross-home registry READS
(lock-free, write-free, quarantine-free — pinned).

## §5. Resolution

**Sid-carrying callers**:

1. **`--fleet-home` flag** — global, applied in `main()` before dispatch (**to be built**;
   `autoclean`-only today). Validation: resolve, `is_dir`, initialized; refusal otherwise; no
   code path may `mkdir` into an uninitialized target. Flag/lookup disagreement → mutating
   verbs refuse without `--yes` + witness line.
2. **sid→home lookup.** Population: listed homes (post-fold) ∪ the legacy install-root home
   **while §8 lives — §8's completion removes the legacy term** (v5's "regardless of listing"
   left a migrated single-fleet machine permanently armed — rb5 B4). Per home, ONE lock-free
   snapshot via `read_registry_at`, tri-state: hit / miss / unreadable. **Membership in a home
   is a home-level concept this spec defines** (rs5 correction: shipped `_record_sids` is
   per-record; no home-level union previously existed and this section stops implying one):
   the union over that home's registry records of each record's `_record_sids`-style identity
   (current `session_id` ∪ `retired_sids`). **No `INCARNATION` term** — v5 added one to a
   concept whose shipped form deliberately refuses to trust `INCARNATION`, and it is
   redundant: every supervisor body has a `sup|…|boot` registry row, so its sid is in the
   union already. `spawned_by` never grants membership (pinned). Exactly one member-home →
   resolved. Two+ → refusal naming all. Miss everywhere → mutating verbs refuse (naming
   unreadable homes); reads fall through to (3) with provenance rendered.
3. **Validated env → legacy default.** `FLEET_HOME` must resolve to an initialized home. For an
   **interactive** caller this channel is sound (Definitions: donation is a daemon property).
   For a **hosted** caller it is fall-through only, and when armed, destructive verbs resolved
   via env require the flag. A hosted session outside every registry (someone's manual
   `claude --bg`) gets miss → refusal → flag: explicit, correct, rare.
4. **TOCTOU**: mutating verbs re-assert caller sid ∈ that home's membership after taking its
   `fleet.lock`.

**Sid-less callers**: flag → validated env → install-root legacy default (§8).

**The manager tier needs no registration** (this is what replaced `adopt`): an interactive
manager resolves by env/flag — its env is its own; a *dispatched* supervisor has a registry
row. The class `adopt` existed to serve — a daemon-hosted manager with no row — is the manual
`claude --bg` case above, served explicitly by the flag. (§6 records why `adopt` died.)

**Hooks**: `--fleet-home` argv baked per-home into rendered worker-settings (survived five
rounds; both `--settings` construction sites — `dispatch_bg`, `cmd_sup_handoff_begin`).
Argv/env disagreement: argv wins, one witness line; env-absent normal and silent.

**Statusline**: sid from the vendor stdin blob, same lookup; words, exit 0, never quarantines;
resolver pure-function under test; blob schema unverified — capture experiment gates the
slice. **Cost bound (rb5 B5):** the statusline refires per assistant message, so: population
of one (post-fold, the overwhelmingly common machine) short-circuits with **zero** foreign
registry reads; multi-home machines pay one lock-free JSON read per listed home per refresh,
N small by construction — stated as an accepted cost, and the fold itself is O(lines) over a
file two verbs append to.

**Arming — fails ARMED**: multi-fleet behavior activates per invocation when the population
holds ≥2 distinct homes that are valid **or unreadable** (a transient exclusive handle must
not disarm the flag requirement mid-window — measured round 4). Distinctness per Definitions.
With <2: byte-identical to today (baseline captured at `12c6521`).

**Refusals print facts and the `fleet homes` view — never a paste-ready command with a chosen
home.**

## §6. `adopt`, deleted — record

v5's `fleet adopt` died at round 5 with both lenses converging on it independently: (rs5
GATE-1, CRITICAL) its `adopted` event made the adopter's sid husk-sweep-**owned** by the
foreign home, so a fleet the operator merely adopted could `claude rm` the operator's own
manager session — and `adopt --remove` stripped the only protection; (rs5 GATE-2)
`kind: "member"` is not a shipped registry concept — `data["workers"]` is one undiscriminated
namespace every sweeper and renderer iterates, so "registry-native, no worker semantics" was
unachievable as written; (rs5 GATE-3) for any session already a member somewhere, adopt
manufactures permanent ambiguity; (rb5 B1) writing the adopter into the target's registry
makes it a *worker turn* in that home under shipped `_require_claim_holder`/`cmd_sup_boot`
rules, so an adopter could never again hold that home's claim — the "authority-neutral by
equivalence" claim was false in every slice order; (rb5 B2) adopt-after-retire silently
reported success against a permanently retired list line. The need it served is dissolved by
the Definitions' hosted/interactive split — see §5's manager paragraph. Anyone re-proposing a
session-registration verb answers GATE-1 first: **membership records that feed the husk sweep
are ownership grants, and ownership of a manager session must never be grantable to a foreign
fleet.**

## §7. Test isolation pins

- Autouse conftest fixture exports `FLEET_HOME=<tmp>` (subprocess-inheriting), function-scope
  override available.
- **The homes-list path helper is monkeypatched by the same autouse fixture** + a pin asserts
  the real `~/.claude/fleet-homes.list` is untouched across a full suite run (the 2026-07-09
  incident class).
- Founding-incident guard: canary armed only against **quiescent** homes, loud skip otherwise;
  the list pin and env fence carry live-home protection. RED first, in a quiescent fixture
  home. If the dogfood home is never quiescent in practice, delete the canary and say the list
  pin is the fence — a permanent skip is worse than an honest absence.
- The §5.2 membership pin: union membership + the `spawned_by` exclusion + **fold semantics**
  (add·retire·add = member), driven through a real fork-steer restamp window, asserting
  member-no-flap.
- The arming pin: 2 valid → refusal fires; 1 valid + 1 unreadable → still armed; <2 →
  byte-identical to baseline.
- The §4 writer pin: N concurrent appenders, zero lost homes; the no-rewrite lint; and a
  fold-order pin (interleaved add/retire from two appenders converges to last-record-wins).
- "Not initialized" is a rendered word on every read surface; no verb `mkdir`s into a
  non-home.

## §8. The legacy default's exit criteria

Kept in M1; removable when ALL of: (1) slice 0 done; (2) the dogfood home physically moves out
of the install **and is listed** — completion **removes the legacy term from the §5
population** (a migrated single-fleet machine must end at population 1, unarmed; v5's
permanent legacy term armed it forever — rb5 B4); (3) the plane-naming lint passes; (4) the
arming pin extended to the sid-less class. Operator decision against these criteria.

## §9. The marker, deleted — record

v2's `.fleet-home` marker + walk-up died at round 2 on four demonstrated findings (invalid in
the dogfood config by its own rules; "enclosing git root" = two designs disagreeing on
all-but-one checkout, with the git-correct reading making parent markers unreachable; stale
markers served cross-fleet; untracked files planted in ~69 project trees). Anyone re-proposing
a marker answers those first.

## Cross-fleet interference audit

| Surface | Status |
|---|---|
| `claude` session namespace | Shared; husk-sweep ownership per-home, default-deny — and with `adopt` gone, **nothing can ever add a foreign sid to a home's ownership evidence**; doctor fleet-unknown stays NOTE-only + "or another fleet's". |
| Daemon env donation | Substitution model (docketed). Hosted callers: registry lookup + hook argv + blob sid. Interactive callers: their env is their own. Inherited residual (sid-donation OPEN) ties to the docketed identity gate; bounded as before. |
| Homes list | Fleet-written global file: search space, not authority; append-only + retirement records, sequence fold; adapter atomic append; tolerant decode incl. no-BOM fallback; three explicit writer verbs. |
| Cross-home READS | Resolution reads foreign registries (`read_registry_at`: lock-free, write-free, quarantine-free — pinned). **Cross-home writes: none exist in the design.** |
| Statusline settings entry | Unchanged; `init --statusline` refuses to clobber foreign. |
| Plugin/skill | Pull-only (D7). Ritual gains the install-vs-home split for step-1/step-3 reads; no adopt step (deleted). |
| `fleet.lock`, registry, mailbox, claims | Home-relative; N single-writer domains. F26/M25 refusal transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; the tenth UNBUILT/M-F-owned, untouched)

1. **daemonless** — preserved. 2. **exit-0 hooks** — preserved. 6. **single-writer registry**
— preserved per home; the lockless list is append-only by rule with a lint; **no cross-home
write exists**. 7. **one live session per name** — preserved per home. 8. **platform-adapter-
only OS branching** — list writes ride `atomic_append_bytes`; path semantics via wrapped
`samefile`; absolute-path grammar is the spec's own. 9. **one-state-many-views** — preserved.

## Graveyard check

§4's corpse paragraph; §6 and §9 are this spec's own graveyard entries, kept in-document so
the next proposer answers the recorded kills. Corpse 10 "brittle sniffing": a registry hit is
a fact dispatch wrote under a lock.

## M2 — read-only federation view (demand-gated, NOT M1)

`fleet status --all-fleets` over the same list, views only.

## Open questions

1. **Sid-donation residual** — closes with the docketed identity ruling.
2. **WSL/Windows dual-view** — two runtimes, two lists = two machines sharing homes; out of
   M1; named in the docket.
3. **`knowledge/` for non-repo homes** — scaffolded plain; accepted for M1.

## Sequencing

1. v6 → **round-6 gate**: fresh dual lens, all TEN prior reports fenced by name. Priority:
   the Definitions' hosted/interactive env-soundness claim (is there ANY measured path to a
   substituted env in an interactive session?); the sequence-fold under interleaved
   append/retire from concurrent writers; the §5 manager paragraph's coverage (what caller
   class, if any, is left with neither row nor sound env nor flag?); the statusline
   single-home short-circuit's correctness when the fold and the legacy term disagree.
2. Fold → **operator docket entry**.
3. Build slices, disjoint, **flag lands in or before the arming slice**: (0) split;
   (a) `read_registry_at` + list + lookup + arming + `fleet homes --add/--retire` + global
   flag; (b) `init --home`; (c) hook argv + witness; (d) statusline (gated on capture
   experiment); (e) pins. RED-then-GREEN, both floors, serially.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
"no measured substituted env in an interactive session" claim is absence-of-evidence and round
6 should attack it directly; the fold's last-record-wins needs its concurrency story told
against `atomic_append_bytes` interleaving (two appenders' records land in SOME total order —
the fold is deterministic per file state, but the verify-then-act window is not); and the §5
manager paragraph quietly assumes the interface session never runs under `--bg`, which is true
of every observed body but is a deployment convention, not a mechanism.
