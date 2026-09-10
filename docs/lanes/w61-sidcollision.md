# w61-sidcollision — three real historical sids, and what a HIT actually does

**Lane:** build (tests). Branch `w61/sidcollision`, from `036b21f`. Commits `475f04b`, `80959f6`.
**Every line is marked MEASURED or BELIEVED.** MEASURED = I ran it on this host in this lane and
read the output. BELIEVED = I reasoned to it and could not drive it.

---

## 0. Verdict, up front

| the brief said | verdict |
|---|---|
| "on a homes-lookup HIT a `fleet` verb is RETARGETED and `fleet kill --yes` then WRITES `dead` into a bystander home's registry" | **CONFIRMED, with one correction that matters** (MEASURED, §2). The retarget is unconditional on a hit. The **write is not**: it needs the bystander to hold a worker of the same NAME, and — for the un-`--yes`'d drives the suite actually runs — that worker to be owned by the colliding sid. One coincidence gets you a retarget and red tests; **three** get you the write. §2.2. |
| "a single archived worker carrying one of these turns every miss into a hit, and the hit retargets a destructive write" | **the first half CONFIRMED** (MEASURED: `retired_sids` alone is enough — `_record_sids` is the union). The second half over-states by two coincidences, see above. |
| the three sids occur **0 times** in the live registry today | **CONFIRMED** (MEASURED, §1). |
| "the live registry carries 20 worker records and 20 total record sids (no `retired_sids` populated at all)" | **drifted, harmlessly: 22 and 22** at the time I measured (MEASURED). Sibling lanes spawned in between. `retired_sids` still empty everywhere. |
| `INSTALL_ROOT` is the still-armed term, unoverridable by env | **CONFIRMED** (MEASURED, §2.1) — and it is what my end-to-end drive goes through. |
| "**Part 1 is prove it, not fix it** … if it does not reproduce, say so and stop" | **it reproduces.** Part 2 landed. |
| three sids, in one file | **there are FOUR sites in TWO files.** `tests/test_subprocess_home_seam.py:56` carried `20fee653..` as well — and unlike `test_destructive_guard.py:157` that one is handed to a **child**. §5.1. |
| "the six host-assumption failures WRITE INTO THE REPO ROOT" | **WRONG, and the recommendation it framed would have missed** (MEASURED, §6). `--bogus/` and the newline-named directory are created by tests that **PASS**. `skipif` on the six would have stopped none of it. |

**THE SEAM REMAINS OPEN.** w61 removed the *collision*, not the mechanism. `INSTALL_ROOT` is still
`__file__`-derived and still unoverridable; every subprocess drive in this suite still reads the
install-root home's registry on every invocation; a sid that home carries still retargets a
destructive verb. What changed is that the suite no longer supplies a sid this project could have
issued. §7 says what is left.

---

## 1. Safety ledger (MEASURED)

The one RATIFIED DESTRUCTIVE artifact and the live home:

| when | check | result |
|---|---|---|
| T0 | `ls -la ~/.claude/fleet-homes.list` | `No such file or directory`, exit 2 |
| end of lane | same | unchanged — still absent |
| T0 | `sha256sum /home/altai/proga/fleet/state/fleet.json` | `b8f6cbd0b9d39a940a5f6800e417e6bc84d35768832fc62643169388635f4579` |
| end of lane | same | **byte-identical, same sha256** |

`mtime` on the live registry moved (09:27:18 → 09:32:57) while the content did not. Not mine — the
live fleet rewrites its own registry and other lanes are running. **The claim I am making is content
equality, which is the one that matters and the one I measured.** I am not claiming to have proved
a negative about every process on this box.

**Never run at any point:** `fleet homes --add`, `fleet homes --retire`, `fleet init`,
`fleet init --home`, or any write under the real `~/.claude`.

### 1.1 Every `fleet` invocation, and WHY it was contained

I never invoked the `fleet` CLI from a shell. Every invocation was a subprocess of a driver or of
pytest. Three populations, and each one is contained by a **different** argument:

| # | invocation | `INSTALL_ROOT` of the child | `HOME` of the child | `FLEET_HOME` | population it could resolve | home it actually touched |
|---|---|---|---|---|---|---|
| A | `python <lab>/install/bin/fleet.py kill victim` ×4, `clean --yes` ×1, `home` ×1 | `<lab>/install` (a COPY of `bin/`) | `<lab>/fakehome` | `<lab>/sandbox` | `[<lab>/install]` | `<lab>/install` or `<lab>/sandbox` |
| B | the shipped `TestAWorkerCallerIsNotExempt` drives, run 3× against a planted worktree home | `<worktree>` | `child_env` tmp | pytest `tmp_path` | `[<worktree>]` | `<worktree>` (planted, then deleted) |
| C | every drive inside the four floor runs | each `git clone` root | per `child_env` / structurally exempt | per test | `[<clone>]` | tmp fixtures |

**Why that is containment and not an assertion.** §5 step 2's search space is
`resolution_population()` = `read_homes_list()["members"]` ∪ `home_identity(INSTALL_ROOT)`, and
nothing else. `read_homes_list()` resolves through `Path.home()`, redirected into the sandbox in A
and by `conftest.child_env` in B/C — and the operator's real list **does not exist anyway**
(measured, above), so `members` is empty in every case. `INSTALL_ROOT` is
`Path(__file__).resolve().parent.parent`, i.e. wherever the `fleet.py` I launched lives. In A that
is a **copy** (not a symlink — `resolve()` follows a symlink straight back to the repo, which would
have put the real checkout in the population); in B it is the worktree; in C it is the clone.
**`/home/altai/proga/fleet` is named by no term of that union in any of the three.** That is why
nothing could reach it — not because I asserted it.

**I did not pass `--fleet-home`, and that is deliberate.** §5 step 1 is the flag, and it OUTRANKS
the lookup. Passing it on the drives whose purpose is to observe the lookup retarget would have
suppressed the exact phenomenon under test — the run would have come back clean **for the wrong
reason**, which the brief warned has already happened once. Instead the containment is the
population itself, and it is **gated**: `lab.gate()` computes `realpath` of every population member,
of `resolve_home()`'s answer and of `homes_list_path()`, and raises `SystemExit("GATE FAILED,
nothing else ran")` if any of them is outside the lab. It ran before every drive in population A.

The brief's literal gate was also run (MEASURED):

```
$ fleet home            # env exactly as in A, CLAUDE_CODE_SESSION_ID=1a9374bd..
/home/altai/.claude/jobs/3409a1f9/tmp/w61lab/sandbox
probe population: ['/home/altai/.claude/jobs/3409a1f9/tmp/w61lab/install']
```

**Population B is the one that deserves a second look, and I am flagging it rather than burying it.**
To drive the collision through the *shipped* tests I planted `state/fleet.json` in this worktree,
making the worktree a live fleet home for the duration. That is a write to a gitignored path inside
my own fence, it named only fabricated workers, and `rm -rf state mailbox logs` removed it — verified
absent, and `git status` clean. It is nonetheless the riskiest thing this lane did, because a home
that exists is a home something else could resolve. Nothing else could: no list names the worktree,
and only a `fleet.py` launched from **this worktree's** `bin/` derives it as `INSTALL_ROOT`.

---

## 2. Part 1 — the collision, driven end to end

### 2.1 The mechanism, re-derived rather than taken from the brief (MEASURED)

`resolve_home()` (`bin/fleet.py`) evaluates step 1 (flag) → step 2 (sid → home) → steps 3/4
(`FLEET_HOME` / legacy) → step 5 (terminus). **Step 2 outranks `FLEET_HOME`.** Its search space is
`resolution_population()`, which appends `home_identity(INSTALL_ROOT)` **unconditionally**, so the
population is never empty even with no homes list at all. `INSTALL_ROOT` (`bin/fleet.py:114`) is
`Path(__file__).resolve().parent.parent` with a comment stating it is deliberately not env-
overridable. Membership is `_record_sids(rec)` = `session_id` ∪ `retired_sids`.

Consequence, measured: `w60`'s `child_env` `$HOME` redirect moves the LIST term and cannot move
this one. In a worktree the term is inert only because the worktree has no `state/` (measured:
`/home/altai/proga/fleet-w61-sidcollision/state` did not exist). In the main checkout it is a live
home with 22 workers.

