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
