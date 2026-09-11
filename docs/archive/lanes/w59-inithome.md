# Lane `w59-inithome` — multi-fleet slice (b): `fleet init --home`

**Branch** `w59/inithome`, worktree `/home/altai/proga/fleet-w59-inithome`, based at `3fce992`.
**Fence held:** commits on this branch only; no push, no merge, no other ref moved.

Every line below is tagged **MEASURED** (I ran it, on this host, this session) or **BELIEVED**
(reasoned from the tree, not driven). Where the two disagree I say so.

---

## 1. What shipped

`fleet init --home <PATH>` — the verb §Definitions names as *"the verb whose contract is
creation"* and §4 names as the first of its three writers. It:

1. validates `<PATH>`: non-empty, resolved, §4-absolute, no `..` segment, and **an existing
   directory** (`_home_to_create`);
2. creates `<PATH>/state/`, writes `state/fleet.json` as `{"workers": {}}` **only if absent**, and
   renders `state/worker-settings.json` from the install-plane template with `{{FLEET_HOME}}` =
   `<PATH>` (`_write_new_home_state`);
3. re-reads `home_is_initialized(<PATH>)` off disk, and only then
4. appends `<PATH>` to `~/.claude/fleet-homes.list` unless already a member
   (`_record_home_on_this_machine`).

**MEASURED** — the trap the brief describes is closed end to end. Before: a fresh directory could
not be made into a home by any verb; `--fleet-home <fresh dir>` refused `not_initialized` and bare
`fleet init` did not create `state/fleet.json`. After, on this host:

```
$ fleet init --home $D/newhome
fleet init: initialized /…/drive/newhome
  registry:    /…/drive/newhome/state/fleet.json
  settings:    /…/drive/newhome/state/worker-settings.json
  python:      /usr/bin/python3.12
  homes list:  /…/fakehome/.claude/fleet-homes.list (appended: /…/drive/newhome)
  note:        that append is permanent -- the list is append-only and only `fleet homes --retire` folds it out.
rc=0
$ fleet --fleet-home $D/newhome home
/…/drive/newhome
rc=0
```

**MEASURED** — idempotent on disk, not merely in effect: a second `init --home` on the same path
prints `already initialized` / `already listed`, appends no second record, and leaves a registry
containing a live worker **byte-identical** (pinned by
`test_re_running_appends_nothing_and_keeps_the_registry`).

## 2. The guard shape — the ruling, and the one adaptation

The 2026-08-10 ruling was followed literally where it is literal and argued where it is not.

| ruling | shipped | status |
|---|---|---|
| flagged token in the destructive tuple | `"init --home"` in `VERB_EFFECT_DESTRUCTIVE` | **MEASURED** |
| the bare verb in NO tuple | `init` removed from `VERB_EFFECT_ORDINARY`; in no tuple | **MEASURED** |
| tier carried in `VERB_EFFECT_RESIDUAL` | `VERB_EFFECT_RESIDUAL["init"] = "ordinary"` | **MEASURED** |
| three files move together | four did — see §3 | **MEASURED** |

**MEASURED — the `w47-homes` idiom transferred WITHOUT adaptation to the tier machinery, and the
brief's "most likely" failure did not happen.** The brief expected trouble because `homes`'
subcommands are `store_true` flags while `--home` takes a VALUE. It does not matter:
`_verb_effect_index` derives the dest mechanically (`--home` → `home`) and
`verb_effect_tier`'s presence predicate is `getattr(args, dest, None) not in (None, False)`,
which is already value-shaped — it was written that way for `sup-decision --answer ''` (ga3 B1).
Driven through the real parser: `fleet init` → `ordinary`, `fleet init --home /srv/x` →
`destructive`, `fleet init --home ""` → `destructive`. `--home` overrides no `dest=`, so it needs
no `VERB_EFFECT_RESIDUAL_FLAGS` entry, exactly like `--add`/`--retire`.

**MEASURED — the fail-safe direction, in both directions.** The brief asked for a test that
deletes the classification and asserts destructive. `TestTheRulingsFailSafeDirection` does that
**and** builds the rejected naive two-row form and shows it failing OPEN, because a pin that only
exercises the shipped shape cannot show why the other was rejected — the two resolve identically
on the intact table.

