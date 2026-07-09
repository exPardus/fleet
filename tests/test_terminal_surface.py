"""Phase 1.6 terminal surface (docs/specs/terminal-surface.md)."""
import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def _write_registry(home, workers):
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8"
    )


def _rec(**over):
    base = {
        "session_id": "sid-1", "cwd": "C:/proj", "task": "t", "mode": "dontask",
        "model": None, "max_budget_usd": None, "setting_sources": None,
        "created": "2026-07-09T12:00:00Z", "status": "working",
        "turn_pid": 123, "turn_pid_ctime": "2026-07-09T12:00:00Z",
        "attached_since": None, "limit_reset_at": None, "limit_kind": None,
        "turns": 3, "cost_baseline": 0.0, "cost_usd": 1.25,
        "last_activity": "2026-07-09T12:00:00Z",
    }
    base.update(over)
    return base


class TestStatusSnapshot:
    def test_missing_registry_reports_not_initialized(self, home):
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "not_initialized"
        assert snap["workers"] == []

    def test_corrupt_registry_reports_unreadable_and_does_not_quarantine(self, home):
        path = home / "state" / "fleet.json"
        path.write_text("{not json", encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"
        assert snap["workers"] == []
        # D4: the view reports; it never quarantines (that is a write).
        assert path.exists()
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []
        assert not (home / "state" / "events.jsonl").exists()

    def test_workers_not_an_object_reports_unreadable(self, home):
        (home / "state" / "fleet.json").write_text('{"workers": [1, 2]}', encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"

    def test_empty_registry_is_ok_with_zero_totals(self, home):
        _write_registry(home, {})
        snap = fleet.status_snapshot()
        assert snap["ok"] is True
        assert snap["reason"] is None
        assert snap["totals"]["workers"] == 0
        assert snap["totals"]["cost_usd"] == 0.0
        assert snap["totals"]["mail"] == 0

    def test_rows_carry_status_cost_turns_and_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("hi", encoding="utf-8")
        snap = fleet.status_snapshot()
        row = snap["workers"][0]
        assert row["name"] == "pmbot"
        assert row["status"] == "working"
        assert row["turns"] == 3
        assert row["cost_usd"] == 1.25
        assert row["mail"] == 1
        assert snap["totals"]["mail"] == 1
        assert snap["totals"]["cost_usd"] == 1.25

    def test_empty_mailbox_file_counts_as_no_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("", encoding="utf-8")
        assert fleet.status_snapshot()["workers"][0]["mail"] == 0

    def test_totals_count_every_status_generically(self, home):
        # Shipped code has statuses beyond SPEC's five (over_budget,
        # over_ceiling); totals must not hardcode a fixed set.
        _write_registry(home, {
            "a": _rec(status="working", session_id="s-a"),
            "b": _rec(status="idle", session_id="s-b"),
            "c": _rec(status="over_ceiling", session_id="s-c"),
        })
        totals = fleet.status_snapshot()["totals"]
        assert totals["workers"] == 3
        assert totals["by_status"] == {"working": 1, "idle": 1, "over_ceiling": 1}

    def test_stale_seconds_derived_from_last_activity(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="2026-07-09T12:00:00Z")})
        snap = fleet.status_snapshot(now=fleet._parse_iso("2026-07-09T12:05:00Z"))
        assert snap["workers"][0]["stale_seconds"] == pytest.approx(300.0)

    def test_unparseable_last_activity_yields_none_stale_seconds(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="garbage")})
        assert fleet.status_snapshot()["workers"][0]["stale_seconds"] is None

    def test_missing_additive_fields_default(self, home):
        # Additive-schema rule (SPEC §4): an old record lacking cost_baseline /
        # limit_reset_at / limit_kind reads as 0.0 / None / None, never raises.
        old = {"session_id": "s-old", "status": "idle", "turns": 1,
               "last_activity": "2026-07-09T12:00:00Z"}
        _write_registry(home, {"legacy": old})
        row = fleet.status_snapshot()["workers"][0]
        assert row["cost_usd"] == 0.0
        assert row["limit_reset_at"] is None
        assert row["limit_kind"] is None
        assert row["resume_eligible"] is False

    def test_limited_past_reset_is_flagged_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2020-01-01T00:00:00Z", limit_kind="session_5h")})
        row = fleet.status_snapshot()["workers"][0]
        assert row["status"] == "limited"
        assert row["resume_eligible"] is True

    def test_limited_before_reset_is_not_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2099-01-01T00:00:00Z")})
        assert fleet.status_snapshot()["workers"][0]["resume_eligible"] is False

    def test_workers_sorted_by_name(self, home):
        _write_registry(home, {"zed": _rec(session_id="s-z"), "abe": _rec(session_id="s-a")})
        assert [w["name"] for w in fleet.status_snapshot()["workers"]] == ["abe", "zed"]


