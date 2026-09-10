# Lane `w63-statusline` — G-K5 build item (1): the statusline row carries the home's identity

**Branch** `w63/statusline-home`, base `64aa96b`, two commits: `245bdf1` (the feature),
`b6edddd` (the re-pins the feature's insertion forced). No push, no merge, no other ref moved.

**Every line below is marked MEASURED or BELIEVED.** MEASURED = I ran it in this lane and the
command is shown or nameable. BELIEVED = read from source or inherited and not re-driven.

---

## 0. The answer in one line

**MEASURED.** On a machine that runs more than one fleet the row now opens `[fleet:a3ad]` instead
of `[fleet]`, where the four hex digits are `fleet.home_tag()` of the home whose registry the row
counted. On a machine with one fleet — every operator's machine today, this one included — the row
is **byte-identical** to the row that shipped at `64aa96b`.

```text
# volatile: host state -- measured 2026-09-10 on this box, ANSI stripped, old tree vs new tree
# run back to back against the same live registries; "real" = the operator's real ~,
# "sbx" = a sandbox HOME whose fleet-homes.list lists the dogfood home
real live  BEFORE(55) [fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h
real live  AFTER (55) [fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h   => BYTE-IDENTICAL
real dogf  BEFORE(55) [fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h
real dogf  AFTER (55) [fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h   => BYTE-IDENTICAL
sbx  live  BEFORE(55) [fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h
sbx  live  AFTER (60) [fleet:a3ad]  sup held 38m  4 bodies  work 2 38m  idle 12 2h  => DIFFERS
sbx  dogf  BEFORE(18) [fleet]  idle 1 2h
sbx  dogf  AFTER (23) [fleet:c3e5]  idle 1 2h                                       => DIFFERS
```

**MEASURED.** The cost is **exactly five columns**, on every row, only on a multi-fleet machine:
55 → 60 and 18 → 23. The brief's ceiling was *"a home identity that doubles the row's width is a
regression"*; this is +9 % of the real row.

---

## 1. I re-derived §1 before building. Both halves hold.

The brief warned that its own §1 — *per-home resolution is BUILT, the row carrying the identity is
NOT* — was inherited from `docs/lanes/w62-dogfood.md` §3-P4 and not measured by the supervisor.
**I did not take it on trust.** Sandbox `HOME` at `$CLAUDE_JOB_DIR/tmp/sbx`, the dogfood home added
to the **sandbox** list with the real `fleet homes --add`, four runs of `bin/fleet_statusline.py`
at `64aa96b`:

```text
# volatile: host state -- measured 2026-09-10, BEFORE any edit, tree at 64aa96b
--- REAL machine HOME (homes list ABSENT) ---
dogfood worker's sid   : [fleet]  sup held  4 bodies  work 2  idle 12 1h
live-home worker's sid : [fleet]  sup held  4 bodies  work 2  idle 12 1h
--- SANDBOX HOME (dogfood IS listed) ---
dogfood worker's sid   : [fleet]  idle 1 1h
live-home worker's sid : [fleet]  sup held  4 bodies  work 2  idle 12 1h
```

**MEASURED — all three of §1's claims reproduce, independently, on my own tree:**

1. **Per-home RESOLUTION is built and works.** Two sids, two different rows. I built nothing here.
2. **The row does NOT carry the identity.** Both rows say `[fleet]`. `PREFIX = "[fleet]"` is a
   module constant with one render site.
3. **On the machine as it stands, the feature is invisible.** `~/.claude/fleet-homes.list` does not
   exist (verified at lane start and at lane end), so `population_is_multi_home` is False, the
   short-circuit fires, and both sids render the live home. The two `REAL` rows above are identical.

**So the brief was right, and saying so is the honest answer.** What it was wrong about is §7.

---

## 2. What I built, and why this shape

### 2.1 `fleet.home_tag()` — four hex digits over `home_identity()`

**MEASURED** (`tests/test_statusline_home_tag.py`, 47 tests): pure function of the home; the three
spellings `C:\f`, `C:/f/`, `C:/f` that the homes-list fold declares to be one home tag identically;
two different homes tag differently; the output is `[0-9a-f]{4}` for every input driven, including
`Path`, `17`, `None`, `""`, `"/\x1b[2K/evil"`, a lone surrogate, and a 5000-character path.

**Why a digest and not a readable abbreviation — and this is the decision I most want the gate to
attack.** Four candidate shapes, all rejected but one:

| Shape | Example | Rejected because |
|---|---|---|
| full path | `[fleet:/home/altai/proga/fleet]` | 4× the row's width |
| basename | `[fleet:fleet-dogfood]` | **not injective, and not injective in the COMMON case for this tool.** A fleet home is a clone or worktree of this repo, so `/home/a/proga/fleet`, `/srv/fleet` and `/mnt/w/fleet` all abbreviate to `fleet`. Two homes rendering identical nameplate bytes is P1-13 on the one field added to stop that confusion, and it is *worse* than no tag: the operator now believes the bar separates them |
| shortest unique path tail | `[fleet:proga/fleet]` vs `[fleet:work/fleet]` | injective, readable — but **population-dependent**: adding an unrelated home renames an existing one. Also unbounded in width |
| basename + digest | `[fleet:dogfood.4f]` | injective and readable, ~13 columns. The brief asked for *"the shortest thing that is unambiguous"*; this is not it |
| **digest (chosen)** | `[fleet:c3e5]` | 5 columns, pure, population-independent, and **maximum entropy per column** — see below |

**BELIEVED (arithmetic, not measured).** Bounded width is non-injective for *every* scheme — there
are more absolute paths than four-character strings — so "can it collide" is the wrong question and
"what does each character buy" is the right one. A digest spends every character on entropy; a
readable abbreviation spends them on whatever the paths have in common, which for this tool is the
word `fleet`. At four hex digits (65 536 buckets), five homes on one machine collide with
probability ≈ 1.5e-4.

**And the digest is a sanitiser, which the alternatives are not.** A member path comes out of
`~/.claude/fleet-homes.list`; since multi-fleet slice (d) the reader is not necessarily its writer,
and the tag lands **inside the nameplate** — the one token `fleet_statusline._safe` strips brackets
to protect (`test_a_forged_all_clear_cannot_be_rendered`). Hex digits cannot carry an ESC, a CR or
a bracket at all, so there is no second sanitiser for a later lane to forget. A name-shaped tag
would have needed `_safe` plus bounding on a brand-new foreign-text field.

### 2.2 The nameplate, not a field beside it

`nameplate(tag)` returns `PREFIX` when there is no tag and `[fleet:<tag>]` when there is, **sliced
from `PREFIX` rather than retyped** — this file already treats a second literal spelling of its own
nameplate as a defect class (`test_the_terminus_text_is_not_a_retyped_literal`), and
`test_the_tagged_nameplate_is_derived_from_prefix_not_retyped` monkeypatches `PREFIX` to prove it.

**Rejected: a separate field (`[fleet]  a3ad  work 3`).** It would have broken **no** existing test
(see §4), which is the strongest argument for it and I still rejected it: a bare hex field reads as
one more status datum among six on a line that is scanned rather than read, whereas the nameplate
is the token the operator's eye already lands on. The tag is the fleet's NAME, not a fact about it.
**Recorded so the gate can overturn it cheaply — it is a two-line change.**

**Rejected: a per-home COLOUR.** Colour on this line is rationed by doctrine — grey is reserved for
`dead`, every other hue is a documented status — so a hue derived from the tag would have to be
drawn from the same small palette and `[fleet]` would eventually render in `working` green.

### 2.3 Where the tag is and is not rendered

**MEASURED** (`TestWhichStatesCarryATag`). `rendered_home_tag` returns a tag on exactly
`HOME_LOOKUP` and `HOME_DEFAULT` — the two verdicts that render a roster — and `""` on everything
else, including a hand-built record, a `None` record, and a `home_tag` that raises.

* `HOME_SINGLE` → no tag. This is the short-circuit **and** `resolve_blob_home`'s error value, so a
  resolution that *dies* degrades to the shipped row rather than to a new word. §5's arming
  paragraph already bound slice (d) to *"with a determinate population of <2: byte-identical to
  today"*; the tag inherits that rule instead of inventing a second one.
  **MEASURED both ways**: no homes list → bare row; `resolution_population` monkeypatched to raise
  → bare row.
* `HOME_DEFAULT` **is** tagged. On a multi-fleet machine an untagged row among tagged ones would be
  the one row the operator could not place.
* The §5 step-5 terminus and the ambiguity word are **untagged by design**: both mean *there is no
  home to name*, and §5's refusal contract is *"facts + the `fleet homes` view, never a chosen
  home"*.

**MEASURED, and it corrected my own first draft of a test.** I expected a corrupt default home to
render a tagged fault row (`[fleet:ad9a]: registry unreadable`). It does not: a corrupt registry
fails `home_is_initialized`, so §5 steps 3/4 are skipped and step 5's terminus takes the line —
`[fleet]: no home -- registry unreadable`. **Residual, recorded rather than fixed: on a multi-fleet
machine that line does not say WHICH home was unreadable.** Naming it is a change to §5's refusal
contract, which §4 of my brief puts outside this lane. See §6, gate draft G-K5-a.

### 2.4 The legend — because four hex digits name no directory

A tag nobody can resolve is an operator hazard, so the mapping is readable on two verb-tier
surfaces that call the **same pure function**:

```text
# volatile: host state -- measured 2026-09-10, SANDBOX homes list, sid stripped
$ fleet homes
fleet homes: <sandbox>/.claude/fleet-homes.list
  c3e5  /home/altai/proga/fleet-dogfood  ok (1 worker)

$ fleet home                                          # UNCHANGED -- see below
/home/altai/proga/fleet
$ fleet home --tag
a3ad
$ FLEET_HOME=/home/altai/proga/fleet-dogfood fleet home --tag
c3e5
```

**MEASURED.** `a3ad` and `c3e5` are the same tags the bar rendered in §0. `fleet homes` also
**names a tag collision** rather than letting two homes quietly share a nameplate
(`test_a_tag_collision_is_named_rather_than_silent` forces one).

**Bare `fleet home` is byte-unchanged and must stay so** — `$(fleet home)` is substituted into
paths by the skill, the slash commands and the briefs, so the tag is a FLAG and not a second column
(`test_bare_fleet_home_is_unchanged`).

**Known gap, stated plainly.** `fleet homes` renders the LISTED homes. An install-root home that
was never added to the list — which is the live home on this machine right now — appears in no row,
so `fleet home --tag` is the only surface that can name it. I did not extend `fleet homes` to
render the legacy term: that view's text is EMBEDDED verbatim in §5's refusals, and changing what
it means is a doctrine change, not a renderer change.

### 2.5 The doctrine this surface is bound by — D4, unmoved

**MEASURED** (`test_the_tag_adds_no_read_to_the_view`): the test counts every `read_registry_at`
call `main()` makes on a two-home machine, then repeats the run with `rendered_home_tag` stubbed
out, and requires the two lists to be equal. **The tag adds no read.** `home_tag` is a pure string
function over a path the process already holds; the homes list was read once by `resolve_blob_home`
before this field existed and whether or not it does. No lock, no probe, no write, no quarantine,
no `mkdir`. `tests/test_views_doctrine.py` and `tests/test_terminal_surface.py` are green.

**I did not need to widen the view's read surface, so I filed no gate for that.** §3 of the brief
told me to stop and file one if I did.

---

## 3. Suite

**PREDICTED IN WRITING BEFORE THE RUN** (`state/journals/w63-statusline.md`, written at build-end
and before any full-suite invocation): *5025 collected, `6 failed, 5002 passed, 16 skipped,
1 xfailed`, identical on 3.10 and 3.12* — baseline 4978 plus exactly 47 new tests, six unchanged
host-assumption ids.

**MEASURED — the prediction is exact on both interpreters.** Run from a separate
`git clone --no-local` of this branch at `b6edddd` into `$CLAUDE_JOB_DIR/tmp/suite`; **the main
checkout and the sibling lane's worktree were never used for a suite run.**

```text
# volatile: host state -- measured 2026-09-10, fresh clone at b6edddd
$ uv run --no-project --python 3.12 --with pytest python -m pytest -q --color=no
6 failed, 5002 passed, 16 skipped, 1 xfailed in 360.38s (0:06:00)
$ uv run --no-project --python 3.10 --with pytest python -m pytest -q --color=no
6 failed, 5002 passed, 16 skipped, 1 xfailed in 444.96s (0:07:24)
```

The six, identical on both: three `test_fleet_index.py::TestPathContainment` and one
`test_fleet_q.py::TestOutlinePathContainment` (Windows drive-qualified-path escapes) and two
`test_terminal_surface.py::TestCollaboratorInstall` (venv-shim re-exec). **BELIEVED** that these
are the same six the brief names — I did not run the suite at `64aa96b` myself; the collected count
(5025 = 4978 + 47, and I added exactly 47 tests and deleted none) is what makes that consistent.

`tools/verify_receipts.py --self-test --strict docs/specs/terminal-surface.md` — **MEASURED**:
`11/11 reproduce exactly`, self-test PASSED on both seed classes, exit 0.

---

## 4. THE FIRST RUN WAS RED IN 22 PLACES, AND THAT IS THE MOST USEFUL THING IN THIS REPORT

**MEASURED.** My first full-suite run reported **28 failed**, not 6. Twenty-two failures in three
files that have nothing to do with the statusline's rendering:

| Count | What | Why |
|---|---|---|
| 10 | `test_self_citations.py` (8) + `test_retired_sid_citations.py` (2) | `bin/fleet.py` cites its own line numbers in prose and those citations are **pinned against the source**. Inserting `home_tag` at `:4286` and the legend at `:6583`/`:6650`/`:22430` shifted **33 cited numbers** (+55 and +98) and one range END |
| 3 | `test_self_citations.py`, *"covered by no expectation"* at `(6583, 9)`, `(6650, 9)`, `(22430, 9)` | the scanner's `_NUMBER_RE` is `:(\d+)`, so writing the example `[fleet:9c3a]` in `bin/fleet.py` prose reads as a self-citation to **line 9**. The example now reads `[fleet:<tag>]` there; the concrete form survives in `fleet_statusline.py`, which that scanner does not read |
| 11 | `test_statusline_home.py::TestAForeignHomeCannotEraseTheOperatorsRow` | those assertions use the `[fleet]` **literal** as shorthand for *"fleet's row is on stdout"*, on fixtures that list TWO homes and therefore now render `[fleet:<tag>]`. The row was never missing |
| 1 | `test_homes_verb.py::test_each_listed_home_renders_with_its_read_time_state` | keyed a rendered row by its FIRST token, which is now the tag column |

**Why this matters more than the count.** `w62-dogfood` §3-P4 called item (1) *"a renderer change"*
and my brief inherited that framing. **MEASURED: it is not.** The tag needs a home-identity helper,
the helper belongs in `bin/fleet.py` beside `home_identity` (invariant 9 — one module owns the
identity vocabulary), and *any* insertion into `bin/fleet.py` above line 22 000 rots this repo's
line-number pins. A lane that budgeted for a renderer change would have shipped a red suite or,
worse, moved the helper somewhere doctrinally wrong to avoid the shift.

**The re-pins are mechanical and verifiable, and I want them read as the riskiest thing on this
branch.** The renumbering was computed from a `difflib` line map between `64aa96b:bin/fleet.py` and
the new file — no citation TEXT changed, only its number — and `tests/test_self_citations.py` is
what verifies the result. `git show --stat b6edddd -- bin/fleet.py` is `23 insertions(+), 23 deletions(-)`
— every one of them a bare number, or the `9c3a` → `<tag>` edit.

**The two test-assertion edits are the ones a gate should look at hardest**, because a lane
loosening a security pin to make its own feature pass is exactly the shape of a bad change. What I
did: added `has_nameplate()` to `test_statusline_home.py`, matching `\[fleet(?::[0-9a-f]+)?\]` and
nothing else, and swapped two `sl.PREFIX in out` assertions for it. **The predicate is not weaker**
— bracket content is `fleet` or `fleet:<hex>`, so a forged plate still fails — and the neighbouring
pins that actually enforce the anti-forgery property (`line.count(sl.PREFIX) == 1`,
`"[" not in line[len(sl.PREFIX):]`, `test_the_erasure_detector_can_see_an_erasure`) were **not
touched and are green**.

---

## 5. What this lane did NOT do

- **MEASURED.** No append to `~/.claude/fleet-homes.list`. `ls -la` reports
  `No such file or directory` at lane start and again after the last suite run. Every two-home
  measurement used a sandbox `HOME` under `$CLAUDE_JOB_DIR/tmp/sbx`, whose list holds exactly
  `/home/altai/proga/fleet-dogfood`.
- **MEASURED.** G-K5 item (2) (`fleet init` inside a repo creating a home) is untouched. No
  `fleet init` of any kind was run.
- **MEASURED.** `bin/fleet_keeper.py` is not in the diff — lane `w63-sidunion` owns it.
- **MEASURED.** `docs/OPERATOR-GATES.md` is not in the diff. No box ticked, no gate filed by me;
  §6's draft is text in this report.
- **MEASURED.** The dogfood home was read and never written: it is not in the diff, and every
  statusline invocation is a view (D4). The suite was never run in `/home/altai/proga/fleet` nor in
  a sibling lane's worktree.
- **MEASURED.** No push, no merge, no other ref moved. One branch, two commits.
- **MEASURED.** Nothing under `/home/altai/proga/` was touched except this worktree; `fleet` and
  `fleet-dogfood` were read only.
- No process left running.

---

## 6. Gate draft — for the supervisor, not filed

**G-K5-a — should the §5 terminus name the home whose registry it could not read?**
Today a multi-fleet machine with a broken default home renders
`[fleet]: no home -- registry unreadable`: the fault is named, the home is not (§2.3). Naming it
would tell the operator which fleet to fix without running a second command. Against: §5's refusal
contract is *"facts + the `fleet homes` view, never a paste-ready command with a chosen home"*, and
the terminus is a refusal — the statusline is on the view side of that split precisely because it
cannot embed the view. **I did not build it.** The remedy, if ruled for, is one line in
`render_home_terminus` and belongs with whoever owns §5, not with a renderer lane.

**G-K5-b — should a tag collision be an alarm on the BAR, not only in `fleet homes`?**
`fleet homes` names a collision (§2.4). The bar cannot see one without reading the whole population
per render, which today it does not do — `resolve_blob_home` reads the homes list but the
statusline never compares tags across homes. Adding that comparison is cheap (the population is
already in hand) but it makes the tag **population-dependent**, which is the property §2.1 rejected
the path-tail scheme for. Probability at four hex digits and five homes is ≈ 1.5e-4.

---

## 7. WHERE THIS BRIEF WAS WRONG

**W1 — §5's fence does not bind this surface at all, and its stated control cannot gate it.
MEASURED.** The brief: *"`env -u CLAUDE_CODE_SESSION_ID` is required on **every** `fleet`
invocation aimed at another home … Gate each step on `fleet home` invoked exactly the same way."*
For the **statusline** that is inapplicable in both halves:

```text
# volatile: host state -- measured 2026-09-10, SANDBOX homes list, new tree
blob=dogfood, sid env UNSET       : [fleet:c3e5]  idle 1 2h
blob=dogfood, sid env = LIVE sid  : [fleet:c3e5]  idle 1 2h
blob=EMPTY,   sid env = dogfood   : [fleet:a3ad]  sup held 38m  4 bodies  work 2 39m  idle 12 2h
blob=EMPTY,   sid env UNSET       : [fleet:a3ad]  sup held 38m  4 bodies  work 2 39m  idle 12 2h
```

**MEASURED: `CLAUDE_CODE_SESSION_ID` changes nothing, in either direction.** The mechanism is
stated in the source and I confirmed it drives the behaviour: `blob_session_id` returns `""` for a
missing sid, `""` is not `None`, and `resolve_home` consults the environment only when `sid is
None` — so the env var is unreachable from this surface by construction, and
`fleet_statusline.py` says why in its own docstring (*"a second evidence source that agrees today
is a second thing to disagree tomorrow"*). Consequence for method, which is the part that matters:
**`fleet home` is not a valid gate for a statusline step**, because `fleet home` reads the env sid
and the statusline reads only the blob — the control and the controlled step take different inputs.
I gated every step on `bin/fleet_statusline.py` itself instead. I kept `-u` on every `fleet` CLI
call regardless; the fence is right about the CLI and I have no evidence against that half.

**W2 — §2's width baseline understates the real row by 11 columns. MEASURED.** The brief quotes
today's row as `[fleet]  sup held  4 bodies  work 3 idle 9 5h` (44 chars). Measured on this box
today it is `[fleet]  sup held 38m  4 bodies  work 2 38m  idle 12 2h` — **55 chars**: the D2 age
suffixes the quoted sample omits are present, twice. This makes the width argument *easier*, not
harder (+5 is 9 % of 55, not 11 % of 44), so nothing in my design turns on it — but the sample was
pasted forward from `w62-dogfood` §3-P4 and has aged, and the brief presents it as *"today's row"*.

**W3 — §1's *"it is a renderer change"* framing (inherited from `w62-dogfood` §3-P4) is wrong, and
it is the framing that would have cost a lane its suite. MEASURED: 22 red tests in three files
that never mention the statusline.** See §4. The half of item (1) that is unbuilt is not a render;
it is a new entry in `bin/fleet.py`'s identity vocabulary plus a render, and this repo pins
`bin/fleet.py` line numbers.

**W4 — §6's prediction about *what* would be wrong was wrong. MEASURED.** The brief: *"§1's
correction is the likeliest [to be wrong] … Run `bin/fleet_statusline.py` against both homes
yourself before you accept my framing of which half is built."* I did, four runs at `64aa96b`
(§1), and **all three of §1's claims reproduced exactly**. The brief's least-trusted paragraph is
the one that survived intact; what did not survive is the sentence right next to it about the
change being a renderer change (W3) and the method paragraph in §5 (W1).

**W5 — §2's *"Measure what a single-home machine renders before and after"* proves the
non-regression and cannot prove the feature. MEASURED, and the brief half-knew it.** §1 itself
records that this machine cannot render two different rows today; the corollary it does not draw is
that the requested before/after on a single-home machine is **required to be identical**, so a lane
that treated it as the acceptance test would conclude it had built nothing. Both halves are in §0:
the `real` pair is the non-regression, the `sbx` pair is the feature.

**Confirmed, not wrong:** §1's three claims (re-measured, §1). §3's doctrine — the statusline is a
view and the tag needed no new read (`test_the_tag_adds_no_read_to_the_view`). §4's scope fences —
nothing outside them is in the diff. §5's claim that a second real home exists at
`/home/altai/proga/fleet-dogfood` with a worker in its registry and is **not** in
`~/.claude/fleet-homes.list` (verified at lane start and lane end). §5's sandbox recipe, which
worked verbatim.
