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

**What is owed to you is not the fix — it is the ACCOUNTING.**

> **RULED PROVISIONALLY 2026-07-28 — A: RE-GROUNDED, unanimous 4/4.** See
> `docs/decisions/W9-section7-council-synthesis.md`. The exemption **stays**, re-grounded on the
> sweep's *effect* (a convergent janitorial pass with no dispatch, steer or claim authority) instead
> of on the retired caller's absent sid. Two binding riders: the exemption is carried **explicitly at
> every frame**, never inherited from the call graph; and it is **scoped to the sweep's current
> effect set**, so any new tier re-opens the question.
>
> **CORRECTION + AN OBLIGATION THE RULING INHERITS, 2026-07-28, by `inc-20260727T235933Z-8455`
> (wave 10).** As first raised, this section told you §7 *"exempts `autoclean` unconditionally."*
> **That is not what §7 says.** The finding is break lens `gate-acg-rb`'s MAJOR-1; I re-verified all
> three citations myself against `main` @ `b7c5c85` rather than relaying them, and the lens's own
> line numbers had already rotted — the ones below are measured.
>
> **This is not merely historical now that A is ruled.** The council re-grounded the exemption but
> **never addressed `claim-nonce.md:2174`**, the binding verb taxonomy, which still lists `autoclean`
> in the **Mutating-lifecycle (GATED)** row. **A re-grounding that does not fix `:2174` leaves the
> ratified text exactly as self-contradictory as it is today, with a better paragraph attached.**
> I am treating the `:2174` repair as part of directive 1 ("re-ground §7's decision block in the same
> merge") and have ordered it on the branch. Flagging it here because it is an amendment to
> operator-owned text that the ruling did not itemise.

**§7's ratified text is INTERNALLY AMBIGUOUS about `autoclean`, and its only disambiguator is
dead.** Three places, all in the ratified block:

- `docs/specs/claim-nonce.md:2023` — the decision line reads *"`autoclean` is **structurally**
  exempt."* **"Structurally" is itself the qualification**, not a synonym for "unconditionally."
- `docs/specs/claim-nonce.md:2091-2092` — the one place that says what "structurally" *meant*:
  *"Its own primary **caller** is structurally exempt: the `autoclean` scheduled task has no
  `CLAUDE_CODE_SESSION_ID`, so a caller-identity gate can never fire on it."* The exemption was
  keyed on **the caller's absent sid**. **That caller is retired; the ground is void.**
- `docs/specs/claim-nonce.md:2174` — the same ratified block makes the verb taxonomy **binding**,
  and that taxonomy lists **`autoclean` in the Mutating-lifecycle (GATED) row.**

So the ratified text says *exempt* in one line, *gated* in its binding table, and the sentence that
reconciled them describes a caller that no longer exists.

**The branch resolved that ambiguity in its own favour and then told you the code already matched
the ratification.** It does not; there is no unambiguous ratification to match. I have corrected the
same claim in the branch's own `docs/OPERATOR-GATES.md` entry.

**Question A as originally asked — "does the exemption stay unconditional?" — was the wrong
question**, because it presumed a settled exemption to keep. There was none. The honest question was
*how do you want §7 disambiguated*, and of the three shapes available the council chose the third:

1. ~~**Exempt unconditionally, and say so plainly**~~ — not chosen.
2. ~~**Condition it**~~ — not chosen, and the cost is worth recording so it is not revisited by
   accident: conditioning the sweep on the caller sid matching the claim-holder's does not merely
   "fail for the interface ritual", it **re-breaks the sweep for a fleet with no supervisor** — the
   exact failure this branch fixes and the exact reason the interface ritual runs `autoclean` at all.
3. **Re-scope §7's accounting — keep the behaviour, rewrite what grounds it, and fix `:2174`.**
   **← CHOSEN, unanimous.** The council supplied the new ground. **It did not supply the `:2174`
   repair, and that half is still owed.**

**Two corrections to the risk statement, so you are not ruling on an inflated surface.** I measured
both:

- The exempt surface **does not expire tombstones in practice.** Tier 3 is **default-OFF**
  (`bin/fleet.py:7802`, `expire_tombstones_hours` defaults to `None`) and **neither driver passes
  `--expire-tombstones-hours`** — not the supervisor beat, not the interface ritual. The earlier
  framing implied tier 3 runs.
- `cmd_archive`'s other mutations were **never guarded by §7 alone.** Six independent
  `_archive_eligible` gates run per record: gate 0 (`bin/fleet.py:6905`) protects the live
  claim-holder's record **under any name**, gate 3 (`:6920`) refuses any roster-live record, and
  `_archive_move_and_rm` (`:7049`) skips any sid the roster shows live. A divergent body running the
  sweep **cannot** archive the live supervisor, **cannot** archive a live worker, and **cannot**
  `claude rm` a live sid. The widened surface is real and worth your ruling; it is **not** the
  catastrophe the original framing invited.

Nothing is narrowed while this waits.

## Route B — `sup-recover`, in `docs/specs/graceful-succession.md` (SPEC, unbuilt, dual-lens gated)

> **RULED PROVISIONALLY 2026-07-28 — see `docs/decisions/W9-section7-council-synthesis.md`.**
> A: **RE-GROUNDED** (unanimous). B: **PARTIAL — arm 5 only; arms 3 and 6 not ruled.**
> **The inversion below is RETRACTED as false**, measured independently by two lenses: `cmd_sup_release`
> writes a fresh six-key dict that never copies `handoff_token_hash`, so §5.7 can never fire on the
> released arms, and repairing the handoff makes the refusal *rarer and shorter*, not more frequent.
> **`docs/specs/graceful-succession.md` does not exist on `main`** — it is on `spec/succession-signal`.

Both lenses returned **ESCALATE** independently and both made this their CRITICAL-1:

> **`sup-recover` is refused by the §7 gate on exactly the states it exists to clear.**

Arm 5's precondition — *"claim `released`, releaser still roster-live and untombstoned"* — is
character-for-character `_supervisor_gate`'s unconditional ARM condition. Arms 3, 6 and 8 are
gated too, and **arm 6 is a freshly-parked `limited` supervisor, one of the two walls the ratified
shape names.** `_wedged_release_gate`'s own docstring (`bin/fleet.py:11867`; this doc originally
said `:12183`, **rotted by 316 lines** — corrected 2026-07-28 after all four councilors caught it
independently) says the remedy cannot work there:

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