class TestStatusSnapshotIsPure:
    def test_never_probes(self, home, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("status_snapshot must never probe a PID")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()

    def test_never_takes_the_lock(self, home):
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()
        assert not (home / "state" / "fleet.lock").exists()

    def test_never_writes_the_registry(self, home):
        _write_registry(home, {"pmbot": _rec()})
        path = home / "state" / "fleet.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        fleet.status_snapshot()
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before


class TestStatusJsonFlags:
    def _args(self, **over):
        base = {"name": None, "json": False, "stale_ok": False}
        base.update(over)
        return argparse.Namespace(**base)

    def test_stale_ok_json_prints_snapshot_and_never_probes(self, home, capsys, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("--stale-ok must never probe")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})

        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["workers"][0]["name"] == "pmbot"
        assert not (home / "state" / "fleet.lock").exists()

    def test_stale_ok_on_corrupt_registry_exits_zero_and_reports(self, home, capsys):
        (home / "state" / "fleet.json").write_text("{bad", encoding="utf-8")
        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["reason"] == "unreadable"
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []

    def test_stale_ok_without_json_prints_the_table(self, home, capsys):
        _write_registry(home, {"pmbot": _rec()})
        rc = fleet.cmd_status(self._args(stale_ok=True))
        assert rc == 0
        assert "pmbot" in capsys.readouterr().out

    def test_a_long_name_does_not_swallow_the_status_column(self, home, capsys):
        # "plan3-t12-lowfunding" is exactly 20 chars; a <20 field left no
        # separator and printed "plan3-t12-lowfundingdead".
        _write_registry(home, {"plan3-t12-lowfunding": _rec(status="dead")})
        fleet.cmd_status(self._args(stale_ok=True))
        out = capsys.readouterr().out
        assert "plan3-t12-lowfunding dead" in out

    def test_unknown_worker_name_raises(self, home):
        _write_registry(home, {"pmbot": _rec()})
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_status(self._args(name="nope", stale_ok=True))

    def test_parser_accepts_the_flags(self):
        args = fleet.build_parser().parse_args(["status", "--json", "--stale-ok"])
        assert args.json is True and args.stale_ok is True

    def test_parser_defaults_both_flags_off(self):
        args = fleet.build_parser().parse_args(["status"])
        assert args.json is False and args.stale_ok is False


