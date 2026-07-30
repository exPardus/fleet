# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v5 (2026-07-30, interface tier). History: v1 → RESTRUCTURE; v2 → RESTRUCTURE
(marker killed, §9); v3 (registry-lookup core) → round 3 held the core, killed mechanics; v4 →
round 4 (`mf-rb4`): **2 GATING, 6 MAJOR — and the round-3 fixes vindicated by execution**
(atomic append 0 lost / 320 across 6 trials both floors vs naive 2–8% loss; `samefile` no false
match; every cited symbol accurate). v5 folds round 4; the architecture is unchanged since v3;
the membership rule is now *simpler* than v4's, not more elaborate. Reports:
`state/journals/mf-r{b,s}{,2,3}.md`, `mf-rb4.md`. GATE THEN BUILD: round-5 gate before the
operator docket. Code references by symbol.

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
per session, per repo, or per directory — instead of exactly one. Today there is one fleet
because `FLEET_HOME` is **two variables wearing one name**: the *data plane* (the home) and the
*install locator* that finds hook scripts, `fleet.py`, the statusline and the worker-settings
template. Measured at round 1 and re-driven since: `fleet init` against a data-only home
refuses; after copying the template in, the rendered hook commands point at
`<home>/bin/hooks/*.py`, which does not exist — a fleet-B worker runs with four dead hooks,
silently, because hooks exit 0. **The split is the work.**

Incident receipt for the coupling: 2026-07-29T22:58:39Z — fleet code run from inside the repo
with no `FLEET_HOME` set overwrote the real `state/fleet.json` + `supervisor/INCARNATION` with
fixture data (quarantine: `state/*.testpollution.20260729T225839Z`). Isolation pins are §7.

## Definitions

- **Install** — the code plane: `bin/fleet.py`, `bin/hooks/`, `bin/fleet_statusline.py`,
  `worker-settings.template.json`, `docs/`, `tests/`. `INSTALL_ROOT =
  Path(__file__).resolve().parent.parent`, never overridable. A plugin-cache copy is
  structurally indistinguishable from an install (measured); what governs is §4 membership.
- **Home** — one fleet's soul and state: `state/`, `logs/`, `mailbox/`, `knowledge/`,
  `supervisor/GOALS.md` + `JOURNAL.md` + `INCARNATION`. Install == home stays legal forever.
- The four worker hooks each carry a standalone `_fleet_home()` (quadruplicated; one copy
  diverges). Slice 0 unifies them plus the statusline's import-time conflation.
- **Home-path comparison**: by filesystem identity (`samefile`) when both exist, **wrapped —
  never allowed to raise out of resolution** (`FileNotFoundError` between an `exists()` probe
  and the call = treat as distinct and continue; mf-rb4 B12 measured the raise, and resolution
  runs inside views that must exit 0). String `normcase(resolve())` fallback for nonexistent
  paths, named in any refusal that turned on it. Identity values are compared **within one
  process only, never persisted** (`st_dev` differs across interpreter floors for the same
  drive — measured).

## M1 — scope

Not a flag (re-vet failed on measured merits, stays failed). M1 = slice 0, the homes list,
resolution, `init --home`, `adopt`, pins. Excluded: federation views, cross-home operations
(§10). Build reality: **no shipped registry reader takes a path** — slice (a) contains
`read_registry_at(home)`, the tolerant path-parameterized reader (driven through 12 corruption
shapes at round 3: zero quarantines, zero raises).

### Slice 0 — the install/home split

Re-point the install-locator sites at `INSTALL_ROOT` — by symbol: `template_settings_path`,
`statusline_script_path`, the lifecycle-steer render, the two doctor hook-smoke checks,
`_render_sup_spawn_task`, `_render_successor_task`, the `render_worker_settings_template` call,
and the template's hook-command placeholder (`{{FLEET_INSTALL}}/bin/hooks/...`). The doctor
legacy-settings check is home-plane — NOT re-pointed. Re-grep `FLEET_HOME /` before touching
anything; every prior enumeration has been wrong at least once.

## §4. The homes list

`~/.claude/fleet-homes.list`. **Append-only, forever**: records are appended, never rewritten —
the file lives outside every home, so no `fleet.lock` can serialize a rewrite, and the
read-modify-write reading of v4's "dedupe" sentence was measured at 95–100% loss under
contention (mf-rb4 B6). Two record kinds, one per line: a home path, or a retirement
`!<home path>` — the reader folds retirements over prior entries, which gives the design its
removal path with no rewrite and no hand-editing (v4 had none; hand-editing was the only exit
and B8 shows one PowerShell redirect corrupting the file).

