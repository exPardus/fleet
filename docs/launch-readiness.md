# Launch readiness — what stops an external user today

**Status:** measured 2026-08-05 against `f457a57` (branch `w42/launch-docs`). Every row below was
derived by executing something on this machine, not by reading prose. Where a claim could not be
executed here, it says so and says why.

**Re-measured 2026-08-09 against `fa236cb`** by an install rehearsal run from a throwaway clone
under the OS temp dir (`docs/lanes/w48-launch.md`), and re-checked the same day under an adversarial
gate. Below is the disposition of **every** entry on this list — nine of them, because gap 2 splits
into 2a and 2b:

| Entry | Disposition on 2026-08-09 |
|---|---|
| 1, 3, 4, 6, 7 | Re-measured; each reproduced unchanged. |
| 2a | Re-measured; the open question is answered below — the argument is a directory path. |
| 2b | Re-measured and stands. Its substance was acted on — all three entry docs now carry the trigger caveat and point at `/fleet:overview` — but the phrase is still not a declared trigger, and whether it matches anyway is still not deterministically verifiable from here. |
| 5 | Re-measured and stands: `.github/` still contains only `ISSUE_TEMPLATE/` (`bug_report.md`, `feature_request.md`) and **zero** workflow files. |
| 8 | Re-measured and **withdrawn — it was false when written.** See the struck section below. |

That rehearsal also found **three blockers this list did not have**, all of them ahead of most of
what is below:

- **A bare `fleet init` configures whatever fleet is already on your PATH, not the clone you are
  standing in.** Measured: from a fresh clone in temp, `fleet home` printed `C:/proga/claude-fleet`.
  This is the 2026-07-29 incident class, reachable by following the published quickstart exactly.
- **The quickstart's PATH step is a comment, not a command**, so on a machine with no prior fleet
  the walkthrough dies at step 2 with `CommandNotFoundException`.
- **`FLEET_HOME` is silently ignored inside a fleet-launched session** — the session-id lookup
  (multi-fleet §5 step 2) outranks it, and `--fleet-home`, the flag that does win, appears in no
  user-facing doc.

All three are prose defects, now fixed in `README.md` and `docs/getting-started.md`.

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

**Answered 2026-08-09 — the argument is a directory path to the clone.** Read off the machine's real
configuration without mutating it:

```console
$ claude plugin marketplace list
Configured marketplaces:
  ❯ claude-fleet                              # 1 of 5 entries; the other 4 are below
    Source: Directory (C:\proga\claude-fleet)
```

That is the source form of a marketplace that demonstrably works, and it agrees with
`.claude-plugin/marketplace.json`, which declares plugin `fleet` at `"source": "./"`. Both docs now
give the directory form.

**Still unverified, stated precisely:** whether `exPardus/fleet` in particular resolves as a
marketplace. That is *not* a question about the argument form, and an earlier revision of this
paragraph wrongly said there was "no evidence either way" about GitHub shorthand — a claim the
abridged block above helped hide, since the four rows it drops are the refutation. The evidence
exists, from the command's own help and from this machine's own configuration:

```console
$ claude plugin marketplace add --help
Usage: claude plugin marketplace add [options] <source>

Add a marketplace from a URL, path, or GitHub repo

$ claude plugin marketplace list | grep -c 'Source: GitHub'
4                     # of 5 configured marketplaces; the 5th is claude-fleet, Directory-sourced
```

So the CLI plainly accepts URL and GitHub-repo sources, and four marketplaces on this box are
installed that way. What no one here has run is `claude plugin marketplace add` itself — in any
form — because it mutates this machine's real plugin configuration. The grade of the directory
answer is therefore *observed source of a working install*, not *command re-executed on a clean
box*.

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

**Re-measured 2026-08-09, with the remedy actually run** — the loop is closed, not merely suspected.
On a scratch home, `fleet knowledge` → the message above → `fleet init` (exit 0, wrote
`state\worker-settings.json`) → `fleet knowledge` again → **byte-identical message**. Two details
this section did not record: `fleet knowledge` **exits 0** on a missing index, so a script that
checks the return code sees success; and nothing in the message tells the reader that `knowledge/`
is git-tracked *in the clone*, which is the fact that makes the loop escapable. The message is the
part worth fixing — the exit code may have callers.

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

### 6. The native-contract pin is a local artefact that a fresh clone does not have

`state/` is gitignored (`git check-ignore -v state/pin-pass.json` names the rule), so **a clone of
this repo carries no `state/pin-pass.json` at all** — while `README.md`, `docs/getting-started.md`
and `CONTRIBUTING.md` all send the reader to that file for the pin-tested `claude` version. What a
fresh clone actually gets, measured against an empty `FLEET_HOME`:

```console
$ fleet doctor          # every other row elided; this is the one about the pin
[PASS] pin-version: no pin-test pass recorded -- run FLEET_LIVE=1 python -m pytest tests/integration/test_native_pin.py
```

Nothing in `bin/fleet.py` writes that file — `record_pin_pass()` has no caller in the CLI. Its only
real writer is `tests/integration/test_native_pin.py`, which `conftest.py` skips unless
`FLEET_LIVE=1` and which spends real money on two live `haiku` workers. So the pin is re-established
only when a human deliberately pays for it, there is no CI to do it for them (gap 5), and the vendor
CLI ships on its own schedule.

**Stated so that it cannot expire:** the distance between the pinned version and the installed one
is unbounded by construction and unobserved by default. `fleet doctor`'s `pin-version` row is the
only thing that reports it, and an absent pin is deliberately a PASS-note rather than a FAIL,
because "not re-verified" is not "broken". Read that row. **Do not paste the current version into
this document** — an earlier revision of this section did exactly that, and the constant was false
nineteen minutes after the commit that introduced it.

### 7. One fleet home per machine

`docs/specs/multi-fleet.md` (v8) is **ratified ready-for-build and unbuilt**; slice 0 is the
install/home split. Today `FLEET_HOME` defaults to the clone root and the env var overrides it, so a
user *can* point fleet at a different home — but there is one home at a time, and `INSTALL_ROOT` is
deliberately not overridable.

What this means for a user with two projects: **nothing bad.** Workers are dispatched with `--dir`,
so one home already manages workers across many projects — that is the normal case, not a
workaround. What you cannot do is run two independent fleets side by side. For launch, that is a
limitation to state, not a blocker.

### 8. ~~`SPEC.md` §18 is stale by two milestones~~ — WITHDRAWN 2026-08-09: it was false when written

This entry claimed *"M-0/M-A/M-B/M-C are recorded; **M-D and M-E shipped afterwards and were never
folded in**"*. Re-measured 2026-08-09 against the tree this document sits in — **false.** §18 records
M-D and M-E as SHIPPED, with dates, alongside M-F and M-G:

```console
$ grep -n '^## 18\.' docs/SPEC.md
355:## 18. Milestones

$ sed -n '355,370p' docs/SPEC.md | grep -oE '^- \*\*M-[A-G0] [^:]+:'
- **M-0 — spike + contract:
- **M-A — supervisor identity:
- **M-B — native dispatch:
- **M-C — deletions + hardening + SPEC v3:
- **M-D — vendor contract rehome + UL horizon parser:
- **M-E — daemon-wedge detection + shipped-code defects + claim-nonce spec:
- **M-F — SDD / drift-control:
- **M-G — audit oracle:
```

They were folded in on **2026-07-22**, fourteen days *before* this entry was written on 2026-08-05
(`0cefc81`):

```console
$ git log --format='%h %ad' --date=short -S'**M-D — vendor contract rehome' -- docs/SPEC.md
36a4c53 2026-07-22
```

(`36a4c53` is the commit that removed the plugin's SessionStart hook. The subject is dropped from
the format above on purpose: `tests/test_doc_claims.py` scans shell-fenced blocks in this file for
`fleet <verb>` invocations, and that subject line contains a word pair it reads as one.)

(Line numbers in the `sed` range are as of `4ccc8f7`; `grep -n` above prints the one they are
anchored on.)

**Why it was wrong is the part worth keeping.** The sentence was never measured against `SPEC.md`.
It was relayed from root `CLAUDE.md`, whose opening paragraph still reads *"M-D and M-E shipped
after and are **not yet folded into §18**"* — a line stale since `36a4c53`. This document opens by
promising that *"Every row below was derived by executing something on this machine, not by reading
prose."* This row was the exception, and it is the only entry here that a hostile re-run has removed
rather than confirmed. **The stale text that remains is root `CLAUDE.md`, not `SPEC.md`** — outside
this lane's fence, flagged for whoever owns it.

What §18 *is* missing is narrower and not a milestone gap: the "Reconcile", three-tier/claim-nonce
and supervisor-tombstone entries are present but unlettered, so §18 is a milestone list with
non-milestone rows in it. Cosmetic, contributor-facing, and not a launch blocker.

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
  this lane. The existing receipt for that path is whatever `state/pin-pass.json` records on the
  machine that last ran the live tier — a fresh clone has none, see gap 6 — plus
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
