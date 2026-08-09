# w52 lane — the stranger-clone rehearsal, driven all the way through

**Lane:** `w52/launch`, worktree `C:/proga/fleet-w52-launch`, branch cut at `64b43c2`.
**Method:** clone the repo into a throwaway, become a stranger, follow `README.md` literally, then
drive the worker lifecycle nobody had ever driven from the documentation's point of view.
Every line is tagged **MEASURED** (I ran it on 2026-08-09 and the output is pasted) or **BELIEVED**
(reasoning, code reading, or relayed claim).

**Scope delivered: all four parts.** Nothing was cut.

> ## ⚠ THIS REPORT HAS BEEN THROUGH AN ADVERSARIAL GATE AND CORRECTED. READ THIS FIRST.
>
> Gate **`w52-glaunch3`** (`e97bbcb` on `w52/glaunch3`) returned **GATING — 1 BLOCKING, 3 MAJOR,
> 5 MINOR**. All nine are **accepted**; none is refused. The corrections are made **in place**, with
> the superseded text struck through or quoted rather than deleted, and the discharge is summarised in
> **§11** at the end.
>
> **The three things a reader must not carry away from an uncorrected copy:**
>
> 1. **W52-2 is MEDIUM, not HIGH.** It was graded on *"deterministic, reproduced four times"*. The
>    gate drove it six times on byte-identical code and got **rc=0 five times**; its one reproduction
>    was in a roster state this report never named. **Determinism is the property that did not
>    replicate**, and it is what the HIGH rested on.
> 2. **W52-2's proposed remedy was unsafe and is RETRACTED.** `_roster_live_sids` has **11 call
>    sites** (AST-derived here, §3), four of them supervisor-identity machinery. The suggested
>    `status == "idle"` disjunct would reclassify live-but-idle sessions as dead. **Do not apply it.**
> 3. **W52-2's mechanism claim was backwards and is RETRACTED.** *"The fix that rescued macOS cannot
>    fire on Windows"* is false: the `state != "done"` guard **does** fire on Windows and is what makes
>    most drives succeed. I read a false docstring parenthetical as an exemption.
>
> **Two findings were repaired on this branch** under the discharge licence — W52-5 (README's demo
> block, now a verbatim capture) and W52-6 (`docs/launch-readiness.md`'s stale sentence). **`bin/` is
> untouched.** One new finding, **W52-8**, was found while generating the replacement.

---

## 0. Vantage, and why any of these readings are about *this* repo

**MEASURED — the three trees are one tree.** The brief warns that an instrument answers about the
tree it stands in. I stood in a clone and am talking about this repo, so I measured the identity
rather than assuming it:

```console
$ git ls-remote https://github.com/exPardus/fleet HEAD
64b43c2099f3dbd2948a31a839eb3c4e5bded4cf	HEAD

$ git -C <clone> rev-parse 'HEAD^{tree}'
fb3db9d9d05920ab94dfabbf59a5bde6de7c388b
$ git -C C:/proga/fleet-w52-launch rev-parse 'HEAD^{tree}'
fb3db9d9d05920ab94dfabbf59a5bde6de7c388b

$ sha256sum <clone>/bin/fleet.py C:/proga/fleet-w52-launch/bin/fleet.py C:/proga/claude-fleet/bin/fleet.py
76b9bcbe50eac88eb72610683e0f6182c5ce3f33bf805c3b02056d83cd815d17 *<clone>/bin/fleet.py
76b9bcbe50eac88eb72610683e0f6182c5ce3f33bf805c3b02056d83cd815d17 *C:/proga/fleet-w52-launch/bin/fleet.py
76b9bcbe50eac88eb72610683e0f6182c5ce3f33bf805c3b02056d83cd815d17 *C:/proga/claude-fleet/bin/fleet.py
```

Public HEAD == my branch base == `main` == the clone. **The stranger's tree and this report's subject
are the same bytes**, so a reading taken in the clone is a reading about this repo. Every source line
number below was read in `C:/proga/fleet-w52-launch/bin/fleet.py` at `64b43c2`; they are not
transferable to another commit.

**MEASURED — I cloned from the local path**, not from GitHub: `git clone --no-hardlinks --branch main
C:/proga/claude-fleet <temp>` (4.48 s). `--no-hardlinks` so the throwaway shares no inodes with the
live repo. The receipt above is what licenses that shortcut.

| Thing | Value |
|---|---|
| Throwaway root | `C:\Users\Techn\AppData\Local\Temp\w52-launch` |
| Stranger's clone | `…\w52-launch\clone\fleet` @ `64b43c2` on `main` |
| Redirected home | `…\w52-launch\fakehome` |
| Worker scratch cwd | `…\w52-launch\scratch` |
| Spaced-path tree | `C:\Users\Techn\AppData\Local\Temp\w52 launch space\…` (Part 3) |
| `claude` | 2.1.226 at `C:\Users\Techn\.local\bin\claude.EXE` |
| Interpreters | `py -3.13` → 3.13.12, `py -3.10` → 3.10.1 |

---

## 1. THE FENCE — proven three ways, and then deliberately narrowed

The brief asked me to explain *why* I was contained, not to assert that I was. There are three
independent legs, and **they do not all hold in both halves of this lane.** That difference is the
lane's first headline.

### 1a. The redirection works — measured at fleet's own functions, not at Python's `~`

Asking `Path.home()` would only prove something about Python. I asked **fleet** where it would write,
by importing the clone's own `bin/fleet.py` and printing its machine-global path helpers. Positive
control first, since "it's contained" is a null shaped like an answer:

```console
=== CONTROL: unfenced (must show the REAL machine-global paths) ===
fleet.FLEET_HOME       = C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet
fleet.INSTALL_ROOT     = C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet
user_settings_path()   = C:\Users\Techn\.claude\settings.json
  -> inside throwaway  = False
homes_list_path()      = C:\Users\Techn\.claude\fleet-homes.list
  -> inside throwaway  = False
statusline_chain_path()= C:\Users\Techn\.claude\fleet-statusline-chain.json
  -> inside throwaway  = False

=== FENCED ===
fleet.FLEET_HOME       = C:\Users\Techn\AppData\Local\Temp\w52-launch\home
fleet.INSTALL_ROOT     = C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet
user_settings_path()   = C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\settings.json
  -> inside throwaway  = True
homes_list_path()      = C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\fleet-homes.list
  -> inside throwaway  = True
statusline_chain_path()= C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\fleet-statusline-chain.json
  -> inside throwaway  = True
claude_daemon_lock_path = C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\daemon.lock
  -> inside throwaway  = True
read_homes_list()      = {'path': WindowsPath('C:/Users/Techn/AppData/Local/Temp/w52-launch/fakehome/.claude/fleet-homes.list'), 'ok': True, 'reason': 'absent', 'members': [], 'retired': [], 'invalid_lines': 0, 'decode_note': None}
```

MEASURED, and re-measured on the 3.10 floor (`Path.home()` redirects identically on 3.10.1 and
3.13.12). **`USERPROFILE` is the lever on Windows**; `HOME` alone would not do it, because
`ntpath.expanduser` consults `USERPROFILE` first — I set both anyway, because Git Bash and the POSIX
shim read `HOME`.

### 1b. The population, measured rather than reasoned about

```console
=== FENCED resolution_population() ===
{'homes': ['C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet'],
 'legacy': 'C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet',
 'list_invalid_lines': 0, 'list_ok': True, 'list_reason': 'absent', 'listed_members': []}
```

The population is **not empty** — the brief is right about that, and right that wave 48's stated
reason was false. It is `['<the clone>']`, because `resolution_population()` is
`read_homes_list()` ∪ the install root, the machine's homes list is ABSENT, and `INSTALL_ROOT` is the
clone (`bin/fleet.py:114`, `Path(__file__).resolve().parent.parent`). The live home is not a
candidate **because I invoked the clone's own `bin/fleet.py`**, not because the population is empty.

### 1c. The three legs, and which ones actually did the work

| # | Leg | Holds in Part 1 (install) | Holds in Part 2 (lifecycle) |
|---|---|---|---|
| 1 | clone's own shim ⇒ `INSTALL_ROOT` = clone ⇒ population = `[clone]` | yes | **yes — and it is the only load-bearing one** |
| 2 | `CLAUDE_CODE_SESSION_ID` removed ⇒ §5 step 2 cannot hit | yes | yes, but redundant (below) |
| 3 | `USERPROFILE`/`HOME` redirected ⇒ every `~`-rooted fleet path lands in the throwaway | yes | **NO — deliberately dropped** |

**MEASURED — leg 2 is not what contains this lane, and I can show it.** Three-way discriminator, same
shell, only the shim and the sid varying:

```console
=== PART-2 GATE: fleet home (real ~, sid removed, clone shim) ===
C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet
normalised match = True

--- CONTROL: same shell, sid RESTORED
C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet

--- CONTROL: the LIVE shim with sid restored
C:/proga/claude-fleet
```

Row 2 is the interesting one: **with my real session id restored, the clone's shim still resolves to
the clone.** So the sid removal bought nothing here. What bought containment is that the sid lookup
searches a population that contains only the clone, whose registry has never heard of my session.
Restore the sid *and* use the live shim and you get the live home — row 3, which is the hazard w48 §1
named, reproduced.

Every gate compared **normalised** (`fleet home` prints `as_posix()`), per the stanza.

### 1d. And then the fence had to be narrowed, which is the lane's first real finding

**MEASURED.** Under the `USERPROFILE` redirect, `claude` cannot authenticate:

```console
$ claude -p "Reply with exactly: OK" --model haiku     # USERPROFILE/HOME -> throwaway
Not logged in · Please run /login
rc=1
```

Credentials live in the real `~` (`~/.claude/.credentials.json` is present there — MEASURED by
listing, not by reading its contents). So **the fence that makes quickstart step 4 runnable makes
Part 2 impossible**, and vice versa. This is discussed as finding **W52-1** in §6.

Part 2 therefore ran under legs (1)+(2) only, against the **real** `~`. What that costs, stated
rather than hidden: `claude --bg` writes its own session records and `~/.claude/daemon.log` in the
real home. That is Claude Code's state, not fleet's, and it is exactly what CLAUDE.md's sanctioned
pattern ("integration tests use a haiku worker in a temp dir") already implies. The three
**fleet-owned** machine-global files were still never written; §7 re-verifies each by hash or absence.

---

## 2. PART 1 — the quickstart, all of it

**The README quickstart has FIVE steps, not four.** The brief says "drive quickstart steps 1 → 4";
step 5 is `fleet doctor`. I drove all five. MEASURED.

### Step 1 — PATH

```console
# cwd = …\w52-launch\clone\fleet
$env:PATH = "$PWD\bin;$env:PATH"

$ Get-Command fleet -All
C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet\bin\fleet.cmd
C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet\bin\fleet.py
C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet\bin\fleet
C:\proga\claude-fleet\bin\fleet.cmd
C:\proga\claude-fleet\bin\fleet.py
C:\proga\claude-fleet\bin\fleet
```

**Works, and w48's MINOR-5 correction is confirmed live**: the live fleet is still on PATH, *behind*
the new clone, and PATH order decides. w48's doc fix for finding 2 (a literal PATH command instead of
a comment) is present in the tree and is copy-pasteable as written. **MATCH.**

