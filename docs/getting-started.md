# Getting started

From zero to a running worker in a few minutes. If you haven't yet, skim **[How claude-fleet works](concepts.md)** first — it's five minutes and the rest of this makes more sense with the mental model in place.

---

## Requirements

Fleet runs today on:

- **Windows 10+** with **PowerShell** and **Git Bash** present, **or Linux**
- **Python 3.10+** — the floor is declared once as `fleet.MIN_PYTHON_VERSION` and the suite runs green at it. **But read the shim caveat below before you install.**
- **Claude Code CLI** `2.1.202+` — the floor `fleet doctor` enforces. The pin-tested version is whatever `state/pin-pass.json` last recorded; `fleet doctor` warns when your `claude` has moved past it. A fresh clone has no such file — `state/` is gitignored and only the `FLEET_LIVE=1` pin tier writes it — so until you run that tier, `doctor` reports `no pin-test pass recorded`, which is the expected state and not a fault.
- **The `claude` CLI on your PATH.** Fleet shells out to it for every dispatch; `fleet doctor`'s `claude-on-path` check reports the resolved binary and its version.

Zero third-party dependencies — `bin/fleet.py` is a single stdlib-only file.

> **The Python shim caveat.** The floor is 3.10, and the library honours it — but the two entry shims do not agree, and on Windows the mismatch is the one you meet first:
>
> | Entry point | Interpreter it selects |
> |---|---|
> | `bin\fleet.cmd` (Windows PATH shim) | `py -3.13`, hard-coded, **no fallback** |
> | `bin/fleet` (Git Bash / POSIX, and every hook via `bin/hooks/run_py.sh`) | first of `py -3.13`, `python3.13`…`python3.10`, honouring `$FLEET_PYTHON` |
>
> So on Windows, *through the documented `fleet.cmd` path*, fleet needs Python 3.13 specifically — a 3.10/3.11/3.12 box will fail at the shim even though the code supports it. Install 3.13, or drive `fleet` from Git Bash where the floor genuinely applies. This is a known gap, not a design choice.
>
> **The failure names neither fleet nor the shim,** so here it is to search for. On a box without 3.13, every `fleet` command dies as:
>
> ```console
> No suitable Python runtime found
> Pass --list (-0) to see all detected environments on your machine
> or set environment variable PYLAUNCHER_ALLOW_INSTALL to use winget
> or open the Microsoft Store to the requested version.
> ```
>
> That is the Windows `py` launcher refusing the `py -3.13` that `fleet.cmd` hard-codes (exit code 103). The library itself is fine at 3.10 — `py -3.10 bin\fleet.py --help` works.

> Windows is verified continuously by the suite on the reference box. Linux was verified by a full suite run during the POSIX-port campaign (2026-07-2x, on a real Linux host, not only WSL) — but **this repo has no CI**, so nothing re-verifies Linux on every change; treat it as "verified once, at a much smaller suite." macOS runs the same POSIX backend as Linux but has no receipt at all — untested, not unsupported. Remaining platform gaps are enumerated at the top of [`SPEC.md`](SPEC.md).

## Install

```powershell
# 1. Clone, and put the clone's bin\ on your PATH (it holds fleet.cmd)
git clone https://github.com/exPardus/fleet.git
cd fleet
$env:PATH = "$PWD\bin;$env:PATH"          # this session only

# 2. Check which fleet you just put in charge, THEN render the hook wiring
fleet home                                 # must print the clone you are standing in
#    (fills in this machine's Python path + FLEET_HOME; nothing machine-specific is committed)
fleet init

# 3. Install the plugin — manager skill + /fleet:* slash commands
#    (no hooks: installing fleet does not change how any other session starts)
claude plugin marketplace add C:\path\to\this\clone    # a DIRECTORY path, not a URL
claude plugin install fleet@claude-fleet
#    restart Claude Code, then verify:
claude plugin details fleet

# 4. (Optional) install the always-on statusline
#    (a plugin can't ship one, so it installs separately; it refuses to clobber a foreign one)
#    This writes ~\.claude\settings.json — your machine-wide Claude Code config, not a repo file.
fleet init --statusline
```

