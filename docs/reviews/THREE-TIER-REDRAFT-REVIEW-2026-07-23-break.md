# Three-tier re-draft — BREAK-lens design review

**Lens:** break (lens 1 of 2; spec lens independent). **Date:** 2026-07-23.
**Document under review:** `docs/specs/three-tier-command.md`, status `drafting`.
**Mandate:** the fresh dual-lens gate the 2026-07-17 adjudication requires before any build
(`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md`, items 4–10).

## Vantage

- Worktree `C:\proga\fleet-mf-tt-break`, branch `mf/tt-break`, **HEAD `0846d1c`**. `FLEET_HOME` unset.
- The spec's fenced receipts are pinned `# at 235421e`. **`bin/fleet.py`, `bin/hooks/stop_outcome.py`
  and `bin/fleet_statusline.py` are byte-identical between `235421e` and `0846d1c`** — the whole
  `235421e..0846d1c` delta is three files (`three-tier-command.md`, `lessons.md`,
  `tests/test_receipts.py` −1 line). So every line-anchored receipt is equally valid at the pin and at
  HEAD, and my hand receipts (run against the working tree) are directly comparable.

## Receipts — clean

- `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md` →
  **32/32 reproduce, self-test PASS** (0 unclassified, 0 volatile, 0 FAILED).
- **13 receipts hand-executed** at HEAD (§3.2 ×2, §4.3, §5.2, §6.1, §6.2, §7.1, §7.2 ×2, §8, §10.1,
  §11.2 ×2) — all reproduce exactly. `tests/test_receipts.py` → **13/13 pass**.
- **Out-of-write-set edit (`tests/test_receipts.py`) is correct and minimal.** The diff removes exactly
  one line — the `"three-tier-command.md": "PROPOSAL … carries no receipts."` UNENFORCED entry. This is
  *mandatory*, not optional: the file's own `stale` gate (`UNENFORCED` ∩ enforced ⇒ fail) would trip
  now that the spec carries pinned receipts. All other `UNENFORCED` entries (`native-substrate.md`, the
  SUPERSEDED one) are intact; nothing else is un/enforced.
- **Substrate honesty:** in this worktree `docs/specs/native-substrate.md` carries **no `WITHHELD`
  string and no 2026-07-23 ratification** — every 2.1.212/2.1.216 row is still
  `[PENDING OPERATOR RATIFICATION]`. §4.1 describes them as PENDING and "this spec changes no verdict
  there" — accurate to the tree. (Dependency note under B-dep below.)
- **Requirement vs. spec:** `knowledge/lessons.md#2026-07-23-three-tier-inputs` + its addendum match
  §1/§3/§11 (swap band 150–200k, tier-based/provider-agnostic, Opus/Sonnet-only, event-driven v1). No
  recorded-vs-specced divergence.
- **§10.3 precedent verified true:** `validate_name` already carries the F6 `_SID_SHAPE_RE` uuid-shape
  refusal, so the `RESERVED` claim ("same technique, one more shape") is honest.

One receipt-vs-claim gap found — see **B2**. Otherwise prose tracks the receipts.

---

## Findings

Severity: CRITICAL / MAJOR / MINOR / nit. Every finding carries an executed receipt; VANTAGE is the
one stated above unless noted.

### B1 — CRITICAL — §7.2's archive/husk exemption is keyed on a name the running supervisor stops having after the first handoff

§7.2 resolves MF3's "autoclean rm's the supervisor" **by construction**:

> the build adds a first gate to `_archive_eligible` **and** to `_sweep_husks` (@5568):
> `name == SUPERVISOR_BODY_NAME ⇒ (False, "supervisor record is protected by construction")`.

The exemption is a single-name equality. But the supervisor body the operator's model
respawns/hands-off "constantly" (§1) does **not** keep the name `supervisor`. The shipped handoff
dispatches the successor under a pipe-delimited name:

```
$ sed -n '8520,8527p' bin/fleet.py          # at 0846d1c (== 235421e for bin/fleet.py)
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict) and isinstance(e.get("sessionId"), str)}
    name = f"sup|{successor_inc}|successor"
    ...
    argv = [exe, "--bg", "-n", name, ...]
```

§11.3 makes the swap band drive **this** machinery ("Both use the shipped sup-handoff machinery"), and
nothing renames the successor to `supervisor` on `sup-handoff-complete` (the complete path @7391
transfers the INCARNATION claim only; registry records are independent). So after swap #1 — which
§11's 150–200k band makes routine, not exceptional — the live claim-holder runs under
`sup|<inc>|successor`, which `name == SUPERVISOR_BODY_NAME` does not match. The exemption protects
generation 0 and no successor. The archive TTL (24h) vs. the ≤23h autoclean cadence collision §7.2
opens with is then **live again against the actual running manager**, which is the campaign-death
outcome §7.2 exists to prevent, reappearing in steady state.

```
$ grep -c "SUPERVISOR_BODY_NAME" bin/fleet.py          # at 0846d1c
0                                                        # [UNBUILT] — design defined here, so fixable here
```

**Fix direction:** key the exemption on *holds the supervisor claim / is the current
`INCARNATION.incarnation_id` body*, not on a static registry name — the successor names are
pipe-delimited and live outside `validate_name`'s `[a-z0-9-]` keyspace, so a name-equality can never
cover both the `sup-spawn` body and its successors. This also forces a decision B9 raises (liveness).

### B2 — MAJOR — §11.2's occupancy formula drops `cache_creation_input_tokens`, and cites a continuity claim as if it were an occupancy claim

§11.2 specifies the swap-band measurement as:

> The supervisor reads **its own** transcript tail's `message.usage.cache_read_input_tokens +
> input_tokens` — the live context-occupancy figure

Anthropic per-turn usage splits the prompt three ways: `input_tokens` (uncached, un-created) **+**
`cache_creation_input_tokens` **+** `cache_read_input_tokens`. Context-window occupancy is the **sum
of all three**. The formula omits `cache_creation_input_tokens`, so on any turn that has just grown the
context (a large read, a fresh worker digest folded in — the supervisor's characteristic move) the
figure **understates occupancy by exactly the newly-created cache segment**. Against a 150–200k band, a
single 40–60k creation turn is decisive: the band-entry trigger fires late or is skipped.

The receipt §11.2 leans on makes the error visible — it is about **continuity, not occupancy**:

> native-substrate: *"session context (`cache_read_input_tokens`) provably continuous across beats"*

`cache_read_input_tokens` is the substrate's *continuity* signal (does the cached prefix persist across
a beat), not a summand of *occupancy*. §11.2 repurposes it as the occupancy base and then drops the one
term (`cache_creation`) that would make the sum correct. This is the one receipt-vs-claim gap in the
draft: the cited evidence supports continuity monitoring, not the occupancy arithmetic built on it.

**Fix:** occupancy = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`; and if the
belt-and-braces Stop-hook capture (§11.2 last bullet) ships, capture `cache_creation_input_tokens`
too, not only `cache_read`.

### B3 — MAJOR — §11.2 gives the supervisor no rotation-safe, freshness-guaranteed way to find *its own current* transcript

§11.2: *"The transcript path is already in every outcome record (`transcript_path`, receipt above), so
no new capture channel is needed."* Outcome records are keyed by `session_id`
(`bin/hooks/stop_outcome.py:220-223`, hand-verified). To read *its own current* context the supervisor
must map current-body → transcript, and every candidate key is unsafe in exactly the conditions the
band matters:

1. **`INCARNATION.session_id`** — **stale after any fork-steer.** claim-nonce §4.5 is explicit that the
   three sid-rotation writers (`_restamp_after_steer`, resume-limited inline, respawn) are
   *registry-only* and *"none touches `supervisor/INCARNATION`"*, and §5.10(a) keeps it that way. A
   supervisor steered by the interface (§5.1 — the v1 beat!) has a rotated body but an INCARNATION sid
   pointing at the **retired** body. Resolving the transcript through it reads a dead body's context.