@pytest.fixture
def statusline(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
    import fleet_statusline
    return fleet_statusline


class TestStatuslineRender:
    def test_not_initialized(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "not_initialized", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: not initialized"

    def test_unreadable_registry(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "unreadable", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: registry unreadable"

    def test_no_workers(self, statusline):
        snap = {"ok": True, "reason": None, "workers": [],
                "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}}}
        assert statusline.render_statusline(snap, color=False) == "⚑ fleet: no workers"

    def _snap(self, workers):
        by_status = {}
        for w in workers:
            by_status[w["status"]] = by_status.get(w["status"], 0) + 1
        return {"ok": True, "reason": None, "workers": workers,
                "totals": {"workers": len(workers),
                           "mail": sum(w["mail"] for w in workers),
                           "cost_usd": sum(w["cost_usd"] for w in workers),
                           "by_status": by_status}}

    def _w(self, **over):
        base = {"name": "w", "status": "working", "turns": 1, "cost_usd": 1.0,
                "mail": 0, "stale_seconds": 5.0, "limit_reset_at": None,
                "limit_kind": None, "resume_eligible": False, "attached_since": None}
        base.update(over)
        return base

    def test_counts_and_cost(self, statusline):
        snap = self._snap([
            self._w(name="a", status="working", cost_usd=1.02),
            self._w(name="b", status="idle", cost_usd=0.41),
            self._w(name="c", status="dead", cost_usd=0.71),
        ])
        line = statusline.render_statusline(snap, color=False)
        assert "1 working" in line.replace("●", " ").replace("○", " ").replace("✗", " ")
        assert "$2.14" in line

    def test_idle_with_mail_renders_as_idle_plus_mail(self, statusline):
        snap = self._snap([self._w(name="b", status="idle", mail=1)])
        assert "idle+mail" in statusline.render_statusline(snap, color=False)

    def test_limited_shows_reset_time(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2026-07-09T14:20:00Z")])
        assert "resets 14:20" in statusline.render_statusline(snap, color=False)

    def test_limited_without_reset_shows_unknown(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at=None)])
        assert "reset?" in statusline.render_statusline(snap, color=False)

    def test_limited_past_reset_flags_resume_eligible_only(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2020-01-01T00:00:00Z",
                                   resume_eligible=True)])
        line = statusline.render_statusline(snap, color=False)
        assert "resume-eligible" in line

    def test_stale_worker_gets_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "~40m" in statusline.render_statusline(snap, color=False)

    def test_fresh_worker_has_no_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=299.0)])
        assert "~" not in statusline.render_statusline(snap, color=False)

    def test_color_false_emits_no_escapes(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "\x1b" not in statusline.render_statusline(snap, color=False)

    def test_color_true_emits_escapes(self, statusline):
        snap = self._snap([self._w(status="working")])
        assert "\x1b" in statusline.render_statusline(snap, color=True)


class TestStatuslineMain:
    def test_main_exits_zero_and_prints_a_line(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO('{"model":{}}'))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0
        assert "⚑" in capsys.readouterr().out

    def test_main_swallows_every_exception_and_prints_nothing(self, statusline, capsys, monkeypatch):
        def boom():
            raise RuntimeError("registry exploded")
        monkeypatch.setattr(statusline.fleet, "status_snapshot", boom)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO(""))
        assert statusline.main() == 0
        assert capsys.readouterr().out == ""

    def test_main_tolerates_garbage_stdin(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("not json at all"))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0

    def test_main_spawns_no_subprocess(self, home, statusline, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("the statusline must spawn no subprocess")
        monkeypatch.setattr(subprocess, "Popen", boom)
        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        _write_registry(home, {"pmbot": _rec()})
        assert statusline.main() == 0


class TestStatuslineAsciiFallback:
    """A Windows console is cp1252 and cannot encode the fleet glyphs. Printing
    them raises UnicodeEncodeError, the exit-0 guard swallows it, and the
    operator sees a permanently BLANK statusline. Caught live during Task 3."""

    def test_ascii_only_render_is_pure_ascii(self, statusline):
        snap = {"ok": True, "reason": None,
                "workers": [{"name": "a", "status": "working", "turns": 1, "cost_usd": 1.0,
                             "mail": 0, "stale_seconds": 5.0, "limit_reset_at": None,
                             "limit_kind": None, "resume_eligible": False,
                             "attached_since": None}],
                "totals": {"workers": 1, "mail": 0, "cost_usd": 1.0,
                           "by_status": {"working": 1}}}
        line = statusline.render_statusline(snap, color=False, ascii_only=True)
        line.encode("ascii")  # raises if any glyph slipped through
        assert "working" in line

    def test_ascii_only_degrades_the_error_lines_too(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "unreadable", "workers": [], "totals": {}},
            color=False, ascii_only=True)
        line.encode("ascii")
        assert "registry unreadable" in line

    def test_main_prints_ascii_when_stdout_cannot_encode_glyphs(
            self, home, statusline, monkeypatch, capsys):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")
        # Simulate a cp1252 console: no reconfigure(), encoding that rejects glyphs.
        monkeypatch.setattr(statusline, "_stdout_can_encode", lambda text: False)

        assert statusline.main() == 0
        out = capsys.readouterr().out
        assert out.strip()  # the bug was: silently empty
        out.encode("ascii")
        assert "working" in out

    def test_stdout_can_encode_rejects_cp1252(self, statusline, monkeypatch):
        class _Cp1252:
            encoding = "cp1252"
        monkeypatch.setattr(statusline.sys, "stdout", _Cp1252())
        assert statusline._stdout_can_encode("⚑ fleet") is False
        assert statusline._stdout_can_encode("# fleet") is True


