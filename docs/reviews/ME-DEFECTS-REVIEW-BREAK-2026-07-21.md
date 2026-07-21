# ME-DEFECTS — adversarial (break-lens) review

**Branch under review:** `me/defects` — `ef0747f` (supervisor successor dispatch) and `0cbc517`
(autoclean F4 ownership), on base `ac3e34d`.
**Reviewer:** fleet worker `me-defects-break`, worktree `C:/proga/fleet-me-defects-break`,
branch `me/defects-break`.
**Lens:** what breaks, and how do I prove it. Spec/doctrine conformance is a parallel reviewer's job
and is not duplicated here.

## Where every probe ran

`me/defects`' two commits were cherry-picked onto `me/defects-break` (`c155cdf`, `bbdbb2f`) so the
suite could be run against them. `git diff 0cbc517 bbdbb2f` is `docs/PLAN-PROGRESS.md` only (5+/3-),
i.e. **`bin/`, `docs/SPEC.md` and `tests/` are byte-identical to `0cbc517`**. Every command below was
run **by me**, in that worktree, on Windows 10 with `py -3.13`.

Baseline, before any injection:

```
$ py -3.13 -m pytest -q
1147 passed, 6 skipped in 57.40s
```

**Not observable from here** (I am a `--bg` worker, and `schtasks` / mutating `sup-*` / `claude
daemon` are hard-banned by my containment): the real `schtasks /Query /XML` round-trip shape, the
command string of the live `claude-fleet-autoclean` task, and whether the daemon propagates the
launcher environment into the hosted session. Those are marked
**[MANAGER-VERIFICATION REQUIRED]** where they matter and are never asserted.

---

## 1. The builder's pasted receipts — all reproduce

| Receipt | Claim | Result |
|---|---|---|
| R1 | `grep -rn '_autoclean_task_is_ours' bin/ tests/` @ `ac3e34d` → 2 hits (`bin/fleet.py:5290` def, `bin/fleet.py:5331` sole consumer) | **reproduces byte-exact** |
| R2 | `grep -n '"--bg"' bin/fleet.py` @ `ac3e34d` → exactly `6650: argv = [exe, "--bg"]` and `7319: argv = [exe, "--bg", "-n", name]` | **reproduces byte-exact** |
| R3 | suite `1136 → 1142` (`ef0747f`), `1142 → 1147` (`0cbc517`) | end state **1147 passed, 6 skipped** — confirmed |
| R4a | `ef0747f`: reverting `bin/fleet.py` + `docs/SPEC.md` takes **5 of 6** new tests RED, sixth is the shape guard | **reconstructed independently — 5 failed, 1 passed**; the passer is `test_exactly_two_bg_argv_builders`, exactly as claimed |
| R4b | `0cbc517`: with the pre-fix path-only predicate restored, **all four** go RED including `test_same_fleet_py_different_subcommand_is_not_ours` | **reconstructed (injection I8) — 4 failed** |

R4a reconstruction:

```
$ git show ac3e34d:bin/fleet.py > bin/fleet.py && git show ac3e34d:docs/SPEC.md > docs/SPEC.md
$ py -3.13 -m pytest -q ... TestHandoff::test_successor_dispatch_* TestDispatchPathsAreDocumented
FAILED ...test_successor_dispatch_carries_instance_settings   - assert '--settings' in [...]
FAILED ...test_successor_dispatch_refused_without_rendered_settings - DID NOT RAISE FleetCliError
FAILED ...test_successor_dispatch_uses_worker_env             - KeyError: 'env'
FAILED ...test_spec_lead_sentence_scopes_the_choke_point      - assert 'worker' in 'every native launch...'
FAILED ...test_spec_names_the_successor_dispatch_path         - assert 'cmd_sup_handoff_begin' in ...
5 failed, 1 passed in 2.13s
```

**No receipt failed to reproduce.** That part of the builder's account is sound.

---

## 2. Fault-injection table — 16 injections, 13 red / 3 green

One at a time, full suite each time, `git checkout --` after each. Driver:
`$CLAUDE_JOB_DIR/tmp/inject.py` + `run.sh`.

| # | Injection | Result | Failing tests |
|---|---|---|---|
| I1 | drop `--settings <instance>` from the successor argv | RED (1146/1) | `TestHandoff::test_successor_dispatch_carries_instance_settings` |
| I2 | drop `env=_worker_env(name)` from the successor `run(...)` | RED (1146/1) | `TestHandoff::test_successor_dispatch_uses_worker_env` |
| I3 | delete the `_require_instance_settings()` pre-flight | RED (1146/1) | `TestHandoff::test_successor_dispatch_refused_without_rendered_settings` |
| I4 | move the pre-flight **inside** the lock, after the journal + task-file writes | RED (1146/1) | `TestHandoff::test_successor_dispatch_refused_without_rendered_settings` |
| I5 | point `--settings` at `template_settings_path()` instead of the rendered instance | RED (1146/1) | `TestHandoff::test_successor_dispatch_carries_instance_settings` |
| I6 | revert `docs/SPEC.md` to `ac3e34d` | RED (1144/3) | `test_spec_states_full_identity_ownership`, `test_spec_lead_sentence_scopes_the_choke_point`, `test_spec_names_the_successor_dispatch_path` |
| I7 | add a third builder spelled `argv = [exe, "--bg", ...]` | RED (1146/1) | `TestDispatchPathsAreDocumented::test_exactly_two_bg_argv_builders` |
| I8 | restore the pre-fix path-substring predicate | RED (1143/4) | `test_same_fleet_py_different_subcommand_is_not_ours`, `test_same_script_and_verb_different_fleet_home_is_not_ours`, `test_ownership_predicate_all_four_directions`, `test_ownership_requires_an_explicit_fleet_home` |
| I9 | drop **only** the subcommand-adjacency check | RED (1145/2) | `test_same_fleet_py_different_subcommand_is_not_ours`, `test_ownership_predicate_all_four_directions` |
| I10 | drop **only** the `--fleet-home` check | RED (1144/3) | `test_same_script_and_verb_different_fleet_home_is_not_ours`, `test_ownership_predicate_all_four_directions`, `test_ownership_requires_an_explicit_fleet_home` |
| I11 | drop `.lower()` case normalization | RED (1146/1) | `test_own_task_recognized_slash_and_case_insensitive` |
| I12 | drop `\\`→`/` slash normalization | RED (1146/1) | `test_own_task_recognized_slash_and_case_insensitive` |
| **I13** | **`_TASK_ARG_RE` → naive `\S+` (kill quoted-run tokenization)** | **GREEN — 1147 passed, 6 skipped** | — |
| **I14** | **drop `.rstrip("/")` trailing-separator normalization** | **GREEN — 1147 passed, 6 skipped** | — |
| I15 | drop quote-stripping inside `_task_command_tokens` | RED (1144/3) | `test_idempotent_reinstall_of_own_task`, `test_own_task_recognized_slash_and_case_insensitive`, `test_ownership_predicate_all_four_directions` |
| **I16** | **third `--bg` builder spelled `cmd = [claude_exe, "--bg", ...]`** | **GREEN — 1147 passed, 6 skipped** | — |

