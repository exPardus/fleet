#!/usr/bin/env python3
"""fleet keeper -- a page-only liveness timer for a headless fleet.

Runs from a systemd user timer every 15 minutes (`--once`). It OBSERVES
fleet state read-only and TYPES one-line pages into the dedicated tmux
interface window (`work:fleet`), whose Claude session relays them to
Telegram through the ccgram bridge. It never takes `fleet.lock`, never
writes fleet state, and NEVER DISPATCHES A SESSION.

WHAT "never dispatches" NOW MEANS (operator ruling 2026-09-09 and its
AMENDMENT, `state/tasks/20260909-succession-ruling.md`; it supersedes the
2026-09-08 "the timer pages, a human revives" ruling recorded in
docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md, which
still carries the old page text and is the prose lane's to correct). The
keeper's own boundary is UNCHANGED in kind -- it observes and it types. What
changed is what it types: the supervisor-liveness rule (named
`rule_supervisor_dead` then, `rule_supervisor_stalled` since G-K6 wave 1)
used to say "await operator before sup-spawn" and now says "relaunch",
because the INTERFACE runs
`sup-spawn` on that line without waiting for the operator. Revival is
therefore no longer a human message from the phone, and the keeper still
runs no `sup-spawn` itself. The two-live-body guard the amendment asks for
lives on the interface, in docs/operator/server-interface-profile.md, not
here.

Exit codes: 0 for every observed fleet state (a dead fleet is news, not an
error), 2 from argparse for a usage error, and 1 for exactly one condition
-- `--fleet-home` naming a home other than the one the imported `fleet`
module froze at import time, where every reading would be about the wrong
home (fix wave 1, I3).

stdlib only; floor is fleet.MIN_PYTHON_VERSION.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT / "bin"))

import fleet  # noqa: E402

Page = namedtuple("Page", "rule fingerprint text")

HEARTBEAT_STALE_SECONDS = 3600
UNPUSHED_PAGE_SECONDS = 6 * 3600
REPAGE_SECONDS = 6 * 3600
ANOMALOUS_STATUSES = ("dead-suspected", "limited")

# THE SANITISER MOVED, THE DOCTRINE DID NOT (w58/notify, 2026-09-09). Fix
# wave 1's C4 body now lives in `fleet.one_line` / `fleet.interface_line`,
# generalised over the prefix, because the SUPERVISOR needs the same wire and
# the same sanitiser and cannot call this module -- the keeper is a separate
# timer process with no inbound surface, and the import direction is
# `fleet_keeper -> fleet`, never the reverse. Two copies of a security control
# is how one of them rots. The four functions below are the keeper's names for
# it; they stay because this module's own tests and rules bind to them, and
# because a delegate that changes no behaviour is cheaper than a rename that
# reddens `tests/test_keeper_*.py`. The WHY is in `fleet.py`'s
# "THE TMUX INTERFACE LINE" section header; do not restate it in two places.
PAGE_PREFIX = fleet.KEEPER_LINE_PREFIX
PAGE_TEXT_LIMIT = fleet.INTERFACE_LINE_LIMIT


def _one_line(text, limit=PAGE_TEXT_LIMIT):
    """Collapse `text` into one printable line of at most `limit` chars
    (fix wave 1, C4). Delegate: `fleet.one_line`."""
    return fleet.one_line(text, limit)


def _page_line(text):
    """The exact bytes a page types: `KEEPER: `-prefixed, then one-lined.
    Delegate: `fleet.interface_line` with this module's prefix."""
    return fleet.interface_line(text, PAGE_PREFIX, PAGE_TEXT_LIMIT)


# --------------------------------------------------------------------- rules

def _since(obs):
    """When the supervisor stopped, if anything says: the claim's own
    `released_at` first, else the heartbeat age in whole minutes."""
    released_at = obs.get("released_at")
    if released_at:
        return str(released_at)
    beat = obs.get("heartbeat_age_seconds")
    if beat is None:
        return None
    return f"{int(beat // 60)} min ago"


def rule_registry_unreadable(obs, now):
    """Two states, two pages (fix wave 1, I1). A home where `fleet init` has
    never run reads as `ok=False, reason="not_initialized"` -- the same shape
    a QUARANTINED registry produces -- and paging "registry unreadable" at an
    operator whose real remedy is `fleet init` sends them looking for an
    incident that never happened."""
    if obs.get("registry_ok", True):
        return None
    reason = obs.get("registry_reason") or "unknown"
    if reason == "not_initialized":
        return Page("not-initialised", reason,
                    "KEEPER: fleet home not initialised "
                    "(state/worker-settings.json or registry missing). "
                    "Run fleet init from a plain shell.")
    return Page("registry-unreadable", reason,
                f"KEEPER: registry unreadable ({reason}). Report it; do not repair.")


