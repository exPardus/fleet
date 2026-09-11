#!/usr/bin/env python3
"""Fleet keeper: guard-directed supervisor wakes and interface pages.

The timer runs sup-guard --do for supervisor-stalled. The guard alone decides
liveness, revalidates, and sends an existing body its wake brief. DISPATCH is
an interface page, never a supervisor spawn. Only keeper dedup state is owned
here; the guard/send path may lock and update fleet state. No daemon socket API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT / "bin"))

import fleet  # noqa: E402

Page = namedtuple("Page", "rule fingerprint text")

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


def rule_supervisor_stalled(obs, now):
    """Render the guard verdict; never derive liveness from keeper readings."""
    guard = obs.get("supervisor_guard")
    if not isinstance(guard, dict):
        return Page("supervisor-stalled", "guard-unavailable",
                    "KEEPER: supervisor stalled (guard unavailable). Report state.")
    if guard.get("quiet") or guard.get("sent"):
        return None
    verdict = guard.get("verdict", "PAGE guard unavailable")
    if verdict == "OK":
        return None
    reason = guard.get("reason", "guard unavailable")
    identity = guard.get("body_name") or guard.get("state") or "unknown"
    if reason.startswith("supervisor limited"):
        fingerprint = f"limited:{identity}:{guard.get('limit_reset_at')}:{reason}"
        text = f"KEEPER: {reason}. Report state; respect the reset horizon."
    elif verdict == "DISPATCH":
        fingerprint = f"dispatch:{identity}"
        text = (f"KEEPER: supervisor stalled ({reason}). Report state, then "
                "relaunch with sup-spawn; do not await the operator.")
    else:
        fingerprint = f"page:{identity}:{reason}"
        text = f"KEEPER: supervisor stalled ({reason}). Report state."
    return Page("supervisor-stalled", fingerprint, text)


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
        # The guard has the current supervisor's dedicated alert and horizon.
        # Including it here would re-page a limited body on the worker cadence.
        guard = obs.get("supervisor_guard") or {}
        if w.get("name") and w.get("name") == guard.get("body_name"):
            continue
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
                or (not page.fingerprint.startswith("limited:")
                    and now - float(prev.get("at", 0)) > REPAGE_SECONDS)):
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


def _supervisor_guard(home, run, *, do):
    argv = [sys.executable, str(_INSTALL_ROOT / "bin" / "fleet.py"),
            "sup-guard", "--fleet-home", str(home), "--json"]
    if do:
        argv.append("--do")
    # A keeper is a plain-shell caller, not the session that launched its timer.
    env = {**os.environ, "FLEET_HOME": str(home)}
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    try:
        cp = run(argv, capture_output=True, text=True, timeout=180, env=env)
        data = json.loads(cp.stdout or "")
        if (not isinstance(data, dict) or not isinstance(data.get("verdict"), str)
                or data["verdict"].split(" ", 1)[0] not in {"OK", "WAKE", "DISPATCH", "PAGE"}):
            raise ValueError("invalid guard verdict")
        if cp.returncode:
            raise ValueError(data.get("reason") or "guard action failed")
        if not isinstance(data.get("reason"), str):
            raise ValueError("missing guard reason")
        data["quiet"] = data.get("quiet") is True
        # A preview or a non-confirmed WAKE must never suppress the alarm.
        data["sent"] = bool(do and data["verdict"].startswith("WAKE ")
                            and data.get("sent") is True)
        return data
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"verdict": "PAGE guard unavailable", "reason": f"guard unavailable: {exc}"}


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
    with NO `--all` -- the two spellings are different lists and a claim about
    one is not a claim about the other. Name the spelling beside any count
    taken from it.

    WHAT THE PLAIN SPELLING ACTUALLY OMITS (MEASURED, w63, 2026-09-10T10:56Z,
    18 plain rows against 32 with `--all`). The inherited sentence here said it
    "omits `done`/`failed`/`stopped` rows". That is not what this host does:
    the plain list CONTAINED three `state: "done"` rows, each with a live pid
    and `status: "idle"`. Every one of the 14 rows `--all` added was in a
    terminal state AND carried neither `pid` nor `status` -- their key set is
    exactly `['cwd','id','kind','name','sessionId','startedAt','state']`. So
    the omission is keyed on the PROCESS being gone, not on the state word
    alone, and a terminal-state row hangs around in the plain list for as long
    as its process does.

    THAT IS ALSO THE MECHANISM BEHIND THE 10:16Z FALSE PAGE, and it is worth
    stating where the reader is. A fork-steer's session takes its turn, exits,
    goes `done`, and LEAVES the plain list -- MEASURED on the very body:
    `d605e989...` (an earlier fork of `sup|inc-20260910T075355Z-4f99|
    successor`) was `--all`-only at 10:56Z while its two sibling sids were in
    the plain list, and `ed943460...` -- the CURRENT `session_id` of
    `sup|inc-20260910T041459Z-2382|boot` -- was `--all`-only while both of
    that body's RETIRED sids sat in the plain list as pid-less corpses. A
    reader joining on one sid sees a body appear and disappear; only the union
    sees the body.

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
    missing from the mapping is "no row at all". These are diagnostics;
    sup-guard owns the action decision.

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
    FOUR things the snapshot does not carry: the pending decision, the
    heartbeat age at claim-projection precision, the claim's session id, and
    -- since w63 -- `claim_sids`, the claim-holder body's sid union. The
    snapshot cannot supply that last one either: its worker rows publish no
    sid at all and `snap["supervisor"]` is claim-FILE-only by mandate
    (`_supervisor_tier_snapshot`: "no lock, no roster read, no probe, no
    subprocess"), so there is no sid in `status_snapshot()`'s output to join
    on. MEASURED at `64aa96b`, not assumed."""
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
        published_sids = status.get("claim_sids")
    else:
        beat = sup.get("heartbeat_age_seconds")
        pending = None
        claim_sid = None
        released_at = None
        published_sids = None
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
    # w63: THE JOIN IS THE BODY'S SID UNION, NOT THE CLAIM'S ONE SID.
    # `sup-status --json` publishes `claim_sids` -- the union
    # `session_id` u `retired_sids` of the registry record that carries the
    # claim's holder sid (`fleet.supervisor_claim_sids`). The keeper does NOT
    # read the registry to get it, and that is the point: it stays a narrow
    # reader (three subprocesses and one in-process snapshot), and the union
    # arrives already resolved against the SAME claim whose `session_id` sits
    # beside it in the same JSON, so the two can never be a fork-steer apart.
    #
    # Every member is normalised the way `claim_sid` above is, and for the
    # same reason: this is JSON from another process, `s in agent_statuses`
    # hashes its operand, and an unhashable member would raise `TypeError`
    # straight out of the tick. A non-list `claim_sids` degrades to the empty
    # union rather than raising.
    #
    # `sid_union_ok` records whether a union was PUBLISHED, not whether it is
    # bigger than one sid: a body that has never been fork-steered has a
    # perfectly good one-element union. `null` means the resolution failed
    # (unreadable registry, no claim, an older fleet), and the page says so
    # rather than making a claim about a body it could only see one session
    # of.
    union = set()
    if isinstance(published_sids, list):
        union = {s for s in published_sids if isinstance(s, str) and s}
    sid_union_ok = bool(union)
    if claim_sid:
        union.add(claim_sid)
    # C (G-K6 wave 1) carried the claim row's own `status`, not merely whether
    # a row existed, because "no row" and "a row with no status" are different
    # facts about the world -- the second is a corpse the CLI is still
    # listing. w63 keeps that distinction and widens its SUBJECT: `claim_rows`
    # maps every union sid that HAS a row to that row's status-or-None, so
    # "no row" is now absence from this mapping and a corpse is a `None`
    # value. The guard owns liveness; these rows remain diagnostic observations.
    #
    # The keys `claim_in_roster`/`claim_row_status` are GONE rather than
    # redefined, exactly as `claim_sid_live` was deleted rather than kept with
    # a new meaning (w61 §5): a name whose meaning silently widened from one
    # session to a whole body is how the next reader inherits this outage.
    claim_rows = {sid: agent_statuses[sid]
                  for sid in sorted(union) if sid in agent_statuses}
    return {
        "goals_active": goals_active,
        "claim_state": claim_state,
        "claim_sid": claim_sid,
        "claim_sids": sorted(union),
        "sid_union_ok": sid_union_ok,
        "claim_rows": claim_rows,
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


def _registered_pane_details(home, run, out=None):
    """Return ``(pane, reason)`` for the registered pane.

    A registration is useful only while its pane is running Claude itself.
    ``pane_current_command`` is deliberately checked in addition to
    ``pane_dead``: after Claude exits, tmux leaves the pane at the user's
    shell prompt and paging that pane is paging into a dead interface.
    """
    if out is None:
        out = sys.stdout
    try:
        pane = (home / "state" / "interface-pane").read_text(
            encoding="utf-8").strip()
    except FileNotFoundError:
        return None, "absent"
    if not (pane.startswith("%") and pane[1:].isascii()
            and pane[1:].isdecimal()):
        raise ValueError("state/interface-pane must contain a tmux pane ID")
    rc, text = _run_text(run, ["tmux", "list-panes", "-a", "-F",
                               "#{pane_id} #{pane_current_command} #{pane_dead}"])
    if rc != 0:
        raise ValueError("tmux pane scan failed")
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == pane:
            if len(parts) < 3 or parts[-1] not in ("0", "1"):
                raise ValueError("tmux pane liveness unreadable")
            command = parts[1]
            if command != "claude":
                # Keep the known shell set as the negative case used by the
                # window classifier. Other commands are equally unsafe as a
                # registered interface, so they receive the same fallback.
                print(f"keeper: registered pane {pane} runs {command}, not claude; "
                      "falling back to window", file=out)
                return None, ("shell" if command in SHELL_COMMANDS else "command")
            if parts[-1] == "1":
                return None, "dead"
            return pane, "claude"
    return None, "gone"


def registered_pane(home, run, out=None):
    """Return the registered live Claude pane ID, or None if unusable.

    The interface writes this registration on launch AND manual resume.
    An unreadable registration or failed scan is not evidence of absence;
    raise so this tick can report the uncertainty without selecting a pane.
    """
    return _registered_pane_details(home, run, out=out)[0]


def registered_session(home):
    """Return a non-tmux interface session registration, if present."""
    path = Path(home) / "state" / "interface-session"
    try:
        sid = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not sid or any(ch in sid for ch in "\r\n"):
        raise ValueError("state/interface-session must contain a session id")
    return sid


def report_interface_candidates(run, target, pane, out):
    """Warn once per tick if the named window is a different candidate.

    Listing pane IDs distinguishes a second window from the registered
    pane's own window (including splits). Neither candidate is recycled.
    """
    rc, text = _run_text(run, ["tmux", "list-panes", "-t", target, "-F",
                               "#{pane_id}"])
    if rc == 0 and pane not in text.split():
        print("keeper: two interface candidates", file=out)


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
                                description="liveness tick for a headless fleet")
    p.add_argument("--once", action="store_true", required=True,
                   help="run one tick and exit (the only mode; a timer supplies cadence)")
    p.add_argument("--dry-run", action="store_true",
                   help="print pages/wakes; touch neither tmux, daemon nor state")
    p.add_argument("--fleet-home", default=str(_INSTALL_ROOT))
    p.add_argument("--tmux-session", default="work")
    p.add_argument("--window", default="fleet")
    p.add_argument("--profile", default=None,
                   help="interface profile the window's claude is told to read")
    return p


