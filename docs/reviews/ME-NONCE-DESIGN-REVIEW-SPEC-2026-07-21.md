# Spec-lens receipt/claim audit — `docs/specs/claim-nonce.md` @ `ccbbc02`

**Reviewer:** `me-nonce-spec` (fleet worker, `--bg`), worktree `C:/proga/fleet-me-nonce-spec`, branch `me/nonce-spec`.
**Under review:** commit `ccbbc02` on `me/nonce` — `docs/specs/claim-nonce.md` (1258 lines, `Status: drafting`)
plus its one-line edits to `docs/SPEC.md` and `docs/README.md`.
**Lens:** mechanical fact-check. *Is every factual claim in this document true of the code, and does every
receipt reproduce?* The adversarial "does the mechanism work" question belongs to the parallel lens and is
**not** answered here.

**VERDICT: `fix-list(S1–S24)`** — the document's factual base is **reliable**. All 31 §3 receipts reproduce
byte-for-byte, all three production incidents are verbatim at their cited sources, and not one code claim I
tested is confabulated. What it is short of is **completeness**: five touchpoints that a builder implementing
§3 literally would miss, one citation that attributes a position to a document that does not hold it, and a
verb taxonomy that contradicts the spec-of-record. None of this is a reason to reject; all of it is a reason
not to build until §3/§5.2/§6 are amended.

---

## 0. Method and probe context

**Pin proof — every grep below is a receipt "at `238b7ad`", run in this worktree, by me:**

```
$ git diff --stat 238b7ad HEAD -- bin/ tests/ supervisor/ knowledge/ .gitignore
$ echo "exit $?"
exit 0                      # empty diff: identical trees

$ git rev-parse HEAD; git hash-object bin/fleet.py; git rev-parse 238b7ad:bin/fleet.py
7f99d842fb08d4d6f9cf83400dfdbbee47954e84
562e2848aab6d85e25ba053ee5ef410917c4d4b1
562e2848aab6d85e25ba053ee5ef410917c4d4b1
```

`238b7ad → 7f99d84` touches `docs/PLAN-PROGRESS.md` only. `bin/fleet.py` is blob `562e284` at both. No temp
checkout was needed and none was made.

**Probe context (v1.7 clause).** I am a `--bg` worker and therefore a live daemon client. **I ran no probe
that requires a dead daemon, and no claim in this review rests on one.** Every receipt below is a static file
read or a `grep`/`sed`/`git` invocation I personally executed. I ran **no** mutating `sup-*` verb, no `fleet`
mutating verb, no `claude`, no `schtasks`. `git` was read-only except for the commit of this file.

**Subagent discipline.** Two subagents were dispatched for breadth (a cross-document citation sweep and an
independent touchpoint re-derivation). **Every claim either of them returned that appears in this review was
re-executed by me before it was written down.** Anything they reported that I could not personally reproduce
is absent from this document.

**What I could not verify — `[MANAGER-VERIFICATION REQUIRED]`:** the spec's open question **O4** (does
`supervisor_epoch_check` pass against a genuinely stale roster served by a dead daemon?). I inherit the
author's own structural blindness here. The spec is correct to park it; see §J.

---

## A. The 31 receipts — all reproduce

I re-ran every fenced `grep`/`sed` block in §3, in order, byte-for-byte.

| # | §  | Command | Result |
|---|----|---------|--------|
| R1  | 3.1  | `grep -n "write_incarnation\|def read_incarnation\|incarnation_path" bin/fleet.py` | REPRODUCES |
| R2  | 3.1  | `grep -n "INCARNATION" bin/fleet.py` | REPRODUCES |
| R3  | 3.1  | `grep -n "supervisor/" .gitignore` | REPRODUCES |
| R4  | 3.2  | `grep -n 'claim.get("session_id")\|claim\["session_id"\]' bin/fleet.py` | REPRODUCES *(but see **S1** — the command undercounts)* |
| R5  | 3.2  | `grep -n "_require_claim_holder" bin/fleet.py` | REPRODUCES |
| R6  | 3.2  | `grep -n "_require_claim_holder(getattr" -B 6 … \| grep -E "def cmd_\|…"` | REPRODUCES |
| R7  | 3.3  | `grep -n '"--sid"\|"--expect-sid"\|"--expect-inc"\|"--successor-sid"' bin/fleet.py` | REPRODUCES |
| R8  | 3.3  | `grep -n "def current_caller_session" -A 9 bin/fleet.py` | REPRODUCES |
| R9  | 3.4  | `sed -n '7014,7042p' bin/fleet.py` | REPRODUCES (29/29 lines exact) |
| R10 | 3.4  | `sed -n '7002,7011p' bin/fleet.py` | REPRODUCES (10/10 lines exact) |
| R11 | 3.5  | `grep -n "_restamp_after_steer(" bin/fleet.py` | REPRODUCES |
| R12 | 3.5  | `sed -n '6331,6352p' bin/fleet.py` | REPRODUCES (22/22 lines exact) |
| R13 | 3.5  | `sed -n '3428,3436p' bin/fleet.py` | REPRODUCES (9/9 lines exact) |
| R14 | 3.6  | `grep -n "def write_handshake" -A 7 bin/fleet.py` | REPRODUCES — content exact; the paste drops the two trailing blank lines (6917–6918) that `-A 7` emits. Cosmetic. |
| R15 | 3.6  | `grep -n "expect_sid\|expect-sid" bin/fleet.py` | REPRODUCES |
| R16 | 3.7  | `grep -n 'SUPERVISOR_JOURNAL_KINDS\|_SUPERVISOR_ENTRY_RE\|choices=\["CHECKPOINT"' bin/fleet.py` | REPRODUCES |
| R17 | 3.7  | `sed -n '6825,6828p;6924,6925p;6981p' bin/fleet.py` | REPRODUCES |
| R18 | 3.8  | `grep -n "_doctor_check_supervisor" bin/fleet.py` | REPRODUCES |
| R19 | 3.8  | `grep -c "def _doctor_check_" bin/fleet.py` → `21` | REPRODUCES |
| R20 | 3.8  | `sed -n '7232,7242p' bin/fleet.py` | REPRODUCES (11/11 lines exact) |
| R21 | 3.8  | `grep -rn "supervisor\|INCARNATION\|sup-" bin/hooks/ bin/fleet_statusline.py` | REPRODUCES *(conclusion overstated — see **S3**)* |
| R22 | 3.9  | `grep -n "spawned_by" bin/fleet.py` | REPRODUCES |
| R23 | 3.9  | `grep -n "def _worker_is_foreign" -A 8 bin/fleet.py` | REPRODUCES |
| R24 | 3.9  | `sed -n '2042,2047p;2055,2060p' bin/fleet.py` | REPRODUCES |
| R25 | 3.9  | `grep -n "def _worker_env" -A 18 bin/fleet.py` | REPRODUCES — the paste elides 991–999 behind an explicit `[...]`. Honest elision, not byte-for-byte. |
| R26 | 3.10 | `grep -n "def load_registry" -A 10 bin/fleet.py` | REPRODUCES |
| R27 | 3.10 | `grep -n "def save_registry" -A 9 bin/fleet.py` | REPRODUCES |
| R28 | 3.12 | `grep -rn "nonce" bin/` → no match, `exit 1` | REPRODUCES |
| R29 | 3.12 | `grep -rn "sup-release\|sup_release" bin/` → no match, `exit 1` | REPRODUCES |
| R30 | 3.12 | `grep -rn "body_id\|body_nonce\|claim_nonce" bin/` → no match, `exit 1` | REPRODUCES |
| R31 | 3.12 | `grep -rn "RESERVED" bin/fleet.py` → no match, `exit 1` | REPRODUCES *(non-probative — see **S14**)* |

**31 / 31 reproduce. 0 differ. 0 do not run.** Two pastes are abridged (R14 trailing blanks, R25 with an
explicit `[...]`); neither changes a fact. The author's stated history — four of its own receipts failed
reproduction and were corrected before commit — appears to have been carried out honestly: **no survivor
found.**

Unreceipted §3 claims I checked independently, **all true**:

- §3.1 "exactly five keys, no version field, no validator"; `claimed_at` written at `7146`/`7160`/`7406` and
  **never read**; `claimed_via` read once at `7249` — confirmed by `grep -n "claimed_at\|claimed_via"`.
- §3.1's 3/3 dict-literal vs round-trip split — confirmed by reading all six write sites.
- §3.3 "`_require_claim_holder(sid_override)` resolves the caller as `sid_override or
  current_caller_session()` (@7184)" — confirmed, line 7184 exactly.
- §3.7 "the seed doc's documented kinds line @6835" — confirmed (`Kinds: BOOT, CHECKPOINT, …` is line 6835).
- §3.7/§3.11(E) "silently absorbed as body text of the *preceding* entry" — confirmed at
  `parse_supervisor_journal` @6928-6947: a non-matching line is appended to `current["body"]`.
- §3.6 "the predecessor learns `successor_sid` by observing the roster (@7314-7367)" — confirmed.
- §3.8 "`supervisor_status_line` (@7503-7530) is file-only, never raises, and **never reads `session_id`**" —
  confirmed by reading the whole function.
- §5.7 "`written_at` remains write-only" — confirmed: `grep -n "written_at"` returns exactly one line, 6915.
- §5.5 "`cmd_sup_boot`'s seize branch calls `supervisor_journal_append` @7162 with no prior
  `_require_claim_holder`" — confirmed.
- §6 "count stays 21" — confirmed (`R19`), and the slice adds no check.

---

## B. The three author self-corrections — all three CONFIRMED, one overstated

The task brief flagged these as "either excellent or confabulated". They are excellent. **No refutation.**

### B1 — "the adjudication's 6-anchor list is incomplete; §3.11 adds 5" → **CONFIRMED**

```
$ sed -n '14p' docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md
1. **Per-body claim nonce is a hard PREREQUISITE, its own slice, own review** (MF1, D1). Identity that
survives fork-steer/respawn/handoff; enumerate every touchpoint by grep (INCARNATION schema,
`_require_claim_holder`, `supervisor_claim_decision`, HANDSHAKE `--expect-sid`, `_SUPERVISOR_ENTRY_RE`,
`_restamp_after_steer`); preserve the roster-liveness two-supervisor guard.
```

Exactly six anchors, in the spec's stated order. All five §3.11 additions are real and receipted (A=R1,
B=R20, C=R13, D=R7, E=R17). The two the spec singles out as build-defeating are both genuine.
**But the list is still incomplete — §C below adds five more.**

Bonus verification: `preserve the roster-liveness two-supervisor guard` is present as a bare imperative, so
§5.6's "Item 1 requires this explicitly" is fair.

### B2 — "`_restamp_after_steer` has **one** call site, not two" → **CONFIRMED**

```
$ grep -n "_restamp_after_steer(" bin/fleet.py
3293:                _restamp_after_steer(r, new_sid, short_id)
6331:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
```

One call site (`3293`, inside `_cmd_send_native`'s fork-steer commit). The docstring @6332-6337 names
`resume-limited`'s native branch as a caller and it is not one — the inline copy at 3428-3436 is real and
reproduces exactly. A correct and non-obvious catch.

Two refinements the spec does not make: the inline copy has **drifted** (it sets `status="working"` and does
**not** bump `turns`, which the shared helper does @6352), and there is a **third** `retired_sids` writer —
see **S13**.

### B3 — "*a stale roster PASSES the epoch check* is the adjudication's claim, not `native-substrate.md`'s" → **CONFIRMED on the load-bearing half; the framing is overstated**

The code half is correct and is the half that matters. `R10` is the whole of `supervisor_epoch_check`: it
tests `roster_ok` and non-emptiness, and **contains no staleness test**. Grounding the claim on code rather
than on either document is exactly right.

The attribution half is correct but partial:

- `ADJUDICATION:17` does contain the parenthetical `(a stale roster currently PASSES the epoch check; …)`. ✔
- `native-substrate.md` does say `Roster reads: zero changes, on evidence` (`:208`) and an idle-exit
  `cannot strand a live-looking entry` (`:43`, `:208-209`). ✔ Both quotes verbatim.
- **But "which concludes the opposite" overstates.** native-substrate never addresses whether
  `supervisor_epoch_check` has a staleness test. It answers a different question — can an *idle-exit* produce
  a stale-but-live-looking roster? — and it explicitly *endorses* the freeze: `:43` says
  `That ambiguity is exactly what the epoch-freeze exists for` and `The roster-epoch freeze rule … is
  **mandatory regardless of G9's eventual answer**`. Two non-overlapping claims, framed as a disagreement.
- **And the provenance is incomplete** — see **S23**.

---

## C. Missing touchpoints — what §3 does not name

This is the section the mandate exists for. Severity is *how badly a builder implementing §3 literally would
be hurt*. Every entry carries the command and the output.

### S1 — MAJOR. §3.2's receipt is quote-sensitive and undercounts the sid equalities 2 → 4

The pasted command matches only double-quoted subscripts. Quote-agnostic:

```
# at 238b7ad
$ grep -n "claim.get(.session_id.)\|claim\[.session_id.\]" bin/fleet.py
7022:    holder_sid = claim.get("session_id")
7187:    if caller != claim.get("session_id"):
7190:            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
7248:        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
```

`7190` and `7248` use single quotes inside an f-string and are invisible to the spec's command. Both are
display-only, so §3.2's *substantive* conclusion — "the whole authorization model is the one string equality
at `7187`" — **survives intact.** The harm is elsewhere and it is real:

- `7190` is `_require_claim_holder`'s refusal message. Under §4.2 step 5 this message is replaced wholesale
  (exit 4, `nonce_seq`, the census instruction). A builder re-running the spec's literal command never sees it.
- **`7248` is a view printing the holder's raw `session_id`.** §4.3 is an argument about what a view may
  publish, and this is the human arm of the very command §3.11(B) singles out. §9 rewrites `sup-status`'s
  `--json` keys and says nothing about the human line.

This is the exact C4 failure mode the brief names: an enumeration that is wrong because of how the grep was
quoted, invisible to careful reading, one `grep` away.

