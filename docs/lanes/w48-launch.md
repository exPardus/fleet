# w48 lane — launch-readiness rehearsal: installing claude-fleet as a stranger

**Lane:** `w48/launch-rehearsal`, worktree `C:/proga/fleet-w48-launch`, branch cut at `fa236cb`.
**Method:** follow `README.md` and `docs/getting-started.md` literally, from a throwaway clone under
the OS temp dir, and record what happens. Every line below is tagged **MEASURED** (I ran it on
2026-08-09 and the output is pasted or quoted) or **BELIEVED** (I did not run it — reasoning, code
reading, or relayed claim).

---

## 0. What I ran under, and the safety fence

MEASURED — the rehearsal environment:

| Thing | Value |
|---|---|
| Rehearsal clone | `C:\Users\Techn\AppData\Local\Temp\w48-rehearsal\fleet` @ `fa236cb` |
| Second (timing) clone | `C:\Users\Techn\AppData\Local\Temp\w48-rehearsal\timed\fleet` @ `fa236cb` |
| Alt scratch home | `C:\Users\Techn\AppData\Local\Temp\w48-althome` (not a clone) |
| `FLEET_HOME` echoed back | `C:/Users/Techn/AppData/Local/Temp/w48-rehearsal/fleet` for the walkthrough; `C:/Users/Techn/AppData/Local/Temp/w48-althome` for the gap-3 probe. **Never the live home.** |
| Interpreters present | `py -0` → 3.14 (default `*`), 3.13, 3.11, 3.10, 3.9. Bare `python` → 3.10.1 |
| `claude` | 2.1.226 at `C:\Users\Techn\.local\bin\claude.EXE` |
| `git` | 2.34.1.windows.1 |

MEASURED — the public HEAD and my branch base are the same tree, so the stranger's clone *is* the
tree this report is about:

```console
$ git ls-remote https://github.com/exPardus/fleet
fa236cbf7925b9bf080bba57ad9473cf9eee8f14	HEAD
```

MEASURED — fence compliance, verified rather than asserted:

- `~/.claude/settings.json` — `mtime=2026-08-08T22:34:02`, `md5=9958041A6AB22CC125FE70968E142FDB`,
  checked at `2026-08-09T04:33:55`, i.e. ~6h older than my first `fleet init`. Never written.
  **`fleet init --statusline` was never run.**
- `~/.claude/fleet-homes.list` — **ABSENT** before and after. Never created, never appended.
- `C:/proga/claude-fleet/state` — file-set + size + mtime snapshot compared before and after every
  step that could have touched it. Reported `UNCHANGED` each time.
- `claude plugin marketplace add` / `plugin install` — **not run** (see §5).
- No worker was spawned anywhere. The one `fleet spawn` I typed is refused before dispatch (§7); the
  rehearsal home's `state/fleet.json` is still absent, which is the receipt that nothing launched.

MEASURED — the mutation detector was positive-controlled before I trusted a "nothing changed"
verdict, because "no change" is a null shaped like an answer:

```console
POSITIVE CONTROL: probe before=DB55DF63E1239FF751811829B718E04D after=F6F678F689ABE9876651ABAE991D5AFD detected_change=True
```

---

## 1. THE HEADLINE: the documented step 2 configures whatever fleet is already on your PATH

**Class (b) — the doc omits a required step. Severity: highest thing in this report.**

MEASURED. The rehearsal clone is in temp. I `cd`-ed into it and asked, read-only, which home the
documented next command would act on:

```console
# cwd = C:\Users\Techn\AppData\Local\Temp\w48-rehearsal\fleet   (the fresh clone)
# PATH untouched — exactly what a user with any prior fleet has
$ fleet home
C:/proga/claude-fleet
rc=0
```

