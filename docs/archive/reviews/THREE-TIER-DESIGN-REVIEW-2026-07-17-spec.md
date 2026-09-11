# Three-tier command — SPEC-COHERENCE lens design review (M-D gate)

**Target:** `docs/specs/three-tier-command.md` (DRAFT PROPOSAL, 2026-07-16, authored by the acting supervisor session).
**Lens:** constructive / spec-coherence. This is one half of a dual-lens gate; a hostile break-lens review runs in parallel and owns failure-scenario invention. This review hunts contradictions against the binding contract set and completeness against existing obligations.
**Reviewer:** `md-review-spec` worker, 2026-07-17.
**Receipt pin:** every fenced receipt below is `# at c1277bd` (`git rev-parse --short HEAD` on `fleet-impl` at review start). Line numbers drift; function names are the durable anchors.
**Authority set:** `docs/SPEC.md` v3 (spec of record) · `docs/specs/native-substrate.md` (G-row contract) · `supervisor/GOALS.md` · `skills/fleet/supervisor.md` · `docs/specs/autoclean.md`.
**Status line:** deliberately absent. The manager adjudicates both lenses; a review does not promote its own target.

**Lens discipline note.** The known failure mode of THIS lens is C0 (4/5 "Approved" verdicts issued against claims the break lens then proved BREAK). Every draft claim below was therefore treated as unproven until receipted, including the ones that read as obviously true. Two of the four "what exists today" bullets survived intact; the load-bearing ones did not.

---

## 1. Claim-by-claim audit — the draft's "What exists today (M-C reality)" section (+ the load-bearing claims its proposal rests on)

16 claims audited. **CONFIRMED: 8. FALSE: 6. PARTLY-FALSE: 2.**

### C1 — "Two tiers, merged at the top. The session the human talks to IS the supervisor (holds the claim, runs the beats, dispatches workers, does merges and reviews)." — **CONFIRMED**

The claim is architecturally accurate and the code agrees that a claim holder is identified only by a session id, with no notion of who is attached to it.

```
# at c1277bd
$ grep -n "def current_caller_session" -A 9 bin/fleet.py
580:def current_caller_session() -> str | None:
581-    """The Claude Code session id of whoever is running this CLI, or None when
582-    fleet is run by a human from a plain shell.
...
587-    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
588-    return sid or None
```

Nothing distinguishes a human-attached session from a `--bg` one at the claim layer. The merge is doctrinal, not enforced — which is exactly what makes the split cheap in principle. **This claim is the draft's strongest.**

### C2 — "Supervisor identity already survives bodies (GOALS.md + JOURNAL.md + INCARNATION claim + seize/handoff rituals, spec §4)." — **CONFIRMED**

```
# at c1277bd
$ grep -n "def goals_path\|def incarnation_path\|def handshake_path\|def supervisor_journal_append\|def supervisor_claim_decision\|def cmd_sup_handoff_begin" bin/fleet.py
6391:def goals_path() -> Path:
6395:def incarnation_path() -> Path:
6399:def handshake_path() -> Path:
6509:def supervisor_journal_append(kind: str, inc: str, sid: str, body: str) -> None:
6560:def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
6826:def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
```

All four artifacts and both rituals exist. See §3 for the citation defect (`spec §4` resolves to the pivot spec, not SPEC v3 §12).

### C3 — "What does NOT exist: a body that acts without a human-attached session driving it." — **FALSE**

Two counter-receipts. First, autoclean: an OS scheduler drives a fleet-mutating command with no session attached at all.

```
# at c1277bd
$ grep -n "AUTOCLEAN_TASK_NAME = \|def _autoclean_task_command" -A 4 bin/fleet.py
4617:AUTOCLEAN_TASK_NAME = "claude-fleet-autoclean"
4618-AUTOCLEAN_INTERVAL_HOURS_DEFAULT = 6
--
4906:def _autoclean_task_command() -> str:
...
4913-    F2 (adversarial review, HIGH): FLEET_HOME is embedded EXPLICITLY as an
4914-    argv flag -- Task Scheduler runs with no operator environment, so
```

Second, and more directly on point: `sup-handoff-begin` already dispatches an *unattended* supervisor successor session that boots, writes HANDSHAKE, polls, and takes the claim — with no human attached to it.

```
# at c1277bd
$ sed -n '6802,6820p' bin/fleet.py
6802:def _render_successor_task(successor_inc: str, old_inc: str) -> str:
...
6807:    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
...
6816:3. Poll every ~30s (up to 10 minutes): py -3.13 {fleet_py} sup-status --json
6817:   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
```

**Why this matters beyond pedantry:** the draft treats "unattended supervisor body" as the thing it must invent. It already half-exists, in a code path the draft never mentions, built on a *different* dispatch mechanism than the one the draft proposes to reuse (see C11). The ratified spec must reconcile `sup-spawn` with `sup-handoff-begin` or it ships a second, divergent supervisor-dispatch path.

### C4 — "Workers are native `--bg` sessions: durable, survive host restarts (proven 2026-07-16 — two host process deaths mid-campaign, zero loss)" — **PARTLY-FALSE (stale as of 2026-07-17)**

The 2026-07-16 observation is not disputed, and `--bg` dispatch is receipted:

```
# at c1277bd
$ grep -n "def dispatch_bg" bin/fleet.py
6167:def dispatch_bg(name: str, cwd: Path, prompt: str, mode: str, ...
```

But the substrate moved under the draft. Per the 2026-07-17 finding (owned by `md-contract`, not re-derived here): claude 2.1.212 made the native daemon **transient** — on-demand start at dispatch, idle-exit ~5 s after the last client, no service install. "Durable, survive host restarts" was observed against a *persistent* daemon. Whether a `--bg` session's on-disk state still resurrects on next dispatch under a transient daemon is **UNOBSERVED at 2.1.212** and is not this review's to settle. The claim is now unpinned, and the draft states it as proven fact.

**Required of the ratified spec:** state its daemon-lifecycle assumption explicitly rather than inheriting a 2.1.207-era one silently. See §3.7 for the full list of daemon-persistence-dependent passages the draft leans on.

### C5 — "but they only run when a turn is dispatched. Nothing self-continues." — **PARTLY-FALSE**

`ScheduleWakeup` is a confirmed in-session self-rearming primitive, and SPEC v3 names it as the supervisor's heartbeat primitive:

> `docs/SPEC.md` §12: "Heartbeat primitive: in-session `ScheduleWakeup` self-rearm, confirmed real (G7); `claude stop` permanently kills a scheduled wake — a stopped supervisor never self-resumes."

> `docs/specs/native-substrate.md` G7: "**CONFIRMED.** `ScheduleWakeup(delaySeconds, prompt, reason)` is a real in-session self-rearming tool: 17 beats observed across two runs at ~173s mean cadence... session context (`cache_read_input_tokens`) provably continuous across beats — not a fresh process per beat."

Something *does* self-continue; it is fragile (G7: a 429 silently kills the loop because the turn never reaches the re-arm), which is a fine reason to prefer an external scheduler — but that is a *robustness* argument the draft does not make. As written, the claim contradicts a CONFIRMED G-row. The draft's scheduler proposal is materially strengthened by citing G7's 429-kills-the-loop sub-finding instead of denying G7 exists.

### C6 — "The autoclean scheduled-task plumbing (`fleet init --autoclean`, M-C) is the first OS-scheduler → fleet-command bridge." — **CONFIRMED**

```
# at c1277bd
$ grep -n "def _install_autoclean_task\|def autoclean_task_install" bin/fleet.py
330:    def autoclean_task_install(self, task_name: str, command: str,
371:    def autoclean_task_install(self, task_name: str, command: str,
4958:def _install_autoclean_task(interval_hours, force: bool) -> None:
```

Sole OS-scheduler bridge in the codebase; "first" holds.

### C7 — "It generalizes." — **FALSE** (the draft's single most load-bearing unproven claim)

