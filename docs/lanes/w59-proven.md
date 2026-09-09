# Lane report — `w59-proven`: verifying the first supervisor succession on this host, and what the record actually says

**Branch** `w59/proven`, based at `1294920`. **Fence:** prose only. `bin/fleet.py`,
`bin/fleet_keeper.py`, `tests/**`, `supervisor/GOALS.md`, `docs/OPERATOR-GATES.md` and the root
`CLAUDE.md` were **read and never edited** — verified by the diffstat in §10.

Every line is tagged **MEASURED** (I ran it, in this worktree or read-only against the live home) or
**BELIEVED** (reasoned from what I read; not executed). A command I did not run is not quoted as if I
had. Written for an adversarial reader: the load-bearing counts are pinned receipts in
`docs/specs/graceful-succession.md` §9.4, re-executed by `tools/verify_receipts.py`.

---

## 0. THE HEADLINE, AND IT IS NOT THE ONE I WAS SENT TO LAND

**MEASURED. The supervisor handoff route was already 6-for-6 when the 2026-09-09 drill ran. That drill
is the sixth completion under the fixed default and the fifteenth overall — not the first, and not
"0-for-8 → 1-for-9".**

Counted over `supervisor/JOURNAL.md` at `1294920`, by regex over entry headers, and pinned as receipts
W1–W3:

| | count |
|---|---|
| `HANDOFF-BEGIN` | **26** |
| `HANDOFF-COMPLETE` | **15** |
| `HANDOFF-ABORT` | **3** |
| begins whose task file is under a drive-lettered (Windows) fleet home | **25** |
| begins whose task file is under `/home/altai/proga/fleet` | **1** |