def rule_claude_missing(obs, now):
    """`claude` absent from the unit's PATH is a DEPLOY fault, not an expired
    login (fix wave 1, I2). systemd user units get a minimal PATH; the login
    remedy (`/login` on the box) would not fix it."""
    if not obs.get("agents_missing"):
        return None
    return Page("claude-missing", "not-on-path",
                "KEEPER: claude binary not found on PATH for the keeper unit. "
                "Check the service PATH.")


def rule_login_expired(obs, now):
    if obs.get("agents_ok", True):
        return None
    if obs.get("agents_missing"):
        return None  # claude-missing says the true thing about this one
    return Page("login-expired", "agents-failed",
                "KEEPER: claude login appears expired (`claude agents` failed). "
                "Operator must /login on the box.")


def rule_claim_unknown(obs, now):
    """`unknown` is "the claim could not be read or projected"
    (`_supervisor_tier_snapshot`), which is NOT evidence of death. It used to
    ride the supervisor-stalled page (`supervisor-dead` when C2 split them)
    and so reported a read failure as a fact about the supervisor (fix wave
    1, C2)."""
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None
    if obs.get("claim_state") != "unknown":
        return None
    return Page("claim-unknown", "unknown",
                "KEEPER: supervisor claim unreadable (state unknown). "
                "Report it; do not repair.")


#: The ONE roster `status` value that means "this body is taking a turn right
#: now" (MEASURED, `docs/lanes/w61-keeperblind.md` §3, claude 2.1.267 on this
#: host: a background session reads `busy` inside its turn and flips to `idle`
#: within 13 s of the turn ending, with no other field moving).
#:
#: IT IS AN ALLOWLIST OF ONE, AND THAT IS THE DELIBERATE CHOICE. Everything
#: else -- `idle`, `waiting`, a value a later CLI invents, a non-string, or no
#: `status` key at all -- reads as NOT WORKING and therefore PAGES once the
#: heartbeat is stale. This is an alarm; the direction it must fail in is
#: LOUD. A denylist ("page unless the status is one of these dead ones") would
#: silently re-acquire the 2026-09-09 blindness the first time the CLI shipped
#: a new value.
ROSTER_BUSY = "busy"


def _claim_activity(obs):
    """`(activity, status)` for the claim's OWN roster row, from
    `claude agents --json` (the plain spelling; never `--all`).

    Four classes, because the three non-busy ones are three different
    sentences for the operator and one of them is not even a defect in the
    same sense:

    - `"busy"`   -- listed, `status == "busy"`: a body in a turn right now.
    - `"quiet"`  -- listed with some other status (`idle` is the measured
                    one): the body is ALIVE and NOT WORKING. This is the
                    2026-09-09 outage, and it is what C exists to page.
    - `"dead"`   -- listed, but the row carries NO `status` at all. MEASURED:
                    on a dead row `status` and `pid` are ABSENT from the
                    object, not present-and-null (w61 §2), and such rows
                    persist in the plain spelling indefinitely -- one was 22h
                    old when measured. Listed is not alive.
    - `"absent"` -- no row for this sid at all.

    `obs.get("claim_row_status")` is NOT read as a bare `.get()` truth test.
    A missing obs key, a row without the key, and a row whose key holds a
    non-string all land on `"dead"`/`"absent"` EXPLICITLY, so the alarm can
    never be silenced by a shape nobody anticipated -- `.get()` returning
    `None` by accident is exactly how a rule ends up passing its tests while
    watching nothing."""
    if not obs.get("claim_in_roster"):
        return "absent", None
    status = obs.get("claim_row_status")
    if not isinstance(status, str) or not status:
        return "dead", None
    return ("busy" if status == ROSTER_BUSY else "quiet"), status