`_install_autoclean_task` parameterizes exactly two things: `interval_hours` and `force`. Task name, command, and ownership predicate are all hard-bound to autoclean.

```
# at c1277bd
$ sed -n '4958,4960p;4995,4996p' bin/fleet.py
4958:def _install_autoclean_task(interval_hours, force: bool) -> None:
4959:    if interval_hours is None:
4960:        interval_hours = AUTOCLEAN_INTERVAL_HOURS_DEFAULT
--
4995:    ok, msg = PLATFORM.autoclean_task_install(AUTOCLEAN_TASK_NAME, command, interval_hours)
4996:    if not ok:
```

`AUTOCLEAN_TASK_NAME` is a module constant read directly from the function body — not an argument. The command is likewise constant-folded:

```
# at c1277bd
$ sed -n '4915,4918p' bin/fleet.py
4915:    py = Path(sys.executable).resolve()
4916:    script = _autoclean_script_path()
4917:    home = Path(FLEET_HOME).resolve()
4918:    return f'"{py}" "{script}" autoclean --fleet-home "{home}"'
```

The verb `autoclean` is a literal inside `_autoclean_task_command()`. A `--supervisor-beat` variant needs a different verb, a different task name, and a different interval default. **As written today, a second variant is a copy-paste fork, not a clean extension.** The refactor is small (thread `task_name` + `command` + `interval` through, rename to `_install_scheduled_task`) — but it is *work the draft's "the delta is one spawn verb, one scheduled-task variant, and doctrine" budget does not account for*, and it touches a function whose guards were hardened by an adversarial fix wave (F2/F3/F4/N1). Refactoring it is not free.

**Worse — the ownership predicate does not survive generalization.** `_autoclean_task_is_ours` distinguishes fleet's task from a foreign task *by fleet.py path only*:

```
# at c1277bd
$ sed -n '4949,4956p' bin/fleet.py
4949:def _autoclean_task_is_ours(command: str) -> bool:
4950:    """F4: ownership = the existing task runs OUR fleet.py -- the exact
4951:    resolved script path, slash- and case-normalized (Windows paths carry
4952:    both variances through schtasks XML round-trips). Never a substring
4953:    like 'autoclean': a foreign C:/tools/autoclean.exe task must refuse."""
4954:    ours = str(_autoclean_script_path()).replace("\\", "/").lower()
4955:    return ours in (command or "").replace("\\", "/").lower()
```

With two fleet tasks on one machine, this predicate returns True for *both*, because both commands contain the same fleet.py path. It can no longer answer "is this task the one I am about to install?" — only "is this task fleet's at all". The F4 guard was designed against a one-task-per-fleet.py assumption that a second variant silently violates. **This is a MUST-fix delta, not a nit** (§4, D3).

### C8 — "holding the claim via the existing sup-boot ritual inside its first turn" — **FALSE, and fatally so**

The ritual's sid source resolves fine for a `--bg` session — this half of the concern raised in the task brief is a false alarm, and I record it as such:

```
# at c1277bd
$ sed -n '6662,6665p' bin/fleet.py
6662:    caller_sid = getattr(args, "sid", None) or current_caller_session()
6663:    if not caller_sid:
6664:        raise FleetCliError("sup-boot: caller session unknown -- run from a Claude "
6665:                            "session or pass --sid")
```

`_worker_env`'s strip does **not** break this. It strips `CLAUDE_CODE_SESSION_ID` from the environment of the `claude --bg` *dispatch subprocess*, not from inside the resulting worker session:

```
# at c1277bd
$ sed -n '999,1007p' bin/fleet.py
 999-
1000:    CLAUDE_CODE_SESSION_ID is STRIPPED (§5.1 provenance): the child `claude`
1001:    stamps its own, and an inherited one would make a worker running
1002:    `fleet kill` look exactly like the manager that spawned it -- so a worker
1003:    could quietly retire its siblings with no confirmation."""
1004:    env = dict(os.environ)
1005:    env.pop("CLAUDE_CODE_SESSION_ID", None)
1006:    env["FLEET_WORKER"] = name
1007:    return env
```

The docstring says the quiet part: *"the child `claude` stamps its own"*. G4 confirms it empirically — `CLAUDE_CODE_SESSION_ID`, unset in the dispatching shell, "is set by the daemon to the child's **own** sid — never a stale/foreign one", with a negative control. So `sup-boot` inside a `--bg` worker's first turn reads its own sid correctly, and the ritual claims. **Claim C8's first turn works.**

**It is the second turn that is fatal.** The claim is keyed on a session id:

```
# at c1277bd
$ sed -n '6689,6695p' bin/fleet.py
6689:            if verdict == "claim":
6690:                inc = mint_incarnation_id()
6691:                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
6692:                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
6693:                                   "claimed_via": "fresh"})
```

and every later supervisor verb re-verifies the caller against that stored sid:

```
# at c1277bd
$ sed -n '6722,6738p' bin/fleet.py
6722:def _require_claim_holder(sid_override=None):
6723:    """(claim, caller_sid) iff the caller holds the claim; FleetCliError
6724:    otherwise. Enforces spec §4's journal single-writer rule at the only
6725:    write chokepoint. Caller MUST already hold fleet_lock."""
...
6733:    if caller != claim.get("session_id"):
6734:        raise FleetCliError(
6735:            f"caller sid {caller} does not hold the claim (holder: "
6736:            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
6737:            f"the journal is single-writer, claim-holder-only (spec §4)")
```

But the draft's beat mechanism is `fleet send supervisor "beat"`, and `send` to an **idle** worker is a fork-steer that **mints a new sid** (RATIFIED G2(b)). The restamp updates the registry record and nothing else:

```
# at c1277bd
$ sed -n '5896,5903p' bin/fleet.py
5896:    old_sid = record["session_id"]
5897:    if old_sid is not None:
5898:        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
5899:    record["session_id"] = new_sid
5900:    record["native_short_id"] = short_id
5901:    record["last_dispatch_at"] = now_iso()
5902:    record["turns"] = record.get("turns", 0) + 1
```

`_restamp_after_steer` touches `record` only. **`supervisor/INCARNATION` is not in its blast radius, and no other code path restamps the claim's `session_id` outside `sup-boot`/`sup-handoff-complete`.**

The sequence is deterministic, not hypothetical:

1. `sup-spawn` → supervisor worker boots, `sup-boot` claims, `INCARNATION.session_id = S0`. Worker goes idle.
2. Scheduled task fires `fleet send supervisor "beat"`. Worker is idle ⇒ fork-steer ⇒ new sid `S1`; registry restamped to `S1`; `INCARNATION.session_id` still `S0`.
3. The beat turn runs in session `S1`. It calls `fleet sup-checkpoint "beat: nothing to do"` → `_require_claim_holder` compares `S1` against `S0` → **`FleetCliError`: caller sid does not hold the claim.** Every `sup-checkpoint` and `sup-heartbeat` from this body fails, forever.
4. The heartbeat therefore never refreshes again.
5. Recovery by re-running `sup-boot` **does not work either**, and fails in the worst available way. `supervisor_claim_decision` sees holder `S0` absent from the roster (retired) but the heartbeat still fresh (< 3600 s):

```
# at c1277bd
$ sed -n '6585,6589p' bin/fleet.py
6585:    age = (now - beat).total_seconds()
6586:    if age > stale_seconds:
6587:        return ("seize", f"holder roster-gone, heartbeat stale ({age:.0f}s > {stale_seconds:.0f}s)")
6588:    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
6589:                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")
```

→ **`freeze`, exit 3, "PAGE THE OPERATOR"**. The never-seize-on-ambiguity rule — correct and load-bearing — fires against a supervisor that is alive and well, because a fork looks exactly like the G9 daemon-restart ambiguity it was written to catch. The supervisor pages a human on its own first beat.