Three injections leave the suite fully green. Per the brief's own rule, each is a CRITICAL
test-theater finding (B1–B3 below).

---

## 3. Findings

### B1 [CRITICAL] The new tokenizer's entire reason for existing is unpinned — and it answers wrong on the shape it was built for

`_TASK_ARG_RE = re.compile(r'"[^"]*"|\S+')` carries the comment *"Quoted runs are single tokens
(paths contain spaces)"*. Injection **I13** replaces it with a naive `\S+` — deleting quoted-run
handling outright — and **the full suite stays green (1147 passed)**. No test in the repo feeds the
predicate a command whose paths contain a space; `tmp_path` on this machine never does.

That matters because the predicate genuinely *is* quote-sensitive. Probe (mine, `bin/` @ `bbdbb2f`,
`FLEET_HOME = C:\Program Files\My Fleet`):

```
A2 <Command> unquoted + <Arguments> quoted   -> True   (want True)  OK
A3 python path w/ spaces, unquoted           -> True   (want True)  OK
A4 everything unquoted:
   C:\py.exe C:\Program Files\My Fleet\bin\fleet.py autoclean --fleet-home C:\Program Files\My Fleet
                                             -> False  (want True)  **WRONG — refuses its own task**
A6 --fleet-home="C:\Program Files\My Fleet"  -> False  (want True)  WRONG (refuse)
A8 sh-style single quotes                    -> False  (want True)  WRONG (refuse)
```

All three wrong answers are in the **safe** direction (refuse, `--force` available), so this is not
data loss — but the code has an untested parser deciding whether a `/Create /F` fires, and A4 is
exactly the shape a quote-stripping XML round-trip would produce. Whether `schtasks /Query /XML`
emits A2 or A4 for a `/TR` string of this shape is **[MANAGER-VERIFICATION REQUIRED]** — I cannot
run `schtasks`.

**Fix:** parametrize `test_ownership_predicate_all_four_directions` over a home/script/interpreter
path containing a space, and add explicit cases for the unquoted and `--fleet-home=VALUE` forms
(either assert the refusal is intended, or accept `=`-form and unquoted-with-spaces).
**Test that pins it:** `test_ownership_survives_paths_with_spaces_in_every_quoting_variant`.

### B2 [CRITICAL] Trailing-separator normalization is unpinned

`_normalize_task_token` ends `return text.rstrip("/") or text`, docstring: *"(and a trailing
separator on a directory argument), so normalize all three."* Injection **I14** removes it —
**suite green, 1147 passed**. Nothing tests `--fleet-home "C:\home\"`. (My direct probe A7 confirms
the code path works; only the *test* is missing.)

**Fix / test that pins it:** `test_trailing_separator_on_fleet_home_still_ours` — feed
`--fleet-home "<home>\"` and assert `True`; it goes RED under I14.

### B3 [CRITICAL] The third-argv-builder shape guard — the guard against this very defect recurring — is evadable

`TestDispatchPathsAreDocumented::test_exactly_two_bg_argv_builders` matches
`ARGV_BUILDER_RE = r'^\s*argv = \[exe, "--bg"'`. SPEC §6.1 promises it *"fails if a third `--bg`
argv builder appears"*. Injection **I16** adds

```python
def _third_bg_builder_evasive(claude_exe):
    cmd = [claude_exe, "--bg", "-n", "probe"]
    return cmd
```

— a real third `--bg` argv builder — and the **suite stays green (1147 passed)**. Injection I7 (same
builder spelled `argv = [exe, ...]`) does go red, so the guard catches only the one spelling it was
written against. `ef0747f` exists because SPEC §6's enumeration went stale; the guard meant to stop
that recurring has a hole one identifier rename wide.

**Fix:** widen to `re.compile(r'^\s*\w+ = \[\w+, "--bg"', re.M)` (still 2 hits today; I16 makes it 3).
**Test that pins it:** the existing test, with the widened regex — I16 then goes RED.

### B4 [MAJOR] The "what this path deliberately does not carry" enumeration is incomplete: the permission-mode flag is missing, and that is the T12 hang class

`cmd_sup_handoff_begin`'s docstring and SPEC §6.1 both enumerate exactly two deliberate omissions
(`--add-dir`, `--setting-sources`) and assert the path *"carries the same `--settings` instance and
the same `_worker_env` process identity the choke point carries."* Mechanical flag diff of the two
builders (mine, grep not reading):

```
dispatch_bg direct flags       : --add-dir --bg --model --resume --setting-sources --settings
dispatch_bg mode_flags() adds  : --dangerously-skip-permissions | --permission-mode <mode>   (ALWAYS)
successor builder              : --bg --settings [--model] [--permission-mode ONLY if args set]

IN the worker path, ABSENT from the successor path: --add-dir, --setting-sources,
                                                     --dangerously-skip-permissions / mode flag
```

