# Operator docket — the durable digest

**For: Altai. FIVE gates are open. None of them is blocking any work — but read G-K6 FIRST: it was raised on 2026-09-10 out of an outage that had your fleet dark for 8h10m overnight while the keeper, watching, paged nothing. G-K5 is still the one about the priority you sent on 2026-09-09.**

*(Count corrected 2026-09-10 from FOUR to FIVE by supervisor `inc-20260910T041513Z-181d`, in the same turn that raised G-K6 — the digest going stale at the moment a gate is filed is the precise failure root `CLAUDE.md` warns about, and the previous digest was allowed to sit stale at three gates while four were open.)*

**THIS FILE IS NOT THE RECORD.** The record is [`docs/OPERATOR-GATES.md`](../OPERATOR-GATES.md) —
tracked, authoritative, carrying every open gate in full with its filer's own reasoning, plus every
settled gate since 2026-07-27. This file exists so that a one-screen digest of what is waiting for
you survives a machine failure, which the previous digest could not. **Where the two disagree, the
gates file wins.** Nothing here is ticked; only Altai ticks a box.

*Written 2026-08-09 by lane `w51-initprep`. No gate text was edited, nothing was ticked, and no gate
was re-litigated — each recommendation below is the one already on file from the incarnation that
raised the gate, attributed and compressed, never a new opinion.*

*Updated 2026-09-08 by the `server/persistent-fleet` fix wave. **The four gates this digest was
first written for were all answered by Altai on 2026-08-10** and now sit under `## Settled` in the
gates file; their sections are kept below as history, marked. The three gates listed here are the
ones the kz-work server design filed (G-K1, G-K2, G-K4 of
`docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md` §7). G-K3 — the server
interface running in bypass — was ruled with the design itself and is already settled. Same
discipline as the first pass: no gate text edited, nothing ticked, each recommendation the filer's
own.*

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

## The five open gates

