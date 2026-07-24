# Proposal: §10.4 `kill supervisor` / `respawn supervisor` tombstone choreography

Status: **BUILT** 2026-07-24 on branch `build/sup-tombstone` (pending operator ratification of the
two council rulings). Everything below is the design of record and was built as specified, with the
build-time notes collected in the closing section "Build record".

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

Operator rulings: **2 requested — both RULED 4–0** (council 2026-07-24: Cassandra/risk,
Brick/delivery, Vista/strategy, Mercer/incident-response) for the recommended options, with
binding merged conditions folded into §2/§3/§5/§7 below; queued for operator ratification.
See the final section for the full ruling record.

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
   (G9 `FleetCliError`, SPEC:1195-1196) or timeout ⇒ **abort** (ruling 1, RULED 4–0):
   leave the body running, rc ≠ 0. Unlike kill, respawn has no mandate to destroy a body
   that won't cooperate — the operator asked for a context reset, not a termination at any
   cost. (Kill's "never blocks indefinitely" contract, SPEC:1198, is about kill.)
   **Ratified abort conditions (council, binding):**
   - Distinct grep-able terminal line **`SUP-RESPAWN-ABORTED <phase>: <reason>`**, naming
     the failed phase (steer-refused / T_release-expired / stop-precondition), and printing
     the escalation commands verbatim: `fleet peek <holder>` / `fleet kill supervisor` then
     `fleet sup-spawn`.
   - The abort output **WARNS that the steer may still land asynchronously**: a slow body
     may complete `sup-release` after the timeout. The operator must check `sup-status`
     before acting on the abort. A re-run of `respawn supervisor` after such a late release
     lands on the resolver's released-claim refusal arm (§4) — that landing spot is a
     tested contract (§7 test 1/11).
   - Abort is **proven side-effect-free**: registry, claim file, and the body's record are
     byte-identical after abort; respawn's abort path shares **no fall-through branch**
     with kill's arm-2 code. Fault-injections F1/F2 (§7) are RATIFICATION-BLOCKING.
   - Abort fires at exactly `SUPERVISOR_RELEASE_TIMEOUT_SECONDS` — bounded, never an
     unbounded hang.
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
5. **Ratified build requirement (council, Mercer — binding, general to any arm-2/freeze
   window):** during any freeze window the *persistent* status surfaces — `sup-status` and
   the statusline — must show **"claim held by dead sid, seizable in `<remaining>`s"**
   (holder roster-gone, heartbeat age vs `SUPERVISOR_CLAIM_STALE_SECONDS`). The one-shot
   `SUP-KILL-FROZEN` line is not sufficient: the state must be diagnosable without
   scroll-back. This extends `supervisor_status_line` exactly as CN:1688-1701 already
   obliges it to learn the released state — same function, one more branch (§7 test 12).

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
| **Released claim** | **Refuse**, rc 2: kill — "already released; any leftover body is an ordinary worker — kill it by its real name"; respawn — "no holder to respawn; `fleet sup-spawn`". Double-kill therefore idempotently refuses (§6.i). **Ratified landing-spot contract (council, ruling-1 condition):** this arm is also where a re-run lands after a respawn abort whose steer released *late* (async completion post-timeout, §2 step 4) — tested explicitly (§7 test 11). |

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
  ⇒ plain freeze, fleet.py:9155-9156) and buying the hour hole for nothing. **REFUSE**
  (ruling 2, RULED 4–0). B5-on-a-new-path (SPEC:390) — no other actor may release for a
  limited-parked holder — reinforces refusal.
  **Ratified refusal-message conditions (council, binding):** the refusal prints ALL
  escapes verbatim and inline — it never reads as a dead end:
  - `fleet sup-boot` — successor claims via `limit-transfer` immediately (no wait);
  - `fleet resume-limited <name>` — after the recorded horizon passes;
  - **poisoned-park sequence** — boot a successor via `limit-transfer` first; the demoted
    body is then an ordinary worker, killable by its REAL registry name. The message
    states the cost of killing *pre*-transfer: a plain freeze of up to
    `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s).
  The refusal performs **ZERO mutations** — no tombstone, no dead-marking, no heartbeat
  touch — asserted with the message text in §7 test 7.
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
   Respawn: abort (ruling 1) — `SUP-RESPAWN-ABORTED steer-refused: <reason>` with the
   escalation commands (§2 step 4), body untouched. Recovery: investigate roster (`fleet
   doctor`), retry; or accept the freeze hole knowingly (kill again — resolver still sees
   the live claim).
b. **Steer accepted, body never releases within `T_release`** (wedged, or errored inside
   the turn — indistinguishable from slow, SPEC:1181-1189). Kill: arm 2 with "T_release
   expired". Respawn: `SUP-RESPAWN-ABORTED T_release-expired: ...` + the async-late-release
   warning — the body may still complete `sup-release` after the abort; check `sup-status`
   before acting; a re-run then lands on the resolver's released-claim refusal (§4).
   Recovery: kill's arm 2 self-documents the wait; respawn abort leaves the operator to
   peek the body (`fleet peek <holder>`) and decide.
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
7. **Matrix refusals** (ruling-2 conditions, binding): pending HANDSHAKE ⇒ kill and
   respawn refuse; `_holder_is_limited` fixture ⇒ both refuse, and the kill refusal:
   (i) performs **zero mutations** — registry snapshot byte-identical, no tombstone
   written, no dead-marking, no heartbeat touch; (ii) message text contains all three
   escapes verbatim (`fleet sup-boot`, `fleet resume-limited <name>`, the poisoned-park
   sequence) and the 3600 s pre-transfer cost.
8. **Protection ordering**: arm-2 corpse survives `_sweep_husks` and `_archive_eligible`
   (gate 0) while the claim names it; after a fixture seize, both remove it (B1/B9 pair).
9. **Tombstone kinds**: arm-1 and arm-2 ⇒ `"killed"`; respawn ⇒ `"stopped"`; kinds stay
   within `TOMBSTONE_KINDS` (fleet.py:7725).
10. **Parser lint**: no `--force`-shaped release escape reappears on kill/respawn/sup-release
    (CN:2176 "No `--force` form", CN §12 O2) — and no bypass flag on either ruled refusal
    (council condition 4: flagless forms only, any bypass needs a NEW council ruling).
11. **Abort landing spot** (ruling-1 condition): fixture where the steer's `sup-release`
    completes *after* the abort (late async release) ⇒ re-run of `respawn supervisor`
    lands on the resolver's released-claim refusal arm with the sup-spawn pointer; abort
    output contains `SUP-RESPAWN-ABORTED <phase>:` and the `sup-status`-first warning.
12. **Freeze-window status surface** (council condition 5): fixture claim with holder
    roster-gone + fresh heartbeat ⇒ `supervisor_status_line` (and thus `sup-status` /
    statusline) renders "claim held by dead sid, seizable in `<remaining>`s"; `<remaining>`
    decreases with a stepped clock; branch coexists with the CN:1688-1701 released branch.

Fault-injection targets (monkeypatch seams). **F1/F2 are RATIFICATION-BLOCKING (council,
ruling-1 condition 2).**

F1. `send` raises `FleetCliError` ⇒ kill falls through with **zero** wait (no sleep call);
    respawn aborts with registry, claim file, and the body's record **byte-identical**
    (serialize-and-compare, not field-spot-checks). Structural assertion: respawn's abort
    path shares no fall-through branch with kill's arm-2 (e.g. the arm-2 helper is never
    reached from the respawn call graph in the abort fixture).
F2. Clock-stepped wait: INCARNATION never flips ⇒ kill's fall-through and respawn's abort
    each fire at exactly `SUPERVISOR_RELEASE_TIMEOUT_SECONDS`, not before/after; respawn
    post-abort state byte-identical as in F1 — never an unbounded hang.
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

## Ruling record — council-ruled 2026-07-24, pending operator ratification

> Both dockets ruled **UNANIMOUS 4–0** for this proposal's recommended options (council:
> Cassandra/risk, Brick/delivery, Vista/strategy, Mercer/incident-response; synthesis by
> manager under the operator's standing 4-councilor directive; queued for operator
> ratification). The merged conditions below are **part of the rulings, not suggestions**,
> and are folded into §2 step 4, §3 phase-2 item 5, §4 (released row), §5
> (limited-parked), and §7 (tests 7, 10-12, F1/F2). Everything else in this proposal is
> grounded in SPEC §10.4/§7.2, CN §5.10(b)/§6.1/§6.3, or the 2026-07-24 ratified rulings
> (SPAWN:452-462) and needed no ruling.

**Ruling 1 — respawn steer-failure disposition: (a) ABORT (4–0).** Leave the body alive,
rc ≠ 0, operator investigates. Falling through kill-style was rejected — SPEC:1198's
never-block contract is written for `kill` only; a fall-through would destroy a live,
possibly mid-turn supervisor and buy the 3600 s freeze hole for a non-emergency.
Binding conditions:
  1. Abort surface: grep-able `SUP-RESPAWN-ABORTED <phase>: <reason>`, names the failed
     phase, prints escalation commands verbatim (`fleet peek <holder>` /
     `fleet kill supervisor` then `fleet sup-spawn`), and warns the steer may still land
     asynchronously post-timeout — operator checks `sup-status` before acting. The
     resolver's released-claim refusal arm is the tested landing spot for a re-run after
     such a late release (§4, §7 test 11).
  2. Abort proven side-effect-free: F1/F2 are **RATIFICATION-BLOCKING** — registry, claim
     file, and the body's record byte-identical after abort; respawn's abort path shares
     no fall-through branch with kill; abort fires at exactly
     `SUPERVISOR_RELEASE_TIMEOUT_SECONDS`, never an unbounded hang (§7 F1/F2).

**Ruling 2 — `kill supervisor` against a limited-parked holder: (a) REFUSE (4–0).** The
park is recoverable state; ND6 makes arm 1 impossible (SPEC:373-380) and arm 2 converts a
fast `limit-transfer` (fleet.py:9097-9120) into an up-to-3600 s freeze.
Binding conditions:
  3. The refusal prints ALL escapes verbatim and inline — `fleet sup-boot`
     (limit-transfer), `fleet resume-limited <name>` (after horizon), and the
     poisoned-park sequence (successor via limit-transfer, then the demoted body is an
     ordinary worker killable by its REAL registry name), stating the 3600 s cost of
     killing pre-transfer. Never a dead end. The refusal performs zero mutations — no
     tombstone, no dead-marking, no heartbeat touch — asserted with message text
     (§5, §7 test 7).

**Cross-cutting conditions:**
  4. **No bypass/`--force` flag on either refusal, ever, without a NEW council ruling** —
     the 4–0 votes ratify the flagless forms only (§7 test 10; consistent with
     CN:1718-1734 / CN §12 O2).
  5. **Freeze-window persistent status surface (Mercer, general to any arm-2/freeze):**
     `sup-status` and the statusline must show "claim held by dead sid, seizable in
     `<remaining>`s" during any freeze window — diagnosable without scroll-back, not just
     the one-shot `SUP-KILL-FROZEN` line (§3 phase-2 item 5, §7 test 12).

---

## Build record — 2026-07-24, branch `build/sup-tombstone`

Built red-first against §7. `tests/test_sup_tombstone.py` (§7's 12 + F1–F5 + the flagged gap below),
`tests/test_sup_tombstone_fixwave1.py` (the gate findings), and
`tests/integration/test_sup_tombstone_live.py` (the one end-to-end graceful kill,
`FLEET_LIVE`-gated). Full suite green on **both** interpreters: `py -3.13` and the
`fleet.MIN_PYTHON_VERSION` floor `py -3.10` — **2113 passed, 11 skipped** on each.

*(rs MIN-4 / rb MIN-6: the build slice's first draft of this line said "2 skipped" and the task brief
said 8. The observed figure is **11** on both floors — 6 `test_native_pin` + 3 this slice's live file
+ 2 platform-gated. Corrected rather than left as a number nobody re-ran.)*

**Stale premises this proposal carried, corrected at build time.** Every `fleet.py:` line number in
§1–§6 is from the design worktree's HEAD and had drifted by ~180 lines (the file is now ~11.9k lines;
the claim constants live at `:8634-8635`, not `:8458-8460`). Two of the deltas §1 lists as *needed*
were already shipped:

- **(a) the §4 resolver already exists** as `_resolve_worker_target` (built for `send` by the
  sup-spawn slice, pinned in `tests/test_sup_spawn.py`). §10.4 did **not** re-implement it. It adds a
  *sibling* entry point, `_resolve_supervisor_lifecycle_target`, for one reason: the refusal **grades**
  differ. `send` collapses everything to `FleetCliError` (rc 1), which is right for a message with
  nowhere to go; a destructive verb owes the rc 2 / rc 3 split this proposal specifies, and a message
  that names the next command *for that verb* ("kill it by its real name" is nonsense advice for
  respawn). Implemented as a new `SupervisorLifecycleRefusal(FleetCliError)` carrying `.rc`, with a
  `main()` arm ahead of the generic ones — fleet's existing taxonomy has no rc 2/3 for a verb error
  (1 = generic, 4 = continuity), so re-grading the shared resolver would have changed `send`.
- **(b) §5's protection ordering is already shipped** — the husk sweep's protected set and
  `_archive_eligible`'s gate 0 both key on the live claim holder under any name. §7 test 8 is
  therefore assertion-only, with **no code delta**.

**Council condition 5, and the one honest substitution.** The condition names "holder **roster-gone**",
but `supervisor_status_line` is file-only by mandate (no lock, no roster fetch, no subprocess — it runs
in the SessionStart hook of every Claude Code session on this machine). The built branch
(`_claim_holder_dead_note`) uses the registry's own `status == "dead"` as the liveness proxy, read
lock-free and without quarantining. That is exactly what kill's arm 2 writes before printing
`SUP-KILL-FROZEN`, so the persistent surface tracks the event that creates the freeze window. A body
that died without fleet noticing keeps the pre-existing stale-heartbeat line: the branch **adds** a
surface, it does not replace one. Recorded here rather than silently narrowed.

**The flagged gap, ruled at build time (NOT a council ruling — operator sign-off wanted).** The
sup-spawn fix wave flagged that `respawn` of a **non-holder supervisor-shaped husk** relaunched with
`compose_prompt`'s journal/mailbox carry-over and **no boot ritual**, producing a supervisor-shaped
body that never runs `sup-boot`, holds no claim, and answers to none of the supervisor contracts.
Ruled fail-closed and consistent with §2: *every* supervisor-shaped respawn routes through the
choreography. The husk arm skips the release-steer (there is no claim) but still dispatches a fresh
`sup|<launch-id>|boot` under the sup-spawn boot ritual, so **`sup-boot` makes the claim decision** —
`refuse` if a live claim exists, `claim` if none does. Fleet never infers holdership from a respawn
flag. If the operator prefers "refuse husk respawn, point at `sup-spawn`", that is a one-branch delta
plus two tests (`TestHuskRespawnGetsTheBootRitual`).

**Superseded guard.** The fix wave's fail-closed stub `_refuse_unbuilt_supervisor_lifecycle` (CRIT-2)
is **deleted** — it existed only to hold this door shut until §10.4 landed. Its two load-bearing
properties are inherited verbatim by the new routing and still pinned by the same fault injections:
FI-7 (the holder is caught however it is addressed, never only by the literal name) and FI-7b (an
indeterminate holder verdict fails toward refusal, and only for supervisor-shaped names, so an
unreadable INCARNATION cannot freeze kills of ordinary workers). Its test class was rewritten against
the built behaviour rather than deleted (`TestSupervisorLifecycleRouting`).

**Doc-sync done here:** SPEC §10.4's `[UNBUILT]` tags and its "sup-release does not exist yet"
sentence. The pinned receipts in that section were **not** re-pinned — a receipt is a claim about a
commit, not about `HEAD`. SPEC §13/§18 milestone rows and the `claim-nonce` §7 taxonomy row remain
owed and are **out of this slice's scope** (the taxonomy row is operator-owned).

**Husk-respawn carve-out vs. the ratified carry-over text (rs MIN-5).** `commands/respawn.md:2` and
three-tier SPEC:1513 both describe `respawn` as relaunching **under the same name** with the worker's
journal + drained mailbox carried forward. The husk ruling above deviates from that on exactly one
class of target — supervisor-**shaped** records — which get a fresh `sup|<launch-id>|boot` name and
the boot ritual instead of the carry-over. The deviation is deliberate (a supervisor-shaped body with
no boot ritual holds no claim and answers to none of the supervisor contracts) but it is **not**
covered by any ratified text, and the ratified bodies were **not edited here**. Recorded as a
carve-out and attached to the operator sign-off item below.

---

## Fix wave 1 — dual-lens gate findings (2026-07-24, commit after `fb8e5ab`)

Spec lens `tomb-rs`: CONFORMS-WITH-FINDINGS 0C/3M/5m. Break lens `tomb-rb`: 1C/3M/6m
(`state/journals/tomb-rb.md`). All thirteen fixed; every fix carries a mutate → RED → restore proof
(10/10 RED).

**CRIT-1 — the stop acted on a STALE sid, and the tests could not have caught it.** Both verbs
captured `session_id` *before* the release steer. A steer delivered to an **idle** holder — the
primary intended case, a planned context reset — takes `_cmd_send_native`'s fork-steer branch
(RATIFIED G2b): `_restamp_after_steer` moves `session_id` to a NEW session and retires the old sid.
Everything downstream then used the retired one. `kill` printed `SUP-KILL-RELEASED`, exited 0 and
marked the record dead **while the live fork kept running**; `respawn`'s caller-side B6 gate polled
the retired sid, passed vacuously, and ended with a dead-marked record holding a live session **plus**
a fresh gen-0 body — two live supervisor bodies, the one invariant §10.4 exists to hold. A
dead-record-with-live-session is also the rogue-session class `_cmd_kill_native`'s own ND-1 comment
calls "a C1 CRITICAL, reached through the front door".

The reason 47 tests missed it is worth recording: **every one of them stubbed `_cmd_send_native` into
a no-op and seeded `status="working"`**, so the entire fork-steer branch was untested. The fix
re-fetches the record after the steer resolves (both outcomes) and acts on the current sid union; the
test doubles now call the production `_restamp_after_steer` rather than modelling it, because a double
that drifts from the code it stands in for is how this happened.

**MAJ-D — a binding condition that is physically unsatisfiable, narrowed honestly.** Ruling 1's
condition 2 requires registry, claim file and record **byte-identical after abort**. That holds for
the `steer-refused` phase and cannot hold for `T_release-expired`: the timeout only exists *because* a
steer was delivered, and delivery either queues mail or fork-steers the body. The build appeared to
satisfy it only because the steer was stubbed. Now:

- `steer-refused` — byte-identical guarantee **unchanged** (F1 stands as ratified);
- `T_release-expired` — a **precisely scoped effect set**: steer-delivery effects only (mail/steer
  events, restamped sid) and **nothing** from the destructive tail (no tombstone, no dead-marking, no
  claim-file change, no dispatch), each asserted;
- the abort text no longer claims the body was untouched — it states that the steer landed and the
  body may have forked.

> **This narrowing is QUEUED FOR OPERATOR RATIFICATION. It is a correction to a binding 4–0
> condition and is NOT itself ratified.** Presenting it as ratified would be exactly the kind of
> quiet scope-move the condition was written to prevent.

**MAJ-A/MAJ-B — two guards that failed OPEN.** The launch-in-flight guard ordinary `kill`/`respawn`
apply was lost on both §10.4 routes (a pre-claim got dead-marked; the husk arm dispatched a *second*
body) — restored. Ruling 2's limited-parked refusal missed a **null-horizon park**, the exact poisoned
park its own message teaches about, and the ND4a **sid-union lag**; root cause is that
`_holder_is_limited` answers the limit-transfer *boot* question, so it is left untouched and the
refusal got its own union-resolved predicate.

**MAJ-C** — council condition 5 names `sup-status` **and** the statusline; the human branch never
printed the freeze-window note, so the surface an operator actually types after `SUP-KILL-FROZEN` was
the silent one.

**MINs** — corrupt `INCARNATION` now freezes (rc 3) on the real-pipe-name route too; §7 test 8 drives
the real `_sweep_husks` and the archive→sweep handoff instead of only asserting predicates; the B6
halt gets its own token **`SUP-RESPAWN-HALTED-B6`** (it is not side-effect-free, and ruling 1
enumerated exactly three abort phases); the wait clamp is pinned with a poll that does *not* divide
the timeout; F5 feeds its own `RELEASED` entry through the real journal reader (it previously passed
`latest_entry=None` and pinned nothing of its own scenario); the vacuous released-branch precedence
test is now non-vacuous; every injected `sleep` is paired with the clock it advances, so a regression
fails fast instead of hanging 300s; and `save_registry` retries `os.replace` on `PermissionError`
(bounded, exponential) — a live WinError 5 class that this build's two new lock-free readers widen.

**Two of the wave's own tests were themselves theater, caught by the injections and rewritten:** the
`save_registry` retry test grepped `inspect.getsource` and stayed green when the call was swapped for
a bare `os.replace` (the docstring still named the helper), and the released-branch precedence test
could not fail by construction. Both are now behavioural.

---

## Ratification queue (operator)

1. **Ruling 1** (respawn aborts on steer failure) and **ruling 2** (refuse kill of a limited-parked
   holder) — council 4–0 each, still pending operator ratification.
2. **MAJ-D narrowing** of ruling 1's condition 2 — the `T_release-expired` phase asserts a scoped
   effect set rather than byte-identity, because byte-identity is unsatisfiable once a steer has been
   delivered. **New; not ratified.**
3. **Husk-respawn build-time call** — every supervisor-shaped respawn routes through the choreography
   and gets the boot ritual, *including* the carve-out from `commands/respawn.md:2` / SPEC:1513's
   same-name carry-over text (rs MIN-5).
4. **`claim-nonce` §7 taxonomy row** — operator-owned, deliberately not edited by this slice.