def rule_supervisor_stalled(obs, now):
    """The fleet has no supervisor TAKING TURNS. Fires on: GOALS active, the
    roster readable, and either a released/absent claim (no supervisor by
    definition -- no roster condition), or a HELD claim whose heartbeat is
    missing/stale AND whose own session row is not `busy`.

    RENAMED FROM `rule_supervisor_dead` (G-K6 wave 1, operator ruling
    2026-09-10 *"G-K6 C then B"*, which invites the rename *"if the lane
    agrees the name is wrong"*). The lane agrees. The rule now pages a body
    that is alive, listed, holding the claim, and idle -- calling that "dead"
    is a false claim about the world in the page the operator reads at 3am.
    The `Page` rule name moved with it (`supervisor-dead` ->
    `supervisor-stalled`), which is the dedup key: see the report for the
    one-off re-fire that costs.

    WHAT C CHANGED, AND WHY THE OLD ARM WAS THE WRONG INSTRUMENT. The arm used
    to be `claim_sid in roster_sids` -- MERE PRESENCE. It was added (fix wave
    1, C2) to protect a supervisor that was *alive and unlisted*, on the
    premise that `claude agents --json` "lists ACTIVE sessions only". MEASURED
    (`docs/lanes/w61-keeperblind.md` §3, §6), that premise is exactly
    INVERTED: an idle-between-turns background session is PRESENT, at
    `state: "working"`, `status: "idle"`, with a live pid, and it stays that
    way until the daemon retires it at 8h. Alive-and-unlisted does not occur
    for a background session on this host. What occurs is dead-and-listed
    (5 of 10 plain rows, one 22h old) and alive-listed-and-doing-nothing --
    and the old arm admitted both. On 2026-09-09 it suppressed the page for
    8h10m51s while the heartbeat screamed; `status`-armed, the identical
    observations page at 21:04:36Z instead of 04:14:36Z.

    THE SID JOIN STAYS, AND IT IS LOAD-BEARING. Only the MEMBERSHIP predicate
    changed. C2's fix -- join on the claim's SESSION ID, never a `sup|` name
    prefix -- is untouched, because `ai-title` can overwrite `name` after a
    resume, so a name join can bind a live supervisor to the wrong row or
    miss it entirely and page at a healthy fleet.

    THE RESIDUAL C DOES NOT CLOSE, STATED PLAINLY: a supervisor WEDGED
    MID-TURN reports `status: "busy"` for as long as its process lives, and
    this rule stays silent for exactly as long. UNMEASURED -- w61 could not
    produce a wedge, and neither did this lane. The hole is strictly smaller
    than the one it replaces (that one swallowed every idle body too), but it
    is a hole, and it is the reason a heartbeat-only rule (reading A) is still
    arguable. A supervisor mid-LEGITIMATE-long-turn reads `busy` too, and is
    suppressed on purpose: that is C's whole claim to introducing no new false
    positive.

    A held claim with a FRESH heartbeat never pages, whatever the roster
    says -- that gate is checked first and is unchanged."""
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None  # cannot tell dead from unlisted; login/missing rules cover it
    state = obs.get("claim_state")
    if state in ("released", "none"):
        reason = f"claim {state}"
        fp = reason
    elif state == "held":
        beat = obs.get("heartbeat_age_seconds")
        if beat is not None and beat <= HEARTBEAT_STALE_SECONDS:
            return None
        activity, status = _claim_activity(obs)
        if activity == "busy":
            return None
        stale = ("no heartbeat" if beat is None
                 else f"heartbeat {int(beat // 60)} min stale")
        if activity == "quiet":
            # The 2026-09-09 shape. Name the value, because "idle" and
            # "waiting" (a permission prompt nobody is at the keyboard for)
            # are different remedies and the operator can only see which
            # from the page.
            seen = f"roster says {status}"
        elif activity == "dead":
            seen = "claim session listed with no live process"
        else:
            seen = "claim session not in the roster"
        reason = f"{stale}, {seen}"
        # The fingerprint must NOT carry the heartbeat age (re-review minor
        # 1): the age changes every tick, so a beat-bearing fingerprint never
        # equals its predecessor and `dedup` can never suppress it -- the
        # operator would be paged every 15 minutes instead of once per
        # REPAGE_SECONDS. The age still reaches the operator, in the TEXT,
        # via `_since` below.
        fp = f"held:stale:{obs.get('claim_sid') or '-'}"
    else:
        return None  # `unknown` belongs to rule_claim_unknown
    since = _since(obs)
    head = (f"supervisor stalled since {since}" if since
            else "supervisor stalled")
    # THE INSTRUCTION IS `RELAUNCH`, NOT `WAIT` (operator ruling 2026-09-09,
    # AMENDMENT: *"keeper must just instruct interface to relaunch
    # supervisor"*). The keeper still does not dispatch -- it types, the
    # INTERFACE runs `sup-spawn`, and it does so without waiting for the
    # operator. The predecessor text ("Report state; await operator before
    # sup-spawn.") is what the amendment names and replaces.
    #
    # THE TWO-LIVE-BODY GUARD IS DELIBERATELY NOT IN THIS PAGE. The amendment
    # puts it on the interface -- *"check `sup-status` and the roster before
    # dispatching, and page the operator instead when the state is
    # ambiguous"* -- and `docs/operator/server-interface-profile.md` is where
    # it is written, because it is a procedure and this is 200 characters
    # shared with a worker-writable `released_at`. A page that spends its
    # budget restating a checklist truncates the verb it exists to name.
    #
    # THE FINGERPRINT IS UNCHANGED ACROSS C, ON PURPOSE, AND THE INVARIANT
    # WAS RE-CHECKED (this change DOES alter what the page says). `fp` still
    # carries no heartbeat age -- and it also does NOT carry the activity
    # class. The class can move under a stalled supervisor (`quiet` becomes
    # `dead` when the daemon finally retires the body, as it did at 04:05:58Z
    # on 2026-09-09), and folding it in would re-page on a transition that
    # changes nothing the operator does. One claim, one held-and-stalled
    # fingerprint, one page per REPAGE_SECONDS.
    #
    # THE RULE NAME DID CHANGE: `supervisor-dead` -> `supervisor-stalled`.
    # That IS the dedup identity (`state/keeper/last-page.json` keys on it),
    # so the first tick after this lands re-pages a stall that was already
    # paged under the old name -- once. Stated, not discovered; see
    # `docs/lanes/w62-keeperc.md`.
    return Page("supervisor-stalled", f"{state}:{fp}",
                f"KEEPER: {head} ({reason}). Report state, then relaunch "
                "with sup-spawn; do not await the operator.")


