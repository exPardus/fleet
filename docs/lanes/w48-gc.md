# `w48-gc` — adversarial gate over `w48/hookargv` (multi-fleet slice (c))

**GATING**

**Lane:** gate. Worktree `C:/proga/fleet-w48-gc`, branch `w48/gc`, forked at `1161d39`. Mode bypass.
**Under gate:** `w48/hookargv`, one commit `1161d39`, 14 files, +1469/−43, report `docs/lanes/w48-c.md`.
**Measured against:** base `fa236cb`; `w48/launch-rehearsal` read at **`b4de97a`** (§3).

`w48/gc` and `w48/hookargv` are the **same sha** (`1161d3908818e50bd90f2027e8291d45893bd478`), so
every measurement ran on the code under gate, in place. No ref was moved; the branch under gate was
not edited; `git status` was clean at every checkpoint and at exit.

**Every line is MEASURED unless it says BELIEVED.** Every measurement whose good answer is
zero/empty has a named known-non-zero control that ran FIRST — and three of those controls caught an
instrument failure before it could become a finding (§5).

---

## 0. THE ANSWER

**No BLOCKING finding.** The mechanism this slice ships is sound. The four attacks aimed at breaking
it — the exit-0 hook invariant, the view-refusal reachability, the fault-injection table, and the
citation re-pin — all came back **CLEARED**, three of them under measurements stronger than the
ones the lane reported. Both floors reproduce the claimed triple exactly on both interpreters, and
the lane's report is the most accurate self-report I have measured in this campaign.

It is **GATING**, not GREEN, on three things:

| # | Grade | What | Cost to clear |
|---|---|---|---|
| 1 | **MAJOR** | `docs/launch-readiness.md` contradicts itself inside one bullet — *"29 checks … goes to 28 PASS / 0 FAIL"*. The branch created it, the measured truth is **29 PASS**, and the pin that exists to stop exactly this is structurally blind to the phrasing. | one line |
| 2 | **MAJOR** | The `home-witness` doctor row is **originated** content, not derived-from-ratified — and it is the direct cause of finding 1. Needs the operator ruling the lane itself asked for. | a ruling (revert ≈ 1 function + 1 line + 6 doc sites) |
| 3 | **MAJOR** | `home-witness` recognises **one of the three `--fleet-home` spellings its own hooks accept**, and three of its documented design decisions are unpinned. Two of the four gaps produce a **false FAIL on a correctly fenced home** — the "permanently-red row" the lane itself argues against. | a wider regex + 3 tests |

Plus four MINOR. Findings 1 and 3 are small edits; finding 2 is not mine to decide.

---

## 1. FINDINGS

### FINDING 1 — MAJOR. A shipped launch doc states two different numbers in one bullet, and the branch put them there.

`docs/launch-readiness.md` at `1161d39`, lines 175–176:

```
- **`fleet doctor` earns its place.** 29 checks; on a fresh home it fails 4 with the exact remedy
  named, and goes to **28 PASS / 0 FAIL** after `fleet init`. It is report-only by default.
```

At `fa236cb` that bullet read `28 checks … 28 PASS / 0 FAIL` — internally consistent. The branch's
diff touches **only line 175**. The contradiction is manufactured by this commit.

**Which half is wrong, measured.** Driven on a fresh home with `bin/fleet.py` at `1161d39`:

```
--- fleet doctor BEFORE init ---
  rc=1  rows=29  PASS=25 FAIL=4
    [FAIL] worker-settings-instance
    [FAIL] instance-freshness
    [FAIL] instance-grants
    [FAIL] hook-registration

--- fleet init (no --home, no --statusline) ---  rc=0

--- fleet doctor AFTER init ---
  rc=0
  TOTAL ROWS : 29
  PASS       : 29
  FAIL       : 0
```

29 rows, **29 PASS / 0 FAIL**. `docs/getting-started.md` says `29 PASS` and is right;
`docs/launch-readiness.md` says `28 PASS` and is wrong.

**It is the lane's own named defect class, committed by the lane.** `docs/lanes/w48-c.md` §2
justifies the out-of-scope `_render_sup_spawn_task` fix with *"fixing only the reported site is how
this project reproduces a miss at the next site."* The identical `N PASS / 0 FAIL` sentence exists in
`docs/getting-started.md` line 77 and the lane **did** update it (`28 PASS` → `29 PASS`, plainly
visible in the diff). It fixed one sibling and missed the other.

**Why the suite cannot see it.** `tests/test_doc_claims.py`:

```python
_CHECK_COUNT = re.compile(r"\b(\d+)\s+(?:fleet\s+)?(?:health\s+)?checks?\b", re.I)
```

