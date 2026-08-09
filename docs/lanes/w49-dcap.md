# `w49-dcap` — does the statusline blob carry a usable session id?

| | |
|---|---|
| Branch | `w49/dcap` |
| Base | `cef230f` (`docs(w48): journal the wave-48 clean release`) |
| Lane | Research. **No production code changed.** Only this file is added. |
| Vendor | `claude --version` → `2.1.226 (Claude Code)` |
| Interpreter used for probes | `C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe` |
| `~/.claude/settings.json` | **byte-identical before and after** — see §7 |
| `~/.claude/fleet-homes.list` | **absent before, absent after** — see §7 |

Every line is tagged **MEASURED** (I ran it in this lane and read the bytes back) or **BELIEVED**
(reasoning or documentation I did not execute). The gate should read §1 and §2 first, and should
treat §2 as the finding that actually decides slice (d) — §1 alone would let the slice be built on
a true premise into a surface where it can almost never fire.

---

## 0. HEADLINE

**The `blob sid` premise is TRUE. The slice is still not buildable as written, for a reason the
brief did not anticipate.**

1. The statusline stdin blob **does** carry a session id, under the key **`session_id`**, and it is
   **byte-identical to `CLAUDE_CODE_SESSION_ID`** as seen by the statusline process itself.
   MEASURED, twice, in two independent sessions, 8 invocations, 8/8 exact match.
2. It is present on **every** refresh, not just the first. MEASURED (4/4 and 4/4).
3. **But the statusline does not fire in a headless (`-p`) session at all** — MEASURED, with a
   discriminating control that proves project settings *were* honoured in that same run. The
   statusline is a TTY surface. It fired only once I gave it a real pseudo-console.
4. **And that is the problem.** The only session class where the statusline fires is an
   *interactive* one — and interactive sessions are **not registry members**. All 145 records in the
   live registry are `dispatch_kind: "bg"`; there is no interface-tier row. Worse, the miss is
   **deliberate and pinned**: `lookup_home_for_sid`'s own docstring states *"MEMBERSHIP IS THE
   UNION, AND `spawned_by` NEVER GRANTS IT (§5.2, pinned)"*, because honouring `spawned_by` would
   make every manager a member of every home it ever dispatched into. MEASURED: feeding the most
   prolific manager sid in the registry (26 dispatches) to `lookup_home_for_sid` returns
   `state='miss'`.

So the resolver is real, the sid is real, the sid is stable — and on the operator's screen, which is
the only screen the statusline renders to, **step 2 is a designed miss on essentially every
invocation**. `blob sid -> same lookup` is not wrong; it is *inert*. Slice (d) as specified buys a
lookup that will resolve for approximately no one.

That is not a "stop, unbuildable" verdict of the kind the brief pre-authorised, and I am not
claiming it is. It is narrower and more actionable: **the slice needs a different resolution rule
for the interactive session class, or it needs to be honest that the statusline always falls through
to the legacy/default home.** §5 has the notes.

---

## 1. THE FOUR QUESTIONS, ANSWERED

### 1.1 Does the blob carry a session id, and under what key? — MEASURED

**Yes. Key: `session_id`.** Top-level, a string, a uuid.

Complete verbatim key set. It is **not constant across refreshes** — the first render carries a
strictly smaller set than every later one. Both are given in full, as asked; `.` denotes nesting.

**First render (invocation 1), 12 top-level keys — MEASURED:**

```
session_id                                str
transcript_path                           str
cwd                                       str
model                                     dict
model.id                                  str
model.display_name                        str
workspace                                 dict
workspace.current_dir                     str
workspace.project_dir                     str
workspace.added_dirs                      list
version                                   str
output_style                              dict
output_style.name                         str
cost                                      dict
cost.total_cost_usd                       int
cost.total_duration_ms                    int
cost.total_api_duration_ms                int
cost.total_lines_added                    int
cost.total_lines_removed                  int
context_window                            dict
context_window.total_input_tokens         int
context_window.total_output_tokens        int
context_window.context_window_size        int
context_window.current_usage              NoneType
context_window.used_percentage            NoneType
context_window.remaining_percentage       NoneType
exceeds_200k_tokens                       bool
fast_mode                                 bool
thinking                                  dict
thinking.enabled                          bool
```