* Shipped shape, `"init --home"` dropped from the destructive tuple → `init` is named by no tuple
  → `verb_effect_tier` returns `destructive` from its `if not rows` arm, for the flagged **and**
  the bare form. The residual dict is never consulted; it only answers when rows exist and none
  matched.
* Naive shape (bare `init` in ORDINARY + flagged token in DESTRUCTIVE), same token dropped →
  `fleet init --home` classifies **`ordinary`**. That is the hole.

### The adaptation that WAS needed, and it is not in the tier

**MEASURED, and this is the finding I would put first for a gate.** The ruling settles the
*classification*. It does not settle what happens when a DESTRUCTIVE verb meets §5's resolution
order — and for this verb, the shipped guard would have **deadlocked it on its own remedy**. Two
distinct states, both reachable, both with `--fleet-home` as the printed remedy:

* **the terminus (§5 step 5).** `resolve_home` reaches step 5 whenever the default home is not
  initialized — i.e. the fresh box `init --home` exists to populate. `init` is not in
  `TERMINUS_VIEW_VERBS`, so it takes `_terminus_refusal`.
* **the wrong-home guard.** On an armed machine (≥2 counted homes) resolved at step 3/4, a
  DESTRUCTIVE verb takes `_refuse_wrong_home_destructive`.

And `--fleet-home` **structurally cannot** be that remedy: §5 step 1's `validate_named_home`
demands an already-INITIALIZED home, which is precisely what `--home` is for creating. This is the
same defect `TERMINUS_EXEMPT_VERBS` was minted for one verb earlier — that tuple's own comment
records `fleet homes --add` printing `[fleet]: no home` and exiting 0 without appending, and calls
it *"a deadlock with a friendly message"*.

So this lane adds `TERMINUS_EXEMPT_FLAGS = {"init": ("home",)}` and `machine_exempting_flags()`.
**`init` deliberately does NOT join `TERMINUS_EXEMPT_VERBS`** — bare `fleet init` writes into the
home §5 resolved for it and must keep taking the order (pinned:
`test_bare_init_still_takes_the_order_at_the_terminus`, which is the half the exemption must not
eat).

**MEASURED, with a control arm** — at the terminus, on a machine with two listed homes and an
uninitialized install root:

```
$ fleet clean                  → rc=1  "no fleet home resolved, so `clean` has nowhere to act…"
$ fleet init --home $D/home3   → rc=0  home3 initialized? YES
```

The control matters: `init --home` not being refused is also what a *broken* guard looks like.
`clean` refusing on the identical fixture is what makes the first line evidence.

**The exemption does not soften the tier**, and the two layers are independent by construction —
`tests/test_verb_effect_guard.py::test_the_guard_never_tiers_a_terminus_exempt_verb` already
states that pairing for `homes`. The exemption stops the RESOLVER refusing; the destructive tier
stops a read-only `/fleet:*` grant reaching the append. `fleet homes --add` already ships in
exactly this combination, so the precedent is exact rather than analogous.
`TestTheExemptionAndTheTierAgree` pins that the exemption and the destructive tier fire on the
**same dest with the same presence predicate** — if they disagreed there would be an invocation
the table calls destructive that still takes the order (deadlock) or one it calls ordinary that
skips it (hole).