6. After 3600 s of enforced silence the claim goes stale and the *next* beat seizes its own claim, journaling a `SEIZED` entry. Steady state: **the supervisor seizes itself once an hour, forever**, and `supervisor/JOURNAL.md` — the append-only identity record — fills with false seizure evidence.

**This is the review's central finding.** The draft's exact words are *"holding the claim via the existing sup-boot ritual"* and *"No new substrate: ... claim rituals ... all shipped"*. The claim rituals as shipped are **incompatible with a body whose sid changes every beat**, and the draft's own chosen beat mechanism changes the sid every beat. The per-body claim nonce the M-D ledger lists as a separate candidate is not an adjacent nice-to-have — **it is a hard prerequisite of the supervisor-as-worker tier, and the draft does not name it once.**

### C9 — "hook write boundary allows outcome records today, not mailbox writes" — **FALSE**

The sanctioned list's item (a) is literally mailbox writes:

> `docs/SPEC.md` §8: "**Hook write boundary (the sanctioned list, v2.3 item (d) carried forward).** Hooks NEVER write the registry or `events.jsonl`. Hooks MAY write, and only: (a) `mailbox\<sid>.md` + its `.claimed.<pid>` rename; (b) `state\hook-errors.log` (append-mode, best-effort, no lock); (c) their own worker's journal, via PostCompact only; (d) their own worker's terminal-outcome record, via the Stop hook only."

Mailbox writes are item (a), sanctioned, and shipped — `posttooluse_mailbox.py` and `stop_mailbox.py` do exactly this. The draft inverts the list and then proposes "a sanctioned-list amendment" to fix a restriction that does not exist. **The proposed amendment is unnecessary as scoped, and the real obstacle is elsewhere** — which means the draft's stated design question is aimed at the wrong target and would be "resolved" without touching the actual blocker.

The genuine obstacles, which the draft does not identify:

- **(a) is same-sid by construction, not by wording.** Items (c) and (d) say "their own worker's"; (a) does not, because in every shipped hook the `<sid>` *is* the hook's own session. A worker's Stop hook writing `mailbox/<supervisor-sid>.md` is a **cross-session** write — a genuinely new category the sanctioned list has never had to rule on. That is the amendment worth debating, and the draft does not pose it.
- **The Stop hook cannot resolve the supervisor's sid without violating its own standalone rule.** SPEC v3 §8 on `stop_outcome.py`: *"Standalone stdlib, never imports `fleet.py`, never blocks, exits 0 on every path."* Confirmed:

```
# at c1277bd
$ grep -rn "import fleet\|sys.path" bin/hooks/stop_outcome.py
(no matches; the only "mailbox" hit is a comment at line 10)
```

  The supervisor's current sid lives in `supervisor/INCARNATION`. To enqueue a reconcile mail the hook must locate FLEET_HOME, read and parse INCARNATION, and re-derive the mailbox path — duplicating `incarnation_path()`/`read_incarnation()` inside a hook that is forbidden from importing them. That is real coupling the "no new substrate" budget omits.
- **And the sid it reads is stale-by-design** — per C8, `INCARNATION.session_id` is exactly the field the fork-steer beat leaves pointing at a retired session. The hook would enqueue mail to a dead mailbox. The two findings compound.

### C10 — "same schtasks pattern as autoclean, same install guards (N1 lessons apply verbatim)" — **PARTLY-FALSE / see C7**

The pattern is reusable; the *function* is not, and "verbatim" is wrong in one specific place. `_marker_guard_problems` is genuinely shared and genuinely generic — the docstring says so explicitly:

```
# at c1277bd
$ sed -n '4921,4932p' bin/fleet.py
4921:def _marker_guard_problems() -> list:
4922:    """N1: the home-guard subset that protects GLOBAL machine state (the
4923:    ~/.claude/fleet-home marker): the resolved home being a linked git
4924:    worktree, or an existing marker that already points elsewhere. Shared
4925:    by `cmd_init`'s marker stamp -- which must evaluate these BEFORE
4926:    writing anything, or a worktree init repoints the marker and thereby
4927:    defeats the very marker-mismatch guard the autoclean install relies
4928:    on -- and by `_install_autoclean_task` (which adds its own
4929:    script-location check on top). Deliberately EXCLUDES that script
4930:    check: a sandboxed/relocated home with no .git file and no
4931:    conflicting marker is a legitimate marker target."""
```

So the N1 guards *do* apply verbatim — that half of C10 is CONFIRMED, and it is the strongest piece of the draft's reuse argument. **But the F3/F4 ownership guard does not** (C7): `_autoclean_task_is_ours` cannot distinguish two fleet-owned tasks, and the N1 ordering fix (guards-before-writes in `cmd_init`) is written against a single `--autoclean` flag whose refusal semantics — *"with `--autoclean` a guard problem refuses the whole init"* (autoclean.md D-command-surface) — must now be defined for a second, independently-flagged task. Does `--supervisor-beat` with a guard problem refuse the whole init, including a co-passed `--autoclean`? The draft is silent; the ratified spec must not be.

### C11 — "No new substrate: durable sessions, mailbox, fork-steer, claim rituals, and the scheduler bridge all shipped in M-B/M-C. The delta is one spawn verb, one scheduled-task variant, and doctrine." — **FALSE**

This is the draft's thesis and the claim that most needs the receipt it lacks. Each conjunct:

| Component | Verdict |
|---|---|
| durable sessions | unpinned at 2.1.212 (C4) |
| mailbox | CONFIRMED shipped |
| fork-steer | shipped — and **actively destroys the claim** it is proposed to carry (C8) |
| claim rituals | shipped, but **sid-keyed and incompatible with the beat** (C8) |
| scheduler bridge | shipped but **not parameterized** (C7) |

And the delta is larger than three items, because **supervisor dispatch does not go through the dispatch choke point today.** SPEC v3 §6 states:

> "Every native launch — spawn, fork-steer, resume-limited, respawn — funnels through one choke point"

`cmd_sup_handoff_begin` hand-rolls its own argv and does not appear in that list:

```
# at c1277bd
$ sed -n '6867,6879p' bin/fleet.py
6867:    name = f"sup|{successor_inc}|successor"
6868:    argv = [exe, "--bg", "-n", name]
6869:    if getattr(args, "model", None):
6870:        argv += ["--model", args.model]
6871:    if getattr(args, "permission_mode", None):
6872:        argv += ["--permission-mode", args.permission_mode]
6873:    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
6874:    try:
6875:        proc = run(argv, cwd=str(FLEET_HOME), capture_output=True, text=True,
6876:                   encoding="utf-8", errors="replace", timeout=120)
```

Consequences, all unremarked by the draft:

- **No `--settings`** ⇒ today's supervisor successor sessions run with **no fleet hooks at all**: no mailbox injection (PostToolUse), no drain-or-block (Stop), no outcome record (Stop), no PostCompact journal. `fleet send supervisor` could not deliver mid-turn mail to such a session even if a record existed. The draft's *entire* beat-delivery design — both the event-driven and the time-driven arm — presumes a hooked session. **`sup-spawn` must route through `dispatch_bg`**, which is a real substrate delta, not doctrine.
- **No `--add-dir`** ⇒ SPEC §6: *"`--add-dir` pre-authorizes exactly `tasks_dir()` (least privilege): the task file lives outside the worker's cwd, and under any non-bypass mode the first Read would otherwise hang forever on an unapprovable headless permission prompt."* The successor task file is written to `state_dir()`, not `tasks_dir()`; `sup-handoff-begin --permission-mode` accepts any mode, so a non-bypass successor can hang on its first Read. Pre-existing defect, inherited by any design that copies this path.
- **No registry record** ⇒ `fleet send supervisor` **fails today**, before any of C8's problems are reached:

```
# at c1277bd
$ sed -n '3244,3248p' bin/fleet.py
3244:    with fleet_lock():
3245:        data = load_registry()
3246:        if args.name not in data["workers"]:
3247:            raise FleetCliError(f"unknown worker: {args.name!r}")
```