### 2.2 The drives (MEASURED — lab population A)

Bystander = the install root itself. Fixture home = a separate sandbox. Caller sid =
`1a9374bd-df92-42ad-972a-06693aeef272`, the shipped constant of the day.

| # | bystander registry | verb | lookup | rc | bystander after | fixture after | bystander file bytes |
|---|---|---|---|---|---|---|---|
| S0 | *no registry* (a worktree) | `kill victim` | **miss** | 0 | — | `victim: idle→dead` | — |
| S1 | a worker whose `session_id` is the caller sid; **no** `victim` | `kill victim` | **hit** | 1 | unchanged | unchanged | **identical** |
| S2 | archived record, sid in `retired_sids`; **plus** a `victim` owned by the caller | `kill victim` | **hit** | 0 | **`victim: idle→dead`** | unchanged | changed |
| S3 | sid on `session_id`; plus a `victim` owned by the caller | `kill victim` | **hit** | 0 | **`victim: idle→dead`** | unchanged | changed |
| S4 | two dead + one idle worker, sid on one | `clean --yes` | **hit** | 0 | **2 records REMOVED, `live: idle→dead-suspected`** | unchanged | changed |

S1's stderr, in full: `fleet: unknown worker: 'victim'`.

**S1 is the correction to the brief.** A hit retargets every time; the *write* needs the bystander to
carry a worker of the same name. S4 is the bound if it ever did not: `clean` is nameless and swept
the bystander without any name collision at all — **no shipped drive passes `clean` a caller sid
today** (MEASURED, §5.2), so S4 is a bound, not an exposure.

### 2.3 The same thing through the SHIPPED tests (MEASURED — population B)

I planted this worktree as a live home carrying `1a9374bd..` in an **archived** record's
`retired_sids`, then ran `tests/test_destructive_guard.py::TestAWorkerCallerIsNotExempt` unmodified.

| plant | result | bystander (`<worktree>/state/fleet.json`) |
|---|---|---|
| control, no plant | `54 passed` (whole file) | n/a |
| sid only, no `victim` | **3 failed, 2 passed** — `unknown worker: 'victim'` three times | untouched |
| sid + a `victim` owned by someone else | **2 failed, 3 passed** | untouched — *the guard refused, correctly* |
| sid + a `victim` owned by the colliding sid | **3 failed, 2 passed** | **`victim: idle → dead`** |

The last row is the brief's hazard, produced by the shipped suite, with no test modified. The
failure text of the third test is `AssertionError: assert 'idle' == 'dead'` — **the fixture home
stayed idle while the bystander died.**

The middle row is worth its own sentence: `test_a_worker_killing_a_sibling_is_refused` **passed**
there, because the *bystander's* worker was foreign to the caller and the guard refused. A green
test, about the wrong home.

---

## 3. Part 2 — the fix

Four constants replaced (`475f04b`):

| file | constant | was | now |
|---|---|---|---|
| `tests/test_destructive_guard.py:157` | `TestAWorkerIsNotExempt.WORKER_SID` | `820762d0-…` | `fa15e51d-0000-0000-0000-000000000003` |
| `tests/test_destructive_guard.py:566` | `TestAWorkerCallerIsNotExempt.WORKER_SID` | `1a9374bd-…` | `fa15e51d-0000-0000-0000-000000000001` |
| `tests/test_destructive_guard.py:567` | `TestAWorkerCallerIsNotExempt.MANAGER_SID` | `20fee653-…` | `fa15e51d-0000-0000-0000-000000000002` |
| `tests/test_subprocess_home_seam.py:56` | `SID` | `20fee653-…` | `fa15e51d-0000-0000-0000-000000000004` |

The two **docstring receipts** that quote the historical sids are untouched. They are records of a
measurement, not executable values, and deleting them would destroy the evidence the tests exist to
carry. Each class now says in a comment that it diverges from its own receipt on purpose.

