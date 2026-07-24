# Proposal: §10.4 `kill supervisor` / `respawn supervisor` tombstone choreography

Status: draft — awaiting manager review

Citation prefixes (same convention as `docs/proposals/sup-spawn-choreography.md:8-9`):
`SPEC:` = `docs/specs/three-tier-command.md`, `CN:` = `docs/specs/claim-nonce.md`,
`fleet.py:` = `bin/fleet.py`, `SPAWN:` = `docs/proposals/sup-spawn-choreography.md`
(branch `design/sup-spawn`). Anchor: `state/journals/tt-build.md:61-65` "REMAINING SCOPE"
item 2. Line numbers for `fleet.py` are as of this worktree's HEAD; SPEC/CN lines are the
current ratified texts.

Ratified rulings honored throughout (SPAWN:452-462, 2026-07-24): gen-0 supervisor body is
`sup|<launch-id>|boot` — no `supervisor`-named record ever exists; `"supervisor"` in
send/kill/respawn positions is a **logical name resolved at verb time via the claim to the
holder's record**.

Label discipline (CN:2000-2002): **G10** is the native-substrate fact *"`claude stop` fires
no Stop hook"*; the duty *"every fleet-initiated stop writes its own outcome record"* is
SPEC §16's **tombstone obligation**. They are cited separately below; the shorthand
"G10 tombstone" in older journals fuses them.

---

## §0. Summary of recommendations

| # | Question | Verdict |
|---|----------|---------|
| Q0 | What already shipped vs. what tt-build claims | `sup-release` **EXISTS** (journal stale); §10.4 arms **UNBUILT** |
| Q1 | Respawn arm | **(A)** graceful: release-steer → stop+tombstone → fresh `sup\|<launch-id>\|boot` body; **abort** if steer fails (ruling 1) |
| Q2 | Kill arm | **(A)** arm-1 self-release-steer bounded by new `SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0`; arm-2 fall-through stop+tombstone into documented freeze-then-seize |
| Q3 | Logical-name resolution | **(A)** claim → holder record via the shipped sid-union matchers; refuse on no-claim / corrupt / released / divergent |
| Q4 | Interaction matrix | handoff-in-flight and limited-parked = **refusals**; husk/autoclean/archive = **sequenced no-ops** via shipped holder-alone gates |
| Q5 | Failure modes | ten enumerated, each with operator surface + recovery |
| Q6 | Test plan | red-first list, five fault-injection targets |

Operator rulings needed: **2** (respawn steer-failure disposition; kill of a limited-parked
holder).

---

## §1. Q0 — what exists today, and which journal claims were stale

The task and `state/journals/tt-build.md:61-65` required verification of the claim that
`cmd_sup_release` "does NOT exist yet". Verified against `bin/fleet.py` in this worktree:

**Shipped (the claim-nonce build, merge `2d58eba`):**

- `cmd_sup_release` exists at fleet.py:9871-9925. Precondition is continuity proof:
  `_require_claim_holder(sid, nonce=..., verb="sup-release", mint=False)` (fleet.py:9901-9903)
  — exactly CN §6.3's plain form (CN:1674-1734). It journals `RELEASED` **first**
  (checkpoint-then-act, fleet.py:9906-9912), then rewrites — never deletes —
  `supervisor/INCARNATION` to the literal released key set of CN:1679-1682
  (fleet.py:9913-9921). No `--force`/`--confirm-inc` (deleted per CN:1718-1734; parser
  deliberately omits them, fleet.py:11127-11140).
- CLI wiring: `sub.add_parser("sup-release", ...)` fleet.py:11135-11140; dispatch
  fleet.py:11255-11256.
- The B6 boot-side guard is **built**: `supervisor_claim_decision` rule 1 refuses a
  `released` record whose `released_by_sid` is still roster-live (fleet.py:9088-9091) —
  the prerequisite SPEC:1224-1229 filed against claim-nonce is met on the boot side.
- The limited-holder branch is built: `_holder_is_limited` (fleet.py:8990-9023) feeds the
  `limit-transfer` arm (fleet.py:9097-9120, CN §6.1 row 1c).
- Generic tombstone plumbing: `write_tombstone_outcome(name, sid, kind)` fleet.py:7809-7813,
  `TOMBSTONE_KINDS = ("killed", "interrupted", "stopped")` fleet.py:7725; already called by
  kill (fleet.py:5053, rationale comment fleet.py:4959) and respawn `--force`
  (fleet.py:4767-4771).

