## 2026-09-10T21:01:09Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=524b9901-f57c-4726-b95f-b89b42c0c5c0

WAVE 67 CLOSED AND PUSHED (`593e927..713f058`). One lane landed, and **`fleet wave-close` ran for
real for the first time and produced three defects** — which is exactly why it was queued to be run
rather than trusted.

## SHIPPED
- `a1b04cb` **`sup-guard`: a seize is an EVENT IN THE PAST, not a state.** It was printing
  `PAGE claim seized` against a healthy fleet — my claim was seized at 15:30Z, so every verdict for
  five hours would have paged. Now seized+fresh flows through the ordinary held-claim rules;
  seized+stale still pages; both directions pinned. The lane answered the sibling-clause question
  instead of skipping it: no other branch treats a past event as a state.
- `8a8d086` + `713f058` **the wave-close repairs** (below).

## THE THREE DEFECTS, IN THE ORDER THEY SURFACED
1. **The floor never ran.** It invoked `python3.10 -m pytest` directly; NO interpreter on this host
   has pytest importable. **My briefing defect** — I gave the lane six hard-won findings about
   foreground-vs-background, the recursive walk and the moving split boundary, and omitted
   `CLAUDE.md`'s FIRST rule, how the suite is invoked at all. The lane had even set `UV_OFFLINE` and
   `UV_CACHE_DIR`, so it knew uv was in the picture; nothing told it the interpreter alone cannot work.
2. **A floor that never ran was indistinguishable from a floor that ran clean.** A half with no
   pytest summary parsed as zero of everything, and zero failures compares EQUAL to an empty expected
   set. It aborted only because the expected set is the six host assumptions — **had it been empty,
   the push would have been licensed by a floor that never executed.** Now it raises and names the log.
3. **`git commit` died on an unset committer identity**, after the reap and both floors — twelve
   minutes of work with the landing prepared and staged. Every commit this generation made passed
   `-c user.name=...`, so nothing had ever exercised the repo config. Repo identity set; and the verb
   now checks `git var GIT_COMMITTER_IDENT` with the cheap preconditions. **Same lesson as moving the
   `uv` lookup ahead of the clone, arriving twelve minutes later and more expensively: check what the
   expensive work depends on BEFORE doing the expensive work.**

**The abort is what makes this a good story rather than a bad one.** At every step the verb refused
to land on a result it could not reconcile. Nothing wrong was pushed.

## WHAT IT GOT RIGHT, MEASURED
- **The reap ran for real: 24 rows** — retired supervisor bodies and finished lane workers back to
  w58, including the 15:18Z OOM corpses. First live exercise of the operator's amendment.
- Both floors ran, matched, and the THROUGHPUT line computed with **`tokens: UNMEASURED`** rather
  than a fabricated zero. The rule held under machine authorship.

## A DESIGN FINDING THE NEXT BODY MUST PLAN AROUND
**`wave-close` takes ~12 minutes, longer than the 600s tool timeout**, so from a Claude Code session
it is ALWAYS pushed to background — which is where the harness low-memory guard lives. It survived
this time. It needs to be resumable, or to run its floors concurrently, or the close needs to be
split. It is also **not idempotent across a failed close**: it had already prepended and staged the
CHANGELOG and JOURNAL, so re-running would have duplicated them. I committed its prepared content by
hand instead.

## PINS ADDED
Three, on the floor arm, because every pre-existing wave-close test injects `run` and neither defect
was reachable from them. **A verb whose expensive arm is only ever mocked is a verb whose expensive
arm is unpinned.**

## NEXT
Batch 2 directive received (five verbs, prose caps, `tokens_per_bin_line` and `external_lines` in
THROUGHPUT). G-K8 ruled **option C**: the socket path comes out, the waker goes through `fleet send`
built on `sup-guard --do`, keeper wake on by default — one astra lane, wave 68. Tier policy stays
**top=opus** per the correction; no PROPOSAL to move it.

## 2026-09-10T21:04:28Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=c8677549-1ea9-4c1e-a8ac-ab65b25aca52

WAVE 68 OPEN — the prose-rot campaign, phase 1 (context-loaded files).

MEASURED at `713f058`, confirming the directive: `docs/` 92,635 md lines, 38,907 of them in 68 lane
reports; `knowledge/` 2,565 (lessons.md 2,033); `skills/fleet/supervisor.md` 587; CLAUDE.md 36 but
mostly corrections of itself; profile 143; GOALS.md 133; 68 history phrases in `bin/fleet.py`.

I am a producer of this rot, not an observer of it. The lane reports being archived are ones I
commissioned, and my checkpoints are the same genre. Checkpoints get shorter from here.

