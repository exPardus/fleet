# Multi-fleet: independent fleets scoped per session, per repo, or per dir

Status: drafting (2026-07-30, interface tier) — GATE THEN BUILD: dual-lens gate, then operator
ratification, then build. Nothing here is buildable until the Status line says so.

## Why this exists

Operator launch goal (2026-07-29): fleet ships when a machine can run **independent fleets** —
one per session, per repo, or per directory — instead of exactly one. Today there is one fleet
because the **home is coupled to the install**: `FLEET_HOME` defaults to `bin/fleet.py`'s own
`parent.parent` (`bin/fleet.py:85-88`), and every hook script re-derives the same fallback
standalone (`bin/hooks/*.py::_fleet_home`, triplicated by design — hooks never import fleet.py).

The coupling is not just a limitation; it is a live hazard with a receipt: on 2026-07-29T22:58:39Z
a test/tool invocation escaped isolation and overwrote the real `state/fleet.json` +
`supervisor/INCARNATION` with fixture data (sid `11111111-1111-4111-8111-111111111111`), because
anything that runs fleet code from inside the repo with no `FLEET_HOME` set resolves to the real
home. Quarantined artifacts: `state/*.testpollution.20260729T225839Z`. Decoupling home from
install closes this class structurally; the isolation-escape forensics lane (dispatched wave 11)
finds the specific culprit.

## Definitions

- **Install** — the directory holding `bin/fleet.py`, `bin/hooks/`, `bin/fleet_statusline.py`,
  templates, tests. One per machine is the normal case (more is allowed; nothing below assumes
  one). Code plane. Git-tracked.
- **Home** — the directory holding one fleet's soul and state: `state/` (registry, events,
  outcomes, journals, tasks, worker-settings), `logs/`, `mailbox/`, `knowledge/`,
  `supervisor/GOALS.md` + `JOURNAL.md` + `INCARNATION`. Data plane. One **per fleet**.
- Today install == home for the dogfood fleet. That identity remains legal forever (back-compat);
  multi-fleet means it stops being required.

## M1 — scope

Deliberately flag-sized (ROADMAP "flag, not subsystem"): the mechanism (`FLEET_HOME` env) already
exists and already works — M1 makes selection first-class, makes homes creatable, and makes the
resolved home explicit at every frame. No federation, no discovery index, no cross-fleet views in
M1 (see M2).

### 1. Resolution precedence — one rule, every entry point

For the CLI, the statusline, and the hooks alike, in order:

1. **`--fleet-home <path>` flag** (CLI: promoted from autoclean-only to a global flag; hooks: a
   baked argv, see §3). Must exist and resolve; a path that does not is a refusal, never a
   fallback.
2. **`FLEET_HOME` env** — the per-session scope. Unchanged semantics.
3. **Marker walk-up** — from cwd toward the filesystem root, the first `.fleet-home` file wins:
   a one-line text file containing the absolute path of a home. This is the per-repo / per-dir
   scope (commit it to a repo → per-repo; drop it in a directory → per-dir subtree).
4. **Install root** — the legacy default, kept for back-compat with the dogfood fleet and every
   existing single-fleet install.

A resolved home that is not initialized (no `state/`) is refused by mutating verbs with a named
remedy (`fleet init --home <path>`); read verbs report "not initialized" as today.

**Hazard, named, with its corpse cited:** a *machine-global mutable pointer* to "the" fleet home
was built once (`~/.claude/fleet-home`) and deleted on 2026-07-22, because a stale marker would
silently redirect `fleet clean`/`kill` at another fleet's registry (`knowledge/INDEX.md`
2026-07-22-hook-removal). The `.fleet-home` marker differs on every axis that made that a corpse:
it is **directory-scoped, not global** (it can only redirect invocations physically under it); it
is **owned by the directory's owner, not by fleet** (fleet never writes one); and it is
**validated, not trusted** — a marker naming a non-existent or uninitialized home is a loud
refusal that names both the marker file and the remedy, never a fallback to a different home.
Residual risk that stays: a *valid but wrong* marker (points at fleet B while the operator thinks
fleet A). Mitigation is visibility, not cleverness: every mutating verb already prints its
effects; M1 adds the resolved home to `fleet status` header, `fleet home` (exists), and the
destructive-verb confirmation lines, so the wrong fleet is visible at the exact moments it costs.

