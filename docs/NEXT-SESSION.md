# Next session — day-5 handoff (written 2026-07-27 by the interface session)

## YOU ARE THE INTERFACE TIER. NEVER RUN `fleet sup-boot`.

You bootstrap a supervisor with `sup-spawn` and steer it with `fleet send supervisor`. A previous
handoff told the incoming session to `sup-boot`; it did, and wedged the claim for hours
(`docs/AUTONOMOUS-2026-07-26.md` §G-D). The claim belongs to a role, not to a body.

## Operator's standing directives for this session (verbatim intent)

1. **Work fully autonomously.** The operator is away from the computer.
2. **4-councilor council rule** for anything operator-gated: four subagents of differing
   personalities (risk auditor / delivery pragmatist / strategist / incident responder) **+
   synthesis**; act on the synthesis; record it in the day's ledger. Never stall for the operator.
3. **Keep working the spec and roadmap backlog. Make sure everything keeps going.**
4. **The operator is clearing `docs/OPERATOR-GATES.md` themselves, in a separate session.** Do not
   tick boxes, do not wait on gates, never block a build on one.
5. **Steer the supervisor more interactively and check on it more often** — short waits, frequent
   `fleet status` / `peek`, and steer the moment it drifts. Do not fire-and-forget for an hour.
6. **YOU choose the target tasks and make the plan; the supervisor manages workers and splits
   tasks.** Explicit division: you decide what gets worked on and in what order; it slices,
   dispatches, gates and merges. If it starts re-planning the queue, pull it back.

## State right now

`main` is green: **2324 passed / 16 skipped on BOTH floors** (py3.13 and py3.10), verified directly
by the interface rather than inherited from a report.

Recently landed: `build/sup-tombstone` (§10.4 kill/respawn), **`fix/handoff-seams`** (the
stillborn-handoff hole that had eaten six supervisors), the `gate-arm` §7 arming, the handoff
template's missing `--nonce`, and a spec note on guards that block their own remedy.

**A supervisor is live**: `sup|inc-20260727T003701Z-bcc7|boot`, spawned on
`state/tasks/lens/sup-brief-wave2.md`, with these targets in order:

1. **`fleet q` M1+M2** — `docs/specs/fleet-index.md`, gated-sound and `ready-for-gate`,
   operator-ORDERED. The main event. Honor §11.7's `[UNVERIFIED]` live-receipt acceptance item and
   the §16 doc-sync list; the worktree recipe includes a manager-side `fleet index init` step.
2. **`fix/identity-registry-judges` @ `7d33d28`** — confirmed/ESCALATE, decision OPEN.
3. **`fix/b6-interface-release` @ `2e824ea`** — PARKED and now conflicting in both `bin/fleet.py`
   and `docs/specs/claim-nonce.md`. Decide rebase-and-gate vs retire-and-re-derive the one mechanism
   worth keeping (`sup-release` tombstoning its own body). Parking may be the right final answer:
   the incident it repairs is now forbidden by doctrine, while the case it leaves broken is every
   ordinary supervisor stand-down.
4. The **`[UNBUILT]` sweep** across `docs/specs/**` toward launch-ready (v2-deferred rows stay
   deferred).

## The interface maneuvers that actually work (learned the hard way)

- **Succession**: `sup-release` → **the interface stops the retired body** (so its sid leaves the
  roster) → fresh `sup-spawn`. A fleet-launched body never leaves the roster on its own, and B6
  refuses a released claim whose releaser is still live — so a supervisor **cannot complete its own
  stand-down**. That last step is yours, every time.
- **`fleet kill` can be refused by the very wedge it clears** (§7 armed on a released claim). The
  documented escape is real and load-bearing: run the verb from a shell with **no
  `CLAUDE_CODE_SESSION_ID`** — `env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py …`. Filed as
  claim-nonce §7.2, DESCRIPTIVE/UNRATIFIED.
- **Handoff dispatch is still unproven** — three stillbirths on 2026-07-27 on top of day-3's five.
  Prefer release-then-interface-stops-body until someone proves the dispatch path end to end.
