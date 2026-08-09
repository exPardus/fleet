# Operator docket — the durable digest

**For: Altai, on his return. Four gates are open. None of them is blocking any work.**

**THIS FILE IS NOT THE RECORD.** The record is [`docs/OPERATOR-GATES.md`](../OPERATOR-GATES.md) —
tracked, authoritative, carrying every open gate in full with its filer's own reasoning, plus every
settled gate since 2026-07-27. This file exists so that a one-screen digest of what is waiting for
you survives a machine failure, which the previous digest could not. **Where the two disagree, the
gates file wins.** Nothing here is ticked; only Altai ticks a box.

*Written 2026-08-09 by lane `w51-initprep`. No gate text was edited, nothing was ticked, and no gate
was re-litigated — each recommendation below is the one already on file from the incarnation that
raised the gate, attributed and compressed, never a new opinion.*

---

## Why this file replaces `state/w48-operator-docket.md`

The previous digest lived at `state/w48-operator-docket.md`. Measured 2026-08-09:

```
git check-ignore -v state/w48-operator-docket.md   ->  .gitignore:1:state/
git ls-files --error-unmatch state/w48-operator-docket.md
    ->  error: pathspec ... did not match any file(s) known to git
```

It was gitignored and untracked — one copy, on one machine, in the same disposable plane that has
already destroyed three lane reports in this campaign (see `docs/lanes/README.md`), on a fleet that
was dead 2.7 days this week to a power cut.

**Two further facts found while relocating it, both of which shaped this file's form:**

1. **The gates themselves were never at risk.** `docs/OPERATOR-GATES.md` is tracked and carries all
   four open gates, gate 4 included. This was a perishable *digest*, not perishable *data*.
2. **The old digest had gone stale.** It opens *"Three gates are open"* and covers gates 1–3; gate 4
   was added afterwards by the wave-49 supervisor. Relocating it verbatim would have committed a
   false count into the tracked tree.

So this is deliberately **a pointer-and-recommendations digest, not a second copy of the gate
text.** Two files claiming to be the record is the defect this campaign keeps re-finding, and the
gates file already carries every word of reasoning below at full length.

**The old file is superseded and may be deleted at your convenience.** Every surviving reference to
its path is in `supervisor/JOURNAL.md` — seven lines, all dated records of what a supervisor did on
a given day. Those are correctly left alone: this repo's own ratified rule is that a claim about a
past tree is not rot, and a record of an act is corrected by appending, never by rewriting. No brief
template, skill, or instruction surface ever pointed a reader at that path.

---

## The four open gates

| # | In one line | Blocks | Recommendation on file |
|---|---|---|---|
| 1 | The `supervisor/GOALS.md` §8 replacement text | nothing | approve the drafted reconstruction |
| 2 | Scope of `--yes` in multi-fleet §5 step 1 | nothing | narrow the clause |
| 3 | Does the E2 ground reach `init --home`? | **build slice (b)** | split `init`, as `homes` was split |
| 4 | What was slice (c)'s `witness` meant to be? | nothing (row parked) | ratify the built row, conditional on repair — *held loosely* |

---

### Gate 1 — the `supervisor/GOALS.md` §8 replacement text

**You already ruled the substance** (2026-08-08): apply the §8 band replacement **in full** rather
than numbers-only, because the block carries three defects — the superseded 150–200k band, a false
`[UNBUILT]` tag on the §11.3 dispatch refusal (shipped `c6fde34`, widened `d969de3`), and the
conflation of the BUILT supervisor arm with the genuinely unbuilt worker arm — and **yes**, add
`supervisor/GOALS.md` to the pin's `SURFACES`.

**Why it is still open:** the "prepared text" that ruling was to be executed against **does not
exist**, measured four ways by the wave-47 supervisor. It was written into a gitignored
per-worktree `state/` path and died with the worktree — the same defect this digest is being moved
away from.

**Also on the record, and it changes what you are answering:** the "paste verbatim" and "no lane may
originate GOALS.md content" clauses were the *interface's* safeguard around an artifact it believed
existed, not your words. A safeguard around a missing artifact is not a ruling.

**Recommendation on file (wave-47 supervisor, carried by three successors): approve the drafted
reconstruction.** It was drafted against your own three-defect specification, with every number
re-derived from `band_thresholds` and every build-state claim re-derived by grep. It is parked,
committed, and correctly **not applied**.

- Draft: `docs/proposals/2026-08-09-goals-band-section-replacement.md` (commit `4f5d5fe`) — verified
  present on the tracked tree 2026-08-09.
- `supervisor/GOALS.md` is untouched and has **not** joined `SURFACES`, deliberately, so no pin goes
  RED with nobody permitted to repair it.
- **You are approving CONTENT, not method.**

---

### Gate 2 — the scope of `--yes` in multi-fleet §5 step 1

**The defect:** §5 step 1 says a mutating verb on a flag/registry disagreement "refuses without
`--yes`", as though every mutating verb has that flag. **Three of thirty-three do.** Measured end to
end through `main()`: `fleet --fleet-home <B> clean --yes` → rc 0, while `archive --yes`,
`autoclean --yes` and `sup-handoff-abort --yes` each exit 2 with an argparse usage error. For 30 of
33 verbs, the remedy the operator is shown does not exist.