**Why these values (MEASURED).** Every session id this project has been observed to carry is an
RFC-4122 **version-4** UUID: all 22 sids in the live registry, the five real historical sids quoted
in this tree, and this session's own — 0 exceptions. `fa15e51d-0000-0000-0000-00000000000N` parses
as a UUID (so `fleet._SID_SHAPE_RE` still matches it and no name-shape refusal changes behaviour)
but has version nibble `0` and the NCS variant, so `uuid.UUID(s).version is None`. **BELIEVED, not
measured:** that `claude`'s generator only ever emits v4. I measured the population, not the
generator. If that ever stops being true the property is still checkable — it just stops being
sufficient.

---

## 4. The pin, and the mutants

`tests/test_sid_collision.py`, 15 tests. Three layers:

1. **`caller_sid_sites()`** — an AST census of every value a test puts into a **child's**
   `CLAUDE_CODE_SESSION_ID`: a call keyword, a dict-literal key, `env[KEY] = …`. **One dataflow hop
   is followed** through the enclosing function's parameter (and its default), because both shipped
   drives spell the value as `_run(…, session=<sid>)` — a literals-only lint would have reported a
   clean tree while looking straight at the two sites that mattered.
2. **`offending_sites()`** — the property, as a function, seed-tested in both directions.
3. **`TestTheRetargetIsRealAndStillOpen`** — three live drives that stage a throwaway install tree
   (hard link, falling back to a copy) and show the retarget still happening, including with today's
   shipped sid. **These pass by demonstrating the hole.**

### 4.1 Mutants planted, each asserting its own patch landed before anything ran