`dispatch_bg` ends with `argv += mode_flags(mode)` and every registry worker has a mode. The
successor gets a permission flag **only** when the operator passes `--permission-mode`, and the
argparse default is `None` (`p_suphb.add_argument("--permission-mode", ...)`, no `default=`).

Repro (probe test, mine, tree @ `bbdbb2f`), `args.permission_mode = None`:

```
PROBE2 successor argv: ['C:/claude.cmd', '--bg', '-n', 'sup|inc-...|successor',
                        '--settings', '.../state/worker-settings.json',
                        'Read .../state/supervisor-handoff-inc-....md and follow it exactly.']
assert "--permission-mode" not in argv                 -> passes
assert "--dangerously-skip-permissions" not in argv     -> passes
```

The successor's bootstrap body (`_render_successor_task`) opens with
`1. Run: py -3.13 <FLEET_HOME>/bin/fleet.py sup-boot --handoff-inc <inc>` — a Bash tool call. In
Claude Code's **default** permission mode a headless `--bg` session cannot answer the resulting
prompt: the successor wedges, never writes `supervisor/HANDSHAKE`, the handoff times out at
`SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS` (300 s), and the operator must abort. That is the exact T12
failure class the brief names, and it is the third difference from the choke point — the one neither
the commit message, the docstring, nor the new SPEC §6.1 enumerates. Classic
"enumeration built by reading instead of grep".

This is a **pre-existing** hazard, not one `ef0747f` introduced. But `ef0747f` is the commit that
audited this argv against the choke point and wrote the resulting enumeration into the SPEC — it
had one job and it missed the dangerous item while catching two harmless ones.

**Fix:** default the successor to the outgoing holder's own mode (or hard-default `bypass` for the
handoff path, matching how a supervisor is booted), and add the mode flag to SPEC §6.1's enumeration.
**Test that pins it:** `test_successor_dispatch_always_carries_a_permission_mode` — assert the argv
from `permission_mode=None` contains one of `mode_flags(...)`'s outputs.

### B5 [MAJOR] The pre-flight was moved before the lock; its twin was not — a missing `claude` strands HANDOFF-BEGIN with **no** abort flag

`cmd_sup_handoff_begin`'s docstring: *"Both failure paths (dispatch failure, successor DOA) raise the
doctor-visible abort flag before returning — a crash here must not leave the old side believing a
successor is in flight when none exists."*

Ordering as shipped:

```python
_require_instance_settings()          # <- moved before the lock by ef0747f  (correct)
with fleet_lock():
    ... task_path.write_text(...)                       # task file written
    supervisor_journal_append("HANDOFF-BEGIN", ...)     # journal written
    handoff_abort_flag_path().unlink()                  # ANY PRIOR ABORT FLAG DELETED
...
exe = resolve_claude_executable(which=which)   # <- can raise ClaudeNotFoundError, still after all of the above
```

`resolve_claude_executable` is the *same class* of pre-flight (a missing external prerequisite) as
`_require_instance_settings`, and it sits after the journal write with no `_abort_flag` guard.

Repro (probe test, mine, tree @ `bbdbb2f`), `which=lambda _n: None`:

```
PROBE1 journal kinds: ['HANDOFF-BEGIN']
PROBE1 task files   : ['supervisor-handoff-inc-20260721T162221Z-df63.md']
PROBE1 abort flag   : False
```

So: `claude` drops off PATH (npm unlink, PATH edit, reinstall) → the journal permanently records
HANDOFF-BEGIN, a stale task file is left in `state/`, any *previous* abort flag has been deleted, no
successor exists, and `fleet doctor` sees nothing. The docstring's promise is false for this path.
The fix that moved one pre-flight left its twin behind — this repo's named recurring class.

**Fix:** hoist `exe = resolve_claude_executable(which=which)` above `with fleet_lock():`, next to
`_require_instance_settings()`.
**Test that pins it:** `test_missing_claude_refuses_before_journal_and_taskfile` — assert
`supervisor_journal_entries() == []` and no `supervisor-handoff-*.md` when `which` returns `None`.
(Injection I4 already proves this test shape bites for the settings pre-flight.)

### B6 [MINOR] `_doctor_check_autoclean`'s scan and the new predicate no longer agree on tokenization

The commit states `_doctor_check_autoclean` *"does NOT use the predicate — it runs its own
quoted-token scan for a missing pinned path, a different check, left alone."* True as far as it goes;
what changed is that the two now **tokenize differently**. Doctor still requires quotes
(`re.findall(r'"([^"]+)"', existing)`); the new predicate accepts both quoted runs and bare `\S+`.

```
cmd = '"C:/py.exe" C:\fleet\bin\fleet.py autoclean --fleet-home "C:\fleet"'   (script token unquoted)
  predicate  -> ours = True
  doctor scan-> fleet.py tokens = []      # F2 "pinned to a missing path" check silently no-ops
```

Doctor is note-only and fails open both ways, so this is diagnostic drift, not breakage — but it is
new drift, introduced by this commit, in the direction of a *quieter* doctor.
**Fix:** have `_doctor_check_autoclean` reuse `_task_command_tokens(existing)`.
**Test that pins it:** `test_doctor_flags_missing_pinned_path_when_unquoted`.

### B7 [MINOR] Residual false-positive: the predicate never checks the interpreter

`_fleet_task_is_ours` requires our script path, `autoclean` immediately after it, and
`--fleet-home <us>`; it never constrains argv[0]. Probes (mine):

```
B5 "C:/py.exe" "C:/tools/wrap.py" --target "<our fleet.py>" autoclean --fleet-home "<us>"  -> True  (want False)
B6 "C:/tools/sweep.exe" "<our fleet.py>" autoclean --fleet-home "<us>" --really-not-fleet  -> True  (want False)
```