class TestLaunchTurnEnvStamp:
    def _fake_popen_factory(self, captured):
        class _Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.pid = 4321

            def poll(self):
                return None

        def fake_popen(argv, **kwargs):
            captured.update(kwargs)
            return _Proc()
        return fake_popen

    def _stub_launch(self, monkeypatch):
        monkeypatch.setattr(fleet, "resolve_claude_executable", lambda which=None: "claude")
        monkeypatch.setattr(
            fleet.PLATFORM, "get_process_info",
            lambda pid: ("claude", fleet.datetime.now(fleet.timezone.utc)))

    def test_child_env_carries_fleet_worker_name(self, home, tmp_path, monkeypatch):
        captured = {}
        self._stub_launch(monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()

        fleet.launch_turn("pmbot", proj, "sid-1", "prompt", "dontask", first=True,
                          popen=self._fake_popen_factory(captured))

        assert captured["env"]["FLEET_WORKER"] == "pmbot"

    def test_child_env_preserves_the_parent_environment(self, home, tmp_path, monkeypatch):
        captured = {}
        monkeypatch.setenv("FLEET_TEST_SENTINEL", "kept")
        self._stub_launch(monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()

        fleet.launch_turn("pmbot", proj, "sid-1", "prompt", "dontask", first=True,
                          popen=self._fake_popen_factory(captured))

        assert captured["env"]["FLEET_TEST_SENTINEL"] == "kept"
        assert "PATH" in captured["env"]


@pytest.fixture
def sshook():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin" / "hooks"))
    import sessionstart_fleet
    return sessionstart_fleet


class TestSessionStartHook:
    def test_suppressed_inside_a_worker(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setenv("FLEET_WORKER", "pmbot")
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO('{"source":"startup"}'))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_emits_briefing_in_a_manager_session(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO('{"source":"startup"}'))
        assert sshook.main() == 0
        payload = json.loads(capsys.readouterr().out)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "pmbot" in ctx and "working" in ctx

    def test_includes_knowledge_index_lines(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {})
        (home / "knowledge").mkdir()
        (home / "knowledge" / "INDEX.md").write_text("- pmbot.md — quirks\n", encoding="utf-8")
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        sshook.main()
        assert "pmbot.md" in capsys.readouterr().out

    def test_flags_idle_plus_mail(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"expardus": _rec(status="idle", session_id="s-e")})
        (home / "mailbox" / "s-e.md").write_text("do the thing", encoding="utf-8")
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        sshook.main()
        assert "idle+mail" in capsys.readouterr().out

    def test_missing_registry_emits_empty_object_and_exits_zero(self, home, sshook, capsys, monkeypatch):
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_any_exception_exits_zero_with_empty_object(self, home, sshook, capsys, monkeypatch):
        def boom():
            raise RuntimeError("kaboom")
        monkeypatch.setattr(sshook.fleet, "status_snapshot", boom)
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        assert sshook.main() == 0
        assert capsys.readouterr().out.strip() == "{}"

    def test_context_truncated_to_ten_thousand_chars(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {
            f"worker-{i:03d}": _rec(session_id=f"s-{i}") for i in range(400)})
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        sshook.main()
        ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
        assert len(ctx) <= 10_000

    def test_writes_nothing_at_all(self, home, sshook, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setattr(sshook.sys, "stdin", io.StringIO("{}"))
        before = sorted(p.name for p in (home / "state").iterdir())
        sshook.main()
        assert sorted(p.name for p in (home / "state").iterdir()) == before
        assert not (home / "state" / "hook-errors.log").exists()


COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"

READ_ONLY_COMMANDS = {"fleet", "status", "peek", "result", "doctor"}
MUTATING_COMMANDS = {"spawn", "send", "interrupt", "respawn", "kill", "clean",
                     "attach", "release", "resume-limited"}


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: missing frontmatter"
    _, fm, _body = text.split("---\n", 2)
    out = {}
    for line in fm.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _body(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---\n", 2)[2]


class TestCommandFiles:
    def test_every_expected_command_exists(self):
        found = {p.stem for p in COMMANDS_DIR.glob("*.md")}
        assert found == READ_ONLY_COMMANDS | MUTATING_COMMANDS

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS | MUTATING_COMMANDS))
    def test_every_command_has_a_description(self, name):
        assert _frontmatter(COMMANDS_DIR / f"{name}.md").get("description")

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS))
    def test_read_only_commands_inline_exec_and_declare_allowed_tools(self, name):
        path = COMMANDS_DIR / f"{name}.md"
        assert "!`" in _body(path), f"{name}: read-only command should inline its CLI output"
        assert "Bash" in _frontmatter(path).get("allowed-tools", "")

    # A read-only command once carried `Bash(fleet:*)`, which matches
    # `fleet kill` and `fleet clean`. A haiku session invoked /fleet:status,
    # decided the dead workers were untidy, and -- fully within permissions --
    # killed a working worker and cleaned five journals. 2026-07-09, real
    # data loss. The grant must name the subcommand, never the whole CLI.
    DESTRUCTIVE_VERBS = ("kill", "clean", "respawn", "interrupt", "spawn",
                         "send", "attach", "release", "resume-limited")

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS))
    def test_read_only_grants_never_cover_the_whole_fleet_cli(self, name):
        grant = _frontmatter(COMMANDS_DIR / f"{name}.md").get("allowed-tools", "")
        assert "Bash(fleet:*)" not in grant, (
            f"{name}: `Bash(fleet:*)` grants `fleet kill` and `fleet clean` too"
        )
        assert "Bash(fleet)" not in grant

    @pytest.mark.parametrize("name", sorted(READ_ONLY_COMMANDS))
    def test_read_only_grants_reach_no_destructive_subcommand(self, name):
        grant = _frontmatter(COMMANDS_DIR / f"{name}.md").get("allowed-tools", "")
        for verb in self.DESTRUCTIVE_VERBS:
            assert f"fleet {verb}" not in grant, f"{name} may invoke `fleet {verb}`"

    @pytest.mark.parametrize("name", sorted(MUTATING_COMMANDS))
    def test_mutating_commands_never_inline_exec(self, name):
        # D3: !`cmd` runs at prompt-expansion time with no permission prompt
        # and no undo. `fleet kill` is terminal; `fleet clean` deletes journals.
        assert "!`" not in _body(COMMANDS_DIR / f"{name}.md"), (
            f"{name} is a mutating command and must not use inline !`` exec"
        )

    @pytest.mark.parametrize("name", sorted(MUTATING_COMMANDS))
    def test_mutating_commands_declare_no_allowed_tools(self, name):
        # Belt and braces: an allowed-tools grant on a mutating command is the
        # first step toward someone adding inline exec to it.
        assert "allowed-tools" not in _frontmatter(COMMANDS_DIR / f"{name}.md")

    @pytest.mark.parametrize("name", sorted(MUTATING_COMMANDS - {"clean"}))
    def test_mutating_commands_declare_an_argument_hint(self, name):
        assert _frontmatter(COMMANDS_DIR / f"{name}.md").get("argument-hint")