**Every later render (invocations 2, 3, 4 — identical key sets), 15 top-level keys — MEASURED.**
Adds, on top of the above:

```
prompt_id                                             str
session_name                                          str
rate_limits                                           dict
rate_limits.five_hour                                 dict
rate_limits.five_hour.used_percentage                 int
rate_limits.five_hour.resets_at                       int
rate_limits.seven_day                                 dict
rate_limits.seven_day.used_percentage                 int
rate_limits.seven_day.resets_at                       int
context_window.current_usage                          dict     (was null)
context_window.current_usage.input_tokens             int
context_window.current_usage.output_tokens            int
context_window.current_usage.cache_creation_input_tokens  int
context_window.current_usage.cache_read_input_tokens  int
context_window.used_percentage                        int      (was null)
context_window.remaining_percentage                   int      (was null)
```

Nothing present on the first render is absent later (`IN 1 BUT NOT 2: []`, MEASURED). `session_id`
is in **both** sets, so the slice's key is in the stable core, not in the volatile tail.

One verbatim blob, first render, exactly as captured (only the uuid is real and this session is
gone) — MEASURED:

```json
{
  "context_window": {
    "context_window_size": 200000,
    "current_usage": null,
    "remaining_percentage": null,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "used_percentage": null
  },
  "cost": {
    "total_api_duration_ms": 0,
    "total_cost_usd": 0,
    "total_duration_ms": 4771,
    "total_lines_added": 0,
    "total_lines_removed": 0
  },
  "cwd": "C:\\Users\\Techn\\AppData\\Local\\Temp\\w49-dcap-probe",
  "exceeds_200k_tokens": false,
  "fast_mode": false,
  "model": { "display_name": "Haiku 4.5", "id": "claude-haiku-4-5-20251001" },
  "output_style": { "name": "default" },
  "session_id": "fa5e3f71-7ed6-44b7-9cb9-4297649c79d6",
  "thinking": { "enabled": true },
  "transcript_path": "C:\\Users\\Techn\\.claude\\projects\\C--Users-Techn-AppData-Local-Temp-w49-dcap-probe\\fa5e3f71-7ed6-44b7-9cb9-4297649c79d6.jsonl",
  "version": "2.1.226",
  "workspace": {
    "added_dirs": [],
    "current_dir": "C:\\Users\\Techn\\AppData\\Local\\Temp\\w49-dcap-probe",
    "project_dir": "C:\\Users\\Techn\\AppData\\Local\\Temp\\w49-dcap-probe"
  }
}
```

Note `transcript_path` — the session id is also the transcript filename. A second, independent
handle on the same value if `session_id` ever moves.

### 1.2 Is it the same value `CLAUDE_CODE_SESSION_ID` carries? — MEASURED, YES

This is the question the brief was right to be most afraid of, so I measured it in the way that
cannot be fooled: **the capture script records `os.environ['CLAUDE_CODE_SESSION_ID']` in its own
process, in the same write, next to the raw stdin bytes.** Same process, same instant, no
cross-referencing of two logs.

| Run | invocation | `env.CLAUDE_CODE_SESSION_ID` | `blob.session_id` | equal |
|---|---|---|---|---|
| 1 | 1–4 | `fa5e3f71-7ed6-44b7-9cb9-4297649c79d6` | same | **True** ×4 |
| 2 | 1–4 | `9966f289-5b2b-4254-a16d-767b2a0dca3f` | same | **True** ×4 |

8/8 byte-identical. The uuid-that-looks-right-but-is-a-different-id failure mode the brief named
**did not occur** at 2.1.226.

Two details that make this stronger than it looks:

- **Run 1 was launched with `CLAUDE_CODE_SESSION_ID` still set to my own worker sid
  (`e4ebf3a6-…`), inherited.** The captured value was `fa5e3f71-…`, not `e4ebf3a6-…`. So Claude
  Code **overwrites** the variable in the statusline child with the current session's id rather than
  passing the parent's through. MEASURED. That is the behaviour slice (d) needs and it is not
  something the docs state.
- **Run 2 was launched with `CLAUDE_CODE_SESSION_ID` and `CLAUDE_CODE_CHILD_SESSION` both stripped
  from the environment**, and produced a fresh, different sid with the same 4/4 agreement. So the
  agreement is not an artifact of inheritance in either direction. MEASURED.