**MEASURED — `--fleet-home` with `--home` is REFUSED, not ignored.** One invocation names one
home. Silently applying a `--fleet-home` that the verb then never uses is the defect
`apply_resolved_home` already names one screen up (*"silently ignoring a `--fleet-home` an
operator typed is its own defect"*).

## 3. The landing obligation — FOUR files, not three

The brief named three. **MEASURED: there is a fourth**, and it is the one a gate should check I
did not route around.

| # | file | what moved |
|---|---|---|
| 1 | `bin/fleet.py` | `VERB_EFFECT_DESTRUCTIVE` += `"init --home"`; `init` out of `VERB_EFFECT_ORDINARY`; `VERB_EFFECT_RESIDUAL["init"]` |
| 2 | `tests/test_round7_defect_pins.py` | `RATIFIED_DESTRUCTIVE` / `RATIFIED_ORDINARY`, same edit |
| 3 | `tests/test_terminal_surface.py` | `DESTRUCTIVE_VERBS` += `"init --home"` (flagged, never bare `init`) |
| **4** | `tests/test_homes_list.py` | `test_only_the_named_writers_append` asserted `callers == {"cmd_homes"}` — an **equality**, so it goes RED the moment a second writer appears. Now `{"cmd_homes", "_record_home_on_this_machine"}`. |
| **5** | **every self-citation in `bin/fleet.py`** | see below — 33 of 44 rotted |
| + | `docs/specs/multi-fleet.md` §5 | the destructive and ordinary ROWS — `TestRatifiedTableIsTranscribedFaithfully` re-reads both from the spec, so the tuples cannot move without them |

### Obligation 5, which no brief has ever named and which every future lane will hit

**MEASURED.** `bin/fleet.py` explains itself with bare line-number citations
(`` `_sweep_husks` (:8477) ``), and `tests/test_self_citations.py` +
`tests/test_retired_sid_citations.py` verify that each one still lands on what it claims.
**Any insertion into `bin/fleet.py` rots every citation below it.** Mine shifted lines by up to
+368 and broke **33 of 44** citations — **14 RED tests across two files**, none of them about
`init --home`, all of them real.

Re-pointed with `tools/repoint_self_citations.py`, added by this lane. It takes the citation
VALUES **from the base commit** (where they are known correct), maps each through a difflib
base→working line map, and writes them back **positionally** — so it is idempotent and cannot
double-apply. **That design is not aesthetic:** my first attempt mapped the working file's own
current numbers, which is fine once and corrupts on the second run. I did run it twice. The tool
exists because I made that mistake and it is the kind that leaves a green suite pointing at wrong
lines. It refuses outright if the citation COUNT moved, because it maps positionally and cannot
know which citation was added.

### And one census that fired on prose

**MEASURED.** `tests/test_rendered_command_quoting.py` censused `_init_named_home` as a COMMAND
RENDER. Its rule (ii) is a SHAPE — *"two path-valued expressions separated by nothing but
whitespace and quote characters"*, the `<interpreter> <script>` argv shape — and
`print(f"fleet init: {state} {Path(target)…as_posix()}")` is exactly that shape. The over-reach is
genuine (`state` is a string; `_path_valued` follows names transitively, and `state` derives from
`created` which derives from `target`, which is `-> Path`).

**I did not add a `print` to `EXPECTED_RENDERS`.** Declaring a report to be a shell command would
make the census's own population a lie, which is this repo's named recurring defect. I made the
report stop looking like an argv (`fleet init: initialized home <path>` — the word `home` is
load-bearing and says so in a comment) and dropped a redundant `(kept)` marker. **Reported as a
finding on the census, not on my code:** rule (ii) will fire on any human-readable report that
prints two derived values side by side, and the next lane to hit it will be tempted to take the
easy exit.

**MEASURED — the spec-row edit has a trap that bit the `homes` landing and would have bitten
mine.** `_spec_row_tokens` resolves *backticked* tokens to verbs, so a backticked `init` left in
the ordinary row while `` `init --home` `` sits in the destructive row is a **two-row partition
breach** (`test_no_verb_IS_NAMED_BY_TWO_spec_rows`). The `homes` entry solved this by leaving the
verb name unbackticked with a note saying why; I copied that shape. Verified by re-deriving all
three rows' token sets and diffing them against the three tuples: **exact match, all three rows.**

## 4. The unpinned prose I invalidated — re-measured

§4's homes-list writer enumeration said, in its own text, that when `init --home` was built *"the
function count moves and this enumeration must be re-measured; it is unpinned prose, so nothing
will catch it."* Nothing did. **MEASURED by AST over `bin/fleet.py` at this branch's tip:**

| | before (`bd93691`, as the spec recorded) | after (this tree) |
|---|---|---|
| reader FUNCTIONS | 1 (`read_homes_list`) | 1 — unchanged |
| reader call sites | 3 | **4** (`homes_population`, `resolution_population`, `cmd_homes`, `_record_home_on_this_machine`) |
| writer FUNCTIONS | 1 (`append_home_record`) | 1 — **unchanged** |
| writer call sites | 2, both in `cmd_homes` | **3 across 2 scopes** (`cmd_homes` ×2, `_record_home_on_this_machine` ×1) |
| scopes naming `homes_list_path` | 2 | **3** (+ `_init_named_home`, which names it only to print where the append landed) |
| no-rewrite lint population | 12 | **14**, **0 offenders** |

The headline is the row that did **not** move: slice (b) added a writing VERB without adding a
writing FUNCTION. §4's writer list is now complete at three built verbs. The spec paragraph is
rewritten with this measurement and dated.

**MEASURED — the shipped lint forced the code's shape, and the brief was right to say "check
rather than assume".** `tests/test_homes_list.py`'s no-rewrite lint bans
`write_text`/`open`/`unlink`/`rename`/`truncate`/`replace` in any scope that **names** a
homes-list symbol — and its population is derived by regex over names, not enumerated. This verb
must both write files inside the new home and append one record. **One function doing both is an
immediate RED, and correctly so:** the lint cannot tell which file a `write_text` is aimed at. So
the append lives alone in `_record_home_on_this_machine` (in the population, clean), the file
writes live in `_write_new_home_state` (names no list symbol at all), and `_init_named_home`
composes them and writes nothing itself. That split is the reason for three functions, and it is
documented at the code rather than left for the next reader to rediscover from a lint failure.

## 5. The fence I was told not to cross

**No cwd-based home resolution was added.** No marker file, no walk-up from cwd, no git root.
§5's five steps are untouched. `TestNoCwdResolutionWasAdded` asserts the absence three ways
(the resolver's source names no `cwd`/`getcwd`/`parents`/`git`; the four new scopes reach no
`.cwd`/`.getcwd`/`.parents`/`.glob`/`.rglob` attribute and name no marker string; the deleted
`~/.claude/fleet-home` marker is not back).

**BELIEVED, and offered as the useful half of the fence:** nothing in building this slice made me
think the cwd step is needed. `init --home` plus `--fleet-home` covers "independent per repo/dir"
for any caller that can name its home, and every fleet caller can — the flag, `FLEET_HOME`, and
the sid lookup are three different ways to say it. **What I would put to the operator instead** is
narrower and does not touch §5: the ergonomics gap is not resolution, it is that a worker session
launched inside repo X has no way to *discover* which home it belongs to except by already being
in that home's registry. That is a §5 step-2 (sid lookup) property and it already works. A cwd
walk-up would add a fourth spelling of "which home" whose answer can disagree with the other
three, and §5's whole design is one order for every caller.

**One caveat on the strength of that fence, stated rather than left for a gate to find:**
`test_the_new_scopes_never_read_the_process_directory_to_find_a_home` passes **vacuously** on the
baseline tree, because the scopes it names do not exist there. It is an absence pin over a named
population; it catches a future edit to these four functions and nothing else. The resolver-source
pin beside it is the one with teeth today.

## 6. The two brief questions I was told to check

**MEASURED — `cmd_init`'s supervisor gate and `--home`.** `_supervisor_gate("init", …)` is the
first statement in `cmd_init` and the `--home` branch sits **below** it, so the gate is unchanged
by this slice and applies to both forms. It arms on the AMBIENT home's supervisor claim (the one
§5 resolved), **not** on the home being created — which has no supervisor by construction. A
sid-bearing caller against a live local supervisor with a fresh heartbeat is still refused, which
is why the operator recipe runs `init` from a shell with no `CLAUDE_CODE_SESSION_ID`. I did not
change this and do not think it should change: the gate is a speed-bump against a divergent second
body, and a second body creating homes on the machine is exactly the shape it is aimed at.

