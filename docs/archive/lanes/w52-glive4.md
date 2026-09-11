# w52-glive4 — adversarial gate on the DISCHARGE of gate `w52-glive3`

Subject: `w52/live` @ `3d1f9d0` (`12c238c..3d1f9d0`). Gating tree: `w52/glive4` @ `3d1f9d0` in
`C:/proga/fleet-w52-glive4`. Verified before starting: `git rev-parse --abbrev-ref HEAD` →
`w52/glive4`, `git rev-parse --short HEAD` → `3d1f9d0`.

---

## VERDICT: **NOT-GATING**

The discharge does what it was told to do, and the two MAJOR findings it was sent to close are
genuinely closed. I re-derived both by routes the lane did not use, and both survive:

- **F1's element half is closed on both verbs, for every shape a JSON registry can hold.** MEASURED
  by driving `cmd_respawn` and `cmd_kill` end to end at `64b43c2`, `12c238c` and `3d1f9d0` from my
  own harness, not the lane's fixtures. At `3d1f9d0` every shape completes the verb, reports the
  corrupt entry on stderr, still sweeps the good sid, still writes the tombstone, and still marks
  the worker dead.
- **F3 is closed.** I replanted `M-W52-KILLGUARD` against the full suite. It is caught by **exactly
  the six new kill-side pins, plus the one `test_native.py` pin, and by zero respawn pins** — both
  halves of the lane's claim confirmed.
- **The floors hit the prediction on both interpreters**, and I hit my own independently-derived
  prediction on the base tree too.

**Nothing I found is a regression this branch introduces.** Everything below is either a claim that
reaches further than the code, or a pre-existing hole that the axis questions correctly suspected
was there. The largest of them — that the corrupt-registry class is wider than two verbs and wider
than the sweep — is real, is measured, and belongs to a successor slice rather than to this gate.

| id | severity | evidence | is it this branch's? |
|---|---|---|---|
| G1 | **MAJOR** | MEASURED | claim is; defect is pre-existing |
| G2 | **MAJOR** | MEASURED | no — pre-existing, three verbs |
| G3 | MINOR | MEASURED | **yes** |
| G4 | MINOR | MEASURED | **yes** |
| G5 | MINOR | MEASURED | **yes** (widening) |
| G6 | MINOR | MEASURED | **yes** |
| G7 | MINOR | MEASURED | **yes** (§10.2, graded) |
| G8 | MINOR | MEASURED | no — the tree's |
| G9 | MINOR | MEASURED | **yes** (arithmetic) |

---

## 0. WHAT I RAN, AND AGAINST WHICH HOME

**ZERO `fleet` verbs. No fleet home was touched, read, or written — not the live home, not a
temporary one.** I did not run `fleet home`, `fleet init`, `fleet status`, or any other verb. I did
not write `~/.claude/settings.json` and did not append to `~/.claude/fleet-homes.list`.

Everything below is `git`, `pytest`, and standalone Python that imports a materialised
`bin/fleet.py` as a module with `fleet.FLEET_HOME` pointed at a fresh `tempfile.mkdtemp()`. The
module-level import never reads a real home.

One structural action worth declaring: I created a **detached** worktree at
`$CLAUDE_JOB_DIR/tmp/base-64b43c2` (`git worktree add --detach … 64b43c2`) to measure the base
floor. A detached worktree creates and moves **no ref**; `git rev-parse` on `w52/glive4` was
unchanged after it. It is removed at the end of this turn. Commits: `w52/glive4` only. No push, no
merge, no other ref moved.

Scratch that survives, per the brief's warning about vanishing session directories:
`C:/proga/fleet-w52-glive4/state/glive4/` (gitignored, inside the worktree) holds every driver,
planter and raw output. The base worktree is one command to recreate and the command is in the
journal.

**The fence.** My digest is a sha256 over **tracked files only** (`git ls-files` + path + content).
That is deliberately not the template's working-tree digest: tracked-only is immune by construction
to the `<repo>/--bogus/state/…` hole the brief names, because ignored and untracked paths are never
in the population. Value before the first floor run and after the last mutant restore, identical:

```
71d68d12501bc3a7  files=263
```

`git status --porcelain` was empty at both ends. **I did not edit any tracked file while any run was
in flight** — this document was written after the last run finished, which is the lane's §7.8 lesson
applied rather than re-learned. My scratch writes all went to `state/`, which is outside the
tracked-file population by construction.

---

## 1. AXIS 1 — THE CENSUS, THE BOUNDARY, AND THE POPULATION

### 1.1 Four is right, and I did not use AST to say so

The lane derived "four sites" by AST. I re-derived it by **bytecode**, which is a different route
and a stronger one: it shows the operations the interpreter actually performs on the loop variable
rather than the syntax that produced them.

`dis.get_instructions(_sweep_retired_sessions)` at `12c238c`, every instruction consuming `retired`:

| line | opcode | what it does to the untrusted value |
|---|---|---|
| 8759 | `CONTAINS_OP` | hashes it (membership) |
| 8761 | `BINARY_SLICE` | subscripts it — **the M1 skip's own message** |
| 8788 | `CALL_KW` → `_stop_native_session_status` | hands it to a callee |
| 8792 | `BINARY_SLICE` | subscripts it — the progress line |

**FOUR. MEASURED. The lane is right and the gate's three was one short** — the missed one is `:8761`,
exactly as the lane says. At `3d1f9d0` the guard is genuinely first: `:8814 isinstance` + `TO_BOOL`
precede all four, every one of which is downstream of the `continue`.

