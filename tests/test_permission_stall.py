"""A worker parked on a permission prompt must not render as HEALTHY.

THE INCIDENT THIS EXISTS FOR, measured live 2026-07-30. A merge worker was
dispatched into a worktree whose `.claude/settings.local.json` `deny` list held
`Bash(git merge:*)`, took the merge, and hung:

    merge-idxq   working   1 turn   9 min ago   FLAGS: waiting-permission

`fleet peek` showed eight consecutive `[tool] Bash` calls and no text. A hard
deny beats every permission mode, `bypass` included, so the call was never going
to return -- and the row read `working` for nine minutes, which is the one status
nobody investigates. This is the third time this fleet has paid for the shape
"a denial presents as a hang rather than as an error" (the stillborn handoff's
`SUCCESSOR_DEFAULT_MODE = "dontask"` was the same geometry, one verb over), and
the governing principle is the 12h53m outage's: *a signal nobody is obliged to
read is not a signal.*

WHY THE FIXTURE IS BUILT THE WAY IT IS. A shipped daemon-wedge check once PASSED
on the exact outage it was built from, because its fixture fabricated two
evidence lines that never happened. When the real artifact exists, the fixture IS
the artifact -- so `founding_incident` below reproduces the measured shape and
nothing else: a `working` native record on its 1st turn, `last_activity` nine
minutes back, and a roster entry carrying `status: "waiting"` +
`waitingFor: "permission prompt"` per the contract's field-presence table
(`docs/specs/native-substrate.md`, the `state: "blocked"` permission-prompt row).
The worktree is a REAL directory with a REAL `.claude/settings.local.json` whose
`deny` list holds the rule that caused it, because the remedy the check prints is
read out of that file and a fabricated remedy is exactly the failure above.

NON-VACUITY. `TestTheDetectorDiscriminates` is the other half, and it is the half
that matters: a detector that fires on everything would pass the incident test
forever while saying nothing. It holds the detector against the near misses that
share most of the incident's shape -- a `busy` worker, a prompt younger than the
threshold, an `attached` worker (an operator IS at the keyboard), and the
contract's OTHER `state: "blocked"` row (a consumed Stop-block, `status: "idle"`,
which is a finished session and not a stall). `test_the_threshold_is_below_the_
founding_incident` pins the trap directly: `LAUNCH_CLAIM_MAX_AGE_SECONDS` is the
obvious constant to key a threshold on and it is LARGER than the incident, so a
detector keyed on it would have been silent through the outage it was built from.
"""
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

import fleet


# Anchored on the REAL clock, deliberately. `_permission_stalls` takes an
# injectable `now`, but `cmd_doctor`/`cmd_status` reach it through the real one,
# and a frozen future NOW made every record's `last_activity` compute a NEGATIVE
# elapsed there -- which is under any threshold, so the end-to-end tests went
# green against a detector that had found nothing (caught while writing this
# file, and it is the same fabricated-evidence hazard the module docstring is
# about, one layer down). The incident's shape is "nine minutes ago", which is
# relative by nature; every helper-level call below passes `now=NOW` so the two
# clocks agree.
NOW = datetime.now(timezone.utc)
SID = "aaaabbbb-1111-2222-3333-444455556666"

# The measured incident: MIN-AGO read 9 and never advanced past it usefully.
INCIDENT_MINUTES = 9


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with a rendered instance settings stub (mirrors
    test_cli.py's `isolated_home` -- pytest path rules block importing fixtures
    across test files, per the M-B plan doc's shared-scaffolding note)."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    settings = tmp_path / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    (tmp_path / "mailbox").mkdir(exist_ok=True)
    return tmp_path


def _worktree(root, *deny_rules):
    """A worktree directory carrying a real `.claude/settings.local.json`."""
    root.mkdir(parents=True, exist_ok=True)
    claude = root / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"],
                                    "deny": list(deny_rules)}}),
        encoding="utf-8")
    return root


def _roster_entry(sid=SID, *, name="fleet|merge-idxq|task", state="blocked",
                  status="waiting", waiting_for="permission prompt", pid=1234,
                  kind="background", cwd="C:/proj"):
    """Roster entry per the contract field-presence table. Defaults reproduce the
    `state: "blocked"` PERMISSION-PROMPT row (§G10): `status: "waiting"` plus a
    `waitingFor` field. Pass `status=None`/`pid=None` to model a dead entry (keys
    OMITTED, never null), and `waiting_for=None` to model an entry that reports
    the wait without saying what for."""
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": cwd,
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    if waiting_for is not None:
        entry["waitingFor"] = waiting_for
    return entry


