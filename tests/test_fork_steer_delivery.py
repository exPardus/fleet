"""A STEER MUST REACH THE WORKER IT IS REPORTED TO HAVE REACHED.

`fleet send` to an idle worker fork-steers: it rewrites the worker's dispatch
payload and launches `claude --bg --resume <old_sid>`, then prints
`fork-steered (new session ...)`. Wave 48's pin tier caught that success line
being printed while the forked worker silently re-did its PREVIOUS task
(`docs/lanes/w48-pin.md` §4). Wave 49 reproduced it live and root-caused it
here.

THE MECHANISM, measured -- and deliberately NOT what these tests assert:
`dispatch_bg` composes its dispatched turn as
`f"Read {task_file_path(name).as_posix()} and follow it exactly."`, a pure
function of the worker NAME. A fork-steer therefore hands the resumed session
a turn BYTE-IDENTICAL to one it has already answered, while everything that
actually changed sits behind a pointer that session already dereferenced. The
resumed session carries the old file contents in its transcript, so replaying
its previous answer is not a malfunction -- it is the cheapest reading of the
turn it was given.

WHY THESE TESTS ARE WRITTEN AS THEY ARE
=======================================
This repo's recorded failure mode is that a pin written against the mechanism
someone fixed misses the one they introduced (`knowledge/lessons.md`, six
instances). So nothing below names `tiny_prompt`, the task file, the mailbox,
or any other storage decision. Both assertions are stated over ONE observable:
**what the dispatched session is handed, and what it already had.**

* `test_a_fork_steer_is_not_a_turn_the_session_already_answered` is the
  NECESSARY condition. It is deliberately weak: a bare per-dispatch nonce
  satisfies it while leaving the defect completely intact. It earns its place
  by being the legible headline -- when it reds, the one-line diff of the two
  prompts IS the diagnosis.

* `test_the_steer_is_determined_by_the_dispatched_turn_alone` is the REAL
  property, and it is the one that discriminates fixes from shams. It computes
  the bytes the resumed session receives THAT IT DID NOT ALREADY HAVE, and
  requires the steer to be among them. Concretely it accepts a fix that
  inlines the steer into the dispatched turn, and equally accepts a fix that
  points the turn at a payload identifier this session has never dereferenced
  (no cached content exists for it, so no replay can satisfy the turn). It
  REFUSES a per-dispatch nonce, a revision hash, and a "the file changed,
  re-read it" notice -- each of those still leaves delivery contingent on the
  worker CHOOSING to re-read, which is precisely the contingency that failed.

  That refusal is a design position, stated so it can be argued with rather
  than discovered: a steer whose arrival depends on model compliance cannot be
  reported as delivered, because nothing downstream can tell the difference.

RESIDUAL, stated rather than hidden: neither test can prove a real model obeys
a turn it has genuinely never seen. They prove the worker is HANDED the steer.
The live evidence that the current shipped turn is not obeyed is in
`docs/lanes/w49-fs.md` §3 (28 driven samples, both interpreters).
"""
import re
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


# ---------------------------------------------------------------------------
# fakes -- only `claude` is faked. The real cmd_spawn/cmd_send/dispatch_bg run.
# ---------------------------------------------------------------------------
SID_SPAWN = "11111111-aaaa-4bbb-8ccc-000000000001"
SID_FORK = "22222222-aaaa-4bbb-8ccc-000000000002"

NAME = "steer-w1"

# The task the worker is spawned on, and the steer that must supersede it. Both
# carry a sentinel on their LAST line: "the last line arrived" reds for a cap,
# a slice, an off-by-one, a marker misparse and for whatever is invented next,
# unlike "the payload is big enough", which a padded stub passes.
TASK_SENTINEL = "TASK-SENTINEL-4a1f: the original task, and nothing else."
TASK = ("# First mission\n\nDo the original thing.\n\n" + TASK_SENTINEL + "\n")

