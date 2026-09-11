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
- `C:/proga/claude-fleet/state` — **this receipt was withdrawn under gate; see DISCHARGE / MINOR-4.**
  It originally claimed a whole-tree file-set + size + mtime snapshot came back `UNCHANGED` each
  time. A whole-tree snapshot cannot truthfully say that on a live fleet — other lanes write `state/`
  continuously, and 33 files were written inside this lane's own window. **What replaces it, and what
  reproduces:** the file `fleet init` writes, `C:/proga/claude-fleet/state/worker-settings.json`, has
  `mtime=2026-07-30T08:12:18` — ten days before this rehearsal, and still that value when re-read on
  2026-08-09 at 05:26. No `fleet init` ran against the live home.
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
resolution population gets that home and `FLEET_HOME` is ignored.**

**The sentence that stood here next was wrong, and the gate broke it.** It read: *"BELIEVED (read
from source, not separately executed): the lookup population is scoped by `INSTALL_ROOT`, which is
why row D still honoured the env var — the temp install cannot see the live registry."* MEASURED
false. `resolution_population()` is `read_homes_list()` — the machine-wide
`~/.claude/fleet-homes.list` — **∪** the install root; the install root does not gate the listed
members, it is appended as one more candidate. Row D honoured the env var for a narrower reason than
scoping: this machine's homes list is ABSENT, so the population collapsed to the temp install root
alone. Correction and the controlled probe behind it: DISCHARGE / MAJOR-1.

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
  `checked=2 broken=1`) before I believed the zero. **The pin belongs on that number and this report
  originally left it off:** 82 is the count at the merge-base `fa236cb`, *before* my edits. The gate
  re-ran an anchor-resolving checker over the tree that would actually land at `4ccc8f7` and got
  `checked=83 broken=0` — the one added link, `concepts.md` → `getting-started.md#become-the-manager`,
  with its anchor resolving. The discharge commit adds one more (README → `getting-started.md#install`),
  checked in DISCHARGE / verification.
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
  ```

  (**The listing is quoted whole here on the second pass.** The first draft of this report abridged
  it to the `claude-fleet` row — and the four rows it dropped were the evidence that refuted the
  report's own next sentence. Abridging a receipt to the row you are arguing about is how that
  happens.)

  MEASURED: the marketplace named `claude-fleet` is installed on this machine from a **directory
  path to the clone**. `launch-readiness.md` gap 2a asks someone to confirm which of the two
  candidate literals works and paste it. This is that answer, at the strongest grade obtainable
  without mutating: it is the observed source of a working install, not a `marketplace add` I
  executed. `.claude-plugin/marketplace.json` declares marketplace `claude-fleet` with plugin
  `fleet` at `"source": "./"`, consistent with the directory form.

  **MEASURED, and it corrects this report's first draft**, which said *"BELIEVED that the GitHub
  shorthand also works — untested, and no evidence either way."* There is evidence, in the output
  above and in the command's own help: `claude plugin marketplace add --help` reads *"Add a
  marketplace from a URL, path, or GitHub repo"*, and four of the five marketplaces on this box are
  GitHub-sourced (`grep -c 'Source: GitHub'` → `4`; `Source: Directory` → `1`). The form is
  evidently accepted. What is genuinely untested is only whether **`exPardus/fleet` in particular**
  resolves as a marketplace.
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
invoked the *temp clone's own shim*.

**That second primitive is conditional, and the first draft of this paragraph stated it flat — the
gate caught it (DISCHARGE / MAJOR-1).** A temp clone's own shim fences only while
`~/.claude/fleet-homes.list` is absent or empty, because `resolution_population()` is that
machine-wide list **∪** the install root, not the install root alone. Register one home with
`fleet homes --add` and the temp clone's shim sees it too: the sid lookup hits, `FLEET_HOME` is
ignored from the temp clone as well, and the fence stops working — silently, with no error, which is
the 2026-07-29 incident's exact shape. It held for this lane, and for the gate, only because the list
was verified ABSENT before and after. That verification is not optional; it is the condition.

**The briefing the next lane that runs an installer on this machine actually needs:**

1. `--fleet-home <PATH>` is the only primitive that wins unconditionally.
2. The target clone's own shim works **only after** you have confirmed `~/.claude/fleet-homes.list`
   is absent or empty. Check it; do not assume it.
3. `FLEET_HOME` is not a fence at all inside a fleet-launched session.
4. Whichever you use, verify with `fleet home` invoked exactly the way the real command will be, and
   abort on a mismatch.

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

**Not fixed, by fence:** every `bin/` item (5, 7, 8-code). **Not fixed, by evidence:** ~~nothing — no
doc edit in this lane is unbacked by a measurement above.~~ **That last clause was false and the gate
proved it** — two hunks shipped with no measurement behind them, plus two more the gate did not
reach. Corrected in DISCHARGE / MINOR-7.

---

# DISCHARGE — against the `w48-glaunch` gate verdict

**Gate:** branch `w48/glaunch`, report `docs/lanes/w48-glaunch.md` @ `f896621`. Verdict **GATING —
0 BLOCKING, 3 MAJOR, 4 MINOR**, plus one defect the manager found in the diff and withheld from the
gate on purpose. Read in full before any edit here.

**All seven are accepted.** I looked for a defensible refusal and did not find one: all three MAJORs
are sentences *this commit added*, each describes behaviour that does not exist or prescribes a
remedy that does not cover the cause, and each re-checks as the gate says. One finding — MINOR-7(a) —
is discharged by **licensing the hunk rather than reverting it**, which the gate itself offered as
the alternative; that is the only place my answer differs from "delete or rewrite", and it is argued
below rather than assumed.

Grades: **MEASURED** (run in this session, output quoted) / **MEASURED (gate)** (the gate ran it,
quoted from `w48-glaunch.md`, and I re-derived the underlying fact from source here) / **BELIEVED**.

Fence unchanged and held: only `README.md`, `docs/getting-started.md`, `docs/launch-readiness.md`,
`docs/concepts.md` and this file were edited. `bin/fleet.py` was **read** at four call sites —
reading is what licenses MAJOR-1 and MINOR-7(a) — and never written.

---

## MAJOR-1 — the sid-lookup population — ACCEPTED, fixed in three places

**What was wrong.** The precedence table said priority 2 looks the session id up *"against the
registries the install root can see"*. It does not.

**MEASURED — the source, re-read here rather than taken on the gate's word.** `bin/fleet.py:4589`,
whose own docstring names the union before the code does:

```python
def resolution_population(install=None) -> dict:
    """§5 step 2's search space: *"folded list u legacy install-root home while
    §8 lives (§8 completion removes the term)"*.
    ...
    if install is None:
        install = INSTALL_ROOT
    listed = read_homes_list()
    legacy = home_identity(install)
    homes, seen = [], set()
    for ident in list(listed["members"]) + [legacy]:
```

`read_homes_list()` reads `homes_list_path()` — `bin/fleet.py:361`, *"`~/.claude/fleet-homes.list` --
the machine's list of fleet homes (multi-fleet §4)"*. The install root is appended as one more
candidate; it gates nothing.

**MEASURED (gate) — the behavioural half**, from a pure-function probe with `homes_list_path`
monkeypatched to a temp file so the real list was never read, run against a homes-list-absent control
and an unclaimed-sid control first:

```
=== TEST: homes list contains homeY; install root is installX ===
    population        = ['.../homeY', '.../installX']
    lookup.state      = hit
    resolve_home.step = lookup
VERDICT:
  homeY in population despite install root being installX?  True
  FLEET_HOME(homeZ) ignored in favour of homeY?             True
```

**Why the lane read it the other way**, stated as cause rather than excuse: on a machine whose
`fleet-homes.list` is ABSENT — this one, verified before and after — the population collapses to
exactly the install root, so install-root scoping is *observationally* true here. §3 of this report
graded that half BELIEVED and the doc then stated it as fact. **Promoting a BELIEVED line into a doc
sentence is the mechanism, and it is a lane-level lesson, not a typo.**

**Changed — three places, because the false sentence had a false consequence hanging off it:**

1. `docs/getting-started.md`, priority table row 2 → *"this session's id, looked up against every
   home in `~/.claude/fleet-homes.list` **plus** this install root"*.
2. `docs/getting-started.md`, a new callout under the table carrying the consequence the gate said
   mattered most: the population is machine-wide; the second-clone fence holds **only while that list
   is empty**; registering a home breaks it *silently* from any clone; `--fleet-home` is the only
   unconditional override. It tells the reader to check `fleet homes` first and to confirm with
   `fleet home` invoked the way the real command will be.
3. `README.md` CLI table and `docs/getting-started.md` command table — the `homes` rows, the verb
   this same commit newly documented, now say that `--add`/`--retire` mutate the list **that home
   resolution searches**, with a link to the resolution section. The gate's sharpest point was that
   this commit advertised the verb that disarms its own safety advice without connecting the two.
   They are now connected at the verb, not only at the table.

Corrected **in this report** as well: §3's BELIEVED sentence is quoted and marked MEASURED-false in
place rather than quietly deleted, and §12.1's *"or the target clone's own shim"* now carries its
condition plus a four-point briefing for the next lane that runs an installer on this machine. **A
fence primitive with an unstated precondition is worse than no primitive, because it gets trusted.**

---

## MAJOR-2 — `# a DIRECTORY path, not a URL` — ACCEPTED, fixed in four places

**MEASURED — re-run here, not relayed:**

```console
$ claude plugin marketplace add --help
Usage: claude plugin marketplace add [options] <source>

Add a marketplace from a URL, path, or GitHub repo

$ claude plugin marketplace list | grep -c 'Source: GitHub'
4
$ claude plugin marketplace list | grep -c 'Source: Directory'
1
```

Four of the five marketplaces configured on this machine are GitHub-sourced. The parenthetical
asserted an exclusivity the CLI's own help denies, and *"no evidence either way"* was false against
evidence this very report had pasted — and then abridged away.

**Changed:**

- `README.md` and `docs/getting-started.md`: the comment on the literal is now
  `# the directory form -- the one verified here`. **The literal itself is unchanged** — the gate
  confirmed it works, and it stays.
- `docs/getting-started.md`, the step-3 callout: names the directory form as the only one verified
  *for this repo*, quotes `--help`'s three accepted source forms, gives the 4-of-5 count, and narrows
  the open question to whether **`exPardus/fleet` in particular** resolves as a marketplace.
- `docs/launch-readiness.md` gap 2a: *"no evidence either way"* is retracted in the text — the
  paragraph says plainly that an earlier revision was wrong — and replaced with both receipts above
  and the narrowed question.
- This report §10: the `marketplace list` block is now quoted **whole**, all five entries, with a
  note that the first draft abridged it to the one row being argued about and that the four dropped
  rows were the refutation. The reusable lesson: **abridging a receipt down to the row you are
  arguing about is how a report refutes itself without noticing.**

---

## MAJOR-3 — "fix PATH" names the wrong cause — ACCEPTED, fixed in both callouts

**MEASURED (gate)** — PATH correct (the new clone's own shim, zero other fleet entries), only a stale
`FLEET_HOME` left over from a prior install:

```
Get-Command fleet -> ...\gate\new\fleet\bin\fleet.cmd
FLEET_HOME        = ...\gate\old\fleet
fleet home -> C:/Users/.../gate/old/fleet          # E3
fleet home -> C:/Users/.../gate/new/fleet          # E3b, same shell, FLEET_HOME removed
```

Priority 3 outranks the install-root default, so a reader who audits PATH, finds it flawless and
stops is left holding a `fleet init` that would still write the old home. **Detection worked; the
remedy under-covered** — which is why the gate capped it below BLOCKING, and why the fix is a remedy
fix rather than a mechanism fix.

**Changed.** Both callouts now end *"check PATH **and** check `FLEET_HOME` — either can point you at
another home"*, and `getting-started`'s points the reader at the resolution table below it.

---

## MINOR-4 — the whole-`state/` fence receipt — ACCEPTED, withdrawn and re-grounded

The conclusion was true; the receipt could not have been. **MEASURED (gate):** 33 files were written
under the live `state/` inside this lane's own observation window, by other lanes —
`state/fleet.json` and `state/events.jsonl` among them. An honest whole-tree file-set + size + mtime
comparison across that window would have reported CHANGED, repeatedly.

**What I did not do: re-assert it more carefully.** A whole-tree snapshot on a live fleet is unusable,
and the right move is to stop claiming it rather than to hedge it.

**MEASURED — the replacement, which reproduces because it names one file:**

```console
FullName : C:\proga\claude-fleet\state\worker-settings.json
mtime    : 2026-07-30T08:12:18
Length   : 858
now = 2026-08-09T05:26:54
```

That is the file `fleet init` writes. Its mtime is ten days older than this rehearsal and unchanged
today — a positive statement about the exact hazard the fence exists for. §0 now carries this, with
the withdrawal stated in the text rather than silently swapped.

**The transferable rule, since the gate asked for one:** on a live fleet, a fence receipt must name
the files the feared write would touch. *"Nothing under `state/` changed"* is not a claim that can be
true while the fleet is running — and a positive-controlled detector does not rescue a claim whose
**scope** is wrong. This lane positive-controlled its detector (`detected_change=True`, §0) and still
shipped an impossible sentence.

---

## MINOR-5 — the callouts justify step 2 with a hazard step 1 removes — ACCEPTED

**MEASURED (gate):** with the new step 1's `$env:PATH = "$PWD\bin;$env:PATH"` applied and a prior
fleet still present, `fleet home` prints the **new** clone (E2). The old claim — *"if another fleet
clone is already on your PATH, a bare `fleet init` configures **that** home"* — was true of the old
walkthrough and false of the one this same commit wrote. The **instruction** stays; only its stated
reason was stale, and the stale reason taught the wrong model: *a prior fleet always wins* instead of
*PATH order decides*.

**Changed.** Both callouts now lead with **PATH order decides**, say that step 1's prepend puts the
new clone in front *for that shell*, and name the case that still makes step 2 worth typing — a later
shell where step 1 was never re-run — alongside the `FLEET_HOME` cause from MAJOR-3. `README.md`
demotes *"the clone you are standing in has nothing to do with it"* from the lead to the subordinate
point it actually is.

---

## MINOR-6 — the disposition omitted 2 of 9 — ACCEPTED, and it found more than the gate did

Discharged by replacing the sentence with a **table covering all nine entries** (1, 2a, 2b, 3, 4, 5,
6, 7, 8) — a prose list is what let two fall out of it. Gaps 5 and 8 were *"not re-checked"*; both are
pure reads, so I re-checked them rather than documenting the skip.

**Gap 5 — MEASURED, stands:**

```console
$ find .github -type f -o -type d | sort
.github
.github/ISSUE_TEMPLATE
.github/ISSUE_TEMPLATE/bug_report.md
.github/ISSUE_TEMPLATE/feature_request.md
$ find .github -name '*.yml' -o -name '*.yaml' | wc -l
0
```

**Gap 8 — MEASURED, and it does not reproduce: the entry is false, and was false the day it was
written.** `SPEC.md` §18 records M-D and M-E as SHIPPED, with dates:

```console
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

and they were folded in fourteen days *before* the entry was authored on 2026-08-05 (`0cefc81`):

```console
$ git log --format='%h %ad' --date=short -S'**M-D — vendor contract rehome' -- docs/SPEC.md
36a4c53 2026-07-22
```

**The cause is worth more than the correction.** Gap 8 was never measured against `SPEC.md`; it was
relayed from root `CLAUDE.md`, whose opening paragraph still says *"M-D and M-E shipped after and are
**not yet folded into §18**"* — stale since `36a4c53`. `launch-readiness.md` opens by promising that
every row was *"derived by executing something on this machine, not by reading prose"*. Gap 8 was the
one row that broke that promise, and it is the only entry on the list that a hostile re-run has
**removed** rather than confirmed. The section is now struck through, with the receipts and the
reason. **The live stale text is root `CLAUDE.md`, outside this lane's fence** — flagged, not edited,
and it belongs to whoever owns `CLAUDE.md` this wave.

This also revises §12.5 of this report, which said `launch-readiness.md` *"held up under a hostile
re-run"*. It held up on the eight entries I reached. The ninth I did not reach, and it was wrong.

---

## MINOR-7 — two unlicensed hunks — (a) LICENSED, not reverted; (b) ACCEPTED and fixed

### (a) `README.md` — *"This writes `~\.claude\settings.json`, your machine-wide Claude Code config."*

**I am keeping this line, and it is the one place I answer the gate with something other than
compliance.** The gate's own finding says it is TRUE, that it is *"a safety warning about a
machine-global write, which is defensible content"*, and that its defect is provenance: §0 of this
report states *"`fleet init --statusline` was never run"*, so no rehearsal measurement licenses it.
The instruction was *"cite the measurement or revert"*. I cite it — and grade it honestly rather than
laundering a code-read as a rehearsal.

**MEASURED — the citation, read in this session:**

```python
# bin/fleet.py:6084
def _install_statusline(force: bool = False, chain: bool = False) -> None:
    """Merge fleet's statusLine into ~/.claude/settings.json (Phase 1.6 D6).
    ...
    path = user_settings_path()          # :6096