The lane's *"the stop itself hashes it"* is also **CONFIRMED**, and it is two touches rather than
one: `_stop_native_session_status` does `_native_job_ref(sid)` (→ `sid.split`, `AttributeError`) and
then `refs = dict.fromkeys((ref or …, sid))` at `:13019` (→ hash, `TypeError`). Both are inside the
`try`, so neither can abort.

### 1.2 "Sweep body" is the WRONG boundary, and the `dict.fromkeys` discovery is only half of why

MEASURED. The statements that consume the untrusted value between the registry read and its last use
span **three** scopes, not one:

| scope | site | status at `3d1f9d0` |
|---|---|---|
| caller — container coercion | `:8370` `list(before.get("retired_sids", []))` (respawn), `:8973`/`:8974` `list(… or [])` (kill) | **UNGUARDED — aborts both verbs** |
| caller — dedup | `:8453` / `:8982` `_ordered_unique_sids(…)` | guarded (was `dict.fromkeys`) |
| caller — truthiness filter | `:8453` / `:8982` `if s and …` | **silently drops the falsy corrupt half** |
| body — four sites above | `:8814` guard, then `:8821/:8823/:8849/:8854` | guarded |
| callee — inside the `try` | `_native_job_ref`, `dict.fromkeys` `:13019` | covered by the best-effort `try` |

So the lane found the second scope and missed the first and third. The correct boundary is *"every
statement between reading `retired_sids` out of the registry and the last one that touches it"*, and
it does not respect function edges.

### 1.3 Driven, not read — every shape, both verbs, three trees

My own harness (`state/glive4/drive_corrupt.py`), independent of
`tests/test_respawn_retired_sweep.py`. **The input population is exactly what `json.load` of
`state/fleet.json` can yield** — `str`, `int`, `float`, `bool`, `None`, `list`, `dict`. I tried
`bytes` and learned it is out of scope the hard way: `save_registry` itself raises
`TypeError: Object of type bytes is not JSON serializable`, so a bytes element is not a reachable
state of a file-backed registry.

**Element corruption, `retired_sids = [<bad>, "good-b"]`:**

| element | `64b43c2` respawn | `64b43c2` kill | `12c238c` both | `3d1f9d0` both |
|---|---|---|---|---|
| `123`, `True`, `3.5` | no sweep at all (0 stops) | `AttributeError: 'int' object has no attribute 'split'` | `TypeError: not subscriptable` | **ok — verb completes** |
| `{"a":1}`, `["x"]`, `[["deep"]]` | no sweep at all | `TypeError: unhashable type` | `TypeError: unhashable type` | **ok — verb completes** |
| `None`, `""`, `0`, `False` | no sweep | ok | ok | ok (**but see G3**) |
| `{}`, `[]` | no sweep | `TypeError: unhashable type` | `TypeError: unhashable type` | ok (**but see G3**) |

At `3d1f9d0`, for every truthy shape, on **both** verbs: verb completes, `is not a session id` on
stderr, `good` still stopped, tombstone written (`stopped` / `killed`), and `kill` leaves
`status:"dead"`. **The lane's F1 discharge claim reproduces in full, from a harness it did not
write.** Note also that base "respawned fine" only in the sense that base never swept at all — the
comparison the gate drew is right, but base's virtue here was absence.

**Container corruption — and this is where it does not hold. See G1.**

| container | `3d1f9d0` respawn | `3d1f9d0` kill |
|---|---|---|
| `123` | `TypeError: 'int' object is not iterable`, 0 stops, no tombstone | same exception, **after** the primary stop, **no tombstone, `status:"working"`** |
| `null` | `TypeError: 'NoneType' object is not iterable` | ok (`or []` covers it) |
| `"abcdefghij"` | **10 bogus single-character stops** | 10 bogus stops |
| `{"a": 1}` | 1 bogus stop (iterates keys) | 1 bogus stop |
| `[]` | ok | ok |

Every one of these behaves **identically at `64b43c2`**, so the container class is pre-existing —
except the two string/dict rows on `respawn`, which base could not reach because base had no sweep.

### 1.4 Is there a third caller? By AST — and the answer is not the one the question expects

**Callers of `_sweep_retired_sessions`: exactly TWO** (`_cmd_respawn_native:8462`,
`_cmd_kill_native:8989`). **Callers of `_ordered_unique_sids`: exactly TWO** (`:8453`, `:8982`).
MEASURED by `ast.walk` at all three trees.

But the *population that matters* is not the helper's callers:

1. **The sweep loop has a third copy**, `_cmd_respawn_supervisor:9772`, and by AST it sits inside no
   `try` at all. The lane's §10.1 says it lacks **four** guards (M1 skip, progress line, best-effort
   `try`, corrupt-element skip). **MEASURED: correct, all four.**
2. **`fleet clean` is a THIRD VERB consuming the same untrusted value** — see **G2**. Nobody named
   it.

And the reach of the best-effort guard is precisely measurable. Of the four direct
`_stop_native_session_status` call sites at `3d1f9d0`, **exactly one has an enclosing `try`**:

```
line 8849  _sweep_retired_sessions      YES   <- the shared body, serving both callers
line 8947  _cmd_kill_native             NO    (kill's PRIMARY stop -- gate F6)
line 9769  _cmd_respawn_supervisor      NO    (its primary stop)
line 9774  _cmd_respawn_supervisor      NO    (its sweep loop -- the third copy)
```

