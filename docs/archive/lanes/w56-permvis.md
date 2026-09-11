# `w56-permvis` — pricing the durable fix for the `fleet spawn` mode default

**Filed 2026-09-09 by lane `w56-permvis`, branch `w56/permvis`, at `1a7b3ca`.**

**THIS IS NOT A GATE AND NOTHING HERE IS TICKED.** Three operator gates (G-K1, G-K2, G-K4) have sat
unanswered since 2026-09-08 and the supervisor is deliberately not raising a fourth. This memo
exists so that when one *is* raised, it is raised as a priced question rather than as a discovery.
Same discipline as [`docs/operator/gate-docket.md`](../operator/gate-docket.md): every
recommendation below is attributed to this lane, no settled gate is re-litigated, and nothing in
`docs/OPERATOR-GATES.md` is touched.

**Scope.** This lane BUILT the detector in commit `1a7b3ca` — a permission-denied worker is no
longer indistinguishable from a fast one. It did **not** implement any option below, by instruction.

---

## 1. The measurement, and it is now 20 for 20

`bin/fleet.py:14133` already carries the July record: `dontask` was the supervisor default for six
days, and **10 of 10 successors dispatched under it were stillborn against 7 of 7 under `bypass`**.
That fix moved `SUCCESSOR_DEFAULT_MODE` (`bin/fleet.py:14167`) and `SUP_SPAWN_DEFAULT_MODE`
(`:14178`) to `bypass`. Its verdict on the mode is the sentence this campaign keeps re-earning:

> Do NOT "restore" dontask to close the hang class: it trades a loud wedge for a silent death,
> which is strictly worse and cost three days.

**The worker surface never got the fix.** `p_spawn.add_argument("--mode", choices=list(MODE_FLAGS),
default="dontask")` is at **`bin/fleet.py:21765`** and still carries the retired value, with a
comment calling it *"the safest non-hanging, non-blanket-bypass choice"* — reasoning written before
the measurement existed. Nothing warns: `skills/fleet/SKILL.md:39`, the verb table a supervisor
reads before dispatching, spells `--mode` as optional and names no default at all, so a dispatcher
who omits it does not know what it is choosing.

On 2026-09-09 three workers were dispatched at that default. All three were born unable to act:
`w55-suite`, `w55-nonce`, `w55-recon`, each `mode=dontask`, each `turns=1`, each now `dead`. Their
transcripts carry `toolDenialKind: "permission-rule"` 11, 3 and 3 times. **17/17 becomes 20/20, zero
exceptions, across two independent incidents seven weeks apart.**

What `dontAsk` actually does is the whole story and it is worth restating because two documents in
this repo still get it wrong: **it does not prompt, it DENIES.** Anything outside the allow-list is
refused immediately. There is no hang to notice.

---

## 2. Option A — default the worker surface to `bypass`

One line at `bin/fleet.py:21765`, matching both supervisor surfaces. It is the only option supported
by a measurement, and the measurement is unanimous.

**The cost, stated honestly, because it is not a consistency fix.** Both supervisor surfaces run a
supervisor **body in `FLEET_HOME`**, under the three-tier §10.2 earned-privilege doctrine — and that
doctrine is *explicitly scoped to the fleet repo*:

> It runs under **bypass** permission mode **in the fleet repo** (earned-privilege doctrine) —
> stated explicitly in GOALS before it ever runs unattended.
> — `docs/specs/three-tier-command.md:1221`

Two things in that sentence do not transfer to a worker. First, **the repo**: a worker runs wherever
`--dir` points, which is by design an arbitrary repo on this machine, not necessarily one the
operator wrote or audited. Second, **the acknowledgement**: the supervisor's bypass is gated on a
prose acknowledgement in `supervisor/GOALS.md`, enforced by `_warn_missing_bypass_ack`
(`bin/fleet.py:17728`). No equivalent exists for the worker surface, so defaulting workers to
`bypass` would grant unattended `--dangerously-skip-permissions` in arbitrary directories with
**nothing anywhere recording that the operator agreed to it.**

That is a security posture change and it should be argued as one. It is defensible — every worker on
this fleet is dispatched by the operator or by their supervisor, into a directory the dispatcher
named — but it is a different claim from "make the three surfaces agree," and shipping it as the
latter is how a posture change lands unnoticed.

---

## 3. Option B — ship a real `permissions.allow` block in the template

**Correction first, because the premise this option is usually stated on is false in three places.**
`docs/SPEC.md:375`, the fleet-index M2 entry, says this is owed:

> **M2** = `fleet q` symbol lookup + source slicing, blocked on `worker-settings.template.json`
> gaining `permissions.allow: ["Bash(fleet q:*)"]` and the `fleet init` migration that implies
> (default mode is `dontask` @8478 and the template ships no permissions block, so a default
> worker's call would hang unanswerable).

Measured at `1a7b3ca`:

1. **The template already ships that block.** `worker-settings.template.json` line 2 is
   `"permissions": { "allow": ["Bash(fleet q:*)"] }`, landed 2026-07-27 in `1844a1f`
   (*"feat(index): M2 worker-facing surface — teach lines, `--context` digests, the template
   grant"*). The rendered instance on this host carries it too. **M2's own blocker is discharged**
   and the entry has read as open for six weeks.
2. **"@8478" is stale.** The spawn default is at `:21765`; `bin/fleet.py:8478` is a comment inside an
   unrelated function.
3. **"would hang unanswerable" is the wrong failure.** `dontAsk` denies; it does not hang. This is
   the exact confusion `SUCCESSOR_DEFAULT_MODE`'s comment was written to correct — *"CORRECT ABOUT
   HANGS AND WRONG ABOUT DENIALS"* — and it survived into the SPEC entry that motivates this option.

So B is not "ship a block", it is **widen the one-entry block that already exists**, and that
reframing is what prices it — because **B in its current form has already been measured, and it
failed.** The live instance on this host carried exactly `Bash(fleet q:*)` when the three workers
died. `w55-suite`'s own report names it:

> `state/worker-settings.json` for this fleet lane only grants `"Bash(fleet q:*)"`. Nothing else is
> allowlisted, and this session is in a mode that auto-denies anything not allowlisted rather than
> prompting.

**The cost, and it is structural rather than a matter of effort.** Every gap in the list is a new
silent denial — which is precisely the failure the detector in `1a7b3ca` was built to make loud, so
B trades a class of incident for a smaller, quieter version of the same class. And the list cannot
be completed: the template is **fleet-wide** while the working set is **per-repo**. A worker sent
into a Python repo needs `uv`/`pytest`, a Node repo `npm`, a Rust repo `cargo`; the same worker
needs `git`, and this fleet's own briefs additionally require `sed`, heredocs, pipes and chaining —
all of which the measured incident found denied. There is no finite fleet-wide allow-list that makes
an arbitrary brief in an arbitrary repo executable, so B cannot be a complete fix **at the layer it
is proposed for**. It is a good *per-repo* practice and it is worth doing; it is not the durable
answer to the default.

**The `fleet init` migration B implies is real and unavoidable if the block is widened**: every
existing instance was rendered from the old template, `fleet doctor` already grades
`instance-freshness` and `instance-grants`, and a widened template makes every installed instance
stale until re-rendered. That is a cost of B, not an argument against it, and it is the same cost the
already-shipped one-entry grant paid in July.

---

## 4. Option C (a third shape) — retire the default rather than change it

Make `--mode` a **required** argument of `fleet spawn`. No worker is then ever born under a mode
nobody chose, which is the actual defect: nothing in the 2026-09-09 incident *decided* on `dontask`,
it was inherited from a line whose comment predates the evidence against it.

**Pro:** no posture change at all, so it needs no gate — it is the one option here an operator can
approve without deciding anything about security. It makes the mistake impossible rather than merely
visible, which is a stronger guarantee than the detector this lane shipped.

**Cost, countable.** Every caller that omits `--mode` breaks. Measured at `1a7b3ca` across the
tracked tree (excluding `tests/`, review transcripts and `supervisor/JOURNAL.md`, which are records
of past acts and not callers):

| where | what it is |
|---|---|
| `skills/fleet/SKILL.md:39` | **the one that matters.** The verb table the supervisor reads, which spells `--mode` as optional — `[--mode bypass\|accept\|dontask\|plan\|omit]` — names no default and carries no warning. This is the surface that produced the 2026-09-09 dispatch. |
| `docs/getting-started.md:164` | the `hello` quickstart, a new operator's first spawn |
| `docs/launch-readiness.md:172` | a `--max-budget-usd` refusal receipt |
| `docs/operator/fleet-init-recipe.md:220` | the `canary-w51` install canary |
| `docs/operator/keeper-soak-2026-09.md:264` | the `canary-srv` install canary — the one wave 55 recorded as passing *because it ran `date`* |
| `docs/specs/fleet-index.md:160`, `docs/superpowers/specs/2026-07-22-fleet-index-design.md:191`, `docs/superpowers/plans/2026-09-08-server-persistent-fleet.md:1780` | `--context` / plan examples |

`README.md:16` is **not** in this list: its example already passes `--mode bypass` (on the
continuation line), as do `docs/getting-started.md:200` and `:261-263`. Each break is a one-line
edit and several are receipts pinned by `tools/verify_receipts.py`, so they move as deliberate
re-pins. The risk is missing one and turning a silent death into a loud refusal at dispatch — which
is strictly better, but still a break.

**Option D**, for completeness and this lane does not recommend it: keep the default and have
`cmd_spawn` warn when `mode == "dontask"`. Precedent exists — `cmd_spawn` already warns about deny
rules at `bin/fleet.py:6585` (*"a deny beats mode ..."*). It is the cheapest possible change and it
is the weakest: a warning printed into a headless dispatch is read by whoever reads dispatch output,
and on 2026-09-09 that was a supervisor session that dispatched three workers in ten seconds.

---

## 5. Is any of them plainly wrong?

**Keeping the default is plainly wrong.** 20/20 fatal across two incidents is not a close call, and
the comment at `bin/fleet.py:21765` justifying it (*"the safest non-hanging, non-blanket-bypass
choice"*) is a claim the evidence has refuted twice: it is not non-hanging-and-safe, it is
non-hanging-and-dead.

**B alone is plainly insufficient**, on its own evidence — it was the configuration under test when
the three workers died. That is not an argument against widening the list; it is an argument against
counting it as the answer.

**A and C are both defensible.** They differ in who decides: A decides once, centrally, and accepts
a posture change; C refuses to decide and pushes the choice to each dispatch.

**A fact that constrains all four:** for a *headless* worker there is no bounded-and-working mode.
`bypass` works. `dontask` denies silently. `accept` and `plan` prompt, and a prompt in a `--bg`
session is the T12 hang class the July fix was originally written for. So "a safe middle" is not
something the mode vocabulary (`bin/fleet.py:1906`) currently offers — B is the only shape that
could manufacture one, and §3 is why it cannot at the template layer. Any answer that assumes a safe
middle exists is assuming something this fleet has not built.

---

## 6. Recommendation

**This lane recommends Option A — default the worker surface to `bypass` — on one condition: that it
ships with the acknowledgement gate, not without it.**

Grounds:

1. **It is the only option with evidence behind it.** 20/20. Every other option is reasoning, and
   this exact question has now been decided by reasoning twice and been wrong both times.
2. **It is the option that matches what the operator already does.** Both supervisor surfaces are
   `bypass`. The three workers that survived 2026-09-09 (`w55-suite-b`, `w55-nonce-b`,
   `w55-recon-b`) were re-dispatched under `bypass`. The default is not protecting anything today;
   it is producing dead workers that the operator then re-dispatches under `bypass` by hand.
3. **The condition is what makes it a posture change rather than a slip.** §2's objection is real and
   the answer is not to dismiss it but to satisfy it: extend the existing `_warn_missing_bypass_ack`
   mechanism (`bin/fleet.py:17728`) to the worker surface, so an unattended bypass worker is
   dispatched only from a fleet whose `supervisor/GOALS.md` says the operator accepted it. That
   mechanism is already built, already ratified (operator ruling 2, 2026-07-24), and already warns
   rather than refuses — the brittleness argument for warning-not-refusing applies unchanged.
   **Without the condition this lane does not recommend A**, because a one-line default change with
   no record that anyone agreed to it is exactly the shape §2 warns about.

**If the operator declines the posture change, take C.** It is strictly better than the status quo,
needs no ruling, and costs four one-line edits. **Take B in addition to whichever is chosen, never
instead of it** — and when it is taken, correct `docs/SPEC.md:375` at the same time, because M2's
stated blocker was discharged in July and the entry has been reading as open ever since.

---

## 7. Two defects found while pricing this, neither fixed here

1. **`docs/SPEC.md:375`** — the fleet-index M2 entry, wrong on three counts (§3 above): the template
   grant it names as a blocker already shipped, its `@8478` citation is stale, and it describes the
   `dontask` failure as a hang when it is a denial. Not edited: this lane's fence is the detector and
   this memo, and the entry belongs to whoever holds the M2 slot.
2. **`knowledge/INDEX.md:4`** cites `bin/fleet.py:21451` for the spawn default. It was already stale
   at `dba0868` (the line was `:21529` there, an offset of 78) and this lane's own commit moved it
   further, to `:21765`. Not edited: `knowledge/` is the campaign's shared plane and a knowledge wave
   owns it. Flagged rather than fixed, and flagged loudly, because the brief that produced this lane
   names stale citations as *"this campaign's most-repeated defect"* and this one is a citation of
   the very line this memo is about.
