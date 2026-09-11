# Adversarial design review (break lens) — `docs/specs/claim-nonce.md` @ `ccbbc02`

**Reviewer:** `me-nonce-break`, worktree `C:/proga/fleet-me-nonce-break`, branch `me/nonce-break`,
based on `fleet-impl @ 7f99d84`. **Under review:** `docs/specs/claim-nonce.md` (1259 lines,
`Status: drafting`) on branch `me/nonce` @ `ccbbc02`, read at
`C:/proga/fleet-me-nonce/docs/specs/claim-nonce.md`.

**Lens:** *does the mechanism actually work, and what does it fail to stop?* A parallel spec-lens
reviewer audits claims-vs-code; this document does not duplicate that, except where a code fact is
the load-bearing step of a break.

**Nothing here is promoted.** The spec stays `drafting`. No `[PENDING OPERATOR RATIFICATION]` row in
any document is touched. Ratification is the operator's alone.

---

## 0. Verdict up front

**`VERDICT: restructure`**

**Root cause.** The design treats a **bearer secret as an authorization credential** on a substrate
with **no privilege separation** — and then documents **three separate no-secret paths to full
authority**, each keyed on a value that a **read-only, unauthenticated view prints**. §4.5 states
honestly that a nonce cannot distinguish two bodies of one lineage; §5.2, §5.4 and §5.5 then each
build an authorization construct that assumes it can. The contradiction is not in one section — it is
the same contradiction, three times, at the root.

The spec's genuinely valuable property — **divergence detection**: a rotating single-use sequence
that converts ~100 minutes of silent phantom steering into one loud refusal — survives the
restructure intact and is worth building. The **authorization** layer built on top of it does not, and
as drafted it *adds* a documented one-command seizure verb where today the only lever is an
undocumented `rm`.

The restructuring is named in §7 below. It is not a patch list; it is a change of what the nonce is
*for*.

**This is not a verdict on the spec's craft.** §3's receipt work is the best in the repo and it
reproduces (§1). The failure is that §4.5's honesty is not carried forward into the decisions.

---

## 1. Provenance of every receipt in this document

`bin/fleet.py` is **byte-identical** between the spec's receipt pin `238b7ad` and my base `7f99d84`,
so every §3 receipt is directly reproducible in this worktree and every line number below is valid at
both commits.

```
$ git log --oneline -1
7f99d84 docs(ledger): me/ul landed (1145 green, manager-verified); hostile review dispatched
$ git diff --stat 238b7ad HEAD -- bin/fleet.py bin/hooks/
(no output — no drift)
```

**Who ran what.** Every command in this document was run by **me** (`me-nonce-break`), read-only, in
this worktree, except the live `sup-status` in §2.1 which was run read-only against
`C:/proga/claude-fleet` (the fleet home holding the live claim). **18 receipts executed.** No mutating
`sup-*` verb was run; no `fleet spawn/respawn/send/kill/clean/init/autoclean/resume-limited`, no
`schtasks`, no `claude daemon *`, no `claude stop`, no write under `C:/Users/Techn/.claude/`.

**Probe-context clause (v1.7).** I am a `--bg` worker and therefore a live daemon client. I **cannot
observe the dead-daemon path**. Every finding below rests on code structure, file contents, or a
read-only view — none rests on dead-daemon behavior. The one thing I cannot observe is flagged
`[MANAGER-VERIFICATION REQUIRED]` in §6 and is the same item the spec itself parks as O4.

### 1.1 The three source corrections — verified independently

The author reports that three of its briefing sources were wrong. I checked all three myself.

**(1) "The adjudication's 6-anchor list is incomplete." — CONFIRMED.**

```
$ grep -n "Per-body claim nonce is a hard PREREQUISITE" \
    C:/proga/fleet-me-nonce/docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md
14:1. **Per-body claim nonce is a hard PREREQUISITE, its own slice, own review** (MF1, D1). Identity that survives fork-steer/respawn/handoff; enumerate every touchpoint by grep (INCARNATION schema, `_require_claim_holder`, `supervisor_claim_decision`, HANDSHAKE `--expect-sid`, `_SUPERVISOR_ENTRY_RE`, `_restamp_after_steer`); preserve the roster-liveness two-supervisor guard.
```

Exactly six anchors named. I verified all five of §3.11's additions independently: (A) the three
dict-literal INCARNATION writers at 7145/7159/7404 (read in `cmd_sup_boot` and
`cmd_sup_handoff_complete`); (B) `sup-status --json` emitting `"incarnation": claim` verbatim at
7232-7241; (C) the inline restamp at 3428-3436; (D) `--sid` on all five gated verbs at 7721-7748;
(E) `_SUPERVISOR_ENTRY_RE` `$`-anchored at 6924-6925 with `parse_supervisor_journal` absorbing
non-matching lines as body text at 6935-6947. **All five are real, and (B) is the one that decides
the design.**

**(2) "`_restamp_after_steer` has one call site, not two." — CONFIRMED.**

```
$ grep -n "_restamp_after_steer(" bin/fleet.py
3293:                _restamp_after_steer(r, new_sid, short_id)
6331:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
```

One call site. The function's own docstring names `resume-limited`'s native branch as a caller; that
branch carries a duplicated inline copy instead (3428-3436). The docstring is wrong; the spec is
right.

**(3) "'a stale roster PASSES the epoch check' is the adjudication's claim, not
`native-substrate.md`'s." — CONFIRMED.**