Anchored on the word `check`; `28 PASS / 0 FAIL` contains no `check`. `docs/launch-readiness.md`
**is** in `ENTRY_DOCS`, so the file is in scope and the phrase is not. `tests/test_doc_claims.py`
→ **`20 passed`** on the branch, and `20 passed` on the merged tree. Green and wrong — the wave-35
class in a different file. The lane's §10e says the count is *"pinned in three shipped docs"*: true
of `N checks` (6 sites, all correctly updated), but there is a **seventh** site in a second phrasing
that nothing pins.

**And the hole was written down in advance, in the file the lane cites by name.** That module's own
docstring enumerates its holes, and under `PHRASING` it says:

> `28 doctor checks`, **`28 PASS / 0 FAIL`** and `checks: 28` are not `"<N> checks"`

The pin file names the exact string that is now stale, as its own worked example of what it does not
hold. This is not "the suite could not have caught it" — it is "the suite says in writing that it
will not, using this very phrase, and the lane read that test's scope closely enough to cite it."
That is what moves this from an unlucky miss to a MAJOR.

*Remedy:* `28 PASS` → `29 PASS` in `docs/launch-readiness.md`. Optionally widen `_CHECK_COUNT` to
also match `(\d+)\s+PASS`, which would have caught it.

### FINDING 2 — MAJOR (governance). The `home-witness` row is originated content — and it caused finding 1.

**The lane's count is right. MEASURED, with a control.** In `docs/specs/multi-fleet.md` at
`fa236cb`, `witness` occurs **exactly twice** (control: `home` occurs 199 times in the same file, so
the grep is not silently matching nothing):

```
143:   disagreement → mutating verbs refuse without `--yes` + witness line.
707:   global flag (with the rb7 C-2 argparse pin); (b) `init --home`; (c) hook argv + witness +
```

Line 143 is §5 step 1's flag/lookup witness, which Sequencing §3 assigns to slice **(a)** and which
(a) shipped; line 707 is the phrase being interpreted. **No third occurrence, and no sentence
anywhere defines a hook- or successor-plane witness.** §3's word *"disjoint"* is verbatim in the
spec, so (c)'s witness genuinely cannot be (a)'s line. The lane misread nothing.

**Would I have built it? No.** Two reasons; the second is the one that matters.

1. When a slice's own name contains a term the ratified document never defines, the in-scope act is
   to build the two parts that ARE defined (`hook argv`, `_render_successor_task argv`) and escalate
   the third. The lane escalated **one** reading (a runtime hook-side witness record, §0d) and
   **built** another — the one it derived itself. Escalating the reading you reject while shipping
   the reading you prefer is not the same as escalating the question.
2. A new `fleet doctor` row is not an internal detail. Its **count is restated in three shipped
   documents**, so adding one is a six-site documentation edit by construction — and that edit is
   exactly what produced finding 1. The governance objection is not abstract here; it has a concrete
   cost inside the same commit.