Both are contrived and both are strictly better than the pre-fix substring predicate (which said
"ours" to *anything* containing the path). Recording it so it is not re-discovered as new. Everything
realistic answers correctly: foreign `autoclean.exe` → False; same script, other verb → False; same
script+verb, other home → False; `--fleet-home` before the script with a different verb after → False.

### B8 [MINOR] Both new line anchors are stale on arrival — comments that lie about the code

`ef0747f` introduces two anchors, each written against the **pre-edit** file and wrong by exactly the
size of its own insertion:

| Anchor introduced | Points at | Actual line at `0cbc517` |
|---|---|---|
| SPEC §6.1 heading: `cmd_sup_handoff_begin @7280` | — | **7351** |
| docstring: *"the choke point's own name guard (@6631)"* | — | **6705** |

**Fix:** `@7351` / `@6705`.

### B9 [DESIGN-QUESTION] `_worker_env` also stamps `FLEET_WORKER` — the successor supervisor now silently loses its SessionStart briefing

The commit justifies `env=_worker_env(name)` entirely by the `CLAUDE_CODE_SESSION_ID` strip. But
`_worker_env` does two things (`bin/fleet.py:989-1008`), and the second is
`env["FLEET_WORKER"] = name`. `bin/hooks/sessionstart_fleet.py:148` reads exactly that:

```python
# D5: never brief a worker about the fleet it belongs to.
if os.environ.get("FLEET_WORKER"):
    return _emit()          # empty context
```

