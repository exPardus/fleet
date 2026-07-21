# Spec: Per-body supervisor claim nonce — identity that survives fork-steer, respawn, and handoff

**Status:** drafting (`me-nonce`, 2026-07-21). **The author of a spec may never promote it.** This
document is input to a dual-lens review; only the operator ratifies, and only after that review.
Nothing here is approved, and nothing here changes the status of any other document.

**Mandate:** `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md` §Sequencing item 2 —
*"Claim-nonce slice: spec task (drafting status, addresses items 1–3 above) → dual-lens review →
build gated on operator ratification of the spec."* Items 1–3 of that document's binding
restructure list are the scope; §5 below answers each explicitly.

**Inherits:** `docs/SPEC.md` v3 invariants (additive-schema rule §4, single-writer registry §4/§16.6,
one-live-session-per-name §16.7, platform-adapter-only OS branching §16.8, G9 epoch freeze §5,
tombstone obligation §16); `docs/specs/terminal-surface.md` views doctrine; `docs/specs/native-substrate.md`
G-row contract (read as observed behavior — this spec changes no verdict status there);
`CLAUDE.md` repo rules (`py -3.13` with a 3.10 floor, `bin/fleet.py` stdlib-only single file).

**Receipt pin:** every fenced `grep`/`sed` block in §3 was executed in this worktree at
`238b7ad2991e02689052853b38bde5ea94961c44` (`fleet-impl @ 238b7ad`) and is pasted with its command.
Line numbers cited in the source reviews are at `c1277bd` and are **stale**; §3 supersedes them.
Where a receipt disagrees with a review's enumeration, §3.11 records the difference.

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

The sid is used as an identity key, and it fails that job in **two opposite directions at once**:

- **Not stable enough.** The body persists but the sid rotates — fork-steer (`_restamp_after_steer`,
  §3.5), resume-limited's inline restamp (§3.5), and respawn all mint a new sid for a body whose
  duty, context, and journal lineage are unbroken.
- **Not unique enough.** The sid persists but the body forks — a host restart re-hosted the
  manager conversation as a `--fork-session` and produced **two live bodies sharing one sid and one
  incarnation id** (§1.2 incident 1).

Any mechanism that fixes only the first failure leaves the zombie class shipped. Any mechanism that
fixes only the second still breaks on the first beat. §4 addresses both, and is explicit about
which of the two it can *prevent* and which it can only *detect* (§4.6).

### 1.2 The three production incidents this spec must answer

These are not hypotheticals. Each anchor below was re-opened and verified at `238b7ad`.

**Incident 1 — dual supervisor bodies, 2026-07-16.** `supervisor/JOURNAL.md:94-96`, entry
`## 2026-07-16T16:11:19Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037`:

> INCIDENT RESOLVED: dual supervisor bodies. Phantom steers (14:23Z-16:03Z, 7 sends: 'final
> micro-wave', 'One last LOW advisory', 'URGENT root-cause task', ...) came from c787a667 -- a
> fork-session resume of THIS conversation created ~20:56 local during a host restart, running
> daemon-hosted with full campaign context, independently re-deriving and dispatching my decisions
> in paraphrase. [...] Claim-protocol gap exposed: both bodies share incarnation id + sid --
> sup-claim cannot discriminate bodies of one lineage

Corroborated at `knowledge/lessons.md:601` (`#2026-07-17-mc`, the zombie-manager class):

> The sup-claim CANNOT see this — both bodies share incarnation id + sid; a per-body nonce is the
> fix candidate (logged in three-tier-command.md).

Two facts about this incident bind the design:

1. **The zombie never ran a `sup-*` verb.** It ran `fleet send` — seven times, over ~100 minutes.
   A claim that gates only the journal would not have refused a single one of them
   (`docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-break.md:193-195`: *"A nonce that only the
   journal checks stops a zombie from journaling. It does not stop a zombie from spawning workers,
   sending phantom steers (7 observed), merging, or pushing — which is exactly what the observed
   zombie did."*). This is the whole argument of §5.2.
2. **Fleet never had a handle on the fork.** The fork was minted by the host restart, not by any
   fleet code path; fleet learned its sid only from a human process census. So *body-fencing* —
   `claude stop` the superseded body — had nothing to stop. §5.2 turns this into a decision.

**Incident 2 — `sup-boot` refuses its own holder on a stale heartbeat, 2026-07-17.**
`supervisor/JOURNAL.md:146-148`, entry `## 2026-07-17T13:45:26Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3`:

> Host restart overnight (~10h gap): same sid resumed, heartbeat refreshed (NOTE claim wart: sup-boot
> REFUSES its own holder when heartbeat stale -- self-recognition missing, feeds nonce spec + lessons).

The recovery lever is recorded in `knowledge/lessons.md:627`, not in the journal entry:

> **Claim-protocol wart found live:** `sup-boot` REFUSES its own holder when the heartbeat is stale
> (>60m) — after an overnight gap the same-sid manager could not re-boot its own claim (VERDICT
> refuse/freeze), only `sup-heartbeat` (which doesn't gate on staleness) recovered it.
> Self-recognition is missing from the claim decision; feeds the nonce spec.

The mechanism of the wart is visible in the receipt at §3.4: **`supervisor_claim_decision` does not
take the caller's identity as a parameter at all.** It cannot recognise self, structurally — not as
an oversight in a branch, but because the information is absent from the signature. §5.4.

**Incident 3 — an operator-authorized `claude stop` is indistinguishable from a daemon restart,
2026-07-17.** `supervisor/JOURNAL.md:114-116`, entry
`## 2026-07-17T01:12:15Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3`:

> Succession: operator-authorized stop of stale body inc-20260716T130803Z-5325 (sid 90bab65e, bg
> session state=done, heartbeat 01:04:27Z). 'claude stop 90bab65e' verified; census clean [...]
> sup-boot refuse->freeze (roster-gone+fresh-heartbeat, G9 heuristic blind to authorized stop);
> operator pre-ratified seize, INCARNATION cleared as delegate, fresh claim taken.

And `knowledge/lessons.md:627` (same entry as above, second clause):

> Also: `sup-boot` freeze heuristic cannot distinguish an operator-authorized `claude stop` from a
> daemon restart (both = roster-gone + fresh-heartbeat) → froze on a legitimate succession; the
> manual `rm supervisor/INCARNATION` is the only release lever — there is no `sup-release` verb.

The freeze branch is the last line of §3.4's receipt. There is no verb by which a departing body,
or an operator acting for one, can say *"this claim is over"* — so the only two shapes the boot
ritual can observe are indistinguishable, and one of them is a healthy supervisor it must never
seize from. §5.5.

### 1.3 What "identity" has to mean here

The design question the break lens left open
(`docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-break.md:139-141`):

> **Design question the spec must answer before build:** what *is* a supervisor body's identity,
> given that fleet mints a new sid on every steer, every resume, and every respawn?

This spec's answer: **a supervisor body is the holder of a secret that only the act of being granted
the claim can produce.** The sid becomes a liveness *pointer* — restamped, observability-grade,
still load-bearing for the roster join — and stops being the authorization key. §4.

---

## 2. Non-goals

- **Not `sup-spawn`, not `fleet beat`, not the scheduler bridge.** Adjudication items 4–10 belong to
  the re-drafted three-tier spec, which is sequenced *after* this one. This spec must be
  implementable and useful with today's human-attached supervisor and no three-tier work at all.
- **Not a defense against a hostile local process.** Every process on this machine can read
  `supervisor/`. The threat model is the one `_confirm_destructive` already states (§3.9): *"an
  over-helpful agent, especially one under `bypassPermissions` where no permission prompt is ever
  shown"* — plus the observed accidental-fork class. §4.3 nonetheless stores only a hash, because
  cheap defense-in-depth against file disclosure costs nothing here.
- **Not a change to `spawned_by`'s spawn-immutability.** §5.3 adds fields; it renames and mutates
  nothing.
- **Not a ratification of anything.** `docs/specs/three-tier-command.md` stays `PROPOSAL`; every
  `[PENDING OPERATOR RATIFICATION]` row in `docs/specs/native-substrate.md` keeps its status;
  `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` stays DRAFT.

---

## 3. THE GREP RECEIPT — every touchpoint of the identity mechanism, at `238b7ad`

The adjudication's item 1 names six anchors. **That list was treated as a starting point and it is
incomplete**: §3.11 lists five touchpoints it does not name, two of which (the field-dropping
INCARNATION writers, and `sup-status --json`'s verbatim claim dump) would each silently defeat a
naive implementation.

### 3.1 Everything that reads or writes `supervisor/INCARNATION`

```
# at 238b7ad
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

**Six write sites, in two classes — the distinction is load-bearing for §7:**

- **Dict-literal writers (unknown fields DROPPED):** `7145` fresh claim, `7159` seize,
  `7404` handoff-complete.
- **Round-trip writers (unknown fields PRESERVED):** `7204` checkpoint, `7215` heartbeat,
  `7473` handoff-abort — each reads the whole claim, mutates `heartbeat_at`, writes the dict back.

```
# at 238b7ad
$ grep -n "INCARNATION" bin/fleet.py
6814:# supervisor/JOURNAL.md append-only). Body claim = supervisor/INCARNATION
6850:    return supervisor_dir() / "INCARNATION"
7171:        lines.append(f"INCARNATION: {inc_line}")
7524:            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
```

**Observed INCARNATION schema — exactly five keys, no version field, no validator:**
`incarnation_id`, `session_id`, `claimed_at`, `heartbeat_at`, `claimed_via`. (`claimed_at` is
written at 7146/7160/7406 and **never read anywhere**; `claimed_via` is read once, at 7249.)

Both `supervisor/INCARNATION` and `supervisor/HANDSHAKE` are runtime, not git-tracked:

```
# at 238b7ad
$ grep -n "supervisor/" .gitignore
7:supervisor/INCARNATION
8:supervisor/HANDSHAKE
```

### 3.2 The equality that must change — `_require_claim_holder`

```
# at 238b7ad
$ grep -n 'claim.get("session_id")\|claim\["session_id"\]' bin/fleet.py
7022:    holder_sid = claim.get("session_id")
7187:    if caller != claim.get("session_id"):
```

```
# at 238b7ad
$ grep -n "_require_claim_holder" bin/fleet.py
6966:    _require_claim_holder) -- spec §4: append-only, single-writer."""
7177:def _require_claim_holder(sid_override=None):
7201:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7213:        claim, _ = _require_claim_holder(getattr(args, "sid", None))
7287:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7391:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7439:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
```

```
# at 238b7ad
$ grep -n "_require_claim_holder(getattr" -B 6 bin/fleet.py | grep -E "def cmd_|_require_claim_holder\(getattr"
7195-def cmd_sup_checkpoint(args) -> int:
7201:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7209-def cmd_sup_heartbeat(args) -> int:
7213:        claim, _ = _require_claim_holder(getattr(args, "sid", None))
7287:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7385-def cmd_sup_handoff_complete(args) -> int:
7391:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
7439:        claim, caller = _require_claim_holder(getattr(args, "sid", None))
```

**Five call sites, all `sup-*`** (checkpoint, heartbeat, handoff-begin @7287, handoff-complete,
handoff-abort @7439). **`spawn`, `send`, `kill`, `clean`, `respawn`, `archive`, `autoclean`, and
every git operation are unguarded by the claim.** The whole authorization model is the one string
equality at `7187`.

### 3.3 The `--sid` override — an existing forgery surface the nonce must not inherit

```
# at 238b7ad
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

`_require_claim_holder(sid_override)` resolves the caller as `sid_override or
current_caller_session()` (@7184). **Any caller can therefore assert any sid** — the claim check is
already, today, a check of *what the caller typed*, not of who the caller is. A nonce is a strictly
stronger proof only because the value cannot be read off `sup-status`; §4.3 keeps it that way, and
§4.7 states what `--sid` becomes.

The sole source of caller identity in the program:

```
# at 238b7ad
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

### 3.4 `supervisor_claim_decision` — the roster-liveness guard, and the missing self-parameter

```
# at 238b7ad
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

`caller_sid` **is not a parameter of this function.** Incident 2 is a structural consequence, not a
branch bug. The `holder_sid in live_sids` line is the genuine two-live-supervisors guard §5.6 must
preserve.

The epoch check that gates it:

```
# at 238b7ad
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

**The epoch check tests fetch-success and non-emptiness only. It has no staleness test.** A roster
that is stale but non-empty therefore returns `(True, ...)` and the claim decision proceeds against
it. §5.6 states the consequence; §8 records the provenance caveat on the substrate side.

### 3.5 `_restamp_after_steer` — and the second, inline restamp path the review's list misses

```
# at 238b7ad
$ grep -n "_restamp_after_steer(" bin/fleet.py
3293:                _restamp_after_steer(r, new_sid, short_id)
6331:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
```

**One call site, not two.** The docstring names a second path that does not call it:

```
# at 238b7ad
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

`_resume_one_limited_native` carries a duplicated inline copy:

```
# at 238b7ad
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

**Both are registry-only; neither touches `supervisor/INCARNATION`.** Any design that relies on
"the steer path restamps the claim" must amend **two** sites, and §4.4 explains why this spec
deliberately does not put a supervisor-protocol write in either of them.

### 3.6 HANDSHAKE and `--expect-sid`

```
# at 238b7ad
$ grep -n "def write_handshake" -A 7 bin/fleet.py
6911:def write_handshake(incarnation_id: str, session_id: str) -> None:
6912-    _write_json_atomic(handshake_path(), {
6913-        "incarnation_id": incarnation_id,
6914-        "session_id": session_id,
6915-        "written_at": now_iso(),
6916-    })
```

```
# at 238b7ad
$ grep -n "expect_sid\|expect-sid" bin/fleet.py
7379:          f"  fleet sup-handoff-complete --expect-inc {successor_inc} --expect-sid {successor_sid}\n"
7386:    """`fleet sup-handoff-complete --expect-inc I --expect-sid S [--sid ...]`.
7397:                or hs.get("session_id") != args.expect_sid):
7401:                f"sid={args.expect_sid} -- NOT transferring (spec §4 id verification)")
7403:                                  f"claim -> {args.expect_inc} sid={args.expect_sid}")
7405:                           "session_id": args.expect_sid,
7743:    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
```

The predecessor learns `successor_sid` by observing the roster after its own hand-rolled dispatch
(@7314-7367); it has no way to bind that sid to the body that will actually run. A successor that
forks between writing HANDSHAKE and the predecessor's `sup-handoff-complete` fails the equality at
`7397` — the same root cause, third instance. §5.7.

### 3.7 The journal: entry regex, kinds, and the three separate kind-lists

```
# at 238b7ad
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
# at 238b7ad
$ sed -n '6825,6828p;6924,6925p;6981p' bin/fleet.py
SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)
_SUPERVISOR_ENTRY_RE = re.compile(
    r"^## (?P<ts>\S+) (?P<kind>[A-Z][A-Z-]*) inc=(?P<inc>\S+) sid=(?P<sid>\S+)\s*$")
    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{safe_body}\n"