> **Step 1's PATH line is a command, not a comment — and step 2 depends on it.** Without it, `fleet
> init` fails with `The term 'fleet' is not recognized ... CommandNotFoundException`. The line above
> lasts for the current shell only; to make it permanent, add the clone's `bin\` to your user PATH
> the way you normally would. `setx` is the scriptable form, and it edits your machine-wide user
> environment — a change outside this repo, worth making deliberately rather than by paste.

> **Step 2's `fleet home` is the step that stops the worst mistake.** `fleet` resolves its home from
> the location of the `fleet.py` behind whichever shim PATH found — *not* from your current
> directory. So if a different fleet clone is already on your PATH, standing inside your new clone
> and typing `fleet init` configures the **other** home and leaves your new one untouched. That has
> happened here and cost a real incident. `fleet home` is read-only, takes no lock, and prints the
> home every following command will act on. If the answer is not the clone you just made, fix PATH
> first.

> **Step 3's argument is a directory path to your clone** (that is the source form a working install
> reports: `claude plugin marketplace list` → `Source: Directory (...)`). Whether the
> `owner/repo` GitHub shorthand also works is untested.

**Where does it install to?** Nowhere you have to choose. Fleet derives `FLEET_HOME` from `bin/fleet.py`'s own location, so the clone can live anywhere — there is no hard-coded path in the CLI. `fleet home` prints the resolved value:

```console
$ fleet home
C:/proga/claude-fleet
```

**Overriding it — and the one case where the environment variable loses.** Home resolution runs in
priority order (`docs/specs/multi-fleet.md` §5):

| Priority | Input | Wins when |
|---|---|---|
| 1 | `--fleet-home <PATH>` — a global flag, accepted in any position | always, if given |
| 2 | this session's id, looked up against the registries the install root can see | the session id is claimed by one of them |
| 3 | the `FLEET_HOME` environment variable | nothing above matched |

For an ordinary user, priority 2 never fires and `FLEET_HOME` behaves exactly as you would expect.
**Inside a Claude Code session that fleet itself launched, it does not:** that session's id is
claimed by the registry that launched it, so priority 2 answers first and `FLEET_HOME` is silently
ignored. If you are scripting against a specific home — and especially if you are testing a second
clone from inside a fleet-managed session — use `--fleet-home <PATH>`, which outranks both. Note
that `--fleet-home` requires an *initialized* home, meaning one whose `state/fleet.json` exists;
`fleet init` writes `worker-settings.json` and does **not** create the registry, which appears on
the first spawn. A freshly `init`-ed home will therefore be rejected as `not_initialized` until a
worker has been spawned into it.

Step 2 writes exactly one file, and tells you where:

```console
$ fleet init
fleet init: wrote C:\proga\claude-fleet\state\worker-settings.json
  python:      C:/Users/you/AppData/Local/Programs/Python/Python313/python.exe
  fleet home:  C:/proga/claude-fleet
