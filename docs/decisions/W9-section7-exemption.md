# Operator decision — §7's exemption envelope, asked twice in one wave by two unrelated routes

Raised by `inc-20260727T232026Z-06cf` (wave 9). §7 is operator-owned; the supervisor may not
ratify a narrowing of it, so both halves below are parked rather than decided.

**The two routes arrived independently and neither knew about the other.** That is the reason
to answer them together rather than one at a time.

---

## Route A — `fleet autoclean`'s archive tier (SHIPPED DEFECT, fix built, unmerged)

The sweep moved onto the tiers' beats when the Windows Scheduled Task was retired. It has been
refused on **every run since**, measured twice:

```
autoclean: archive tier failed: archive: refusing -- a supervisor claim
(inc-20260727T184603Z-f054) is held and fresh, and this call did not prove continuity on it
(claim-nonce §7).
autoclean: husks_removed=0 husks_deferred=0 tombstones_expired=0 errors=1
```

and again from the **interface tier**, which holds no claim at all:

```
autoclean: archive tier failed: archive: refusing -- a supervisor claim
(inc-20260727T232026Z-06cf) is held and fresh, and this call did not prove continuity on it
```

**Both callers are refused, and the interface caller cannot be repaired by `--nonce`** — it holds
no claim, so it has no generation to present. `fleet autoclean` has no `--nonce` flag either.

`fix/autoclean-archive-gate` @ `e4a0730` repairs it structurally (`cmd_archive(...,
as_autoclean_tier=False)`; the gate call becomes `if not as_autoclean_tier`; four executable
lines) and explicitly did **not** narrow §7: the armed-verb set is unchanged, `fleet archive` as a
verb is refused exactly as before, and nothing reaches the parameter from `build_parser`.

**What is owed to you is not the fix — it is the ACCOUNTING.** §7's ratified decision block
exempts `autoclean` unconditionally, but it priced that exemption on *"the scheduled task has no
session id."* **That ground no longer exists**: both drivers are now sessions with a sid, and the
supervisor beat runs *only* while a fresh claim is held, which is the exact arming condition.

**Question A: does `autoclean`'s §7 exemption stay unconditional now that its stated grounds are
gone?** Nothing is narrowed while this waits.

## Route B — `sup-recover`, in `docs/specs/graceful-succession.md` (SPEC, unbuilt, dual-lens gated)

Both lenses returned **ESCALATE** independently and both made this their CRITICAL-1:

> **`sup-recover` is refused by the §7 gate on exactly the states it exists to clear.**

Arm 5's precondition — *"claim `released`, releaser still roster-live and untombstoned"* — is
character-for-character `_supervisor_gate`'s unconditional ARM condition. Arms 3, 6 and 8 are
gated too, and **arm 6 is a freshly-parked `limited` supervisor, one of the two walls the ratified
shape names.** `_wedged_release_gate`'s own docstring (`bin/fleet.py:12183`) says the remedy
cannot work there:

> **NO CONTINUITY PATH** … `_nonce_presentation` would return None for every caller and every
> value: there is no generation to present because there is no claim to prove continuity ON.
> **Offering `--nonce` here would be a named remedy that always fails, which is the exact defect
> the 2026-07-26 ruling (R2) forbids writing into a refusal.**

`claim-nonce` §7.2 already records the matching debt: *"**no in-fleet disarm** … An in-fleet
disarm path is owed work; the human-at-a-shell exit is explicitly NOT ratified."* **Arm 5 IS that
owed path, and the guard it exists to relieve refuses it.**

The break lens added the sharper form, which I am carrying because it inverts the obvious reading:
**repairing the handoff makes this MORE frequent, not less.** Every in-flight handoff and every
successor that dies mid-boot leaves a `handoff_token_hash` on a `held` claim, and §5.7 mandates
refusal there. So the one-command front door is **strictly less capable than the three-command
sequence it was specified to replace, in exactly the class of state it was specified for** — the
older `sup-spawn` → `sup-boot` route still works, because `_supervisor_boot_decision` never reads
`handoff_token_hash`.

**Question B: may `sup-recover` be exempted from §7's arming (or gated differently), and does the
§5.7 handoff-token refusal stay?** A builder cannot start until this is answered — an exemption
**widens** the disarm envelope, which is yours, not mine.

---

## Why these are one decision

Both ask the same thing: **when the fleet's recovery machinery is itself gated by the guard it
exists to recover from, which side gives?** A is that question about a shipped sweep; B is the
same question about an unbuilt front door. Answering them separately risks two different answers
to one principle.

## What I am NOT asking

I am not asking you to approve either fix's code. A is built and gated; B is unbuilt by design
(GATE THEN BUILD). Nothing is narrowed while this docket entry stands.
