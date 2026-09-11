# `w49-fold` — the knowledge fold for waves 44–48

**DONE.** Research/docs lane. Worktree `C:/proga/fleet-w49-dcap`, branch `w49/dcap` at `c228d69`. Mode bypass.

**Every line is MEASURED unless it says BELIEVED.** Nothing under `knowledge/` is re-executed by
`tools/verify_receipts.py`, so every command quoted below is pinned to the commit it ran at, and I
have preferred derived claims over pasted receipts throughout. No line-number citation into any
rolling document appears anywhere in what I wrote — anchors only, per this repo's own rule.

**Changed:** `knowledge/lessons.md` (+78), `knowledge/INDEX.md` (+6/−2), `knowledge/playbooks/campaign-template.md` (+22/−1), and this report. No other tree touched.

---

## 0. THE ANSWER

Four new `knowledge/` artifacts and one correction:

| what | where |
|---|---|
| The fold's own finding — why lessons recur | `lessons.md#2026-08-09-fold-44-48` |
| Wave 48 | `lessons.md#2026-08-09-w48-fences` |
| Wave 46 | `lessons.md#2026-08-09-w46-fidelity` |
| Wave 45 | `lessons.md#2026-08-09-w45-ceiling-pins` |
| A dated correction appended to wave 47's entry | inside `lessons.md#2026-08-09-w47-slice-a` |
| Four INDEX lines + one swept stale claim | `INDEX.md` |
| Process changes, nine of them | `playbooks/campaign-template.md` **v1.11** + a routing header |

**The single most important thing I found is not in any wave.** It is that the mechanism standing
goal 4 relies on has been disconnected for sixteen days, and that the disconnection is *structural
rather than negligent* — §3 below.

---

## 1. SCOPE — the brief's "waves 44–48" is right about the span and wrong about the debt (MEASURED)

**Wave boundaries: the brief's 44–48 span is CORRECT.** `supervisor/JOURNAL.md` carries no `WAVE N`
headers — waves are supervisor incarnations, and I derived the boundaries from `BOOT`/`SEIZED`/
`RELEASED` lines rather than from the prose:

| wave | incarnation | opened | closed |
|---|---|---|---|
| 44 | `inc-20260805T173144Z-e447` | 2026-08-05T17:35:03Z | handoff 19:32:48Z |
| 45 | `inc-20260805T193255Z-4ee5` | 19:36:12Z | RELEASED 22:24:12Z (operator stand-down) |
| 46 | `inc-20260806T005348Z-e7a3` | 2026-08-06T00:53:48Z | **died** — last checkpoint 01:09:11Z |
| 47 | `inc-20260808T173852Z-5dc6` | SEIZED 2026-08-08T17:38:52Z | RELEASED 23:20:08Z |
| 48 | `inc-20260808T232242Z-ae09` | 23:22:42Z | RELEASED 2026-08-09T01:47:59Z |

**But only THREE of the five were unfolded.** Waves 44 and 47 already had entries
(`#2026-08-06-w44-landing`; `#2026-08-09-w47-slice-a` plus `#2026-08-08-docket-and-outage`). I
established that by grepping `lessons.md` for tokens that could only exist in an entry for the
missing waves rather than by reading for absence — `2.1.226`, `4217`, `instance-freshness`, `gceil`,
`gpins`, `c2572`, `238a477`, `1be5bea`, `5ebba74`, `7c3e48b`, `launch rehearsal`, `gap 8`,
`merge -F`, `not a fence` — **every one returning 0**, measured at `c228d69`.

**One near-duplicate caught by that grep and NOT re-recorded.** `fork-steer` returns 9 hits, so a
naive "is it folded?" check would have passed. All nine are the *other* fork-steer findings — sid
rotation under a live claim, the unstamped claim-holder's ceiling exemption, and the wave-35
brief-store truncation. **None is wave 48's defect**, which is that a *correctly written* task file
is never re-read. I recorded it with an explicit "related but NOT the same as" pointer to
`#2026-07-31-w35-brief-store` rather than as a fresh discovery.

