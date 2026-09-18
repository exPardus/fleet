"""w100 (queue item 31): respawn accepts a turn that died mid-stream.

THE DEFECT THIS FILE PINS, MEASURED 2026-09-18 ~16:15Z. w98c (kimi-k3) ended
turn 1 with transcript tail `API Error: stream closed before completion`. The
session process outlived its stream, so no Stop hook ever ran and no outcome
record exists. The two liveness verdicts then disagreed about the same record:

  * `fleet status` recomputed it `dead-suspected` -- no fresh outcome, past the
    dispatch grace window, no limit wall in the transcript tail
    (`_investigate_no_outcome`, `bin/fleet.py:2441`);
  * `fleet respawn w98c` refused `turn is running -- pass --force`, because its
    guard asks a different question -- Q1 (`_roster_live_sids`) counts any
    keyed roster entry with `state != "done"` as a live body, and the resident
    session is still keyed (`bin/fleet.py:5936-5941`).

So the SAFE verb demanded the UNSAFE flag, and the operator's only way to
recover a dead lane was to assert a live turn it did not have. This is now the
common OpenRouter death: w98c died this way twice in one day.

WHAT THE BUILD DOES (shape (a) of the queue item). The guard accepts the row
without `--force` only when BOTH verdicts agree on a hung turn: the probe's
verdict is `dead-suspected` AND the transcript tail's newest qualifying record
is an API stream death. The old session is still stopped and tombstoned -- the
acceptance is about the FLAG, never about skipping the teardown, because two
live sessions under one name is the hole the refusal exists to close.

WHAT IT MUST NOT DO, and the last four tests are the guards: a genuinely
running turn (roster `busy`/`waiting`), a `limited` row (429 is its own status,
not a hung turn), a row whose tail is ordinary chatter, and a tail whose newest
record is chatter AFTER an older death all keep the `--force` refusal.

THE MARKER SET IS MEASURED, NOT INVENTED. Every `isApiErrorMessage` record on
this host was tallied on 2026-09-19; the stream-death family is exactly
`stream closed before completion`, `Connection lost mid-response`,
`Server error mid-response` and `The response stopped arriving`. Rate-limit,
credit-exhaustion (402) and `model_not_found` texts were excluded deliberately
-- each is a different condition with its own recovery verb.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet

SID = "32fbc137-2ccf-4980-a9cd-6695f313cf89"

# The roster shape the hung session presents: keyed (so Q1 answers LIVE, which is
# what the respawn guard reads) but no running turn -- `status` is not
# busy/waiting, so the status probe's idle branch runs and finds no outcome.
KEYED_IDLE = {"sessionId": SID, "state": "working", "status": "idle",
              "pid": 4436, "kind": "background", "cwd": "/home/altai/proga/fleet"}

# The four measured stream-death tails, verbatim from real transcripts.
STREAM_DEATH_TEXTS = (
    "API Error: stream closed before completion",
    "API Error: Connection lost mid-response. The response above may be incomplete.",
    "API Error: Server error mid-response. The response above may be incomplete.",
    "API Error: The response stopped arriving. The response above may be incomplete.",
)


class _ReachedDispatch(Exception):
    """Control flow got past everything under test and would have launched."""


def _must_not_dispatch(*_a, **_k):
    raise _ReachedDispatch()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    (tmp_path / "proj").mkdir(exist_ok=True)
    fleet.save_registry({"workers": {}})
    return tmp_path


def _install(home, name="w", sid=SID, age_seconds=3600):
    """A worker record dispatched long enough ago that the launch grace window
    has expired. Without the aged anchor the probe answers `working` (in grace)
    and the dead-suspected verdict this file is about cannot arise."""
    rec = fleet.new_worker_record(sid, str(home / "proj"), "task", "bypass",
                                  dispatch_kind="bg")
    anchor = (datetime.now(timezone.utc)
              - timedelta(seconds=age_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["created"] = anchor
    rec["last_activity"] = anchor
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _transcript(home, records):
    """Write a transcript jsonl of the given records and point fleet at it."""
    path = home / "transcript.jsonl"
    path.write_text("".join(r + "\n" for r in records), encoding="utf-8")
    return path


def _api_error(text, error="unknown"):
    """The measured error-record shape: an assistant record flagged
    `isApiErrorMessage`, with the transport text in its message content."""
    return (
        '{"type": "assistant", "isApiErrorMessage": true, "error": "%s", '
        '"timestamp": "2026-09-18T16:09:03.006Z", "message": {"role": '
        '"assistant", "model": "<synthetic>", "content": [{"type": "text", '
        '"text": "%s"}]}}' % (error, text)
    )


def _chatter(text="All done."):
    return (
        '{"type": "assistant", "timestamp": "2026-09-18T16:09:04.000Z", '
        '"message": {"role": "assistant", "content": [{"type": "text", '
        '"text": "%s"}]}}' % text
    )


def _respawn_args(name="w", force=False, **over):
    ns = dict(name=name, task=None, force=force, yes=True, nonce=None,
              max_budget_usd=None, setting_sources=None, token_ceiling=None,
              permission_mode=None, model=None)
    ns.update(over)
    return SimpleNamespace(**ns)


def _run_factory(rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        return SimpleNamespace(returncode=rc, stdout="", stderr="")
    return fake_run


def _stops(calls):
    """The stop commands actually issued, as their job references."""
    return [argv[2] for argv in calls if len(argv) > 2 and argv[1] == "stop"]


def _tombstones(name, sid):
    return [o for o in fleet.read_outcomes(name, sid=sid)
            if o.get("kind") in fleet.TOMBSTONE_KINDS]


def _arm(monkeypatch, roster, transcript):
    """Point the drive at a roster and a transcript, and block the launch.

    The roster is STATEFUL, deliberately: the first fetch answers with `roster`,
    later fetches answer empty, modelling the daemon tearing the old session
    down when respawn stops it. A constant roster makes every accepted drive
    abort on its own post-stop re-verification ("never two live sessions under
    one name"), which would look like a refusal for a different reason
    altogether. Each call re-arms a fresh counter, so one test may drive twice.
    """
    fetches = []

    def _roster_fetch(**_):
        fetches.append(1)
        return (True, list(roster) if len(fetches) == 1 else [])

    monkeypatch.setattr(fleet, "find_transcript_path",
                        lambda _n, _s, _p=transcript: _p)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_fetch)
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)


def _drive(home, monkeypatch, roster, transcript=None, *, force=False,
           calls=None, name="w"):
    """Drive a real `cmd_respawn` to the dispatch boundary and stop there.

    `run`/`which` are real enough that the stop is genuinely issued: the fake
    `run` records the argv, so what is asserted is the stop respawn executed,
    not a recorder standing in for one.
    """
    _arm(monkeypatch, roster, transcript)
    with pytest.raises(_ReachedDispatch):
        fleet.cmd_respawn(_respawn_args(name, force=force),
                          run=_run_factory(calls=calls),
                          which=lambda _: "claude")


def _refuses(monkeypatch, roster, transcript, *, calls=None, name="w"):
    """Drive `cmd_respawn` without --force and return the refusal message.

    Every refusal test in this file uses it TWICE: once on the row that must be
    refused, and once on the otherwise-identical row that must be accepted. A
    blanket refusal satisfies the first limb alone, so the second is what makes
    the refusal mean "this row is a live turn" rather than "nothing is accepted".
    """
    _arm(monkeypatch, roster, transcript)
    with pytest.raises(fleet.FleetCliError) as ei:
        fleet.cmd_respawn(_respawn_args(name), run=_run_factory(calls=calls),
                          which=lambda _: "claude")
    return str(ei.value)


# ---------------------------------------------------------------------------
# The headline: the measured w98c row respawns without --force.
# ---------------------------------------------------------------------------

def test_dead_suspected_stream_death_respawns_without_force(home, monkeypatch,
                                                            capsys):
    """The exact measured row: no outcome record, keyed-but-idle roster entry,
    transcript tail `API Error: stream closed before completion`. Pre-change
    this raised `turn is running -- pass --force` and never reached dispatch."""
    _install(home)
    transcript = _transcript(home, [_api_error(
        "API Error: stream closed before completion")])
    calls = []
    _drive(home, monkeypatch, [KEYED_IDLE], transcript, calls=calls)

    assert _stops(calls) == [fleet._native_job_ref(SID)], (
        "the hung session must still be stopped -- accepting the row without "
        "--force must not skip the teardown that keeps one live body per name")
    assert [o["kind"] for o in _tombstones("w", SID)] == ["stopped"], (
        "a stopped session emits no Stop hook; respawn must write the tombstone")
    assert "without --force" in capsys.readouterr().err, (
        "the acceptance is a decision the operator did not ask for; it must be "
        "visible, not silent")


@pytest.mark.parametrize("text", STREAM_DEATH_TEXTS)
def test_the_measured_stream_death_family_is_accepted(home, monkeypatch, text):
    """All four measured stream-death texts, not just the one that was filed.

    Each is the same condition -- the transport died mid-turn, so no Stop hook
    ran and the session process is left keyed with no outcome record."""
    _install(home)
    transcript = _transcript(home, [_api_error(text)])
    calls = []
    _drive(home, monkeypatch, [KEYED_IDLE], transcript, calls=calls)
    assert _stops(calls) == [fleet._native_job_ref(SID)]


def test_the_predicate_is_the_verdict_not_the_status_field(home, monkeypatch):
    """The guard must agree with the STATUS PROBE, not with a stale persisted
    `status` string. The registry row here still says `working` (it was never
    rewritten), exactly as w98c's was -- the dead-suspected verdict lives only
    in the recompute. A guard that read `record["status"]` would refuse."""
    rec = _install(home)
    assert rec["status"] == "working"
    transcript = _transcript(home, [_api_error(
        "API Error: stream closed before completion")])
    calls = []
    _drive(home, monkeypatch, [KEYED_IDLE], transcript, calls=calls)
    assert _stops(calls) == [fleet._native_job_ref(SID)]


# ---------------------------------------------------------------------------
# The refusals that must survive: --force is still required for a live turn.
# ---------------------------------------------------------------------------

DEATH = "API Error: stream closed before completion"


def test_a_busy_roster_entry_still_refuses_without_force(home, monkeypatch):
    """The published contract, restated against this build. A roster entry with
    a RUNNING turn makes the probe answer `working`, so the acceptance predicate
    cannot fire: --force is still required.

    The second limb is what makes the refusal discriminating: the SAME record
    and the SAME transcript are accepted the moment the entry stops reporting a
    running turn. A blanket refusal would satisfy the first limb alone."""
    _install(home)
    transcript = _transcript(home, [_api_error(DEATH)])
    calls = []
    msg = _refuses(monkeypatch, [dict(KEYED_IDLE, status="busy")], transcript,
                   calls=calls)
    assert "turn is running" in msg
    assert _stops(calls) == [], "nothing may be stopped on the refusal path"
    _drive(home, monkeypatch, [KEYED_IDLE], transcript)


def test_a_rate_limit_tail_is_not_a_stream_death(home, monkeypatch):
    """A 429 tail is its own verdict (`limited`, with a reset horizon), not a
    hung turn. Accepting it without --force would turn a parked worker into a
    respawn and burn the wait the operator is already serving.

    The second limb shows the difference is the TAIL, not the roster: the same
    keyed-idle entry with a stream-death tail is accepted."""
    _install(home)
    limited = _transcript(home, [_api_error(
        "You've hit your session limit · resets 2:10pm (Asia/Almaty)",
        error="rate_limit")])
    assert "turn is running" in _refuses(monkeypatch, [KEYED_IDLE], limited)
    _drive(home, monkeypatch, [KEYED_IDLE],
           _transcript(home, [_api_error(DEATH)]))


def test_no_transcript_evidence_still_refuses(home, monkeypatch):
    """Dead-suspected with NO tail evidence is the row the doctrine says to
    inspect, never to respawn: the probe could not tell a hung turn from a
    session whose Stop hook was lost. Absent evidence never licenses the
    destructive verb.

    The second limb proves the refusal is about the MISSING evidence: the same
    record, once a stream-death tail exists, is accepted."""
    _install(home)
    calls = []
    assert "turn is running" in _refuses(
        monkeypatch, [KEYED_IDLE], home / "absent.jsonl", calls=calls)
    assert _stops(calls) == []
    _drive(home, monkeypatch, [KEYED_IDLE], _transcript(home, [_api_error(DEATH)]))


def test_chatter_after_the_death_refuses(home, monkeypatch):
    """Newest-first, exactly as the limit scan reads it: the first qualifying
    record is the authoritative last thing that happened. A death buried under
    newer chatter means the turn came back, so it is not a hung row.

    The second limb drops the chatter and shows the identical tail is accepted
    once the death IS the newest record."""
    _install(home)
    buried = _transcript(home, [_api_error(DEATH),
                                _chatter("Recovered; continuing.")])
    assert "turn is running" in _refuses(monkeypatch, [KEYED_IDLE], buried)
    _drive(home, monkeypatch, [KEYED_IDLE],
           _transcript(home, [_api_error(DEATH)]))


# ---------------------------------------------------------------------------
# The scanner itself, on its own seams.
# ---------------------------------------------------------------------------

def test_the_scanner_reads_the_tail_not_the_head(home, monkeypatch):
    """A death older than the 64KB tail window is not evidence: the scanner
    reads `_read_tail_lines`, so it can only ever see what a probe would see."""
    path = home / "transcript.jsonl"
    path.write_text(_api_error("API Error: stream closed before completion") + "\n"
                    + _chatter("x" * 200_000) + "\n", encoding="utf-8")
    assert fleet.transcript_stream_death_scan(SID, transcript_path=path) is False


def test_the_scanner_declines_when_the_transcript_is_unreadable(home):
    """Missing access returns False -- never guess a death from absence."""
    assert fleet.transcript_stream_death_scan(
        SID, transcript_path=home / "nope.jsonl") is False
    assert fleet.transcript_stream_death_scan("", transcript_path=None) is False