**BELIEVED, not measured:** that this holds across resume/fork. `fleet` already models sid churn
(`retired_sids` exists on every record), and I did not exercise `--resume` or a fork-steer inside a
pty. A build lane should not assume the blob sid survives a fork.

### 1.3 Present on every refresh, or only some? — MEASURED, EVERY REFRESH

`session_id` appeared in **8 of 8** captured invocations across the two runs (4 each). The invocation
count itself is evidence the refresh mechanism ran: run 1 fired at session start, after the
assistant message, and twice more; run 2 the same.

Refresh cadence is **not** what changes; the **key set** is. See §1.1: the first render lacks
`prompt_id`, `session_name`, `rate_limits`, and has three `context_window` fields as `null`. A build
lane that reads `blob["rate_limits"]["five_hour"]` unguarded will `KeyError` on exactly the first
render of every session and then work forever after — the nastiest possible shape of bug for a
surface whose failures are swallowed by an exit-0 guard. **`session_id` is not in that hazard set.**

### 1.4 Does the schema differ across the `claude` versions in play? — PARTIALLY MEASURED

- **2.1.226: MEASURED.** The blob carries its own `version` field, and it read `"2.1.226"` on all 8
  invocations — self-consistent with `claude --version`. A consumer can therefore version-gate on
  the payload itself without shelling out. That is a better answer than a diff would have been.
- **2.1.222: NOT MEASURED. I cannot measure it and did not pretend to** — 2.1.226 is what is
  installed, and installing an older CLI is a machine-global act this lane is fenced out of.
- **BELIEVED (documentary, via `claude-code-guide`):** the docs carry per-field version notations —
  `prompt_id` requires v2.1.196+, subagent fields v2.1.205+ / v2.1.214+ — but **no changelog entry
  documents any statusline payload change between 2.1.222 and 2.1.226.** Since every field the pin
  stamp's version would care about is older than 2.1.196, the risk that `session_id` differs at
  2.1.222 is low. **That is an inference, not a measurement.** If the slice must run on 2.1.222, the
  `version` field in the blob is the guard to use.

---

## 2. THE FINDING THAT OUTRANKS THE FOUR QUESTIONS

### 2.1 The statusline does not fire headless — MEASURED, with a control that discriminates

The brief flagged this as the honest failure mode. It is real, and I separated it from the
lookalike failure ("project settings were never read") before believing it.

The probe project declared, in **one** `.claude/settings.json`, both a capture `statusLine` **and** a
`SessionStart` + `Stop` hook writing a marker. One file, two surfaces, so the marker is a
discriminator, not a second experiment:

| observation | means |
|---|---|
| marker present, capture present | statusline fires |
| **marker present, capture absent** | **project settings honoured; statusline specifically did not fire** |
| marker absent, capture absent | project settings never read — route (2) collapses |

`claude -p "Reply with exactly: PROBE-OK" --model haiku` in the probe dir: **`PROBE-OK` returned,
exit 0, `hookmark.log` written with both `SessionStart` and `Stop` payloads, `capture.log` absent.**
MEASURED. Row 2. The statusline did not fire; project settings were unambiguously honoured.

So: **project-level `statusLine` is honoured (§1 proves it — the capture only ever came from a
project-level settings file, never from `~/.claude/settings.json`), and `-p` mode does not render a
statusline.** The brief's two suspicions were both correct, and they are independent facts.

I then got the measurement anyway, without touching any machine-global file, by giving Claude Code a
real pseudo-console: **`winpty` (already on this machine at `/usr/bin/winpty`) driving `claude
--model haiku` with scripted keystrokes.** First attempt stalled on the folder-trust dialog — visible
in the pty log, so I fixed the keystroke sequence rather than guessing. Second and third attempts
started the TUI and the statusline fired 4 times each. That is §1's entire evidence base, and it is
a real Claude Code session, not a synthetic blob.

**I constructed no synthetic blob and reported no key from one.** The only hand-fed JSON in this lane
is the instrument control in §6, which is labelled `CONTROL-NOT-A-MEASUREMENT` in its own payload and
is kept in a separate file.

### 2.2 The session class that gets a statusline is the one the lookup is designed to miss — MEASURED

Live registry, `C:/proga/claude-fleet/state/fleet.json`, 161 154 bytes:

| fact | value | MEASURED by |
|---|---|---|
| raw records | 145 | direct JSON read |
| records with `dispatch_kind` other than `"bg"` | **0** | `Counter` over all 145 |
| records with a `tier` field | **0** (`tier` is derived at snapshot time, not stored) | `Counter` over all 145 |
| records carrying a `session_id` | 145 / 145 | direct |
| records whose name suggests an interface/manager row | **none** | name scan |
| `lookup_home_for_sid(<this bg worker's sid>)` | `state='hit'`, `home='C:/proga/claude-fleet'` | direct call |
| `lookup_home_for_sid(<most prolific manager sid, 26 dispatches>)` | **`state='miss'`, `home=None`, `hits=[]`** | direct call |

And the miss is not an oversight to be patched. `lookup_home_for_sid`'s docstring, read from the
shipped source — MEASURED (quoted verbatim):

> MEMBERSHIP IS THE UNION, AND `spawned_by` NEVER GRANTS IT (§5.2, pinned). … A record's
> `spawned_by` is the MANAGER's sid, so honouring it would make every manager a member of every
> home it ever dispatched into — ambiguity by construction, on the one caller class §5 most needs
> to serve.

Chain it together, all four links MEASURED:

1. the statusline renders **only** in an interactive session (§2.1);
2. interactive sessions are **not** registry records (0/145 non-`bg`);
3. their sid appears only as `spawned_by` on the records they dispatched;
4. `spawned_by` is **pinned never to grant membership**.

⇒ On the operator's screen, `blob sid -> §5 step 2` is a **designed, permanent miss**.

The saving grace, and it is a real one: **`miss` falls through, it does not refuse.** The docstring
is explicit — *"Falls through, for every verb class — v6's miss-refusal is DELETED"*. So a statusline
built on this resolves to the legacy/default home and prints a correct line. It does not break. It
just never does the thing the slice was for.

**BELIEVED, and the one case worth checking before the slice is scoped:** `fleet attach` opens a
full interactive TUI on a **worker's** session. If that session runs under the worker's own sid, the
statusline there **would** hit — attach may be the single context where slice (d)'s lookup pays off.
I did not measure it (attaching would seize a live worker in another lane's fleet). It is one
command for whoever builds this.

---

## 3. WHAT THE OPERATOR CAN RUN IN ONE COMMAND

Not needed for §1 — that is measured. Kept because the brief asked for it and because it is the
cheapest possible independent replication of my headline, on the operator's *own* real session
rather than my probe:

```
cd C:/Users/Techn/AppData/Local/Temp/w49-dcap-probe && claude --model haiku
```

Type anything, then `/exit`. Then read `capture.log`. The probe project is left in place, intact,
with its `.claude/settings.json`, `capture.py`, `hookmark.py`, `control-capture.log`,
`capture-run1.log` and `capture.log` (run 2). It touches nothing outside that directory.

To verify the §2.2 claim instead — the one that actually gates the slice — no session is needed:

```
py -3.13 -c "import sys;sys.path.insert(0,'C:/proga/claude-fleet/bin');import fleet,json;r=json.load(open(fleet.registry_path(),encoding='utf-8'))['workers'];print(set(v.get('dispatch_kind') for v in r.values()))"
```

Expected: `{'bg'}`.

---

## 4. SECOND QUESTION — NOTES FOR THE BUILD LANE

The first question answered yes, so these are in scope. Short, as asked. **No code was written into
`bin/`.**

### 4.1 `single-home short-circuit` — the cost premise is wrong by two orders of magnitude

The brief said `bin/fleet.py` "already carries comments warning the registry read is on the hot path
for every view and the statusline." True, and the comments are good hygiene — but the number does
not support treating the registry read as the thing to optimise. All MEASURED on this machine,
Python 3.13, warm:

| thing | cost |
|---|---|
| `fleet.status_snapshot()` in-process, 16 live rows out of 145 records | **2.405 ms** mean over 200 calls |
| bare `open(fleet.json).read()`, 161 154 bytes | **0.102 ms** mean over 200 |
| `fleet.homes_population()` | **0.053 ms** mean over 200 |
| `fleet.lookup_home_for_sid(sid)` — the whole of §5 step 2 | **1.641 ms** mean over 200 |
| python startup + `import fleet` + `status_snapshot()`, as a process | **135.9 ms** median, n=12 |
| python startup + `import fleet` only, as a process | **149.4 ms** median, n=12 |
| bare `python -c pass` | **23.5 ms** mean |
| **`bin/fleet_statusline.py` end to end, as Claude Code actually invokes it** | **559.9 ms** median, min 519.6, max 608.5, n=12 |

Read those last rows together. `import fleet` **without** the snapshot measured *slower* than with
it — the registry read is **below this machine's process-noise floor**. The statusline's real cost is
~135 ms of interpreter-and-import before a single byte of registry is touched, and then ~420 ms more
in the **chained delegate**: the live `state/statusline-chain.json` has a delegate installed, and the
end-to-end run printed a `[CAVEMAN]` row above fleet's own. MEASURED (`rc=0`, output
`'\x1b[38;5;172m[CAVEMAN]\x1b[0m\n[fleet]  sup held  work 3 8m  idle 10 2h  +2 dead\n'`).

