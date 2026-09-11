<!-- lane-report-root: docs/lanes -->

# `docs/lanes/` — where a lane's report lives

**A lane's report is committed on the lane's own branch, at `docs/lanes/<lane-name>.md`, and
arrives on `main` with the merge that lands the lane's work.**

That one sentence is the whole convention. The rest of this file is why it is a *rule* rather
than a habit, because the habit was tried and it lost three reports in a single campaign.

## The defect this directory exists for

`state/` is gitignored (`.gitignore:1`) and a git worktree gets its **own** `state/`. A lane
told to write its report to `state/journals/<name>.md` therefore writes it into a directory
that is in no commit and that dies with the worktree — and the path is *relative*, so which
`state/` it lands in depends on the lane's cwd rather than on anything the instruction said.

Three instances, all in the wave-44→47 campaign:

1. **`w44-ceil` report §8** carried the prepared `supervisor/GOALS.md` replacement text. The
   pointer was relayed four times (`supervisor/JOURNAL.md:6200`, `:6230`, and the gate verdict
   `state/verdicts/w45-gceil.md:598`). **The artifact is gone.** Measured: no `w44-ceil` file
   in `state/journals/`; the lane's worktree `C:/proga/fleet-w44-ceil` has no `state/`
   directory at all; and the only commit in all of history containing the replacement's band
   heading is `ee62ecd`, the docket entry that *records the loss* — the search for the text
   now finds only its own obituary. An operator ruling is blocked on it
   (`docs/OPERATOR-GATES.md`, gate opened 2026-08-08).
2. **Slice a3's self-report**, lost outright when its registry record was archived. Its
   adversarial gate had to audit the branch from the code instead of from what the lane claimed.
3. **The a2 gate's verdict**, 38,815 bytes, survived *only* because a supervisor noticed and
   hand-copied it to the main tree. Nine advisories in its §6 would otherwise have gone unread.

## Why this shape and not another

**Why committed on the lane's branch.** A lane's report is an artifact *of that branch's work*:
it is the lane's claim about the diff, written for the adversarial gate that reads the diff.
Committing it makes durability a consequence of the thing the lane already must do — commit and
be merged — rather than an extra step somebody has to remember. Nothing new can be forgotten.

**Why not copy-on-death.** It is one more thing that can be forgotten, and it cannot run at all
when the death is the machine losing power. This fleet was dead 2.7 days this week for exactly
that reason. A durability scheme that requires the dying process to act is not a durability
scheme.

**Why not "just always use the absolute `$FLEET_HOME/state/journals/` path".** It is a genuine
improvement over the relative form — it survives worktree removal — and the machine-generated
preamble already does it. It is still not durable: the path is gitignored, `fleet clean` deletes
journals irreversibly by design, `fleet archive` moves them into `logs/archive/`, and none of it
is in any commit or any backup. It converts "dies with the worktree" into "dies with the
machine", which is the failure this fleet actually suffered.

**Why not `knowledge/`.** `knowledge/` is git-tracked and would be durable, but it holds the
fleet's *distilled* lessons — the notes-to-your-next-self that the learning loop curates. Lane
reports are raw primary evidence, high-volume and one-per-lane. Mixing them would drown the
index that `knowledge/INDEX.md` exists to keep readable. A lane's *lesson* still belongs in
`knowledge/lessons.md`; its *report* belongs here.

## Journal and report are different artifacts — do not conflate them

This is the conflation that caused the loss. Keep them apart:

| | **Journal** | **Report** |
|---|---|---|
| Path | `$(fleet home)/state/journals/<name>.md` | `docs/lanes/<name>.md` on the lane's branch |
| Written by | the lane, continuously; also `bin/hooks/postcompact_journal.py` | the lane, once, at the end |
| Audience | the lane's own next session after a respawn or compaction | the adversarial gate, the supervisor, and every later reader |
| Lifetime | scratch — may be archived or cleaned | permanent, arrives on `main` with the merge |
| Durable? | **no, and that is correct** — it is working state | **yes, by construction** |

The journal stays in `state/`. It is high-churn machine-written working state and committing
every compaction landmark to git would be noise. The mistake was never that journals live in
`state/`; it was that briefs ordered the *report* into the *journal file*.

## Gate verdicts — the one case this shape does not fully cover

An adversarial gate works in a **detached** worktree that is never merged, so its verdict has no
merge of its own to ride. The verdict belongs to the branch it gates. Land it as
`docs/lanes/<gate-name>.md` **on the branch under gate**, so it arrives with that branch's merge
and the gated work and the verdict on it land together. If the branch is rejected and never
merged, commit the verdict to `main` directly — a rejection is exactly the outcome whose reasons
must outlive the branch.

## Rescued reports

A report recovered by a retro-sweep from a worktree it was about to die in is committed here with
a `RESCUED` provenance header naming where it was found and which branch it describes. A rescued
report's presence here says nothing about whether its branch merged.

## Conventions

- One file per lane, named for the lane: `docs/lanes/<lane-name>.md`.
- Write it MEASURED/BELIEVED per line, and include a `WHERE THIS BRIEF WAS WRONG` section — the
  gate reads that first.
- Commit it on the lane's branch, in the lane's own commits. Do not stage it to `main` by hand;
  hand-copying is the failure mode this directory replaces.
- `docs/lanes/BRIEF-TEMPLATE.md` carries the deliverables stanza to paste into a lane brief.

## Pinned

`tests/test_lane_report_durability.py` pins that this location is tracked and not ignored, that
`state/` really is ignored (so the premise above stays true), and that the surfaces which instruct
lanes do not point a report at a disposable path. It cannot check that a future lane obeyed the
convention — no test can — so it checks the instructions instead.