**Stale journal claims (tt-build.md:61-65), explicitly:**

1. *"`sup-release` (cmd_sup_release) does NOT exist yet"* — **STALE.** It exists, is
   parser-registered, and is dispatched (cites above). SPEC §10.4's own grep receipt
   (SPEC:1170-1172, → 0) is pinned at a pre-merge commit, so the receipt itself has not
   rotted, but it no longer describes HEAD.
2. *"needs continuity"* — **CORRECT and satisfied**: the shipped verb requires the holder's
   nonce. Which is precisely why B5 stands: the **killer still cannot call it** (§3 below).
3. *"Two arms w/ bounded transition"* — **STILL TRUE / UNBUILT.** There is no
   `T_release` constant (fleet.py:8458-8460 has only `SUPERVISOR_CLAIM_STALE_SECONDS =
   3600.0` and `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0`), no release-steer logic in
   `cmd_kill`/`_cmd_kill_native` (fleet.py:5079-5114 / 4954-5076), no logical-name
   resolution in either verb (they resolve `args.name` literally against the registry), and
   no supervisor choreography in `cmd_respawn`/`_cmd_respawn_native`
   (fleet.py:4907-4947 / 4669-4904) beyond the `_supervisor_gate` policy check
   (fleet.py:4922, 5095).

**What §10.4 still needs on top of the shipped verb** — the delta this proposal designs:
(a) the verb-time logical-name resolver (§4); (b) kill arm-1 steer + bounded wait + arm-2
fall-through (§3); (c) the respawn choreography as release-steer + fresh boot body (§2);
(d) the caller-side B6 gate — confirm the old body roster-gone before any successor boots
(SPEC:1224-1229 obliges *callers*, not just the boot rule); (e) the refusal arms of the
interaction matrix (§5).

---

## §2. Q1 — respawn arm: body change under the same claim

### What the ratified texts fix

- SPEC:1155-1160: respawn is a body change routed through the claim-nonce respawn path;
  the fresh body "holds no generation and boots via `sup-boot`", which "resumes if it can
  prove continuity, else seizes once the heartbeat is stale, else takes an explicit release
  (claim-nonce §5.10(b))". Verbatim: "A `respawn` that silently re-claimed would
  reintroduce the two-bodies hole."
- CN:1568-1572 (§5.10(b)): "A respawned body holds no generation and cannot present one."
  Silent continuity is not offered.
- SPEC:1159: the old body gets a tombstone (G10: no Stop hook fires, so the verb writes the
  outcome record itself) **and** the claim transition is journaled.

A respawned body therefore has exactly one non-pathological door into the claim: **rule 1b**
— boot off a cleanly released record (CN:1585-1593; boot-shape table CN:1708-1716: released
→ `claim` fresh, journal `BOOT`, no `SEIZED`, no page). It cannot `resume` (no nonce), and
`seize` costs the full `SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0` (fleet.py:8458) freeze
window. Any respawn choreography that does not first obtain a released record buys the
up-to-one-hour hole by construction.

### Options