2. **the current turn's outcome record** — **does not exist yet.** §11.2 says the read happens "at each
   `fleet beat` / checkpoint boundary", i.e. while the supervisor turn is *running*; the Stop hook that
   writes the outcome record has not fired, so the freshest record for the current sid is the previous
   turn's, and immediately after a fork-steer there is **no** record for the new sid at all.
3. the registry record (fresh sid post-steer) works — but §7.2/B1 shows that record's *name* is not
   stable either.

§11.2 names "when the measurement source is absent/stale" as a case it must cover and then does not.
For the operator's binding "supervisor self-monitors its context" requirement, the self-read has no
specified behaviour precisely at rotation and mid-turn.

**Fix direction:** resolve the transcript from the running process's own
`CLAUDE_CODE_SESSION_ID` env (the one key guaranteed fresh for the actor doing the reading) and read
the transcript file directly rather than via an outcome record; specify the absent/stale return (fail
toward "assume near-band, hand off" — the safe direction for an unenforceable ceiling, cf. B4).

### B4 — MAJOR — the 200k ceiling is prose: "urgent" is undecidable and unbounded, and the whole band is a self-read with no external enforcement

§11.3:

> Entering 150k → the supervisor hands off *at the next wave/task boundary*; past 200k → hand off after
> the current urgent task, no new work.

and §11.2 fixes the actor:

> This is a **read**, not a hook: the supervisor is the actor that must decide

"urgent" is nowhere defined, and there is no hard ceiling above 200k at which handoff stops being the
supervisor's discretion. A supervisor whose judgement is degrading with context pressure — the exact
condition the band exists to catch — can classify each next task as "the current urgent task" and never
cross into "hand off," indefinitely. The only mechanism the spec offers is a `[UNBUILT]` check that
*"emits the hand-off directive"* (§11.3) — emitting a directive to the actor that is free to ignore it
is not a ceiling. Composed with B3 (the actor may be reading a stale/absent occupancy figure) and B2
(the figure understates), nothing in the design bounds supervisor context growth.

```
$ grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat" bin/fleet.py   # at 0846d1c
0
```

**Fix direction:** a hard, enforced ceiling (e.g. `fleet beat`/checkpoint *refuses to dispatch new
worker turns* above a fixed `H > 200k`, leaving only handoff/urgent-finish verbs), and either drop
"urgent" or reduce it to a decidable predicate (e.g. "a wave already dispatched and not yet reconciled"
— a state fleet can read, unlike a self-asserted importance label).

### B5 — MAJOR — §10.4 "`kill supervisor` performs the release-then-stop sequence" is infeasible for the caller that runs `kill`

§10.4:

> Design rule: `kill supervisor` performs the release-then-stop sequence, and owes a tombstone like any
> stop-shaped verb.

`kill supervisor` is an interface/operator verb — the killer is **not** the supervisor body. But
`sup-release` (claim-nonce §6.3) *"requires continuity proof per §5.3"*, i.e. the caller must present
the holder's current nonce, which a different session does not have; and claim-nonce §6.3 **deleted**
the non-continuity escape (`"--force --confirm-inc is deleted"`). So the release arm of the sequence is
unavailable to `kill`:

```
$ grep -c "sup-release\|cmd_sup_release" bin/fleet.py           # at 0846d1c
0                                                                # unbuilt; and per claim-nonce §6.3 it needs continuity
```

§10.4 does offer the fallback (*"or the operator accepts the bounded-freeze-then-seize recovery"*), but
the stated **design rule** is the release path, and it cannot be the rule for the actor named. In
practice `kill supervisor` *always* lands in claim-nonce incident 3 (roster-gone + fresh heartbeat =
`freeze`) for up to `SUPERVISOR_CLAIM_STALE_SECONDS = 3600s` before a successor can `seize` —
```
$ sed -n '7918p' bin/fleet.py                                   # at 0846d1c
SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, ...
```
— i.e. the exact hour-long recovery-hole the "release first" rule was written to avoid.

**Fix direction:** either `kill supervisor` is defined as *steer the body to `sup-release` itself, then
stop* (making it a graceful stop, not a kill), or the design accepts and documents that `kill` always
takes the bounded-freeze path and states the tombstone/journal duties for that path only.

### B6 — MAJOR — release-then-stop composes with claim-nonce boot **rule 1** to open a two-live-bodies window that three-tier's automated callers can enter

claim-nonce §6.1 boot order (verified):

| # | Condition | Verdict |
|---|---|---|
| 1 | `claim.get("state") == "released"` | `claim` (fresh) |
| 2 | `holder_sid in live_sids and not(self+nonce)` | `refuse` |

**Rule 1 is checked ahead of rule 2 and carries no roster-liveness precondition.** So during any
`release → stop` window (§6.3's planned doctrine *and* §10.4's `kill`), INCARNATION reads `released`
while the old body is still **roster-live** — and any session that runs `sup-boot` in that window is
granted a **fresh claim** while the predecessor is still executing. claim-nonce blesses this ordering
only for the *manual, single-operator* planned case (§6.3). Three-tier adds automated bootstrappers
that can occupy the window — the v2 scheduled `fleet beat`, a `sup-spawn`, an in-flight handoff
successor polling `sup-boot` — reintroducing the 2026-07-16 dual-live-body class the entire claim-nonce
edifice exists to close. `one-live-session-per-name` (§16.7) blocks a *second* `supervisor`-named
spawn but not a `sup-boot` from an already-live differently-named session (the interface, a successor).
The spec analyses neither the window nor the new callers.

**Fix direction:** make release+stop atomic from the claim's perspective (the record is not left
`released`-and-live), or add a roster-liveness guard to rule-1's consumption in the three-tier callers,
or forbid `sup-boot` claiming a `released` record whose `released_by_sid` is still roster-live.

### B7 — MAJOR — the split relocates the 2026-07-16 fork-divergence class up to interface→supervisor, where nothing detects it

The design's headline safety property (claim-nonce) protects the **supervisor** claim. The **interface**
tier holds no claim by construction:

> §11.3: the interface session … *it never held the claim, so nothing transfers to it*

and it steers the supervisor with `fleet send` (§5.1), which is **not** claim-gated — claim-nonce §4.2
enumerates the five `_require_claim_holder` callers and they are all `sup-*`; `send` is unguarded.
Incident 1 (`supervisor/JOURNAL.md`, quoted in claim-nonce §1.2) was a host-restart `--fork-session` of
the manager conversation "independently re-deriving and dispatching my decisions in paraphrase." The
three-tier split does not remove that failure — it **moves it up a tier**: a fork-resumed *interface*
session carrying campaign context will re-derive and issue `fleet send supervisor …` steers, and the
supervisor has no way to tell two interface bodies apart (no claim, no nonce, `send` accepts either).
The exposure is worst in exactly the scenario the tiers exist for — the supervisor running *unattended*
while the human is away, so no human notices the second interface body. The spec never addresses
interface-body divergence; §13's "Not replacing the human" is a mandate boundary, not a detection
mechanism.

