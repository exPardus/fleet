#!/usr/bin/env python3
"""fleet keeper -- a page-only liveness timer for a headless fleet.

Runs from a systemd user timer every 15 minutes (`--once`). It OBSERVES
fleet state read-only and TYPES one-line pages into the dedicated tmux
interface window (`work:fleet`), whose Claude session relays them to
Telegram through the ccgram bridge. It never takes `fleet.lock`, never
writes fleet state, and never dispatches a session -- revival is a human
message from the phone (operator ruling 2026-09-08, spec
docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md).

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

HEARTBEAT_STALE_SECONDS = 3600
UNPUSHED_PAGE_SECONDS = 6 * 3600
REPAGE_SECONDS = 6 * 3600
ANOMALOUS_STATUSES = ("dead-suspected", "limited")

PAGE_PREFIX = "KEEPER: "
PAGE_TEXT_LIMIT = 200
# Only the CSI form is matched here; a bare ESC left by any other escape
# shape is dropped by the C0 filter in `_one_line` a line later.
_ANSI_RE = re.compile(r"\x1b\[[0-9;:<=>?]*[ -/]*[@-~]")


def _one_line(text, limit=PAGE_TEXT_LIMIT):
    """Collapse `text` into one printable line of at most `limit` chars.

    Fix wave 1, C4. Every page is typed into a `bypassPermissions` Claude
    session with `tmux send-keys -l`, and the substrings it interpolates --
    a `sup-decision` question, a registry key -- are worker-writable. A
    newline in either becomes a SECOND submitted prompt line, i.e. a
    worker->interface injection channel, and an ANSI run or a 5 000-char
    name makes the page unreadable. So: ANSI stripped, `\\r\\n\\t` and the
    other C0 controls folded to spaces, whitespace collapsed, truncated
    with an ellipsis. Sanitising at DELIVERY (rather than in each rule)
    means a rule added later cannot forget to do it.
    """
    text = _ANSI_RE.sub("", str(text))
    text = "".join(" " if ch < " " or ch == "\x7f" else ch for ch in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def _page_line(text):
    """The exact bytes a page types: `KEEPER: `-prefixed, then one-lined.

    Prefix FIRST, sanitise second (C4's ruling): the prefix is what stops a
    page whose interpolated text begins with `-` from reaching `send-keys`
    as something that could read as a flag, and one-lining afterwards keeps
    the guarantee that the whole delivered line is one line."""
    text = str(text)
    if not text.startswith(PAGE_PREFIX):
        text = PAGE_PREFIX + text
    return _one_line(text)


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
    ride the supervisor-dead page and so reported a read failure as a fact
    about the supervisor (fix wave 1, C2)."""
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None
    if obs.get("claim_state") != "unknown":
        return None
    return Page("claim-unknown", "unknown",
                "KEEPER: supervisor claim unreadable (state unknown). "
                "Report it; do not repair.")


def rule_supervisor_dead(obs, now):
    """Fires on: GOALS active, the roster readable, and either a
    released/absent claim (dead by definition -- no roster condition), or a
    HELD claim whose heartbeat is missing/stale AND whose own session id is
    not in `claude agents --json`.

    Fix wave 1, C2: the identity test is the claim's SESSION ID, not a
    `sup|` name prefix. `claude agents --json` lists ACTIVE sessions only, so
    an idle-between-turns supervisor is absent from it while perfectly alive
    -- fleet's own verdict engine reads roster-absence plus a fresh outcome
    as `idle`, not dead -- and a name join is the weaker proof anyway
    (ai-title can overwrite `name` after a resume). A held claim with a
    FRESH heartbeat never pages, whatever the roster says."""
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None  # cannot tell dead from unlisted; login/missing rules cover it
    state = obs.get("claim_state")
    if state in ("released", "none"):
        reason = f"claim {state}"
    elif state == "held":
        beat = obs.get("heartbeat_age_seconds")
        if beat is not None and beat <= HEARTBEAT_STALE_SECONDS:
            return None
        if obs.get("claim_sid_live"):
            return None
        stale = ("no heartbeat" if beat is None
                 else f"heartbeat {int(beat // 60)} min stale")
        reason = f"{stale}, claim session not in the roster"
    else:
        return None  # `unknown` belongs to rule_claim_unknown
    since = _since(obs)
    head = f"supervisor dead since {since}" if since else "supervisor dead"
    return Page("supervisor-dead", f"{state}:{reason}",
                f"KEEPER: {head} ({reason}). Report state; "
                "await operator before sup-spawn.")


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
    n = obs.get("unpushed") or 0
    oldest = obs.get("oldest_unpushed_ts")
    if n <= 0 or oldest is None:
        return None
    age = now - oldest
    if age < UNPUSHED_PAGE_SECONDS:
        return None
    hours = int(age // 3600)
    return Page("unpushed", f"{n}:{int(oldest)}",
                f"KEEPER: {n} commits unpushed for {hours}h. Push or explain.")


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
    rule_supervisor_dead,
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
    """(ok, missing, session_ids). `claude agents --json` lists the ACTIVE
    sessions; the sids are the identity join C2 replaced the name prefix
    with."""
    rc, out = _run_text(run, ["claude", "agents", "--json"])
    if rc == MISSING_BINARY_RC:
        return False, True, set()
    if rc != 0:
        return False, False, set()
    try:
        rows = json.loads(out)
    except ValueError:
        return False, False, set()
    if not isinstance(rows, list):
        return False, False, set()
    sids = set()
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("sessionId"), str):
            if row["sessionId"]:
                sids.add(row["sessionId"])
    return True, False, sids


def _git_unpushed(home, run, out=sys.stdout):
    """(count, oldest unpushed commit ts). A repo with no `origin/main` --
    or no `origin` at all -- makes `rev-list` exit non-zero; that is "cannot
    tell", not "nothing unpushed", and it must not page (fix wave 1, minor).
    It says so on the keeper's own stdout and returns the silent value."""
    rc, text = _run_text(run, ["git", "rev-list", "--count", "origin/main..main"],
                         cwd=str(home))
    if rc != 0:
        print("keeper: git unpushed check unavailable", file=out)
        return 0, None
    try:
        n = int(text.strip())
    except ValueError:
        return 0, None
    if n <= 0:
        return 0, None
    rc, text = _run_text(run, ["git", "log", "--format=%ct", "--reverse",
                               "origin/main..main"], cwd=str(home))
    first = text.strip().splitlines()[0] if rc == 0 and text.strip() else ""
    try:
        return n, float(first)
    except ValueError:
        return n, None


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
    agents_ok, agents_missing, agent_sids = _agents(run)
    unpushed, oldest = _git_unpushed(home, run, out=out)
    workers = [{"name": w.get("name"), "status": w.get("status"),
                "mail": w.get("mail") or 0, "limit_kind": w.get("limit_kind")}
               for w in (snap.get("workers") or [])]
    return {
        "goals_active": goals_active,
        "claim_state": claim_state,
        "claim_sid": claim_sid if isinstance(claim_sid, str) and claim_sid else None,
        "claim_sid_live": bool(claim_sid) and claim_sid in agent_sids,
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
        "hook_error_lines": _count_lines(home / "state" / "hook-errors.log"),
        "prev_hook_error_lines": int(prev_state.get("_hook_error_lines", 0) or 0),
    }


# ---------------------------------------------------------------------- tmux

SHELL_COMMANDS = ("sh", "bash", "zsh", "fish", "dash")


def _tmux(run, out, *args):
    argv = ["tmux", *args]
    rc, _ = _run_text(run, argv)
    if rc != 0:
        print(f"keeper: tmux failed: {argv}", file=out)
    return rc == 0


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


def ensure_window(run, *, session, window, cwd, launch, out=sys.stdout):
    """Create `session:window` when it is absent or provably unusable.

    Returns True only when a `new-window` actually SUCCEEDED (fix wave 1,
    C3 -- it used to return True unconditionally, so a tmux server that was
    gone still read as "created"). The caller treats True as "defer this
    tick's pages" (I6): a freshly launched Claude TUI is not ready to
    receive typed input, and a page typed into its startup is lost.

    RECYCLING IS NARROW (I5). `pane_current_command` is one sample of a
    live pane, and `claude` is not what it reads while claude shells out --
    at that instant it reads `git`, `rg`, `node`. Killing the window then
    kills the operator's live interface session mid-turn. So the window is
    recycled only when its pane is DEAD or is sitting at a bare shell
    prompt; anything else is left alone and reported."""
    target = f"{session}:{window}"
    panes = _panes(run, target)
    if panes is not None:
        if any(cmd == "claude" and not dead for cmd, dead in panes):
            return False
        cmd, dead = panes[0] if panes else ("", True)
        if not dead and cmd and cmd not in SHELL_COMMANDS:
            print(f"keeper: window {target} busy with {cmd}; not recycling", file=out)
            return False
        _tmux(run, out, "kill-window", "-t", target)
    return _tmux(run, out, "new-window", "-d", "-t", session, "-n", window,
                 "-c", cwd, launch)


def page(run, target, text, out=sys.stdout):
    """Type one sanitised line and submit it. Returns whether it landed --
    the caller records dedup state only for a page that did (C3).

    `Enter` is NOT sent when the literal send failed: that would submit
    whatever the interface session had half-typed in its prompt box."""
    line = _page_line(text)
    if not _tmux(run, out, "send-keys", "-t", target, "-l", line):
        return False
    return _tmux(run, out, "send-keys", "-t", target, "Enter")


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
        if not window_alive(run, target):
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