This is the R2 class — *a refusal that names a remedy the machine will not accept*. Slice a3 built a
test specifically to prevent it, which missed this by construction because it drove the disagreement
with `clean`, one of the three verbs where `--yes` does exist.

**Recommendation on file (wave-47 supervisor, concurring with the `w47-ga3` gate): NARROW the
clause** — say the escape exists only where the verb already carries `--yes`. Two grounds. On a
disagreement the operator has already named a home and the registry disagrees, so the informative act
is to drop the flag or name the right home, not to confirm harder. And promoting `--yes` globally
would collide with the destructive tier's deliberate refusal to honour it, putting one flag on two
surfaces with opposite meanings.

**Not parked on you:** the misleading message itself was already repaired (the `--yes` sentence now
prints only for verbs that have the flag). What needs your ruling is the ratified sentence in §5,
which no lane may edit.

- Full measurement: `state/verdicts/w47-ga3.md` §B2 *(gitignored — the gate's own argument is
  restated in full in `docs/OPERATOR-GATES.md`)*.

---

### Gate 3 — does the E2 ground reach `init --home`?

**The question:** you ruled `homes --add`/`--retire` DESTRUCTIVE on the E2 ground — an irreversible
append to the machine-global `~/.claude/fleet-homes.list`, which only the fold reverses — while
`fleet homes` (the read) stays ORDINARY. Multi-fleet §4 names `init --home` as a **second writer of
that same file**. `init` is ratified wholly ORDINARY. Does the split reach it?

**Nothing contradicts today.** Re-verified 2026-08-09 against `bin/fleet.py`'s parser: `init` carries
`--nonce`, `--statusline`, `--chain`, `--force` and **no `--home`**. Slice (b) is unbuilt and the
ratified ordinary row is true of the shipped tree.

**This is the one gate something is waiting on:** slice (b) is the next build slice in Sequencing §3
and it would ship the flag.

**Recommendation on file (wave-47 supervisor, from the `w47-homes` lane's measurement): split `init`
the same way**, using the shipped `doctor --repair` idiom — flagged tokens in the destructive tuple,
the bare verb in **no** tuple, tier carried in `VERB_EFFECT_RESIDUAL`. That form fails SAFE (drop the
flagged tokens and the verb is unclassified, hence destructive) where the naive two-row form fails
OPEN. The lane verified that the shipped tree already implements exactly that idiom for `homes`.
Ruling before (b) is built is cheaper than retrofitting after.

---

### Gate 4 — what was slice (c)'s `witness` meant to be?

**The question:** Sequencing §3 names build slice (c) as *"hook argv + witness"*, but the word
`witness` occurs exactly twice in the whole multi-fleet spec and neither occurrence defines a
hook-plane witness. The (c) lane derived a new `fleet doctor` row (`home-witness`) from that prose
and built it.

**Where it stands:** the row did **not** land. Slice (c) shipped the ratified mechanism only — hook
argv, the successor-render argv, and a sibling fix the gate independently endorsed. The complete row,
its tests and the lane's derivation are preserved on branch **`w49/home-witness`** (`da04c80`) with a
re-land recipe at `docs/lanes/w49-home-witness.md` **on that branch** — verified readable 2026-08-09.

The row's measured defects are why it is parked: it parses `--fleet-home` with a third grammar
agreeing with neither the hooks' nor `fleet.py`'s, so a correctly fenced instance is reported as
unfenced with a remedy that would not fix it; and three of its design decisions survived the full
4217-test floor unpinned.

**Recommendation on file (wave-49 supervisor): ratify the derived row as slice (c)'s witness,
conditional on the repair landing first** — one grammar shared with the hooks and `fleet.py`, plus
pins for the three unpinned decisions. **The filer explicitly held this loosely**, and said why:
*you* ratified the sentence, so only you can say what `witness` in slice (c) was meant to name. The
alternative readings are unbuilt.

---

## The one-line asks

1. **Gate 1** — approve the drafted §8 text, supply your own, or take the numbers-only fallback?
2. **Gate 2** — narrow §5's `--yes` clause, or promote the flag globally?
3. **Gate 3** — split `init` on the E2 ground, or keep it wholly ordinary? *(unblocks slice (b))*
4. **Gate 4** — ratify the derived row conditional on repair, specify what (c)'s witness should be,
   or rule the word vestigial?

Answer any of them in one line in `docs/OPERATOR-GATES.md`, or through
`fleet sup-decision --answer <text>` for whatever is occupying the supervisor's decision slot.

---

## Related, and separate from the docket

`docs/operator/fleet-init-recipe.md` — a prepared, measured recipe for running `fleet init` on this
home, which has never been run here. **It is not a fifth gate**: it is a deploy you approve or
decline in one line, nothing is degrading while it waits, and it asks you no question about ratified
text. It does touch gate 3's subject matter (`init`), but only the shipped, flagless `init` — it
neither depends on nor prejudges that ruling.