**The existing wave-46 coverage is about the outage, not the wave.** `#2026-08-08-docket-and-outage`
records the 2.7-day gap and its known cause correctly. Wave 46's own sixteen minutes of work — which
produced the finding that created the `docs/lanes/` convention — was nowhere. My entry cross-links
rather than restates the outage.

---

## 2. WHAT I FOLDED, PER WAVE

Full text is in the entries; this is the ledger so a reader can see what was judged worth keeping.

**Wave 45** — the 400k ceiling landing (`238a4778`, floor 3936 predicted and hit both interpreters)
and `1be5beac`; three adversarial gates, **two returning a blocking defect the full suite could not
see**. The backwards self-citation range (`cmd_respawn:7443-7343`) and its **four independent
structural blindnesses**, including the lane's own control being of the wrong *shape* — a
one-wave-old lesson failing against its own author. The dated-line carve-out that exempted every
candidate line on one of a pin's two surfaces, so a parametrised green certified a file with no
coverage. And a lane re-planting from a verdict that noticed the verdict's *quoted* mutant was
weaker than its own prose.

**Wave 46** — `fleet result` at 3,117 bytes against a 38,815-byte verdict, with the dispatching
brief asserting they were the same document; the gitignored per-worktree `state/` write that caused
it, and the archival that later destroyed the result entirely. The `instance-freshness` doctor row
proved a **consequence-free false alarm by rendering rather than by reasoning** (sha256-identical,
846 chars), with the remedy filed and **still unbuilt three waves later** — and wave 48's wrinkle
that the same row fires *correctly* on a branch that really changes the template. The superseded-band
pin passing 4/4 while the file the boot ritual loads first stated the dead band, because `SURFACES`
did not list it.

**Wave 48** — `FLEET_HOME` is not a fence, and the correction to that correction (§4). The
containment audit clean for the wrong reason. Gate coverage measured **by withholding**, and the
discharge finding the uncovered class is wider than grammar. The fork-steer defect with its honest
epistemics (*prior greens were samples that got lucky*). Three mutants surviving a 4217-test suite
while the audited lane's own table was **truthful**. The pin tier's skip count proved zero and the
stamp deliberately held. `git merge -F -` at rc 129. Three more instrument failures, all caught by
controls, one of them a tool timeout stranding a mutant on disk.

---

## 3. THE FINDING THE BRIEF ASKED FOR: why the lessons recur (MEASURED)

The brief's central ask was *"a process change per entry"*, on the grounds that several of these
lessons have now recurred two and three times, *"which means the lesson was recorded and the process
was not changed."* That is correct, and it has a measurable mechanism.

`knowledge/playbooks/campaign-template.md` §8 makes amending itself **required to close** a knowledge
wave; §3(h) says in terms that *"a lessons entry with no process change is rejected."* Measured at
`c228d69` by `git log` over each path:

- **`knowledge/lessons.md`: 37 commits since 2026-07-25.**
- **`knowledge/playbooks/campaign-template.md`: ZERO.** Last touched **2026-07-24** (`f67f875`),
  still declaring **v1.10**.

So fifteen supervisor waves recorded their lessons and amended the instrument not once, while the
instrument's own closing checklist says they must.

**The honest diagnosis is not negligence, and this is the part that matters.** The supervisor era
does not run the campaign-template pipeline at all — it runs waves, lanes and adversarial gates,
whose doctrine lives in `docs/lanes/BRIEF-TEMPLATE.md` (created wave 47 at `e5889fe`, amended wave 48
at `44f056e`), `docs/lanes/README.md`, `skills/fleet/supervisor.md` and the ratified specs. **That
channel is alive and is being amended.** The process-change channel did not die; it **moved**. What
nobody did was tell the template, which still opens by declaring itself *"a LIVING instrument…
every campaign amends it."*

*A doctrine file that is merely stale is a cost. A doctrine file that is stale **and still claims to
be the live one** routes every future process change into a dead drop* — which is precisely the
shape of "the lesson was recorded and the process was not changed."

**Applied here** (this is the one process change I was able to execute rather than name, because
`knowledge/**` is my fence): the template carries a **ROUTING header** naming the live instrument for
lane-era work, is bumped to **v1.11** with nine amendments drawn from waves 44–48, and §8's closing
item now reads *"amend the LIVE instrument"* with a sub-item that requires you to **record which file
and version you bumped, or record explicitly that the lesson has no mechanical remedy and why.**

