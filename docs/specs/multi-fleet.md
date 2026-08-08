# Multi-fleet: independent fleets scoped per session, per repo, or per dir

**Status:** **v8 — ratified ready-for-build by Altai 2026-07-30** (in-session, docket pass;
docket entry ticked in `docs/OPERATOR-GATES.md` §Settled, *"Multi-fleet spec v8 — ratify
ready-for-build, order round 8, or overturn?"*). The ruling, verbatim: *"**RATIFIED
ready-for-build.** What was ratified: the §5 resolution order + verb-effect table; the two
accepted residuals (pre-claim window 6.8–63s; wrong-home disruptive verbs proceed loudly rather
than refuse); §8's four exit criteria for the legacy default stay a second, later decision; WSL
dual-view out of scope for M1; build slices 0/a–e with the round-7 defect pins (the
silently-dropped `['--fleet-home','H','autoclean']` flag; `doctor --repair` absent from every
destructive enumeration) as slice conditions. Build starts at Sequencing §3 slice 0
(install/home split). The gate loop's non-termination was accepted as the reason the operator is
the terminus — no round 8."* The author never promoted this spec; the ratification is the
operator's act and this status line is a transcription of it, not a promotion. History: v1→v2
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

**BUILT 2026-07-31** (`INSTALL_ROOT`, `tests/test_install_home_split.py`). The symbol list
was accurate and complete: re-grepped, all eight sites existed as named, "the two doctor
hook-smoke checks" were exactly two, and the legacy-settings check was correctly left alone.
The count is now pinned by derivation rather than by list — `test_no_bin_path_is_still_
resolved_from_the_home` fails on any surviving `FLEET_HOME / "bin"`. Four measured
disagreements with this section, none of them changing what was ratified:

1. **"four dead hooks" is exactly right, and it undercounts the damage.** Derived from the
   template (4 declared hook commands, 4 rooted at the home) and driven against a data-only
   home: all 4 dead — `posttooluse_mailbox`, `stop_outcome`, `stop_mailbox`,
   `postcompact_journal`. The statusline dies the same way; this section already names it
   separately, so the arithmetic is consistent, but "four" is the hook count and not the
   casualty count.
2. **The four hooks are NOT textually unified, deliberately.** This section says slice 0
   "unifies them". `bin/hooks/stop_outcome.py`'s own module docstring records the opposite as
   established doctrine — *"Standalone, stdlib only. Never imports bin/fleet.py — duplicates
   its own tiny helpers (`_fleet_home`, `_log_hook_error`, `_resolve_name`) per the
   established pattern"* — so collapsing them means the first cross-module import in a plane
   whose invariant is exit-0 hooks, to save nine lines. Built instead as **behavioural**
   unification: the four are driven and required to agree with each other *and with
   `fleet.py`'s own resolution*, which a shared hook module would not have covered. Their
   `__file__` fallback still derives the home from the install; that is not fixable here —
   a hook learns its home only when the dispatch tells it, which is slice (c)'s baked argv.
3. **§7's test-isolation pins have no code-plane half, and the split needs one.** Pointing
   `template_settings_path()` at the install removed the sandbox those tests had for free
   from monkeypatching the home; the first full run **overwrote this repo's real, git-tracked
   `worker-settings.template.json` with `{}`** — the same class as the incident receipt at
   the top of this document, reached through the code plane instead of the data plane.
   `conftest.py` gains an `INSTALL_ROOT` redirect (same shape as the home's, so later
   install-plane paths land in it by default) plus a session-scoped drift guard over the
   git-tracked code plane, with a seed. §7 should be read as owing this half.
4. **`{{FLEET_HOME}}` is kept as a legal placeholder alongside `{{FLEET_INSTALL}}`**, and
   `render_worker_settings_template` defaults its new `fleet_install` argument to the home.
   Not in this section, and it is what makes the legacy layout byte-identical rather than
   merely equivalent: every existing 3-argument caller and any out-of-tree template still
   written against `{{FLEET_HOME}}` renders exactly what it rendered before.

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

> **DIVERGENCE RECORD — steps 3 and 5 above describe behaviour the tree does not have.
> Measured 2026-08-06 against `39f84d0` (slice a2's landing commit), py 3.13 and py 3.10
> alike. This note RECORDS the divergence and deliberately does NOT close it:** closing it
> means choosing between the ratified text and the shipped resolver, and **that choice is the
> operator's**. The ratified sentences above are unedited and stay unedited — rewriting a
> record of a ratification to fix a lookup problem falsifies the record to save the index.
>
> The diverging sentences are cited **by step number and by their own words, never by line** —
> the lines move, and a line citation in a rolling document rots. Step 3 reads *"Validated env
> — `FLEET_HOME` resolving to an initialized home"*; step 5 fires *"pre-§8 when step 4 yields
> an uninitialized directory"*. Read together, pre-§8 the terminus is triggered by **step 4** —
> the legacy install root — being uninitialized, while an uninitialized **env** home is a
> step-3 failure, and a failed step falls to the next one.
>
> **What ships**, with `INSTALL_ROOT` initialized and `FLEET_HOME` naming an
> existing-but-uninitialized directory:
>
> | Layer / machine | Result |
> |---|---|
> | `resolve_home()` as a pure function | `step = None` — **the terminus**. Provenance: *"[fleet]: no home -- no flag, no membership, no initialized default"* |
> | through `main()`, **single-fleet** box (no homes list) | `_multi_fleet_population_is_live` is False, so the terminus is disarmed, `apply_resolved_home` returns `None`, and **dispatch proceeds into the uninitialized env home**: `fleet home` prints it, `fleet status` renders the table *and creates `state/` inside it*, and `fleet clean --yes` — a RATIFIED-DESTRUCTIVE verb — runs there to rc 0 |
> | through `main()`, **multi-fleet** box (list names one other home) | the terminus fires: `fleet status`/`fleet home` print `[fleet]: no home` at rc 0; `fleet init`/`fleet clean --yes` exit 1 naming the remedy |
> | **what steps 3–4 literally require** | fall 3→4 and resolve to the **initialized install root** — `step="legacy"` — and proceed there |
>
> **The text describes one behaviour and the tree has two, neither of them that one** — and
> which of the two an operator gets is decided by a gate §5 does not mention. (The `w45-ga2`
> verdict phrases this as *"the shipped tree does none of the three things the spec's text
> describes"*; re-measured, the count is one described behaviour against two shipped ones, so
> it is restated here rather than transcribed.)
>
> **1. Step 3's fall-through is unimplemented.** A named env home that fails validation
> terminates inside `resolve_home` rather than retargeting to step 4. What is absent is the
> FALL, not step 4: measured over four env shapes at this same commit, step 4 is alive and
> answers `step="legacy"` at the install root whenever the env var is unset, and an
> initialized env home answers `step="env"`. Only step 3's failure edge is missing.
>
> **2. Step 5's pre-§8 trigger is evaluated against the env-collapsed default, not against
> step 4's install root.** `FLEET_HOME` is computed once at import as *env if set, else the
> install root*, so steps 3 and 4 are collapsed into one value before `main()` runs, and step
> 5's *"step 4 yields an uninitialized directory"* is tested against that collapsed value.
> When the env var is set, the directory tested is the **env home**; the install root's own
> initialization is never consulted on that path.
>
> **3. The population gate makes the OBSERVABLE behaviour a THIRD thing, on every machine that
> exists today.** `_multi_fleet_population_is_live` gates terminus *enforcement* — not
> resolution, which runs identically either way — on the machine having a homes list with a
> member, or an unreadable one. On a single-fleet box it is False and the terminus is disarmed,
> which is the second row above. **The sentence a2 filed this deviation under — carried in
> `resolve_home`'s own docstring, so it ships — *"A NAMED HOME THAT FAILS VALIDATION TERMINATES
> HERE rather than retargeting"* — is therefore true of `resolve_home` and false of the shipped
> CLI on the machine every operator has today**, where such a home neither terminates nor
> retargets: it is acted in. That sentence is corrected here, in §5, rather than only in the
> journal it was written in, because §5 is where the next lane will look.
>
> **Why the divergence was nevertheless the right call, and why no code changed.** Implemented
> literally, step 3's fall-through means the operator names a home, the home has no registry
> yet, and fleet silently writes into the install root instead — the 2026-07-29T22:58:39Z
> incident recorded at the top of this document, reached through the mechanism this document
> was built to prevent. Refusing is the safe direction; a2 took it and reported it rather than
> editing this section from inside its own fence. **What was owed was the record, not a
> rewrite,** and this note is that record.
>
> **The cost of closing it is larger than the lane estimated, and that is measured.** a2 filed
> the faithful branch as *"one `elif` away"*. That is true of `resolve_home` and false of the
> CLI — the same shape as the sentence corrected in item 3. Measured by wrapping
> `resolve_home` so a terminus answer becomes `step="legacy"` at the install root (exactly what
> that `elif` would return) and then driving `apply_resolved_home`: **the verb still acts in
> the uninitialized env home**, because `apply_resolved_home` assigns `FLEET_HOME` only for
> steps 1 and 2 — *"this function moves the home only when something NAMED one"*, its own
> docstring — while steps 3 and 4 ARE the module global's import-time computation. The
> one-line change would ship a resolver whose provenance line names the install root while the
> verb writes into the env home. Closing this faithfully touches that assignment rule too.
>
> **THE OPEN CHOICE — the operator's, and this note does not take it.** Two ways to close the
> divergence, with the costs as measured here:
>
> * **A — narrow §5's text to match the shipped resolver:** say that a named env home which
>   fails validation terminates rather than falling through, and that pre-§8 the terminus is
>   triggered by the collapsed default rather than by step 4 specifically. Cost: one prose edit
>   in this section; no code, no test, no floor movement. On this one edge it also writes down
>   what §8's completion would make the only rule anyway — post-§8 there is no step 4, so a
>   failed step 3 terminates by step 5's own post-§8 clause, and what makes it a divergence
>   today is only that §8 has not completed. **A is incomplete unless it also records the
>   population gate**: narrowing the resolver's rule alone still leaves the second row — the
>   behaviour every operator actually has — undescribed by §5.
> * **B — change the resolver to match §5:** cost is the `elif`, **plus** a change to
>   `apply_resolved_home`'s steps-1-and-2-only assignment rule (above), **plus** re-opening the
>   incident route that the refusal closes, **plus** pins for both halves.
>
> ***Recommendation: A.*** B's behaviour is the one this document's own opening incident exists
> to prevent, and a spec that instructs the tree to reach it would be ratifying the failure it
> was written to close; A costs prose and loses nothing measured. **A recommendation is not a
> decision** — whichever is chosen, the population gate needs a sentence of its own in §5,
> because today it is the thing that decides which of two behaviours ships and §5 is silent on
> it.
>
> **Evidence, and why this note carries no fenced receipt.** Every row above was produced by a
> throwaway harness outside the repo — a tmp install root, a tmp env home, `homes_list_path`
> redirected — run against this commit's own tree on both interpreters, rather than
> transcribed from the gate report it discharges. It carries no fenced receipt block because
> inside its fence it could not: this document is listed by name in `tests/test_receipts.py`'s
> `UNENFORCED` set, and MEASURED, adding a single pin line to it moves the file into the
> enforced set — four tests RED and the suite's collection count 4014 → 4017 — which is
> dischargeable only by editing that test file. **Receipts here land with the trigger that
> exclusion names, and this note is not it.**

**The verb-effect table (replaces v7's one-line criterion, which did not generate its own
list — rs7 C-2 killed it on `kill`, this repo's own contract for which is respawn-recoverable):**
verbs classify by their **worst irreversible effect in the wrong home**, enumerated per verb:

| Class | Verbs | Wrong-home effect |
|---|---|---|
| **destructive** — destroys evidence or sessions; nothing recovers it | `clean` (journals, outcomes, records), `archive` + `autoclean` tier 2+/3 (`claude rm`, tombstone drop), `doctor --repair` (registry renamed aside — rb7 C-3; **[w47/e5 — operator ruling 2026-08-08, E5]** RE-GROUNDED ON THE RENAME: it renames the target home's `state/fleet.json` aside — destroying a file the operator may want to inspect — and no shipped verb un-renames it; the ground, its measurement and its one residual are stated below the table), `sup-handoff-abort` (stops a successor session), **[w42/mf5]** `sup-boot` (HANDSHAKE unlink + claim seizure), `sup-handoff-begin` (supersedes every unresolved handoff entry — an in-flight successor is left permanently unbootable), `sup-handoff-complete` (HANDSHAKE unlink + claim transfer), `sup-decision --clear` (removes the queued operator decision; no verb restores it), **[w43/s5 — operator ruling 2026-08-05]** `sup-spawn` (**the dispatch is the act** — E1: it dispatches a body that then boots and seizes the claim, which is the cheapest path to seizing a foreign fleet's claim; its own in-process effect set is narrower than that, so no static effect-site walk can see this and **this entry is hand-maintained**, an accepted cost ruled with it), `sup-checkpoint` and `sup-release` (E2: **an irreversible append IS an irreversible effect** — both append to the home-relative append-only `supervisor/JOURNAL.md`, which no shipped verb removes an entry from, so a wrong-home append permanently contaminates a foreign fleet's record; the bound on which appends count is stated below the table), **[w47/homes — operator ruling 2026-08-08, E2/homes]** `homes --add` and `homes --retire` (**an irreversible append IS an irreversible effect**, the same E2 ground: both append to the machine-global `~/.claude/fleet-homes.list`, which only the FOLD reverses and no verb un-appends; the READ is not here and stays ordinary as the residual — the split, its grant ground and its shape are stated below the table), any future verb whose implementation calls `claude rm`, deletes evidence files, or renames registry/claim state — **the lint keys on those effect sites** (`claude rm` invocations, unlink/rename of `state/`/`supervisor/`/`logs/` paths), NOT on `_confirm_destructive`, which is an ownership guard whose call sites neither contain nor are contained by this list (rs7 C-3 measured the disjointness) |
| **disruptive** — recoverable but harms a live foreign fleet | `kill`, `interrupt`, `send`, `respawn` (all forms), `release`; **[w42/mf5]** `resume-limited`, `sup-heartbeat` |
| **ordinary** | `spawn`, `init`, `status`/`peek`/`result`/views, **[w47/homes — operator ruling 2026-08-08, E2/homes: SUPERSEDED IN PLACE, not deleted — this row read "homes --add/--retire (list-reversible)" and the ruling overturned it; the two writes are DESTRUCTIVE above, and the bare read is ordinary by RESIDUAL, stated below the table. The verb name is deliberately left unbackticked here: the row readers in tests/test_round7_defect_pins.py resolve backticked tokens to verbs, and a backticked "homes" in two rows is exactly the partition breach test_no_verb_IS_NAMED_BY_TWO_spec_rows forbids]**; **[w42/mf5]** `home`, `knowledge`, `attach`, `wait`, `sup-status`, `sup-context`, `q`, `index` (all four leaves) |

**When armed: destructive via env/legacy requires the flag; disruptive via env/legacy
proceeds but renders its resolution provenance in output** (a wrong-home kill is loud where a
wrong-home clean would have been fatal); ordinary flows. Lookup-hit resolutions are exempt
from both — membership is affirmative evidence. Guard grounded on the EFFECT, not on caller
configuration.

**Table completion — measured, `w42/mf5`, at `f457a57`, both interpreters.** The rows above
named 15 verbs; `build_parser()` exposes **32 top-level subparsers** (derived by introspecting
the parser tree for `_SubParsersAction` choices, not by grepping `add_parser(`; 32 distinct
parser objects, no aliases). The 14 additions tagged **[w42/mf5]** are *derivations* from the
criterion already stated here, not new rule: each rests on a transitive effect-site walk (BFS
to fixpoint from the verb's `cmd_*` entry, no depth limit) and is licensed either by
set-equality with an already-classified row or by the effects this section's supervisor
paragraph already calls irreversible. Three verbs (`sup-spawn`, `sup-checkpoint`,
`sup-release`) were deliberately **left unclassified** by that branch — the operator ruled all
three on 2026-08-05 and they are now carried in the destructive row above; the proposal block
below is kept as the record of the questions, marked with its answers. Two
counts in the census are worth carrying: the parser tree holds **36** subparser choices, not
32, because `index` nests `init|build|update|status` (35 dispatchable leaves), and `cmd_index_init`
is the only command that creates `.fleet-index/`; and `fleet home` (prints the
resolved home) is a **different verb** from `fleet homes` (§4's list manager).

> **CENSUS RE-MEASURED at the landing tree, 2026-08-05 (`w43/s5`), both interpreters — every
> number above is stale by exactly one, and one clause of it was false.** The paragraph's
> counts are TRUE OF ITS OWN PIN and are left standing: driven against `build_parser()`
> materialised at `f457a57`, the census is exactly **32** top-level subparsers / **36** total
> choices / **35** dispatchable leaves, and `homes` does not exist there. Driven against the
> tree this landed on, it is **33 / 37 / 36** — slice a1 built `fleet homes` on 2026-08-05 and
> moved all three by one. **The clause that had to change rather than be footnoted** was
> *"`fleet homes` (unbuilt, §4's list manager), so the ordinary row's `homes --add/--retire`
> classifies nothing that ships today"*: a claim about **today** is a claim about the current
> tree, and it is false of it — `homes` ships, and the ordinary row classifies a live verb.
> The counts are claims about a named commit and stay; that split is the 2026-08-05 `:337`
> ruling (*a reference is only rot when it is a claim about the CURRENT tree*) applied here.
> Consequence for the 14/15 and 10/15 reproduction figures below: they were derived over the
> 32-verb tree and are not re-derived here; treat them as pinned to `f457a57` too.

Applying the criterion mechanically over the call graph reproduces only **10 of the existing
15 rows**. It reproduces **14 of 15** once four exclusions are applied, and each exclusion is
forced by a ratified row rather than chosen: **X1** the verb's own scaffolding (its `fleet_lock`
file, the tmp half of an atomic write) — else ratified-ordinary `status`/`spawn`/`init` are
destructive; **X2** the corruption-conditional `_quarantine_registry` rename — else
ratified-ordinary `status` is destructive; **X3** rollback of the verb's own write
(`restore_brief`, whose `unlink` arm fires only when the pre-image was absent) — else
ratified-disruptive `respawn` is destructive; **X4** `claude rm` of a session the verb itself
just created (`dispatch_bg`'s wedged-dispatch cleanup) — else ratified-ordinary `spawn` is
destructive. The fifteenth row does not reproduce under any of them; that is E5 below.

**Set-equality alone does not decide a class — the separating ground (operator ruling
2026-08-05, B3; MEASURED by the `w43-gmf5` gate and reproduced at the landing tree).** An
adversarial re-measurement found that `wait`, `status` and `release` have **byte-identical**
effect-site sets (9 sites each, transitive BFS to fixpoint, raw sites before any exclusion) —
yet `status` is ratified **ordinary** and `release` is ratified **disruptive**. Set-equality
therefore selects two classes at once and cannot pick one, and it does so on rows that predate
this table's completion, so the defect is in the ratified table itself and holds before X1–X4
are applied. **The ground that separates them, and the second discriminator of this criterion:
`wait` persists only transitions it observed; `release` alters ownership.** Where two rows
share an effect set, the class is decided by whether the verb **alters ownership or authority
over another body's state** (disruptive or worse) or merely **records state it observed**
(ordinary). Under it `wait` is **ordinary**, which is where the table carries it. A verb whose
effect set matches an already-classified row must now be checked against this ground too — a
match alone is not a licence.

**The bound on E2: which appends count (operator ruling 2026-08-05, E2).** An irreversible
append is an irreversible effect, and the record it must land in is one **the spec corpus makes
append-only and from which no shipped verb removes an entry**. **The first conjunct is not
sourced by this document alone.** An earlier draft of this sentence said *"§4 makes append-only"*
and that was wrong in a way that mattered: §4 above is `The homes list` and sources the homes
list and nothing else, so read literally the bound admitted ONE record — and the record it
excluded is the one carrying the two promotions this same section lands. Each record's
append-only property is therefore cited below **where it is actually sourced, by section and
never by line** (the rolling-doc doctrine, `68dcba1`). MEASURED, **two** records satisfy the
test, and naming only the first would be an enumeration smaller than reality:

1. `supervisor/JOURNAL.md` — **append-only by `docs/SPEC.md` §12 (*Supervisor protocol*)**,
   which states it in those words: *"`supervisor/JOURNAL.md` (append-only, claim-holder-only)"*;
   corroborated by `docs/specs/three-tier-command.md` §3.5.3, which calls it *"the append-only
   `supervisor/JOURNAL.md`"* while listing what a successor boots from. **Not by §4 of this
   document, which does not mention it** — §4 governs the homes list only. Reached by exactly
   six verbs (`sup-boot`, `sup-checkpoint`, `sup-release`, and all three handoff verbs — reverse
   BFS over the call graph to `supervisor_journal_append`). Four were already destructive on
   removal grounds, so **E2 moves exactly two**, and E3 collapses into it.
2. `~/.claude/fleet-homes.list` — **append-only by §4 of THIS document** (*"Append-only
   forever"*), whose **retirement is itself an append** (`!<home path>`), so only the FOLD is
   reversible and no entry is ever removed. Measured at this section's landing tree
   (`bd93691`), at function granularity: one reader function (`read_homes_list`) and one writer
   function (`append_home_record`, two call sites, both in `cmd_homes`), plus a shipped lint
   forbidding truncate/unlink/rename in any scope naming `homes_list_path`. **That is a count of
   functions, not of verbs, and it is deliberately narrower than §4's own writer list** — §4
   names three writers (`fleet init --home`, `fleet homes --add`, `fleet homes --retire`) and
   `fleet init --home` does not write the list at this tree (measured: `cmd_init` neither calls
   `append_home_record` nor names `homes_list_path`). When that writer is built the function
   count moves and this enumeration must be re-measured; it is unpinned prose, so nothing will
   catch it. **Its writer is
   `homes --add/--retire`, which the RATIFIED ordinary row calls *ordinary (list-reversible)* —
   so the ground and that row disagree, and THIS LANDING DOES NOT RESOLVE IT.** The ratified row
   stands; the disagreement was opened the same day as its own operator docket item
   (*reclassify `homes` under the E2 ground, or keep the ratified ordinary row?*). Recorded here
   so the bound is not read as quietly exempting the second record — it does not.

**The bound is load-bearing, not tidiness:** read
without it, the ground reaches the outcome store — whose appending verbs are `kill`, `interrupt`
and `respawn`, all three ratified **disruptive** — and a ground that promotes three ratified
rows refutes the table it is required to reproduce. The outcome store is not that record
because a shipped verb removes from it, and the destructive row names the verb in its own
words: *"`clean` (journals, outcomes, records)"*. Same footing as X1–X4: **forced by a ratified
row rather than chosen.**

**The ground for `doctor --repair` (operator ruling 2026-08-08, E5; MEASURED at `5a320f1`,
`py -3.13` and `py -3.10`, byte-identical output).** The row's original reason — *"registry
renamed aside — rb7 C-3"* — stands above unedited; this is the append that re-grounds it, and
the defect it repairs is that the reason named an effect `load_registry` produces for many
verbs and therefore did not generate the row it justified. **The re-grounded reason is the
rename read as an ACT rather than as a reachable effect: `doctor --repair` renames the target
home's `state/fleet.json` aside, destroying a file the operator may want to inspect, and no
shipped verb un-renames it; `peek` only reads.** Same effect-grounded discriminator already
ratified for E1 (*the dispatch is the act*) and E2 (*an irreversible append IS an irreversible
effect*), so §5 stays internally consistent.

**Derived rather than asserted**, by AST over `bin/fleet.py` at the commit above — cited by
symbol and never by line, since that file is being moved by two other lanes in the same wave:

* `_quarantine_registry` has exactly **one** caller, `load_registry`, and it holds the module's
  only rename of the registry file. The only other writer of `state/fleet.json` is
  `save_registry`'s atomic tmp→dest replace, which writes fresh content and cannot restore an
  artifact.
* **18** `cmd_*` verbs reach `load_registry` transitively — the count E5's own question states,
  reproduced here rather than trusted.
* **`peek` is not one of the 18.** It calls `read_registry_no_repair`, and neither it nor its
  native half reaches the loader, so the rename does separate the two verbs the docket item
  named. That read-only half is not incidental: it is the views doctrine landed 2026-07-27
  (`docs/specs/terminal-surface.md` D4).
* `--repair` is declared on **exactly one** subparser, and it is the only branch of `cmd_doctor`
  that calls `load_registry`; the unflagged branch calls `read_registry_no_repair`. The flag is
  the whole discriminator — which is why the ratified row and both pin tuples carry the flagged
  spelling and not bare `doctor`.
* **Nothing un-renames.** Every filesystem-moving call site in the module was enumerated —
  `rename`/`replace`/`move`/`copy*`/`write_*`, plus the `os.*` and `shutil.*` spellings — and
  none takes a `state/fleet.json.corrupt.<ts>` artifact as its SOURCE; all twelve scopes that
  name the artifact glob perform zero moves. The way back is an operator restoring the file by
  hand, which `_identity_abstention_note` says to the operator in those words.

**The one residual, recorded rather than written around: the rename separates `doctor --repair`
from `peek`, and it does NOT separate it from `status`, `attach` and `wait`** — all three
ratified **ordinary**, all three among the 18. What keeps those three ordinary is **X2** above
(the corruption-conditional rename, excluded); what puts `doctor --repair` outside X2 is that
for it the rename is not scaffolding reached while loading but the act the operator asked for by
typing the flag. So this ground answers the docket item on its own terms and is **not by itself
generative** over the other seventeen — X2 is still doing that work, and a reader should
re-derive both rather than trust this paragraph.

**Two things this note deliberately does not do.** It does not touch the E5 bullet in the
PROPOSAL block below, which still reads *"E5 — NOT RULED … its own OPEN operator docket item"*
and is stale as of the ruling above; that bullet sits outside this lane's fence and is reported
to the operator rather than quietly fixed. And it carries **no fenced receipt**: this document is
listed by name in `tests/test_receipts.py`'s `UNENFORCED` set, so one `# at <sha>` line moves it
into the enforced set and turns that file's own staleness assertion RED — the trap the
DIVERGENCE RECORD above already measured. The derivation's transcripts live in the lane report.

**The `homes` split (operator ruling 2026-08-08, E2/homes; MEASURED at `e5889fe`, `py -3.13` and
`py -3.10`).** The ordinary row read *"`homes --add/--retire` (list-reversible)"*; that entry is
annotated as superseded in place above rather than deleted. The ruling: **split the verb —
reading `fleet homes` stays ORDINARY, `--add`/`--retire` become DESTRUCTIVE.** Two grounds, both
the operator's:

* **The E2 ground, already ratified.** `--add` irreversibly appends to the machine-global
  `~/.claude/fleet-homes.list`, and **only the FOLD reverses it** — a retirement record is
  another append, not a removal. That is *an irreversible append IS an irreversible effect*
  applied to the one list that is not home-relative, so a wrong-home append pollutes the
  MACHINE's record rather than one fleet's. The superseded reason, *"list-reversible"*, was
  reading the fold as if it undid the write.
* **The grant ground, which is the security half.** ORDINARY meant a read-only `/fleet:*` grant
  of `Bash(fleet homes)` **reached `--add`** — the same class as the 2026-07-09 kill/clean fix,
  where read-only slash commands could reach destructive verbs because the grant covered the
  whole CLI. Splitting closes that while keeping the read-only grant useful, which a
  whole-verb reclassification would not.

**The shape is `doctor --repair`'s, and that is load-bearing rather than stylistic.** The two
FLAGGED tokens are what the destructive row and both pin tuples carry; the bare verb is named by
no row, and its tier is declared in `fleet.VERB_EFFECT_RESIDUAL` — the same mechanism already
ratified for `doctor` and `sup-decision`. The alternative (bare `homes` left in the ordinary row,
flagged tokens added to the destructive one) resolves identically at runtime and is still wrong
twice: it puts one verb in **two rows**, which this section's own partition pins forbid because
*whichever row a reader finds first decides how it is guarded*; and it degrades **fail-open**,
since dropping the flagged tokens would send the writes back to ordinary — the hole this ruling
closed. In the residual shape the same slip leaves `homes` in no row at all, and an unclassified
verb is destructive.

**Derived rather than asserted**, by driving `build_parser()` at the commit above — cited by
symbol, never by line, since `bin/fleet.py` moved roughly 1500 lines this wave:

* `--add` and `--retire` declare **no `dest=` override**, so argparse's defaults (`add`,
  `retire`) are exactly what the table's mechanical `--x-y` → `x_y` rule produces. Neither needs
  a `VERB_EFFECT_RESIDUAL_FLAGS` entry, unlike `sup-decision --raise` (argparse maps it to
  `question`). Measured, not assumed — the two flags are `_StoreAction` with `default=None`.
* On the pre-ruling table `homes` was a **bare** token in the ordinary tuple, which yields
  `dest=None` — *"this tier applies however the verb is invoked"* — so **`fleet homes --add`
  classified `ordinary`**, which is precisely what the ruling forbids. That is the defect, driven
  through the real parser rather than a hand-built namespace.
* **`homes` is not in `TERMINUS_VIEW_VERBS`**, so there is no second surface repeating the
  `doctor --repair` shape here: it sits in the machine-level tuple whose own comment records that
  putting `homes` in the view tuple once made `fleet homes --add` print *"[fleet]: no home"* and
  exit 0 without appending.
* **The grant hole is PROSPECTIVE, not live.** No `commands/homes.md` ships, so no read-only
  slash command grants `Bash(fleet homes)` today. The two lint entries are what keep it shut when
  one lands, and bare `homes` is deliberately NOT among them — the lint asserts `fleet <verb>` is
  absent from the grant, so a bare entry would fail a future read-only command for granting the
  very read the operator ruled should stay useful.

**The one residual, recorded rather than written around: this ruling does not re-open the other
ordinary rows, and one of them is adjacent.** `init` is ratified **ordinary** and this section's
own homes-list commentary names *"`init --home`, slice b"* as a second writer of the same
machine-global list. If that slice ships an appending `init --home` while `init` is bare-ordinary,
the E2 ground reaches it exactly as it reached `--add` — the pre-ruling `homes` defect, one verb
over. **It is REPORTED, not fixed here**: slice b is unbuilt at this commit (`build_parser()`'s
`init` declares `--nonce`, `--statusline`, `--chain`, `--force`, and no `--home`), so there is no
shipped contradiction to repair, and reclassifying a ratified row is an operator edit, not a
lane's. A reader should re-derive this rather than trust the paragraph.

**Two things this note deliberately does not do**, both inherited from the E5 note above. It
carries **no fenced receipt** — this document is in `tests/test_receipts.py`'s `UNENFORCED` set
and one `# at <sha>` line moves it into the enforced set, four tests RED, which the DIVERGENCE
RECORD measured. And it states the verb contrast **below the table** rather than inside a row,
because the row readers resolve backticked tokens to verbs.

> **PROPOSAL — RULED 2026-08-05 by the operator (`docs/OPERATOR-GATES.md`, first settled
> entry). Kept as the record of the questions, never deleted; each carries its answer.**
> E1, E2 and E3 are ANSWERED and their consequences are landed in the table above. E4 is still
> live. E5 was split out as its own **open** docket item and outlives this landing.
>
> - **E1 — RULED: YES, the dispatch is the act; `sup-spawn` is DESTRUCTIVE.** The
>   hand-maintained lint entry is an accepted cost, ruled with it. Question as raised:
>   **`sup-spawn`: do out-of-process consequences count?** Its static effect set is a
>   strict subset of ratified-ordinary `spawn`'s, which reads *ordinary*. But it dispatches a
>   **supervisor body**, which then runs `sup-boot` and seizes the claim — the act whose
>   33.0–63.1s pre-claim window the accepted residual below is entirely about. Reading A
>   (in-process effects) gives ordinary; reading B (the dispatch is the irreversible act) gives
>   destructive. *Recommendation: **destructive*** — B is the reading the residual paragraph
>   already takes, and a wrong-home `sup-spawn` is the cheapest path to seizing a foreign
>   fleet's claim.
> - **E2 — RULED: YES, an irreversible append IS an irreversible effect.** A wrong-home append
>   pollutes a foreign fleet's append-only record permanently; over-guarding costs a prompt,
>   under-guarding corrupts history. Bounded as stated above the block. Question as raised:
>   **is an irreversible *append* an irreversible effect?** `sup-boot`, `sup-checkpoint`,
>   `sup-release` and all three handoff verbs append to `supervisor/JOURNAL.md`. Measured: the
>   seed write is guarded on non-existence, so nothing is clobbered — the append only adds, and
>   §4's append-only rule means **no shipped verb removes an entry**. The destructive row says
>   *"destroys evidence"*; an append destroys none, yet permanently contaminates a foreign
>   fleet's journal. The criterion is silent. *Recommendation: decide it either way, explicitly
>   — six verbs hang on it.*
> - **E3 — RULED by E2: both are DESTRUCTIVE.** It was E2 wearing two verb names and it fell
>   out mechanically, exactly as the gate predicted. Its sub-item did NOT fall out and is
>   carried forward as an open question: `sup-decision --raise`/`--answer` are still
>   unclassified at flag granularity, while the verb `sup-decision` is classified on the
>   strength of `--clear` alone. Question as raised: **`sup-checkpoint` and `sup-release` have
>   a derived floor of `disruptive` and a
>   ceiling open on E2.** Both do everything `sup-heartbeat` does (heartbeat stamp +
>   `write_incarnation`), so disruptive is derivable; both also append, so E2 could promote
>   them. Landing either class would assert an answer to E2, so neither is landed.
>   Sub-item: `sup-decision --raise`/`--answer` (as distinct from the derived `--clear`) write
>   foreign supervisor decision state and are also unclassified.
> - **E4 — the lint this section specifies would not match shipped code.** The row above says
>   the lint *"keys on those effect sites (`claude rm` invocations, …)"*. The **only** `claude
>   rm` in `bin/fleet.py` is reached through a **parameter-default alias**
>   (`run=subprocess.run`), this repo's test-injection idiom — invisible to the naive form of
>   that lint. Measured: a walker without parameter-default alias resolution returns **zero**
>   `claude rm` sites for the whole file while still passing four hand-planted destructive
>   mutants. The slice-(a) lint needs alias resolution over parameter defaults, or it ships
>   green and vacuous.
> - **E5 — RULED 2026-08-08: RE-GROUND IT ON THE RENAME.** `doctor --repair` renames the target
>   home's `state/fleet.json` aside — destroying a file the operator may want to inspect — and
>   no shipped verb un-renames it; `peek` only reads. Same effect-grounded discriminator as E1
>   and E2, so §5 stays internally consistent. The ground is landed on the destructive row and
>   derived against shipped code in *The ground for `doctor --repair`* above — including the one
>   thing it does NOT do. **Its earlier state is annotated, never deleted, because the record of
>   a question is the point of this block: NOT RULED at the 2026-08-05 landing, split out that
>   day as its own OPEN operator docket item** (*"how should that justification be restated?"*),
>   separable from any branch, with no work parked on it. It was untouched by that landing and
>   was not repaired there. A third horn the framing
>   below omits, MEASURED by the gate: the table also maps one identical effect set to two
>   different classes on `status`/`release` — rows that have nothing to do with X2 — which is
>   the defect the B3 ground above closes. Question as raised: **the destructive row's stated
>   reason for `doctor --repair` does not distinguish
>   `doctor --repair`.** The row justifies it as *"registry renamed aside"*, but the rename
>   lives in `load_registry`, whose sole caller relationship makes it reachable identically
>   from `status`, `attach`, `wait`, `kill`, `clean`, `archive` and 12 more — **18 verbs** in
>   total. Either X2 above is right and the row's *reason* is wrong, or X2 is wrong and 18
>   verbs are destructive. This is the defect class rs7 C-2 used to kill v7's one-line
>   criterion (*"it did not generate its own list"*), reappearing in v8's table.

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

> **CORRECTION — measured in slice 0, 2026-07-31, both interpreters. The word `today` is
> false; the defect is LATENT, not shipped.** Driven against `build_parser()` at `09995f9`:
> `['--fleet-home','H','autoclean']` exits 2 with *"argument command: invalid choice: 'H'"* on
> `py -3.13` and `py -3.10` alike, and `['autoclean','--fleet-home','H']` yields `'H'`. There is
> no global `--fleet-home` to clobber: of the 32 subparsers `autoclean` is the only one that
> defines it, and the top-level parser declares no options beyond `-h/--help`. The **mechanism**
> is exactly as rb7 stated and is reproduced on a synthetic parser in the pin — the clobber is
> created by the act of promoting the flag in slice (a), so the sentence above is a correct
> instruction to the flag-promotion slice and a wrong description of shipped code. Nothing in
> the ratification changes: the pin exists, one slice early, as a lint that makes the clobbering
> shape unlandable (`tests/test_round7_defect_pins.py`). Recorded rather than deleted, because
> the *shipped-defect* framing is what made this a slice condition and a reader needs to know
> the framing was measured wrong without losing why the condition stands.

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
2. **Operator docket entry — DISCHARGED 2026-07-30.** It carried the spec, the two accepted
   residuals (pre-claim window 6.8–10.6s worker / 33–63s successor, dual-adopt-era ambiguity
   costs), the destructive/disruptive table, §8's criteria, WSL out-of-scope,
   `fix/b6-interface-release` ratification, and the CONFIRM-A identity-gate update. Altai
   ruled **"RATIFIED ready-for-build"** in-session on the 2026-07-30 docket pass, and
   **"Build starts at Sequencing §3 slice 0 (install/home split)"** — so the block this item
   used to state (*"No build slice dispatches before the operator rules"*) is discharged and
   step 3 is open. The rider was ruled separately, as the docket asked:
   `fix/b6-interface-release` (2e824ea) gets a **GATE LANE, MERGE ON GREEN**. Still NOT
   discharged and still blocking what it governs: **the §8 exit is a second, later operator
   decision**, quoted from the same ruling — *"§8's four exit criteria for the legacy default
   stay a second, later decision"*.
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