`Get-Command fleet -All` resolves to `C:\proga\claude-fleet\bin\fleet.cmd` — the **live** fleet, and
its PATH entry is present **twice**. Standing inside a brand-new clone, the very next line the
quickstart tells you to type — `fleet init` — would have written into the live fleet's home. That is
the incident recorded at the top of `docs/specs/multi-fleet.md` (2026-07-29), reachable by following
the published instructions exactly, and **neither README nor `getting-started` contains a word about
it.** I did not run it; `fleet home` is in `TERMINUS_VIEW_VERBS` and `cmd_home` is a one-line
`print`, so the probe is safe and the live `state/` snapshot confirmed no write.

BELIEVED — the population this bites: anyone re-cloning, anyone trying a second copy, anyone
upgrading by cloning fresh beside an old checkout, and every contributor. A stranger with no prior
fleet is not affected by *this*; they are affected by §2 instead.

**Doc fix applied:** both install blocks now check `fleet home` before `fleet init`, and say what a
surprising answer means. This describes what the code does today; no code change is implied.

---

## 2. The walkthrough is not copy-pasteable: step 1's PATH instruction is a comment

**Class (b). MEASURED.**

Both entry docs give step 1 as a code block whose PATH line is a comment:

```powershell
git clone https://github.com/exPardus/fleet.git
cd fleet
#    add <repo>\bin to PATH
```

Nothing in that block modifies PATH. On a machine with no prior fleet — the actual stranger case —
the next documented command fails:

```console
$ fleet init
fleet : The term 'fleet' is not recognized as the name of a cmdlet, function, script file, or operable program.
    + CategoryInfo          : ObjectNotFound: (fleet:String) [], CommandNotFoundException
```

MEASURED by stripping every `claude-fleet` entry from `PATH` first
(`fleet-bin entries left on PATH: 0`) so this is the fresh-machine behaviour, not a typo.

The doc never says *which* PATH — session or persistent — and the persistent Windows form (`setx`)
is a machine-global write, which a reader deserves to be told before they run it.

**Doc fix applied:** both blocks now carry the literal session-scoped command and name the
persistent alternative as a separate, explicitly machine-global choice.

---

## 3. `FLEET_HOME` does not always override — and the override that does is undocumented

**Class (a) — the doc says something false (conditionally). MEASURED, and this one corrected my own
safety procedure mid-lane.**

`docs/getting-started.md` says, unconditionally: *"Set the `FLEET_HOME` environment variable to
override it."* Measured four ways (`fleet home`, read-only, live `state/` unchanged throughout):

| # | Shim invoked | `FLEET_HOME` | Resolved home |
|---|---|---|---|
| A | live `bin\fleet.cmd` | unset | `C:/proga/claude-fleet` |
| B | live `bin\fleet.cmd` | temp clone | **`C:/proga/claude-fleet`** ← env ignored |
| C | temp `bin\fleet.cmd` | live path | `C:/proga/claude-fleet` |
| D | temp `bin\fleet.cmd` | temp clone | `C:/Users/.../w48-rehearsal/fleet` |

Row B is the anomaly. Discriminating experiment, MEASURED:

```console
CLAUDE_CODE_SESSION_ID=[16590cb0-d140-4fa1-9b56-53c750e274cc]
=== LIVE shim, FLEET_HOME=temp, sid present ===
C:/proga/claude-fleet
=== LIVE shim, FLEET_HOME=temp, sid REMOVED ===
C:/Users/Techn/AppData/Local/Temp/w48-rehearsal/fleet
=== LIVE shim, FLEET_HOME=temp, sid set to a random unclaimed uuid ===
C:/Users/Techn/AppData/Local/Temp/w48-rehearsal/fleet
```

The sid→home lookup wins. `bin/fleet.py` `resolve_home` implements multi-fleet §5 in order: step 1
`--fleet-home`, step 2 `lookup_home_for_sid(...)` which `return`s on a hit, and only then steps 3/4
where the env var is consulted. So **a session whose session id is claimed by a registry in the
install root's home population gets that home and `FLEET_HOME` is ignored.** BELIEVED (read from
source, not separately executed): the lookup population is scoped by `INSTALL_ROOT`, which is why
row D still honoured the env var — the temp install cannot see the live registry.

MEASURED — the override that *does* outrank the lookup exists and is invisible to users:

```console
$ fleet --help
> global: --fleet-home <PATH> selects which fleet home to act on (accepted in
  any position; see docs/specs/multi-fleet.md §5)

$ Select-String -Path README.md,docs\getting-started.md,docs\concepts.md,docs\launch-readiness.md,docs\README.md -Pattern 'fleet-home'
(no matches)
```

**This is a correction to the brief's own safety instruction** — see §12.

**Doc fix applied:** the sentence is qualified to what the code does, and `--fleet-home` is
documented with its precedence.

---

## 4. `fleet init` does not produce an "initialized home"

**Class (b), R2-shaped. MEASURED.**

```console
$ fleet --fleet-home C:\Users\Techn\AppData\Local\Temp\w48-rehearsal\fleet home
fleet: --fleet-home C:\Users\...\w48-rehearsal\fleet is not initialized (not_initialized) -- an initialized home is one whose `state/fleet.json` exists and parses (docs/specs/multi-fleet.md, Definitions). Nothing was created.
rc=1
```

`fleet init` had run on that home, rc=0, minutes earlier. It writes `state/worker-settings.json`;
`state/fleet.json` appears on the first `save_registry`, i.e. the first spawn.

BELIEVED → **retracted as a defect.** I went looking for a class (c) here and the code refuses the
charge in writing: `home_is_initialized`'s docstring says *"NOTE THE RATIFIED CONSEQUENCE, which is
surprising and is pinned rather than softened: `fleet init` ... does NOT create `state/fleet.json`
... a home that has been `fleet init`-ed but never spawned into is NOT initialized by this
definition. That is the spec's call."* So the code is deliberate and correct. The defect is that
**a verb named `init` does not do what a refusal three feet away calls "initialized", and no
user-facing doc mentions it.** The refusal also names a definition and a spec path but no remedy —
R2's shape, though a milder instance than §5.

---

## 5. R2, confirmed with a closed loop: `fleet knowledge` sends you to a command that cannot fix it

**Re-measures `launch-readiness.md` gap 3 and strengthens it.** That document reported the message.
It did not run the remedy. I did:

```console
$ FLEET_HOME=C:\Users\Techn\AppData\Local\Temp\w48-althome
$ fleet knowledge
(no knowledge index at C:\Users\Techn\AppData\Local\Temp\w48-althome\knowledge\INDEX.md -- run `fleet init`)
rc=0

$ fleet init
fleet init: wrote C:\Users\Techn\AppData\Local\Temp\w48-althome\state\worker-settings.json
  python:      C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe
  fleet home:  C:/Users/Techn/AppData/Local/Temp/w48-althome
init rc=0

$ fleet knowledge
(no knowledge index at C:\Users\Techn\AppData\Local\Temp\w48-althome\knowledge\INDEX.md -- run `fleet init`)
knowledge rc=0

$ ls -R C:\Users\Techn\AppData\Local\Temp\w48-althome
state
state\worker-settings.json
```

MEASURED — the remedy succeeds and changes nothing relevant; the message is byte-identical. **A
closed R2 loop.** Two things the prior document did not record:

1. **`fleet knowledge` exits 0** on a missing index. A script that checks `rc` sees success.
2. The loop is unescapable from inside the message: nothing tells the user the index is a
   *git-tracked directory in the clone*, so a `FLEET_HOME` outside the clone can never have one.

**REPORTED, NOT REPAIRED** (`bin/` is fenced this lane). The change I would have written:

```diff
-        print(f"(no knowledge index at {idx} -- run `fleet init`)")
-        return 0
+        print(f"(no knowledge index at {idx} -- knowledge/ is git-tracked in the clone and "
+              f"`fleet init` does not create it; point FLEET_HOME at a clone, or copy "
+              f"knowledge/ into this home)")
+        return 1
```

BELIEVED: the `return 1` half needs a maintainer's call — some caller may depend on rc=0. The
message half is unambiguously right.

---

## 6. Python: the floor claim is TRUE, and the failure a stranger hits names nothing

MEASURED — the documented invocation on every interpreter this box has:

```console
=== py -3.13 bin\fleet.py --help ===   rc=0  first=usage: fleet [-h]
=== py -3.10 bin\fleet.py --help ===   rc=0  first=usage: fleet [-h]
=== py -3.14 bin\fleet.py --help ===   rc=0  first=usage: fleet [-h]
=== py -3.11 bin\fleet.py --help ===   rc=0  first=usage: fleet [-h]
```

`MIN_PYTHON_VERSION == (3,10)` holds in practice, on 3.10 and on 3.13, and also on 3.11 and 3.14
which no doc claims. **MATCH.**

MEASURED — `launch-readiness.md` gap 1 says the `.cmd` shim hardcodes `py -3.13` and that "nothing in
the failure names the cause." Both true, and here is the string it never pasted. I could not
uninstall 3.13, so I asked `py` for a version this box genuinely lacks (3.12), which is the same
launcher failure a 3.10/3.11/3.12 user meets:

```console
$ py -3.12 bin\fleet.py --help
No suitable Python runtime found
Pass --list (-0) to see all detected environments on your machine
or set environment variable PYLAUNCHER_ALLOW_INSTALL to use winget
or open the Microsoft Store to the requested version.
rc=103
```

No mention of fleet, of `fleet.cmd`, or of the fact that 3.13 was requested by a shim rather than by
the user. A stranger searching that text finds Python launcher documentation, not this repo.

MEASURED — `bin/fleet.cmd` is `py -3.13 "%~dp0fleet.py" %*`, no fallback, no `$FLEET_PYTHON`.
`bin/fleet` execs `hooks/run_py.sh`. Both confirmed by reading the two files. Gap 1 **stands
unchanged**; it is `bin/`-fenced here as it was there.

**Doc fix applied:** the exact failure text is now pasted in `getting-started.md` so it is
searchable.

---

## 7. Docs vs the shipped CLI surface

MEASURED — every documented verb and flag parses. `fleet <verb> --help`, rc=0 for all:

| verb | flags argparse accepts |
|---|---|
| `init` | `--chain --force --help --nonce --statusline` |
| `spawn` | `--category --context --dir --help --max-budget-usd --mode --model --nonce --setting-sources --task --token-ceiling` |
| `status` | `--all --help --json --stale-ok` |
| `clean` | `--dead-only --help --nonce --tombstones --yes` |
| `wait` | `--all --any --help --timeout` |
| `doctor` | `--help --repair` |
| `homes` | `--add --help --retire` |
| `respawn` | `--force --help --max-budget-usd --nonce --setting-sources --task --token-ceiling --yes` |
| `index` | positional `{init,build,update,status}` |

Every flag the two entry docs mention (`--dir --task --mode --token-ceiling --json --all --stale-ok
--repair --statusline --chain --dead-only`, and `index init/build/update/status`) exists. **No
class-(a) flag defect. MATCH.**

**Class (a), MEASURED — the subcommand count is wrong.** `getting-started.md` says *"That is all 32
subcommands `fleet --help` ships, as of `f457a57`."* At `fa236cb`:

```console
{home,knowledge,homes,init,spawn,status,peek,result,wait,send,interrupt,attach,release,respawn,resume-limited,kill,clean,archive,autoclean,index,q,doctor,sup-boot,sup-spawn,sup-checkpoint,sup-heartbeat,sup-release,sup-status,sup-context,sup-decision,sup-handoff-begin,sup-handoff-complete,sup-handoff-abort}
SUBCOMMAND_COUNT=33
```

**33.** The new verb is `homes`, and it appears in *neither* command table — not README's, not
`getting-started`'s. The doc predicted its own drift (*"if this table and `fleet --help` ever
disagree, `--help` wins"*), which is honest but is not the same as being right.

**Why a green suite did not catch either half.** MEASURED, by reading `tests/test_doc_claims.py` —
the module that exists to pin doc claims against the parser. It declares both blind spots itself:

> *"EVERY OTHER NUMBER. Test counts, file counts and subcommand counts pasted into these docs are
> hand-derived and unheld here; they will drift the same way `21 checks` did."*