**MEASURED — where `save_registry`'s `mkdir` is, and whether an above-it refusal exists.** The
brief asserted the refusal *"must sit above `save_registry`"* on the spec's word. `save_registry`
does `d = state_dir(); d.mkdir(parents=True, exist_ok=True)` as its **first two lines**, so yes,
the write layer mkdirs unconditionally. And yes, an above-it refusal already ships — but it is not
one refusal, it is the §5 terminus plus `validate_named_home`, both of which run in
`apply_resolved_home` **before any `cmd_*` is entered**. `save_registry` itself is never reached
for an unresolved home. This slice does not use `save_registry` at all: it writes
`registry_path_at(target)` directly through the same `tempfile` + `_replace_with_retry` idiom,
because `save_registry` is bound to the module-global `state_dir()` and this verb writes into a
home the process does not live in.

**MEASURED — `init` had no pre-existing home-resolution behaviour to conflict with.** `cmd_init`
read `FLEET_HOME` and `INSTALL_ROOT` and nothing else; no `args.home` dest existed anywhere in
`bin/fleet.py`; `--fleet-home` is stripped from argv before argparse runs
(`strip_global_fleet_home`), so the two flags cannot collide by dest or by abbreviation — driven,
not reasoned.

## 7. Refusals — every one leaves the machine as it found it

