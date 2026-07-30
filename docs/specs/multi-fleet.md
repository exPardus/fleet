# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting v2 (2026-07-30, interface tier) — v1 (`35cd7b7`) took a dual-lens gate the same
day: **RESTRUCTURE** (break lens `mf-rb`, 10 findings, 4 gating) + 10 of 32 claims FALSE (verify
lens `mf-rs`). Reports: `state/journals/mf-rb-REPORT.md`, `mf-rs-REPORT.md` (state-plane, not
committed; summaries and every load-bearing measurement are folded below). v2 is the fold.
GATE THEN BUILD: v2 takes its own gate round before any operator docket entry.

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
per session, per repo, or per directory — instead of exactly one. Today there is one fleet because
`FLEET_HOME` is **two variables wearing one name** (mf-rb F1, measured): the *data plane* this
spec calls the home, and the *install locator* that finds `bin/hooks/*.py`, `bin/fleet.py`,
`bin/fleet_statusline.py` and `worker-settings.template.json`. Nine shipped sites conflate them
(`bin/fleet.py` @272, @313, @6225, @8057, @8083, @8105, @13399, @13618 — cite by symbol, the
numbers rot — plus the `{{FLEET_HOME}}/bin/hooks/...` commands the worker-settings template
bakes into every worker). Driven at v1's gate: `fleet init` against a data-only home **refuses**
("template not found"), and after hand-patching, `fleet doctor` emits **five FAILs** including
both hook smoke tests — a fleet-B worker would run with four dead hooks, silently, because hooks
exit 0. Splitting the two roles is not a flag on a working mechanism; **the split is the work.**

