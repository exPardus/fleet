#!/usr/bin/env python3
"""claude-fleet statusline (docs/specs/terminal-surface.md §4.3).

Renders one line under the operator's input box in Claude Code. Installed
into ~/.claude/settings.json by `fleet init --statusline` -- a plugin cannot
ship a statusLine (plugin settings.json accepts only `agent` and
`subagentStatusLine`).

Contract, all four points load-bearing:
  * imports fleet.status_snapshot() rather than shelling out, so registry
    schema knowledge lives in exactly one module (invariant 9);
  * no lock, no PID probe, no subprocess, no write (D1);
  * never asserts liveness it did not probe for -- a stale bucket carries a
    greyed age suffix (D2);
  * exits 0 on every path, printing nothing on error. This is the statusline
    analogue of invariant 2 (exit-0 hooks): a traceback here would render
    under the input box on every refresh.

WHICH home it reads is answered by `resolve_blob_home()` below (multi-fleet
slice d): the session id Claude Code puts in the stdin blob is run through
`fleet.resolve_home()`, so a machine with two fleets renders each session's OWN
fleet. A machine with one home short-circuits before the lookup and is
byte-identical to the pre-slice statusline. None of the four points above move:
the resolution takes no lock, probes nothing, writes nothing, and its failure
mode is the default home rather than a blank line.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# THE IMPORT-TIME CONFLATION, SPLIT (multi-fleet slice 0, docs/specs/
# multi-fleet.md "Slice 0"). This used to read `$FLEET_HOME` and insert
# `$FLEET_HOME/bin` on sys.path -- using the DATA plane to locate the CODE
# plane. Point FLEET_HOME at a data-only home and that insert names a directory
# with no `fleet.py` in it; the import survived only because a script's own
# directory is already sys.path[0], i.e. by an accident this file did not state
# and an `import fleet_statusline` (not a run) does not get.
#
# The install is where THIS FILE is, always, and cannot be moved by an env var.
# The home is fleet.py's business: it re-reads $FLEET_HOME itself, so nothing
# here needs to know about it.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT / "bin"))

import fleet  # noqa: E402

PREFIX = "[fleet]"
STALE_AFTER_SECONDS = 300

# The rendered line is PURE ASCII by construction -- no glyphs, no box drawing.
# A Windows console defaults to cp1252 and cannot encode the block/geometric
# glyphs an earlier design used; print() then raised UnicodeEncodeError, the
# exit-0 guard swallowed it, and the operator got a permanently BLANK
# statusline with no way to tell why. A fallback renderer only papered over
# that: colour and word are already the whole signal, so the glyphs bought
# nothing but width and a failure mode. `test_the_rendered_line_is_pure_ascii`
# is the invariant.
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
# Grey is RESERVED for `dead`. Nothing else on the line may use it: the moment a
# second field is grey, "greyed out" stops meaning "inert" and the operator has
# to read the words to find out what is going on.
_GREY = "\x1b[90m"
_NAME = "\x1b[1;94m"       # bold bright blue -- the fleet nameplate
_AGE = "\x1b[33m"          # yellow: a clock, distinct from every status hue
# The command tier (three-tier §3). Bold bright white: the line's first field
# after the nameplate, and the one whose absence is itself the news.
_SUP = "\x1b[1;97m"
# Reserved for the one condition three-tier exists to prevent: more than one
# live supervisor-shaped body. Bold red, distinct from `over_budget`'s plain
# bright red, because this is not a spend state -- it is a command state.
_ALARM = "\x1b[1;91m"
# Distinct hue per status, bright variants so they separate on a dark terminal.
_STATUS_COLOR = {
    "working": "\x1b[92m",       # bright green  -- burning tokens
    "idle+mail": "\x1b[95m",     # bright magenta -- waiting on its mail
    "idle": "\x1b[96m",          # bright cyan   -- alive, unengaged
    "attached": "\x1b[35m",      # magenta       -- an operator holds it
    "limited": "\x1b[93m",       # bright yellow -- parked on a plan limit
    # Spend exhausted, not merely parked -- red, which `dead` gave up for grey.
    "over_budget": "\x1b[91m",   # bright red
    "over_ceiling": "\x1b[31m",  # red
    "dead": _GREY,               # inert: never competes with a live bucket
}
_LABEL = {
    "working": "work", "idle+mail": "mail", "idle": "idle",
    "attached": "att", "limited": "lim", "over_budget": "budget",
    "over_ceiling": "ceiling", "dead": "dead",
}
# Fixed reading order, loudest first. Deliberately NOT sorted by count: a
# count-sorted line reshuffles between refreshes, so the operator has to re-read
# it every time, and a pile of dead workers outranks the one that is working.
_ORDER = ["working", "idle+mail", "attached", "limited",
          "over_budget", "over_ceiling", "idle"]


def _fmt_age(seconds) -> str:
    if seconds is None:
        return "?"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.0f}h"


def _reset_clock(iso) -> str:
    """'2026-07-09T14:20:00Z' -> '14:20'. Any other shape -> the raw value."""
    if not iso:
        return ""
    try:
        return fleet._parse_iso(iso).strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return str(iso)


def _bucket(worker: dict) -> str:
    if worker["status"] == "idle" and worker["mail"]:
        return "idle+mail"
    return worker["status"]


# --- the command tier ------------------------------------------------------
#
# three-tier §3 splits one flat roster into three tiers, and the flat render
# hid the split: a supervisor body is a registry row, so a fleet with one
# worker and fourteen retired supervisor husks rendered as fifteen workers.
# Worse, the field that actually decides whether anything can be dispatched --
# does someone hold the claim -- was not on the line at all.
#
# Two rules, both deliberate:
#   * LIVE supervisor-shaped bodies leave the worker buckets. They are the
#     command tier, counted separately, and never inflate `work`/`idle`.
#   * DEAD ones stay in the grey tail. A corpse is a corpse whatever tier it
#     died in, and splitting the tail would put a second grey field on the
#     line, which `test_grey_is_reserved_for_dead` forbids for good reason.

_SUP_STATE_LABEL = {"held": "sup held", "released": "sup released",
                    "none": "sup none", "unknown": "sup ?"}


def _supervisor_chunk(snap: dict, paint, stale_after: int):
    """The tier field, or None when there is nothing to say.

    Silent when GOALS.md is dormant/absent: a fleet with no supervisor doctrine
    running should not carry a permanent `sup none` scold on every refresh.
    """
    sup = snap.get("supervisor")
    if not isinstance(sup, dict) or not sup.get("goals_active"):
        return None
    state = sup.get("state") or "unknown"
    chunk = paint(_SUP_STATE_LABEL.get(state, "sup ?"), _SUP)
    # D2 applied to the claim: an aged heartbeat is exactly the evidence a
    # seizure would one day rest on, so the operator sees it before fleet does.
    # `released` carries no heartbeat BY DESIGN (claim-nonce §6.3) -- rendering
    # an age there would invent staleness out of a correct stand-down.
    age = sup.get("heartbeat_age_seconds")
    if state == "held" and age is not None and age > stale_after:
        chunk += paint(f" {_fmt_age(age)}", _AGE)
    return chunk


def _live_supervisor_bodies(workers) -> int:
    return sum(1 for w in workers
               if w.get("tier") == "supervisor" and w.get("status") != "dead")


def _bucket_order(buckets) -> list:
    """Fixed order for the buckets present, unknown statuses last, `dead` never
    among them -- it is collapsed into the tail counter by the caller."""
    known = [b for b in _ORDER if b in buckets]
    unknown = sorted(b for b in buckets if b not in _ORDER and b != "dead")
    return known + unknown


def render_statusline(snap: dict, color: bool = True,
                      stale_after: int = STALE_AFTER_SECONDS) -> str:
    def paint(text, code):
        return f"{code}{text}{_RESET}" if color and code else text

    # A bracketed, brightly-coloured nameplate -- the operator's eye lands on
    # the row's owner before reading a single word of it. Foreground only: a
    # reverse-video block reads as a hard UI chrome element next to Claude
    # Code's own rows, which are all plain bracketed labels.
    head = paint(PREFIX, _NAME)

    if not snap.get("ok"):
        if snap.get("reason") == "not_initialized":
            return f"{head}: not initialized"
        # P1-13: the rename makes absence ambiguous, so `not initialized` was
        # what a just-quarantined fleet printed too -- byte-identical to a box
        # that never ran `fleet init`, on the one surface the operator reads
        # continuously. `status_snapshot` distinguishes the two now; this is a
        # render, and renders nothing new of its own.
        if snap.get("reason") == "quarantined":
            return f"{head}: registry quarantined"
        return f"{head}: registry unreadable"

    workers = snap["workers"]
    if not workers:
        return f"{head}: no workers"

    buckets: dict = {}
    for w in workers:
        # A live supervisor body is the command tier, not a worker. A dead one
        # rejoins the flat roster for the grey tail -- see the block comment
        # above `_supervisor_chunk`.
        if w.get("tier") == "supervisor" and w.get("status") != "dead":
            continue
        buckets.setdefault(_bucket(w), []).append(w)

    # The tier fields lead, and they are kept OUT of `parts` until the worker
    # buckets have decided whether the fleet is all-dead: `sup held` is not a
    # live worker, and letting it satisfy the "did anything render" test would
    # silently retire the `no live workers` message the moment GOALS went live.
    lead = []
    sup_chunk = _supervisor_chunk(snap, paint, stale_after)
    if sup_chunk:
        lead.append(sup_chunk)
    bodies = _live_supervisor_bodies(workers)
    if bodies > 1:
        # Never two live supervisors over one GOALS.md. The line says so before
        # the operator has to go looking, and it says the COUNT because "2" and
        # "9" are different incidents.
        lead.append(paint(f"{bodies} bodies", _ALARM))

    parts = []
    for bucket in _bucket_order(buckets):
        group = buckets[bucket]
        label = _LABEL.get(bucket, bucket)
        count = f"{_BOLD}{len(group)}" if color else str(len(group))
        chunk = paint(f"{label} {count}", _STATUS_COLOR.get(bucket, ""))

        # D2: a bucket where every worker is stale carries the freshest age, so
        # the line never presents an unverified status as freshly observed. The
        # age gets its own hue -- dimming it (the old behaviour dimmed the whole
        # chunk) put grey-on-dark text on the operator's screen, and grey now
        # means dead.
        stalest = [w["stale_seconds"] for w in group if w["stale_seconds"] is not None]
        if stalest and min(stalest) > stale_after:
            chunk += paint(f" {_fmt_age(min(stalest))}", _AGE)

        if bucket == "limited":
            resets = {_reset_clock(w["limit_reset_at"]) for w in group}
            clock = f"resets {sorted(resets)[0]}" if all(resets) else "reset?"
            if any(w["resume_eligible"] for w in group):
                # invariant 1: a view flags resume-eligibility, it never launches.
                clock = "resume-eligible"
            chunk += paint(f" {clock}", _STATUS_COLOR["limited"])
        parts.append(chunk)

    # `dead` is inert -- it cannot be steered, only respawned or cleaned. It gets
    # a grey tail counter rather than a bucket of its own, so eleven dead workers
    # never outshout the one that is actually running.
    dead = len(buckets.get("dead", ()))
    if not parts:
        parts = [paint("no live workers", _STATUS_COLOR["dead"])]
    if dead:
        parts.append(paint(f"+{dead} dead", _STATUS_COLOR["dead"]))

    # NO COST FIELD (removed 2026-07-27, operator's call). It was a running
    # total the operator cannot act on: under the Max-20x cap doctrine the plan
    # limits spend, fleet enforces no dollar ceiling, and native dispatch
    # carries no cost field at all -- so the number was increasingly a sum over
    # rows that report nothing. `fleet status` still totals it for anyone who
    # wants it; the statusline is for what you would act on.
    #
    # Two spaces between fields: wide enough to group `label count age` as one
    # unit without a separator glyph, which would cost width and ASCII purity.
    return "  ".join([head] + lead + parts)


def _want_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return True


# --- §5 resolution, on a view (multi-fleet slice d) ------------------------
#
# `docs/specs/multi-fleet.md`, the paragraph above §6:
#
#   **Statusline**: blob sid -> same lookup; single-home short-circuit; words,
#   exit 0; resolver pure-function; capture experiment gates the slice.
#
# WHAT MOVED, IN ONE SENTENCE: the home this file reads used to be whatever
# `fleet.FLEET_HOME` computed at import (env, else the install root), and is now
# the home whose registry CLAIMS the session Claude Code is rendering for.
#
# THE GATE, RE-DRIVEN BEFORE ANY OF THIS WAS WRITTEN (docs/lanes/w50-d.md §1):
# 13 statusline invocations of a real `--bg` session, captured to a file and
# read back from the file. `session_id` is a top-level `str` on 13/13, is
# byte-identical to the `CLAUDE_CODE_SESSION_ID` the statusline child itself
# carries on 13/13, and is in the FIRST render's smaller key set as well as
# every later one. Slice (d) stands on that measurement and on nothing else.
#
# THE ORDER IS NOT RE-SPELLED HERE. `fleet.resolve_home()` is §5's five steps as
# a pure function and its own header names this file as one of its four callers;
# a fifth spelling of the order is *"the exact defect the four standalone
# `_fleet_home()` copies already demonstrate"*. What this module owns is the
# three things §5 does not: where the sid comes from on THIS surface, when not
# to ask at all, and what a VIEW renders where a verb would refuse.

#: `resolve_blob_home()`'s verdicts.
#:
#: `HOME_SINGLE` is the short-circuit: one home on this machine, so nothing was
#: looked up and nothing moved. It is deliberately also the ERROR value -- a
#: resolution that dies degrades to "render the default home exactly as the
#: shipped statusline always did", never to a blank line and never to a word the
#: operator cannot act on.
HOME_SINGLE = "single_home"
HOME_LOOKUP = "lookup"        # a member home claims this session -- home moved
HOME_DEFAULT = "default"      # steps 3/4 answered; the global already IS that
HOME_NONE = "no_home"         # §5 step 5's terminus
HOME_AMBIGUOUS = "ambiguous"  # two+ member homes claim this session


def blob_session_id(payload) -> str:
    """The blob's session id, or `""`. A PURE FUNCTION, AND IT NEVER RAISES.

    This is the slice's one genuinely new pure function and the only place the
    statusline knows anything about the payload's shape. Four degenerate inputs
    are real and all four answer `""`: unparseable JSON, a non-dict top level, a
    missing `session_id`, and a non-string one. `""` is not `None` on purpose --
    it is what `lookup_home_for_sid` already treats as *"nobody asked"*, so the
    empty case needs no second spelling downstream.

    IT DOES NOT FALL BACK TO `CLAUDE_CODE_SESSION_ID`, and that is a decision
    rather than an omission. The env var carries the same bytes today -- MEASURED
    13/13 -- but §5 step 2's input on this surface is *"blob sid"*, and a second
    evidence source that agrees today is a second thing to disagree tomorrow, on
    a surface whose failures are swallowed by an exit-0 guard."""
    try:
        blob = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(blob, dict):
        return ""
    sid = blob.get("session_id")
    if not isinstance(sid, str):
        return ""
    return sid.strip()


def population_is_multi_home(pop) -> bool:
    """Is this machine in multi-fleet territory? THE SHORT-CIRCUIT'S PREDICATE.

    Delegates to `fleet._multi_fleet_population_is_live`, which is the shipped
    answer `apply_resolved_home` already gates the terminus on. The two callers
    hold different records -- that one has a `lookup_home_for_sid` result, this
    one has only a `resolution_population`, because HAVING RUN THE LOOKUP IS
    EXACTLY WHAT THE SHORT-CIRCUIT AVOIDS -- so this adapts the keys rather than
    re-deriving the rule. `test_the_short_circuit_agrees_with_fleets_own_
    predicate` drives both shapes through the predicate and requires them to
    agree, so the adapter cannot drift into a second opinion.

    NOT A PERFORMANCE FEATURE. The lookup costs 1.35 ms inside a ~560 ms
    statusline process (measured, w49-dcap §4.1 and re-measured by w50-d §3), so
    skipping it saves 0.2 % of nothing. It exists because §5's arming paragraph
    binds the whole feature to *"with a determinate population of <2:
    byte-identical to today"*, and a single-home machine that rendered `[fleet]:
    no home` -- or an ambiguity, or a home resolved from a sid rather than from
    `$FLEET_HOME` -- would not be byte-identical to today."""
    return bool(fleet._multi_fleet_population_is_live({
        "list_ok": pop["list_ok"],
        "population": pop["homes"],
        "legacy": pop["legacy"],
    }))


def resolve_blob_home(payload, population=None, install=None) -> dict:
    """§5's order, driven from the blob. NEVER RAISES; NEVER WRITES.

    Returns `{"state", "home", "sid", "hits"}` where `home` is a `Path` ONLY for
    `HOME_LOOKUP` -- steps 3 and 4 ARE `fleet.FLEET_HOME`'s own import-time
    computation, so handing them back would be a no-op in production and would
    overwrite the suite's monkeypatch in every test. `apply_resolved_home` makes
    the same split for the same reason: this moves the home only when something
    NAMED one.

    THE AMBIGUITY BRANCH COSTS A SECOND LOOKUP, DELIBERATELY. `resolve_home`
    raises §5 step 2's two-plus refusal rather than returning it, because for a
    verb it is not a verb-class decision. A view cannot re-raise it -- `main`'s
    exit-0 guard would swallow it into a permanently blank line -- so it is
    caught, and the hit COUNT the word needs is re-read from step 2 directly.
    One extra ~1.4 ms read, on the branch that cannot happen on a single-home
    machine at all.

    EVERY FAILURE DEGRADES TO `HOME_SINGLE`. See that constant."""
    unresolved = {"state": HOME_SINGLE, "home": None, "sid": "", "hits": 0}
    try:
        pop = (fleet.resolution_population(install) if population is None
               else population)
        if not population_is_multi_home(pop):
            return dict(unresolved)

        out = dict(unresolved)
        out["sid"] = sid = blob_session_id(payload)
        try:
            res = fleet.resolve_home(flag=None, sid=sid, population=pop,
                                     install=install)
        except fleet.FleetCliError:
            look = fleet.lookup_home_for_sid(sid, population=pop, install=install)
            out["state"], out["hits"] = HOME_AMBIGUOUS, len(look["hits"])
            return out

        if res["step"] == "lookup":
            out["state"], out["home"] = HOME_LOOKUP, Path(res["home"])
        elif res["step"] is None:
            out["state"] = HOME_NONE
        else:
            out["state"] = HOME_DEFAULT
        return out
    except BaseException:  # noqa: BLE001 -- a statusline never surfaces a traceback
        return dict(unresolved)


def _paint_terminus(line: str, color: bool) -> str:
    """Paint the nameplate and nothing else, so the WORDS are exactly the
    constant they came from and `plain(line)` round-trips to it."""
    if not color:
        return line
    head, sep, tail = line.partition(":")
    return f"{_NAME}{head}{_RESET}{sep}{tail}"


def render_home_terminus(decision, color: bool = True):
    """The word a VIEW renders where a verb refuses, or `None` for "render the
    fleet row normally".

    §5 step 5 splits the surface exactly once -- *"mutating verbs refuse with the
    named remedy, and views render `[fleet]: no home` and exit 0"* -- and the
    statusline is on the view side of that split, so it has NO refusal path and
    prints no remedy. The terminus text is `fleet.NO_HOME_LINE`, the constant §5
    is quoted into, never retyped here (`test_the_terminus_text_is_not_a_retyped_
    literal`).

    THE AMBIGUITY WORD NAMES NO HOME, AND THAT IS THE REFUSAL CONTRACT TAKEN
    SERIOUSLY RATHER THAN DROPPED. §5's rule is *"Refusals print facts + the
    `fleet homes` view, never a paste-ready command with a chosen home"*. The
    `fleet homes` view is multi-line and this surface is one line under the
    operator's input box, refired after every assistant message -- so embedding
    it is not available, and the honest one-line form of *"facts, and no chosen
    home"* is the COUNT: it says how many homes claim this session and leaves
    every one of them unnamed. Naming one would be choosing; naming all of them
    would be a paragraph. The full view is one `fleet homes` away and every
    verb-tier surface already embeds it.

    TOLERANT OF A HAND-BUILT RECORD, like `fleet.resolution_provenance` and for
    the same reason: unit tests hand it dicts, and a renderer that raised on a
    missing key would be a view that fails."""
    state = (decision or {}).get("state")
    if state == HOME_NONE:
        return _paint_terminus(fleet.NO_HOME_LINE, color)
    if state == HOME_AMBIGUOUS:
        hits = (decision or {}).get("hits")
        count = hits if isinstance(hits, int) and hits > 1 else "?"
        return _paint_terminus(f"{PREFIX}: home ambiguous ({count})", color)
    return None


# --- statusline chaining ---------------------------------------------------
#
# Claude Code allows exactly ONE `statusLine` command. An operator who already
# runs another statusline (ccusage, caveman, ...) would otherwise have to
# choose. `fleet init --statusline --chain` captures the incumbent command
# into state/statusline-chain.json; this script runs it, prints its rows, then
# prints fleet's row beneath.
#
# This is the ONE place fleet's statusline spawns a subprocess, and it is a
# deliberate, opt-in exception to the D1 no-subprocess-on-the-hot-path rule:
# the delegate is a command the operator was already paying for on every
# refresh. Fleet's own row still costs zero subprocesses. A delegate that
# fails, hangs, or writes garbage is DROPPED -- fleet's row always prints.

DELEGATE_TIMEOUT_SECONDS = 4


def _chain_path() -> Path:
    return Path(fleet.state_dir()) / "statusline-chain.json"


def _load_delegates() -> list:
    try:
        data = json.loads(_chain_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    delegates = data.get("delegates") if isinstance(data, dict) else None
    if not isinstance(delegates, list):
        return []
    return [d["command"] for d in delegates
            if isinstance(d, dict) and isinstance(d.get("command"), str) and d["command"].strip()]


def _run_delegate(command: str, payload: str) -> list:
    """Run one delegate statusline, return its output rows. Never raises."""
    try:
        proc = subprocess.run(
            command,
            shell=True,  # the command is a shell string straight out of settings.json
            input=payload,
            capture_output=True,
            text=True,
            timeout=DELEGATE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _delegate_rows(payload: str) -> list:
    rows = []
    for command in _load_delegates():
        rows.extend(_run_delegate(command, payload))
    return rows


def _stdout_can_encode(text: str) -> bool:
    """Whether sys.stdout's encoding can carry `text`. A cp1252 console cannot
    encode the fleet glyphs; printing them there raises UnicodeEncodeError,
    which the exit-0 guard would swallow into a permanently blank statusline."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def main() -> int:
    try:
        # Claude Code passes a session JSON blob on stdin. Fleet needs none of
        # it, but a chained delegate might, so it is captured and forwarded
        # verbatim. Read it in full so the writer never blocks on a full pipe.
        try:
            payload = sys.stdin.read()
        except (OSError, ValueError):
            payload = ""

        # Prefer real UTF-8 output; fall back to ASCII glyphs when the console
        # cannot carry them rather than dying silently.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass

        # §5, BEFORE ANY READ (multi-fleet slice d). ONE RENDER, ONE HOME: the
        # chain file lives at `state/statusline-chain.json`, i.e. INSIDE a home,
        # so resolving after the delegates ran would read the operator's
        # delegate out of one home and the roster out of another. On a
        # single-home machine this is a no-op by construction.
        decision = resolve_blob_home(payload)
        if decision["home"] is not None:
            fleet.FLEET_HOME = decision["home"]

        # Delegates print above fleet's row. A delegate that fails, hangs, or
        # emits unprintable bytes is dropped -- it must never cost fleet's row.
        #
        # AND THE CONVERSE, ADDED WITH SLICE (d): fleet failing to resolve a
        # home must never cost the DELEGATE its row. The delegate is the
        # operator's own statusline, captured from the one machine-global
        # `statusLine` entry Claude Code allows; it has nothing to do with which
        # fleet home this session belongs to, so it runs on every path including
        # the terminus.
        try:
            for row in _delegate_rows(payload):
                if _stdout_can_encode(row):
                    print(row)
        except BaseException:  # noqa: BLE001
            pass

        # Fleet's own row is pure ASCII, so no console encoding can reject it
        # and there is no fallback renderer to get wrong. At the terminus and at
        # an ambiguity there is no home to read a roster from, so the word takes
        # the row's place -- one line either way, exit 0 either way.
        line = render_home_terminus(decision, color=_want_color())
        if line is None:
            line = render_statusline(fleet.status_snapshot(), color=_want_color())
        print(line)
    except BaseException:  # noqa: BLE001 -- a statusline never surfaces a traceback
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