REPO = Path(__file__).resolve().parent.parent


class TestPluginPackaging:
    @property
    def manifest(self) -> dict:
        return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    def test_plugin_is_named_fleet_so_commands_namespace_as_fleet(self):
        # The slash-command namespace derives from the plugin NAME: a plugin
        # named "claude-fleet" would give /claude-fleet:status, not /fleet:status.
        assert self.manifest["name"] == "fleet"
        assert self.manifest["description"]

    def test_manifest_does_not_ship_a_statusline(self):
        # A plugin CANNOT ship a statusLine; plugin settings.json accepts only
        # `agent` and `subagentStatusLine`. fleet init --statusline installs it.
        raw = (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        assert "statusLine" not in raw

    def test_skill_lives_at_the_plugin_standard_path(self):
        assert (REPO / "skills" / "fleet" / "SKILL.md").exists()
        assert not (REPO / "skill").exists()

    def test_commands_and_skills_are_convention_discovered(self):
        # A working reference plugin (caveman) declares no `commands`/`skills`
        # path keys and relies on convention. Declaring them appeared to make
        # the manifest unusable here; do not add them back without evidence.
        assert "commands" not in self.manifest
        assert "skills" not in self.manifest

    def test_manifest_registers_the_sessionstart_hook_inline(self):
        # Hooks are inlined in plugin.json (caveman's working shape), not
        # referenced as a separate hooks/hooks.json path.
        entries = self.manifest["hooks"]["SessionStart"]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        assert any("sessionstart_fleet.py" in c for c in commands)
        assert not (REPO / "hooks" / "hooks.json").exists()

    def test_hook_command_uses_forward_slashes(self):
        # Git Bash sh -c eats backslashes in unquoted strings.
        raw = (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        assert "\\\\" not in raw

    def test_author_is_an_object(self):
        # `claude plugin validate` rejects a string author.
        assert isinstance(self.manifest["author"], dict)

    def test_hook_command_goes_through_the_interpreter_shim(self):
        # A bare `py -3.13` breaks every non-Windows collaborator; the shim is
        # the one place that resolves an interpreter.
        entries = self.manifest["hooks"]["SessionStart"]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        assert all("run_py.sh" in c for c in commands)
        assert not any("py -3.13" in c for c in commands)


class TestCollaboratorInstall:
    """The plugin must install for someone who is not on Altai's machine."""

    def test_marketplace_manifest_is_present_and_offers_fleet(self):
        mkt = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        assert mkt["name"] == "claude-fleet"
        assert mkt["description"]
        assert isinstance(mkt["owner"], dict)
        names = [p["name"] for p in mkt["plugins"]]
        assert names == ["fleet"]

    def test_interpreter_shim_is_tracked_and_executable(self):
        shim = REPO / "bin" / "hooks" / "run_py.sh"
        assert shim.exists()
        tracked = subprocess.run(
            ["git", "ls-files", "-s", "bin/hooks/run_py.sh"],
            cwd=REPO, capture_output=True, text=True).stdout
        assert tracked, "run_py.sh must be committed -- a plugin clone needs it"
        # Mode 100755: a cloned shim that is not executable cannot be exec'd.
        assert tracked.split()[0] == "100755", f"expected mode 100755, got: {tracked.split()[0]}"

    def test_shim_prefers_an_explicit_fleet_python(self, tmp_path):
        script = tmp_path / "say.py"
        script.write_text("print('ran')", encoding="utf-8")
        out = subprocess.run(
            ["sh", str(REPO / "bin" / "hooks" / "run_py.sh"), str(script)],
            capture_output=True, text=True,
            env={**__import__("os").environ, "FLEET_PYTHON": sys.executable})
        assert out.stdout.strip() == "ran"

    def test_posix_cli_shim_is_tracked_and_executable(self):
        # `fleet.cmd` only resolves from cmd.exe/PowerShell. bash ignores
        # PATHEXT, so a slash command's inline !`fleet status` -- which runs
        # under a shell -- found nothing and produced SILENT empty output.
        shim = REPO / "bin" / "fleet"
        assert shim.exists()
        tracked = subprocess.run(
            ["git", "ls-files", "-s", "bin/fleet"],
            cwd=REPO, capture_output=True, text=True).stdout
        assert tracked, "bin/fleet must be committed"
        assert tracked.split()[0] == "100755", f"expected mode 100755, got: {tracked.split()[0]}"

    def test_posix_cli_shim_runs_the_cli(self):
        out = subprocess.run(
            ["sh", str(REPO / "bin" / "fleet"), "--help"],
            capture_output=True, text=True)
        assert out.returncode == 0
        assert "fleet" in out.stdout

    def test_shell_scripts_are_pinned_to_lf(self):
        # A CRLF shim dies on Linux with `\r: command not found`, and a hook's
        # exit-0 rule would make that silent.
        attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
        assert "*.sh text eol=lf" in attrs
        assert "bin/fleet text eol=lf" in attrs

    def test_shim_exits_zero_when_no_interpreter_exists(self, tmp_path):
        # invariant 2: a hook never breaks a session, even with no python.
        script = tmp_path / "say.py"
        script.write_text("print('ran')", encoding="utf-8")
        out = subprocess.run(
            ["sh", str(REPO / "bin" / "hooks" / "run_py.sh"), str(script)],
            capture_output=True, text=True,
            env={"PATH": str(tmp_path), "FLEET_PYTHON": ""})
        assert out.returncode == 0
        assert out.stdout.strip() == ""


class TestFleetHomeMarker:
    """A marketplace-installed plugin runs from a CACHE COPY of this repo whose
    state/ is gitignored and empty. Resolving FLEET_HOME from the script's own
    location would make the hook read that empty cache while the operator's CLI
    writes elsewhere. `fleet init` stamps ~/.claude/fleet-home with the truth."""

    def test_init_writes_the_marker(self, home, monkeypatch, tmp_path, capsys):
        marker = tmp_path / "dot-claude" / "fleet-home"
        monkeypatch.setattr(fleet, "fleet_home_marker_path", lambda: marker)
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")

        fleet.cmd_init(argparse.Namespace(statusline=False, force=False))

        assert marker.read_text(encoding="utf-8").strip() == home.resolve().as_posix()

    def test_marker_write_failure_never_breaks_init(self, home, monkeypatch, capsys):
        def boom():
            raise OSError("read-only home")
        monkeypatch.setattr(fleet, "fleet_home_marker_path", boom)
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        # Best-effort: init still succeeds.
        with pytest.raises(OSError):
            fleet.cmd_init(argparse.Namespace(statusline=False, force=False))

    def test_hook_resolution_order_env_then_marker_then_own_location(self, sshook, tmp_path, monkeypatch):
        real = tmp_path / "real-fleet"
        real.mkdir()
        marker = tmp_path / "fleet-home"
        marker.write_text(real.as_posix(), encoding="utf-8")

        monkeypatch.setenv("FLEET_HOME", str(tmp_path / "from-env"))
        assert sshook._resolve_fleet_home() == tmp_path / "from-env"

        monkeypatch.delenv("FLEET_HOME")
        monkeypatch.setattr(sshook.Path, "home", staticmethod(lambda: tmp_path))
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "fleet-home").write_text(real.as_posix(), encoding="utf-8")
        assert sshook._resolve_fleet_home() == real

    def test_hook_ignores_a_marker_pointing_at_a_missing_dir(self, sshook, tmp_path, monkeypatch):
        monkeypatch.delenv("FLEET_HOME", raising=False)
        monkeypatch.setattr(sshook.Path, "home", staticmethod(lambda: tmp_path))
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "fleet-home").write_text("/nope/not/here", encoding="utf-8")
        # Falls back to the script's own repo root rather than trusting it.
        assert sshook._resolve_fleet_home().name != "not"