**Writers**: `fleet init --home`, `fleet adopt` (append a home), `fleet adopt --remove` and
`fleet homes --retire <path>` (append a retirement) — never hooks or dispatch. All appends go
through the platform adapter's `atomic_append_bytes` (win32 `FILE_APPEND_DATA` — the mechanism
adopted for this defect class at `851e15f`, extended at `a4f0079`; v4's "2026-07-16" date
matched no commit), newline-terminated, POSIX half `O_APPEND` single `write()`. **Read-side
verify only**: after appending, re-read and confirm your own line landed (retry if lost); no
verb rewrites the file, stated as a rule.

**Read grammar**: decode tolerantly — detect and honor `EF BB BF`, `FF FE`, `FE FF` (PowerShell
5.1 `>`/`Out-File` emit UTF-16LE; refusing the whole list on that would brick every mutating
verb machine-wide until a hand-fix — mf-rb4 B8 — so the encoding is detected and `doctor` names
it rather than reporting an opaque unreadable). Per line: strip, skip empty; `!`-prefix =
retirement. A path line is valid iff (a) **absolute by the spec's own definition** — drive-letter
root `X:\`/`X:/` or UNC `\\server\share` on Windows, leading `/` on POSIX; never `os.path.isabs`,
whose answer for `/c/...` changed between 3.10 and 3.13, the two declared floors (measured:
same bytes, two populations — mf-rb4 B4); (b) containing no `..` segment; and (c) naming an
**initialized home** at read time — which is also what quietly retires a torn-prefix line (a
partial `atomic_append_bytes` write leaves an absolute-shaped prefix; an uninitialized target is
a skip + doctor NOTE, not a member — mf-rb4 B11). Invalid lines never invalidate other lines.

**Why this is not the deleted corpse** (`~/.claude/fleet-home`, 2026-07-22): the corpse was an
*authority* — a stale pointer would redirect `clean`/`kill`. The list is a **search space**: a
hit requires the caller's sid in that home's registry (§5), so a stale, wrong, duplicated, or
torn line can only produce a miss, a skip, or an ambiguity refusal — never a wrong-home
resolution. Unreadable *file* → refusal for sid-carrying mutating callers, never fall-through
to env.

Honesty items: a second fleet-written file outside any home (the `user_settings_path` "ONLY
file" docstring is restated in the same slice); and resolution performs cross-home registry
READS — the audit table pins that the read path is lock-free, write-free and quarantine-free.

## §5. Resolution

**Sid-carrying callers**:

1. **`--fleet-home` flag** — global, applied in `main()` before dispatch (**to be built**;
   exists on `autoclean` only today). Validation: resolve, `is_dir`, **initialized**; refusal
   otherwise; **no code path may `mkdir` into an uninitialized target as a side effect**
   (measured shipping today from `--dry-run`; three in-the-wild empty `state/` dirs).
   Flag/lookup disagreement → mutating verbs refuse without `--yes` + witness line.
2. **sid→home lookup.** Population: **listed homes (after folding retirements) ∪ the legacy
   install-root home**. Per home, ONE lock-free snapshot via `read_registry_at`, tri-state
   outcome: **hit / miss / unreadable**. Membership is **the shipped identity concept,
   verbatim**: sid ∈ `_record_sids`-union of that home (current `session_id`s ∪ `retired_sids`)
   ∪ the `INCARNATION` holder's sid. v4's LIVE/RETIRED split with a forensic refusal is
   **withdrawn**: the ratified Steering contract leaves every fork-steered session live under an
   identity that sits in `retired_sids` (shipped comments in `cmd_send`'s restamp block say so),
   so "retired-only ⇒ stale" was false and the verdict flipped on an unrelated file's write
   timing (mf-rb4 B1 built the state). One set, one rule, timing-immune; divergent-body
   detection is the nonce system's job, not resolution's. `spawned_by` still never grants
   membership (pinned) — a manager must not be ambiguous across the fleets it manages.
   Cross-home consequences stated: a sid retired in home A and current in home B is a member of
   both → ambiguity refusal → flag per call (rare; accepted; the alternative re-opens B1).
   Exactly one member-home → resolved. Two+ → refusal naming all. Miss everywhere → mutating
   verbs refuse (naming any unreadable homes); reads fall through to (3) with provenance
   rendered (the compact status table gains a one-line header as its render site).
3. **Validated env → legacy default** (reads; and everything while unarmed): `FLEET_HOME` must
   resolve to an initialized home. When armed (below), destructive verbs resolved via env
   additionally require the flag.
4. **TOCTOU**: mutating verbs re-assert caller sid ∈ that home's membership after taking its
   `fleet.lock` (`adopt` exempted — §6).

**Sid-less callers**: flag → validated env → install-root legacy default (§8).

**Hooks**: `--fleet-home` argv baked per-home into rendered worker-settings (survived four
rounds; both `--settings` construction sites — `dispatch_bg`, `cmd_sup_handoff_begin` — touched
or the second pinned). Argv/env disagreement: argv wins, one witness line; env-absent is normal
and silent.

**Statusline**: sid from the vendor stdin blob, same lookup; words, exit 0, never quarantines;
resolver pure-function under unit test; blob schema unverified — capture experiment gates the
slice.

**Arming — fails ARMED, not open (mf-rb4 B3):** multi-fleet behavior activates per invocation
when the population contains ≥2 distinct homes that are **valid or unreadable** — an unreadable
home counts toward the threshold, because "cannot read this home" is not "this home stopped
existing", and v4's readable-only rule let a transient exclusive handle (any AV scanner) disarm
the flag requirement in exactly the window a destructive verb could fire through env to the
wrong home. Distinctness by the Definitions comparator (exception-wrapped). With <2, behavior
is byte-identical to today (baseline captured at `12c6521`, the falsifiability fixture).

**Refusal texts print facts and the `fleet homes` view — never a paste-ready command with a
chosen home.**

## §6. `fleet adopt <home>`

Takes its target as an **explicit path argument** — no resolution involved, since bootstrapping
resolution is its purpose (v4 left the target undefined; mf-rb4 B2c). Writes a membership
record into that home's registry under that home's `fleet.lock` — a record whose
`session_id` is the adopter's sid, so the §5.2 union reads it **by construction** (this answers
v4's open question 1: the record is registry-native, `kind: "member"`, no worker semantics; the
§7 membership pin covers it). Appends the home to the list if absent. Exempt from §5's
miss-refusal and §5.4's re-assert by the ratified rule — **a verb that clears a state must not
be gated on that state** (mf-rb4 B2a measured the bootstrap deadlock).

**What adopt does and does not confer, stated (B2a's "self-authorization")**: adopt grants
*resolution* — the ability to name the home implicitly. It grants **no authority**: ownership
checks (`spawned_by`, `_worker_is_foreign`), the §7 claim-nonce gate, and destructive
confirmations are all unchanged, and an unadopted session could always reach the same home
explicitly via `--fleet-home`. Adopt is therefore authority-neutral by equivalence with an
existing channel — and it is *auditable where the flag is not*: it appends an `adopted` event
to the target home's `state/events.jsonl`. `adopt --remove` deletes the membership record and
appends a list retirement (§4). The skill ritual runs adopt as an explicit documented step;
hooks and dispatch never touch the list.

## §7. Test isolation pins

- Autouse conftest fixture exports `FLEET_HOME=<tmp>` (subprocess-inheriting), function-scope
  override available.
- **The homes-list path helper is monkeypatched by the same autouse fixture** — the list lives
  outside FLEET_HOME, so the env fence alone cannot sandbox it, which is byte-for-byte the
  2026-07-09 `~/.claude/fleet-home` suite-overwrite incident the current fixture's docstring
  records (mf-rb4 B7). A pin asserts the real `~/.claude/fleet-homes.list` is untouched across
  a full suite run.
- Founding-incident guard, re-scoped (v4's content-hash canary was measured flapping on the
  live dogfood home — 6 files churn inside one suite duration; a canary that flaps gets
  xfail'd): the canary arms only against **quiescent** homes (no fresh claim heartbeat, no
  working workers at suite start) and **skips LOUDLY** otherwise; the list pin above and the
  env fence carry the live-home protection. RED first, in a quiescent fixture home.
- The §5.2 membership pin: union membership + both exclusions + the adopt record, driven
  through a real fork-steer restamp window, asserting *member, no flap* (v4's pin only pinned
  the pre-flip side of a verdict that could flip — mf-rb4 B1).
- The arming pin: 2 valid homes → sid-less/flag-less/env-less mutating invocation refuses;
  1 valid + 1 unreadable → **still armed**; <2 → byte-identical to the `12c6521` baseline.
- The §4 writer pin: N concurrent appenders, zero lost homes, and a **no-rewrite lint** (no
  code path opens the list with truncate/write modes).
- "Not initialized" is a rendered word on every read surface; no verb `mkdir`s into a non-home.

## §8. The legacy default's exit criteria

Kept in M1; removable when ALL of: (1) slice 0 done; (2) the dogfood home physically moves out
of the install and is listed (the §7 population follows the list, so the watch moves with it);
(3) the plane-naming lint passes (each `$FLEET_HOME`/`fleet home` consumer tagged install-plane
or home-plane in a checked table); (4) the arming pin extended to the sid-less class. Operator
decision against these criteria. The legacy home is in the §5 population regardless of listing,
so retiring it changes the sid-less class only.

## §9. The marker, deleted — record

v2's `.fleet-home` marker + walk-up died at round 2 on four demonstrated findings: the dogfood
config made the dispatch-written marker invalid by its own rules; "enclosing git root" is two
designs disagreeing on all-but-one checkout here, and the git-correct reading makes parent
markers unreachable; "write if absent" serves fleet A's stale marker to fleet B; dispatch would
plant untracked files in ~69 project trees. Anyone re-proposing a marker answers those first.

## Cross-fleet interference audit

| Surface | Status |
|---|---|
| `claude` session namespace | Shared; husk-sweep ownership per-home, default-deny; doctor fleet-unknown stays NOTE-only + "or another fleet's". |
| Daemon env donation | Substitution model (docketed 2026-07-30). Env = validated read fall-through; hooks argv; statusline blob sid; CLI registry lookup. Inherited residual, stated: the lookup keys on `CLAUDE_CODE_SESSION_ID`; sid-donation is OPEN in shipped code's own comment — bounded (fleet pops the sid pre-dispatch; every measured body shows the vendor stamping the session's own sid); ties to the docketed identity gate. |
| Homes list | Fleet-written global file: search space, not authority; append-only with retirement records; adapter atomic append; tolerant decode; a bad line can only miss/skip/refuse. |
| Cross-home READS | Resolution reads foreign registries (`read_registry_at`: lock-free, write-free, quarantine-free — pinned); the quiescent-home canary reads content in tests only. No cross-home write exists except `adopt`, under the target's own lock, evented. |
| Statusline settings entry | Unchanged; `init --statusline` refuses to clobber foreign. |
| Plugin/skill | Pull-only (D7). Ritual gains the explicit `adopt` step and the install-vs-home split for its step-1/step-3 reads. |
| `fleet.lock`, registry, mailbox, claims | Home-relative; N single-writer domains. F26/M25 refusal transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; the tenth is UNBUILT/M-F-owned, untouched)

1. **daemonless** — preserved. 2. **exit-0 hooks** — preserved. 6. **single-writer registry** —
preserved per home; the one file no lock covers (the list) is therefore append-only by rule,
with rewrites linted against. 7. **one live session per name** — preserved per home.
8. **platform-adapter-only OS branching** — list writes ride the existing `atomic_append_bytes`
seam; path semantics delegated to the filesystem via wrapped `samefile`; the absolute-path
grammar is the spec's own, not a version-dependent stdlib predicate. 9. **one-state-many-views**
— preserved; lookup and `fleet homes` are derivations.

## Graveyard check

§4's corpse paragraph. Corpse 10 "brittle sniffing": a registry hit is a fact dispatch wrote
under a lock; no help-text or version sniffing anywhere.

## M2 — read-only federation view (demand-gated, NOT M1)

`fleet status --all-fleets` over the same list, views only.

## Open questions

1. **Sid-donation residual** — closes with the docketed identity ruling.
2. **WSL/Windows dual-view** — two runtimes, two lists = two machines sharing homes; out of M1;
   named in the docket.
3. **`knowledge/` for non-repo homes** — scaffolded plain; accepted for M1.

## Sequencing

1. v5 → **round-5 gate**: fresh dual lens, all seven prior reports fenced out. Priority: the
   simplified §5.2 union rule against the same fork-steer states that killed v4's (does
   dropping the forensic arm re-open any *demonstrated* stale-identity attack, not a reasoned
   one?); §4's retirement-fold reader under interleaved append/retire contention; the
   fail-armed rule's false-positive cost (AV handle on a *single*-fleet machine arming
   multi-fleet behavior — what breaks?); §6 adopt's authority-neutrality equivalence claim.
2. Fold → **operator docket entry**.
3. Build slices, disjoint: (0) split; (a) `read_registry_at` + list + lookup + arming +
   `fleet homes`; (b) `init --home` + `adopt`/`--remove`/`--retire`; (c) hook argv + witness;
   (d) statusline (gated on capture experiment); (e) pins. RED-then-GREEN, both floors,
   serially.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Named soft spots: the
retirement-fold grammar (`!` prefix) is invented this round and ungated; the quiescent-home
canary may skip forever on this machine (the dogfood fleet is rarely quiescent — if so, say the
list pin is the real fence and delete the canary rather than shipping a permanent skip); and
the claim that adopt is authority-neutral leans on `--fleet-home` being reachable by the same
caller, which is only true once the flag is global (slice ordering constraint: flag before
adopt, or the equivalence is briefly false).