def _record(cwd, *, name="merge-idxq", status="working", minutes_ago=INCIDENT_MINUTES,
            sid=SID, **overrides):
    rec = fleet.new_worker_record(sid, cwd, "merge idx/core into main", "bypass",
                                 dispatch_kind="bg")
    rec["status"] = status
    rec["turns"] = 1
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=minutes_ago))
    rec["last_activity"] = _iso(NOW - timedelta(minutes=minutes_ago))
    rec.update(overrides)
    return {name: rec}


@pytest.fixture
def founding_incident(home, tmp_path):
    """The 2026-07-30 stall, reproduced: `merge-idxq`, working, 1 turn, dispatched
    nine minutes ago, into a worktree that denies `Bash(git merge:*)`, with the
    roster reporting it parked on a permission prompt."""
    cwd = _worktree(tmp_path / "fleet-idxq", "Bash(git merge:*)", "Bash(git push:*)")
    workers = _record(cwd)
    fleet.save_registry({"workers": workers})
    return types.SimpleNamespace(cwd=cwd, workers=workers,
                                 roster=[_roster_entry(cwd=str(cwd))])


# ---------------------------------------------------------------------------
# 1. The detector fires on its founding incident.
# ---------------------------------------------------------------------------

class TestTheFoundingIncidentIsDetected:

    def test_the_nine_minute_merge_stall_is_a_stall(self, founding_incident):
        """THE HEADLINE. The exact measured shape, detected."""
        stalls = fleet._permission_stalls(
            founding_incident.workers, founding_incident.roster, now=NOW)
        assert [s[0] for s in stalls] == ["merge-idxq"]
        _name, _rec, elapsed, waiting_for = stalls[0]
        assert elapsed == pytest.approx(INCIDENT_MINUTES * 60, abs=2)
        assert waiting_for == "permission prompt"

    def test_doctor_FAILS_on_it(self, founding_incident, capsys):
        name, ok, message = fleet._doctor_check_permission_stalls(
            founding_incident.workers,
            which=lambda _n: "claude.cmd",
            run=_fake_run(founding_incident.roster))
        assert name == "permission-stalls"
        assert ok is False, "a worker that will never finish must turn doctor red"
        assert "merge-idxq" in message

    def test_the_row_names_the_rule_that_caused_it(self, founding_incident):
        """A check that reports a condition without naming the remedy is half a
        check -- and the remedy has to come out of the real file, not out of the
        message template."""
        _n, _ok, message = fleet._doctor_check_permission_stalls(
            founding_incident.workers,
            which=lambda _n: "claude.cmd",
            run=_fake_run(founding_incident.roster))
        assert "Bash(git merge:*)" in message
        assert "settings.local.json" in message
        assert str(founding_incident.cwd) in message

    def test_the_remedy_is_one_the_reader_can_actually_run(self, founding_incident):
        """R2 (2026-07-26): a diagnostic must never name a remedy that cannot
        work for its audience. The audience ran `fleet doctor` on this machine,
        so every verb named must be theirs to run."""
        _n, _ok, message = fleet._doctor_check_permission_stalls(
            founding_incident.workers,
            which=lambda _n: "claude.cmd",
            run=_fake_run(founding_incident.roster))
        assert "fleet peek merge-idxq" in message
        assert "fleet respawn merge-idxq" in message
        assert "fleet kill merge-idxq" in message

    def test_the_row_says_a_deny_beats_bypass(self, founding_incident):
        """The root cause, in the output. The worker was in `bypass` mode and
        still hung; an operator who does not know that reads the mode and
        concludes the deny cannot be the cause."""
        _n, _ok, message = fleet._doctor_check_permission_stalls(
            founding_incident.workers,
            which=lambda _n: "claude.cmd",
            run=_fake_run(founding_incident.roster))
        assert "bypass" in message
        assert "never returns" in message

    def test_cmd_doctor_prints_the_row_and_exits_nonzero(
            self, founding_incident, capsys):
        """End to end through the real `cmd_doctor`, not just the check
        function -- registration in `check_calls` is exactly the one-liner an
        edit drops."""
        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(args, which=lambda _n: "claude.cmd",
                              run=_fake_run(founding_incident.roster))
        out = capsys.readouterr().out
        assert "[FAIL] permission-stalls:" in out
        assert "merge-idxq" in out
        assert rc == 1

    def test_fleet_status_repeats_it_below_the_table(
            self, founding_incident, monkeypatch, capsys):
        """`fleet status` printed `waiting-permission` in the FLAGS column all
        along, and the incident is the proof that a flag among token counts is
        not a signal. It gets its own line, next to hook-errors."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, founding_incident.roster))
        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args)
        out = capsys.readouterr().out
        assert rc == 0
        # The old surface still there...
        assert "waiting-permission" in out
        # ...and the new one, on its own line, after the table.
        stall_line = [ln for ln in out.splitlines() if ln.startswith("permission-stall:")]
        assert len(stall_line) == 1
        assert "Bash(git merge:*)" in stall_line[0]
        assert out.index("waiting-permission") < out.index("permission-stall:")

    def test_status_json_does_not_get_the_line(
            self, founding_incident, monkeypatch, capsys):
        """`--json` consumers parse stdout; a human sentence in there is a
        corruption, not a courtesy."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, founding_incident.roster))
        args = fleet.build_parser().parse_args(["status", "--json"])
        fleet.cmd_status(args)
        out = capsys.readouterr().out
        assert "permission-stall:" not in out