- **No `_worker_env`** ⇒ the successor dispatch does not stamp `FLEET_WORKER`, so the SessionStart manager briefing is **not** suppressed in supervisor sessions (SPEC §14 / D5). A supervisor-as-worker spawned via `dispatch_bg` *would* get `FLEET_WORKER` stamped — quietly changing supervisor session behavior in a way the draft never considers.

**Verdict: the delta is a supervisor-dispatch unification, a claim-nonce mechanism, a scheduled-task parameterization, a cross-session hook-write ruling, and doctrine.** That is a milestone, which is fine — M-D is a milestone. But the draft's cheapness argument is the reason it is being fast-tracked, and the argument does not survive contact with the code.

### C12 — "It reads `sup-status --json` + journal tail, never worker transcripts, never code. It holds NO claim." — **CONFIRMED**

`cmd_sup_status` is pure file-read: `read_incarnation` + `read_handshake` + `supervisor_goals_active` + a flag-file `.exists()`. No roster fetch, no `fleet.lock`, no write — it satisfies the SPEC §14 view doctrine (*"a view ... never takes `fleet.lock`, never probes anything live, never writes ... the snapshot path also never fetches the roster"*) even though it is not formally listed as a view.

```
# at c1277bd
$ sed -n '6770,6786p' bin/fleet.py
6770:    claim = read_incarnation()
6771:    hs = read_handshake()
...
6778:    info = {
6779:        "goals_active": supervisor_goals_active(),
6780:        "incarnation": claim,
6781:        "heartbeat_age_seconds": beat_age,
6782:        "handshake": hs,
6783:        "abort_flag": handoff_abort_flag_path().exists(),
6784:        "nag": supervisor_status_line(),
6785:    }
```

The interface tier can poll this for cents. **This is the draft's second-strongest claim** and the part of the design most worth keeping intact.

### C13 — "hands them to the supervisor via `fleet send supervisor @brief.md`" — **CONFIRMED (mechanism), blocked (preconditions)**

The `@file` syntax works on `send`:

```
# at c1277bd
$ sed -n '3242,3243p' bin/fleet.py
3242:    message = _read_task_arg(args.message)
--
$ sed -n '1724,1733p' bin/fleet.py
1724:def _read_task_arg(task: str) -> str:
1725:    """`@file` task syntax (SPEC §5): a task string starting with `@` names
1726:    a file whose contents are the task text."""
1727:    if task.startswith("@"):
1728:        path = Path(task[1:])
```

The file is read by `fleet.py` at send time and composed into the mailbox/task body, so no `--add-dir` grant is needed for the brief — a genuine (if accidental) strength of the design, and worth stating in the ratified spec so it is not "fixed" later. Blocked only on C11 (`supervisor` must be a registry worker) and C8.

### C14 — reserved-name collision for `supervisor` — **CONFIRMED SAFE, but unreserved**

There is no reserved-name list anywhere in the codebase:

```
# at c1277bd
$ grep -n "RESERVED" bin/fleet.py
(no matches)
```

`supervisor` is a legal worker name — `NAME_RE` accepts it and the only F6 refusal is uuid-shaped names:

```
# at c1277bd
$ sed -n '472,473p;483,499p' bin/fleet.py
472:NAME_RE = re.compile(r"^[a-z0-9-]+$")
--
483:def validate_name(name: str, existing=()) -> None:
484:    """Raise ValueError unless name matches [a-z0-9-]+ and isn't in `existing`.
...
496:    if not name or not NAME_RE.match(name):
497:        raise ValueError(f"invalid worker name {name!r}: must match [a-z0-9-]+")
498:    if _SID_SHAPE_RE.match(name):
```

**No filesystem collision exists.** The supervisor soul lives under `FLEET_HOME/supervisor/`:

```
# at c1277bd
$ sed -n '6387,6400p' bin/fleet.py
6387:def supervisor_dir() -> Path:
6388:    return FLEET_HOME / "supervisor"
...
6395:def incarnation_path() -> Path:
6396:    return supervisor_dir() / "INCARNATION"
```

while a worker named `supervisor` would own `state/journals/supervisor.md`, `state/tasks/supervisor.md`, `state/outcomes/supervisor.jsonl`, `logs/archive/supervisor/` — disjoint roots, no path collides with `supervisor/GOALS.md` or `supervisor/JOURNAL.md`. The F6 keyspace argument (names vs sids) does not apply here.

**But safe-by-accident is not safe-by-contract, and two live hazards follow from the absence of a reservation:**

1. **Nothing stops an operator from `fleet spawn supervisor --dir <some project>`** as an ordinary worker, on any project, at any time — silently occupying the name the three-tier design depends on, with `cwd` pointing somewhere the supervisor must never act. The ratified spec needs an actual reserved-name check at the `validate_name` choke point (where F6 already lives), not a convention.
2. **Two worker journals named "supervisor" will be confused by humans and by future code.** `state/journals/supervisor.md` (worker journal, respawn carry-forward, freely rewritten) vs `supervisor/JOURNAL.md` (append-only, single-writer, claim-holder-only, git-tracked, the identity record). Disjoint paths, near-identical names, opposite write disciplines. The ratified spec should name the worker something the filesystem cannot confuse (`sup-body`) or state the two-journal distinction explicitly and loudly.

### C15 — "**Workers** — unchanged. Respawn-fresh doctrine already binding." — **FALSE**

Workers are not unchanged, because the *provenance* of every worker changes when its spawner is a forking supervisor. `spawned_by` is compared against the caller's live sid:

```
# at c1277bd
$ sed -n '1910,1918p' bin/fleet.py
1910:def _worker_is_foreign(record: dict, caller: str | None) -> bool:
1911:    """True when this session did not spawn the worker.
1912-
1913:    An UNKNOWN owner (`spawned_by` absent -- every record written before this
1914:    field existed) counts as foreign: the guard fails toward asking."""
1915:    owner = record.get("spawned_by")
1916:    if not owner:
1917:        return True
1918:    return owner != caller
```

and SPEC v3 §4 fixes `spawned_by` as **spawn-immutable**: *"`mode`/`cwd`/`model`/`setting_sources`/`token_ceiling`/`spawned_by` are recorded at spawn and re-passed by every later launch path"*; §15 adds *"immutable across respawn"*.

So: the supervisor spawns worker `w` at sid `S0` ⇒ `w.spawned_by = S0`. The next beat forks the supervisor to `S1`. Now `_worker_is_foreign(w, S1)` → `S0 != S1` → **True**. Every `kill`/`clean`/`respawn` against **its own workers** refuses without `--yes`:

```
# at c1277bd
$ sed -n '1951,1956p' bin/fleet.py
1951:    detail = ", ".join(f"{n} ({_describe_owner(records.get(n, {}))})" for n in foreign)
1952:    raise DestructiveActionRefused(
1953:        f"refusing to {action} {len(foreign)} worker(s) this session did not spawn: {detail}. "
1954:        f"Re-run with --yes to confirm. (A worker you spawned needs no confirmation.)"
1955:    )
```

The guard's threat model is stated as *"an over-helpful agent, especially one under `bypassPermissions` where no permission prompt is ever shown"* (@1935-1937) — which is **precisely** the background supervisor the draft proposes (see the draft's own "Permission mode" hazard: *"needs bypass in the fleet repo"*). Two bad outcomes, pick one: the supervisor is blocked on its own fleet every beat, or it learns to pass `--yes` reflexively and the destructive guard is dead for the one actor it was written to constrain. **The draft's "workers — unchanged" is the sentence that hides this.** Any claim-nonce design MUST address `spawned_by` continuity across supervisor forks in the same stroke — same root cause as C8 (sid-as-identity vs fork-mints-new-sid), second independent blast radius.

### C16 — "the supervisor respawns/handoffs on the existing 300–500k band without losing the human thread (it never had it)" — **CONFIRMED (band), UNSPECCED (respawn)**

The band is real and operator-set:

> `skills/fleet/supervisor.md`: "Trigger band (operator-set 2026-07-14): BEGIN handoff at ~300k tokens of context; hard-latest at 500k. Never ride to the compaction wall."

But "respawns/**handoffs**" conflates two different things. Handoff exists. **Supervisor *respawn* does not** — `_cmd_respawn_native` operates on registry records, and today's supervisor is not one (C11). Under the draft it would become one, at which point `fleet respawn supervisor` is suddenly a live verb that fresh-dispatches the claim holder with no `--resume` and no claim transfer — bypassing `sup-handoff-begin/complete` entirely and leaving `INCARNATION` pointing at a stopped sid. **A new hazard the draft creates and does not mention.** See §4 D5.

---

## 2. Contradiction list vs the binding contract set

Exact quotes, both sides.

### X1 — fork-steer vs. the sid-keyed claim (**BLOCKING**)

- **Draft:** "a scheduled task (`fleet init --supervisor-beat N`) runs `fleet send supervisor \"beat\"` every N hours"
- **Draft:** "holding the claim via the existing sup-boot ritual inside its first turn"
- **SPEC v3 §9:** "**Idle steering = fork-steer (RATIFIED G2(b)).** No CLI channel injects a prompt into an existing idle daemon session; `claude --bg --resume <sid>` **forks** — new sid, full transcript carried. Fleet adopts the fork as the worker's new canonical identity"
- **SPEC v3 §12:** "`supervisor/INCARNATION` (gitignored), written only under `fleet.lock` ... carrying incarnation id, sid, and a heartbeat"
- **Code (`_require_claim_holder` @6733):** `if caller != claim.get("session_id"): raise FleetCliError(...)`

An idle supervisor + a `send` beat = a new sid every beat; the claim is keyed on a sid nothing restamps. Full failure sequence at C8. **Irreconcilable as drafted.**

### X2 — fork-steer vs. spawn-immutable `spawned_by` (**BLOCKING**)

- **Draft:** "**Workers** — unchanged."
- **SPEC v3 §4:** "**Spawn-immutable fields:** `mode`/`cwd`/`model`/`setting_sources`/`token_ceiling`/`spawned_by` are recorded at spawn and re-passed by every later launch path"
- **SPEC v3 §15:** "`spawned_by` records the spawner's `CLAUDE_CODE_SESSION_ID` ... immutable across respawn. `kill`/`clean`/`respawn` refuse a foreign worker (differing or unknown owner) without `--yes`"

A forking supervisor's own workers become foreign to it on the next beat. Detail + receipts at C15.

### X3 — "no new substrate" vs. the §6 dispatch choke point (**BLOCKING**)

- **Draft:** "No new substrate: durable sessions, mailbox, fork-steer, claim rituals, and the scheduler bridge all shipped in M-B/M-C."
- **SPEC v3 §6:** "Every native launch — spawn, fork-steer, resume-limited, respawn — funnels through one choke point"
- **Code (`cmd_sup_handoff_begin` @6867-6876):** hand-rolled `argv = [exe, "--bg", "-n", name]`, no `--settings`, no `--add-dir`, no `_worker_env`, no registry record, `run(argv, ...)` directly.

Supervisor dispatch is the one native launch that does **not** funnel through `dispatch_bg`. SPEC §6's "every" is inaccurate as written (a spec-vs-code defect worth filing on its own), and the draft's reuse budget assumes a unification that has not happened. Detail at C11.

### X4 — hook write boundary, inverted (**MED**)

- **Draft:** "hook write boundary allows outcome records today, not mailbox writes — needs a sanctioned-list amendment"
- **SPEC v3 §8:** "Hooks MAY write, and only: (a) `mailbox\<sid>.md` + its `.claimed.<pid>` rename; ... (d) their own worker's terminal-outcome record, via the Stop hook only."