def rule_supervisor_frozen(obs, now):
    q = obs.get("pending_decision")
    if not q:
        return None
    return Page("supervisor-frozen", str(q),
                f"KEEPER: supervisor parked on decision: {q} "
                "Carry it to the operator.")


def rule_worker_anomaly(obs, now):
    names = []
    for w in obs.get("workers", []):
        status = w.get("status")
        if status in ANOMALOUS_STATUSES:
            names.append(f"{w.get('name')}({status})")
        elif status == "idle" and (w.get("mail") or 0) > 0:
            names.append(f"{w.get('name')}(idle+mail)")
    if not names:
        return None
    joined = ", ".join(sorted(names))
    return Page("worker-anomaly", joined,
                f"KEEPER: {len(names)} worker anomalies: {joined}. "
                "Summarise for the operator.")


def rule_unpushed(obs, now):
    """`unpushed` is commits that exist on NO remote -- see `_git_unpushed`,
    which is where w56 replaced the fixed `origin/main..main` ref pair.

    The page NAMES the ref it measured (w56). The page this host actually got
    said `2 commits unpushed for 9h` and nothing more, and the operator had no
    way to see from it that the two commits were on `main`, fully contained in
    a pushed branch, while the nineteen the rule could not see were on the
    working branch. `unpushed_ref` is optional: an observation that could not
    read the name still pages the count."""
    n = obs.get("unpushed") or 0
    oldest = obs.get("oldest_unpushed_ts")
    if n <= 0 or oldest is None:
        return None
    age = now - oldest
    if age < UNPUSHED_PAGE_SECONDS:
        return None
    hours = int(age // 3600)
    ref = obs.get("unpushed_ref")
    where = f" on {ref}" if ref else ""
    return Page("unpushed", f"{n}:{int(oldest)}",
                f"KEEPER: {n} commits unpushed{where} for {hours}h. "
                "Push or explain.")


def rule_hook_errors(obs, now):
    cur = obs.get("hook_error_lines") or 0
    prev = obs.get("prev_hook_error_lines") or 0
    if cur <= prev:
        return None
    return Page("hook-errors", f"{prev}->{cur}",
                f"KEEPER: hook-errors.log grew by {cur - prev} lines. Read it.")


RULES = (
    rule_registry_unreadable,
    rule_claude_missing,
    rule_login_expired,
    rule_claim_unknown,
    rule_supervisor_stalled,
    rule_supervisor_frozen,
    rule_worker_anomaly,
    rule_unpushed,
    rule_hook_errors,
)


def evaluate(obs, now) -> list:
    pages = []
    for rule in RULES:
        page = rule(obs, now)
        if page is not None:
            pages.append(page)
    return pages


# --------------------------------------------------------------------- dedup

def dedup(pages, state, now):
    """Send a page when its rule is new, its fingerprint changed, or the
    re-page window elapsed. Rules that stopped firing drop out of state."""
    send = []
    new_state = {}
    for page in pages:
        prev = state.get(page.rule)
        if (prev is None or prev.get("fingerprint") != page.fingerprint
                or now - float(prev.get("at", 0)) > REPAGE_SECONDS):
            send.append(page)
            new_state[page.rule] = {"fingerprint": page.fingerprint, "at": now}
        else:
            new_state[page.rule] = prev
    return send, new_state


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------- collect

SUBPROCESS_TIMEOUT = 30
MISSING_BINARY_RC = 127
# The rev set the unpushed rule measures: everything the checked-out work
# reaches that no remote-tracking ref does. Named once so the count and the
# oldest-timestamp lookup cannot drift apart.
UNPUSHED_REVS = ("HEAD", "--not", "--remotes")


def _run_text(run, argv, *, cwd=None, env=None):
    """(rc, stdout). A missing executable returns `MISSING_BINARY_RC`, which
    is the shell's own convention -- folding it into rc=1 made "claude is not
    on this unit's PATH" indistinguishable from "claude ran and refused",
    i.e. from an expired login (fix wave 1, I2). Every other failure class
    (timeout, permission, non-zero exit) still lands on rc != 0."""
    kwargs = {"capture_output": True, "text": True, "timeout": SUBPROCESS_TIMEOUT}
    if cwd is not None:
        kwargs["cwd"] = cwd
    if env is not None:
        kwargs["env"] = env
    try:
        cp = run(argv, **kwargs)
    except FileNotFoundError:
        return MISSING_BINARY_RC, ""
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return cp.returncode, cp.stdout or ""


def _sup_status(home, run):
    argv = [sys.executable, str(Path(home) / "bin" / "fleet.py"),
            "sup-status", "--json"]
    rc, out = _run_text(run, argv, env={**os.environ, "FLEET_HOME": str(home)})
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _pending_question(status):
    """The open decision's QUESTION, or None.

    Fix wave 1, C4. `sup-status --json` publishes `read_pending_decision()`'s
    whole dict (`question`/`raised_by_inc`/`raised_at`/`answer`), so the old
    code interpolated a dict repr into the page. An ANSWERED-but-unconsumed
    decision is not a freeze either, so it must not page. A bare string is
    accepted as the question for the older shape."""
    pending = status.get("pending_decision")
    if isinstance(pending, str):
        return pending or None
    if not isinstance(pending, dict):
        return None
    if pending.get("answer"):
        return None
    question = pending.get("question")
    return question if isinstance(question, str) and question else None


def _agents(run):
    """(ok, missing, {sessionId: status-or-None}). `claude agents --json`,
    with NO `--all` -- the two spellings are different lists (the plain one
    omits `done`/`failed`/`stopped` rows) and a claim about one is not a
    claim about the other. Name the spelling beside any count taken from it.

    THE OLD DOCSTRING SAID THIS LISTS "the ACTIVE sessions". IT IS FALSE, AND
    IT WAS LOAD-BEARING (`docs/lanes/w61-keeperblind.md` §6, MEASURED on this
    host at `claude 2.1.267`): at 04:27Z the plain spelling returned 10 rows
    of which 5 were dead bodies, the oldest dead and listed for 22h05m. That
    word told every reader that membership IS liveness, so no caller filtered
    -- and the resulting arm watched a dark fleet for 8h10m.

    SO THE VALUE IS THE ROW'S `status`, NOT JUST THE KEY (G-K6 wave 1 / C).
    Rows are heterogeneous by `kind`: an `interactive` row carries
    `pid`/`status` and no `state`; a `background` row carries `state`, and
    carries `pid`/`status` ONLY WHILE THE PROCESS LIVES. On a dead row the
    `status` key is ABSENT from the object, not present-and-null -- so the
    mapping's value is None for "listed with no live process", and a sid
    missing from the mapping is "no row at all". `_claim_activity` is the one
    place that reads the difference.

    A non-str or empty `status` is normalised to None (the same treatment a
    dead row gets), because this data crosses a process boundary and the
    alarm must not depend on the CLI's JSON being well-typed."""
    rc, out = _run_text(run, ["claude", "agents", "--json"])
    if rc == MISSING_BINARY_RC:
        return False, True, {}
    if rc != 0:
        return False, False, {}
    try:
        rows = json.loads(out)
    except ValueError:
        return False, False, {}
    if not isinstance(rows, list):
        return False, False, {}
    statuses = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("sessionId"), str):
            if row["sessionId"]:
                status = row.get("status")
                statuses[row["sessionId"]] = (
                    status if isinstance(status, str) and status else None)
    return True, False, statuses