So a handoff successor — a *supervisor*, the one session for which the fleet briefing is most
relevant — now deterministically starts with the briefing suppressed. Before `ef0747f` the successor
inherited the launcher's environment and the outcome was nondeterministic. `docs/reviews/
THREE-TIER-DESIGN-REVIEW-2026-07-17-spec.md:353` already flagged this and demanded a ruling
("state whether that is intended"); neither the commit message, the docstring, nor SPEC §6.1 mentions
it. Not a defect — an unstated, unruled behavior change on the machinery that lost a supervisor claim
in production. **Ruling needed**, then one sentence in SPEC §6.1 either way.

### B10 [MINOR] The successor's sid-keyed evidence files are never reaped

Confirmed empirically (my hook probe, below): with `--settings` now wired, each successor session
leaves `state/outcomes/<sid>.jsonl` and, on compaction, `state/journals/<sid>.md`. Both
`fleet archive` (`outcome_path(name)` / `outcome_path(sid)` / retired sids from the registry) and
`fleet clean` enumerate from **registry records**, and a successor has none — so these accumulate
one pair per handoff, forever. Pure litter, not corruption. Worth a one-line note in §6.1 or a
sweep in `sup-handoff-complete`.

### B11 [MINOR] A pre-F2 installed task now blocks reinstall

`--fleet-home` entered `_autoclean_task_command` in `8742a72` (`git log -S'--fleet-home "'`). Any task
installed by a fleet build older than that carries no `--fleet-home`, and
`test_ownership_requires_an_explicit_fleet_home` codifies "no `--fleet-home` ⇒ not ours" — so
`fleet init --autoclean` on such a machine now **refuses** instead of overwriting fleet's own task.
Safe direction, and the new error message names all three identity components plus `--force`, so it
is recoverable and self-explanatory. Whether the live `claude-fleet-autoclean` task on this machine
predates `8742a72` is **[MANAGER-VERIFICATION REQUIRED]** (`schtasks /Query /TN claude-fleet-autoclean
/XML` — read-only, but `schtasks` is banned in my containment).

---

## 4. Claims I attacked and could not break

**The four-hook degradation claim — TRUE, verified empirically, not by reading.** I ran each hook as
a real subprocess against a temp `FLEET_HOME` whose `state/fleet.json` contains one worker with a
*different* sid, feeding the successor's sid on stdin:

```
hook=stop_outcome         rc=0 stdout=<empty>
hook=stop_mailbox         rc=0 stdout=<empty>
hook=posttooluse_mailbox  rc=0 stdout=<empty>
hook=postcompact_journal  rc=0 stdout=<empty>
--- state/hook-errors.log: (absent -- no hook errored)
--- files created: state/journals/<sid>.md, state/outcomes/<sid>.jsonl
```

Per code path: `stop_outcome` → `_resolve_name` misses → `key = sid`, and a uuid passes `_valid_token`
→ `outcomes/<sid>.jsonl`. `postcompact_journal` → same fallback → `journals/<sid>.md`.
`posttooluse_mailbox` / `stop_mailbox` never touch the registry at all — sid-keyed throughout.
No path writes a record keyed to a nonexistent worker's *name*, and none logs an error. The claim
holds exactly as written. (A fifth hook exists — `sessionstart_fleet.py` — but it ships in the
plugin, not `worker-settings.template.json`, so "all four" is the correct count for `--settings`; see
B9 for what it does do.)

**`--setting-sources` deliberately not carried — correct.** It is a per-worker registry field
(`setting_sources` in the record, `default=None` on `spawn`/`respawn`, forwarded by `dispatch_bg`
only `if setting_sources:`). A successor with no record therefore behaves identically to any worker
that never had one — not "differently from every worker". No divergence.

**`--add-dir` deliberately not carried — defensible on every layout.** `cwd=str(FLEET_HOME)` and the
task file is `FLEET_HOME/state/supervisor-handoff-<inc>.md`; both are under `FLEET_HOME` by
construction (`state_dir() = FLEET_HOME / "state"`), so a linked worktree, a different drive, or any
`FLEET_HOME` layout keeps the task file inside cwd. `dispatch_bg` needs `--add-dir tasks_dir()` only
because a *worker's* cwd is its project, not `FLEET_HOME`. (The permission hazard on this path is
real but it is B4, not `--add-dir`.)

**Pre-flight-before-lock claim — TRUE and pinned.** Injection I4 (pre-flight moved after the journal
and task-file writes) goes RED on
`test_successor_dispatch_refused_without_rendered_settings`, which asserts
`supervisor_journal_entries() == []` and no `supervisor-handoff-*.md`. The ordering is genuinely
tested, not just claimed.

**Tier-2 husk sweep cannot reap a live successor.** I hypothesized that the new
`state/outcomes/<sid>.jsonl` might vouch the successor's sid as fleet-owned and expose the live
supervisor to `claude rm`. It does not: owned evidence is registry sids ∪ `_archive_dir_sids()`
(`logs/archive/*/`) ∪ `_events_sids()` (`events.jsonl`) — the outcomes dir is not a source. Probe:
with `state/outcomes/succ0001-full.jsonl` present, `_archive_dir_sids() | _events_sids()` is `set()`.
Default-deny holds. **Disproved — no finding.**

**3.10 floor intact.** `py -3.10 bin/fleet.py --help` exits 0 and prints the full subcommand list.

**Double-spawn / foreign-sid-join.** The successor join uses `_join_roster_by_short_id` with
`exclude_sids=pre_sids` from a pre-dispatch snapshot, and unlike `dispatch_bg` it has **no**
wedge-retry — so there is no path where one invocation produces two bodies. A stale roster or a
daemon dying mid-join yields `successor-doa`: abort flag raised, claim unchanged, and if the session
was in fact alive, its own bootstrap self-terminates with `HANDOFF-ORPHAN <inc>` after 10 minutes of
polling. A retry mints a *fresh* incarnation id, and `sup-handoff-complete --expect-inc` can only
transfer to one of them. Bounded. Unchanged by these commits.

---

## 5. SPURIOUS-FIX verdicts (mandatory, per commit)

**`ef0747f` — NOT spurious.** The defect was real and load-bearing: at `ac3e34d` the successor argv
was `[exe, "--bg", "-n", name]` with no `--settings` and the `run(...)` call carried no `env=`
(verified in the `ac3e34d` tree). Both omissions are exactly the ones that would have made a
successor hookless and sid-confused.
*Quietly changed something it was not asked to:* **yes, one** — the `FLEET_WORKER` stamp that rides
along with `_worker_env` and suppresses the successor's SessionStart briefing (B9). The commit
attributes the whole `env=` change to the sid strip.
*Quietly skipped something:* **yes, one, and it is the dangerous one** — the permission-mode flag
(B4). The commit performed an explicit audit of this argv against `dispatch_bg` and published a
two-item omission list into the SPEC; the list is missing the third and only hazardous item.

**`0cbc517` — NOT spurious.** The defect was real: at `ac3e34d` the predicate was
`str(_autoclean_script_path()).lower() in command.lower()`, a bare substring, so any scheduled task
running this `fleet.py` read as "ours". Injection I8 restores it and takes four tests RED, including
`test_same_fleet_py_different_subcommand_is_not_ours` — the defect itself. The SPEC §11 correction
("ownership by exact normalized path" → full identity) is in scope, since the old sentence described
the bug.
*Quietly changed something it was not asked to:* **no.**
*Quietly skipped something:* **one, minor** — it introduced a second, more permissive tokenizer
without aligning `_doctor_check_autoclean`'s quoted-token scan (B6). The commit's own statement that
doctor is "a different check, left alone" is accurate about *intent*, but the two now disagree about
what a token is.

---

## 6. Verdict

Both fixes are real fixes for real defects, both reconstruct under independent fault injection, and
the central hook claim survives empirical verification. What does not survive is the completeness of
`ef0747f`'s enumeration and the depth of `0cbc517`'s test coverage.

**VERDICT: fix-wave(B1, B2, B3, B4, B5)**

| id | exact defect | exact fix | test that pins it |
|---|---|---|---|
| B1 | quoted-run tokenization unpinned (I13 green); predicate answers wrong on the all-unquoted-with-spaces shape | parametrize the ownership tests over a space-bearing home/script/interpreter path; decide and encode the `--fleet-home=VALUE` and unquoted forms | `test_ownership_survives_paths_with_spaces_in_every_quoting_variant` |
| B2 | `rstrip("/")` trailing-separator normalization unpinned (I14 green) | none needed in code — add the missing test | `test_trailing_separator_on_fleet_home_still_ours` |
| B3 | the third-`--bg`-builder shape guard misses any other spelling (I16 green) | widen `ARGV_BUILDER_RE` to `r'^\s*\w+ = \[\w+, "--bg"'` | existing `test_exactly_two_bg_argv_builders`, now RED under I16 |
| B4 | successor dispatch emits no permission-mode flag when `--permission-mode` is omitted → headless prompt wedge (T12 class); SPEC §6.1's omission list is incomplete | default the successor's mode (holder's mode, or `bypass` for the handoff path); add the mode flag to the §6.1 enumeration | `test_successor_dispatch_always_carries_a_permission_mode` |
| B5 | `resolve_claude_executable` still runs after the journal + task-file write, so a missing `claude` strands HANDOFF-BEGIN with no abort flag | hoist it above `with fleet_lock():`, beside `_require_instance_settings()` | `test_missing_claude_refuses_before_journal_and_taskfile` |

Follow-ups, not merge blockers: **B6** (doctor tokenizer alignment), **B8** (two stale anchors —
one-character-class fix), **B10** (successor evidence litter), **B7**/**B11** (recorded so they are
not re-discovered as new). **B9 needs an operator ruling**, then one sentence in SPEC §6.1.

`git status` is clean apart from this file; every injection was reverted and the baseline
re-verified at **1147 passed, 6 skipped** after the campaign.

---

# FINAL GATE — wave 1 (`1c0eb42`, `97c980a`)

**Reviewer:** `me-defects-break`, worktree `C:/proga/fleet-me-defects-break`. Both wave commits were
cherry-picked on top of the two originals (`9b0606a`, `207ec59`); `git diff 97c980a HEAD` is
`docs/PLAN-PROGRESS.md` + this review file only, so **`bin/`, `docs/SPEC.md`, `docs/specs/autoclean.md`
and `tests/` are byte-identical to `97c980a`**. Every command below was run by me in that worktree.

