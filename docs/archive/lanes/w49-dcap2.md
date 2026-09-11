# w49-dcap2 — the resumed-worker statusline: does the blob sid resolve?

Research lane, wave 49. Worktree `C:/proga/fleet-w49-dcap`, branch `w49/dcap`, from `75a9acc`.
Measured 2026-08-09 against Claude Code **2.1.226**, `py -3.13`, Windows 10 19045.
Companion to `docs/lanes/w49-dcap.md`, **which this report corrects in one important place** (§6).

Every line below is tagged **MEASURED** (I ran it and read the output) or **BELIEVED**
(inference I did not close). Nothing here is reasoned-about-but-uncalled.

---

## 1. The answer

**YES — and on a stronger path than the brief proposed.** MEASURED.

A Claude Code session resumed against a worker's session id carries the **worker's** sid in its
statusline blob, and that sid resolves `state='hit'` through `lookup_home_for_sid`.

But the resume path turned out not to be the interesting one. The interesting one is that
**`--bg` background sessions render a statusline all by themselves**, under their own sid, which
**is** a registry member — so §5 step 2 already resolves today, in shipped code, with no resume
and no operator action at all.

Slice (d)'s `blob sid -> same lookup` is **not inert**. It is live in the ordinary case.

---

## 2. The measurement, by session class

Every row MEASURED, all in one temp home, one probe project, one capture instrument.

| session class | new session? | statusline fires? | blob `session_id` | `lookup_home_for_sid` |
|---|---|---|---|---|
| `--bg` worker, its own process | yes | **yes** — 6 and 7 renders, two workers | the worker's own sid | **`hit`** |
| `claude --resume <worker sid>` | yes, **adopts** the sid | yes | the **worker's** sid | **`hit`** |
| `claude attach <short-id>` | **no session at all** | none of its own | — | n/a (see §4) |
| `claude agents` menu host | yes, fresh sid | yes | its **own** fresh sid | `miss` |
| `claude --resume <sid> --fork-session` | yes, fresh sid | yes | fresh sid | `miss` |
| `claude -p` headless | yes | **no** | — | n/a (w49-dcap §2.1) |
| plain interactive | yes, fresh sid | yes | fresh sid | `miss` (w49-dcap §2.4) |

### 2.1 The three strings the brief asked for, verbatim

MEASURED. All three are the same string:

```
worker's registry session_id (temp home)     b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
statusline blob session_id, resumed session  b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
sid of the session actually driven           b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
```

The third is not a restatement of the first. It is corroborated independently by three fields of
the resumed session's own blob:

```
session_id      : b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
transcript_path : ...\projects\C--Users-Techn-AppData-Local-Temp-w49-dcap2-proj\
                  b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7.jsonl
session_name    : 'fleet|w49-dcap2-probe|Do exactly this and nothing else, then s'
```

and by the capture process's own environment, `CLAUDE_CODE_SESSION_ID=b4f8ad98-…`, read inside
the statusline subprocess. **`claude --resume <sid>` adopts the sid; it does not mint a new one.**

The brief named "a resumed session may be issued a NEW sid" as a real possible outcome. It is a
real outcome — but only under `--fork-session`, which is exactly what that flag is documented to
do (`--fork-session   When resuming, create a new session ID`). See §3.

### 2.2 The lookup, actually called

MEASURED. `population` built by the shipped `resolution_population(install=<temp home>)`, so the
search space is the real one, not a hand-made dict:

```
population homes = ['C:/Users/Techn/AppData/Local/Temp/w49-dcap2/home']
list_ok = True

CONTROL registry sid  b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7 -> state=hit    home=<temp home>
CAPTURED blob sid     b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7 -> state=hit    home=<temp home>
NEG control           00000000-dead-beef-0000-000000000000 -> state=miss   home=None
empty                 <empty>                              -> state=no_sid home=None
FORKED sid            38cbc048-8b88-4644-b05d-0363921b6074 -> state=miss   home=None
```

Control first, as the brief required: the known-good registry sid returns `hit` before any
`miss` elsewhere is trusted, and a sid that should miss does miss. The population argument is
sound in both directions.

---

## 3. The discriminator (why the YES is not an instrument artifact)

MEASURED. `claude --resume <worker sid> --fork-session`, same instrument, same project, same
driver script, one flag different:

```
blob session_id = 38cbc048-8b88-4644-b05d-0363921b6074      (NOT the worker's)
transcript      = ...\38cbc048-8b88-4644-b05d-0363921b6074.jsonl
```

So the capture **can** see a fresh sid when a fresh sid is what happens. The plain-`--resume`
result is a positive, not a capture that merely echoes what I typed.

This also settles a live design point for free: **an operator's manual `--fork-session` breaks
the lookup.** `_record_sids` bridges a fork by unioning `retired_sids`, but only fleet-initiated
steers push the old sid there. A human forking from the CLI leaves no such trace, and the forked
body misses (`38cbc048… -> miss`, above). MEASURED. Whether that matters is an operator call; it
is not in slice (d)'s path.

---

## 4. `claude attach` — the path the brief actually cared about

The brief said `fleet attach` "refuses and redirects" to the agents menu or `claude attach
<session-id>`. Both halves needed correcting, in opposite directions.

**`claude attach` exists.** MEASURED. It is absent from `claude --help`'s `Commands:` list, which
is why I first recorded it as nonexistent — that draft was wrong and is retracted here rather
than left out. It responds:

```
$ claude attach b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
No job matching 'b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7'. Run 'claude agents' to list running sessions.
```

**But it takes the SHORT id, not the session id — so `fleet attach`'s redirect is unusable as
printed.** MEASURED, and this is a shipped defect worth a line on the docket:

```
$ fleet attach w49-dcap2-probe
fleet: w49-dcap2-probe: native worker -- attach via the agents menu (Ctrl+T in claude)
       or: claude attach b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
```