STEER_SENTINEL = "STEER-SENTINEL-9c3b: the steered instruction, and the whole point."
STEER = ("Change of plan from the manager. The earlier mission is superseded.\n"
         "Do the NEW thing instead, and report on it.\n" + STEER_SENTINEL)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """FLEET_HOME in a tmp dir with the rendered instance settings every
    dispatch path requires (SPEC §14)."""
    home = tmp_path / "fleet-home"
    (home / "state").mkdir(parents=True)
    (home / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (home / "logs").mkdir()
    (home / "mailbox").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    return home


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


def _entry(sid):
    return {"id": sid[:8], "sessionId": sid, "name": f"fleet|{NAME}|t",
            "cwd": "C:/proj", "startedAt": 1783986489446, "kind": "background",
            "state": "working", "status": "idle", "pid": 4321}


def _roster(*answers):
    box = {"i": 0}

    def _fetch(**_kw):
        i = min(box["i"], len(answers) - 1)
        box["i"] += 1
        return answers[i]
    return _fetch


def _claude(_name):
    return "claude"


class Dispatch:
    """One observed `claude` launch, recorded at the instant it happened.

    `turn` is exactly what the session is handed. `readable` is the content of
    every file the turn NAMES, snapshotted at that same instant -- a session
    that dereferences a pointer gets what was there then, not what is there
    now, and reconstructing the defect requires that distinction.
    """

    def __init__(self, argv):
        self.argv = list(argv)
        self.turn = self.argv[-1]
        self.readable = {str(p): _read(p) for p in _paths_named_in(self.turn)}

    @property
    def resumed_sid(self):
        return (self.argv[self.argv.index("--resume") + 1]
                if "--resume" in self.argv else None)


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_TOKEN_SPLIT = re.compile(r"[\s`'\"<>()\[\]]+")


def _paths_named_in(turn: str):
    """Every existing file the turn names -- derived from the turn text, with
    no knowledge of how fleet phrases a pointer. A future dispatch that says
    "open X" or "the brief is at X" is covered by the same walk."""
    found = []
    for tok in _TOKEN_SPLIT.split(turn or ""):
        tok = tok.strip().rstrip(".,;:")
        if len(tok) < 4:
            continue
        try:
            p = Path(tok)
            if p.is_file():
                found.append(p)
        except (OSError, ValueError):
            continue
    return found


def _recorder(sid, log):
    def _run(argv, **_kw):
        log.append(Dispatch(argv))
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"backgrounded \u00b7 {sid[:8]} \u00b7 fleet|{NAME}|t\n",
            stderr="")
    return _run


# ---------------------------------------------------------------------------
# the two dispatches under test
# ---------------------------------------------------------------------------
def _spawn(project, monkeypatch, log):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, [_entry(SID_SPAWN)])))
    args = SimpleNamespace(name=NAME, dir=str(project), task=TASK, mode="bypass",
                           model=None, max_budget_usd=None, setting_sources=None,
                           token_ceiling=None, category=None, context=None,
                           yes=True, nonce=None)
    assert fleet.cmd_spawn(args, run=_recorder(SID_SPAWN, log), which=_claude,
                           sleep=lambda s: None, clock=lambda: 0.0) == 0


def _settle_to_idle(monkeypatch):
    """Leave the worker in the state a finished turn leaves it in. Without
    this, `send` takes the mailbox-QUEUE branch and never dispatches at all --
    which is how a driver here could silently stop exercising a fork-steer."""
    data = fleet.load_registry()
    rec = data["workers"][NAME]
    fleet.append_outcome(NAME, {"ts": fleet.now_iso(),
                                "session_id": rec["session_id"], "kind": "result"})
    rec["status"] = "idle"
    fleet.save_registry(data)

    def _idle(worker, rec, roster, **kw):
        out = dict(rec)
        out["status"] = "idle"
        return out
    monkeypatch.setattr(fleet, "recompute_worker_native", _idle)


def _steer(monkeypatch, log):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, [_entry(SID_SPAWN)]),
                                (True, [_entry(SID_SPAWN)]),
                                (True, [_entry(SID_SPAWN), _entry(SID_FORK)])))
    args = SimpleNamespace(name=NAME, message=STEER, yes=True, nonce=None)
    assert fleet.cmd_send(args, run=_recorder(SID_FORK, log), which=_claude,
                          sleep=lambda s: None) == 0


@pytest.fixture
def dispatches(project, monkeypatch):
    """(spawn, fork-steer) as the resumed session experiences them."""
    log = []
    _spawn(project, monkeypatch, log)
    assert len(log) == 1, log
    _settle_to_idle(monkeypatch)
    _steer(monkeypatch, log)
    assert len(log) == 2, (
        "the send did not dispatch -- it queued to the mailbox instead of "
        "fork-steering, so everything below would be vacuous")
    spawn_d, steer_d = log
    assert steer_d.resumed_sid == SID_SPAWN, (
        "the second dispatch did not RESUME the first session, so it is not a "
        f"fork-steer and these tests do not apply: argv={steer_d.argv}")
    return spawn_d, steer_d