```
$ py -3.13 -m pytest -q
1173 passed, 6 skipped in 59.20s          # matches the manager-verified count
```

## M0 — adjudication

**Verdict: `no-change-made`. Not a `SPURIOUS-FIX`.**

I re-measured M0 independently, loading `bin/fleet.py` from each commit as a module and setting the
vantage explicitly, against the manager-supplied live command literal:

```
LIVE = '"C:\Users\Techn\...\python.exe" "C:\proga\claude-fleet\bin\fleet.py" autoclean --fleet-home "C:\proga\claude-fleet"'

  pre  0cbc517  vantage=CANONICAL C:/proga/claude-fleet        ours=True
  pre  0cbc517  vantage=WORKTREE  C:/proga/fleet-me-defects    ours=False
  post 1c0eb42  vantage=CANONICAL C:/proga/claude-fleet        ours=True
  post 1c0eb42  vantage=WORKTREE  C:/proga/fleet-me-defects    ours=False
```

Pre- and post-wave agree on both vantages. The manager's correction is right: M0 was a vantage
artifact, and the `False` it reported is the F2 worktree-install refusal behaving as designed.

**Was the F2 refusal weakened to make the false receipt pass? No — and this is provable, not
argued.** I diffed every ownership/F2 function's *executable body* between `0cbc517` and `1c0eb42`
via AST, with docstrings stripped:

```
IDENTICAL (code, docstring ignored): _fleet_task_is_ours
IDENTICAL (code, docstring ignored): _autoclean_task_is_ours
IDENTICAL (code, docstring ignored): _normalize_task_token
IDENTICAL (code, docstring ignored): _autoclean_script_path
IDENTICAL (code, docstring ignored): _autoclean_task_command
IDENTICAL (code, docstring ignored): _marker_guard_problems
CHANGED: _install_autoclean_task  -> the B11 sentence appended to the refusal message, nothing else
CHANGED: _task_command_tokens     -> the B1 `--flag=value` split + `_strip_task_quotes` extraction
```

The script-path match, the home guards and `_marker_guard_problems` — the whole F2 refusal — are
**byte-identical code**. Nothing was loosened for M0. The wave's response to M0 was two tests: a
verbatim literal pin of the live command evaluated from the canonical vantage, and
`test_worktree_checkout_refuses_the_live_task_under_both_predicates`, which is the control the
original probe lacked — it asserts the *pre-fix* predicate refuses the same command for the same
reason. Adding a control that disputes a claim is the correct response to a disputed claim, not a
spurious fix. B1 is independent of the error and was real (I13 was green).

Test-hygiene nit only: both new fixtures use `monkeypatch.setattr(..., raising=False)` on an
attribute that exists, so the flag is a no-op today; if the function were ever renamed the patch
would silently no-op and the test would go RED (fail-safe), so this is a nit, not a hole.

## Injection table — 16/16 RED

Same 16 injections, re-anchored to the wave-1 tree, one at a time, full suite each, reverted after
each. **The three that were green are now red.**

| # | Injection | wave 1 result | key failing tests |
|---|---|---|---|
| I1 | drop `--settings` from the successor argv | RED 1172/1 | `test_successor_dispatch_carries_instance_settings` |
| I2 | drop `env=_worker_env(name)` | RED 1172/1 | `test_successor_dispatch_uses_worker_env` |
| I3 | delete the `_require_instance_settings()` pre-flight | RED 1172/1 | `test_successor_dispatch_refused_without_rendered_settings` |
| I4 | move that pre-flight inside the lock, after the writes | RED 1172/1 | same |
| I5 | `--settings` to template instead of rendered instance | RED 1172/1 | `test_successor_dispatch_carries_instance_settings` |
| I6 | revert `docs/SPEC.md` to `ac3e34d` | RED 1167/6 | + `test_spec_61_records_the_mode_flag_decision`, `test_spec_61_keeps_the_unobserved_hedge`, `test_spec_12_does_not_claim_the_successor_uses_dispatch_bg` |
| I7 | third builder `argv = [exe, "--bg", ...]` | RED 1171/2 | `test_exactly_two_bg_argv_builders`, `test_both_bg_argv_builders_live_in_the_documented_functions` |
| I8 | restore the pre-fix substring predicate | RED 1166/7 | the four originals + 3 new quoting-variant tests |
| I9 | drop only the subcommand-adjacency check | RED 1170/3 | + `test_spaced_path_wrong_subcommand_still_refused` |
| I10 | drop only the `--fleet-home` check | RED 1170/3 | the three ownership-direction tests |
| I11 | drop the `.lower()` case fold | RED 1171/2 | + `...[uppercased throughout ...]` |
| I12 | drop the backslash-to-slash fold | RED 1169/4 | + `...[forward slashes throughout ...]`, 2 trailing-separator cases |
| **I13** | **`_TASK_ARG_RE` to a naive `\S+`** | **RED 1164/9** *(was GREEN)* | all 6 `test_accepted_quoting_variants_are_ours` + all 3 `test_trailing_separator_...` |
| **I14** | **drop `.rstrip("/")`** | **RED 1170/3** *(was GREEN)* | `test_trailing_separator_on_fleet_home_still_ours` x3 |
| I15 | `_strip_task_quotes` to identity | RED 1159/14 | incl. `test_live_installed_task_command_is_ours` |
| **I16** | **third builder `cmd = [claude_exe, "--bg", ...]`** | **RED 1171/2** *(was GREEN)* | both shape guards |

**16 red / 16.** B1, B2 and B3 are genuinely closed, not papered over: I13 now takes down nine tests
across six quoting variants, and I15 (removing quote-stripping) takes down fourteen including the
live-artifact pin.

## New-defect hunt — 8 fresh injections at the wave itself