That pasted command is the full `session_id`, and it fails with "No job matching". The roster
carries `id` and `sessionId` as **separate** fields (`id: 14317734`, `sessionId:
14317734-30bb-41df-9d98-a9bc5609f380`), and `attach` matches on `id`. `claude attach 14317734`
attached immediately. The record already holds a `short_id`; the refusal prints the wrong one.
*(Not fixed here — `bin/fleet.py` is another lane's this wave.)*

**`claude attach` starts no session of its own.** MEASURED, by the hook discriminator: seven
`SessionStart`/`Stop` events were recorded in the probe project across the whole turn, and every
one is accounted for by a session I can name (2 bg workers × start+stop, the resume, the fork,
the agents host). **Neither attach run produced one**, and neither grew the capture log by a
byte. `claude attach` is a thin client onto an existing session, not a new one.

**And what the attached operator sees is the WORKER's statusline.** MEASURED. The capture script
prints the token `dcap-probe`; here it is in the attach TUI, in the statusline slot:

```
─────────────── fleet|w49-dcap2-live|Do exactly this and nothing else, then s ──
❯
────────────────────────────────────────────────────────────────────────────────
  dcap-probe                                   <-- the WORKER's statusline
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← 32 agents
```

Token census across the four TUIs: `pty-resume3` ×2, `pty-fork` ×2, `pty-attach2` ×1,
`pty-agents` ×0.

One nuance, stated precisely because it is easy to overclaim: the capture log did **not** grow
during either attach window, yet the token is on screen. So the frame the attaching client
received carried a statusline the **worker process** had rendered earlier, under the worker's
sid. The statusline is part of the worker's frame, replayed to the client — not re-rendered by
the client. MEASURED (zero capture growth + token present). BELIEVED: a refresh while attached
would likewise run in the worker.

**The agents menu is the one path that misses.** MEASURED. `claude agents` starts its own
session (`3ad17039-dab4-43a4-a4d7-437d8c10bb38`, `session_name: None`, model `claude-opus-5[1m]`
— note it is *not* the worker's haiku), it renders **its own** statusline, and that sid is not a
registry member: `3ad17039… -> miss`. The menu is a launcher/list, not a hand-off; the hand-off
happens when you press enter and it hands you to `attach`.

---

## 5. Notes for the build lane (the brief's IF YES section)

Short, and scoped to slice (d).

1. **The lookup half is live.** MEASURED. It resolves in the ordinary worker case with no resume
   and no attach — every `--bg` worker renders its own statusline under a member sid. §5 step 2
   is not a designed permanent miss; my previous report's claim that it was rests on the
   generalization corrected in §6.
2. **The short-circuit is for refusal shape, not speed.** UNCHANGED and still MEASURED — last
   turn's cost numbers stand and were not re-run: `status_snapshot()` 2.405 ms · bare registry
   read 0.102 ms · `lookup_home_for_sid` 1.641 ms · `homes_population` 0.053 ms, against a
   **559.9 ms** median for `bin/fleet_statusline.py` end to end. A ~2 ms lookup inside a 560 ms
   process is not a performance decision.
3. **`words, exit 0` and `refusals print facts + the fleet homes view` are unaffected.** No
   measurement in this turn touches either obligation.
4. **Design the single-home short-circuit so it does not skip the lookup when it would hit.**
   With one home the answer is the same either way, so this is free; it becomes a real choice
   only in a multi-home population, which is where the refusal shape has to be right anyway.
5. **Do not build anything keyed on the operator's own interactive sid.** That class still
   misses (w49-dcap §2.4, unchanged). The sid that hits is the worker's, and it arrives because
   the renderer runs *in the worker*.

---

## 6. Correction to `docs/lanes/w49-dcap.md` (my own previous report)

That report's §2.1 measurement is sound and stands: **the statusline does not fire under `-p`**,
proven with a `SessionStart` control in the same settings file. I re-ran nothing there and
retract nothing there.

Its **generalization** is wrong. w49-dcap.md §2 headline 4 says:

> "The only session class where the statusline fires is an *interactive* one — and interactive
> sessions are **not registry members**."

and its §5 conclusion 1 says "the statusline renders **only** in an interactive session".

**FALSE.** MEASURED: a `--bg` session renders it too — 6 renders during probe 1's `--bg` turn and
7 across probe 2's, `stdin.isatty=False` on every one, each carrying the worker's own sid:

```
=== CAPTURE t_ns=1786242842974999600 pid=50772 ===
env.CLAUDE_CODE_SESSION_ID=b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7
stdin.isatty=False
stdin_bytes=1290
{ "session_id": "b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7",
  "session_name": "fleet|w49-dcap2-probe|Do exactly this and nothing else, then s",
  "model": {"id": "claude-haiku-4-5-20251001"}, "version": "2.1.226", ... }
```

`-p` and `--bg` are different classes, and I collapsed them into "headless". The error was a
two-class model (headless / interactive) where the machine has three (`-p` / `--bg` /
interactive), and the third is the only one that is a registry member. **The conclusion that
turned on it — "§5 step 2 is a designed permanent miss on the operator's screen" — does not
hold.** The manager-sid finding it also cites (`spawned_by` never grants membership; the
most-prolific manager sid misses) is independent and still stands.

---

## 7. Side finding: `FLEET_HOME` does not reach a `--bg` child

MEASURED, and unrelated to the question, but it is a live multi-fleet defect and the operator
should see it.

I spawned with `FLEET_HOME=<temp home>` explicitly set and `CLAUDE_CODE_SESSION_ID` stripped.
The worker read its own environment and reported:

```json
{ "CLAUDE_CODE_SESSION_ID": "b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7",
  "FLEET_HOME": null,
  "FLEET_WORKER": "sup|inc-20260808T173831Z-c6d4|boot",
  "CLAUDE_CODE_ENTRYPOINT": "cli",
  "CLAUDE_PROJECT_DIR": null }
```

`FLEET_WORKER` is **not my dispatch's stamp** — it is the live fleet's supervisor boot dispatch.
The `--bg` daemon donated the environment of whichever dispatch started it, exactly as
`_worker_env`'s docstring predicts ("*The daemon that hosts `--bg` sessions donates the
environment of whichever dispatch started it, so a stamp that disagrees with the registry is a
measurable leak*"). This is that leak, measured live, and the witness `_doctor_check_identity_
witness` was kept for is doing its job.

**The downstream consequence is the part that matters**, and it is not just a witness mismatch.
With `FLEET_HOME` absent from the child, the worker's Stop hook resolved its home by the legacy
step — the hook script's own `INSTALL_ROOT` — and wrote its outcome to

```
C:/proga/fleet-w49-dcap/state/outcomes/b4f8ad98-1fd9-4cb0-891b-0582b6f59ff7.jsonl
```

**not** to the home that spawned it. The spawning home's registry therefore never saw the turn
end: `fleet status` in the temp home read `w49-dcap2-probe … working` while the roster read
`idle`/`done`. MEASURED, both.

Corroborating detail, MEASURED from the live process table — the daemon re-launches the session
under `--session-id`, which is why `dispatch_bg`'s own argv (`claude --bg -n … --settings …`) is
not what ends up running:

```
claude.exe --session-id 14317734-30bb-41df-9d98-a9bc5609f380 -n "fleet|w49-dcap2-live|…"
           --settings C:/…/w49-dcap2/home/state/worker-settings.json
           --add-dir C:/…/w49-dcap2/home/state/tasks --add-dir C:/…/w49-dcap2/home/state/journals
           --dangerously-…
```

Note what *did* survive: `--settings` and both `--add-dir` values are correct, because they are
**argv**, chosen by the dispatching process. Only the **environment** was lost. BELIEVED (not
measured): any fleet mechanism that depends on env reaching a `--bg` worker is unreliable
machine-wide, and anything carried on argv is fine. In a single-fleet install this is invisible
because `INSTALL_ROOT == FLEET_HOME`; multi-fleet is precisely where it bites.

Nothing of mine reached the live fleet — see §8.

---

## 8. Safety receipts

The hard line was: never drive any session belonging to the live fleet. **How it was
guaranteed** — every session I drove is one I spawned into a temp home, and the fence was proven
by `fleet home` run identically to every other invocation:

```
A: sid stripped + FLEET_HOME=temp  -> C:/Users/Techn/AppData/Local/Temp/w49-dcap2/home
B: sid present  + FLEET_HOME=temp  -> C:/Users/Techn/AppData/Local/Temp/w49-dcap2/home
C: sid stripped, no FLEET_HOME     -> C:/proga/fleet-w49-dcap        <-- my worktree
```

Row C is the real margin: this worktree is its own `INSTALL_ROOT`, so the legacy fallback is my
worktree and **never** `C:/proga/claude-fleet`. A mistake could not have landed in the live
fleet even if the env had been dropped — which, per §7, is exactly what happened, and it landed
in my worktree's gitignored `state/` as predicted.

Sessions driven, all four mine: `b4f8ad98` (spawned by me), its resume, its `--fork-session`
fork, `3ad17039` (agents host I started), `14317734` (spawned by me) and its attach. No
`--resume`, attach, or steer of any foreign sid at any point.

- `~/.claude/settings.json`: `mtime_ns=1786210442854189800 size=1859` **BEFORE and AFTER** —
  byte-identical, and identical to last turn's numbers too, so nothing drifted between turns.
- `~/.claude/fleet-homes.list`: **ABSENT** before and after. Never created, never appended.
- `fleet init --statusline`: **never run**. `fleet homes --add`: never run.
- Live fleet `C:/proga/claude-fleet/state/fleet.json`: **145 records** at start and at end; no
  `w49-dcap2*` name present; none of `b4f8ad98` / `14317734` / `38cbc048` / `3ad17039` appears
  anywhere in it.
- Temp home bootstrapped by hand (`state/fleet.json = {"workers": {}}`) because `fleet init`
  alone does **not** satisfy `home_is_initialized` — init writes `state/worker-settings.json`,
  and the registry only appears on the first `save_registry`. That asymmetry is pinned in
  `home_is_initialized`'s own docstring; it is the reason a temp home needs one manual file
  before any verb will resolve to it.
- Fleet verbs run, all against the temp home with the sid stripped: `home` ×3, `init`, `spawn`
  ×2, `status`, `attach` (refusal only), `kill`.
- `bin/fleet.py`, `tests/`, `docs/specs/`: **not touched.** The only files this lane writes are
  this report and its journal.

**Running processes: none.** Both probe workers stopped (`fleet kill w49-dcap2-live`; probe 1
exited on its own). Verified twice by command-line match — no `claude.exe` on the machine has
`w49-dcap2` in its argv, and no `winpty` process remains.

---

## 9. WHERE THIS BRIEF WAS WRONG

The brief asked for this section and named its own likeliest errors. Scoring them:

1. **"that a resumed session adopts the worker's sid rather than being issued a fresh one"** —
   the brief flagged this as its likeliest error. **It was not an error.** A plain `--resume`
   adopts. Only `--fork-session` mints. §2.1, §3.
2. **"that `claude --resume` renders a statusline at all under winpty"** — it does. §2.1. Two
   mechanical obstacles had to be cleared first, and neither was about resume: winpty needs
   `-Xallow-non-tty` with `COLUMNS`/`LINES` exported, and the first interactive entry into a
   fresh project dir blocks on the **folder-trust dialog** ("Is this a project you created or
   one you trust?"), which a `--bg` session never sees. An Enter keystroke at 5 s clears it.
   Anyone re-running this from a headless lane will hit both.
3. **"that the agents-menu path and `claude --resume` are the same mechanism under the hood"** —
   **wrong, and it matters.** They are three distinct mechanisms: `claude agents` is its own
   session with its own non-member sid; `claude attach` is a thin client that starts **no**
   session; `--resume` is a real session that adopts the sid. §4.
4. **"my assumption that a throwaway worker in a temp home can be resumed the same way a real
   one can"** — correct, it can. But the brief's framing of *why* was off: nothing about the
   temp home mattered to the resume. What mattered is that the worker was `--bg`, and that class
   behaves identically wherever its home is.
5. **"if the honest answer is that the resumed-session class cannot be measured from a headless
   lane either, say so"** — it can be measured, and was.

**What the brief got wrong that it did not anticipate**, and it is the load-bearing one:

> "You established that the statusline fires only in interactive sessions… so §5 step 2 is a
> **designed permanent miss on the operator's own screen**."

That premise came from my own last report and is false (§6). The whole turn was framed as
"resume is the one case where the lookup would hit". In fact the lookup hits in the **ordinary**
case — a `--bg` worker rendering its own statusline, with nobody watching. The resume result is
real but it is a corollary, not the finding.

**And the escalation the brief pre-authorised is not needed.** §5.2's exclusion of `spawned_by`
and slice (d)'s `blob sid -> same lookup` are **not** in tension. They looked to be only because
the manager was thought to be the sole statusline-bearing class. The sid that reaches the lookup
is the worker's own, which membership grants directly — no `spawned_by` reading, no ambiguity by
construction, nothing for the operator to rule on. Slice (d) is buildable as specified.

---

## 10. Replication

Artifacts kept on disk, deliberately outside any git repo and outside `~/.claude`:

```
C:/Users/Techn/AppData/Local/Temp/w49-dcap2/
  home/state/{fleet.json,worker-settings.json,events.jsonl,tasks/,briefs/}   temp FLEET_HOME
  proj/.claude/settings.json      statusline capture + SessionStart/Stop discriminator
  capture.py  hookmark.py         instruments (carried over from w49-dcap, unmodified)
  capture.log                     28638 B, 16 statusline blobs across 5 sessions / 4 distinct sids
                                  (6 probe1-bg · 1 resume · 1 fork · 1 agents-host · 7 probe2-bg)
  hookmark.log                    7 SessionStart/Stop events — the "is this a session?" control
  drive-resume.sh drive-fork.sh drive-attach.sh drive-agents.sh
  pty-resume1..3.log pty-fork.log pty-attach.log pty-attach2.log pty-agents.log
  worker-env.json                 the daemon-env leak of §7
```

Transcripts of the probe sessions live under
`~/.claude/projects/C--Users-Techn-AppData-Local-Temp-w49-dcap2-proj/`. All of it is safe to
delete.

The one command that reproduces the headline, given a `--bg` worker in a home with a project-
local capture statusline:

```sh
( sleep 5; printf '\r'; sleep 5; printf '\r'; sleep 25 ) \
  | timeout -k 5 90 /usr/bin/winpty -Xallow-non-tty -- claude --resume "$WORKER_SID"
```

with `COLUMNS=120 LINES=40 TERM=xterm-256color` exported and `CLAUDE_CODE_SESSION_ID` stripped.

Two caveats for a re-runner, both MEASURED here. Driving `claude` from inside a `claude` session
prints *"Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION marker · restart with
CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1"*, so the child's transcript is not written — the blob's
`transcript_path` still names it correctly, which is what the sid comparison uses, but do not
use "a new `.jsonl` appeared" as your discriminator. And `winpty` asserts
`wp != nullptr && cols > 0 && rows > 0` on teardown when stdout is a file; that is exit noise
after the measurement, not a failed run.
