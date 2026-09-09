# w60-homeseam — the subprocess half of `~/.claude` isolation

**Lane:** build (tests). Branch `w60/homeseam`, from `1c7f9a4`.
**Every line below is marked MEASURED or BELIEVED.** MEASURED means I ran it on this host in this
lane and read the output; BELIEVED means I reasoned to it and could not drive it.

---

## 0. Safety ledger (MEASURED)

`~/.claude/fleet-homes.list` is RATIFIED DESTRUCTIVE — only the fold reverses an append.

| when | check | result |
|---|---|---|
| T0, before anything else in this lane ran | `ls -la ~/.claude/fleet-homes.list` | `No such file or directory`, exit 2 |
| after each live drive (5 checkpoints) | same | unchanged — still absent |
| end of lane | same | unchanged — still absent |

**Absence is the recorded pre-state and the recorded post-state.** There is no sha256 to record
because there is no file; that *is* the measurement, and `conftest.homes_list_snapshot` already
models it as `(False, None, None)`.

Commands that touched the **real** home, exhaustively — all read-only:

- `ls ~/.claude/fleet-homes.list`, `ls -la ~/.claude/` (inventory).
- `python -c` against `/home/altai/proga/fleet/bin`, calling `resolution_population()`,
  `lookup_home_for_sid()` and `read_registry_at()` — §6's measurement. These read
  `/home/altai/proga/fleet/state/fleet.json`. `read_registry_at` never writes (its own docstring,
  and `tests/test_read_registry_at.py`).
- `grep` over `/home/altai/proga/fleet/state/fleet.json`.

**Never run, at any point: `fleet homes --add`, `fleet homes --retire`, `fleet init`,
`fleet init --home`, or any write to any path under the real `~/.claude`.** Every live `fleet` and
`fleet_statusline` drive in this lane ran with `HOME` redirected into a fresh
`tempfile.mkdtemp()`/`tmp_path` — including the drives whose *purpose* was to show what happens
without the redirect, which resolve the real path and read it but create nothing.

---

## 1. Verdict on the brief, up front

| the brief said | verdict |
|---|---|
| four shipped sites read the operator's real list | **CONFIRMED** (MEASURED), line numbers drifted 1–10 |
| `homes_list_path()` ultimately reads `$HOME` | **CONFIRMED** (MEASURED) |
| the real list is absent on this host | **CONFIRMED** (MEASURED) |
| "LOW TODAY … a determinism hazard, not a data-loss hazard" | **PARTLY WRONG, in the direction of under-stating it.** On a lookup *hit* the verb is **retargeted**, and `kill` then writes `"dead"` into a home the fixture never named. MEASURED end to end in §5.2. It is still low *today* — but the failure mode is a destructive write, not a read. |
| "count of four … might be eleven" | **the census is 46 subprocess launches, of which 8 drive a real fleet interpreter and 5 unit-tier ones needed the seam.** The brief's own grep shape (`{**os.environ}` / `os.environ.copy()`) finds **6** of the 46; `dict(os.environ)` and `dict(os.environ, **kw)` are two further spellings it does not match. §3. |
| "most likely: `HOME` is not the whole seam" | **RIGHT, twice over.** (a) `USERPROFILE` is a separate arm and `ntpath.expanduser` never reads `HOME` at all. (b) **A second, non-env seam exists** — the legacy `INSTALL_ROOT` term of `resolution_population()`. §6. |
| "I may be wrong that this is only tests" | **it is only tests.** The one shipped `{**os.environ}` site is correct in production. §7.1. |
| "I am asserting this should land before multi-fleet is adopted" | **AGREED, and the urgency is not only yours** — §6 shows an exposure that is live today with no list at all. |

---

## 2. The mechanism, re-derived (MEASURED)

`bin/fleet.py:361` — `homes_list_path()` returns `Path.home() / ".claude" / "fleet-homes.list"`.
`Path.home()` is `cls("~").expanduser()` (`/usr/lib/python3.12/pathlib.py:1200`), which dispatches to
the platform flavour's `os.path.expanduser`.

Driven in a child with `FLEET_HOME` set and the four interesting `HOME` states:

```
A) HOME inherited (the shipped sites' shape)  -> /home/altai/.claude/fleet-homes.list
B) HOME=<tempdir>                             -> /tmp/tmpXXXX/.claude/fleet-homes.list
C) HOME=""                                    -> /.claude/fleet-homes.list
D) HOME deleted from the child env            -> /home/altai/.claude/fleet-homes.list
```

**(D) is the one that matters and it is not obvious.** `posixpath.expanduser` falls back to
`pwd.getpwuid(os.getuid()).pw_dir` when `HOME` is absent, so **deleting the variable is not
isolation** — it lands back on the operator's real home. The seam must **set**, never unset.
**(C) is a third wrong answer**: the empty string is taken at its word rather than falling back.
Both are pinned (`TestUnsettingIsNotTheSeam`).

**The Windows arm (MEASURED from stdlib source, BELIEVED as to Windows runtime behaviour).**
`/usr/lib/python3.12/ntpath.py::expanduser` reads `USERPROFILE`, else `HOMEDRIVE` + `HOMEPATH`.
**It never consults `HOME`.** So a POSIX-only redirect would be a seam that silently does nothing on
the Windows host this repo still supports. I cannot drive Windows here; the *env dict* is what the
pin asserts, because that half is observable from every host.

**One variable moves the whole surface** (MEASURED, AST): `homes_list_path`, `user_settings_path`,
`claude_daemon_lock_path`, `claude_daemon_log_path` and the transcript glob in `_transcript_for`
(`bin/fleet.py:2600`) all spell `Path.home()`. **No module-level assignment in `bin/fleet.py`,
`bin/fleet_statusline.py`, `bin/fleet_keeper.py` or any `bin/hooks/*.py` is home-derived** — verified
over `ast.parse(...).body`, so a bare `import fleet` in a child is inert.

---

## 3. The census (MEASURED, AST over `tests/`)

**46 real subprocess launches.** My first AST pass reported 56; ten were `run(...)`/`Popen(...)`
bound to something that is not `subprocess` (a `lambda` wrapping a git helper in
`test_fleet_index.py`, a `SimpleNamespace` test double in `test_supervisor.py`, a bound test method
in `test_round7_defect_pins.py`). Cross-checked against a regex sweep, which found 48 textual hits;
the two the AST does not carry are `subprocess.run(...)` inside **docstrings**
(`test_cli.py:329`, `test_rendered_command_quoting.py:495`). Both directions reconciled.

### 3.1 How the env is built — every spelling in the tree

| spelling | sites | matched by the brief's grep? |
|---|---|---|
| *no `env=` at all* (inherits the entire parent env, real `$HOME` included) | 20 | no |
| `dict(os.environ)` then `env["FLEET_HOME"] = …` | 13 | **no** |
| `{**os.environ, "FLEET_HOME": …}` | 5 | yes |
| `dict(os.environ, GIT_CONFIG_NOSYSTEM="1", …)` (`GIT_ENV`) | 5 | **no** |
| `{**__import__("os").environ, "FLEET_PYTHON": …}` | 3 | yes (barely) |
| `{k: v for k, v in os.environ.items() if k != "FLEET_HOME"}` | 1 | **no** |
| fully-explicit dict, no inheritance | 2 | n/a — structurally clean |
| caller-supplied `env` parameter | 3 | opaque at the site |

The brief's shape finds **6 of 46**. This is the census payoff: the defect class is *"a child that
inherits the real `$HOME`"*, and `{**os.environ}` is one of six ways this repo writes that.

### 3.2 Verdict per site, by child

**A. Real `bin/fleet.py` CLI drive — `main()` reaches `read_homes_list()`. NEEDS THE SEAM.**

| site | verb | env | verdict |
|---|---|---|---|
| `tests/test_destructive_guard.py:505` `TestRealCliRefusesCleanly._run` | `kill` | `{**os.environ}` | **FIXED** (one of the briefed four) |
| `tests/test_destructive_guard.py:583` `TestAWorkerCallerIsNotExempt._run` | `kill` | `{**os.environ}` | **FIXED** (one of the briefed four) |
| `tests/test_native.py:4912` `TestMainUtf8Reconfigure` | `result w1` | `dict(os.environ)` | **FIXED — the brief did not have this one** |
| `tests/integration/test_native_pin.py:292` `Sandbox.fleet` | any | `dict(os.environ)` | **NEEDS IT, NOT APPLIED** — see §7.2 |
| `tests/integration/test_sup_tombstone_live.py:94` `Sandbox.fleet` | any | `dict(os.environ)` | **NEEDS IT, NOT APPLIED** — see §7.2 |