The sentence appears at `THREE-TIER-ADJUDICATION-2026-07-17.md:17`, inside item 4.
`native-substrate.md:43` reaches a **different** conclusion for the idle-exit path (*"An idle-exit
cannot strand a live-looking roster entry"*, 15/15 `leases=0, live_workers=0`) and names
`cause=upgrade` as the one residual stale-roster vector (`:43`, `:233`). The spec's decision to
ground §5.6 on the code receipt rather than on either document is correct, and the code receipt is
correct: `supervisor_epoch_check` (7002-7011) tests fetch-success and non-emptiness, and contains no
staleness test.

**Assessment of the author.** Three for three. The corrections are real and the receipts reproduce.
This author is careful, not story-building. The findings below are about the *decisions*, not the
evidence.

---

## 2. CRITICAL

### C1 — Rule 0b (`re-issue`) is a complete, documented bypass of the entire mechanism

**§4.4(d), §4.7, §5.4 Rule 0b.** The lost-nonce recovery path: no nonce presented, but
`caller_sid == claim["session_id"]` and `caller_sid` comes from `current_caller_session()` ⇒ **mint a
fresh nonce for the same incarnation, rc 0.**

Two facts kill it.

**Fact 1 — `current_caller_session()` is an environment variable, nothing more.**

```
$ grep -n "def current_caller_session" -A 9 bin/fleet.py
580:def current_caller_session() -> str | None:
...
587-    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
588-    return sid or None
```

**Fact 2 — the holder's sid is published by a read-only, unauthenticated view.** Run by me, read-only,
against the live fleet home:

```
$ py -3.13 bin/fleet.py sup-status
supervisor: inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca via seize, heartbeat 2257s ago
```

`cmd_sup_status` is a view: no lock, no probe, no write, no authorization. It prints the holder sid in
the human form (7248-7249) and dumps the whole claim dict in `--json` (7232-7241). The sid is
**additionally** published in `supervisor/JOURNAL.md`, which is **git-tracked** and therefore pushed
to any remote:

```
$ git ls-files supervisor/
supervisor/GOALS.md
supervisor/JOURNAL.md
$ grep -n "^## " C:/proga/claude-fleet/supervisor/JOURNAL.md | tail -1
162:## 2026-07-21T15:12:26Z CHECKPOINT inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca
```

**The break, in two commands, with no secret:**

```
1.  py -3.13 bin/fleet.py sup-status          # a view. prints sid=S_holder
2.  CLAUDE_CODE_SESSION_ID=S_holder py -3.13 bin/fleet.py sup-boot
    -> Rule 0b -> "mint a fresh nonce for the same incarnation", rc 0, NONCE printed to me.
```

The caller now holds a valid, current nonce for the live claim and can run every gated verb.

**§4.7's justification is void.** It reads: *"§4.4(d)'s `re-issue` verdict uses
`current_caller_session()` and **ignores `--sid`** — otherwise the recovery path would hand a fresh
nonce to anyone who typed the holder's sid."* Setting `CLAUDE_CODE_SESSION_ID=X` is not harder than
typing `--sid X`. There is no privilege difference on this substrate. The spec's own §3.3 states the
principle correctly — *"the claim check is already, today, a check of what the caller typed, not of who
the caller is"* — and then §4.7 reinstates exactly that as the authorization for the recovery path.

**Why this is not a threat-model quibble.** §2 disclaims defense against "a hostile local process" and
names the real threat as *"an over-helpful agent, especially one under `bypassPermissions`"*. An
over-helpful agent under `bypassPermissions` is precisely the actor that will set an env var after a
failed command — and **§4.6's new refusal message instructs it to go read the view that supplies the
input**: *"run `fleet sup-status` and a process census before doing anything else"*. The refusal hands
the bypass to the actor it just refused.

**Net effect:** the nonce is no stronger than today's sid equality, because a nonce-less path to full
authority exists **by design**, is **documented**, and is **permanent** (§4.4(d): "stated because it
will happen").

### C2 — Rule 0 disables the roster-liveness two-supervisor guard for exactly the class it exists to catch

**§5.4 Rule 0, §5.6.** Rule 0: `nonce_valid` ⇒ verdict `resume`, *"regardless of heartbeat age and
**regardless of roster liveness**"*, ahead of every existing rule.

The rule it jumps is the `holder_sid in live_sids` refusal (7021-7024) — which the spec itself calls
*"the genuine two-live-supervisors guard"* (§3.4) and which adjudication item 1 **binds** the spec to
preserve: *"preserve the roster-liveness two-supervisor guard."*

**The contradiction is internal.** §4.5 states, correctly and at length, that two bodies of one lineage
are byte-identical and that **both hold the nonce** (the fork is a copy of the transcript that contains
it). Rule 0 then spends that same body-blind credential to skip the only body-*discriminating* check
in the program. A credential the spec declares incapable of distinguishing bodies is used as proof
that no second body needs checking for.

**Concrete:** in the incident-1 shape, body B (the fork) runs `sup-boot --nonce V1`. Rule 0 fires
first. Verdict `resume`. `session_id` restamped to B, nonce rotated, journal entry `BOOT` bodied
"resumed own claim". **No `SEIZED`, no freeze, no operator page** — and the roster check that would
have reported *"claim holder inc-I (sid S_A) is live in the roster"*, the single available two-body
signal, never executes.

**§5.6's defense is refuted by §4.5.** It argues the guard *"never fires against the caller's own
proven claim — which is the bug it currently has, not a capability it loses."* But §4.5 establishes
that "the caller's own proven claim" and "the caller's own body" are **not the same set**. In the one
scenario that motivated this entire spec, the guard firing is *correct behavior*, and Rule 0 removes
it. The claim that the guard "gets more accurate" is true only for the sid-restamping half (§5.6
bullet 2, which is a real improvement) and false for the Rule 0 half.

**Fix direction (this one is patchable):** run the roster-liveness check **before** Rule 0. Grant
`resume` only when the recorded holder is **roster-gone**. That still resolves incident 2 in full (the
10h host-restart gap left the holder roster-gone with a stale heartbeat) and does not surrender the
guard. Rule 0 as drafted buys nothing incident 2 needs and costs the item-1 requirement.

### C3 — Both operator escapes are keyed on a value the view prints; the "non-memorizable" argument is void

**§5.2 `--claim-override <incarnation-id>` / `FLEET_CLAIM_OVERRIDE`; §5.5 `sup-release --force
--confirm-inc <incarnation-id>`.**

Both require naming the exact incarnation id and nothing else. The same read-only view prints it
(receipt in C1: `supervisor: inc-20260721T150630Z-2c07 sid=...`), as does the git-tracked journal
header. So:

```
INC=$(py -3.13 bin/fleet.py sup-status --json | python -c "import json,sys;print(json.load(sys.stdin)['incarnation']['incarnation_id'])")
py -3.13 bin/fleet.py sup-release --force --confirm-inc $INC --reason "cleanup"
py -3.13 bin/fleet.py sup-boot        # released row -> verdict `claim` (fresh), no SEIZED, no page
```

**A two-command, fully-sanctioned seizure of a live supervisor's claim, requiring no secret, leaving
a clean `RELEASED` + `BOOT` pair in the journal and no `SEIZED` entry and no operator page** (§5.5's
table, row 5, is explicit that the released row produces *"`BOOT`, no `SEIZED`, no page"*).

Compare against the disease it cures. Today the only release lever is `rm supervisor/INCARNATION` —
undocumented, not a verb, not in `--help`, and not something a refused agent is *told* to reach for.
The spec replaces that with a documented verb, in `--help`, whose input is printed by the view that
§4.6's refusal message instructs the refused caller to run. **The cure is larger than the disease.**

**The anti-reflex argument confuses memorability with authorization.** §5.2: *"Because `incarnation_id`
changes on every fresh claim and every seize, the flag cannot be memorized, aliased, or baked into a
script the way a bare `--yes` can."* Two defeats:

1. It can be baked into a script — the one-liner above is the script, and it is stable across every
   incarnation change because it *looks the id up*. The property §5.2 relies on is "the literal string
   changes", not "the value is hard to obtain", and only the second would be a security property.
2. §5.2 makes the flag a **daily requirement**: *"An operator's own interactive Claude session must
   pass `--claim-override` ... to mutate a claimed fleet."* A flag required on every operator action
   is a flag that gets scripted on day two. This is exactly the reflexive-`--yes` normalization that
   adjudication item 3 forbids, re-created under a new name — and this spec's §5.3 correctly refuses
   to normalize `--yes` in the *other* half of the same design.

### C4 — `$FLEET_SUP_NONCE` and `FLEET_CLAIM_OVERRIDE` are inherited by every worker turn

**§4.2 step 2 and §9** make `$FLEET_SUP_NONCE` the standing fallback channel for presenting the nonce;
§5.2 offers `FLEET_CLAIM_OVERRIDE` as an env-var form of the override. The worker child environment:

```
$ grep -n "def _worker_env" -A 18 bin/fleet.py
989:def _worker_env(name: str) -> dict:
...
1004-    env = dict(os.environ)
1005-    env.pop("CLAUDE_CODE_SESSION_ID", None)
1006-    env["FLEET_WORKER"] = name
1007-    return env
```

The whole parent environment is copied and **exactly one** key is stripped. If the supervisor ever
exports `FLEET_SUP_NONCE` — which §9 presents as the ordinary working mode, since the alternative is
re-typing a 43-character token on every command — **every worker fleet spawns receives the live
supervisor nonce in its environment**, and every subagent those workers spawn inherits it again.

The §5.2 gate does **not** contain this. The gate's carve-out (`FLEET_WORKER is not None` ⇒ ungated)
governs the *mutating verbs only*. `_require_claim_holder` — the path to `sup-checkpoint`,
`sup-heartbeat`, `sup-handoff-begin/-complete/-abort` and the new `sup-release` — has **no
`FLEET_WORKER` check at all**, today or in the spec. So a worker holding the inherited nonce can
checkpoint the supervisor's journal, hand the claim off, or release it.

Five workers are live in sibling worktrees as I write this. Under the drafted design every one of them
would hold the supervisor's credential.

This is fixable (strip both keys in `_worker_env`; drop the env channel entirely), but the spec does
not mention `_worker_env` once — despite quoting it at §3.9 for a *different* purpose (the
`FLEET_WORKER` discriminator), which means the design read the exact function that defeats it and did
not draw the consequence.

### C5 — The gate is armed only by a fresh heartbeat, and this slice ships no beat; protection is anti-correlated with risk

**§5.2:** *"When the gate is armed: only while a claim exists **and** carries a `nonce_hash` **and** its
heartbeat is fresher than `SUPERVISOR_CLAIM_STALE_SECONDS`."*

```
$ grep -n "SUPERVISOR_CLAIM_STALE_SECONDS *=" bin/fleet.py
6821:SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0
```

One hour. And there is no automatic beat — `fleet beat` is explicitly a **§2 non-goal**, deferred to
the three-tier slice:

```
$ grep -n 'ScheduleWakeup\|def cmd_beat\|"beat"' bin/fleet.py
$ echo "exit=$?"
exit=1
$ grep -n "sup-heartbeat" bin/fleet.py
7210:    """`fleet sup-heartbeat [--sid S]` -- beat without journal spam ...
7730:    p_supbeat = sub.add_parser("sup-heartbeat", ...)
```

The only beat is a **manual** verb a human-attached supervisor remembers to type.

**Consequence:** the gate protects the fleet only during the hour after the supervisor last typed a
command. It **disarms itself** during any quiet stretch — which is precisely when an unattended zombie
does damage. Incident 1's phantom steers spanned **~100 minutes**; under this design the gate would
have expired partway through and the second half would have been ungated.

Live evidence, from the receipt in C1: the **currently live, actively-managed** supervisor's heartbeat
is **2257s old — 63% of the way to disarmed**, at a moment when six workers are running.

This is also a **sequencing defect**: the slice's central protection depends for its arming condition
on a primitive the same document's §2 defers to the *next* slice. §7 states the gate "is inert on a
fleet nobody has booted a supervisor on" as a safety property; the same mechanism makes it inert on a
fleet whose supervisor is merely *busy*, and that is not stated anywhere.

---

## 3. MAJOR

### M1 — Rotation-on-every-verb + parallel tool calls: one body raises the two-body alarm against itself

**§4.5:** *"every successful claim-bearing call rotates it and prints the replacement."* §5.2 gates
`spawn`, `send`, `respawn`, `kill`, `clean`, `interrupt`, `archive`, `autoclean`, `resume-limited`,
`init` — so every one of those rotates.

A Claude Code manager session is instructed by its own harness to batch independent tool calls:
*"If you intend to call multiple tools and there are no dependencies between the calls, make all of
the independent calls in the same block."* A supervisor dispatching a wave issues several
`fleet send`s in one block. `fleet_lock` serialises them; the first rotates, and **every subsequent
call in the same block presents a stale nonce**.

Result, per §4.6, for a **single healthy body doing exactly what the fleet skill tells it to do**:
exit 4, a rejection record in `state/supervisor-nonce-rejections.jsonl`, `_doctor_check_supervisor_claim`
flipping to `ok=False` for 24 hours, and the message *"a second body of your lineage may be acting."*

The alarm in §4.6 **is the entire value of the mechanism** once C1–C3 have removed the authorization
value. An alarm that fires on normal operation is an alarm that gets trained away within a week, and
then incident 1 recurs undetected with a doctor check that everyone has learned to ignore.

There is **no concurrency section** in the spec, and **no concurrent-call test** in §8 — T5's
"second body, one lineage" test uses two callers and asserts the refusal is *correct*, which is
indistinguishable from this false positive.

### M2 — Rotation is committed to disk but delivered over a stream with no acknowledgment

**§4.2 step 3:** *"On success the verb, **before returning**, restamps `session_id` ... and rotates the
nonce."* **§9:** *"each re-prints the rotated nonce on stderr."*

The new nonce is written into `supervisor/INCARNATION` under `fleet_lock`, and the only copy the
caller can use is text on a stream. There is no acknowledgment, no two-phase commit, no
"previous generation remains valid until the next successful call."

**Attack 7's incident, applied:** this session's own 9th live catch — a stale `daemon.lock` with a
reused PID wedged every dispatch machine-wide for ~16h while `fleet doctor` read all-PASS. Dispatch
dead, files perfectly readable. Under the drafted protocol:

1. Supervisor runs `fleet send`. Gate armed. Nonce valid.
2. `_require_claim_holder` rotates: `nonce_seq` 4→5, `nonce_hash = H(V5)` written to INCARNATION.
3. The verb proceeds to dispatch — which, per F4 doctrine, runs **outside** `fleet_lock` — and hangs.
4. The turn times out or is interrupted. **V5 was never rendered to the caller.**
5. The supervisor now holds V4. The file holds `H(V5)`. **The supervisor is locked out of its own
   claim during the incident in which it most needs to act.**

This is the "goes wrong, not merely unavailable" behavior the task asked me to look for: the failure
is not that dispatch is down, it is that the *claim* is destroyed by a dispatch failure.

The design self-heals — via **C1's bypass** (Rule 0b re-issue still works, because step 2 also
restamped `session_id` to the caller). So the only thing preventing a hard brick here is the hole that
must be closed. Closing C1 without addressing M2 converts C1 into a bricked-claim CRITICAL. **They
must be fixed together**, which is one reason this is a restructure and not a fix list.

The spec never states where the gate sits relative to `fleet_lock`, nor how rotation interacts with a
verb that fails after validation. §8 has no test for it.

### M3 — §4.2 step 4's legacy predicate collides with §5.5's released claim

§4.2 step 4: *"**If the claim has no `nonce_hash`** (a legacy claim, §7): fall back to today's exact
`caller != claim.get("session_id")` comparison, and **upgrade the claim in place**."*

§5.5: `sup-release` *"does **not** delete INCARNATION. It rewrites it as a **released** claim ...
**`nonce_hash` removed**, plus `state: "released"`."*

A released claim **has no `nonce_hash`**. So by §4.2 step 4's literal predicate, a released claim is a
*legacy* claim, and `_require_claim_holder` falls back to sid equality and **upgrades it in place**.
"Released" would not be a terminal state; whoever matches the recorded sid resurrects the claim
silently — and, per C1, matching the recorded sid is an env-var assignment.

The spec cannot be read to resolve this. §5.5's preserved-field list is `incarnation_id`,
`lineage_id`, `released_at`, `released_by_sid`, `claimed_via` — it does **not** say whether
`session_id` and `heartbeat_at` survive, and the behavior differs in both directions:

- **If `session_id` survives:** the resurrection above is live.
- **If it does not:** `claim.get("session_id")` is `None`. The existing guard at 7185
  (`if not caller: raise`) blocks the `None == None` match from a plain shell, so this direction
  fails closed — but only by accident of an unrelated guard, and the spec does not know it is relying
  on it.

§4.2 step 4's predicate must be `"no `nonce_hash` **and no `state`**"`, and §5.5 must enumerate the
full post-release key set. Neither is stated; §8 T11 tests that `sup-boot` handles a released claim
but never tests `_require_claim_holder` against one.

### M4 — The incident-1 interleaving: at-most-one *nonce-bearing actor*, not at-most-one *actor*

The task asked for the step-by-step. Here it is, with the state each actor holds. Initial state:
claim `inc-I`, `session_id = S_A`, `nonce_hash = H(V1)`, `nonce_seq = 1`, `lineage_id = L`, heartbeat
fresh ⇒ gate armed.

| t | Actor | Action | What the actor sees | What the *other* body sees | What a **human** sees |
|---|---|---|---|---|---|
| t0 | A (real manager) | working normally | holds V1 | — | normal |
| t1 | host restart | re-hosts A's conversation as `--fork-session` ⇒ **B** | B's transcript is byte-identical to A's, so **B holds V1** | — | nothing (fleet has no handle on the fork — §1.2 fact 2) |
| t2 | **B** | `fleet send me-x "final micro-wave"` presenting V1 | valid. `session_id`→`S_B`, rotate→V2, `seq`=2. **Steer dispatches.** | nothing | **nothing.** `send` writes no journal entry; no rejection record; doctor still `ok=True` |
| t3 | A | `fleet send me-y ...` presenting V1 | **exit 4.** rejection record. doctor `ok=False`. *"a second body of your lineage may be acting"* | nothing | **first learnable moment** — A's next mutating call |
| t4 | A | follows §4.6's instruction: `fleet sup-status` | prints `sid=S_B`, `inc-I` | nothing | A now holds both escape-hatch inputs |
| t5 | A | `--claim-override inc-I` (§5.2) | **mutates without the claim** | **B is unaffected and still holds V2** | **both bodies acting again** |
| t5′ | A | *or* `sup-release --force --confirm-inc inc-I` then `sup-boot` | A takes a fresh claim | B refused at its next call — and B, an autonomous body, repeats t4/t5′ from the same published inputs | **claim ping-pong**, each round a clean `RELEASED`+`BOOT` pair |

**What the mechanism actually delivers.** Detection improves enormously and genuinely: **~100 minutes
of undetected phantom steering → one phantom steer, then a loud refusal.** That is real, it is the
best thing in this spec, and it is worth building.

**Mutual exclusion does not improve; it regresses.** The refused body's *documented* recovery is an
escape hatch that either (i) re-establishes two concurrent actors (t5) or (ii) hands each body a
one-command seizure they can trade indefinitely (t5′). §4.5's *"After the first divergence **at most
one body can act**"* is true only of nonce-bearing calls. The spec never audits what a refused body
does next, and what it does next is documented three sections away.

**The honest statement §4.5 should make:** *at most one body can act **with the nonce**; the escape
hatches are unauthenticated and any refused body can use them.*

### M5 — Scope: the slice absorbs three-tier's operator doctrine and depends on three-tier's beat

§2 declares items 4–10 out of scope and requires the slice be *"implementable and useful with today's
human-attached supervisor and no three-tier work at all."*

§5.2 then makes `--claim-override` mandatory for the operator's own interactive sessions and justifies
it by quoting `three-tier-command.md:73-75` — *"humans talk to the interface tier; direct `fleet send`
to a claimed fleet's workers is an incident, not a convenience"* — and says *"This spec makes it
mechanical rather than aspirational."* That is item 4–10 doctrine, mechanised, inside a slice that
disclaims it. §10's O2 puts the *cost* in front of the operator but not the *scope* question.

And per C5 the gate's arming condition depends on a beat this slice defers. So the slice both
over-reaches into the next slice's doctrine and under-delivers on the next slice's primitive.

**O1's framing is therefore incomplete.** O1 offers "ship the gate here" vs "defer the gate", with
*"the honest cost of deferring: incidents of class 1 stay undetected."* That cost statement is wrong
on the spec's own design: **detection lives in §4.5/§4.6 (rotation + refusal + rejection log), not in
§5.2's gate.** Deferring the *gate* while shipping the *rotation* keeps all of the detection and drops
all of C1/C3/C5/M1. O1 should be re-put to the operator with that corrected.

### M6 — Plaintext secrets written to `state/` with no deletion, and a rejection log with no bound

**§5.7 step 1** renders the plaintext `handoff_token` *"into the successor's task file under `state/`"*.
That file is `state/supervisor-handoff-<inc>.md` (7289). It is **never deleted**:

```
$ grep -n "supervisor-handoff" bin/fleet.py
6865:    return state_dir() / "supervisor-handoff-aborted.json"
7289:        task_path = state_dir() / f"supervisor-handoff-{successor_inc}.md"
7566:    return ("supervisor-handoff", ok, " | ".join(parts))
```

One write site, no `unlink`. So every handoff leaves a plaintext one-shot credential on disk
permanently. Being gitignored is not a retention policy. The spec gives no expiry, no consumption
delete, and no `fleet clean`/autoclean/archive-TTL integration; §8 T3 tests token verification and
never tests that the plaintext is gone afterwards.

Same class: `state/supervisor-nonce-rejections.jsonl` (§4.6) has no rotation, no TTL, and no size
bound, while `_doctor_check_supervisor_claim` must scan it on **every** `fleet doctor` run to answer
"any rejection in the last 24h". Under M1's false-positive rate that file is append-only forever.

---

## 4. MINOR

**m1 — §4.3's suppression rule is asserted but never made a binding build rule, and T14 does not test
it.** §3.8's own receipt shows the view emits `"incarnation": claim` verbatim (7232-7241), so a
naive implementation publishes `nonce_hash` — and, via §5.7, `handoff_token_hash` — through a
lock-free view. §4.3 asserts *"it never sees the hash either"*, which requires converting the view from
a verbatim dump to a filtered projection. §7 gets a **"Binding build rule"** callout plus a dedicated
test (T7) for the analogous dict-literal hazard; §4.3 gets neither. §8's T14 asserts only that *the
nonce string* is absent from `sup-status` — but the nonce string was never in the file. **T14 as
written passes on an implementation that publishes both hashes.** (Publishing a sha256 of a
`token_urlsafe(32)` is not itself a break; the defect is that the spec claims a property its own test
does not check.)

**m2 — §6 contradicts §5.2 on process control.** §6: *"nothing here is platform-specific — no
scheduler, **no process control**, no path semantics beyond `Path` — so **no platform-adapter seam is
required, and none is added**."* §5.2: *"`sup-handoff-complete` and `sup-release --force` `claude stop`
the superseded sid using `_stop_native_session`'s existing verify-via-roster shape, and write the G10
tombstone."* That is process control, and it is new work in `sup-release`. The existing seam covers
it, but §6's portability paragraph is false as written and a builder reading only §6 will not
implement the G10 tombstone obligation.

**m3 — §4.2 step 3's comparison is type-broken as written.**
`hmac.compare_digest(sha256(presented), claim["nonce_hash"])` compares a digest object (or bytes) to a
hex string. Trivial for a builder, but the spec elsewhere is precise about stdlib call shapes and this
is the one that guards the whole mechanism.

**m4 — the gate's position relative to `fleet_lock` is unspecified**, and `send`'s dispatch runs
outside the lock by F4 doctrine. This is the mechanism of M2 and it deserves an explicit sentence.

**nit — §3.1's parenthetical is right and should be promoted.** *"`claimed_at` is written at
7146/7160/7406 and **never read anywhere**"* — I confirmed it. A schema section adding three fields is
the right moment to say so.

---

## 5. DESIGN-QUESTION and SPURIOUS

### Q1 (DESIGN-QUESTION) — where is the trust boundary?

There is no threat-model section. §2 offers a **non-goal** (*"not a defense against a hostile local
process"*) and a **threat actor** (*"an over-helpful agent, especially one under `bypassPermissions`"*),
but never a **boundary**: a statement of what is inside, what is outside, and what capability the
inside has that the outside does not.

The reason that matters is that on this substrate **there is no such capability**. The actor the spec
defends against has: the filesystem (INCARNATION, `state/`, the transcripts), the environment (so
`CLAUDE_CODE_SESSION_ID` and `FLEET_SUP_NONCE`), the views (`sup-status`, the git-tracked journal), and
a shell. That is a superset of everything the supervisor has. **The spec is trying to authenticate one
actor against another actor with identical capabilities.** §4.5 discovers this for the two-bodies case
and states it honestly; the design never generalises the discovery, and §5.2/§5.4/§5.5 each proceed as
if a boundary existed.

Every one of C1–C4 is a consequence of the missing boundary, which is why they cannot be patched
independently.

### S1 (SPURIOUS) — §4.3's hash-only store defends a copy that is not the exposed one

§4.3 is presented as *"cheap defense-in-depth against file disclosure [that] costs nothing here."* It
is not free — it is the constraint that forces the print-once-to-a-stream delivery model, and therefore
M2 (rotate-then-lose), M1 (nothing can re-read the current value), and §4.4(d)'s re-issue path, which
is C1.

And it protects the wrong copy. The nonce's **actual** store is the Claude session transcript: it is
printed as command output, and command output is persisted per-session on disk. Receipt (existence and
permissions only — I did not read any transcript's contents):

```
$ ls -ld ~/.claude/projects && find ~/.claude/projects -maxdepth 2 -name '*.jsonl' | wc -l
drwxr-xr-x 1 Techn 197609 0 Jul 21 20:44 /c/Users/Techn/.claude/projects/
729
```

729 world-readable session transcripts. And `--fork-session` **duplicates that store by design** —
which is exactly how body B obtains V1 in M4's t1. So the mechanism hashes the copy in `supervisor/`
while the copy that the attack actually uses is duplicated by the very operation the spec exists to
defend against.

`[MANAGER-VERIFICATION REQUIRED]` — that a `sup-boot` stdout line lands verbatim in the session's
`.jsonl` is inference from documented harness behavior, not something I verified; verifying it would
mean reading a transcript's contents, which I did not do. The existence, count and permissions above
are my receipt.

Not harmful in itself — keep the hash, it costs little once the delivery model is fixed. But it must
stop being described as the thing that makes the nonce unforgeable, because the file was never where
the secret was.

---

## 6. `[MANAGER-VERIFICATION REQUIRED]`

I am a `--bg` worker and a live daemon client. **I cannot observe the dead-daemon path.**

1. **Does `supervisor_epoch_check` pass against a genuinely stale roster served by a dead daemon?**
   I confirmed by receipt that the function contains **no staleness test** (7002-7011), so it must pass
   on any non-empty payload — but I cannot produce the dead-daemon condition. The spec parks the same
   question as O4 and I agree with its recommendation (fold into the parked G9 standalone probe, do not
   gate this slice on it): §5.6's fail-safe analysis of both error directions is correct as far as it
   goes, and none of C1–C5 depend on the answer.
2. **Whether a `sup-boot` stdout line is persisted verbatim into the session transcript `.jsonl`** —
   S1. Deliberately not verified; it would require reading transcript contents.

Neither is asserted anywhere above.

---

## 7. The restructuring

Not a patch list. The change is **what the nonce is for.**

**Root cause, named:** the design uses a **bearer secret as an authorization credential** on a
substrate with **no privilege separation**, and then, because a bearer secret on such a substrate is
inevitably lost or unavailable, adds **three unauthenticated recovery paths** — each keyed on a value a
public view prints. The recovery paths are not a lapse; they are forced by the substrate. Any spec
that puts authorization on a bearer secret here will re-derive them.

**Restructure into a detection mechanism.**

1. **Keep, unchanged — this is the part that works.** §4.1's `nonce_hash` / `nonce_seq` / `lineage_id`;
   the single-use rotation; §4.6's loud refusal, the rejection record, and the doctor surface. This
   converts incident 1 from ~100 minutes of forensics to one refused command (M4, t2→t3). It is worth
   building on its own and it needs no gate.
2. **Drop the authorization framing.** The nonce proves *"the last body to act was the same body as
   this one"*. It does **not** prove *"I am authorized"*, and §4.5 already knows why. Rewrite §4.5's
   guarantee as: *at most one **nonce-bearing** actor after divergence; the escape paths are
   unauthenticated and a refused body will use them.*
3. **Take the §5.2 gate out of this slice** and re-put adjudication item 2 to the operator with O1's
   cost statement corrected (M5): detection ships either way. If a gate is still wanted afterwards, it
   needs an authorization input **not derivable from any view and not an environment variable** —
   and on this box, today, there isn't one. Say that plainly in front of the operator instead of
   offering `--claim-override`.
4. **Delete Rule 0b (`re-issue`) (C1).** Lost-nonce recovery becomes either an explicit release or a
   seize once the heartbeat goes stale. Both are honest; a sid-keyed re-issue is not. This is only safe
   once **M2** is fixed, because today Rule 0b is what silently repairs a rotate-then-fail — which is
   why they are one change, not two.
5. **Fix the rotation contract (M1, M2).** Rotation must survive a verb that fails after validation and
   must not fire the two-body alarm on one body's concurrent calls. Concretely: keep generation *N*
   valid until *N+1* has been **used**, or move rotation to `sup-*` verbs only and leave the gated
   mutating verbs as *validate-without-rotate*. Then write the concurrency section the spec does not
   have, and the tests §8 does not have.
6. **Run the roster-liveness guard before Rule 0 (C2)**, granting `resume` only when the recorded holder
   is roster-gone. Restores adjudication item 1's binding requirement and still fully resolves
   incident 2.
7. **Close the environment channel (C4).** Strip `FLEET_SUP_NONCE` and `FLEET_CLAIM_OVERRIDE` in
   `_worker_env`, or do not offer env-var channels at all. Add a `FLEET_WORKER` refusal to
   `_require_claim_holder` — a worker turn must never hold the supervisor claim, which is true today
   only by accident.
8. **`sup-release` keeps its no-`--force` form and loses `--force --confirm-inc` (C3)** until an
   authorization input exists. Incident 3's real requirement is *"an operator-authorized stop must be
   distinguishable from a daemon restart"*, and that is satisfiable without an unauthenticated verb —
   e.g. the operator's `claude stop` doctrine writes the released state, or the freeze page grows a
   "was this an authorized stop?" prompt. §5.5's diagnosis (the fourth unambiguous shape) is right; its
   `--force` form is the part that must change.

**Sections that must exist and do not** (attack 10):

- **Threat model / trust boundary** (Q1) — the missing section that generates C1–C4.
- **Nonce lifecycle: delivery, acknowledgment, concurrency, rotate-then-fail** (M1, M2, m4).
- **The transcript as the real secret store** (S1), including that `--fork-session` duplicates it.
- **Secret retention: `state/supervisor-handoff-<inc>.md` deletion, rejection-log rotation** (M6).
- **What a refused body does next** — the audit that M4's t4/t5 performs and the spec does not.
- **Gate disarm / rollback** — what an operator does when the gate blocks them and the claim is
  unreachable (C5); currently the only answer is C3's seizure verb.
- **What a view may publish, given that every escape is keyed on published values** (C1, C3).

---

## 8. What is right, and should survive

Stated because a restructure verdict should not be read as a rejection of the work.

- **§3 is the best receipt section in this repo.** It reproduces byte-for-byte at my base commit, and
  all three of the author's source corrections are correct (§1.1). §3.11's five additions are real,
  and (B) — `sup-status --json` dumping the claim verbatim — is a genuine find that a naive
  implementation would have shipped straight through a view.
- **§4.5 is intellectually honest** about undecidability, and is the section that ultimately falsifies
  §5.4 and §5.6. The spec argued itself out of its own decisions and did not notice; that is a better
  failure mode than not arguing.
- **§5.3's lineage answer to `spawned_by` is correct and should ship** roughly as drafted. It solves a
  real problem (sid rotation making a supervisor's own workers foreign), it refuses to normalize
  `--yes`, it is additive, and none of C1–C5 touch it. It does depend on "a claim the caller **proved**
  with a valid nonce", so it inherits the restructured proof semantics — but the shape is right.
- **§7's dict-literal-writer analysis and its binding build rule (with T7)** is exactly how a
  migration hazard should be written up.
- **The detection property** — one refused command instead of 100 minutes of forensics — is real, is
  the spec's best contribution, and survives the restructure whole.

---

## VERDICT

**`VERDICT: restructure`**

**Root cause:** a bearer secret is used as an authorization credential on a substrate with no
privilege separation; the resulting unavoidable recovery paths (Rule 0b re-issue, `--claim-override`,
`sup-release --force`) are each unauthenticated and each keyed on a value a read-only view prints —
and §4.6's refusal message directs the refused caller to that view. §4.5 states the impossibility;
§5.2, §5.4 and §5.5 each proceed as though it were not stated.

**Restructuring:** re-scope the nonce from **authorization** to **divergence detection** (§7.1–§7.2);
take the mutating-verb gate out of this slice and re-put item 2 to the operator with O1's cost
statement corrected (§7.3); close Rule 0b and fix the rotation contract together (§7.4–§7.5); restore
the roster-liveness guard ahead of Rule 0 (§7.6); close the environment channel (§7.7); drop
`sup-release --force` until an authorization input exists (§7.8); write the seven missing sections.

`spawned_by` lineage (§5.3), the §3 receipts, and the detection property survive intact.

**Findings:** 5 CRITICAL, 6 MAJOR, 4 MINOR, 1 nit, 1 DESIGN-QUESTION, 1 SPURIOUS.
**Receipts executed:** 18, all read-only, all by `me-nonce-break`.
**Source corrections:** 3/3 confirmed.

---

# RE-GATE — `claim-nonce.md` v2 @ `091d5fa` ("detection, not authorization")

**Reviewer:** `me-nonce-break`, same worktree/branch. **Under review:** `docs/specs/claim-nonce.md`
@ **`091d5fa`** on `me/nonce`, 1814 lines. **Authority for this wave:**
`ME-NONCE-ADJUDICATION-2026-07-21.md` (my `restructure` upheld; binding re-draft items 1–12).

**Status check, first, because it is a hard requirement of the task.** Line 3 of the spec reads
``**Status:** drafting (`me-nonce`, v2 re-draft 2026-07-21)``. **`drafting` — unchanged. Nothing
promoted here either;** no `[PENDING OPERATOR RATIFICATION]` row touched, and the four operator
questions (§12 O1–O4) are left open below, with recommendations only.

**Who ran what.** 10 read-only receipts this turn (29 cumulative), all by me in this worktree, except
the `supervisor/JOURNAL.md` and `knowledge/lessons.md` reads against `C:/proga/claude-fleet`. No
mutating verb of any kind. Probe-context clause unchanged: I am a `--bg` worker and a live daemon
client; **nothing below rests on dead-daemon behavior**, and §12 O4 remains
`[MANAGER-VERIFICATION REQUIRED]` for the same reason it did in the first gate.

**`VERDICT: fix-list(N1, N2, N3, N4, N5, N6, N7)` — not `restructure`, and explicitly not `ESCALATE`.**

The root is fixed. §2 exists, is correct, and is the section whose absence generated four of my five
v1 CRITICALs. All three unauthenticated paths are gone and none is replaced. The two-generation
lifecycle is a real mechanism that discharges both of my rotation MAJORs. **v2 is not wrong at the
root**, so the escalation trigger does not fire. What it has is one clause that regresses shipped
behavior (N1), one headline claim that its own §1.2 falsifies (N2), and five smaller defects — all
local, all patchable in the document.

---

## R1. Disposition of my §7 items 1–7

| # | Item | Disposition |
|---|---|---|
| 1 | Reframe to detection, not authorization | **DONE** — and strengthened, see R2 |
| 2 | Delete Rule 0b (`re-issue`) | **DONE** — absent from §6.1's table; correctly landed jointly with (5) |
| 3 | Roster-liveness guard before Rule 0 | **REGRESSED** — see R3 and **N1** |
| 4 | Close the environment channel | **DONE** — §6.5, no channel at all |
| 5 | Fix the rotation contract | **DONE** — §5.3/§5.4 discharge M1 and M2; two new defects live inside it (**N3**, **N4**) |
| 6 | `sup-release --force --confirm-inc` goes | **DONE** — and the replacement is genuinely narrower, see R4 |
| 7 | The seven missing sections | **DONE** — six written well; one is moot-until-(b) and §14 says so; §8's touched list is short by one (**N5**); §5.8's human-form half is a **SPURIOUS-FIX**, see R5 |

**No item is NOT-DONE.** One is REGRESSED, and one sub-item is a SPURIOUS-FIX.

## R2. Item 1 — verified, including the strengthening receipt

§2.3 claims the obvious authorization candidate (prompt a human) is already refuted in shipped code.
I ran it myself, widened to show the surrounding context:

```
$ sed -n '2044,2056p' bin/fleet.py
    interposing prompts there would break every existing script for no safety
    gain -- a human typing `fleet clean` meant to type it. The threat model is
    an over-helpful agent, especially one under `bypassPermissions` where no
    permission prompt is ever shown.

    There is deliberately NO interactive prompt. An agent's Bash tool has no
    stdin to answer one with (it gets an EOFError), and `isatty()` cannot tell
    the two apart on Windows anyway: Git Bash's `/dev/null` is `NUL`, a
    CHARACTER DEVICE, so `sys.stdin.isatty()` returns True under
    `fleet kill x < /dev/null`. An agent must pass --yes; there is nothing to
    prompt."""
```

**Exact, and the strengthening is real.** My Q1 said the trust boundary was missing; §2.1 draws it
and §2.3 closes the one escape I had left implicit. An author that answers a finding by making it
*stronger* against itself is the behavior this gate is supposed to reward, and I am recording it as
such.

## R3. The dispute on item 3 — `DISPUTE-UPHELD`, and the amendment nonetheless regresses

**Ruling: `DISPUTE-UPHELD`.** All three receipts verify exact; I ran each myself.

```
$ sed -n '6986,6999p' bin/fleet.py
def _roster_live_sids(entries: list) -> set:
    """Sids whose backing process is LIVE. Contract rule
    (docs/specs/native-substrate.md, roster contract): `status`/`pid` keys
    exist only while the process lives; a lingering `state:"done"` entry
    (observed surviving >=3h21m) must NOT count as live, or a finished
    predecessor would block every successor claim for hours."""
    ...
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
    }

$ sed -n '7020,7024p' bin/fleet.py
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    holder_sid = claim.get("session_id")
    if holder_sid in live_sids:
        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "

$ sed -n '627p' knowledge/lessons.md
**Claim-protocol wart found live:** `sup-boot` REFUSES its own holder when the heartbeat is stale
(>60m) — after an overnight gap the same-sid manager could not re-boot its own claim (VERDICT
refuse/freeze), only `sup-heartbeat` (which doesn't gate on staleness) recovered it. ...
```

The author is right and my adjudicated parenthetical was wrong. A resumed, running holder carries
`status`/`pid`, so it **is** in `live_sids`; the unconditional refusal at `7023` fires before any
later branch; and the recorded verdict is `refuse`, not the `seize` a roster-gone holder would have
produced. Under the strict clause *"grant `resume` only when the recorded holder is roster-gone"*,
incident 2 lands on the guard and is refused again — **the strict form does not fix incident 2.** My
C2 asked for the guard to run first; it does. The parenthetical was an over-specification I attached
to it, and the dispute correctly removes it.

**But the amendment as drafted is not a smaller version of the right fix — it is a different fix with
a hole**, and that hole is N1. The dispute is upheld; the disposition of item 3 is still REGRESSED,
because the implemented clause makes one case strictly worse than shipped code. Those are compatible
findings and I am deliberately not collapsing them.

## R4. Item 6 — the bounded seize path *is* genuinely narrower

The manager asked whether §6.3's replacement is *"the same seizure with a smaller name."* It is not.

| | `sup-release --force --confirm-inc` (v1, deleted) | The `seize` path (v2) |
|---|---|---|
| Input needed | the incarnation id — **printed by `sup-status`** | none |
| Wait | **none** | heartbeat must age past `SUPERVISOR_CLAIM_STALE_SECONDS` = 3600 s (@6821) |
| Precondition on the holder | **none — works against a live, beating supervisor** | holder must be roster-gone |
| Audit record | `RELEASED` + `BOOT` — reads as a clean, planned succession | `SEIZED` — reads as what it is |

A live supervisor that is beating keeps **both** preconditions false, so the seize path cannot touch
it; v1's `--force` could, instantly. The one-hour wait and the `SEIZED` entry are the narrowing, and
they are real. Item 6 is correctly discharged. (§12 O2 re-puts the escape to the operator; that is
the right place for it and I have no objection to the recommendation to leave it removed.)

## R5. `SPURIOUS-FIX` — §5.8's human-form redaction

§5.8 binds `cmd_sup_status` to omit the hashes from **"both the `--json` and the human forms"**, and
T15 asserts their absence in both. The `--json` half is the whole fix, and it is correct — §4.8's
receipt shows `"incarnation": claim` dumped verbatim. The **human** half is ceremony: that line is a
hand-written f-string over named fields (`incarnation_id`, `session_id`, `claimed_via`, heartbeat
age), so it has never contained a hash and no implementation slip could put one there.

This is precisely the failure mode I filed as v1's **m1** — *"T14 asserted the nonce string was
absent, and the nonce string was never in the file"* — reproduced one layer out. Harmless, but it is
a test that cannot fail dressed as a regression guard, and the vocabulary exists to name it. Scope
§5.8's rule and T15 to the dict-dumping paths.

---

## R6. New defects

### N1 — CRITICAL. §6.1 rule 2's narrow amendment lets a caller who sets one environment variable `seize` a live, healthy supervisor's claim — which shipped code refuses unconditionally

**The verdict order as drafted (§6.1):**

- rule 2: `holder_sid in live_sids` **and** `holder_sid != caller_sid` ⇒ `refuse`
- rule 3: `nonce_valid` **and** (`holder_sid not in live_sids` **or** `holder_sid == caller_sid`) ⇒ `resume`
- rules 4–: *"unchanged"*

**The defect is in what "unchanged" means.** The shipped branches below the guard have **no roster
test at all** — "roster-gone" is only ever an *implication* of having already passed the
unconditional refusal at `7023`:

```
$ sed -n '7025,7042p' bin/fleet.py
    try:
        beat = _parse_iso(claim["heartbeat_at"])
    except (KeyError, TypeError, ValueError):
        return ("freeze", "claim heartbeat unreadable -- ambiguous; never seize on ambiguity")
    if latest_entry is not None and latest_entry.get("inc") != claim.get("incarnation_id"):
        ...
            return ("refuse", f"journal's latest checkpoint is a fresher incarnation "
                              f"({latest_entry.get('inc')}) -- transition in flight")
    age = (now - beat).total_seconds()
    if age > stale_seconds:
        return ("seize", f"holder roster-gone, heartbeat stale ({age:.0f}s > {stale_seconds:.0f}s)")
    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")
```

`holder roster-gone` appears in both reason strings and is tested by neither. v2 weakens the
premise those strings depend on and leaves the branches "unchanged", so the implication silently
becomes false.

**The interleaving.** Live claim, holder body H running normally, `session_id = S_H`, heartbeat aged
past 3600 s (see below — this is the normal state, not a contrived one). Caller X holds no nonce.

| step | actor | action | result |
|---|---|---|---|
| 1 | X | `py -3.13 bin/fleet.py sup-status` — a lock-free, unauthenticated view | prints `sid=S_H`, per my first gate's live receipt |
| 2 | X | `CLAUDE_CODE_SESSION_ID=S_H py -3.13 bin/fleet.py sup-boot` | — |
| 3 | rule 1 | `state` is not `released` | fall through |
| 4 | **rule 2** | `S_H in live_sids` is **True** (H is running) — but `holder_sid != caller_sid` is **False** | **does not refuse** |
| 5 | rule 3 | `nonce_valid` is False | fall through |
| 6 | rules 4– | heartbeat readable; journal's latest inc == claim's inc; `age > 3600` | **`seize`** |
| 7 | — | new incarnation minted, INCARNATION overwritten, `SEIZED` journalled bodied *"seized from …: holder roster-gone, heartbeat stale"* | **the reason string is false — the holder was roster-live** |

**Against shipped code today, step 4 returns `refuse` and the sequence ends.** So this is not a
residual the spec inherits; it is a regression the amendment creates.

**Why the stale-heartbeat precondition is the normal case, not a contrived one.** There is no
automatic beat — `fleet beat` is a §3 non-goal and the spec's own §7(b) says so. The only beat is a
human-typed verb. My first gate's live receipt measured the then-current holder's heartbeat at
**2257 s** — 63 % of the way to the threshold — on an actively-managed fleet with six live workers.

**This is the exact failure shape the manager predicted: a trust boundary stated in §2 and violated
in §6.** §2.1's own capability table lists *"Set any environment variable, including
`CLAUDE_CODE_SESSION_ID`"* with the receipt that `current_caller_session()` is one `os.environ.get` —
and §6.1 rule 2 then uses `caller_sid` as the discriminator that decides whether the guard applies.
§2.1 says no stored value can authorize; rule 2 lets a settable one **de-authorize a guard**, which
is the same mistake with the sign flipped.

**The fix is one clause, and it keeps the dispute's win intact.** Rule 2 must be:

> `holder_sid in live_sids` **and not** (`holder_sid == caller_sid` **and** `nonce_valid`) ⇒ `refuse`

Check it against all four cases: incident 2 (same sid, running, holds its generation) ⇒ not refused,
falls to rule 3 ⇒ `resume` ✓ — the dispute's requirement is preserved exactly. Incident 1's fork
with a *distinct* sid and a valid generation ⇒ refused ✓. A same-sid spoofer with **no** generation
⇒ refused, as today ✓. A roster-gone holder ⇒ untouched ✓. Continuity, not a self-asserted sid,
becomes the thing that unlocks the guard — which is what §5.1 says the nonce is for.

**Additionally**, whichever form is chosen: the `seize`/`freeze` reason strings must stop asserting
`roster-gone` unless the branch tests it, or add the test. A `SEIZED` journal entry — append-only,
git-tracked — that records a false precondition is a durable corruption of the audit record, and the
journal is the only artifact a future incident review will have.

### N2 — CRITICAL. Under §7's recommended option (a), incident 1 produces no refusal at all; §5.6 and §7 contradict each other

The spec's headline benefit, stated four times:

- §7: *"**Whatever the operator chooses, incident 1 becomes a refusal.**"*
- §7(a): *"Detection only — no gate. … **Incident 1 surfaces within two supervisor actions.**"*
- §5.4(c): *"measured against incident 1 it is ~100 minutes … versus **a refusal within two supervisor actions**"*
- §2.2: *"Claims: divergence detection. A second body of the same lineage, acting concurrently, is surfaced by a loud refusal"*

Now the spec's own load-bearing facts:

- **§1.2, stated as one of *"two facts [that] bind the design"*:** *"**The zombie never ran a `sup-*`
  verb** — it ran `fleet send`, seven times, over ~100 minutes."*
- **§5.6:** *"**Bodies that do not present a nonce are unaffected** — this is a continuity signal, not
  a capability."*
- **§5.3:** minting happens *"only on a `sup-*` verb"*; *"**Gated mutating verbs, if a gate is ever
  adopted (§7), validate without minting.**"*
- **§3:** *"**Not the claim gate.**"* §7 recommends **(a)**, under which `fleet send` presents nothing
  and is refused by nothing.

**Compose them.** Under (a), the only actor that ever presents a generation is a body running
`sup-*`. The incident-1 zombie ran zero. **It never touches the mechanism: no validation, no
refusal, no rejection record, `_doctor_check_supervisor_claim` stays `ok=True`, and the real body's
generations advance undisturbed because it is the only presenter.** The outcome is byte-for-byte
today's outcome — ~100 minutes, seven phantom dispatches, discovered by transcript identity, a
process census and event-timeline correlation.

§5.6 is the sentence that is right. §7's *"whatever the operator chooses"* is the sentence that is
wrong, and it is the one carrying the recommendation.

**Why this matters more than a wording slip.** The adjudication's sequencing item 3 —
*"the detection-only slice may be worth shipping ahead of any gate decision — both lenses
independently say it stands alone"* — is an operator-facing recommendation resting on this claim.
And it is the same gap that made **v1** choose the gate in the first place: v1 §1.2 quoted my
three-tier break lens verbatim — *"A nonce that only the journal checks stops a zombie from
journaling. It does not stop a zombie from spawning workers, sending phantom steers (7 observed)"* —
and reasoned from it to *"claim-gate the mutating verbs."* v2 correctly unwinds the gate **and then
re-claims the benefit the gate existed to deliver.** The unwinding is right; the claim must go with
it.

**What the spec must say instead.** State the detected class precisely, in §2.2, §5.4(c), §5.6 and
§7, in one consistent form:

> Under (a), a divergent body is detected **iff it runs a `sup-*` verb**. That is a real and
> important class — a fork that checkpoints, heartbeats, releases or hands off is caught within one
> or two supervisor actions. **It is not incident 1 as recorded**, whose zombie confined itself to
> `fleet send`. Extending detection to the mutating verbs is exactly what option (b) buys, and that
> is the honest statement of what (b) is for.

That correction also repairs §7's own framing. §7 currently corrects v1's cost statement by saying
detection lives in the rotation rather than the gate — true — and then overshoots into *"whatever the
operator chooses."* The accurate version is: **deferring the gate keeps detection for `sup-*`-active
second bodies and drops it for `send`-only ones.** With that sentence written, O1 becomes a real
choice instead of one with a free option; without it, the operator is choosing (a) on a false
premise. **I do not recommend a different option** — (a) may still be right, and (b)'s own
accounting in §7 is honest and damning. I recommend only that the price of (a) be stated.

### N3 — MAJOR. The pending TTL discards a *delivered* generation, refusing the body that holds it — and it systematically refuses the slower body, which is normally the legitimate one

§5.3: *"mint iff `pending_nonce_hash` is absent **or** `now - pending_at > PENDING_NONCE_TTL_SECONDS`
(proposed 300 s)."* Validation has no TTL, so a stale pending stays presentable — good. But a **new**
mint **overwrites** the outstanding pending, and the spec never asks where the old one went.

**Constructed interleaving.** Live generation *G*. Body **A** is the legitimate, human-attached
supervisor; body **B** is a fork of A holding only *G* (§5.5).

| t | actor | action | INCARNATION after | who holds what |
|---|---|---|---|---|
| 0 | **A** | `sup-checkpoint --nonce G` | live *G*; pending *P1*, `pending_at`=0 | A holds *P1* |
| 0–310 | A | one long turn — reasoning, a compaction, a human reading the checkpoint. Nothing is wrong. | unchanged | — |
| 310 | **B** | `sup-heartbeat --nonce G` — *G* is still live, nothing acknowledged ⇒ **valid** | mint check: `pending_at` is 310 s > 300 s ⇒ **mint *P2*, overwriting *P1*** | B holds *P2*; **A's *P1* is now dead** |
| 320 | **A** | `sup-checkpoint --nonce P1` | *P1* is neither live (*G*) nor pending (*P2*) ⇒ **REFUSED** | exit 4, rejection record, doctor `ok=False`, *"a second body of your lineage may be acting; stop and escalate"* |
| 330 | **B** | `sup-checkpoint --nonce P2` | **acknowledged**: live ← *P2*, `nonce_seq`++ | **B owns the chain** |

The alarm is correct and the attribution is **inverted**: the body that stops and escalates is the
legitimate one; the divergent body proceeds with a valid generation and, per §5.7, A is locked out of
`sup-*` for up to an hour — during which B can `sup-release` or hand the claim off.

**§5.4(c)'s narrative asserts the opposite outcome** (it casts the refused body as the divergent one)
and never states that the mechanism cannot prefer either. It cannot: both present byte-identical
values, which §2.1 and §5.5 both say. But the TTL is not neutral — **it makes the winner the body
that acts most often inside a 300 s window**, which systematically favours an automated or looping
body over a human-attached one that thinks. That is the wrong bias for this system.

**A second-order tension the spec does not notice.** §5.4(b) wants the TTL *short*, so a pending lost
to a failed verb is replaced quickly. N3 wants it *long*, so a delivered pending is not stolen from a
slow body. 300 s is below a routine supervisor turn in this project. The two requirements pull in
opposite directions and §5.3 states only one of them.

**And the one artifact the design produces cannot tell the operator which case happened.** §5.6's
rejection record stores `presented_prefix` = the first 8 hex of the presented value's sha256. At
t=320 the file no longer stores H(*P1*), so nothing in the record distinguishes *"a superseded
pending — the TTL fired"* from *"a stale or forged value — a real second body."* Those are the two
cases the operator most needs to tell apart, and they are the whole point of the log.

**Fix directions** (the spec should pick one and say so): retain the superseded pending for one more
generation and accept it once with a distinct, quieter record; or refuse to overwrite an outstanding
pending at all and let the TTL only *expire* it into absence; or, minimally, record `pending_at` and
the discarded pending's hash prefix in the rejection record so the two cases are separable after the
fact. Any of these needs a test; §10's T7 tests only that a stale pending is replaced and a fresh one
is not — it never asserts what happens to the body holding the replaced one.

### N4 — MAJOR. The acknowledgment is the only thing that ever retires a generation, and the obligation to perform it is nowhere specified

§5.3 defines what the *validator* does with each presented value. It never defines what the
*presenter* must present. Yet the entire detection property depends on one unstated rule: **a body
must present the newest value it was given.**

Trace it. A generation dies *"only when its successor is proven received"* (§5.3). A successor is
proven received only when someone presents the pending. If every body keeps presenting the **live**
value — which is always valid, by rule 1, forever — then:

- no acknowledgment ever occurs;
- `nonce_seq` never advances;
- §5.4(c)'s divergence never fires;
- **two bodies of one lineage both validate indefinitely**;
- there is **no refusal, no rejection record, and `_doctor_check_supervisor_claim` stays `ok=True`.**

That is the **silent miss** — no alarm and no artifact, which is strictly worse than a false alarm,
and it is the class v1's design could not produce (v1 rotated on every call, so a second body was
refused immediately; that was M1's false-positive problem, and v2 has traded it for this).

It is not hypothetical. A body presents `live` rather than `pending` whenever it did not read, or did
not retain, the minted value: a `NONCE: unchanged` line in a batch (§5.4(a) *guarantees* calls 2..N
see exactly that); a verb whose output was truncated; a supervisor that keeps its generation in a
scratch file and re-reads it; a compaction that drops the newest line but keeps an older one. §5.4(b)
explicitly builds on `live` staying valid after a lost pending — the same property that, if a body
never advances, silently disables detection.

**What the spec must add.** A named, testable presenter obligation in §5.3 — *the holder presents the
most recent generation it received; presenting a superseded-but-live generation is permitted for
recovery and is recorded* — plus the observability that makes a violation visible rather than silent:
an `unacknowledged pending older than N` condition surfaced by `_doctor_check_supervisor_claim`
alongside the rejection count, and `pending_present` / `pending_at` age in the §5.8 projection (which
already publishes `pending_present`, so the cost is one integer). And a test: §10 has no case where a
body repeatedly presents `live` and never acknowledges — T5 asserts exactly that shape succeeds
within one batch, and nothing asserts what it means across many.

Note this obligation is enforceable only by prose in `skills/fleet/supervisor.md`, which §8 already
lists as touched. That is acceptable — §5.7 already concedes one audience-boundary convention and
labels it as a convention, not a mechanism. This one must be labelled the same way, and it currently
is not labelled at all.

### N5 — MAJOR. A cleanly released claim reads as a corrupt one to every view, including the SessionStart nag in every Claude session on the box

§6.3 enumerates the post-release key set and **removes `heartbeat_at`**. `supervisor_status_line` —
the one supervisor consumer outside `bin/fleet.py`, per §4.8's own receipt — reads it:

```
$ sed -n '7503,7530p' bin/fleet.py
def supervisor_status_line(now=None):
    """One-line supervisor status/nag for VIEWS (SessionStart hook, doctor,
    sup-status). File-only by mandate ..."""
        ...
        claim = read_incarnation()
        if claim is None:
            return ("SUPERVISOR: GOALS active, no claim -- boot one "
                    "(`fleet sup-boot`; see skills/fleet/supervisor.md).")
        inc = claim.get("incarnation_id", "?")
        try:
            age = (now - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
```

A released claim is not `None`, so the first branch is skipped; `heartbeat_at` is absent, so the
`KeyError` arm fires. **After a correct, planned `fleet sup-release`, every consumer of this line
reports `heartbeat unreadable -- inspect supervisor/INCARNATION`** — i.e. tells the operator their
cleanly released claim is corrupt, and points them at the file.

Blast radius, from §4.8's own receipt (`bin/hooks/sessionstart_fleet.py:126`): that hook fires in
**every Claude Code session on this machine**, and the line also feeds `fleet doctor`'s
`supervisor-claim` row and `sup-status`'s nag. So the doctrine §6.3 introduces — *release, then
`claude stop`* — produces a persistent, machine-wide false corruption warning as its **normal**
outcome, until someone boots a new claim.

This is the *"invariant listed as preserved that the new design breaks"* class. §8's touched-artifact
table lists `docs/SPEC.md §13`, both `skills/fleet/` files and `_render_successor_task`, but **not
`supervisor_status_line`** — and §5.8's projection rule is scoped to `cmd_sup_status`'s dicts, which
is a different function. v1 never hit this because v1's released claim kept `session_id` and
`heartbeat_at` unspecified; §6.3's enumeration is the *right* fix for my M3 and it is what exposes
this.

**Fix:** add a released branch to `supervisor_status_line` ahead of the heartbeat read — *"SUPERVISOR:
claim `<inc>` released `<age>` ago — boot one (`fleet sup-boot`)"* — and add the function to §8's
table and to §10 (no test in the plan touches it; T12 covers `_require_claim_holder` and `sup-boot`
against a released claim, not the view).

### N6 — MINOR. §5.9's writer-side truncation breaks the atomic-append property, exactly when two writers are concurrent

§5.6: the refused caller *"appends one JSON record"*. §5.9: *"the writer truncates to the most recent
200 records."* Those are different operations. This codebase has a deliberate primitive for the
first:

```
$ grep -n "def _atomic_append_bytes" -A 8 bin/fleet.py
6136:def _atomic_append_bytes(path: Path, data: bytes) -> None:
6137-    """Single-syscall atomic append. Opens the file for FILE_APPEND_DATA
6138-    access ONLY (no GENERIC_WRITE) -- the Win32 kernel documents this access
6139-    mode as giving each WriteFile call atomic append semantics across
6140-    concurrently-open handles/processes, so two writers appending "at the
6141-    same instant" (Stop hook + fleet-side tombstone, see module banner)
6142-    never interleave or clobber each other's line.
```

Truncate-to-200 is a read-modify-write and needs `GENERIC_WRITE`, which is exactly the access mode
that docstring says forfeits the guarantee. And the concurrent-writer case is not exotic here — **it
is the case the file exists to record**: two bodies of one lineage, both being refused, both
appending. The bound I asked for in M6 is right; this form of it can lose the very records that
prove the incident.

**Fix:** keep the append atomic and bound the file elsewhere — doctor already *"reads only the tail"*
(§5.9), so the cap can be enforced by `fleet clean`'s sweep or by an occasional out-of-band
compaction under `fleet_lock`, not by the unauthenticated refused caller. §10's T17 asserts the
truncation, so it would lock the wrong shape in.

### N7 — MINOR. §1.2's binding fact *"the zombie never ran a `sup-*` verb"* is an inference the record cannot establish, and it is load-bearing in both directions

I read the source myself rather than the spec's quote of it:

```
$ sed -n '94,97p' supervisor/JOURNAL.md
## 2026-07-16T16:11:19Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-...

INCIDENT RESOLVED: dual supervisor bodies. Phantom steers (14:23Z-16:03Z, 7 sends: 'final
micro-wave', 'One last LOW advisory', 'URGENT root-cause task', ...) came from c787a667 ...
Confirmed via transcript identity (same first user message), process census (fork-session --resume
cmdline), event-timeline correlation (each phantom seconds-minutes after mine). ... Claim-protocol
gap exposed: both bodies share incarnation id + sid -- sup-claim cannot discriminate bodies of one
lineage ...
```

The entry enumerates **seven sends** and the three forensic methods, all of which are
dispatch-oriented. It does **not** say the zombie ran no `sup-*` verb — and it cannot be made to,
because the same entry records that *both bodies share incarnation id + sid*, so a zombie
`sup-checkpoint` would have been **indistinguishable** in the journal from the real body's.

The spec states this as one of *"two facts [that] bind the design."* It is a well-supported inference
and it is probably true, but it is not a receipt, and this spec is otherwise scrupulous about that
distinction (§5.5 marks a weaker inference `[MANAGER-VERIFICATION REQUIRED]`). Label it the same way.

It matters because it is load-bearing **in both directions**: it is the premise of N2 (if the zombie
ran no `sup-*` verb, option (a) never fires) and, inverted, it is the only thing that would rescue
§7's claim (if it *did* checkpoint, (a) catches it). The spec cannot rely on the fact in §1.2 and
contradict it in §7. Whichever way it is stated, N2's correction is still required, because
*"whatever the operator chooses"* is false for a `send`-only body regardless.

---

## R7. What is right in v2, recorded

- **§2 is the section v1 needed and is correct.** Its capability table is receipted, its conclusion
  (*a secret proves continuity, never entitlement*) is the right generalisation of v1's own §4.5, and
  §2.3 strengthens my finding against itself with a shipped-code receipt (R2).
- **All three unauthenticated paths are gone and none is replaced.** Verified against §6.1 (no Rule
  0b), §6.3 (no `--force`), §6.5 (no env channel), §11's command surface, and §14's disposition.
- **The two-generation lifecycle genuinely discharges M1 and M2.** §5.4(a) removes the false alarm on
  a batched body; §5.4(b) removes the rotate-then-fail lockout, and doing it in the same wave as the
  Rule 0b deletion is the correct joint landing the adjudication demanded. N3 and N4 live inside the
  new mechanism; they do not undo it.
- **§5.7 and §5.8 are the two best new sections.** §5.7 audits the refused body — v1's most expensive
  omission — and reaches the right answer (*add no fourth path*), including the honest labelling of
  the agent/human audience split as *"a convention, not a mechanism."* §5.8 fixes my m1 exactly,
  including naming why v1's test would have passed.
- **§7's option accounting is honest and damning about its own (b)** — the heartbeat-arming window,
  the structurally-exempt autoclean caller, the corrected verb taxonomy. N2 is a defect in (a)'s
  benefit claim, not in this accounting.
- **§9's legacy predicate** (`nonce_hash` absent **and** `state` absent) plus §6.3's enumerated key
  set is a complete and correct fix for my M3, including the second-order reasoning about a future
  reader re-introducing a sid comparison.

## R8. Fix list, ordered

1. **N1** — one clause in §6.1 rule 2 (`and not (holder_sid == caller_sid and nonce_valid)`), plus
   the `roster-gone` reason strings. Blocking: it regresses shipped behavior.
2. **N2** — state the detected class precisely in §2.2, §5.4(c), §5.6 and §7; delete *"whatever the
   operator chooses, incident 1 becomes a refusal."* Blocking: O1 is otherwise decided on a false
   premise, as is the adjudication's ship-detection-first sequencing.
3. **N3** — decide and specify what happens to a superseded pending; state the TTL tension; make the
   rejection record separable. Add the test.
4. **N4** — write the presenter obligation, label it a convention, and give it an observable
   (`unacknowledged pending age`) plus a test.
5. **N5** — released branch in `supervisor_status_line`; add it to §8 and §10.
6. **N6** — keep the append atomic; bound the log out of band; retarget T17.
7. **N7** — label §1.2's inference as an inference.

None of these is structural. **`VERDICT: fix-list(N1, N2, N3, N4, N5, N6, N7)`.** The escalation
trigger — *v2 wrong at the root again* — **does not fire**: the root is fixed, and I am recording
that as the finding it is.

**Ratified nothing. Promoted nothing.** `Status: drafting` verified at line 3. §12's O1–O4 remain the
operator's; my only recommendation on them is N2's — that O1's option (a) be re-put with its real
price stated, not that a different option be chosen.

---

# FINAL GATE — `claim-nonce.md` v3 @ `cecaed2`

**Reviewer:** `me-nonce-break`, same worktree/branch. **Under review:** `docs/specs/claim-nonce.md`
@ **`cecaed2`** on `me/nonce` (wave 2: `+937 / −203`, plus a new `tools/verify_receipts.py`).
**Scope, per the manager: narrow** — my two CRITICALs and what they touched. The receipt lens owns
receipts and the harness; I have not duplicated it.

**Status check.** Line 3 reads ``**Status:** drafting (`me-nonce`, v3 fix wave 2026-07-21)`` —
**`drafting`, unchanged**, and the `me/nonce` worktree is clean. Nothing ratified, nothing promoted,
no `[PENDING OPERATOR RATIFICATION]` row touched. O1/O1b/O2/O3/O4 left open.

**Who ran what.** 6 receipts this turn (34 cumulative), all by me, all read-only — including one
**executed differential harness** (R-N1 below) that calls the shipped pure function
`supervisor_claim_decision` with synthetic arguments under a scratch `FLEET_HOME`. No fleet verb of
any kind was invoked; no `sup-*`; nothing written outside my own worktree and this job's temp dir.
Probe-context clause unchanged: I am a `--bg` worker and a live daemon client, and nothing below
rests on dead-daemon behavior.

## **`VERDICT: sound`** — with three residuals named in R-F.

Both CRITICALs are fixed, and N1's fix is confirmed by execution rather than by reading. N3–N7 are
fixed. The SPURIOUS-FIX was reverted and the revert **net-added** a real guard. The three residuals
are document-completeness items; one of them (F2) is a build-time trap the operator should see
closed before a build starts, and none of the three changes a decision or creates a hazard as it
stands.

**`ESCALATE` does not fire.** Nothing is wrong at the root. The root was fixed in wave 1 (detection,
not authorization) and wave 2 did not disturb it.

---

## R-N1. The regression is gone — executed, not asserted

`supervisor_claim_decision` is a pure function with no IO, so the spoof can be run rather than
argued. I wrote a harness that imports `bin/fleet.py` with `FLEET_HOME` pointed at a scratch temp
dir, calls the **shipped** function with the spoof inputs, evaluates **v3 §6.1**'s rule order over
the same inputs, and — for comparison — evaluates **v2's** clause. Holder sid `S_H` is the value
`sup-status` publishes; heartbeat aged 4000 s (> `SUPERVISOR_CLAIM_STALE_SECONDS` = 3600.0); the
holder is **roster-live and healthy** in every case but the last.

```
$ FLEET_SRC=C:/proga/fleet-me-nonce-break py -3.13 n1_spoof.py
SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0
heartbeat age at NOW = 4000s (stale)

case                                                           SHIPPED    v3 6.1
------------------------------------------------------------------------------------
N1 ATTACK: env-spoofed holder sid, NO generation, holder roster-LIVE  refuse   refuse   (rule 2 -- roster-liveness guard)
Incident 2: same sid resumed+running, holds its generation           refuse   resume   (rule 3 -- continuity proven)
Incident 1 fork: distinct sid, valid generation, holder roster-live  refuse   refuse   (rule 2 -- roster-liveness guard)
Holder genuinely roster-gone, no generation, heartbeat stale         seize    seize    (holder roster-gone, heartbeat stale (4000s > 3600s))

-- v2's clause, same N1 attack inputs, for comparison --
v2 verdict for the N1 attack: ('seize', 'holder roster-gone, heartbeat stale (4000s > 3600s)')
```

**Read the first and last lines together.** v2's clause returns **`seize`** against a live, healthy
supervisor — and the reason string it would have written into the append-only, git-tracked journal
says *"holder roster-gone"* while the holder was roster-live. That is the regression, reproduced.
v3 returns **`refuse`**, identical to shipped behavior, and the only row where v3 diverges from
shipped code is incident 2 — which is the wart the slice exists to fix.

So: **`n1-spoof = refuse`.** Rule 2 is keyed on continuity
(`and not (holder_sid == caller_sid and nonce_valid)`), which is the clause I prescribed, and the
env-var spoof no longer decides whether the guard applies.

**Rules 4– now test roster-liveness explicitly** (§6.1's row 4– carries *"and only when
`holder_sid not in live_sids`"*), rather than inheriting it from a refusal that wave 2 had weakened.
That closes the mechanism by which the regression became reachable. I verified the invariant holds
by construction as well as by test: reaching rule 4 requires rule 2 not to fire and rule 3 not to
fire, and the only way rule 2 does not fire while `holder_sid in live_sids` is
`holder_sid == caller_sid and nonce_valid` — which makes rule 3 fire. Rule 4 is therefore reachable
only with the holder roster-gone. See **F2** for the one thing that is still unstated about it.

**The journal-write test the manager asked about.** T14b — *"no `seize` or `freeze` verdict is
returned while `holder_sid in live_sids`"* — is the right test and it does cover the write. The
`roster-gone` string is written by `supervisor_journal_append` downstream of the verdict; preventing
the verdict prevents the write, and asserting on the pure function is the correct altitude (it is
the only place the condition is decidable). T14(iii) pins the attack itself and, as the spec says,
fails against v2's clause and passes against v3's. **Adequate.**

## R-N2. The analysis is correct, not merely rewritten

§7 now states, per option, what incident 1 produces, **before** the recommendation, in a table. I
checked the analysis against the mechanism rather than against the prose.

**Option (a) → nothing.** Under (a) the only actors presenting a generation are `sup-*` callers
(§5.3: minting *"only on a `sup-*` verb"*; §5.6: *"bodies that do not present a nonce are
unaffected"*; §3: no gate). The incident-1 zombie ran only `fleet send` (§1.2 fact 1, now correctly
tagged — see N7). It therefore never validates, never mints, never acknowledges: no refusal, no
rejection record, doctor stays `ok=True`, and the real body's chain advances undisturbed because it
is the sole presenter. **Correct.**

**Option (b) → a refusal.** Under (b) gated mutating verbs *"validate without minting"* (§5.3). The
zombie holds generation *G* (a transcript fork, §5.5). Its `fleet send` presents *G*, which is still
live because nothing has acknowledged — **accepted**. The real body's next `sup-*` call presents its
pending and acknowledges; *G* dies. The zombie's next gated verb presents *G* → neither live, nor
pending, nor prior-pending → **refused**. That is exactly §7's table row: *"at the zombie's first
gated verb after the real body's next acknowledgment."* **Correct.** And it is if anything
understated — a zombie that presents *no* nonce is refused by the gate immediately.

**So the narrowed recommendation is true of the mechanism as specified:** (a) discharges the slice's
mandate (three-tier item 1 — identity across fork-steer/respawn/handoff), fixes incident 2 (§6.1
rule 3, confirmed in the harness above) and incident 3 (§6.3), and **does not close incident 1**;
**(b) is the only option that does.** This is the sentence the manager's sequencing was wrong about,
and it is now right. **`n2-analysis = correct`.**

Two supporting checks:

- **The qualifier is not lost.** §7(b)'s own accounting still says the gate is armed only while the
  heartbeat is fresh and that *"Incident 1 ran ~100 minutes; the window is 60"* — so (b)'s refusal is
  not unconditional. The table row does not carry that caveat, but the recommendation bullet
  immediately below does, in the operator's own decision text (*"a speed-bump armed for one hour
  after a human last typed a command"*). Not a softening; the price is where the choice is made.
- **§5.6 and §7 no longer contradict.** §5.6's guarantee now carries the explicit *"Not 'incident 1
  becomes a refusal'"* clause and names the detected class. §2.2 and §5.4(c) carry the same bound.
  The four places v2 asserted the opposite are all corrected.

**O1b states the re-scope honestly.** It says outright that the adjudication's open question 2 rested
on a premise that *"is false"* — that detection is independent of the gate — and recommends shipping
(a) *"as the continuity fix it is, not as incident-1 coverage"*, with the alternative put as treating
(a) as a **partial delivery**. That is the re-scope stated at full strength, not softened.

## R-N3–N7 disposition

| # | Disposition | Verified by |
|---|---|---|
| **N3** pending-TTL overwrite inverts attribution | **FIXED** | §5.3 adds `prior_pending_hash` and a *quiet* `superseded-pending` record (validation rule 3: accept, promote nothing, **not** an alarm); §5.4(d) states the bias and what the slot does and does not buy; TTL raised to 900 s **with the asymmetry argument** — a long TTL only delays *replacement* of a lost pending while the body keeps working on `live`, a short one *actively invalidates* a value a legitimate body holds. The asymmetry is real and correctly directed. T7 extended to the missing half. See **F3**. |
| **N4** unspecified acknowledgment — the silent miss | **FIXED** | §5.3 writes the presenter obligation (*"the holder presents the most recent generation it was given"*) and labels it *"a convention, not a mechanism"*, with the reason it is unenforceable; §5.4(e) states the failure in full including doctor-green; §5.6 adds the `unacknowledged pending age` observable; §5.8 publishes `pending_age_seconds`; T9b asserts **both** halves and says why the second is load-bearing. |
| **N5** released claim reads as corruption | **FIXED** | §6.3 carries a *binding build rule* for `supervisor_status_line` @7503-7530; §8 has the row (naming the SessionStart blast radius); T19 asserts via **both** the function and `fleet doctor`'s row; and §4.1 now enumerates all four `read_incarnation()` call sites so `7516` cannot go unassigned again — that last part fixes the *class*, not just the instance. |
| **N6** truncation forfeits atomic append | **FIXED** | §5.6 appends via `_atomic_append_bytes` @6136 by name, with the reason; §5.9 moves the cap out of band under `fleet_lock` and states that the refused caller *"holds no lock and may be the untrusted body"*; T17 inverted to assert no read-modify-write. |
| **N7** inference stated as receipt | **FIXED** | §1.2 fact 1 tagged `[INFERENCE — NOT A RECEIPT]`, with why the record cannot establish it (shared inc **and** sid ⇒ a zombie checkpoint would be indistinguishable) and why it is load-bearing in both directions. |
| **SPURIOUS-FIX** §5.8 human form | **REVERTED, and the revert took no real guard with it** | §5.8 is rescoped to the dict-dumping paths with the reasoning restated. I checked what the revert removed: `7248` is a hand-written f-string over four named fields, and §5.8 separately records that the raw `session_id` published there is *deliberately* not a secret under §5.1 — so there was nothing to guard. **The revert net-added a guard**: §5.8 now also claims jurisdiction over `cmd_sup_boot`'s stdout (the second publisher, with its receipt) and T15 covers both verbs. Narrower rule, wider coverage. |

## R-F. New defects — last pass, aimed at what wave 2 changed

Three, all MINOR, all in text wave 2 rewrote. I looked hardest at the five surfaces the manager
named; these are what survived.

### F1 — MINOR. §5.9 applies two different standards to `fleet clean` in adjacent bullets

Bullet 1 withdraws v2's *"swept by `fleet clean`"* for `state/supervisor-handoff-<inc>.md`, on the
§4.13(g) receipt that every candidate `_remove_worker_files` builds is keyed on a worker name or sid,
and concludes: *"Rather than invent a sweep site §8 does not authorize, the residue gets an
**observable**"* — a `_doctor_check_supervisor_handoff` NOTE. Correct, well-receipted, and **§8 duly
carries the row** for that function.

Bullet 2 then places the rejection-log cap in *"a compaction under `fleet_lock` in a mutating verb
(`fleet clean`'s existing sweep is the natural home — it already holds the lock and already
deletes)"*. That is a sweep site in the same verb, two bullets later — and **§8 has no `fleet clean`
row**:

```
$ sed -n '1903,1946p' docs/specs/claim-nonce.md | grep -i "clean"
(no match; the only new-function rows are `supervisor_status_line` and
 `_doctor_check_supervisor_handoff`)
```

By bullet 1's own standard, bullet 2 invents a site §8 does not authorize. The *outcomes* are both
defensible — unlink-on-completion plus a doctor NOTE is a fine answer for the handoff file, and an
out-of-band compaction is the right answer for the log (it is the fix for N6 and I do not want it
reverted). What is wrong is that a builder reading §5.9 gets contradictory guidance about what may be
added to `fleet clean`. **Fix:** either add the `fleet clean` compaction row to §8 and soften bullet
1's rationale to *"no existing candidate builder covers it"* (which is what the receipt actually
shows), or state the cap as unowned-by-this-slice. One sentence either way.

### F2 — MINOR, and the one to close before a build. §6.1's new roster precondition on rules 4– has no stated `else`

Row 4– reads: *"otherwise, **and only when `holder_sid not in live_sids`** (see below): heartbeat
unreadable ⇒ `freeze`; … heartbeat stale ⇒ `seize`; heartbeat fresh ⇒ `freeze`"*. It never says what
the function returns when that precondition is **false**.

Today the precondition cannot be false at rule 4 — I proved that by construction in R-N1, and my
harness's `<UNDEFINED>` arm never fired across the four cases. **But "cannot be false" is exactly what
`roster-gone` was before N1**: an implication that held until an edit weakened its premise, and whose
failure was invisible because nothing named it. Wave 2's whole lesson is that the precondition must
stop being implicit; leaving its `else` implicit reproduces the shape one level in.

The concrete build hazard: a builder writing `if holder_sid not in live_sids: <branches>` with no
`else` falls off the end and returns `None`, which `rc = {"claim": 0, "seize": 0, "refuse": 2,
"freeze": 3}[verdict]` (shipped, `cmd_sup_boot`) raises `KeyError` on — an unhandled traceback out of
the boot ritual. T14b asserts no `seize`/`freeze` is returned in that state; it does not assert what
*is*.

**Fix, one clause:** state the `else` as **`freeze`**, matching the codebase's own *"never seize on
ambiguity"* doctrine, and extend T14b to assert it. Cheap, and it converts an invariant into a
branch.

### F3 — MINOR. §5.4(d) says `prior_pending_hash` *"stops"* the timeout picking the faster body; it bounds it

§5.3's slot rule is explicit and correct: *"One slot, not a chain: a second replacement drops the
oldest."* §5.4(d) then claims the slot *"stops the **timeout** from silently picking the faster
body."* Compose them: body A holds *P1*; a first replacement moves *P1* → `prior_pending`; a **second**
replacement (another TTL period, another mint by the other body) drops *P1* entirely, and A's next
presentation is refused with the attribution inverted — the v2 failure, delayed by one generation
rather than removed.

The residual is **bounded and defensible**: at 900 s that is >1800 s of one body silent while another
acts twice, and a refusal at that point is arguably correct, because a body that quiet has genuinely
lost continuity. I am not asking for a second slot. I am asking the text to say *bounds to two TTL
periods* rather than *stops*, because §5.4(d) is the section a future author will read when deciding
whether the slot can be dropped, and an overclaim there is how the next N1 gets written.

**Also worth one sentence in §5.6:** a `superseded-pending` record cannot be produced by a
protocol-conforming single body — that body would have to present an older value after a newer one,
which the §5.3 presenter obligation forbids. So the record implies **either a second presenter or a
violated obligation**, and both are conditions the design wants seen. Classifying it as a NOTE rather
than `ok=False` is right (it is not proof of a second body), but "quiet" should not read as "benign".

## R-G. Residuals the operator must see before ratifying

Beyond F1–F3, these are properties of the design as specified, not defects — every one is stated
somewhere in the document, and each is something I would want an operator to have read before
signing:

1. **(a) does not close incident 1.** The slice's motivating incident is not covered by the option
   the slice recommends. §7 and O1b now say so plainly; this is the single most important thing on
   the page.
2. **The silent miss is real and mitigated by a convention.** §5.4(e): a body that never acknowledges
   leaves two bodies validating indefinitely with doctor green. The presenter obligation is prose in
   a skill file, and the only backstop is the `unacknowledged pending age` observable. That is the
   honest ceiling on this substrate, and it is a ceiling.
3. **The mechanism cannot prefer the legitimate body.** §5.4(c): *"The refused body may be the
   legitimate one."* Detection tells the operator that two bodies exist; it never says which is
   which.
4. **The lockout window (O3).** A supervisor that loses its generation is out of `sup-*` for up to an
   hour. Every cheaper recovery re-creates the bypass wave 1 deleted.
5. **`sup-release --force` stays removed (O2)**, so an operator-authorized stop of an
   already-dead body self-resolves only after the hour.
6. **O4 remains `[MANAGER-VERIFICATION REQUIRED]`** — whether `supervisor_epoch_check` passes against
   a genuinely stale roster served by a dead daemon. Every reviewer in this gate, and the author, is
   a `--bg` session and none of us can observe it. I continue to agree it should fold into the parked
   G9 probe rather than gate this slice; no finding in any of my three passes depends on the answer.

## R-H. Recorded, because it bears on how much weight this document carries

Wave 2 fixed all seven of my findings without a single one being argued down, corrected a
SPURIOUS-FIX I named by **reverting** it rather than defending it, and — in §14's R2 note — corrected
an overstated claim the author had made about its *own* verification harness, unprompted, including
that the harness caught one of four defects rather than the four it had implied. The §6.1
binding-item history also records both of the wrong turns on item 3, mine and the author's, without
collapsing either. That is the behavior this gate exists to produce, and the second CRITICAL was
found only because the first gate's fix list was taken literally rather than approximately.

---

**`VERDICT: sound`** — residuals F1, F2, F3 (document fixes; close **F2** before a build) plus the
six operator-facing residuals in R-G. Both CRITICALs verified fixed, N1 by execution. `ESCALATE` does
not fire; nothing is wrong at the root.

**Ratified nothing. Promoted nothing.** `Status: drafting` verified at line 3; O1, O1b, O2, O3, O4
left open and undecided.