The extraction genuinely paid for itself: one guarded site covers two verbs. It also makes the
remaining exposure exact.

---

## 2. AXIS 2 — THE COVERAGE CLAIM, MEASURED

### 2.1 The replant. Both halves of the claim are TRUE, and there is a third half nobody stated

`M-W52-KILLGUARD` replanted from the lane's own ledger text, on bytes, against the **full** suite:

```
rc=1  KILLED   11 failed, 4635 passed, 14 skipped, 1 xfailed in 463.55s
```

Decomposed:

| group | count | which |
|---|---|---|
| new kill-side pins | **6** | `…cannot_abort_the_KILL[bool|dict|float|int|list]` + `test_a_raising_stop_CANNOT_abort_the_KILL` |
| `test_native.py` pin | **1** | `TestCmdKillNative::test_retired_sid_matching_another_workers_current_sid_is_skipped` |
| **respawn pins** | **0** | — |
| **citation pins — undisclosed** | **4** | `test_retired_sid_citations` ×2, `test_self_citations` ×2 |

**"Exactly six kill-side pins and no respawn pin" is CONFIRMED, and so is the `test_native.py` pin
that F5's driver repair made visible.** The lane's claim survives the check it was asked to survive.

**The 4 citation failures are the lane's own mutant shifting line numbers** — the plant grows the
file by 201 bytes / +4 lines, so every `bin/fleet.py` self-citation below `:8989` rots. The gate's
original G1 was **line-count preserving on purpose**, and said why: *"a mutant that shifts line
numbers goes RED for a reason nobody can attribute."* The lane adopted that discipline verbatim
elsewhere (§5.4's byte-exactness repair) and did not carry it into its own replant. It is invisible
inside the ledger only because `TESTFILES` excludes the citation files. **G6.**

### 2.2 Mutants the lane did not think of

Planter: `state/glive4/plant.py`. Bytes only; the anchor must occur **exactly once** or it aborts
having written nothing and run nothing; the patch is proven applied by three assertions (sha moved,
anchor absent, replacement present) **before pytest starts**; restore is verified by sha in a
`finally`. Every prediction below was written into the planter source before any of them ran.

*The exactly-once guard earned itself on first use:* four multi-line anchors matched **zero** times
because the checkout is CRLF and my byte literals used `\n`. It refused and ran nothing. Had it
warned instead of aborting, I would have had four clean floors that read exactly like green mutants
— which is the failure mode the brief names, reproduced accidentally and caught by the rule.

Scope: `tests/{test_liveness_readers,test_respawn_retired_sweep,test_native,test_sup_tombstone}.py`
= 513 tests (the ledger's `TESTFILES` plus the supervisor tombstone file), except where noted.

| mutant | predicted | MEASURED | killed by |
|---|---|---|---|
| `M-G4-FALSY` — drop the `or not retired` arm | SURVIVED | **SURVIVED** | nothing → **G3** |
| `M-G4-TRUNC` — drop the `:.40` on the corrupt report | SURVIVED | **SURVIVED** | nothing → **G4** |
| `M-G4-GUARDLAST` — guard no longer FIRST | KILLED | **KILLED** | 10 (5 kill + 5 respawn) |
| `M-G4-BREAK` — `continue` → `break` | KILLED | **KILLED** | 10 |
| `M-G4-KILLDEDUP` — revert the **kill** dedup site | KILLED | **KILLED** | **2, both kill-side** |
| `M-G4-STDERR` — report to stdout | KILLED | **KILLED** | 10 |
| `M-G4-SELFCITE` — falsify a `bin/fleet.py` self-citation | KILLED | **KILLED** | 5 |
| `M-G4-DOCCITE` — falsify `docs/SPEC.md`'s citation (**full suite**) | SURVIVED | **SURVIVED** | nothing → **§3** |
| `M-W52-KILLGUARD` — the gate's G1 (**full suite**) | KILLED, kill-side only | **KILLED** | 6 + 1, and 4 collateral |

**9/9 predictions hit.** `M-G4-GUARDLAST` is the one that earns the lane's "FIRST" comment: moving
the guard one statement later re-opens F1 for `dict`/`list` on both verbs, and ten pins say so.

### 2.3 The generalisation, graded

> *A shared helper needs a pin per caller, because extraction single-sources the code and not the
> coverage.*

**It is right, and it is worth keeping.** `M-W52-KILLGUARD` is the direct proof: the shared body is
one function, and the mutant that reintroduces the regression on `kill` is caught by six kill-driven
pins and by **zero** of the respawn pins standing over the identical lines.

Two amendments from measurement:

1. **State it as coverage-per-entry-point, not per-caller.** `M-G4-KILLDEDUP` is the clean case: the
   *fix* has two call sites, and the lane's own `M-W52-DEDUP` plants the revert at the respawn site
   only. The pins do cover the kill site (my mutant proves it, 2 kill-side reds) — but the ledger
   does not prove they do. **The lesson applies to the instrument that carries it, and was not
   applied there.** G6.
2. **The generalisation has an unbuilt consequence already on the branch.**
   `_cmd_respawn_supervisor`'s copy is a third entry point into the same loop with **zero** pins on
   any of its four missing guards. The lane files this as successor slice 1 and is right to; the
   generalisation is what says that slice needs its own pins rather than inheriting the shared
   body's.

---

## 3. AXIS 3 — §10.2 GRADED: THE DIAGNOSIS IS RIGHT AND BOTH REMEDIES ARE WRONG

> `_HISTORICAL_PREFIXES` keys on **path prefix**, while `docs/SPEC.md` declares its pin **in prose** —
> and **no instrument reads prose.**

### 3.1 Half one — the exemption really is path-keyed. CONFIRMED

MEASURED. `tests/test_doc_claims.py:445-469` is a tuple of path prefixes and `current_tree_docs()`
selects with `str.startswith(_HISTORICAL_PREFIXES)`. No file content is consulted. A document cannot
declare anything to it.

*(Also verified, per the mid-lane correction: `"docs/specs/"` **is** in that tuple, at line 452,
with its reason beside it. The brief's original sentence was wrong and the correction is right.
Note the population is **tracked markdown only** — `tests/`, `bin/` and `tools/` are not "not
exempt", they are not in `CHECK_COUNT_DOCS` at all. This changed nothing in my arithmetic; I had not
used the list when the correction arrived.)*

### 3.2 Half two — a prose pin is invisible, and the hole is BIGGER than §10.2 says

Not merely *"no instrument reads prose."* **No instrument resolves a line-number citation living in
a markdown document at all — for any document, pinned or not.**

MEASURED, by enumerating every test that parses a `:NNNN` citation. There are exactly two —
`tests/test_self_citations.py` and `tests/test_retired_sid_citations.py` — and both resolve against
`bin/fleet.py` and nothing else, which `test_self_citations.py`'s own docstring states. Every other
markdown-reading test checks phrasing, counts, verb existence, or section anchors.

The unread population, measured by me at `3d1f9d0`:

```
tracked *.md files                                  : 156
`bin/fleet.py:NNNN` citations in markdown           : 900 across 55 files
`<doc>.md:NNNN` cross-document citations in markdown: 665 across 54 files
docs/SPEC.md: 1 `bin/fleet.py:NNNN` citation, 50 `name` @NNN anchors
```

**And I proved it two-sided rather than arguing it.** Same falsification, once on each side of the
oracle's boundary:

| seed | scope | result |
|---|---|---|
| `_sweep_husks` (`:11072` → `:99999`) in `bin/fleet.py` | citation tests | **KILLED — 5 pins fire** |
| `bin/fleet.py:61-110` → `:99998-99999` in `docs/SPEC.md` | **full suite** | **SURVIVED — `4646 passed, 14 skipped, 1 xfailed`** |

The second run is byte-identical to a clean floor. **A deliberately false citation in the spec of
record — the exact citation the whole F2 / §3.6 / §10.2 argument is about — changes nothing anywhere
in 4661 tests.**

### 3.3 The grade

**Diagnosis: CORRECT, and it explains the wave's three retractions.** A classifier that mirrors
`_HISTORICAL_PREFIXES` will read `docs/SPEC.md` as current-tree, conclude its citations claim the
current tree, and grade them stale. Three parties did exactly that.

**Remedy A — "a machine-readable pin marker": premature, not wrong.** The tree already has this
mechanism and it works: `# at <sha>`, matched gutter-blind anywhere in a document, with
`test_every_spec_is_classified` making *unclassified* a hard failure rather than a silent pass. But
it is scoped to `SPEC_DIR.glob("*.md")` = `docs/specs/`, and `docs/SPEC.md` is not in that directory.
More importantly, **a pin marker is an input to a reader that does not exist.** §3.2 measured the
reader population at zero. Adding a marker closes nothing on its own; it is step 2 of a two-step
change whose step 1 — a cross-document citation resolver — is unbuilt and is already an owed item.

**Remedy B — "an explicit entry" in the exemption list: actively harmful. Do not do this.**
`tests/test_doc_claims.py:730` (`test_the_check_count_population_is_derived_and_split_correctly`)
**asserts that `docs/SPEC.md` IS in `CHECK_COUNT_DOCS`**, under the comment *"present: the
stranger-facing surfaces AND the spec of record"* — and that membership exists because w50 caught
that file shipping `**23** checks` against an actual 28. Exempting the document would turn that pin
red and re-open a hole closed the expensive way. The reason is structural: **`docs/SPEC.md` carries
two claim classes pointing at two different trees** — line numbers pinned to `c63d7dd`, and check
counts about now. A path-keyed, all-or-nothing switch cannot express that, which is also why the
tree keys on path in the first place.

**What it would actually take, cheapest first:**

1. **Anchor conversion — needs no new instrument and is already the tree's ratified answer.**
   `knowledge/lessons.md` made exactly this move (line citations → `#anchor`) because it is
   append-at-top; `tests/test_doctrine_citations.py` resolves `§NN` headings into a spec and checks
   verbatim quotation; `tests/test_supervisor.py` splits `docs/SPEC.md` on heading text.
   **`docs/SPEC.md` §0 already instructs it** — *"the function names are the durable anchors"* — and
   then cites a line range anyway. Converting the one citation costs one edit and removes the
   ambiguity that produced three retractions.
2. **Then, if the 900 + 665 population is judged worth holding, build the cross-document resolver**
   and give it a per-document pin declaration. Machine-readable pinning is the right shape *for that
   instrument*, once it exists.
3. **Never a blanket path exemption for `docs/SPEC.md`.**

**Filed, not built** — as instructed. **G7.**

---

## 4. AXIS 4 — THE INSTRUMENT FAILURES

### 4.1 The fixpoint-loop failure is not in this lane's report

The brief says the lane disclosed four instrument failures, *"one [of which] matters far beyond this
branch: a fixpoint loop printed `FIXPOINT` while a test was red, because its pattern could not see
that failure class."*

**MEASURED: that disclosure is not in `docs/lanes/w52-live.md`.** `FIXPOINT` appears three times in
the report, all in §6, and none describes a loop reporting convergence over a red. What the lane
actually disclosed is five instrument problems, and the list does not match the brief's:

| brief says | in the report? |
|---|---|
| a fixpoint loop printed `FIXPOINT` while a test was red | **NO** |
| a digest script lost with a scratch dir | YES — §7.7 |
| a fence contaminated by editing during a run | YES — §7.8 |
| prose that accidentally minted a citation | **not as an instrument failure** |
| *(unlisted)* the driver graded one file, `TESTFILE` a single string | YES — §5.4 |
| *(unlisted)* the planter is text-mode | YES — §5.4, repaired |
| *(unlisted)* a re-pin script flattened CRLF→LF over 1173 lines | YES — §5.5 |

The nearest real thing is one directory over: `docs/lanes/w51-dtype.md:443`, *"FIXPOINT is a census,
not a red/green read. A pin file reports its FIRST failure per test, so one green run is a lower
bound."* **The brief's own "what this probably got wrong" section names this possibility and is
right.** I have graded the tree instead, which is the version that matters.

### 4.2 The tree-level version, which is worse than the brief feared

There is **no fixpoint-loop tool in the repo**; the loop is a procedure (run the citation oracles,
re-pin, repeat until green). So its "pattern" is not a regex — it is **the oracle's population**, and
that is the thing that cannot see the failure class.

§3.2's two-sided seed is the measurement. A landing that re-pins citations and runs this loop to
fixpoint converges over `bin/fleet.py`-about-itself and is **structurally silent** on 900 + 665
citations in markdown. That is not a loop that misparses a red; **it is a loop that cannot produce
one.** `docs/lanes/BRIEF-TEMPLATE.md` already states the rule — *"name the oracle's population before
you trust its colour"*, recording a supervisor who ordered this pin run to fixpoint as a merge oracle
and *"would have shipped all 108 green."*

**Answer to the axis question:** the loop the wave-52 landing will run is safe against the failures
it can see and blind to the ones it cannot, and the boundary is exactly `bin/fleet.py`. Its verdict
is sound for `bin/fleet.py` self-citations and means nothing about anything else. A lander must not
read a green citation oracle as "citations are re-pinned."

The one grading instrument that *does* parse output — `tools/mutate_liveness.py` — grades on
`returncode != 0` (`:313`, `:394`), which sees every failure class including collection errors. Its
`FAILED `-prefixed id list (`:339`) would come back empty on an `ERROR`, so a collection error grades
KILLED with no attribution. Display gap, not a verdict gap; not worth a finding.

### 4.3 The digest instrument is still not durable. G8

The lane's own rule from §7.7 is *"keep the instrument where the run cannot outlive it."*

**MEASURED: `git ls-files` finds no digest script anywhere in the repo.**
`docs/lanes/BRIEF-TEMPLATE.md:142` prescribes the measurement and ships no implementation. The lesson
was written down and not acted on, so the next lane loses it the same way — and the wave-52 landing
is the run that most needs it.

### 4.4 "Prose that accidentally minted a citation" — checked for scope

MEASURED: `docs/lanes/w52-live.md` contains **6** `bin/fleet.py:NNNN` strings at `3d1f9d0` (5 at
`12c238c`) and 3 cross-document ones. So yes, prose mints citation-shaped text, and every lane report
adds more.

But the scope conclusion is the opposite of a population *problem* for the instrument reading
citations: **there is no instrument reading them.** The population is 900 + 665 and the readership is
zero (§3.2). Prose cannot corrupt an oracle that never looks at it. This connects to Axis 3 exactly
as the brief suspected, but the connection is *absence of a reader*, not *a reader with a bad
population*.

---

## 5. AXIS 5 — THE FLOOR

**Predicted before running anything**, in the journal, derived from my own collection measurements:

| tree | collected (MEASURED by me) | predicted | **MEASURED** |
|---|---|---|---|
| `64b43c2` py-3.13 | **4636** | 4621 / 14 / 1 | **`4621 passed, 14 skipped, 1 xfailed`** ✅ 525.38s |
| `3d1f9d0` py-3.13 | **4661** | 4646 / 14 / 1 | **`4646 passed, 14 skipped, 1 xfailed`** ✅ 539.09s |
| `3d1f9d0` py-3.10 | **4661** | 4646 / 14 / 1 | **`4646 passed, 14 skipped, 1 xfailed`** ✅ 454.49s |

**Every term, all three runs.** No red on either interpreter, so the py-3.13 flake seen elsewhere
this wave did not appear and there was nothing to re-run in isolation. Base `4636` is now measured a
fourth independent time and agrees.

**I ran the base floor specifically so the 14/1 split would be measured rather than inherited** — it
was the one term of my prediction I had taken from the brief, I said so in the prediction, and it is
now derived.

**The delta is attributable by construction**, per-file, at both trees:

| file | `64b43c2` | `3d1f9d0` | delta |
|---|---|---|---|
| `tests/test_respawn_retired_sweep.py` | absent (`git cat-file -e` fails) | 25 | **+25** |
| `tests/test_liveness_readers.py` | 34 | 34 | 0 |
| `tests/test_doc_claims.py` | 75 | 75 | 0 |
| **total** | **4636** | **4661** | **+25** |

`docs/lanes/w52-live.md` is new tracked markdown and adds **zero** collected tests, which is what
`docs/lanes/` being in `_HISTORICAL_PREFIXES` predicts. `tools/mutate_liveness.py` is not collected.
**One file accounts for the entire delta.**

**The MISS's regression is genuinely closed.** Driven directly rather than inferred from a green
suite — `run=lambda *a, **k: None`, the §7.2 stub shape, at all three trees:

| tree | respawn | kill |
|---|---|---|
| `64b43c2` | no sweep to break | ABORT at the **primary** stop |
| `12c238c` | **ok** — completes, tombstone, `error (AttributeError) -- not retried` on stderr | ABORT at the primary stop |
| `3d1f9d0` | **ok** — same | ABORT at the primary stop |

Driven again with `retired_sids = []` — no sweep at all — and `kill` aborts identically, which proves
the remaining abort is the **primary** stop and not the sweep. Same with a raising `run`. **That is
gate F6, pre-existing, unchanged at all three trees, and correctly accepted-not-actioned by the
lane.** The regression the missed prediction caught is fixed; the *class* it belongs to is not, and
the lane says so.

---

## 6. AXIS 6 — MERGE STATE. THE LANE IS RIGHT, AND IT IS STRUCTURAL

**Confirmed, and stronger than "no conflict".** MEASURED:

```
main                                          : 0d82460
merge-base(main, w52/live)                    : 64b43c2   (unchanged)
files main changed since the merge-base       : supervisor/JOURNAL.md   -- exactly one
files w52/live changed since the merge-base   : bin/fleet.py, docs/lanes/w52-live.md,
                                                tests/test_liveness_readers.py,
                                                tests/test_respawn_retired_sweep.py,
                                                tools/mutate_liveness.py
OVERLAP                                       : none
```

The two change sets are **disjoint at file granularity**, so the clean merge is not luck — no textual
merge is performed on any file at all. My anchored probe agrees with the lane's and with the
manager's census, a third independent route:

```
w52/live  x main  ->  0    anchored conflict markers  (grep -cE '^\+?<<<<<<<')
w35/nd4c  x main  ->  25   control, non-vacuous
```

**What the lander still owes, stated plainly.** A floor measured **at the merge result**, on both
interpreters. Everything in §5 is measured on a tree based at `64b43c2`. The lane's sentence — *"a
clean merge is not a passing floor, and that measurement belongs to the merging lane"* — is correct
and I endorse it. Concretely the lander owes:

1. both interpreters at the merge commit, predicted before running;
2. the collection count re-derived there — **it should still be 4661**, because `main`'s only delta
   is `supervisor/JOURNAL.md`, which is in `_HISTORICAL_PREFIXES` and collects nothing. That is a
   prediction the lander can check cheaply, and a disagreement would mean something else moved;
3. the citation re-pin, **with §4.2's warning attached**: a green `tests/test_self_citations.py` is a
   statement about `bin/fleet.py` self-citations and about nothing else.

---

## 7. FINDINGS

### G1 — **MAJOR, MEASURED.** The discharge's headline claim is wider than what it delivers: a corrupt registry can still abort both callers, at the container

Commit `325ca94`'s subject is *"F1 — a corrupt registry may not abort the sweep's callers either"*,
and the new inline comment reads *"A CORRUPT ELEMENT MUST NOT ABORT THE VERB EITHER."* The element
half is true. **The container half is false**, and the container is read from the same corrupt
registry by the same threat model.

MEASURED at `3d1f9d0`, `retired_sids: 123`:

- `respawn` → `TypeError: 'int' object is not iterable` from `:8370`, **0 stops, no tombstone**;
- `kill` → same exception from `:8973`, **after** the primary stop, **no tombstone, `status:"working"`**
  — the precise consequence §7.2 calls the worse one, reached by a different route;
- `retired_sids: null` → aborts `respawn` (`:8370` lacks the `or []` that `:8973` has).

Both surface as unhandled tracebacks. MEASURED at `bin/fleet.py:21854`, `main()`'s catch-all is
`except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
UnsupportedPlatformError)`; `TypeError` and `AttributeError` are not among them, and neither is
caught by the three narrower handlers above it.

**Not gating, because it is identical at `64b43c2`** — pre-existing, not introduced and not widened.
The finding is the *claim*: the branch states a guarantee it does not deliver, in a commit subject
and in a code comment, on the recovery verb.

Two things make it worth a MAJOR rather than a MINOR:

- **The tree already has the idiom and these two callers do not use it.** `bin/fleet.py:12034` does
  `isinstance(retired_sids, list)` before iterating, and `:10966` documents the rule in words:
  *"non-list retired_sids are skipped, never trusted."*
- **An element-typed guard is the wrong shape and cannot be widened into the right one.** Iterating a
  *string* container yields strings, which pass `isinstance(retired, str)` cleanly — see G5.

### G2 — **MAJOR, MEASURED.** The population is not two. `fleet clean` is a third exposed verb, and its abort lands after a durable write

Nobody in this wave has named it. `_remove_worker_files` builds
`[outcome_path(s) for s in retired_sids]` (`:9884-9885`) from the registry value with no guard, and
`outcome_path` → `name_fs_stem` → `s.replace(...)`.

Driven (`state/glive4/drive_clean.py`), two dead workers, the first with a corrupt element:

| element | `3d1f9d0` | `64b43c2` |
|---|---|---|
| `123`, `True`, `3.5`, `{...}`, `[...]` | `AttributeError: … has no attribute 'replace'` | identical |
| control `"zzz-1"` | completes, file removed | identical |

**And the abort lands after `save_registry`.** In every failing case: `registry_left=[]` — both
workers are already gone from the registry and their `cleaned` events already appended — while
`wB_file_orphaned=True`, i.e. the *second* worker's files were never removed. A half-completed
destructive verb with a raw traceback, from the same input class, on a third verb.

Pre-existing and unchanged by this branch, so **not gating**. It is the direct answer to the axis:
the population of *sweep-helper callers* is two, the population of *sweep loops* is three, and the
population of **verbs consuming untrusted `retired_sids` is at least four** (`respawn`, `kill`,
`sup-respawn`, `clean`). Any successor slice scoped to "the sweep" will miss `clean` again.

### G3 — MINOR, MEASURED. The falsy half is silently dropped, which falsifies the new helper's own stated rationale

`_ordered_unique_sids`' docstring says unhashable values *"pass through UNCHANGED rather than being
dropped here… Dropping them silently would hide a corrupt registry from the operator;
`_sweep_retired_sessions` is the only place that … can say so on stderr, so the reporting belongs
there and this function stays a dedup."*

MEASURED at `3d1f9d0`: for `{}` and `[]` — unhashable **and** falsy — the pass-through works exactly
as designed, and then both callers' `if s` filter drops them before the sweep ever sees them. **No
report is produced.** Same for `None`, `""`, `0`, `False`. The value is passed through to a reporter
that never receives it, so the sentence is false for precisely the values it was written about.

Corollary, and the reason `M-G4-FALSY` **SURVIVED**: the `or not retired` arm of the new guard is
unreachable from both real callers, so nothing pins it. (Measured against the 513-test sweep scope,
not the full suite — see §9.)

Cheapest correct fix is not in the guard: report the drop where it happens, in the callers' filter.

### G4 — MINOR, MEASURED. The corrupt report's truncation is unpinned

`M-G4-TRUNC` removes the `:.40` from `{retired!r:.40}` and **SURVIVED**. The new code's own comment
says the truncation exists *"so a large corrupt value cannot flood the operator's terminal"* — a
stated property with no pin. A 10 MB string in `retired_sids` would print in full, per sid, up to the
cap. (513-test scope.)

### G5 — MINOR, MEASURED. The branch newly makes a corrupt *container* issue up to 20 bogus stops from `respawn`

`retired_sids: "abcdefghij"` → `list(...)` explodes the string into 10 single characters, each a
`str`, each passing the new `isinstance` guard, each issued as `claude stop <char>`. `{"a": 1}`
iterates keys the same way. MEASURED on both verbs at all three trees — but base `respawn` issued
**0** stops because it had no sweep, so on `respawn` this branch widened it from nothing to up to
`_RETIRED_SID_SWEEP_CAP` = 20 bogus subprocesses at 5 s each: **up to 100 s** added to the recovery
verb, which is F7's window with a new trigger.

Best-effort, so it cannot abort — the harm is wall time and a misleading progress line, not
corruption. It is listed separately from G1 because it is the one row of the container class this
branch actually widened, and because it is the concrete demonstration that an element type-check
cannot cover a container defect.

### G6 — MINOR, MEASURED. The F3 lesson is not applied to the instrument that carries it

Two instances, both in `tools/mutate_liveness.py`:

1. **`M-W52-DEDUP` plants the `dict.fromkeys` revert at the respawn call site only.** The fix has two
   call sites. My `M-G4-KILLDEDUP` plants the kill side and it is **KILLED by exactly 2 pins, both
   kill-side** — so the coverage exists and the ledger simply does not prove it. This is the lane's
   own generalisation, unapplied one file over from where it was written.
2. **`M-W52-KILLGUARD` is not line-count preserving.** +201 bytes / +4 lines, producing 4
   unattributable citation reds on any run wider than `TESTFILES` (§2.1). The gate's original G1 was
   line-count preserving and said why; the lane adopted that discipline in §5.4 and dropped it here.

Neither weakens the F1/F3 fixes. Both weaken the ledger as evidence, which is the thing the ledger
exists to be.

### G7 — MINOR, MEASURED. §10.2: right diagnosis, both remedies wrong

Full grade in §3. Summary: the path-keyed exemption is confirmed; the invisibility is confirmed and
is **larger** than stated (no instrument resolves any markdown-resident citation — proved by a
falsified `docs/SPEC.md` citation surviving the full 4661-test suite). Remedy A (pin marker) is an
input to a reader that does not exist. Remedy B (explicit exemption entry) would turn
`test_the_check_count_population_is_derived_and_split_correctly` red and re-open the `**23** checks`
hole. The cheap correct move is anchor conversion, which the tree has already ratified three times
and which `docs/SPEC.md` §0 already instructs. **Filed, not built.**

### G8 — MINOR, MEASURED. The instrument-durability lesson was written down and not acted on

No digest script is tracked anywhere in the repo (`git ls-files`), and
`docs/lanes/BRIEF-TEMPLATE.md:142` prescribes the measurement without shipping an implementation. The
next lane loses it exactly as §7.7 did — and the wave-52 landing is the run that most needs a fence.
One tracked file closes it.

### G9 — MINOR, MEASURED. A small arithmetic slip in the discharge's own decomposition

§7.7 and commit `bd463f7` say *"12 of the 13 added cases come from two `parametrize`d pins over five
shapes each."* MEASURED: the discharge adds **4** test functions (13 → 17 `def test_`), of which two
are parametrized over five shapes, giving **10 + 2 = 12** new collected items. The `+12` prediction
was right and hit; the sentence explaining it is not. Nothing downstream depends on it.

---

## 8. WHERE THIS BRIEF WAS WRONG

1. **"`docs/specs/` is not exempt from `CHECK_COUNT_DOCS`" — WRONG, and corrected mid-lane by the
   manager before I had used it.** Verified independently: `"docs/specs/"` is in
   `_HISTORICAL_PREFIXES` at `tests/test_doc_claims.py:452`. A further refinement the correction did
   not make: the population is **tracked markdown only**, so `tests/`, `bin/` and `tools/` are not
   "not exempt" — they are not in the population at all. Zero impact on my arithmetic.
2. **"The lane disclosed four of its own instrument failures … a fixpoint loop printed `FIXPOINT`
   while a test was red."** MEASURED: that disclosure is not in the report, and the four the brief
   lists are not the ones the report contains (§4.1). The brief's own hedge — *"that the fixpoint-loop
   defect is this lane's rather than the tree's"* — is correct. I graded the tree instead, and the
   tree's version is worse: the loop's oracle cannot produce the red at all, rather than failing to
   parse it.
3. **"Do not assume the population is two" — right to warn, and the true answer is bigger than the
   warning.** The helper has exactly two callers; the sweep loop has three sites; **the verbs exposed
   to the input class number at least four**, and the fourth (`fleet clean`) has the worst failure
   mode of any of them (G2).
4. **"That 'four sites' is now complete"** — flagged as a likely error and it is one, though not in
   the direction implied. Four is exactly right *for the sweep body*, confirmed by bytecode. It is
   the **boundary** that is incomplete: the container coercion and the truthiness filter sit outside
   the body and outside the fix (§1.2).
5. **"§10.2's proposal is sound rather than a plausible mechanism for a real symptom."** The symptom
   is real, the mechanism is correct, and **both proposed remedies are wrong** — one premature, one
   harmful (§3.3). The brief anticipated this one.
6. **A framing quibble, recorded because it shaped the axis.** Axis 1 opens with *"a regression the
   branch itself introduced … where base respawned fine."* True, but base "respawned fine" by having
   no sweep at all: at `64b43c2` respawn issues **0** stops for every shape, corrupt or not. The
   regression is real; base's tolerance was absence, not robustness, and that matters when judging
   how much the branch owes.

**Instructions I refused:** none. Every instruction in this brief was executable as written, once the
`docs/specs/` correction landed.

---

## 9. WHAT I CHOSE TO CUT, RECORDED AS A FINDING OF ITS OWN

The brief declined to tell me what to cut and asked me to record the choice. Four cuts, in
descending order of how much I think they could hide something:

1. **The two SURVIVED sweep mutants (`M-G4-FALSY`, `M-G4-TRUNC`) were graded against 513 tests, not
   4661.** This is the cut most likely to be wrong, because a SURVIVED verdict is exactly the claim
   that needs the wide net, and I spent my two full-suite mutant runs on `M-W52-KILLGUARD` (required
   by the axis) and `M-G4-DOCCITE` (the load-bearing evidence for §3). The scope I used is a superset
   of the ledger's own `TESTFILES`, so within the ledger's contract the verdicts stand. **A successor
   should re-run these two against the full suite before treating G3 and G4 as settled.**
2. **I did not drive `_cmd_respawn_supervisor` end to end.** Its exposure is established by AST (no
   enclosing `try` at `:9769` or `:9774`) plus a direct measurement that
   `_stop_native_session_status(123, …)` raises. That is a sound argument, not a driven verb, and it
   is one rung below the standard I held everything else to.
3. **No base floor on py-3.10.** The brief required both interpreters at HEAD, which I ran; the base
   3.13 run was an addition to de-inherit the 14/1 split. A base 3.10 run would add nothing I would
   act on.
4. **I did not run `tools/verify_receipts.py`.** The branch touches no `docs/specs/**` file, and this
   verdict lives in `docs/lanes/`, which is exempt. Recorded so the absence is not mistaken for a
   pass.

---

## 10. WHAT I WOULD DO NEXT, IF I WERE THE LANDER

Neither of the first two is a blocker on this branch.

1. **Widen the corrupt-registry guard to the CONTAINER, at all four verbs** (G1 + G2). The tree's own
   idiom is already written at `:12034` and documented at `:10966`. `fleet clean` should be first,
   because it is the only one whose failure leaves a half-completed destructive operation.
2. **Carry the guards to `_cmd_respawn_supervisor`** — the lane's slice 1, with its own pins per the
   generalisation, not inherited from the shared body.
3. **The one edit I would make in this wave:** convert `docs/SPEC.md:84`'s single `bin/fleet.py:61-110`
   to a function-name anchor (§3.3). It is one line, it is what §0 already instructs, it removes the
   ambiguity that cost this wave three retractions, and — unlike everything else in §10.2 — it needs
   no instrument that does not exist. **I have not made it; I am a gate and I fixed nothing.**