**Implication for the slice:** a single-home short-circuit is worth building for *correctness and
refusal-shape*, not for speed. Skipping the lookup saves ~1.6 ms on a ~560 ms surface — 0.3 %. If the
build lane is told the short-circuit is a performance feature it will optimise the one component
that is already free. The cheap signal already exists and is essentially free to consult:
`homes_population()` costs **0.053 ms** and returns `homes: []` when `~/.claude/fleet-homes.list` is
absent, which is this machine's current state (MEASURED, §7).

### 4.2 `words, exit 0` — already satisfied by the shipped statusline

`fleet_statusline.render_statusline` is a pure function over a snapshot dict. Called directly on
degenerate snapshots — no files touched, no I/O — MEASURED:

| snapshot | rendered |
|---|---|
| `{'ok': False, 'reason': 'not_initialized'}` | `[fleet]: not initialized` |
| `{'ok': False, 'reason': 'quarantined'}` | `[fleet]: registry quarantined` |
| `{'ok': False, 'reason': 'whatever'}` | `[fleet]: registry unreadable` |
| `{'ok': True, 'workers': []}` | `[fleet]: no workers` |

`main()` wraps every path in `except BaseException: return 0`. MEASURED by reading the source. So
the corrupt/absent-registry contract CLAUDE.md states is met today, and slice (d) inherits it — it
only has to not *add* a raising path. **BELIEVED (pinned elsewhere, not re-derived here):** that
`status_snapshot()` takes no lock, runs no probe and cannot quarantine; `tests/test_views_doctrine.py`
and `tests/test_load_registry_callers.py` are the pins, and this lane is fenced out of `tests/`.

Note for the build lane: the shipped statusline **already reads the whole blob** —
`payload = sys.stdin.read()` — and forwards it verbatim to delegates. Slice (d) does not need to add
a read; it needs to add a `json.loads` on a string it already has, inside the existing try/except.

### 4.3 `resolver pure-function` — mostly already true, with one honest caveat

`fleet.lookup_home_for_sid(sid, population=None, install=None)` — MEASURED signature. Both
`population` and `install` are **injectable**, and the function's only I/O when `population` is
supplied is `read_registry_at` per member home, which the docstring states *"never raises and never
writes."* So it is testable without a live session **provided the test injects `population`**. With
`population=None` it reads `~/.claude/fleet-homes.list` and every listed home's registry, so it is
not pure by default. Return shape is a tri-state dict — `state` ∈ `no_sid | hit | miss | ambiguous`
plus `home`, `hits`, `unreadable`, `population`, `legacy`, `list_ok`, `list_reason`,
`list_invalid_lines`, `states`. MEASURED (returned live).

The slice's genuinely new pure function is the **blob → sid extractor**: `str | None` out of a raw
stdin string, tolerating (a) unparseable JSON, (b) a non-dict top level, (c) a missing `session_id`,
(d) a non-string `session_id`. All four are one-line tests with no session. That is where the pure
function should live.

### 4.4 Refusals

Nothing to add beyond restating it: with `state='miss'` falling through by design (§2.2), the
statusline has **no refusal to print** in the single-home case. The refusal surface only opens on
`ambiguous`, which requires a populated `fleet-homes.list` — absent on this machine. `fleet` already
ships `render_homes_view` for that render. **BELIEVED** — I did not exercise an ambiguous lookup,
because manufacturing one requires appending to `fleet-homes.list`, which is RATIFIED DESTRUCTIVE and
which I did not do.

---