# bin/fleet.py:353
def user_settings_path() -> Path:
    """~/.claude/settings.json -- the ONLY file outside FLEET_HOME that fleet
    ever writes, and only via `fleet init --statusline` (Phase 1.6 D6)."""
    return Path.home() / ".claude" / "settings.json"
```

**Grade: MEASURED against source; NOT measured by execution.** Reverting a true, load-bearing warning
about a machine-global write in order to satisfy a provenance rule would make the document worse and
the reader less safe. The rule this hunk actually broke is that its *grade* went unstated — and that
is what this paragraph repairs.

**The gate found one instance; there are two.** `docs/getting-started.md` carries the same warning
(*"This writes `~\.claude\settings.json` — your machine-wide Claude Code config, not a repo file."*)
against the same unrun step, and the gate's hunk walk did not flag it. Same licence, disclosed here
so the ledger is complete rather than only as complete as the gate's coverage.

### (b) `README.md` — *"One thing … Both"*

ACCEPTED, straightforwardly wrong: the paragraph opened with *"One thing"*, described two things and
closed with *"Both"*. It now reads *"Two things this quickstart cannot do for you."* with the two
split into their own sentences.

---

## THE PROOFREADING PASS — the class both the suite and the gate missed

The manager found *"`FLEET_HOME` is silently ignored inside a session fleet launched"* in
`docs/launch-readiness.md` by reading the diff, and withheld it from the gate to learn what a gate of
that shape covers. The answer: **not this.** The gate attacked every claim on the branch and did not
read one sentence for grammar. Neither does the suite — `tests/test_doc_claims.py` pins verbs, flags
and counts against the parser, never prose.

I re-read every line the commit added. Fixed:

| Where | Was | Now |
|---|---|---|
| `docs/launch-readiness.md` | "inside a session fleet launched" | "inside a fleet-launched session" |
| `docs/concepts.md` | "The phrase … **often works**, but it is not one of the triggers" | "is **not** one of the triggers …; activation is semantic, so it may match anyway, but nothing here guarantees it" |
| `docs/getting-started.md` | "`homes` shipped and went unlisted here **for a wave**" | "… and went unlisted here" |
| this report §9 | "82 relative links across the five entry docs, 0 broken" | same, now pinned to the merge-base `fa236cb`, with the tip's 83/0 attributed to the gate |

Only the first is a grammar defect. **The other three are the same substantive defect wearing
different clothes:** *"often works"* is a frequency claim, *"for a wave"* is a duration claim, and an
unpinned link count is a claim about an unnamed tree — three unmeasured quantities sitting in prose
that reads as measured. The gate's MINOR-7 caught the two hunks with *no* measurement behind them;
these three had a measurement nearby and quietly overstated it. **A proofreading pass over a
measurement-graded document is not spellcheck — it is where unquantified intensifiers get caught**,
and nothing in this repo's harness looks for them.

---

## WHAT THIS DISCHARGE FOUND THAT THE GATE DID NOT

Recorded because the gate asked to be attacked back, and because two of these enlarge its own
findings rather than adding new ones:

1. **Gap 8 is false, not merely unlisted** (MINOR-6). The gate found the bookkeeping omission and
   correctly noted that gap 8 appears nowhere in this report. It did not re-measure the gap itself,
   so it did not find that the entry has been wrong since the day it was written, nor that root
   `CLAUDE.md` is the stale source still propagating it.
2. **MINOR-7(a) has two instances, not one** — `docs/getting-started.md` carries the same unlicensed
   statusline warning that `README.md` does.
3. **Three unmeasured quantities in prose** (the proofreading table above) — a class adjacent to
   MINOR-7 that a hunk-by-hunk measurement walk does not model.
4. **INFO, `bin/`, out of fence, not this lane's to touch:** two docstrings contradict each other
   about how many files fleet writes outside `FLEET_HOME`. `user_settings_path` (`:354`) calls
   `~/.claude/settings.json` *"the ONLY file outside FLEET_HOME that fleet ever writes"*;
   `homes_list_path` (`:362`) calls `~/.claude/fleet-homes.list` *"The SECOND file outside FLEET_HOME
   that fleet writes"*. The second is correct; the first was not updated when the homes list landed.
   Harmless in code — and exactly the kind of stale absolute a doc lane reads and promotes into
   user-facing prose, which is what MAJOR-1 was.

**Where the gate was right and I had nothing to defend:** all three MAJORs. I went looking hardest on
MAJOR-2, where the directory literal *is* correct and the gate agrees — and the parenthetical still
cannot be made true. Per the method, a sentence that cannot be made true is deleted, not softened.

---

## ONE HARNESS COLLISION, WORTH RECORDING

`tests/test_doc_claims.py::test_no_doc_invents_a_fleet_verb` failed on the first discharge run:

```
AssertionError: docs/launch-readiness.md names `fleet <verb>` for verbs build_parser() does not
ship: ['is']
```

Cause: the gap-8 receipt originally pasted `git log --format='%h %ad %s'`, and the subject line of
`36a4c53` contains the words *fleet is* — which the detector, scanning shell-fenced blocks for
`fleet <verb>`, reads as an invocation. **Not a false claim; a true receipt the pin cannot parse.**
Resolved by dropping `%s` from the format and re-running the command, so the pasted output is still
exactly what the command prints. Recorded because the failure mode is non-obvious and will recur for
anyone pasting `git log` subjects into a scanned doc.

---

## VERIFICATION

**Fence — MEASURED.** The discharge commit touches exactly `README.md`, `docs/concepts.md`,
`docs/getting-started.md`, `docs/launch-readiness.md` and `docs/lanes/w48-launch.md`. Nothing under
`bin/`, `tests/`, `commands/`, `skills/`, `hooks/` or `docs/specs/**`; `bin/fleet.py` is
byte-identical.

**Live machine — MEASURED.** No `fleet` verb was run in this discharge session at all. The only
commands executed were `git`, `grep`/`find`/`sed`/`wc`, `pytest`, `Get-Item`, and three read-only
`claude plugin marketplace` reads. `C:/proga/claude-fleet/state/worker-settings.json` is still
`mtime=2026-07-30T08:12:18`. `~/.claude/fleet-homes.list` was neither created nor appended to. No
`fleet init`, no `homes --add`, no statusline install, no spawn, no `doctor --repair`.

**New links — MEASURED.** This commit adds one relative link, `README.md` →
`docs/getting-started.md#install`; the target heading `## Install` is at `docs/getting-started.md:40`.
The anchor added by `4ccc8f7`, `getting-started.md#become-the-manager`, still resolves
(`## Become the manager`, line 146).

**Suite — MEASURED.** The gate's exact five-file selection, on the 3.10 floor **and** on 3.13, not
piped through `head`:

```console
$ py -3.10 -m pytest tests/test_doc_claims.py tests/test_receipts.py tests/test_terminal_surface.py tests/test_lane_report_durability.py tests/test_views_doctrine.py -q -rs
330 passed, 2 skipped in 89.82s (0:01:29)

$ py -3.13 -m pytest <same selection> -q -rs
330 passed, 2 skipped in 97.86s (0:01:37)
```

(Two independent pairs of runs, over two successive trees during this discharge, both returned
**330 passed, 2 skipped**. Wall-clock varies between runs; the counts do not. The confirming run over
the exact tree being committed is quoted in the commit message, because a receipt pasted *into* the
tree it is about can never quote a run that includes itself.)

Same totals as the gate measured at `4ccc8f7`, and the 2 skips are the documented D4 pair, named
identically on both interpreters:

```
SKIPPED [2] tests\test_views_doctrine.py:247: no view quarantines any more -- D4 is true of shipped
code, so an unqualified restatement is no longer a defect.
```

**The first run of that selection was RED, and it was my defect** — recorded above under ONE HARNESS
COLLISION rather than quietly re-run into green.