**A second structural cause, visible only from doing this fold.** Entries here are single paragraphs
of 400–900 words with the finding buried mid-sentence, and INDEX lines have grown into the same
shape — so answering *"has this already been recorded?"* costs a full read of a 1,700-line file, and
the cheap alternative is to record it again. Three of the items I was told to look for turned out to
be *sharpenings* of lines already present rather than new facts, and I could only establish that by
grepping distinctive tokens. New entries now lead with a bolded, independently greppable claim
sentence. **I did not retrofit the old ones** — rewriting dated records to fix a lookup problem is
the exact failure this file already names.

---

## 4. THE CORRECTIONS — three, each appended and never rewritten

**(a) A dated line in wave 47's entry is now false, and its stated mechanism was always wrong.**
`#2026-08-09-w47-slice-a` closes *"One defect FILED, NOT FIXED"* about the `fleet_lock` Windows
EACCES escape. Measured: **it landed at `f402895` in that same wave** (`git merge-base --is-ancestor
f402895 HEAD` → yes), so the line was true when written and false hours later. And the mechanism it
gives — *a contender racing the holder's `unlink()`* — was measured wrong by the lane that fixed it:
`unlink()` alone does not usually produce delete-pending on Win10 1809+, the window needs a third
party holding a handle without `FILE_SHARE_DELETE`, and the exception carries **`winerror=None`**, so
a fix keyed on `winerror == 5` could never have fired. **Appended as a dated correction; the original
paragraph is deliberately untouched.**

**(b) I swept for the value, not the sighting.** The same *"filed not fixed"* claim also sat in the
`INDEX.md` line for that entry. This repo has already paid for fixing a wrong figure at the surface
where it was noticed while the same figure sat elsewhere (the "four months" case). Both sites now
carry the correction; the INDEX one is corrected in place because INDEX is a current-state pointer
rather than a dated record of an act, and a stale claim there is read at every session start.

**(c) The journal and the lane report disagree about the wave-48 slice-(c) gate, and the report
wins.** The brief told me to prefer the report and to say so when I found a disagreement. I found
one, and it is substantive. Wave 48's closing checkpoint recorded that gate **from peeks** while it
was still running — hedging honestly that a peek is ephemeral — and wrote two claims into the
successor queue that the committed verdict (`w48/gc:docs/lanes/w48-gc.md`, 629 lines) contradicts:

| the journal says | the verdict says |
|---|---|
| *"Attack F CONFIRMED — a real breakage… This must be discharged before (c) lands"* | the unquoted `{fleet_py}` is **FINDING 4, MINOR**, *"Pre-existing… not a blocker"*; and the verdict's own "attack F" is **scope creep**, a different subject entirely |
| *"(c) is NOT landed and must not be landed until that gate is discharged"* | **"No BLOCKING finding."** GATING on three MAJORs, **none of them either peeked item** |
| X2's survival shows *"the a3 lesson… a self-reported table is a claim about the mutants the author thought of"* | *"the lane's table is **truthful**. 6/6 of its mutants die"* — all three survivors are the **gate's own**, and all three are the same subject |

The verdict's own bottom line is that the lane's report *"is the most accurate self-report I have
measured in this campaign."* **The journal's conclusion "do not land yet" was right; its reasons were
not.** The generalisable part is that **a mid-run alarm is systematically louder than a final grade**,
so transcribing peeks into a successor queue converts working hypotheses into inherited findings.
The remedy is cheap and already half-built: cite a running gate by **artifact path and status**, never
by transcribed content — the `docs/lanes/` convention is what made the verdict readable to me at all,
two waves and one supervisor later.