**Fix:** re-run §3.2's receipt quote-agnostically, publish four lines, and state which of the four are
authorization and which are display.

### S2 — MAJOR. `_render_successor_task` @7257-7274 hard-codes the successor protocol, and §3 never mentions it

```
# at 238b7ad
$ sed -n '7257,7274p' bin/fleet.py
def _render_successor_task(successor_inc: str, old_inc: str) -> str:
    """Successor bootstrap body (task-file bootstrap, contract G8 -- never
    argv for size-unbounded content). Paths rendered .as_posix()."""
    fleet_py = (FLEET_HOME / "bin" / "fleet.py").as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
[...]
1. Run: py -3.13 {fleet_py} sup-boot --handoff-inc {successor_inc}
   This prints your boot bundle and writes supervisor/HANDSHAKE. You hold NO claim yet.
[...]
3. Poll every ~30s (up to 10 minutes): py -3.13 {fleet_py} sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     py -3.13 {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}"
```

The successor's *entire behaviour* is a generated prompt. §5.7 changes that behaviour materially: the
successor must now mint a nonce at step 2, deliver its **hash** via HANDSHAKE, and receive
`--handoff-token`. **If this string is not amended, the successor runs the old protocol against new code** —
and it fails only during a real handoff, i.e. the moment the spec exists to protect. §3 does not name it and
§6's touched-artifacts table does not list it.

**Fix:** add `_render_successor_task` to §3 as a receipted touchpoint and to §6's table.

### S3 — MAJOR. `skills/fleet/` is the shipped operator contract for everything this spec changes; §3.8's "only consumer" sentence is scoped narrower than the sentence it supports

§3.8 pastes `grep -rn "supervisor\|INCARNATION\|sup-" bin/hooks/ bin/fleet_statusline.py` (one hit) and
concludes *"The only supervisor consumer outside `bin/fleet.py`"*. Widening to the whole repo:

```
# at 238b7ad
$ grep -rln "sup-status\|sup-boot\|INCARNATION\|supervisor" commands/ skills/ workflows/
skills/fleet/SKILL.md
skills/fleet/supervisor.md
```

`commands/` and `workflows/` are clean — the receipt's *code* conclusion holds. The shipped **documentation**
conclusion does not:

```
$ grep -n "sup-boot\|sup-handoff\|rm supervisor\|freeze\|seize" skills/fleet/supervisor.md
10:1. Run `fleet sup-boot`. Read the ENTIRE bundle it prints (GOALS, journal
13:   - `claim` / `seize` (exit 0): you hold the claim. Continue the duty.
18:   - `freeze` (exit 3): ambiguity (daemon restart? G9). PAGE THE OPERATOR.
19:     Never seize, never mass-respawn.
56:2. `fleet sup-handoff-begin` — note the `SUCCESSOR-INC:` / `SUCCESSOR-SID:` lines.
59:4. On handshake: `fleet sup-handoff-complete --expect-inc <INC> --expect-sid <SID>`,

$ sed -n '37p' skills/fleet/SKILL.md
| `fleet sup-boot [--handoff-inc <id>]` | Supervisor boot ritual: epoch check → claim/seize/refuse/freeze +
boot bundle. Exit 0=hold/handshake-written, 2=refuse, 3=freeze. See `skills/fleet/supervisor.md`. |
```

`supervisor.md` (80 lines, 19 supervisor hits) is the operator runbook for the boot verdict table, the
handoff sequence with a **required** `--expect-sid`, and the successor protocol. `SKILL.md:37` **publishes
the exit-code contract** — which §9's exit 4 falsifies. Every one of these changes under this spec, and §6's
"invariants and specs touched" table lists neither file. §5.5 even says *"Doctrine this enables (for the
skill, not for code)"* — the spec knows the skill needs work and never makes it a touchpoint.

**Fix:** add both files to §3 and to §6's table, and state the `SKILL.md:37` exit-code line explicitly.

### S4 — MAJOR. §5.2's verb partition contradicts the spec-of-record and is incomplete

§5.2 partitions every verb into gated-mutating and exempt-views, justified by *"terminal-surface doctrine is
untouched, and a view that could refuse would be a view that reads a decision."*

**(a) The contradiction.** `status` (bare) and `wait` are listed as views. They are not:

```
$ sed -n '172p;175p;237p' docs/SPEC.md
| `status [name] [--json] [--stale-ok] [--all]` | `cmd_status` @2355. Authoritative path: F4 lock shape, one
roster fetch, recompute + conditional merge, table + anomaly flags. `--stale-ok` = the
probe-free/lock-free/write-free view path (`status_snapshot` @1558). …
| `wait <name...> …` | `wait_for_workers` @2711: poll-recompute until `NATIVE_TERMINAL_STATUSES` … One roster
fetch per poll …
… Post-pivot the "never probes a PID" clause generalizes: the snapshot path also never fetches the roster —
roster fetches belong to mutating/authoritative commands only.

$ sed -n '51p' docs/specs/terminal-surface.md
… `fleet status` (no flag) remains the authoritative, recomputing command …
```

Only `status --stale-ok` is the view path. Bare `status`, `wait`, and `doctor` take `fleet.lock`, fetch the
roster, and **write** the registry. The exemption may still be the right policy — but the *stated reason* for
it is false, and a builder reading §5.2 will mis-classify these three.

**(b) The incompleteness.** Two registry-mutating verbs appear in **neither** list:

```
$ grep -n "add_parser(\"attach\"\|add_parser(\"release\"" bin/fleet.py
7656:    p_attach = sub.add_parser("attach", help="attach an interactive terminal to a worker")
7660:    p_release = sub.add_parser("release", help="release an attached worker back to idle")

$ sed -n '3704,3720p' bin/fleet.py
def cmd_release(args) -> int:
    """`fleet release <name>` (SPEC §5 release row): attached -> idle,
    clearing attached_since; a friendly no-op warning if not attached."""
    with fleet_lock():
        ...
        rec["status"] = "idle"
        rec["attached_since"] = None
        data["workers"][args.name] = rec
        save_registry(data)
        append_event("released", args.name)
```

`release` mutates, saves, and emits an event. (`attach` @3688 always raises under native — effectively a
no-op today, but it is still unclassified.) §5.2's list is a partition and it does not partition.

**Fix:** restate the taxonomy against SPEC §7's own authoritative/view split rather than against
terminal-surface doctrine, and classify `attach`/`release`.

### S5 — MAJOR. §5.2's "Accepted cost" attributes to the adjudication a position it does not hold

§5.2, the paragraph justifying the most operator-visible change in the spec:

> It is also the doctrine the adjudication already wants ratified separately
> (`docs/specs/three-tier-command.md:73-75`: *"humans talk to the interface tier; direct `fleet send` to a
> claimed fleet's workers is an incident, not a convenience"*).

The quote itself is verbatim at `three-tier-command.md:73-75` — I checked. The attribution is not:

```
# at 238b7ad
$ grep -n "interface\|three-tier-command.md\|convenience\|humans talk" docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md
8:**RESTRUCTURE — upheld.** `docs/specs/three-tier-command.md` stays `PROPOSAL`; no spec task may claim it
as-is; no build delta from it may start. …

$ grep -n "doctrine\|ratif" docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md
17:4. **Substrate re-pin FIRST** … the ratified three-tier spec states its daemon-lifecycle assumptions …
34:2. Claim-nonce slice: spec task (drafting status, addresses items 1–3 above) → …
38:**Both review verdict files are the authority for finding details; this adjudication only merges and
sequences — no finding is re-interpreted.** Per the promotion rule, nothing here ratifies any spec; operator
gates stay.
```

The adjudication (38 lines total) **never mentions the interface tier, never mentions this doctrine, and
never says it wants anything ratified.** `:38` says the opposite: *"nothing here ratifies any spec"*. And the
source of the quote carries:

```
$ sed -n '3,9p' docs/specs/three-tier-command.md
Status: **PROPOSAL — RESTRUCTURE REQUIRED (dual-lens design gate, 2026-07-17).** …
… Do NOT spec or build from this draft as written.
```

So the spec cites, as supporting authority for a behavior change that will be felt on every operator
command, a sentence from a document explicitly marked *do not spec from this draft*, wrapped in a claim
about the adjudication that the adjudication does not make.

The **doctrine** may well be right — this review takes no position on that; it is the other lens's call and
the operator's. What is wrong is the appeal to authority. This is also the reason §2's non-goal *"stays
`PROPOSAL`"* is worth tightening: the real status is `PROPOSAL — RESTRUCTURE REQUIRED`.

**Fix:** delete the "the adjudication already wants" clause, or replace it with a citation that exists. State
`three-tier-command.md`'s full status wherever the spec calls it `PROPOSAL`.

---

## D. MODERATE findings

### S6 — §4.3/§9's "never sees the hash either" is contradicted by §3.8's own receipt, with no build rule to close it

§3.11(B) states the mechanism correctly: *"any field added to INCARNATION is published by a view, for free,
with no further code change."* §4.3 then promises the opposite for the hash, and §9 specifies no redaction:

```
# at 238b7ad
$ sed -n '7232,7242p' bin/fleet.py
    info = {
        "goals_active": supervisor_goals_active(),
        "incarnation": claim,
        "heartbeat_age_seconds": beat_age,
        "handshake": hs,
        …
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
```

`"incarnation": claim` is the whole dict. Add `nonce_hash` and `sup-status --json` publishes it, lock-free,
to every worker and hook — unless a **redaction step** is specified. §7 gets a *"Binding build rule"* for the
symmetric problem (the dict-literal writers); this one gets nothing.

Same reasoning applies to `"handshake": hs`, which §5.7 adds `handoff_token_hash` to. §3.11(B) makes the
argument only for INCARNATION.

The nonce itself is never at risk (only the hash is stored) and §4.3 concedes *"a hash is not a secret"* —
so this is a specification gap, not a security break. But it is a gap in the one section whose whole job is
to say where values may not appear.

**Fix:** a binding build rule for the redaction, symmetric with §7's, covering both `claim` and `hs`.

### S7 — `supervisor/INCARNATION.tmp` is not gitignored; §3.1's `.gitignore` receipt does not cover the file the writer creates

```
# at 238b7ad
$ git check-ignore -v supervisor/INCARNATION supervisor/HANDSHAKE
.gitignore:7:supervisor/INCARNATION	supervisor/INCARNATION
.gitignore:8:supervisor/HANDSHAKE	supervisor/HANDSHAKE

$ git check-ignore -v supervisor/INCARNATION.tmp supervisor/HANDSHAKE.tmp
$ echo "exit $?"
exit 1                       # neither is ignored

$ sed -n '6879,6885p' bin/fleet.py
def _write_json_atomic(path: Path, obj: dict) -> None:
    """Atomic JSON write (temp + os.replace) so lock-free readers (views,
    SessionStart hook) can never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))

$ git ls-files supervisor/
supervisor/GOALS.md
supervisor/JOURNAL.md
```

`_write_json_atomic` writes the sibling **inside a git-tracked directory**, and `.gitignore` covers only the
two exact final paths. A crash between `write_text` and `os.replace` leaves the full claim JSON as an
untracked-but-not-ignored file that a `git add -A` commits. §3.1 presents its `.gitignore` receipt as proof
that *"Both `supervisor/INCARNATION` and `supervisor/HANDSHAKE` are runtime, not git-tracked"* — true of
those paths, not of the writer's actual output. §4.3 is titled *"where the nonce may never appear"*.

Under the spec's hash-only store this is a doctrine violation (CLAUDE.md: runtime dirs gitignored), not a
disclosure. Under any variant that stores more, it is worse.

**Fix:** widen the §3.1 receipt to `git check-ignore` on the `.tmp` siblings, and have §7 or §6 own the
`.gitignore` amendment.

### S8 — `state/supervisor-handoff-aborted.json` is a third supervisor store §3 never names, carrying a fifth sid equality inside the stop path

```
# at 238b7ad
$ sed -n '6861,6865p' bin/fleet.py
def handoff_abort_flag_path() -> Path:
    """Doctor-visible flag written by sup-handoff-abort (spec §4 timeout
    branch). Lives in state/ (gitignored runtime), cleared by the next
    sup-handoff-begin or manually by the operator."""
    return state_dir() / "supervisor-handoff-aborted.json"

$ sed -n '7447,7456p' bin/fleet.py
            flag = read_handoff_abort_flag()
            recorded_sid = flag.get("successor_sid") if flag is not None else None
            …
            if recorded_sid is None or recorded_sid != args.successor_sid:
                raise FleetCliError(
```

Writers @7303-7310 and @7467-7471 (persisting `successor_sid` **and** `holder: claim["incarnation_id"]`);
readers @7237 (`sup-status --json`), @7447-7456, @7549 (doctor FAIL). §5.7 declares
`sup-handoff-abort`'s `--successor-sid` cross-check *"unchanged — it is genuinely a sid question"* and cites
`@7441-7445` — the **HANDSHAKE arm**. The abort-flag fallback arm at `@7456` is a separate, unmentioned sid
equality, in the one verb whose job is to `claude stop` another session. `state/` is gitignored, so there is
no disclosure concern; the concern is that §3's store enumeration is two-of-three.

### S9 — `_roster_live_sids` @6986-6999 defines the guard §5.6 must preserve, and is never receipted

```
# at 238b7ad
$ sed -n '6996,6999p' bin/fleet.py
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
    }
```

§3.4 calls `holder_sid in live_sids` *"the genuine two-live-supervisors guard §5.6 must preserve"* without
showing what decides membership. The `("status" in e or "pid" in e)` predicate is the proximate mechanism by
which a fork-steered supervisor's retired sid stops counting as live — which is the failure §5.6's
"**The nonce makes this guard load-bearing again**" argument turns on. A builder asked to preserve the guard
cannot reason about it from §3 alone.

### S10 — exit code 4 has no seam, and the published contract says 0/2/3

```
# at 238b7ad
$ grep -rn "return 4$\|sys.exit(4)\|exit code 4\|exit 4" bin/ docs/SPEC.md skills/
$ echo "exit $?"
exit 1

$ sed -n '7166p;7824,7828p' bin/fleet.py
        rc = {"claim": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]
    except RegistryCorruptError as exc:
        print(f"fleet: registry error: {exc}", file=sys.stderr)
        return 1
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
```

`_require_claim_holder`'s three refusals are plain `FleetCliError` → `main()` → **exit 1**, indistinguishable
from "registry corrupt" or "lock timeout". §4.2 step 5 and §9 assert exit 4 as if it were a return-value
change; it is a new exception class plus a `main()` branch plus an amendment to `skills/fleet/SKILL.md:37`'s
published `Exit 0=hold/handshake-written, 2=refuse, 3=freeze`. §6's table names none of it.

### S11 — §8's "All with injected clock/roster/run" is false for T3, T1 and T10

```
# at 238b7ad
$ grep -n "^def cmd_sup_" bin/fleet.py
7111:def cmd_sup_boot(args, which=shutil.which, run=subprocess.run) -> int:
7195:def cmd_sup_checkpoint(args) -> int:
7209:def cmd_sup_heartbeat(args) -> int:
7220:def cmd_sup_status(args) -> int:
7277:def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
7385:def cmd_sup_handoff_complete(args) -> int:
7417:def cmd_sup_handoff_abort(args, which=shutil.which, run=subprocess.run) -> int:
```

- **T3.** §5.2 has `sup-handoff-complete` `claude stop` the superseded sid. `cmd_sup_handoff_complete` @7385
  takes **no `which=`/`run=`** — unlike the other three subprocess-bearing verbs. The seam must be added; §8
  does not say so.
- **T1 / T10.** There is **no clock seam on any command path.** Only the two pure functions accept `now=`
  (`supervisor_claim_decision` @7014, `supervisor_status_line` @7503); every `cmd_sup_*` calls `now_iso()` /
  `datetime.now` directly. T1 asserts `nonce_seq` and restamping through a command; T10 needs a heartbeat
  aged past `SUPERVISOR_CLAIM_STALE_SECONDS` (= `3600.0` @6821) *through `sup-boot`*. Both presume a seam
  nobody has built.
- Seams that **do** exist and are correctly presumed: temp `FLEET_HOME` (`sup_home` fixture,
  `tests/test_supervisor.py:12-22`, monkeypatching `fleet.FLEET_HOME`); roster injection via `run=`;
  `tests/test_destructive_guard.py` **exists** with a `home` fixture and unit tests over `_worker_is_foreign`
  / `_confirm_destructive` / `spawned_by` provenance — T12/T13 land on real ground.

### S12 — conftest deletes the env var §4.2's fallback depends on

```
# at 238b7ad
$ grep -n "^@pytest.fixture\|^def _no_inherited\|delenv" tests/conftest.py
21:@pytest.fixture(autouse=True)
43:@pytest.fixture(autouse=True)
53:    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
```

The `_no_inherited_claude_session` fixture is **autouse** and strips `CLAUDE_CODE_SESSION_ID` from every
test. §4.2 step 2's `$FLEET_SUP_NONCE` fallback, §4.4(d)'s "`current_caller_session()`, not `--sid`" rule,
and §5.2's gate matrix (T12: *human shell / worker turn / Claude session*) all need controlled env seams the
fixture layer does not offer. Buildable, but it is a conftest change §8 does not budget.

---

## E. LOW findings

**S13 — §3.5's "Both are registry-only" and §3.11(C)'s "two edits, not one" omit the third `retired_sids` writer.**
```
$ grep -n 'retired_sids' bin/fleet.py | grep -E '3432|3860|6348'
3432:                r["retired_sids"] = list(r.get("retired_sids", [])) + [old_sid]
3860:        new_record["retired_sids"] = prior_retired + [old_sid]
6348:        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
```
`3860` is in `_cmd_respawn_native` — the only one of the three that mints a **fresh record**
(`new_worker_record(..., spawned_by=spawned_by, ...)` @3857). The spec's own title covers respawn, and §1.1
names respawn as a sid-rotation path, so "two sites" reads as complete when it is complete only for steer.
§4.4(b) routes respawn through `sup-boot` instead, so the *design* is unaffected — the *count* is wrong.

**S14 — §3.12's `RESERVED` receipt is non-probative.** It is case-sensitive:
```
$ grep -rni "reserved" bin/ | head -4
bin/fleet.py:497:            f"invalid worker name {name!r}: uuid-shaped names are reserved "
bin/fleet.py:5423:    to survive an update. FAIL is reserved for a confirmed mismatch against
bin/fleet.py:6634:            f"uuid-shaped names are reserved for session ids, F6)")
```
Reserved-name *enforcement* exists (`validate_name` @490-500, `NAME_RE` = `[a-z0-9-]+`, uuid-shape refusal).
The conclusion — no reserved-name **list** for the three-tier slice — survives; the receipt does not support
it. In a document whose thesis is *"reading a document does not verify a claim about code"*, a receipt that
proves nothing is worth replacing.

**S15 — §3.7's "three lists" is four.** `skills/fleet/SKILL.md:38` independently publishes
``| `fleet sup-checkpoint <text\|@file> [--kind CHECKPOINT\|PROPOSAL]` |``. §5.5's `RELEASED` kind touches it.

**S16 — §3.4's epoch analysis omits the mirrored predicate.**
```
$ sed -n '1557,1558p' bin/fleet.py
def native_epoch_suspicious(roster_ok: bool, entries: list, workers: dict) -> bool:
    """G9 epoch-freeze predicate (mirrors supervisor_epoch_check): the
```
Same staleness gap, second copy, unmentioned.

**S17 — two `-break.md` line ranges are stale.** Text verbatim in both cases; ranges off by one.
`"A nonce that only the *journal* checks…"` is at **192-194** (cited `:193-195`).
`"still leaves the 'two bodies, one sid' hole open"` is at **137** (cited `:134-136`). Verified by
`sed -n '190,196p'` and `sed -n '133,141p'`. `:139-141` and `:977-985` are exact.

**S18 — §5.6's probe-context quote is attributed to the wrong document.** The spec bolds *"cannot observe the
dead-daemon path at all"* as `native-substrate.md:146`. That source says `cannot **reproduce** the dead-daemon
path at all`; the word *observe* is `knowledge/lessons.md:619`'s (`a bg worker CANNOT observe the dead-daemon
path`). Substantively equivalent, wrongly sourced. The same sentence also drops the idle-exit conjunct — the
source reads `idle-exits ~5s after the last client disconnects **and** its live-worker count reaches 0`, and
that conjunct is what the whole G9 idle-exit argument rests on.

**S19 — §4.6 and §5.5 argue opposite sides of the same fact.** §4.6: *"It cannot journal — the caller holds no
claim, and the journal is claim-holder-only (§3.7)."* §5.5: *"Precedent for journalling without holding the
claim already exists in shipped code"* (`cmd_sup_boot`'s seize @7162). Both code facts are true —
`supervisor_journal_append` @6963-6983 enforces only the kind list; the claim rule is a call-site convention
(`grep -n "_require_claim_holder"` → 5 call sites, none of them `sup-boot`). One of the two arguments has to
give.

**S20 — §5.2 gates `autoclean`, whose primary caller is structurally ungated.**
`docs/specs/autoclean.md:48` installs `schtasks … running "<python>" "<fleet.py>" autoclean --fleet-home
"<home>"`. A scheduled task has no `CLAUDE_CODE_SESSION_ID`, so `current_caller_session()` is `None` and
§5.2's first conjunct is false. No conflict with `autoclean.md` — and no effect either. Worth one sentence so
a builder does not write a gate test that can never fire. (`autoclean.md:38`: *"the scheduler ignores exit
codes"* — so a refusal there would also be silent.)

**S21 — §6's table has two omissions and one mislabel.**
- `docs/SPEC.md:222` describes `supervisor/JOURNAL.md` as `(append-only, claim-holder-only)`. §5.5's
  `sup-release --force --confirm-inc` journals `RELEASED` without the claim. The §12 row does not name it.
- §5.2 writes *"the G10 tombstone every stop-shaped verb owes (SPEC §16)"*. SPEC §16 `:257` says
  `**tombstone obligation** (every fleet-initiated stop writes its own outcome record)`; the `G10` label is
  SPEC §8 `:192` and `native-substrate.md`. Correct in substance, mislabelled by section.
- The adjudication `:27` records that `SPEC §6 "one choke point" is inaccurate as written` and a
  `SPEC correction [is] owed regardless`. §3.6 relies on that hand-rolled dispatch (@7314-7367); §6's table
  has no §6 row. Sequenced elsewhere (adjudication sequencing item 4), but unmentioned.

**S22 — one unreceipted claim in a receipt-driven document.** §4.6: *"Today it always returns `ok=True`,
§3.8"*. True — `bin/fleet.py:7533-7539`, docstring `ALWAYS ok=True` and both returns hard-code `True` — but
§3.8's receipts (`grep -n "_doctor_check_supervisor"`, `grep -c` → 21) do not show it, and `docs/SPEC.md:233`
does not document it either. Cite the code.

**S23 — §5.6's provenance correction is incomplete.**
```
$ sed -n '989,993p' docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-break.md
4. **Re-pin the substrate contract before speccing against it.** (C5) `md-contract`'s
   transient-daemon findings land in `docs/specs/native-substrate.md` first; the epoch check
   needs a staleness axis, because a stale roster passes it today and every claim decision and
   every `send` branch reads it.
```
The break lens states the stale-roster fact independently, inside **MUST-fix item 4**, and demands a
staleness axis. §5.6 declines that axis (arguing both directions fail safe) without noting that MUST-fix 4 is
sequenced to the substrate re-pin (adjudication `:17`, sequencing item 1) and is therefore out of this
slice's scope. Say so; a silent decline of a MUST-fix reads as an oversight.

**S24 — the README edit exceeds the declared scope.** `git diff 238b7ad ccbbc02 -- docs/README.md` adds four
spec filenames to the index, not one: `native-substrate.md`, `autoclean.md`, `claim-nonce.md`,
`three-tier-command.md`. All four are real files and the index was genuinely stale, so this is a correct
repair — but it is three repairs the task did not ask for, made in a review-gated commit, and §6's table does
not mention `docs/README.md` at all.

---

## F. `[UNBUILT]` discipline — clean

`grep -n "UNBUILT\|unbuilt\|PRESCRIPTIVE\|not shipped\|not yet shipped\|does not exist"` over the whole spec
returns **six** hits, all in §3.12 (lines 646, 648, 670, 671, 672, 676). No lowercase `unbuilt`, no
`PRESCRIPTIVE`, no `not shipped`. There is no false tag and no untagged prose masquerading as description:
§§4–10 are openly prescriptive ("gains", "becomes", "must be amended") in a document whose `Status:` is
`drafting`, which is the correct register.

All four §3.12 no-match proofs re-run as no-matches at `238b7ad` (R28–R31). The three `[UNBUILT — owned by
this slice]` tags are sound. The one `[UNBUILT — owned by the three-tier slice]` tag reaches a defensible
conclusion on a non-probative receipt — **S14**.

The `SUPERVISOR_JOURNAL_KINDS` bullet ("no `RELEASED` and no `REBODY` kind") is correct: R17 shows the
seven-kind tuple.

---

## G. Doctrine conformance — passes, with S4 and S7 attached

| Rule | Status | Receipt |
|---|---|---|
| `bin/fleet.py` stdlib-only, single file | **PASS.** `secrets`/`hashlib`/`hmac` are stdlib; §6's *"all already imported or stdlib"* is a true disjunction — only `json` is currently imported (`sed -n '22,37p'`). | A12/A13 |
| `py -3.13` with a 3.10 floor | **PASS.** `from __future__ import annotations` at line 20, so `X \| Y` annotations are never evaluated; `secrets.token_urlsafe` (3.6+), `hmac.compare_digest` (3.3+) are in-floor. | A12 |
| Forward slashes in hook commands | **N/A** — no new hook commands. Correctly stated in §6. | — |
| No Git-Bash `&` | **N/A** — no background processes. | — |
| Runtime dirs gitignored, `knowledge/` tracked | **PASS with S7.** `.gitignore` line 1 is `state/`, so `state/supervisor-nonce-rejections.jsonl` is covered. `knowledge/` untouched. The `.tmp` sibling is the gap. | W1/A14 |
| Views never probe / never take `fleet.lock` / never write | **PASS on `sup-status`** (`cmd_sup_status` @7220-7223 docstring `READ-ONLY VIEW …no lock, no probe, no write`; body confirms). **Storage never puts a secret where a view prints it: PASS for the nonce, GAP for the hash — S6.** `terminal-surface.md` has **zero** matches for `supervisor`/`sup-status`, so the classification is code-supported, not doctrine-supported. | A39, V14 |
| Mutating slash commands stay prompt templates | **PASS.** `grep -rln … commands/ workflows/` → no supervisor hits; `sup-release` needs no slash command. | S3 receipt |
| Portability invariant 8 (Win/macOS/Linux) | **PASS.** `docs/SPEC.md:254` is invariant 8 as cited; `secrets`/`hashlib`/`hmac` are OS-identical; no adapter seam added or needed. Invariants 6 and 7 also verified at `:252`/`:253` exactly as the "Inherits" line claims. | V12 |
| Views never refuse | **PASS in intent, S4 in taxonomy.** | S4 |

---

## H. §7 migration — the rule survives the three writers

§7's central claim re-verified from the code, not from §3:

- **Reader tolerance.** `read_incarnation` @6888-6895 does `json.loads` → `isinstance(data, dict)` → return.
  No key validation. `write_incarnation` @6898-6900 hands the dict straight to `_write_json_atomic`. Unknown
  fields survive.
- **The three round-trip writers genuinely round-trip.** All three take `claim` from `_require_claim_holder`
  → `read_incarnation()`, mutate `heartbeat_at`, and write the whole dict back (`7201-7204`, `7213-7215`,
  `7471-7473`). Verified by reading each.
- **The three dict-literal writers genuinely drop.** `7145-7147`, `7159-7161`, `7404-7407` construct fresh
  five-key literals. Verified by reading each.

**So §7's binding build rule is necessary and sufficient**, and T7 is correctly aimed. §7's scope caveat is
the right one and the spec makes it itself. Registry tolerance (`load_registry` @526 / `save_registry` @562,
whole-dict `json.load`/`json.dump`) likewise confirmed, and `docs/SPEC.md:118` says verbatim what §3.10
quotes.

One thing §7 does not cover: the **old-code `sup-boot`** path. §7 says an old-code seize or handoff-complete
"drops the new fields and produces a legacy claim, which the next new-code call re-upgrades" — correct. But
an old-code `sup-boot` also cannot produce a `resume` verdict, so during a mixed-code window a
nonce-holding body still meets today's refuse/freeze wart. Degradation, as claimed; worth one sentence.

---

## I. §8 test plan — seams

T2, T4, T5, T6, T7, T8, T9, T11, T12, T13, T14 all land on seams that exist (`sup_home` temp `FLEET_HOME`;
`which=`/`run=` on `cmd_sup_boot`/`handoff-begin`/`handoff-abort`; `now=` on the two pure functions;
`tests/test_destructive_guard.py` with its `home` fixture and existing `spawned_by` coverage; `capsys`).
T1, T3 and T10 presume seams that do not exist — **S11**; T12 and §4.2 step 2 need env-var control the
autouse conftest fixture removes — **S12**.

One inherited coupling worth naming for the builder: `tests/test_destructive_guard.py` carries ~30
`spawned_by` assertions across `TestOwnership` / `TestProvenanceRecorded` / `TestRespawnDoesNotLaunderOwnership`
that §5.3's third `_worker_is_foreign` parameter will touch. §8 budgets T13 but does not mention the existing
suite.

---

## J. SPURIOUS check — nothing is specified for a problem that is not real

All three incidents verified against their cited sources, headers included. **All three verbatim.**

| Incident | Cited | Verified |
|---|---|---|
| 1 — dual supervisor bodies | `supervisor/JOURNAL.md:94-96` | **EXACT**, header `## 2026-07-16T16:11:19Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-…` and body through `sup-claim cannot discriminate bodies of one lineage`. Corroboration at `knowledge/lessons.md:601` **EXACT**. |
| 2 — `sup-boot` refuses its own holder | `supervisor/JOURNAL.md:146-148` | **EXACT**, header `## 2026-07-17T13:45:26Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-…`. |
| 3 — authorized stop ≡ daemon restart | `supervisor/JOURNAL.md:114-116` | **EXACT**, header `## 2026-07-17T01:12:15Z CHECKPOINT …`. |

**The author's third correction about where the claims live is CONFIRMED.** `sed -n '623,630p'
knowledge/lessons.md` shows line 627 is a single paragraph carrying **both** clauses the spec attributes to
it — the `sup-boot` REFUSES-its-own-holder wart *and* `Also: sup-boot freeze heuristic cannot distinguish an
operator-authorized claude stop from a daemon restart … the manual rm supervisor/INCARNATION is the only
release lever — there is no sup-release verb`. Neither is in the journal entries; the journal entries carry
only the terse `NOTE claim wart` and the succession record. The spec says exactly this and it is right.

Mechanism cross-check, so the incidents are not merely quoted but *explained correctly*:

- Incident 2's mechanism is structural, as §3.4 claims: `supervisor_claim_decision` (R9) has no `caller_sid`
  parameter, and the same-sid holder resumed into the roster hits `holder_sid in live_sids` → `refuse`.
  `sup-heartbeat` recovered it because `_require_claim_holder` @7177-7192 compares sid only, with **no**
  staleness test. Both halves confirmed in code.
- Incident 3's ambiguity is the last two branches of R9 — `seize` on stale, `freeze` on fresh — with no
  release state to distinguish. Confirmed.
- `SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0` @6821 matches lessons.md:627's `>60m`.

**No SPURIOUS finding.** Every fix in §5 answers a defect that exists at `238b7ad`.

---

## K. Status check — clean

```
$ sed -n '3p' docs/specs/claim-nonce.md
**Status:** drafting (`me-nonce`, 2026-07-21). **The author of a spec may never promote it.** This
```

`Status: drafting`, unchanged. **The author did not promote its own spec.**

The two one-line edits do not promote anything either:

- `docs/SPEC.md:268` places the nonce under `**Future candidates `[DRAFT — not specced]`:**` and describes it
  as *"a `drafting` spec awaiting dual-lens review and operator ratification"*. Correctly non-promoting; it
  does not touch three-tier's status.
- `docs/README.md:38` adds filenames to the specs index — see **S24** for scope, not for status.

**No `[PENDING OPERATOR RATIFICATION]` row anywhere changed.** `docs/specs/native-substrate.md` and
`docs/specs/three-tier-command.md` are untouched by `ccbbc02` (`git diff --stat 238b7ad ccbbc02` lists exactly
three files: `docs/README.md`, `docs/SPEC.md`, `docs/specs/claim-nonce.md`). §2's non-goal is honoured.

**I have promoted nothing. Ratification is the operator's alone.**

---

## Fix list

**MAJOR — amend before build.**
- **S1** §3.2's receipt is quote-sensitive: four sid-equality sites, not two; `7248` is a *view* printing the holder's sid.
- **S2** `_render_successor_task` @7257-7274 hard-codes the successor protocol §5.7 changes. Absent from §3 and §6.
- **S3** `skills/fleet/supervisor.md` + `skills/fleet/SKILL.md` are the shipped operator contract for every verdict, verb and exit code this spec changes. §3.8's "only consumer" sentence outruns its grep; §6 omits both.
- **S4** §5.2's verb partition contradicts SPEC §7/§14 + terminal-surface D2 (`status`, `wait`, `doctor` are authoritative, not views) and omits `release`/`attach`.
- **S5** §5.2 attributes to the adjudication a doctrine position it does not hold, quoting a document marked *"Do NOT spec or build from this draft as written."*

**MODERATE.**
- **S6** §4.3/§9's "never sees the hash" has no redaction rule; `"incarnation": claim` and `"handshake": hs` are dumped verbatim.
- **S7** `supervisor/INCARNATION.tmp` is not gitignored; §3.1's receipt does not cover the writer's actual output.
- **S8** `state/supervisor-handoff-aborted.json` — third store, fifth sid equality @7456, inside the stop path.
- **S9** `_roster_live_sids` @6986-6999 — the guard's membership predicate, never receipted.
- **S10** exit 4 has no seam; `FleetCliError` → exit 1; `SKILL.md:37` publishes 0/2/3.
- **S11** T3 needs a `run=`/`which=` seam on `cmd_sup_handoff_complete` (none); T1/T10 need a command-path clock seam (none anywhere).
- **S12** conftest's autouse fixture strips `CLAUDE_CODE_SESSION_ID`; §4.2 step 2 / T12 need env seams.

**LOW.** S13 third `retired_sids` writer · S14 non-probative `RESERVED` receipt · S15 four kind-lists, not three ·
S16 `native_epoch_suspicious` mirror · S17 two stale `-break.md` ranges · S18 misattributed
"observe"/"reproduce" + dropped idle-exit conjunct · S19 §4.6 ↔ §5.5 journal-authorization inconsistency ·
S20 `autoclean`'s gate is structurally inert · S21 §6 table omissions + G10 mislabel · S22 one unreceipted
claim · S23 incomplete provenance, silent decline of break-lens MUST-fix 4 · S24 README edit exceeds scope.

**Open, not a finding:** O4 remains `[MANAGER-VERIFICATION REQUIRED]`. I am a `--bg` worker and inherit the
author's exact blindness. The spec's recommendation — fold it into the already-parked G9 standalone probe
(`native-substrate.md:268-274`, verified present and parked at `:265`) — is sound on the evidence available
to me.

**VERDICT: `fix-list(S1–S24)`.** Receipts sound, incidents sound, status clean, no confabulation found. The
enumeration is incomplete in five places that would each cost a builder real work, and one citation claims an
authority that says the opposite.

---
---

# RE-AUDIT — `docs/specs/claim-nonce.md` @ `091d5fa` ("claim nonce v2 — detection, not authorization")

**Reviewer:** `me-nonce-spec` (fleet worker, `--bg`), second pass, 2026-07-21.
**Under review:** commit `091d5fa` on `me/nonce` — the re-draft after `ME-NONCE-ADJUDICATION-2026-07-21.md`
(break lens: `restructure`; this lens: `fix-list(S1–S24)`). 1258 → **1814 lines**, 31 → **48 receipts**.
**Lens unchanged:** does every factual claim hold, and does every receipt reproduce?

**VERDICT: `fix-list(R1–R5)`.** The factual base is **stronger than v1's**, which was already reliable.
All 24 of my fix-list items are fixed against the code — none deferred, none faked, three fixed better
than I asked. Every receipt reproduces. Zero collateral. `Status:` still `drafting`.

Five findings, all new, none touching a decision. The one that matters: **the restructure dropped an
anchor.** v1 receipted `_require_claim_holder`'s five call sites; v2 rewrites that exact function's
signature and validation contract in §5.3 and **no longer receipts its call sites anywhere**. That is the
precise failure mode the re-audit brief predicted, and it is the only finding here a builder would feel.

---

## RA-0. Method, blob identity, and probe context

**Blob-identity proof — run by me, not taken from the spec's header block:**

```
$ for r in 238b7ad ccbbc02 091d5fa HEAD; do printf "%-10s %s\n" "$r" "$(git rev-parse $r:bin/fleet.py)"; done
238b7ad    562e2848aab6d85e25ba053ee5ef410917c4d4b1
ccbbc02    562e2848aab6d85e25ba053ee5ef410917c4d4b1
091d5fa    562e2848aab6d85e25ba053ee5ef410917c4d4b1
HEAD       562e2848aab6d85e25ba053ee5ef410917c4d4b1
```

`bin/fleet.py` is one blob across all four. Receipts pinned `# at ccbbc02` are therefore equally receipts
at `238b7ad`, and greps in my worktree reproduce them. I additionally confirmed that of every path any
receipt reads, **only `docs/SPEC.md` differs** between my HEAD and `ccbbc02` — and that its cited lines
172/175 are byte-identical in both:

```
$ git diff --name-only ccbbc02 HEAD -- bin/ .gitignore skills/ commands/ tests/ docs/SPEC.md \
      docs/specs/terminal-surface.md docs/specs/autoclean.md docs/specs/native-substrate.md
docs/SPEC.md
$ diff <(git show ccbbc02:docs/SPEC.md | sed -n '172p;175p') <(sed -n '172p;175p' docs/SPEC.md) && echo IDENTICAL
IDENTICAL
```

**Probe context (v1.7).** Still a `--bg` worker, still a live daemon client. I ran no probe requiring a
dead daemon; no claim below rests on one. Every receipt is a static read or a `grep`/`sed`/`git`
invocation I personally executed. No mutating `sup-*` or `fleet` verb, no `claude`, no `schtasks`, no
write under `C:/Users/Techn/.claude/` (the one receipt that touches it is a read-only `ls`/`find`). One
subagent was used for breadth; **everything it returned was re-executed by me before it was written down.**

---

## RA-1. The receipts — 49 blocks, 0 factual differences

I did not sample. I wrote an extraction harness (stdlib-only, read-only) that parses **every** fenced
block in the 1814-line file, replays each as a single Git Bash session, and diffs the replay against the
pasted text byte-for-byte.

```
$ py -3.13 reaudit.py claim-nonce.md /c/proga/fleet-me-nonce-spec
...
=== 44/49 blocks reproduce byte-for-byte ===
```

**49 shell blocks. 44 byte-exact. All 5 remaining deltas are non-factual, and I checked each by hand:**

| Block | Delta | Verdict |
|---|---|---|
| 1 (header pin proof) | `git rev-parse HEAD` → pasted `ccbbc02…`, mine `2a181d9…` | **Expected.** Worktree-local by nature. The *substantive* half — `git diff --stat 238b7ad HEAD -- bin/ tests/ supervisor/ skills/ commands/ .gitignore` empty with `exit 0`, and `hash-object` == `rev-parse 238b7ad:bin/fleet.py` — **reproduces in my worktree too.** |
| 43, 45, 49 | one blank line between consecutive commands inside a block | Cosmetic paste formatting. Zero content. |
| 46 (`~/.claude/projects`) | count `735` pasted, `737` then `738` on my runs | Time-variant machine state. **The spec discloses this itself** (line 1114: *"it read 732 twenty minutes earlier in this same session"*). The trailing slash my harness flagged **does** reproduce in a real Git Bash — that was my harness's artifact, not the spec's. |

**No receipt DIFFERS on substance. None DOES-NOT-RUN.** The v1 carry-overs were re-checked not merely for
running but for still supporting the sentence they now sit under; §4's restructure re-homed them
accurately, and §4.2 / §4.13(c) correctly *replaced* two v1 receipts rather than re-using them.

**New vs carried-over, computed rather than eyeballed** (diffing the `$`-command sets of the two commits):

```
v1 $-lines: 35   v2 $-lines: 62
NEW in v2: 28    DROPPED from v1: 4
```

Of the 4 dropped, **2 were correctly replaced** — `grep -n 'claim.get("session_id")…'` by its
quote-agnostic form (my S1) and `grep -rn "RESERVED"` by `grep -rni "reserved"` (my S14). **2 were dropped
with no replacement — see R1.**

**The author's accounting reconciles.** I counted independently: 49 shell blocks, of which exactly 3
cannot be automated — blocks 1 and 44 (`git`) and block 46 (`~`). The claim *"48 total, 45 automated, 3
direct"* is right to ±1, the ±1 being whether the header pin-proof block counts as a receipt. Not a
finding.

---

## RA-2. The verification harness — technique validated, artifact absent

This was the interesting new claim, so I tested it as a claim rather than as a virtue.

**Does it exist in the worktree? No.**

```
$ cd /c/proga/fleet-me-nonce && git status --short --ignored
$ ls state/ 2>/dev/null
$ find . -iname "*verif*" -o -iname "*harness*" -o -iname "*receipt*" | grep -v "^./.git/"
```

All three empty. `git status --ignored` shows no untracked and no ignored file; there is no `state/`
directory; nothing on disk under the fleet home matches. **And the spec never documents it** — the only
two occurrences of "harness" in 1814 lines are at `:1130-1131`, about *transcript* harness behavior, an
unrelated subject.

**R2 (MODERATE).** The harness is a claim with no artifact. Its four asserted catches cannot be checked,
it cannot be re-run by a reviewer or by the next author, and — the manager's actual interest — **it cannot
be adopted campaign-wide, because there is nothing to adopt.** The verification *result* is not in doubt:
I re-derived it independently and got the same answer. What is missing is the reusable tool.

**Is the technique sound? Yes — I built one and seeded it.** A verifier that cannot fail is theater, so:

```
$ py -3.13 reaudit.py claim-nonce.md . --only 19 --seed "19:the handoff was aborted:the claim was aborted"
SEEDED block 19: 'the handoff was aborted' -> 'the claim was aborted'
[DIFFERS   ] block 19  spec line 522  $ sed -n '7257,7274p' bin/fleet.py
      -   - If 10 minutes pass without transfer: the claim was aborted. STOP -- take no actions,
      +   - If 10 minutes pass without transfer: the handoff was aborted. STOP -- take no actions,
=== 0/1 blocks reproduce byte-for-byte ===
```

That is **the author's own claimed catch, reproduced** — a one-word paraphrase inside a pasted code
receipt, caught. A second seed (a one-digit line-number change, block 13: `6331`→`6332`) was also caught.
A third seed mis-targeted a block that pastes source without line numbers and failed to apply — my error
in choosing the block, not a harness failure.

Worth recording for the campaign: **my own harness had two bugs that made it under-report on the first
run**, and both would have produced false findings against the spec:

1. `subprocess.run(["bash", …])` resolved to **WSL** bash, which mangles a linked worktree's `.git`
   pointer (`fatal: not a git repository: /mnt/c/…/C:/proga/…`) and expands `~` to `/home/techn`. It must
   be `C:\Program Files\Git\bin\bash.exe` explicitly.
2. Echoing the `$ cmd` prompt line between commands **clobbers `$?`**, so every `$ echo "exit $?"` receipt
   reported `exit 0` instead of `exit 1`. Fix: `__rc=$?; printf …; ( exit $__rc )`.

Before those fixes it reported 42/49 and would have accused four correct `[UNBUILT]` no-match receipts of
being wrong. **A receipt harness needs its own seed test before its output is trusted** — the same lesson
the technique exists to teach, applied to itself.

---

## RA-3. Does the restructured §4 still name every touchpoint?

Independently re-derived. Every touchpoint from my wave-1 fix list is present and receipted — §4.2 (four
sid equalities), §4.4 (`_roster_live_sids`, `native_epoch_suspicious`), §4.5 (three rotation writers),
§4.6 (`_render_successor_task`), §4.7 (four kind-lists), §4.8 (`skills/`), §4.13(a) (abort-flag store),
§4.13(b) (exit-code funnel), §4.13(c) (reserved names), §4.13(f) (`INCARNATION.tmp`).

One anchor was lost.

### R1 — MODERATE. The restructure dropped `_require_claim_holder`'s call-site receipts

v1 §3.2 carried two receipts establishing which verbs are claim-gated:

```
# v1, at ccbbc02 -- both DROPPED from v2, neither replaced
$ grep -n "_require_claim_holder" bin/fleet.py
$ grep -n "_require_claim_holder(getattr" -B 6 bin/fleet.py | grep -E "def cmd_|_require_claim_holder\(getattr"
```

v2 contains neither, and no receipt anywhere carries the call-site line numbers:

```
# at ccbbc02, over all 1814 lines of the re-draft
$ grep -n '7201\|7213\|7287\|7391\|7439' docs/specs/claim-nonce.md
$ echo "exit $?"
exit 1
```

The mapping those receipts carried is still true and still load-bearing:

```
# at ccbbc02
$ grep -n "_require_claim_holder" bin/fleet.py
6966:    _require_claim_holder) -- spec §4: append-only, single-writer."""
7177:def _require_claim_holder(sid_override=None):
7201:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # cmd_sup_checkpoint
7213:        claim, _ = _require_claim_holder(getattr(args, "sid", None))        # cmd_sup_heartbeat
7287:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # cmd_sup_handoff_begin
7391:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # cmd_sup_handoff_complete
7439:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # cmd_sup_handoff_abort
```

**Why this is the one finding a builder would feel.** §5.3 rewrites this exact function — new parameter
(`nonce=`), new three-branch validation, and a mint/acknowledge/promote step that must commit inside the
same `fleet_lock` section. §5.2's schema table names it as the reader of `nonce_hash`,
`pending_nonce_hash` and `state`. Every one of the five call sites must pass the presented value and
handle the new refusal — and §5.3 states a **per-call-site rule** (*"`sup-handoff-begin` does not mint"*,
about the site at `7287`) for a site the document never receipts.

§4.12's `grep -n "^def cmd_sup_"` is not a substitute: it lists all **seven** `cmd_sup_*` definitions and
their subprocess seams, and says nothing about which five call `_require_claim_holder` — `sup-boot` and
`sup-status` do not, and `sup-boot` is precisely the verb §6.1 rewrites by a different route. A builder
working from §4 literally must re-derive the mapping by hand, which is the one thing §4 exists to prevent.

**Fix:** restore both receipts, in §4.2 or a new §4.x beside the validation surface, and annotate each
call site with its enclosing verb.

---

## RA-4. Fix-list disposition — 24/24 FIXED

Verified against the code, not against the claim. `FIXED` here means I re-ran the receipt and checked the
prose it now supports.

| Item | Disposition | Evidence I ran |
|---|---|---|
| **S1** quote-sensitive sid grep | **FIXED** | §4.2 is titled *"quote-agnostic, four sites not two"*; block 6 reproduces 4 lines; `7248` is classified **display/view** and §5.8 carries the consequence |
| **S2** `_render_successor_task` | **FIXED** | §4.6 + block 19 (`sed -n '7257,7274p'`) reproduces; §8 table row assigns it to this slice |
| **S3** `skills/fleet/` is the operator contract | **FIXED** | §4.8 blocks 27+28 reproduce; the prose now says the `bin/hooks/` receipt *"supports a **code** conclusion only"*; §8 rows for both files |
| **S4** verb partition | **FIXED** | §7's corrected 4-class table, receipted from `SPEC.md:172/175` + `terminal-surface.md:51`; `release` classified mutating, `attach` as refuses-under-native |
| **S5** misattributed "Accepted cost" | **FIXED** | `grep -n "adjudication already wants\|humans talk to the interface tier\|incident, not a convenience"` → **`exit 1`**, deleted outright along with the gate decision it supported; §3 now states three-tier's full status verbatim |
| **S6** hash published by a view | **FIXED, better than asked** | §5.8 is a new **binding build rule** for a `cmd_sup_status` projection, covers `"handshake": hs` as well as `"incarnation": claim`, and T15 asserts the **hash** strings absent — the spec notes v1's own test would have passed on a leaky build |
| **S7** `INCARNATION.tmp` | **FIXED (documented; fix correctly filed elsewhere)** | §4.13(f) block 44 reproduces; §13 names it a **prerequisite**; §8 has a `.gitignore` row marked *not this slice* |
| **S8** abort-flag store / 5th sid equality | **FIXED** | §4.13(a), blocks 37+38 reproduce; explicitly corrects v1's *"cited only the HANDSHAKE arm"* |
| **S9** `_roster_live_sids` | **FIXED** | §4.4 block 10 reproduces; the predicate is now load-bearing in §6.1's dispute |
| **S10** exit-code seam | **FIXED** | §4.13(b) blocks 39+40 reproduce; §11 requires exception subclass + `main()` branch + `SKILL.md:37` amendment; §8 lists all three; §13 files the contract mismatch |
| **S11** test seams | **FIXED** | §4.12 block 35; §10 opens *"Seams this plan requires that do not exist yet — named rather than presumed, because v1 asserted…"*. My T3 sub-point is resolved honestly: no subprocess seam is needed **because §3 drops body-fencing** |
| **S12** conftest strips the env var | **FIXED** | §4.12 block 36 (`conftest.py` autouse `delenv`) reproduces; §10 budgets the env-control seam; and §6.5 removes the env channel entirely, which moots the fallback |
| **S13** third `retired_sids` writer | **FIXED** | §4.5 titled *"three writers, not two"*; block 16 reproduces `3432/3860/6348` |
| **S14** non-probative `RESERVED` receipt | **FIXED** | §4.13(c) block 41 (`grep -rni`) reproduces; conclusion re-based on a receipt that supports it |
| **S15** four kind-lists | **FIXED** | §4.7 *"four lists, not three"* + block 22 (`SKILL.md:38`); no "three lists" remains |
| **S16** `native_epoch_suspicious` mirror | **FIXED** | §4.4 block 12 (`sed -n '1557,1563p'`) reproduces |
| **S17** stale `-break.md` ranges | **FIXED** | `grep -n ":193-195\|:134-136"` → **`exit 1`** |
| **S18** *observe*/*reproduce* misquote | **FIXED** | `grep -n "cannot observe the dead-daemon\|lessons.md:619"` → **`exit 1`**; §6.6 rebuilt from the code receipt |
| **S19** journal-authorization inconsistency | **FIXED in substance** | `grep -n "cannot journal"` → **`exit 1`**; deleting `--force` (item 6) dissolved the contradiction. *But §14 mis-locates the fix — see R5* |
| **S20** `autoclean` gate inert | **FIXED** | §7(b) uses it as an argument against the gate, citing `autoclean.md:38` |
| **S21** §6-table omissions + G10 mislabel | **FIXED** | §8 has an explicit **"Label correction"** paragraph distinguishing SPEC §16's *tombstone obligation* from the `G10` label, plus a §12-journal row |
| **S22** unreceipted `ok=True` | **FIXED** | §4.8: *"the receipt for the current behavior is the function body at 7533-7539, not the two greps above"* |
| **S23** incomplete provenance / silent decline | **FIXED, better than asked** | §6.6 declines break-lens MUST-fix 4 **explicitly with its sequencing** (`:17`, sequencing item 1) and rewrites the provenance note to *"non-overlapping claims"*, quoting native-substrate's own *"That ambiguity is exactly what the epoch-freeze exists for"* |
| **S24** README scope | **FIXED** | §8 row records the three extra index repairs |

**24 FIXED · 0 NOT-FIXED · 0 REGRESSED · 0 SPURIOUS-FIX.**

I looked specifically for a `SPURIOUS-FIX` — a change that repairs something not broken, or breaks
something to satisfy a finding — and found none. The two candidates I tested both cleared: §4.2's
replacement grep is strictly wider than v1's (4 ⊇ 2 sites, nothing lost), and §4.13(c)'s replacement grep
supports the same conclusion on better evidence.

Three fixes exceeded the finding. §5.8 (S6) turned a gap into a binding rule with a test that asserts the
right string. And §9 caught a defect **I did not find**: v1's legacy predicate (`nonce_hash` absent) would
have classified a *released* claim as legacy, fallen back to sid equality and upgraded it in place —
resurrecting a released claim. The corrected predicate is *legacy ⇔ `nonce_hash` absent **and** `state`
absent*. That is the author auditing its own §6.3 against its own §9, and it is what this gate is for.

---

## RA-5. New-material sweep — every assertion in the new sections

New in v2: §2 (threat model / trust boundary), §5.3 (two-generation lifecycle), §5.4 (concurrency and
failure), §5.5 (transcript), §5.7–§5.9, §6.1's disputed clause, §7's three options.

**Receipted and verified:**

- **§2.3** — *"the obvious candidate — prompt a human — is already refuted in shipped code"*, block 2
  (`sed -n '2049,2054p'`): the `_confirm_destructive` docstring, *"There is deliberately NO interactive
  prompt… An agent must pass --yes; there is nothing to prompt."* Reproduces; supports the claim exactly.
- **§5.3** — *"`sup-handoff-begin`'s dispatch runs outside the lock by F4 doctrine (@7312-7367)"*. Verified
  by hand: `with fleet_lock():` opens at `7286` and closes before `7312`; `roster_fetch`/`exe`/dispatch/
  polling run `7312-7367`, outside. **Correct.**
- **§5.6 item 3** — `_doctor_check_supervisor_claim` *"hard-codes `ok=True` on both returns today
  (@7533-7539)"*. Verified by reading the function. **Correct.**
- **§5.8** — *"the human line at `7248`"* publishes the holder's raw sid. `sed -n '7248p'` confirms.
- **§5.5** — the `~/.claude/projects` receipt, plus an honest `[MANAGER-VERIFICATION REQUIRED]` that a
  stdout line lands verbatim in the `.jsonl`, with the correct note that **nothing in the guarantees
  depends on the answer**. Appropriate; I inherit the same blindness and did not read transcript contents.

**The disputed §6.1 clause — all three of its receipts reproduce.** (Whether the dispute is *right* is the
break lens's call; whether it is *factually founded* is mine.)

1. `_roster_live_sids` @6986-6999 — *"counts any entry carrying `status` or `pid`"*. Re-verified:
   `and e.get("sessionId") and ("status" in e or "pid" in e)`. ✔
2. `supervisor_claim_decision` @7014-7042 — *"hits `holder_sid in live_sids → refuse` before every later
   branch, and has no caller parameter"*. Re-verified: the refusal is the second branch, immediately after
   `claim is None`, ahead of the heartbeat parse. ✔
3. `knowledge/lessons.md:627` — *"the observed verdict was `refuse`/freeze… recovery was `sup-heartbeat`"*.
   Re-verified verbatim: *"could not re-boot its own claim (VERDICT refuse/freeze), only `sup-heartbeat`
   (which doesn't gate on staleness) recovered it."* ✔

The inference is also sound on the code: a roster-gone holder with a stale heartbeat reaches
`age > stale_seconds ⇒ seize`, not `refuse`. The record says `refuse`. So the holder **was** in
`live_sids`, and the strict *"resume only when roster-gone"* clause cannot fire on incident 2's shape.
**The dispute's factual base holds.**

### R3 — LOW. One unreceipted historical claim

§5.4(b), lines 1075-1076:

> the shape of this project's own 9th live catch, where a stale `daemon.lock` wedged every dispatch for
> **~16 h** while **`fleet doctor` read all-PASS**.

No source is cited. The core of it is supported:

```
# at ccbbc02
$ sed -n '83p' docs/PLAN-PROGRESS.md
| M-E | vendor-bump gate: claude 2.1.214->2.1.216 pin re-run | done | RED at test_1 -> root-caused to a
STALE ~/.claude/daemon.lock naming a REUSED pid (15740 -> WacomHost, StartTime unreadable) wedging every
`--bg` dispatch machine-wide; ... rm of the lock restored dispatch; pin 6/6 GREEN on 2.1.216,
`record_pin_pass` stamped, doctor 21 PASS / 0 FAIL. 9th live catch. | 2026-07-21 |
```

But the two specifics are not:

```
$ grep -rn "16 h\|16h\|~16" knowledge/ docs/PLAN-PROGRESS.md supervisor/JOURNAL.md
$ echo "exit $?"
exit 1
```

and the ledger's `doctor 21 PASS / 0 FAIL` is the **post-fix** reading — it sits in the same clause as
`rm of the lock restored dispatch` and `pin 6/6 GREEN`, not during the wedge. Neither "~16 h" nor
"`fleet doctor` read all-PASS *while wedged*" is recorded anywhere in the repo.

Not load-bearing — §5.4(b)'s argument stands without the anecdote — but this is a document that holds
itself to receipting every factual assertion, and this is a factual assertion about the project's own
history with no receipt. **Fix:** cite `docs/PLAN-PROGRESS.md:83`; source or drop the two specifics.

---

## RA-6. Discipline re-checks — clean

**`[UNBUILT]`.** `grep -n "UNBUILT\|unbuilt\|PRESCRIPTIVE\|not shipped\|not yet shipped"` → six hits, all
in §4.13(c) and §4.14. No lowercase `unbuilt`, no `PRESCRIPTIVE`, no `not shipped`. All four §4.14 tags
re-verified against their no-match receipts (blocks 41, 45 — reproduce). The reserved-name tag is now
carried by a receipt that actually supports it (S14). **No false tag; no untagged prescriptive prose** —
§§5–12 are openly prescriptive in a `drafting` document, which is the correct register.

**Cross-spec.** §8's table checked row by row against the cited targets; every claim I sampled holds,
including the two v1 got wrong (the SPEC §12 journal sentence, and the G10-vs-tombstone-obligation label).
`docs/specs/three-tier-command.md` is quoted with its **full** status — `PROPOSAL — RESTRUCTURE REQUIRED
(dual-lens design gate, 2026-07-17)` — at §3 and §8, which was my wave-1 ask. `native-substrate.md`'s
`[PENDING OPERATOR RATIFICATION]` rows are declared unchanged and are untouched by the commit.

**Promotion.** `Status: drafting` at line 3, with *"The author of a spec may never promote it… Nothing
here is approved, and nothing here changes the status of any other document."* Nothing promoted, nothing
ratified, no `[PENDING OPERATOR RATIFICATION]` row altered.

### R4 — LOW. Two mis-pointing cross-references

```
$ grep -n "§4.13(d)" docs/specs/claim-nonce.md
287:| 7190 | **display** — 7187's refusal message | §5.3 replaces the message wholesale (new exit code, §4.13(d)) |
588:§4.13(d).
1220:  once and never deleted (§4.13(d)). It must be **unlinked by ...
```

`§4.13(d)` is *"The handoff task file is written once and never deleted"* (line 915). The exit-code
contract is **`§4.13(b)`** (line 873). Lines 287 and 588 both point at (d) while discussing the exit code;
line 1220 is correct. A builder chasing the exit-code contract lands on the handoff task file.

I swept all cross-references mechanically for this class — every `§N`/`§N.N` reference resolves to a real
heading (the only unmatched ones, `§16`/`§16.6-8`, are explicitly `docs/SPEC.md`-qualified at lines 17-18
and 1570), and every sub-letter target `(a)`–`(f)` exists. These two are the only mis-pointers.

### R5 — LOW. §14 mis-locates its own S19 disposition

§14, lines 1797-1799, claims S19 was folded in at **§5.6**:

> S19 (§5.6 states the code fact — the append function enforces only the kind list, the claim rule is a
> call-site convention, and this spec adds no call site that skips it)

```
$ grep -n "call-site convention\|enforces only the kind list" docs/specs/claim-nonce.md
1798:function enforces only the kind list, the claim rule is a call-site convention, and this spec adds no
```

That sentence exists **only inside §14's own table**. §5.6 (lines 1135-1160) contains no mention of the
journal, the kind list, or a call-site convention. S19 **is** genuinely fixed — the contradiction was
dissolved by deleting `sup-release --force`, and `grep -n "cannot journal"` returns `exit 1` — but a
disposition table that points a reviewer at a section which does not contain the stated reasoning is the
same class of defect as a receipt that does not support its sentence.

---

## RA-7. Zero-collateral proof — run by me, widened

```
$ git diff --stat 238b7ad 091d5fa            # WHOLE TREE, not just the named paths
 docs/README.md            |    2 +-
 docs/SPEC.md              |    2 +-
 docs/specs/claim-nonce.md | 1814 +++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 1816 insertions(+), 2 deletions(-)
```

Three files, all documentation. **No change to `bin/`, `tests/`, `supervisor/`, `skills/`, `commands/`,
`knowledge/`, `.gitignore`, `docs/specs/three-tier-command.md`, `docs/specs/native-substrate.md`, or
`docs/superpowers/`** — and the two one-line doc edits are the v1 ones, carried forward unchanged.
`Status:` reads `drafting`. **Collateral: 0.**

---

## RE-AUDIT fix list

**MODERATE**

- **R1** — the restructure dropped both of v1's `_require_claim_holder` call-site receipts and replaced
  neither, while §5.3 rewrites that function's signature and validation contract and states a
  per-call-site rule about `7287`. Restore them, annotated with enclosing verbs.
- **R2** — the verification harness does not exist in the worktree and is not documented in the spec. Its
  four claimed catches are unverifiable and the technique cannot be adopted from it. Commit the script (it
  is a dev tool, not spec content) or drop the claim. If it is committed it needs its own seed test — mine
  had two bugs that produced four false findings before I seeded it.

**LOW**

- **R3** — §5.4(b)'s "~16 h" and "while `fleet doctor` read all-PASS" have no source in the repo; the core
  `daemon.lock` claim is supported by `docs/PLAN-PROGRESS.md:83`. Cite it; source or drop the specifics.
- **R4** — lines 287 and 588 cite `§4.13(d)` for the exit-code contract, which is `§4.13(b)`.
- **R5** — §14's S19 row cites §5.6 for reasoning that appears only in §14.

**Unchanged and still open:** O4 remains `[MANAGER-VERIFICATION REQUIRED]`. I am a `--bg` worker and
inherit the same blindness as the author and the break lens. §12's recommendation — fold it into the
parked G9 standalone probe — is sound on the evidence available to me.

**VERDICT: `fix-list(R1–R5)`.** 49/49 receipts sound, 24/24 fix-list items fixed against the code, zero
collateral, `Status: drafting` intact, nothing promoted. One dropped anchor, one absent tool, three
citation nits. This is a materially more reliable document than the one I audited yesterday.

---

## RA-8. ADDENDUM — second-pass sweep (R6–R12)

A wider independent sweep landed after the section above was committed. Everything below was
**re-executed by me** before it was written down; nothing here is taken on a subagent's word. It does
not change RA-1 (receipts), RA-4 (24/24 fixed), or RA-7 (zero collateral) — it lengthens the fix list.

**The pattern R1 belongs to is bigger than one anchor.** R6 is the same failure mode: the restructure
carried a *forward reference* across while leaving the referenced text behind. Two of these in one
re-draft is a structural symptom, not two typos.

### R6 — MODERATE. §9 depends on "§5.3 step 4", which does not exist

§9's first paragraph, the rule that decides how a **shipped** five-key INCARNATION is accepted at all:

> **An existing five-key INCARNATION.** It has no `nonce_hash`. **§5.3 step 4's legacy fallback** honors
> it under today's sid equality once, then upgrades it in place…

§5.3's Validation list has exactly three steps:

```
$ sed -n '1033,1039p' docs/specs/claim-nonce.md
**Validation** — `_require_claim_holder(nonce=...)`, under `fleet_lock`:

1. presented == live ⇒ **valid**. Nothing is promoted.
2. presented == pending ⇒ **valid, and this is the acknowledgment**: `nonce_hash ← pending_nonce_hash`,
   `nonce_seq ← N+1`, `pending_nonce_hash`/`pending_at` cleared. The caller has proven it received
   the value; only then does the old generation die.
3. otherwise ⇒ **refuse** (§5.6), exit code per §4.13(b).
```

There is no step 4, and the word *legacy* appears nowhere in §5.3. v1 carried this rule as its §4.2
step 4; the restructure rewrote §5.3 around the two-generation protocol and **dropped the legacy branch
while §9 kept pointing at it.**

This costs more than R1, because §9's *next* paragraph amends the missing rule:

> **The legacy predicate must exclude a released claim.** … The predicate is therefore:
> **legacy ⇔ `nonce_hash` absent and `state` absent.**

That correction is genuinely good — I praised it in RA-4 and I stand by that — but it is an amendment to
a rule the document never states. A builder gets the exception without the rule, for the one code path
that every existing installation hits on first contact.

**This qualifies my RA-4 note on §9:** the released-claim catch is real and self-found; the base rule it
corrects is missing.

**Fix:** restore the legacy branch as an explicit step in §5.3's Validation list, then let §9 amend it.

### R7 — MODERATE. The kind-lists are **five**, not four

§4.7 corrected v1's "three" to "four" (my S15). It is five. The fifth is the **shipped, git-tracked
journal header**:

```
# at ccbbc02
$ sed -n '6p' supervisor/JOURNAL.md
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.
```

and it is never regenerated, because the seed is written only when the file is absent:

```
# at ccbbc02
$ sed -n '6969,6971p' bin/fleet.py
    path = supervisor_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
```

So amending `_SUPERVISOR_JOURNAL_SEED` @6835 fixes only *future* journals. `supervisor/JOURNAL.md`
exists, is git-tracked, and will still advertise seven kinds after `RELEASED` ships (§6.3). Both §4.7
and §4.14 say "four".

### R8 — MODERATE. `supervisor/HANDSHAKE.tmp` is equally un-gitignored, and the filed defect is narrower than the leak

```
# at ccbbc02
$ git check-ignore -v supervisor/HANDSHAKE.tmp
$ echo "exit $?"
exit 1
```

Same mechanism as `INCARNATION.tmp`: `write_handshake` @6911 → `_write_json_atomic` @6879-6885 →
`path.name + ".tmp"` in the git-tracked `supervisor/` directory. And §6.4 puts **`handoff_token_hash`
and the successor's `nonce_hash`** into HANDSHAKE, so it is not a lesser target.

The spec is internally inconsistent here rather than simply wrong: **§8's `.gitignore` row correctly says
`supervisor/*.tmp`**, but §4.13(f)'s receipt and §13's filed defect both name only `INCARNATION.tmp`.
Since §13 is what a separate slice will be handed, the narrow version is the one that ships.

### R9 — MODERATE. §5.8's redaction rule has no jurisdiction over the loudest publisher

§5.8 is binding and well-built — but it is written entirely against `cmd_sup_status`, and T15 tests only
`sup-status`. `cmd_sup_boot` publishes claim identity to stdout on the same run:

```
# at ccbbc02
$ sed -n '7085p;7169,7174p' bin/fleet.py
            out.append(f"## {e['ts']} {e['kind']} inc={e['inc']} sid={e['sid']}")
    lines = [bundle, "", f"EPOCH: {'ok' if epoch_ok else 'FAIL'} -- {epoch_reason}"]
    if inc_line:
        lines.append(f"INCARNATION: {inc_line}")
    lines.append(f"VERDICT: {verdict} -- {reason}")
    _write_text_tolerating_console_encoding("\n".join(lines) + "\n")
```

`_render_boot_bundle` emits the journal tail (headers carry `inc=` and `sid=`) plus an `INCARNATION:`
line — and §11 adds **`NONCE: <value>`** to that same stream. `7171` appears as a raw hit inside §4.1's
second grep and is never analysed anywhere. A redaction rule scoped to one view, plus a test scoped to
the same view, leaves the verb that actually prints the secret ungoverned.

Not a leak of the *stored* material — the boot bundle prints an incarnation id, not a hash — but §5.8 is
the section that exists to enumerate publishers, and it enumerates one of two.

### R10 — MODERATE. §5.7 asserts a human runbook entry that does not exist, untagged

§5.7 introduces its options table as *"all of which exist today"*, and its third row says the manual
`rm supervisor/INCARNATION` lever is *"documented for a human in `skills/fleet/supervisor.md` (§8)"*.

```
# at ccbbc02
$ grep -n "rm \|INCARNATION\|release" skills/fleet/supervisor.md
6:`supervisor/INCARNATION`.
```

One hit, and it is the file's *definition* of "body" (`Body = the session holding the claim, recorded in
supervisor/INCARNATION.`), not a lever. The runbook documents no manual release at all.

Two consequences. First, this is a **behavior-that-does-not-exist claim carrying no `[UNBUILT]` tag**,
under a header that positively asserts existence — the one such case in the document (RA-6 otherwise
clean). Second, it is load-bearing: §5.7's *"Binding constraint on the refusal message"* forbids naming
the lever agent-side **because** a human runbook is said to carry it. Today there is no far side to that
boundary. §8's own `supervisor.md` row lists the manual lever as a change *this slice makes* — so §5.7
and §8 disagree on tense, and §5.7 has the wrong one.

### R11 — MODERATE. §5.9 binds `fleet clean` to a sweep it has no seam for

§5.9: *"`state/supervisor-handoff-<inc>.md` … must be **unlinked by `sup-handoff-complete` and by
`sup-handoff-abort`**, best-effort, **and swept by `fleet clean`**."* The first half is buildable. The
second has no code path:

```
# at ccbbc02
$ sed -n '4188,4196p' bin/fleet.py
        ceiling_file_path(sid),
        outcome_path(name),
        outcome_path(sid),
        task_file_path(name),
    ]
    candidates += [outcome_path(s) for s in retired_sids]
    candidates += [ceiling_file_path(s) for s in retired_sids]
```

Every candidate in `_remove_worker_files` is keyed on a **worker name or sid**. A
`supervisor-handoff-<inc>.md` is keyed on an incarnation id and belongs to no worker record, so
`cmd_clean` never reaches it — and `cmd_autoclean`'s three tiers (archive TTL / husk removal / tombstone
expiry) are worker-scoped too. The file carries the **plaintext handoff token** (§6.4), which is exactly
the retention §5.9 exists to close.

The builder either drops the sweep silently or invents a new sweep site that §8's touched-contracts table
does not authorize. §5.9 should say which.

### R12 — LOW. Three citation/classification slips

**(a) §6.6 attaches the right substance to the wrong label.** It cites
*"(`THREE-TIER-ADJUDICATION-2026-07-17.md:17`, sequencing item 1)"*. `:17` is **binding restructure list
item 4**, not a sequencing item:

```
$ sed -n '17p' docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md | cut -c1-90
4. **Substrate re-pin FIRST** (MF4, D4): `md-contract`'s 2.1.212 transient-daemon findings
$ sed -n '31,33p' docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md
## Sequencing (binding for M-D)

1. `md-contract` lands (substrate re-pin, pins 6/6, G-rows amended `[PENDING OPERATOR RATIFICATION]`).
```

Both point at the same substrate re-pin, so the argument holds; the label is on the wrong line. Worth
fixing precisely because §6.6 is the paragraph that exists to correct a provenance error (my S23).

**(b) §13 item 3 misclassifies a spec-created change as a shipped defect.** It files *"The published
exit-code contract mismatch"* among *"Three shipped-code defects this gate surfaced."* There is no
mismatch at `ccbbc02` — the published contract and the code agree exactly:

```
$ sed -n '7166p' bin/fleet.py
        rc = {"claim": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]
$ sed -n '37p' skills/fleet/SKILL.md | grep -o "Exit [^.]*\."
Exit 0=hold/handshake-written, 2=refuse, 3=freeze.
```

`0/0/2/3` published, `0/0/2/3` implemented. The mismatch is **created by this spec** when it adds a
fourth code — which §8 and §11 already correctly assign to this slice. In fairness the misclassification
originates upstream, in `ME-NONCE-ADJUDICATION-2026-07-21.md`'s shipped-defect list (*"the docs say
0/2/3; the code has a 4 with no seam"* — the code has no 4); the spec propagated it rather than
introducing it. My own S10 did not make this claim, and §4.13(b)'s own text is accurate.

**(c) §4.1's heading overruns its grep.** The heading is *"Everything that reads or writes
`supervisor/INCARNATION`"*; the grep anchors on `def read_incarnation`, so no read **call site** appears:

```
# at ccbbc02
$ grep -n "read_incarnation()" bin/fleet.py
7137:            claim = read_incarnation()     # cmd_sup_boot, under fleet_lock
7181:    claim = read_incarnation()             # _require_claim_holder
7224:    claim = read_incarnation()             # cmd_sup_status (view)
7516:    claim = read_incarnation()             # supervisor_status_line (nag / doctor / SessionStart hook)
```

Each is separately amended by this spec — 7137 by §6.1, 7181 by §5.3, 7224 by §5.8 — and **7516 is
assigned by nobody.** That one is `supervisor_status_line`, the only supervisor state a manager session
sees automatically at SessionStart (`bin/hooks/sessionstart_fleet.py:126`). §5.6 routes divergence to
`fleet doctor`, a command nobody runs during an incident; the surface that fires every session is left
alone. Same family as R9: the enumeration of *publishers* is short.

### Not findings

- **`tests/test_supervisor.py` (828 lines, ~80 tests) is unreceipted and unaudited by §10**, which
  budgets new seams only. `:343` asserts `data["incarnation"]["incarnation_id"]` against `sup-status
  --json`, whose shape §5.8 changes; the builder should check it. Recorded as a build note, not a defect
  in the spec's factual base.
- **The three authority documents do not resolve from the spec's own tree** — `ME-NONCE-ADJUDICATION`
  lives in `C:/proga/claude-fleet/docs/reviews/`, and the two lens reviews live on unmerged sibling
  worktree branches. That is the normal fleet review topology and the manager owns integration; the
  citations become resolvable on merge. Flagged so it is a deliberate choice rather than an oversight.
- **`_render_boot_bundle`'s journal tail and argparse's exit 2** (argparse uses rc 2 for a bad
  subcommand, colliding with the published `2=refuse`) are pre-existing shipped ambiguities this spec
  neither creates nor worsens.

---

## Revised RE-AUDIT fix list

**MODERATE**

- **R1** — dropped anchor: `_require_claim_holder`'s call-site receipts removed, not replaced.
- **R2** — the verification harness does not exist in the worktree and is undocumented.
- **R6** — dropped anchor: §9 depends on "§5.3 step 4", which does not exist; the legacy-acceptance rule
  is missing while its amendment is present.
- **R7** — the kind-lists are five, not four; the fifth is the shipped, never-regenerated
  `supervisor/JOURNAL.md:6`.
- **R8** — `supervisor/HANDSHAKE.tmp` is equally un-gitignored; §4.13(f)/§13 file only the narrow half.
- **R9** — §5.8's redaction rule and T15 cover `sup-status` only; `sup-boot` prints identity — and, per
  §11, the nonce — to stdout ungoverned.
- **R10** — §5.7 asserts a `skills/fleet/supervisor.md` entry that does not exist, untagged, under a
  header claiming existence; the claim is load-bearing for §5.7's own binding constraint.
- **R11** — §5.9 binds `fleet clean` to sweep a file `_remove_worker_files` cannot reach.

**LOW**

- **R3** — §5.4(b)'s "~16 h" / "doctor read all-PASS" unsourced.
- **R4** — lines 287, 588 cite `§4.13(d)` for the exit-code contract, which is `§4.13(b)`.
- **R5** — §14's S19 row cites §5.6 for reasoning that appears only in §14.
- **R12** — (a) §6.6 labels adjudication `:17` a sequencing item; (b) §13 item 3 files a spec-created
  change as a shipped defect (no mismatch exists at `ccbbc02`; error inherited from the adjudication);
  (c) §4.1's heading overruns its grep, hiding four read call sites, one of which — `7516`,
  `supervisor_status_line`, the SessionStart surface — is assigned to nobody.

**REVISED VERDICT: `fix-list(R1–R12)`.** Unchanged on everything measured: **49/49 receipts sound,
24/24 wave-1 items FIXED, 0 REGRESSED, 0 SPURIOUS-FIX, collateral 0, `Status: drafting`, nothing
promoted.** The document's factual base remains reliable — no receipt is wrong and no code claim is
confabulated. What the second pass found is that the *restructure* cost two anchors (R1, R6) and that
the enumeration of **publishers** and of **sweep/ignore sites** is short in four more places. Same class
as the wave-1 verdict, one layer deeper: this document's failures are omissions, not errors.

---
---

# FINAL GATE — `docs/specs/claim-nonce.md` @ `cecaed2` (v3, fix wave 2)

**Reviewer:** `me-nonce-spec` (fleet worker, `--bg`), third pass, 2026-07-21.
**Scope (narrow, as briefed):** receipts, the harness, and my R-items. N1–N7 and the mechanism belong
to the break lens and are not touched here.

**VERDICT: `fix-list(F1, F2)`.** R1–R12 are **12/12 FIXED**, several better than filed, and the author
self-reported and reverted a `SPURIOUS-FIX` I had not caught. The harness is real, stdlib-only,
read-only, covers every receipt in the document, and **passed three seeds I wrote myself** — including
the abridgement class.

Two findings, and **neither warrants a third authoring wave.** F1 is a two-line edit using a mechanism
the author already built. F2 is a campaign-level policy call that is the manager's, not the author's.
`ESCALATE beats a third` is respected: I am not asking for a re-draft.

The headline is that both findings are the same fact seen twice: **the harness catches this document's
one remaining defect, exits 1 on it, and the document shipped anyway.**

---

## FG-1. The receipts — 60/62 exact, 1 volatile-WARN, **1 FAIL**

The brief reported *"62 claimed, 62/62 reproducing, 1 volatile-WARN."* That is not what the shipped
tree does. Running the author's own harness, unmodified, on the committed document:

```
$ py -3.13 tools/verify_receipts.py --self-test docs/specs/claim-nonce.md
shell: C:\Program Files\Git\bin\bash.exe
root:  C:\proga\fleet-me-nonce
SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.
WARN  (volatile) line 1327: ls -ld ~/.claude/projects && find ~/.claude/projects -maxdepth 2 -name '*.jsonl' | wc -l
      output line 2
      EXPECTED: '747'
      ACTUAL:   '751'
FAIL  line 46: git rev-parse HEAD
      output line 1
      EXPECTED: '091d5faff903bf30b8024baa5168c17ec17de504'
      ACTUAL:   'cecaed2f0f866704ee18ab2fa4eeb8e99a9f0cb9'

60/62 receipts reproduce exactly (56 fenced blocks, 1 volatile-drift, 1 FAILED)

$ py -3.13 tools/verify_receipts.py docs/specs/claim-nonce.md >/dev/null 2>&1; echo "rc=$?"
rc=1
```

**Independently confirmed by my own extractor**, written in wave 2 and unrelated to the author's:

```
$ py -3.13 reaudit.py claim-nonce.md /c/proga/fleet-me-nonce
[DIFFERS   ] block  1  spec line 44  $ git rev-parse HEAD
      -091d5faff903bf30b8024baa5168c17ec17de504
      +cecaed2f0f866704ee18ab2fa4eeb8e99a9f0cb9
[DIFFERS   ] block 51  spec line 1324  $ ls -ld ~/.claude/projects && ...
      -747
      +751
=== 49/55 blocks reproduce byte-for-byte ===
```

(The other four deltas my extractor reports are its own known cosmetic artifact — blank-line separators
between consecutive commands inside one block — documented in RA-1. Two independent extractions, two
non-cosmetic deltas, same two.)

**The volatile one is legitimate and properly disclosed.** `# volatile:` marker at line 1326, the
command is `ls -ld ~/.claude/projects && find … | wc -l`, and the prose at 1331-1336 discloses the full
drift history (*"732 → 735 → 743 across this document's three waves"*) and names the load-bearing facts
as **existence** and **same-user readability**, neither of which drifts. My run read `751`. Genuinely
time-variant machine state, correctly marked, correctly demoted to WARN. **No finding.**

### F1 — MODERATE. The pin-proof receipt is stale in the shipped tree, for the second consecutive wave

Spec lines 44-47:

```
# at 091d5fa
$ git rev-parse HEAD
091d5faff903bf30b8024baa5168c17ec17de504
```

HEAD is `cecaed2`. The block asserts the *previous* commit.

This is not a new mistake — it is the **same** mistake, and the document says so itself at lines 57-58:

> *(This block itself was stale in v2 — it still asserted `ccbbc02` after the v2 commit moved HEAD.
> `tools/verify_receipts.py` caught it, which is the first thing that tool earned.)*

So the author hit this in v2, fixed the *instance* (`ccbbc02` → `091d5fa`), wrote a parenthetical about
it, and the instance went stale again the moment `cecaed2` was created. **The class was never fixed.**

It cannot be fixed by pasting a sha. `git rev-parse HEAD` inside the commit that contains it is
self-referential: the value is not knowable until after the write. Any wave that edits this file will
reproduce the defect.

**Severity is bounded and I want to be precise about it.** The *facts* the block exists to establish are
all true and I verified them myself, independently of the block:

```
# run by me at cecaed2
$ for r in 238b7ad ccbbc02 091d5fa cecaed2; do printf "%-9s %s\n" "$r" "$(git rev-parse $r:bin/fleet.py)"; done
238b7ad   562e2848aab6d85e25ba053ee5ef410917c4d4b1
ccbbc02   562e2848aab6d85e25ba053ee5ef410917c4d4b1
091d5fa   562e2848aab6d85e25ba053ee5ef410917c4d4b1
cecaed2   562e2848aab6d85e25ba053ee5ef410917c4d4b1
```

and the block's other two commands both reproduce (the `git diff --stat … -- bin/ tests/ supervisor/
skills/ commands/ .gitignore` is empty with `exit 0`, and the two hashes match). So this is a **stale
label on a true claim**, not a false claim about the code. Nothing downstream is invalidated.

But it is the *pin-proof block* — the one whose whole job is to establish that every other receipt in
the document is valid — and in the shipped tree it is red, in a document whose thesis is that a receipt
nobody re-ran is a claim.

**Fix (two lines, using a mechanism the author already built):** add `# volatile: HEAD is not knowable
inside the commit that asserts it` to the block, exactly as the transcript block is marked — or drop
`git rev-parse HEAD` entirely and keep the two commands that are not self-referential, which is
strictly better because they carry the whole argument.

---

## FG-2. The harness — real, sound, and seeded by me

`tools/verify_receipts.py`, 264 lines. Audited as a claim, not a virtue.

**Stdlib-only — confirmed.**
```
$ grep -n "^import\|^from" tools/verify_receipts.py
33:from __future__ import annotations
35:import argparse
36:import os
37:import pathlib
38:import shutil
39:import subprocess
40:import sys
```

**Read-only, writes nothing — confirmed.**
```
$ grep -n "open(\|write_text\|mkdir\|urllib\|requests\|socket\|shutil.copy\|os.remove\|unlink" tools/verify_receipts.py
$ echo "exit $?"
exit 1
```
No writer of any kind. It reads the markdown, shells out, compares in memory. The only I/O outside the
worktree is whatever the *receipts themselves* do — in this document, `git`, `grep`, `sed`, and one
read-only `ls`/`find` under `~/.claude/`. Nothing mutating.

**Coverage — it covers every receipt in this document, with zero dropped.** Verified by importing its
own parser and counting against the raw file:
```
$ py -3.13 -c "import verify_receipts as v; r,b = v.parse(open('docs/specs/claim-nonce.md').read()); ..."
parsed receipts: 62  fenced blocks: 56
$ lines: 70  exit-assertions: 8  => commands: 62
dropped (no expected, no exit): 0
```
70 `$` lines − 8 `$ echo "exit $?"` assertions = **62 commands, 62 parsed.**

**What it skips, enumerated as asked** — none of it active in this document, all of it latent:

| Skip | Mechanism | Active here? |
|---|---|---|
| Blocks with no `$ ` line | documented; quoted prose and journal entries | Yes, by design — correct |
| `$ echo "exit $?"` | consumed as an exit assertion on the previous command, not run as its own receipt | Yes, by design — correct |
| **stderr** | `run()` reads `proc.stdout` only (line 140); stderr is discarded, never compared | **No** — `grep -n '^\$ .*2>&1'` → `exit 1`, no receipt pastes stderr. Latent. |
| Receipts with **neither** expected output nor an exit assertion | dropped silently by `return [r for r in out if r.expected or r.exit_code is not None]` (line 127) | **No** — 0 dropped. Latent, and silent when it fires. |
| Language-tagged fences | fence detection is `raw.strip() == "```"` (line 84), so ```` ```python ```` is not a boundary | **No** — `grep -c '^```$'` = 112, `grep -n '^```[a-zA-Z]'` → none. Latent. |

One design note, not a defect: the tool executes arbitrary shell read out of a markdown file. That is
correct for its job and the job cannot be done otherwise, but it means the harness is only as safe as
the document it is pointed at.

### Seeded by me — PASS on all three, including the abridgement class

The brief is right that an author's own seed test is the weakest evidence, so I wrote three of my own
against a mutated **copy** in my job tmp (nothing written into the author's worktree). I deliberately
chose a *different* receipt from the one the author's `--self-test` picks.

```
SEED A — one-word paraphrase inside a pasted receipt
  "uuid-shaped names are reserved" -> "uuid-shaped names are RESTRICTED"
FAIL  line 1017: grep -rni "reserved" bin/ | head -4
      EXPECTED: '...uuid-shaped names are RESTRICTED "'
      ACTUAL:   '...uuid-shaped names are reserved "'                       CAUGHT

SEED B — the ABRIDGEMENT class: one output line deleted from a pasted receipt
  (deleted the 7213 line from the _require_claim_holder receipt)
FAIL  line 341: grep -n "_require_claim_holder" bin/fleet.py
      EXPECTED: '7287:        claim, caller = _require_claim_holder(...)'
      ACTUAL:   '7213:        claim, _ = _require_claim_holder(...)'        CAUGHT

SEED C — one-digit line-number change
  "6821:SUPERVISOR_CLAIM_STALE_SECONDS" -> "6822:..."
FAIL  line 1048: grep -n "SUPERVISOR_CLAIM_STALE_SECONDS *=" bin/fleet.py   CAUGHT
```

**Seed B is the one the brief asked about** — *"an abridged receipt it had copied from your own review
rather than executed."* An abridged paste is a deleted line, and the harness catches it. The author's
own `--self-test` also passes when I run it (it seeds the §2.3 `_confirm_destructive` receipt at line
219 and catches it).

**Harness seeded by me: PASS.**

### F2 — MODERATE. Caught is not the same as cannot-ship, and this document proves it

The brief asks me to *"confirm that class is now impossible to ship, not merely caught once."*
**It is not impossible to ship. It is reliably detected and not prevented.**

```
$ grep -rn "verify_receipts" CLAUDE.md CONTRIBUTING.md pytest.ini docs/SPEC.md tests/ .claude-plugin/
$ echo "exit $?"
exit 1
```

The harness is referenced nowhere outside its own docstring: no pytest test, no pre-commit hook, no CI
step, no CLAUDE.md rule, no CONTRIBUTING note. `pytest.ini` declares markers only and no `testpaths`,
and the file is not named `test_*.py`, so the suite never touches it.

The proof is not hypothetical — **it is F1.** The harness detects that defect, prints `FAIL`, and exits
`1`. The document shipped with it anyway. A tool that catches a defect the commit then carries is a tool
nobody ran at the moment that mattered.

**What would make the class impossible**, in ascending cost:

1. A `tests/test_receipts.py` that runs `verify_receipts.py` over `docs/specs/*.md` and asserts rc 0 —
   it is a `unit`-tier, no-`claude` test, which is exactly the tier `pytest.ini` describes.
2. A CLAUDE.md rule binding any spec that carries receipts to a green `--self-test` run before commit.
3. Both, which is what the repo already does for the doctrine it takes seriously (the
   `tests/test_terminal_surface.py` no-inline-exec lint is the precedent — a doctrine rule with a test
   behind it).

**This is the manager's call, not the author's**, which is why I am filing it as a finding against the
campaign rather than asking for a fourth draft of the spec. The author built the tool that was asked
for and built it well; nobody has yet decided it is binding.

---

## FG-3. Disposition — R1–R12, all FIXED

Verified against the code and the text, not against §14's claims.

| # | Disposition | What I ran |
|---|---|---|
| **R1** | **FIXED, better than filed** | §4.2 restores `grep -n "_require_claim_holder" bin/fleet.py` (reproduces) **and** adds a table mapping each of `7201/7213/7287/7391/7439` to its enclosing verb **and** to §5.3's per-verb mint rule — including the `7287` "does not mint" case I flagged as stated-but-unreceipted |
| **R2** | **FIXED, with the original claim corrected** | `tools/verify_receipts.py` exists, runs, stdlib-only, read-only, 62/62 coverage, seeded by me — FG-2. §14 additionally **retracts the overstatement**: of v2's four pre-commit defects the harness caught **one**, the other three were manual. Self-correction of exactly the kind this lens exists to force |
| **R3** | **FIXED** | `grep -n "16 h\|16h\|all-PASS"` → the unsourced specifics are gone; line 1257 now cites `docs/PLAN-PROGRESS.md:83` |
| **R4** | **FIXED** | lines 379 and 701 now read `§4.13(b)`; line 1493's `(d)` is the correct one (handoff task file) |
| **R5** | **FIXED** | §14 line 2224 states the S19 code fact inline with its own anchor instead of pointing at §5.6 |
| **R6** | **FIXED, better than filed** | §5.3's Validation list now has **five** rules; rule 4 *is* the legacy branch (*"legacy claim — `nonce_hash` absent **and** `state` absent (§9)"*), so §9 amends a rule the document states. The released-claim exclusion is folded into the rule itself rather than living only in §9 |
| **R7** | **FIXED** | "five lists of §4.7" at 1126 and 1632; §4.7 carries the receipt that the seed is written only when the file is absent, which is *why* the shipped `supervisor/JOURNAL.md:6` is the fifth |
| **R8** | **FIXED** | §4.13(f) retitled *"Neither `INCARNATION.tmp` nor `HANDSHAKE.tmp`"* and receipts both `git check-ignore` runs; §13 item 2 widened to `supervisor/*.tmp`; §8's row already said `*.tmp` and now says so explicitly |
| **R9** | **FIXED** | §5.8 lines 1459-1476 extend the redaction rule to `cmd_sup_boot`'s stdout with the `_render_boot_bundle` receipt; T15 covers both verbs (line 2078) |
| **R10** | **FIXED** | line 1416 tagged `[UNBUILT — owned by this slice]` with the exact receipt. I re-ran the proof: `grep -n "rm \|INCARNATION\|release\|remove" skills/fleet/supervisor.md` → **one hit, `6:`supervisor/INCARNATION`.`**, the definition of "body", not a lever. Tag is accurate and §5.7/§8 now agree on tense |
| **R11** | **FIXED** | §4.13(g) is a new receipt showing every `_remove_worker_files` candidate is worker/sid-keyed; §5.9 line 1496 explicitly says *"That clause is withdrawn: there is no seam for it"* and replaces it with a doctor NOTE that §8 authorizes |
| **R12** | **FIXED (all three)** | (a) §6.6 line 1744 now says *"binding restructure list item 4"* and line 1746 records the v2 mislabel; (b) §13's exit-code item withdrawn, line 2194 stating the published contract and the rc map agree *exactly* and naming the upstream provenance of the error; (c) §4.1 now enumerates all four `read_incarnation()` call sites (`7137/7181/7224/7516`) in a table that assigns each — `7516` included |

**R1–R12: 12 FIXED · 0 NOT-FIXED · 0 REGRESSED · 0 SPURIOUS-FIX from me.**

Worth recording separately: **the author found and reverted a `SPURIOUS-FIX` of its own** — §14 line
2242, *"§5.8's human-form redaction guards an f-string that never held a hash — **REVERTED**, §5.8
scoped to the dict-dumping paths; T15 likewise."* That is a fix being withdrawn because it repaired
nothing, self-reported. I did not catch it. It is the single best signal in this wave.

---

## FG-4. Discipline on changed text — clean

**`[UNBUILT]`.** Eight tags; `grep -n "unbuilt\|PRESCRIPTIVE\|not shipped\|not yet shipped"` → `exit 1`.
§4.14's no-match proofs all reproduce under both harnesses (blocks 50/51 in my extractor, all green in
the author's). **R10's new tag re-verified by me** — it is a one-match proof, not a no-match proof, and
that is the correct form for the claim being tagged (*"the runbook mentions the file once, at `:6`, as
the definition of 'body'"*); my independent grep returns exactly that one line.

**A new tag class appeared and it is a good one.** `[INFERENCE — NOT A RECEIPT]` at line 109, applied to
§1.2's *"the zombie appears to have run only `fleet send`"* — a claim I let pass in two prior waves
because it was framed as a receipt and I checked the quote rather than the inference. The break lens
caught it (N7). Worth adopting campaign-wide alongside `[UNBUILT]` and `[MANAGER-VERIFICATION
REQUIRED]`.

**Untagged prescriptive prose:** none found. §§5–13 are openly prescriptive in a `drafting` document.

**Cross-spec.** No new contradiction on changed text. §8's rows for `native-substrate.md` (*"unchanged,
including every `[PENDING OPERATOR RATIFICATION]` row"*) and `three-tier-command.md` (*"stays `PROPOSAL
— RESTRUCTURE REQUIRED`"*) hold; §3 line 250 keeps `2026-07-18-sdd-drift-control-design.md` at DRAFT.

**Promotion.** Nothing promoted, nothing ratified, no `[PENDING OPERATOR RATIFICATION]` row altered.

```
$ sed -n '3,5p' docs/specs/claim-nonce.md
**Status:** drafting (`me-nonce`, v3 fix wave 2026-07-21). **The author of a spec may never promote
it.** This document is input to a second dual-lens review; only the operator ratifies. Nothing here
is approved, and nothing here changes the status of any other document.
```

---

## FG-5. Collateral — 0, whole tree

```
$ git diff --name-only 238b7ad cecaed2
docs/README.md
docs/SPEC.md
docs/specs/claim-nonce.md
tools/verify_receipts.py
```

Four files. Three are the documentation this slice owns, unchanged in shape since v1. The fourth,
`tools/verify_receipts.py`, is **new non-docs code — and it is the artifact R2 asked for**, so it is
authorized output rather than collateral. I checked it cannot disturb the suite: `pytest.ini` declares
markers only, sets no `testpaths`, and the file is not named `test_*.py`, so nothing collects it.

**Untouched: `bin/`, `tests/`, `supervisor/`, `skills/`, `commands/`, `knowledge/`, `.gitignore`,
`docs/specs/three-tier-command.md`, `docs/specs/native-substrate.md`, `docs/superpowers/`.**
`bin/fleet.py` is still blob `562e284`, identical at all four commits. **Collateral: 0.**

---

## FINAL GATE fix list

- **F1 (MODERATE)** — the pin-proof block asserts `091d5fa`; HEAD is `cecaed2`. The author's own harness
  reports it `FAIL` and exits 1 on the shipped tree. Second consecutive wave for the same block, because
  the instance was fixed twice and the class never was: `git rev-parse HEAD` is self-referential and
  cannot be pasted correctly. **Fix:** mark the block `# volatile`, or drop that one command and keep
  the two that carry the argument. Two lines, no re-draft.
- **F2 (MODERATE, manager-owned)** — `tools/verify_receipts.py` is bound to nothing: no test, no hook,
  no CI, no CLAUDE.md rule. The class it exists to prevent is **detected, not prevented**, and F1 is the
  standing proof. **Fix:** a `unit`-tier `tests/test_receipts.py` asserting rc 0 over `docs/specs/*.md`,
  and/or a CLAUDE.md rule — following the `tests/test_terminal_surface.py` precedent of a doctrine rule
  with a test behind it. **This is a campaign decision, not a spec edit.**
- **F3 (note, not a finding)** — three latent harness gaps, none active in this document: stderr is
  never captured; a receipt with neither expected output nor an exit assertion is dropped silently; a
  language-tagged fence would not be recognised as a block boundary. Worth a comment in the tool before
  it is pointed at a second document.

**Still open, unchanged:** O4 remains `[MANAGER-VERIFICATION REQUIRED]`. Every reviewer of this document
and its author have been `--bg` sessions and share the same blindness to the dead-daemon path.

**On `ESCALATE beats a third`:** I am not asking for one. R1–R12 are closed, N-items are the break
lens's to close, and the two findings here are a two-line edit and a policy decision. If the manager
wants a single closeout commit that marks the pin block `# volatile` and adds the receipts test, that
finishes it; if not, F1 is a stale label on a true claim and F2 is a known, documented gap. Neither
blocks the operator's ratification decision.

**VERDICT: `fix-list(F1, F2)`.** 60/62 receipts exact + 1 disclosed volatile + 1 stale self-referential
label · harness verified and seeded by me, PASS · R1–R12 12/12 FIXED · collateral 0 ·
`Status: drafting` · nothing promoted. The document's factual base is sound; what it lacks is a gate
that makes the tool it now owns actually bind.