# ---------------------------------------------------------------------------
# THE PINS
# ---------------------------------------------------------------------------
def test_the_steer_actually_reached_the_dispatch_layer(dispatches):
    """Guard on the two pins below: if the steer never got as far as anything
    the fork could reach, they would red for the wrong reason and the diagnosis
    would be wrong. This asserts the steer IS available somewhere -- in the
    turn, or behind a pointer the turn names."""
    _spawn_d, steer_d = dispatches
    reachable = steer_d.turn + "".join(steer_d.readable.values())
    assert STEER_SENTINEL in reachable, (
        "the steer reached neither the dispatched turn nor anything it names -- "
        "this is a DIFFERENT defect from the one below (delivery lost the "
        f"message entirely). turn={steer_d.turn!r} named={list(steer_d.readable)}")


def test_a_fork_steer_is_not_a_turn_the_session_already_answered(dispatches):
    """NECESSARY condition. A resumed session is handed a turn it has already
    completed, so its previous answer remains a correct answer to the question
    it was just asked. Nothing about that is the model behaving badly.

    Weak by construction -- a per-dispatch nonce passes it. See the module
    docstring for why it is here anyway."""
    spawn_d, steer_d = dispatches
    assert steer_d.turn != spawn_d.turn, (
        "the fork-steer dispatched a turn BYTE-IDENTICAL to the one this "
        "session already answered, so replaying the previous answer satisfies "
        f"it:\n  {steer_d.turn!r}")


def test_the_steer_is_determined_by_the_dispatched_turn_alone(dispatches):
    """THE property. Compute what the resumed session receives that it did not
    already have, and require the steer to be in it.

    A pointer the session has already dereferenced contributes NOTHING new: the
    session holds that path's old contents and has no way to know they moved.
    A pointer it has never dereferenced contributes its content, because no
    cached answer exists for it. Inlining the steer contributes it directly.
    """
    spawn_d, steer_d = dispatches
    already_dereferenced = set(spawn_d.readable)

    new_to_this_session = [steer_d.turn]
    for path, content in steer_d.readable.items():
        if path not in already_dereferenced:
            new_to_this_session.append(content)
    new_bytes = "\n".join(new_to_this_session)

    assert STEER_SENTINEL in new_bytes, (
        "the fork-steer handed the resumed session ZERO bytes it did not "
        "already have: the steer sits behind a pointer this session already "
        "dereferenced, so obeying it depends entirely on the worker CHOOSING "
        "to re-read a file it believes it has read.\n"
        f"  dispatched turn : {steer_d.turn!r}\n"
        f"  already read    : {sorted(already_dereferenced)}\n"
        f"  named this time : {sorted(steer_d.readable)}")


# ---------------------------------------------------------------------------
# a delivery test's success token must not have a second way in
# ---------------------------------------------------------------------------
def test_the_steer_text_is_copied_into_the_dispatched_session_name(dispatches):
    """CHARACTERISATION, currently GREEN -- and a warning to anyone writing a
    delivery test against a live worker.

    `dispatch_bg` renders the session's roster name as `cat|name|hint` with
    `hint` = the steer's opening characters. So a short steer's text is visible
    to the forked session as its OWN TITLE, on a channel that has nothing to do
    with whether delivery worked. A live test whose success token fits inside
    that window can pass while the delivery path under test is broken.

    `tests/integration/test_native_pin.py`'s step 3 steers with
    `Reply with exactly: STEER-OK` -- 28 characters, entirely inside the
    window -- so its GREENs are weaker evidence than they look. The remedy is
    one line: push the token past the window, or make it per-run unique.
    (Not applied here: that file belongs to another lane this wave.)
    """
    _spawn_d, steer_d = dispatches
    name_value = steer_d.argv[steer_d.argv.index("-n") + 1]
    assert STEER[:20] in name_value, (
        "the steer no longer reaches the session name -- if that is "
        "deliberate, delete this test and the warning it carries; if it is "
        f"accidental, the hint channel moved. name={name_value!r}")
    assert fleet.NATIVE_NAME_HINT_MAX < len(STEER), (
        "this test's steer no longer exceeds the hint window, so it cannot "
        "demonstrate the truncation that makes the leak partial")