def _git_unpushed(home, run, out=sys.stdout):
    """(count, oldest unpushed commit ts, ref name) for the work AT RISK:
    commits reachable from the checked-out HEAD that exist on no remote-
    tracking ref -- `git rev-list --count HEAD --not --remotes`.

    W56, MEASURED ON THIS HOST. This used to ask `origin/main..main`, which is
    a claim about two REF NAMES rather than about exposure, and this fleet does
    not work on `main`. At `f4aa63f` (the 2026-09-09T01:26:01Z page) it
    answered **2** while **21** commits sat on one disk and on no remote: the
    entire server bring-up, 19 commits, invisible to the rule during the exact
    window it exists to cover. Four hours later, with the branch pushed, those
    same two `main` commits were fully contained in
    `origin/server/persistent-fleet` (`git merge-base --is-ancestor` proves it)
    and at no risk whatever -- and the rule would have re-paged about them
    every six hours forever. A page that is technically true and operationally
    false is worse than no rule, because it teaches the operator to ignore the
    channel.

    HEAD, NOT `--branches`. The wider rule -- page about any local branch
    carrying unpushed work -- is defensible in the abstract and wrong for this
    fleet: worker lanes are branches in worktrees of this same repository which
    are committed-and-not-pushed BY POLICY until the manager merges them, so
    `--branches` would manufacture, every wave, exactly the operationally-false
    page this change removes. Their remedy is a merge, not a push, so they are
    not this rule's business. The cost is named rather than hidden: a lane
    worktree has its own HEAD, so its commits are not counted here.

    NO REMOTE-TRACKING REF IS "CANNOT TELL", AND IS THE MOST LIKELY WAY TO MAKE
    THIS RULE WORSE. `--not --remotes` subtracts nothing when there are no
    remote refs, so `rev-list` counts the ENTIRE history and exits 0 -- the
    failure does not even look like one (measured: 5 of 5 commits in a fresh
    repo). So the probe below runs FIRST and nothing else is attempted. That is
    the same doctrine the old docstring picked for a missing `origin/main`: a
    repo that cannot be compared says so on the keeper's own stdout and stays
    silent. Every other unreadable state -- no commits yet (`HEAD` is not a
    revision), a home that is not a repo, an unparsable count -- lands there
    too. A detached HEAD and a repo mid-rebase or mid-merge are NOT unreadable:
    `HEAD` resolves in all three and the commits it reaches are exactly the
    ones at risk, which is why they are counted rather than excused."""
    rc, refs = _run_text(run, ["git", "for-each-ref", "--count=1",
                               "--format=%(refname)", "refs/remotes/"],
                         cwd=str(home))
    if rc != 0 or not refs.strip():
        print("keeper: git unpushed check unavailable "
              "(no remote-tracking ref to compare against)", file=out)
        return 0, None, None
    rc, text = _run_text(run, ["git", "rev-list", "--count", *UNPUSHED_REVS],
                         cwd=str(home))
    if rc != 0:
        print("keeper: git unpushed check unavailable", file=out)
        return 0, None, None
    try:
        n = int(text.strip())
    except ValueError:
        print("keeper: git unpushed check unavailable (unreadable count)", file=out)
        return 0, None, None
    if n <= 0:
        return 0, None, None
    # The age half must move with the count or the six-hour gate and the
    # fingerprint go stale in a new way, so it asks the SAME rev set. And it
    # takes the MINIMUM rather than the first line of `--reverse`: `git log`
    # orders by commit date subject to a topological constraint, so a skewed
    # clock or a merge of an old local branch can print a younger commit first.
    rc, text = _run_text(run, ["git", "log", "--format=%ct", *UNPUSHED_REVS],
                         cwd=str(home))
    stamps = []
    if rc == 0:
        for line in text.split():
            try:
                stamps.append(float(line))
            except ValueError:
                pass
    oldest = min(stamps) if stamps else None
    return n, oldest, _git_head_ref(home, run)