| mutant | what it does | result on `tests/test_sid_collision.py` |
|---|---|---|
| **M1** | reverts `TestAWorkerCallerIsNotExempt.WORKER_SID` to `1a9374bd-…` | **4 failed**, 10 passed — incl. `AssertionError: these tests hand a CHILD process a session id shaped like one claude issues…` |
| **M2** | reverts `test_subprocess_home_seam.SID` to `20fee653-…` | **3 failed**, 11 passed |
| **M3** | reverts the in-process `TestAWorkerIsNotExempt.WORKER_SID` to `820762d0-…` | **1 failed**, 13 passed — only `test_the_shipped_constants_are_not_issuable`. **This is the census's stated scope showing through**, not a bug: that constant reaches `monkeypatch.setenv`, never a child. |
| **M4** | `caller_sid_sites` returns `[]` | **7 failed**, 7 passed |
| **M5** | `is_an_issuable_sid` returns `False` for everything | **1 failed**, 13 passed |
| **M6** | `resolution_population()` stops appending the legacy `INSTALL_ROOT` term | **2 failed** — `AssertionError: the INSTALL_ROOT retarget no longer happens — if that is because the seam was fenced, DELETE this class; do not restore the hole.` |
| **M7** | replaces the property test's filter with `offenders = []` | **SURVIVED on the first cut. 15 passed.** |
| **M8** | `offending_sites()` returns `[]` (the fix for M7) | **1 failed**, 14 passed |
| **M9** | `_drive_hook` ignores its `cwd=` keyword (§6's fix) | **4 failed**, 78 passed — and `--bogus/` reappeared in the clone's root |

**M7 is the finding inside the finding.** The first cut of this file spelled the property inline in
one test, exactly the tautology this repo has shipped before — a mutant that hardcoded the offender
list to empty left all 14 tests green. The fix was to pull the selector out into
`offending_sites()` and seed it in both directions, which is what M8 now kills. **M7 as literally
written still survives**, because it edits the assertion body of a test and no test can defend
another test's body against being rewritten; what M8 proves is that the *logic* the property depends
on is independently covered. I am stating that rather than quietly re-scoring M7 as dead.

Every planter asserted `count(anchor) == 1`, asserted the patched text was on disk after writing,
and restored + verified the original in a `finally`. **No floor run was started with a mutant on
disk** — M1–M8 ran against one file, M9 ran in a throwaway clone, and both floor measurements were
taken from a fresh `git clone --no-local` at a committed sha.

### 4.2 What the pin does NOT cover

* **Not the seam.** The reads remain; `INSTALL_ROOT` is still unoverridable. §7.
* **Not in-process `monkeypatch.setenv`.** Deliberate, and stated in the file. Those callers are
  sandboxed by conftest's autouse `_never_touch_the_real_home` and `_never_touch_the_real_install`,
  so a real sid there resolves against a tmp population. **There are 8 v4-shaped `*_SID`
  constants left in 6 other files** (`test_autoclean.py` ×3, `test_doctor_claim_provenance.py`,
  `test_identity_registry.py`, `test_liveness_readers.py`, `test_respawn_retired_sweep.py`,
  `test_statusline_home.py`), three of which (`108300de-…`, `b9b2124d-…` ×2, `d3ebc580-…`) look
  like real captured sids. **Not touched** — out of this lane's mechanism, and cleaning them would churn six unrelated
  files. Filed here so it is not rediscovered as new.
* **Not local variables.** The resolver follows module constants, class constants, `self.X` and one
  parameter hop. A sid held in a local is reported **unresolved**, and `test_every_site_resolves`
  turns that into a FAILURE rather than a skip — the safe direction, and my own file tripped it
  twice while I was writing it, which is how I know the detector is live.
* **Not other environment keys.** Only `CLAUDE_CODE_SESSION_ID`.
* **Not new files added outside `tests/`.**

---

## 5. Things the brief did not have

### 5.1 A fourth site, in a second file (MEASURED)

`tests/test_subprocess_home_seam.py:56` held `SID = "20fee653-f07e-4208-8c0e-1c737f9119f7"` — the
same real manager sid — and hands it to a **child** at lines 236 and 256, one of which is
`kill prod --yes`. That is the *more* exposed of the two files: `--yes` bypasses the destructive
guard entirely, so the third coincidence §2.2 requires (bystander-worker ownership) does not apply
there. The brief listed three sids in one file; the tree had four sites in two.

### 5.2 The sharper hazard class, and why it is NOT armed (MEASURED)

The three hardcoded sids miss by luck. **My own session id does not miss**: `3409a1f9-…` is in the
live registry right now, under the record `w61-sidcollision`. Any subprocess that inherits this
session's environment and drives the real CLI from an install root that is a live home resolves by
**guaranteed** hit — no luck involved.

I checked whether the suite has one. **It does not, today.** AST sweep over `tests/`: 13 subprocess
drives mention a fleet entrypoint, **11 pass an explicit `env=`, 2 do not** — `sh bin/fleet --help`
(exits inside `parse_args`, before `apply_resolved_home`; w60 measured this) and `git ls-files`.
Of the 11, the two integration `Sandbox.env()` helpers build `dict(os.environ)`:
`test_sup_tombstone_live.py` pops `CLAUDE_CODE_SESSION_ID`, and `test_native_pin.py` **does not** —
but both stage `bin/` into their own sandbox home, so their `INSTALL_ROOT` is the sandbox and the
inherited sid misses. `test_native_pin.py` is one `INSTALL_ROOT` change away from being the armed
case; w60 already filed it as open item 1 and I am agreeing with that filing, not re-opening it.

---

## 6. Secondary — and the brief's attribution is wrong (MEASURED)

The brief: *"the six host-assumption failures WRITE INTO THE REPO ROOT"*. They do not.

```
$ git clone --no-local … && pytest -q tests/test_hook_fleet_home_argv.py
78 passed in 7.47s
$ ls -a | grep -E 'bogus|line'
--bogus
line1
line2
```

**Created by a file that is 78/78 GREEN**, with none of the six failures in the run.
`TestHostileArgvNeverRaises.HOSTILE` contains two **relative** values — `--bogus` and
`line1\nline2` — a hook takes `--fleet-home <value>` at its word without resolving it, and the child
inherited pytest's cwd. Contents measured: `<dir>/state/outcomes/<sid>.jsonl` and
`<dir>/state/journals/<sid>.md`, 24 KB each, four hook scripts producing them.

Invisible to `git status` because a directory whose only contents are gitignored is not reported as
untracked. **`git check-ignore` does not ignore the directories themselves** — re-measured, and the
predecessor was right:

```
$ git check-ignore -v -- '--bogus'          ; echo rc=$?   ->  rc=1   (NOT ignored)
$ git check-ignore -v -- '--bogus/state'    ; echo rc=$?   ->  .gitignore:1:state/   rc=0
```

**Recommendation, and it is neither `skipif` nor a fix to the six: give the hook drive a `cwd`.**
The hostility under test is the ARGV; the working directory is fixture. One keyword changes no
assertion, and the six failures are untouched and still carry no `skipif`. The brief asked me to
recommend rather than build; it is one keyword and I measured it, so it is here as a **separate
commit (`80959f6`) that can be dropped without touching this lane's deliverable**. Measured after:
`82 passed`, repo root clean, and clean through **two full floor runs**. Mutant M9 above.

---

## 7. What is still open

1. **The `INSTALL_ROOT` term itself.** Not fenced, and I did not attempt it — the brief priced it
   and a previous test lane correctly refused. **I found no cheap fence and am not proposing one.**
   The two candidates I considered and rejected: (a) a `FLEET_INSTALL` env override — `bin/fleet.py`
   argues against it in a comment at the definition, and it would hand back exactly the separation
   the install/home split exists to make; (b) staging an install tree per drive — that is the twin
   of `conftest._never_touch_the_real_install` and is the cost already priced. `TestTheRetargetIsReal
   AndStillOpen` stages exactly one, once, to keep the hole demonstrated; it is not a fence and says
   so.
2. **Eight v4-shaped `*_SID` constants in six other files** (§4.2), three of which look like real captured
   sids. Inert today because they are in-process only.
3. **`test_native_pin.py`'s `Sandbox.env()`** keeps an inherited `CLAUDE_CODE_SESSION_ID`
   (w60 open item 1). Not armed today; one `INSTALL_ROOT` change from being armed.
4. **The census does not cover a sid held in a local variable** — it FAILS on those rather than
   skipping, which is the right direction but means a future author has to spell sids as constants.

---

## 8. The floor

Predicted in the journal **before** each run, and taken from a separate `git clone --no-local`,
never from the tree being edited.

| sha | interpreter | predicted | measured |
|---|---|---|---|
| `475f04b` | 3.12 | `6 failed, 4938 passed, 16 skipped, 1 xfailed` | **exactly that**, 335s |
| `475f04b` | 3.10 | same | **exactly that**, 370s |
| `80959f6` | 3.12 | `6 failed, 4942 passed, 16 skipped, 1 xfailed` | **exactly that**, 330s |
| `80959f6` | 3.10 | same | **exactly that**, 351s |

4965 collected at `80959f6` (4946 baseline + 15 + 4). The report commit that follows adds this
file and one corrected COMMENT in `tests/test_sid_collision.py`; the floor was re-measured at that
sha too and is unchanged (§8 last row). The six failures are the same host-assumption
ids named in `CLAUDE.md` — three `test_fleet_index.py::TestPathContainment`, one
`test_fleet_q.py::TestOutlinePathContainment`, two `test_terminal_surface.py::TestCollaboratorInstall`.
**No `skipif` was added to any of them.**

---

## 9. WHERE THIS BRIEF WAS WRONG

1. **"the hit retargets a destructive write."** The hit retargets. The *write* needs two more
   coincidences on the drives the suite actually runs — a worker-name match, and (without `--yes`)
   that worker being owned by the colliding sid. §2.2, S1: a hit with no name match leaves the
   bystander registry **byte-identical**. This does not make the hazard smaller in kind, and I would
   not soften the brief's conclusion — but "one archived worker is enough for a write" is not what
   the code does, and a reader planning a fix from that sentence would mis-scope it.
2. **"three sids … hardcoded in `tests/test_destructive_guard.py`."** Four sites, two files. The one
   the brief missed is the more exposed of the two, because it drives `--yes`. §5.1.
3. **"the six host-assumption failures WRITE INTO THE REPO ROOT."** They do not. A passing file does.
   The `skipif`-or-fix decision the brief framed was aimed at tests that create nothing. §6.
4. **"the live registry carries 20 worker records and 20 total record sids."** 22 and 22 when I
   measured. Harmless drift, recorded because the brief invited re-derivation.
5. **The brief's own safety recipe (`--fleet-home` on every invocation) is wrong for this lane** and
   I did not follow it. It is §5 step 1, which outranks the lookup; obeying it would have suppressed
   the phenomenon and produced a clean run for the wrong reason — the failure mode the brief itself
   warns about two paragraphs later. §1.1 gives what I did instead and why it is stronger.

*Written by w61-sidcollision, 2026-09-10.*