## 5. WHERE THIS BRIEF WAS WRONG

The brief named four suspicions and asked me to grade them. Three were right, one was right in the
brief's favour, and it missed the one that matters.

### 5a. "that a project-level `.claude/settings.json` statusline is honoured at all" — **RIGHT, route (2) held**

It is honoured. §1's entire evidence base came from a project-level settings file; the machine-global
one was never edited and never read for this. MEASURED, and independently confirmed by the docs'
precedence table (project overrides user).

### 5b. "that the statusline fires in a headless session" — **WRONG, and the brief suspected so**

It does not. §2.1. The brief pre-authorised stopping here; I did not have to, because `winpty` was
already installed. **The brief did not know a pty was available on this machine, and that is the
single thing that turned a "cannot measure from a headless lane" report into a measurement.** Any
future lane blocked on "that is a TUI surface" should check `which winpty` first.

### 5c. "that the blob's session id, if present, is the same one fleet's registry keys on" — **RIGHT, but the brief asked the smaller half of the question**

The blob sid **is** `CLAUDE_CODE_SESSION_ID` (§1.2), and the registry **does** key on
`session_id` (§2.2, `lookup_home_for_sid` hit on a bg worker). Both halves of the brief's worry check
out. What the brief did not ask — and what decides the slice — is whether *the session that renders a
statusline* is ever **in** that registry. It is not (§2.2). The brief framed the risk as *"a
different id that looks like a uuid"*; the real risk was **the right id for a session the registry
was pinned never to contain.**

### 5d. "that this is a small job" — **RIGHT, it was not**

Four capture attempts (one control, one headless null, one pty stall on the trust dialog, two pty
successes) plus the registry archaeology in §2.2.

### 5e. The brief's `FLEET_HOME` safety stanza — **CORRECT, and now MEASURED rather than asserted**

The brief said `FLEET_HOME` is not a fence inside a fleet-launched session because the sid lookup
outranks it, and that removing `CLAUDE_CODE_SESSION_ID` from the child environment restores the
fence. I tested all four cells before relying on it. `bin/fleet.py home`, print-only (verified by
reading `cmd_home` — no `open(`, no `write_text`, no `save_registry`, no lock):

| # | `CLAUDE_CODE_SESSION_ID` | `FLEET_HOME` | `fleet home` printed |
|---|---|---|---|
| 1 | present | unset | `C:/proga/claude-fleet` |
| 2 | stripped | unset | `C:/proga/claude-fleet` |
| 3 | **present** | **set to a scratch dir** | **`C:/proga/claude-fleet`** ← env ignored |
| 4 | stripped | set to a scratch dir | `…/w49-dcap-probe/fakehome` ← env honoured |

MEASURED. Row 3 is the trap, exactly as the brief described it. The scratch dir was empty afterwards
— nothing was created in it. **The brief was right and the mechanism works; a lane that trusts
`FLEET_HOME` alone is unfenced.**

### 5f. One thing the brief could not have known

`docs/OPERATOR-GATES.md` (mtime 07:09:14) and `supervisor/JOURNAL.md` (07:10:50) in
`C:/proga/claude-fleet` were modified during my session window **by a concurrent body, not by me**.
My only write anywhere under `C:/proga/claude-fleet` was
`state/journals/w49-dcap.md` (gitignored). I am recording this so the gate does not attribute those
two dirty files to this lane.

---

## 6. THE INSTRUMENT, AND ITS CONTROL

Scratch project: **`C:/Users/Techn/AppData/Local/Temp/w49-dcap-probe`** — deliberately **not** inside
a git repo (so no settings from a repo root could leak in) and **not** under `~/.claude` (so nothing
could be mistaken for global config). Not the worktree, because the branch must change exactly one
file.