**MEASURED.** The eight recorded stillbirths are exactly the eight `HANDOFF-BEGIN` entries with no
terminal event, and **all eight predate the `dontask` fix** (`87cbf9a`, authored 2026-07-28T00:10+05 =
**2026-07-27T19:10Z**; `SUCCESSOR_DEFAULT_MODE` `"dontask"` → `"bypass"` in that commit's diff). So are
the three aborts (2026-07-27T03:15/03:32/03:53Z, all before 19:10Z).

**MEASURED.** Every completion after the fix:

    2026-08-05T16:48:54Z   2026-08-05T17:32:10Z   2026-08-05T19:33:26Z
    2026-08-09T19:03:01Z   2026-08-09T22:54:36Z   2026-09-09T17:49:36Z

The first five ran on the retired Windows host. **MEASURED**, and not from the dates: those five
`HANDOFF-BEGIN` bodies name a task file under `C:/proga/claude-fleet/state/…`; the sixth names
`/home/altai/proga/fleet/state/…`.

**MEASURED.** `SUCCESSOR_DEFAULT_MODE = "bypass"` at `68dcba1` (2026-08-05), so those five ran with the
fixed default in the tree. **BELIEVED, and the gap is real:** no artifact records whether those
dispatches took the mode from the default or from an explicit `--permission-mode`, because the
`spawned` event records only the resolved value. On the same evidence the 2026-09-09 drill is equally
undetermined (`state/events.jsonl` records `mode: "bypass"`, and `succ_mode` is the same expression
that feeds `argv`, so the event faithfully reports the argv and not the branch that supplied it).

**MEASURED.** The origin and lifetime of the sentence this wave exists to retire. `skills/fleet/SKILL.md`'s
*"no live drill has run under the fixed default, so the route is a CANDIDATE, not a proven one"*
entered at **`b9957f7`, 2026-07-30** (`git log -S"no live drill"`) — **true then**, six days before the
first post-fix completion. It has been **false since 2026-08-05T16:48:54Z**. It was then **re-landed
verbatim on 2026-09-09 by `5d11f99`**, whose diff shows that line being edited: new context wrapped
around it, the stale clause preserved character for character.

**So the sentence I landed, everywhere, is the narrower one:**

> The claim moved by the handoff path **for the first time on this host and on POSIX**, on
> `server/persistent-fleet`, on a **quiet fleet with no lane in flight, at ~169k, at a boundary the
> outgoing body chose for itself.** It is not the first completion anywhere. One green run in that
> shape says nothing about a handoff at 400k with workers mid-task, which is the case the protocol
> exists for.

**BELIEVED** in that sentence: "~169k" and "a boundary it chose" come from the outgoing and incoming
bodies' own journal prose. There is no independent occupancy artifact I can read; I did not measure it
and I am not asserting it as measured.

---

## 1. THE EVENT ITSELF — what I could establish independently, and what I could not

I was told not to take the supervisor's word. Here is each artifact and what it is worth.

### 1.1 The live claim — MEASURED

`"/home/altai/.venv/china-infra/bin/python3.12" bin/fleet.py sup-status --json`, read-only against the
live home, and `supervisor/INCARNATION` read directly. Both agree:

    incarnation_id  inc-20260909T174911Z-efa0
    session_id      f9b83beb-41c1-4fa0-8a0e-968b0d3d98ac
    claimed_at      2026-09-09T17:49:36Z
    claimed_via     handoff
    lineage_id      lin-20260909T162943Z-6040
    nonce_seq       3            (1 at transfer; rotated twice since)
    handoff_pending []           handshake  null       abort_flag  false

### 1.2 `claimed_via: "handoff"` — MEASURED, one creator, and here is the enumeration

`grep -n '"claimed_via"' bin/fleet.py` returns five sites and no dynamic assignment exists (no
`claim["claimed_via"] = …` anywhere): `:16130` writes `"fresh"`, `:16179` writes the seize /
limit-transfer verdict, `:17428` copies the field into `sup-release`'s released record, `:17486` is a
key list, and **`:19041` is the only site that can ever write the string `"handoff"` — inside
`cmd_sup_handoff_complete`.** Receipt W4.

**What that verb requires before it writes:** `_require_claim_holder` (the caller holds the claim, with
a valid nonce); a `supervisor/HANDSHAKE` present; `hs["incarnation_id"] == --expect-inc`; and
`hs["handoff_token_hash"] == claim["handoff_token_hash"]`, fail-closed when the claim carries no token.
Only `sup-handoff-begin` (`:18554`) ever mints that hash.

**Two ways the value could exist without a genuine succession, and I am naming them because the brief
asked me to say so loudly if any existed:**

1. **MEASURED, and it is not a code path: `supervisor/INCARNATION` is a JSON file.** Anyone with shell
   access can write `"claimed_via": "handoff"` into it. Every conclusion here is rooted in "nobody
   hand-edited the claim file", which no artifact can establish.
2. **BELIEVED, and it is a real forgery shape: a SELF-handoff.** A live claim holder can run
   `sup-handoff-begin` (minting a token and a task file), write `supervisor/HANDSHAKE` itself carrying
   that token and its own `nonce_hash`, and then run `sup-handoff-complete`. Nothing in the token
   verification distinguishes that from a real successor, because the predecessor legitimately holds
   the plaintext token. `claimed_via: "handoff"` alone therefore proves *the completion verb ran*, not
   *that a second body exists*.

**Neither weakens THIS event, and the reason is corroboration rather than the string.** §1.3–§1.5.

### 1.3 A SECOND, INDEPENDENT WITNESS THAT DOES NOT READ `claimed_via` AT ALL — MEASURED

`mint_lineage_id()` stamps `datetime.now(timezone.utc)`. `grep -n 'mint_lineage_id()' bin/fleet.py`
returns its definition and **exactly two call sites** — `:16132` (the fresh claim) and `:16181` (the
seize / limit-transfer arm). `cmd_sup_handoff_complete` calls neither: it writes
`"lineage_id": claim.get("lineage_id")`, carrying the predecessor's. Receipt W5.

**Therefore a claim whose `lineage_id` timestamp strictly predates its own `claimed_at` cannot have
been produced by `fresh`, `seize` or `limit-transfer`.** The live claim reads
`lin-20260909T162943Z-6040` against `claimed_at: 2026-09-09T17:49:36Z` — **80 minutes apart.** The
`resume` arm preserves both fields together, so it cannot manufacture the gap either. This is a
structural witness in a *different field*, produced by a *different code path*, and it agrees.

### 1.4 A second body demonstrably existed — MEASURED

`state/events.jsonl`, which is written by the dispatch and hook paths rather than by the supervisor's
prose:

    {"ts":"2026-09-09T17:49:14Z","kind":"spawned","name":"sup|inc-20260909T174911Z-efa0|successor",
     "cwd":"/home/altai/proga/fleet","mode":"bypass"}
    {"ts":"2026-09-09T17:49:14Z","kind":"turn_started", … "session_id":"f9b83beb-…"}
    {"ts":"2026-09-09T17:49:36Z","kind":"turn_started", … "session_id":"f9b83beb-…"}

and the registry carries three supervisor-shaped records with **three distinct sids** — the predecessor
`sup|inc-20260909T162927Z-147a|boot` at `c903f29a-…` (idle) and the successor
`sup|inc-20260909T174911Z-efa0|successor` at `f9b83beb-…` (working, `last_activity` 17:49:36Z, the
stamp `cmd_sup_handoff_complete`'s seam #2 writes). `fleet doctor` independently lists `f9b83beb` among
live `claude` agent sessions. The two `turn_started` events at 17:49:14 and 17:49:36 are the
successor's own boot and the transfer's stamp — two writers, one sid.

**This closes the self-handoff shape for this event**, and it closes it on evidence the supervisor did
not author.

### 1.5 The journal — MEASURED that it says this, and it is a RECORD, not a witness

`supervisor/JOURNAL.md` carries `HANDOFF-BEGIN` at 17:49:11Z, `HANDOFF-COMPLETE` at 17:49:36Z (both
under the predecessor's inc and sid), then `CHECKPOINT` entries at 17:49:58Z and 17:52:07Z under the
successor's. **I use it for counting and for the sid/inc pairs, and I do not use it as a second
witness to the transfer**: it is the claim-holder's own append-only account, and both sides of this
handoff wrote into it. Its value here is that it is *git-tracked*, so its August entries can be shown
to have been committed contemporaneously — `5b0a17a` (2026-08-06) and `3929848` (2026-08-10) — and are
not a later reconstruction. That check is what makes the 6-for-6 count trustworthy.

### 1.6 The §5.9 discharge — MEASURED absent, and the unlinkers named

| artifact | state | unlinked by |
|---|---|---|
| `state/supervisor-handoff-inc-20260909T174911Z-efa0.md` | **absent** (no `state/supervisor-handoff-*` exists at all) | `unlink_handoff_task_file(args.expect_inc)` at `:19074` in `cmd_sup_handoff_complete`; also `:18668` (dispatch failed), `:19160` (`--retire-all`), `:19252` (abort). `sweep_handoff_task_files` at `:19077` takes earlier attempts' files. |
| `supervisor/HANDSHAKE` | **absent** | `handshake_path().unlink()` at `:19070` in `cmd_sup_handoff_complete`; also `:16167` (the seize/limit-transfer arm's stale-HANDSHAKE hygiene) and `:19244` (abort). |
| `state/supervisor-handoff-aborted.json` | **absent** | never written on this path. Written only by `sup-handoff-abort` (`:18613`, `:19166`, `:19260`) and **cleared by the next `sup-handoff-begin`** (`:18602`). Its absence means no abort was recorded, not that a cleanup ran. |

### 1.7 The git record — MEASURED

`server/persistent-fleet` at `1294920`; `bin/fleet.py`'s last change is `803a9a3`, authored
2026-09-09T17:33:36Z — **16 minutes before the transfer.** So the code I read is byte-identical to the
code that ran the handoff (`diff` of `server/persistent-fleet:bin/fleet.py` against this worktree's:
identical). That is worth stating: my code-path enumeration is about the executed program, not a later
one.

### 1.8 What I could NOT establish

- **BELIEVED only:** the occupancy (~169k) and that the boundary was chosen rather than forced.
- **Not establishable:** that the claim file was never hand-edited.
- **Not establishable from artifacts:** whether the successor's `bypass` came from the default or a
  flag — for this drill or for the five before it.
- **Not attempted:** anything about a handoff under load. Nothing here speaks to it.

---

## 2. THE DOCTOR FINDING — REFUTED AS STATED, AND THE REFUTATION IS A MEASUREMENT

The brief handed me a derived claim: `[FAIL] identity-witness: LEAK` is **structural to every handoff**,
because a predecessor is alive when it dispatches, so a `--bg` daemon is already live and cannot have
idle-exited, so **"a successor's stamp can never name the successor"** and the row is always red. I was
told to attack step 3.

**MEASURED, and it does not need step 3 attacked at all.** I ran `fleet doctor` from inside **this
lane**, which is nobody's successor and has no relationship to any handoff:

    [FAIL] identity-witness: LEAK: … Witness: 'sup|inc-20260909T162927Z-147a|boot'
           (a registry record, status idle). Registry verdict for my sid
           'ffb7903b-4595-4387-b4b9-8119e0fbbc4e': 'w59-proven'.

**Same row, same shape, same foreign witness, no handoff involved.** `daemon.lock`: pid 119225,
`startedAt` 2026-09-09T16:29:31Z, `spawnedBy.label "claude --bg"`, `cwd /home/altai/proga/fleet` — the
predecessor supervisor's own dispatch founded the daemon, and **every `--bg` body hosted by it since
reads that founder's name**, successor and ordinary worker alike.

**So the finding is real but its subject is wrong.** It is claim-nonce §18, ratified 2026-07-30, and
`skills/fleet/SKILL.md` already carries it as a bullet ("*the daemon SUBSTITUTES the FIRST dispatch's
whole environment…*"). The handoff successor is one instance of a class, not the cause of one. The
sentence *"nobody could have known that before, because no handoff had ever completed"* is doubly
wrong: handoffs had completed, and the class was known and documented six weeks earlier.

**Step 3 is separately refutable, and I record this even though it is now redundant.** It conflates
*"the predecessor is alive"* with *"the predecessor is `--bg`-hosted"*. `sup-boot` is a verb any session
can run; a supervisor need not be daemon-hosted, and the daemon's liveness is keyed on live `--bg`
sessions, not on the claim holder being alive. **BELIEVED:** with a non-`--bg` predecessor and no live
workers, the daemon may have idle-exited, and `sup-handoff-begin`'s dispatch would found it with
`_worker_env(successor_name)` — witness == registry, row **GREEN**. `DAEMON_ENV_LEAK_REMEDY` names that
escape in its own words ("*or ensure the supervisor's own dispatch is the one that starts it*"). I did
not test it; I could not, from inside a hosted session.

**The operationally true version, which is what should be carried:** on a persistent server fleet — a
`--bg` supervisor plus live workers, which is this design — the row is red for the successor's whole
generation, and doctor's stated remedy (let the daemon idle-exit) cannot run. That is exactly the shape
root `CLAUDE.md` warns "trains the operator to ignore the row that will one day be real". **It is a
grading question about `identity-witness` in general, not about handoff, and it is code — see
RECOMMENDATION 1.**

---

## 3. `docs/specs/graceful-succession.md` — what I amended, site by site

Ratified text left verbatim in every case; each amendment is a dated box or a struck-through cell in
the pattern `w58-docs` used in this file (§1.2, §5.8) and that §10.1 O9 already used for a table row.

**§5.7 `:1094` row ("currently UNREPAIRED") and `:1103–1117` box ("stillborn on every attempt").** One
dated box after the box, because the row already says "see below". Four points: the route was repaired
at `87cbf9a` and **this document already recorded that in §10.3** — the file has carried its own
discharge and its own stale claim side by side since 2026-07-30; *"stillborn on every attempt"* was
**correct when written and the qualifier is what made it correct** — the claim was about
`sup-handoff-begin` **under its shipped default**, which is 17/17 exactly right, and was never a claim
that the route had never completed (the journal holds **9 completions before that box was written**);
the eight are all pre-fix and the post-fix record is 6-for-6; and the sentence the drill earns is the
narrower one. **This is the distinction the brief asked for and it is not a hedge:** the box's
present-tense reading is dead, its past-tense reading about the eight is true, and the qualifier
"under its shipped default" is the hinge between them.

**§7's Q `:1417` — the premise is dead and the answer survives, and I checked rather than assumed.**
The **No** rests on *"every dispatching arm routes through `_dispatch_supervisor_body` and never through
`sup-handoff-begin`"* — a statement about which function calls which, true at 0-for-8 and at 6-for-6
alike. Deleting the premise costs the answer nothing, and **§10.3 says so in its own words** (*"designed
not to need the answer and still does not"*). Two clauses around it do move:

1. the word **"broken"** in *"depending on the broken mechanism to succeed"* is now wrong; the safety
   argument never rested on the adjective;
2. **the refusal's trade CHANGES SIGN, in the refusal's favour.** When the route always failed, refusing
   recovery on a minted `handoff_token_hash` cost a real window — it held off recovery for a succession
   that was not going to happen. Now the same refusal waits on a mechanism that works and usually
   resolves in under a minute. **The refusal is better justified after the repair than before it**,
   which is the opposite of the intuitive reading;
3. and a caveat the ratified text does not carry: **`sup-recover` is SPECIFIED AND UNBUILT** —
   `grep -c 'sup-recover' bin/fleet.py` returns **0** at `1294920` (receipt W6). The **No** is a claim
   about a design, not a measurement of a shipped call graph.

**§10.1 O13 `:1849`.** Struck the "Revisit if" cell in the O9 pattern and said which half moves. **The
condition it names is MET** — repaired 2026-07-27, 6-for-6 since — so "unrepaired" is retired. **What is
NOT restored is "PREFERRED":** a route that works is not thereby the route to prefer, that word was
ratified out, and re-earning it is an operator judgement about routing under a keeper, not a
consequence of one drill. **The routing half is untouched** and the drill says nothing about it — and
with `sup-recover` unbuilt there is no shipped call graph to re-derive it against either way.

**§9.4 — six new receipts, pinned `# at 1294920`** (deliberately a different pin from R1–R14's
`cebae4f`, because they are claims about the record *as it stood when the succession landed*).
**MEASURED:** `tools/verify_receipts.py --self-test --strict docs/specs/graceful-succession.md` →
`34/34 reproduce exactly (36 fenced blocks, 0 unclassified, 0 volatile-skipped)`, `VERDICT: pass`,
`SELF-TEST VERDICT: PASSED` on both seed classes, `EXIT: 0`.

**`:1355` — THE BRIEF MIS-ANCHORED THIS ONE AND I LEFT IT ALONE.** The quoted phrase *"a fleet that has
never run…"* does occur there, but the full sentence is *"a fleet that has never run **supervisor
doctrine** sees `[PASS]` forever"* — it is §6.3's row 0 about a resting fleet with no GOALS, and it has
nothing to do with the handoff record. Its premise is untouched and it needs no amendment. Editing it
would have been a change made because a grep matched.

---

## 4. WHAT THE RECEIPT HARNESS CAN AND CANNOT HOLD — read before pasting, as instructed

**MEASURED from `tools/verify_receipts.py` and `tests/test_receipts.py`:** a receipt is executed
against a **materialised commit tree** (`git archive <sha>`), or against the working repo under
`# live: <reason>`; `# volatile: <reason>` means the evidence lives outside the repo, drift only WARNs,
and `tests/test_receipts.py` passes `skip_volatile=True` so **the suite never executes it at all**.

**Therefore: a one-time live event on one host is NOT receiptable by this harness.** Everything that
carries the succession as a *live* fact — `supervisor/INCARNATION`, `sup-status --json`,
`state/events.jsonl`, `~/.claude/daemon.lock`, `fleet doctor`'s row — is in gitignored `state/` or
outside the repo entirely, so no materialised tree contains it and `# volatile` would buy a warning
nobody runs. I said that in §9.4 rather than manufacturing a block.

**What IS receiptable, and this is the useful half:** `supervisor/JOURNAL.md` is **git-tracked and
append-only**, so the counts that carry my headline are ordinary pinned receipts and will keep
reproducing forever. That is why §0's numbers are receipts and §1's live readings are attributed prose.

---

## 5. `docs/SPEC.md` §18 — three stale clauses, and the argued disposition of the pinned one

Appended a dated amendment to the server persistent-fleet entry; nothing above it edited.

1. **`fleet sup-notify` is SHIPPED.** **MEASURED:** `grep -c "sup.notify" bin/fleet.py` → **8** at
   `1294920`, verb in `build_parser()` (`:22284`) with its own dispatch arm (`:22475`). **And the
   entry's pinned clause is TRUE:** `git grep -c "sup.notify" 2a15dec -- bin/ tests/ docs/` returns
   nothing, re-verified.
   **The argued disposition, since both answers are defensible:** the sentence splits. *"is UNSHIPPED at
   `2a15dec`"* is **pinned past-tense evidence about when the gap existed** and falls squarely under
   this repo's ratified rule — *"a pinned receipt and a quoted argument are claims about a PAST tree and
   are still true"* — so editing it would destroy the only record of that. *"so the behaviour binds and
   the spelling is provisional"* is an **unpinned present-tense inference** about the current tree, and
   it is now false; leaving it makes a status entry lie. **Keep the pin verbatim, correct the inference
   beside it.** The test of the ratified rule is that it *cuts a sentence in two* rather than choosing a
   side — and applying it that way is what shows the rule was applied rather than cited.
2. **The keeper clause is DISCHARGED. MEASURED:** `bin/fleet_keeper.py:211-212` types
   `KEEPER: … Report state, then relaunch with sup-spawn; do not await the operator.`, and the module
   docstring (`:16-20`) names the predecessor text it replaced. Both halves of *"the prose and the code
   disagree"* are gone.
3. **The succession is recorded**, in the narrow form of §0, with its limits attached.
4. **The general finding, which I was asked to name and which I think is the most transferable thing
   here:** *two lanes in one merge cannot describe each other's state, and an honest hedge is not a
   reconciliation.* `w58-docs` wrote the clause correctly, pinned it, and flagged it *"reconcile at
   merge"*. `w58-notify` shipped the verb. Both merged in one range, and the hedge shipped as a **false
   present-tense sentence** in a status entry and as a `⚠ NAME UNSHIPPED` warning in the file an
   interface session reads at startup. **A hedge names a debt and assigns it to the merging tier; no
   lane can discharge it from inside its own fence.** The merging supervisor recorded that it did not
   reconcile.

**One scope judgement, declared rather than buried:** the brief named `skills/fleet/SKILL.md` line ~109.
I also discharged the `⚠ NAME UNSHIPPED — reconcile at merge` marker **two lines above it in the same
file**, because it is the identical defect the brief sent me to fix in SPEC §18 and leaving a false
warning in the startup file while correcting it elsewhere would have been a worse outcome than a
slightly wider edit. If that is out of fence, revert that one hunk; nothing else depends on it.

---

## 6. `skills/fleet/SKILL.md` — what changed and what deliberately did not

**Changed:** the "unproven / eight stillbirths / prefer release-then-spawn" opener is quoted as retired
rather than deleted; the CANDIDATE clause is replaced by the measured record, the origin and lifetime of
the false clause, and the narrow sentence with its limits inline; the dangling *"the cautious order
above still applies"* now names what still justifies caution (**nobody is watching if the successor is
stillborn — a claim about who is present, not about the mechanism**); the `sup-notify` marker is
discharged; and the daemon-leak bullet gained the measured note that a successor's red
`identity-witness` row is the general leak, not a handoff defect.

**Deliberately unchanged, as instructed and because both are still correct:** the *"0 turns, no
transcript"* **RETRACTION** and *"diagnose a stillborn body by whether the claim moved, never by turn
count"*; and the whole `dontask`/`bypass` 17/17 autopsy.

---

## 7. `knowledge/` — one entry, one pointer

`knowledge/lessons.md#2026-09-09-handoff-proven`, appended at the TOP (the file is append-at-top; cited
by anchor, never by line), **with its matching one-line `knowledge/INDEX.md` pointer added in the same
change** — the w58 entry shipped without one and had to be repaired.

**Of the four candidate lessons the brief offered, one is kept as given, one is kept inverted, one is
corrected, one is kept and sharpened:**

- *"A failure count stops being evidence about the present once its cause is named and fixed"* — **kept**
  (it is the prior wave's lesson and it holds).
- *"...but only a live drill retires the word unproven"*, and *"the CANDIDATE sentence was CORRECT the
  whole time"* — **BOTH REFUTED.** Five live drills ran and the word did not move; the sentence was
  correct for **6 days** and wrong for **35**. **A drill retires nothing; a COUNT retires it.**
- *"The tier that runs the protocol is the only one that can retire a claim about it"* — **INVERTED.**
  It is the **worst** placed: it grades its own event and its evidence is its own journal. The record
  was fixed by a fenced lane with no stake, doing arithmetic.
- The doctor finding — **kept, with its subject corrected** (§2).
- The two-lanes-one-merge gap — **kept** (§5.4).

Plus three the evidence produced: the premise/answer separation (§3), the receipt-harness boundary
(§4), and the second-witness technique (§1.3) — *when one field is the whole proof, look for a second
field whose value SHAPE only one path can produce.*

---

## 8. SUITE — predicted in writing before the run, then measured on both interpreters

**Invocation:** `uv run --no-project --python 3.1x --with pytest python -m pytest -q`. (Root
`CLAUDE.md`'s `py -3.13` line is about the retired Windows host — see RECOMMENDATION 3.)

**Baseline re-measured by me at `1294920`, not inherited:** `6 failed, 4857 passed, 16 skipped,
1 xfailed` = **4880 collected**, py3.12, 337.59s. Same six host-assumption failures the brief explains.

**PREDICTION, written into the journal before the post-edit run: 4880 collected, 6/4857/16/1
UNCHANGED.** The brief said a docs-only landing moves the floor *by construction*. **I predicted it
would not, and derived it rather than defaulting to it:**

- `tests/test_receipts.py` parametrises `@pytest.mark.parametrize("path", _specs())` — **one item per
  spec FILE, not per receipt** (`:246`, `:619`, `:646`). MEASURED: the module collects 64 items and
  exactly 3 mention `graceful-succession`. `RECEIPT_FLOOR` is a **floor**, and a spec "may GAIN receipts
  freely" — 14 → 34 extracted moves nothing.
- `tests/test_doc_claims.py::CHECK_COUNT_DOCS = current_tree_docs()` **is** a glob over tracked
  markdown — but `docs/lanes/` is one of `_HISTORICAL_PREFIXES` (`:447`), so a new lane report adds no
  items, and every other file touched was already tracked. `ENTRY_DOCS` is a fixed tuple containing
  none of my surfaces.
- Nothing parametrises over `knowledge/lessons.md` anchors or `knowledge/INDEX.md` lines.

**MEASURED, after the edits:** *(filled in below at §8.1.)*

**One live pin caught a real defect in my own prose, and it is worth recording:**
`TestCollaboratorInstall::test_shipped_surfaces_hardcode_no_absolute_fleet_home[skills]` went RED
because I quoted `task=C:/proga/claude-fleet/…` into `SKILL.md` as *evidence about the retired host*.
The lint is right and the quote was rephrased. **A citation of a path is indistinguishable from a
hardcoded path to a lint, and the lint is the one that ships.**

### 8.1 Measured floors

*(see §11)*

---

## 9. RECOMMENDATIONS — for the operator, not filed as gates, not ticked, no box touched

**R1 — `identity-witness` grading, and it is CODE so it is outside my fence.** On a persistent server
fleet the row is red for every `--bg` body that did not found the daemon — measured on this lane, and on
the handoff successor. Doctor's own remedy (let the daemon idle-exit) cannot run while workers are live.
The two honest shapes are (a) demote the LEAK row to a NOTE when the witness names a record that exists
and the acting sid resolves cleanly — i.e. when the disagreement is fully explained by §18 — or (b)
leave it red and accept that the row is decorative on this host. **Both are grading changes to shipped
code and neither should be originated by a lane or by a body on the turn it inherits the claim.** The
cost of doing nothing is the one root `CLAUDE.md` names: an operator trained to ignore a red row.

**R2 — the O13 word "PREFERRED" is yours, not a lane's.** The condition O13 names ("repair the handoff
path") is met. Whether the ratified downgrade is *reversed* is a routing judgement under a keeper, and
"spec promotion (no author self-promotion)" is a standing gate. I retired "unrepaired" and left
"PREFERRED" unrestored.

**R3 — root `CLAUDE.md` carries a wrong Python rule for this host.** `py -3.13` is the retired Windows
launcher; no interpreter on this box has pytest importable, the china-infra venv included. Reported and
left, as instructed. The working invocation is in §8 and in three lanes' reports now.

**R4 — `supervisor/JOURNAL.md` is 1.9 MB, git-tracked, and is now load-bearing evidence.** The 6-for-6
count only survives because its August entries can be shown to have been committed contemporaneously.
Nothing enforces that it stays append-only. Not a gate I am filing; a fact worth knowing.

---

## 10. FENCE — MEASURED

*(see §11 for the diffstat, produced after the final commit.)*

`bin/fleet.py`, `bin/fleet_keeper.py`, `tests/**`, `supervisor/GOALS.md`, `docs/OPERATOR-GATES.md` and
root `CLAUDE.md` are **read-only in this lane**. No gate ticked, no Settled line added, no gate filed —
G-K1, G-K2 and G-K4 stay open and untouched. No push, no merge, no ref moved but `w59/proven`.

---

## 11. WHERE THIS BRIEF WAS WRONG

The brief asked for this section and predicted its own most likely error correctly.

1. **"I have overstated 'proven'" — YES, and by more than the brief expected.** The brief's own
   fallback was *"the claim moved by the handoff path once, on a quiet fleet, at 169k"*. The record is
   further from "proven" than that: the route had already completed **fourteen** times, **five of them
   under the fixed default**, before this drill. The honest headline is **first on this host**, not
   first at all.
2. **"the ninth attempt; the eight prior are the recorded stillbirths" — WRONG.** It was the **26th**
   `HANDOFF-BEGIN` and the **15th** `HANDOFF-COMPLETE`. The eight stillbirths are a real and correctly
   counted set, but they are the eight *pre-fix* begins with no terminal event — not "the eight prior
   attempts".
3. **"0-for-8 is now 1-for-9" — WRONG**, for the same reason. Post-fix it is **6-for-6**.
4. **`skills/fleet/SKILL.md`'s "no live drill has run under the fixed default" was not merely
   awaiting a drill — it had been false for 35 days**, and was re-landed verbatim on 2026-09-09 by an
   edit to that very line.
5. **The doctor finding's step 3 did not need attacking, because the CONCLUSION is refutable one level
   up.** The row is not handoff-structural at all: I measured the identical red row from inside this
   lane, which is nobody's successor. *"Nobody could have known that before, because no handoff had ever
   completed"* is wrong twice over — handoffs had completed, and `SKILL.md` already carried the class.
   Step 3 is separately weak (it conflates "alive" with "`--bg`-hosted"), which I record even though it
   is now redundant.
6. **The `:1355` site was mis-anchored.** The matching phrase is *"a fleet that has never run supervisor
   doctrine sees `[PASS]` forever"* — §6.3's resting-fleet row, unrelated to the handoff record and
   needing no amendment. I left it alone rather than edit a grep hit.
7. **"I may be wrong that the §1417 Q's answer survives its premise dying" — the brief was right that
   this is the interesting question, and the answer is that it survives**, because the **No** was
   grounded in call structure, not in the route's health. The brief did not anticipate that one of the
   answer's supporting clauses **changes sign and gets stronger** after the repair, nor that
   `sup-recover` is still **unbuilt**, which qualifies the whole exchange.
8. **"A docs-only landing moves the floor by construction" — not here.** Derived from the
   parametrisation before running: `test_receipts.py` counts spec FILES, `docs/lanes/` is exempt from
   `CHECK_COUNT_DOCS`. See §8.
9. **The brief was right about the receipt harness.** A live-event receipt is not possible; the
   git-tracked journal counts are, and that is the useful half. Nothing was forced.
10. **The brief was right that `sup-notify` is shipped, that the keeper says "relaunch", and that the
    two-lanes-one-merge gap is the general finding.** All three measured and landed.