def _git_head_ref(home, run):
    """What HEAD points at, for the page TEXT only -- never for the count, and
    never a reason to suppress a page. `rev-parse --abbrev-ref HEAD` prints the
    literal string `HEAD` when detached, which reads as nonsense in a page and
    is precisely the state where naming it matters most: nothing but the reflog
    points at that work."""
    rc, text = _run_text(run, ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         cwd=str(home))
    name = text.strip() if rc == 0 else ""
    if not name:
        return None
    return "a detached HEAD" if name == "HEAD" else name


def _count_lines(path):
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def collect(home, *, now, run=subprocess.run, snapshot_fn=fleet.status_snapshot,
            prev_state=None, out=sys.stdout):
    """One observation dict from four read-only sources.

    CLAIM STATE AND GOALS COME FROM `status_snapshot()`, ALWAYS (fix wave 1,
    C1). `sup-status --json`'s `incarnation` projection copies the claim's
    raw `state` key, and only `sup-release` ever WRITES that key -- so a
    perfectly healthy HELD claim projects `state: None` and read `unknown`
    here, which put every live supervisor into the dead-trigger set.
    `_supervisor_tier_snapshot` is the normaliser (`none`/`held`/`released`/
    `unknown`), so it is the source. `sup-status` is still read, for the
    three things the snapshot does not carry: the pending decision, the
    heartbeat age at claim-projection precision, and the claim's session id."""
    home = Path(home)
    prev_state = prev_state or {}
    snap = snapshot_fn()
    sup = snap.get("supervisor") or {}
    status = _sup_status(home, run)
    claim_state = sup.get("state") or "unknown"
    goals_active = bool(sup.get("goals_active"))
    if status is not None:
        incarnation = status.get("incarnation") or {}
        beat = status.get("heartbeat_age_seconds")
        pending = _pending_question(status)
        claim_sid = incarnation.get("session_id")
        released_at = incarnation.get("released_at")
    else:
        beat = sup.get("heartbeat_age_seconds")
        pending = None
        claim_sid = None
        released_at = None
    agents_ok, agents_missing, agent_statuses = _agents(run)
    unpushed, oldest, unpushed_ref = _git_unpushed(home, run, out=out)
    workers = [{"name": w.get("name"), "status": w.get("status"),
                "mail": w.get("mail") or 0, "limit_kind": w.get("limit_kind")}
               for w in (snap.get("workers") or [])]
    # Type-normalise BEFORE the roster lookup (re-review minor 2):
    # `incarnation.get("session_id")` is worker-writable projection data, and
    # a non-str shape (a dict, say) used to reach `claim_sid in agent_sids`
    # RAW -- `in` on a set hashes its operand, and an unhashable value raised
    # `TypeError` straight out of the tick. A dict key lookup hashes its
    # operand the same way, so the normalisation is still load-bearing after
    # C swapped the set for a sid->status mapping. `claim_sid` here is the
    # same normalised value the caller reads back as `obs["claim_sid"]`.
    claim_sid = claim_sid if isinstance(claim_sid, str) and claim_sid else None
    # C (G-K6 wave 1): the observation carries the claim row's own `status`,
    # not merely whether a row exists. `claim_in_roster` and
    # `claim_row_status` are separate keys because "no row" and "a row with
    # no status" are different facts about the world -- the second is a
    # corpse the CLI is still listing -- and `_claim_activity` is the only
    # reader that has to tell them apart. There is no `claim_sid_live` any
    # more: it was never a liveness fact (w61 §5), and leaving the name in
    # place with a new meaning is how the next reader inherits this outage.
    claim_in_roster = claim_sid is not None and claim_sid in agent_statuses
    claim_row_status = agent_statuses.get(claim_sid) if claim_in_roster else None
    return {
        "goals_active": goals_active,
        "claim_state": claim_state,
        "claim_sid": claim_sid,
        "claim_in_roster": claim_in_roster,
        "claim_row_status": claim_row_status,
        "released_at": released_at,
        "heartbeat_age_seconds": beat,
        "pending_decision": pending,
        "agents_ok": agents_ok,
        "agents_missing": agents_missing,
        "registry_ok": bool(snap.get("ok", True)),
        "registry_reason": snap.get("reason"),
        "workers": workers,
        "unpushed": unpushed,
        "oldest_unpushed_ts": oldest,
        "unpushed_ref": unpushed_ref,
        "hook_error_lines": _count_lines(home / "state" / "hook-errors.log"),
        "prev_hook_error_lines": int(prev_state.get("_hook_error_lines", 0) or 0),
    }