**(d) A correction to wave 48's own corrected doctrine, and this one is still live.** Wave 48
concluded *"pass `--fleet-home <temp>` explicitly"* and landed that stanza in
`docs/lanes/BRIEF-TEMPLATE.md` at `44f056e`. The slice-(c) gate then measured that **`--fleet-home`
cannot name a home you are about to `init`**: §5 step 1 validates that the target is *initialized*,
and `home_is_initialized`'s docstring records as a ratified, deliberately-pinned consequence that
**`fleet init` does not create `state/fleet.json`** — I verified that docstring is live at `c228d69`
by reading it. So the flag refuses `not_initialized` on exactly the case a fence exists for: a
brand-new throwaway home. The gate's actual fence was **removing `CLAUDE_CODE_SESSION_ID` from the
child environment**, gated on `fleet home` run identically. **The shipped stanza names the flag and
not the mechanism.** I cannot fix it — `docs/lanes/` is outside my fence except for this file — so
it is named as an owed amendment in §5.

---

## 5. PROCESS CHANGES — applied, named-but-owed, and none-exists

The brief asked for a process change per entry where one is warranted, and for an explicit statement
where none exists rather than leaving a reader to assume one. All three categories are populated.

### APPLIED (in this branch)

1. **Template v1.11 + ROUTING header** — the nine amendments, and the sentence that stops the next
   fifteen waves from writing into a dead drop.
2. **§8 closing item rewritten** — "amend the LIVE instrument", plus a sub-item requiring the file
   and version to be recorded, or the absence of a remedy to be stated.
3. **New entries lead with a greppable claim sentence**; INDEX lines front-load the finding.

### NAMED, OWED, NOT MINE TO APPLY (each is a small edit in a tree I am fenced out of)

4. **`docs/lanes/BRIEF-TEMPLATE.md` safety stanza** — add (a) *unset `CLAUDE_CODE_SESSION_ID` in the
   child env* as the primary fence, (b) the not-yet-initialized carve-out for `--fleet-home`,
   (c) keep the existing `fleet home`-run-identically verification. **Today every brief on this
   machine carries a fence that fails on a fresh temp home.**
5. **`instance-freshness`: compare the RENDERED template to the instance, not mtimes.** Filed by wave
   46, restated by 47 and 48, **unbuilt for three waves.** Strictly stronger than the current row.
6. **The fork-steer dispatch prompt** — make the pointer distinguishable per dispatch (inline the
   manager message), and make the pin's steer token unique per run so a stale answer cannot
   coincidentally match. Do **not** weaken the assertion; it caught a real defect.
7. **A gate brief may name what to attack and never what grade the result deserves** — belongs in
   the gate-brief section of `BRIEF-TEMPLATE.md`, not only in the template I could reach.

### NO MECHANICAL REMEDY EXISTS — stated plainly rather than implied

8. **Nothing tests a brief.** This is the load-bearing gap behind wave 48's headline: the code was
   right, the *briefing doctrine* was wrong, and no suite, pin or receipt harness looks at
   `state/tasks/lens/*.md`. Every safeguard we have added is prose that a human or a supervisor must
   remember to paste. A candidate remedy exists and I am naming it as a **candidate, not a fact**:
   a lint over dispatched brief files asserting that any brief mentioning `fleet` verbs carries the
   safety stanza's distinctive sentence. **BELIEVED** to be cheap; nobody has costed it, and it would
   catch omission but never wrongness — a brief can carry the stanza and still be wrong, which is
   exactly what happened at `44f056e`.
9. **Measuring a gate's coverage by withholding a known defect is not automatable.** It worked
   because a supervisor happened to spot a defect and had the discipline to stay quiet. You cannot
   schedule that; you can only keep doing it deliberately and recording the result as a property of
   the instrument. The *proofreading pass* (amendment 9) is the mechanical fragment of it and covers
   strictly less.
10. **"Ask why contained, not whether"** is a question a reader must choose to ask. The audit that
    exposed it was clean by every automated measure. No test distinguishes *contained by the fence*
    from *contained by an accident of an absent file*.

---

## 6. WHERE THIS BRIEF WAS WRONG

The brief asked to be told, and named its own likeliest errors. It scored well; four corrections.

