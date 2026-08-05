# Launch readiness — what stops an external user today

**Status:** measured 2026-08-05 against `f457a57` (branch `w42/launch-docs`). Every row below was
derived by executing something on this machine, not by reading prose. Where a claim could not be
executed here, it says so and says why.

This document exists because the operator's directive is *launch readiness*, not a nicer README.
The README/`getting-started` corrections that shipped alongside it fix what the docs **said**; this
is the list of what the repo **is**. Ordered by what blocks a first successful use — not by how hard
each is to fix.

---

## The blockers, in order

### 1. On Windows, the CLI needs Python 3.13 — but every doc says the floor is 3.10

The library floor is real: `fleet.MIN_PYTHON_VERSION == (3, 10)`, and `py -3.10 bin/fleet.py --help`
works. The problem is the shim the quickstart puts on your PATH.

| Entry point | Interpreter selection |
|---|---|
| `bin\fleet.cmd` | `py -3.13 "%~dp0fleet.py" %*` — hard-coded, **no fallback, no `$FLEET_PYTHON`** |
| `bin/fleet` → `bin/hooks/run_py.sh` | `py -3.13`, then `python3.13`…`python3.10`, then `python3`/`python`, each version-gated at ≥ 3.10; honours `$FLEET_PYTHON` |

A Windows user on 3.10/3.11/3.12 follows the documented install, puts `bin\` on PATH, types
`fleet init`, and the launcher fails before Python starts. Nothing in the failure names the cause.

This is the **only** gap on this list that stops an otherwise-correct install dead, which is why it
is first. `run_py.sh` already contains the fallback logic and even documents *why* hardcoding
`py -3.13` is wrong ("breaks every non-Windows collaborator") — the `.cmd` shim just never got it.

**Fix:** give `fleet.cmd` the same descending probe, or have it delegate to `run_py.sh`. Not done in
this lane: `bin/**` was fenced.

### 2. Two documented entry steps cannot be executed as written

#### 2a. The plugin install step is a placeholder

Both the README and `getting-started` say:

```
claude plugin marketplace add <path-or-github-repo-of-this-clone>
```

`<path-or-github-repo-of-this-clone>` is never resolved to a literal. The manifests are correct —
`.claude-plugin/marketplace.json` declares marketplace `claude-fleet` containing plugin `fleet`, so
the following `claude plugin install fleet@claude-fleet` is right — but the reader has to guess the
argument that produces that marketplace.

**Unverified here:** resolving it means running `claude plugin marketplace add`, which mutates this
machine's real plugin configuration. Not run. The two candidate literals are the clone path and the
`exPardus/fleet` GitHub shorthand; **someone with a throwaway machine must confirm which, and paste
the working line.** Until then this is a step the user cannot copy.

#### 2b. The phrase both docs tell you to say is not a declared trigger

README and `getting-started` both instruct the reader to say **"become the fleet manager"**. The
skill's own frontmatter declares these triggers:

> `fleet`, `spawn workers`, `manage sessions`, `dispatch task to <project>`, `check on workers`,
> `boot a supervisor`, parallel work across projects, long-running babysat jobs, review pipelines

"become the fleet manager" is not among them. Skill activation is semantic, so the phrase may well
match anyway — **this is unverified either way, and not verifiable deterministically from here**,
which is exactly why it should not be the only instruction given. Both docs now also point at
`/fleet:overview`, a slash command, which cannot fail to match.

The vocabulary has also moved underneath the phrase: the skill describes itself as making the
session the fleet's **interface tier** (`docs/specs/three-tier-command.md`, ratified 2026-07-23),
while the user-facing docs still say *manager*. Not wrong — `SKILL.md`'s own heading is still
"Fleet manager" — but worth aligning before launch.

### 3. `fleet knowledge` sends you to a command that cannot fix it

Executed, on a scratch `FLEET_HOME`, immediately after a successful `fleet init`:

```console
$ fleet init
fleet init: wrote <FLEET_HOME>\state\worker-settings.json
$ fleet knowledge
(no knowledge index at <FLEET_HOME>\knowledge\INDEX.md -- run `fleet init`)
```

`fleet init` had just run, exit 0. It does not create `knowledge/`, and `knowledge_dir()` resolves
under `FLEET_HOME` — so any user who points `FLEET_HOME` somewhere other than the clone gets a hint
that loops. Harmless to state, but it is the first thing that tells a new user the tool is lying to
them.

### 4. `--max-budget-usd` is advertised by `--help` and always refused

```console
$ fleet spawn probe --dir . --task "noop" --max-budget-usd 5
fleet: no USD budget under native dispatch (contract G3) -- use --token-ceiling
```

The flag is registered on both `spawn` and `respawn`, appears in `--help`, and is rejected
unconditionally at dispatch. A flag that `--help` offers and the code always refuses is a trap: the
user's reasonable reading of `--help` is wrong every time. Either drop it from the parser or make
the help text say it is inert. (`--token-ceiling` is the working control and does what the docs
promise.)

### 5. There is no CI, so the platform claims can rot silently

`.github/` contains only `ISSUE_TEMPLATE/`. No workflow, anywhere.

Consequences for a launch:

- The README badge and the platform sentence claim Linux support. The receipt is real but
  **historical**: the POSIX-port campaign ran the full suite green on both platforms at ~1376 tests
  (`knowledge/lessons.md`, 2026-07-2x). The suite is now **3662** collected. Nothing has re-verified
  Linux since, and nothing will.
- macOS has no receipt at all.
- Every green number in this repo is "green on the maintainer's Windows box, in whichever shell they
  used." `lessons.md` records that Windows PowerShell skips 5 `sh`-gated tests that Git Bash runs —
  **the same suite reports different skip counts per shell**, so even the local number is
  shell-dependent and must be quoted with its shell.

### 6. The Claude Code pin is two releases behind the installed CLI

```console
$ cat state/pin-pass.json
{"claude_version": "2.1.220", "passed_at": "2026-07-26T17:03:45Z"}
$ claude --version
2.1.222 (Claude Code)
```

`fleet doctor`'s `pin-version` check exists precisely to surface this, and the vendor daemon is
explicitly treated as a moving target. Not a blocker for first use — but the end-to-end dispatch
path's last live receipt is 10 days and 2 vendor releases old, and that is the receipt a launch
leans on.

### 7. One fleet home per machine

`docs/specs/multi-fleet.md` (v8) is **ratified ready-for-build and unbuilt**; slice 0 is the
install/home split. Today `FLEET_HOME` defaults to the clone root and the env var overrides it, so a
user *can* point fleet at a different home — but there is one home at a time, and `INSTALL_ROOT` is
deliberately not overridable.

What this means for a user with two projects: **nothing bad.** Workers are dispatched with `--dir`,
so one home already manages workers across many projects — that is the normal case, not a
workaround. What you cannot do is run two independent fleets side by side. For launch, that is a
limitation to state, not a blocker.

### 8. `SPEC.md` §18 is stale by two milestones

M-0/M-A/M-B/M-C are recorded; **M-D and M-E shipped afterwards and were never folded in.** Anyone
reading §18 as "what works" gets a two-milestone-old picture; `docs/PLAN-PROGRESS.md` and
`docs/NEXT-SESSION.md` hold the rest. Contributor-facing, not user-facing — hence low. Flagged, not
edited: `SPEC.md` was fenced for this lane.

---

## What is genuinely ready

Worth stating, because a gap list read alone is misleading:

- **The clone is portable.** `bin/fleet.py` contains **no** hard-coded install path — four
  `C:`-shaped hits, all inside comments and docstrings. `FLEET_HOME` derives from the file's own
  location and `bin/fleet.cmd` uses `%~dp0`. The repo can be cloned anywhere.
- **`fleet init` is honest and narrow.** It wrote exactly one file
  (`<FLEET_HOME>/state/worker-settings.json`), printed both values it substituted, and left the
  machine's real `~/.claude/settings.json` byte-identical (md5 checked before and after).
- **`fleet doctor` earns its place.** 28 checks; on a fresh home it fails 4 with the exact remedy
  named, and goes to **28 PASS / 0 FAIL** after `fleet init`. It is report-only by default.
- **The plugin really does inject nothing.** `.claude-plugin/plugin.json` declares no `hooks` key.
- **The public clone URL resolves** — `git ls-remote https://github.com/exPardus/fleet` succeeds
  anonymously.

---

## What this document did not verify

- **An end-to-end `fleet spawn` → `fleet result` on a live worker.** Not executed. Dispatching a
  real `claude --bg` session spends real money and adds a session to the machine-wide daemon; this
  repo gates exactly that behind `FLEET_LIVE=1` for the same reason, and no spend was authorised for
  this lane. The existing receipt for that path is `state/pin-pass.json` (2.1.220, 2026-07-26) plus
  `tests/integration/test_native_pin.py`. **The install walkthrough is therefore verified from
  `git clone` through `fleet doctor` 28/28, and unverified from `fleet spawn` onward.**
- **`claude plugin marketplace add` / `plugin install` / `plugin details`.** Mutates this machine's
  real plugin config. Not run. See gap 2.
- **`fleet init --statusline`.** Writes `~/.claude/settings.json`. Not run — this machine has a live
  statusline that the flag would either refuse to clobber or replace, and neither outcome is worth
  producing on the operator's real box. The refuse-a-foreign-statusline behaviour is asserted by the
  existing suite, not by this lane.
- **Any behaviour on Linux or macOS.** This is a Windows box. Every "runs on Linux" statement here
  is relayed from the repo's own receipts, not re-measured.
- **A genuinely fresh machine.** Nothing here proves the absence of an undeclared dependency that
  this box happens to satisfy — the strongest remaining launch risk, and the one only a clean VM
  closes.
