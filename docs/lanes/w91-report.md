# w91 report — a verb that cannot measure must not publish a measurement

DONE means: `wave-close` never publishes `MEASURED` on a lane count it could not derive, reporting unparsed merges instead and refusing when the range holds merges it cannot attribute; `fleet land` enforces the same docs-currency rules the wave floor does; and the `merge(<lane>):` convention is stated where a supervisor reads it, all three pinned by tests.

## A. `_wave_merge_audit` replaces the silent-drop regex

`_wave_landed_lanes` used to `continue` past any merge subject that failed
`^merge\(([^)]+)\):` -- git's own default `Merge <branch>: ...` included --
so an unattributable merge simply vanished from the lane list and every
downstream figure (`workers`, `tokens`, `external_lines`,
`tokens_per_bin_line`) read as a confident, measured zero. `bin/fleet.py`
now has `_wave_merge_audit(repo, base, run)`, returning
`(lanes, unparsed)`: `lanes` is unchanged (parsed, substrate-joined), and
`unparsed` is the short SHAs of merges the regex could not match.
`_wave_landed_lanes` is now a one-line wrapper around it, so its own
existing callers and tests (`tests/test_reap_lane_arm.py`,
`_wave_mark_landed_lanes`) are untouched.

## Where the refusal lands, and why

`cmd_wave_close` calls `_wave_merge_audit` immediately after the committer
identity check and BEFORE the first `with fleet_lock():` -- i.e. before the
claim heartbeat write, the reap, the interpreter floor, the changelog
prepend, the journal prepend, `_wave_mark_landed_lanes`, and the commit.
That is every mutation this command performs, plus its two most expensive
steps. `unparsed` non-empty raises `FleetCliError` naming
`UNPARSED: <n> of <total>` and the offending SHAs; a genuinely empty range
(`lanes == [] and unparsed == []`) falls through unchanged and closes as
the legitimate no-lanes wave, which is explicitly distinguished by
`test_merge_audit_zero_merges_is_not_the_same_as_unparsed`. Moving the
check this early also means a close that cannot be attributed no longer
pays for the reap or the floor -- both already unavoidable expense before
this lane, `_wave_merge_audit` itself is one cheap `git log`.

`tests/test_wave_close.py::test_wave_close_refuses_an_unattributable_range_before_any_mutation`
drives this through real `git` (init a repo, merge a branch with `--no-ff`
so git writes its own default subject, no interpreter floor or FLEET_HOME
needed because the refusal is unreachable-past that point) and asserts the
CHANGELOG, the commit log, and the working tree are byte-for-byte
unchanged after the refusal.
`test_unparsed_merge_refusal_precedes_every_mutation_in_cmd_wave_close`
pins the same ordering statically, in source.

## B. The convention, stated where a supervisor reads it

`skills/fleet/SKILL.md`'s "Wave boundary" section now states the
`merge(<lane>): <summary>` convention and what happens when it is not
followed. `fleet land`'s GREEN output now prints
`next: git merge --no-ff -m 'merge(<lane>): <summary>' <lane_branch>` --
the exact command to run next -- so the convention is read at the moment a
supervisor is about to merge, not enforced by a regex documented nowhere.
A RED verdict prints no such line (`test_land_red_verdict_prints_no_merge_command`).
`docs/SPEC.md`'s `wave-close` row states the attribution rule and the
refusal.

## C. `land`'s docs-currency check now matches the floor's

