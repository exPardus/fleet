# `fleet init` on this home — the recipe

**For: Altai, at a plain PowerShell prompt, after being away.**
**Decision asked of you: one line — "run it" or "leave it".**
**Prepared 2026-08-09 by lane `w51-initprep`, branch `w51/initprep`, base `7b2ff75`. Nothing in
this document was run against the live home except two read-only commands, both named in §5.**

---

## The short version, before the detail

`fleet init` has never been run on `C:/proga/claude-fleet`. The settings file every worker is
dispatched with predates the work built to fence it, `fleet doctor` has been RED about it, and
**the RED row is telling the truth** — the file really is missing four arguments, not merely older
than the template.

**But nothing is misrouting today, and this document would be dishonest if it let you think
otherwise.** The hooks land on the correct home anyway, by a fallback that happens to be right on
this machine. Running `fleet init` closes a fence *before* it is needed rather than after. It takes
about five seconds, it writes exactly one file, and it is fully reversible with a one-line copy
first.

**My recommendation: run it.** Cheap, correct, clears a real RED row, and the fence it installs
becomes load-bearing the moment a second fleet home exists — which is the next build slice.
**It is not urgent.** If you would rather do nothing until you have read §7, nothing degrades.

---

## 1. What is wrong today, in two sentences, with the measurement

The live `C:/proga/claude-fleet/state/worker-settings.json` was rendered before build slice (c) and
contains the `--fleet-home` argument **zero** times, while the template it is supposed to be
rendered from contains it **four** times — so every one of the four hooks that fires inside a
worker turn has to *guess* which fleet home to write to instead of being told. That guess is
currently correct on this machine, so the practical damage today is nil; what is actually broken is
that the guess is the only thing standing between a worker's Stop hook and the wrong home.

Re-derived on 2026-08-09, not copied from the brief that ordered this document:

```
grep -o -- '--fleet-home' worker-settings.template.json      | wc -l   ->  4
grep -o -- '--fleet-home' state/worker-settings.json         | wc -l   ->  0
```

**And the difference is real content, not a stale timestamp.** `fleet doctor`'s
`instance-freshness` row compares **modification times only** (`bin/fleet.py`,
`instance_freshness_info`), and it has cried wolf before: in wave 46 the same row was RED for six
days while the rendered template proved sha256-identical to the live instance at 846 characters.
That is not the case here. Rendering the template exactly as `fleet init` renders it and diffing
against the live file:

| | characters | sha256 (first 8) |
|---|---|---|
| live `state/worker-settings.json` | **846** | `50b048c5` |
| the same file re-rendered from today's template | **1002** | `ff44c7da` |

The entire 156-character difference is the four `--fleet-home "C:/proga/claude-fleet"` additions.
Nothing else in the file changes — same interpreter path, same four hook scripts, same
`Bash(fleet q:*)` grant. Wave 46's "846 chars, identical" measurement was true then; 846 is still
the live size, and the template has moved since.

### Why nothing is misrouting today, stated plainly

All four hooks (`stop_outcome`, `stop_mailbox`, `posttooluse_mailbox`, `postcompact_journal`) share
one resolution ladder:

1. `--fleet-home` on their own command line — **absent today**
2. the `FLEET_HOME` environment variable — **not set anywhere on this machine** (the worker
   environment builder copies your environment and adds only `FLEET_WORKER`; it never sets
   `FLEET_HOME`)
3. the directory the hook script itself lives in, walked up to the repo root — **`C:/proga/claude-fleet`,
   which is correct**

Step 3 saves it, and step 3 is correct *only because this fleet's code and its data are the same
directory*. It stops being correct the moment a second home shares this install — which is exactly
what build slice (b) would introduce, and slice (b) is one of the four decisions waiting for you.