**MEASURED** on the live drive; the homes list was sha256'd before and after the whole block and
is unchanged, and no `~/.claude/settings.json` was written.

| invocation | rc | why |
|---|---|---|
| `init --home ""` | 1 | empty value; ga1 N1's shape one verb along. Still classified **destructive** (presence, not truth). |
| `init --home /nope/nowhere/deep` | 1 | not a directory; nothing created, not even the parent. Advice: `mkdir -p …`. |
| `init --home <a file>` | 1 | not a directory — **different advice**, because `mkdir -p` over an existing file cannot work. Found on the drive, not by reasoning; split afterwards. |
| `--fleet-home Y init --home X` | 1 | one invocation names one home |
| `init --home X --statusline` | 1 | see §8 |
| `init --home <corrupt registry>` | 1 | never overwritten; names `doctor` as the remedy |
| `init --home X` with an unreadable list | 1 | the home IS created; only the append refuses, and the message says so and names `fleet homes --add` as the finish |

The last row is the ordering contract: **the home is made initialized first and listed second**,
because the append is the irreversible half. A failure before it leaves a usable home and a clean
machine list; the reverse order would leave a permanent record of a home §4's reader drops.

## 8. What I did NOT build — stopping boundaries, stated as the brief asked

1. **`--statusline` does not compose with `--home`; it refuses.** The statusline is ONE
   machine-global setting, while `--home` creates one home among many — and `--chain` captures the
   incumbent into `state/` of the home §5 **resolved**, not the one just named, so the pair would
   write two different homes from one invocation. Refusing is the fail-safe reading. **This is a
   narrowing an operator can overturn**; the alternative (chain into the named home) is a
   behaviour question, not a bug.
2. **`init --home` requires the directory to already exist.** §Definitions says creation verbs
   create; I read what it asks this verb to create as the `state/fleet.json` that makes a directory
   a HOME, not the directory. `cmd_homes` states the ground: *"a typo'd path refuses, and leaves no
   directory behind to make the typo look right the second time."* A `--create-dir` flag is one
   `elif` away if the operator wants the other behaviour. **Recorded as a boundary, not a ruling.**
3. **The identity recorded is the RESOLVED path.** `_home_to_create` resolves before applying §4's
   grammar, for ga1 N5's measured reason (an unresolved relative argument reads the process CWD —
   and this one gets *appended to an append-only machine-global list*, where a CWD-dependent record
   is permanent). **This is a real divergence from `homes --add`**, which refuses a relative path
   outright and deliberately never rewrites the operator's spelling (`home_identity`'s docstring
   argues for that). Both are defensible; they are not the same, and a home added by one verb and
   retired by hand through the other could disagree if a symlink is in the path. **Flagged rather
   than resolved** — it is a spec-shaped question about §4's grammar, not a builder's call.
4. **No `commands/init.md` slash command.** None exists today; the `DESTRUCTIVE_VERBS` entry is
   PROSPECTIVE and is what keeps the grant shut when one lands. **MEASURED:** no shipped
   `commands/*.md` grants `fleet init` at all.

## 9. WHERE THIS BRIEF WAS WRONG

