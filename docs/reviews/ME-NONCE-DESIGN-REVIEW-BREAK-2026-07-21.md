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