- **Keep briefs SHORT — the highest-leverage thing you control.** Five supervisors each burned a
  full context reading long handovers and merged nothing; the one given a one-page "merge first,
  read second" brief merged the blocker on its first turn. Long handovers are the failure mode.
- **Never author a worker brief at `state/tasks/<workername>.md`** — `dispatch_bg` overwrites it, so
  the worker boots holding a file telling it to read the file it is reading. Use `state/tasks/lens/`.
- PowerShell mangles quotes; Git Bash mangles Windows paths (`C:/x` → `C;C:\Program Files\Git\x`).
  For anything long or quoted, write a file and `send @file`.

## Known live defects, none blocking

- **The daemon leaks the first dispatch's `FLEET_WORKER`** into every later session (§G-E). Benign
  when the leaked value is supervisor-shaped; **malignant** when worker-shaped — that body takes the
  claim and can never beat, checkpoint or release it. Mitigation: let the transient daemon
  idle-exit, and make `sup-spawn` the dispatch that starts the new one.
- **`_supervisor_gate` calling `load_registry()` inside `except RegistryCorruptError`** while
  documenting itself read-only — on a corrupt registry `fleet send` renames `state/fleet.json`
  aside. Fixed on the hs branch; **re-verify it survived the merge.**
- **Two orphaned successor task files** carry spent plaintext tokens and are **correctly unabortable
  forever** (minted before the fix; no pending entry exists to retire). Deleting them is an operator
  shell action per §5.9 — not an agent's.
- `fleet doctor`'s second-body FAIL is self-healing: one historical refusal inside a 24h window, and
  the template fix stops new ones.

## Operator ratification stack (only the operator ticks — they are clearing it separately)

Now on `main` with the hs merge, still owed a ruling: **A1** (§6.4 — `sup-handoff-abort` has three
arms, abort-flag arm deleted as unreachable), **A2** (§5.9/§8 — fail-closed age-gated sweep at four
sites), **A3** (§6.4/§5.9 — explicit `superseded` state + boot refusal; **changes the protocol
shape**, no promote verb by design).

Day-4: the G-D synthesis (`sup-release --interface`, council 4–0, built, now parked); the rejected
repairs (a+)/(e) with their refutations; claim-nonce §7.2 (guard-blocks-its-own-remedy); the
doctrine that *the claim belongs to a role, not a body* and that *a guard keyed on a proxy must name
the predicate it proxies for*; the `[UNBUILT]` follow-up to gate `sup-boot` on fleet-launched
provenance. Day-3 carry-over: claim-nonce §7.1 interface-send amendment; tombstone rulings 1+2, the
ruling-1 cond-2 narrowing, the husk-respawn boot-ritual call, the six-token terminal contract, the
rb MIN-D lock-budget note; the abort-recipe doc defect; G-A..G-C records; the fleet-index settled
row.

## Doctrine worth not re-learning

- **Fix waves mint defects: 7 of 7 this campaign** — and the last two were traceable to a
  *supervisor's ruling*, not a builder's slip. Always re-gate; ESCALATE beats a third wave.
- **A pin written against the mechanism you fixed does not cover the mechanism you introduced** —
  three instances in one campaign.
- **An allowlist entry is a claim, like a receipt or a citation.** The first thing to check about a
  new detector is not what it catches but what it excuses — one shipped blessing a live defect.
- **Absence is not evidence on this substrate**: records are deletable, archivable, and born with
  `session_id: None`. Any predicate that permits on a missing record fails open.
- **A guard's postcondition must be satisfiable by every legitimate caller class**, and **a verb that
  clears a state must not be gated on that state.**
- A skip-by-default live test is an unexecuted claim. Restore proof is `git status --porcelain`
  EMPTY, never a sha compare. `git log` is the only truth; push `main` at every green milestone.

## Ledgers

`docs/AUTONOMOUS-2026-07-26.md` (day 4: §G-D claim wedge + council, §G-E daemon leak, §G-G first
live respawn-of-holder, §G-H..§G-V identity work and the gate wave).
`supervisor/JOURNAL.md` — read the last two CHECKPOINTs, never the whole file.