1. **"The `w47-homes` idiom does not transfer cleanly, because `--home` takes a VALUE" — WRONG,
   and it pointed at the wrong risk.** The value/flag distinction costs nothing:
   `verb_effect_tier`'s `not in (None, False)` predicate was already built for a value-shaped flag
   (`sup-decision --answer ''`, ga3 B1). The idiom transferred verbatim. **The real adaptation is
   somewhere the brief did not look** — §5's resolution ORDER, where a destructive `init --home`
   deadlocks on a remedy it structurally cannot use (§2 above). A lane that took the brief's
   framing at face value would have shipped the tier, passed every pin the brief named, and left
   the verb unusable on exactly the multi-home machine it exists for.
2. **"Three files move together or the landing is RED" — UNDERCOUNTED BY ONE.**
   `tests/test_homes_list.py::test_only_the_named_writers_append` asserts an **equality** over the
   AST-derived caller set of `append_home_record`, so the second writer reddens it by
   construction. It is the pin that most directly encodes §4's *"Writers: …"* sentence, and it is
   not in the brief's list of three. (It went RED as designed; I moved it rather than widened it,
   which is the difference the pin's own docstring now records.)
3. **"Override the homes-list path itself to a temp file for every test and drive — if no such
   seam exists, that is a finding." — TWO seams exist, and the brief's framing hides the second.**
   For TESTS the seam is conftest's autouse `_never_touch_the_real_home`, which has monkeypatched
   `homes_list_path` by name since multi-fleet slice (e), backed by a session-scoped fixture that
   hashes the real list around the whole run. For a LIVE DRIVE there is no monkeypatch — and the
   brief's own safety stanza does not name what to use instead. **MEASURED: `HOME=<temp dir>` in
   the child environment is the seam**, because `homes_list_path`, `user_settings_path` and both
   daemon paths all resolve from `Path.home()`, which reads `$HOME` on POSIX. One env var moves the
   whole `~/.claude` surface. I used it for every drive here and have added it to
   `docs/lanes/BRIEF-TEMPLATE.md`, since every future lane touching a list-writing verb needs it.
4. **"`fleet home` prints `as_posix()`, compare NORMALISED" — true but not the thing that
   mattered.** The gate that actually bound was that `INSTALL_ROOT` is not overridable by env at
   all, so a drive of MY code had to run from a throwaway copy of the tree; pointing `FLEET_HOME`
   at a temp dir is not sufficient on its own.
5. **"I may be wrong that this slice is small."** It was roughly right: one verb, three helpers,
   one exemption, four pin files, two spec sections. What made it larger than the diff suggests is
   the co-moving surface, and the brief predicted that correctly.
6. **A brief-adjacent correction, recorded because it will mislead the next lane.** The brief's
   baseline is *"4880 collected … six failures"*. Both numbers are right, but my first attempt to
   confirm them reported **11 failures and 1 error** — because I ran the suite in the worktree
   **while editing `bin/fleet.py`**. Five of the extras are `inspect.getsource`-shaped
   (`test_sup_tombstone*`, `test_views_doctrine`): editing a module mid-run makes `getsource`
   return the wrong function at cached line offsets. **Do not run this suite in a tree you are
   editing.** Clean baseline taken from a separate `git clone` at `3fce992`.

## 10. Findings not in scope, reported rather than fixed

1. **Running this suite leaves two stray directories in the repo ROOT** — `--bogus/` and one whose
   name contains a literal newline (`line1\nline2`) — the POSIX residue of the four
   drive-qualified-path escape failures the brief calls host assumptions. **They are invisible to
   `git status`** because each contains only `state/`, which is gitignored, so they accumulate
   silently. **MEASURED: present in the pristine `3fce992` clone too**, so this is not mine. Worth
   a `skipif`-or-fix decision, since "the six failures are host assumptions" is currently also
   "the six failures write into the repo".
2. **`homes --add` and `init --home` normalise paths differently** (§8.3). Flagged for the
   operator/spec, not fixed here.

## 11. Suite

Command, on this host: `uv run --no-project --python 3.1x --with pytest python -m pytest -q`.