```

Adding a journal kind touches **three** lists: `SUPERVISOR_JOURNAL_KINDS` @6825, the seed doc's
documented kinds line @6835, and `sup-checkpoint --kind`'s narrower `choices` @7727.

**`_SUPERVISOR_ENTRY_RE` is fully anchored (`$`).** A header carrying any extra trailing token would
fail `.match()` and be silently absorbed as body text of the *preceding* entry by
`parse_supervisor_journal` (@6935-6943) — an invisible corruption of the append-only record. §4.5
takes the only safe consequence: **the journal header format does not change, and the nonce never
appears in it.** `supervisor/JOURNAL.md` is git-tracked (`docs/SPEC.md:59`), which independently
forbids a secret there.

### 3.8 The two supervisor doctor checks, and the view/hook consumers

```
# at 238b7ad
$ grep -n "_doctor_check_supervisor" bin/fleet.py
6088:        functools.partial(_doctor_check_supervisor_claim),
6089:        functools.partial(_doctor_check_supervisor_handoff),
7533:def _doctor_check_supervisor_claim():
7542:def _doctor_check_supervisor_handoff():
```

```
# at 238b7ad
$ grep -c "def _doctor_check_" bin/fleet.py
21
```

**`sup-status --json` dumps the entire claim dict verbatim** — so any field added to INCARNATION is
published by a view, for free, with no further code change:

```
# at 238b7ad
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

This is the single most dangerous touchpoint for a naive implementation, and §4.3 is written around
it. The only supervisor consumer outside `bin/fleet.py`:

```
# at 238b7ad
$ grep -rn "supervisor\|INCARNATION\|sup-" bin/hooks/ bin/fleet_statusline.py
bin/hooks/sessionstart_fleet.py:126:        sup_line = fleet.supervisor_status_line()
```

`supervisor_status_line` (@7503-7530) is file-only, never raises, and **never reads `session_id`** —
so a sid rotation is invisible to the nag today.

### 3.9 `spawned_by` — every write and every read

```
# at 238b7ad
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

**Writers: two.** `cmd_spawn` @2310 (`spawned_by=current_caller_session()` — a raw sid) and
`cmd_respawn` @3806/@3857 (carried forward verbatim). **Readers: two**, both feeding the destructive
guard:

```
# at 238b7ad
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
# at 238b7ad
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

The discriminator §5.2 reuses is already stamped on every worker turn:

```
# at 238b7ad
$ grep -n "def _worker_env" -A 18 bin/fleet.py
989:def _worker_env(name: str) -> dict:
990-    """Child environment for a worker turn: the parent's, plus FLEET_WORKER.
[...]
1000-    CLAUDE_CODE_SESSION_ID is STRIPPED (§5.1 provenance): the child `claude`
1001-    stamps its own, and an inherited one would make a worker running
1002-    `fleet kill` look exactly like the manager that spawned it -- so a worker
1003-    could quietly retire its siblings with no confirmation."""
1004-    env = dict(os.environ)
1005-    env.pop("CLAUDE_CODE_SESSION_ID", None)
1006-    env["FLEET_WORKER"] = name
1007-    return env
```

### 3.10 Unknown-field tolerance — confirmed by grep, not assumed

```
# at 238b7ad
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
# at 238b7ad
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

`json.load` → whole dict → `json.dump` of the whole dict: **registry unknown fields round-trip.**
Confirmed against `docs/SPEC.md:118` (*"Additive-schema rule ... the single writer preserves unknown
fields on round-trip. No migration step, no format-version gate."*).

`read_incarnation` (@6888-6895) does no key validation and `write_incarnation` (@6898-6900) writes
whatever dict it is handed — **so INCARNATION unknown fields survive the three round-trip writers
and are dropped by the three dict-literal writers** (§3.1). §7 turns that asymmetry into a migration
rule instead of a defect.

**Counter-example, stated plainly: the journal is NOT unknown-field tolerant** (§3.7's anchored
regex). Tolerance is a property of the two JSON stores only.

### 3.11 What the adjudication's starting list does not name

Item 1 names: INCARNATION schema, `_require_claim_holder`, `supervisor_claim_decision`, HANDSHAKE
`--expect-sid`, `_SUPERVISOR_ENTRY_RE`, `_restamp_after_steer`. All six are real and are receipted
above. Five further touchpoints, each of which changes the design:

| # | Touchpoint | Receipt | Why it changes the design |
|---|---|---|---|
| A | Three **dict-literal** INCARNATION writers drop unknown fields (7145 / 7159 / 7404) | §3.1 | A nonce added only to the round-trip writers is destroyed by the next seize or handoff. §7. |
| B | `sup-status --json` dumps the claim dict verbatim (7232-7241) | §3.8 | A plaintext nonce in INCARNATION is published by a **view**, readable lock-free by anything. Forces the hash-only store, §4.3. |
| C | `_resume_one_limited_native`'s **inline** restamp (3428-3436) | §3.5 | The "restamp the claim from the steer path" option needs two edits, not one. §4.4. |
| D | `--sid` override on all five gated verbs (7721-7748) | §3.3 | Caller identity is already self-asserted; §4.7 must say what `--sid` means once a nonce exists. |
| E | `_SUPERVISOR_ENTRY_RE` is `$`-anchored; an extra header token is **silently swallowed as body** (6924-6947) | §3.7 | Rules out putting the nonce (or any new field) in the journal header. §4.5. |

### 3.12 `[UNBUILT]` proofs — reproduced as no-matches at `238b7ad`

Every claim below that something does not exist yet is `[UNBUILT — owned by this slice]` unless
otherwise tagged.

```
# at 238b7ad
$ grep -rn "nonce" bin/
$ echo "exit $?"
exit 1

$ grep -rn "sup-release\|sup_release" bin/
$ echo "exit $?"
exit 1

$ grep -rn "body_id\|body_nonce\|claim_nonce" bin/
$ echo "exit $?"
exit 1