```

Confirm the wiring is healthy any time:

```powershell
fleet doctor
```

`fleet doctor` runs 28 checks — hook registration, version pins, orphaned mailboxes, stale attaches, how long since the last autoclean run, the supervisor claim, and more. It prints one `[PASS]`/`[FAIL]` row per check and exits nonzero if any failed. It is **report-only**: `--repair` is the only flag that mutates anything, and all it does is rename a corrupt `state/fleet.json` aside.

> **Run `fleet init` before `fleet doctor`, not after.** On a home where `init` has not run, four checks fail by design — `worker-settings-instance`, `instance-freshness`, `instance-grants` and `hook-registration` all report that `worker-settings.json` is missing and tell you to run `fleet init`. That is doctor working, not fleet being broken. After `init`, the same run goes to 28 PASS / 0 FAIL.

## Become the manager

Open a Claude Code session and say:

> **become the fleet manager**

That triggers the manager skill: the session reads `knowledge/INDEX.md` and the current fleet state, and from then on drives workers on your behalf.

> **If nothing happens, the skill didn't match.** Skill activation is semantic, and that exact phrase is *not* one of the triggers `skills/fleet/SKILL.md` declares — its description lists `fleet`, `spawn workers`, `manage sessions`, `dispatch task to <project>`, `check on workers`, `boot a supervisor`. Any of those is a surer trigger, and **`/fleet:overview` is the deterministic one** — it's a slash command, so it cannot fail to match.

You can also run the `fleet` CLI directly in a shell — the manager session and the CLI operate on the exact same files. Nothing is pushed at you either way: fleet injects nothing into a session, so fleet state shows up only when you ask for it.

## Spawn your first worker

One task, one worker. That's the doctrine — small, well-scoped tasks, not marathons.

```powershell
fleet spawn hello --dir C:\path\to\some\project `
  --task "List the top-level modules and write a one-paragraph summary to NOTES.md"
```

Watch it:

```powershell
fleet status              # the table (columns below)
fleet peek hello          # ~20-line digest of the current/last turn (works mid-turn)
fleet wait hello          # block until the turn ends
fleet result hello        # just the final result text
```

`fleet status` prints one row per worker under these columns — `MIN-AGO` is minutes since the last activity, `MAIL` is undelivered messages, `ATTACH` is who holds it interactively:

```console
$ fleet status
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
hello               working        1     0.00        2     0        -  -
```