* **Clean baseline @ `3fce992`** (separate clone, nothing being edited): `6 failed, 4857 passed,
  16 skipped, 1 xfailed` = **4880 collected**, python 3.12. The six are the brief's host
  assumptions exactly.
* **RED** — the final `tests/test_init_home.py` on the pristine tree, nothing else changed:
  **`30 failed, 9 passed`, byte-identical on 3.10 and 3.12.** The nine passers are the deliberate
  absence-pins and control arms. **My written prediction said ~24 failed / ~15 passed — wrong on
  the split**; the passers were fewer than I guessed.
* **GREEN** — this branch, **both floors, identical**:

| | collected | failed | passed | skipped | xfailed |
|---|---|---|---|---|---|
| baseline `3fce992`, 3.12 | 4880 | 6 | 4857 | 16 | 1 |
| baseline `3fce992`, 3.10 | 4880 | 6 | 4857 | 16 | 1 |
| `w59/inithome`, 3.12 | **4919** | **6** | 4896 | 16 | 1 |
| `w59/inithome`, 3.10 | **4919** | **6** | 4896 | 16 | 1 |

`4880 + 39 = 4919`, and the six failures are the SAME six on all four runs — the brief's host
assumptions, byte-for-byte the same test ids. **This matches the floor I predicted in writing
before running.** The prediction's only miss was the RED split (I said ~24/~15; it was 30/9).

## 12. Every `fleet` command I ran, and which home it touched

`~/.claude/fleet-homes.list` was **ABSENT** when this lane started (`ls` → No such file or
directory; recorded before anything else ran) and is **ABSENT now**. Absent is a state, not a
gap — it was preserved, not recreated. `~/.claude/settings.json` sha256
`29eaa82a0dfe191db38934ab7db7267b4b4f2f235f741c465ec42be1b40ee9f5`, unchanged.

**Every invocation** ran through one wrapper with three fences, and the wrapper hard-aborts
(`exit 99`) if the real list ever appears, checked BEFORE and AFTER each command:

```
env -u CLAUDE_CODE_SESSION_ID \
    HOME=$D/fakehome \
    FLEET_HOME=$D/install \
    python3 $D/install/bin/fleet.py …
```

* `HOME=$D/fakehome` — moves `homes_list_path()`, `user_settings_path()` and both daemon paths
  into the sandbox. **This is the seam, and the brief did not name it** (§9.3).
* `FLEET_HOME=$D/install` + a throwaway `tar`-copy of the tree — `INSTALL_ROOT` is
  `Path(__file__).resolve().parent.parent` and is **not overridable by env**, so a step-4
  install-root fallback can only be fenced by running a copy.
* `env -u CLAUDE_CODE_SESSION_ID` — measured wave 48: with a sid present, `FLEET_HOME` is IGNORED
  because §5 step 2's lookup outranks step 3.

**Gate, run first:** `fleet home` printed `/…/tmp/drive/install`, the throwaway. Nothing else ran
until it did.

| command | home it touched |
|---|---|
| `fleet home` (gate) | throwaway install (read only) |
| `fleet init --home $D/newhome` ×2 | `$D/newhome` + `$D/fakehome/.claude/fleet-homes.list` |
| `fleet init --home $D/home2`, `…/home3` | those dirs + the fake list |
| `fleet homes` ×3 | fake list (read only) |
| `fleet --fleet-home $D/newhome home` | `$D/newhome` (read only) |
| `fleet clean` (control arm, refused rc=1) | none — refused at the terminus before dispatch |
| 6 refusal drives (`--home ''`, missing dir, a file, `--fleet-home`+`--home`, `--statusline`, corrupt registry) | none — every one refused before any write; fake list sha256 identical across the whole block |

**Never run:** `fleet init` or `fleet init --statusline` against the live home
`/home/altai/proga/fleet`; `fleet homes --add`/`--retire` against the real list; any write to
`~/.claude/settings.json`; any spawn, kill, clean, or `doctor --repair` against a real home.

The pytest suite reaches the list too — through conftest's autouse `homes_list_path` redirect,
with a session-scoped fixture that hashes the real file around the whole run and fails if it
moved. It did not, on any of the six full-suite runs.