`bin/fleet_land.py:_check_commands` shells
`{python} tests/test_docs_currency.py .` deliberately without a `uv`/pytest
dependency (the module's own comment: "no dependency on the fleet kernel
or its parser globals"; `land` cannot assume pytest is importable on the
host interpreter -- see CLAUDE.md's own `--with pytest` invocation). Its
`__main__` ran only `currency_violations`, never
`test_new_lane_documents_have_done` or `test_dispatched_tasks_have_done`,
so `land`'s cheap gate was strictly weaker than the wave floor's pytest
pass over the same file -- exactly the w90 defect (`docs/lanes/w89-report.md`
missing its DONE line passed `land` GREEN, then failed the floor after the
full two-interpreter run). Fix: `__main__` now also calls those two test
functions directly (no pytest import, per the "no new dependency"
constraint) and folds any `AssertionError` into the same error list
`currency_violations` already returns.

`tests/test_fleet_land.py::test_check_commands_docs_currency_catches_a_lane_report_missing_done`
replays the w90 shape through the real subprocess call: a synthetic git
repo, a copy of the real `tests/test_docs_currency.py` re-cut with a local
`ADOPTION_BASE` (the constant is repo-specific and does not exist in a
throwaway repo), a `docs/lanes/w1.md` missing its DONE line, and asserts
`fleet_land._check_commands` returns a non-zero `docs-currency` rc.
`tests/test_docs_currency.py::test_main_runs_the_done_checks_not_just_currency_violations`
pins the `__main__` source change directly.

## Scope and constraints held

Out of scope, untouched: `_wave_mark_landed_lanes`'s worktree join (item
16), the reap predicate, the notify headline (item 5), the brief lints
(item 6). `bin/fleet.py` and `bin/fleet_land.py` stay stdlib-only. No
`fleet.lock` probing/writing/quarantining was added to any view.

## Full floor

Both interpreters, six known pre-existing host-venv artifacts
(`test_fleet_index.py::TestPathContainment` x3,
`test_fleet_q.py::TestOutlinePathContainment` x1,
`test_terminal_surface.py::TestCollaboratorInstall` x2), not adopted.
Exact counts: `docs/lanes/w91.json` `claims[]` (3.10: 5376 passed, 6 failed,
16 skipped, 3 xfailed; 3.12: same counts).

## Judgement: a self-inflicted line-number regression, found and fixed

The first real full-floor run (not the placeholder counts an earlier
session in this worktree had drafted without running) came back 11 failed,
not 6. The six matched the documented artifacts exactly; the other five did
not: `tests/test_retired_sid_citations.py` (2) and
`tests/test_self_citations.py` (3). Both suites assert that comments in
`bin/fleet.py` citing OTHER lines of the same file by number (e.g. "see
`_tombstone_releasing_body` (:12573)") still point at the line they claim
to. This lane's own edit -- inserting `_wave_merge_audit` and the
`cmd_wave_close` refusal check, net +37 lines -- shifted every line number
below the insertion point, so four such self-citations (written by earlier
lanes, untouched by this one) went stale:

- `bin/fleet.py:828` (`_quarantine_artifacts`'s docstring, "quarantine-
  artifact readers" bullet for `_tombstone_releasing_body`): `:12573` was
  the call site before this lane's insert; the real call is now at
  `:12610`.
- `bin/fleet.py:10535-10536` and `:11183` (two `retired_sids` "OWN prior
  sid alone" citing sentences): `:14054` was the real writer
  (`succ_rec["retired_sids"] = list(...) + [prior]`) before the insert;
  it is now at `:14091`.
- `bin/fleet.py:10533` (the same docstring's "sites that already key on
  the union" enumeration): four of its numbers (`:12866, :12867, :12928,
  :13729`) shifted to `:12903, :12904, :12965, :13766`.

Decision, recorded per the manager's no-`AskUserQuestion` rule: fixed these
four citations in this lane rather than reporting them as a claim or
leaving them for a future lane. This is direct fallout of this lane's own
edit to `bin/fleet.py` -- unlike the six documented host-venv artifacts,
which predate this lane and the brief explicitly says not to adopt -- so
leaving it broken on `w91/measured-zero` would land a self-citation
invariant failure this lane caused, on the exact kind of dishonest-
measurement defect this lane's DONE clause targets. Each fix is a citation
number correction with no behavior change; re-verified by the same tests
that caught the breakage
(`uv run --no-project --python 3.10 --with pytest python -m pytest -q
tests/test_retired_sid_citations.py tests/test_self_citations.py` -- 23
passed), and the full 3.10 floor was then re-run in full to confirm it
returns to exactly the six documented failures (job re-run: 6 failed, 5376
passed, 16 skipped, 3 xfailed -- byte-identical `FAILED` lines to the
pre-fix run's six).