### 2. `fleet init --home <path>` — scaffold a new home

Creates `state/` `logs/` `mailbox/` `knowledge/` (with a seed `INDEX.md`), `supervisor/GOALS.md`
(stub with the tier-policy block commented), and renders `state/worker-settings.json` from the
install's template — exactly what `fleet init` does today, pointed at a foreign directory.
Refuses a path inside another home or inside the install's `state/`. Does not touch git; whether
a home is a repo is the operator's business (`knowledge/` wants to be tracked, `state/` wants to
be ignored — the scaffold writes a suggested `.gitignore`).

### 3. The resolved home is explicit at every frame

Council rider on §7 (2026-07-28), generalised: an ambient value inherited through a call graph is
how this fleet gets hurt. Applied here:

- **Dispatch stamps `FLEET_HOME=<resolved home>` into every worker/supervisor child env**
  (`_worker_env` @1446-1449 today stamps only `FLEET_WORKER` and relies on inheritance).
- **Hook commands carry `--fleet-home <home>` argv**, baked by the worker-settings render (the
  template already substitutes `{{FLEET_HOME}}` for the render; the hooks gain one argv and keep
  env → script-location as fallbacks so existing installs keep working unmodified).

The argv matters because of a **measured cross-fleet hazard**: the native daemon donates the
FIRST dispatch's environment to every later session it hosts (live defect, `skills/fleet/SKILL.md`
doctrine list). With env-only resolution, fleet B's worker hooks can inherit fleet A's
`FLEET_HOME` and write B's outcomes into A's state. With the argv baked into B's own
worker-settings, the donated env loses. The existing witness doctrine extends: a hook whose argv
home disagrees with its env home logs the disagreement to `state/hook-errors.log` (the argv wins;
the log is the divergence evidence, deciding nothing — same shape as the `FLEET_WORKER` witness).

### 4. Test isolation pins (founding incident: 2026-07-29T22:58:39Z)

- A session-scoped autouse conftest fixture exports `FLEET_HOME=<tmp>` into `os.environ` so every
  subprocess the suite spawns (CLI invocations, hook smoke tests) inherits an isolated home —
  monkeypatching `fleet.FLEET_HOME` protects in-process paths only, and the founding incident
  proves the subprocess path is real.
- A pin asserts the real repo's `state/fleet.json` mtime is unchanged across the suite
  (cheap, direct, catches the whole class regardless of culprit).
- The isolation-escape lane's root-cause fix lands independently; this spec does not wait for it.

## Cross-fleet interference audit (what is machine-global, and why each is safe or fenced)

| Surface | Status under multi-fleet |
|---|---|
| `claude` session namespace | Shared by nature. Safe: husk-sweep ownership is per-home evidence (registry/archive/events sids), **default-deny** — fleet B can never `claude rm` a session absent from B's own evidence (SPEC §11 autoclean discriminator). Cost: `doctor`'s fleet-unknown-sessions check reports other fleets' sessions as unknown — stays NOTE-only, wording gains "or another fleet's". |
| Native daemon env donation | The named hazard of §3; fenced by baked argv + witness log. |
| Statusline (`~/.claude/settings.json`, the one file fleet writes outside home) | One global statusLine; the script resolves the home per §1 from the session's own cwd/env, so each session renders **its** fleet. Install-anchored script path unchanged. `fleet init --statusline` still refuses to clobber a foreign one. |
| Plugin/skill | Pull-only (D7). The skill's ritual starts with `fleet home` — which now applies §1. No injection surface is added; scoping is exactly what makes D7's "which fleet would a hook even brief?" question moot. |
| OS scheduler | None since 2026-07-27. The retired task's F2/F3/F4 ownership rules (home embedded in command; full-identity match) already anticipated a second fleet's task and bind any future scheduled anything (SPEC §11 retired-scheduler record). |
| `fleet.lock`, registry, mailbox, claims | All home-relative already; N homes = N independent single-writer domains. No shared writable anything — the F26/M25 refusal (*"never a shared writable fleet.json"*) transfers verbatim from multi-machine to multi-fleet. |