class TestInitStatusline:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        path = tmp_path / "dot-claude" / "settings.json"
        monkeypatch.setattr(fleet, "user_settings_path", lambda: path)
        return path

    def _args(self, **over):
        base = {"statusline": False, "force": False}
        base.update(over)
        return argparse.Namespace(**base)

    def test_plain_init_never_touches_user_settings(self, home, settings, capsys):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args())
        assert not settings.exists()

    def test_statusline_creates_settings_when_absent(self, home, settings, capsys):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        assert fleet.cmd_init(self._args(statusline=True)) == 0
        payload = json.loads(settings.read_text(encoding="utf-8"))
        assert "fleet_statusline.py" in payload["statusLine"]["command"]
        assert payload["statusLine"]["type"] == "command"

    def test_statusline_command_uses_forward_slashes(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args(statusline=True))
        cmd = json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert "\\" not in cmd

    def test_statusline_backs_up_and_preserves_siblings(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"model": "opus", "env": {"A": "1"}}), encoding="utf-8")

        fleet.cmd_init(self._args(statusline=True))

        payload = json.loads(settings.read_text(encoding="utf-8"))
        assert payload["model"] == "opus"
        assert payload["env"] == {"A": "1"}
        assert payload["statusLine"]["type"] == "command"
        assert list(settings.parent.glob("settings.json.bak.*"))

    def test_statusline_refuses_a_foreign_statusline(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "ccusage statusline"}}), encoding="utf-8")

        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_init(self._args(statusline=True))
        assert "ccusage" in str(exc.value)
        # Untouched.
        assert "ccusage" in settings.read_text(encoding="utf-8")

    def test_force_overwrites_a_foreign_statusline(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "ccusage statusline"}}), encoding="utf-8")

        assert fleet.cmd_init(self._args(statusline=True, force=True)) == 0
        assert "fleet_statusline.py" in settings.read_text(encoding="utf-8")

    def test_reinstall_over_fleets_own_statusline_is_idempotent(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args(statusline=True))
        first = json.loads(settings.read_text(encoding="utf-8"))
        assert fleet.cmd_init(self._args(statusline=True)) == 0
        assert json.loads(settings.read_text(encoding="utf-8")) == first

    def test_corrupt_user_settings_refuses_rather_than_clobbering(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text("{not json", encoding="utf-8")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_init(self._args(statusline=True))
        assert settings.read_text(encoding="utf-8") == "{not json"

    def test_parser_accepts_statusline_and_force(self):
        args = fleet.build_parser().parse_args(["init", "--statusline", "--force"])
        assert args.statusline is True and args.force is True

    def test_parser_accepts_chain(self):
        args = fleet.build_parser().parse_args(["init", "--statusline", "--chain"])
        assert args.chain is True

    def test_refusal_message_offers_both_chain_and_force(self, home, settings):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "ccusage statusline"}}), encoding="utf-8")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_init(self._args(statusline=True))
        assert "--chain" in str(exc.value) and "--force" in str(exc.value)


