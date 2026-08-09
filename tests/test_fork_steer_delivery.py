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

THE OTHER TWO TESTS HERE ARE ABOUT A DIFFERENT THING and are GREEN. A steer's
opening characters are copied into the dispatched session's own roster NAME, so
any delivery test whose success token fits inside that window can pass while
delivery is broken -- which is what wave 48's live pin tier did. One test
characterises the leak channel; the other holds `tests/integration/
test_native_pin.py`'s step-3 token outside it, in this tier, where it is
checked on every commit rather than only when someone spends money on a live
haiku run. See `docs/lanes/w49-fs.md` §11d for what driving that confound
actually showed -- the channel is real; the model was never observed to use it.
"""
import importlib.util
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
SID_THIRD = "33333333-aaaa-4bbb-8ccc-000000000003"

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

# The operator message that meets a usage limit. `cmd_send` REFUSES to steer a
# `limited` worker, so mail can never arrive DURING a park -- it is queued to a
# `working` worker whose turn then dies on the limit, and the resume drains it.
# That is the ordinary way a manager's message meets a usage limit, and it is
# the case wave 49's own patch did not cover (`docs/lanes/w49-fs.md` 11g).
MAIL_SENTINEL = "MAIL-SENTINEL-7e2d: the queued operator message, and the whole point."
QUEUED_MAIL = ("Manager, mid-turn: the requirements changed while you were working.\n"
               "Apply this to the task you are already on.\n" + MAIL_SENTINEL)


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


def _steer(monkeypatch, log, message=STEER):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, [_entry(SID_SPAWN)]),
                                (True, [_entry(SID_SPAWN)]),
                                (True, [_entry(SID_SPAWN), _entry(SID_FORK)])))
    args = SimpleNamespace(name=NAME, message=message, yes=True, nonce=None)
    assert fleet.cmd_send(args, run=_recorder(SID_FORK, log), which=_claude,
                          sleep=lambda s: None) == 0


def _park_limited(mail=None):
    """Leave the worker exactly as a turn killed by a usage limit leaves it:
    `limited`, horizon already passed -- and, optionally, an operator message
    queued into the CURRENT sid's mailbox.

    The mail is queued here rather than during the park on purpose: `cmd_send`
    refuses a `limited` worker outright, so the only reachable ordering is
    mail-then-park. Driving the unreachable one would pin a scenario the CLI
    forbids."""
    data = fleet.load_registry()
    rec = data["workers"][NAME]
    rec["status"] = "limited"
    rec["limit_reset_at"] = "2020-01-01T00:00:00Z"
    rec["limit_kind"] = "session_5h"
    fleet.save_registry(data)
    if mail:
        fleet.append_mailbox(rec["session_id"], mail)


def _resume_limited(monkeypatch, log, new_sid=SID_FORK, prior=(SID_SPAWN,)):
    """The unattended sweep: `fleet resume-limited <name>` on a parked worker
    whose horizon has passed."""
    entries = [_entry(s) for s in prior]
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, list(entries)),
                                (True, list(entries)),
                                (True, entries + [_entry(new_sid)])))
    args = SimpleNamespace(name=NAME, force_now=False, nonce=None)
    assert fleet.cmd_resume_limited(args, run=_recorder(new_sid, log),
                                    which=_claude, sleep=lambda s: None) == 0


def _bytes_new_to_this_session(previous, current):
    """What `current`'s session receives that it did not already have.

    Identical accounting to `test_the_steer_is_determined_by_the_dispatched_turn
    _alone`: the turn itself always counts; a pointer this session has already
    dereferenced contributes NOTHING (it holds that path's old contents and
    cannot know they moved); a pointer it has never dereferenced contributes its
    content."""
    already = set(previous.readable)
    parts = [current.turn]
    for path, content in current.readable.items():
        if path not in already:
            parts.append(content)
    return "\n".join(parts)


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
# THE SAME PROPERTY AT THE OTHER RESUMING CALL SITE
#
# `_resume_one_limited_native` fork-steers exactly like `send` does -- same
# `--resume`, same name-derived turn, same session that already answered it --
# and it fires UNATTENDED after a usage-limit park, on a worker whose turn was
# cut off mid-task, with no operator watching the reply. `docs/lanes/w49-fs.md`
# §2e found it and 11g measured it; the tests below are the pins that arm has
# never had.
# ---------------------------------------------------------------------------
@pytest.fixture
def limit_resume_dispatches(project, monkeypatch):
    """(spawn, limit-resume) with an operator message queued BEFORE the park."""
    log = []
    _spawn(project, monkeypatch, log)
    assert len(log) == 1, log
    _park_limited(mail=QUEUED_MAIL)
    _resume_limited(monkeypatch, log)
    assert len(log) == 2, (
        "resume-limited did not dispatch -- it skipped the worker, so "
        "everything below would be vacuous")
    spawn_d, resume_d = log
    assert resume_d.resumed_sid == SID_SPAWN, (
        "the resume did not RESUME the parked session, so it is not the "
        f"fork-steer these tests are about: argv={resume_d.argv}")
    return spawn_d, resume_d


def test_the_queued_mail_actually_reached_the_resume_dispatch_layer(limit_resume_dispatches):
    """Guard, mirroring `test_the_steer_actually_reached_the_dispatch_layer`:
    if the queued mail never got as far as anything the resumed session could
    reach, the pin below would red for a DIFFERENT defect (the park lost the
    mail entirely) and the diagnosis would be wrong."""
    _spawn_d, resume_d = limit_resume_dispatches
    reachable = resume_d.turn + "".join(resume_d.readable.values())
    assert MAIL_SENTINEL in reachable, (
        "the queued mail reached neither the resume turn nor anything it "
        "names -- the park DROPPED it, which is a different defect from the "
        f"one below. turn={resume_d.turn!r} named={list(resume_d.readable)}")


def test_a_limit_resume_delivers_queued_mail_by_the_dispatched_turn_alone(limit_resume_dispatches):
    """THE property, at the unattended arm.

    An operator's message that met a usage limit must reach the resumed session
    in bytes that session did not already have. Wave 49's own patch inlined a
    CONSTANT continuation sentence here and left the mail behind the
    already-dereferenced pointer -- so the turn said "read it again", which is
    SHAM-2, the shape this file refuses (module docstring), and refuses for a
    reason that applies here verbatim: delivery stays contingent on the worker
    CHOOSING to re-read."""
    spawn_d, resume_d = limit_resume_dispatches
    new_bytes = _bytes_new_to_this_session(spawn_d, resume_d)
    assert MAIL_SENTINEL in new_bytes, (
        "the limit-resume handed the resumed session the operator's queued "
        "message ONLY behind a pointer it had already dereferenced, so "
        "delivering it depends entirely on the worker CHOOSING to re-read a "
        "file it believes it has read -- unattended, with nobody watching.\n"
        f"  dispatched turn : {resume_d.turn!r}\n"
        f"  already read    : {sorted(spawn_d.readable)}\n"
        f"  named this time : {sorted(resume_d.readable)}")


def test_a_limit_resume_with_no_queued_mail_is_not_a_turn_already_answered(project, monkeypatch):
    """The other half of 11g's table. With no mail there is still an
    instruction to deliver -- *continue the task* -- and it must not be
    delivered as a turn the session has already answered."""
    log = []
    _spawn(project, monkeypatch, log)
    _park_limited(mail=None)
    _resume_limited(monkeypatch, log)
    assert len(log) == 2, "resume-limited did not dispatch"
    spawn_d, resume_d = log
    assert resume_d.turn != spawn_d.turn, (
        "the limit-resume dispatched a turn BYTE-IDENTICAL to the one this "
        "session already answered, so replaying the previous answer satisfies "
        f"it:\n  {resume_d.turn!r}")


def test_compose_prompt_hands_back_the_mail_it_drained(isolated_home):
    """The enabling contract for the pin above, stated directly.

    `compose_prompt` CLAIMS the mailbox -- it is the sole drain point -- so
    until now the drained text was reachable only by re-parsing the composed
    prompt or by a second claim. A resuming caller has to inline that exact
    text, so the drain returns it: ONE source of truth, and the turn and the
    payload cannot disagree about what the operator said.

    Pinned here rather than left implicit because the two-value shape is what
    made §6e inline a constant at the resume arm in the first place."""
    fleet.append_mailbox("sid-x", QUEUED_MAIL)
    prompt, claim, mail = fleet.compose_prompt("w", "C:/x", "", "sid-x")
    assert mail.strip() == QUEUED_MAIL.strip(), (
        "compose_prompt did not return the mail it drained, so a resuming "
        f"caller cannot inline it: {mail!r}")
    assert mail in prompt, (
        "the returned mail is not the text that went into the prompt -- two "
        "copies that can disagree is exactly what this return value exists "
        "to prevent")
    assert claim is not None

    _p, claim2, none_mail = fleet.compose_prompt("w", "C:/x", "", "sid-empty")
    assert none_mail == "", (
        f"no mail must read as the empty string, not {none_mail!r} -- the "
        "resume arm branches on it")
    assert claim2 is None


# ---------------------------------------------------------------------------
# THE TWO ARMS SAY OPPOSITE THINGS AND MUST NOT SHARE ONE SENTENCE
# ---------------------------------------------------------------------------
def test_the_steer_and_resume_arms_do_not_share_one_wrapper(project, monkeypatch):
    """A steer SUPERSEDES the running task; a limit-resume CONTINUES it. Wave
    49's patch used one wrapper for both -- *"That message is a NEW instruction
    and it supersedes anything earlier in this session"* -- which is right for
    `send` and actively wrong for `resume-limited`, whose entire purpose is to
    pick the earlier task back up.

    **The two arms having different wrapper text IS the property here. A shared
    constant is the regression this test exists to catch**, so it is stated over
    what the two REAL dispatches carry rather than over the constants: someone
    collapsing them has to defeat a driven comparison, not rename a variable.

    Both arms are driven in ONE fleet home, in the order an operator produces
    them (spawn -> steer -> park -> resume), so the comparison is between two
    turns the same code emitted in the same run.

    `wrapper_of` subtracts the SPAWN turn -- the bytes this session has already
    answered -- rather than reconstructing fleet's pointer sentence. That keeps
    the test ignorant of the storage decision (module docstring) and degrades
    safely: a future fix that changes the payload IDENTITY per dispatch leaves
    the subtraction a no-op and the whole turn as the wrapper, which still
    satisfies every assertion below for the right reason."""
    log = []
    _spawn(project, monkeypatch, log)
    _settle_to_idle(monkeypatch)
    _steer(monkeypatch, log)
    _park_limited(mail=None)
    _resume_limited(monkeypatch, log, new_sid=SID_THIRD,
                    prior=(SID_SPAWN, SID_FORK))
    assert len(log) == 3, (
        f"expected spawn + steer + resume dispatches, got {len(log)}")
    spawn_d, steer_d, resume_d = log
    assert resume_d.resumed_sid == SID_FORK, (
        "the resume did not resume the steered session, so the two arms were "
        f"not both exercised: argv={resume_d.argv}")

    def wrapper_of(d, body=""):
        w = d.turn.replace(spawn_d.turn, "")
        if body:
            # Subtract the operator's OWN words too. `STEER` itself contains
            # "superseded", so without this the steer assertion below would
            # pass on a wrapper that says nothing at all -- a test that reds
            # only because of the fixture's prose is not a pin.
            w = w.replace(body.strip(), "")
        return w.strip()

    steer_w, resume_w = wrapper_of(steer_d, STEER), wrapper_of(resume_d)

    assert steer_w, ("the steer turn carries nothing beyond the turn the "
                     f"session already answered: {steer_d.turn!r}")
    assert resume_w, ("the limit-resume turn carries nothing beyond the turn "
                      f"the session already answered: {resume_d.turn!r}")
    assert steer_w != resume_w, (
        "`send` and `resume-limited` now frame their dispatched turn with the "
        "SAME sentence. They mean opposite things: a steer supersedes the "
        "running task, a limit-resume continues it. Collapsing them tells a "
        "resumed worker to abandon the task the resume exists to finish.\n"
        f"  shared wrapper : {steer_w!r}")
    assert "supersede" in steer_w.lower(), (
        "the steer arm no longer tells the worker its new instruction "
        f"supersedes the running task: {steer_w!r}")
    assert "supersede" not in resume_w.lower(), (
        "the limit-resume arm tells the worker something supersedes the task "
        "it was parked mid-way through. The resume exists to CONTINUE that "
        f"task: {resume_w!r}")
    assert "continue" in resume_w.lower(), (
        "the limit-resume arm no longer tells the worker to continue the task "
        f"it was parked on: {resume_w!r}")


# ---------------------------------------------------------------------------
# THE KNOWN HOLE, PINNED RATHER THAN LEFT AS PROSE
# ---------------------------------------------------------------------------
BIG_HEAD = "BIG-STEER-HEAD-1a2b: the opening of an over-length steer."
BIG_TAIL = "BIG-STEER-TAIL-5f6e: past the inline cap, and therefore NOT delivered."


def test_an_over_length_steer_rides_the_turn_only_as_far_as_the_cap(project, monkeypatch):
    """CHARACTERISATION of a hole this lane did NOT close, pinned so it cannot
    be mistaken for fixed and cannot silently get worse.

    Inlining is bounded (`NATIVE_INLINE_STEER_MAX`) because Win32 caps a
    command line at 32767 characters and `fleet send @file` accepts arbitrarily
    large input -- uncapped, a large steer makes dispatch fail outright, which
    trades a rare silent miss for a common loud one.

    **Over the cap the guarantee degrades to exactly the SHAM-2 shape this file
    refuses**: the turn is distinguishable and says the file was rewritten, so
    the tail arrives only if the worker chooses to re-read. `docs/lanes/
    w49-fs.md` §6b calls that "a real hole in my own fix" and it is still open
    -- closing it needs FIX-B composed onto the overflow (a payload identity
    the session has never dereferenced), which changes `task_file_path`'s
    identity and so touches cleanup and archive. Out of this lane's arm.

    What IS pinned: the head reaches the turn, the turn SAYS it was cut, and
    the tail is still reachable behind the pointer. A regression that dropped
    the marker, or dropped the inline entirely at length, reds here."""
    big = BIG_HEAD + "\n" + ("filler line that pads this steer out. " * 130) + "\n" + BIG_TAIL
    assert len(big) > fleet.NATIVE_INLINE_STEER_MAX, (
        "this test's steer no longer exceeds the inline cap, so it cannot "
        f"exercise truncation at all (len={len(big)}, "
        f"cap={fleet.NATIVE_INLINE_STEER_MAX})")

    log = []
    _spawn(project, monkeypatch, log)
    _settle_to_idle(monkeypatch)
    _steer(monkeypatch, log, message=big)
    assert len(log) == 2
    _spawn_d, steer_d = log

    assert BIG_HEAD in steer_d.turn, (
        "an over-length steer no longer rides the turn AT ALL -- the cap is "
        "meant to bound the inline, not remove it")
    assert "truncated" in steer_d.turn.lower(), (
        "the turn carries a silently truncated steer: the worker is given a "
        "cut-off instruction with nothing saying it was cut. That is worse "
        f"than the hole it replaces. turn={steer_d.turn[:200]!r}")
    assert BIG_TAIL not in steer_d.turn, (
        "the tail now rides the turn too -- if the cap was raised or removed "
        "deliberately, update this test and `docs/lanes/w50-fs2.md`; if it "
        "was an accident, a `fleet send @bigfile` can now blow the Win32 "
        "command-line limit and fail the dispatch outright")
    assert BIG_TAIL in "".join(steer_d.readable.values()), (
        "the truncated tail is not reachable behind the pointer either, so it "
        "is simply LOST -- the marker in the turn points at a file that does "
        "not contain it")


def test_an_unrecognised_inline_kind_is_a_loud_error(project):
    """A dispatch that means to inline must not silently fail to.

    `inline_kind` is a string selecting between two sentences that contradict
    each other, so a typo (`"resumed"`, `"send"`) is a plausible edit. Without
    this guard it would fall through to an un-inlined turn -- i.e. it would
    silently restore the exact defect the parameter exists to remove, on a path
    whose tests all still pass because they assert about the OTHER arm."""
    with pytest.raises(fleet.NativeDispatchError) as exc:
        fleet.dispatch_bg(NAME, str(project), "body", "bypass",
                          inline_kind="resumed", inline_body="x",
                          resume_sid=SID_SPAWN, which=_claude,
                          run=lambda *a, **k: (_ for _ in ()).throw(
                              AssertionError("dispatch must not launch")),
                          sleep=lambda s: None,
                          roster_fetch=lambda **kw: (True, []))
    assert "inline_kind" in str(exc.value)


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

    `tests/integration/test_native_pin.py`'s step 3 used to steer with
    `Reply with exactly: STEER-OK` -- 28 characters, entirely inside the
    window -- so every GREEN it produced across five waves was weaker
    evidence than it looked. REPAIRED in wave 49; the test below is what
    stops it coming back, and it lives in the unit tier on purpose.

    Wave 49 turn 1 called that remedy "one line" and was wrong: a longer or
    unique literal fixes today's string and re-breaks on the next edit that
    shortens the message. The repair that survives is structural -- position
    derived from `NATIVE_NAME_HINT_MAX` rather than hand-counted, and an
    assertion that renders the name through `render_native_name` instead of
    trusting the count. THIS test stays because the leak channel itself is
    unchanged: `bin/fleet.py` is not fixed, and any future live delivery test
    is one short token away from the same tautology.
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


def _load_pin_tier_constants():
    """Load `tests/integration/test_native_pin.py` by PATH, under a private
    module name.

    By path on purpose: `tests/` is not a package, so importing it by
    basename would work or not depending on whether pytest had already
    prepended `tests/integration/` to `sys.path` -- i.e. on collection order,
    which is not a thing a guard should depend on. Under a private name on
    purpose too: this must not collide with pytest's own module registry
    entry for that file, and loading it here must not collect its tests. It
    does not -- `conftest.py` applies the `FLEET_LIVE=1` gate at COLLECTION,
    and an import is not a collection. Nothing in that module runs at import
    time beyond building the constants read below."""
    path = Path(__file__).resolve().parent / "integration" / "test_native_pin.py"
    spec = importlib.util.spec_from_file_location("_pin_tier_constants", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_pin_tiers_steer_token_cannot_reach_the_session_name(project, monkeypatch):
    """THE GUARD, and the reason it is in the unit tier.

    `tests/integration/test_native_pin.py::test_3_pin_fork_steer` is the only
    thing that checks a steer is delivered to a REAL worker, and its success
    token used to sit inside the hint window characterised above -- so it
    could pass on a fork that read nothing. It now carries its own guard, but
    that guard only fires when someone runs a live haiku tier, and whoever
    shortens the steer next will not be doing that. This runs on every
    commit, for free.

    It does NOT re-derive `hint=message[:NATIVE_NAME_HINT_MAX]`. Recomputing
    the call site's own slice would leave the one thing it most needs to
    watch -- that call site -- unwatched. Instead it drives the REAL
    `cmd_send` with the pin tier's REAL message and reads the `-n` value off
    the argv `dispatch_bg` actually assembled, so a change to the slice, to
    the constant, or to `render_native_name` is all covered by the same
    assertion.

    Three properties, because the confound had three ways back in: the token
    is not in the dispatched name (the leak itself), it is positioned past
    the window rather than merely happening to be long (so a prose edit to
    the lead-in reds here instead of silently sliding the token back inside),
    and it differs between runs (so a stale answer carried in a fork's
    transcript can never coincidentally match it)."""
    pin = _load_pin_tier_constants()

    log = []
    _spawn(project, monkeypatch, log)
    _settle_to_idle(monkeypatch)
    _steer(monkeypatch, log, message=pin.PIN_STEER_MESSAGE)
    assert len(log) == 2, (
        "the send did not dispatch, so no name was rendered and this guard "
        "would pass vacuously")
    steer_d = log[1]
    name_value = steer_d.argv[steer_d.argv.index("-n") + 1]
    assert pin.PIN_STEER_TOKEN not in name_value, (
        "the live pin tier's step-3 success token is back inside the roster "
        "name its own fork is dispatched under, so that step can go GREEN on "
        "a worker that never read the steer -- the exact tautology wave 49 "
        f"removed. name={name_value!r} token={pin.PIN_STEER_TOKEN!r}")

    assert pin.PIN_STEER_MESSAGE.index(pin.PIN_STEER_TOKEN) > fleet.NATIVE_NAME_HINT_MAX, (
        "the pin tier's token is no longer positioned past "
        f"NATIVE_NAME_HINT_MAX ({fleet.NATIVE_NAME_HINT_MAX}) by "
        "construction. It may still be outside the window by luck of the "
        "current wording; that is what broke last time. Derive the offset "
        "from the constant.")

    assert pin.PIN_STEER_TOKEN != _load_pin_tier_constants().PIN_STEER_TOKEN, (
        "the pin tier's steer token is the same on two independent loads, so "
        "it is no longer per-run unique -- an answer carried over in a "
        "forked session's transcript can satisfy the delivery assertion "
        "without the steer having been delivered")