> *"PRESENCE ONLY -- a shipped verb the docs never mention is invisible here."* — the docstring of
> `test_fleet_verbs_written_as_commands_in_entry_docs_are_shipped`

So the pin checks that every verb the docs *name* is shipped, never that every verb shipped is
*named*, and it explicitly disclaims pasted counts. **"32" and the missing `homes` row are precisely
the two drifts the test file predicted in writing.** MEASURED: `py -3.10 -m pytest
tests/test_doc_claims.py tests/test_lane_report_durability.py -q` → `35 passed in 1.73s`, both
before and after my edits. That is not a criticism of the pin — its holes are documented and it
positive-controls itself with `test_the_detector_catches_planted_drift` — but it means this class of
drift is found by rehearsal or not at all.

MEASURED — `fleet homes` read form works and is harmless:

```console
$ fleet homes
fleet homes: C:\Users\Techn\.claude\fleet-homes.list
  (no homes listed -- this machine runs a single fleet)
rc=0
```

BELIEVED (from `knowledge/INDEX.md`, ratified 2026-08-08, and honoured by the fence): `--add` and
`--retire` are **destructive**; I did not run either.

**Doc fix applied:** count corrected, `homes` added to both tables with the read/write split stated.

**Gap 4 re-measured, unchanged.** `--max-budget-usd` is still advertised by `--help` on `spawn` and
`respawn` and still refused unconditionally:

```console
$ fleet spawn probe --dir . --task "noop" --max-budget-usd 5
fleet: no USD budget under native dispatch (contract G3) -- use --token-ceiling
rc=1
```

MEASURED — the guard sits at `bin/fleet.py:6466`, *before* `_read_task_arg` and before the registry
commit, which is why running it was safe and why nothing was created. `bin/` is fenced; REPORTED.

---

## 8. What a stranger sees when it goes wrong

MEASURED — I deliberately did three documented things wrong. Errors are good; only §5 is R2.

```console
$ fleet spawn probe --dir C:\nope\does\not\exist --task "noop"
fleet: --dir does not exist or is not a directory: C:\nope\does\not\exist        rc=1

$ fleet statuss
fleet: error: argument command: invalid choice: 'statuss' (choose from home, knowledge, homes, ...)   rc=2

$ fleet peek nosuchworker
fleet: unknown worker: 'nosuchworker'                                            rc=1
```

MEASURED — after all three refusals plus the `--max-budget-usd` one, `state/fleet.json` in the
rehearsal home was still absent (`Test-Path` → `False`). Refusals refuse without side effects.

---

## 9. What the docs got RIGHT — measured, and worth stating

- **`fleet init` is honest and narrow.** MEASURED: rc=0 in 0.26s, printed the two values it
  substituted, and wrote exactly one file — `<FLEET_HOME>\state\worker-settings.json` — confirmed by
  enumerating the whole `state/` tree afterwards. Machine-global files untouched (§0).
- **`fleet doctor` really is 28 checks and really does go 28 PASS / 0 FAIL after `init`.**
  MEASURED: rc=0, 1.69s, 28 `[PASS]` rows, 0 `[FAIL]`. Counted from the full unpiped output.
- **The documented pre-`init` failure set is exactly right.** MEASURED, with
  `worker-settings.json` moved aside: rc=1 and exactly four FAILs —
  `worker-settings-instance`, `instance-freshness`, `instance-grants`, `hook-registration` — each
  naming ``run `fleet init` ``. That is a doc claim, stated with names and a count, that survives
  execution. **MATCH.**
- **The clone is portable and the public URL resolves.** MEASURED: clone 4.4s, 10.2 MB, HEAD
  `fa236cb`; `fleet home` from the temp clone (with its own shim) returns the temp path.
- **82 relative links across the five entry docs, 0 broken.** MEASURED — and the checker was
  positive-controlled on a seeded bad link (`DETECTED-BROKEN -> docs/NO-SUCH-FILE.md`,
  `checked=2 broken=1`) before I believed the zero.