**WRONG 1 — the debt is three waves, not five.** *"The fold for waves 44–48 has been owed across
three supervisor incarnations and carried forward untouched by each."* True of the *instruction*, not
of the *state*: waves 44 and 47 were folded contemporaneously, wave 47's by its own supervisor at
`aeab0fa`. The brief anticipated this exactly (*"that these lessons are not already partly folded —
some may be"*), and it changed the work materially: three entries, not five, and one of my main jobs
became not re-recording what was there.

**WRONG 2 — the journal and the lane reports DO disagree, on the item the brief itself listed.** The
brief's checklist item *"a mutant can survive a full 4217-test suite. Three did"* is **correct**, and
its adjacent item is more correct than the journal it came from: the brief says the table *"can be
truthful (6/6 of its own mutants died) and still incomplete, with every survivor being the gate's
own"* — which is what the verdict says, and **not** what wave 48's closing checkpoint says. So the
brief's recollection outranked the primary source on this point. The unquoted `{fleet_py}` item is
the reverse case: the brief inherits the journal's peeked framing. §4(c) has both.

**WRONG 3 — "`FLEET_HOME` is not a fence" is right, and the fix that shipped for it is not.** The
brief lists the wave-48 finding accurately. What neither it nor the shipped stanza carries is that
`--fleet-home` does not work on an uninitialized home, so the remedy has a hole on the exact case it
exists for. §4(d).

**RIGHT, and it shaped the whole report — the rules section.** Every one of the five rules the brief
imposed bit at least once: I had to cite by anchor (the entries are full of cross-references and not
one is a line number into a rolling doc); I had to pin the one command I quote to a commit; the
append-not-rewrite rule is what made §4(a) a correction rather than a falsification; **and "sweep for
the value, not the sighting" caught the second site in §4(b), which I would otherwise have missed** —
I had already written the lessons correction and considered the job done.

**Also right, and cheap for me because a previous lane paid for it:** the ordering of sources.
Reading `supervisor/JOURNAL.md` first gave me the shape of five waves for the price of one file, and
the lane reports then corrected it in three places. The reverse order would have cost far more.

---

## 7. SAFETY LEDGER

- **No `fleet` verb was run. No spawn. No worker touched.** The task said this lane needs neither and
  it did not.
- **`fleet init` / `--statusline`: never run.** `~/.claude/settings.json`: **never opened for
  writing**. `~/.claude/fleet-homes.list`: **never created, never appended** — and independently
  confirmed still absent, which is itself load-bearing evidence for the wave-48 containment finding.
- **No push, no merge, no ref moved.** `main` is untouched; the only ref that moves is `w49/dcap`.
- **Files written:** `knowledge/lessons.md`, `knowledge/INDEX.md`,
  `knowledge/playbooks/campaign-template.md`, `docs/lanes/w49-fold.md` — all inside my fence — plus
  my own journal at `state/journals/w49-fold.md` (gitignored) and a pointer journal under the live
  home per the task's standing line. **Nothing under `bin/`, `tests/`, `docs/specs/`,
  `supervisor/`, `docs/OPERATOR-GATES.md`, or any other lane's report.**
- **Reads outside the worktree, all read-only:** `C:/proga/claude-fleet/state/verdicts/` (the wave-45
  gate verdicts, which are gitignored and exist on that disk only) and the `w48/gc` branch via
  `git show`. No file there was modified; `w45-ga2.md` measured **38,815 bytes**, matching the
  journal's claim exactly.

## 8. WHAT I DID NOT DO

- **Did not fold wave 49.** It is still running; the brief ordered 44–48 and said the interface
  carries 49 at close. My own two wave-49 reports (`w49-dcap.md`, `w49-dcap2.md`) are therefore
  deliberately unfolded.
- **Did not retrofit older entries** to the new greppable-lead format, and did not shorten any
  existing INDEX line. Both would be rewrites of dated records.
- **Did not amend `docs/lanes/BRIEF-TEMPLATE.md`**, though it is the file that most needs it (§5.4) —
  three other lanes hold `docs/lanes/` this wave and my fence is explicit.
- **Did not read the wave-45 `w45-ga2` verdict in full** (38,815 bytes). Its substance is already
  folded through `#2026-08-09-w47-slice-a`, and wave 46's entry records the fidelity finding *about*
  it, which is the part that was missing. I read `w45-gceil` and `w45-gpins` at the sections carrying
  their blocking findings.
- **Did not re-run any suite.** This lane changed no code and no test; the floors it quotes are the
  supervisors' and the gates', attributed as theirs.