## Invariants touched (SPEC §16, all nine checked, four material)

1. **daemonless** — preserved: no new resident anything; a home is directories.
2. **exit-0 hooks** — preserved: hooks gain an argv and a witness log line, refuse nothing, exit 0.
6. **single-writer registry** — preserved and multiplied: one `fleet.lock` per home; no verb in
   M1 opens two homes in one invocation (federation would; that is exactly why it is M2, gated).
7. **one live session per name** — preserved per home. Names are registry-scoped, so `alpha` in
   fleet A and `alpha` in fleet B are distinct workers with distinct sids; the sid, not the name,
   is the daemon-facing key, and sids never collide.
8. **platform-adapter-only OS branching** — untouched: resolution is pathlib, no new OS seam.
9. **one-state-many-views** — preserved per home: `status_snapshot()` unchanged; the statusline
   change is which home it reads, not how.

(3 mailbox, 4 journal-injection, 5 cwd-scoped dispatch: home-relative already; unaffected.)

## Graveyard check (IDEA-FORGE §5)

No corpse re-proposed. Adjacent: corpse 10's "brittle sniffing" objection — §1 sniffs nothing
(explicit flag/env/marker, else legacy default); the deleted `~/.claude/fleet-home` marker (a
lessons-corpse, not a forge one) is answered in §1's hazard paragraph — the load-bearing
difference is directory-scoped + fleet-never-writes-it + validated-not-trusted.

## M2 — read-only federation view (demand-gated, NOT part of M1)

`fleet status --all-fleets` over an operator-maintained list of homes (a read-only config, e.g.
`~/.claude/fleet-homes.list`, consulted by VIEWS ONLY — never by resolution, never by a mutating
verb; a stale line can misrender a table but cannot redirect a write). Per-machine-registry
reasoning of F26/M25 applies unchanged. Build only on demand evidence per the soak doctrine:
specs always run; BUILD is what's gated.

## Open questions

1. **Does the install-root default (§1.4) survive to launch?** It is the escape hatch that made
   today's incident possible. Recommendation: keep in M1 (back-compat), retire behind a
   deprecation warning once the dogfood fleet itself runs on a marker — an operator decision at
   that point, not now.
2. **Marker filename**: `.fleet-home` proposed. Bikeshed guarded: one name, documented, lint that
   nothing else reads it.
3. **`knowledge/` for non-repo homes**: scaffolded as plain directory; the learning-loop commits
   only apply when the home is a repo. Accepted as-is for M1.

## Sequencing

1. This spec → **dual-lens adversarial gate** (two independent lenses, no shared context; verify
   the code citations by grep, attack the marker hazard and the daemon-donation fence).
2. Findings folded → **operator gate** (docket entry in `docs/OPERATOR-GATES.md`): ratify scope,
   the §1 precedence, and open question 1's disposition.
3. Build slices, disjoint file sets: (a) resolution + `--fleet-home` global flag + status header;
   (b) `init --home` scaffold; (c) hook argv + env stamp + witness; (d) statusline resolution;
   (e) conftest isolation pins. Each RED-then-GREEN, both floors.

WHAT THIS SPEC GOT WRONG — assume it contains an error and go find it. Known soft spots: the
`bin/fleet.py` line citations (grep them, they rot), whether the worker-settings template really
renders per-home today (verify `render_worker_settings_template` call sites), and whether the
statusline can resolve cwd at all in its render context.