- **`/fleet:overview` exists.** MEASURED: `commands/overview.md` present, 14 command files.
- **The trigger caveat is already in both entry docs.** MEASURED against
  `skills/fleet/SKILL.md`'s frontmatter: the declared triggers are `fleet`, `spawn workers`,
  `manage sessions`, `dispatch task to <project>`, `check on workers`, `boot a supervisor` — and
  *"become the fleet manager"* is indeed absent. README and `getting-started` both already say so
  and both already point at `/fleet:overview`. `docs/concepts.md` repeats the phrase with **no**
  caveat — the only one of the three that does. Fixed.

---

## 10. Steps I did NOT perform, and why

Stated plainly, because a silently-skipped step would make this lane worthless.

- **Step 3, `claude plugin marketplace add` / `plugin install` / `plugin details`.** NOT RUN —
  mutates the operator's real plugin configuration. **But the placeholder is now resolved from
  evidence**, read-only:

  ```console
  $ claude plugin marketplace list
  Configured marketplaces:
    ❯ claude-fleet
      Source: Directory (C:\proga\claude-fleet)
  ```

  MEASURED: the marketplace named `claude-fleet` is installed on this machine from a **directory
  path to the clone**, not from a GitHub shorthand. `launch-readiness.md` gap 2a asks someone to
  confirm which of the two candidate literals works and paste it. This is that answer, at the
  strongest grade obtainable without mutating: it is the observed source of a working install, not a
  `marketplace add` I executed. `.claude-plugin/marketplace.json` declares marketplace
  `claude-fleet` with plugin `fleet` at `"source": "./"`, consistent with the directory form.
  **BELIEVED** that the GitHub shorthand also works — untested, and no evidence either way.
- **Step 4, `fleet init --statusline`.** NOT RUN — writes `~/.claude/settings.json`, the operator's
  live machine-global config. Fence item 4.
- **`fleet homes --add` / `--retire`.** NOT RUN — ratified destructive.
- **Any real `fleet spawn`.** NOT RUN. The one spawn command I typed was refused pre-dispatch.
  Everything from `fleet spawn` onward — `send`, `peek`, `result`, `wait`, `respawn`,
  `resume-limited`, `kill`, `clean` — is **unverified by this lane**, exactly as
  `launch-readiness.md` already states.
- **`fleet doctor --repair`.** NOT RUN — the only mutating doctor path.
- **Linux/macOS.** Windows box only.

---

## 11. Two things measured that nobody asked for