# ---------------------------------------------------------------------- tmux

SHELL_COMMANDS = ("sh", "bash", "zsh", "fish", "dash")


def _tmux(run, out, *args):
    """Delegate: `fleet.tmux_command`, labelled `keeper` so the failure line
    on `out` is byte-identical to the one this function printed itself."""
    return fleet.tmux_command(run, out, *args, label="keeper")


def _panes(run, target):
    """[(current command, dead)] for `target`, or None when the window is
    absent (that is what a non-zero `list-panes` means)."""
    rc, text = _run_text(run, ["tmux", "list-panes", "-t", target, "-F",
                               "#{pane_current_command} #{pane_dead}"])
    if rc != 0:
        return None
    panes = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        panes.append((parts[0], len(parts) > 1 and parts[1] == "1"))
    return panes


def window_alive(run, target):
    panes = _panes(run, target)
    return bool(panes) and any(cmd == "claude" and not dead for cmd, dead in panes)


def _window_disposition(panes):
    """Classify `panes` (as returned by `_panes`) into what `ensure_window`
    would do with them, without doing it: `("alive", None)` -- a live claude
    pane, leave it; `("busy", cmd)` -- occupied by something else, leave it
    and report `cmd`; `("create", None)` -- absent, dead, or a bare shell,
    safe to (re)create.

    RECYCLING IS NARROW (I5). `pane_current_command` is one sample of a
    live pane, and `claude` is not what it reads while claude shells out --
    at that instant it reads `git`, `rg`, `node`. Killing the window then
    kills the operator's live interface session mid-turn. So `"create"` is
    returned only when the pane is DEAD or is sitting at a bare shell
    prompt; anything else reads `"busy"`.

    Shared by `ensure_window` (which acts on the verdict) and the `--dry-run`
    path in `main` (which only reports it) so the two cannot drift apart
    (re-review minor 3: `--dry-run` used to print "would create" for a busy
    non-claude pane too, which `ensure_window` refuses to recycle)."""
    if panes is None:
        return "create", None
    if any(cmd == "claude" and not dead for cmd, dead in panes):
        return "alive", None
    cmd, dead = panes[0] if panes else ("", True)
    if not dead and cmd and cmd not in SHELL_COMMANDS:
        return "busy", cmd
    return "create", None


def ensure_window(run, *, session, window, cwd, launch, out=sys.stdout):
    """Create `session:window` when it is absent or provably unusable.

    Returns True only when a `new-window` actually SUCCEEDED (fix wave 1,
    C3 -- it used to return True unconditionally, so a tmux server that was
    gone still read as "created"). The caller treats True as "defer this
    tick's pages" (I6): a freshly launched Claude TUI is not ready to
    receive typed input, and a page typed into its startup is lost."""
    target = f"{session}:{window}"
    panes = _panes(run, target)
    disposition, cmd = _window_disposition(panes)
    if disposition == "alive":
        return False
    if disposition == "busy":
        print(f"keeper: window {target} busy with {cmd}; not recycling", file=out)
        return False
    if panes is not None:
        _tmux(run, out, "kill-window", "-t", target)
    return _tmux(run, out, "new-window", "-d", "-t", session, "-n", window,
                 "-c", cwd, launch)


