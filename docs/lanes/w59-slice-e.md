# w59-slice-e — how far multi-fleet actually is, measured, and what slice (e) still owes

**Lane:** research / audit. Branch `w59/slice-e`, worktree `/home/altai/proga/fleet-w59-slice-e`,
dispatched at `3fce992`. **One file written: this one.** No source, test or spec edit — every
mutation below was applied to a COPY of the tree outside the repo (§10).

**Every line is tagged MEASURED or BELIEVED.** MEASURED = a command ran on this host at `3fce992`
and its output is the ground for the sentence. BELIEVED = a reading of prose, and the prose is
quoted.

**Host note.** MEASURED: `~/.claude/fleet-homes.list` **does not exist** on `kz-work` — `ls` says
so. This machine is single-fleet today, and nothing this lane did changed that. All two-home
drives ran in `$CLAUDE_JOB_DIR/tmp/mf` with `HOME` redirected.

---

## 0. THE ANSWER, IN ONE PARAGRAPH — quote this to the phone

MEASURED. Four of the five build slices are shipped and pinned; the fifth, **`init --home`
(slice (b)), is the only unbuilt one and it is now the only thing standing between the operator
and a working per-repo fleet in the flag/env sense.** But the distance is *not* "one slice of
polish", and this is the finding the supervisor should carry: **on a machine that has been armed
— i.e. that has one home in `~/.claude/fleet-homes.list`, which is the very act of turning
multi-fleet on — there is today NO shipped path to create a second home.** All four routes were
driven and all four exit 1 (§5). So the honest sentence is: *multi-fleet's plumbing is built and
guarded, and the feature is not reachable at all until slice (b) lands, because arming it
produces a one-home machine that cannot grow.* Slice (b) is unblocked — operator gate 3 was ruled
2026-08-10 (*"split `init` the same way"*) — and a sibling lane is on it now. Slice (e) (pins) is
**substantially discharged**, at wave 51, not unknown: §7's ten pin categories all exist and
**every one of the ten has a mutant that reddens it on this host** (§2) — nine under a mutant
aimed at the category itself, and the tenth (category 2, the redirect's *reach*) under the same
mutant as category 1, because w51's conftest default subsumed it, which §2 row 2 measures rather
than assumes. What (e) still owes is small and
named in §7. The **zero-configuration** sense of the operator's sentence — cwd decides the home,
no flag, no env — **does not exist and cannot be reached without a new §5 step** (§6); that is an
operator decision nobody has been asked.

---

## 1. WHAT SLICE (e) ACTUALLY IS — the brief's framing is correct

MEASURED, `docs/specs/multi-fleet.md` Sequencing §3, item 3, verbatim:

> (0) split; (a) `read_registry_at` + list + lookup + arming + verb-effect table + `fleet homes`
> + global flag (with the rb7 C-2 argparse pin); (b) `init --home`; (c) hook argv + witness +
> `_render_successor_task` argv; (d) statusline (capture-gated); (e) pins.

So **(e) is "pins"**, one word, and the brief's assumption holds. The population is §7's ten
categories plus the two round-7 defect pins named as slice conditions in the v8 ratification.

**The brief's "UNKNOWN, and this is your centre of gravity" is the one place it is materially
wrong, and it is wrong in the good direction.** MEASURED: slice (e) was built at **wave 51**.
`tests/test_slice_e_pins.py` is 444 lines / 24 tests, landed across `438ef52` (RED), `47700d8`
(GREEN), `0117b83`, `ebf823a`, `2e3e44d`; the lane report is `docs/lanes/w51-slicee.md` (639
lines). Its census — six of §7's ten landed and toothy, two landed and vacuous (#3, #7), two
never built (#1, #4) — is what that lane repaired. **I did not inherit it. Every row below was
re-measured at `3fce992` with my own mutants.**

---

## 2. THE PIN TABLE — §7's ten categories, and whether each can FAIL

MEASURED at `3fce992`. Suite baseline first, because a mutant count means nothing without one:

```
uv run --no-project --python 3.12 --with pytest python -m pytest -q
6 failed, 4857 passed, 16 skipped, 1 xfailed in 341.54s      # = 4880 collected
```

4880 collected — identical to the figure root `CLAUDE.md` pins — and the six failures are the
documented host assumptions (four drive-qualified-path escapes, two venv-shim re-execs), not
fleet defects.

The **CAN IT FAIL** column is the one that matters. Each mutant was applied to a copy of the tree
(§10), the named selection re-run, and the copy restored.

| # | §7 category | Exists? Where | CAN IT FAIL — mutant, and the measured result |
|---|---|---|---|
| 1 | env fixture | **YES.** `tests/conftest.py::_never_touch_the_real_home` redirects `homes_list_path` alongside the other three helpers; asserted from a file that opts into no sandbox, `tests/test_slice_e_pins.py::TestTheConftestRedirectReachesEveryFile` | **YES.** `M1` — delete the `homes_list_path` redirect from conftest: **4 failed, 13 passed, 7 errors**. Failures name the default resolving to the operator's real list; the 7 errors are the canary fixture *refusing to write* it |
| 2 | homes-list-path monkeypatch | **YES**, now twice over: the conftest default plus four file-scoped `sandboxed_list` copies. Seed `test_the_redirect_is_actually_in_force` | **Subsumed by 1, and measured as such.** `M2` — drop `autouse` from `test_homes_list.py`'s file-scoped copy: **71 passed**, because the conftest default now covers it. That is the correct answer, not a hole: `M1` proves the default is what carries it |
| 3 | real-list-untouched pin | **YES.** `tests/conftest.py::_the_real_homes_list_is_untouched_afterwards` (session-scoped, content digest, never raises) + 7 seeds in `test_slice_e_pins.py::TestTheRealListGuardCanActuallySeeAChange` | **YES.** `M3` — `homes_list_drift` always returns `None`: **4 failed** (append / creation / deletion / same-length edit all reported invisible). And see §3: the guard catches a real 122-record append that the pin it replaced sleeps through |
| 4 | quiescent-home canary | **YES.** `test_slice_e_pins.py::TestTheQuiescentHomeCanary` — builds A and B, drives A, asserts B byte-identical; loud skip; `delete-if-never-quiescent` discharged by construction | **YES, but ONE ARM WIDE — see §7.2.** `M4` — `read_registry_at` appends a line to the home's `logs/` on every read: **1 failed**, `…[argv1]`, the `homes` arm. The `status`, `clean --yes` and `home` arms stayed green because with no sid the lookup never reads a foreign home at all |
| 5 | membership + fold pins | **YES.** Fold: `test_homes_list.py::TestTheSequenceFold`. Membership: `test_home_resolution.py::TestMembershipIsTheUnionAndSpawnedByNeverGrantsIt` | **YES, both.** `C5a` — fold becomes first-record-wins: **16 failed** across four files. `C5b` — `spawned_by` grants membership: **exactly 1 failed**, `test_spawned_by_never_grants_membership` |
| 6 | writer-contention pin | **YES.** `test_homes_list.py::TestWriterContention::test_concurrent_appends_lose_nothing` | **YES, and now on POSIX too.** `C6` — drop `O_APPEND` for `open`+`lseek(SEEK_END)`: **1 failed**, *"expected 100 folded members, got 80"*. w51 could only measure this against the Windows backend; **20% loss reproduced on Linux** |
| 7 | no-rewrite lint | **YES**, widened at w51. `test_homes_list.py::TestTheWriterIsAppendOnly::test_the_no_rewrite_lint`, population ≥12 scopes incl. `cmd_homes` | **YES.** `M7` — plant a whole-file `write_text` in `cmd_homes`: **1 failed**, *"these scopes touch the homes list and can rewrite it: [('cmd_homes', 'write_text')]"*. This is the exact shape that was a **proven full-suite survivor** before w51 |
| 8 | rendered "not initialized" | **YES.** `test_homes_verb.py::TestTheView::test_each_listed_home_renders_with_its_read_time_state` | **YES.** `C8` — drop the state-word mapping: **exactly 1 failed**, that test |
| 9 | destructive-tier pin | **YES.** `test_verb_effect_guard.py::TestTheDestructiveTierPin` (armed machine, env-resolved `clean` refuses / `spawn` proceeds) | **YES, and it is load-bearing across files.** `C9` — `_apply_wrong_home_guard` returns immediately: **10 failed**, including `test_slice_e_pins.py`'s own `test_the_reached_assertion_can_see_a_verb_that_never_ran` — the canary's seed notices that the tier stopped refusing |
| 10 | arming-indeterminacy pin | **YES**, and it is two mechanisms. `test_verb_effect_guard.py::TestIndeterminacyAlwaysArms` (the TIER) and `test_home_resolution.py::TestTheTerminus::test_an_unreadable_list_arms_the_terminus` (the TERMINUS gate) | **YES, both.** `C10b` — unreadable list no longer arms `multi_fleet_arming`: **2 failed**, exactly w51's pair. `C10` — `_multi_fleet_population_is_live` returns False on an unreadable list: **1 failed**, the terminus test. **These are different functions and w51's row conflated them** |

**Verdict: 10 of 10 categories exist, and every one has a mutant that reddens it** — nine under a
mutant aimed at the category itself, and category 2 under category 1's, which is the right answer
for a category the conftest default absorbed rather than a gap. **Nothing in §7's ten is owed.**
That is a suspicious-looking zero, which is why §3 exists, and it is not a clean bill of health:
§7 lists ten categories, and §7 is not the whole of what (e) owes — see §7 of this report.

### 2.1 The round-7 defect pins (the other half of the slice condition)

MEASURED, both present, both with their own seeds:

* **`['--fleet-home','H','autoclean']` silently dropped.** `tests/test_round7_defect_pins.py::
  TestGlobalPositionFleetHome`, plus the dest-collision lint below it — 9 test functions, two of
  them explicitly seeds. It pins the **PARSER** layer and says so at length in its own docstring.
  The **CLI** layer — which is where the defect lived — is pinned separately by
  `test_home_resolution.py:207::TestTheGlobalFlagIsReconciledNotClobbered`: four spellings yield
  one home, verbs that never defined the flag are reached, repetition with two values is refused,
  tokens after a bare `--` are values. The shipped fix is structural rather than linted:
  `strip_global_fleet_home` consumes the token before argparse runs, so **there is no second dest
  to clobber**. MEASURED end-to-end in the sandbox, three spellings, one answer, rc 0 each:
  `fleet --fleet-home A home`, `fleet home --fleet-home A`, `fleet --fleet-home=A home`.
* **`doctor --repair` unenumerated.** `TestDestructiveEnumerationsCarryTheRatifiedClass::
  test_the_repair_flag_is_carried_as_the_flagged_spelling` and `test_verb_effect_guard.py::
  test_doctor_repair_is_destructive_and_bare_doctor_is_not`. Also visible in shipped code:
  `apply_resolved_home`'s terminus arm reads `if command in TERMINUS_VIEW_VERBS and not
  getattr(args, "repair", False)` — `doctor` is a view, `doctor --repair` is not.

---

## 3. THE CONTROL — proof this instrument returns something other than green

The brief is right that *"a zero from an instrument that has never returned anything else is not
a measurement."* Two controls, both MEASURED.

**Control A — the same instrument returns GREEN for a pin with no teeth, on the same defect that
turns another pin RED.** `tests/test_home_resolution.py::test_the_real_list_is_untouched` still
ships at `3fce992` and is still a tautology (it compares `REAL_LIST.exists()` before and after one
read, under an autouse sandbox). Mutant `C3b` — `read_homes_list` appends one record to
`Path.home()/".claude"/"fleet-homes.list"` on every call — run with `HOME` pointed at a throwaway
directory holding a pre-created list:

```
### C3b-read_homes_list-appends-to-the-REAL-list      (tests/test_home_resolution.py)
ERROR …::test_the_real_list_is_untouched - AssertionError: the test suite changed the operator's real homes list at /h…
94 passed, 1 error in 3.02s
$ wc -l  <throwaway>/.claude/fleet-homes.list
123          # 1 pre-existing + 122 planted appends
```

Read it carefully, because the two halves are the whole point: the test **named** `test_the_real_
list_is_untouched` **PASSED** — it is one of the 94 — while **122 records were appended to the
list it is named after**. The ERROR is the *conftest session guard* w51 built, firing at teardown
and naming the breach. Same defect, one pin blind, one pin loud. w51 measured 122 too, and the
number reproduced exactly.

**Control B — my own instrument was wrong once and said so.** The first `M4` was an idempotent
write-back (`json.dumps(..., indent=2)` into the home's registry) and the canary reported **24
passed**. That was not a hole in the canary: `home_is_quiescent(b)` runs *before* the digest
snapshot in the test body, so the first mutated read normalised B and every later one was a
no-op. Replacing it with a non-idempotent append turned the canary RED. **A "green" from a
mutation harness is a claim about the mutant until you have shown the mutant does something.**

---

## 4. IS THE INTERFACE'S BUILT LIST TRUE? — re-derived, slice by slice

MEASURED at `3fce992` by grep/AST/parser-introspection, not by reading the census.

| Slice | Census claim | Verdict | How I derived it, and what "built" means here |
|---|---|---|---|
| **0** install/home split | BUILT | **TRUE** | `INSTALL_ROOT` = 13 occurrences in `bin/fleet.py`; `tests/test_install_home_split.py` = **41 tests**. "Built" = the two planes are separate *and derived rather than listed*: `test_no_bin_path_is_still_resolved_from_the_home` fails on any surviving `FLEET_HOME / "bin"`, and `conftest.py` carries the code-plane sandbox + drift guard (`_the_real_install_plane_is_byte_identical_afterwards`) |
| **(a)** reader + list + lookup + arming + table + `homes` + flag | BUILT | **TRUE, all seven parts** | `read_registry_at` (fleet.py:4087, 14 refs, `tests/test_read_registry_at.py` = 35 tests); `homes_list_path`/`read_homes_list`/`append_home_record`/`fold_homes_list` (`test_homes_list.py` = 71); `lookup_home_for_sid` + `resolve_home` + `apply_resolved_home` (`test_home_resolution.py` = 94); `multi_fleet_arming` + `_multi_fleet_population_is_live` + verb-effect tuples (`test_verb_effect_guard.py` = 61); `cmd_homes` with `--add`/`--retire` derived from the parser (`test_homes_verb.py` = 27); `_GLOBAL_HOME_FLAG` + `strip_global_fleet_home` (fleet.py:5380-5445). "Built" here = a verb ships, a pin guards it, and a mutant reddens the pin |
| **(b)** `init --home` | UNBUILT | **TRUE** | Derived from the parser, not grepped: `build_parser()` exposes **34** top-level subparsers; `init`'s option strings are exactly `['--chain','--force','--help','--nonce','--statusline','-h']`. No `--home`. **Unblocked** — operator gate 3 ruled 2026-08-10, *"split `init` the same way"*; branch `w59/inithome` exists and carried no commits past `3fce992` when I looked |
| **(c)** hook argv + successor argv | BUILT | **TRUE**, and the `witness` half is correctly reported vestigial | All four hooks carry `_ARGV_HOME_FLAG = "--fleet-home"` with a grammar their own docstrings say *"deliberately matches `fleet.strip_global_fleet_home`"*; `worker-settings.template.json` bakes `--fleet-home "{{FLEET_HOME}}"` into all four commands; `_render_successor_task` and `_render_sup_spawn_task` bake it into `sup-boot`, `sup-status --json`, `sup-checkpoint` (fleet.py:18064, 18099, 18335, 18360, 18362). `tests/test_hook_fleet_home_argv.py` = **78 tests**. The `witness` ruling is real (`docs/OPERATOR-GATES.md` §Settled, 2026-08-10) — **but see §7.3, it is undischarged in the spec** |
| **(d)** statusline | BUILT | **TRUE** | `resolve_blob_home(payload, population=None, install=None)` at `bin/fleet_statusline.py:525`; it *delegates* to `fleet.resolve_home` / `fleet.resolution_population` / `fleet.read_registry_at` rather than re-spelling §5. `tests/test_statusline_home.py` = **251 tests**, including a D1 view-doctrine class (no lock, no probe, no subprocess, no write, exit 0 always). Landed at wave 50, i.e. *before* w51-slicee, which is why w51's §9.2 "when (d) lands" brief reads as future tense — see §7.1 |

Total pinned surface across the six files above plus `test_round7_defect_pins.py` and
`test_slice_e_pins.py`: **745 collected tests.**

**The census is TRUE on every row.** It is also incomplete in one respect that changes the
headline: it treats the five slices as five equal units of build, and (b) is not one fifth of the
remaining work — it is 100% of it, because of §5.

---

## 5. THE BOOTSTRAP DEADLOCK — the headline finding, measured four ways

MEASURED in `$CLAUDE_JOB_DIR/tmp/mf`, `HOME` redirected, `/usr/bin/python3.12`.

**Step 1 — nothing creates an initialized home.** §4 refuses to list a home that is not
*initialized*, and Definitions define initialized as *"a directory whose `state/fleet.json` exists
and parses"*. MEASURED: `fleet init` does **not** write one.

```
$ FLEET_HOME=$PWD/A fleet init
fleet init: wrote …/A/state/worker-settings.json
$ find A
A  A/state  A/state/worker-settings.json          # no fleet.json
```

Driven afterwards on a fresh home, **eight verbs, every one rc 0, and `state/fleet.json` still
absent after all eight**: `init`, `status`, `clean --yes` (*"nothing to clean"*), `autoclean
--dry-run`, `archive` (*"archived 0 worker(s)"*), `doctor` (*"[PASS] registry: …/fleet.json does
not exist"*), `home`, `homes`. After the run the home holds exactly one file,
`state/worker-settings.json`. DERIVED (AST): `save_registry` has 20 callers, every one a
roster-mutating path. And the shipped code says so itself — `_multi_fleet_population_is_live`'s
docstring: *"Pre-slice-(b) NOTHING CREATES `state/fleet.json` EXCEPT A SPAWN … A fresh home would
be permanently unbootable. Slice (b)'s `init --home` is what closes that hole."*

**Step 2 — that docstring's mitigation only defers the brick by one home.** The population gate
disarms the terminus on a machine with *no* listed home. Add the first one — the act that turns
multi-fleet on — and the terminus arms for everything. MEASURED, with `A` listed and `B` an
existing, `init`-ed, registry-less directory:

| route | result |
|---|---|
| `FLEET_HOME=B fleet init` | **rc 1** — *"no fleet home resolved, so `init` has nowhere to act… Name a home with `--fleet-home <PATH>` or `FLEET_HOME`."* |
| `fleet --fleet-home B init` | **rc 1** — *"--fleet-home …/B is not initialized (not_initialized)… Nothing was created."* |
| `fleet homes --add B` | **rc 1** — same `not_initialized` refusal |
| `fleet --fleet-home B spawn …` / `FLEET_HOME=B fleet spawn …` | **rc 1**, one refusal each of the two above |

**Note what the first refusal says.** It names `FLEET_HOME` as the remedy, and `FLEET_HOME` was
set to exactly the home it is refusing. This is the R2 class the operator has already ruled on
elsewhere (*a refusal naming a remedy the machine will not accept*), reached here by a different
route. It is not a defect in the guard — the guard is correct and deliberate — it is the shape of
the hole slice (b) fills.

**Consequence for the phone answer.** MEASURED: on a machine with an *empty* homes list the
terminus is disarmed and dispatch proceeds into an uninitialized env home — `FLEET_HOME=A fleet
init` and `fleet status` both ran there at rc 0 and `fleet status` rendered the table, which is
exactly the spec's own DIVERGENCE RECORD row 2. DERIVED, not driven (it would launch a real
`claude` session, which is outside a read-only lane): `cmd_spawn` is one of `save_registry`'s 20
callers, so a spawn into that home is what finally writes `state/fleet.json`. Putting the two
together, the only path to a second home today is: keep the list empty, spawn a real worker into
the new home to force `save_registry`, then `fleet homes --add`. **You must launch a Claude
session in a fleet you have not configured yet, once per home, and you must do it before you list
the first one.** That is what "how far away are we" costs today, and it is why (b) is the whole
remaining distance.

---

## 6. DISTANCE TO DONE — the operator's sentence contains two questions

### 6.1 Flag/env sense — *"reached by `--fleet-home <path>` or `FLEET_HOME`, with `init --home` creating it"*

MEASURED: **the reaching half works today; the creating half is the whole gap.** Driven in the
sandbox with A listed and initialized: `fleet --fleet-home A status` renders A's table;
`fleet home --fleet-home A` and `fleet --fleet-home=A home` print the same path at rc 0 —
`strip_global_fleet_home` makes position and spelling irrelevant; `FLEET_HOME=A fleet home`
resolves; `fleet homes` renders `…/A  ok (0 workers)`. The lookup, the arming rule, the
destructive tier and the terminus are all shipped and all reddened under mutation (§2).

**Distance: slice (b), and nothing else that I could find by measurement.** Its shape is already
ruled and measured, so the lane is not designing anything: gate 3's answer names the idiom
(*flagged tokens in the destructive tuple, the bare verb in NO tuple, tier in
`VERB_EFFECT_RESIDUAL`*), and `docs/lanes/w51-slicee.md` §9.1 is an executable four-item brief for
the pin side. **Add one item to that brief, from §8 of this report: the writer-enumeration pin
will go RED the moment (b) lands, and that is by design.**

### 6.2 Zero-configuration sense — *"a session whose cwd is `/home/altai/proga/X` reaches X's fleet"*

**MEASURED: this does not exist, and I established it from the shipped resolver rather than from
the brief.** `resolve_home` (`bin/fleet.py:4716`) takes `flag`, `sid`, `env`, `default_home`,
`install`, `population` and consults, in order: the flag; `lookup_home_for_sid`; then the collapsed
`FLEET_HOME` module global; then the terminus. It never reads the working directory. Repo-wide,
`bin/fleet.py` contains exactly **two** `getcwd`/`Path.cwd()` sites — `find_index_root` (line
20567) and `_index_root_arg` (line 21184) — and **both belong to the `fleet index` verb**, not to
home resolution. `bin/fleet_statusline.py` and the four hooks contain none. Driven: with cwd
inside a repo directory, no flag, no env, on an armed machine, `fleet home` prints `[fleet]: no
home`.

**What a cwd step would have to do, and what it would collide with. Described, not proposed — this
question is with the operator and unanswered, and a lane's design would read as a recommendation.
I recommend nothing.**

* **Shape.** It would be a walk-up from cwd looking for a per-repo marker, terminating at a
  boundary. The repo already ships exactly that machine, for a different purpose:
  `find_index_root` walks up from cwd for `.fleet-index/` and **stops at the first `.git` entry,
  file or directory**, precisely so a linked worktree does not resolve its parent checkout's
  index. Any cwd step would face the same worktree problem and would need the same stop, or a
  worker in `fleet-w59-slice-e` would resolve `fleet`'s home.
* **Collision 1 — §9 is a graveyard, and this is the corpse.** *"§9. The marker, deleted —
  record"*. v1/v2's marker design was killed by measurement, and `test_terminal_surface.py::
  test_no_shipped_code_references_the_marker` is a **live lint** over five files banning the
  marker path construction by signature, with a stated reason: *"a stale marker could silently
  redirect the CLI — `fleet clean` and `fleet kill` included — at a different fleet's registry."*
  A cwd step is a marker step unless it derives the home from something other than a file in the
  tree, and that lint is what it collides with first.
* **Collision 2 — where in §5's ratified order?** Above the sid lookup, cwd would outrank
  registry membership — the only *affirmative, lock-written* evidence of ownership the design has,
  and the thing that survived five gate rounds. Below the lookup but above `FLEET_HOME`, it would
  silently overrule an env var an operator exported, on a `--bg` body whose env is the daemon
  donor's (the two-media model) — so the cwd would be the body's and the env the donor's, and the
  new step would sometimes be the *more* correct one and sometimes not, with nothing able to tell
  which. Below `FLEET_HOME`, it changes nothing for the manager, which is the caller the operator
  is asking about.
* **Collision 3 — the verb-effect tier is grounded on "nobody named this home".** §5: *"destructive
  via env/legacy requires the flag … Lookup-hit resolutions are exempt — membership is affirmative
  evidence."* A cwd resolution is neither named nor affirmative, so the tier would need a ruling on
  which side it falls, and the `_apply_wrong_home_guard` steps-1-and-2 carve-out would need a
  fourth case.
* **Collision 4 — the four hooks and the statusline.** Slice (c)'s whole point is that a hook
  learns its home **only when the dispatch tells it** (baked argv), because a hook's `__file__`
  fallback derives the home from the install. A hook's cwd is the worker's `--dir`, which is a
  *repo*, not a home. Any cwd step would either not reach the hook plane at all or would make four
  standalone stdlib-only scripts re-implement a walk-up — and `test_install_home_split.py::
  TestTheFourHookHomeResolversDoNotDrift` drives all four against `fleet.py`'s own resolution, so
  they would all have to move together.

---

## 7. RESIDUALS SLICE (e) STILL OWES — small, named, and none of them blocking

Everything in §2 is discharged. These four are what a follow-up (e) lane would pick up.

### 7.1 The conftest redirect does not reach a subprocess — MEASURED, and it is w51's own open question

`docs/lanes/w51-slicee.md` §9.2 item 1 said the statusline is *"a separate process with its own
imports — so `tests/conftest.py`'s redirect does not reach it when it is driven as a subprocess.
**Measure that before assuming either way.**"* MEASURED here, and the assumption was right:

```
# a child launched exactly as the shipped tests launch one: env={**os.environ, "FLEET_HOME": d}
$ python -c "import sys; sys.path.insert(0,'bin'); import fleet; print('LIST=', fleet.homes_list_path())"
as the shipped tests run it: LIST= /home/altai/.claude/fleet-homes.list     # the OPERATOR'S REAL LIST
with HOME redirected:       LIST= /tmp/tmphnrvt7a6/.claude/fleet-homes.list
```

Four shipped test sites drive a real subprocess with `{**os.environ}` and only `FLEET_HOME`
overridden: `test_terminal_surface.py:1372` and `test_install_home_split.py:351` (both
`fleet_statusline.py`), and `test_destructive_guard.py:506` and `:584` (`bin/fleet.py` itself,
running `kill`). All four therefore read the operator's real homes list.

**Severity, honestly: LOW today, and it becomes real exactly when multi-fleet ships.** They are
reads, not writes — the session guard would not fire and should not. On `kz-work` the real list
does not exist, so all four see a single-fleet machine and behave deterministically. **The moment
the operator runs `fleet homes --add`, those four tests start resolving against the real
population** — the `kill` pair would run `lookup_home_for_sid` across the operator's live homes,
and the statusline pair would too. The outcome becomes a function of machine state. It is not a
data-loss hazard; it is the exact shape §2 row 1 records, one level out, and (e) is where it
belongs. **BELIEVED** (not measured, because I could not do it without editing a test): the fix is
a helper that adds `HOME`/`USERPROFILE` to the child env for every subprocess drive.

### 7.2 The quiescent canary is one arm wide, not four

MEASURED under `M4` (§2 row 4): of the four parametrised verbs, only `homes` caught a cross-home
write. The other three never touch home B at all, because `test_driving_home_a_leaves_home_b_byte_
identical` deletes `CLAUDE_CODE_SESSION_ID` and a sid-less lookup returns `no_sid` **without
reading any home**. So the canary's stated property — *"driving a fleet in home A leaves every
OTHER listed home byte-identical"* — is genuinely exercised by one of its four arms; the other
three are asserting that a verb which never opened B did not change B. They are not wrong, and the
`reached` assertion keeps them from being vacuous *about the verb*; they are just narrower than
they read. **A sid-carrying parametrisation would widen all four for the cost of one fixture
argument.** (Its own seed, `test_the_canary_can_see_a_perturbation`, is unaffected — it perturbs B
directly and is toothy.)

### 7.3 The 2026-08-10 `witness` ruling is undischarged in the spec

MEASURED. The ruling: *"the word comes out of Sequencing §3 with a dated note recording that it
defined nothing."* At `3fce992`, `grep -n witness docs/specs/multi-fleet.md` returns three hits,
and **line 744 still reads `(c) hook argv + witness + _render_successor_task argv`**, with no
dated note. Nothing tests it.

**Precision matters here and a careless fix would break something.** The other two hits are a
*different* witness and must stay: §5 step 1's *"refuse without `--yes` + witness line"* is
**shipped and correct** — `apply_resolved_home` builds `"[fleet] WITNESS: --fleet-home names …,
but this session is a member of …"` at `bin/fleet.py:5352`. Only §3's token is vestigial. This is
a spec edit under an operator ruling, so it is named here and not made.

### 7.4 The tautological pin is still in the tree

MEASURED: `tests/test_home_resolution.py::test_the_real_list_is_untouched` is unchanged at
`3fce992` and is still green over 122 planted appends (§3). w51 deliberately left it and
**recommended** the manager fold it into a one-line docstring pointer to the conftest guard rather
than delete it from inside the lane that replaced it. That recommendation has not been actioned.
Cost of leaving it: a reader greps `real_list_is_untouched`, finds a pin with that name, and stops.

---

## 8. §4's HOMES-LIST WRITER ENUMERATION — the brief is WRONG, and the sibling lane needs this today

The brief says §4's writer enumeration is *"unpinned prose … it names three writers and measures
one, saying 'nothing will catch it'"*, and asked me to confirm that today. **It is pinned, and
something will catch it.**

MEASURED. `tests/test_homes_list.py::TestNoImplicitReaders::test_only_the_named_writers_append`
walks `bin/fleet.py`'s AST and asserts, with equality:

```python
assert callers == {"cmd_homes"}, (
    "`append_home_record` is called from {…}. §4 names its writers exhaustively "
    "-- never hooks, never dispatch, never session-implicit. Add the new writer "
    "to this pin deliberately.")
```

Its own docstring already anticipates (b): *"`init --home` is slice (b) and does not exist yet, so
at a1 the only caller of the appender is `cmd_homes`."* Teeth measured by re-implementing the
walk over mutated **copies** of `bin/fleet.py` (no repo file touched — §10):

| mutant shape for (b) | derived callers | pin |
|---|---|---|
| clean tree | `['cmd_homes']` | — |
| `cmd_init` calls `append_home_record(...)` directly | `['cmd_homes','cmd_init']` | **RED** |
| `cmd_init` calls a new `_init_records_the_home()` wrapper | `['_init_records_the_home','cmd_homes']` | **RED** |
| module-qualified `fleet.append_home_record(...)` | `['cmd_homes']` | GREEN — blind |

The third row is not a realistic shape inside a single-file module that does not import itself, so
**the pin has teeth against both plausible shapes of slice (b)**. Two blind spots worth naming
anyway, both cheap to close in the same commit: it walks `bin/fleet.py` only (a writer landing in
`fleet_statusline.py`, which *does* `import fleet`, would be invisible — the hooks are covered
separately by `test_no_hook_script_mentions_the_homes_list`), and it matches `ast.Name` only.

**Message for `w59/inithome`, today:** when `init --home` lands, `test_only_the_named_writers_
append` goes RED and that is the pin doing its job — widen the expected set to `{"cmd_homes",
"cmd_init"}` **in the same commit**, deliberately, and re-run `test_the_population_is_what_the_
docstring_says_it_is` (the no-rewrite lint's `LIST_SYMBOL` is a pattern, so `cmd_init` joins that
population automatically only if it names a `homes_list|homes_population|home_record|homes_view`
symbol; the `len(pop) >= 12` assertion is what makes a silent shrink RED). Both are already in
`docs/lanes/w51-slicee.md` §9.1 — this report adds the measurement that they will actually fire.

---

## 9. §8's LEGACY DEFAULT — the four criteria, what is measurable, and a gate that was never opened

**I do not decide this.** §8, verbatim and unchanged from v6:

> (1) slice 0; (2) dogfood home moves out + listed, completion removes the legacy population
> term; (3) plane-naming lint; (4) arming pin extended to sid-less class. Operator decision.

| # | criterion | measurable today? | state, MEASURED |
|---|---|---|---|
| 1 | slice 0 | **Yes, fully** | **MET.** `INSTALL_ROOT` ships, `tests/test_install_home_split.py` = 41 tests, `test_no_bin_path_is_still_resolved_from_the_home` is the derivation that keeps it met |
| 2 | dogfood home moves out + listed | **Yes, fully** | **NOT MET.** `~/.claude/fleet-homes.list` does not exist on `kz-work`, so the dogfood home is neither moved out nor listed. **Blocked by §5's deadlock**: listing it and then creating a second home is not possible before slice (b) |
| 3 | plane-naming lint | **NO — the criterion is undefined** | grepping all three spellings (`plane-naming`, `plane_naming`, `plane naming`) over `docs/`, `tests/` and `bin/` returns **one hit: §8 itself.** Nothing says what the lint asserts. The nearest shipped thing is `test_install_home_split.py::test_no_bin_path_is_still_resolved_from_the_home`, a one-direction lint (home→bin). **Ruling on §8 requires first saying what this is** — and by the standing rule ratified 2026-08-10 (*a build slice may not derive a normative deliverable from a spec word the spec never defines — it files a gate instead*), a lane may not invent it |
| 4 | arming pin extended to sid-less class | **Yes, but the wording is ambiguous** | On the reading *"the arming pin runs as a sid-less caller"*: **already MET** — `conftest.py::_no_inherited_claude_session` deletes `CLAUDE_CODE_SESSION_ID` for every test, so `TestTheDestructiveTierPin`'s `armed` fixture already drives sid-less, and `test_home_resolution.py::test_a_sidless_caller_is_its_own_state` pins `no_sid` as its own tri-state. On the reading *"a new arm covering sid-less callers specifically"*: not identifiable. **Which reading is intended is the operator's to say** |

**And the finding under the finding.** MEASURED: the v8 ratification promised *"§8's four exit
criteria for the legacy default stay a second, later decision"*. `docs/OPERATOR-GATES.md` `##
Open` today carries **three** gates — G-K1 (keeper/D7), G-K2 (silent failures), G-K4
(`supervisor/briefs/`) — and **none of them is §8**. `docs/operator/gate-docket.md`'s "three open
gates" are the same three. The §8 decision exists only as a sentence inside a *settled* entry.
**It has never been put to the operator.** The 2026-07-30 docket lesson applies verbatim: *"the
queue was never your latency, it was nobody asking."*

---

## 10. INSTRUMENTS — how to re-run every number here

* **Interpreter.** `/usr/bin/python3.12` is what `uv run --no-project --python 3.12` selects on
  this host; `bin/fleet.py` is stdlib-only, so CLI drives call it directly and pytest goes through
  `uv … --with pytest`. No interpreter on `PATH` has pytest importable (root `CLAUDE.md`, and
  re-confirmed: `/usr/bin/python3.12 -m pytest` → *No module named pytest*).
* **The fence.** I edited exactly one repo file: this report. Every mutant was applied to
  `$CLAUDE_JOB_DIR/tmp/mtree`, a `cp -r` of the tracked tree, by
  `$CLAUDE_JOB_DIR/tmp/mutate.py`, which asserts its target path does **not** contain
  `fleet-w59-slice-e`, asserts the patch applied (`out != src`), runs the selection, and restores
  the original bytes in a `finally`. The AST-only probes ran in
  `$CLAUDE_JOB_DIR/tmp/w59_ast_probe.py` over strings, never over files on disk.
* **The two-home sandbox.** `$CLAUDE_JOB_DIR/tmp/mf` with `HOME` redirected into it, so
  `homes_list_path()` resolves inside the sandbox. `~/.claude/fleet-homes.list` did not exist
  before this lane and does not exist after it.
* **The thirteen mutants**, by name, with the selection each was run against and the measured
  result: `M1` (conftest drops the redirect → 4F/13P/7E), `M2` (file-scoped sandbox loses `autouse`
  → 71P, correctly), `M3` (`homes_list_drift` blind → 4F), `M4` (a cross-home READ writes → 1F,
  `homes` arm only), `M7` (`cmd_homes` rewrites the list → 1F), `C3b` (`read_homes_list` appends to
  the real list → the vacuous pin PASSES, the conftest guard ERRORS, 122 records), `C5a` (fold →
  first-record-wins → 16F), `C5b` (`spawned_by` grants membership → 1F), `C6` (`O_APPEND` dropped →
  1F, 20/100 records lost), `C8` (state-word mapping dropped → 1F), `C9` (wrong-home guard stops
  refusing → 10F), `C10` (`_multi_fleet_population_is_live` stops arming → 1F), `C10b`
  (`multi_fleet_arming` stops arming on indeterminacy → 2F).
* **Baseline.** `4880` collected, `6 failed / 4857 passed / 16 skipped / 1 xfailed` in 341.54s on
  3.12. I did not run 3.10; root `CLAUDE.md` records the counts identical on both and nothing in
  this lane changes code, so the floor claim is inherited rather than re-measured — **stated as
  BELIEVED**, not measured, and it is the one number in this report I did not produce myself.

---

## 11. WHERE THIS BRIEF WAS WRONG

1. **"Slice (e) pins — UNKNOWN, and this is your centre of gravity."** Wrong, and in the good
   direction. Slice (e) was built at wave 51 (`tests/test_slice_e_pins.py`, `docs/lanes/w51-
   slicee.md`). It is not unknown; it is largely discharged, and §2 re-measures every row of it
   rather than inheriting the claim. The brief's *instruction* was still the right one — the
   census asked to be checked and checking it is what produced §2's control and §7's residuals.
2. **"§4's homes-list writer enumeration is unpinned prose … 'nothing will catch it'."** Wrong.
   `test_only_the_named_writers_append` pins it by AST with an equality assertion, and it has teeth
   against both plausible shapes of slice (b) (§8). The sibling lane will go RED and should.
3. **"The interface's BUILT list … only needs checking."** Right on every row (§4) — but the list
   is *arithmetically* misleading in a way that matters for the phone answer. Four of five slices
   built does not mean 80% done. §5 shows the feature is unreachable end-to-end until (b) lands,
   so (b) is the entire remaining distance in the flag/env sense.
4. **"A '0 owed' result is suspicious."** Correct, and it happened: 10 of 10 pin categories can
   fail. §3 is the control the brief demanded — the same harness returns GREEN for
   `test_the_real_list_is_untouched` while 122 records are appended to the file it is named after,
   so the zero is a measurement and not an instrument that has never returned anything else. §3's
   Control B additionally records my *own* harness returning a false green once, and how it was
   caught.
5. **What the brief did not ask for and is the most useful thing here:** the bootstrap deadlock
   (§5). It is not in the census, not in the spec's open questions, and only half-visible in
   `_multi_fleet_population_is_live`'s docstring — which describes the brick the population gate
   avoids without noting that the gate only defers it to the second home.