**(A) Graceful respawn = release-steer, stop+tombstone, dispatch fresh boot body.**
Sequence below. On steer failure, **abort** — leave the body alive, exit non-zero.
**(B) Bare body swap** — stop + tombstone, dispatch successor, let it freeze-then-seize.
(rejected — deliberately opens the 3600 s hole for a *planned* operation; CN:1725-1726
gives the planned-stop doctrine as release-then-stop precisely to avoid this)
**(C) Carry the nonce to the successor so it can `resume`.**
(rejected — CN:1568-1572 forbids it: "nothing a fresh body could present would be
unavailable to a wrong one"; also CN §6.5 bans any env channel, CN:1761-1777)

### Recommended: (A) — exact choreography

1. **Resolve** `"supervisor"` → holder record (§4). Refuse if no live claim.
2. **Gate + guards**: `_supervisor_gate("respawn", nonce=...)` stays (fleet.py:4922);
   refuse if handoff in flight or holder limited-parked (§5).
3. **Release-steer**: deliver a `sup-release` steer turn to the holder body — a `send`
   instructing it to run `fleet sup-release --reason "respawn <why>" --nonce <its own>`
   and exit. The body holds its own nonce; B5 is not violated because the *holder*
   performs the release (SPEC:1175-1179 pattern, borrowed from the kill arm).
4. **Bounded wait**: poll `supervisor/INCARNATION` for `state == "released"` for at most
   `SUPERVISOR_RELEASE_TIMEOUT_SECONDS` (§3 defines it). An immediate `send` refusal
   (G9 `FleetCliError`, SPEC:1195-1196) or timeout ⇒ **abort** (ruling 1): print which
   phase failed, leave the body running, rc ≠ 0. Unlike kill, respawn has no mandate to
   destroy a body that won't cooperate — the operator asked for a context reset, not a
   termination at any cost. (Kill's "never blocks indefinitely" contract, SPEC:1198, is
   about kill.)
5. **Stop + tombstone**: stop the old body via the captured `native_short_id` (ND-1
   pattern, fleet.py:5003-5029), then `write_tombstone_outcome(name_old, old_sid,
   "stopped")` — same kind respawn `--force` already writes (fleet.py:4767-4771). SPEC §16
   tombstone obligation discharged; G10 is why nothing else would have written it
   (SPEC:583-584).
6. **Caller-side B6 gate**: re-fetch the roster and confirm `old_sid` gone before
   dispatching the successor; grace-sleep + refetch on reported-success-still-live, abort
   if still live — the exact loop `_cmd_respawn_native` already runs (fleet.py:4772-4789).
   Rule 1 (fleet.py:9088-9091) would refuse the successor's boot anyway, but SPEC:1224-1229
   obliges automated callers to gate themselves: "the graceful-`kill` arm ... is only safe
   once the old body is confirmed roster-gone".
7. **Dispatch fresh body** through `dispatch_bg` (SPEC:1064-1069 — no hand-rolled argv),
   registry name `sup|<launch-id>|boot`. Grounding: rule 1b mints a *fresh* claim — new
   incarnation, lineage minted at first fresh claim (CN §6.2, CN:1654-1672) — so the body
   is a new launch with no predecessor token or HANDSHAKE, which is exactly the ratified
   gen-0 shape (SPAWN:452-462(i)); the `successor` role segment is reserved for the
   token-verified handoff path (CN §6.4). The name must be supervisor-shaped for the
   `_require_claim_holder` `FLEET_WORKER` exemption (SPEC:1116-1123;
   `_is_supervisor_shaped`, fleet.py:1321-1327) — `sup|<launch-id>|boot` matches the
   family regex (SPAWN:66-68).
8. **Task re-composition**: the new body does NOT get `compose_prompt`'s worker
   carry-over (journal + drained mailbox, fleet.py:4819-4827) as its identity; it gets the
   **sup-spawn first-turn boot ritual** (SPAWN §4): run `fleet sup-boot`, honor verdicts
   `claim`/`refuse`/`freeze` with the `SUP-BOOT-*` terminal contracts (SPAWN:262-265).
   Expected verdict: `claim` fresh, reason *predecessor released cleanly* (CN:1708-1716).
   Supervisor state lives in `supervisor/JOURNAL.md`, GOALS, and the claim files — not in a
   worker journal — so re-seeding from durable artifacts is the §3.5.4 doctrine
   (SPEC:508-535), not a loss.
9. **Nonce/generation across the swap**: none carried. Old generation dies with the
   released record (released key set removes `nonce_hash`/`nonce_seq`, CN:1679-1682); the
   new body mints its own generation at boot, `nonce_seq = 1` (CN:1191, 1217-1220).
10. **Claim transition journaling**: satisfied with **zero new journal kinds** — the
    holder's own `sup-release` writes `RELEASED` (fleet.py:9906-9912, CN:1684-1686) and the
    successor's boot writes `BOOT` (CN:1708-1716). No five-list surgery (CN §4.7) needed.

**Failure midway (tombstone written, dispatch fails)**: the released record is the durable
recovery point. Roll the registry back exactly as `_cmd_respawn_native` does on dispatch
failure (fleet.py:4862-4880); the claim stays `released`, which the status line must and
does surface — *"SUPERVISOR: claim `<inc>` released `<age>` ago — boot one
(`fleet sup-boot`)"* (CN:1688-1701). Operator recovery: `sup-spawn` (or any `sup-boot`)
lands on rule 1b. No corruption, no freeze window, no dual-body risk.

---

## §3. Q2 — kill arm: terminate + release, but the killer cannot release (B5)

### What the ratified texts fix

- B5 (MAJOR), SPEC:1161-1172 verbatim: "`kill supervisor` = terminate the body **and
  release the claim** — but the release cannot be performed *by the killer*". `sup-release`
  requires the holder's current nonce; CN §6.3 deleted the non-continuity escape.
- Arm 1, SPEC:1175-1179 verbatim: "`kill supervisor` **steers the body to release
  itself** — it delivers a `sup-release` turn to the supervisor (which holds its own
  nonce), waits **at most `T_release`** for `supervisor/INCARNATION` to read `released`,
  then stops the body."
- ND3 (MINOR), SPEC:1181-1198: arm 1 is bounded; the shipped handoff bound
  `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0` (fleet.py:8459) "is the precedent for its
  shape"; immediate `send` refusal fails over at once; on timeout **or** refusal, kill
  "stops the body anyway and falls through to arm 2 — announcing which arm it took";
  "kill never blocks indefinitely".
- Arm 2, SPEC:1200-1205: bounded-freeze-then-seize — claim-nonce incident 3 exactly;
  freeze until the heartbeat ages past `SUPERVISOR_CLAIM_STALE_SECONDS = 3600` s, then a
  successor `seize`s (fleet.py:9152-9156). "The design **accepts and documents it** for
  this arm rather than pretending the killer can release."
- Both arms, SPEC:1206-1208: reuse the tombstone obligation; "never a killer-side release
  the caller cannot perform".

### What the shipped `sup-release` provides vs. what §10.4 adds

Shipped: the *release primitive*, callable only by the holder with its nonce (§1). The
boot-side B6 refusal (fleet.py:9088-9091). The freeze/seize arms and their single
threshold (fleet.py:9140-9156).
§10.4 adds: the *orchestration* — kill's steer, the bounded wait, the fall-through, the
arm announcement, and the tombstone at the right point in each arm. None of that exists in
`_cmd_kill_native` today (fleet.py:4954-5076 is target-agnostic).

### Options

**(A) Two phases per SPEC, new constant `SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0`,**
poll INCARNATION, fall through on refusal/timeout, announce the arm.
**(B) Reuse `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS` directly for the wait.**
(rejected — SPEC:1191 offers it as the precedent *for the shape*, not the same knob; tying
kill's patience to handoff's would couple two unrelated tunables. Same 300.0 value, own
name.)
**(C) Skip arm 1, always arm 2.** (rejected — throws away the clean-boot path SPEC:1175-1179
mandates and makes every kill cost up to an hour)

### Recommended: (A) — the two phases, concretely

**Phase 1 — graceful self-release-steer (bounded `T_release`):**
1. Resolve `"supervisor"` → holder record (§4); `_supervisor_gate("kill", ...)`
   (fleet.py:5095) and the launch-in-flight guard (fleet.py:5102-5105) stay.
2. Interaction refusals first (§5): handoff in flight; limited-parked holder (ruling 2).
3. Deliver the `sup-release` steer turn (a `send` to the resolved record's name). An
   immediate refusal — G9 suspicious-roster `FleetCliError` (SPEC:1195) or any send-path
   refusal — fails over to phase 2 **without waiting**.
4. Wait at most `SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0` (new constant beside
   fleet.py:8458-8460), polling `read_incarnation()` for `state == "released"`.
5. On `released`: stop the body (captured short-id, ND-1), verify roster-gone
   (B6 — SPEC:1179, 1231-1232: "stop the body, *then* let a successor boot"), then
   `write_tombstone_outcome(name, sid, "killed")` and mark the record dead
   (kill's existing unconditional-dead semantics, fleet.py:5055-5074).
   Operator surface: terminal line **`SUP-KILL-RELEASED <inc>`** — claim released, record
   dead, a successor `sup-boot` lands on rule 1b immediately. (Terminal-contract style per
   SPAWN:262-265.)

**Phase 2 — bounded-freeze-then-seize (arm-1 timeout/refusal, or body already gone):**
1. Stop the body anyway (skip if roster already shows it gone) and write the same
   `"killed"` tombstone — SPEC:1204-1205 assigns the tombstone to this path explicitly.
2. Leave the claim untouched. Do **not** attempt any killer-side release (B5) and do not
   touch `heartbeat_at`.
3. Operator surface: terminal line **`SUP-KILL-FROZEN <inc> — claim frozen; successor can
   seize after <SUPERVISOR_CLAIM_STALE_SECONDS>s stale`** plus the reason phase 1 was
   skipped or failed (refusal text or "T_release expired"). The announcement is normative:
   SPEC:1196-1198 — "announcing which arm it took, because the two have materially
   different recovery costs (clean successor boot vs. up-to-one-hour freeze)".
4. Recovery is exactly incident 3 (CN:1727-1731): below the hour every `sup-boot` verdicts
   `freeze` ("never seize on ambiguity", fleet.py:9143, 9155-9156); past it, `seize` with a
   `SEIZED` entry and a re-minted lineage (CN:1666).

**Claim transition journaling per arm**: arm 1 — `RELEASED` (by the holder) then the
successor's `BOOT`; arm 2 — nothing at kill time (the claim did not transition), the
eventual seizure writes `SEIZED`. Zero new journal kinds in either arm.

---

## §4. Q3 — logical-name resolution: `kill supervisor` / `respawn supervisor`

### Options

**(A) Claim → holder record via the shipped sid-union matchers**, shared with the Q2
resolver SPAWN already designs for `send` (SPAWN:148, 152-153, 340 — "one resolver ...
later reused by §10.4's `kill supervisor` / `respawn supervisor` arms").
**(B) Fall back to a registry record literally named `supervisor` when no claim exists.**
(rejected — ratified ruling: no `supervisor`-named record ever exists, SPAWN:452-462(i);
SPEC §10.3's `RESERVED` refusal at `validate_name` makes the literal name uncreatable by
ordinary paths, SPEC:1142-1147)
**(C) Resolve to the most recent supervisor-shaped record.** (rejected — shape ≠ holdership;
a retired successor husk is supervisor-shaped and dead, §7.2 B9 direction SPEC:915-920)

### Recommended: (A) — mechanics and edge behavior

Resolution at verb time: `read_incarnation()` → claim; find the registry record whose
`session_id ∪ retired_sids` contains the claim's holder sid — the union match
`_record_is_supervisor_claim_holder` / `_caller_holds_supervisor_claim` already implement
(fleet.py:1935+, 1878-1932; the union bridges fork-steer restamp lag, fleet.py:1855).

| Claim state | Behavior |
|---|---|
| No claim file | **Refuse**, rc 2: "no supervisor claim — nothing to kill/respawn; `fleet sup-spawn` boots one". Never guess a target. |
| Live claim, holder record found | Resolve to that record, whatever its name (`sup\|…\|boot`, `sup\|…\|successor`). Proceed. |
| Live claim, **no matching record** | **Refuse**, rc 2, naming both sides ("claim `<inc>` holder sid `<sid>` matches no registry record — run `fleet doctor`"). Registry/claim divergence is never auto-repaired by a destructive verb. |
| **Corrupt / unreadable claim** | **Refuse**, rc 3 (freeze-style): "never decide blind" — the `supervisor_epoch_check` doctrine (SPEC:587-609; fleet.py:9140-9143 same posture). Surface: run `fleet doctor`. |
| **Released claim** | **Refuse**, rc 2: kill — "already released; any leftover body is an ordinary worker — kill it by its real name"; respawn — "no holder to respawn; `fleet sup-spawn`". Double-kill therefore idempotently refuses (§6.i). |

`"supervisor"` stays purely logical in these positions — consistent with the same resolver
in `send` (SPAWN:340), one implementation, three call sites.

---

## §5. Q4 — interaction matrix

Rows = the §10.4 operations; columns = the five neighbors named by the task. Legend:
**REFUSE** (verb exits non-zero, nothing mutated), **SEQ** (sequenced — ordering guarantees
make it safe), **NO-OP** (neighbor's own gates already exclude the record).

| | handoff in flight | holder limited-parked | husk sweep | autoclean | archive exemption (§7.2 holder-alone) |
|---|---|---|---|---|---|
| **kill arm 1** | REFUSE | REFUSE (ruling 2) | SEQ | SEQ | SEQ |
| **kill arm 2** | REFUSE | REFUSE (ruling 2) | NO-OP (protected) | NO-OP | NO-OP (protected) |
| **respawn** | REFUSE | REFUSE | SEQ | SEQ | SEQ |
| **tombstone write** | n/a (never reached) | n/a | SEQ (enables later sweep) | SEQ | SEQ (satisfies outcome-record gate) |

**Handoff in flight (pending HANDSHAKE / minted `handoff_token_hash`, CN §6.4) — REFUSE.**
A kill or respawn mid-handoff races the token-verified successor: the boot decision already
refuses when the journal names a fresher incarnation (transition-in-flight arm,
fleet.py:9144-9151); the verbs adopt the same posture one step earlier. Surface: "handoff
to `<inc>` in flight — `fleet sup-handoff-complete` or `sup-handoff-abort` first"
(abort verb unchanged per CN:1736-1759).

**Holder limited-parked (`status=="limited"` + horizon, fleet.py:8990-9023).**
- *Kill*: arm 1 is structurally impossible — fleet refuses to steer a `limited` worker
  (ND6 receipt, SPEC:373-380) — so kill degrades to arm 2, destroying the fast
  `limit-transfer` path (CN §6.1 row 1c runs ahead of the roster guard *because the parked
  body is roster-live*, fleet.py:9097-9120; kill makes it roster-gone-with-fresh-heartbeat
  ⇒ plain freeze, fleet.py:9155-9156) and buying the hour hole for nothing. **REFUSE**,
  pointing at the sanctioned paths: a successor `sup-boot` (verdict `limit-transfer`,
  journal `LIMIT-TRANSFER`, no wait) or `fleet resume-limited` after the horizon.
  B5-on-a-new-path (SPEC:390) — no other actor may release for a limited-parked holder —
  reinforces refusal. Flagged as **ruling 2** because §10.4 itself is silent on this cross.
- *Respawn*: **REFUSE** — SPEC:388: a bare respawn against a limited body yields `freeze`
  not `seize`; the fallback machinery is driven from outside by the interface tier
  (SPEC:356-507, ND6), and §3.5.4 already defines the limit-triggered body change. Respawn
  would be a worse duplicate of a designed path. Not a ruling — the spec settles the
  sanctioned route.

**Husk sweep (fleet.py:6039-6167).** The sweep's protected set includes every sid of the
current live claim-holder record under any name (fleet.py:6113-6116). Kill arm-2 leaves
the claim naming the dead body ⇒ the corpse is **protected** (NO-OP) until a successor
seizes or the operator resolves the claim — after which it is an ordinary husk and is swept
(B9 direction, SPEC:915-920). Kill arm-1 / respawn release the claim first ⇒ the dead
record is unprotected and sweepable on the normal cadence (SEQ). No refusal needed in
either direction; ordering does the work.

**Autoclean (fleet.py:6204-6293).** Tier 1 archive-TTL and tier 2 husk sweep inherit the
gates above; tier 3 `_expire_tombstones` is opt-in and only pops the registry tombstone
(fleet.py:6169-6199). Autoclean is structurally exempt from `_supervisor_gate`
(no operator sid env, fleet.py:9418-9420) — safe, because protection lives in gate 0 /
the sweep's protected set, not in the gate. SEQ/NO-OP throughout.

**Archive exemption (§7.2 holder-alone, SPEC:903-913; amended 2026-07-24, built
`5a8860b` — note: the task brief attributed the amendment commit as `6a25d10`; the spec's
own amendment text SPEC:906-910 cites `5a8860b`).** `_archive_eligible` gate 0 protects
the current live claim-holder under any name, holder alone, roster-live or not
(fleet.py:5395-5398). Kill arm-2 corpse: still the holder ⇒ exempt (NO-OP) — correct, its
tombstone must survive until the claim resolves. Arm-1/respawn corpse: claim released ⇒
no record is holder ⇒ ordinary archive path; the `"killed"`/`"stopped"` tombstone outcome
satisfies the no-outcome-record gate (fleet.py:5413, 7813), so the record ages out on TTL
normally (SEQ). B1 and B9 both land exactly as §7.2 intends.

---

## §6. Q5 — failure modes

Each: what breaks → operator surface → recovery.

a. **Steer refused immediately** (G9 suspicious roster / send-path `FleetCliError`,
   SPEC:1195). Kill: instant arm-2 fall-through, `SUP-KILL-FROZEN` names the refusal.
   Respawn: abort (ruling 1), body untouched. Recovery: investigate roster (`fleet
   doctor`), retry; or accept the freeze hole knowingly (kill again — resolver still sees
   the live claim).
b. **Steer accepted, body never releases within `T_release`** (wedged, or errored inside
   the turn — indistinguishable from slow, SPEC:1181-1189). Same surfaces as (a) with
   "T_release expired". Recovery: kill's arm 2 self-documents the wait; respawn abort
   leaves the operator to peek the body (`fleet peek`) and decide.
c. **Release written but body fails to exit** (accepted turn, ran the verb, hung before
   stopping). The B6 window is open: INCARNATION reads `released` while the releaser is
   roster-live. Boot-side rule 1 refuses any consumer (fleet.py:9088-9091); kill proceeds
   to stop the body anyway (arm-1 step 5) and only then declares success. Surface if the
   stop then fails verification: kill's existing warn-and-rc-1 (fleet.py:5063-5074) plus
   an explicit B6 warning ("do NOT sup-boot until roster shows `<sid>` gone"). Recovery:
   re-run the stop / wait for roster truth; rule 1 holds the door shut meanwhile.
d. **Arm-2 stop fails** (body survives the stop attempt). Record marked dead with warning,
   rc 1 (kill's unconditional-dead precedent, fleet.py:5055-5074). The claim's heartbeat
   keeps refreshing if the body is genuinely alive ⇒ every `sup-boot` refuses on the
   roster-liveness guard (fleet.py:9121-9123) — fail-closed, no dual body. Recovery:
   manual stop; `fleet doctor` shows the live-sid/dead-record divergence.
e. **Tombstone written, successor dispatch fails** (respawn step 7 blows up). Registry
   rolled back per fleet.py:4862-4880; claim remains `released` — the durable, boot-ready
   state. Surface: rc 1 + the released status line (CN:1700-1701). Recovery: `fleet
   sup-spawn` (rule 1b). No retry loop inside the verb.
f. **Crash between `RELEASED` journal and INCARNATION rewrite** inside `sup-release`
   (checkpoint-then-act order, fleet.py:9906-9921). Journal says released; claim is still
   live-shaped with the old heartbeat. Boot decisions: roster-gone + fresh beat ⇒ freeze
   (fleet.py:9155-9156); the journal/claim mismatch is visible in `sup-status`. Recovery:
   holder still owns its nonce if alive (re-run `sup-release`); if dead, staleness resolves
   it in ≤ 3600 s. Documented, bounded, no guard bypassed.
g. **Corrupt INCARNATION at resolve time.** Refuse rc 3, never decide blind (§4). Recovery:
   `fleet doctor`; operator inspects/repairs the claim file; no destructive verb touches a
   claim it cannot read.
h. **Claim/registry divergence** (holder sid matches no record, §4 row 3). Refuse rc 2
   naming both sids. Recovery: `fleet doctor`, manual reconciliation; the verbs never
   auto-repair.
i. **Double kill / kill after release.** Resolver sees `released` ⇒ idempotent refusal
   (§4). No second tombstone, no second dead-marking.
j. **Kill/respawn racing a scheduled beat or a `sup-spawn`** (the automated occupants
   SPEC:1219-1223 adds). The B6 boot-side rule 1 plus the caller-side roster-gone gate
   (§2 step 6, SPEC:1224-1229) close the window from both ends; `one-live-session-per-name`
   (SPEC §16.7) does not help here and is not relied on. Surface: the racing `sup-boot`
   verdicts `refuse`/`freeze` with the standard reasons — no new surface needed.

---

## §7. Q6 — test plan sketch (red-first)

Unit (pure / registry-fixture; pytest per SPEC §12):

1. **Resolver table (§4)**: no claim ⇒ rc 2 + message; corrupt claim ⇒ rc 3; released ⇒
   rc 2 kill-vs-respawn distinct messages; live claim resolves a `sup|x|successor`-named
   record via retired-sid union; live claim + no record ⇒ rc 2 divergence message.
2. **Constant exists and is used**: `SUPERVISOR_RELEASE_TIMEOUT_SECONDS == 300.0`, and the
   kill wait loop reads it (TestInterpreterFloor-style declaration test; guards against
   silently reusing the handshake constant).
3. **Arm-1 happy path**: fixture holder writes `released` inside the window ⇒ stop called
   with captured short-id, `"killed"` tombstone written, record dead, output contains
   `SUP-KILL-RELEASED`.
4. **Arm announcement**: arm-2 output contains `SUP-KILL-FROZEN` + the phase-1 failure
   reason; arm choice is asserted, not incidental (SPEC:1196-1198 is normative).
5. **Respawn success**: new record name matches `_is_supervisor_shaped`; dispatched prompt
   contains the sup-boot ritual, and does NOT contain the old mailbox/journal carry-over;
   no nonce material anywhere in the new body's env or prompt (CN §6.5).
6. **Respawn journaling**: exactly `RELEASED` (holder) — no new journal kinds introduced;
   `--kind` choices list unchanged (CN §4.7 five-lists check).
7. **Matrix refusals**: pending HANDSHAKE ⇒ kill and respawn refuse; `_holder_is_limited`
   fixture ⇒ both refuse with the limit-transfer pointer (pending ruling 2).
8. **Protection ordering**: arm-2 corpse survives `_sweep_husks` and `_archive_eligible`
   (gate 0) while the claim names it; after a fixture seize, both remove it (B1/B9 pair).
9. **Tombstone kinds**: arm-1 and arm-2 ⇒ `"killed"`; respawn ⇒ `"stopped"`; kinds stay
   within `TOMBSTONE_KINDS` (fleet.py:7725).
10. **Parser lint**: no `--force`-shaped release escape reappears on kill/respawn/sup-release
    (CN:2176 "No `--force` form", CN §12 O2).

Fault-injection targets (monkeypatch seams):

F1. `send` raises `FleetCliError` ⇒ kill falls through with **zero** wait (no sleep call);
    respawn aborts, registry unchanged, body's record untouched.
F2. Clock-stepped wait: INCARNATION never flips ⇒ fall-through fires at exactly
    `T_release`, not before/after.
F3. Stop reports success but roster still shows the sid (grace-loop seam,
    fleet.py:4772-4789) ⇒ successor dispatch is NOT reached (caller-side B6 gate); kill
    warns rc 1 with the B6 message.
F4. `dispatch_bg` raises after release+stop (respawn) ⇒ rollback runs, claim file still
    reads `released`, rc 1 (failure-mode e).
F5. `sup-release` fixture that journals `RELEASED` then dies before `write_incarnation`
    ⇒ next boot verdicts freeze, `sup-status` shows the mismatch (failure-mode f).

Integration (haiku worker in temp dir, per SPEC §12): one end-to-end graceful kill — spawn
a fixture holder, kill it, assert `SUP-KILL-RELEASED`, boot a successor, assert rule-1b
`BOOT` journal entry.

---

## Operator rulings needed

> Both items below are genuinely unsettled by ratified text; everything else in this
> proposal is grounded in SPEC §10.4/§7.2, CN §5.10(b)/§6.1/§6.3, or the 2026-07-24
> ratified rulings (SPAWN:452-462) and needs no ruling.

**Ruling 1 — respawn steer-failure disposition.** When the release-steer fails (refusal or
`T_release` expiry), does `respawn supervisor`:
  (a) **abort** — leave the body alive, rc ≠ 0, operator investigates (RECOMMENDED: respawn
      is a convenience reset, not a termination mandate; falling through would destroy a
      live, possibly mid-turn supervisor and buy the 3600 s freeze hole for a
      non-emergency); or
  (b) fall through kill-style — stop + tombstone + fresh boot body that freezes until
      seize (kill's "never blocks" contract extended to respawn).
  Options considered: (b) rejected above; SPEC:1198's never-block contract is written for
  `kill` only, so extending it is an operator call, not a derivation.

**Ruling 2 — `kill supervisor` against a limited-parked holder.** ND6 makes arm 1
impossible (no steer to a `limited` worker, SPEC:373-380), so kill can only take arm 2 —
which converts a roster-live parked holder with a fast `limit-transfer` path
(fleet.py:9097-9120) into a roster-gone freeze of up to 3600 s. Does kill:
  (a) **refuse**, pointing at `sup-boot` (limit-transfer) / `fleet resume-limited`
      (RECOMMENDED: the park is recoverable state; destroying it strictly worsens every
      recovery path); or
  (b) proceed to arm 2 with a loud warning (operator may want the body gone regardless,
      e.g. a poisoned park).
  Options considered: a `--force`-style override for (a) was rejected — it reintroduces a
  two-command destruction of supervisor state, the shape CN:1718-1734 deleted.