def page(run, target, text, out=sys.stdout):
    """Type one sanitised line and submit it. Returns whether it landed --
    the caller records dedup state only for a page that did (C3).
    Delegate: `fleet.type_interface_line` with this module's prefix."""
    return fleet.type_interface_line(run, target, text, prefix=PAGE_PREFIX,
                                     out=out, limit=PAGE_TEXT_LIMIT,
                                     label="keeper")


# ---------------------------------------------------------------------- main

def _parser():
    p = argparse.ArgumentParser(prog="fleet_keeper",
                                description="page-only liveness tick for a headless fleet")
    p.add_argument("--once", action="store_true", required=True,
                   help="run one tick and exit (the only mode; a timer supplies cadence)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be paged; touch neither tmux nor state")
    p.add_argument("--fleet-home", default=str(_INSTALL_ROOT))
    p.add_argument("--tmux-session", default="work")
    p.add_argument("--window", default="fleet")
    p.add_argument("--profile", default=None,
                   help="interface profile the window's claude is told to read")
    return p


def main(argv=None, *, run=subprocess.run, now_fn=time.time,
         snapshot_fn=fleet.status_snapshot, out=sys.stdout):
    args = _parser().parse_args(argv)
    home = Path(args.fleet_home).resolve()
    # I3: `--fleet-home` reaches the sup-status subprocess, git's cwd and the
    # state path -- but `fleet.FLEET_HOME` is frozen at IMPORT, so
    # `status_snapshot()` reads whatever home the imported module resolved.
    # A mismatch means half the observation is about one home and half about
    # another, which is worse than no tick at all. Read, never assigned:
    # rebinding it here would make the keeper a second definition of where
    # the fleet lives.
    imported_home = Path(fleet.FLEET_HOME).resolve()
    if imported_home != home:
        print(f"keeper: --fleet-home {home} does not match the imported fleet "
              f"home {imported_home}; refusing", file=out)
        return 1
    profile = Path(args.profile) if args.profile else (
        home / "docs" / "operator" / "server-interface-profile.md")
    launch = ('claude --permission-mode bypassPermissions '
              f'"Read {profile} and follow it exactly."')
    target = f"{args.tmux_session}:{args.window}"
    state_path = home / "state" / "keeper" / "last-page.json"
    now = float(now_fn())

    state = load_state(state_path)
    obs = collect(home, now=now, run=run, snapshot_fn=snapshot_fn,
                  prev_state=state, out=out)
    pages = evaluate(obs, now)
    prev_rules = {k_: v for k_, v in state.items() if not k_.startswith("_")}
    send, rule_state = dedup(pages, prev_rules, now)

    if args.dry_run:
        for p in pages:
            print(f"[dry-run] {p.rule}: {_page_line(p.text)}", file=out)
        # Mirror `ensure_window`'s own verdict (via the same classifier)
        # instead of asking only "is it alive" (re-review minor 3): a busy
        # non-claude pane reads not-alive too, but `ensure_window` refuses
        # to recycle it, so a dry-run that only checked `window_alive` over-
        # reported "would create" for a window it would actually leave alone.
        disposition, cmd = _window_disposition(_panes(run, target))
        if disposition == "busy":
            print(f"[dry-run] window {target} busy with {cmd}; would not recycle",
                  file=out)
        elif disposition == "create":
            print(f"[dry-run] would create {target}: {launch}", file=out)
        return 0

    created = ensure_window(run, session=args.tmux_session, window=args.window,
                            cwd=str(home), launch=launch, out=out)
    if created:
        # I6: nothing is paged into a window created this tick, and the dedup
        # record is left exactly as the previous tick wrote it -- so the next
        # tick, 15 minutes into the new session's life, pages everything that
        # is still true.
        print(f"keeper: created {target}; pages deferred to next tick", file=out)
        rule_state = prev_rules
    else:
        for p in send:
            if page(run, target, p.text, out=out):
                print(f"keeper: paged {p.rule}", file=out)
                continue
            # C3: a page tmux refused was never seen by anyone. Recording it
            # as sent suppressed the rule for the whole 6h re-page window --
            # the fleet's loudest alarm silenced by the failure of the wire
            # that carries it. Carry the previous entry forward (or drop the
            # key) so the next tick tries again.
            print(f"keeper: page NOT delivered: {p.rule}", file=out)
            previous = prev_rules.get(p.rule)
            if previous is None:
                rule_state.pop(p.rule, None)
            else:
                rule_state[p.rule] = previous

    rule_state["_hook_error_lines"] = obs["hook_error_lines"]
    save_state(state_path, rule_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