**Fix direction:** at minimum, record and surface interface provenance on `send` to the supervisor
(the 2026-07-17 adjudication already floated "caller provenance in `events.jsonl` + foreign-claim warn
on `send`" as a same-milestone candidate); state explicitly that interface-fork divergence is
out-of-scope-and-why if it is, rather than leaving the new top boundary silently unguarded.

### B8 — MINOR — §3.3's `[UNBUILT]` tier-resolution pre-flight needs fleet to read the very namespace env §3.2/§3.3 say fleet must not touch

§3.3 specifies a fleet-owned safety check:

> a `[UNBUILT]` tier-resolution check that, before `sup-spawn`/`spawn` dispatches with a tier alias,
> confirms the alias is resolvable in the active namespace

But the same section's architecture is that the tier→model table *"lives below fleet, in the daemon
env"* and *"Fleet has no `CLAUDE_CONFIG_DIR` handling (receipt §3.2), so it neither sets nor reads the
table."*

```
$ grep -c "CLAUDE_CONFIG_DIR\|ANTHROPIC_\|--provider\|provider" bin/fleet.py    # at 0846d1c
0
```

To "confirm the alias is resolvable in the active namespace" fleet must read that namespace's
`ANTHROPIC_DEFAULT_*_MODEL` — precisely the surface §3.2/§3.3 disclaim. The pre-flight is therefore not
implementable without granting fleet a new provider-env read surface the section spends its argument
denying. Not build-blocking (the failure still surfaces loudly at the daemon, as §3.3 concedes), but
the "fleet should pre-flight it" recommendation is in tension with the file's own boundary and should
be reconciled or dropped.

### B9 — MINOR — the §7.2 exemption is liveness-blind, so it also protects dead supervisor husks forever

Independent of B1's naming gap: `name == SUPERVISOR_BODY_NAME ⇒ (False, protected)` has no liveness
term. A genuinely dead supervisor record (roster-gone, claim seized/released) is then **un-sweepable by
construction** and lingers in `fleet status` until a human removes it — the mirror image of the
data-loss B1 describes. The right predicate (B1's fix) — *is this the current live claim-holder* —
closes both: it protects the running manager under any name and stops protecting a dead husk under the
reserved one.

### B10 — MINOR — three-tier makes the supervisor's dominant verb the one claim-nonce option-(b) cannot see

claim-nonce §2.2/§7 accept, as option (b)'s stated price, that a divergent body confining itself to
**ungated** verbs (`send`, `spawn`, `kill`) is undetected. §5.1 makes the supervisor's core loop
exactly that — dispatching workers via `fleet send`. So the design concentrates the supervisor's
activity in claim-nonce's accepted blind spot rather than in the `sup-*` verbs the nonce actually
guards. This is priced upstream (not a new defect), but §5/§8 should note that a zombie supervisor's
*most likely* behaviour (send-only worker churn) is the branch the ratified gate does not catch, so the
operator reads option (b)'s residual against the tier that maximises it.

### B-dep — note, not a finding — §4.1 builds on the weakest-evidenced substrate rows, which are unratified in this tree

§4.1's daemon-lifecycle consequences (idle-exit, **daemon-wedge**, the dead-daemon "beats silently do
not run") rest on the 2.1.212/2.1.216 rows, which in this worktree are `[PENDING OPERATOR
RATIFICATION]` and whose dead-daemon halves are self-described as *manager reports "NOT RE-OBSERVED BY
TWO SUBSEQUENT WAVES"* / `[MANAGER-VERIFICATION REQUIRED]`. §4.1 correctly labels them PENDING and
changes no verdict, so this is **not** a "leans on a withheld claim" defect — but the build slice's
`_doctor_check_supervisor_beat` and the "wedge ⇒ visibly-missing run-stamp" backstop inherit that
row's unratified, `--bg`-unreproducible status. Flagged so the operator ratifies the substrate rows
before, not after, the beat backstop is built on them.

---

## Verdict

The tier model is sound (the 2026-07-17 gate already agreed), the claim-nonce foundation is real, and
the receipts are clean end-to-end — 32/32 automated + 13 hand-run reproduce, `bin/fleet.py` unchanged
pin→HEAD, the out-of-write-set test edit correct. The draft answers adjudication items 4–10 in
structure. But three of its load-bearing new mechanisms have concrete holes: the swap band (B2+B3+B4)
does not reliably measure or enforce the operator's binding 150–200k requirement; the archive/husk
protection (B1) defeats itself the first time the supervisor hands off, which the band makes routine;
and the stop/recovery semantics (B5+B6) are either infeasible for their caller or reopen the
two-live-bodies class. B7 leaves the new top boundary undefended. None of these require abandoning the
architecture — each is a correction to a named section (§7.2 exemption key, §11.2 formula + resolution,
§11.3 ceiling, §10.4 kill semantics, plus an interface-divergence disposition). That is a fix-list, not
a restructure, but **B1 is CRITICAL and must close before any build starts.**

fix-list(B1,B2,B3,B4,B5,B6,B7,B8,B9,B10)

---

# Re-review r2 — fix wave 1 (`1a3d4e5` on `mf/three-tier`, merged clean into `mf/tt-break`)

**Date:** 2026-07-23. **Wave under review:** `1a3d4e5` "docs(review): three-tier re-draft fix-wave 1 —
close B1-B10 + S1". **Vantage:** worktree `C:\proga\fleet-mf-tt-break`, HEAD after fast-forward merge
`1a3d4e5`, `FLEET_HOME` unset. Receipt pin still `235421e`; **`bin/fleet.py` /
`bin/hooks/stop_outcome.py` remain byte-identical to `235421e`** (the wave is docs-only:
`three-tier-command.md` +337 lines, plus the spec-lens verdict file), so every line-anchored receipt —
old and new — is valid at HEAD.

## Receipts — clean, including the 2 new blocks

- `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md` →
  **34/34 reproduce, self-test PASS** (was 32/32; +2 blocks). Plain `--strict` run exits 0.
- The 4 new/added fix-wave receipts hand-executed at HEAD, all reproduce:
  `sed -n '8522p'` → `name = f"sup|{successor_inc}|successor"` (B1);
  `sed -n '826,827p'` → `sid = os.environ.get("CLAUDE_CODE_SESSION_ID")` (B3/B4);
  `grep -n 'append_event("mail_sent"'` → 3 sites, all target-sid (B7);
  `grep -c "sup-release\|cmd_sup_release"` → 0 (B5).
- Out-of-write-set: none new in the wave beyond the already-dispositioned test/lessons edits.

## Per-finding disposition (B1–B10)

| ID | Sev | Disposition | Basis |
|---|---|---|---|
| **B1** | CRIT | **FIXED** | Exemption re-keyed from `name == "supervisor"` to *is-this-the-current-live-claim-holder, under any name*: protected iff the record's `session_id` **or a member of `retired_sids`** equals `INCARNATION`'s body **and** roster-live. The `retired_sids` clause is load-bearing and correct — it covers the post-fork-steer gap where `_restamp_after_steer` has moved the old sid into `retired_sids` and `INCARNATION.session_id` is still the old sid (claim-nonce §4.5, registry-only rotation). **Verified no transient-roster regression** (see ND-cleared below). |
| **B2** | MAJOR | **FIXED** | Occupancy corrected to the 3-way sum `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`; the mis-cited "continuity" line is now explicitly labelled a continuity signal, not an occupancy figure. Arithmetic correct against Anthropic per-turn usage accounting. |
| **B3** | MAJOR | **FIXED** | Resolution moved to the running process's own `CLAUDE_CODE_SESSION_ID` (fresh for the acting body; receipt `sed 826,827p`), read the transcript by sid directly (not via an outcome record), and the absent/stale return is specified to **fail toward the band** ("assume near-band, hand off"). Closes the rotation/mid-turn holes I raised. |
| **B4** | MAJOR | **FIXED (design), but the new mechanism introduces ND1+ND2** | "urgent" replaced by a decidable, fleet-readable predicate (*work dispatched-and-not-yet-reconciled*); 200k made a hard fleet-enforced refusal, not a directive. Direction is exactly right; the **new refusal surface** has two gaps — see ND1 (MAJOR), ND2 (MINOR). |
| **B5** | MAJOR | **FIXED** (ND3 minor gap) | Two-arm kill: body-responsive → steer body to self-release then stop; body-unresponsive → documented bounded-freeze-then-seize. The killer-side release the earlier draft wrongly asserted is gone; receipt confirms `sup-release` unbuilt + continuity-required. Arm-1 lacks a timeout/fallback — ND3 (MINOR). |
| **B6** | MAJOR | **FIXED — correctly scoped as a claim-nonce prerequisite** | The spec does not own the boot verdict order, so it states the rule-1-vs-release-window constraint and **files the guard to the claim-nonce build slice** (rule 1 gains a roster-liveness precondition, or release+stop made atomic), with an **interim self-gate** for three-tier's automated callers (`sup-boot` only when `released_by_sid not in live_sids`). Honest ownership. *Residual (not a regression):* the interim gate binds automated callers only — a **manual** `sup-boot` inside the graceful-kill window is unprotected until claim-nonce ships the rule-1 guard. Carry into the claim-nonce slice. |
| **B7** | MAJOR | **FIXED (detect + surface + scoped non-goal)** | New §5.3: interface-caller provenance on `send` (receipt shows all 3 `mail_sent` events carry only the target sid today) + supervisor divergence-warn; full *prevention* scoped out in §13 with its reason (would need a claim on the tier the operator keeps human/claimless). Appropriate — the substrate cannot prevent an unregistered fork (claim-nonce §1.2), and the mitigation matches the 2026-07-17 same-milestone candidate. |
| **B8** | MINOR | **FIXED** | Pre-flight recommendation **dropped**; the §3.2/§3.3 boundary tension is resolved on the page; §13 non-goal "Not a fleet provider-env read surface." Accepted the finding rather than papering it. |
| **B9** | MINOR | **FIXED** (same fix as B1, opposite direction) | The live-claim-holder predicate's roster-live conjunct stops protecting a dead husk: a roster-gone record no longer holding the claim is an ordinary husk and the sweep removes it. Verified the conjunct is safe (below). |
| **B10** | MINOR | **FIXED** (recorded, priced upstream) | §5.3 records that the supervisor's dominant verb (`send`) is exactly option-(b)'s accepted blind spot, and points to §8 operator-gate routing as what bounds a send-only zombie's damage. Correct framing. |

**No SPURIOUS-FIX and no REGRESSED.** The author engaged each finding with receipts rather than
rubber-stamping (B1/B9 unified into one predicate; B6 correctly disclaimed as another slice's; B8
accepted-and-removed). The one regression candidate I hunted — B1's new `roster-live` conjunct being
fooled by a false-empty roster — is **cleared**: both and only callers of the predicate epoch-freeze
*upstream* of it —

```
$ sed -n '5407,5410p' bin/fleet.py          # cmd_archive, at 0846d1c == 235421e for bin/fleet.py
    if epoch_frozen:
        print("EPOCH: roster suspicious -- archival refused (G9); zero mutations", file=sys.stderr)
        return 1
$ sed -n '5629,5630p' bin/fleet.py          # _sweep_husks
    if native_epoch_suspicious(roster_ok, payload, workers):
        raise FleetCliError("husk sweep refused: roster suspicious (G9)")
```

— so a daemon-idle-exit empty roster (the state the autoclean sweep is *most* likely to meet) refuses
the whole pass before `_archive_eligible`/the liveness predicate ever runs. The predicate is never
asked "is this live?" against a blind roster.

## Mandated new-defect hunt

### Aim 1 — B4's fleet-enforced hard ceiling (a NEW refusal surface)

**ND1 — MAJOR — the ceiling's trigger population is under-specified and, taken literally, throttles the
interface tier the operator's model must keep long-lived.** §11.3 says the refusal is *"for a supervisor
caller,"* but the mechanism it specifies has **no supervisor-identity gate**:

> the dispatch verb reads the **caller's** own `CLAUDE_CODE_SESSION_ID` … resolves the caller's live
> transcript, computes the B2-correct occupancy, and refuses above `H`.

That fires for **any** `fleet spawn`/`fleet send` caller whose own context exceeds 200k. The **interface
session** issues `fleet send supervisor …` (the v1 beat, §5.1) and, per the operator's model, *"saves its
context for talking, interpreting, and long-term ideas"* — it is the tier deliberately **not**
respawned, and it is **outside fleet's launch surface** (§3.1), so fleet cannot hand it off or reset it.
A caller-agnostic occupancy ceiling therefore refuses the interface's only steering verb once the
interface's own context passes 200k, and the human has **no recourse** (no fleet handoff for tier 1).
The operator set the 150–200k band for the **second** tier only; nothing bands the highest tier.

```
$ grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat\|SUPERVISOR_BODY_NAME" bin/fleet.py
0                                                        # ceiling + identity concept entirely unbuilt — nothing constrains the build to scope it
```

**Fix:** gate the ceiling on *caller-is-the-supervisor-claim-holder* (reuse B1/B3's
`CLAUDE_CODE_SESSION_ID` vs `INCARNATION` resolution), and state explicitly that the interface tier is
exempt — it has no fleet-enforced band. Without this the build is free to ship a caller-agnostic refusal
that silences the human's control channel.

**ND2 — MINOR — the "reconcile-of-in-flight-work" carve-out is mechanically undefined against the
blanket `send` refusal.** §11.3 leaves *"only the handoff verbs … and reconcile-of-in-flight-work"* above
`H`. If reconciling an in-flight worker requires a `fleet send` (steer it to wrap up), that send is
caught by the very refusal §11.3 imposes; if reconcile is read-only (`result`/`peek`/`wait`), it is fine
but the spec never says so. The band explicitly permits *finishing* the in-flight urgent task, so the
carve-out must be decidable. **Fix:** state that past `H`, reconcile is read-only (outcome reads), or
name the exact send shape exempted.

*(B4 deadlock hunt — cleared. I checked whether the ceiling could also refuse the handoff-successor
dispatch and self-lock a supervisor at `H`: `sup-handoff-begin` **hand-rolls its own argv** with its own
roster pre-snapshot (`sed -n '8515,8522p'`), routing through neither `cmd_spawn` nor `dispatch_bg`, so a
ceiling scoped to `fleet spawn`/`fleet send` cannot catch it. No deadlock.)*

*(Limited-park / nonce-rc-map hunt — cleared. The ceiling is an occupancy refusal on `spawn`/`send`; it
does not pass through `supervisor_claim_decision`'s `{claim:0,seize:0,refuse:2,freeze:3}` rc map, so no
collision there. The autoclean scheduled caller neither spawns nor sends, so the scheduler-eats-exit-code
hazard (§4.3) does not reach it. Limited-park restamps registry sids inline and is orthogonal to an
occupancy read — no interaction beyond ND1's shared identity question.)*

### Aim 2 — B5's two-arm kill, 2026-07-16 incident class replayed through both arms

**ND3 — MINOR — the graceful arm has no timeout/fallback.** Arm 1 *"steers the body to release itself …
waits for the record to read `released`, then stops."* If the self-release steer never lands — `send`
refuses under a suspicious roster (§4.3), or the body accepts it and errors — the wait has no specified
bound, so `kill supervisor` can hang instead of falling through to arm 2. **Fix:** arm 1 needs a bounded
wait → fall to arm-2 bounded-freeze on timeout.

**Incident-class replay — no new defect, one limit worth recording (not a regression).** Replaying the
2026-07-16 dual-body fork through both arms: `kill supervisor` operates on the **registered** body (send
targets the registry record's current sid; arm 2 freezes on the registered claim). The incident-1 zombie
was an **unregistered** `--fork-session` that *"fleet never had a handle on"* (claim-nonce §1.2(2)) — so
**neither arm reaches it**: arm 1 releases only the registered body (and, via boot rule 1, a successor
could then claim while the zombie still runs — this is B6/B7 territory, already filed), arm 2 freezes the
registered claim while the zombie keeps issuing `send`s. This is the **substrate limit** claim-nonce
already records (no fleet verb can reach a fork minted outside every fleet code path), **not** a defect
introduced by B5's fix — recorded so the operator does not read "kill supervisor" as a remedy for an
incident-1 zombie. Detection of such a body remains §8 operator-gate routing + B7's provenance-warn, not
`kill`.

### Aim 3 — B1's live-claim-holder predicate: can a dead-but-claim-holding husk still be protected?

**Cleared — the predicate's `roster-live` conjunct closes the inverse-B9 hole, and its callers close the
transient-roster hole.** A body that holds the claim but is roster-gone (the incident-3 freeze state:
roster-gone + fresh heartbeat) fails the `roster-live` conjunct and is **not** protected — an ordinary
husk the sweep removes. And because both callers epoch-freeze upstream (receipts above), the conjunct is
never evaluated against a *false*-empty roster, so a live-but-idle supervisor during a daemon idle-exit is
not mis-classified dead-and-swept: the pass refuses wholesale first. Both the "protect a live successor
under any name" (B1) and "don't protect a dead husk" (B9) directions hold, and the dangerous middle
(false-empty roster) is unreachable. No new defect.

## r2 verdict

Fix wave 1 **closes all ten findings** (B1–B10 FIXED; B6 correctly re-homed to the claim-nonce slice
with an interim gate; no spurious fixes, no regressions — the one regression candidate is provably closed
by upstream epoch-freeze). The wave's own riskiest change — B4's new fleet-enforced ceiling — introduces
one MAJOR and one MINOR gap in an `[UNBUILT]` mechanism (**ND1** interface-tier over-application, **ND2**
reconcile carve-out), and B5's graceful arm leaves one MINOR gap (**ND3** no timeout). All three are
bounded corrections to unbuilt mechanisms with clear fix directions — not architecture rework, and not
grounds for a third full review wave. The tier model and the claim-nonce foundation stand; **escalation
is not warranted.**

fix-list(ND1,ND2,ND3)

---

# FINAL GATE (r3) — fix wave 2 (`4e540f8`), receipt-parser audit, and merge verdict

**Date:** 2026-07-23. **Wave under review:** `4e540f8` "docs(review): three-tier fix-wave 2 — close
ND1-ND3 + R1". **Vantage:** worktree `C:\proga\fleet-mf-tt-break`, HEAD after fast-forward merge of
`mf/three-tier` = `4e540f8`, `FLEET_HOME` unset. Pin still `235421e`; **`bin/fleet.py` byte-identical
to the pin across the entire review range** (`git log 0846d1c..4e540f8 -- bin/fleet.py` empty), so every
line-anchored receipt is valid at pin and HEAD alike.

## 1. Disposition — ND1, ND2, ND3, R1

| ID | Sev | Disposition | Basis (re-verified) |
|---|---|---|---|
| **ND1** | MAJOR | **FIXED** | §11.3 now scopes the ceiling to *"exactly one caller"*: it fires *"when — and only when — the caller **is the current supervisor claim-holder**."* The interface tier is **explicitly exempt** — *"it has no fleet-enforced band, and no fleet verb may refuse it on occupancy"* — with my whole argument (interface is fleet-unlaunchable §3.1, operator banded only tier 2, no recourse) carried into the spec as binding text. Workers named as unaffected. Exactly the fix I asked for, not a narrower one. |
| **ND2** | MINOR | **FIXED** | Reconcile past `H` is now **explicitly read-only** — `fleet status`/`wait`/`result`/`peek` — and *"It may **not** issue a `fleet send` to 'steer an in-flight worker to wrap up': that send is a new worker turn and is caught by the very refusal above, so leaving it implicitly permitted would have made the carve-out undecidable."* The undecidability I flagged is named and closed in the safe direction. Spot-checked `cmd_wait` (@3398) — no dispatch/spawn/send in its body, so the read-only carve-out is genuinely read-only. |
| **ND3** | MINOR | **FIXED** | Arm 1 now takes a bounded wait `T_release`, with a **new receipt** for the precedent — hand-executed at HEAD: `sed -n '7919p'` → `SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0`. An immediate `send` refusal fails over at once without waiting out the bound; on timeout **or** refusal `kill` *"stops the body anyway and falls through to arm 2 — announcing which arm it took."* The hang I raised is gone, and the arm-announcement (which I did not ask for) is a genuine improvement, since the two arms differ by an hour of recovery cost. |
| **R1** (spec lens) | nit | **FIXED** | §12's `longcat-fleet-usage.md` bullet no longer reads as a live roadmap item: it now says the supervisor row lands *"only if a namespace-aware tier-resolution pre-flight is ever built as **separate scope** — which §3.3 argues *against* for v1 … Listed as a conditional consequence of a decision already made the other way, **not** a live `[UNBUILT]` deliverable of this slice."* Matches §13's non-goal; the B8 fix now propagates to all three sites. |

**No SPURIOUS-FIX, no REGRESSED.** Every wave-2 edit traces to a finding; none over-reaches; no
previously-passing receipt broke (39/39, below).

## 2. Audit of the resurrected receipts — and a correction to the gate's premise

### 2.1 What actually evaded, and when

I reconstructed the evasion from the committed trees rather than accepting the summary. Fence-marker
census (every line whose stripped form opens a fence, allowing indent, `>`, and `~~~`):

| commit | fence markers | blocks | harness reported | non-column-0 markers |
|---|---|---|---|---|
| `0846d1c` (r1) | 64 | 32 | `32/32 … (32 fenced blocks)` | **none** |
| `1a3d4e5` (wave 1, my r2) | 76 | 38 | `34/34 … (37 fenced blocks)` | **8** (4 blocks) |
| `4e540f8` (wave 2, now) | 78 | 39 | `39/39 … (39 fenced blocks)` | **none** |

**Correction to the task's premise, on receipt: no block rode through r1.** At `0846d1c` every one of
the 32 fenced blocks sat at column 0 and 32/32 were parsed and verified — r1's coverage claim was
complete. **All four evading blocks were introduced by fix wave 1**, so they evaded **r2 only**, not
"r1 AND r2". The four, in their wave-1 form:

- `> ```…` (blockquote, §7.2 B1) — `sed -n '8522p'`
- `  ```…` (2-space list indent, §10.4 B5) — `grep -c "sup-release\|cmd_sup_release"`
- `  ```…` (§11.2 B3) — `sed -n '826,827p'`
- `  ```…` (§11.3 B4) — `grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat"`

The blockquoted one is invisible to the parser entirely (38 real blocks → 37 counted); the three
indented ones are counted but yield zero receipts (37 counted → 34 receipts).

### 2.2 The four, re-executed by hand at HEAD — all reproduce, prose checked

| # | Receipt | Output at HEAD | Prose claim it is offered for | Match? |
|---|---|---|---|---|
| R-a | `sed -n '8522p' bin/fleet.py` | `    name = f"sup|{successor_inc}|successor"` | successor runs under a pipe-delimited name, so a `name == "supervisor"` equality protects gen-0 only | **yes** — with one nit, §2.3 |
| R-b | `grep -c "sup-release\|cmd_sup_release" bin/fleet.py` | `0` | `sup-release` does not exist yet | **yes** (the "needs continuity" half is attributed to claim-nonce §6.3, not to this grep — correctly) |
| R-c | `sed -n '826,827p' bin/fleet.py` | `sid = os.environ.get("CLAUDE_CODE_SESSION_ID")` / `return sid or None` | `current_caller_session()` is exactly that env read | **yes** (the "daemon sets it to the child's own sid" half is attributed to native-substrate G4, not to this receipt) |
| R-d | `grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat\|SUPERVISOR_BODY_NAME" bin/fleet.py` (5-term; wave 1 had 3) | `0` | neither the ceiling nor the identity concept exists today | **yes** in aggregate (see §2.3) |

### 2.3 Two prose-vs-proof nits (recorded, non-blocking)

- **R-a proves the name, not the negative.** The sentence it serves also asserts *"which nothing renames
  back to `supervisor`"* — a negative this receipt cannot establish. I independently confirmed it true in
  r1 by reading `cmd_sup_handoff_complete` (it transfers the INCARNATION claim; registry records are
  untouched), so the claim is **correct but under-receipted**.
- **R-d's grep is a proxy for "no identity concept exists."** Four string spellings absent ≠ the concept
  absent. Adequately supported *in aggregate* by §10.3 (`RESERVED` → 0), §10.1 (`sup-spawn` → 0) and
  Appendix A, so not a false claim — just a grep carrying more weight than its terms.

### 2.4 Hunt for other receipt-shaped text still evading — the document is clean, **the tool is not**

**Document: clean.** In `4e540f8` all 78 fence markers are column-0 backtick fences; **zero**
receipt-shaped lines (`$ `, `# at `, 4-space-indented `$ `) live outside a fenced block; **zero** inline
backtick spans carry a `$ ` command. No residual evasion of any shape.

**Tool: the class is alive.** `tools/verify_receipts.py` and `tests/test_receipts.py` were **never
touched** in the entire review range — the remedy was to move four blocks in the document. I probed all
four evasion shapes with a deliberately **false** expectation (`999999` for `grep -c "RESERVED"
bin/fleet.py`, true answer `0`). A column-0 control is caught (`1 FAILED`). Every evasion shape passes:

```
# live: probes the working tool, not a pinned tree
$ for s in blockquoted indent2 indent4 tildefence; do printf '%-12s ' $s; py -3.13 tools/verify_receipts.py --strict $CLAUDE_JOB_DIR/tmp/e-$s.md 2>&1 | grep -o '[0-9]*/[0-9]* receipts.*FAILED)'; done
blockquoted  0/0 receipts reproduce exactly (0 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
indent2      0/0 receipts reproduce exactly (1 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
indent4      0/0 receipts reproduce exactly (0 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
tildefence   0/0 receipts reproduce exactly (0 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
```

All four exit **0** with **0 FAILED** on a receipt that is flatly false. Mechanism: `parse()` lstrips
before the fence test (@228) but `_parse_block()` matches `# at `/`$ ` on **raw** lines (@244-255), so an
indented block parses to nothing; and `lstrip()` does not strip `>`, so a blockquoted fence is not a
fence at all. `~~~` is not a fence to this tool either.

### 2.5 H1 — MAJOR, filed against the harness (outside this spec's write-set)

**The evidentiary guarantee the operator is asked to rely on has a silent bypass, and it was live during
two of this gate's three waves.** Four compounding facts:

1. Four shapes of receipt silently verify-as-nothing (§2.4), with **no error, no warning, exit 0**.
2. `tests/test_receipts.py` never reconciles blocks against receipts and sets **no per-spec receipt
   floor**; `test_harness_can_fail` seeds *"the first spec with any non-volatile receipt"* (@182-190), a
   **global** non-vacuity guard. A spec whose receipts were all indented would fall to zero verified
   receipts with the entire suite green.
3. The only tell is the printed `blocks` vs `receipts` mismatch — `34/34 … (37 fenced blocks)`. That line
   appeared in wave-1 output that **both** lenses quoted and **neither** reconciled, mine included.
4. **"Two independent verifiers" gave false assurance.** The spec lens ran its own extractor sharing no
   code with `verify_receipts.py`, and it also reported `34/34` — because both implementations share the
   same *unstated assumption* that receipts live at column 0. Independence of implementation is not
   independence of assumption; two verifiers with one blind spot are one verifier.

This contradicts the repo's own doctrine (`CLAUDE.md`: *"A pasted command+output block is a claim until
something re-runs it"*; `claim-nonce.md`'s *"stop fixing an instance and kill a class"*). **Fix (own
slice, not this spec's):** `lstrip()` — and strip a leading `> ` — in `_parse_block`; accept `~~~`;
**fail** on any fenced block that yields zero receipts and zero unclassified; assert
`blocks == receipts + unclassified` per spec; add a per-spec receipt floor to `tests/test_receipts.py`;
and extend the seed test to prove **extraction completeness**, not only paraphrase detection — the
current seed test validates that a *parsed* receipt can fail, which is silent about everything unparsed.

**Own-conduct note.** My r2 conclusions were not affected: I hand-executed all four evading receipts
independently in r2, which is why the substance held. But I reported *"34/34 reproduce"* as harness
coverage without reconciling the printed `37 fenced blocks`, so my characterisation of what the harness
had checked was wrong even though my findings were not.

## 3. Final new-defect hunt

**ND4 — MINOR — the ND1 identity gate can fail OPEN after a fork-steer, which is how every supervisor
turn starts.** §11.3 specifies the ceiling's gate as *"the same `CLAUDE_CODE_SESSION_ID` vs
`supervisor/INCARNATION` resolution B1 uses."* Read literally as `caller_sid == INCARNATION.session_id`,
it fails, because claim-nonce §5.10(a) is explicit that the restamp is **pull, not push**:

> `session_id` is restamped to the caller as part of the **next validated `sup-*` write** … a steer that
> never leads to a supervisor action never touches supervisor state.

Sequence: the interface fork-steers the supervisor (the v1 beat, §5.1) → the body has a **new** sid while
`INCARNATION.session_id` still holds the **old** one → the supervisor, above `H`, runs `fleet spawn`
*before* any `sup-checkpoint` → the gate finds `caller_sid != INCARNATION.session_id`, concludes *"not the
claim-holder,"* and **does not fire**. The hard ceiling is dormant for that turn's dispatches — the exact
outcome B4 exists to prevent, failing in the unsafe direction.

The fix is already on the page one section away and just needs restating at the ceiling: §7.2's predicate
matches on *`session_id` **or a member of `retired_sids`***, and `_restamp_after_steer` pushes the old sid
into the registry record's `retired_sids` at steer time — so resolving *caller → registry record →
claim* bridges the gap. Two additions worth binding: (a) name the fail direction (unresolvable identity ⇒
treat the caller as the supervisor, mirroring §11.2's *"fail toward the band"*), and (b) use the
**structural** discriminator that needs no sid at all for the half that matters most — the interface is
not a fleet worker, and the supervisor is (§10.2), so `FLEET_WORKER` alone exempts the interface
unconditionally:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '1284p' bin/fleet.py
    env["FLEET_WORKER"] = name
```

Rated MINOR, not MAJOR, because the correct predicate is cross-referenced rather than absent and the
build slice gets its own review — but it must be stated explicitly, since the failure is silent and
unsafe-directional.

*(Also cleared in this hunt: the de-indentation changed no receipt semantics — R-d's grep gained a 5th
term and still returns `0`, prose still matches; the wave introduced no new `[UNBUILT]` claim without a
no-match receipt; status is still `drafting`; the write-set is still the spec plus review files, no code
edit.)*

## 4. Merge verdict — is `mf/three-tier` fit to go to the operator for ratification?

**Yes, with two disclosed carry-items.**

**The spec is sound.** Across three waves and two independent lenses, **fifteen findings** (break
B1–B10, spec S1, ND1–ND3, R1) are closed with no spurious fix and no regression. Every design hole I
raised — the self-defeating archive exemption, the mis-measured and unenforceable swap band, the
infeasible kill-release, the two-live-bodies release window, the unguarded interface boundary — is
answered in the design rather than deferred by wording, and the two answers that genuinely belong to
another slice (B6's boot-order guard, and the `FLEET_WORKER` refusal) are **filed as claim-nonce
prerequisites rather than absorbed**, which is the correct behaviour for a consumer spec. All 39 receipts
now parse and reproduce; the document carries no evasion of any shape; status discipline and the
never-promote-your-own-spec rule are intact.

**Carry-item 1 — H1 (MAJOR, harness, own slice).** The operator is being asked to ratify a document whose
credibility rests on *"every receipt is re-executed."* That guarantee currently has a silent bypass which
was live during two of three waves and remains live in the tool today. This is **not** a defect in the
spec and does not block its ratification — but it is material to an informed ratification and should be
disclosed alongside it, and fixed before the next spec leans on the same harness.

**Carry-item 2 — ND4 (MINOR, spec).** One sentence in §11.3 must name the `retired_sids` bridge, the
fail direction, and the `FLEET_WORKER` exemption, or the build can ship a ceiling that quietly does not
fire. Bounded, and the build slice reviews it again.

Neither item is a design defect and neither warrants a third review wave or an escalation. The tier
model, the claim-nonce foundation it consumes, and the mechanisms this gate stress-tested all stand.

sound

---

# RE-GATE r4 — wave 3, the operator-amendment wave (`8a089bf`)

**Date:** 2026-07-23. **Wave:** `8a089bf` "three-tier wave 3 — operator amendments (top tier, fallback
chain, worker band, cap doctrine)", merged fast-forward into `mf/tt-break`. **Vantage:** worktree
`C:\proga\fleet-mf-tt-break`, HEAD `8a089bf`, `FLEET_HOME` unset. Pin still `235421e`; `bin/fleet.py`
still byte-identical to it (the only code-tree change in the whole range is `tests/test_receipts.py`
−1 line, dispositioned in r1). **Scope: the four amended items only**, per the re-gate brief.

**Receipts: 46/46 reproduce, self-test PASS** (was 39/39; +7 blocks). I hand-executed all seven new
ones — `sed 3909,3912p` (resume-limited carries `resume_sid`+`model`), `sed 4367,4368p`
(`new_worker_record(... model=model)`), `sed 1920,1924p` (limit park writes `status="limited"` +
`limit_reset_at`), `sed 1635,1640p` (horizon gate; null ⇒ never auto-eligible), `sed 858p`
(`"token_ceiling"` is a shipped field), `sed 1284p` (`FLEET_WORKER`), and the `# live` substrate-status
grep — **all reproduce**. Independent fence census: 92 markers, **all column 0**, 46 blocks = 46
receipts, no block/receipt mismatch (the H1 evasion class that bit wave 1 has not recurred in the
document; the tool gap itself is still open — H1 stands as filed).

**Substrate status re-check (§4.1's wave-3 correction is accurate):** `PENDING OPERATOR RATIFICATION`
→ **0**; `RATIFIED 2026-07-23` → **8**; `RATIFICATION WITHHELD 2026-07-23` → **3**. The three withheld
claims are the dead-daemon `rm` string, its `stop` twin, and *"rm/stop do not revive the daemon"* —
and §4.1 leans on none of them (its wedge consequence rests on the 2.1.216 row, ratified). The
correction is honest maintenance, not a scope grab.

## 1. Per-item disposition

### Item 1 — supervisor promoted to top tier (§3.1) — **FOLDED CORRECTLY**

The role table is rebuilt to the operator's second addendum: tiers renamed `highest`→`top`; supervisor
binding is *"top, falling back to second"*; worker is *"second **or** third"*; and the ownership column
records the operator's actual reasoning — interface owns *"the long-term goals"*, supervisor owns
*"solid plans, details, and splitting tasks"*. The promotion is justified as division of labour, not
budget, matching the addendum verbatim. Consequential edits are consistent: §3.4's allowlist re-scoped
from *"third-tier ∈ {opus, sonnet}"* to *"worker tier ∈ {second, third}"*. No spurious change.

### Item 2 — preference chain + UL fallback vs the swap band (§3.5) — **FOLDED, with DEFECTS (ND6, ND7)**

Well-constructed on shipped machinery, and it answers the brief's band question head-on and correctly.
§3.5.1's constraint chain is right: the model is spawn-immutable, and `resume-limited` re-dispatches the
*same* sid (receipt @3909-3912), so it can neither change tier nor reset context — therefore a fallback
is necessarily a **body change**. §3.5.3 then states *"a fallback respawn **IS** a band handoff … one
body change satisfies both"*, which is the right answer to *"does a fallback respawn count as the band
handoff?"* and avoids burning two context resets for one need.

**But the mechanism is unperformable in its own trigger condition — ND6 below.**

### Item 3 — worker band sweep (§11, §11.4, §11.3 restatement) — **FOLDED CORRECTLY, and notably well**

§11's title and preamble now cover *"supervisor AND workers"*; §11.4 gives three worker-specific
differences that each follow from what a worker is (task boundary not wave; `respawn` not claim handoff,
since a worker holds no claim; enforcement by the supervisor, since a worker calls neither `spawn` nor
`send` and so has nothing to refuse). The operator's *coherence, not spend* rationale is recorded
explicitly — which matters, because reading it as a spend argument is exactly what would justify
dropping it under the cap doctrine.

**The good catch, and the reason this is not a spurious edit:** my ND1 exemption in wave 2 rested partly
on *"the operator set the band for the **second tier only**."* Wave 3 retires that scoping — so the
author noticed the load-bearing premise had been knocked out from under an accepted fix and **re-based
the exemption** on *recourse and dispatch* instead: the interface is exempt because it is outside
fleet's launch surface and a refusal it cannot escape has no remedy; workers are not refused because
they never call the gated verbs. That reasoning survives the extension where the old one would not.
Sweep verified complete — `grep` for surviving `"second tier only"` / `"supervisor only"` scoping
returns only the two retirement statements themselves and one unrelated §7.2 line about the registry
footprint.

### Item 4 — cap-doctrine B4 reshape (§11.5) — **DEFECT (ND5, CRITICAL)**

The *substance* of the reading is defensible and I do not dispute it: a spend ceiling answers *"has this
cost too much?"* (already answered by the plan's own limits, for everyone), a context band answers *"is
this session still sharp?"*, and its only remedy is a handoff, never a stop — which is why the same
docket that retired spend caps *extended* the band to workers. The §11.5 negative is genuinely valuable
too: §11.3's ceiling *"must not be implemented by reusing, extending, or re-denominating the spend
machinery, or it would silently inherit the flag's off-by-default state and stop firing."*

**The problem is the authority it claims, not the reasoning.** See ND5.

## 2. New-defect hunt (aimed at the fallback chain, per the brief)

### ND5 — CRITICAL — §11.5 declares an operator ruling the record does not contain, and withdraws the contingency on the strength of it

§11.5 is titled *"SETTLED (operator ruling, 2026-07-23)"*, states *"**This is decided, not pending.** The
manager's reading was put to the operator and **confirmed**"*, cites
`knowledge/lessons.md#2026-07-23-three-tier-inputs`, **third addendum**, and block-quotes it:

> **Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — **cost/spend
> ceilings are gone unless the counting flag puts them back** … The context band … is a freshness
> mechanism, not a budget, and its enforcement stays.

**That addendum does not exist.**

```
# live: a claim about the working tree's recorded operator decisions
$ grep -c "Third addendum" knowledge/lessons.md
0
```

`git log -S "Third addendum" -- knowledge/lessons.md` returns no commit, and a repo-wide search for the
quoted phrases finds them **only inside `three-tier-command.md` itself** and at one place in
`lessons.md` — which says the **opposite about status**:

> `lessons.md:781` — **Manager reading of the cap doctrine vs the spec's B4 hard arm:** … a context band
> is a freshness mechanism, not a budget. Wave 3 states this reading in-spec; **the operator rules on it
> at ratification.**

So the record holds a *manager reading*, expressly **pending the operator's ruling at ratification**;
the spec upgrades it to a *quoted operator ruling*, marks the section SETTLED, and — the damaging part —
**withdraws the safety valve**: *"the earlier draft's contingency branch ('if the operator rules the
other way, the band becomes advisory') is **withdrawn**, since the operator ruled."* `OPERATOR-GATES.md`
records the cap doctrine itself in broad terms (*"no fleet-enforced token or USD ceilings for anyone;
the plan's own usage limits cap workers and managers alike"*) and contains no carve-out for a context
band — so the tension §11.5 resolves is real and, on the record, unresolved.

This violates the spec's own governing rule, stated in its header: *"An author never promotes its own
spec … every operator gate stays open until Altai ticks it"* — and it does so in the one section that
decides whether B4's enforcement, the mechanism three waves were spent shaping, survives at all.

**Fairness, stated plainly:** the re-gate brief itself says *"per the operator's third-addendum ruling,"*
so a verbal ruling may well have occurred and simply never been written down. I cannot distinguish an
unrecorded ruling from an anticipated one from the tree, and I am **not** asserting fabrication. But the
distinction does not change the disposition: **a binding operator ruling whose only witness is the
document it authorizes is not established**, on this repo's own doctrine that a pasted claim is a claim
until something independent bears it out.

**Fix (cheap, mechanical, but blocking):** either (a) record the third addendum in `lessons.md` and tick
`OPERATOR-GATES.md`, then re-cite — one commit, and §11.5 stands as written; or (b) revert §11.5 to
`PENDING`, restore the withdrawn contingency branch, and let the operator rule at ratification as
`lessons.md:781` says they will. Not (c): leave the spec as the sole witness.

### ND6 — MAJOR — the fallback chain cannot perform the ritual it mandates, because its trigger is what disables the predecessor

§3.5.3 binds the fallback to the handoff ritual: *"**It must go through the handoff ritual, not a bare
respawn**, whenever a plan is in flight: the successor document is what carries the plan across the
context reset."* The handoff ritual must be run **by the claim-holding body** — `cmd_sup_handoff_begin`
is one of the five `_require_claim_holder` callers:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8492p' bin/fleet.py
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
```

But the chain's **only** trigger is the top tier's usage limit, and hitting it parks the body
`status="limited"` (receipt @1920-1924) — after which fleet **refuses to give it a turn at all**:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '3681,3687p' bin/fleet.py
        if status == "limited":
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(
                f"{name}: parked (limited) -- use `fleet resume-limited {name}` "
                "instead (never steer a parked worker)"
            )
```

**So at the exact moment the fallback fires, the predecessor cannot be steered, therefore cannot run
`sup-handoff-begin`, therefore cannot write the successor document or mint the handoff token.** Every
alternative route is also shut:

- **Bare respawn** — §3.5.3 permits it only *"when nothing is in flight,"* which is not the fallback's
  normal case; and claim-nonce §5.10(b) is explicit that *"a respawned body holds no generation and
  cannot present one,"* so the fresh body cannot `resume`. It reaches `sup-boot` and finds the holder
  either roster-**live** (⇒ rule 2 `refuse`) or roster-gone with a **fresh** heartbeat — the limited body
  was working seconds earlier — which is `freeze`, not `seize`. Seizure waits out
  `SUPERVISOR_CLAIM_STALE_SECONDS = 3600s`.
- **`sup-release` by the holder** — same blocker: the holder cannot act. And claim-nonce §6.3 deleted the
  non-continuity escape, so no other actor can release for it (this is B5 again, on a new path).

Net: the "automatic fallback" the operator asked for either **loses the in-flight plan** or **stalls the
campaign for up to an hour** — and it does so every time the top tier limits, which the operator says is
roughly **twice as often** as the standard limit. The mechanism is at its weakest precisely where it was
introduced to help. §3.5.2 step 2 passes over this in a parenthetical.

**Fix direction:** `limited` is a *fleet-observed, unambiguous* state — unlike roster-gone, which is
G9-ambiguous and is the reason the freeze exists. The clean answer is to make *holder parked `limited`
with a recorded horizon* an authorized claim-transfer state, so a successor may take the claim
immediately without waiting out staleness. That is a **claim-nonce boot-order change**, which this spec
does not own — so it should be filed as a claim-nonce build-slice prerequisite, exactly as B6 and the
`FLEET_WORKER` refusal already are. Failing that, the honest alternative is to state that a UL fallback
**loses the working plan** (bare respawn, journal + task file only) and accept it in the spec rather
than mandate a ritual that cannot run.

### ND7 — MINOR — two smaller wrong notes in §3.5.2

- **`resume` is cited first for a path where it is unreachable.** Step 2 says the claim carries *"per
  claim-nonce §5.10(b) (`sup-boot` → `resume` on proven continuity, else the release/seize path)"*. For a
  **respawned** body §5.10(b) itself forecloses `resume` (*"holds no generation and cannot present
  one"*), so the only live branches are seize-on-stale-heartbeat or explicit release. Leading with the
  dead branch makes the path read safer than it is — and is part of how ND6 stayed hidden.
- **"Every input the chain needs already exists" overstates the receipts.** `limit_reset_at` exists, but
  shipped code consults it only for records whose status *is* `limited` (`"resume_eligible": status ==
  "limited" and _limit_reset_passed(rec)`, @2162). The chain's design puts an **inherited** horizon on a
  *running* second-tier body, where that machinery never looks — so the return logic is entirely new, not
  existing input. Relatedly, the null-horizon case is unhandled by the chain: @1635-1640 returns False
  forever (*"never auto-eligible — needs an operator-set reset or `--force-now`"*), so a top-tier limit
  parked without a horizon would strand the supervisor on the second tier permanently with nothing
  nagging. State it.

**UL detection is per-session — confirmed, with the consequence the brief asked for.** The scan is a
per-session transcript read (`scan(sid, transcript_path=path)`, @1920), so fleet learns *"this session
hit a wall,"* never *"the top tier is exhausted."* It therefore cannot distinguish a **tier** limit from
an **account-wide** one: if the wall is account-wide, the fallback spawns a fresh second-tier body that
limits immediately, costing a body change to discover what §3.5.2 step 4 then handles correctly
(*"both tiers limited ⇒ stays parked"*). Worth one sentence; not a defect on its own.

**SPURIOUS-FIX check: none.** Every wave-3 edit traces to the operator addendum or to a consequence of
it. The two edits that could have looked like scope creep are both justified: §4.1's substrate-status
correction is required maintenance (the partial ratification landed on `main`) and is receipted `# live`;
§11.3's ND1 re-basing was *forced* by this wave retiring its old premise, and re-derives the same
conclusion from a durable basis rather than quietly leaving a fix resting on a retired fact.

## 3. r4 verdict and merge decision

Three of the four amended items fold correctly, and the worker-band item folds better than asked — the
author caught that wave 3 had knocked out the premise under an accepted wave-2 fix and re-based it
rather than leaving it dangling. Receipts are clean at 46/46 with no recurrence of the H1 evasion class.

**But `mf/three-tier` is not, at this commit, fit to go to the operator for ratification** — a reversal
of my r3 position, on one ground: **the document now tells the operator they already ruled on the one
question the record says they will rule on at ratification (ND5), and has deleted the branch that
handles them ruling the other way.** Handing an operator a spec that pre-declares their decision
corrupts the ratification act itself, and it is the exact failure mode this spec's own header rule and
this whole four-wave gate exist to prevent. The fix is one commit in either direction and is not mine to
choose — it is a provenance question for the manager and the operator, not a spec-authoring one.

ND6 is a real design hole in the wave's headline mechanism and should close before the build slice, but
it does not block ratification the way ND5 does: it is a bounded fix with an obvious shape (file the
`limited`-as-authorized-transfer-state guard as a claim-nonce prerequisite, or state the plan loss
honestly), and the build slice reviews it again. ND7 is two sentences.

Once ND5 is resolved — by recording the ruling or by restoring `PENDING` and the contingency — the
document returns to the r3 position: sound, and fit, with H1 and ND6 disclosed alongside it.

fix-list(ND5,ND6,ND7)