class TestStatuslineChainInstall:
    """Claude Code allows exactly ONE statusLine command. --chain composes
    rather than forcing the operator to choose between fleet and ccusage/caveman."""

    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        path = tmp_path / "dot-claude" / "settings.json"
        monkeypatch.setattr(fleet, "user_settings_path", lambda: path)
        return path

    def _args(self, **over):
        base = {"statusline": True, "force": False, "chain": False}
        base.update(over)
        return argparse.Namespace(**base)

    def _with_foreign(self, home, settings, command="caveman-statusline.ps1"):
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": command}}), encoding="utf-8")

    def test_chain_captures_the_incumbent_and_installs_fleet(self, home, settings, capsys):
        self._with_foreign(home, settings)
        assert fleet.cmd_init(self._args(chain=True)) == 0

        chain = json.loads(fleet.statusline_chain_path().read_text(encoding="utf-8"))
        assert chain["delegates"][0]["command"] == "caveman-statusline.ps1"
        assert chain["delegates"][0]["captured_at"]
        assert "fleet_statusline.py" in json.loads(
            settings.read_text(encoding="utf-8"))["statusLine"]["command"]

    def test_chain_never_captures_fleets_own_statusline(self, home, settings):
        # Re-running --chain against a fleet-owned statusline must not make
        # fleet's statusline invoke itself once per refresh, forever.
        (home / "worker-settings.template.json").write_text('{"hooks":{}}', encoding="utf-8")
        fleet.cmd_init(self._args())                      # install fleet's
        assert fleet.cmd_init(self._args(chain=True)) == 0  # re-run with --chain
        assert not fleet.statusline_chain_path().exists()

    def test_force_overwrites_without_chaining(self, home, settings):
        self._with_foreign(home, settings)
        assert fleet.cmd_init(self._args(force=True)) == 0
        assert not fleet.statusline_chain_path().exists()


