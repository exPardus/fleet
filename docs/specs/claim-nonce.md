# Spec: Per-body supervisor claim nonce — divergence detection for the supervisor claim

**Status:** drafting (`me-nonce`, v2 re-draft 2026-07-21). **The author of a spec may never promote
it.** This document is input to a second dual-lens review; only the operator ratifies. Nothing here
is approved, and nothing here changes the status of any other document.

**Mandate:** `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md` §Sequencing item 2 (the slice), and
`docs/reviews/ME-NONCE-ADJUDICATION-2026-07-21.md` binding re-draft items 1–12 (this wave).

**Gate history.** v1 (`ccbbc02`, 1258 lines, 31 receipts) went through a dual-lens design gate:
`ME-NONCE-DESIGN-REVIEW-BREAK-2026-07-21.md` returned **`restructure`**;
`ME-NONCE-DESIGN-REVIEW-SPEC-2026-07-21.md` returned **`fix-list(S1–S24)`** with the factual base
**reliable** (all 31 receipts reproduced byte-for-byte, all three incidents verbatim, nothing
confabulated). The facts were sound and the design they supported was not. §2 of this document is
the section whose absence caused that, and it is now written first.

**Inherits:** `docs/SPEC.md` v3 invariants (additive-schema §4, single-writer registry §4/§16.6,
one-live-session-per-name §16.7, platform-adapter-only OS branching §16.8, G9 epoch freeze §5);
`docs/specs/terminal-surface.md` views doctrine; `docs/specs/native-substrate.md` G-row contract
(read as observed behavior — this spec changes no verdict status there); `CLAUDE.md` repo rules
(`py -3.13` with a 3.10 floor, `bin/fleet.py` stdlib-only single file).

**Receipt pin.** Every fenced block in §4 was executed by me in this worktree and is pinned
`# at ccbbc02`. The v1 receipts were pinned at `238b7ad`; they remain valid verbatim because the
non-docs tree is byte-identical across that range:

```
# at ccbbc02
$ git rev-parse HEAD
ccbbc023ef4dcef3db44769f1f9796e6403b3c6b

$ git diff --stat 238b7ad HEAD -- bin/ tests/ supervisor/ skills/ commands/ .gitignore
$ echo "exit $?"
exit 0

$ git hash-object bin/fleet.py; git rev-parse 238b7ad:bin/fleet.py
562e2848aab6d85e25ba053ee5ef410917c4d4b1
562e2848aab6d85e25ba053ee5ef410917c4d4b1
```

**Disposition of the binding list is recorded in §14.** One item is **DISPUTED in part, with a
receipt** (item 3); every other item is adopted.

---

## 1. Problem

### 1.1 The root cause

`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md:10`, verbatim:

> **The root cause, named identically by both lenses working independently:** fleet identifies
> actors by session id, and every steering primitive the draft relies on (fork-steer — the only way
> to start a turn in an idle session) mints a new session id. The claim protocol (`INCARNATION` sid
> key, `_require_claim_holder` exact-compare, `supervisor_claim_decision` roster join) breaks
> deterministically on the first beat, and degrades into the worst available failure mode:
> freeze-page against a healthy supervisor, then hourly self-seizure polluting the append-only
> journal.

The sid is used as an identity key and fails that job in **two opposite directions at once**:

- **Not stable enough.** The body persists but the sid rotates — fork-steer (`_restamp_after_steer`,
  §4.5), resume-limited's inline restamp (§4.5), respawn's fresh record (§4.5).
- **Not unique enough.** The sid persists but the body forks — a host restart re-hosted the manager
  conversation as a `--fork-session` and produced **two live bodies sharing one sid and one
  incarnation id** (§1.2 incident 1).

### 1.2 The three production incidents

Each anchor re-opened and verified; the spec-lens gate re-verified all three as **EXACT**.

**Incident 1 — dual supervisor bodies, 2026-07-16.** `supervisor/JOURNAL.md:94-96`, entry
`## 2026-07-16T16:11:19Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037`:

> INCIDENT RESOLVED: dual supervisor bodies. Phantom steers (14:23Z-16:03Z, 7 sends: 'final
> micro-wave', 'One last LOW advisory', 'URGENT root-cause task', ...) came from c787a667 -- a
> fork-session resume of THIS conversation created ~20:56 local during a host restart, running
> daemon-hosted with full campaign context, independently re-deriving and dispatching my decisions
> in paraphrase. [...] Claim-protocol gap exposed: both bodies share incarnation id + sid --
> sup-claim cannot discriminate bodies of one lineage

Corroborated at `knowledge/lessons.md:601`:

> The sup-claim CANNOT see this — both bodies share incarnation id + sid; a per-body nonce is the
> fix candidate (logged in three-tier-command.md).

Two facts bind the design. **The zombie never ran a `sup-*` verb** — it ran `fleet send`, seven
times, over ~100 minutes. And **fleet never had a handle on the fork**: it was minted by a host
restart, outside every fleet code path, and its sid reached fleet only via a human process census.

**Incident 2 — `sup-boot` refuses its own holder, 2026-07-17.** `supervisor/JOURNAL.md:146-148`,
entry `## 2026-07-17T13:45:26Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3`:

> Host restart overnight (~10h gap): same sid resumed, heartbeat refreshed (NOTE claim wart: sup-boot
> REFUSES its own holder when heartbeat stale -- self-recognition missing, feeds nonce spec + lessons).

The recovery lever and the observed verdict are recorded at `knowledge/lessons.md:627`, **not** in
the journal entry:

> **Claim-protocol wart found live:** `sup-boot` REFUSES its own holder when the heartbeat is stale
> (>60m) — after an overnight gap the same-sid manager could not re-boot its own claim (VERDICT
> refuse/freeze), only `sup-heartbeat` (which doesn't gate on staleness) recovered it.
> Self-recognition is missing from the claim decision; feeds the nonce spec.

The mechanism is structural: **`supervisor_claim_decision` does not take the caller's identity as a
parameter at all** (§4.4). It cannot recognise self. The observed verdict word — *refuse* — is
load-bearing for §6.1 and is analysed there.

**Incident 3 — an authorized stop is indistinguishable from a daemon restart, 2026-07-17.**
`supervisor/JOURNAL.md:114-116`, entry `## 2026-07-17T01:12:15Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3`:

> Succession: operator-authorized stop of stale body inc-20260716T130803Z-5325 [...] sup-boot
> refuse->freeze (roster-gone+fresh-heartbeat, G9 heuristic blind to authorized stop); operator
> pre-ratified seize, INCARNATION cleared as delegate, fresh claim taken.

And `knowledge/lessons.md:627`, second clause:

> Also: `sup-boot` freeze heuristic cannot distinguish an operator-authorized `claude stop` from a
> daemon restart (both = roster-gone + fresh-heartbeat) → froze on a legitimate succession; the
> manual `rm supervisor/INCARNATION` is the only release lever — there is no `sup-release` verb.

---

## 2. Threat model and trust boundary

*(This section did not exist in v1. The break lens named its absence as the design question that
generated four of its five CRITICALs. It is therefore first, and everything after it is constrained
by it.)*

### 2.1 What is inside, what is outside, and what the difference buys

**There is no privilege boundary on this substrate.** Every actor this spec concerns runs as the
same OS user, in the same filesystem, with the same environment and the same shell. Concretely, the
actor the design must worry about — an over-helpful agent, especially one under `bypassPermissions`
(`_confirm_destructive`'s own stated threat model, §4.9) — possesses:

| Capability | Receipt |
|---|---|
| Read `supervisor/INCARNATION`, `supervisor/HANDSHAKE`, all of `state/` | §4.1, §4.8 — plain files, atomic-written, lock-free-readable by design |
| Read the holder's sid and incarnation id from a **read-only, unauthenticated view** | §4.8 (`sup-status --json` dumps the claim dict verbatim); §4.2 (`sup-status` human line prints the sid) |
| Read the holder's sid and incarnation id from a **git-tracked** file | `supervisor/JOURNAL.md` header format, §4.7 |
| Set any environment variable, including `CLAUDE_CODE_SESSION_ID` | §4.3 — `current_caller_session()` is one `os.environ.get` |
| Pass `--sid` to every gated verb | §4.3 |
| Read every session transcript on the box | §5.5 |

That is a **superset** of what the supervisor body has. There is no capability the inside holds that
the outside does not.

**The consequence, stated once and applied everywhere below:** *no value stored on this box can
function as an authorization credential.* A secret can prove **continuity** — that the actor
presenting it is the same actor that was handed it — because handing it over is an event with a
before and an after. It cannot prove **entitlement**, because nothing distinguishes an actor that
was handed it from an actor that copied it.

v1 discovered half of this in its own §4.5 (two bodies of one lineage are byte-identical, so mutual
exclusion is undecidable) and then built three authorization constructs on top of the secret anyway.
The generalisation is the fix.

### 2.2 What this spec therefore claims, and what it does not

- **Claims:** divergence detection. A second body of the same lineage, acting concurrently, is
  surfaced by a loud refusal instead of by a human forensics exercise (§5.6).
- **Claims:** continuity across sid rotation. Fork-steer and respawn stop breaking the claim (§5.10).
- **Claims:** two shipped warts fixed — self-recognition (§6.1) and a clean release (§6.3).
- **Does not claim:** that the nonce authorizes anything. It is not a capability, not a permission,
  and no verb refuses on its absence except the `sup-*` verbs that already refuse on a sid mismatch
  today.
- **Does not claim:** to make the pre-existing unauthenticated levers harder. It also **does not add
  one**: v1's three (`re-issue`, `--claim-override`, `sup-release --force`) are all gone (§14).

### 2.3 Is there an authorization input on this box? — no, and here is the receipt

The break lens' position is that a gate needs an authorization input *not derivable from any view
and not an environment variable*, and that on this box today there is not one. I agree, and can
strengthen it: the obvious candidate — prompt a human — is **already refuted in shipped code**, in
the docstring of the very guard a claim gate would sit beside:

```
# at ccbbc02
$ sed -n '2049,2054p' bin/fleet.py
    There is deliberately NO interactive prompt. An agent's Bash tool has no
    stdin to answer one with (it gets an EOFError), and `isatty()` cannot tell
    the two apart on Windows anyway: Git Bash's `/dev/null` is `NUL`, a
    CHARACTER DEVICE, so `sys.stdin.isatty()` returns True under
    `fleet kill x < /dev/null`. An agent must pass --yes; there is nothing to
    prompt."""
```

So: a file is readable, an env var is readable and **auto-propagated to every child** (§4.10), a
view publishes it, a prompt cannot be delivered. What would work is an input that never lives on
this box — an operator-held value supplied out of band per session. That is real, and it is **new
scope**: a delivery channel, a rotation story, and a lockout story, none of which exist. It is
option (c) in §7, priced honestly rather than assumed away.

---

## 3. Non-goals

- **Not `sup-spawn`, not `fleet beat`, not the scheduler bridge.** Three-tier adjudication items
  4–10 belong to the re-drafted three-tier spec, sequenced after this one.
- **Not the claim gate.** v1 decided it; the gate lens unwound that decision. §7 puts it to the
  operator with three options and a recommendation, and decides nothing.
- **Not body-fencing.** v1 attached a `claude stop` of a superseded body to `sup-handoff-complete`
  as belt-and-braces for the gate. With the gate deferred its justification is gone, and it would
  add process control to a verb with no subprocess seam (§4.12). Dropped; noted for the three-tier
  slice.
- **Not a change to `spawned_by`'s spawn-immutability.** §6.2 adds fields and renames nothing.
- **Not a ratification.** `docs/specs/three-tier-command.md` stays **`PROPOSAL — RESTRUCTURE
  REQUIRED (dual-lens design gate, 2026-07-17)`** — its full status, per its own header line 3;
  every `[PENDING OPERATOR RATIFICATION]` row in `docs/specs/native-substrate.md` keeps its status;
  `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` stays DRAFT.

---

## 4. THE GREP RECEIPT — every touchpoint, at `ccbbc02`

v1 carried 31 receipts; the spec lens re-ran all 31 and **31/31 reproduced**. They are retained
verbatim below. §4.13 adds the ones v1 was short of, each of which a builder implementing this
section literally would have missed.

### 4.1 Everything that reads or writes `supervisor/INCARNATION`

```
# at ccbbc02
$ grep -n "write_incarnation\|def read_incarnation\|incarnation_path" bin/fleet.py
6849:def incarnation_path() -> Path:
6888:def read_incarnation() -> dict | None:
6892:        data = json.loads(incarnation_path().read_text(encoding="utf-8"))
6898:def write_incarnation(claim: dict) -> None:
6900:    _write_json_atomic(incarnation_path(), claim)
7145:                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
7159:                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
7204:        write_incarnation(claim)
7215:        write_incarnation(claim)
7404:        write_incarnation({"incarnation_id": args.expect_inc,
7473:        write_incarnation(claim)
```

**Six write sites in two classes — the distinction is load-bearing for §9:**

- **Dict-literal writers (unknown fields DROPPED):** `7145` fresh claim, `7159` seize,
  `7404` handoff-complete.
- **Round-trip writers (unknown fields PRESERVED):** `7204` checkpoint, `7215` heartbeat,
  `7473` handoff-abort.

```
# at ccbbc02
$ grep -n "INCARNATION" bin/fleet.py
6814:# supervisor/JOURNAL.md append-only). Body claim = supervisor/INCARNATION
6850:    return supervisor_dir() / "INCARNATION"
7171:        lines.append(f"INCARNATION: {inc_line}")
7524:            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
```

**Observed schema — exactly five keys, no version field, no validator:** `incarnation_id`,
`session_id`, `claimed_at`, `heartbeat_at`, `claimed_via`. **`claimed_at` is written at
7146/7160/7406 and never read anywhere**; `claimed_via` is read once, at 7249. A schema section
adding fields is the right place to record that.

```
# at ccbbc02
$ grep -n "supervisor/" .gitignore
7:supervisor/INCARNATION
8:supervisor/HANDSHAKE
```

**That receipt covers the two final paths and not the file the writer actually creates** — see
§4.13(f) and §13.

### 4.2 The sid equalities — quote-agnostic, four sites not two

v1's command matched only double-quoted subscripts and undercounted. Corrected:

```
# at ccbbc02
$ grep -n "claim.get(.session_id.)\|claim\[.session_id.\]" bin/fleet.py
7022:    holder_sid = claim.get("session_id")
7187:    if caller != claim.get("session_id"):
7190:            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
7248:        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
```

| Line | Role | Touched by this spec |
|---|---|---|
| 7022 | **authorization** — `supervisor_claim_decision`'s roster join | §6.1 reorders and parameterises it |
| 7187 | **authorization** — `_require_claim_holder`'s single equality | §5.3 replaces it |
| 7190 | **display** — 7187's refusal message | §5.3 replaces the message wholesale (new exit code, §4.13(d)) |
| 7248 | **display, in a lock-free view** — prints the holder's raw sid | §5.8 governs it |

`7190` and `7248` use single quotes inside f-strings and were invisible to v1's command. The
substantive v1 conclusion — the whole authorization model is the one equality at `7187` — survives;
the enumeration did not. **`7248` matters most: it is the human arm of the view whose `--json` arm
§4.8 singles out, and §5.8 is the section that must govern both.**

### 4.3 The `--sid` override, and the sole source of caller identity

```
# at ccbbc02
$ grep -n '"--sid"\|"--expect-sid"\|"--expect-inc"\|"--successor-sid"' bin/fleet.py
7721:    p_supboot.add_argument("--sid", help="override caller session id (default: CLAUDE_CODE_SESSION_ID)")
7728:    p_supckpt.add_argument("--sid", help="override caller session id")
7731:    p_supbeat.add_argument("--sid", help="override caller session id")
7739:    p_suphb.add_argument("--sid", help="override caller session id")
7742:    p_suphc.add_argument("--expect-inc", dest="expect_inc", required=True)
7743:    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
7744:    p_suphc.add_argument("--sid", help="override caller session id")
7747:    p_supha.add_argument("--successor-sid", dest="successor_sid", required=True)
7748:    p_supha.add_argument("--sid", help="override caller session id")
```

```
# at ccbbc02
$ grep -n "def current_caller_session" -A 9 bin/fleet.py
580:def current_caller_session() -> str | None:
581-    """The Claude Code session id of whoever is running this CLI, or None when
582-    fleet is run by a human from a plain shell.
583-
584-    Provenance for the destructive-command guard (§5.1): a session may retire
585-    the workers it spawned without ceremony, but must explicitly acknowledge
586-    (`--yes`) before killing or sweeping someone else's."""
587-    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
588-    return sid or None
589-
```

`_require_claim_holder` resolves the caller as `sid_override or current_caller_session()` (@7184).
**Caller identity is therefore what the caller typed or exported, in both branches.** §2.1 is this
receipt generalised. §5.3 stops treating a sid as proof of anything.

### 4.4 `supervisor_claim_decision` — the guard, and the missing self-parameter

```
# at ccbbc02
$ sed -n '7014,7042p' bin/fleet.py
def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS):
    """Claim rules at boot (spec §4, verbatim order). Returns (verdict, reason);
    verdict in {"claim","refuse","seize","freeze"}. Pure function -- no IO."""
    if now is None:
        now = datetime.now(timezone.utc)
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    holder_sid = claim.get("session_id")
    if holder_sid in live_sids:
        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "
                          f"(sid {holder_sid}) is live in the roster")
    try:
        beat = _parse_iso(claim["heartbeat_at"])
    except (KeyError, TypeError, ValueError):
        return ("freeze", "claim heartbeat unreadable -- ambiguous; never seize on ambiguity")
    if latest_entry is not None and latest_entry.get("inc") != claim.get("incarnation_id"):
        try:
            entry_ts = _parse_iso(latest_entry["ts"])
        except (KeyError, TypeError, ValueError):
            entry_ts = None
        if entry_ts is not None and entry_ts > beat:
            return ("refuse", f"journal's latest checkpoint is a fresher incarnation "
                              f"({latest_entry.get('inc')}) -- transition in flight")
    age = (now - beat).total_seconds()
    if age > stale_seconds:
        return ("seize", f"holder roster-gone, heartbeat stale ({age:.0f}s > {stale_seconds:.0f}s)")
    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")
```

**`caller_sid` is not a parameter.** Incident 2 is a structural consequence.

**The membership predicate the guard turns on — never receipted in v1:**

```
# at ccbbc02
$ sed -n '6986,6999p' bin/fleet.py
def _roster_live_sids(entries: list) -> set:
    """Sids whose backing process is LIVE. Contract rule
    (docs/specs/native-substrate.md, roster contract): `status`/`pid` keys
    exist only while the process lives; a lingering `state:"done"` entry
    (observed surviving >=3h21m) must NOT count as live, or a finished
    predecessor would block every successor claim for hours."""
    # Same hostile-sessionId-value guard as dispatch_bg's pre-snapshot: a
    # dict-valued sessionId (CLI drift / hostile roster) must never raise
    # TypeError from an unhashable value landing in the set.
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
    }
```

`("status" in e or "pid" in e)` is what decides membership. **A running session — including the
caller's own — carries those keys and is therefore in `live_sids`.** §6.1 turns on exactly this.

The epoch check that gates the whole decision:

```
# at ccbbc02
$ sed -n '7002,7011p' bin/fleet.py
def supervisor_epoch_check(roster_ok: bool, payload):
    """Roster-epoch sanity check, run BEFORE any claim decision (spec §4).
    A failed or empty roster freezes the decision -- a daemon restart (G9)
    must never let a fresh boot seize a claim whose holder is alive."""
    if not roster_ok:
        return (False, f"roster unavailable ({payload}) -- freeze, never decide blind")
    if not payload:
        return (False, "roster is EMPTY -- not even this session is listed; "
                       "daemon restart suspected (G9). Freeze + page operator.")
    return (True, f"roster holds {len(payload)} entr{'y' if len(payload) == 1 else 'ies'}")
```

**It tests fetch-success and non-emptiness only; there is no staleness test.** Its mirror carries the
same gap and was unmentioned in v1:

```
# at ccbbc02
$ sed -n '1557,1563p' bin/fleet.py
def native_epoch_suspicious(roster_ok: bool, entries: list, workers: dict) -> bool:
    """G9 epoch-freeze predicate (mirrors supervisor_epoch_check): the
    roster fetch failed, OR it came back empty while some native worker's
    own last-committed record still says `working` with a real sid -- a
    fresh daemon boot (or a transient CLI failure shaped like an empty
    list) must never be read as "everything died". Callers freeze: no
    native record is recomputed or written while this is true."""
```

§6.4 states what this spec does and does not do about it, and §13 records the sequencing.

### 4.5 The sid-rotation paths — three writers, not two

```
# at ccbbc02
$ grep -n "_restamp_after_steer(" bin/fleet.py
3293:                _restamp_after_steer(r, new_sid, short_id)
6331:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
```

**One call site.** The docstring names a second caller that does not call it:

```
# at ccbbc02
$ sed -n '6331,6352p' bin/fleet.py
def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
    """Mutate `record` in place after a fork-steer (`send`'s idle path,
    `resume-limited`'s native branch): retire the OLD sid into
    retired_sids, restamp session_id/native_short_id to the new fork,
    stamp last_dispatch_at (the fresh-outcome anchor for the NEXT
    recompute), and bump turns -- mirrors _resume_one_limited_native's
    inline commit shape, shared here so `send` and a future resume-limited
    refactor stay in lockstep.

    S2 fix (final wave), defense-in-depth: never append a None into
    retired_sids -- a caller reached here with `record["session_id"]` is
    None (e.g. a respawn --force's fresh pre-claim) would otherwise poison
    retired_sids, which `_cmd_kill_native`'s sweep later feeds straight into
    `_stop_native_session(None)` -> `run([exe, "stop", None])`, a TypeError
    outside the caught (OSError, SubprocessError) tuple."""
    old_sid = record["session_id"]
    if old_sid is not None:
        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
    record["session_id"] = new_sid
    record["native_short_id"] = short_id
    record["last_dispatch_at"] = now_iso()
    record["turns"] = record.get("turns", 0) + 1
```

```
# at ccbbc02
$ sed -n '3428,3436p' bin/fleet.py
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") == old_sid:
                r["retired_sids"] = list(r.get("retired_sids", [])) + [old_sid]
                r["session_id"] = new_sid
                r["native_short_id"] = short_id
                r["status"] = "working"
                r["last_dispatch_at"] = now_iso()
```

The inline copy has **drifted**: it sets `status="working"` and does **not** bump `turns`, which the
shared helper does. And there is a **third** writer v1 missed:

```
# at ccbbc02
$ grep -n 'retired_sids' bin/fleet.py | grep -E '3432|3860|6348'
3432:                r["retired_sids"] = list(r.get("retired_sids", [])) + [old_sid]
3860:        new_record["retired_sids"] = prior_retired + [old_sid]
6348:        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
```

`3860` is in `_cmd_respawn_native`, the only one that mints a **fresh record**. **Three sid-rotation
sites, all registry-only; none touches `supervisor/INCARNATION`.** §5.10(a) explains why this spec
still amends none of them.

### 4.6 HANDSHAKE, `--expect-sid`, and the successor's hard-coded protocol

```
# at ccbbc02
$ grep -n "def write_handshake" -A 7 bin/fleet.py
6911:def write_handshake(incarnation_id: str, session_id: str) -> None:
6912-    _write_json_atomic(handshake_path(), {
6913-        "incarnation_id": incarnation_id,
6914-        "session_id": session_id,
6915-        "written_at": now_iso(),
6916-    })
6917-
6918-
```

```
# at ccbbc02
$ grep -n "expect_sid\|expect-sid" bin/fleet.py
7379:          f"  fleet sup-handoff-complete --expect-inc {successor_inc} --expect-sid {successor_sid}\n"
7386:    """`fleet sup-handoff-complete --expect-inc I --expect-sid S [--sid ...]`.
7397:                or hs.get("session_id") != args.expect_sid):
7401:                f"sid={args.expect_sid} -- NOT transferring (spec §4 id verification)")
7403:                                  f"claim -> {args.expect_inc} sid={args.expect_sid}")
7405:                           "session_id": args.expect_sid,
7743:    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
```

**The successor's entire behaviour is a generated prompt string, and v1 never named it:**

```
# at ccbbc02
$ sed -n '7257,7274p' bin/fleet.py
def _render_successor_task(successor_inc: str, old_inc: str) -> str:
    """Successor bootstrap body (task-file bootstrap, contract G8 -- never
    argv for size-unbounded content). Paths rendered .as_posix()."""
    fleet_py = (FLEET_HOME / "bin" / "fleet.py").as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
Your predecessor ({old_inc}) dispatched you mid-handoff (spec docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §4).

Do exactly this, in order:
1. Run: py -3.13 {fleet_py} sup-boot --handoff-inc {successor_inc}
   This prints your boot bundle and writes supervisor/HANDSHAKE. You hold NO claim yet.
2. Take NO spawn/respawn/send/kill/clean actions before claim transfer -- spec §4's double-spawn guard.
3. Poll every ~30s (up to 10 minutes): py -3.13 {fleet_py} sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     py -3.13 {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}"
     then read your boot bundle output and continue the supervisor duty per skills/fleet/supervisor.md.
   - If 10 minutes pass without transfer: the handoff was aborted. STOP -- take no actions,
     end your turn with the final message: HANDOFF-ORPHAN {successor_inc}
"""
```

§6.4 changes what the successor must do (mint a nonce, deliver a hash, receive `--handoff-token`).
**If this string is not amended in the same commit, the successor runs the old protocol against new
code and fails only during a real handoff** — the moment the spec exists to protect. It is in §8's
table.

### 4.7 The journal: entry regex, kinds, and the kind-lists

```
# at ccbbc02
$ grep -n 'SUPERVISOR_JOURNAL_KINDS\|_SUPERVISOR_ENTRY_RE\|choices=\["CHECKPOINT"' bin/fleet.py
6825:SUPERVISOR_JOURNAL_KINDS = (
6924:_SUPERVISOR_ENTRY_RE = re.compile(
6936:        m = _SUPERVISOR_ENTRY_RE.match(line)
6967:    if kind not in SUPERVISOR_JOURNAL_KINDS:
6968:        raise ValueError(f"unknown journal kind {kind!r}; allowed: {', '.join(SUPERVISOR_JOURNAL_KINDS)}")
6976:    # _SUPERVISOR_ENTRY_RE no longer matches (line no longer starts with "##").
6978:        f" {line}" if _SUPERVISOR_ENTRY_RE.match(line) else line
7727:    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
```

```
# at ccbbc02
$ sed -n '6825,6828p;6924,6925p;6981p' bin/fleet.py
SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)
_SUPERVISOR_ENTRY_RE = re.compile(
    r"^## (?P<ts>\S+) (?P<kind>[A-Z][A-Z-]*) inc=(?P<inc>\S+) sid=(?P<sid>\S+)\s*$")
    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{safe_body}\n"
```

Adding a kind touches **four** lists, not three — the fourth is shipped documentation:

```
# at ccbbc02
$ grep -n "sup-boot\|sup-checkpoint" skills/fleet/SKILL.md
37:| `fleet sup-boot [--handoff-inc <id>]` | Supervisor boot ritual: epoch check → claim/seize/refuse/freeze + boot bundle. Exit 0=hold/handshake-written, 2=refuse, 3=freeze. See `skills/fleet/supervisor.md`. |
38:| `fleet sup-checkpoint <text\|@file> [--kind CHECKPOINT\|PROPOSAL]` | Append a journal checkpoint (claim holder only) + refresh heartbeat. |
```

So: `SUPERVISOR_JOURNAL_KINDS` @6825, the seed doc's kinds line @6835, `--kind`'s `choices` @7727,
and `SKILL.md:38`. **`SKILL.md:37` additionally publishes the exit-code contract as 0/2/3** — see
§4.13(d).

**`_SUPERVISOR_ENTRY_RE` is `$`-anchored.** A header with any extra trailing token fails `.match()`
and is silently absorbed as body text of the *preceding* entry (`parse_supervisor_journal`
@6935-6943) — an invisible corruption of an append-only record. **The journal header format does not
change and no secret ever appears in it**; `supervisor/JOURNAL.md` is git-tracked, which forbids it
independently.

### 4.8 Doctor checks, and the views that publish the claim

```
# at ccbbc02
$ grep -n "_doctor_check_supervisor" bin/fleet.py
6088:        functools.partial(_doctor_check_supervisor_claim),
6089:        functools.partial(_doctor_check_supervisor_handoff),
7533:def _doctor_check_supervisor_claim():
7542:def _doctor_check_supervisor_handoff():
```

```
# at ccbbc02
$ grep -c "def _doctor_check_" bin/fleet.py
21
```

`_doctor_check_supervisor_claim` @7533-7539 hard-codes `ok=True` on both returns (docstring: *"ALWAYS
ok=True -- the nag is advisory"*). §5.6 changes that for one condition; the receipt for the current
behavior is the function body at 7533-7539, not the two greps above.

**`sup-status --json` dumps the entire claim dict verbatim** — any field added to INCARNATION is
published by a lock-free view with no further code change:

```
# at ccbbc02
$ sed -n '7232,7242p' bin/fleet.py
    info = {
        "goals_active": supervisor_goals_active(),
        "incarnation": claim,
        "heartbeat_age_seconds": beat_age,
        "handshake": hs,
        "abort_flag": handoff_abort_flag_path().exists(),
        "nag": supervisor_status_line(),
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
```

Note `"handshake": hs` beside `"incarnation": claim` — §6.4 adds a field to HANDSHAKE too, so the
redaction rule of §5.8 must cover **both**.

```
# at ccbbc02
$ grep -rn "supervisor\|INCARNATION\|sup-" bin/hooks/ bin/fleet_statusline.py
bin/hooks/sessionstart_fleet.py:126:        sup_line = fleet.supervisor_status_line()
```

That receipt supports a **code** conclusion only. The shipped operator contract is wider:

```
# at ccbbc02
$ grep -rln "sup-status\|sup-boot\|INCARNATION\|supervisor" commands/ skills/
skills/fleet/SKILL.md
skills/fleet/supervisor.md
```

```
# at ccbbc02
$ grep -n "sup-boot\|sup-handoff\|rm supervisor\|freeze\|seize" skills/fleet/supervisor.md
10:1. Run `fleet sup-boot`. Read the ENTIRE bundle it prints (GOALS, journal
13:   - `claim` / `seize` (exit 0): you hold the claim. Continue the duty.
18:   - `freeze` (exit 3): ambiguity (daemon restart? G9). PAGE THE OPERATOR.
19:     Never seize, never mass-respawn.
32:sticky park: the boot reconcile and the epoch freeze never demote it --
56:2. `fleet sup-handoff-begin` — note the `SUCCESSOR-INC:` / `SUCCESSOR-SID:` lines.
58:   `sup-boot --handoff-inc`). Timeout T = 300s.
59:4. On handshake: `fleet sup-handoff-complete --expect-inc <INC> --expect-sid <SID>`,
61:5. On timeout / dispatch failure: `fleet sup-handoff-abort --successor-sid <SID>`
65:Successor: driven entirely by the task file `sup-handoff-begin` wrote — it
76:  freeze — never act on an ambiguous claim.
```

`skills/fleet/supervisor.md` is the operator runbook for the boot verdict table, the handoff sequence
with a **required** `--expect-sid`, and the successor protocol. Every one of those changes here.
`commands/` is clean — no slash command touches the supervisor, so none is added (mutating slash
commands stay prompt templates by CLAUDE.md rule; this spec adds no slash command at all).

### 4.9 `spawned_by` and the destructive guard

```
# at ccbbc02
$ grep -n "spawned_by" bin/fleet.py
593:                       spawned_by=None, dispatch_kind=None, category=None) -> dict:
625:        "spawned_by": spawned_by,
2022:    An UNKNOWN owner (`spawned_by` absent -- every record written before this
2024:    owner = record.get("spawned_by")
2031:    owner = record.get("spawned_by")
2310:            spawned_by=current_caller_session(),
3770:    works), spawned_by carried immutably (§5.1 provenance), cost_usd/
3806:    spawned_by = before.get("spawned_by")
3857:            spawned_by=spawned_by, dispatch_kind="bg", category=category)
```

**Writers: two** (`cmd_spawn` @2310 — a raw sid; `cmd_respawn` @3806/@3857 — carried forward).
**Readers: two**, both feeding the destructive guard:

```
# at ccbbc02
$ grep -n "def _worker_is_foreign" -A 8 bin/fleet.py
2019:def _worker_is_foreign(record: dict, caller: str | None) -> bool:
2020-    """True when this session did not spawn the worker.
2021-
2022-    An UNKNOWN owner (`spawned_by` absent -- every record written before this
2023-    field existed) counts as foreign: the guard fails toward asking."""
2024-    owner = record.get("spawned_by")
2025-    if not owner:
2026-        return True
2027-    return owner != caller
```

```
# at ccbbc02
$ sed -n '2042,2047p;2055,2060p' bin/fleet.py
    The guard applies to CLAUDE SESSIONS only. A human at a plain shell has no
    CLAUDE_CODE_SESSION_ID; fleet has always been a human-driven CLI and
    interposing prompts there would break every existing script for no safety
    gain -- a human typing `fleet clean` meant to type it. The threat model is
    an over-helpful agent, especially one under `bypassPermissions` where no
    permission prompt is ever shown.
    caller = current_caller_session()
    if caller is None:
        return
    foreign = [n for n in names if _worker_is_foreign(records.get(n, {}), caller)]
    if not foreign or assume_yes:
        return
```

### 4.10 The worker child environment — why this spec offers no env-var channel

```
# at ccbbc02
$ grep -n "def _worker_env" -A 18 bin/fleet.py
989:def _worker_env(name: str) -> dict:
990-    """Child environment for a worker turn: the parent's, plus FLEET_WORKER.
991-
992-    Phase 1.6 D5: a globally-enabled fleet plugin fires its SessionStart hook
993-    in EVERY Claude Code session on this machine, including every worker turn.
994-    The hook reads FLEET_WORKER and suppresses itself, so a worker never gets
995-    the manager's fleet briefing injected into its context.
996-
997-    os.environ is copied explicitly -- passing env= at all replaces the whole
998-    inherited environment, and a child without PATH cannot launch.
999-
1000-    CLAUDE_CODE_SESSION_ID is STRIPPED (§5.1 provenance): the child `claude`
1001-    stamps its own, and an inherited one would make a worker running
1002-    `fleet kill` look exactly like the manager that spawned it -- so a worker
1003-    could quietly retire its siblings with no confirmation."""
1004-    env = dict(os.environ)
1005-    env.pop("CLAUDE_CODE_SESSION_ID", None)
1006-    env["FLEET_WORKER"] = name
1007-    return env
```

**The whole parent environment is copied and exactly one key is stripped.** Any env-var channel for
the nonce would be inherited by every worker fleet spawns and by every subagent those workers spawn.
§6.5 is the consequence.

### 4.11 Unknown-field tolerance — confirmed by grep, not assumed

```
# at ccbbc02
$ grep -n "def load_registry" -A 10 bin/fleet.py
526:def load_registry() -> dict:
527-    """Load state/fleet.json. Missing file -> {"workers": {}}. An existing
528-    but corrupt/unreadable file is quarantined (renamed aside) and raises
529-    RegistryCorruptError -- callers must abort, not catch-and-continue."""
530-    path = registry_path()
531-    if not path.exists():
532-        return {"workers": {}}
533-    try:
534-        with open(path, "r", encoding="utf-8") as f:
535-            data = json.load(f)
536-    except (json.JSONDecodeError, UnicodeDecodeError):
```

```
# at ccbbc02
$ grep -n "def save_registry" -A 9 bin/fleet.py
562:def save_registry(data: dict) -> None:
563-    """Atomically write state/fleet.json (temp file + os.replace)."""
564-    d = state_dir()
565-    d.mkdir(parents=True, exist_ok=True)
566-    fd, tmp_name = tempfile.mkstemp(dir=str(d), prefix=".fleet.", suffix=".tmp")
567-    try:
568-        with os.fdopen(fd, "w", encoding="utf-8") as f:
569-            json.dump(data, f, indent=2)
570-            f.write("\n")
571-        os.replace(tmp_name, str(registry_path()))
```

Whole-dict `json.load` → `json.dump`: **registry unknown fields round-trip** (`docs/SPEC.md:118`).
`read_incarnation` (@6888-6895) does no key validation and `write_incarnation` (@6898-6900) writes
whatever dict it is handed, so INCARNATION unknown fields survive the three round-trip writers and
are dropped by the three dict-literal writers (§4.1). **The journal is the counter-example** — §4.7's
anchored regex. Tolerance is a property of the two JSON stores only.

### 4.12 Command seams that exist, and the ones the test plan needs

```
# at ccbbc02
$ grep -n "^def cmd_sup_" bin/fleet.py
7111:def cmd_sup_boot(args, which=shutil.which, run=subprocess.run) -> int:
7195:def cmd_sup_checkpoint(args) -> int:
7209:def cmd_sup_heartbeat(args) -> int:
7220:def cmd_sup_status(args) -> int:
7277:def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
7385:def cmd_sup_handoff_complete(args) -> int:
7417:def cmd_sup_handoff_abort(args, which=shutil.which, run=subprocess.run) -> int:
```

Three verbs carry `which=`/`run=`; `cmd_sup_handoff_complete` does not — which is one reason §3
drops body-fencing rather than adding process control there. **There is no clock seam on any command
path**: only the two pure functions accept `now=` (`supervisor_claim_decision` @7014,
`supervisor_status_line` @7503). §10 budgets that seam explicitly instead of presuming it.

```
# at ccbbc02
$ grep -n "^@pytest.fixture\|delenv\|def _no_inherited" tests/conftest.py
21:@pytest.fixture(autouse=True)
43:@pytest.fixture(autouse=True)
44:def _no_inherited_claude_session(monkeypatch):
53:    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
```

An **autouse** fixture strips `CLAUDE_CODE_SESSION_ID` from every test. Any test that needs a
controlled caller identity must opt back in; §10 budgets it.

### 4.13 The rest of the identity surface

**(a) `state/supervisor-handoff-aborted.json` — a third supervisor store, carrying a fifth sid
equality inside the stop path.**

```
# at ccbbc02
$ grep -n "handoff_abort_flag_path\|read_handoff_abort_flag" bin/fleet.py
6861:def handoff_abort_flag_path() -> Path:
6868:def read_handoff_abort_flag() -> dict | None:
6873:        data = json.loads(handoff_abort_flag_path().read_text(encoding="utf-8"))
7237:        "abort_flag": handoff_abort_flag_path().exists(),
7253:        print(f"WARNING: aborted-handoff flag present ({handoff_abort_flag_path()})")
7297:            handoff_abort_flag_path().unlink()
7304:        _write_json_atomic(handoff_abort_flag_path(), {
7432:    (`handoff_abort_flag_path()`) written by sup-handoff-begin on a DOA/
7447:            flag = read_handoff_abort_flag()
7467:        _write_json_atomic(handoff_abort_flag_path(), {
7549:    if handoff_abort_flag_path().exists():
7551:        parts.append(f"aborted-handoff flag present ({handoff_abort_flag_path().name}) -- "
```

```
# at ccbbc02
$ sed -n '7446,7460p' bin/fleet.py
        else:
            flag = read_handoff_abort_flag()
            recorded_sid = flag.get("successor_sid") if flag is not None else None
            # Roll-up item 8 (simplified): an abort flag recorded with
            # successor_sid=None (the dispatch-failed shape) names nothing
            # verifiable to stop -- refuse on the RECORDED side, whatever the
            # caller passed. The old args-side None check was dead via the
            # CLI (argparse required=True) and is now subsumed: a None
            # args.successor_sid can only match a None recorded_sid, which
            # this refuses first.
            if recorded_sid is None or recorded_sid != args.successor_sid:
                raise FleetCliError(
                    f"no HANDSHAKE and --successor-sid {args.successor_sid} matches no "
                    f"recorded limbo successor -- refusing to stop an unverified session "
                    f"(check claude agents; stop manually if certain)")
```

v1 declared `sup-handoff-abort`'s sid cross-check "unchanged — genuinely a sid question" and cited
only the HANDSHAKE arm @7441-7445. **This is a separate arm**, in the one verb whose job is to
`claude stop` another session. §6.4 leaves both arms unchanged, and now says so about the right
number of arms. The store is under `state/` (gitignored), so there is no disclosure question — the
gap was enumeration, not exposure.

**(b) The exit-code contract — there is no seam for a new code, and 0/2/3 is published.**

```
# at ccbbc02
$ grep -rn "return 4$\|sys.exit(4)\|exit code 4" bin/ docs/SPEC.md skills/
$ echo "exit $?"
exit 1
```

```
# at ccbbc02
$ sed -n '7166p;7822,7828p' bin/fleet.py
        rc = {"claim": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]
    except RegistryCorruptError as exc:
        print(f"fleet: registry error: {exc}", file=sys.stderr)
        return 1
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1
```

`_require_claim_holder`'s refusals are plain `FleetCliError` → **exit 1**, indistinguishable from a
corrupt registry or a lock timeout. A distinct code is a new exception class **plus** a `main()`
branch ordered ahead of the generic handler **plus** an amendment to `SKILL.md:37`. §11 specifies all
three; §8 lists them.

**(c) Reserved names — v1's receipt was non-probative.** It was case-sensitive. Corrected:

```
# at ccbbc02
$ grep -rni "reserved" bin/ | head -4
bin/fleet.py:497:            f"invalid worker name {name!r}: uuid-shaped names are reserved "
bin/fleet.py:926:            # registry invariant (6) is preserved.
bin/fleet.py:5423:    to survive an update. FAIL is reserved for a confirmed mismatch against
bin/fleet.py:6634:            f"uuid-shaped names are reserved for session ids, F6)")
```

Reserved-name *enforcement* exists (uuid-shape refusal at `validate_name`). What does not exist is a
reserved-name **list** for a supervisor body name — still `[UNBUILT — owned by the three-tier
slice]`, now on a receipt that supports the conclusion. This spec reserves no name.

**(d) The handoff task file is written once and never deleted.**

```
# at ccbbc02
$ grep -n "supervisor-handoff" bin/fleet.py
6865:    return state_dir() / "supervisor-handoff-aborted.json"
7289:        task_path = state_dir() / f"supervisor-handoff-{successor_inc}.md"
7566:    return ("supervisor-handoff", ok, " | ".join(parts))
```

One write site, no `unlink`. §5.9 is the consequence.

**(e) No beat primitive exists in this slice's substrate.**

```
# at ccbbc02
$ grep -n 'ScheduleWakeup\|def cmd_beat\|"beat"' bin/fleet.py
$ echo "exit $?"
exit 1

$ grep -n "SUPERVISOR_CLAIM_STALE_SECONDS *=" bin/fleet.py
6821:SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
```

The only beat is the manual `sup-heartbeat` verb. §7 uses this: any design whose protection is armed
by heartbeat freshness is armed only in the hour after a human last typed a command, and disarms
during exactly the quiet stretches when an unattended second body does damage. Incident 1's phantom
steers spanned ~100 minutes — longer than the window.

**(f) `supervisor/INCARNATION.tmp` is not gitignored.** Filed as a shipped-code defect (§13), not
built here, but §4.1's `.gitignore` receipt must not be read as covering it:

```
# at ccbbc02
$ git check-ignore -v supervisor/INCARNATION.tmp
$ echo "exit $?"
exit 1
```

`_write_json_atomic` (@6879-6885) writes `path.name + ".tmp"` beside the target — inside a git-tracked
directory — before `os.replace`. §5.8's redaction rule and §9's schema make this worse if unfixed,
which is why §13 names it as a prerequisite rather than a nicety.

### 4.14 `[UNBUILT]` proofs — reproduced as no-matches at `ccbbc02`

```
# at ccbbc02
$ grep -rn "nonce" bin/
$ echo "exit $?"
exit 1

$ grep -rn "sup-release\|sup_release" bin/
$ echo "exit $?"
exit 1

$ grep -rn "body_id\|body_nonce\|claim_nonce" bin/
$ echo "exit $?"
exit 1
```

- No nonce of any kind exists in `bin/` — **`[UNBUILT — owned by this slice]`**.
- No `sup-release` verb exists — **`[UNBUILT — owned by this slice]`** (§6.3).
- `SUPERVISOR_JOURNAL_KINDS` @6825-6828 has no `RELEASED` kind — **`[UNBUILT — owned by this
  slice]`**, and adding one touches the four lists of §4.7.
- No reserved-name list — **`[UNBUILT — owned by the three-tier slice]`**, receipt at §4.13(c).

---

## 5. The mechanism — divergence detection

### 5.1 What the nonce is, and what it is not

**The nonce is a continuity token.** Presenting the current generation proves exactly one thing:

> *the actor presenting this value is the same actor to which the last generation was delivered.*

It does **not** prove *"I am authorized"*, and §2.1 explains why nothing on this box can. Every
consequence in this document follows from taking that sentence literally.

Operationally this means: the nonce **replaces the sid as the continuity key** in
`_require_claim_holder` — a strictly better key, because it survives fork-steer and respawn and
because a stale one is *evidence* rather than noise — and it **adds** a detection signal that did
not exist. It does not add a permission, and no verb that is ungated today becomes gated by this
spec (§7 leaves that to the operator).

### 5.2 INCARNATION schema v2

Additive only; no rename, no removal (SPEC §4's additive-schema rule).

| Field | Value | Read by |
|---|---|---|
| `nonce_hash` | `sha256(live_nonce).hexdigest()` — **never the nonce** | `_require_claim_holder` |
| `pending_nonce_hash` | `sha256(pending_nonce).hexdigest()`, or absent | `_require_claim_holder` |
| `pending_at` | ISO-8601 UTC of the pending mint, or absent | the TTL rule, §5.3 |
| `nonce_seq` | integer generation of the **live** nonce, starts at 1 | doctor, rejection log |
| `lineage_id` | `lin-<utc>-<4 hex>`; minted at first fresh claim, carried across handoff, re-minted on seize | `_worker_is_foreign` (§6.2) |
| `state` | absent, or `"released"` (§6.3) | `supervisor_claim_decision`, `_require_claim_holder` |

`session_id` **keeps its name and its roster-join role**, and changes meaning: it is a **liveness
pointer** — the sid of the body that most recently proved continuity — not an authorization key.
`incarnation_id`, `claimed_at`, `heartbeat_at`, `claimed_via` are unchanged. (`claimed_at` remains
write-only, §4.1; this spec does not start reading it.)

The nonce is `secrets.token_urlsafe(32)`. Stdlib-only and 3.10-safe: `secrets.token_urlsafe` (3.6+),
`hashlib.sha256`, `hmac.compare_digest` (3.3+). The comparison is **`hmac.compare_digest` over two
hex strings** — `sha256(presented.encode()).hexdigest()` against the stored string; comparing a
digest object to a hex string is the shape to avoid.

### 5.3 Nonce lifecycle — mint, deliver, present, acknowledge

*(v1 had no lifecycle section. Two of the gate's MAJORs — a false two-body alarm on one body's
concurrent calls, and a claim bricked by a verb that fails after rotating — were both consequences of
its absence.)*

Two generations are live at once: the **live** generation (`nonce_hash`, seq *N*) and an optional
**pending** generation (`pending_nonce_hash`, seq *N+1*) that has been minted and committed but not
yet proven received.

**Validation** — `_require_claim_holder(nonce=...)`, under `fleet_lock`:

1. presented == live ⇒ **valid**. Nothing is promoted.
2. presented == pending ⇒ **valid, and this is the acknowledgment**: `nonce_hash ← pending_nonce_hash`,
   `nonce_seq ← N+1`, `pending_nonce_hash`/`pending_at` cleared. The caller has proven it received
   the value; only then does the old generation die.
3. otherwise ⇒ **refuse** (§5.6), exit code per §4.13(b).

**Minting** — only on a `sup-*` verb whose whole effect commits inside one `fleet_lock` section:

- mint iff `pending_nonce_hash` is absent **or** `now - pending_at > PENDING_NONCE_TTL_SECONDS`
  (proposed 300 s). Otherwise leave the outstanding pending alone and print
  `NONCE: unchanged (generation N+1 already outstanding)`.
- the mint, the acknowledgment, and the verb's own state change are **one** `write_incarnation`
  inside **one** `fleet_lock` acquisition. A verb that fails before that write rotates nothing.
- `sup-handoff-begin` **does not mint**: its dispatch runs outside the lock by F4 doctrine (@7312-7367),
  so a mint in its first critical section would be exposed to exactly the failure §5.4(b) exists to
  prevent — and it is handing the claim over regardless.
- **Gated mutating verbs, if a gate is ever adopted (§7), validate without minting.** Rotation is a
  supervisor-ritual event, not a side effect of dispatching a worker.

**Delivery.** The plaintext of a newly minted pending is printed once, on the verb's own stdout,
after the commit. There is no other copy anywhere (§5.5 is honest about where the copy actually
ends up).

**Where the gate sits relative to the lock.** Validation, mint/acknowledge, and the verb's state
change are inside `fleet_lock`; every subprocess and every dispatch is outside it, per F4 doctrine
(no lock across a subprocess). This sentence is the one v1 omitted and it is the mechanism of §5.4(b).

### 5.4 Concurrency and failure

**(a) One body, several calls in one block.** A Claude Code session batches independent tool calls by
instruction. A supervisor dispatching a wave issues several verbs at once; `fleet_lock` serialises
them.

Under this protocol all of them present the **live** generation and all of them validate, because
the live generation is not retired until something acknowledges a pending. The first to run mints a
pending and prints it; the rest see an outstanding fresh pending and mint nothing. **No refusal, no
rejection record, no doctor flip.** This is the property v1 lacked: its rotate-on-every-call design
turned a healthy body following its own skill into a two-body alarm.

**(b) A verb that fails after validating.** Mint and commit happen together; the verb's out-of-lock
work (a dispatch) may then hang or die — the shape of this project's own 9th live catch, where a
stale `daemon.lock` wedged every dispatch for ~16 h while `fleet doctor` read all-PASS. Under this
protocol the plaintext of the pending may be lost, but **the live generation is untouched and still
valid**, so the body keeps working. After `PENDING_NONCE_TTL_SECONDS` the next successful verb mints
a replacement. **There is no path here that locks a body out of its own claim**, which is what makes
deleting v1's `re-issue` bypass safe rather than a new CRITICAL — the adjudication requires those two
as one change and this is the join.

**(c) Two bodies of one lineage — the detection timeline.** Both hold generation *G* (the fork copied
it, §5.5). B acts: validates on live *G*, mints pending *P*, receives *P*. A acts: validates on live
*G* — **still accepted**; a fresh pending exists so A mints nothing. B acts again, now presenting *P*:
**acknowledged**, live becomes *P*, seq advances. A acts: presents *G*, which is neither live nor
pending ⇒ **refused, loudly**.

So detection fires on the divergent body's **first call after the other body completes one
acknowledgment** — in practice within one or two supervisor actions, not on the very first divergent
call. That is the price of (a) and (b), and it is the right trade: measured against incident 1 it is
~100 minutes of undetected phantom steering and a manual process census versus **a refusal within two
supervisor actions**. No cheaper attribution exists on this substrate — both bodies present
byte-identical values from byte-identical contexts, so nothing in the presented material distinguishes
them, and only the *sequence* can.

**(d) Two racing acknowledgments.** Both are serialised by `fleet_lock`; the first promotes and clears
the pending, the second then presents a value that is neither live nor pending and is refused. Exactly
one wins, which is the property §5.6 states.

### 5.5 The transcript is the real secret store

Hashing the value in `supervisor/INCARNATION` protects the copy in `supervisor/`. **That is not the
copy the attack uses.** The nonce is printed as command output, and command output is persisted in the
session transcript:

```
# at ccbbc02 (existence and count only; no transcript contents were read)
$ ls -ld ~/.claude/projects && find ~/.claude/projects -maxdepth 2 -name '*.jsonl' | wc -l
drwxr-xr-x 1 Techn 197609 0 Jul 21 20:54 /c/Users/Techn/.claude/projects/
735
```

*(The count is a point-in-time observation on a live box and drifts by the minute — it read 732
twenty minutes earlier in this same session. The load-bearing facts are **existence** and
**same-user readability**, neither of which drifts.)*

`--fork-session` **duplicates that store by design** — which is precisely how the second body in
§5.4(c) comes to hold generation *G*.

Two consequences, stated so no later section can quietly forget them:

- **Keep the hash-only store**, because it costs almost nothing and it removes one trivially-scriptable
  read path. **Stop describing it as what makes the nonce unforgeable** — it never was; the file was
  never where the secret lived.
- **Nothing about a fork can be prevented.** §5.4(c) is a detection story, not a containment story,
  and §2.2 says so up front.

`[MANAGER-VERIFICATION REQUIRED]` — that a `sup-boot` stdout line lands verbatim in the session's
`.jsonl` is inference from documented harness behavior; the break lens flagged it the same way and
neither of us verified it, because verifying it means reading a transcript's contents. The existence
and count above are the receipt. **Nothing in this spec's guarantees depends on the answer** — if
transcripts did *not* persist command output, the design would be strictly stronger, never weaker.

### 5.6 The guarantee, stated exactly

> **At most one *nonce-bearing* actor after divergence.** The nonce is single-use per generation and
> a generation dies only when its successor is proven received. Two actors holding one generation
> diverge at the first acknowledgment; from that point exactly one can present a valid value, and the
> other's next attempt is refused. Bodies that do **not** present a nonce are unaffected — this is a
> continuity signal, not a capability.

What that deliberately does **not** say, and v1's §4.5 wrongly implied by omission: it does not say at
most one *actor*. A refused body still has every capability §2.1 lists. §5.7 audits what it does next
rather than leaving that three sections away.

**The refusal is the whole product, so it is loud.** A refused presentation:

1. exits with the distinct code of §4.13(b), naming the expected `nonce_seq` and instructing a census
   — see §5.7 for the exact constraint on that message's wording;
2. appends one JSON record to `state/supervisor-nonce-rejections.jsonl` (`state/` is gitignored;
   fields `ts`, `verb`, `caller_sid`, `expected_seq`, `presented_prefix` = first 8 hex of the
   presented value's sha256, `claim_inc`) — never the presented value itself;
3. flips `_doctor_check_supervisor_claim` to `ok=False` for any rejection in the last 24 h. That check
   hard-codes `ok=True` on both returns today (@7533-7539, docstring *"ALWAYS ok=True -- the nag is
   advisory"*); a rejection is not a nag, it is evidence of a second body, and this is the one
   condition that changes.

Rejection-log bounds are §5.9.

### 5.7 What a refused body does next

*(v1 never audited this. The gate's step-by-step showed the refused body walking straight into v1's own
escape hatches, which was the design's most expensive omission.)*

A refused body is, in the honest case, a supervisor that lost its generation — most plausibly to
context compaction eating the last printed value. Its options, all of which exist today:

| Path | Cost | Authenticated? |
|---|---|---|
| Wait out the heartbeat, then `sup-boot` ⇒ `seize` | up to `SUPERVISOR_CLAIM_STALE_SECONDS` = 3600 s (@6821); writes a `SEIZED` entry, which is the correct audit record for "a body lost continuity" | no — but it is today's shipped behavior, unchanged |
| Escalate to the operator | immediate | n/a |
| The operator's manual lever (remove `supervisor/INCARNATION`) | immediate | no — today's only release lever, undocumented in `--help`, documented for a human in `skills/fleet/supervisor.md` (§8) |

**This spec adds no fourth path.** That is a deliberate reversal of v1, which added three, each keyed
on a value a read-only view prints, and whose refusal message *instructed the refused caller to run
that view*.

**Binding constraint on the refusal message, and on the freeze page.** Agent-facing output must
name the ambiguity and the escalation, and must **not** name a lever that resolves it unilaterally. It
says *"a second body of your lineage may be acting; stop and escalate to the operator"* — not *"run
`sup-status` and then …"*. The human-facing runbook (`skills/fleet/supervisor.md`) is where the manual
lever is documented, because a human reading a runbook and an agent reading stderr are different
audiences with different capabilities. This is the one place where the absence of a privilege boundary
is worked around by an **audience** boundary, and it is worth saying that it is a convention, not a
mechanism.

**Accepted cost, stated plainly:** a supervisor that loses its nonce catastrophically is locked out of
`sup-*` for up to an hour. §5.4(b) removes the common causes; compaction remains. Shortening
`SUPERVISOR_CLAIM_STALE_SECONDS` is **not** the mitigation — it is the seizure threshold, and lowering
it makes an unattended body easier to seize from. §12 O3 puts this in front of the operator.

### 5.8 What a view may publish

*(New, and binding. §4.8's receipt shows `sup-status --json` emitting `"incarnation": claim` and
`"handshake": hs` verbatim, so **every** field added by this spec is published by a lock-free view
unless a redaction step is specified. v1 asserted the opposite and its own test would have passed on an
implementation that published both hashes.)*

> **Binding build rule — view redaction.** `cmd_sup_status` must stop emitting the raw dicts. It emits
> a **projection** of `claim` and of `hs`. `nonce_hash`, `pending_nonce_hash` and
> `handoff_token_hash` are **omitted** from both the `--json` and the human forms. The projection
> publishes `nonce_present` (bool), `pending_present` (bool), `nonce_seq` (int), `lineage_id`, and
> `state`. Symmetric with §9's dict-literal rule, and tested by T15, which asserts the **hash strings**
> are absent — not merely the nonce string, which was never in the file.

Two further rules in the same family:

- **The nonce and the hashes never appear in `supervisor/JOURNAL.md`** (git-tracked; §4.7's anchored
  regex would corrupt the record even if they did), in `state/events.jsonl`, in any task file, or in
  any error message.
- **The holder's raw `session_id` continues to be published** by the human line at `7248` and by the
  git-tracked journal header. That is unchanged and, under §5.1, no longer a secret in any sense —
  precisely because this spec stops keying anything on it. It is recorded here because v1's escapes
  *were* keyed on it and a future reader must not re-introduce one.

### 5.9 Secret retention and log bounds

- **`state/supervisor-handoff-<inc>.md`** carries the plaintext handoff token (§6.4) and is written
  once and never deleted (§4.13(d)). It must be **unlinked by `sup-handoff-complete` and by
  `sup-handoff-abort`**, best-effort, and swept by `fleet clean`. Gitignored is not a retention policy.
- **`state/supervisor-nonce-rejections.jsonl`** is bounded: the writer truncates to the most recent
  200 records, and `_doctor_check_supervisor_claim` reads only the tail. Without §5.4(a) this file
  would grow on ordinary operation; with it, a record means something happened.
- **`supervisor/INCARNATION.tmp`** must be gitignored before any of this ships — §4.13(f), §13.

### 5.10 The three continuity problems

**(a) Fork-steer — the body persists, the sid rotates.** Nothing to do at rotation time: the claim is
not keyed on the sid, so the body simply keeps presenting its generation. `session_id` is restamped to
the caller as part of the next validated `sup-*` write.

This spec **deliberately amends none of the three sid-rotation sites** (§4.5). Pushing a
supervisor-protocol write into the generic worker steer path was the break lens' own second-choice
option and it leaves the two-bodies-one-sid hole open regardless; and §4.5 shows it is now three edits
across two drifted copies. The restamp is **pull, not push** — a steer that never leads to a supervisor
action never touches supervisor state.

**(b) Respawn — the body is gone, a fresh session inherits the duty.** A respawned body holds no
generation and cannot present one. **A respawn of the supervisor body is a body change**, and body
changes go through `sup-boot`: `resume` (§6.1) if it can prove continuity, otherwise `seize` once the
heartbeat is stale, or an explicit release (§6.3). Silent continuity across a context reset is not
offered, because nothing a fresh body could present would be unavailable to a wrong one.

**(c) Handoff — a different body, deliberately, with the predecessor alive to vouch.** §6.4.

---

## 6. Decisions

### 6.1 D1 — the boot verdict order

New signature: `supervisor_claim_decision(claim, live_sids, latest_entry, now=None,
stale_seconds=..., caller_sid=None, nonce_valid=False)`. Order:

| # | Condition | Verdict |
|---|---|---|
| 0 | `claim is None` | `claim` (fresh) |
| 1 | `claim.get("state") == "released"` | `claim` (fresh), reason *predecessor released cleanly* — §6.3 |
| 2 | `holder_sid in live_sids` **and** `holder_sid != caller_sid` | **`refuse`** — the roster-liveness two-supervisor guard, against a distinct live body |
| 3 | `nonce_valid` **and** (`holder_sid not in live_sids` **or** `holder_sid == caller_sid`) | **`resume`** — no seize, no new incarnation, no `SEIZED`, no page. Restamp `session_id`, refresh `heartbeat_at`, journal `BOOT` bodied *resumed own claim after \<age\>* |
| 4– | unchanged: heartbeat unreadable ⇒ `freeze`; journal names a fresher incarnation ⇒ `refuse`; roster-gone + stale ⇒ `seize`; roster-gone + fresh ⇒ `freeze` | |

**Rule 0b (`re-issue`) is deleted.** v1 granted a fresh nonce to any caller matching the recorded sid,
which §2.1 shows is an environment-variable assignment away — a documented, permanent bypass of the
whole mechanism. It was safe to delete only once §5.4(b) removed the failure it silently repaired.

**Item 3 of the binding list is adopted in substance and DISPUTED in one clause, with a receipt.**

The binding text: *"Run the roster-liveness guard **before** Rule 0, granting `resume` only when the
recorded holder is roster-gone. Restores what adjudication item 1 binds the spec to preserve, and
**still fully resolves incident 2**."* The first half is adopted verbatim — the guard is now rule 2 and
runs first. **The parenthetical "only when the recorded holder is roster-gone" does not resolve
incident 2**, and the receipts say why:

1. `_roster_live_sids` (@6986-6999, §4.4) counts any entry carrying `status` or `pid`. **A resumed,
   running session carries them.** So a holder that is *the caller itself* is in `live_sids`.
2. `supervisor_claim_decision` (@7014-7042, §4.4) hits `holder_sid in live_sids → refuse` before every
   later branch, and has no caller parameter with which to notice.
3. Incident 2's own record says the observed verdict was **`refuse`/freeze** (`knowledge/lessons.md:627`),
   and the recovery was `sup-heartbeat` — a verb that reaches `_require_claim_holder`'s sid equality
   rather than the claim decision. A roster-gone holder with a stale heartbeat would have produced
   `seize`, and there would have been no wart to record.

Under the strict clause, incident 2's shape lands on rule 2 and is refused again. The narrow
amendment — **rule 2 refuses only a *distinct* live sid; rule 3 grants `resume` when the caller
proves continuity and is either roster-gone or is itself the recorded holder** — resolves it while
surrendering nothing: a second body with a *different* sid still hits rule 2, and a second body with
the *same* sid is undecidable here by §2.1 and is covered by §5.4(c)'s detection instead. That is the
correct division of labour between the two mechanisms.

**If a reviewer prefers the strict form**, the cost is explicit: incident 2 stays unfixed in its
`refuse` arm, and `sup-heartbeat` remains the documented workaround. Flagged for the next gate rather
than decided here.

### 6.2 D2 — `spawned_by` continuity across supervisor body changes

*(Both lenses agreed this ships roughly as drafted. Unchanged from v1 except that "proved with a valid
nonce" now means §5.3's semantics.)*

- Worker records gain **`spawned_by_lineage`** (additive, nullable): the spawning claim's `lineage_id`,
  or `null`. Written where `spawned_by` is written (@2310) and carried forward exactly as it is
  (@3806/@3857).
- `_worker_is_foreign(record, caller, claim_lineage=None)` returns **not-foreign** if *either*
  `record["spawned_by"] == caller` (today's rule, byte-for-byte unchanged) *or*
  `record["spawned_by_lineage"] == claim_lineage`, where `claim_lineage` comes from a claim the caller
  proved continuity on in this same invocation. An unproven caller gets today's answer.
- `lineage_id` is minted at the first fresh claim, **carried across handoff**, **re-minted on seize** —
  a seize is a recovery, and being asked once at a recovery is correct.

`spawned_by` remains spawn-immutable and untouched, so SPEC §4/§15's immutability sentence needs no
amendment; the schema and the guard description do (§8). Note for the builder: the existing
`tests/test_destructive_guard.py` carries roughly thirty `spawned_by` assertions that the third
parameter touches (§10).

### 6.3 D3 — `sup-release`, plain form only

`fleet sup-release [--reason TEXT] [--nonce N] [--sid S]` — requires continuity proof per §5.3.
It does not delete INCARNATION; it rewrites it as a **released** claim.

**The full post-release key set, enumerated** (v1 left this open, and the gap made a released claim
indistinguishable from a legacy one — §9): `incarnation_id`, `lineage_id`, `claimed_via`,
`released_at`, `released_by_sid`, optional `reason`, and **`state: "released"`**. Removed:
`nonce_hash`, `pending_nonce_hash`, `pending_at`, `nonce_seq`, `session_id`, `heartbeat_at`.

It journals a new kind **`RELEASED`**, which touches the four lists of §4.7 (`--kind`'s `choices` is
the exception: `RELEASED` is not a `sup-checkpoint` value).

What this buys is the fourth unambiguous shape at boot:

| INCARNATION state | `sup-boot` verdict | Journal |
|---|---|---|
| absent | `claim` (fresh) | `BOOT` |
| held, a **distinct** holder sid roster-live | `refuse` | — |
| held, roster-gone, heartbeat stale | `seize` | `SEIZED` |
| held, roster-gone, heartbeat fresh | `freeze` + escalate | — |
| **released** | **`claim` (fresh), reason *predecessor released cleanly*** | **`BOOT`, no `SEIZED`, no page** |

**`--force --confirm-inc` is deleted.** v1 added it for the case incident 3 actually presented — the
body was already `claude stop`ped and could not release itself — and in doing so created a
two-command, fully-sanctioned seizure of a live claim whose only input is printed by a read-only view.
That is a larger disease than the one it cured. Incident 3's real requirement is *an
operator-authorized stop must be distinguishable from a daemon restart*, and it is met **without** an
unauthenticated verb:

- **Planned case (the doctrine):** `fleet sup-release`, then `claude stop`. The released row is
  unambiguous. This is the fix going forward and it is what `skills/fleet/supervisor.md` will say.
- **Unplanned case (the body is already gone):** the shape resolves itself. Roster-gone plus a
  heartbeat that ages past `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s, @6821) becomes `seize` with a
  `SEIZED` entry — today's shipped behavior, correct, and bounded by one hour. Below that hour the
  verdict is `freeze`, whose page must name the ambiguity and escalate without naming a lever
  (§5.7). The operator's manual lever stays exactly as documented-for-humans as it is today.

If the operator wants the escape hatch anyway, that is a deliberate acceptance of an unauthenticated
seizure verb — §12 O2, surfaced, not decided.

### 6.4 D4 — handoff verifies a token, not a sid

§4.6 shows the handoff turning on `hs["session_id"] != args.expect_sid`, with the predecessor learning
that sid only by watching the roster. A successor that forks between HANDSHAKE and complete fails the
equality — the same root cause, third instance.

1. `sup-handoff-begin` mints a one-shot **`handoff_token`**, stores `sha256(token)` as
   `handoff_token_hash` in its **own** INCARNATION (so the predecessor need not remember it and
   survives its own fork-steer mid-handoff), and renders the plaintext into the successor's task file
   under `state/` — deleted on complete or abort per §5.9.
2. `sup-boot --handoff-inc <inc> --handoff-token <tok>` writes HANDSHAKE as
   `{incarnation_id, session_id, handoff_token_hash, nonce_hash, written_at}`, where `nonce_hash` is
   the successor's own freshly-minted generation. `session_id` stays for observability; `written_at`
   remains write-only (the doctor check uses file mtime).
3. `sup-handoff-complete --expect-inc I [--expect-sid S]` verifies `hs["incarnation_id"] == I` **and**
   `hs["handoff_token_hash"] == claim["handoff_token_hash"]`. **`--expect-sid` becomes optional**:
   when passed it is checked, and a mismatch is a loud warning naming the fork rather than a refusal.
   The new INCARNATION literal at @7404 carries the successor's `nonce_hash`, `nonce_seq = 1`, and the
   predecessor's `lineage_id`.
4. `_render_successor_task` (@7257-7274, §4.6) is amended in the same commit, and so is
   `skills/fleet/supervisor.md`'s handoff sequence with its required `--expect-sid` (§4.8).

`sup-handoff-abort` is unchanged — **both** of its sid checks (the HANDSHAKE arm @7441-7445 and the
abort-flag arm @7456, §4.13(a)) are genuinely sid questions: they choose which *session* to stop.

### 6.5 D5 — no environment-variable channel

`--nonce <value>` is the only presentation channel. **There is no `FLEET_SUP_NONCE`.**

§4.10's receipt is the reason: `_worker_env` copies the entire parent environment and strips exactly
one key, so any env-var channel is inherited by every worker fleet spawns and by every subagent those
workers spawn. A command-line argument does not propagate to children; on this substrate both are
readable by a same-user process, so propagation is the whole difference, and it is decisive.

Two consequences the builder must carry:

- The design **depends on** a `FLEET_WORKER` refusal in `_require_claim_holder`, which does not exist
  today — a worker turn can hold the supervisor claim and is prevented only by accident. That is a
  **shipped-code defect, filed separately and not built here** (§13). This spec references it as a
  prerequisite; it does not specify it.
- Belt-and-braces if any future env channel is ever added: strip it in `_worker_env` alongside
  `CLAUDE_CODE_SESSION_ID`. Recorded so the next author does not have to re-derive it.

### 6.6 D6 — the roster-liveness two-supervisor guard

Three-tier adjudication item 1 binds this spec to preserve it. It is preserved and improved:

- **It runs first** (§6.1 rule 2), ahead of any continuity check. v1 put `resume` ahead of it and thereby
  spent a body-blind credential to skip the only body-discriminating check in the program.
- **It refuses a distinct live sid** — its actual purpose. §6.1 records the one-clause dispute.
- **Its input improves.** Today the recorded `session_id` is written at claim time and never restamped,
  so after a fork-steer it points at a retired sid, which is roster-gone, and the guard silently
  protects nothing. Restamping on every validated `sup-*` write makes the roster join track the body
  that is actually acting.
- **Under a stale roster** both error directions fail safe: a dead holder shown live ⇒ `refuse` (no
  seize); a live holder shown gone with a fresh heartbeat ⇒ `freeze` (no seize).

**On the staleness axis.** `supervisor_epoch_check` has no staleness test (§4.4), and its mirror
`native_epoch_suspicious` has the same gap. The break lens of the *three-tier* gate demanded a
staleness axis as its MUST-fix item 4 — and that item is sequenced to the substrate re-pin
(`THREE-TIER-ADJUDICATION-2026-07-17.md:17`, sequencing item 1), i.e. **out of this slice's scope**.
This spec therefore declines it explicitly rather than silently, and relies on the fail-safe analysis
above. The residual is `[MANAGER-VERIFICATION REQUIRED]`, §12 O4.

Provenance note, corrected: the sentence *"a stale roster currently PASSES the epoch check"* is the
three-tier adjudication's (`:17`). `docs/specs/native-substrate.md` does not address whether
`supervisor_epoch_check` has a staleness test; it answers a different question — whether an *idle-exit*
can produce a stale-but-live-looking roster — and answers it *no* (`:43`, `:208-209`) while
**endorsing** the epoch freeze (`:43`: *"That ambiguity is exactly what the epoch-freeze exists
for"*). v1 framed these as a disagreement; they are non-overlapping claims. The code receipt at §4.4 is
what this spec relies on, and it is unaffected.

---

## 7. What the claim gates — OPEN, for the operator

**This spec does not decide this.** v1 did, and the gate unwound it. Three-tier adjudication item 2 is
re-put here with the cost statement corrected.

**The correction that matters most.** v1's framing said deferring the gate meant *"incidents of class 1
stay undetected."* That is false on this design's own structure: **detection lives in the rotation and
the refusal (§5.3, §5.6), not in the gate.** Deferring the gate keeps every bit of the detection
property and drops the gate's costs. Whatever the operator chooses, incident 1 becomes a refusal.

### The three honest options

**(a) Detection only — no gate.** `sup-*` verbs key on continuity instead of a sid; nothing else
changes. Incident 1 surfaces within two supervisor actions. No operator-visible cost, no new refusal
surface, no new flag.

**(b) A gate that is knowingly bypassable.** Claim-gate the mutating verbs for supervisor-shaped
callers. The honest accounting:

- It cannot be authorization (§2.1). Anything it refuses, the refused caller can reach by another
  documented route — and if the escape is removed, the caller is simply stuck, which is a different
  failure, not a better one.
- **It is armed only while the heartbeat is fresh** (≤ 3600 s, @6821) and **this slice ships no beat**
  (§4.13(e)). Protection would be present in the hour after a human last typed a command and absent
  during exactly the quiet stretches when an unattended second body does damage. Incident 1 ran ~100
  minutes; the window is 60.
- Its own primary caller is structurally exempt: the `autoclean` scheduled task has no
  `CLAUDE_CODE_SESSION_ID`, so a caller-identity gate can never fire on it, and
  `docs/specs/autoclean.md:38` records that *the scheduler ignores exit codes* anyway.
- It would need the corrected verb taxonomy below, which v1 got wrong.

**(c) Build an authorization input first, as separate scope.** §2.3 prices it: an operator-held value
supplied out of band, never resident on this box, with a delivery channel, a rotation story and a
lockout story — none of which exist. An interactive prompt is already refuted in shipped code (§2.3).
This is a real option and a real slice; it is not a paragraph.

**Recommendation: (a) — detection only, in this slice.** It is the part both lenses independently said
stands alone and is worth building; it carries no cost the operator will feel; and it does not spend
this slice's review budget on a construct that §2.1 shows cannot do the job it would be named for. If a
gate is wanted, **(c) then (b)** is the honest order — an input first, a gate second — and (b) alone
should be chosen only as a deliberate speed-bump against accident, never described as a control.

### The verb taxonomy, corrected — needed only if (b) or (c) is chosen

v1 partitioned verbs into "gated mutating" and "exempt views" and justified the exemptions with
terminal-surface doctrine. That justification is false, and the partition was incomplete:

```
# at ccbbc02
$ sed -n '172p;175p' docs/SPEC.md | cut -c1-200
| `status [name] [--json] [--stale-ok] [--all]` | `cmd_status` @2355. Authoritative path: F4 lock shape, one roster fetch, recompute + conditional merge, table + anomaly flags. `--stale-ok` = the prob
| `wait <name...> [--any\|--all] [--timeout]` | `wait_for_workers` @2711: poll-recompute until `NATIVE_TERMINAL_STATUSES` (@1305: idle, dead, dead-suspected, limited, over_ceiling, interrupted). One r
```

```
# at ccbbc02
$ grep -n "authoritative" docs/specs/terminal-surface.md | head -2 | cut -c1-170
51:**D2 — the statusline never asserts liveness it did not probe for.** `--stale-ok` returns each worker's **last-committed** status plus `stale_seconds` derived from `
118:`--json` prints `status_snapshot()` as JSON to stdout. `--stale-ok` selects the probe-free path (no recompute, no lock, no write). Without `--stale-ok`, `--json` prin
```

`:51` continues, verbatim: *"`fleet status` (no flag) remains the authoritative, recomputing command"*.

**Only `status --stale-ok` is the view path.** Bare `status`, `wait` and `doctor` take `fleet.lock`,
fetch the roster and write the registry — they are *authoritative*, not views. And two registry-mutating
verbs appeared in neither of v1's lists:

```
# at ccbbc02
$ grep -n 'add_parser("attach"\|add_parser("release"' bin/fleet.py
7656:    p_attach = sub.add_parser("attach", help="attach an interactive terminal to a worker")
7660:    p_release = sub.add_parser("release", help="release an attached worker back to idle")

$ sed -n '3704,3719p' bin/fleet.py
def cmd_release(args) -> int:
    """`fleet release <name>` (SPEC §5 release row): attached -> idle,
    clearing attached_since; a friendly no-op warning if not attached."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]
        if rec["status"] != "attached":
            print(f"{args.name}: not attached -- nothing to release")
            return 0
        rec["status"] = "idle"
        rec["attached_since"] = None
        data["workers"][args.name] = rec
        save_registry(data)
        append_event("released", args.name)
```

| Class | Verbs |
|---|---|
| **View** (no lock, no roster, no write) | `status --stale-ok`, `peek`, `result`, `home`, `knowledge`, `sup-status` |
| **Authoritative read** (lock + roster + registry write, but not a lifecycle action) | `status` (bare), `wait`, `doctor` |
| **Mutating lifecycle** | `spawn`, `send`, `respawn`, `kill`, `clean`, `interrupt`, `archive`, `autoclean`, `resume-limited`, `init`, **`release`** |
| **Refuses under native** | `attach` (@3688 always raises) |

Any gate must be stated against **this** partition, and must say what it does with the middle row —
which is where v1's error lived.

---

## 8. Invariants, specs and shipped contracts touched

| Artifact | What changes | Owner |
|---|---|---|
| `docs/SPEC.md` §4 registry schema | `spawned_by_lineage` added (additive; `spawned_by` and its immutability sentence unchanged) | this slice, at build time |
| `docs/SPEC.md` §12 supervisor protocol | INCARNATION v2 fields; `resume`/`released` states; `sup-release`; handoff verifies a token | this slice |
| `docs/SPEC.md` §12 journal description | `:222` calls the journal *"append-only, claim-holder-only"*; `RELEASED` is written by the claim holder, so the sentence stands — recorded because v1's deleted `--force` form would have broken it | this slice |
| `docs/SPEC.md` §13 doctor roster | `supervisor-claim` stops being unconditionally `ok=True` for one condition (§5.6); check count stays 21 | this slice |
| `docs/SPEC.md` §15 destructive guard | the lineage arm of `_worker_is_foreign` | this slice |
| `docs/SPEC.md` §14 / `terminal-surface.md` | **unchanged in doctrine**, but `cmd_sup_status` becomes a filtered projection (§5.8) — still no lock, no probe, no write | this slice |
| **`skills/fleet/SKILL.md`** | `:37` publishes `Exit 0=hold/handshake-written, 2=refuse, 3=freeze` — amended for the new code (§4.13(b)); `:38` publishes the `--kind` list (§4.7) | this slice |
| **`skills/fleet/supervisor.md`** | the boot verdict table (`:13`, `:18`), the handoff sequence with its required `--expect-sid` (`:59`), the successor protocol (`:65`), and the *release-then-stop* doctrine plus the human-facing manual lever (§5.7, §6.3) | this slice |
| **`_render_successor_task`** @7257-7274 | the successor's generated protocol (§4.6, §6.4) — amended in the same commit or the handoff fails only during a real handoff | this slice |
| `bin/fleet.py` exception + `main()` | a `FleetCliError` subclass and a `main()` branch ahead of the generic handler, for the distinct exit code (§4.13(b)) | this slice |
| `.gitignore` | `supervisor/*.tmp` — **prerequisite, filed separately** (§13) | not this slice |
| `docs/README.md` | the specs index already lists `claim-nonce.md`; the v1 commit also restored three specs the index had been missing (`native-substrate.md`, `autoclean.md`, `three-tier-command.md`). Recorded here because the v1 table omitted it | done |
| `docs/specs/native-substrate.md` | **unchanged, including every `[PENDING OPERATOR RATIFICATION]` row** | — |
| `docs/specs/three-tier-command.md` | **unchanged; stays `PROPOSAL — RESTRUCTURE REQUIRED`** | three-tier slice |

**Repo constraints, explicitly.** Stdlib-only and single-file: `secrets`, `hashlib`, `hmac` are stdlib
(only `json` of the four is currently imported). **3.10 floor** honored — `from __future__ import
annotations` at line 20 means the `X | Y` annotations are never evaluated; `secrets.token_urlsafe`
(3.6+) and `hmac.compare_digest` (3.3+) are in-floor. No new hook commands, so the forward-slash rule
is not engaged; no background processes, so the no-Git-Bash-`&` rule is not engaged. New runtime
artifacts (`state/supervisor-nonce-rejections.jsonl`, INCARNATION v2) are under already-gitignored
paths, modulo §4.13(f). `knowledge/` untouched. No slash command is added.

**Portability (SPEC.md v3 invariant 8): nothing here is platform-specific** — no scheduler, **no
process control** (body-fencing is dropped, §3), no path semantics beyond `Path`. **No
platform-adapter seam is required and none is added.** `secrets`/`hashlib`/`hmac` are OS-identical.
*(v1's portability paragraph asserted the same thing while v1's own gate section quietly added a
`claude stop`; that contradiction is resolved by removing the process control, not by weakening the
sentence. Section numbers prefixed "v1's" refer to the superseded draft at `ccbbc02`, not to this
document.)*

**Label correction:** the tombstone rule this spec no longer invokes is SPEC §16's *"tombstone
obligation (every fleet-initiated stop writes its own outcome record)"*; **G10** is the
`native-substrate.md` / SPEC §8 label for *`claude stop` fires no Stop hook*. v1 conflated them.

---

## 9. Migration and compatibility

**An existing five-key INCARNATION.** It has no `nonce_hash`. §5.3 step 4's legacy fallback honors it
under today's sid equality once, then upgrades it in place — mint a live generation, print it, set
`nonce_seq = 1`. No operator action, no migration step, no format-version gate (SPEC §4's
additive-schema rule, confirmed by grep at §4.11, not assumed).

**The legacy predicate must exclude a released claim.** A released claim also has no `nonce_hash`
(§6.3). Read literally, v1's predicate would have classified it as legacy, fallen back to sid equality
and **upgraded it in place** — so "released" would not have been terminal, and whoever matched the
recorded sid would resurrect the claim. The predicate is therefore:

> **legacy ⇔ `nonce_hash` absent **and** `state` absent.**

A released claim matches neither the legacy path nor the continuity path; the only verb that acts on it
is `sup-boot`, which returns `claim` (§6.1 rule 1). §6.3's enumerated post-release key set (which drops
`session_id` and `heartbeat_at`) is the second half of the fix: with no recorded sid there is nothing
for a sid comparison to match even if a future reader re-introduces one.

**The asymmetry that would eat the nonce.** §4.1: three **dict-literal** writers drop unknown fields;
three round-trip writers preserve them. Fields added only to the round-trip writers survive checkpoints
and heartbeats and are then silently destroyed by the next seize or handoff — a claim that works for
days and fails at the worst moment.

> **Binding build rule:** all three dict-literal writers (`7145`, `7159`, `7404`) must carry
> `nonce_hash`, `nonce_seq`, `lineage_id` and, where applicable, `state` explicitly. T7 exists solely
> to fail if any one of them is missed.

**A supervisor body running the old code during the change.** Old `write_incarnation` writes whatever
dict it is handed, and old checkpoint/heartbeat read-mutate-write the whole dict — so a v2 claim
survives an old-code checkpoint untouched. Old `_require_claim_holder` compares the caller's sid to
`claim["session_id"]`; because new code restamps that field to the acting body, an old-code body that
*is* the acting body still matches. **Old-code `sup-boot` cannot produce a `resume` verdict**, so during
a mixed-code window a continuity-holding body still meets today's refuse/freeze wart — degradation, not
breakage. An old-code seize or handoff-complete drops the new fields and produces a legacy claim, which
the next new-code call re-upgrades.

**A new-code fleet with no supervisor** is unaffected in every path: no claim, nothing to prove.

**Registry.** `spawned_by_lineage` is one nullable additive field; §4.11's receipts show unknown fields
round-trip, and a record without it reads as `null` ⇒ today's ownership answer.

---

## 10. Test plan (unit tier — the builder writes these; this spec does not)

`tests/test_supervisor.py` (existing home of the claim/handoff/seizure state machine), plus
`tests/test_destructive_guard.py` for T12–T13.

**Seams this plan requires that do not exist yet** — named rather than presumed, because v1 asserted
"all with injected clock/roster/run" and §4.12 shows that false:

- **A command-path clock seam.** There is none anywhere; only two pure functions accept `now=`. T1 and
  T10 both need `sup-boot`/`sup-checkpoint` to run against a controlled clock. Budget: a module-level
  `_now` seam or `clock=` parameters on the `cmd_sup_*` functions the tests drive.
- **Env control for `CLAUDE_CODE_SESSION_ID`.** `tests/conftest.py`'s autouse
  `_no_inherited_claude_session` deletes it from every test (§4.12). Tests that need a controlled caller
  must `monkeypatch.setenv` after the fixture, or the fixture gains an opt-out.
- **No new subprocess seam is needed** on `cmd_sup_handoff_complete`, because §3 drops body-fencing.
  (v1 needed one and did not say so.)

**Continuity (§5.10):**

- **T1 fork-steer:** validated call, caller's sid changes, same generation presented ⇒ accepted;
  `session_id` restamped; **no** new `incarnation_id`, **no** `SEIZED`.
- **T2 respawn:** fresh caller, no generation ⇒ `sup-boot` does not grant; verdict is one of
  `refuse`/`freeze`/`seize` per §6.1, and succession is reachable only via seize or a released claim.
- **T3 handoff:** token minted, only its hash stored, HANDSHAKE carries the hash; complete transfers on
  token match **with a deliberately mismatched `--expect-sid`** (warning, rc 0, claim transferred); a
  wrong token refuses with the claim untransferred; the plaintext task file is **gone** afterwards
  (§5.9).

**Lifecycle and concurrency (§5.3, §5.4) — the block v1 had no tests for at all:**

- **T4 acknowledgment promotes:** presenting the pending generation promotes it to live, clears
  pending, bumps `nonce_seq`; presenting the *old* live value afterwards is refused.
- **T5 concurrent batch, one body:** N sequential validations all presenting the live generation all
  succeed; exactly one pending is minted; **zero** rejection records; doctor stays `ok=True`. This is
  the false-positive regression test.
- **T6 rotate-then-fail:** commit the mint, then make the verb's post-lock work raise; assert the body
  can still validate on the live generation and is **not** locked out.
- **T7 pending TTL:** a pending older than `PENDING_NONCE_TTL_SECONDS` is replaced on the next mint; a
  fresh one is not.
- **T8 two bodies, one lineage** — the incident-1 regression: two callers, same generation. Both
  validate before any acknowledgment; after the first caller acknowledges, the second is **refused**;
  assert the rejection record, the distinct exit code, and `_doctor_check_supervisor_claim` ⇒
  `ok=False`.
- **T9 racing acknowledgments:** two callers both presenting the pending value — exactly one promotes,
  the other is refused.

**Schema and migration (§9):**

- **T10 dict-literal writers**, parameterized over `7145`/`7159`/`7404`: each produces a claim that
  still validates on the next call. *This is the test that catches the §9 build rule being missed.*
- **T11 legacy upgrade:** a five-key claim is honored by sid equality once, upgraded, and thereafter
  requires the generation.
- **T12 released ≠ legacy:** `_require_claim_holder` against a released claim **refuses** (it is not a
  legacy claim); `sup-boot` against it returns `claim` with the released reason and journals `BOOT`,
  never `SEIZED`; and a caller asserting the pre-release sid gets nothing, because §6.3 removed it.
- **T13 unknown-field round-trip:** an unknown key survives checkpoint, heartbeat and handoff-abort.

**Verdicts and the two warts (§6.1, §6.3):**

- **T14 verdict order:** table-driven over §6.1's rows. Includes the two that v1 got wrong —
  (i) a **distinct** live holder sid ⇒ `refuse` **even when the caller presents a valid generation**
  (the guard runs first); (ii) the caller *is* the recorded holder, roster-live, heartbeat aged past
  3600 s, valid generation ⇒ `resume`, **no `SEIZED`, no new incarnation** (incident 2). Plus: no
  generation and a spoofed matching sid ⇒ **no grant of any kind** (Rule 0b is gone).

**Hygiene and publication (§5.8, §5.9):**

- **T15 view redaction:** assert `nonce_hash`, `pending_nonce_hash` and `handoff_token_hash` are absent
  from `sup-status` stdout in **both** the human and `--json` forms, and that `nonce_present` /
  `nonce_seq` are present. *v1's equivalent asserted only that the nonce string was absent — and the
  nonce string was never in the file, so it passed on an implementation that published both hashes.*
- **T16 no secret leaks:** the nonce plaintext appears in none of `supervisor/JOURNAL.md`,
  `state/events.jsonl`, the rejection log, or any raised error message; `_SUPERVISOR_ENTRY_RE` still
  matches every header the new code writes.
- **T17 rejection-log bound:** the log truncates to its cap; doctor reads only the tail.

**Provenance (§6.2):**

- **T18 lineage ownership:** a worker spawned under lineage L is not-foreign to a later body of L that
  proved continuity, across a sid rotation **and** across a handoff; **is** foreign after a seize. Note
  for the builder: `tests/test_destructive_guard.py` already carries ~30 `spawned_by` assertions across
  `TestOwnership` / `TestProvenanceRecorded` / `TestRespawnDoesNotLaunderOwnership` that the new
  parameter touches.

**Not in scope:** the live pin suite is unchanged; nothing here needs a real `claude`.

---

## 11. Command surface (delta only)

- `fleet sup-boot [--sid S] [--nonce N] [--handoff-inc I] [--handoff-token T]` — verdicts gain
  `resume` (§6.1); prints `NONCE: <value>` whenever it mints one.
- `fleet sup-checkpoint | sup-heartbeat | sup-handoff-begin | sup-handoff-complete | sup-handoff-abort
  [--nonce N]` — no env-var fallback (§6.5); each prints the newly minted generation, or
  `NONCE: unchanged` when one is already outstanding.
- `fleet sup-handoff-complete --expect-inc I [--expect-sid S]` — `--expect-sid` becomes optional (§6.4).
- **`fleet sup-release [--reason TEXT] [--nonce N] [--sid S]`** — new (§6.3). **No `--force` form.**
- `fleet sup-status [--json]` — a filtered projection (§5.8): adds `nonce_present`, `pending_present`,
  `nonce_seq`, `lineage_id`, `state`; **never** any hash. Still a view: no lock, no probe, no write.
- **Exit code:** a distinct code for a failed continuity proof, via a `FleetCliError` subclass plus a
  `main()` branch ordered ahead of the generic handler (§4.13(b)), and an amendment to
  `skills/fleet/SKILL.md:37`, which today publishes `Exit 0=hold/handshake-written, 2=refuse,
  3=freeze`. The value (4, or another free code) is a builder detail; **that it needs a seam and a
  published-contract amendment is not.**

---

## 12. Open questions for the operator

Short, real, and none of them decided here.

**O1 — what does the claim gate?** Options (a) detection only, (b) a knowingly-bypassable gate,
(c) build an authorization input first — priced in §7. **Recommendation: (a) in this slice**, with
(c)→(b) as the honest order if a gate is wanted later. *Alternative fairly stated:* (b) has real value
as a speed-bump against accident — most second bodies are accidents, not adversaries, and an accident
does stop at a refusal. The reasons not to lead with it are that it cannot be described as a control
without misleading a future reader, and that §4.13(e) shows it would be disarmed during exactly the
quiet stretches that matter.

**O2 — `sup-release --force`.** Removed by §6.3 until an authorization input exists.
**Recommendation: leave it removed**; the unplanned case self-resolves within one hour via `seize`, and
the manual lever remains for a human. *Alternative fairly stated:* one hour is a long time in an
incident, and an operator who accepts a documented unauthenticated seizure verb gets the wait back. That
is a legitimate trade — it is simply not the author's to make.

**O3 — the lockout window.** A supervisor that loses its generation to compaction cannot run `sup-*`
for up to `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s). **Recommendation: accept it**, because every
cheaper recovery re-creates the bypass §6.1 just deleted, and because §5.4(b) removes the common causes.
*Alternative fairly stated:* a shorter stale threshold shortens the wait — but it is the *seizure*
threshold, so shortening it makes an unattended body easier to seize from, which is the wrong direction.

**O4 — [MANAGER-VERIFICATION REQUIRED] does `supervisor_epoch_check` pass against a genuinely stale
roster served by a dead daemon?** §4.4 shows it has no staleness test, so it must pass on any non-empty
payload — but the dead-daemon path is unreachable from a `--bg` session, and both this author and both
gate reviewers are `--bg` sessions. **Recommendation: fold it into the already-parked G9 standalone
probe** (`native-substrate.md:268-274`) rather than gating this slice on it; §6.6 shows both error
directions fail safe and no decision here depends on the answer. *Alternative:* gate the build on the
probe, at the cost of a quiet-machine window.

---

## 13. Filed elsewhere — referenced, not built here

Three shipped-code defects this gate surfaced. **They are not this slice's to fix**; §6.5 and §5.9
depend on the first two, so they are prerequisites, not nice-to-haves.

1. **A worker turn can hold the supervisor claim, and is prevented only by accident.**
   `_require_claim_holder` has no `FLEET_WORKER` refusal (§4.10 shows `_worker_env` stamps it).
   Prerequisite for §6.5.
2. **`supervisor/INCARNATION.tmp` is not gitignored** (§4.13(f)). `_write_json_atomic` writes it inside
   a git-tracked directory. Prerequisite for §5.8.
3. **The published exit-code contract mismatch** — `skills/fleet/SKILL.md:37` says 0/2/3; §4.13(b) shows
   there is no seam for a fourth. §11 depends on this being resolved.

Also outside any branch, manager-owned: `docs/specs/autoclean.md:48` (path-only task ownership, now
false) and `docs/NEXT-SESSION.md:23` (lists both M-D-gate defects as still outstanding).

---

## 14. Disposition of the binding re-draft list

| # | Item | Disposition |
|---|---|---|
| 1 | Reframe to detection, not authorization | **DONE** — §2 (new), §5.1, §5.6; guarantee restated as *at most one nonce-bearing actor*, escapes named as unauthenticated in §5.7 |
| 2 | Delete Rule 0b (`re-issue`) | **DONE** — §6.1; safe because §5.4(b) landed in the same wave |
| 3 | Roster-liveness guard before Rule 0 | **DONE in substance, DISPUTED in one clause with a receipt** — §6.1: the guard runs first; the *"resume only when roster-gone"* clause does not resolve incident 2, per `_roster_live_sids` @6986-6999 + `supervisor_claim_decision` @7014-7042 + `lessons.md:627`'s recorded `refuse` verdict. Narrow amendment stated; the strict form's cost stated; flagged for the next gate |
| 4 | Close the environment channel | **DONE** — §6.5: no env channel at all; `_worker_env` receipt at §4.10; the `FLEET_WORKER` refusal referenced as a filed defect (§13), not built |
| 5 | Fix the rotation contract | **DONE** — §5.3 lifecycle, §5.4 concurrency and failure, T4–T9 |
| 6 | `sup-release` loses `--force --confirm-inc` | **DONE** — §6.3; incident 3 met by the release-then-stop doctrine plus the bounded `seize` path; §12 O2 re-puts the escape to the operator |
| 7 | The seven missing sections | **DONE** — threat model §2, lifecycle §5.3, transcript §5.5, retention §5.9, refused body §5.7, gate disarm/rollback §7 (as the gate's own accounting, since the gate is now open), view publication §5.8 |
| 8 | §3 short by five touchpoints | **DONE** — S1 §4.2, S2 §4.6, S8 §4.13(a), S9 §4.4, S6 §5.8; plus S13 §4.5, S14 §4.13(c), S15 §4.7, S16 §4.4, S7 §4.13(f) |
| 9 | S4 verb partition contradicts the spec-of-record | **DONE** — §7's corrected taxonomy, receipted, incl. `release`/`attach` |
| 10 | S5 misattributed "Accepted cost" | **DONE** — the claim is deleted with the gate decision; §3 now states `three-tier-command.md`'s full status |
| 11 | S3 `skills/fleet/` is the shipped operator contract | **DONE** — §4.8 receipts, §8 table rows for both files |
| 12 | S10 / S11 / S12 | **DONE** — §4.13(b) + §11 (exit-code seam and published contract), §4.12 + §10 (the seams that must be built), §4.12 + §10 (conftest env control) |

Also folded from the LOW list: S17/S18 citation corrections (§6.6 rewritten from the code receipt;
the *observe*/*reproduce* wording no longer relied on), S19 (§5.6 states the code fact — the append
function enforces only the kind list, the claim rule is a call-site convention, and this spec adds no
call site that skips it), S20 (§7's autoclean note), S21 (§8's G10 label correction and journal row),
S22 (§4.8 cites the function body, not the two greps), S23 (§6.6's explicit decline with its
sequencing), S24 (§8's `docs/README.md` row).

---

## 15. Pointers

- This wave's authority: `docs/reviews/ME-NONCE-ADJUDICATION-2026-07-21.md` (items 1–12);
  `ME-NONCE-DESIGN-REVIEW-BREAK-2026-07-21.md` §7 (the restructuring), §8 (what survives);
  `ME-NONCE-DESIGN-REVIEW-SPEC-2026-07-21.md` (fix list S1–S24).
- The slice's authority: `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md` (binding list items 1–3,
  §Sequencing item 2).
- Incidents: `supervisor/JOURNAL.md:94`, `:114`, `:146`; `knowledge/lessons.md:601`, `:625`, `:627`.
- Substrate (read-only input, status unchanged): `docs/specs/native-substrate.md:43`, `:146`,
  `:208-213`, `:233`, `:268-274`.