DISPATCHED, both `gpt-5.6-luna` high, detached, observers armed:
- `BqtwsRwm` w68-skill — `skills/fleet/` becomes the operating manual, <=400 lines total, imperative,
  verbs derived from `build_parser()` rather than from any existing doc. This is the operator's
  "more instructions" ask.
- `SsvzANTe` w68-caps — CLAUDE.md <=60, profile <=100, briefs <=60, loaded knowledge <=400 with
  entries <=12, lessons >30d to `docs/archive/`, and `tests/test_prose_caps.py` pinning EVERY cap
  including the ones later lanes must satisfy, xfail with the lane named. A cap nobody wrote down is
  a cap nobody meets.

ONE CONSTRAINT I DID NOT LET THE CAMPAIGN OVERRIDE: `supervisor/GOALS.md` is 133 against an 80 cap,
but it is operator-owned and no lane may originate its content. The lane writes a proposed trim to
`docs/operator/goals-trim-proposal.md` and I carry it as a PROPOSAL. The cap is pinned xfail meanwhile.

QUEUED, NOT DROPPED: G-K8 option C (socket path out, waker via `fleet send` on `sup-guard --do`,
keeper wake on by default) — one astra lane, next wave. Batch 2's five verbs after it.

BRIEFS ARE NOW UNDER ONE SCREEN, per the new prose caps. Mine had been ~80 lines.

## 2026-09-10T22:42:04Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=819e3008-5862-4e86-b01c-993ecfc50bfe

WAVE 68 CLOSED AND PUSHED (`116860f..16f28c5`). The prose campaign's phase 1 landed and
`fleet wave-close` closed a wave end to end for the first time.

## SHIPPED
- `314ea3e` `skills/fleet/` is a 160-line operating manual; `supervisor.md` (587) and
  `docs/operator/server-interface-profile.md` deleted, their current content absorbed. It teaches the
  INTERFACE AS A ROLE: "become" and "continue" are the same six steps, because the role's state lives
  in the home and never in a conversation.
- `efc4b5c` context-loaded files under cap, lessons >30d archived, `tests/test_prose_caps.py` pinning
  every cap including the four later waves must close, xfail with the lane named.
- `b0b5370` interface state in the home; bare `init` registers the caller; the §7 gate follows the
  home being INITIALISED so a claim elsewhere no longer blocks `init` in an unrelated repo.

## THE CAMPAIGN KEEPS FINDING DEFECTS THAT ARE NOT ABOUT VERBOSITY — SIX NOW
A keeper that would have gone SILENT on any host with no registered pane (only alerting tier, early
`return 0` before paging); a keeper `--profile` default aimed at a file the same wave deleted;
`fleet init` refused in unrelated repos by a foreign claim, breaking the ruling's headline scenario;
doc-claims auditing the archive as a claim about the current tree; a receipt greping a lesson that
had moved to the archive; and the wave id below. **The operator's "full of inconsistencies" was
literal.** Deleting prose keeps exposing places where prose was load-bearing and nobody had said so.

## `wave-close` EARNED ITS KEEP AND THEN MISLABELLED ITSELF
It ran both interpreter floors from a fresh clone, found the receipt failure the campaign had
introduced, and REFUSED to land or push. Second run: green, committed, pushed, relayed. Then it
labelled wave 68 as `wave 67`: `_wave_id` took the max from the FIRST matching file, JOURNAL.md, and
**the board roll shipped in wave 65 had migrated the highest wave number into journal-history**. Two
mechanisms built two waves apart, neither wrong alone. Fixed to take the max across board, changelog
and every history file. The mislabelled commit is pushed and stays: rewriting shared history to fix a
label is the worse trade.

## MY OWN DEFECTS THIS WAVE
- I shortened briefs to meet the new prose cap and dropped the offline uv invocation, so THREE lanes
  reported "pytest blocked" and one shipped a keeper regression untested. **A cap on brief LENGTH
  must not drop the line that makes the work verifiable.** Clause now saved for verbatim reuse.
- "Targeted tests" was read by lanes as "the tests I wrote". Briefs must name the suite per file
  touched.
- I passed `--base 116860f`, a checkpoint rather than the close commit, so the range double-counted.

## DISPATCHED
`yT3qCJAa` w69-wc (5.6 luna) — the interface's six remaining wave-close accounting defects plus the
board's pending-rulings computation. The one that matters most: **wave-close must refuse to close
when a merge since base has no CHANGELOG line** — an unrecorded landing is invisible forever.

## OBSERVERS DID NOT FAIL
Every observer fired and I acted on each. The 68-minute idle was AFTER the last lane, during landing,
and ended with my turn over and the wave still open. Re-arming would not have helped: nothing was
left to observe. That gap is what G-K8 option C's waker closes; it is now the third page it would
have prevented.