Add `--json` for the machine-readable snapshot (it carries each worker's `session_id`), `--all` to include archived tombstones, and `--stale-ok` for the read-only fast path that takes no lock and probes nothing.

### Permission modes

Each worker runs at a trust level you pick at spawn with `--mode`:

| `--mode` | Behavior |
|---|---|
| `dontask` | Middle ground — the default. |
| `accept` | Auto-accept edits. |
| `plan` | Plan mode; proposes, doesn't execute. |
| `bypass` | `--dangerously-skip-permissions` — full autonomy. Use when you trust the task. |
| `omit` | Pass no permission flag; inherit whatever the session default is. |

```powershell
fleet spawn migrate --dir C:\proga\billing --mode bypass `
  --task "@C:\proga\billing\TASK.md" --token-ceiling 200000
```

`--task` accepts inline text or `@file` to read a task file. `--token-ceiling` caps total tokens — a worker that would exceed it refuses the next turn rather than burning through your budget unwatched.

## Steer, mid-flight

You don't have to wait for a worker to finish to change its course:

```powershell
fleet send migrate "also add a down-migration, I forgot to ask"
```

- If the worker is **working**, the message lands in its mailbox and is injected at the next tool boundary — no attach needed.
- If it's **idle**, the same command resumes it on a fresh turn with your message as the input.

Need the full interactive experience? A worker is a real Claude Code session, so you attach to it **through Claude Code**, not through fleet:

```powershell
# Ctrl+T in claude opens the agents menu, or address the session directly:
claude attach <session-id>        # fleet status --json shows the session_id

fleet release migrate             # flip a stale `attached` record back to idle
```

> `fleet attach` currently **refuses and redirects** to the above — a `--bg` worker has no fleet-owned terminal to spawn. Native attach integration is a later milestone (`SPEC.md` §7).

## Reset context without losing the work

Long campaigns fill a worker's context. Respawn gives it a **fresh session** — same name, cwd, and mode — while carrying its **journal** and any drained mailbox forward:

```powershell
fleet respawn migrate                    # fresh context, work history preserved
fleet respawn migrate --task "@NEW.md"   # …and re-scope the task
```

## When a worker hits a usage limit

It parks itself as `limited` with the reset time recorded — it does not die silently. Once the window passes:

```powershell
fleet resume-limited            # resume every parked worker whose reset horizon has passed
fleet resume-limited migrate    # …or just one
```

## Clean up

```powershell
fleet kill hello                # stop the turn (if running) and mark it dead
fleet clean --dead-only         # remove dead workers + their outcomes/mailboxes/journals
fleet clean                     # broader sweep (see fleet clean --help for tiers)
```

`fleet archive` and `fleet autoclean` are what keep staleness down. **There is nothing to install and no scheduler** — the timer was retired on 2026-07-27, because a timer sweeps when the clock says so, which on a machine that loses power means it does not sweep at all. Instead the sweep rides on the tiers: a supervisor runs it on its watchtower beat, and the `fleet` skill's startup ritual runs it when a manager session begins. If you are running neither, run `fleet autoclean` yourself now and then — `fleet doctor` tells you how long it has been since the last run.

## A first real campaign: parallel workers

The point of fleet is *many* workers. Fan out independent tasks, then collect:

```powershell
fleet spawn lint-api    --dir C:\proga\api      --mode accept --task "@tasks\lint.md"
fleet spawn lint-web    --dir C:\proga\web      --mode accept --task "@tasks\lint.md"
fleet spawn lint-worker --dir C:\proga\jobs     --mode accept --task "@tasks\lint.md"

fleet wait lint-api lint-web lint-worker --all    # block until all three finish
fleet status                                       # review outcomes
fleet result lint-api                              # read each result
```

For dependent or review-style work (one worker builds, another attacks the diff), let the manager session orchestrate — it's what the manager skill and the `knowledge/playbooks/` doctrine are for. See [`../knowledge/playbooks/`](../knowledge/playbooks/) for the campaign template and spawn etiquette.

## The full command surface

| Command | Purpose |
|---|---|
| `fleet init` | Render machine-local `worker-settings.json` (add `--statusline`) |
| `fleet spawn` | Spawn a new worker session |
| `fleet status` | Worker status table |
| `fleet peek` | Digest of the last few substantive transcript records (works mid-turn) |
| `fleet result` | Final result text of the last completed turn |
| `fleet wait` | Block until turn(s) end |
| `fleet send` | Steer a worker (mailbox mid-turn, or a new turn if idle) |
| `fleet interrupt` | Stop a worker's running turn |
| `fleet attach` / `release` | `attach` refuses and points at `claude attach` / the agents menu; `release` returns a stale `attached` record to idle |
| `fleet respawn` | Fresh session, journal carried forward |
| `fleet resume-limited` | Relaunch usage-limit-parked workers past their reset |
| `fleet kill` | Interrupt (if running) and mark dead |
| `fleet clean` / `archive` / `autoclean` | Tiered cleanup and staleness sweeps |
| `fleet doctor` | Run the 28 health checks (`--repair` quarantines a corrupt registry) |
| `fleet home` | Print the resolved `FLEET_HOME` |
| `fleet homes` | List the machine's registered fleet homes. The bare verb is read-only; `--add` / `--retire` mutate the machine-wide homes list |
| `fleet knowledge` | Print `knowledge/INDEX.md` |
| `fleet index` / `fleet q` | Opt-in per-project symbol index (`index init/build/update/status`) and the query verb over it |
| `fleet sup-*` | Supervisor identity: `sup-boot`, `sup-spawn`, `sup-checkpoint`, `sup-heartbeat`, `sup-release`, `sup-status`, `sup-context`, `sup-decision`, `sup-handoff-{begin,complete,abort}` |

That is all 33 subcommands `fleet --help` ships, as of `fa236cb`. Every command's exact contract lives in [`SPEC.md`](SPEC.md) §7 — and if this table and `fleet --help` ever disagree, `--help` wins and this table has drifted. To check for yourself, read the `{...}` choice list at the top of `fleet --help`; that is the authority, and it drifted from this table once already (`homes` shipped and went unlisted here for a wave).

---

## Next

- **[How claude-fleet works](concepts.md)** — the architecture and design bets, with diagrams.
- **[SPEC.md](SPEC.md)** — the binding architecture of record.
- **[Docs index](README.md)** — every doc, tagged by audience.