The coupling also has an incident receipt: on 2026-07-29T22:58:39Z something ran fleet code from
inside the repo with no `FLEET_HOME` set and overwrote the real `state/fleet.json` +
`supervisor/INCARNATION` with fixture data (quarantine artifacts:
`state/*.testpollution.20260729T225839Z`; the rename was manual — no code emits that suffix). The
forensics slice that finds the culprit is **owed and not yet dispatched** (v1 claimed it live;
false at the gate's read). Decoupling narrows this class **for any caller that names a home** —
not "structurally"; §1.4 keeps the legacy default and §7 states its exit criteria honestly.

## Definitions

- **Install** — the directory holding `bin/fleet.py`, `bin/hooks/`, `bin/fleet_statusline.py`,
  `worker-settings.template.json`, `docs/`, `tests/`. Code plane. Resolved as `INSTALL_ROOT =
  Path(__file__).resolve().parent.parent` — **never overridable** by flag, env, or marker.
  Named limitation: under a plugin-marketplace cache copy, `__file__`'s grandparent is the cache,
  not an install — running fleet from a plugin cache is unsupported and must refuse loudly (the
  deleted `~/.claude/fleet-home` marker existed to serve exactly that caller; see §3 history).
- **Home** — one fleet's soul and state: `state/`, `logs/`, `mailbox/`, `knowledge/`,
  `supervisor/GOALS.md` + `JOURNAL.md` + `INCARNATION`. Data plane. One per fleet.
- Today install == home for the dogfood fleet; that identity stays legal (back-compat) and stops
  being required.
- The four worker hooks each carry their own standalone `_fleet_home()` (**quadruplicated**, not
  triplicated — and `stop_outcome.py`'s copy already diverges: `Path.resolve()` vs
  `os.path.abspath`, which pick different homes under a symlinked install). Slice 0 unifies four
  call sites plus `bin/fleet_statusline.py:25-29`, which conflates both planes in one variable at
  import time.

## M1 — scope

The flag-not-subsystem re-vet was run and **failed honestly**: v1 sized M1 as flag-shaped on the
premise "the `FLEET_HOME` env mechanism already works", and the gate measured that premise false.
There is no flag-sized alternative to a variable that must become two variables. M1 is the
minimal decoupling: the split, explicit selection, scaffolding, and pins. Still excluded:
federation, discovery, cross-fleet views (§8).

### 0. The install/home split (new slice, ahead of everything)

Introduce `INSTALL_ROOT` (definition above) and re-point the nine conflation sites; the template
gains a second placeholder — hook commands become `{{FLEET_INSTALL}}/bin/hooks/...` while
`{{FLEET_HOME}}` keeps meaning the home. The template itself moves to the install plane
(`template_settings_path` currently reads it from the *home* root). The four hook
`_fleet_home()` copies unify on one behaviour (resolve symlinks; return `Path`). The statusline
splits its import anchor (own script dir) from the rendered home and **deletes** its
`sys.path.insert(0, <home>/bin)` — under a home that is itself a repo clone, that insert imports
the wrong `fleet.py` at every refresh, silently (mf-rb F7 residue; the crash attack itself
failed and is reported in the mf-rb report so nobody re-runs it).

### 1. Resolution precedence — shared resolution, per-surface failure handling

For the CLI, the statusline, and the hooks alike, in order:

1. **Explicit argument** — CLI: `--fleet-home <path>` promoted from autoclean-only to a global
   flag, applied in `main()` **before dispatch** (today's `cmd_autoclean`-internal application is
   the opposite precedent; its validation semantics — resolve, `is_dir()`, refusal naming raw and
   resolved forms — lift verbatim). Hooks: a `--fleet-home` argv baked by the worker-settings
   render (§3).
2. **`.fleet-home` marker walk-up from cwd** (§2) — the donation-immune channel.
3. **`FLEET_HOME` env** — the per-session scope, kept for the interface shell and operator
   one-liners. Ranked BELOW the marker deliberately: env is the one channel the machine-wide
   daemon can donate across fleets (§3), and v1 ranking env above marker meant a fleet-B worker
   with B's marker under its feet still resolved A — the corpse hazard arriving through the
   daemon (mf-rb F2). A marker/env disagreement is logged (hook-errors.log shape), env loses.
4. **Install root** — the legacy default. Load-bearing today (install == home for the dogfood
   fleet, and until slice 0 lands the *code* is found through it). Exit criteria in §7.

**Failure handling is per-surface, and saying "one rule" about it was false (mf-rb F6):**
*resolution* is shared; the *response* to an invalid marker or home is: CLI **refuses loudly**
naming file and remedy; hooks **log to `state/hook-errors.log` and exit 0** (invariant 2); the
statusline **renders `[fleet]: bad marker` and exits 0** (its contract forbids refusal — and its
`BaseException` swallow means the resolver must be a pure function under unit test, not trusted
to the render path). An **uninitialized** home is a rendered word everywhere — today
`fleet status` against an empty home prints a header row and silence, which under multi-fleet is
indistinguishable from a mis-resolved home; "not initialized" becomes a printed line (the
repo's unknown-is-a-word rule), with a pin.

### 2. The marker

Format (each item is a branch someone would otherwise write by guess — mf-rb F9): UTF-8, no BOM;
one line, whitespace-stripped; an **absolute** path (a relative path is invalid, not resolved —
"against which cwd" has two defensible answers, so neither is taken); native or forward slashes;
must be a regular file; empty, unreadable, or directory-shaped is invalid (per-surface handling
above); symlinks in the target are resolved; a target that is the install root, inside another
home's `state/`, or not a directory is invalid. No `~` expansion.

**The walk is bounded and placement is policed (mf-rb F3):**

- The walk stops at the **enclosing git repository root** (the first ancestor containing `.git`),
  else after a fixed ceiling of directory levels. It never reaches the filesystem root.
- A marker at `$HOME`, `$HOME/.claude`, or a drive/filesystem root is **refused by path** — those
  placements are the deleted corpse under a new name; the lint checks placement, not just the
  filename (v1's lint checked the name, which is not the property that distinguishes this design
  from the corpse).
- **A committed `.fleet-home` is a defect, documented as such.** `git worktree add` and `git
  clone` copy a committed marker everywhere — measured on this machine: 64 worktrees, 60 sharing
  the real home's parent — which reproduces the founding incident at scale, through the fix. The
  scaffold's `.gitignore` lists `.fleet-home`; per-repo scope means an **untracked** marker each
  clone opts into explicitly. What this costs — a fresh clone does not inherit fleet scope — is
  accepted and stated.
- **Worker worktrees get their marker written by dispatch** (§3), so the bound-walk never has to
  reach across a repo boundary to serve a worker.

**A marker may select a home; it may not suffice to destroy one.** `_confirm_destructive` returns
early when the caller has no session id — the human-at-a-shell is exempt from confirmation *by
design*, and the human at a shell in a project directory is exactly the marker's audience (mf-rb
F3c). So `fleet kill` / `fleet clean` whose home resolved **via marker** and whose caller is
sid-less require the home named explicitly (`--fleet-home`); the refusal prints the one-liner to
re-run. Costs nothing at the dogfood home (resolves via §1.4, not a marker).

**History, stated precisely (mf-rs 2.5):** `~/.claude/fleet-home` was deleted on 2026-07-22
because its only reader (the plugin SessionStart hook) was removed and stamping it was fleet's
only unconditional write to global machine state; the *redirect hazard* is on record as the
reason the **rescue** — giving it a reader — was refused. §1–§2 are that rescue re-proposed with
the global axis removed: directory-scoped, bounded upward, placement-refused at the global
points, never fleet-written at machine scope, and insufficient alone for destruction.

### 3. Dispatch: the home is explicit at every frame

- **Hook commands carry `--fleet-home <home>` argv**, baked per-home by the worker-settings
  render. Fence rationale, stated honestly (mf-rs 2.8): the daemon env-donation hazard is
  **plausible, not measured** — the measured leak is the single variable `FLEET_WORKER`
  (`skills/fleet/supervisor.md` doctrine; live capture in `docs/specs/claim-nonce.md` §16.2,
  which is explicitly not a receipt), and `bin/fleet.py` @2119-2129 records "does the daemon
  donate arbitrary env vars" as OPEN by the same argument it makes about the sid. The argv fence
  is chosen because it is **correct under either answer**, not because the general case is
  measured. Pin what is pinnable today: a hook's argv home beats a disagreeing env home.
- **Dispatch writes the worker's `.fleet-home` marker into its cwd** (if absent), so `fleet`
  verbs run *from inside the session* — the actual destructive surface, where no argv exists —
  resolve by the donation-immune channel. v1 instead stamped `FLEET_HOME` into the child env;
  the gate killed that: the stamp reaches a session only when that dispatch started the daemon,
  and otherwise *manufactures the donation payload* it feared (mf-rb F2). **No `FLEET_HOME` env
  stamp.** Env remains an operator channel, not a fence.
- **The witness has three outcomes, specified** (v1's two-valued divergence witness could not
  fire in its own scenario — the common case is one side absent, mf-rb F2b): argv present + env
  absent → normal, log nothing; argv + env equal → normal; argv + env differ → argv wins, one
  witness line to `hook-errors.log`. No env observation — present or absent — is treated as
  evidence about *this body*; the registry sid union is the sound identity channel. (The
  falsification of the ratified "absence is sound" clause that this rests on is filed as its own
  operator gate — `docs/OPERATOR-GATES.md`, 2026-07-30 — because a spec may not inherit a premise
  its own gate falsified, and may not re-ratify one either.)
- **Every dispatch shape is covered, and one is named because it bypasses the choke point:** all
  worker/supervisor `--bg` launches route through `dispatch_bg`, whose `--settings` comes from
  the resolved home's `instance_settings_path()` — except the handoff successor
  (`cmd_sup_handoff_begin` builds its own `run(...)`), which passes the same settings path today
  but will not inherit a future `dispatch_bg` edit. The build touches both sites or pins the
  successor path separately (mf-rb Target 2 table).

### 4. `fleet init --home <path>` — a scaffold verb, not a re-pointing

Sized honestly (mf-rs 2.2): today's `fleet init` writes exactly one file
(`state/worker-settings.json`) and requires the template at the home root. Six of the seven
artifacts are new work: `state/` `logs/` `mailbox/` `knowledge/INDEX.md` (seed),
`supervisor/GOALS.md` (stub, tier-policy block commented), a `.gitignore` (ignoring `state/`,
`logs/`, `mailbox/`, `.fleet-home`), and the worker-settings render — from the **install's**
template (slice 0), with both placeholders. Refuses a path inside another home, inside the
install's `state/`, or equal to the install root. Whether a home is a git repo is the operator's
business.

### 5. Test isolation pins (founding incident: 2026-07-29T22:58:39Z)

- Session-scoped autouse conftest fixture exports `FLEET_HOME=<tmp>` into `os.environ` — the
  current `_never_touch_the_real_home` patches only in-process helpers, and the founding
  incident proves the subprocess path is real. (It also keeps `fleet init` reachable in tests at
  all: `cmd_init` opens with the §7 supervisor gate, and only a claim-less temp home passes it —
  mf-rs brief-error 5.)
- A guard pin watches the **dogfood home anchored at the install tree** (`INSTALL_ROOT/state/` +
  `supervisor/INCARNATION` — the incident touched both; v1 watched one file, mf-rb F4): asserts
  mtimes unchanged across the suite. Where no `state/` exists (64 of 65 checkouts on this
  machine are worktrees without one) it **skips LOUDLY by design**, the win32-symlink-skip
  precedent — its habitat is the real checkout, which is where the hazard lives. Landed RED
  first: a test writes to the watched path and the pin must catch it, before the fence is
  trusted.
- The argv-beats-env hook pin (§3).
- The statusline resolver pure-function pin (§1).
- The root-cause fix for the escape itself rides the forensics lane; this spec does not wait for
  it and no longer claims it is dispatched.

### 6. Statusline (slice, ordering constraints measured — mf-rs soft-spot c)

cwd **is** reachable: the vendor stdin blob is already read in full at
`bin/fleet_statusline.py:333` and forwarded to delegates unparsed. Two mechanical constraints:
`_FLEET_HOME` is computed at import and used for `sys.path` before stdin exists, so slice 0's
variable split must land first; and marker resolution must run inside `main()` and **rebind
`fleet.FLEET_HOME` after import** (every path helper re-reads the global per call, so a late
rebind works — the module comment @74-84 says so). The blob's schema is unreceipted anywhere in
the repo: **the build gate for this slice requires the capture experiment** (temporary delegate
dumps payload + `os.getcwd()`, refresh from two directories, diff) — if neither channel carries
cwd, the marker scope does not exist for the statusline and the §"audit" row below changes.

## Cross-fleet interference audit

| Surface | Status under multi-fleet |
|---|---|
| `claude` session namespace | Shared by nature. Safe: husk-sweep ownership is per-home evidence, default-deny — fleet B cannot `claude rm` a session absent from B's own evidence. `doctor`'s fleet-unknown check stays NOTE-only; wording gains "or another fleet's". |
| Native daemon env donation | Plausible-not-measured (§3); fenced by argv + worker-local marker; env demoted below marker. |
| Statusline (`~/.claude/settings.json` — the one file fleet writes outside home) | One global statusLine; script resolves per §1 from its own stdin/cwd context (§6). `init --statusline` still refuses to clobber a foreign one. |
| Plugin/skill | Pull-only (D7). **Build item, not an audit note (mf-rs 2.6):** the skill ritual reads `$(fleet home)/docs/OPERATOR-GATES.md` and `$(fleet home)/knowledge/INDEX.md`; under the split, `docs/` is install-plane and `knowledge/` home-plane — SKILL.md steps 1/3 need a `fleet install`-vs-`fleet home` split (or a companion verb), else they break the moment the planes diverge. |
| OS scheduler | None since 2026-07-27; the retired task's F2/F3/F4 ownership rules bind any future scheduled anything. |
| `fleet.lock`, registry, mailbox, claims | Home-relative already; N homes = N independent single-writer domains. The F26/M25 refusal ("never a shared writable `fleet.json`") transfers verbatim. |

## Invariants touched (SPEC §16 — all nine checked, six argued; §16's tenth is UNBUILT/M-F-owned and untouched)

1. **daemonless** — preserved: no new resident anything; a home is directories.
2. **exit-0 hooks** — preserved: hooks gain an argv and a witness line, refuse nothing, exit 0.
6. **single-writer registry** — preserved and multiplied: one `fleet.lock` per home; no M1 verb
   opens two homes in one invocation (federation would; that is why it is M2, gated).
7. **one live session per name** — preserved per home; the sid, not the name, is the
   daemon-facing key, and sids never collide.
8. **platform-adapter-only OS branching** — untouched: resolution is pathlib; the marker's
   case-sensitivity/symlink surface on POSIX is flagged for the gate's POSIX pass, not a new seam.
9. **one-state-many-views** — preserved per home: `status_snapshot()` unchanged; the statusline
   change is which home it reads, not how.

(3 mailbox, 4 journal-injection, 5 cwd-scoped dispatch: home-relative already; unaffected.)

## Graveyard check (IDEA-FORGE §5)

No corpse re-proposed. Corpse 10's "brittle sniffing": §1 sniffs nothing — explicit argument,
bounded marker, env, else legacy default. The `~/.claude/fleet-home` lessons-corpse is §2's
history paragraph; the honest statement is that §1–§2 *are* the refused rescue, rebuilt without
the properties that made it refusable.

## §7. The legacy default's exit criteria (v1's open question 1, answered — mf-rb F5)

§1.4 is kept in M1 and is removable when ALL of: (1) slice 0 is done — no code path uses
`FLEET_HOME` to find code; (2) **the dogfood home physically moves out of the install** (e.g. a
sibling directory) so install ≠ home is the dogfooded configuration — NOT by committing a marker
into the fleet repo, which detonates in every worktree (mf-rb F3a); (3) the shims
(`bin/fleet`, `bin/fleet.cmd`), the statusline, and the skill are audited to name which plane
each means; (4) a loud refusal replaces the fallback, with a pin that goes RED if any path
silently falls back to `parent.parent`. Removal is an operator decision **at that point**,
against these criteria.

## M2 — read-only federation view (demand-gated, NOT M1)

`fleet status --all-fleets` over an operator-maintained read-only list of homes, consulted by
VIEWS ONLY — never by resolution, never by a mutating verb. F26/M25 reasoning unchanged. Build
on demand evidence; specs always run, BUILD is gated.

## Open questions

1. **Worker-local marker teardown**: dispatch writes `.fleet-home` into a worker cwd (§3); who
   removes it, and is a stale one harmful? (A worktree's marker names the fleet that ran it —
   correct ownership even stale; but say so after the gate attacks it.)
2. **Plugin-cache refusal shape** (Definitions): what exactly distinguishes a cache copy from an
   install at runtime? Needs one measurement on a machine with the marketplace cache populated.
3. **`--setting-sources` under `--bg`** is unobserved (vendor): if worker settings can compose
   from sources beyond `--settings`, the argv fence's exclusivity is unestablished. Carried as a
   vendor-contract gap, not blocking (the marker fence does not depend on it).
4. **`knowledge/` for non-repo homes**: scaffolded plain; learning-loop commits apply only when
   the home is a repo. Accepted for M1.

## Sequencing

1. v2 → **second gate round** (fresh dual lens, no shared context, neither saw round 1;
   priority: attack the worker-local marker (§3), the bounded walk (§2), and the §7 exit
   criteria).
2. Findings folded → **operator docket entry**: ratify scope, precedence, the marker design, and
   §7. (The F2b identity-clause falsification is already docketed separately.)
3. Build slices, disjoint: (0) install/home split; (a) resolution + global flag + rendered
   "not initialized"; (b) `init --home` scaffold; (c) hook argv + witness + dispatch marker;
   (d) statusline (behind its capture experiment); (e) isolation pins. Each RED-then-GREEN, both
   floors, serially (the 235-missing-tests concurrency anomaly is uncharacterised).

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. v1's soft-spot list was
under-weighted by its own gate briefs and one of its three items unravelled the largest finding;
v2's known soft spots: the nine-site conflation list is v1-gate-measured and will rot as main
moves (re-grep at build time); the bounded-walk ceiling ("git root else fixed depth") has an
unstated interaction with worktrees whose `.git` is a *file*, not a directory; and §3's claim
that the successor dispatch "passes the same settings path today" was verified at `35cd7b7`,
one merge queue ago.