*(G-K6 is written up in full in the record, `docs/OPERATOR-GATES.md`; the one-line ask is at the bottom of this file. It is deliberately not re-narrated here — this digest is pointers and the filer's own recommendation, never a second copy of the gate text.)*

| # | In one line | Blocks | Recommendation on file |
|---|---|---|---|
| G-K1 | Is the keeper typing `KEEPER:` lines into `work:fleet` inside D7's pull-only intent? | nothing (the keeper is built and its unit is not installed) | rule it INSIDE D7, and say so in D7's own text |
| G-K2 | Two failures stay silent under the ccgram-only ruling — accept, or permit one out-of-band path? | nothing | accept both as known blind spots for the soak week |
| G-K4 | Does `supervisor/briefs/` become a git-tracked home for standing briefs? | the standing brief S5 dispatches | approve the directory |

---

### G-K1 — the keeper types into `work:fleet`; is that inside D7?

**The question:** D7 (`docs/specs/terminal-surface.md`, 2026-07-22) says fleet injects nothing into
any session — it is pull-only, because a globally-enabled SessionStart hook leaked this fleet's
gates and worker table into every unrelated project on the machine. The keeper types one-line
`KEEPER:` pages into a tmux window. **Is that an injection surface, or is it outside D7's subject?**

**What the design already constrains** (`§3.3`, "Doctrine check, rule by rule"): the keeper types
into ONE dedicated window whose sole purpose is fleet, which the keeper itself launched with the
server interface profile; it never touches another session, never installs a hook, and never fires
in a session that did not opt in. Nothing reaches a session an operator did not create for fleet.

**Recommendation on file (the design's author, folded into the spec rather than assumed): rule it
INSIDE D7's intent and amend D7 to name it**, rather than leaving a reader to infer that a rule
saying "fleet injects nothing" has an unwritten exception. The design deliberately files this as a
gate instead of treating it as obviously permitted — the standing rule from gate 4 below (a slice
may not derive a normative deliverable from prose the spec never defines) applied to itself.

**Nothing is waiting on it.** The keeper is built and tested; its systemd unit is not installed.

---

### G-K2 — two silent failures under the notify-only-via-ccgram ruling

**The question:** ruling 2 (yours, 2026-09-08) says outbound notification goes only through the
ccgram-bound `work:fleet` window. Two failures then tell nobody: a **login expiry** that also kills
the interface window (the keeper's page has nowhere to land), and a **failed `fleet-keeper` unit**
(nothing observes the observer — `systemctl --user status` is the only witness). **Accept both as
known blind spots, or permit one out-of-band alert path later?**

**What the fix wave changed about the shape of this:** the keeper now distinguishes a missing
`claude` binary from an expired login and pages each with its own remedy, so the *diagnosable* half
of the login mode reaches you whenever the window is alive. The blind spot is narrower than filed,
and it is still real: it is exactly the case where the window is gone too.

**Recommendation on file (the design's author, §5 "Failure modes"): accept both for the soak
week** and record every real page in `docs/operator/keeper-soak-2026-09.md`. A second outbound path
is the thing ruling 2 exists to prevent, and one week of measured pages is what would justify
re-opening it — a decision better taken with the soak's evidence than before it.

---

### G-K4 — `supervisor/briefs/` as a git-tracked home for standing briefs

**The question:** the server standing brief (`supervisor/briefs/server-standing.md`) is what the
interface session dispatches with `sup-spawn --task @…`. It
must survive a reboot, a dead supervisor and a dead interface session. **(Amended 2026-09-09: this used to read "when you say `revive` from the phone". Under the succession ruling and its amendment the interface also dispatches that brief on a `KEEPER: … relaunch` page, with no operator keystroke — which makes the durability argument below stronger, not weaker: the brief is now read on a path where nobody is watching. The gate itself is UNCHANGED and still OPEN; nothing here ticks it.)** `state/` is gitignored and
disposable — the exact plane this whole docket was moved OUT of. **Approve a git-tracked
`supervisor/briefs/`, or keep briefs under `state/tasks/`?**

**Recommendation on file (the design's author, §3.2): approve the directory.** The brief carries no
task of its own — the plan lives in `supervisor/JOURNAL.md`, which is the point of a persistent
identity — so it is stable text, reviewed once, dispatched many times. Keeping it in `state/` would
repeat the failure this digest exists because of: an artifact three supervisors depended on, living
in one disposable directory on one machine.

**This one has work behind it:** S5 (the first revival from the phone) dispatches that brief.

---

### G-K5 — "independent per repo/dir": is the flag/env sense what you asked for?

*Raised 2026-09-09 by supervisor `inc-20260909T174911Z-efa0` from your own Telegram priority, relayed
by the interface. Measured evidence: `docs/lanes/w59-slice-e.md` §6.2. Recommendation below is the
filer's, as this file's discipline requires — the audit lane deliberately recommended nothing.*

**Your words:** *"how far away are we from multi fleet? it should be independent per repo/dir, this
is a high priority and should be done asap"*. That sentence has two readings and the fleet has built
exactly one of them.

**Reading A — built, as of this wave.** Each repo gets its own home, reached by `--fleet-home <path>`
or `FLEET_HOME`, and **created by the new `fleet init --home`**, which merged today (slice (b), the
last unbuilt multi-fleet slice). Before it, an armed machine had *no shipped path to create a second
home at all* — four routes, all exit 1 — so the feature was unreachable rather than merely
unpolished. That is fixed.

**Reading B — does not exist.** A session whose cwd is `/home/altai/proga/X` reaches X's fleet with
**no flag and no env**. `resolve_home` consults flag → sid lookup → `FLEET_HOME` → terminus and
**never reads the working directory**; the only two `cwd` sites in `bin/fleet.py` both belong to
`fleet index`. Building it means a **new §5 resolution step**, which is a spec amendment only you
ratify.

**Three things Reading B would have to clear**, none of them fatal, all of them real:
1. It is a **marker step**, and multi-fleet §9 is that design's graveyard. A live lint bans the
   marker across five files, for the stated reason that *a stale marker could silently redirect the
   CLI — `fleet clean` and `fleet kill` included — at a different fleet's registry.*
2. **Linked worktrees.** A cwd walk-up would resolve a lane's worktree to its parent checkout's home
   unless it stops at `.git`, the way `find_index_root` already does for the index.
3. It adds a **fourth spelling of "which home"** whose answer can disagree with the other three,
   where §5's design is deliberately one order for every caller.

**Filer's recommendation: A is probably what you want, and it is done — try it before ordering B.**
`fleet init --home /home/altai/proga/X/.fleet` then `--fleet-home` (or an exported `FLEET_HOME` per
shell) gives independent per-repo fleets today. If typing that per shell is the actual friction, say
so and B becomes worth its three collisions; if it is not, B buys a fourth way to be wrong about
which fleet you are killing. **No lane has built any of B, and every brief this wave forbade it.**

## Settled 2026-08-10 — the four gates this digest was first written for

*Kept as history, not as a docket. Altai answered all four in-session through the interface on
2026-08-10; each answer, in full, is under `## Settled` in `docs/OPERATOR-GATES.md`, which is the
record. Nothing below is waiting on anybody.*

### Gate 1 (settled: approve the drafted reconstruction) — the `supervisor/GOALS.md` §8 replacement text

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

### Gate 2 (settled: narrow the clause) — the scope of `--yes` in multi-fleet §5 step 1

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

### Gate 3 (settled: split `init` the same way) — does the E2 ground reach `init --home`?

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

### Gate 4 (settled: the word is vestigial, dropped) — what was slice (c)'s `witness` meant to be?

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

1. **G-K1** — is the keeper's one dedicated window inside D7, or does D7 need amending to say so?
2. **G-K2** — accept the two silent failures for the soak week, or permit one out-of-band path now?
3. **G-K4** — approve a git-tracked `supervisor/briefs/`? *(the standing brief S5 dispatches lives
   there)*
4. **G-K5** — "independent per repo/dir": is `--fleet-home`/`FLEET_HOME` per repo (built today)
   what you meant, or do you want cwd to decide the home with nothing typed? *(the second needs a
   new §5 step and your ratification)*
5. **G-K6** — the keeper cannot see a supervisor that has stopped acting but whose session is still
   listed. **Now a choice of THREE, not two** — the lane sent to measure it refuted my framing:
   **C (recommended)** arm the rule on `status == "busy"` instead of on mere presence (would have
   paged 7h10m51s earlier, no new false positive, keeps C2's guard); **A** drop the roster arm
   (= C minus the safety); **B** give the supervisor a wake mechanism (prevents rather than detects;
   do C first, because B's own failure is silent). *(This is the one that already fired — twice in
   one day. And eight hours was the LUCKY case: a body retired `idle-prompt` stays in the keeper's
   list with no expiry observed, and 2 of 3 retired supervisors here did. It also makes G-K2's list
   of "two silent failures" a list of three.)*

Answer any of them in one line in `docs/OPERATOR-GATES.md`, or through
`fleet sup-decision --answer <text>` for whatever is occupying the supervisor's decision slot.

---

## Related, and separate from the docket

`docs/operator/fleet-init-recipe.md` — a prepared, measured recipe for running `fleet init` on this
home, which has never been run here. **It is not a fifth gate**: it is a deploy you approve or
decline in one line, nothing is degrading while it waits, and it asks you no question about ratified
text. It does touch gate 3's subject matter (`init`), but only the shipped, flagless `init` — it
neither depends on nor prejudges that ruling.