| # | Probe | Result |
|---|---|---|
| **N1** | third `--bg` builder spelled **multi-line** (`"--bg"` on its own line) | **GREEN 1173** — guard still blind |
| N2 | drop the `else: argv += mode_flags(SUCCESSOR_DEFAULT_MODE)` branch | RED — `test_successor_dispatch_always_carries_a_permission_mode` |
| N3 | `SUCCESSOR_DEFAULT_MODE = "omit"` (a **valid** key that emits no flag) | RED — the same test's `assert expected` catches it |
| N4 | explicit `--permission-mode` **also** appends the default (two opinions) | RED — `test_explicit_permission_mode_overrides_the_successor_default` |
| N5 | kill the new `--flag=value` split | RED — the `--fleet-home=VALUE` variant |
| N6 | drop the new `Path(tok).is_absolute()` narrowing in doctor | RED 2 — `test_installed_no_stamp`, `test_installed_stale_stamp` |
| N7 | revert doctor to the pre-wave quoted-only scan | RED — `test_doctor_flags_missing_pinned_path_when_unquoted` |
| N8 | third builder that **replaces** one (count stays 2) | RED — `test_both_bg_argv_builders_live_in_the_documented_functions` |

**Manager's question — "does exactly one mode opinion reach the argv, on every path, including when
the operator passes one?" Answer: yes.** N2 (no opinion), N3 (an opinion that emits nothing) and N4
(two opinions) all go red. The `if/else` arms are mutually exclusive and both are pinned.

**N6 is the interesting negative.** Removing the `is_absolute()` narrowing turns two *pre-existing*
doctor tests red — i.e. the narrowing was **required** by the wider tokenizer, not a quiet weakening
smuggled in beside it. The commit's claim "no existing assertion was weakened" holds.

### G1 [MINOR] `B3-residual` — the shape guard is still evadable by a line break

`ARGV_BUILDER_RE = r'\[[^\]\n]*"--bg"'`. The `\n` in the negated class means the match cannot cross a
newline, so a third builder whose `"--bg"` sits on its own line walks past both guards (N1, suite
green at 1173). This is a **residual, not new** — the pre-wave regex was equally blind — and the
wave's own claim is scoped honestly ("catches the I7, I16 and `argv += [...]` shapes", all three of
which I confirmed red). But a multi-line list is what any formatter produces once the line grows,
and SPEC 6.1 still leans on this guard.

**Fix (one character), verified by me:**

```
CURRENT  r'\[[^\]\n]*"--bg"' : clean=2  with-multiline-3rd-builder=2   <- blind
PROPOSED r'\[[^\]]*"--bg"'   : clean=2  with-multiline-3rd-builder=3   <- catches it
```

Dropping `\n` from the class is safe: `[^\]]*` still stops at the first `]`, so it cannot run away.
**Test that pins it:** N1 as a fixture in `test_exactly_two_bg_argv_builders`.

### G2 [MINOR, NEW] The `--flag=value` split manufactures a `--fleet-home` token out of another flag's value

The B1 fix splits any `-`-leading token on its first `=`. That is index-blind: the **value** half is
emitted as an ordinary token, and `tokens.index("--fleet-home")` cannot tell it from a real flag.

```
cmd = '"C:/py.exe" "<our fleet.py>" autoclean --exclude=--fleet-home "<our home>"'

pre-wave  0cbc517: tokens=[..., 'autoclean', '--exclude=--fleet-home', 'c:/program files/my fleet']
                   ours=False
post-wave 1c0eb42: tokens=[..., 'autoclean', '--exclude', '--fleet-home', 'c:/program files/my fleet']
                   ours=True     <-- regression, dangerous direction
```

A genuine new false-positive in the direction that matters, introduced by this wave. Its
exploitability is negligible — the command must *already* name our exact resolved `fleet.py` with
`autoclean` immediately after, which is the B7 envelope the docstring now documents — so I am not
blocking on it. But it is a regression, and the fix is one line.

**Fix:** only split when the flag half is a flag fleet actually renders — e.g.
`if raw.startswith("--fleet-home=")` — or, equivalently, refuse to emit the value half as an
index-searchable token.
**Test that pins it:** `test_equals_split_does_not_manufacture_a_fleet_home_flag`, asserting the
command above is `False`.

### G3 [MINOR, NEW] `--permission-mode` now carries two vocabularies on one flag

The default arm emits a **fleet** mode name resolved through `mode_flags`; the explicit arm passes
the operator's string straight through as a **claude** mode. `p_suphb.add_argument("--permission-mode")`
has no `choices=`.

```
default path emits              : ['--permission-mode', 'dontAsk']
SUCCESSOR_DEFAULT_MODE literal  : 'dontask'
operator typing `--permission-mode dontask` emits: ['--permission-mode', 'dontask']
```

An operator who reads the new constant and types it verbatim gets a different, probably invalid,
value — which surfaces as `dispatch-failed` rather than as an argument error. New with the wave,
because the constant is what invites the confusion.
**Fix:** `choices=` on the argparse (claude mode strings), or route the explicit arm through
`mode_flags` too.
**Test that pins it:** `test_permission_mode_rejects_a_fleet_mode_name`.

### G4 [MINOR, NEW] The B5 twin-check receipt was run at the pre-fix commit

The manager asked me to re-run it. It does **not** reproduce at the commit it is pasted in:

```
pasted in 1c0eb42's message : _require_instance_settings: 2291 3349 3524 3969 7407
                              resolve_claude_executable : 4658 5460 5523 5833 6373 6712 7124 7435
actual @ 0cbc517 (pre-fix)  : 2291 3349 3524 3969 7407  /  4658 5460 5523 5833 6373 6712 7124 7435   <- exact match
actual @ 1c0eb42 (ships in) : 2291 3349 3524 3969 7498  /  4658 5501 5564 5874 6431 6770 7191 7500
actual @ 97c980a (HEAD)     : 2291 3349 3524 3969 7499  /  4658 5501 5564 5874 6431 6770 7191 7501
```