The list is inverted; the proposed amendment addresses a non-existent restriction while the real one (cross-session writes; `stop_outcome.py`'s no-import-fleet rule) goes unnamed. Detail at C9.

### X5 — `--supervisor-beat` vs. the portability directive (**BLOCKING for M-D scope**)

- **Draft:** "a scheduled task (`fleet init --supervisor-beat N`) ... same schtasks pattern as autoclean"
- **SPEC v3 header [PRESCRIPTIVE], 2026-07-17:** "everything must be multi-platform — Windows, macOS, and Linux ... New features ship with all-OS support through the platform adapter (invariant 8, §16), or with an explicit `UnsupportedPlatformError` seam plus a tracked gap — never with silent Windows-only assumptions."
- **SPEC v3 §16 invariant 8:** "Per the 2026-07-17 portability directive (header), the adapter's POSIX side must reach parity — cron/launchd for autoclean, a POSIX attach path — and **a raising `_PosixPlatform` is a tracked gap, not an accepted end state**; new adapter methods land with all three OS implementations or an explicit gap note."
- **Code:**

```
# at c1277bd
$ sed -n '368,377p' bin/fleet.py
368:    def autoclean_task_query(self, task_name: str, run=None):
369:        self._unsupported("autoclean_task_query")
370-
371:    def autoclean_task_install(self, task_name: str, command: str,
372:                               interval_hours: int, run=None):
373:        self._unsupported("autoclean_task_install")
374-
375:    def autoclean_task_remove(self, task_name: str, run=None):
376:        self._unsupported("autoclean_task_remove")
```

The draft predates the directive (draft 2026-07-16; directive 2026-07-17) — this is a staleness defect, not an authoring fault. But the directive is now binding and the draft's proposal is a **new** feature adding a **new** scheduler dependency on a Windows-only adapter surface. Autoclean's schtasks-only status is grandfathered as a *known gap at v3, in-scope to close*; a new feature is not grandfathered.

**What the ratified spec must say** (the task brief asks this explicitly): the supervisor-beat scheduler MUST be specified through the platform adapter with either (a) all three implementations at ship — `schtasks` / `launchd` (`launchctl` + a plist) / `cron` (`crontab -l` + rewrite, or a systemd timer) — or (b) an explicit `UnsupportedPlatformError` seam plus a **tracked gap entry** in the SPEC header's gap list, on the same footing as autoclean's. Option (b) is defensible only if the ratified spec also states that the interface-tier + event-driven-beat arm works on POSIX without the timer arm — i.e. that the timer is an availability optimization, not the mechanism the design's correctness rests on. If the design cannot degrade that way, (a) is mandatory. Since `_install_autoclean_task` must be parameterized anyway (C7), doing that refactor **through** the adapter (`scheduled_task_install(name, command, interval)` on all three backends) closes the autoclean gap and the new one in one stroke — the cheapest available path and worth calling out as such.

### X6 — beat cost vs. GOALS frugality (**LOW — draft is compliant, states it weakly**)

- **Draft:** "**Beat cost.** A scheduled supervisor beat is a model turn every N hours forever."
- **GOALS.md:** "**Right-size the beat**: heartbeats are model turns and every beat spends tokens. Idle fleet ⇒ long beats or event-driven silence; beat rate scales with how fast the watched state actually changes, never faster."

Consistent — the draft cites the constraint and proposes long beats + cheapest-capable model. **No contradiction.** One addition worth making: `fleet spawn` takes `--model`, but the *beat* arrives via `send`, and `send` has no `--model` flag —

```
# at c1277bd
$ grep -n 'add_parser("send"' -A 3 bin/fleet.py
7195:    p_send = sub.add_parser("send", help="send a message to a worker (mailbox or resume)")
7196:    p_send.add_argument("name")
7197:    p_send.add_argument("message")
```

The fork-steer re-passes the record's spawn-immutable `model` (SPEC §4), so the beat runs on **whatever model the supervisor was spawned with** — one model for both the cheap "nothing to do" beat and the expensive campaign-slicing turn. The draft's "cheapest-capable model for the beat turn (a beat that finds nothing should cost cents)" is therefore **not achievable** with the mechanism as drafted. Not a contradiction with GOALS — a contradiction between the draft's cost argument and its own mechanism. Per-beat model selection would need either a `send --model` (which collides with `model` being spawn-immutable) or a two-session split.

### X7 — daemon transience vs. the draft's durability premise (**flagged, adjudication owned by `md-contract`**)

- **Draft:** "Workers are native `--bg` sessions: durable, survive host restarts (proven 2026-07-16 ...)"
- **Substrate change 2026-07-17:** claude 2.1.212 — daemon transient, on-demand start at dispatch, idle-exit ~5 s after last client; no service install; `rm`/`stop` fail against a dead daemon; `claude agents --json` reads a stale `roster.json`.
- **`docs/specs/native-substrate.md` header:** "Date: 2026-07-14. `claude --version`: 2.1.207 ... Re-verify via the pin-test tier (§7 below) whenever `claude --version` changes."

Everything the draft leans on is a 2.1.207 observation. See §3.7 for the enumerated exposure.

---

## 3. Completeness — existing contracts the draft's deltas touch but never mention

Each item below is a contract the proposal collides with and does not cite.

### 3.1 Spawn-immutable fields (SPEC §4) — **touched, unmentioned**

`spawned_by` breaks across supervisor forks (X2/C15). `model` being spawn-immutable defeats the draft's own per-beat cost argument (X6). `cwd` immutable ⇒ `sup-spawn` must fix the supervisor's cwd at FLEET_HOME forever; `sup-handoff-begin` already hardcodes `cwd=str(FLEET_HOME)` (@6875), so this is consistent — but the ratified spec must say it rather than inherit it.

### 3.2 Claim rituals (SPEC §12) — **touched, unmentioned**

The draft cites sup-boot once and never examines `_require_claim_holder`, `supervisor_claim_decision`, `SUPERVISOR_CLAIM_STALE_SECONDS`, or the INCARNATION schema. The nonce touchpoints are enumerated by grep in §3.8.

### 3.3 Tombstone obligation (SPEC §16 / G10) — **touched, unmentioned**

> `docs/SPEC.md` §16: "**tombstone obligation** (every fleet-initiated stop writes its own outcome record)"
> `docs/specs/native-substrate.md` G10: "`claude stop` on a not-yet-naturally-ended session fires no Stop hook ... a stopped worker with no outcome record is a real case that would otherwise misclassify as `dead-suspected` forever, or worse, as silently completed."

If `supervisor` is a registry worker, every stop-shaped verb against it (`interrupt`/`kill`/`respawn --force`) must write a tombstone. `sup-handoff-abort` already stops a limbo successor:

```
# at c1277bd
$ grep -n "def cmd_sup_handoff_abort" bin/fleet.py
6963:def cmd_sup_handoff_abort(args) -> int:
```

Today that stop writes **no** tombstone, because the successor has no registry record to tombstone against — the obligation is vacuous. Give the supervisor a record and the obligation becomes live and **currently unmet**. Same for the interaction with `write_tombstone_outcome` (@5834, kinds `killed | interrupted | stopped` @5702).

### 3.4 G9 epoch freeze — **touched, unmentioned, and it misfires**

> `docs/SPEC.md` §5: "**G9 epoch-freeze discipline:** ... the roster fetch failed, OR came back empty while some native record's last-committed status is `working` with a real sid (a daemon restart must never read as 'everything died'). While true, **no native record is recomputed or written**: `status`/`wait`/`clean` skip verdicts that pass, `send`/`respawn` **refuse outright**."

**`send` refuses outright under a suspicious roster.** The draft's beat *is* a `send`. So a scheduled beat that fires during a roster hiccup does not queue, does not retry, and does not warn a human — it exits nonzero into a scheduler that (per autoclean.md D3) *"ignores exit codes"*. The beat is silently dropped and the next one is N hours away. Under the 2.1.212 transient daemon — where a cold-start roster read is exactly the "empty/stale roster" shape G9 watches for — this is not an edge case, it is plausibly the **common** case. The draft mentions G9 nowhere.

Compounding: `sup-boot` runs the same check first and returns `freeze` (exit 3) on a suspicious roster (@6684-6686), and per C8 the fork-steer already drives the claim decision into `freeze`. Two independent freeze sources, one alarm channel, no operator attached to the tier that would see it.

### 3.5 Hook sanctioned-writes (SPEC §8) — **mentioned, inverted** — see X4/C9.

### 3.6 Autoclean N1 guards + tier interactions (autoclean.md) — **partly mentioned**

The N1 install-ordering guard genuinely applies verbatim (C10). Unmentioned:

- **F3/F4 ownership cannot distinguish two fleet tasks** (C7) — MUST-fix.
- **Multi-flag refusal semantics** (C10) — must be specified.
- **Doctor's autoclean check is task-name-bound** and would not see a second task:

```
# at c1277bd
$ sed -n '5507,5509p' bin/fleet.py
5507:        existing = PLATFORM.autoclean_task_query(AUTOCLEAN_TASK_NAME, run=run)
5508:    except UnsupportedPlatformError:
```

  A `--supervisor-beat` task needs its own doctor check (installed? stale?) or the fleet's most operator-visible safety net is blind to the mechanism keeping the supervisor alive. Doctor is currently 21 checks (SPEC §13).
- **Tier-2 husk ownership.** Today the supervisor's sids are **not** owned evidence — INCARNATION is not among the harvest sources (autoclean.md D2: registry `session_id`/`retired_sids`, archive-dir sid filenames, `events.jsonl` sids), so supervisor sessions are foreign and untouchable. Safe direction, by accident. Under the draft they become owned; a supervisor forking once per beat accrues one retired sid per beat, and tier 2 becomes the thing that reaps them. That is *desirable* and should be stated — but it also means **an archived supervisor tombstone's `claude rm` would remove the sid `INCARNATION` still names**. `refuse_if_archived` (@152) guards mutating verbs; it does not guard the claim.

### 3.7 Daemon-lifecycle assumptions — **the draft never states one** (task brief's explicit ask)

Every passage the draft relies on that presumes a **persistent** daemon:

| Passage | Source | Exposure at 2.1.212 |
|---|---|---|
| "Workers are native `--bg` sessions: durable, survive host restarts" | draft, "What exists today" | Observed against a persistent daemon. Unpinned. |
| "`claude stop <id>` only" / raw-kill respawn hazard | SPEC §1, native-substrate G10 Hazards | G10's "daemon supervisor auto-respawns the killed process" **presumes a resident supervisor process**. A transient daemon may not. The hazard may be gone — or `stop` may now fail against a dead daemon (per the 2026-07-17 finding), which is a *different* hazard the tombstone obligation must cover. |
| Roster = liveness truth (`claude agents --json`) | SPEC §1, §5 | The finding reports `claude agents --json` reads a **stale `roster.json`** against a dead daemon. The verdict engine's entire input is now potentially stale-by-default, and G9's "empty roster ⇒ freeze" fires on the ordinary cold-start path. Directly load-bearing for §3.4. |
| Startup transient / `_dispatch_grace_active` | native-substrate.md "Startup transient (amended 2026-07-16)" | The grace window was calibrated against a warm daemon. A cold-start daemon adds unmeasured latency inside the same 600 s constant. |
| "~1h idle reap ... supervisor stops its process" | native-substrate.md Hazards (quoted from Anthropic docs) | The whole reap model is a *supervisor-process* behavior. Under idle-exit-5s the reap semantics may be entirely different. The draft's beat period ("every N hours") is chosen against this model. |
| G4 env propagation (dispatch shell env → hook subprocesses) | native-substrate.md G4 | **Newly lifecycle-dependent.** `FLEET_WORKER` reached the child because the dispatch started (or shared env with) the daemon. Under a transient daemon, whether a *second* dispatch's env reaches its child depends on whether the daemon was cold-started by that dispatch or was still inside its 5 s idle window. `_worker_env`'s `FLEET_WORKER` stamp — which suppresses the SessionStart briefing (SPEC §14/D5) — may be **nondeterministic** at 2.1.212. Flagged for `md-contract`; not adjudicated here. |
| `ScheduleWakeup` self-rearm (G7) | SPEC §12 | Confirmed against a persistent daemon; idle-exit-5s vs. a 20-minute scheduled wake is exactly the open question. |

**Required of the ratified spec:** a short, explicit "daemon-lifecycle assumptions" section — what it needs the daemon to guarantee (survives between beats? or is cold-started by each beat and that is fine?) and which G-rows it inherits. The three-tier design is *unusually* exposed here: it is the first design whose correctness depends on state surviving **hours** of daemon idleness, which is precisely the interval the transient daemon changed. This is the design most affected by the substrate change and the one that must be most explicit about it.

### 3.8 Per-body claim nonce — every touchpoint, BY GREP (task brief: "an enumeration by inspection is a defect")

The nonce must break the `INCARNATION.session_id == caller_sid` equality that C8/C15 turn fatal. Complete touchpoint set:

**(a) INCARNATION schema writers — 3 sites, all write `session_id`:**

```
# at c1277bd
$ grep -n "write_incarnation(" bin/fleet.py
6444:def write_incarnation(claim: dict) -> None:
6691:                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
6705:                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
6952:                           "claimed_via": "handoff"})
```

(@6691 `claimed_via:"fresh"` · @6705 `claimed_via:"seize"` · @6952 `claimed_via:"handoff"`; plus the heartbeat-refresh round-trips in `cmd_sup_checkpoint` @6741 / `cmd_sup_heartbeat` @6755, which rewrite the whole dict.)

Current schema, exhaustively: `incarnation_id`, `session_id`, `claimed_at`, `heartbeat_at`, `claimed_via`. **No nonce field exists.**

**(b) The equality that must change — 1 site:**

```
# at c1277bd
$ grep -n "claim.get(\"session_id\")\|claim\[\"session_id\"\]" bin/fleet.py
6733:    if caller != claim.get("session_id"):
6736:            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
```

`_require_claim_holder` @6722 is the single chokepoint for `sup-checkpoint`, `sup-heartbeat`, `sup-handoff-begin`, `sup-handoff-complete`, `sup-handoff-abort`.

**(c) The claim-decision predicate — 1 site:**

```
# at c1277bd
$ sed -n '6566,6569p' bin/fleet.py
6566:    holder_sid = claim.get("session_id")
6567:    if holder_sid in live_sids:
6568:        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "
6569:                          f"(sid {holder_sid}) is live in the roster")
```

`supervisor_claim_decision` @6560 — the roster-liveness join is sid-based; a nonce must not break the genuine two-live-supervisors refusal it implements.

**(d) HANDSHAKE schema — 1 writer, 1 verifier:**

```
# at c1277bd
$ grep -n "def write_handshake\|def read_handshake\|expect_sid" bin/fleet.py
6450:def read_handshake() -> dict | None:
6457:def write_handshake(incarnation_id: str, session_id: str) -> None:
7288:    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
```

`write_handshake` @6457 writes `{incarnation_id, session_id, written_at}`; `sup-handoff-complete --expect-sid` performs the dual verification (SPEC §12: *"the HANDSHAKE must carry EXACTLY the incarnation id the old side minted AND the sid it dispatched"*). A successor that forks between HANDSHAKE and complete breaks this check too — same root cause.

**(e) Journal kinds — the allowed set is closed and validated:**

```
# at c1277bd
$ sed -n '6371,6374p;6513,6514p' bin/fleet.py
6371:SUPERVISOR_JOURNAL_KINDS = (
6372:    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
6373:    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
6374:)
--
6513:    if kind not in SUPERVISOR_JOURNAL_KINDS:
6514:        raise ValueError(f"unknown journal kind {kind!r}; allowed: {', '.join(SUPERVISOR_JOURNAL_KINDS)}")
```

A `REBODY`/`RESTAMP` kind (the fork event) and the draft's proposed `NEEDS-OPERATOR` kind both require adding here **and** to `_SUPERVISOR_JOURNAL_SEED`'s documented kinds line (@6377-6385) **and** to `sup-checkpoint --kind`'s choices, which are a *separate, narrower* hardcoded list:

```
# at c1277bd
$ sed -n '7276,7277p' bin/fleet.py
7276:    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
```

**Three places, not one** — and the entry-header regex `_SUPERVISOR_ENTRY_RE` @6470 parses `sid=<session-id>` out of every journal line, so a nonce that replaces sid-as-identity touches the journal's on-disk format too.

**(f) The restamp path that must also restamp the claim — 1 site:**

```
# at c1277bd
$ grep -n "_restamp_after_steer(" bin/fleet.py
5877:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
```

Called from `_cmd_send_native`'s idle fork-steer and `_resume_one_limited_native` (@3255). Registry-only today.

**(g) Respawn carry-forward list (SPEC §7 respawn row): "Carries forward cwd/mode/model/category/setting_sources/token_ceiling/spawned_by/cost fields; `retired_sids` += old sid."** A supervisor record adds a claim-bearing dimension this list has never had to carry. See §4 D5.

**(h) `spawned_by` provenance — 2 sites** (@1910 `_worker_is_foreign`, @1928 `_confirm_destructive`), per X2/C15.

**Touchpoint count: 8 groups, ~14 code sites, 2 on-disk schemas (INCARNATION, HANDSHAKE), 1 journal line format, 3 separate kind-lists.** The draft's "the delta is one spawn verb, one scheduled-task variant, and doctrine" does not survive this enumeration.

### 3.9 Portability directive — see X5. **The draft predates it and must be re-scoped, not merely annotated.**

### 3.10 Things the draft gets right and should keep

Stated for the manager's benefit, since this lens's failure mode is over-approval — these are the parts that **survived** receipting, not a courtesy list:

- The interface/supervisor/worker split itself is not refuted by anything in the contract set. The claim layer is sid-agnostic about human-attachment (C1); nothing in SPEC forbids the split.
- `sup-status --json` as the interface tier's read surface is **exactly right** and already view-doctrine-clean (C12).
- `@file` briefs over `fleet send` need no `--add-dir` grant (C13) — a genuine, non-obvious strength.
- The `NEEDS-OPERATOR` journal-kind proposal is the correct shape for the operator-gate routing GOALS requires ("Operator gates stay: destructive operations, HALT-grade fallback ratification, spec promotion..."). It needs the three-list amendment of §3.8(e), not a redesign.
- The two-manager-confusion doctrine ("humans talk to the interface tier; direct `fleet send` to a claimed fleet's workers is an incident, not a convenience") is well-founded and independently valuable — it is worth ratifying **now**, separately, regardless of this design's fate.
- The token-efficiency tie-in's reasoning ("a plugin the worker repo doesn't have installed is a silent no-op; a task-file clause always arrives") is sound and already landed in template v1.6 per the ledger.
- The N1 marker guards genuinely do generalize verbatim (C10) — the one reuse claim that receipts clean.

---

## 4. Verdict

```
VERDICT: restructure
```

**Rationale.** The architecture is not refuted; the *mechanism* is. Three blocking contradictions (X1, X2, X3) all trace to one root cause the draft never names: **fleet identifies actors by session id, and every steering primitive the draft chose mints a new session id.** The claim (X1) and the destructive-guard provenance (X2) both break on the first beat, deterministically, and the failure mode of X1 is the worst available one — the never-seize-on-ambiguity rule fires against a healthy supervisor, paging an operator who by design is not attached to that tier, then degrades into hourly self-seizure that pollutes the append-only identity record. Meanwhile the draft's cheapness thesis (X3, C7, C11) — the reason it is being fast-tracked — is false on receipt in three independent places: the scheduler bridge is not parameterized, supervisor dispatch does not use the dispatch choke point, and today's supervisor sessions have no hooks at all.

Not `reject`: the tier split is sound, `sup-status` is the right seam, the brief-as-file contract is right, and the operator-gate routing is well-shaped. Not `ratify-with-deltas`: the deltas below change what gets built, not how it is worded — the per-body claim nonce moves from "a separate M-D candidate" to "a hard prerequisite," and the scheduled-task work moves from "one variant" to "an adapter refactor across three OSes."

**Recommended sequencing:** the claim-nonce work (D1) is a prerequisite of this design *and* independently useful (it fixes the handoff-fork gap at §3.8(d) too). Land it as its own M-D slice with its own review; re-draft three-tier on top of it. Attempting both in one campaign repeats the C4/M-B lesson the autoclean spec itself cites — *"fix waves and riders mint new Criticals."*

### MUST-fix deltas

**D1 — Specify the per-body claim nonce as a prerequisite, not a sibling candidate.**
The claim must be keyed on something a fork does not invalidate (a nonce minted at `sup-boot` and carried in the body's context, or a claim-restamp verb called by the beat before any other supervisor action). The spec must enumerate all touchpoints from §3.8 — INCARNATION schema, `_require_claim_holder` @6733, `supervisor_claim_decision` @6566, HANDSHAKE + `--expect-sid`, the three kind-lists, `_SUPERVISOR_ENTRY_RE`'s `sid=` field, `_restamp_after_steer` @5877 — and state how `supervisor_claim_decision`'s roster-liveness join (the genuine two-live-supervisors guard) survives the change. **A design that does not close X1 does not ship.**

**D2 — Resolve `spawned_by` continuity across supervisor forks (X2).**
State explicitly whether the supervisor's workers stay "owned" across its body changes and how, without either (a) blocking the supervisor on its own fleet every beat or (b) normalizing reflexive `--yes` on the one actor `_confirm_destructive`'s threat model (@1935-1937: *"an over-helpful agent, especially one under `bypassPermissions`"*) was written to constrain. `spawned_by` is spawn-immutable per SPEC §4/§15 — any change here amends the spec of record and must say so.

**D3 — Parameterize the scheduler bridge THROUGH the platform adapter, and fix the ownership predicate (C7, X5, §3.6).**
Required: (i) `_install_autoclean_task` → a generic installer taking `task_name` + `command` + `interval`; (ii) `_autoclean_task_is_ours` replaced with a predicate that distinguishes *which* fleet task it is looking at (fleet.py path **and** the verb) — the current path-only match returns True for every fleet task and silently voids the F4 guard once a second task exists; (iii) per the 2026-07-17 portability directive, either all three backends (`schtasks`/`launchd`/`cron`) or an explicit `UnsupportedPlatformError` seam **plus a tracked gap entry in the SPEC header's gap list**, with option (b) permitted only if the ratified spec also states that the event-driven arm alone is a correct (degraded) supervisor on POSIX; (iv) define multi-flag refusal semantics for `fleet init --autoclean --supervisor-beat N` when a guard fires; (v) a doctor check for the new task (@5507 is `AUTOCLEAN_TASK_NAME`-bound and blind to it).

**D4 — State the daemon-lifecycle assumption explicitly (§3.7).**
A dedicated section naming what the design requires of the daemon across a multi-hour beat interval, and which G-rows it inherits at which `claude` version. Cross-reference the 2.1.212 transient-daemon finding (`md-contract` owns the code/pin adaptation). Two specifics that are this design's alone: (i) whether `--bg` state survives a daemon idle-exit between beats, and (ii) whether G9's epoch freeze fires on the ordinary cold-start roster read — because per §3.4, **`send` refuses outright under a suspicious roster**, and the draft's beat *is* a `send`, dispatched by a scheduler that ignores exit codes. As drafted, a beat lost to a G9 hiccup is silently dropped for N hours with nobody watching. Specify the beat's G9 behavior (retry? escalate? a doctor-visible stamp?).

**D5 — Close the supervisor-dispatch unification and its consequences (X3, C11, C16, §3.3).**
`sup-spawn` MUST route through `dispatch_bg` — the supervisor needs `--settings` (or it has no hooks and neither beat arm can be delivered), `--add-dir` (or a non-bypass mode hangs on its first Read), a registry record (or `fleet send supervisor` returns `unknown worker: 'supervisor'`), and `_worker_env` (which stamps `FLEET_WORKER` and thereby changes SessionStart behavior in supervisor sessions — state whether that is intended). Then reconcile with the pre-existing `cmd_sup_handoff_begin` @6867 path, which does none of this, or the fleet ships two divergent supervisor-dispatch mechanisms. **File the SPEC §6 defect separately**: "Every native launch ... funnels through one choke point" is inaccurate today. And rule on the verbs a registry-backed supervisor newly exposes — `fleet respawn supervisor` would fresh-dispatch the claim holder with no claim transfer, bypassing handoff entirely; `fleet kill supervisor` leaves `INCARNATION` fresh-hearted and roster-gone, i.e. `freeze` for a full `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s @6367). Each stop-shaped verb owes a tombstone (SPEC §16, G10).

**D6 — Reserve the supervisor's worker name at the `validate_name` choke point (C14).**
There is no reserved-name list (`grep -n "RESERVED" bin/fleet.py` → no matches); `supervisor` is spawnable as an ordinary worker on any project today. No filesystem collision exists — but the reservation must become a check at @483 (where F6's uuid refusal already lives), not a convention. Prefer a name the filesystem cannot confuse with the soul (`sup-body`), or state the `state/journals/supervisor.md` vs `supervisor/JOURNAL.md` distinction explicitly — two files, near-identical names, opposite write disciplines (freely-rewritten worker journal vs append-only claim-holder-only identity record).

**D7 — Withdraw the sanctioned-list amendment as scoped; pose the real question (X4, C9).**
Mailbox writes are sanctioned today (SPEC §8 item (a)). The amendment actually needed — if the event-driven arm survives at all — is a ruling on **cross-session** hook writes, plus a resolution mechanism for the supervisor's sid that does not make `stop_outcome.py` import `fleet.py` (SPEC §8: *"Standalone stdlib, never imports `fleet.py`"*). Note that the sid the hook would resolve from INCARNATION is exactly the field D1 fixes — resolve D1 first, or the arm is moot.

**D8 — Fix the beat's cost model or drop the cost claim (X6).**
`send` has no `--model` (@7195-7197) and the fork-steer re-passes the record's spawn-immutable `model` (SPEC §4), so every beat runs on the supervisor's spawn model. The draft's "cheapest-capable model for the beat turn (a beat that finds nothing should cost cents)" is not achievable with the drafted mechanism. Either specify how per-beat model selection works against `model`-is-spawn-immutable, or remove the claim and re-argue beat cost honestly under GOALS' "right-size the beat."

---

## Receipt index

18 fenced grep/sed receipts, all pinned `# at c1277bd`. Anchors used: `current_caller_session` · `goals_path`/`incarnation_path`/`handshake_path`/`supervisor_journal_append`/`supervisor_claim_decision`/`cmd_sup_handoff_begin` · `AUTOCLEAN_TASK_NAME`/`_autoclean_task_command` · `_render_successor_task` · `dispatch_bg` · `_install_autoclean_task`/`autoclean_task_install` · `_autoclean_task_is_ours` · `_marker_guard_problems` · `cmd_sup_boot` sid source · `_worker_env` · `write_incarnation` · `_require_claim_holder` · `_restamp_after_steer` · `cmd_sup_status` · `_read_task_arg`/`cmd_send` · `NAME_RE`/`validate_name`/`_SID_SHAPE_RE` · `supervisor_dir` · `_worker_is_foreign`/`_confirm_destructive` · `_PosixPlatform` · `SUPERVISOR_JOURNAL_KINDS` · `write_handshake`/`read_handshake` · `_doctor_check_autoclean` · parser rows (`send`, `sup-checkpoint --kind`, `sup-handoff-complete --expect-sid`) · `grep -n "RESERVED"` (negative). `bin/fleet.py` was never read end-to-end.