**MEASURED — `fleet doctor` is not home-scoped.** On a brand-new home with no workers, three rows
report machine-global state: `claude-agents` listed **37** untracked sessions on the first run and
**40** twenty minutes later (this machine's real session population), `daemon-wedge` read
`daemon.lock held by pid 4188`, and `identity-witness` read this session's inherited `FLEET_WORKER`.
Not wrong — those checks are *about* the machine. But a stranger's "28 PASS" is not 28 statements
about their fleet, and **what those three rows print on a genuinely fresh machine with no daemon and
no sessions is UNVERIFIED here.** BELIEVED: they still PASS, since each has a benign empty-case
message; not measured.

**MEASURED — honest time from `git clone` to a working `fleet status`.** A second clean clone,
fully scripted, no human reading time:

```
clone     4.29s
PATH      0.01s
init      0.25s
status    0.23s
TOTAL     4.78s
```

**That number is the ceiling of the good news and should not be quoted alone.** The scripted path is
4.78 seconds only because the script already knows the two things the documents do not tell you:
the literal PATH command (§2) and which fleet it is about to configure (§1). A human following the
published text stalls at step 1 with `CommandNotFoundException` and again at step 3's unresolved
placeholder. **Machine time: ~5s. Documented-path time: unbounded, because the documented path does
not terminate.** That is what "launch readiness" costs today, and it is one small doc fix and one
warning away from being genuinely ~5s.

---

## 12. WHERE THIS BRIEF WAS WRONG

**1. The brief's safety instruction is not sufficient, and I can prove it.** It says: *"Set
`FLEET_HOME` explicitly to your temp home for every fleet command you run."* MEASURED in §3: inside
a fleet-managed Claude Code session whose session id is claimed by another home's registry,
**`FLEET_HOME` is ignored** — the sid→home lookup outranks it. Had I set `FLEET_HOME=<temp>` and
invoked the fleet that was already on PATH, I would have run `fleet init` against the live home
while believing the fence held. My fence held for a reason the brief never states: I also always
invoked the *temp clone's own shim*, which scopes the lookup population away from the live registry.
**The correct primitives are `--fleet-home <PATH>`, or the target clone's own shim — not the env
var.** The next lane that runs an installer on this machine should be briefed with that.

**2. Guess 1 — "the entry pair may be wrong" — did not land.** `README.md` → `docs/getting-started.md`
is the front door, `docs/README.md` routes correctly by audience, and all 82 relative links resolve.
The entry point is not the problem. What is wrong is *inside* the walkthrough.

**3. Guess 2 — "the walkthrough may be unrehearsable under the fence" — partly landed, and better
than predicted.** Steps 1, 2 and 5 are fully rehearsable; step 4 is structurally unrehearsable
(machine-global write) and stays unrehearsed. Step 3 I could not *execute* — but its open question
was answerable read-only, so the outcome is better than "unrehearsable": the placeholder is resolved
(§10).

**4. Guess 3 — "the docs may be fine and the code may have moved" — landed, in a direction the
brief's taxonomy has no box for.** The prediction was a report of class-(c) findings. What I found
instead: the single most dangerous defect (§1) is neither a false sentence nor a wrong line of code —
it is a *hazard the code creates and the doc never warns about*, and it is fixable purely in prose.
Likewise §4: I went hunting for class (c) and found the code had already argued the case against me
in a docstring. **The brief says "class (c) is the valuable one." On this evidence the valuable class
is (b) — the omission — and the brief's four-way taxonomy has no slot for "the code is deliberately
surprising and no user-facing doc says so", which is what §1, §3 and §4 all are.**

**5. The brief assumed `launch-readiness.md` might be contradicted by my run. It was not — it was
extended.** Every gap it lists that I could reach (1, 3, 4, 6, 7) reproduced exactly. Its own
"what this document did not verify" list is accurate and honest. Its one open request — resolve the
plugin placeholder — I answered. **The document on disk held up under a hostile re-run, which is
worth saying out loud, because that is unusual.**

---

## 13. Findings ledger

| # | Class | Sev | Finding | Fixed here? |
|---|---|---|---|---|
| 1 | (b) | **HIGH** | Documented `fleet init` targets a pre-existing fleet home; no warning anywhere (§1) | doc fix |
| 2 | (b) | **HIGH** | Step 1's PATH instruction is a comment; walkthrough dies at step 2 on a fresh box (§2) | doc fix |
| 3 | (a) | MED | *"Set `FLEET_HOME` … to override it"* is false inside a claimed session; `--fleet-home` undocumented (§3) | doc fix |
| 4 | (a) | MED | *"all 32 subcommands"* — it is 33; `homes` in neither table (§7) | doc fix |
| 5 | R2 | MED | `fleet knowledge` names a remedy that cannot fix it; exits 0 (§5) | **REPORTED** — `bin/` fenced; diff supplied |
| 6 | (b) | MED | `fleet init` does not make an "initialized home"; refusal names no remedy (§4) | doc fix (code is ratified) |
| 7 | (a) | MED | `--max-budget-usd` advertised by `--help`, always refused (§7) | **REPORTED** — pre-existing gap 4 |
| 8 | (b) | LOW | `bin\fleet.cmd`'s missing-3.13 failure names nothing about fleet (§6) | doc fix (text pasted); code `bin/`-fenced |
| 9 | (b) | LOW | `concepts.md` repeats the non-trigger phrase without the caveat the other two carry (§9) | doc fix |
| 10 | — | INFO | `doctor` mixes machine-global rows into a fresh home's 28/28 (§11) | reported |

**Not fixed, by fence:** every `bin/` item (5, 7, 8-code). **Not fixed, by evidence:** nothing — no
doc edit in this lane is unbacked by a measurement above.