### Step 2 — `fleet home` then `fleet init`

```console
$ fleet home
C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet
rc=0

$ fleet init
fleet init: wrote C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet\state\worker-settings.json
  python:      C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe
  fleet home:  C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet
rc=0  seconds=0.26
```

`state/` did not exist before; after, it holds exactly one file. The throwaway `~` was still
completely empty. **Exactly what the doc says. MATCH.**

### Step 3 — the plugin. **RUN. Wave 48 called this structurally unrunnable; it is not.**

The unlock is leg 3: `claude`'s own configuration is `~`-rooted, so the redirect fences it too.
**Positive control first**, because "the install succeeded" means nothing if it went to the real
config:

```console
=== CONTROL: unfenced 'claude plugin marketplace list' (operator's real config) ===
Configured marketplaces:

  ❯ claude-plugins-official
    Source: GitHub (anthropics/claude-plugins-official)

  ❯ openai-codex
    Source: GitHub (openai/codex-plugin-cc)

  ❯ caveman
    Source: GitHub (JuliusBrussee/caveman)

  ❯ claude-fleet
    Source: Directory (C:\proga\claude-fleet)

  ❯ cc-oracle
    Source: GitHub (exPardus/cc-oracle)

=== FENCED: same command, USERPROFILE/HOME redirected ===
No marketplaces configured
```

(Quoted whole, all five rows, per w48's MAJOR-2 lesson about abridging a receipt to the row you are
arguing about.) The fenced view is empty ⇒ the redirect fences `claude`. Then:

```console
=== 3a: claude plugin marketplace add <clone dir> ===
Adding marketplace…✔ Successfully added marketplace: claude-fleet (declared in user settings)
rc=0

=== 3b: claude plugin marketplace list ===
Configured marketplaces:

  ❯ claude-fleet
    Source: Directory (C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet)

rc=0

=== 3c: claude plugin install fleet@claude-fleet ===
Installing plugin "fleet@claude-fleet"...✔ Successfully installed plugin: fleet@claude-fleet (scope: user)
rc=0

=== 3d: claude plugin details fleet ===
fleet 0.2.0
  Three-tier command for Claude Code sessions: an interface tier that owns the plan, a supervisor tier that dispatches and gates, and worker sessions that survive reboots.
  Source: fleet@claude-fleet

Component inventory
  Skills (15)  attach, clean, doctor, fleet, interrupt, kill, overview, peek, release, respawn, result, resume-limited, send, spawn, status
  Agents (0)
  Hooks (0)
  MCP servers (0)
  LSP servers (0)

Projected token cost
  Always-on:   ~473 tok   added to every session
rc=0
```

**Three things this settles.**

1. **`launch-readiness.md` gap 2a is CLOSED at the strongest grade available.** The directory form is
   no longer "the form a known-working install on the maintainer's machine reports" — it is a form
   **re-executed on a clean box**, rc=0, install and `details` both green. MEASURED.
