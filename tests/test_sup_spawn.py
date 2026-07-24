"""three-tier §10.1 `sup-spawn` -- the gen-0 supervisor dispatch verb.

Built from the ratified decision record docs/proposals/sup-spawn-choreography.md
(operator rulings 1(i-iii) + 2 applied 2026-07-24). Test list = design §8
(16 red-first tests, floor not ceiling) plus the win32 task-file mapping the
design's G8 assumption missed (`|` is invalid in Windows filenames).

Fault-injection targets (mutate -> confirm red -> restore, tt-build convention):
  FI-1 dispatch_bg name-guard widening   (TestDispatchBgSupShapedGuard)
  FI-2 DOA rollback `session_id is None` (TestSupSpawnDOARollback)
  FI-3 `_supervisor_gate("sup-spawn")`   (TestSupSpawnGateWiring)
  FI-4 resolver never guesses by shape   (TestSupervisorLogicalResolution)
  FI-5 bypass-ack WARN (ruling 2)        (TestBypassAckWarn)
"""
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
SID = "aaaabbbb-1111-2222-3333-444455556666"
HOLDER_SID = "99998888-7777-6666-5555-444433332222"

SUP_NAME_RE = re.compile(r"^sup\|inc-\d{8}T\d{6}Z-[0-9a-f]{4}\|boot$")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with state/ and a rendered instance settings file."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="sup|inc|boot", state="working",
                      status="busy", pid=1234, kind="background"):
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_run_factory(stdout="backgrounded · aaaabbbb · sup\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


def _roster_with(sid=SID, **kw):
    """1st call (pre-dispatch snapshot): absent; 2nd+ (join poll): present."""
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [make_roster_entry(sid, **kw)]
    return fetch


class _FakeClock:
    def __init__(self, start=0.0):
        self.t = start
    def __call__(self):
        return self.t
    def advance(self, dt):
        self.t += dt


def _sup_args(**kw):
    base = dict(task="run the campaign", model=None, permission_mode=None, nonce=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _happy_spawn(native_home, monkeypatch, args=None, calls=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
    rc = fleet.cmd_sup_spawn(args or _sup_args(),
                             run=_fake_run_factory(calls=calls),
                             which=lambda _: "claude", sleep=lambda s: None)
    return rc


def _the_one_worker(expect_shape=True):
    workers = fleet.load_registry()["workers"]
    assert len(workers) == 1, workers
    name = next(iter(workers))
    if expect_shape:
        assert SUP_NAME_RE.match(name), name
    return name, workers[name]


def _held_claim(sid=HOLDER_SID, **extra):
    claim = {"incarnation_id": "inc-held", "session_id": sid,
             "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
             "claimed_via": "fresh", "nonce_hash": "deadbeef", "nonce_seq": 1,
             "lineage_id": "lin-x"}
    claim.update(extra)
    (fleet.FLEET_HOME / "supervisor").mkdir(exist_ok=True)
    fleet.write_incarnation(claim)
    return claim


# ---------------------------------------------------------------------------
# win32 task-file mapping (build finding: `|` is invalid in Windows filenames;
# the design's G8 route writes task_file_path(name) -- so the helper maps it).
# ---------------------------------------------------------------------------
class TestTaskFilePathMapping:
    def test_pipe_name_maps_to_fs_safe_stem(self, native_home):
        p = fleet.task_file_path("sup|inc-1|boot")
        assert p.name == "sup~inc-1~boot.md"
        assert "|" not in p.name

    def test_plain_names_unchanged(self, native_home):
        assert fleet.task_file_path("w1").name == "w1.md"

    def test_mapped_stem_outside_ordinary_name_charset(self):
        # `~` is not in NAME_RE's [a-z0-9-]+, so no spawnable worker's task
        # file can collide with a mapped supervisor-body task file.
        assert not fleet.NAME_RE.match("sup~inc-1~boot")


# ---------------------------------------------------------------------------
# Design §8-2: dispatch_bg guard widening (the one enabling change). FI-1.
# ---------------------------------------------------------------------------
class TestDispatchBgSupShapedGuard:
    def test_accepts_supervisor_shaped_name(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        out = fleet.dispatch_bg("sup|inc-1|boot", str(native_home), "BODY", "bypass",
                                run=_fake_run_factory(), which=lambda _: "claude",
                                sleep=lambda s: None)
        assert out["session_id"] == SID
        task = fleet.task_file_path("sup|inc-1|boot")
        assert task.exists() and task.read_text(encoding="utf-8") == "BODY"

    @pytest.mark.parametrize("bad", [
        "a|b",              # arbitrary pipe junk
        "sup|x|",           # empty role
        "sup||boot",        # empty inc
        "sup|x|boot|z",     # third separator
        "sup|x|Boot",       # role not [a-z][a-z0-9-]*
        "aaaabbbb-1111-2222-3333-444455556666",  # sid-shaped stays refused
    ])
    def test_still_refuses_non_family_names(self, native_home, bad):
        with pytest.raises(fleet.NativeDispatchError, match="invalid worker name"):
            fleet.dispatch_bg(bad, str(native_home), "b", "bypass",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=lambda s: None)

    def test_supervisor_shape_unforgeable_via_ordinary_spawn(self):
        # NAME_RE forbids `|`, so `fleet spawn` can never name a worker into
        # the widened family (the E(2) grounding the widening rests on).
        with pytest.raises(ValueError):
            fleet.validate_name("sup|inc-1|boot")


# ---------------------------------------------------------------------------
# Design §8-3: rendered-name pin -- the `-n` argv value is the BARE pipe name
# (no render_native_name cat|name|hint corruption).
# ---------------------------------------------------------------------------
class TestRenderedNamePin:
    def test_dash_n_is_bare_name_for_supervisor_shaped(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        calls = []
        fleet.dispatch_bg("sup|inc-1|boot", str(native_home), "b", "bypass",
                          category=None, hint="",
                          run=_fake_run_factory(calls=calls),
                          which=lambda _: "claude", sleep=lambda s: None)
        argv = calls[0][0]
        rendered = argv[argv.index("-n") + 1]
        assert rendered == "sup|inc-1|boot"

    def test_worker_rendering_unchanged(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        calls = []
        fleet.dispatch_bg("w1", str(native_home), "b", "accept",
                          category=None, hint="do it",
                          run=_fake_run_factory(calls=calls),
                          which=lambda _: "claude", sleep=lambda s: None)
        argv = calls[0][0]
        assert argv[argv.index("-n") + 1] == "fleet|w1|do it"

    def test_cmd_sup_spawn_argv_name_is_bare(self, native_home, monkeypatch):
        calls = []
        assert _happy_spawn(native_home, monkeypatch, calls=calls) == 0
        name, _ = _the_one_worker()
        argv = calls[0][0]
        assert argv[argv.index("-n") + 1] == name


# ---------------------------------------------------------------------------
# Design §8-1 / §8-4 / §8-15: the verb -- mint, record fields, event ordering.
# ---------------------------------------------------------------------------
class TestCmdSupSpawn:
    def test_mints_supervisor_shaped_boot_name(self, native_home, monkeypatch):
        assert _happy_spawn(native_home, monkeypatch) == 0
        name, rec = _the_one_worker()
        assert fleet._is_supervisor_shaped(name)
        assert name != fleet.SUPERVISOR_BODY_NAME
        assert fleet.SUPERVISOR_BODY_NAME not in fleet.load_registry()["workers"]
        assert rec["session_id"] == SID and rec["native_short_id"] == "aaaabbbb"
        assert rec["status"] == "working" and rec["turns"] == 1

    def test_record_fields(self, native_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "interface-sid")
        assert _happy_spawn(native_home, monkeypatch) == 0
        _, rec = _the_one_worker()
        assert rec["spawned_by"] == "interface-sid"
        assert rec["spawned_by_lineage"] is None     # no claim held at gen-0
        assert rec["mode"] == "bypass"                # §10.2 earned-privilege
        assert rec["dispatch_kind"] == "bg"
        assert rec["category"] is None
        assert rec["cwd"] == str(native_home)         # forced FLEET_HOME

    def test_dispatch_runs_in_fleet_home(self, native_home, monkeypatch):
        calls = []
        assert _happy_spawn(native_home, monkeypatch, calls=calls) == 0
        assert calls[0][1]["cwd"] == str(native_home)

    def test_mode_override_via_permission_mode(self, native_home, monkeypatch):
        calls = []
        rc = _happy_spawn(native_home, monkeypatch,
                          args=_sup_args(permission_mode="dontask"), calls=calls)
        assert rc == 0
        _, rec = _the_one_worker()
        assert rec["mode"] == "dontask"
        argv = calls[0][0]
        assert "--dangerously-skip-permissions" not in argv
        assert "dontAsk" in argv

    def test_default_mode_argv_is_bypass(self, native_home, monkeypatch):
        calls = []
        assert _happy_spawn(native_home, monkeypatch, calls=calls) == 0
        assert "--dangerously-skip-permissions" in calls[0][0]

    def test_event_ordering_spawned_then_turn_started(self, native_home, monkeypatch):
        assert _happy_spawn(native_home, monkeypatch) == 0
        events_path = native_home / "state" / "events.jsonl"
        kinds = [json.loads(ln)["kind"] for ln in
                 events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert kinds == ["spawned", "turn_started"]

    def test_requires_instance_settings(self, native_home, monkeypatch):
        (native_home / "state" / "worker-settings.json").unlink()
        with pytest.raises(fleet.FleetCliError, match="fleet init"):
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}


# ---------------------------------------------------------------------------
# Design §8-5: --model default matrix (argv pins; resolver itself is pinned
# in tests/test_tier_resolver.py).
# ---------------------------------------------------------------------------
class TestSupSpawnModelDefault:
    def _goals(self, native_home, text):
        supdir = native_home / "supervisor"
        supdir.mkdir(exist_ok=True)
        (supdir / "GOALS.md").write_text(text, encoding="utf-8")

    def test_goals_block_absent_omits_model_flag(self, native_home, monkeypatch):
        calls = []
        assert _happy_spawn(native_home, monkeypatch, calls=calls) == 0
        assert "--model" not in calls[0][0]
        _, rec = _the_one_worker()
        assert rec["model"] is None

    def test_goals_block_present_resolves_supervisor_chain_head(self, native_home, monkeypatch):
        self._goals(native_home,
                    "Bypass acknowledgement (§10.2)\n" + fleet.proposed_goals_tier_block())
        calls = []
        assert _happy_spawn(native_home, monkeypatch, calls=calls) == 0
        argv = calls[0][0]
        assert argv[argv.index("--model") + 1] == "opus"
        _, rec = _the_one_worker()
        assert rec["model"] == "opus"

    def test_explicit_model_overrides_policy(self, native_home, monkeypatch):
        self._goals(native_home,
                    "Bypass acknowledgement (§10.2)\n" + fleet.proposed_goals_tier_block())
        calls = []
        rc = _happy_spawn(native_home, monkeypatch,
                          args=_sup_args(model="tier-x"), calls=calls)
        assert rc == 0
        argv = calls[0][0]
        assert argv[argv.index("--model") + 1] == "tier-x"

    def test_model_line_printed(self, native_home, monkeypatch, capsys):
        assert _happy_spawn(native_home, monkeypatch) == 0
        out = capsys.readouterr().out
        assert "model:" in out and "(claude default)" in out


# ---------------------------------------------------------------------------
# Design §8-6: DOA rollback. FI-2 (`session_id is None` guard).
# ---------------------------------------------------------------------------
class TestSupSpawnDOARollback:
    def test_doa_pops_preclaim_and_appends_spawn_failed(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.FleetCliError, match="native spawn failed"):
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(rc=1),
                                which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}
        events = [json.loads(ln)["kind"] for ln in
                  (native_home / "state" / "events.jsonl")
                  .read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert "spawn_failed" in events

    def test_concurrent_fast_stamp_never_clobbered(self, native_home, monkeypatch):
        """A fast-completion stamp that raced in is not popped by the DOA arm."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        real_dispatch = fleet.dispatch_bg
        def stamping_then_raising(*a, **k):
            # A concurrent actor stamps the pre-claim before the DOA branch runs.
            data = fleet.load_registry()
            name = next(iter(data["workers"]))
            data["workers"][name]["session_id"] = "conc-sid"
            fleet.save_registry(data)
            raise fleet.NativeDispatchError("boom")
        monkeypatch.setattr(fleet, "dispatch_bg", stamping_then_raising)

        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                which=lambda _: "claude", sleep=lambda s: None)
        name, rec = _the_one_worker()
        assert rec["session_id"] == "conc-sid"   # survived; never popped


# ---------------------------------------------------------------------------
# Design §8-7: fast completion before join.
# ---------------------------------------------------------------------------
class TestSupSpawnFastCompletion:
    def test_join_expiry_with_fresh_outcome_commits_idle(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        # The Stop hook's own fallback shape: sid-keyed (name resolution cannot
        # match a session_id=None pre-claim -- and a pipe name is not a valid
        # hook token anyway, so sid-keyed is this body's steady state too).
        fleet.append_outcome(SID, {"ts": fleet.now_iso(), "session_id": SID,
                                   "kind": "result", "result_text": "done"})
        clock = _FakeClock()
        rc = fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                 which=lambda _: "claude",
                                 sleep=lambda s: clock.advance(s), clock=clock)
        assert rc == 0
        name, rec = _the_one_worker()
        assert rec["status"] == "idle" and rec["session_id"] == SID
        assert rec["turns"] == 1
        assert rec["native_short_id"] == "aaaabbbb"   # derived, not captured

    def test_join_expiry_without_outcome_is_doa(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        clock = _FakeClock()
        with pytest.raises(fleet.FleetCliError, match="aaaabbbb"):
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                which=lambda _: "claude",
                                sleep=lambda s: clock.advance(s), clock=clock)
        assert fleet.load_registry()["workers"] == {}


# ---------------------------------------------------------------------------
# Design §8-8: stranded stamp.
# ---------------------------------------------------------------------------
class TestSupSpawnStranded:
    def test_commit_exhaustion_reports_stranded_keeps_preclaim(self, native_home,
                                                               monkeypatch, capsys):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        monkeypatch.setattr(fleet, "_commit_launched_turn",
                            lambda fn, sleep=None: False)
        rc = fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                 which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 1
        name, rec = _the_one_worker()
        assert rec["session_id"] is None          # NOT popped -- live session exists
        err = capsys.readouterr().err
        assert "CRITICAL" in err and SID in err
        events = [json.loads(ln)["kind"] for ln in
                  (native_home / "state" / "events.jsonl")
                  .read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert "turn_commit_failed" in events


# ---------------------------------------------------------------------------
# Design §8-9: first-turn task-file contract (boot ritual, design §4).
# ---------------------------------------------------------------------------
class TestSupSpawnTaskFileContract:
    def _task_text(self, native_home, monkeypatch, **kw):
        assert _happy_spawn(native_home, monkeypatch, **kw) == 0
        name, _ = _the_one_worker()
        return name, fleet.task_file_path(name).read_text(encoding="utf-8")

    def test_boot_first_no_handoff_flags(self, native_home, monkeypatch):
        _, text = self._task_text(native_home, monkeypatch)
        assert "sup-boot" in text
        assert "--handoff" not in text

    def test_nonce_record_instruction_and_terminal_contracts(self, native_home, monkeypatch):
        _, text = self._task_text(native_home, monkeypatch)
        assert "NONCE" in text
        assert "LAST line" in text
        assert "SUP-BOOT-REFUSED" in text
        assert "SUP-BOOT-FROZEN" in text

    def test_launch_id_is_not_incarnation_id_note(self, native_home, monkeypatch):
        name, text = self._task_text(native_home, monkeypatch)
        assert "launch id" in text.lower()
        assert "not" in text.lower() and "incarnation" in text.lower()
        assert name in text                      # identity preamble names the body

    def test_campaign_body_appended_goals_not_embedded(self, native_home, monkeypatch):
        supdir = native_home / "supervisor"
        supdir.mkdir(exist_ok=True)
        (supdir / "GOALS.md").write_text(
            "GOALS-SENTINEL-XYZZY\nBypass acknowledgement (§10.2)\n", encoding="utf-8")
        _, text = self._task_text(
            native_home, monkeypatch, args=_sup_args(task="CAMPAIGN-BODY-42"))
        assert "CAMPAIGN-BODY-42" in text
        assert "GOALS-SENTINEL-XYZZY" not in text   # GOALS rides the boot bundle

    def test_no_plaintext_secret_in_task_file(self, native_home, monkeypatch):
        # Unlike the successor task (which carries the one-shot handoff token),
        # the gen-0 task file carries NO secret -- pin it stays that way.
        _, text = self._task_text(native_home, monkeypatch)
        assert "--handoff-token" not in text
        # The `NONCE: <value>` placeholder is instructional; a REAL minted
        # value (mint_nonce is hex) must never appear.
        assert not re.search(r"NONCE: (?!<)\S", text)


# ---------------------------------------------------------------------------
# Design §8-11: gate wiring. FI-3.
# ---------------------------------------------------------------------------
class TestSupSpawnGateWiring:
    def test_live_fresh_claim_sid_caller_without_nonce_refused(self, native_home, monkeypatch):
        value = fleet.mint_nonce()
        _held_claim(nonce_hash=fleet.nonce_digest(value))
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "some-other-sid")
        with pytest.raises(fleet.SupervisorClaimGateError, match="sup-spawn"):
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}

    def test_no_claim_passes_gate(self, native_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "some-sid")
        assert _happy_spawn(native_home, monkeypatch) == 0


# ---------------------------------------------------------------------------
# Design §8-12: ceiling wiring (§11.3).
# ---------------------------------------------------------------------------
class TestSupSpawnCeilingWiring:
    def test_claim_holding_worker_caller_at_ceiling_refused(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-1|boot")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", HOLDER_SID)
        _held_claim()
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 205000)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(),
                                which=lambda _: "claude", sleep=lambda s: None)
        assert "11.3" in str(ei.value)

    def test_interface_caller_exempt_at_any_occupancy(self, native_home, monkeypatch):
        # No FLEET_WORKER in the env -> structural exemption (ND4c).
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "interface-sid")
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 900000)
        assert _happy_spawn(native_home, monkeypatch) == 0


# ---------------------------------------------------------------------------
# Design §8-13: reserved name unchanged; docstring/refusal corrected (design §5).
# ---------------------------------------------------------------------------
class TestReservedNameReconciliation:
    def test_ordinary_spawn_of_supervisor_still_refused(self):
        with pytest.raises(ValueError, match="reserved"):
            fleet.validate_name("supervisor")

    def test_allow_reserved_bypass_retired(self):
        # Design §5(B): the pipe name fails NAME_RE before the reserved check,
        # so the bypass is dead for sup-spawn -- and it had zero other callers.
        assert "allow_reserved" not in inspect.signature(fleet.validate_name).parameters

    def test_docstring_no_longer_claims_sup_spawn_mints_it(self):
        doc = fleet.validate_name.__doc__ or ""
        assert "minted only by" not in doc
        assert "logical" in doc

    def test_refusal_text_names_logical_reservation(self):
        with pytest.raises(ValueError) as ei:
            fleet.validate_name("supervisor")
        msg = str(ei.value)
        assert "minted only by" not in msg
        assert "logical" in msg


# ---------------------------------------------------------------------------
# Design §8-14 / ruling 1(ii): "supervisor" as a logical name resolved via the
# claim -- never an alias record, never resolved by shape. FI-4.
# ---------------------------------------------------------------------------
class TestSupervisorLogicalResolution:
    def _seed_holder(self, name="sup|inc-A|boot", sid=HOLDER_SID, **overrides):
        rec = fleet.new_worker_record(sid, "C:/x", "t", "bypass", dispatch_kind="bg")
        rec.update(overrides)
        data = fleet.load_registry()
        data["workers"][name] = rec
        fleet.save_registry(data)
        return rec

    def test_resolves_to_claim_holder_record(self, native_home):
        _held_claim()
        self._seed_holder()
        assert fleet._resolve_worker_target("supervisor") == "sup|inc-A|boot"

    def test_non_supervisor_names_pass_through(self, native_home):
        assert fleet._resolve_worker_target("w1") == "w1"

    def test_no_claim_refuses_loudly(self, native_home):
        with pytest.raises(fleet.FleetCliError, match="nothing answers"):
            fleet._resolve_worker_target("supervisor")

    def test_released_claim_refuses(self, native_home):
        (native_home / "supervisor").mkdir(exist_ok=True)
        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released",
                                 "released_at": fleet.now_iso()})
        with pytest.raises(fleet.FleetCliError, match="nothing answers"):
            fleet._resolve_worker_target("supervisor")

    def test_holder_sid_in_no_record_names_the_sid(self, native_home):
        _held_claim(session_id="ghost-sid")
        self._seed_holder()   # a record exists, but not the holder's
        with pytest.raises(fleet.FleetCliError, match="ghost-sid"):
            fleet._resolve_worker_target("supervisor")

    def test_resolves_by_claim_never_by_shape(self, native_home):
        """Two supervisor-shaped records coexist (handoff in flight); only the
        claim disambiguates. FI-4: a shape-guessing resolver goes red here."""
        _held_claim(session_id="succ-sid")
        self._seed_holder(name="sup|inc-A|boot", sid="pred-sid")       # shape-plausible decoy
        self._seed_holder(name="sup|inc-B|successor", sid="succ-sid")  # the holder
        assert fleet._resolve_worker_target("supervisor") == "sup|inc-B|successor"

    def test_resolves_through_retired_sids_union(self, native_home):
        _held_claim(session_id="old-sid")
        self._seed_holder(sid="new-sid", retired_sids=["old-sid"])
        assert fleet._resolve_worker_target("supervisor") == "sup|inc-A|boot"

    @pytest.mark.parametrize("verb,args", [
        ("cmd_send", dict(name="supervisor", message="hi", nonce=None)),
        ("cmd_interrupt", dict(name="supervisor", nonce=None)),
        ("cmd_kill", dict(name="supervisor", yes=True, nonce=None)),
        ("cmd_respawn", dict(name="supervisor", task=None, force=False, yes=True,
                             nonce=None, max_budget_usd=None, setting_sources=None,
                             token_ceiling=None)),
        ("cmd_peek", dict(name="supervisor", lines=20)),
        ("cmd_result", dict(name="supervisor")),
        ("cmd_status", dict(name="supervisor", json=False, stale_ok=False, all=False)),
        ("cmd_status", dict(name="supervisor", json=False, stale_ok=True, all=False)),
    ])
    def test_verbs_resolve_supervisor_no_claim_refuses(self, native_home, verb, args):
        with pytest.raises(fleet.FleetCliError, match="nothing answers"):
            getattr(fleet, verb)(SimpleNamespace(**args))

    def test_send_lands_on_holder_record(self, native_home, monkeypatch):
        """`fleet send supervisor` with a live claim mails the pipe-named
        holder record (mid-turn mailbox path -- roster says busy)."""
        _held_claim()
        self._seed_holder(status="working",
                          last_dispatch_at=_iso(NOW - timedelta(minutes=5)))
        monkeypatch.setattr(
            fleet, "_fetch_agents_roster",
            lambda **_: (True, [make_roster_entry(HOLDER_SID, name="sup|inc-A|boot")]))
        rc = fleet.cmd_send(SimpleNamespace(name="supervisor", message="beat", nonce=None))
        assert rc == 0
        mail = native_home / "mailbox" / f"{HOLDER_SID}.md"
        assert mail.exists() and "beat" in mail.read_text(encoding="utf-8")

    def test_result_resolves_and_reads_holder_outcome(self, native_home, capsys):
        _held_claim()
        self._seed_holder()
        fleet.append_outcome(HOLDER_SID, {"ts": fleet.now_iso(), "session_id": HOLDER_SID,
                                          "kind": "result", "result_text": "sup says hi"})
        rc = fleet.cmd_result(SimpleNamespace(name="supervisor"))
        assert rc == 0
        assert "sup says hi" in capsys.readouterr().out

    def test_no_alias_record_is_ever_created(self, native_home, monkeypatch):
        assert _happy_spawn(native_home, monkeypatch) == 0
        assert "supervisor" not in fleet.load_registry()["workers"]


# ---------------------------------------------------------------------------
# Ruling 2: bypass-acknowledgement check -- WARN and proceed. FI-5.
# ---------------------------------------------------------------------------
class TestBypassAckWarn:
    def test_missing_goals_warns_and_proceeds(self, native_home, monkeypatch, capsys):
        assert _happy_spawn(native_home, monkeypatch) == 0
        err = capsys.readouterr().err
        assert "acknowledgement" in err and "WARNING" in err

    def test_goals_without_ack_warns(self, native_home, monkeypatch, capsys):
        supdir = native_home / "supervisor"
        supdir.mkdir(exist_ok=True)
        (supdir / "GOALS.md").write_text("just goals prose\n", encoding="utf-8")
        assert _happy_spawn(native_home, monkeypatch) == 0
        assert "acknowledgement" in capsys.readouterr().err

    def test_goals_with_ack_is_silent(self, native_home, monkeypatch, capsys):
        supdir = native_home / "supervisor"
        supdir.mkdir(exist_ok=True)
        (supdir / "GOALS.md").write_text(
            "Bypass acknowledgement (§10.2): the supervisor runs under bypass.\n",
            encoding="utf-8")
        assert _happy_spawn(native_home, monkeypatch) == 0
        assert "acknowledgement" not in capsys.readouterr().err

    def test_non_bypass_mode_needs_no_ack(self, native_home, monkeypatch, capsys):
        # §10.2's precondition attaches to bypass; an operator override to a
        # non-bypass mode does not trip it.
        rc = _happy_spawn(native_home, monkeypatch,
                          args=_sup_args(permission_mode="dontask"))
        assert rc == 0
        assert "acknowledgement" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Design §8-10: boot-decision pins the ritual rests on (pure function).
# ---------------------------------------------------------------------------
class TestBootDecisionPins:
    def test_fresh_state_claims(self):
        verdict, _ = fleet.supervisor_claim_decision(None, set(), None)
        assert verdict == "claim"

    def test_live_fresh_claim_second_body_refused(self):
        claim = {"incarnation_id": "inc-1", "session_id": "h",
                 "heartbeat_at": fleet.now_iso(), "nonce_hash": "x", "nonce_seq": 1}
        verdict, _ = fleet.supervisor_claim_decision(claim, {"h"}, None,
                                                     caller_sid="other")
        assert verdict == "refuse"

    def test_released_with_releaser_roster_live_refused_b6(self):
        claim = {"incarnation_id": "inc-1", "state": "released",
                 "released_by_sid": "r"}
        verdict, _ = fleet.supervisor_claim_decision(claim, {"r"}, None)
        assert verdict == "refuse"
        verdict2, _ = fleet.supervisor_claim_decision(claim, set(), None)
        assert verdict2 == "claim"


# ---------------------------------------------------------------------------
# Design §8-16 (stretch): per-launch names never collide; a DOA'd launch's
# task file is inert (name-keyed, next launch mints a different name).
# ---------------------------------------------------------------------------
class TestOrphanTaskHygiene:
    def test_two_doa_launches_leave_distinct_inert_task_files(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        for _ in range(2):
            with pytest.raises(fleet.FleetCliError):
                fleet.cmd_sup_spawn(_sup_args(), run=_fake_run_factory(rc=1),
                                    which=lambda _: "claude", sleep=lambda s: None)
        stems = list((native_home / "state" / "tasks").glob("sup~*~boot.md"))
        assert len(stems) == 2
        assert fleet.load_registry()["workers"] == {}