$ grep -rn "RESERVED" bin/fleet.py
$ echo "exit $?"
exit 1
```

- No nonce of any kind exists in `bin/` — **`[UNBUILT — owned by this slice]`**.
- No `sup-release` verb exists — **`[UNBUILT — owned by this slice]`** (§5.5).
- No reserved-name list exists — **`[UNBUILT — owned by the three-tier slice]`** (adjudication item
  10, D6). This spec does not reserve a name.
- `SUPERVISOR_JOURNAL_KINDS` @6825-6828 has no `RELEASED` and no `REBODY` kind, so even a
  journal-only release is impossible today without the three-list amendment of §3.7 —
  **`[UNBUILT — owned by this slice]`**.

---

## 4. The mechanism

### 4.1 D1 — the claim is keyed on a secret, not on the sid

`supervisor/INCARNATION` gains **three additive fields** (no rename, no removal — SPEC §4's
additive-schema rule):

| Field | Value | Read by |
|---|---|---|
| `nonce_hash` | `sha256(nonce).hexdigest()` — **never the nonce itself** | `_require_claim_holder`, `supervisor_claim_decision` |
| `nonce_seq` | integer, starts at 1, `+1` on every rotation | views (safe), doctor, the rejection log |
| `lineage_id` | `lin-<utc>-<4 hex>`, minted at the first fresh claim, **carried across handoff, re-minted on seize** | `_worker_is_foreign` (§5.3) |

`session_id` **stays** — it keeps its key name and its roster-join role, but its meaning changes from
*authorization key* to **liveness pointer: the sid of the body that most recently proved the claim**
(§4.4). `incarnation_id`, `claimed_at`, `heartbeat_at`, `claimed_via` are unchanged.

The **nonce** is a `secrets.token_urlsafe(32)` string. It is minted by whichever code path grants
the claim, **printed once on that command's stdout**, and never written anywhere in plaintext.
Stdlib-only and 3.10-safe: `secrets.token_urlsafe` (3.6+), `hashlib.sha256`, `hmac.compare_digest`
(3.3+, used for the comparison so validation is constant-time).

### 4.2 How a body proves it holds the claim

`_require_claim_holder(sid_override=None, nonce=None)` becomes:

1. Read INCARNATION under `fleet_lock` (unchanged; the docstring's lock requirement stands).
2. Resolve the presented nonce: `--nonce <value>` if given, else `$FLEET_SUP_NONCE`, else absent.
3. **If the claim has a `nonce_hash`:** valid iff
   `hmac.compare_digest(sha256(presented), claim["nonce_hash"])`. The caller's sid is **not**
   compared. On success the verb, before returning, **restamps `session_id` to
   `current_caller_session()` and rotates the nonce** (§4.4).
4. **If the claim has no `nonce_hash`** (a legacy claim, §7): fall back to today's exact
   `caller != claim.get("session_id")` comparison, and **upgrade the claim in place** — mint a
   nonce, store its hash, set `nonce_seq = 1`, print it. Zero operator action; one-way.
5. On failure: refuse loudly, exit code `4` (new, distinct from `refuse`=2 / `freeze`=3), and append
   a rejection record (§4.6).

### 4.3 Why the store is a hash, and where the nonce may never appear

`supervisor/INCARNATION` is a plain file that every process on this box can read, and §3.8 shows
`sup-status --json` republishing the claim dict verbatim through a lock-free **view**. A plaintext
nonce would therefore be readable by (a) anything with filesystem access and (b) anything that can
run a read-only fleet view — which is every worker, every hook, and the statusline.

Storing only `sha256(nonce)` makes the file useless to a reader: *the only way to hold the nonce is
to have been given it.* Three binding consequences:

- **The nonce never enters `supervisor/JOURNAL.md`.** That file is git-tracked (`docs/SPEC.md:59`),
  and §3.7's anchored regex would silently swallow a modified header anyway. The journal header
  format is unchanged by this spec.
- **The nonce never enters `sup-status` output, `--json` or human.** `sup-status` gains
  `nonce_present: true|false` and `nonce_seq: <int>`; it never sees the hash either (a hash is not a
  secret, but publishing it invites a rainbow-free offline compare with no upside).
- **The nonce never enters `state/events.jsonl`, `state/tasks/*.md`, or any error message.**
  Rejection records store `nonce_seq` and a `sha256` prefix, never the presented value.

### 4.4 The three continuity problems, answered separately

They are three different problems and the design owes three different answers.

**(a) Fork-steer — the body persists, the sid rotates.** Nothing to solve at rotation time: the
claim is not keyed on the sid, so the fork carries the nonce in its context and simply keeps
proving. The next claim-bearing call restamps `session_id` to the new sid and rotates the nonce.

This spec **deliberately does not** amend `_restamp_after_steer` or the inline copy at §3.5. Reasons:
(i) it would put a supervisor-protocol write inside the generic worker steer path — the break lens's
own stated objection to that option (`-break.md:134-136`: *"still leaves the 'two bodies, one sid'
hole open"*); (ii) §3.11(C) shows it is two edits, and the two paths have drifted once already;
(iii) the restamp is **pull, not push** — the body restamps the claim when it acts, so a steer that
never leads to a supervisor action never touches supervisor state. The claim's `session_id` becomes
*more* accurate than today, not less (§5.6).

**(b) Respawn — the body is gone, a fresh session inherits the duty.** A respawned body has no
transcript and therefore no nonce; it cannot prove anything, and it must not be able to. **Respawn
of a supervisor body is a body change, and body changes go through the claim-grant path** —
`sup-boot`, which decides `resume` / `refuse` / `seize` / `freeze` / `claim` as today plus §5.4's
new self-recognition rule. A body that legitimately succeeds a dead predecessor takes the claim by
`seize` (heartbeat stale) or by an explicit release (§5.5), and receives a fresh nonce with a new
`incarnation_id`. Silent continuity across a context reset is not offered, because there is nothing
the fresh body could present that a wrong body could not.

**(c) Handoff — a different body, deliberately, with the predecessor alive to vouch.** This is the
only case where a *specific* successor can be authorized in advance, and §5.7 replaces the sid
equality with a token the predecessor minted.

**(d) The lost-nonce case, stated because it will happen.** A long-lived supervisor body compacts;
a nonce printed 200k tokens ago can be summarized away. The body cannot recover it from the file
(that is the point of §4.3). Recovery: `sup-boot` grows a **`re-issue`** verdict — the caller
presents no nonce but *is* the recorded `session_id` (`current_caller_session()`, not `--sid`; see
§4.7) → mint a fresh nonce for the **same** incarnation, journal a `BOOT` entry bodied
`nonce re-issued to holder sid`, rc 0. This path is exactly as strong as today's whole authorization
model and no weaker; it is recorded in the rejection log and surfaced by doctor, and every re-issue
rotates, so §4.6's property still holds. Every mutating verb re-prints the current nonce on stderr,
so an ordinary working rhythm keeps the value fresh in context without a re-issue.

### 4.5 What a second body of one lineage cannot forge — and what it can

Incident 1's two bodies were **byte-identical in context and identical in sid**. There is no
intrinsic property that distinguishes them: not the sid, not the cwd, not the environment, not the
filesystem. Any secret the real body holds, the fork holds too, because the fork *is* a copy of the
real body's transcript.

**Therefore: mutual exclusion between two bodies of one lineage cannot be decided correctly at the
mechanism level, and this spec does not claim to.** What the mechanism guarantees instead:

> **The at-most-one property.** The nonce is single-use: every successful claim-bearing call rotates
> it and prints the replacement. Two bodies that both hold generation *N* diverge at the first call
> — one consumes *N* and receives *N+1*; the other's next call presents a stale *N* and is refused,
> loudly, with exit code 4 and a doctor-visible record. After the first divergence **at most one
> body can act**, and the other is stopped cold rather than silently interleaving.

What a second body **cannot** forge: a nonce it was never given (a file read yields only a hash, §4.3);
a *current* nonce once the other body has rotated (single-use); a handoff (§5.7's token is minted
per-handoff and consumed).

What it **can** do: win the race, if it calls first. That is not a defect of the mechanism but a
property of the situation — and it is acceptable because the loser is the one that finds out
immediately, by refusal, and the human-attached body is normally the one still being driven.

Measured against incident 1: seven phantom steers over ~100 minutes, detected by an
event-timeline correlation plus a process census, become **one refused command**. Detection latency
goes from ~100 minutes of human forensics to the next supervisor action.

### 4.6 The refusal is the alarm

A rejected nonce is never silent. It:

1. exits **4** with a message naming the expected `nonce_seq`, the presented sequence if parseable,
   and the literal instruction *"a second body of your lineage may be acting — run
   `fleet sup-status` and a process census before doing anything else"*;
2. appends one JSON record to **`state/supervisor-nonce-rejections.jsonl`** (`state/` is gitignored;
   fields: `ts`, `verb`, `caller_sid`, `expected_seq`, `presented_prefix` (first 8 chars of the
   presented value's sha256), `claim_inc`). It cannot journal — the caller holds no claim, and the
   journal is claim-holder-only (§3.7);
3. is surfaced by `_doctor_check_supervisor_claim`, which **stops being unconditionally `ok=True`**
   for this one condition: any rejection in the last 24 h ⇒ `ok=False` with the count and the newest
   timestamp. (Today it always returns `ok=True`, §3.8 — advisory-nag doctrine. A rejection is not a
   nag; it is evidence of a second body.)

### 4.7 What `--sid` becomes

`--sid` stays, unchanged in form, for the two things it is actually for: running `sup-*` from a
plain shell during recovery, and unit-testing. But once a claim carries a `nonce_hash`, **`--sid` no
longer authorizes anything** — it only labels the caller for the journal and the restamp. The two
paths that still consult a sid for a *decision* both require it to be the process's real identity:

- §4.4(d)'s `re-issue` verdict uses `current_caller_session()` and **ignores `--sid`** — otherwise
  the recovery path would hand a fresh nonce to anyone who typed the holder's sid.
- §5.6's roster-liveness guard joins on the *recorded* `session_id`, not on the caller's.

---

## 5. Decisions

### 5.1 D2 — adjudication item 1: identity that survives fork-steer, respawn, and handoff

Settled by §4.1–§4.5. The roster-liveness two-supervisor guard is preserved by §5.6.

### 5.2 D3 — adjudication item 2: **what the claim gates**

> `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md:15`: **Decide what the claim gates** (MF2).
> Journal-only + body-fencing, or claim-gate the mutating verbs. Silence ships the zombie class.

*(The labels `MF1`/`MF2` are the adjudicator's own numbering of the break-lens
`### MUST-fix before any spec/build task starts` list at `-break.md:977-985`; those literal strings
do not appear in the break-lens document.)*

**DECISION: claim-gate the mutating verbs. Journal-only + body-fencing is rejected as insufficient,
on receipt.**

**Why the road not taken fails.** Body-fencing means: on handoff-complete or seize, the winning side
`claude stop`s the superseded body (`respawn --force`'s verified-stop shape). It genuinely closes
the *beat-resurrection* path — a stopped body cannot be fork-steered and its `ScheduleWakeup` dies
with it (G7). **It provably does not close incident 1**, because fleet never had a handle on the
fork: it was minted by a host restart, outside every fleet code path, and its sid reached fleet only
via a human process census (§1.2). A mechanism whose input is "the sid fleet dispatched" cannot fence
a body fleet never dispatched. Shipping body-fencing alone and calling item 2 answered would ship
exactly the class the adjudication warns about.

**The gate, precisely.** A caller is **supervisor-shaped** iff:

```
current_caller_session() is not None        # a Claude session, not a human shell
AND os.environ.get("FLEET_WORKER") is None  # not a fleet-dispatched worker turn
```

Both halves are free, existing discriminators — `_worker_env` @989-1007 strips
`CLAUDE_CODE_SESSION_ID` and stamps `FLEET_WORKER` on every worker turn (§3.9), and the
`caller is None` carve-out is verbatim `_confirm_destructive`'s existing human-shell rule (@2055-2057).
So: a human at a shell is ungated (unchanged, and deliberately — *"a human typing `fleet clean`
meant to type it"*); a fleet worker is ungated (it holds no claim and never should); **the only
callers left are Claude sessions fleet did not spawn — which is the supervisor body's shape, and was
exactly the zombie's shape.**

**When the gate is armed:** only while a claim exists **and** carries a `nonce_hash` **and** its
heartbeat is fresher than `SUPERVISOR_CLAIM_STALE_SECONDS`. No claim, a legacy claim, or a stale
one ⇒ today's behavior for everyone. This matters: it means the gate cannot brick a fleet whose
supervisor has gone away, and it means adopting this spec is a no-op until someone boots a
supervisor.

**Which verbs:** the mutating set — `spawn`, `send`, `respawn`, `kill`, `clean`, `interrupt`,
`archive`, `autoclean`, `resume-limited`, `init`. **Not** the views (`status`, `peek`, `result`,
`wait`, `doctor`, `home`, `knowledge`, `sup-status`) — terminal-surface doctrine is untouched, and a
view that could refuse would be a view that reads a decision.

**The operator escape, and why it does not become a reflexive `--yes`:**
`--claim-override <incarnation-id>` (or `FLEET_CLAIM_OVERRIDE=<incarnation-id>`). It must **name the
exact incarnation id it is overriding**; a wrong or absent id refuses. Because `incarnation_id`
changes on every fresh claim and every seize, the flag cannot be memorized, aliased, or baked into a
script the way a bare `--yes` can — it has to be looked up from `sup-status` at the moment of use,
which is precisely the moment the operator should be looking. Every use appends a `claim_override`
event and is doctor-visible for 24 h.

**Accepted cost.** An operator's own interactive Claude session must pass `--claim-override` (or use
`sup-release`, §5.5) to mutate a claimed fleet. That is a behavior change and it will be felt. It is
also the doctrine the adjudication already wants ratified separately
(`docs/specs/three-tier-command.md:73-75`: *"humans talk to the interface tier; direct `fleet send`
to a claimed fleet's workers is an incident, not a convenience"*). This spec makes it mechanical
rather than aspirational — and open question O2 (§10) puts that cost in front of the operator
explicitly, because it is the one decision here a reviewer cannot make for them.

**Body-fencing is additionally adopted where fleet has a handle** — it is cheap and it closes a
different path: `sup-handoff-complete` and `sup-release --force` `claude stop` the superseded sid
using `_stop_native_session`'s existing verify-via-roster shape, and write the G10 tombstone every
stop-shaped verb owes (SPEC §16). This is belt-and-braces, not the answer to item 2.

### 5.3 D4 — adjudication item 3: `spawned_by` continuity across supervisor body changes

> `...ADJUDICATION...:16`: **`spawned_by` continuity across supervisor body changes** (MF-adjacent,
> D2) — without normalizing reflexive `--yes`.

Today (§3.9): `spawned_by` is the spawner's raw sid; `_worker_is_foreign` is `owner != caller`. Every
sid rotation makes the supervisor's own workers foreign to it, so `kill`/`clean`/`respawn` demand
`--yes` every time — and the spec lens's own objection (`-spec.md:474`) is that the supervisor then
learns to pass `--yes` reflexively and *"the destructive guard is dead for the one actor it was
written to constrain."*

**DECISION: add a lineage dimension; change neither `spawned_by` nor its immutability.**

- Worker records gain **`spawned_by_lineage`** (additive, nullable): the spawning claim's
  `lineage_id` at spawn time, or `null` when the spawner held no claim. Written at `cmd_spawn`
  @2310's call and carried forward verbatim by `cmd_respawn` @3806/@3857, exactly as `spawned_by` is.
- `_worker_is_foreign(record, caller, claim_lineage=None)` returns **not-foreign** if
  *either* `record["spawned_by"] == caller` (today's rule, byte-for-byte unchanged) *or*
  `record["spawned_by_lineage"] == claim_lineage` where `claim_lineage` is the lineage of a claim the
  caller **proved with a valid nonce in this same invocation**. An unproven caller gets today's
  answer.
- `lineage_id` is minted once at the first fresh claim, **carried across handoff** (a deliberate
  continuity transfer of the same duty) and **re-minted on seize** (a recovery from an unresponsive
  body — the one moment an operator *should* be asked before the new body sweeps the old one's
  workers).

Net effect: the supervisor's workers stay owned across every sid rotation, every fork-steer, every
respawn of the *body*, and across handoff — and become foreign exactly when the lineage genuinely
changes hands. No `--yes` is normalized; the ownership question simply gets asked at the right times
instead of every time. `spawned_by` remains spawn-immutable and untouched, so SPEC §4/§15's
immutability sentence needs no amendment — but the schema and the guard description do (§6).

### 5.4 D5 — wart 1: self-recognition on a stale heartbeat (incident 2)

`supervisor_claim_decision`'s signature does not include the caller (§3.4). Fix:

```
supervisor_claim_decision(claim, live_sids, latest_entry, now=None,
                          stale_seconds=..., caller_sid=None, nonce_valid=False)
```

with **two new rules, ahead of every existing rule**:

- **Rule 0 — `resume`.** `nonce_valid` ⇒ verdict `resume`: **no seize, no new incarnation, no
  `SEIZED` entry, no operator page**, regardless of heartbeat age and regardless of roster liveness.
  Restamp `session_id` to the caller, refresh `heartbeat_at`, rotate the nonce, journal a `BOOT`
  entry bodied `resumed own claim after <age>`. rc 0.
- **Rule 0b — `re-issue`.** No nonce presented, but `caller_sid == claim["session_id"]` and
  `caller_sid` comes from `current_caller_session()` (§4.7) ⇒ §4.4(d)'s re-issue path.

Everything below Rule 0b is unchanged, including the `holder_sid in live_sids` refusal. Incident 2
resolves at Rule 0: the same body resumed after a ~10 h host-restart gap, still holding its nonce,
and `sup-boot` recognises it instead of refusing it. The `sup-heartbeat`-as-recovery-lever workaround
recorded in `knowledge/lessons.md:627` becomes unnecessary and stops being the documented path.

### 5.5 D6 — wart 2: `sup-release` (incident 3)

**DECISION: add the verb.** `knowledge/lessons.md:627` — *"the manual `rm supervisor/INCARNATION` is
the only release lever — there is no `sup-release` verb"* — and §3.12 reproduces that as no-matches
at `238b7ad`.

`fleet sup-release [--reason TEXT] [--nonce N] [--sid S]` — claim-holder-only via §4.2. It does
**not** delete INCARNATION. It rewrites it as a **released** claim: `incarnation_id`, `lineage_id`,
`released_at`, `released_by_sid`, `claimed_via` preserved, **`nonce_hash` removed**, plus
`state: "released"` and the optional reason. It journals a new kind **`RELEASED`** (which requires
the three-list amendment of §3.7: `SUPERVISOR_JOURNAL_KINDS`, the seed doc's kinds line, and — for
`RELEASED` only, since it is not a `sup-checkpoint --kind` value — *not* the `choices` list).

The point is what `sup-boot` then sees. A released claim is a **fourth, unambiguous shape**:

| INCARNATION state | `sup-boot` verdict | Journal |
|---|---|---|
| absent | `claim` (fresh) | `BOOT` |
| held, holder roster-live | `refuse` | — |
| held, roster-gone, heartbeat stale | `seize` | `SEIZED` |
| held, roster-gone, heartbeat fresh | `freeze` + page operator | — |
| **released** | **`claim` (fresh), reason `predecessor released cleanly`** | **`BOOT`, no `SEIZED`, no page** |

Incident 3 was precisely the ambiguity between rows 3 and 4 — *"both = roster-gone + fresh-heartbeat"*
— and the release row removes it by having the departing side **say so** instead of leaving the boot
ritual to guess from a heuristic that is, correctly, blind to operator intent.

**The operator-side form, because the body is usually already stopped.** In incident 3 the body was
`claude stop`ped and never got to release. So:
`fleet sup-release --force --confirm-inc <incarnation-id> [--reason TEXT]` — no nonce required, but
the exact incarnation id must be named (the same non-memorizable discipline as §5.2's override). It
journals `RELEASED` bodied `released by operator: <reason>`. **Precedent for journalling without
holding the claim already exists in shipped code**: `cmd_sup_boot`'s seize branch calls
`supervisor_journal_append` @7162 with no prior `_require_claim_holder` — the seize is an authorized
identity act, and so is an operator release.

**Doctrine this enables (for the skill, not for code):** an operator-authorized supervisor stop is
`fleet sup-release` (from the body if it can, else `--force --confirm-inc`), *then* `claude stop`.

### 5.6 D7 — the roster-liveness two-supervisor guard is preserved, and gets more accurate

Item 1 requires this explicitly. The guard is the `holder_sid in live_sids` refusal at §3.4.

- **Form unchanged.** It still refuses when the claim's recorded `session_id` is live in the roster.
  It runs *after* Rule 0, so it never fires against the caller's own proven claim — which is the
  bug it currently has, not a capability it loses.
- **Input improved.** Today the recorded `session_id` is written once at claim time and never
  restamped; after a fork-steer it points at a **retired** sid, which is roster-gone, so the guard
  silently stops guarding — it protects nothing at exactly the moment two bodies are most likely.
  Under §4.4(a) the recorded sid is restamped on every proven claim-bearing call, so the roster join
  tracks the *currently acting* body. **The nonce makes this guard load-bearing again.**
- **Under a stale roster.** §3.4's receipt shows `supervisor_epoch_check` tests fetch-success and
  non-emptiness only — **it has no staleness test**, so a stale-but-non-empty roster passes and the
  claim decision proceeds against it. Both stale-roster error directions fail safe: a dead holder
  shown live ⇒ `refuse` (no seize); a live holder shown gone, with a fresh heartbeat ⇒ `freeze` (no
  seize). Adding Rule 0 strictly *reduces* the blast radius, because the true holder is recognised
  before the roster is consulted at all — a stale roster can no longer freeze or refuse a body that
  can prove it holds the claim.

**Provenance, stated honestly.** The sentence *"a stale roster currently PASSES the epoch check"* is
the adjudication's (`...ADJUDICATION...:17`), not the substrate contract's; `docs/specs/native-substrate.md`
reaches a different conclusion for the idle-exit path (@43, @208-213: *"Roster reads: zero changes,
on evidence"*; an idle-exit *"cannot strand a live-looking entry"*), and names `cause=upgrade` as the
one remaining stale-roster vector (@43, @233). This spec therefore grounds the claim on **code**, not
on either document: the receipt at §3.4 is the whole of `supervisor_epoch_check`, and it contains no
staleness test. Substrate facts this spec relies on and does **not** restate or re-status: the daemon
is transient and idle-exits ~5 s after its last client, and `claude agents --json [--all]` still
answers from the on-disk snapshot with the daemon down (`native-substrate.md:146`,
`[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]` — **status unchanged by this spec**).

**Probe-context clause.** The author of this spec is a `--bg` worker and is therefore itself a live
daemon client; per `native-substrate.md:146` it **cannot observe the dead-daemon path at all**. No
claim in this document rests on dead-daemon behavior. The one thing a builder would want confirmed
on a quiet machine — *does `supervisor_epoch_check` pass against a genuinely stale roster served by
a dead daemon?* — is **[MANAGER-VERIFICATION REQUIRED]** and is folded into open question O4.

### 5.7 D8 — handoff: verify a token, not a sid

§3.6 shows the handoff's dual verification turning on `hs["session_id"] != args.expect_sid`, and the
predecessor learning that sid only by watching the roster. Fix, in three parts:

1. `sup-handoff-begin` mints a one-shot **`handoff_token`** (`secrets.token_urlsafe(32)`), stores
   `sha256(token)` as `handoff_token_hash` in its **own** INCARNATION (so the predecessor need not
   remember it, and survives its own fork-steer mid-handoff), and renders the plaintext token into
   the successor's task file under `state/` (gitignored, and already the sanctioned bootstrap
   channel — contract G8).
2. `sup-boot --handoff-inc <inc> --handoff-token <tok>` writes HANDSHAKE as
   `{incarnation_id, session_id, handoff_token_hash, written_at}`. `session_id` stays for
   observability; `written_at` remains write-only (§3.6 — the doctor check uses file mtime).
3. `sup-handoff-complete --expect-inc I [--expect-sid S]` verifies `hs["incarnation_id"] == I`
   **and** `hs["handoff_token_hash"] == claim["handoff_token_hash"]`. **`--expect-sid` becomes
   optional**: when passed it is checked and a mismatch is a loud warning naming the fork, not a
   refusal — the successor forking between HANDSHAKE and complete is now a normal event, not a
   failed handoff. The new INCARNATION literal at @7404 carries the successor's fresh `nonce_hash`
   (minted by the successor at step 2 and delivered via HANDSHAKE as a hash), `nonce_seq = 1`, and
   the predecessor's `lineage_id` (§5.3).

`sup-handoff-abort`'s `--successor-sid` cross-check (@7441-7445) is unchanged — it is choosing which
*session* to stop, which is genuinely a sid question.

---

## 6. Invariants and specs touched

| Document | What changes | Owner |
|---|---|---|
| `docs/SPEC.md` §4 registry schema | `spawned_by_lineage` added to the schema block (additive; `spawned_by` and its immutability sentence unchanged) | this slice, at build time |
| `docs/SPEC.md` §12 supervisor protocol | INCARNATION's three new fields; `resume`/`re-issue`/`released` states; `sup-release`; handoff verifies a token | this slice, at build time |
| `docs/SPEC.md` §13 doctor roster | `supervisor-claim` is no longer unconditionally `ok=True` (§4.6); count stays 21 | this slice |
| `docs/SPEC.md` §15 destructive guard | the lineage arm of `_worker_is_foreign`; the `--claim-override` escape | this slice |
| `docs/SPEC.md` §14 / `terminal-surface.md` | **unchanged** — no view gains a probe, a lock, a write, or a decision (§5.2) | — |
| `docs/specs/native-substrate.md` | **unchanged, including every `[PENDING OPERATOR RATIFICATION]` row** — read-only input here | — |
| `docs/specs/three-tier-command.md` | **unchanged, stays `PROPOSAL`** — re-drafted on top of this, per sequencing item 3 | three-tier slice |

**Repo constraints this design meets, explicitly:** stdlib-only and single-file (`secrets`,
`hashlib`, `hmac`, `json` — all already imported or stdlib); **3.10 floor** honored (no `match`, no
`X | Y` runtime unions beyond what the file already uses in annotations); no new hook commands, so
the forward-slash rule is not engaged; no background processes, so the no-Git-Bash-`&` rule is not
engaged; the two new runtime artifacts (`state/supervisor-nonce-rejections.jsonl`, the modified
`supervisor/INCARNATION`) are both already gitignored (§3.1), and `knowledge/` is untouched.
**Portability (SPEC.md v3 invariant 8): nothing here is platform-specific** — no scheduler, no
process control, no path semantics beyond `Path` — so **no platform-adapter seam is required, and
none is added.** `secrets`/`hashlib`/`hmac` behave identically on Win/macOS/Linux.

---

## 7. Migration and compatibility

**An existing `supervisor/INCARNATION` written by the current schema.** It has five keys and no
`nonce_hash`. §4.2 step 4 honors it under today's sid equality and upgrades it in place on the first
successful `sup-*` call. No operator action, no migration step, no format-version gate — consistent
with SPEC §4's additive-schema rule, which §3.10 confirms by grep rather than by assumption.

**The asymmetry that would eat the nonce, and the rule that prevents it.** §3.1 shows three
**dict-literal** writers (fresh claim @7145, seize @7159, handoff-complete @7404) that drop unknown
fields, and three round-trip writers that preserve them. A nonce added only to the round-trip
writers would survive checkpoints and heartbeats and then be silently destroyed by the next seize or
handoff — a claim that works for days and then fails at the worst moment.

> **Binding build rule:** all three dict-literal writers must be amended to carry `nonce_hash`,
> `nonce_seq`, and `lineage_id` explicitly. The test at §8 (T7) exists solely to fail if any one of
> them is missed.

**A supervisor body running the old code during the change.** Old `write_incarnation` writes whatever
dict it is handed, and old `cmd_sup_checkpoint`/`cmd_sup_heartbeat` read-mutate-write the whole dict
(@7201-7204, @7213-7215) — so a nonce-bearing claim **survives an old-code checkpoint or heartbeat
untouched**. Old `_require_claim_holder` compares the caller's sid to `claim["session_id"]`; because
new code restamps that field to the acting body (§4.4a), an old-code body that is the acting body
still matches. Rotation is sequence-based and lazy: validity is *presented == stored*, and an
old-code write simply does not advance `nonce_seq`, which is harmless. The one genuine mixed-code
hazard: an old-code **seize or handoff-complete** drops the new fields and produces a legacy claim,
which the next new-code call re-upgrades via §4.2 step 4. Degradation, never breakage.

**A new-code fleet with no supervisor.** The gate of §5.2 is armed only by a fresh, nonce-bearing
claim, so every behavior in this spec is inert on a fleet nobody has booted a supervisor on.

**Registry.** `spawned_by_lineage` is one nullable additive field; §3.10's `load_registry`/
`save_registry` receipt shows unknown fields round-trip, so an old binary neither loses it nor trips
on it, and a record without it reads as `null` ⇒ today's ownership answer.

---

## 8. Test plan (unit tier — the builder writes these; this spec does not)

Target file `tests/test_supervisor.py` (existing home of the claim/handoff/seizure state machine per
SPEC §17), plus `tests/test_destructive_guard.py` for T12–T13. All with injected clock/roster/run, no
`claude`.

**The three continuity paths (§4.4):**

- **T1 fork-steer:** claim with nonce → caller's sid changes → present the same nonce →
  accepted; assert `session_id` restamped to the new sid, `nonce_seq` incremented, the returned
  nonce differs, and **no** new `incarnation_id` and **no** `SEIZED` entry.
- **T2 respawn:** claim with nonce → fresh caller, no nonce, different sid → `sup-boot` does **not**
  grant; asserts the verdict is one of `refuse`/`freeze`/`seize` per the existing rules, and that a
  legitimate succession is reachable only via seize (stale heartbeat) or §5.5's released state.
- **T3 handoff:** begin mints a token and stores only its hash; successor writes HANDSHAKE with the
  token hash; complete transfers on token match **with a deliberately mismatched `--expect-sid`**
  (the successor forked) and asserts a warning, rc 0, and the claim transferred; and a wrong token
  refuses with the claim untransferred.

**Forgery and the second body of one lineage (§4.5):**

- **T4 forged nonce:** a wrong nonce is refused with exit 4, INCARNATION unchanged (`nonce_seq`
  identical), one rejection record appended, and the presented value absent from the record.
- **T5 second body, one lineage** — the incident-1 regression: two callers **with the same sid** and
  the same nonce generation. First call succeeds and rotates; **second call is refused**; assert
  at-most-one (the second caller's mutation did not occur), a rejection record, and
  `_doctor_check_supervisor_claim` returning `ok=False`.
- **T6 file-read gives nothing:** a caller that reads `supervisor/INCARNATION` and presents
  `claim["nonce_hash"]` as the nonce is refused (guards against a hash-as-token implementation slip).

**Schema and migration (§7):**

- **T7 dict-literal writers** — parameterized over the three sites: fresh claim, seize, and
  handoff-complete each produce a claim that still validates on the *next* call. **This is the test
  that catches the §7 build rule being missed.**
- **T8 legacy upgrade:** a five-key INCARNATION is honored by sid equality once, upgraded in place,
  and thereafter requires the nonce.
- **T9 unknown-field round-trip:** a claim carrying an unknown key survives checkpoint, heartbeat,
  and handoff-abort.

**The two warts (§5.4, §5.5):**

- **T10 self-recognition:** holder with a valid nonce, heartbeat aged past
  `SUPERVISOR_CLAIM_STALE_SECONDS`, own sid roster-gone → verdict `resume`, rc 0, **no `SEIZED`
  entry, no new incarnation**. Plus the `re-issue` path: no nonce, `current_caller_session()` equals
  the recorded sid → fresh nonce, same incarnation. Plus the negative: `--sid` spoofing the holder's
  sid does **not** reach `re-issue`.
- **T11 release:** `sup-release` produces a released claim with no `nonce_hash`; a subsequent
  `sup-boot` returns `claim` with the released reason and journals `BOOT`, **never `SEIZED`** and
  never `freeze`; `--force --confirm-inc` with a wrong id refuses and mutates nothing.

**Gating and provenance (§5.2, §5.3):**

- **T12 gate matrix:** for each of {human shell (no sid), worker turn (`FLEET_WORKER` set), Claude
  session with valid nonce, Claude session with no nonce, Claude session with stale nonce} × {a
  mutating verb, a view}: assert allowed/refused. Views are **never** refused. Assert the gate is
  disarmed when no claim, a legacy claim, or a stale-heartbeat claim exists.
- **T13 lineage ownership:** a worker spawned under lineage L is not-foreign to a later body of L
  that proves its claim, across a sid rotation **and** across a handoff; **is** foreign after a
  seize (lineage re-minted); and `--claim-override <wrong-inc>` refuses while the right id proceeds
  and emits the event.

**Hygiene (§4.3):**

- **T14 no secret leaks:** assert the nonce string appears in **none** of `sup-status` stdout
  (human and `--json`), `supervisor/JOURNAL.md`, `state/events.jsonl`, the rejection log, or any
  raised error message. Assert `_SUPERVISOR_ENTRY_RE` still matches every header the new code writes
  (guards §3.11(E)).

**Not in scope for the unit tier:** the live pin suite is unchanged by this slice; nothing here
needs a real `claude`. A pin addition would be justified only if a future slice makes the daemon
part of the claim path.

---

## 9. Command surface (delta only)

- `fleet sup-boot [--sid S] [--nonce N] [--handoff-inc I] [--handoff-token T]` — verdicts gain
  `resume` and `re-issue`; prints `NONCE: <value>` on stdout whenever it grants or re-issues one.
- `fleet sup-checkpoint|sup-heartbeat|sup-handoff-begin|sup-handoff-complete|sup-handoff-abort
  [--nonce N]` — `$FLEET_SUP_NONCE` is the fallback; each re-prints the rotated nonce on stderr.
- `fleet sup-handoff-complete --expect-inc I [--expect-sid S]` — `--expect-sid` becomes optional
  (§5.7).
- **`fleet sup-release [--reason TEXT] [--nonce N] [--sid S]`** and
  **`fleet sup-release --force --confirm-inc <incarnation-id> [--reason TEXT]`** — new (§5.5).
- `fleet sup-status [--json]` — adds `nonce_present`, `nonce_seq`, `lineage_id`, `state`; **never**
  the nonce or its hash. Still a view: no lock, no probe, no write.
- Every mutating verb: `[--claim-override <incarnation-id>]` (§5.2).
- Exit code **4** = claim proof failed (distinct from `refuse`=2, `freeze`=3).

---

## 10. Open questions for the operator

Short and real. Each carries my recommendation in bold and the alternative stated fairly.

**O1 — Does the mutating-verb gate (§5.2) ship in this slice, or wait for the three-tier slice?**
**Recommendation: ship it here.** It is the only part of this design that closes the zombie class,
and the adjudication says silence on item 2 ships that class. *Alternative:* land the nonce and the
two warts now and defer the gate — smaller, reviewable in isolation, and genuinely lower-risk for a
fleet the operator drives by hand today. The honest cost of deferring: incidents of class 1 stay
undetected until someone runs a census, which is exactly the status quo.

**O2 — Is `--claim-override <incarnation-id>` an acceptable price on the operator's own interactive
sessions?** **Recommendation: yes** — naming a value that changes every incarnation is the strongest
available anti-reflex, and it is the mechanical form of the two-manager doctrine the adjudication
already wants. *Alternative:* exempt sessions whose cwd is not `FLEET_HOME`, which restores
convenience but reopens the gate for exactly the shape the zombie had (it ran in the fleet cwd).

**O3 — Should a handoff preserve worker ownership (§5.3's `lineage_id` carried across handoff), or
should a successor be asked once?** **Recommendation: preserve across handoff, re-mint on seize.**
A handoff is a planned continuity of one duty; a seize is a recovery, and being asked once at a
recovery is cheap and correct. *Alternative:* re-mint on handoff too — one extra `--yes`-equivalent
per handoff, in exchange for a successor that inherits nothing implicitly.

**O4 — [MANAGER-VERIFICATION REQUIRED] Does `supervisor_epoch_check` pass against a genuinely stale
roster served by a dead daemon?** §3.4 shows it has no staleness test, so it passes on *any*
non-empty payload — but the dead-daemon path is unreachable from a `--bg` session
(`native-substrate.md:146`), and this spec's author is one. **Recommendation: fold the check into the
already-parked G9 standalone probe** (`native-substrate.md:268-274`) rather than gating this slice on
it — §5.6 shows both stale-roster error directions already fail safe, and Rule 0 strictly reduces the
exposure. *Alternative:* gate the build on the probe; costs a quiet-machine window for a risk the
design already fails safe against.

---

## 11. Pointers

- Authority: `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md` (binding list items 1–3,
  §Sequencing item 2).
- Lenses: `docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-break.md` (C1, C2, the MUST-fix list),
  `...-spec.md` (X1, X2, §3.8's touchpoint enumeration at `c1277bd` — superseded by §3 here).
- Incidents: `supervisor/JOURNAL.md:94`, `:114`, `:146`; `knowledge/lessons.md:601`, `:625`, `:627`.
- Substrate (read-only input, status unchanged): `docs/specs/native-substrate.md:146`, `:43`,
  `:208-213`, `:233`.