2. **`Hooks (0)`** — the no-injection rule (CLAUDE.md's D7 stanza; README line 88, *"the plugin itself
   registers no hooks and injects nothing"*) is **measured true at the vendor's own inventory**, not
   just asserted from the manifest. That claim had been read from `.claude-plugin/marketplace.json`
   before; this is `claude` itself reporting it after a real install. **MATCH.**
3. `exPardus/fleet` as a *GitHub-shorthand* marketplace source remains **untested** — w48's narrowed
   open question is unchanged. I did not run it, because it would reach the network for a repo whose
   marketplace resolution is the actual unknown, and the throwaway proves nothing about GitHub.

### Step 4 — `fleet init --statusline`. **RUN. Never run by anyone before.**

```console
$ fleet home
C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet

$ fleet init --statusline
fleet init: wrote C:\Users\Techn\AppData\Local\Temp\w52-launch\clone\fleet\state\worker-settings.json
  python:      C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe
  fleet home:  C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet
  backup:      C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\settings.json.bak.20260809T155041Z
fleet init: installed statusLine into C:\Users\Techn\AppData\Local\Temp\w52-launch\fakehome\.claude\settings.json
  restart Claude Code to see it
rc=0 seconds=0.26
```

The resulting file, whole — note that the marketplace and plugin keys step 3 wrote are **preserved**,
which is the merge behaviour `_install_statusline`'s docstring promises:

```json
{
  "extraKnownMarketplaces": {
    "claude-fleet": {
      "source": { "source": "directory", "path": "C:\\Users\\Techn\\AppData\\Local\\Temp\\w52-launch\\clone\\fleet" }
    }
  },
  "enabledPlugins": { "fleet@claude-fleet": true },
  "statusLine": {
    "type": "command",
    "command": "\"C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe\" \"C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet/bin/fleet_statusline.py\"",
    "refreshInterval": 10
  }
}
```

**Step 4 works end-to-end**: backs up, merges only `statusLine`, emits the **quoted** command form.
It is no longer "believed unblocked at the one line that was fixed" — it is driven. **MATCH.**

### Step 5 — `fleet doctor`

rc=0, 1.48 s, **28 `[PASS]`, 0 `[FAIL]`, 0 `[WARN]`**, counted from the full unpiped output. README's
*"all 28 checks should pass"* — **MATCH.**

**And this run discharges a BELIEVED that w48 left open.** w48 §11 recorded that three `doctor` rows
read machine-global state (`claude-agents` saw 37→40 sessions, `daemon-wedge` saw a held lock,
`identity-witness` saw an inherited `FLEET_WORKER`) and said: *"what those three rows print on a
genuinely fresh machine with no daemon and no sessions is UNVERIFIED here. BELIEVED: they still
PASS."* Under leg 3 those rows are pointed at an empty `~`, which is that machine. MEASURED, all
three PASS with benign empty-case messages:

```console
[PASS] identity-witness: no FLEET_WORKER stamp in this environment; registry verdict for sid None: unresolved
[PASS] claude-agents: no fleet-unknown claude agent sessions
[PASS] daemon-wedge: no ~/.claude/daemon.lock -- no daemon singleton to be stale
```

**w48's BELIEVED is now MEASURED and it was right.** The three rows are `~`-scoped, not
machine-scoped — a distinction w48 could not draw, because it had no way to move `~`.

### Also re-measured, because pasted counts are the drift class this repo keeps hitting

```console
$ fleet --help
{home,knowledge,homes,init,spawn,status,peek,result,wait,send,interrupt,attach,release,respawn,resume-limited,kill,clean,archive,autoclean,index,q,doctor,sup-boot,sup-spawn,sup-checkpoint,sup-heartbeat,sup-release,sup-status,sup-context,sup-decision,sup-handoff-begin,sup-handoff-complete,sup-handoff-abort}
SUBCOMMAND_COUNT=33
```

`docs/getting-started.md:296` says *"all 33 subcommands"*. **w48's fix held. MATCH.**

---

## 3. PART 2 — the worker lifecycle, driven for the first time

One haiku worker, `probe`, in `…\w52-launch\scratch`, `--mode bypass --token-ceiling 60000`. Fence
legs (1)+(2), real `~`. Every verb the brief named, plus `interrupt` and `doctor --repair`.

### The loop, MEASURED

```console
$ fleet spawn probe --dir …\scratch --mode bypass --model haiku --token-ceiling 60000 --task "…"
model: haiku
probe 4c058fc0-7e5e-4124-bd06-9d3d40d2d4c1 (native bg, short id 4c058fc0)
rc=0

$ fleet status
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
probe               working        1        -        0     0        -  -

$ fleet peek probe                       # mid-turn
-- probe (4c058fc0) --
[user] Read C:/Users/Techn/AppData/Local/Temp/w52-launch/clone/fleet/state/tasks/probe.md and follow it exactly.
[tool] Read
[tool] Write
[tool] Write

$ fleet send probe "Also create a file named world.txt containing exactly the word WORLD."
probe: turn running -- message queued to mailbox
rc=0                                      # and MAIL goes 0 -> 1 in status

$ fleet wait probe --timeout 240
probe: idle -- **Changed:** Created world.txt with WORLD content. Journal updated.
rc=0 seconds=2.12

$ fleet result probe
-- tokens in=8 out=65 model=claude-haiku-4-5-20251001
**Changed:** Created world.txt with WORLD content. Journal updated.
rc=0
```

The worker really did the work: `hello.txt` = `HELLO`, `world.txt` = `WORLD`, both MEASURED by
reading them. `spawn → status → peek → send → result → wait` all behave as documented. **MATCH.**

Later verbs, MEASURED:

```console
$ fleet send probe "…"                    # worker IDLE
probe: fork-steered (new session 844c3e88) -- fork carries full transcript (G2b)

$ fleet interrupt probe
probe: stopped via claude stop; marked interrupted. Respawn is a separate decision (fleet respawn probe).
rc=0

$ fleet resume-limited
probe: skipped -- not limited
rc=0

$ fleet kill probe --yes
fleet: probe: stopping retired session 4c058fc0... ok
fleet: probe: stopping retired session 1b5bea1f... ok
fleet: probe: stopping retired session 844c3e88... ok
fleet: probe: stopping retired session 0d8177a1... ok
probe: killed
rc=0

$ fleet clean --yes
removed probe (session 55c18f57-ad0a-400d-b99b-662a5b55f0a4)
rc=0
$ cat state/fleet.json
{
  "workers": {}
}
```

`kill` sweeping the entire fork lineage — four retired sids from three `send`/`respawn` forks — is
better hygiene than any document promises, and worth recording as a thing that works.

### `doctor --repair`, the only mutating doctor path — MEASURED, and the views doctrine holds

Registry deliberately corrupted to `{ this is not json`:

```console
=== A. fleet status ===
fleet: registry error: …\state\fleet.json is not valid JSON -- repair it with `fleet doctor --repair`
rc=1
registry still present+corrupt = True

=== B. fleet doctor  (report-only) ===
[FAIL] registry: …\state\fleet.json is not valid JSON; every worker-keyed check below ran against an EMPTY registry. Rerun as `fleet doctor --repair` to quarantine it (renames it aside to state/fleet.json.corrupt.<ts>)
rc=1
registry still present = True

=== C. fleet doctor --repair ===
[FAIL] registry: registry was corrupt and has been quarantined -- registry is not valid JSON; quarantined to …\state\fleet.json.corrupt.2026-08-09T160407Z
[PASS] autoclean: … quarantine artifact present (fleet.json.corrupt.2026-08-09T160407Z) -- husk sweep is refusing itself (NEW-1); restore the quarantined data, then remove the artifact
rc=1

=== D. fleet status after repair ===
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
rc=0
```

**The load-bearing half of CLAUDE.md's views rule holds:** neither `fleet status` nor a bare `fleet
doctor` quarantined anything — the corrupt file was still on disk after both. `doctor` is report-only;
`--repair` renames aside exactly as advertised; `autoclean` notices the artifact and refuses itself
rather than sweeping over it. **MATCH.**

One qualification, stated because the rule's wording invites it: CLAUDE.md says views must
*"read `fleet.status_snapshot()` and exit 0"*, and **`fleet status` exited 1** here. That is not a
breach of the rule as scoped — the rule names *"statusline, `/fleet:*`"*, and the CLI verb refusing
loudly on a corrupt registry is defensible. I did not measure `/fleet:status` or the statusline
against a corrupt registry, so **whether the exit-0 half holds at the surfaces the rule actually names
is UNVERIFIED by this lane.** Flagged, not claimed.

### W52-2 — **`fleet respawn` can refuse `"turn is running"` on an idle worker. MEDIUM.**

> **REGRADED AND PARTLY RETRACTED after gate `w52-glaunch3` (`e97bbcb`), which drove this finding six
> times on a byte-identical `bin/fleet.py`.** This heading previously read *"is unreachable by its
> documented invocation on Windows. **HIGH**"*, and the line under it read *"**MEASURED,
> deterministic, reproduced four times across ten minutes.**"* **Both are withdrawn.** The gate got
> **rc=0 on 5 of 6 drives** of the bare `fleet respawn <name>`, and its one reproduction was in a
> roster state this report never named (`blocked`), not the `state:"working"` pasted below. Its null
> is trustworthy: its positive control — respawn against a genuinely running turn — refused with
> rc=1, so its harness can see the refusal. A 30-sample / 60 s poll immediately after a turn ended
> showed only `state=done status=idle pid=present`: **no window, no transition.**
>
> **What survives, and it is the whole defect class:** `_roster_live_sids` decides liveness from key
> *presence* plus a single terminal state, and never from `status`'s *value* — so a finished session
> sitting in a non-`done` state with `pid`/`status` present is read as a running turn. The gate
> confirms that reasoning and reproduced it once. **What does not survive is the word
> *deterministic*, which is what the HIGH rested on.** A stranger following the documented
> invocation gets a working `respawn` most of the time, and when they do not, the refusal's own
> first clause names the escape that works. **MEDIUM.**
>
> I do not think the inflation was invention. The brief that produced this lane pre-committed the
> outcome — *"this rehearsal has never once been run without finding something … the something is in
> the half nobody has walked"* — and the manager has since said so in the same words. But **I** wrote
> *deterministic* after four drives that all pointed one way, and four same-direction drives is not a
> determinism claim. **The correct grade of a four-sample run is a rate, not an adjective.**

**MEASURED at the time — four drives, all refusing, over roughly ten minutes.** Read the retraction
above before this receipt: it is a true record of what my harness printed, and a 4-sample rate of 4/4
against the gate's 1/6 on the same code.

```console
$ fleet wait probe --timeout 240
probe: idle -- **Changed:** …
rc=0

$ fleet status
probe               idle           1        -        0     0        -  tokens:in=8 out=65

$ fleet respawn probe --yes
fleet: probe: turn is running -- pass --force to interrupt it first, or wait for it to finish
rc=1
```

`status --json` agrees with `status`, not with `respawn`:

```json
{ "name": "probe", "status": "idle", "turns": 1, "stale_seconds": 64.848781, "dispatch_kind": "bg" }
```

**Cause, MEASURED at the source.** `_cmd_respawn_native` gates on
`old_live = old_sid in _roster_live_sids(entries)` (`bin/fleet.py:8373`). `_roster_live_sids`
(`bin/fleet.py:14869`) counts a sid live when:

```python
and e.get("sessionId") and ("status" in e or "pid" in e)
and e.get("state") != "done"
```

The actual roster entry for the **idle** worker, at claude 2.1.226 on Windows:

```json
{
    "pid":  46460,
    "id":  "4c058fc0",
    "cwd":  "C:\\Users\\Techn\\AppData\\Local\\Temp\\w52-launch\\scratch",
    "kind":  "background",
    "startedAt":  1786290777718,
    "sessionId":  "4c058fc0-7e5e-4124-bd06-9d3d40d2d4c1",
    "name":  "fleet|probe|Create a file named hello.txt in the cur",
    "status":  "idle",
    "state":  "working"
}
```

`pid` present, `status` present, and **`state` is `"working"`, not `"done"`** — so the `done` guard
never fires, and a finished session is read as a running turn. Still `state=working status=idle` at
T+8 min, with pid 46460 alive.

> **The sentence that stood here next said *"Not a transient race."* WITHDRAWN.** The gate could not
> produce `state:"working"` on a finished session once in six drives, and its 60 s poll saw only
> `done`. My entry above is what my roster read — the roster is machine-global and we were looking at
> the same object five hours apart — but a state I observed four times and the gate observed zero
> times is not a stable property of a finished session, and I called it one.

#### The mechanism claim — **RETRACTED OUTRIGHT, and this is the instructive one**

This report charged the `_roster_live_sids` docstring with *"predicting this bug and then exempting
the platform it happens on"*, and concluded:

> ~~*"The fix that rescued macOS therefore cannot fire on Windows"*~~

**MEASURED FALSE by the gate, and the direction of the error is the lesson.** The `state != "done"`
guard **does** fire on Windows — it is precisely what makes five of the gate's six drives return
rc=0. Without it, all six would have refused. The guard is not inapplicable here; it is load-bearing
here.

**My own evidence pointed the other way and I read it backwards.** I measured 90 `done` entries that
had lost both keys and concluded the parenthetical was *"half true"*. The gate found the entries I did
not look for: `done` entries that **keep** `pid` and `status` — including **my own lane's session**,
on Windows, `done`, holding both. So on Windows a `done` entry keeps its keys while its host process
lives, which is exactly the macOS shape the docstring describes.

**Stated plainly, because it is the transferable error: I read a false parenthetical as an
exemption.** The parenthetical *"(On Windows the two conditions agree -- done entries lose
pid/status.)"* is simply wrong. But a wrong sentence in a docstring does not make the code it sits
above wrong, and I let the wrong sentence tell me what the code did instead of measuring the code.
**The code is right, the comment is wrong, and I inverted which was which.**

**What the genuine hole is, narrowed to what survives:** states that are neither `done` nor a running
turn are counted live. `blocked` — the gate measured it, and it is the state its one reproduction sat
in. `working` on a finished session — I measured it; the gate could not. Neither document names
either case, and `status`'s *value*, the field that actually reports turn completion, is never read.

**One of the two remedies the message offers is wrong** *(corrected: this read "**Both remedies … are
wrong**", and the gate is right that it is one too strong)*. *"wait for it to finish"* never
terminates when the turn has already finished. *"pass `--force` to interrupt it first"* is offered
**first** in the refusal text and it works — it interrupts nothing, but it does what the operator
wanted:

```console
$ fleet respawn probe --yes --force
probe 1b5bea1f-7b95-4791-a5e0-5998f124cf0a (native bg)
rc=0
```

There is a second escape, which no document names: `fleet interrupt` then `fleet respawn --yes`
succeeds (MEASURED). But `fleet interrupt`'s own success message points the operator at
`fleet respawn probe` — the bare form that refuses. **`interrupt` → `respawn` → "interrupt it first"
is a closed R2 loop between two verbs**, escapable only by adding `--force`, which the loop never
suggests as the primary remedy for an idle worker.

**Impact, restated at MEDIUM.** `fleet respawn` is the documented context-reset lever (README's
feature table; a `/fleet:respawn` slash command; `docs/getting-started.md` names it 3 times).
*Sometimes* — 1 in 6 on the gate's harness, 4 in 4 on mine — a stranger following the documented
invocation on an idle worker gets a refusal that misdescribes the state. The escape is in the
refusal's first clause. Real, worth fixing, not a launch blocker.

#### THE PROPOSED REMEDY — **RETRACTED. It is unsafe, and I never measured its blast radius.**

This section previously carried, as BELIEVED: *"the minimal correct fix is to stop inferring turn
state from key presence and read `status`'s value, e.g. treat `state in ("done","stopped","failed")`
**or** `status == "idle"` as not-a-running-turn."*

**Do not apply that.** It was reasoned from one call site and proposed for a shared helper. The gate
raised this BLOCKING; I re-derived the blast radius myself rather than inheriting its number, and
**by AST rather than by grep, because grep is what produced the wrong number in the first place**
(see W52-4, where a grep receipt of my own did not reproduce).

**MEASURED — `_roster_live_sids` call sites, by `ast.Call`, on `bin/fleet.py` `76b9bcbe…`:**

```console
$ py -3.13 callsites.py bin/fleet.py _roster_live_sids
target                 : _roster_live_sids
AST def sites          : [14869]
AST CALL sites (count) : 11
AST CALL sites (lines) : [8373, 8392, 8398, 9559, 9598, 9914, 10121, 15393, 15443, 15673, 18772]
bare Name refs (non-call, e.g. passed as a value): []

call sites by enclosing function:
  _any_live                                x1  lines 9598
  _archive_eligible                        x1  lines 10121
  _cmd_respawn_native                      x3  lines 8373,8392,8398
  _cmd_respawn_supervisor                  x1  lines 9559
  _doctor_check_supervisor_wedge           x1  lines 18772
  _render_boot_bundle                      x1  lines 15393
  _wedged_release_gate                     x1  lines 15673
  cmd_clean                                x1  lines 9914
  cmd_sup_boot                             x1  lines 15443

textual grep-style occurrences of the bare name: 14
```

**Eleven call sites, in nine functions.** The reasoning I did covered three of them, all inside
`_cmd_respawn_native`. The other eight include **four supervisor-identity sites** —
`_cmd_respawn_supervisor`, `cmd_sup_boot`, `_wedged_release_gate`, `_doctor_check_supervisor_wedge` —
plus `cmd_clean`, `_archive_eligible`, `_render_boot_bundle` and `_any_live`. Two of the supervisor
sites feed `_releaser_live_sids`, i.e. the decision *"may another supervisor take this claim"*.

**A correction to the gate, which does not weaken its finding.** The gate's number is **13**, from
`grep -n` returning 14 lines minus the `def`. Two of those 14 are prose, not calls —
`bin/fleet.py:8270` (a docstring naming the helper) and `:18724` (a docstring paragraph). The manager
told me to re-derive by AST rather than inherit, and this is why: **13 is a grep artifact of the same
family as the receipt the gate charged me with in G4.** The correct count is 11 calls / 14 textual
occurrences / 1 def. **The BLOCKING is unaffected** — the argument needs "many, including the
supervisor", not "thirteen".

**The hazard, measured on live data, on my own roster:**

```
roster size                                  = 181
live by _roster_live_sids today              = 8
of those, status=='idle' (my fix kills them) = 1
```

**One in eight currently-live sessions would be reclassified not-live by the `status == "idle"`
disjunct** — today a `claude-oracle-…` session with a live pid and **no `state` key at all**.

**On the supervisor instance specifically, I owe a distinction.** The gate MEASURED a supervisor at
`state:"blocked" status:"idle"` with pid 44232 alive — exactly the shape the proposed clause would
kill. I re-read that same session id five hours later and it has since **lost** `pid` and `status`:

```json
{"id": "3cb901f7", "cwd": "C:\\proga\\claude-fleet", "kind": "background",
 "startedAt": 1786268531571, "sessionId": "3cb901f7-b361-466e-9488-7df4dde80e3d",
 "name": "sup|inc-20260809T094210Z-5c4e|boot", "state": "blocked"}
```

So my re-measurement **neither confirms nor refutes** the gate's observation — the process died in
between, and a degraded observation is not a contradiction. I record the gate's as MEASURED-by-gate
and mine as a null that cannot speak. **The hazard does not depend on catching one live:** a
supervisor between turns *is* idle by definition, and four of the eleven call sites are supervisor
machinery. That is enough.

**Is `status`'s value even contractual?** The docstring cites `docs/specs/native-substrate.md`'s
roster contract for **key presence** (*"`status`/`pid` keys exist only while the process lives"*). I
found no clause making the *value* contractual and I cite none. **BELIEVED** — a `status`-value fix
builds on an unpinned field, which is a second, independent reason not to put it in the shared helper.

**What I now believe, stated as a direction and not as a diff:** any fix belongs **scoped to
`_cmd_respawn_native`**, not in `_roster_live_sids`, and it needs the roster contract settled first.
**REPORTED, not repaired.** I am explicitly *not* proposing the one-line change any more; the
campaign's standing count is that fix-waves mint defects 7 out of 7, and this remedy would have been
one of them.

### W52-3 — `interrupted` overflows the STATUS column. LOW, cosmetic, but on the primary surface.

MEASURED:

```console
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
probe               interrupted     3        -        0     0        -  -
```

`_text_cell(value, width)` returns `f"{value:<{width}}"` — a **minimum** width, not a truncation — and
the STATUS column is `<10`, so every column right of STATUS shifts. Only reachable by driving a worker
into `interrupted`, which no lane had done.

**The enumeration here originally named two statuses. It is three** *(corrected after gate
`w52-glaunch3` G6, and re-derived rather than inherited)*. MEASURED, against the statuses the code
actually writes into a record:

```console
$ grep -oE '\["status"\] = "[a-z_-]+"|"status": "[a-z_-]+"' bin/fleet.py | grep -oE '"[a-z_-]+"$' | sort -u
"dead"  "dead-suspected"  "idle"  "interrupted"  "limited"  "ok"  "orphan"  "over_ceiling"  "withheld"  "working"

  dead-suspected   len=14  OVERFLOWS
  over_ceiling     len=12  OVERFLOWS      <-- missing from the original enumeration
  interrupted      len=11  OVERFLOWS
```

**And I checked for a fourth, because an incomplete enumeration is the defect here.** `over_budget`
is 11 characters and appears in `_NATIVE_STICKY` (`bin/fleet.py:3657`) — but it is **never assigned**
as a status anywhere in the file; its only other occurrences are comments and docstrings. So it is a
fourth *name* in a sticky-guard tuple, not a fourth reachable status. **Three is the right number,
and the gate's three is confirmed by an independent derivation.** LOW stands; it matters only if
someone widens the column to 12 on this section's authority, which is exactly what an incomplete list
invites.

### Would a stranger have known the order?

**MEASURED — every lifecycle verb appears in both entry docs** (`grep -c "fleet <verb>"`, README /
getting-started): spawn 3/6, status 2/6, peek 2/2, send 3/2, result 2/3, wait 1/3, respawn 2/3,
interrupt 1/1, kill 1/2, clean 1/3, resume-limited 2/3. `doctor --repair` is documented as
`fleet doctor [--repair]` in README's CLI table. **Nothing in the lifecycle is undocumented.**

What a stranger would *not* have predicted, all MEASURED above:

- `fleet send` to an **idle** worker changes the worker's **session id** (`fork-steered (new session
  844c3e88)`). README describes it as *"a new turn if idle"*. A new turn and a new session are not the
  same thing, and the sid is the handle a user is told elsewhere to `claude attach` to.
- `fleet respawn` needs `--force` on a healthy idle worker (W52-2).
- `fleet kill` silently sweeps the whole retired-sid lineage — good, undocumented.

---

## 4. PART 3 — the statusline, installed and rendering, and the regression the blocker never got

### It renders

Taking `statusLine.command` **out of the settings file fleet wrote** and running it through a shell
with the blob Claude Code feeds (`{"session_id": …, "cwd": …, "model": …, "workspace": …}`):

```console
$ cmd.exe /c "type blob.json | "C:/…/python.exe" "C:/…/w52-launch/clone/fleet/bin/fleet_statusline.py""
[fleet]  sup none  idle 1
rc=0
```

25 characters, all ASCII (hex dumped: `5B 66 6C 65 65 74 5D …`), no ANSI bytes — consistent with the
module's *"the rendered line is PURE ASCII by construction"* invariant. It reports `idle 1`: **the one
real worker in my temp home**, so the line is derived from live registry state, not a stub. **MATCH.**

### The space regression — differential, not assertion

The launch blocker was a quoting defect that only bites on a spaced path, so I built one: a second
clone at `C:\…\Temp\w52 launch space\clone\fleet`, a second throwaway `~` at
`…\w52 launch space\fakehome`, and — after a false start — a **real interpreter at a spaced path**.

> **Instrument correction, recorded because it nearly produced a false pass.** My first spaced
> interpreter was a directory *junction* (`…\w52 launch space\py 313`). It did not work:
> `_install_statusline` writes `Path(sys.executable).resolve()`, and `.resolve()` follows the
> junction back to the unspaced target, so the command came out with a spaced *script* and an
> unspaced *interpreter*. A `python -m venv "…\w52 launch space\py venv"` produces a real file whose
> `resolve()` keeps the space. **A fence or a fixture you asserted is worth nothing.**

`fleet init --statusline` run with that interpreter, from that clone, writes:

```
"C:/Users/Techn/AppData/Local/Temp/w52 launch space/py venv/Scripts/python.exe" "C:/Users/Techn/AppData/Local/Temp/w52 launch space/clone/fleet/bin/fleet_statusline.py"
```

**Both paths spaced, both quoted.** The differential, all MEASURED, all through `cmd.exe`:

| # | Form | Result |
|---|---|---|
| A3 | as shipped — both quoted | `[fleet]  sup none  idle 1 7m`, rc=0 |
| B1 | interpreter quoted, **script unquoted** | `can't open file 'C:\Users\Techn\AppData\Local\Temp\w52'` |
| B3 | **interpreter unquoted**, script quoted | `'C:' is not recognized as an internal or external command` |
| B4 | both unquoted | `'C:' is not recognized as an internal or external command` |

**B1 is the clean one and it is the proof.** It changes exactly one thing — the quotes around the
spaced script path — and the interpreter then receives `C:\…\Temp\w52` as its script argument: the
path split at the space, which is the blocker, reproduced on demand. A3 is the same command with the
quotes restored and it renders real worker data.

**Honest limit on B3/B4:** those fail for a *compounded* reason — `cmd` also splits an unquoted
forward-slash path in command position — so they demonstrate that unquoting breaks the command, but
they do **not** isolate the space in the interpreter position. B1 does isolate it, in the script
position. I did not find a way to isolate the space alone in command position under `cmd`, and I am
not claiming one.

**This is the regression test the fix never got**, and it now exists as a receipt. It is not a
`tests/` pin — writing one was outside this lane's deliverable set — and **BELIEVED**: it should be,
because nothing in the suite currently renders `_install_statusline`'s output against a spaced path.

### W52-4 — **the fix does not reach installs that already exist, and nothing detects that. MEDIUM.**

**MEASURED, read-only, on the live machine.** The operator's real
`~/.claude/settings.json` currently holds:

```
C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py
```

```
contains a double-quote character = False
token count when split on space   = 2
```

**That is the pre-fix, unquoted form, still installed.** `_install_statusline` writes the quoted form,
but it only runs when someone runs `fleet init --statusline`; an already-installed statusline is never
re-rendered. It works on this machine only because neither path happens to contain a space.

**Who this bites, BELIEVED but on a firm premise:** on a default Windows install the user-scoped
Python lives under `%LOCALAPPDATA%`, i.e. under `USERPROFILE`, i.e. under `C:\Users\<account name>`.
**Any user whose Windows account name contains a space** gets a spaced interpreter path — so the
population for whom the blocker is still live is "installed before the fix" ∪ "account name has a
space", and the second set is large. MEASURED on this machine: my own account has no space, which is
precisely why the defect stayed invisible here.

**And `fleet doctor` cannot see it.**

> **THE RECEIPT PRINTED HERE DID NOT REPRODUCE, and the correction is below** *(gate `w52-glaunch3`
> G4, MAJOR)*. This paragraph claimed *"MEASURED by **exhaustive** reference count — three
> references"* and pasted a three-line block. Re-executed on a tree whose `bin/fleet.py` is
> byte-identical, plain `grep -n` prints **four**. The dropped line is `6040`, inside a docstring. I
> did not reconstruct how the block lost it — the honest reading is that I pasted a filtered or
> hand-trimmed view and labelled it as the command's output, which is the exact defect class this
> repo keeps paying for and which this same report charges the README with in W52-5. **The word
> *exhaustive* is withdrawn.**

MEASURED, re-executed at `76b9bcbe…` and quoted whole:

```console
$ grep -n "user_settings_path()" bin/fleet.py
353:def user_settings_path() -> Path:
6040:    DERIVED FROM `user_settings_path()` RATHER THAN RE-SPELLING `Path.home()`,
6052:    return user_settings_path().with_name("fleet-statusline-chain.json")
6204:    path = user_settings_path()
$ grep -c "user_settings_path()" bin/fleet.py
4
```

Four occurrences: the definition, **a docstring mention at `6040`**, the chain-path derivation, and
`_install_statusline` itself. `6040` is prose, so no `doctor` row is hiding in it and **the conclusion
is unchanged**: no doctor check reads the installed statusline, so the 28/28 a stranger is told to
trust says nothing about whether their statusline is the working form. REPORTED; the remedy is a
`doctor` row and is `bin/` work.

**The lesson I take, since a careful report shipped an uncareful receipt:** a pasted command block is
a claim that *this command prints this*, and reading the output is not checking it. Only re-execution
checks it. The gate found this by re-executing, and it is the one item it says it would have missed
by reading.

---

## 5. PART 4 — grading the documentation

### W52-5 — **the README's flagship demo block is output the shipped code cannot produce. MEDIUM. → FIXED ON THIS BRANCH.**

Where the code is right and the docs are wrong, in those words: **the code is right; README's
"See it in action" section is wrong.** It is the first thing a stranger reads.

> **CONFIRMED by gate `w52-glaunch3` line by line, five for five — and it is STRONGER than this
> section claimed.** The gate ran `git log -S` per tag and found that **`[mail]` and `[assistant]`
> have never existed in `bin/fleet.py` at any commit.** They are not substrate-pivot rot; they were
> invented. The gate also closed a scope hole I left open: *"the shipped renderer"* has no ambiguity,
> because `cmd_peek` calls `_cmd_peek_native` unconditionally with no legacy branch.
>
> **REPAIRED on this branch** *(licensed by the discharge brief)*: the block is now pasted verbatim
> from a real captured session. See "The replacement" below.

MEASURED at the renderer. `_render_native_peek_lines` (`bin/fleet.py:7103`–`7138`) emits exactly four
shapes, and its docstring enumerates them:

```python
lines.append(f"[text] {_truncate(text, 200)}")     # :7124
lines.append(f"[tool] {part.get('name', '?')}")    # :7126
tag = "[user:meta]" if rec.get("isMeta") else "[user]"   # :7136
```

`grep '\[mail\]' bin/fleet.py` → **no matches.** Now README lines 28–33:

```console
$ fleet peek migrate-users
[tool] Read MIGRATION.md
[tool] Write migrations/0042_users.sql
[mail] delivered: "also add a down-migration, I forgot to ask"
[tool] Write migrations/0042_users.down.sql
[assistant] Added the down-migration and re-ran the local suite; both pass.
```

**All five lines are unemittable:**

| README line | Why the shipped renderer cannot produce it |
|---|---|
| `[tool] Read MIGRATION.md` | `:7126` prints the tool **name only** — never arguments |
| `[tool] Write migrations/0042_users.sql` | same |
| `[mail] delivered: "…"` | there is no `[mail]` tag anywhere in `bin/fleet.py` |
| `[tool] Write migrations/0042_users.down.sql` | same as row 1 |
| `[assistant] Added the down-migration…` | assistant text renders as `[text]`, not `[assistant]` |

What a real `peek` looks like, MEASURED, from this lane's own worker:

```console
-- probe (4c058fc0) --
[tool] Read
[tool] Write
[tool] Write
[text] DONE
[user:meta] Stop hook feedback:
Also create a file named world.txt containing exactly the word WORLD.
```

**The steered message did land** — the worker created `world.txt`, and later `a4.txt` from a second
mid-turn `send` — so the *feature* README is advertising is real. Only its rendering is fictional.

#### The tool-boundary question — **RESOLVED IN THE DOCUMENTATION'S FAVOUR, and it produced W52-8**

This section originally said the delivery *"surfaced as `[user:meta] Stop hook feedback:`"* in both
observations, and therefore that README line 81's *"injected at the next tool boundary"* was **not
confirmed either way.** Generating the replacement demo block (Part B) required driving a real
mid-turn `send`, so I looked at the transcript instead of the digest. **MEASURED, twice, on two
independent workers:**

```json
{"attachment":{"type":"hook_success","hookName":"PostToolUse:Read","hookEvent":"PostToolUse",
  "stdout":"{\"hookSpecificOutput\": {\"hookEventName\": \"PostToolUse\",
   \"additionalContext\": \"<MANAGER MESSAGE>\\nalso add a down-migration, I forgot to ask\\n\\n\"}}"},
 "type":"attachment"}
```

`hookName: "PostToolUse:Read"` — the message was injected **at the tool boundary immediately after
the worker's `Read`**, exactly as README line 81 says. **The claim is TRUE and now MEASURED.** My
"not confirmed" was a null produced by a blind instrument, and the instrument was `fleet peek`.

**W52-8 (NEW, LOW) — `fleet peek` cannot show a mailbox delivery that arrives at a tool boundary.**
MEASURED at the filter: `_is_substantive_transcript_record` opens with

```python
if rec.get("type") not in ("assistant", "user"):
    return False
```

and a PostToolUse delivery is recorded as `type: "attachment"`. So the record is dropped before
`_render_native_peek_lines` ever sees it, and no `-n` widens the window enough to reveal it — I tried
`-n 20` on a transcript whose delivery sat at record 31 of 80, and it did not appear. **Both delivery
paths exist and only one is visible:** a Stop-hook delivery is a real `user`/`isMeta` record and
renders as `[user:meta]` (my Part 2 observations); a PostToolUse delivery is an `attachment` and
renders as nothing.

**This is the hole the fabricated `[mail]` line was papering over.** Someone wanted `peek` to show a
steer landing; `peek` structurally cannot, for the delivery path the README's own prose advertises.

**Graded LOW, deliberately, and with the case for MEDIUM stated rather than taken:** there *is* a
surface that answers "did my steer land" — `fleet status`'s `MAIL` column goes `0 → 1` on queue and
back to `0` on delivery, MEASURED in both drives. So the operator is not blind, only `peek` is. Given
the gate has just corrected this report for grading a real finding one notch high, I am not going to
do it twice in the same document.

The same block's `fleet status` row is wrong for a second, independent reason:

```console
$ fleet status
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
migrate-users       working        1     0.00        2     0        -  -
```

MEASURED at `bin/fleet.py:7085`:

```python
if is_native(rec):
    # G3: USD cost is REFUTED-for-contract under native dispatch --
    # render "-", never a stale/zero dollar figure.
    cost_s = f"{'-':>9}"
```

Every worker is native (`dispatch_kind: "bg"`; the spawn banner says `native bg`), and every
`fleet status` in this lane rendered `-`.

> **The sentence here overreached and is corrected** *(gate `w52-glaunch3` G5)*. It read: **"`0.00`
> is a value the code is explicitly written never to print**, and the comment says so." The comment
> says so **for the native branch only**. Fifteen lines on, the `else` branch calls `_cost_cell`,
> which returns `f"{cost:>{width}.2f}"` and therefore *does* render `0.00` for a cost of `0.0`. That
> branch is live code, reached when `dispatch_kind != "bg"` — a **pre-pivot record**. Every spawn
> site sets `"bg"`, so nothing fleet can spawn today reaches it.
>
> **Correct wording, and what the finding actually is:** `0.00` is never printed for any worker fleet
> can spawn today. The README example shows a `COST` value that no current worker can produce — which
> is the defect — but the code is not "written never to print it" in general, and I should not have
> said so on the strength of a comment attached to one branch of an `if`.

README's own line 49 correctly explains that USD budgets are refused under G3 — **the prose and the
example in the same document disagree, and the prose is right.**

**This is w48's headline shape repeating one level down.** w48 found the docs wrong about hazards; this
is the docs wrong about *output*, in the block that exists to show a newcomer what the tool looks
like. Nothing tests it: `tests/test_doc_claims.py` pins verbs, flags and counts against the parser —
by its own docstring — and a pasted sample transcript is none of those.

#### The replacement — generated, not composed

**REPAIRED on this branch.** `README.md`'s "See it in action" block is now a verbatim capture of a
real session driven for this discharge: a fenced clone at `64b43c2`, a haiku worker, a genuine
Knex→SQL port in a scratch project, and a genuine mid-turn `fleet send`. The block carries the real
`spawn` banner (`model: haiku`, a full session id), `COST` as `-`, `MAIL` going `0 → 1`, the real
`peek` tag vocabulary, `peek`'s own 200-character truncation, and the worker's actual result text.

Two things I added rather than merely fixing, because a fix that does not stop the recurrence is half
a fix:

1. A caption stating the block is a verbatim capture, **naming that an earlier version was
   hand-written and that none of its `peek` lines were producible**. A future editor now has to
   knowingly overwrite that sentence to reintroduce the defect.
2. Two sentences of prose making `MAIL 0 → 1 → 0` the documented way to confirm a steer landed, and
   saying outright that `peek` does **not** show the delivery (W52-8). The fabricated `[mail]` line
   existed because the README needed to show something `peek` cannot show; deleting the line without
   answering the need would have left the same pressure in place.

### W52-6 — the §18 question the brief asked, answered: the repair went the *other* way

The brief said `docs/launch-readiness.md` inherited a known error from CLAUDE.md and asked me to check
whether it was corrected. **MEASURED: it was corrected first, and it is the source of the correction,
not an inheritor of the error.** `docs/launch-readiness.md:222` opens the entry struck through —
*"### 8. ~~`SPEC.md` §18 is stale by two milestones~~ — WITHDRAWN 2026-08-09: it was false when
written"* — and w48's MINOR-6 discharge is where that withdrawal was argued.

**But the repair created a fresh stale sentence, in the document that reported it.**
`docs/launch-readiness.md` (the paragraph at `4ccc8f7`'s lines ~258–264) still says:

> It was relayed from root `CLAUDE.md`, whose opening paragraph **still reads** *"M-D and M-E shipped
> after and are **not yet folded into §18**"* — a line stale since `36a4c53`. … **The stale text that
> remains is root `CLAUDE.md`, not `SPEC.md`** — outside this lane's fence, flagged for whoever owns
> it.

CLAUDE.md was then corrected (its own text dates the correction 2026-08-09). So that paragraph now
makes a false claim about a sibling document: CLAUDE.md's opening paragraph does **not** still read
that. **A sentence that reports an outstanding repair rots the moment the repair lands** — and this
one is load-bearing, because it tells a reader where the remaining defect is.

**And the instrument nearly said the opposite.** MEASURED:

```console
$ grep -c "not yet folded into" CLAUDE.md
1
```

A count of 1 reads as "CLAUDE.md still says it." It does not. The surviving occurrence is CLAUDE.md
**quoting the sentence in order to retract it**: *"The superseded sentence said M-D and M-E were 'not
yet folded into §18', which sent readers past the section that answers them."* A substring count is
not a claim about assertion, and on this exact question — where the whole dispute is about a quoted
sentence — the naive detector inverts the answer. Per the brief's own rule, I checked the vantage
before believing the reading.

~~**REPORTED, not repaired.**~~ **REPAIRED on this branch** *(licensed by the discharge brief; the
original sentence deferred it to "whoever owns that document this wave", and that turned out to be
me)*. `docs/launch-readiness.md`'s paragraph now (a) puts the CLAUDE.md quotation in the past tense,
(b) records that CLAUDE.md has since been corrected and that this paragraph was the last place saying
otherwise, and (c) warns that a substring search still matches CLAUDE.md and that the match is a
retraction — so the next reader does not re-open this on a `grep -c`.

**CONFIRMED by gate `w52-glaunch3`, which sharpened it:** `docs/launch-readiness.md` is **not** in
`_HISTORICAL_PREFIXES`, so by this repo's own exemption logic it is a current-tree document — a stale
present-tense claim there is exactly the class the exemption exists to keep held.

**The everywhere-rule, applied and MEASURED after the fix** *(the discharge brief's governing rule:
apply each repair everywhere the claim appears, not where the gate quoted it)*:

```console
$ grep -rn "not yet folded into" --exclude-dir=.git .
./CLAUDE.md:5:                    … quoting the superseded sentence in order to retract it
./docs/lanes/w48-launch.md:831:   … dated lane history, quoting
./docs/lanes/w52-launch.md:786:   … this report, quoting
./docs/lanes/w52-launch.md:798:   … this report's own grep receipt
./docs/launch-readiness.md:260:   … now past tense ("then read"), inside the retraction
./docs/launch-readiness.md:268:   … the new warning that a substring match is a retraction

$ grep -rn "still reads" --exclude-dir=.git . | grep launch-readiness
(no matches)
```

**Zero asserting occurrences remain.** The other `still reads` hits in the tree are unrelated
documents about unrelated claims, checked individually.

### Two README self-limits this lane discharges — **still unrepaired, and deliberately so**

MEASURED — README line 136 currently reads:

> Two things this quickstart cannot do for you. The walkthrough is only executed as far as `fleet
> doctor` — **nothing from `fleet spawn` onward is covered by a rehearsal receipt.** And step 3's
> marketplace argument, a directory path to the clone, is the form a known-working install on the
> maintainer's machine reports, **not a form re-executed on a clean box.**

Both clauses are **false in the good direction**, and this report is the receipt for both: §3 covers
`spawn` through `clean`, and §2 step 3 re-executed the directory form on a throwaway box, rc=0. The
gate independently confirmed the sentence is still in the tree exactly as quoted.

**I did not fix it, and the reason is scope rather than tidiness.** The discharge brief licenses two
documentation repairs by name — W52-5 and W52-6 — and this is a third claim in the same file as one of
them. Its correct rewrite also *depends* on the regrade above: the honest residue is no longer "the
drive found a HIGH defect" but "found a MEDIUM one, at a rate of 1-in-6 on an independent harness",
and that sentence should be written by whoever holds the settled grade. Flagged here, loudly, as the
most conspicuous known-false sentence left in a launch-facing document. It is one paragraph of work.

### What the docs got right — MEASURED, and worth saying

- **28 checks, 28 PASS** on a fresh home. README's number is exact.
- **33 subcommands**, matching `getting-started.md:296` — w48's correction held.
- **Step 1's PATH block is copy-pasteable** and the callout's "PATH order decides" model is the one
  that reproduces.
- **`fleet init` is honest and narrow** — one file, 0.26 s, and it names both values it substituted.
- **`Hooks (0)`** — the no-injection guarantee, confirmed by the vendor's own inventory after a real
  install.
- **The plugin installs and resolves** from the directory form, on a clean config, first try.

---

## 6. W52-1 — the fence finding, stated as its own item

**The `USERPROFILE` redirection fences `~/.claude` cleanly. It is the two-fence consequence that is
new.** MEASURED both directions:

- With the redirect: `fleet init --statusline` is runnable and contained (§2 step 4), `claude plugin
  install` is runnable and contained (§2 step 3), and `doctor`'s three `~`-scoped rows report a fresh
  machine (§2 step 5). All three were previously unreachable.
- With the redirect: **no worker can run.** `Not logged in · Please run /login`, rc=1.

So there is no single fence under which this whole rehearsal runs. **Any future lane that wants both
halves needs two fences and must say which one each measurement came from** — this report does, per
section. A lane that used one fence throughout would either skip step 4 (as w48 had to) or report a
lifecycle that never launched.

**The primitive the doctrine does not name.** BRIEF-TEMPLATE's stanza offers two: `--fleet-home` for
an initialised home, `FLEET_HOME` + sid removal for one you are creating. This lane used a **third**:
*invoke the target clone's own shim with `FLEET_HOME` unset*, so §5 falls through to step 4, the
install-root default. It is the primitive the README already tells every stranger to use, it needs no
env var, and it is what actually contained Part 2 (§1c). Its precondition is the one w48's MAJOR-1
discharge stated and this lane re-verified before and after: **`~/.claude/fleet-homes.list` absent or
empty.** MEASURED absent at the start and at the end.

---

## 7. Every `fleet` command I ran, and which home it touched

MEASURED. Every row's home was gated by `fleet home` invoked the same way, compared normalised.

| Fence | Commands | Home actually touched |
|---|---|---|
| A: redirect + clone shim, `FLEET_HOME` unset | `home` ×3, `init`, `init --statusline`, `doctor` | `…/w52-launch/clone/fleet` (+ the **fake** `~/.claude/settings.json`) |
| B: spaced tree, redirect to spaced fake `~` | `home`, `init --statusline` ×2 (2nd `--force`) | `…/w52 launch space/clone/fleet` (+ the **spaced fake** `~`) |
| C: real `~`, sid removed, clone shim | `home` ×6, `spawn`, `status` ×12, `status --json`, `peek` ×4, `send` ×4, `wait` ×3, `result`, `respawn --yes` ×3, `respawn --yes --force`, `interrupt`, `resume-limited`, `kill --yes`, `clean --yes`, `doctor` ×2, `doctor --repair`, `--help` | `…/w52-launch/clone/fleet` |
| — | **`C:\proga\claude-fleet\bin\fleet.cmd home`, ONCE, deliberately** | printed `C:/proga/claude-fleet` |

**That last row is disclosed rather than buried.** I invoked the **live** shim exactly once, as the
third arm of the §1c discriminator. `home` is read-only — `cmd_home` is a single `print` of
`Path(FLEET_HOME).resolve().as_posix()` (`bin/fleet.py`, `cmd_home`) — and it took no lock and wrote
nothing. Without that arm I could not have shown *which* leg contains this lane.

`claude` commands: `plugin marketplace add|list`, `plugin install`, `plugin details` (fence A → the
fake `~`); `plugin marketplace list` ×2 **unfenced, read-only**, as the control; `agents --json --all`
×4, read-only, machine-global by nature; `claude -p` once under fence A (failed auth, §1d).

**Never run, per the fence:** `fleet homes --add` / `--retire`; `fleet init` against the live home;
any write to the real `~/.claude/settings.json`; any `claude plugin` mutation outside the throwaway.

---

## 8. What I left behind — the containment audit, with its detector controlled

**MEASURED, baseline taken before the first command and re-taken at the end.**

| Artifact | Baseline (20:45) | Final (21:05) | Verdict |
|---|---|---|---|
| `~/.claude/settings.json` sha256 | `578BDE7B…D918` | `578BDE7B…D918` | **byte-identical** |
| …size / mtime | 1859 / `2026-08-08T22:34:02.8541898+05:00` | 1859 / `2026-08-08T22:34:02.8541898+05:00` | unchanged |
| `~/.claude/fleet-homes.list` | ABSENT | ABSENT | never created |
| `~/.claude/fleet-statusline-chain.json` | ABSENT | ABSENT | never created |
| `C:/proga/claude-fleet/state/worker-settings.json` | mtime `2026-07-30T08:12:18`, sha `642BDCBE…` | identical | no `fleet init` on the live home |

**The `.bak` files, checked because a count alone would have looked incriminating.** The real `~`
holds two `settings.json.bak.*` files. MEASURED mtimes: `2026-07-09T20:37:55` and
`2026-07-13T19:45:31` — **a month before this lane**, from earlier operator installs. Fleet's backup
step ran twice in this lane and both backups are in the throwaway homes.

**Why I was contained, not merely that I was:**

1. **Part 1** — three legs, any one of which sufficed for the machine-global files: the write targets
   themselves resolved into the throwaway (§1a, measured at fleet's own functions, with a control
   showing the real paths).
2. **Part 2** — one leg did the work: `INSTALL_ROOT` = the clone ⇒ population = `[clone]` ⇒ the sid
   lookup searches a registry that has never heard of my session. **Proven by the discriminator in
   §1c**, where restoring my sid changed nothing and switching to the live shim changed everything.
   Its precondition — an absent `fleet-homes.list` — was verified at both ends.

**Disclosed, because Part 2's fence was narrower on purpose:** running real workers wrote Claude
Code's own state in the real `~` — session records under `~/.claude/projects`, entries in the agents
roster, and `~/.claude/daemon.log`. MEASURED: after `fleet kill` + `fleet clean`, all six probe
sessions read `stopped`/`done` with no pid, and the only live agent under a `w52-launch` cwd is this
lane's own session. **No process was left running.**

**Left on disk deliberately, for an adversarial gate to re-run:** the two throwaway trees
(`…\Temp\w52-launch`, `…\Temp\w52 launch space`) and their helper scripts. Both are under the OS temp
dir and touch nothing else. *(Added at discharge: `…\Temp\billing-service` — the scratch project the
replacement README block was captured against — and `$CLAUDE_JOB_DIR\tmp\w52d\`, the discharge
clone.)*

### THE CENSUS THIS SECTION OWED — what the narrow fence could NOT have caught

*Added at discharge; gate `w52-glaunch3` G9 is right that its absence was this report's largest
structural gap, and that a clean audit without it is a smaller statement than it looks.*

The table above is a claim about **five named artifacts**. It is not a claim that nothing was written.
Stated precisely, so nobody reads it as broader than it is:

| What the fence would have caught | What it would NOT have caught |
|---|---|
| A write to `~/.claude/settings.json` (hashed before/after) | A write to any **other** path under the real `~/.claude` |
| A `fleet-homes.list` append (absence checked both ends) | A file created and deleted **inside** my observation window |
| A `fleet-statusline-chain.json` (absence checked both ends) | A write reaching `~` via a **fourth spelling** of `Path.home()` |
| A `fleet init` against the live home (`worker-settings.json` mtime+sha) | A write to any other file in the live `C:/proga/claude-fleet` tree |
| A live worker process left behind (roster, pid) | A registry mutation in the live home that left no live process |

**The load-bearing weakness, named:** under Part 2's legs (1)+(2) the real `~` is *in scope for
writes*, and my audit covers it only at the three fleet-owned paths I knew to name. `_install_statusline`
is proven not to have run against the real home **by absence of invocation** — I did not run
`fleet init --statusline` outside the redirect — not by containment. Anything writing `~/.claude` under
a path helper I did not enumerate would have landed in the operator's real config and **no row in my
table would have seen it.**

**How much of a hole is it, measured rather than waved at.** MEASURED at `76b9bcbe…`, quoted whole:

```console
$ grep -n "Path.home()" bin/fleet.py
358:    return Path.home() / ".claude" / "settings.json"          <-- user_settings_path
368:    docstring that *"any new `Path.home()` path added to fleet lands here by
377:    return Path.home() / ".claude" / "fleet-homes.list"       <-- homes_list_path
386:    Portable by construction: `Path.home()/".claude"` is the vendor's config
392:    return Path.home() / ".claude" / "daemon.lock"            <-- claude_daemon_lock_path
398:    return Path.home() / ".claude" / "daemon.log"             <-- claude_daemon_log_path
2597:        candidates = sorted(Path.home().glob(f".claude/projects/*/{sid}.jsonl"))   <-- a READ
6040:    DERIVED FROM `user_settings_path()` RATHER THAN RE-SPELLING `Path.home()`,
6044:    `Path.home()` spelling would sit outside that sandbox exactly as
12240:    PORTABILITY (SPEC.md v3 invariant 8): pure `Path.home()` + `Path.read_text`
$ grep -c "Path.home()" bin/fleet.py
10
```

**Ten occurrences: four path-returning helpers, one transcript read, five prose lines.** And zero in
the other code that runs — `bin/fleet_statusline.py` and all four `bin/hooks/*.py`:

```console
$ grep -l "Path.home()" bin/hooks/*.py bin/fleet_statusline.py
(no file matches)
$ ls bin/hooks/*.py | wc -l          # the null is not vacuous: the files exist
4
```

So there is no fifth `~`-writer, and the hole is narrow. **But *"I enumerated the writers and found
four"* is the statement I can defend, and *"nothing was written"* is the statement I made.** Those are
different, and the gate is right that I made the second while measuring the first.

**And a whole-tree digest would not have closed it either**, which is worth saying because it is the
obvious rebuttal: the real `~` is outside any tree digest I ran, and `~/.claude` churns continuously
under a live machine (`daemon.log`, `history.jsonl`, `projects/`), so a whole-`~` snapshot could not
truthfully return UNCHANGED — the same lesson w48's MINOR-4 paid for with `state/`. **A fence receipt
on a live machine must name the files the feared write would touch. Mine did. It just must not then
be summarised as if it had named all of them.**

---

## 9. WHERE THIS BRIEF WAS WRONG

**1. The headline prediction inverted.** The brief's likeliest-wrong guess was *"that the `USERPROFILE`
redirection fences `~/.claude` cleanly (it may not, and if it does not, step 4 stays unrunnable and
that is your headline)."* It fences cleanly — measured at fleet's own path helpers, with a control.
The failure is the opposite one: **it fences `claude` too, which takes the credentials with it**, so
the redirect that unlocks step 4 forbids Part 2. The headline is not "step 4 is still unrunnable"; it
is "no single fence runs this rehearsal, and a lane that uses one will silently deliver half of it."

**2. The brief's stated fence mechanism is not the one that held.** It says: *"Removing
`CLAUDE_CODE_SESSION_ID` from the child environment is what makes the fence hold."* MEASURED false for
this lane's configuration: with my real sid **restored**, the clone's own shim still resolved to the
clone (§1c). The sid removal is the correct remedy when the install root can see the live home — it
was never the operative leg here. **The brief inherited the wave-48 remedy without its precondition**,
which is the exact shape it warned me to look for. The stanza's own two primitives also do not cover
what this lane actually did (§6): there is a third, `FLEET_HOME` unset + the target clone's own shim,
which is what the README already prescribes.

**3. "Quickstart steps 1 → 4" is four steps of a five-step quickstart.** Minor, but step 5
(`fleet doctor`) is the one that produces the "28 PASS" a stranger is told to trust, and it is where
w48's open BELIEVED got discharged.

**4. "Step 3 must not be run" was right about the risk and wrong about the possibility.** The brief
says *"NEVER run `claude plugin marketplace add` or `plugin install` — those mutate the operator's
real plugin configuration; wave 48 correctly refused them."* True **only without the redirect**. With
it, they mutate the throwaway, which the control proves (empty fenced list vs the operator's five).
Obeying the instruction literally would have left `launch-readiness.md` gap 2a open for a third wave
running. I ran them under a fence I proved first — which is what the brief's own governing principle
asks for, and it conflicts with its literal prohibition.

**5. "If you must cut, cut Part 4" was not needed, and Part 4 was not the cheap part.** Nothing was
cut. Part 4 produced W52-5 — a five-line README block none of which the code can emit — which is a
larger doc defect than anything Parts 1–3 found in prose, and it took one `grep` after the drive told
me what real output looks like. **The drive is what made the prose grading cheap**, so the two are not
separable in the order the brief assumed.

**6. Where the brief was exactly right, and it paid.** *"Do not read a clean containment audit as
proof the fence worked."* My audit is clean; the reason it is clean differs between my two halves, and
I only know that because I ran the discriminator instead of asserting a mechanism. Likewise *"run any
measurement whose good answer is 0 against a known non-zero input first"* — it caught the junction
that silently unspaced my interpreter (§4) and would have produced a false green on the one thing Part
3 exists to test. And *"an instrument's answer is about the tree it is STANDING IN"* — `grep -c "not
yet folded into" CLAUDE.md` returns 1 for a document that says the opposite (§5, W52-6).

**7. This report's own weakest claims, named so a gate does not have to find them** — *and updated at
discharge, because naming a weak claim is not the same as leaving it weak. Two of the five were one
command from a measurement, and the gate was right to say so.*

- ~~README line 81's *"injected at the next tool boundary"* is **not confirmed**~~ → **RESOLVED,
  MEASURED, and the doc is right.** `hookName: "PostToolUse:Read"`, twice, on two workers (§5). My
  "not confirmed" was a null produced by a blind instrument, and the blind instrument was `fleet
  peek` — which became W52-8. **A non-claim that is really an undiagnosed instrument failure is worth
  less than nothing: it reads as caution and is actually an unexamined bug.**
- ~~The views-doctrine exit-0 half is **unverified at the surfaces the rule names**~~ → **RESOLVED at
  the statusline, MEASURED BY ME** (not inherited from the gate, which also ran it), with the control
  first:
  ```console
  === POSITIVE CONTROL: healthy registry ===   [fleet]: no workers          rc=0
  === CORRUPT registry ({ this is not json) ===[fleet]: registry unreadable rc=0
  registry still present = True; content = { this is not json
  quarantine artifacts   = 0
  ```
  **The rule holds at the statusline: it reads, renders a word, exits 0, and quarantines nothing.**
  For the `/fleet:*` half, "exit 0" has no direct referent — they are prompt templates, and what they
  invoke is the CLI verb, which exits 1 by design and does not quarantine (§3). **A refusal to claim
  that costs one command is a gap wearing humility**, and this was one.
- W52-4's affected population ("account names with spaces") is **still BELIEVED**, reasoned from where
  Windows puts user-scoped Python. Nobody has measured it, the gate says so too, and it is the reason
  W52-4 stays MEDIUM rather than going higher.
- The space could not be isolated alone in the **interpreter** position under `cmd` (§4); B1 isolates
  it in the script position and that is the proof I am standing on. **Ungraded by the gate** — it did
  not rebuild the spaced tree — so Part 3 rests on my measurement alone.
- One `claude` version, one OS. Everything here is Windows 10 / claude 2.1.226. **The gate's
  refutation of `state:"working"` carries the same limit**, so W52-2's rate is a claim about this
  machine on this day and not about the platform.
- **New at discharge:** Part 1 (quickstart steps 1–5) is **ungradeable now**. The gate could not audit
  it because I deleted nothing — but the throwaway trees it needed were mine and it did not rebuild
  them, and a future reader cannot re-run those receipts either. **A rehearsal whose evidence lives in
  a temp tree cannot be gated on its central half**, which is the gate's observation and is a defect
  in how this lane was *structured*, not in what it measured.

---

## 10. Findings ledger

**Severities below are POST-GATE.** Where a grade moved, the original is struck through so the change
is visible rather than quiet.

| # | Class | Sev | Finding | Where | Disposition |
|---|---|---|---|---|---|
| W52-1 | fence doctrine | **HIGH** | `USERPROFILE` redirect fences `claude` too, so credentials go with it: no single fence runs both halves of this rehearsal | §1d, §6 | **CONFIRMED + strengthened by gate**; doctrine input for BRIEF-TEMPLATE |
| W52-2 | (c) code | ~~HIGH~~ **MEDIUM** | `fleet respawn` **can** refuse `"turn is running"` on an idle worker — 4/4 on my harness, **1/6 on the gate's**, its one reproduction at `state:"blocked"`. `_roster_live_sids` never reads `status`'s *value*, so a finished session in a non-`done` state with keys present reads as live. ~~Both remedies wrong~~ → one of two. **Mechanism claim retracted; proposed remedy retracted as unsafe** | §3 | **REPORTED** — `bin/` untouched, and the obvious fix is now known-unsafe |
| W52-3 | (c) code | LOW | `dead-suspected` (14), `over_ceiling` (12) and `interrupted` (11) overflow the `<10` STATUS column. ~~two statuses~~ → **three**; `over_budget` checked and **not** reachable | §3 | **REPORTED** |
| W52-4 | (b) gap | MED | The statusline quoting fix never reaches an already-installed statusline; the live machine still runs the unquoted form, and **no `doctor` row reads `user_settings_path()`**. Finding CONFIRMED; ~~"exhaustive… three references"~~ → the receipt prints **four** | §4 | **REPORTED** |
| W52-5 | (a) doc | MED | README's flagship demo: all 5 `fleet peek` lines are unemittable — and per the gate `[mail]`/`[assistant]` **never existed at any commit**. `0.00` rescoped: never printed for any worker fleet can spawn today | §5 | **FIXED on this branch** — block replaced with a verbatim capture |
| W52-6 | (a) doc | LOW | `docs/launch-readiness.md` asserted root `CLAUDE.md` "still reads" the superseded §18 sentence, after CLAUDE.md had been corrected — a repair-tracking sentence that rotted when the repair landed | §5 | **FIXED on this branch** + whole-tree everywhere-check |
| W52-7 | (b) doc | LOW | `fleet send` to an idle worker changes the **session id** (fork-steer); described as "a new turn if idle" in README, `getting-started.md` **and** `skills/fleet/SKILL.md` (gate: three surfaces, not one) | §3 | **REPORTED** |
| W52-8 | (b) gap | LOW | **NEW at discharge.** `fleet peek` cannot show a mailbox delivery that arrives at a tool boundary: the record is `type:"attachment"` and `_is_substantive_transcript_record` drops it. This is the hole the fabricated `[mail]` line was papering over | §5 | **REPORTED**; README now documents `MAIL 0→1→0` as the surface that does answer it |
| — | — | INFO | README line 81's *"injected at the next tool boundary"* is **TRUE and now MEASURED** (`PostToolUse:Read`, twice) — my earlier non-claim withdrawn | §5 | discharged |
| — | — | INFO | The views exit-0 rule **holds at the statusline**, measured by me with a control: rc=0, `[fleet]: registry unreadable`, zero quarantine artifacts | §9 | discharged |
| — | — | INFO | Step 3 gap 2a **CLOSED**: directory-form marketplace install re-executed on a clean box, rc=0. GitHub shorthand still untested | §2 | discharged |
| — | — | INFO | w48 §11's BELIEVED **discharged**: `identity-witness`/`claude-agents`/`daemon-wedge` all PASS on a fresh `~` | §2 | discharged |
| — | — | INFO | README line 136's two self-limits are still false in the good direction — **left unrepaired on purpose**, outside the licensed scope, and its rewrite depends on W52-2's settled grade | §5 | flagged for a successor |

**Repaired in this lane: exactly two documentation defects, both licensed by the discharge brief**
(W52-5, W52-6). **`bin/` is untouched** — `git diff --stat` against `64b43c2` names no file under
`bin/`. Every code finding stays REPORTED with its measurement, and W52-2's obvious remedy is now
recorded as *known-unsafe* rather than as a suggestion.

**The honest state of "launch-ready", updated twice.** Before this lane: the install half was
rehearsed and repaired, the use half had never been driven. After the lane: both halves had been
driven, and the use half returned what I graded a HIGH. **After the gate: that HIGH is a MEDIUM that
reproduces about one time in six, and its stated mechanism was backwards.** What stands is a real
intermittent defect on the context-reset lever, a still-unquoted statusline on the live machine that
no check inspects, a flagship README example the code could never have produced — now replaced with a
real one — and a `peek` that cannot show the feature the README advertises.

**The rehearsal has never once been run without finding something. That is still true, and it is now
true of the report as well** — which is the gate's line, and it is the right one to close on. The
most expensive defect this document contained was not in the half nobody had walked; it was in an
adjective I wrote about my own measurement.

---

# 11. DISCHARGE — against the `w52-glaunch3` gate verdict

**Gate:** branch `w52/glaunch3`, report `docs/lanes/w52-glaunch3.md` @ `e97bbcb`, cut at this
branch's tip `7c87730`. Verdict **GATING — 1 BLOCKING, 3 MAJOR, 5 MINOR.** Read in full before this
section.

**All nine accepted. I looked for a defensible refusal and did not find one.** The BLOCKING is a real
hazard in a change I proposed without measuring its reach; the three MAJORs are each a sentence *this
report shipped* that does not survive re-execution. Where I add to the gate rather than merely
complying — the call-site count, and a null it read as a confirmation — it is argued below, not
assumed.

| Gate item | Disposition | Where |
|---|---|---|
| **G1 BLOCKING** — proposed remedy unsafe/unscoped | **ACCEPTED — remedy RETRACTED**, blast radius re-derived by AST (11 call sites, 9 functions, 4 supervisor), hazard quantified (1 of 8 live sessions today) | §3 |
| **G2 MAJOR** — HIGH grade / *"deterministic, reproduced four times"* | **ACCEPTED — regraded MEDIUM**, phrase struck, gate's 1-of-6 and the `blocked` state recorded | §3 + banner |
| **G3 MAJOR** — macOS/Windows mechanism backwards | **ACCEPTED — RETRACTED outright**, replaced with what was measured, and named as "I read a false parenthetical as an exemption" | §3 |
| **G4 MAJOR** — `user_settings_path()` receipt prints 4, not 3 | **ACCEPTED** — receipt re-executed and quoted whole, *"exhaustive"* withdrawn; finding survives | §4 |
| **G5 MINOR** — `0.00` sentence overreaches | **ACCEPTED** — rescoped to *"never printed for any worker fleet can spawn today"* | §5 |
| **G6 MINOR** — two overflowing statuses, not three | **ACCEPTED** — `over_ceiling` added; I also checked for a fourth and `over_budget` is **not** reachable | §3 |
| **G7 MINOR** — no suite claim in the report | **ACCEPTED** — a real floor is now in this document, below | §11 |
| **G8 MINOR** — statusline exit-0 was one command away | **ACCEPTED — and I ran it myself** rather than citing the gate's run, with a positive control | §9 |
| **G9 MINOR** — no census of what the narrow fence could not catch | **ACCEPTED** — census added, with the `Path.home()` enumeration that bounds it | §8 |

## What I add back to the gate

**1. The call-site count is 11, not 13 — and the difference is the gate's own G4 defect.** The gate
derived *"13 call sites"* from `grep -n` returning 14 lines minus the `def`. Two of those 14 are
prose: `bin/fleet.py:8270` and `:18724`, both docstrings naming the helper. By `ast.Call` the answer
is **11 calls in 9 functions** (receipt in §3). The manager told me to re-derive by AST rather than
inherit the number, and this is exactly why. **The BLOCKING is untouched** — it needs "many call
sites, including the supervisor's", and 11 is many. I record it because a gate that charges a report
with a grep-shaped receipt should not rest its own headline on one.

**2. One of the gate's confirmations is a null it could not have failed.** Its §7 says the
containment audit *"re-verifies on every line I can read"* — true, and it re-measured the degrading
half first, which is right. But four of the six rows are absence checks (`fleet-homes.list`,
`fleet-statusline-chain.json`, and two "unchanged" hashes), and **the gate ran no positive control on
its own file-absence detector**, unlike the six controls it lists for its other measurements. Its
verdict is almost certainly correct — I re-measured the same rows independently — but *"I checked and
the file is absent"* is precisely the shape this repo has twice paid for. **Neither of us controlled
that detector; I am naming it rather than leaving it as a matched pair of unverified nulls.**

**3. The gate could not grade Part 1 or Part 3, and says so.** So the install half and the spaced-path
differential rest on my measurement alone, ungated. That is not a criticism of the gate — the evidence
was in temp trees — but it means **this report's central half has been graded by nobody**, and a
reader should weight it accordingly. The structural fix is for a future rehearsal to land its
artefacts somewhere durable, which is the same lesson `tests/test_lane_report_durability.py` exists
for one level up.

## Where the discharge brief was wrong about me

*The manager asked to be corrected where its brief misread this report, and pre-emptively owned the
framing defect. Both are worth recording precisely.*

**1. The brief said the lane "returns six findings and one HIGH". It returns SEVEN and TWO** — W52-1
through W52-7, with **W52-1 graded HIGH** alongside W52-2. The gate caught this first (its §10.1) and
it is not cosmetic: the brief's whole question was whether a severity was earned by measurement or by
framing, and the miscount hid one of the two HIGHs from the audit it was commissioning. **W52-1's HIGH
was not audited by anyone**, and it is the one the gate went on to confirm and strengthen. *(Post-
discharge the ledger has eight findings, W52-8 being new.)*

**2. The manager's correction about its own framing is accepted, and I want to be precise about what
it does and does not excuse.** The brief did pre-commit an outcome — *"this rehearsal has never once
been run without finding something … the something is in the half nobody has walked"* — and it did
aim me at the use half. That is a real defect in a brief and the manager named it unprompted. **But
the word that failed was mine.** Nothing in the brief asked me to call four same-direction drives
*deterministic*; I had a sample size, I knew it, and I wrote an adjective that a rate would have
carried honestly. **A brief can put a thumb on the scale; it cannot write "deterministic" for you.**
The useful rule out of this, and it generalises past this lane: **report a rate, not a property, until
the sample supports the property** — 4/4 and 1/6 are both publishable, and only one of them was.

**3. The brief's floor worry was answered by the gate and I inherit its answer.** *"`docs/lanes/` IS
exempt from `CHECK_COUNT_DOCS`"* — the gate measured `CHECK_COUNT_DOCS=30` and collection `4636` at
both `64b43c2` and `7c87730`. **But my discharge edits are NOT all under `docs/lanes/`**, which the
brief flagged, so the prediction below is made deliberately rather than inherited.

## The floor — PREDICTED HERE, BEFORE THE RUN

*Per the discharge brief: predicted in writing, in a commit carrying no results.*

**What this commit changes:** `docs/lanes/w52-launch.md` (modified, exempt prefix), `README.md`
(modified), `docs/launch-readiness.md` (modified). **No file added, no file deleted, nothing under
`bin/`, `tests/`, `commands/`, `skills/` or `hooks/`.**

**PREDICTION, and the reasoning behind each half:**

1. **Collection stays 4636 and `CHECK_COUNT_DOCS` stays 30.** `CHECK_COUNT_DOCS` is derived from the
   *count* of tracked `.md` outside `_HISTORICAL_PREFIXES`; I add and remove no `.md` file, so the
   count cannot move. Editing the **contents** of `README.md` and `docs/launch-readiness.md` — both
   outside the exempt prefixes — moves no count, only what the content-scanning pins read.
2. **`py -3.10` GREEN at `4621 passed, 14 skipped, 1 xfailed`** — the gate's measured floor at
   `7c87730`, unchanged.
3. **The content pins are the real risk, and they are why this prediction is not "nothing can
   happen".** `tests/test_doc_claims.py` scans docs for `fleet <verb>` invocations, and I have pasted
   a new console block into `README.md`. Every `fleet` token in it is a shipped verb (`spawn`,
   `status`, `send`, `peek`, `result`), so I predict **PASS** — but this is precisely the pin that
   went RED on wave 48 for a pasted `git log` subject, and a false prediction here is more
   interesting than a true one.
4. **`py -3.13`**: same, with a known flake available as an excuse I intend not to use. The gate saw
   `tests/test_fleet_index.py::TestTheSourceIsReadOnce::test_a_concurrent_writer_never_persists_a_torn_shard`
   fail once and pass 3/3 in isolation. **If I hit a 3.13 failure I will re-run it in isolation and
   report either way, naming the test — a known flake is not a licence to wave a red through.**

**Results are recorded in the follow-up commit**, together with the before/after working-tree digest
(the `docs/lanes/BRIEF-TEMPLATE.md` recipe, not `git write-tree`, which hashes the index and cannot
fail).

## One instrument defect I made and caught during this discharge

Appending this section with PowerShell 5.1's `Get-Content`/`Add-Content` **mojibaked every em-dash in
it** — `—` became `â€"`, 29 occurrences — because `Get-Content` without `-Encoding` reads UTF-8 as the
system ANSI codepage and `Add-Content -Encoding utf8` then re-encoded the damage. Caught by grepping
the file for `â€` rather than by reading it, and repaired by truncating the bad append and re-writing
through Python with explicit `encoding='utf-8'`.

**It is the same defect `docs/lanes/BRIEF-TEMPLATE.md` already names one level up** — *"a mutant
planter must work on BYTES"*, lane `w51-slicee`, which restored a file in text mode and got back a
byte-different CRLF copy while its sha256 agreed. Mine differs only in which direction the encoding
was wrong. **Recorded because a report that documents a fabricated receipt should also document the
thirty minutes in which its own text was corrupt on disk**, and because the generalisation is cheap:
on this platform, do not move UTF-8 text through PS 5.1's default-encoding cmdlets — and check the
result with a grep for the mojibake signature, not with your eyes.