There is a second, live reason to want the fence. The `claude` daemon **substitutes** the
environment of whichever dispatch cold-started it into every session it hosts afterwards. That is
not a theory here: while writing this, the lane's own session was carrying
`FLEET_WORKER='sup|inc-20260808T173831Z-c6d4|boot'` — a dead supervisor's stamp, not its own — and
`fleet doctor` reported the mismatch. Environment donation is happening on this machine right now.
It donates no `FLEET_HOME` only because nothing on this machine ever sets one. `--fleet-home` on
the command line outranks the environment, and that is the whole point of it.

---

## 2. What `fleet init` actually does to this home, file by file

Derived from `cmd_init` in `bin/fleet.py`, not from documentation about it.

| Path | What happens | Clobber behaviour |
|---|---|---|
| `C:/proga/claude-fleet/worker-settings.template.json` | **read** | never written |
| `C:/proga/claude-fleet/state/` | created if absent (**it exists**) | — |
| `C:/proga/claude-fleet/state/worker-settings.json` | **written** | **overwritten unconditionally, with no backup and no prompt** |

**That is the complete list for plain `fleet init`.** It is one file.

Details that matter:

- **It refuses if the template is missing.** No template, no write — you get a one-line error and
  nothing changes.
- **It refuses if the render leaves a placeholder unfilled.** A typo'd `{{NAME}}` in the template
  raises rather than writing a broken settings file, because `claude` silently ignores invalid
  `--settings` JSON in print mode and dead hooks would otherwise be undetectable.
- **`{{PYTHON}}` becomes the absolute path of the interpreter that ran `fleet init`.** This is the
  one way to get a wrong result from a successful run: `fleet` (the shim on your PATH) pins
  `py -3.13` → `C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe`, which is what
  the live file already names. A bare `python` on this machine is **3.10.1** at
  `C:/Program Files/Python310/python.exe`, and running init that way would bake 3.10 into all four
  hook commands. Use `fleet init`, or spell out `py -3.13`.
- **It writes nothing outside the fleet home.** No `~/.claude/settings.json`, no
  `~/.claude/fleet-homes.list` (that file does not exist on this machine and plain `init` will not
  create it), no scheduled task, no marker file.
- **It does not create `state/fleet.json`.** Worth knowing because it means `fleet init` cannot be
  used to bring a brand-new home into existence for `--fleet-home` to name.
- **It is gated.** `init` is a mutating lifecycle verb: a caller that carries a
  `CLAUDE_CODE_SESSION_ID` while a supervisor claim is held with a fresh heartbeat is refused with
  exit code 4. A supervisor claim **is** live right now. **A human at a plain shell carries no
  session id and is not gated** — so run this from PowerShell, *not* from inside a Claude Code
  session, or it will refuse.

It prints three lines on success:

```
fleet init: wrote C:\proga\claude-fleet\state\worker-settings.json
  python:      C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe
  fleet home:  C:/proga/claude-fleet
```

Read both of those values before you do anything else. If `fleet home:` is not
`C:/proga/claude-fleet`, you have written some other home's settings file and should revert (§6).

### `fleet init --statusline` — do not use it here

The flag merges fleet's `statusLine` key into `~/.claude/settings.json`. Its refusal logic:

- **A foreign statusline** (any command not naming `fleet_statusline.py`) → it **refuses** and tells
  you to re-run with `--chain` (keep yours, print fleet's row beneath it) or `--force` (overwrite).
- **A fleet-owned statusline** → not foreign, so no refusal and no chaining; it backs the file up to
  `~/.claude/settings.json.bak.<timestamp>` and rewrites the `statusLine` key.

**What is installed on this machine right now** (read, never written):

```json
"statusLine": {
  "type": "command",
  "command": "C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py",
  "refreshInterval": 10
}
```

That is fleet's own statusline, already pointing at the right script with the right interpreter.
`--statusline` would therefore take the fleet-owned branch, write a third backup file next to the
two already in `~/.claude/`, and rewrite the file with an identical value. **Zero benefit, one
unnecessary write to a machine-global file. Omit the flag.**

---

## 3. The exact commands, in order

Open **Windows PowerShell**. Not a Claude Code session — see the gate note in §2.

```powershell
# STEP 0 — the backup that makes step 3 reversible. Do not skip it.
#          REVERSIBLE. Creates one new file, changes nothing.
Copy-Item C:\proga\claude-fleet\state\worker-settings.json `
          C:\proga\claude-fleet\state\worker-settings.json.pre-w51 -Force

# STEP 1 — confirm which home this shell will act on.
#          READ-ONLY. Must print exactly: C:/proga/claude-fleet
fleet home

# STEP 2 — the "before" health snapshot, kept for comparison.
#          READ-ONLY (no --repair). Expect a non-zero exit code; that is normal, see section 5.
fleet doctor | Tee-Object C:\proga\claude-fleet\state\doctor-before-w51.txt

# STEP 3 — THE DEPLOY. Writes exactly one file. NOT reversible by any fleet verb;
#          reversible only by the copy you made in step 0.
fleet init

# STEP 4 — confirm the write landed and says what it should.
#          READ-ONLY.
Select-String -Path C:\proga\claude-fleet\state\worker-settings.json -Pattern '--fleet-home' | Measure-Object
#   -> Count : 4
```

| Step | Reversible? |
|---|---|
| 0 — `Copy-Item` | yes (delete the copy) |
| 1 — `fleet home` | nothing to reverse |
| 2 — `fleet doctor` | nothing to reverse (report-only; `--repair` is the writing variant and is not used) |
| 3 — **`fleet init`** | **only via the step-0 copy.** No fleet verb undoes it, and the overwrite takes no backup of its own |
| 4 — `Select-String` | nothing to reverse |

If you want to see the change before committing to it, run step 4's `Select-String` against
`...\worker-settings.json.pre-w51` too — 0 vs 4 is the entire diff.

---

## 4. The canary worker

**Why a canary at all:** `fleet init` only changes what *future* dispatches are launched with.
Workers already running keep the settings they started with, so the only way to test the new file is
to spawn something new. And a worker that "runs fine" proves nothing — the thing that can go wrong
is a hook writing its record into a different directory, which does not make the worker fail.

**Name the positive artifact first, then look for it:**

> `C:\proga\claude-fleet\state\outcomes\canary-w51.jsonl` must exist and its last line must be a
> JSON object with `"kind": "result"` and a `"ts"` from the last few minutes.

That file is written by `bin/hooks/stop_outcome.py` at the end of the turn, into
`<the home the hook resolved>/state/outcomes/`. Its presence *in this home* is the proof — not that
the worker finished, not that `fleet status` looks healthy.

```powershell
# spawn one throwaway worker with a trivial task
fleet spawn canary-w51 --dir C:\proga\claude-fleet --task "Print the current date and stop. Do not edit any file."

# ...wait ~30-60 seconds, then:

# THE PROOF — the file must exist and its last line must carry "kind":"result"
Get-Content C:\proga\claude-fleet\state\outcomes\canary-w51.jsonl -Tail 1

# the same fact through the CLI, which reads that store
fleet result canary-w51
```

### What its absence looks like, versus what a slow worker looks like

These are genuinely distinguishable, and the discriminator is `fleet status`, not the clock:

| `fleet status` says | Outcome file | Meaning |
|---|---|---|
| `working` | not there yet | **A slow worker.** The session roster still reports the session busy. Wait. This is also what the first few seconds after any spawn look like. |
| `idle` | **present**, fresh `"kind":"result"` | **Success.** The turn ended and its record landed in this home. |
| `dead-suspected` | **absent** | **The failure this canary exists to catch.** The roster says the session is over, but no completion record reached this home. Either the hook wrote somewhere else, or it did not run. |
| `limited` | absent | Unrelated — the worker hit a plan usage limit. Not a hook problem. |

So the failure is *not* indistinguishable from a healthy worker, which is worth knowing: fleet
recomputes a worker whose session has ended but whose outcome never arrived as **`dead-suspected`**,
and `fleet doctor` carries a `dead-suspected` row. It looks like "working" only for as long as the
session is genuinely still running.

Second signal, if the canary does fail: `C:\proga\claude-fleet\state\hook-errors.log`. A hook that
resolved *this* home but then failed logs there. A hook that resolved the *wrong* home logs into the
wrong home's copy of that file — so **an empty `hook-errors.log` alongside a missing outcome file is
itself evidence of a home-resolution problem** rather than a hook crash.

### Disposing of the canary

```powershell
fleet kill canary-w51 --yes
```

That marks it dead and is terminal. **Then stop.** Do not reach for `fleet clean` to tidy it up:
`clean` has no per-worker targeting — it sweeps *every* dead worker in the registry along with
their logs, mailboxes and journals, irreversibly. The routine autoclean sweep (the supervisor runs
it on its beat; it last ran 0.2h before this document was written) will collect the canary on its
own schedule, together with whatever else is already dead. If you want the canary's outcome record
as evidence, copy that one `.jsonl` line somewhere durable before the sweep takes it.

---

## 5. Verification — `fleet doctor` before and after

Two commands were run against the live home while preparing this document, both read-only, both
named here for the record: **`fleet home`** and **`fleet doctor`** (no `--repair`; `cmd_doctor`
without that flag performs no writes, and its two hook smoke-tests run against a throwaway temporary
directory, not against this home). No mutating fleet verb was run.

### The row this is about

`[FAIL] instance-freshness: worker-settings.json instance is older than the template -- run
'fleet init'` **will clear.** This is measured, not predicted: the rendered instance was written
into a throwaway home and graded by fleet's own check functions.

| Row | Before | After | Note |
|---|---|---|---|
| `instance-freshness` | **FAIL** | **PASS** | the whole point of the deploy |
| `worker-settings-instance` | PASS | PASS | still parses, still forward slashes, scripts still exist |
| `instance-grants` | PASS | PASS | the `Bash(fleet q:*)` grant is unchanged by the render |
| `hook-registration` | PASS | PASS | the added `--fleet-home` argument does not disturb it |

### The rows that stay RED — and are **not** a failure of this deploy

**Three, not two.** Do not read any of them as a symptom of what you just did:

1. **`pin-version`** — `claude 2.1.226 != 2.1.222 at last pin pass (2026-08-05)`. The vendor CLI
   moved past the version the native-substrate contract was last verified against. Entirely
   unrelated to worker settings; it clears when someone re-runs the pin tier, not when you run
   `fleet init`.
2. **`identity-witness`** — a known live hole, benign here. The daemon substitutes environments
   wholesale, so the `FLEET_WORKER` stamp routinely names a different (often dead) body. The
   registry is the judge and the row says so itself: *no observation of this variable is evidence
   about this body, in either direction*. It is a **witness**, never an answer.
3. **`supervisor-pending-decision`** — the ND4(c) residual, which is your own open question. It
   stays RED until you answer it with `fleet sup-decision --answer <text>`.

### `fleet doctor` will still exit non-zero afterwards

It returns 0 only when every row passes, and three rows will still be RED for the reasons above.
**Judge this deploy by the `instance-freshness` line, not by the exit code.**

```powershell
fleet doctor | Tee-Object C:\proga\claude-fleet\state\doctor-after-w51.txt
Compare-Object (Get-Content C:\proga\claude-fleet\state\doctor-before-w51.txt) `
               (Get-Content C:\proga\claude-fleet\state\doctor-after-w51.txt)
```

The only line that should differ is `instance-freshness`. Anything else that moved deserves a look
before you spawn the canary.

---

## 6. The revert path

**Step 0 of §3 is the revert.** It is not optional bookkeeping — `fleet init` overwrites the
instance with no backup of its own, and no fleet verb restores it.

```powershell
# put the home back exactly as it was
Copy-Item C:\proga\claude-fleet\state\worker-settings.json.pre-w51 `
          C:\proga\claude-fleet\state\worker-settings.json -Force

# confirm
Select-String -Path C:\proga\claude-fleet\state\worker-settings.json -Pattern '--fleet-home' | Measure-Object
#   -> Count : 0     (back to the pre-deploy state)
```

`instance-freshness` will go RED again after a revert. That is correct and expected — it is the row
telling you the instance is once more older than the template.

**Nothing in the plain-`fleet init` path is irreversible**, provided step 0 ran. Two caveats, stated
in those words:

- **If you skipped step 0, the old file is gone.** It is not recoverable from git (`state/` is
  gitignored) and no fleet verb reconstructs it. You would rebuild it by hand from the template
  minus the four arguments — recoverable, but by hand.
- **If you used `--statusline` against advice**, that flag writes its own timestamped backup of
  `~/.claude/settings.json` before rewriting, so reverting it is copying
  `~/.claude/settings.json.bak.<timestamp>` back over `~/.claude/settings.json`. Nothing else
  outside the fleet home is touched.
- **The canary is a separate, irreversible act.** `fleet kill` is terminal, and if you run
  `fleet clean` the deletion of every dead worker's files cannot be undone.

---

## 7. What could go wrong, ranked, each with its detection signal

**1 — You run `fleet init` from inside a Claude Code session and it refuses (most likely).**
A supervisor claim is live with a fresh heartbeat, and any caller carrying a session id is gated.
*Detection:* exit code 4 and a refusal message naming continuity. *Fix:* run it from a plain
PowerShell window. Nothing was written.

**2 — You skipped step 0 and want to go back.**
*Detection:* immediate — there is no `worker-settings.json.pre-w51`. *Fix:* rebuild by hand from
the template (§6). Cost is minutes, not data.

**3 — The wrong interpreter gets baked into all four hook commands.**
Running init through a bare `python` (3.10.1 on this machine) instead of the `fleet` shim's
`py -3.13` rewrites every hook command to a different interpreter. *Detection:* the `python:` line
`fleet init` prints, and `Select-String -Path ...\worker-settings.json -Pattern 'Python310'` finding
anything. *Fix:* revert (§6) and re-run as `fleet init`.

**4 — The home path becomes wrong later, and now it is baked in rather than derived.**
This is the real cost of the change, and it should be stated. Today the hooks derive the home from
their own location, so moving or renaming the repo would keep working. After `fleet init` they carry
`--fleet-home "C:/proga/claude-fleet"` on the command line, and **the argv value wins without being
validated** — deliberately, because validating it and falling through would trade a broken bake for
a write into somebody else's home. *Detection:* after any move of `C:/proga/claude-fleet`, new
workers go `dead-suspected` and `state/outcomes/` stops growing. *Fix:* re-run `fleet init` from the
new location.

**5 — You run `fleet init` while workers are mid-turn.**
The file is truncated and rewritten in place. Sessions already running are unaffected (they read
their settings at launch), but a session *starting* during that fraction of a second could read a
partial file, and `claude` ignores invalid `--settings` JSON silently. *Detection:* a worker spawned
in that instant produces no outcome record and goes `dead-suspected`. *Fix:* respawn it. *Avoid:*
run the deploy when nothing is spawning — which is now, with you at the keyboard and the fleet idle.

**6 — `--statusline` is used and rewrites `~/.claude/settings.json` for nothing.**
Not damaging: it backs up first and the incumbent is already fleet's own. *Detection:* a new
`settings.json.bak.*` file in `~/.claude/`. *Fix:* none needed; delete the surplus backup if it
bothers you.

**7 — The canary passes but proves less than you think.**
A canary that merely finishes tells you nothing. *Detection:* you looked at `fleet status` instead
of at `state/outcomes/canary-w51.jsonl`. *Fix:* §4's table — the artifact is the proof, and
`dead-suspected` is the shape of the failure.

---

## What this recipe deliberately does not ask you

**No new gate.** You have four open in `docs/OPERATOR-GATES.md`, all yours, all carried untouched
across three waves. Nothing measured while preparing this forced a fifth. This is a recipe you
approve or decline in one line — and declining costs nothing that is degrading today.