Byte-exact at `0cbc517`, wrong at 7 of 13 lines at the commit that carries it — the same
stale-on-arrival class as B8, recurring inside the wave that fixed B8.

**The substance is nonetheless correct, and I verified it independently rather than taking it.**
Owning function for every `resolve_claude_executable` call site at HEAD:

```
 4658  _rm_native_session_status      try/except ClaudeNotFoundError -> (False, "no-claude")
 5501  _doctor_check_claude_version   try/except -> a doctor row
 5564  _doctor_check_pin_version      try/except Exception
 5874  _doctor_check_claude_agents    try/except -> "skipped"
 6431  _stop_native_session_status    try/except -> (False, "no-claude")
 6770  dispatch_bg                    -> NativeDispatchError
 7191  _fetch_agents_roster           -> (False, reason)      [read in full: cannot raise at all]
 7501  cmd_sup_handoff_begin          -> FleetCliError, now ABOVE the lock
```

No third raw-raise site. `_fetch_agents_roster` is total (catches `ClaudeNotFoundError`, wraps `run`
in `except Exception`, catches `JSONDecodeError`, and shape-checks the payload), and
`_join_roster_by_short_id` is isinstance-guarded throughout, so nothing between the journal write and
the first `_abort_flag` can raise. **The abort-flag question is answered: every pre-dispatch failure
path that writes anything is now covered.**
**Fix:** re-run the grep at the commit, or cite functions rather than lines — which is exactly what
B8's own fix did in the sibling commit.

**Residual, unchanged and not introduced here:** an interrupt (Ctrl-C, or any exception) *after* a
successful dispatch but *before* the sid is printed leaves a live successor, HANDOFF-BEGIN journaled,
no abort flag, and no handle. `dispatch_bg` wraps its join in `except BaseException` to `add_note` the
short id; this path does not. Pre-existing on both waves; recorded, not filed.

## Disposition — B1 through B11

| id | severity | disposition | receipt |
|---|---|---|---|
| B1 | CRITICAL | **FIXED** | I13 9 red (was green); 6 accepted + 2 refused variants pinned as decisions; both refusals are the safe direction |
| B2 | CRITICAL | **FIXED** | I14 3 red (was green), parametrized over the three separator shapes |
| B3 | CRITICAL | **FIXED**, residual G1 | I16 2 red (was green); N8 red via the new owner guard; **N1 multi-line still green** |
| B4 | MAJOR | **FIXED** | N2/N3/N4 all red — exactly one mode opinion on every path; residual G3 |
| B5 | MAJOR | **FIXED** | both pre-flights above the lock; prior abort flag preserved (own test); twin check re-verified by me at HEAD — no third site; receipt hygiene G4 |
| B6 | MINOR | **FIXED** | N7 red; N6 red proves the `is_absolute()` narrowing was required, not a weakening |
| B7 | MINOR | **ACCEPTED / DOCUMENTED** | recorded in `_fleet_task_is_ours`'s docstring so it is not re-filed; slightly widened by G2 |
| B8 | MINOR | **FIXED** | both line anchors replaced by durable name anchors rather than renumbered — the right fix |
| B9 | DESIGN-QUESTION | **RULED — accepted** | keep `_worker_env`; SPEC 4 forbids the successor any action before transfer, so a manager briefing would invite exactly the banned actions. The recorded constraint (`FLEET_WORKER` means *not the manager*, not *is a registry worker*) is the load-bearing half and is correct |
| B10 | MINOR | **DEFERRED `[UNBUILT]`** | accepted: reaping needs a successor registry identity, which is SPEC 7's call |
| B11 | MINOR | **FIXED** | refusal message names the pre-F2 migration path; `--force` recovers |

**No finding regressed. No finding is `NOT-FIXED`.**

## Other gate items

- **3.10 floor:** `py -3.10 bin/fleet.py --help` exit 0; `import fleet` under 3.10 OK;
  `mode_flags('dontask') == ['--permission-mode', 'dontAsk']` and the new `=`-split tokenizer both
  evaluate correctly under 3.10.
- **Views never probe:** `tests/test_terminal_surface.py` → **169 passed**. The wave touches
  `_fleet_task_is_ours`, `_task_command_tokens`, `_doctor_check_autoclean` and
  `cmd_sup_handoff_begin` — no view path, and the new code is pure string work with no probe.
- **Portability invariant 8 (D8):** `_normalize_task_token`'s code is unchanged and contains no OS
  branch. The added caveat is correct on both counts: the case fold is a false-**miss** on a
  case-sensitive filesystem, and the backslash-to-slash fold is a false-**match** there — naming the
  more dangerous direction is the right addition. Still `[UNVERIFIED]`, correctly labelled.

## FINAL VERDICT

Wave 1 closes all five blockers with receipts that survive independent re-injection: **16 of 16
injections red, the three formerly-green ones now the hardest-hitting of the set.** M0 was correctly
disputed rather than obeyed, and the F2 refusal it would have pressured is provably byte-identical
code. The one place the wave over-claimed (the twin-check grep) is wrong only in its line numbers;
its substance holds when re-derived from scratch.

Three one-line residuals remain (G1 regex, G2 `=`-split, G3 argparse `choices`) plus a receipt-hygiene
note (G4). None is a merge blocker; G2 is a real but negligibly-exploitable regression inside the
already-documented B7 envelope. Spending a third wave on three one-liners is worse than merging and
filing them.

**VERDICT: merge**

Follow-ups to file, not blockers: **G1** (`\[[^\]]*"--bg"` — verified: clean 2, catches the multi-line
builder), **G2** (split only on `--fleet-home=`), **G3** (`choices=` on `sup-handoff-begin
--permission-mode`), **G4** (re-run or de-number the twin-check receipt).

`git status` clean apart from this file; every injection reverted; baseline re-verified at
**1173 passed, 6 skipped** after the campaign.