**B. Real `bin/fleet_statusline.py` drive — calls `fleet.resolution_population()`
(`bin/fleet_statusline.py:547`). NEEDS THE SEAM.**

| site | env | verdict |
|---|---|---|
| `tests/test_terminal_surface.py:1382` | `{**os.environ}` | **FIXED** (briefed) |
| `tests/test_install_home_split.py:350` | `{**os.environ}` | **FIXED** (briefed) |

**C. `sh bin/fleet --help` — `tests/test_terminal_surface.py:1172`, `env=None`. EXEMPT (MEASURED).**
`--help` exits inside `parser.parse_args`, which runs *before* `apply_resolved_home`
(`bin/fleet.py:22787` vs `:22792`). Driven with `HOME` pointed at a two-home poisoned list: exit 0,
no ambiguity refusal — the resolver is never reached.

**D. Hook drives (`bin/hooks/*.py`) — 14 sites. STRUCTURALLY EXEMPT (MEASURED).**
No hook resolves a home from the user profile: zero occurrences of `Path.home()`, `expanduser`,
`USERPROFILE`, `HOMEDRIVE` or a `HOME` env read across all four scripts, and none imports `fleet`
(standalone doctrine, stated in `stop_outcome.py`'s own docstring). A hook child with an inherited
`$HOME` reads nothing under `~/.claude` at all.
**This exemption is now enforced, not remembered** — `TestTheHookExemptionIsStructural` fails the
day a hook grows one of those reads, and its message names this section.
Sites: `test_hooks.py:39,232,234`; `test_native.py:809`; `test_outcome_surrogate.py:104,276,299,327,349`;
`test_outcome_usage_provenance.py:51`; `test_permission_denials.py:75`; `test_pin_usage_contract.py:81`;
`test_stillborn_handoff.py:229`; `test_hook_fleet_home_argv.py:117`.

**E. `python -c "<payload>"` importing fleet — 5 sites. EXEMPT TODAY (MEASURED), by fact not by shape.**
`test_core.py:74`, `test_install_home_split.py:182,396,418`, and `_probe` in the new file. The first
four print an import-time attribute (`fleet.FLEET_HOME`, `fleet.INSTALL_ROOT`, a hook's
`_fleet_home()`); §2 establishes that the bare import touches no home. The fifth is the measuring
instrument and is deliberate. **A `-c` payload that called `main()` would slip past the lint** — that
boundary is written into `census_home_seam_sites`'s docstring rather than implied.

**F. `git` drives — 11 sites. EXEMPT from *this* defect; a different one is noted.**
`git` reads the operator's `~/.gitconfig`. `GIT_ENV` sets `GIT_CONFIG_NOSYSTEM=1` and pins
author/committer, but does **not** redirect `HOME`, so user-scope git config still reaches these
tests. **Not in this lane's scope, not fixed, reported here so it is not rediscovered as new.**
Sites: `test_doc_claims.py:490`; `test_lane_report_durability.py:147,189`;
`test_keeper_collect.py:452,467,487,583`; `test_fleet_index.py:2004`;
`test_terminal_surface.py:1079,1163`.

**G. Real `claude` binary — `test_native_pin.py:194`, `test_sup_tombstone_live.py:72`, `env=None`.
MUST NOT BE REDIRECTED.** These need the operator's real `~/.claude` — that is where the
credentials live. Redirecting `HOME` here would break the tier, not fix it.

**H. `sh run_py.sh` / CLI shim — 4 sites. EXEMPT.** Interpreter selection; touches no `~/.claude`.
`test_terminal_surface.py:1091,1121,1150,1212`.

**I. `cmd /c mklink` — 2 sites, Windows-only filesystem ops. EXEMPT.**
`test_handoff_seams.py:1545`, `test_fleet_index.py:1374`.

---

## 4. Which mechanism covers which population

The brief asked for this said plainly, because conflating the two is how the defect survived.

| population | mechanism | pinned by |
|---|---|---|
| **in-process** tests | `conftest._never_touch_the_real_home` — monkeypatches four helpers **by name** in the pytest interpreter. **Does not reach a subprocess**: a child re-imports `fleet` and gets the shipped `homes_list_path`. | `test_slice_e_pins.py::TestTheConftestRedirectReachesEveryFile` |
| **subprocess** drives | `conftest.child_env(sandbox, **over)` — a redirected `$HOME`/`%USERPROFILE%` in the **child environment**. NEW. | `tests/test_subprocess_home_seam.py` |
| **writes** to the real list, from either | `conftest._the_real_homes_list_is_untouched_afterwards` (session-scoped, hashes contents). | its own seeds in `test_slice_e_pins.py` |

**The gap the third row does not close, stated because it is the one that bit:** that guard hashes
`~/.claude/fleet-homes.list`. It sees an append **to the list**. It does not see a **read**, and it
does not see a write into a home the list merely *names* — which is exactly the hazard §5.2
measures. Nothing in the tree caught it, and nothing would have.

---

## 5. Proving the seam has teeth

### 5.1 The discriminator (MEASURED)

`tests/test_subprocess_home_seam.py`, 27 tests, all green on 3.12.

Both directions are asserted, as the brief required: with `HOME` redirected a child resolves the
**temp** list *and reads the planted members back*; with the seam removed the same child resolves
the **real** one. The second is the control — without it, every other assertion would pass just as
happily on a host where `Path.home()` ignored `$HOME`, and the seam would be a no-op nobody noticed.

**Five mutants of `child_env`, each run against the file (MEASURED):**

| mutant | result |
|---|---|
| M1 — set neither `HOME` nor `USERPROFILE` | **6 failed**, 6 passed |
| M2 — pop them instead of setting them (the plausible wrong fix) | **7 failed**, 5 passed |
| M3 — set both to `""` | **6 failed**, 6 passed |
| M4 — set `HOME` only, drop the Windows arm | **1 failed**, 11 passed |
| M5 — leave `HOMEDRIVE`/`HOMEPATH` standing | **1 failed**, 11 passed |
| (restored) | **12 passed** |

M1's six, by name — these are the tests that would have been green on the broken world had they
been written without teeth:

```
TestTheSeamDecidesWhichListAChildReads::test_with_the_seam_a_child_resolves_the_sandbox_list
TestTheSeamDecidesWhichListAChildReads::test_the_two_arms_disagree
TestTheWindowsArmIsCarried::test_userprofile_is_set_to_the_same_directory
TestARealKillsAnswerFollowsTheSeam::test_two_sandbox_homes_claiming_the_sid_reach_the_ambiguity_refusal
TestARealKillsAnswerFollowsTheSeam::test_a_listed_home_that_claims_the_sid_retargets_a_destructive_verb
TestTheStatuslineRenderFollowsTheSeam::test_the_render_changes_with_the_sandbox_list
```

(The mutation counts above are from the 12-test file as it stood before the census lint was added;
the lint's own seeds are mutation-tested separately, below.)

**Reverting one shipped site fix** (`test_destructive_guard.py`'s first `_run` back to
`{**os.environ, …}`): `test_every_site_carries_child_env_or_a_written_exemption` goes RED,
1 failed / 26 passed. Restored: 27 passed.

### 5.2 The hazard itself, driven (MEASURED) — this is the part the brief under-stated

`resolve_home` computes `lookup_home_for_sid(...)` **eagerly, before step 1**
(`bin/fleet.py`, `out = {... "lookup": lookup_home_for_sid(...)}`), and `apply_resolved_home` runs
before dispatch for every verb outside `TERMINUS_EXEMPT_VERBS = ("homes",)`. So the list is read on
essentially **every** `fleet` invocation, `FLEET_HOME` notwithstanding — not only on `kill`.

Two homes in the list, both claiming the child's sid, `FLEET_HOME` naming a third:

```
HOME inherited (real, list absent) : rc=1  "refusing to kill 1 worker(s) this session did not spawn"
HOME -> a 2-home list              : rc=1  "session … is a member of 2 fleet homes, so no home can be
                                            resolved from membership alone: /…/homeA  /…/homeB"
```

The shipped test asserts `"--yes" in (out.stdout + out.stderr)`. **The second message does not
contain `--yes`. The test fails.**

**One** home in the list claiming the sid — the *hit* case, which does not refuse but **retargets**:

```
$ fleet kill prod --yes        # FLEET_HOME = <sandbox>, HOME -> a list naming <bystander>
rc: 0
out: prod-worker: killed
  <bystander>/state/fleet.json  workers.prod.status -> "dead"      <-- WRITTEN
  <sandbox>  /state/fleet.json  workers.prod.status -> "idle"      <-- UNTOUCHED
```

A destructive verb wrote outside the fixture, into a home the fixture never named. Not a read.
Pinned as `test_a_listed_home_that_claims_the_sid_retargets_a_destructive_verb`.

The statusline pair is milder and worth stating precisely: `rc` stays 0 either way, so **the two
shipped statusline tests would have stayed green over the defect** — only the *render* changes
(`[fleet] idle 1` vs `[fleet]: home ambiguous (2)`). Their exposure is determinism, not failure.

---

## 6. THE SECOND SEAM — `HOME` is not the whole of it (MEASURED)

The brief predicted this and it is real, though not where it guessed.

`resolution_population()` is **the folded list ∪ the legacy `INSTALL_ROOT` home** (§8's term, still
live). `INSTALL_ROOT` is `Path(__file__).resolve().parent.parent` and is **deliberately not
overridable by env** — no `HOME`, no `FLEET_HOME`, nothing moves it. So:

- **the population is never empty, even with no list at all**; and
- **when the suite runs from a checkout that is itself a live fleet home, every one of these drives
  reads that home's registry.**

Measured against the operator's main checkout:

```
INSTALL_ROOT (main checkout) = /home/altai/proga/fleet
population                   = ['/home/altai/proga/fleet']
real registry readable: True | workers: 19
lookup(820762d0..) -> miss     lookup(1a9374bd..) -> miss     lookup(20fee653..) -> miss
```

All three sids hardcoded in `test_destructive_guard.py` **miss today** — 0 occurrences in the real
registry, measured. That is **luck, not design**: they are real historical sids of this very
project, `_record_sids` is `session_id ∪ retired_sids`, and one archived worker carrying one of them
turns every miss into a hit and every hit into §5.2.

In this worktree the term is benign (`INSTALL_ROOT` is the worktree, which has no `state/`), which
is why the fixed tests pass here. **That is an accident of where the lane ran.**

**NOT FIXED, deliberately.** `conftest._never_touch_the_real_install` already redirects
`INSTALL_ROOT` for **in-process** tests; the subprocess twin would mean staging a whole fake install
tree per drive, which is a design decision with a real cost and belongs to the operator, not to a
test lane. `child_env`'s docstring says it does not do this, and names this section. **Filed as open
item 2.**

**This is also why I would not say the urgency is only the manager's.** The list term arms when
`fleet homes --add` runs; the legacy term is armed **now**, on any box where the suite runs from a
live home.

---

## 7. Findings the brief asked me to look for

### 7.1 Is a SHIPPED code path the same shape? (MEASURED — no)

12 subprocess launches in `bin/`. One builds a partially-overridden env:
`bin/fleet_keeper.py:363` — `_run_text(run, argv, env={**os.environ, "FLEET_HOME": str(home)})`.
`bin/fleet.py`'s `_worker_env` is `dict(os.environ)` minus `CLAUDE_CODE_SESSION_ID` plus
`FLEET_WORKER`. **Both are correct in production**: a child of the real fleet *should* inherit the
operator's real `~/.claude` — that is where the credentials, the settings and the true homes list
live. There is no shipped defect of this shape. **The brief's biggest-finding slot is empty, and I
checked it rather than assuming.**

### 7.2 Open item 1 — the two live-tier sandboxes (BELIEVED, not measured)

`tests/integration/{test_native_pin,test_sup_tombstone_live}.py`'s `Sandbox.fleet` drives the real
CLI with `dict(os.environ)`, so it has the defect. **I did not apply the seam there.**

Reasoning: `Sandbox.fleet("spawn", …)` reaches `dispatch_bg`, which launches the real `claude`
binary with `_worker_env(name)` — a plain `dict(os.environ)`. A redirected `HOME` therefore
**propagates to `claude`**, which would find an empty `~/.claude` and no credentials. I believe that
breaks the tier; I could not measure it, because the tier is `FLEET_LIVE=1`-gated and costs real
Claude sessions, which is outside this lane's fence.

The correct fix is probably *narrower than `child_env`*: redirect only `homes_list_path`'s file, or
give `_worker_env` an explicit `HOME` passthrough — but that is a change to **shipped** code and
needs the operator. **Exempted with a written sentence in `_EXEMPT`**, which
`test_no_exemption_is_stale` will fail the day either site moves.

### 7.3 Open item 3 — `~/.gitconfig` in the git drives (MEASURED, out of scope)

See §3.2 group E. Eleven sites; user-scope git config reaches all of them. Same *class*, different
file, no fleet involvement. Not fixed.

---

## 8. What changed

| file | change |
|---|---|
| `tests/conftest.py` | `+ subprocess_home(sandbox)`, `+ child_env(sandbox, **over)` — module-level, beside the existing in-process sandbox, with the "set, never unset" and Windows-arm reasoning in the docstring. **No existing fixture touched.** |
| `tests/test_subprocess_home_seam.py` | NEW. 27 tests: the two-direction discriminator, the three wrong-redirect shapes, the Windows arm, the verb-level teeth, the AST census lint + 6 seeds, the hook-exemption pin. |
| `tests/test_destructive_guard.py` | both `_run` helpers → `child_env`. |
| `tests/test_terminal_surface.py` | the statusline drive → `child_env`. |
| `tests/test_install_home_split.py` | the statusline drive → `child_env`. |
| `tests/test_native.py` | the `fleet.py result` drive → `child_env`. |

---

## 9. WHERE THIS BRIEF WAS WRONG

1. **"a determinism hazard … not a data-loss hazard, and you should not write it up as one."**
   I am writing it up as neither, but the honest description is stronger than the brief's: on a
   lookup **hit** the verb is retargeted, and `fleet kill --yes` then **writes** `"dead"` into a
   bystander home's registry (§5.2, driven). Still low today — but the failure mode is a write
   outside the fixture, not a read.

2. **"the `kill` pair would run `lookup_home_for_sid` across it."** True but too narrow. The lookup
   is computed eagerly in `resolve_home` for **every verb** outside `TERMINUS_EXEMPT_VERBS`
   (one entry: `homes`). `kill` is not special; `result`, `status`, `clean` and the rest all read
   the list.

3. **"census every subprocess launch … that passes `{**os.environ}` or `os.environ.copy()`."**
   That shape finds **6 of 46**. `os.environ.copy()` appears **zero** times in this tree.
   `dict(os.environ)` — 13 sites — is the spelling the repo actually uses, and the one that carries
   two of the sites that needed fixing (`test_native.py`, both integration sandboxes). A census run
   to the brief's grep would have missed them.

4. **"four … `env={**os.environ}` and only `FLEET_HOME` overridden."** The larger population is
   `env=None` — **20 sites**, which inherit the *entire* parent environment, `$HOME` included. Same
   defect, spelled shorter, and invisible to any grep for `os.environ`. The census lint flags a
   missing `env=` as an offence for exactly this reason (seeded:
   `test_a_missing_env_kwarg_is_flagged`).

5. **"`Path.home()` on POSIX prefers `$HOME` but falls back to `pwd`."** Correct, and the
   consequence is sharper than the brief drew it: it means **deleting `HOME` is not a fix** — it
   lands back on the real home (§2, measured). A reader who reached for `env.pop("HOME")` would have
   written a seam that does nothing and a green test suite that proves nothing.

6. **"some site may … hold a module-level constant computed at import."** Checked by AST across
   `bin/fleet.py`, `bin/fleet_statusline.py`, `bin/fleet_keeper.py` and all four hooks: **none**.
   The real second mechanism is elsewhere — the `INSTALL_ROOT` term of `resolution_population()`
   (§6), which no environment variable can move.

7. **"I am asserting this should land before multi-fleet is adopted. If your census shows the
   exposure is narrower than that, say so."** It is **not** narrower. §6 shows a term that is armed
   today, with no list on the machine at all, on any box where the suite runs from a live fleet
   home — which is how this repo is routinely developed.

8. **Line numbers.** All four had drifted (1372→1382, 351→350, 506→505, 584→583). Found by shape, as
   instructed; recorded here so the next reader knows the drift was real and small.

---

## 10. Suite

Prediction was written down before the run; see §11 in the commit message and the journal.