# ---------------------------------------------------------------------------
# 2. Non-vacuity: the detector says NO to the near misses.
# ---------------------------------------------------------------------------

class TestTheDetectorDiscriminates:

    def test_the_threshold_is_below_the_founding_incident(self):
        """The trap, pinned. `LAUNCH_CLAIM_MAX_AGE_SECONDS` is the obvious
        constant to reuse and it is LARGER than the nine-minute incident -- a
        detector keyed on it would have stayed silent through the outage it was
        built from."""
        assert fleet.PERMISSION_STALL_SECONDS < INCIDENT_MINUTES * 60
        assert fleet.PERMISSION_STALL_SECONDS < fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS

    def test_a_busy_worker_is_not_a_stall(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        roster = [_roster_entry(status="busy", waiting_for=None)]
        assert fleet._permission_stalls(_record(cwd), roster, now=NOW) == []

    def test_a_prompt_younger_than_the_threshold_is_not_a_stall(self, home, tmp_path):
        """A prompt answered in 20s is not a stall. Neither is one an operator
        is still mid-answer on."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, minutes_ago=1)
        assert fleet._permission_stalls(workers, [_roster_entry()], now=NOW) == []

    def test_an_attached_worker_is_not_a_stall(self, home, tmp_path):
        """`attached` means an operator is at that session's keyboard and CAN
        answer the prompt -- the one case that genuinely is not a stall."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, status="attached")
        assert fleet._permission_stalls(workers, [_roster_entry()], now=NOW) == []

    def test_a_consumed_stop_block_is_not_a_stall(self, home, tmp_path):
        """The contract's OTHER `state: "blocked"` row: a session that passed a
        consumed Stop-block reports `state: "blocked"` with `status: "idle"` and
        is genuinely FINISHED. `state` alone means two different things, so the
        detector reads `status`."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        roster = [_roster_entry(state="blocked", status="idle", waiting_for=None)]
        assert fleet._permission_stalls(_record(cwd), roster, now=NOW) == []

    def test_a_worker_absent_from_the_roster_is_not_a_stall(self, home, tmp_path):
        """Roster-gone is the dead-suspected discriminator's business, not
        this check's."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        assert fleet._permission_stalls(_record(cwd), [], now=NOW) == []

    def test_a_different_sids_wait_is_not_this_workers_stall(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        other = "ffffffff-9999-8888-7777-666655554444"
        assert fleet._permission_stalls(_record(cwd), [_roster_entry(sid=other)],
                                        now=NOW) == []

    def test_an_archived_tombstone_is_not_a_stall(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, archived_at=_iso(NOW))
        assert fleet._permission_stalls(workers, [_roster_entry()], now=NOW) == []

    def test_a_legacy_prepivot_record_is_not_a_stall(self, home, tmp_path):
        """No native roster semantics apply to a pre-pivot record."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, dispatch_kind=None)
        assert fleet._permission_stalls(workers, [_roster_entry()], now=NOW) == []

    def test_a_preclaim_with_no_sid_is_not_a_stall(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, session_id=None)
        assert fleet._permission_stalls(workers, [_roster_entry()], now=NOW) == []

    def test_a_nondict_record_cannot_crash_it(self, home):
        """Registry field-shape drift (hand-repaired records) must degrade the
        detector to a no-op, never a traceback -- doctor's per-check isolation
        would catch a crash, but it would replace a real finding with one."""
        assert fleet._permission_stalls({"junk": "not a dict"},
                                        [_roster_entry()], now=NOW) == []

    def test_no_stalls_reads_as_no_stalls_not_as_silence(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt")
        _n, ok, message = fleet._doctor_check_permission_stalls(
            _record(cwd), which=lambda _n: "claude.cmd", run=_fake_run([]))
        assert ok is True
        assert "no worker parked on a permission prompt" in message


# ---------------------------------------------------------------------------
# 3. An unreadable timestamp must not silence a witnessed stall.
# ---------------------------------------------------------------------------

class TestAWitnessedWaitOutranksAMissingClock:

    def test_a_record_with_no_last_activity_is_still_reported(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd)
        del workers["merge-idxq"]["last_activity"]
        stalls = fleet._permission_stalls(workers, [_roster_entry()], now=NOW)
        assert [(s[0], s[2]) for s in stalls] == [("merge-idxq", None)]

    def test_an_unparseable_last_activity_is_still_reported(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, last_activity="not-a-timestamp")
        stalls = fleet._permission_stalls(workers, [_roster_entry()], now=NOW)
        assert [(s[0], s[2]) for s in stalls] == [("merge-idxq", None)]

    def test_the_line_says_age_unknown_rather_than_inventing_one(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        workers = _record(cwd, last_activity="not-a-timestamp")
        stall = fleet._permission_stalls(workers, [_roster_entry()], now=NOW)[0]
        assert "age unknown" in fleet._permission_stall_line(*stall)


# ---------------------------------------------------------------------------
# 4. A roster it cannot fetch is "NOT CHECKED", never "nothing wrong".
# ---------------------------------------------------------------------------

class TestAnUnfetchableRosterIsNotAPass:

    def test_claude_missing_says_not_checked(self, home, tmp_path):
        """Same tolerance as `_doctor_check_claude_agents`: the roster is a
        foreign CLI surface and its absence is not this fleet's health. But the
        row must not read like a clean bill -- `_doctor_check_registry` documents
        exactly this hazard (a vacuous PASS looking like "nothing wrong")."""
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        _n, ok, message = fleet._doctor_check_permission_stalls(
            _record(cwd), which=lambda _n: None, run=_fake_run([]))
        assert ok is True
        assert "NOT CHECKED" in message
        assert "no worker parked" not in message

    def test_unparseable_roster_says_not_checked(self, home, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")

        def run(argv, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout="not json", stderr="")

        _n, ok, message = fleet._doctor_check_permission_stalls(
            _record(cwd), which=lambda _n: "claude.cmd", run=run)
        assert ok is True
        assert "NOT CHECKED" in message


# ---------------------------------------------------------------------------
# 5. The deny-list reader: a diagnostic input that must never raise.
# ---------------------------------------------------------------------------

class TestWorktreeDenyRules:

    def test_reads_the_deny_list(self, tmp_path):
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)", "Bash(git push:*)")
        assert fleet._worktree_deny_rules(cwd) == ["Bash(git merge:*)", "Bash(git push:*)"]

    def test_absent_settings_file_is_empty_not_an_error(self, tmp_path):
        (tmp_path / "bare").mkdir()
        assert fleet._worktree_deny_rules(tmp_path / "bare") == []

    def test_absent_directory_is_empty_not_an_error(self, tmp_path):
        assert fleet._worktree_deny_rules(tmp_path / "nope" / "nowhere") == []

    def test_unparseable_json_is_empty_not_an_error(self, tmp_path):
        cwd = tmp_path / "wt"
        (cwd / ".claude").mkdir(parents=True)
        (cwd / ".claude" / "settings.local.json").write_text("{not json", encoding="utf-8")
        assert fleet._worktree_deny_rules(cwd) == []

    @pytest.mark.parametrize("payload", [
        "[]",                                        # top level is not an object
        '{"permissions": []}',                       # permissions is not an object
        '{"permissions": {"deny": "Bash(x:*)"}}',    # deny is a bare string
        '{"permissions": {"allow": ["Bash(x:*)"]}}',  # no deny key at all
        "{}",
    ])
    def test_every_wrong_shape_degrades_to_empty(self, tmp_path, payload):
        cwd = tmp_path / "wt"
        (cwd / ".claude").mkdir(parents=True)
        (cwd / ".claude" / "settings.local.json").write_text(payload, encoding="utf-8")
        assert fleet._worktree_deny_rules(cwd) == []

    def test_non_string_entries_are_dropped_not_rendered(self, tmp_path):
        """A bare string in a list position would char-spread through
        `", ".join`; a dict would raise inside it."""
        cwd = tmp_path / "wt"
        (cwd / ".claude").mkdir(parents=True)
        (cwd / ".claude" / "settings.local.json").write_text(
            json.dumps({"permissions": {"deny": ["Bash(git merge:*)", 7, None, {"a": 1}]}}),
            encoding="utf-8")
        assert fleet._worktree_deny_rules(cwd) == ["Bash(git merge:*)"]

    def test_a_stall_with_no_readable_deny_rule_does_not_claim_one(self, home, tmp_path):
        """The line must not assert a cause it did not verify: a prompt with no
        local deny rule is a DIFFERENT bug (inherited settings, or the mode), and
        sending the operator to an empty file burns the one read they were going
        to do."""
        cwd = _worktree(tmp_path / "wt")   # allow-only, no deny rules
        stall = fleet._permission_stalls(_record(cwd), [_roster_entry()], now=NOW)[0]
        line = fleet._permission_stall_line(*stall)
        assert "no deny rules readable" in line
        assert "inherited settings file" in line


# ---------------------------------------------------------------------------
# 6. Dispatch time: name the denials while the dispatcher is still looking.
# ---------------------------------------------------------------------------

class TestSpawnNamesTheWorktreesDenials:
    """The supervisor's own error was copying a REVIEW-class allowlist (which
    correctly denies `git merge`) into a MERGE-class worktree, verifying its
    hash, and concluding it was correct: verifying provenance is not verifying
    fitness. This is the narrow version -- it never guesses which commands the
    brief needs, it only says the denials exist and that a hit HANGS."""

    def test_spawning_into_a_denying_worktree_prints_a_note(
            self, home, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _joining_roster())
        cwd = _worktree(tmp_path / "wt", "Bash(git merge:*)")
        args = fleet.build_parser().parse_args(
            ["spawn", "w1", "--dir", str(cwd), "--task", "merge it", "--mode", "bypass"])
        rc = fleet.cmd_spawn(args, run=_fake_bg_run(), which=lambda _n: "claude.cmd",
                             sleep=lambda _s: None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Bash(git merge:*)" in out
        assert "HANG, not error" in out
        assert "bypass" in out

    def test_spawning_into_a_clean_worktree_prints_nothing_extra(
            self, home, tmp_path, monkeypatch, capsys):
        """Advisory only, and silent when there is nothing to say -- a note on
        every spawn is a note nobody reads."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _joining_roster())
        cwd = tmp_path / "wt"
        cwd.mkdir()
        args = fleet.build_parser().parse_args(
            ["spawn", "w1", "--dir", str(cwd), "--task", "do it", "--mode", "bypass"])
        rc = fleet.cmd_spawn(args, run=_fake_bg_run(), which=lambda _n: "claude.cmd",
                             sleep=lambda _s: None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "note:" not in out

    def test_the_note_never_refuses_the_spawn(self, home, tmp_path, monkeypatch, capsys):
        """A deny list is usually CORRECT. Refusing over one would break every
        legitimately-restricted dispatch."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _joining_roster())
        cwd = _worktree(tmp_path / "wt", "Bash(git push:*)")
        args = fleet.build_parser().parse_args(
            ["spawn", "w1", "--dir", str(cwd), "--task", "review it", "--mode", "bypass"])
        assert fleet.cmd_spawn(args, run=_fake_bg_run(), which=lambda _n: "claude.cmd",
                               sleep=lambda _s: None) == 0
        capsys.readouterr()
        assert "w1" in fleet.load_registry()["workers"]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_run(roster):
    """A `subprocess.run` stub that answers `claude agents --json --all` with
    `roster` and everything else with a failure -- the roster fetch is what is
    under test here, not `claude --version` or the hook smokes."""
    def run(argv, **kwargs):
        argv = list(argv)
        if "agents" in argv and "--all" in argv:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(roster),
                                         stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")
    return run


def _fake_bg_run(stdout="backgrounded · aaaabbbb · fleet|w1|t\n"):
    def run(argv, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run


def _joining_roster(sid=SID):
    """Call-count-aware roster: the 1st fetch (dispatch_bg's pre-dispatch
    snapshot) says the session does not exist yet, the 2nd+ (the join poll) says
    it does -- how the real daemon mints a session after `--bg` returns."""
    state = {"n": 0}

    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [_roster_entry(sid=sid, state="working", status="busy",
                                    waiting_for=None, name="fleet|w1|t")]
    return fetch
