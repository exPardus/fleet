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
3. ~~**`fix/b6-interface-release` @ `2e824ea`**~~ — **RULED RETIRED, 2026-07-27** (supervisor
   `inc-20260727T003737Z-0ccd`, checkpoint G-C; retirement executed by `inc-20260727T012335Z-0dd8`).
   **Retired on merit, not on merge cost**: the inherited "conflict too large to resolve in a wave"
   premise was re-measured against the tree the branch would actually enter and came back at
   **three hunks** (one `bin/fleet.py`, two `docs/specs/claim-nonce.md`) — false, and recorded as
   false so the retirement does not rest on it. The grounds that decide it: (a) its founding incident
   — an interface session running `sup-boot` — is now doctrine-*forbidden*, so its only customer is a
   forbidden path; (b) `--interface` is **a caller supplying the grounds of its own non-refusal**,
   which is precisely what the clause ratified 2026-07-27 forbids ("inference may select the SUBJECT
   of a measurement, but may not supply the GROUNDS of a refusal") — an attestation can only ever be
   *added*, never withheld by an adversary, so its presence proves nothing; (c) the case it leaves
   broken is **every ordinary supervisor stand-down**, and that is better served by deleting the
   condition than by authorising an exception to it.
   **The ref is NOT deleted** — it holds the reasoning, tests and amendments. Its `claim-nonce.md`
   and `three-tier-command.md` amendments were marked for operator ratification and die with it
   unless the re-derived slice needs them, which it largely will not. Worktrees `C:/proga/fleet-b6`,
   `fleet-b6-rb`, `fleet-b6-rs` removed as litter.
   **Re-derive instead, as its own slice with its own gate — NOT a rebase of this branch:**
   **`sup-release` tombstones its own body's registry record as part of releasing.** Then
   `releaser_live` is FALSE by construction, `sup-boot` claims cleanly, and there is no attestation
   to forge — it removes the condition instead of trusting what the caller says about itself. It also
   retires the manual "the interface stops the retired body" step in the succession recipe below,
   which is where every unproven handoff has died.
   **BUILT, 2026-07-27, on `fix/sup-release-tombstone`** (worker `tombstone`): `sup-release` now
   tombstones its own registry record via §10.4's spelling (`status: dead`, read by
   `_record_is_live`), and `_releaser_body_is_tombstoned` is the arm `_releaser_live_sids` gained —
   one predicate, so B6 and the §7 gate cannot disagree. No new flag; the retired attestation road is
   pinned shut by `test_no_flag_by_which_the_caller_declares_anything_about_itself`. **Owed:**
   `docs/specs/claim-nonce.md` §6.1 row 1 and §7.2's *"ARMED, unconditionally"* row are now
   incomplete about shipped code and need an operator amendment — §7 is operator-owned, so the
   worker reported it instead of editing it. This is the in-fleet disarm `docs/OPERATOR-GATES.md`
   already recorded as owed work on 2026-07-27.
4. The **`[UNBUILT]` sweep** across `docs/specs/**` toward launch-ready (v2-deferred rows stay
   deferred).

## The interface maneuvers that actually work (learned the hard way)

- **Succession**: `sup-release` → fresh `sup-spawn`. **Two steps, both fleet's, since
  `fix/sup-release-tombstone`.** `sup-release` tombstones the releasing body's own registry record,
  so B6's live-releaser test is false by construction and the successor boots immediately. The old
  middle step — *the interface stops the retired body so its sid leaves the roster* — is **gone**;
  it was the last step of this recipe that lived outside the fleet, and it is where every unproven
  handoff died. Stop the retired body anyway to reclaim the session, but succession no longer waits
  on it. The old rule still applies to a release that could not tombstone: an **interface** session
  (no registry record to retire — which is one more reason the interface must never `sup-boot`), an
  ambiguous registry identity, an unreadable registry, or a crash between the release and the
  tombstone. `sup-release` says which case it was on stdout.
- **`fleet kill` can be refused by the very wedge it clears** (§7 armed on a released claim). The
  documented escape is real and load-bearing: run the verb from a shell with **no
  `CLAUDE_CODE_SESSION_ID`** — `env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py …`. Filed as
  claim-nonce §7.2, DESCRIPTIVE/UNRATIFIED.
- **Handoff dispatch is still unproven** — three stillbirths on 2026-07-27 on top of day-3's five.
  Prefer release-then-`sup-spawn` until someone proves the dispatch path end to end.
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