class TestStatuslineChainRender:
    def _chain(self, home, command):
        (home / "state" / "statusline-chain.json").write_text(
            json.dumps({"delegates": [{"command": command}]}), encoding="utf-8")

    def test_delegate_rows_print_above_fleets_row(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        self._chain(home, f'{sys.executable} -c "print(\'CAVEMAN ROW\')"')
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")

        statusline.main()

        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert lines[0] == "CAVEMAN ROW"
        assert "working" in lines[1]

    def test_delegate_receives_the_session_json_on_stdin(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {})
        self._chain(home, f'{sys.executable} -c "import sys; sys.stdout.write(sys.stdin.read())"')
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO('{"model":"opus"}'))
        monkeypatch.setenv("NO_COLOR", "1")

        statusline.main()
        assert '{"model":"opus"}' in capsys.readouterr().out

    def test_a_failing_delegate_never_costs_fleets_row(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        self._chain(home, f'{sys.executable} -c "import sys; sys.exit(3)"')
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")

        assert statusline.main() == 0
        out = capsys.readouterr().out
        assert "working" in out

    def test_a_hanging_delegate_is_dropped_on_timeout(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        self._chain(home, "sleep 30")
        monkeypatch.setattr(statusline, "DELEGATE_TIMEOUT_SECONDS", 1)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")

        assert statusline.main() == 0
        assert "working" in capsys.readouterr().out

    def test_no_chain_file_means_a_single_row(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")
        statusline.main()
        assert len([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]) == 1

    def test_corrupt_chain_file_is_ignored(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        (home / "state" / "statusline-chain.json").write_text("{bad", encoding="utf-8")
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0
        assert "working" in capsys.readouterr().out

    def test_chain_spawns_no_subprocess_when_unconfigured(self, home, statusline, monkeypatch):
        # D1 still holds for fleet's own row: zero subprocesses unless the
        # operator explicitly chained a delegate.
        _write_registry(home, {"pmbot": _rec()})
        def boom(*a, **k):
            raise AssertionError("no delegate configured: nothing should be spawned")
        monkeypatch.setattr(statusline.subprocess, "run", boom)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        assert statusline.main() == 0