def main(argv=None, *, run=subprocess.run, now_fn=time.time,
         snapshot_fn=fleet.status_snapshot, out=sys.stdout):
    parser = _parser()
    args = parser.parse_args(argv)
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
        home / "skills" / "fleet" / "SKILL.md")
    # `env -u CLAUDE_CODE_OAUTH_TOKEN`: a long-lived token in the keeper's
    # environment is inference-only and blocks Remote Control, so the launched
    # interface must fall back to the `claude auth login` credentials. Measured
    # 2026-09-11: the token is present in the environment inherited by the
    # keeper (not exported from ~/.zshenv), so unsetting it at the launch is the
    # only place that reliably strips it.
    launch = ('env -u CLAUDE_CODE_OAUTH_TOKEN '
              'claude --permission-mode bypassPermissions '
              f'"Read {profile} and follow it exactly."')
    target = f"{args.tmux_session}:{args.window}"
    state_path = home / "state" / "keeper" / "last-page.json"
    now = float(now_fn())
    interface_state = (home / "state" / "interface").is_dir()

    state = load_state(state_path)
    obs = collect(home, now=now, run=run, snapshot_fn=snapshot_fn,
                  prev_state=state, out=out)
    # Run independently of pane availability; a failed action remains a page.
    obs["supervisor_guard"] = _supervisor_guard(home, run, do=not args.dry_run)
    if args.dry_run:
        print(f"[dry-run] {obs['supervisor_guard']['verdict']}", file=out)
    elif obs["supervisor_guard"].get("sent"):
        print("keeper: supervisor wake sent", file=out)
    pages = evaluate(obs, now)
    prev_rules = {k_: v for k_, v in state.items() if not k_.startswith("_")}
    interface_notice = None

    registration_path = home / "state" / "interface-pane"
    pane_reason = "absent"
    try:
        pane, pane_reason = _registered_pane_details(home, run, out=out)
    except (OSError, ValueError) as exc:
        if not interface_state:
            print(f"keeper: interface pane unavailable ({exc}); "
                  "falling back to window", file=out)
        else:
            interface_notice = ("KEEPER: interface registration unavailable "
                                f"({exc}); page delivered to {target}")
            print(interface_notice, file=out)
        pane = None
        pane_reason = "unknown"
    if pane:
        report_interface_candidates(run, target, pane, out)
        target = pane
    elif interface_state and pane_reason == "absent":
        try:
            interface_session = registered_session(home)
        except (OSError, ValueError) as exc:
            interface_notice = ("KEEPER: interface registration unavailable "
                                f"({exc}); page delivered to {target}")
            print(interface_notice, file=out)
            interface_session = None
        if interface_session and interface_notice is None:
            print(f"KEEPER: interface session {interface_session} is registered "
                  f"outside tmux; page delivered to {target}", file=out)
            interface_notice = ("KEEPER: interface session is registered "
                                f"outside tmux; page delivered to {target}")
        elif interface_notice is None:
            interface_notice = ("KEEPER: interface is not registered; "
                                f"page delivered to {target}")
            print(interface_notice, file=out)

    if interface_notice:
        if pages:
            first = pages[0]
            pages[0] = Page(first.rule, first.fingerprint,
                            f"{first.text} [{interface_notice}]")
        else:
            pages = [Page("interface-status", interface_notice, interface_notice)]
    send, rule_state = dedup(pages, prev_rules, now)

    if args.dry_run:
        for p in pages:
            print(f"[dry-run] {p.rule}: {_page_line(p.text)}", file=out)
        if pane:
            print(f"[dry-run] interface pane {pane}; would not create a window",
                  file=out)
            return 0
        if interface_notice:
            print(f"[dry-run] {interface_notice}; would not create a window",
                  file=out)
            return 0
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

    created = False if (pane or interface_notice) else ensure_window(
        run, session=args.tmux_session, window=args.window,
        cwd=str(home), launch=launch, out=out)
    if created:
        # A shell/dead registered pane is stale state. The newly launched
        # session must register itself; retaining the old ID lets the next
        # tick select the wrong pane again. These fallback cases still emit
        # their page through the window path (the no-registration path keeps
        # the normal startup deferral).
        if registration_path.exists():
            try:
                registration_path.unlink()
            except OSError as exc:
                print(f"keeper: could not remove stale interface pane "
                      f"({exc})", file=out)
        if pane_reason in {"shell", "command", "dead"}:
            for p in send:
                if page(run, target, p.text, out=out):
                    print(f"keeper: paged {p.rule}", file=out)
                    continue
                print(f"keeper: page NOT delivered: {p.rule}", file=out)
                previous = prev_rules.get(p.rule)
                if previous is None:
                    rule_state.pop(p.rule, None)
                else:
                    rule_state[p.rule] = previous
        else:
            # I6: nothing is paged into a window created this tick, and the
            # dedup record is left exactly as the previous tick wrote it.
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