`capture.py` reads `sys.stdin.buffer` and appends **raw bytes** to `capture.log` in `"ab"` mode, with
a header recording `t_ns`, pid, argv, cwd, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PROJECT_DIR`,
`CLAUDE_CODE_ENTRYPOINT`, `stdin.isatty()` and the byte count. Binary throughout — the brief warned
this project has lost four measurements to text-mode `\r` mangling. **MEASURED: `CR count in file: 0`
across all 6 550 captured bytes.** It writes, then prints `dcap-probe`, then exits 0.

**Control, run before the subject and kept in a separate file — MEASURED.** Hand-fed
`{"control":true,"session_id":"CONTROL-NOT-A-MEASUREMENT"}` on stdin:

- stdout `dcap-probe`, `exit=0`;
- `control-capture.log` written, 385 bytes, payload round-tripped byte-exact.

So the headless null in §2.1 is a measured zero, not a broken instrument. The control payload is
self-labelling so it can never be mistaken for a capture if the two files are ever concatenated.

Instrument facts worth carrying forward, MEASURED from the capture headers:

- `stdin.isatty()` is **False** in the statusline child even in a TTY session — the statusline is
  piped, always. A build lane must not gate colour on `isatty`.
- `CLAUDE_PROJECT_DIR` **is** set for the statusline child (`…/w49-dcap-probe`). Another handle, if
  the slice ever wants cwd rather than sid.

---

## 7. SAFETY RECEIPTS

| target | before | after | verdict |
|---|---|---|---|
| `~/.claude/settings.json` | `mtime_ns=1786210442854189800 size=1859` | `mtime_ns=1786210442854189800 size=1859` | **byte-identical, never opened for write** |
| `~/.claude/fleet-homes.list` | **absent** | **absent** | never created, never appended |

MEASURED at both ends by `os.stat`. `fleet init --statusline` was **never run**. Nothing was appended
to `fleet-homes.list`. The global statusline installed there
(`…/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py`, `refreshInterval: 10`) is untouched
and still installed.

### Every `fleet` invocation in this lane, and the home it actually touched

| invocation | count | home touched | read/write |
|---|---|---|---|
| `bin/fleet.py home`, sid present, no `FLEET_HOME` | 1 | `C:/proga/claude-fleet` | print only |
| `bin/fleet.py home`, sid stripped, no `FLEET_HOME` | 1 | `C:/proga/claude-fleet` | print only |
| `bin/fleet.py home`, sid present, `FLEET_HOME`=scratch | 1 | `C:/proga/claude-fleet` (env ignored) | print only |
| `bin/fleet.py home`, sid stripped, `FLEET_HOME`=scratch | 1 | `…/w49-dcap-probe/fakehome` | print only |
| `bin/fleet_statusline.py` as a subprocess | 12 | `C:/proga/claude-fleet` | read only — **also ran the chained `[CAVEMAN]` delegate 12×** |
| in-process `fleet.status_snapshot()` | ~231 (206 in the timing loop, 12 + 12 inside subprocesses, 1 in the tier check) | `C:/proga/claude-fleet` | read only |
| in-process `fleet.lookup_home_for_sid()` | ~204 | `C:/proga/claude-fleet` | read only |
| in-process `fleet.homes_population()` / `read_homes_list()` | ~202 | reads `~/.claude/fleet-homes.list` (absent) | read only |
| in-process `json.load(fleet.registry_path())` | 3 | `C:/proga/claude-fleet` | read only |

No `fleet` verb that takes `fleet.lock`, writes, spawns, kills, cleans, archives or quarantines was
run. No `fleet` CLI verb other than `home` was run at all.

Sessions created: **3** Claude Code sessions in the probe directory (one `-p`, two pty), plus their
transcripts under `~/.claude/projects/C--Users-Techn-AppData-Local-Temp-w49-dcap-probe/`. That is
ordinary Claude Code state, is the unavoidable cost of measuring a session surface, and is outside
both fleet homes.

---

## 8. WHAT I DID NOT MEASURE

Stated plainly so the gate does not have to infer it:

- **2.1.222.** Not installed; installing it is machine-global. §1.4.
- **Whether the blob sid survives `--resume` or a fork-steer.** `retired_sids` exists because sids
  churn; I exercised neither inside a pty.
- **Whether `fleet attach` renders a statusline under the worker's sid** — the one case where §5
  step 2 would hit on a statusline. §2.2. It would seize a live worker in another lane's fleet.
- **An `ambiguous` lookup.** Requires appending to `fleet-homes.list`. §4.4.
- **Any behaviour of a fleet home other than `C:/proga/claude-fleet`.** The population is a single
  home on this machine (`homes: []` from an absent list, falling back to the legacy home).
- **Whether Claude Code re-renders the statusline on `/compact`, permission-mode change or vim
  toggle.** BELIEVED from the docs; my 4 invocations per run came from session start, the assistant
  message, and the refresh timer. Not separated.