**Grading it fairly, because the other direction is worth as much.** The derivation is well argued
and quotes real sentences (the interference audit's *"fenced by hook argv"*; the file's own *"THE
REGISTRY JUDGES, THE ENVIRONMENT ONLY WITNESSES"*). The row is report-only. It detects a state
nothing else in the tree can see. It PASSes on a fresh `fleet init` (measured, finding 1) and
correctly declines to duplicate the instance rows' fault — measured: in the pre-init run it PASSed
with a NOTE while the three instance rows FAILed, exactly as §3 claims. And the lane disclosed all
of it unprompted. **This is MAJOR as governance, not as defect** — nothing here is wrong, it is
unauthorised.

*Remedy:* an operator ruling. The lane's revert estimate checks out — the row is registered as a
single `functools.partial(_doctor_check_home_witness)` in `cmd_doctor`'s list.

### FINDING 3 — MAJOR. The witness does not recognise its own subject, in two measured ways; and three of its documented decisions are unpinned.

The lane's §1b makes a point of the hook grammar *deliberately* matching `strip_global_fleet_home`,
because *"a hook that disagreed with `fleet.py` about its own flag's spelling would be drift by
construction."* `_doctor_check_home_witness` is a **third parser of the same option string** —
`re.search(r'--fleet-home\s+"([^"]*)"', command)` — and it agrees with neither of the other two.

**(a) Spelling. A shipped defect, not a coverage gap.** Driven: the same instance command fed to the
hook's real `_argv_fleet_home()` and to the doctor row.

```
space + quotes  (what the template renders)
    HOOK resolves home  : 'C:/.../home'
    DOCTOR row says     : [PASS] every dispatched hook command names this home
    witness agrees: True

EQUALS form     (which the hook also accepts)
    command             : "py" "h.py" --fleet-home=C:/.../home
    HOOK resolves home  : 'C:/.../home'
    DOCTOR row says     : [FAIL] 1 of 1 dispatched hook command(s) carry no --fleet-home ...
                                 The instance predates the baked argv: re-run `fleet init`
    witness agrees: False

space, UNQUOTED (a hand edit)
    HOOK resolves home  : 'C:/.../home'
    DOCTOR row says     : [FAIL] ... carry no --fleet-home ...
    witness agrees: False
```

A correctly fenced instance is reported as unfenced, with a remedy (`re-run fleet init`) that would
not fix it — a permanently-red row, which is the precise harm the lane cites when refusing to route
witnesses to `hook-errors`. **Reachability is limited and I checked it:** `template_settings_path()`
is hard-wired to `INSTALL_ROOT / "worker-settings.template.json"` with no override, so this needs an
edited clone template rather than a supported config knob. That is what keeps it MAJOR-with-a-narrow
mouth rather than blocking. *Remedy:* one regex covering `=`, unquoted, and single-quoted forms —
or better, reuse the grammar the hooks and `fleet.py` already share.

**(b) Case. Correct in shipped code, unpinned.** Mutant **X2** replaced
`os.path.normcase(b) != os.path.normcase(here)` with a raw `b != here` and **survived the full
4217-test floor** — `4217 passed, 14 skipped, 1 xfailed in 394.50s`, with the mutant on disk and the
immediately preceding clean floor green. Driven, the mutant turns a same-home-different-case bake
into a false `LEAK:` on a correctly configured home:

```
X2, same home upper-cased:   shipped : PASS
                             mutant  : FAIL LEAK -> ['C:/USERS/TECHN/.../HOME']
```

On Windows this is reachable without tampering — `here` is `FLEET_HOME.as_posix()` and `FLEET_HOME`
can arrive un-resolved from the environment. The `normcase` is load-bearing and nothing holds it.

**(c) Two further unpinned decisions, both also surviving the full floor.** Mutant **X4** (an empty
`--fleet-home ""` counts as fenced) survived: `4217 passed, 14 skipped, 1 xfailed`. I nearly graded
this a fail-open and it is **not** — driven, both shipped and mutant **FAIL**; the mutant only
degrades the remedy (`unfenced … re-run fleet init` becomes `LEAK -> ['']`). Mutant **X5** (the row
registered after `hook-registration` instead of immediately after `instance-grants`) also survived:
`4217 passed, 14 skipped, 1 xfailed`. `TestCmdDoctorRegistersNewChecks` pins only the `pin-version`
and `tzdata` positions, so the "three instance rows read as one answer" argument in the lane's §3
has no pin behind it.

Taken together: of the new row's four documented design decisions I probed, **one is a shipped
defect (a) and three have no pin (b, c)** — in the one part of this change that is entirely new
code, from a lane whose fault-injection rigour is otherwise exemplary.

### FINDING 4 — MINOR. `_render_successor_task` renders `{fleet_py}` unquoted; the branch added a *quoted* argument to it and left the quoting alone.

Driven against an install root named `Fleet Install With Spaces`, with the sibling as control:

```
CONTROL  _render_sup_spawn_task  sup-boot   (QUOTED)
  [cmd.exe]  rc=0  out='=== SUPERVISOR BOOT BUNDLE ===\n\n--- supervisor/GOALS.md ---...'

SUBJECT  _render_successor_task  sup-status (UNQUOTED)
  [cmd.exe]  rc=2  err="python.exe: can't open file 'C:\\...\\Temp\\...\\Fleet':"
  [git bash] rc=2  err="python.exe: can't open file 'C:\\...\\Temp\\...\\Fleet':"
```

All three commands the successor render emits are affected. **Pre-existing** — `fa236cb` renders
them identically unquoted — and explicitly disclosed in the lane's §11.1, so severity is unchanged
by the branch and this is not a blocker. What earns it a grade: the lane's stated reason for fixing
the *other* sibling gap (*"leaving one of two sibling renders unfenced is this repo's own named
recurring defect"*) applies verbatim here in the opposite direction, and this one sits inside the
function Sequencing §3 **does** name, while the fix it did make is in the one §3 does not. The
branch also added a correctly quoted `--fleet-home "{home}"` to these very lines, leaving a command
that looks quoting-aware and is not.

### FINDING 5 — MINOR. The lane's line-count arithmetic is wrong (the repair is not).

`docs/lanes/w48-c.md` §8: *"`bin/fleet.py` 21,447 → 21,533 lines (+86)."*

```
$ git show fa236cb:bin/fleet.py | wc -l
21438
$ git show 1161d39:bin/fleet.py | wc -l
21533
```

Base is **21,438**; delta is **+95**. `21,447` is base + the `_render_successor_task` hunk (+9) — an
intermediate state presented as the starting point. Reporting slip only: the repair ran difflib
against the base blob and its own alignment figure (*"21,433 of 21,438 base lines"*) names the
correct base and reproduces exactly (§2E).

### FINDING 6 — MINOR. A CR-suffixed baked home produces a FAIL whose two paths look identical.

```
--- this home with a trailing CR
    => [FAIL] home-witness: LEAK: this home is C:/.../home, but its own settings instance
       dispatches hooks at C:/.../home -- every worker launched from here drains mailboxes ...
```

The row correctly detects it — a real mitigation the base did not have — but renders the `\r`
invisibly, so the operator reads a LEAK between two identical strings and cannot act. Given this
campaign's four CRLF-shaped instrument failures, a `repr()`-style rendering of a mismatching value
would be cheap. MINOR.

### FINDING 7 — MINOR / observation. An unmakeable baked home loses the record silently.

With `--fleet-home "<path>\r"`, `stop_outcome.py` exits 0, writes nothing and logs nothing — the
outcome record is lost with no diagnostic (`_log_hook_error` writes into the same unmakeable home
and swallows its own failure). Raw `Path(...).mkdir()` on that name raises
`OSError(22, 'The filename, directory name, or volume label syntax is incorrect')`, so the loss is
real. **Not a regression:** the `fa236cb` hook behaves identically through `FLEET_HOME`; slice (c)
adds a second channel with the same property, and `home-witness` at least FAILs on such a bake.
Recorded so a later slice does not rediscover it as new.

---

## 2. WHAT I TRIED TO BREAK AND COULD NOT — the four CLEARED attacks

### B. THE EXIT-0 HOOK INVARIANT — **CLEARED**, driven, 192 runs.

The lane's §1d asymmetry is real and I confirmed it in source before driving anything:
`bin/hooks/stop_outcome.py` ends `if __name__ == "__main__": sys.exit(main())` with **no `except`**,
and `main()`'s first statement is `home = _fleet_home()` (line 338) — **above** its `try` (line 339).
The other three wrap `main()` and `sys.exit(0)` unconditionally.

**Controls first.** Three synthetic children ran before any hook: one exiting 3, one raising, one
clean. Detector: `['rc=3']`, `['rc=1','TRACEBACK-on-stderr']`, `CLEAN`. All three behaved.

**4 hooks × 24 hostile argv shapes × 2 interpreters = 192 runs**, real argv, real JSON on stdin,
real subprocesses. Shapes covered every one the brief named — unknown flag, `--fleet-home` with no
value, nonexistent path, path with spaces, empty string, **trailing `\r`**, non-existent drive —
plus `--fleet-home=`, flag-eats-a-flag, contradictory repeat, `--` terminator, bare positional,
embedded newline, embedded CRLF, a value that is itself a flag, UNC, glob/quote characters, and a
5000-character value.

```
                            py 3.13.12                 py 3.10.1
stop_outcome.py            ........................   ........................
stop_mailbox.py            ........................   ........................
posttooluse_mailbox.py     ........................   ........................
postcompact_journal.py     ........................   ........................
CLEAN: all 96 runs exited 0 with no traceback.   (both interpreters)
```

**Zero non-zero exits. Zero tracebacks** — including in the one hook whose call site is outside its
net.

*Side measurement, because a hook that exits 0 can still do something.* An unvalidated argv home is
`mkdir`'d (`C:/does/not/exist/w48gc/state/outcomes/…` was created). **Not new.** Control both ways:
the `fa236cb` hook creates the same tree from `FLEET_HOME`, and given the argv it ignores it
(`argv-target created=False, env-target created=True`). Slice (c) adds a second channel with
identical semantics. A *relative* argv home writes into the worker's CWD; that needs a hand-edited
instance and `home-witness` FAILs on it. Litter I created (`C:/a`, `C:/does`) was removed.

### C. THE RECORDED DIVERGENCE — the defect is real, **pre-existing**, and the branch **improves** the one path it touches.

The brief pre-committed: *"If it does [make a view exit 1 on a reachable path], that is BLOCKING."*
I am not applying that grade. Here is the measurement that changed it.

**(i) Slice (c) did not create it.** AST-extracted source, sha256-compared across the branch:

```
apply_resolved_home   51e34d7330e4c2ada9fa90edbbafdbcf47069a3fa6b53f03db0c60bd4ea6e8ab  (both shas)
resolve_home          IDENTICAL
TERMINUS_VIEW_VERBS   15494da54e9d9382752bb9c0310005d4040bd905b0577674dfa18ad3b6f8f6cb  (both shas)
```

Control: the same extractor on `_render_successor_task` reports DIFFERS, so it can see a change.
**This settles the brief's uncertainty #2 — the divergence predates the branch.**

**(ii) The refusal is real.** Two-home world, sid a member of home B, `--fleet-home` naming home A.
Control C2 (a mutating verb must refuse): `clean` → rc 1 with the WITNESS line. Then **9 of 9
`TERMINUS_VIEW_VERBS` refuse at rc 1** — `home knowledge status peek result doctor q sup-status
sup-context` — each with `fleet: [fleet] WITNESS: --fleet-home names …`. **branch = 9, base = 9.**

**(iii) The deciding comparison, which the lane did not run.** The question is not whether the
*flagged* view refuses. It is what the *pre-slice* render did in the same state:

```
PRE-SLICE  sup-status --json, no flag   [fa236cb]  rc=0   home used: homeB (WRONG HOME)
PRE-SLICE  sup-status --json, no flag   [1161d39]  rc=0   home used: homeB (WRONG HOME)
POST-SLICE sup-status --json --fleet-home A        rc=1   home used: homeA (CORRECT), witness printed
```

Before slice (c) the successor's poll **silently read the wrong home and returned 0**. It could
never have seen its own incarnation there, so it polled the full ten minutes and ended
`HANDOFF-ORPHAN` — the same terminal state, reached quietly. `sup-checkpoint` refuses at rc 1 both
ways; `sup-boot` refuses at rc 1 both ways, creating no `supervisor/` directory in either home.
**The branch converts a silent wrong-home read into a named refusal. It does not turn a working
path into a broken one.**

**(iv) In ordinary operation it is not reached.** Pre-claim window (sid claimed by no home):
`sup-status`, `status`, `home` all rc 0 — the lookup misses, the flag wins, which is the hole the
slice exists to close, working. After the claim the successor's sid belongs to the home that
dispatched it, so flag and lookup agree. A genuine disagreement needs the successor's sid in a
*different* home's registry, i.e. cross-home registry contamination. On this machine
`~/.claude/fleet-homes.list` **does not exist** (measured), so the population is the install root
alone and the state is unreachable here.

**CLEARED for this branch.** The underlying divergence stays exactly where the lane put it: a
recorded, unclosed §5 step 1 divergence under an open operator gate. It should be fixed; it is not
this branch's to fix, and this branch makes the one path it touches strictly more honest.

### D. THE MUTANTS, RE-PLANTED — **the lane's table is truthful.** 6/6 of its mutants die.

My own planter, not the lane's: `occurrences == 1` asserted **before** anything runs (abort
otherwise), sha256 before/after with a byte-identical restore assert, `git status` re-checked after
every restore, `try/finally` plus an on-disk recovery guard, and a **clean-floor control of the same
target set first** so a RED is attributable. Targeted set = `test_hook_fleet_home_argv`,
`test_supspawn_fixwave2`, `test_install_home_split`, `test_native`, `test_doc_claims`,
`test_terminal_surface`, `test_home_resolution` → clean floor **`855 passed, 1 skipped`**.

**M1–M6 restate the lane's six, formulated from the code rather than copied from its report.
X1–X5 are mine and are not in that table** — a self-reported fault-injection table is a claim about
the mutants its author thought of.

| # | mutant | result |
|---|---|---|
| M1 | argv no longer beats env (steps 1 and 3 swapped) in ONE hook | **RED** — 4 failed, 851 passed |
| M2 | a contradictory repeated flag resolves by position instead of declining | **RED** — 1 failed, 854 passed |
| M3 | the argv parser RAISES on an unknown token (exit-0 broken) | **RED** — 3 failed, 852 passed |
| M4 | one dispatched hook command loses its baked home | **RED** — 4 failed, 851 passed |
| M5 | **the sup-spawn render loses the flag — the exact revert** | **RED** — 2 failed, 853 passed |
| M6 | the witness compares nothing (a foreign baked home reads as agreement) | **RED** — 1 failed, 854 passed |
| X1 | *mine:* the successor render loses the flag on the `sup-status` POLL **only** — a partial loss inside the function §3 actually names | **RED** — 2 failed, 853 passed |
| X2 | *mine:* `home-witness` compares raw strings instead of `os.path.normcase` | **GREEN — SURVIVED**, and survived the **FULL** floor: `4217 passed, 14 skipped, 1 xfailed` |
| X3 | *mine:* a hook drops the `--fleet-home=VALUE` spelling | **RED** — 1 failed, 854 passed |
| X4 | *mine:* `home-witness` accepts an EMPTY baked value as fenced | **GREEN — SURVIVED**, full floor: `4217 passed, 14 skipped, 1 xfailed` |
| X5 | *mine:* the `home-witness` row registered in a different position | **GREEN — SURVIVED**, full floor: `4217 passed, 14 skipped, 1 xfailed` |

**8 of 11 died. All three survivors are mine, and all three are the same subject — the new
`home-witness` row** (finding 3). Each was escalated to the full suite before being reported, and
the clean full floor that preceded them was itself green (`4217 passed, 14 skipped, 1 xfailed in
386.84s`), so a GREEN above is a real survival and not a broken harness.

M1's first pattern asserted `occurrences == 0` and **aborted without running the suite** — the
planter working, not a survivor; `posttooluse_mailbox.py` returns `str`, not `Path`. Re-run with the
corrected pattern above.

**Tree integrity across all 15 plants:** every restore verified sha256-byte-identical, `git status`
re-checked clean after each, and the full 233-file manifest re-diffed at the end — **identical to
the pre-gate baseline**.

**M5 — the one the brief named, the exact revert of the out-of-scope `_render_sup_spawn_task` fix —
is RED, watched with my own eyes.** M3's failure count (3) and M6's (1) match the lane's report
exactly; M4 and M5 differ only because my target set is wider than theirs, which can only surface
more failures, not fewer.

**Protocol:** a mutant that goes GREEN on a subset is not a survivor until the full suite has had
its chance. All three survivors were escalated to the full 4217-test floor before being reported.

### E. THE CITATION RE-PIN — **CLEARED, and more strongly than the lane claimed.**

Green was not the test. Two independent checks, each with a control.

**(1) Every rewrite lands inside the function it names.** An AST innermost-`def` map over the whole
file, applied to all **12** rewrites. Control: a fabricated pair (`_doctor_check_autoclean` cited at
line 100) is flagged, so the checker can see a mismatch.

**Result: 0 of 12 mismatched.** Every rewrite is content-byte-identical
(`old_lines[old-1] == new_lines[new-1]`) **and** its enclosing function is unchanged and equal to
the symbol named. The five `_quarantine_artifacts` call sites land on
`artifacts = _quarantine_artifacts()` inside `_doctor_check_autoclean`, `_identity_abstention_note`,
`_doctor_check_registry`, `_tombstone_releasing_body` and `_require_claim_holder`. The unnamed ones
land on exactly what they claim: `:12800` and `:18114` are the two
`record["retired_sids"] = list(...) + [old_sid]` writers in `_restamp_after_steer` and
`cmd_sup_handoff_complete`; `:14894` is the union-keyed carrier list in
`_releaser_body_is_tombstoned`; `:14822` is `def _registry_records_or_none():` itself.

**(2) Nothing was missed.** Masking every integer and pairing the two files with difflib pairs
**21,433 of 21,438** base lines — independently reproducing the lane's own alignment figure — then
classifying every citation on every paired line. Control: a fabricated "left the number unchanged"
case is flagged `MISSED-REWRITE`.

```
  ok-rewritten     12
  ok-unchanged     66
NO missed and NO wrong rewrites across every paired citation line.
NEW (unpaired) lines carrying a `:NNNN` citation: 0
```

**(3) Ranged forms.** Exactly one exists at both shas — `` `cmd_respawn:8470-8472` `` — correctly
needing no rewrite (it sits above the first insertion at 11249), and **both** START and END resolve
inside `cmd_respawn`. The lane's claim that range ends were *checked* rather than merely unchanged
is verified.

### F. SCOPE CREEP — the `_render_sup_spawn_task` fix is correct, and I would have taken it.

The hole is identical (both renders dispatch a sid-less body that claims afterwards), the fix is the
same one token, M5 proves it is pinned, and slice 0's symbol list names both functions — so §3
naming one reads as an omission rather than an exclusion. The lane's honesty about the *differing*
justification (gen-0's accepted 6.8–10.6s worker-class window vs the successor's unaccepted
33–63s) is the right call and I found nothing to correct in it. **In scope by the repo's own
sibling-defect doctrine; correct as written.** The unquoted-`{fleet_py}` half is finding 4.

---

## 3. CROSS-BRANCH COHERENCE — the half the manager could not measure

**`w48/launch-rehearsal` moved during this gate.** I read it at **`b4de97a`** (*"discharge the
glaunch gate — 3 MAJOR, 4 MINOR, and one gap that was false all along"*), one commit past the
`4ccc8f7` the brief describes. It is **docs-only**: `git diff --name-only fa236cb b4de97a` returns
`README.md`, `docs/concepts.md`, `docs/getting-started.md`, `docs/lanes/w48-launch.md`,
`docs/launch-readiness.md`. No code file, so there is no code-level interaction to assess.

**The merge is clean, re-measured on that tip.** `git merge-tree --write-tree` does not exist on this
box (git 2.34.1) and the flag was **parsed as a rev** — the exact failure the brief warned about,
caught because a control ran first. Redone in a detached worktree:

```
Auto-merging README.md
Auto-merging docs/getting-started.md
Auto-merging docs/launch-readiness.md
Automatic merge went well; stopped before committing as requested
conflict files: (none)
```

**Now the meaning, which is what was asked.**

1. **The doctor count merges coherently — except finding 1, which survives intact.** Merged tree:
   README says 29 at all three sites; getting-started says 29 at all three including
   `29 PASS / 0 FAIL`; `docs/launch-readiness.md` still reads `29 checks` (line 282) and
   `28 PASS / 0 FAIL` (line 283). `pytest -q tests/test_doc_claims.py` on the merged tree:
   **`20 passed`**. The merged, landed, tested result is self-contradictory.
2. **No contradiction on home resolution, but a growing omission.** `w48/launch-rehearsal` adds a
   user-facing priority table to `docs/getting-started.md` — `1 --fleet-home`, `2 sid→home lookup`,
   `3 FLEET_HOME` — and states plainly that *"inside a Claude Code session that fleet itself
   launched … priority 2 answers first and `FLEET_HOME` is silently ignored."* Slice (c)'s hooks run
   a **different** order: argv → env → install root, step 2 deliberately skipped. Nothing merged is
   false — that table is written about `fleet` CLI invocations — but after both land, hooks are a
   `--fleet-home` consumer that no user-facing document describes, and the only published resolution
   order does not apply to them. An omission of the merge, not of either branch. One sentence in a
   later doc pass.
3. **A latent trap the two jointly create.** `w48/launch-rehearsal` tells users `--fleet-home`
   *"outranks both"* and is the reliable override. §2C's divergence means that under a genuine
   flag/lookup disagreement that override makes **views exit 1**. Both statements are individually
   true; a user following the merged advice on a multi-home box would meet a refusal on a read-only
   command. This is the divergence reaching a user-facing recommendation for the first time — it
   belongs on the same operator gate as §5 step 1, not on this branch.
4. **No collision on `fleet home` / PATH guidance.** Only `w48/launch-rehearsal` touches it;
   `w48/hookargv` mentions neither in any of the three files. Nothing to reconcile.

---

## 4. THE FLOORS — both reproduce the claim exactly

| run | claimed | measured | verdict |
|---|---|---|---|
| py 3.13.12 full | `4217 passed, 14 skipped, 1 xfailed` | `4217 passed, 14 skipped, 1 xfailed in 418.68s (0:06:58)` | **HIT** |
| py 3.10.1 full | identical triple | `4217 passed, 14 skipped, 1 xfailed in 373.97s (0:06:13)` | **HIT** |

Both on the branch tree with no mutant on disk. **Tree integrity proven around every run:** a
sha256 manifest of all **233** tracked files taken before the first floor and re-diffed after each
run — identical every time, and identical again after all 11 mutants. `git status --porcelain`
empty. `worker-settings.template.json` — the file the suite has previously overwritten with `{}` —
byte-unchanged at `8091bbf055e6c16ec07e2503b306fb954cb58c941dc2b5c067c325f7173e7fbe`.

The **+78** delta is confirmed independently and attributed:

```
tests/test_hook_fleet_home_argv.py   78 tests collected
branch 1161d39                     4232 tests collected   (= 4217 + 14 + 1)
base   fa236cb                     4154 tests collected   (= 4139 + 14 + 1)
```

4232 − 4154 = 78, and the new file contributes exactly 78. The lane's *"+78, all from
`tests/test_hook_fleet_home_argv.py`"* is exact, and the manager's baseline collection count of 4154
is independently confirmed. **The lane was wrong about a number twice and is right about this one.**

---

## 5. INSTRUMENT FAILURES — three, each caught by a control before it became a finding

Recorded because a gate that hides these is asking to be trusted on the rest.

1. **`git merge-tree --write-tree` parsed as a rev** (`fatal: unknown rev --write-tree`) on git
   2.34.1 — it would have reported "0 conflicts" by measuring nothing. Caught by running a
   known-conflicting control pair first. Redone as a real detached-worktree merge.
2. **`cmd /c` mangled the quoting** in the first attack-F executor, so the *control* failed with the
   identical error as the subject. That is how I knew the instrument had failed, not the subject.
   Redone via a `.bat` and Git Bash, where control and subject separated cleanly.
3. **A 10-minute tool timeout killed my first planter mid-run and stranded mutant X4 on disk**
   (`bin/fleet.py` modified). Caught immediately by `git status` plus the sha256 manifest, restored
   with `git checkout --`, all 233 files re-verified against baseline before anything else ran. The
   planter was re-run in the background with an on-disk recovery guard. **No floor run was ever
   started with a mutant on disk** — both floors completed before any mutant existed.

Two non-fatal ones: my attack-C control initially judged agreement by `rc == 0` and flagged itself
as failing, because `peek`/`result`/`doctor`/`q` legitimately exit non-zero in a bare temp home for
reasons unrelated to home resolution — the predicate was wrong, not the subject, and the
branch-vs-base comparison was unaffected because both sides used the identical harness. And I nearly
graded mutant X4 a "fail-open" from an armchair reading of the diff; driving it showed both shipped
and mutant FAIL, so it is a message-quality gap. Both corrections are in the findings above.

---

## 6. SAFETY LEDGER — every `fleet` command, and the home it actually touched

Every invocation ran as a child process of my own scripts with **`CLAUDE_CODE_SESSION_ID` removed**,
so §5 step 2's sid→home lookup misses and cannot outrank the home I named. The brief is right that
`FLEET_HOME` alone is not a fence inside a fleet-launched session; removing the sid is what makes it
one. `INSTALL_ROOT` for the `init`/`doctor` drives was a detached worktree under the job tmp dir, so
even a step-4 fallback could not reach the real home.

| command | count | home it touched |
|---|---|---|
| `fleet home` | 3 | temp home — used as a **gate**: the script refuses to run `init`/`doctor` unless `fleet home`, run exactly the same way, prints the temp path |
| `fleet doctor` | 2 | temp home (once before `init`, once after) |
| `fleet init` | 1 | temp home. **No `--home`** (never appends to the homes list). **No `--statusline`** |
| `fleet clean` | 2 | temp two-home worlds (attack C disagreement control) |
| `status`, `peek`, `result`, `q`, `knowledge`, `sup-status`, `sup-context`, `sup-boot`, `sup-checkpoint` | 40+ | temp two-home worlds under the OS temp dir |

One note on the brief's instruction to pass `--fleet-home <temp>`: **it cannot be used to name a
home you are about to `init`.** Measured — `fleet home --fleet-home <fresh temp>` refuses with
`--fleet-home … is not initialized (not_initialized)`, because §5 step 1 validates that
`state/fleet.json` exists and `fleet init` does not create it. (This is the same behaviour
`w48/launch-rehearsal` documents.) The `init`/`doctor` drives therefore used the env channel with
the sid removed, gated on `fleet home` run identically — which is the verification the brief
actually asked for.

- **`fleet init` was NEVER run against `C:/proga/claude-fleet`.** No command in this gate named it.
- **`~/.claude/fleet-homes.list`: ABSENT before and ABSENT after** — snapped and compared
  programmatically, not assumed. This machine has no homes list at all.
- **`~/.claude/settings.json`: unchanged** — `(mtime_ns, size)` identical before and after
  (`1786210442854189800, 1859`).
- No statusline. No spawn into any project. No push, no merge, no ref moved. `supervisor/GOALS.md`
  and `docs/OPERATOR-GATES.md` untouched.
- Litter created by hostile-argv drives (`C:/a`, `C:/does`) removed, absence verified.
- Two detached worktrees under the job tmp dir created no branch and moved no ref.

---

## 7. WHERE THIS BRIEF WAS WRONG, and where it was right

**Right, and it changed my order of work:** *"B or C may outrank A."* They did. I drove both before
touching the governance question, and C's grade turned entirely on a measurement (the pre-slice
wrong-home read) that only exists if you go looking for what the *old* code did.

**Wrong 1 — the BLOCKING pre-commitment on C.** Reachability is the right test and the
pre-commitment is still too strong. The branch makes a view exit 1 **in a state where the previous
behaviour was to return 0 while reading the wrong home**, with the same terminal outcome for the
successor either way. A loud refusal naming the correct home is not a regression against a silent
wrong answer. Graded CLEARED, and said so explicitly rather than applying a grade the measurement
does not support.

**Wrong 2 — uncertainty #2 resolves in the lane's favour.** The divergence is pre-existing;
`apply_resolved_home`, `resolve_home` and `TERMINUS_VIEW_VERBS` are byte-identical across the branch.

**Wrong 3 — the doc overlap is NOT benign.** The brief was right to distrust the clean auto-merge.
But the incoherence is not *between* the branches — it is *within* `w48/hookargv`, and the merge
merely carries it through intact while the pin stays green.

**Wrong 4 — "the standing expectation is a live fail-open."** There is not one here. The lane's
mutant table is truthful, its alignment figure reproduces to the line, its floors reproduce to the
test, and the three things it told the gate to attack are genuinely its three weakest points.
Manufacturing a BLOCKING finding to match the a3 precedent would have been this gate's failure mode.
The two MAJOR findings I do have are both in the *documentation and detection* skirt of the change,
not in its mechanism — and one of them exists only because the row in finding 2 was built at all.

---

## 8. WHAT I DID NOT DO

- Did not re-run the `fa236cb` **execution** floor (the manager states they measured `4139/14/1` on
  both interpreters). I confirmed the baseline **collection** count of 4154 instead, which is
  consistent with it and is what the +78 attribution needs.
- Did not drive the hooks inside a real Claude Code session — the drive is subprocess-level with
  real argv and real stdin JSON.
- Did not construct a genuine cross-home sid contamination in the real fleet; I argued its
  unreachability from the absent homes list instead.
- Did not fix anything. Nothing outside `docs/lanes/w48-gc.md` on `w48/gc` was changed; every mutant
  was restored byte-identically and verified.
