# `w51-initprep` — preparing `fleet init` for the operator

**Lane:** research + docs. **Branch:** `w51/initprep`, base `7b2ff75`. **Worktree:**
`C:/proga/fleet-w51-initprep`. **Date:** 2026-08-09.

**`fleet init` was NOT run.** `~/.claude/settings.json` was not written.
`~/.claude/fleet-homes.list` was not created or appended — it still does not exist. The live
`state/worker-settings.json` was not modified. Every command run against the live home is
enumerated in §6, with the reason each was safe.

Every line below is tagged **MEASURED** (I ran it and read the output, this wave) or **BELIEVED**
(derived by reading code or documents without executing the case). Note for a later reader: this
file is `docs/lanes/`, which `tests/test_receipts.py` does **not** scan — `SPEC_DIR` is
`docs/specs` only. The command blocks below are transcripts, not harness-verified receipts, and
should be re-run rather than trusted.

---

## 1. Verdict

**Run `fleet init`. It is correct, cheap, reversible, and it clears a genuinely RED row — but the
justification the brief gave for it is wrong, and the recipe says so.**

**MEASURED — the deploy is real, not a false alarm.** The live instance and the rendered template
differ in content, not merely in mtime.

**MEASURED — but nothing is misrouting today.** All four hooks resolve the correct home through
their step-4 install-root fallback, because install == home on this machine and no `FLEET_HOME` is
set anywhere. The deploy closes a fence *before* it is load-bearing, rather than repairing a live
leak. `docs/operator/fleet-init-recipe.md` leads with that correction instead of with the brief's
premise.

**I did not add a fifth operator gate.** Nothing measured forced one. §5 carries one finding I am
flagging loudly to the supervisor — a ratified-doctrine correction, not an operator question.

---

## 2. The measurements that decide it

### 2.1 The `--fleet-home` count, re-derived

**MEASURED.** Template **4**, live instance **0**. The brief's number is confirmed, and it was
re-derived rather than copied.

```
$ grep -o -- '--fleet-home' worker-settings.template.json | wc -l
4
$ grep -o -- '--fleet-home' /c/proga/claude-fleet/state/worker-settings.json | wc -l
0
```

### 2.2 `instance-freshness` is REAL here, not the wave-46 mtime false alarm

**MEASURED.** This was the brief's own named likeliest error, and the answer is that the row is
telling the truth this time.

`instance_freshness_info()` (`bin/fleet.py:5653`) compares **st_mtime only** — **MEASURED** by
reading it; `stale = template_mtime > instance_mtime`, with no content comparison anywhere in the
function. So the row could not, by construction, distinguish wave 46's case from this one.

I rendered the template exactly as `cmd_init` renders it and diffed against the live file. Two
independent renders agree: a hand-written 3-replace substitution, and a second pass through
fleet's own `render_worker_settings_template()` — **MEASURED** byte-identical to each other.

| | chars | bytes on disk | sha256 (first 8) |
|---|---|---|---|
| live `state/worker-settings.json` | **846** | 858 (CRLF) | `50b048c5` |
| rendered from today's template | **1002** | — | `ff44c7da` |

**MEASURED — the entire delta is the four `--fleet-home "C:/proga/claude-fleet"` additions.**
Nothing else differs: same interpreter path, same four hook script paths, same `Bash(fleet q:*)`
grant, same structure.

**MEASURED — and this reconciles wave 46 rather than contradicting it.** Wave 46 measured the
rendered template sha256-identical to the live instance at **846 chars**. 846 is *still* the live
instance's size today. The instance has not changed since; the **template** gained slice (c). Wave
46's finding was true then and is stale now, which is exactly what an mtime-only check cannot tell
you.

mtimes — **MEASURED**: live instance `2026-07-30 08:12:18`, live template `2026-08-09 08:42:17`.
Template newer ⇒ `stale = True` ⇒ `[FAIL] instance-freshness`.

### 2.3 What the missing flag actually costs today: essentially nothing

**MEASURED — all four hooks share one ladder.** `bin/hooks/{stop_outcome,stop_mailbox,
posttooluse_mailbox,postcompact_journal}.py` each define `_fleet_home()` with the same three live
steps: (1) `--fleet-home` in their own argv, (3) `FLEET_HOME` env, (4) the hook file's own location
walked up three parents to the repo root. (Steps 2 and 5 are deliberately skipped in the hook
plane.) Verified per-file by extracting each function's returns.

- Step 1 — **MEASURED absent**: the live instance carries the flag zero times.
- Step 3 — **MEASURED absent**: `FLEET_HOME` is unset in the ambient environment, and
  `_worker_env()` (`bin/fleet.py:2095`) copies `os.environ`, pops `CLAUDE_CODE_SESSION_ID`, and
  adds only `FLEET_WORKER`. It never sets `FLEET_HOME`.
- Step 4 — **MEASURED correct**: `bin/hooks/x.py → bin/hooks → bin → C:/proga/claude-fleet`, which
  is this fleet's home, because install == home in the legacy single-home layout.

**BELIEVED (code-derived, not driven): the exposure the flag closes is (a) a second, data-only home
sharing this install — step 4 would resolve to the install, i.e. the wrong home — and (b) a donor
environment carrying a foreign `FLEET_HOME`, since step 3 outranks step 4.**

**MEASURED — the donation mechanism is live on this machine right now.** This lane's own session
carried `FLEET_WORKER='sup|inc-20260808T173831Z-c6d4|boot'` — a dead supervisor's stamp — while the
registry resolved its sid to `w51-initprep`; `fleet doctor` printed the `identity-witness` LEAK row
saying exactly that. Environment substitution is happening. It donates no `FLEET_HOME` only because
nothing on this machine sets one.

### 2.4 The four settings-related doctor rows, graded against the rendered instance

**MEASURED**, in a throwaway home (`$CLAUDE_JOB_DIR/tmp/home51`), by pointing `fleet.FLEET_HOME` at
it and leaving `INSTALL_ROOT` on the live install so the template under comparison is the real one:

```
[PASS] worker-settings-instance: ... parses as JSON, hook commands use forward slashes, referenced scripts exist
[PASS] instance-freshness: instance is up to date with the template
[PASS] instance-grants: instance fleet grants match the template: ['allow:Bash(fleet q:*)']
[PASS] hook-registration: all registered hook events known and command paths exist (PostCompact, PostToolUse, Stop)
```

This is why the recipe's §5 table states the post-deploy rows as fact rather than as prediction. It
also rules out the specific worry that the added `--fleet-home <path>` token would be mistaken for a
hook script path by `hook-registration` or `worker-settings-instance`: **MEASURED**, it is not.

### 2.5 `fleet init`, file by file

**MEASURED (read of `cmd_init`, `bin/fleet.py:6331`).** Plain `fleet init` reads
`INSTALL_ROOT/worker-settings.template.json` and writes exactly one file,
`<home>/state/worker-settings.json`, **unconditionally, with no backup and no clobber refusal**
(`instance_path.write_text(rendered)`). It creates `state/` if absent. It writes nothing else
anywhere. It does **not** create `state/fleet.json`. It raises rather than writing if the template
is missing or a `{{PLACEHOLDER}}` survives the render.

`{{PYTHON}}` is `sys.executable` — **MEASURED**: `fleet` on PATH resolves to
`C:\proga\claude-fleet\bin\fleet.cmd`, which pins `py -3.13` →
`C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe`, matching what the live file
already names; a bare `python` on this machine is **3.10.1** at `C:/Program Files/Python310/`, and
would bake 3.10 into all four hook commands.

**MEASURED — `init` can refuse, and the brief's hedge was right for a reason it did not name.**
`cmd_init` opens with `_supervisor_gate("init")`. The gate arms on a caller carrying
`CLAUDE_CODE_SESSION_ID` while a supervisor claim is held with a fresh heartbeat, and a claim IS
live (`[PASS] supervisor-claim: SUPERVISOR: inc-20260809T094233Z-5e96 live, heartbeat 2m ago`).
**A human at a plain shell carries no sid and is not gated** — so the recipe tells the operator to
run it from PowerShell and not from inside a Claude Code session.

### 2.6 The statusline, read and never written

**MEASURED.** `~/.claude/settings.json` already carries a **fleet-owned** statusline:
`…/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py`, `refreshInterval: 10`, and
two `settings.json.bak.*` files already exist beside it.

**MEASURED (read of `_install_statusline`, `bin/fleet.py:6096`):**
`foreign = bool(incumbent) and "fleet_statusline.py" not in incumbent` → **False** here. So
`--statusline` would take the non-foreign path: no refusal, no `--chain` capture, a third
timestamped backup, and a rewrite of the `statusLine` key with an identical value. The recipe
therefore says **omit the flag** — it is a write to a machine-global file for zero gain.

For completeness, the foreign case (**BELIEVED**, code-derived, not driven here because driving it
would require writing that file): a non-fleet incumbent makes `fleet init --statusline` **refuse**
with a message naming `--chain` (capture the incumbent into `state/statusline-chain.json` and print
fleet's row beneath it) or `--force` (overwrite).

### 2.7 The canary's positive artifact, and the absence/slow discriminator

**MEASURED (read of `bin/hooks/stop_outcome.py:409-439`).** The Stop hook appends one JSON line to
`<resolved home>/state/outcomes/<key>.jsonl`, where `key = _resolve_name(home, sid) or sid` — so
normally `<worker-name>.jsonl`, falling back to `<sid>.jsonl` if the registry lookup misses. The
record carries `"kind": "result"`. `fleet result <name>` reads that store.

**MEASURED (read of `recompute_worker_native`, `bin/fleet.py:3771-3792`, and
`_investigate_no_outcome`, `:3691`).** The discriminator is mechanical:

- roster entry `busy`/`waiting` → `working` — **a slow worker**
- roster `idle` or gone, **and** `has_fresh_outcome(name, sid, since)` → `idle` — **success**
- roster `idle` or gone, **no** fresh outcome, past the dispatch grace window →
  **`dead-suspected`** — the failure the canary exists to catch

`has_fresh_outcome` defaults to `kinds=("result",)`, so a fleet-written tombstone cannot launder a
kill into a false success.

---

## 3. Deliverable 2 — the operator docket

**MEASURED — both of the brief's premises hold.**

- `docs/OPERATOR-GATES.md` is tracked (`git ls-files --error-unmatch` succeeds) and carries **all
  four** open gates, gate 4 (the slice-(c) `witness` question) included. The gates were never at
  risk. This is the "much bigger finding" the brief told me to stop for; it does not apply.
- `state/w48-operator-docket.md` is untracked: `git check-ignore -v` → `.gitignore:1:state/`, and
  `git ls-files --error-unmatch` → `error: pathspec ... did not match any file(s) known to git`.

**MEASURED — two things the brief did not anticipate, and both changed the deliverable's form:**

1. **The digest is STALE.** It opens *"Three gates are open"* and covers gates 1–3; gate 4 was
   added later by the wave-49 supervisor. Relocating it verbatim would have committed a false count
   into the tracked tree.
2. **There was no live pointer to fix.** Every tracked reference to `state/w48-operator-docket.md`
   is in `supervisor/JOURNAL.md` — seven lines, each a dated record of what a supervisor did on a
   given day. This repo's ratified rule is that a claim about a past tree is not rot, and a record
   of an act is corrected by appending, never by rewriting. **MEASURED**: no brief template, skill,
   or instruction surface names that path.

**What I did instead**, taking the brief's own escape hatch: `docs/operator/gate-docket.md` is a
**pointer-plus-recommendations digest**, explicitly not the record, stating that
`docs/OPERATOR-GATES.md` wins on any disagreement. Each gate gets one line of question, the
recommendation *already on file from its filer* (attributed, compressed, never re-argued), and its
artifact paths. Nothing is ticked, no gate text is edited, nothing is re-litigated.

**MEASURED — every artifact pointer in the digest resolves**, because a digest that hands the
operator a dead path is the defect it exists to remove:

- `docs/proposals/2026-08-09-goals-band-section-replacement.md` (`4f5d5fe`) — tracked on this branch.
- `w49/home-witness` at `da04c80`, and `docs/lanes/w49-home-witness.md` **on that branch** —
  `git show` reads it.
- `init` carries `--nonce/--statusline/--chain/--force` and **no `--home`** — gate 3's "slice (b) is
  unbuilt, nothing contradicts today" is still true of the shipped tree.
- `state/verdicts/w47-ga3.md` is gitignored; the digest says so rather than pretending it is
  reachable.

**Discoverability fix:** one clause added to `CLAUDE.md`'s "start here" paragraph, pointing at
`docs/operator/` as digest-and-recipes and re-stating that `docs/OPERATOR-GATES.md` is the record.
**BELIEVED safe:** `tests/test_lane_report_durability.py`'s `SURFACES` tuple is
`("skills/fleet/SKILL.md", "skills/fleet/supervisor.md", "docs/lanes/BRIEF-TEMPLATE.md")` —
**MEASURED** — so neither `CLAUDE.md` nor anything under `docs/operator/` is scanned by that pin.

---

## 4. WHERE THIS BRIEF WAS WRONG

**(1) "The failure mode is silent — a worker whose Stop hook writes its outcome to the *wrong* home
looks exactly like a worker that is working."** **MEASURED FALSE, and it is the load-bearing claim
of the brief's framing.** It looks like `working` only while the session is genuinely still running.
Once the roster reports the session idle or gone with no fresh outcome in this home, the recompute
verdicts **`dead-suspected`**, which has its own `fleet doctor` row and its own `fleet status` flag.
The canary section is therefore much stronger than the brief expected: the discriminator is a state
word, not a stopwatch.

**(2) "Two rows are expected to stay RED."** **MEASURED: THREE.** Alongside `identity-witness` and
`supervisor-pending-decision`, `[FAIL] pin-version: claude 2.1.226 != 2.1.222 at last pin pass
(2026-08-05T15:03:55Z)` is RED and unrelated to this deploy. An operator handed a two-row
expectation and shown three would reasonably suspect the deploy. The recipe names all three.

**(3) "`state/w48-operator-docket.md` … the pointer every brief hands the operator points at the
perishable copy."** **MEASURED FALSE.** Every tracked reference is inside `supervisor/JOURNAL.md`,
append-only history that must not be rewritten. No brief, template, or skill points there. There
were no live pointers to update — the fix was to create a durable digest and give it one
discoverability line, not to repoint anything.

**(4) The brief treats the docket as a current restatement to be relocated.** **MEASURED: it is
stale** — three gates named, four open. Relocating it as-is would have made the tracked tree carry
a false count, which is the same class of defect the brief was trying to prevent.

**(5) "Every worker this fleet spawns is running under a settings instance that predates the work
built to fence it."** **MEASURED TRUE as stated, but the implied consequence is FALSE.** No worker
is at risk of writing to a wrong home on this machine today: step 4 resolves correctly and there is
no second home and no `FLEET_HOME` anywhere. The recipe leads with that rather than with the
implication, because an operator who runs this believing he is stopping a live leak will draw the
wrong conclusion from the canary passing.

**(6) "`instance-freshness` … may be the mtime false alarm."** **MEASURED FALSE here** — real
content difference, 846 → 1002 chars. The brief was right to demand the measurement and right that
it would reshape the document; it reshaped the *justification*, not the recommendation.

**(7) "`fleet init` is a single clean operation on an existing home (it may be several, or may
refuse)."** **MEASURED: it is a single write of a single file — and it CAN refuse**, via
`_supervisor_gate`, for a caller carrying a session id while a live claim beats. The hedge was
right; the reason was not named, and it is an operator-facing instruction (run it from PowerShell,
not from a Claude Code session), so it is in the recipe.

**(8) "the docket relocation is trivial."** Not trivial — but for reasons (3) and (4), not the
reason expected.

**Where the brief was right, and it mattered:** its instruction not to trust a sha in prose
(**MEASURED**: HEAD is `7b2ff75`, as the brief said, and its own corrected note about `main` was
accurate); its demand that the `--fleet-home` count be re-derived; its demand that
`instance-freshness` be measured before writing anything; and its instruction to report *why*
contained rather than *that* contained — which is what produced §5.

---

## 5. FLAGGED TO THE SUPERVISOR — the ratified fence lesson is wrong about *why*

**Not an operator gate.** It is a correction to `knowledge/lessons.md#2026-08-09-w48-fences`,
`knowledge/INDEX.md`, `docs/lanes/BRIEF-TEMPLATE.md`'s stanza and
`knowledge/playbooks/campaign-template.md` v1.11 item (7). It changes no ratified spec text and asks
the operator nothing. I did not edit any of those surfaces — this lane's fence is docs-only and
those are shared instruction surfaces.

**What the record currently says:** *"A containment audit came back clean for the WRONG reason —
`~/.claude/fleet-homes.list` did not exist, so the lookup population was empty; one `fleet homes
--add` and every lane's temp-home fence evaporates."*

**MEASURED: the population is never empty, and no `fleet homes --add` is needed.**
`resolution_population()` (`bin/fleet.py:4601`) returns the homes-list members **∪ the legacy
install-root home**, and the legacy term is unconditional while §8 lives. Driven in-process against
the live install:

```
homes list ok=True members=[] reason=absent
population homes: ['C:/proga/claude-fleet']  legacy: C:/proga/claude-fleet
lookup state: hit  home: C:/proga/claude-fleet  hits: ['C:/proga/claude-fleet']
```

And end-to-end through the CLI, with a control arm — **MEASURED**:

```
$ env -u CLAUDE_CODE_SESSION_ID FLEET_HOME=<temp> fleet home
C:/Users/Techn/.claude/jobs/34e07221/tmp/home51        <- fence HOLDS

$ FLEET_HOME=<temp> fleet home                          (sid present, homes.list ABSENT)
C:/proga/claude-fleet                                   <- fence FAILS, today, with no --add
```

So the wave-48 audit was indeed clean for the wrong reason, but not the reason recorded: the
protection was never coming from an empty population, because the population always contains the
install-root home and every fleet-launched lane's sid is in that home's registry. **The practical
consequence points the same way as the existing advice but harder:** removing
`CLAUDE_CODE_SESSION_ID` from the child environment is not a belt-and-braces addition to
`FLEET_HOME` — on this machine, as it stands, it is the *only* thing that fences a lane, and the
"one `fleet homes --add` away" framing understates the exposure as conditional when it is present.

**Recommended disposition:** a small, gated docs edit to those four surfaces. It is not this lane's
to take.

---

## 6. Every `fleet` command run, and which home it touched

The brief asks *why* contained, never merely *whether*. **This lane's containment is not the
wave-48 accident** (which came back clean because a lookup population was believed empty — see §5,
where that explanation is measured wrong). It rests on two things instead: **I ran no mutating verb
at all**, and the two read-only verbs were pointed at the live home **deliberately**, because
reading the live home is the task.

| # | Command | Home it actually touched | Why safe |
|---|---|---|---|
| 1 | `py -3.13 bin/fleet.py home` (cwd `C:\proga\claude-fleet`) | **the LIVE home** — printed `C:/proga/claude-fleet` | `cmd_home` is one `print`. No lock, no read of state, no write. |
| 2 | `py -3.13 bin/fleet.py doctor` (same cwd) | **the LIVE home** — read only | No `--repair`, so it takes the `read_registry_no_repair` path; `cmd_doctor`'s own docstring: *"Nothing below this line writes."* Its two hook smoke-tests fire against a fresh `tempfile.TemporaryDirectory()`, never against this home. |
| 3 | `env -u CLAUDE_CODE_SESSION_ID FLEET_HOME=<temp> … fleet home` | **the throwaway home** `…/tmp/home51` — the fence gate | Gate for drive 5. Compared NORMALISED (`as_posix()`), so the Windows-separator false alarm the stanza warns about could not fire. |
| 4 | `FLEET_HOME=<temp> … fleet home` (sid present) | **the LIVE home** — printed, nothing else | The deliberate **control arm** of §5. `cmd_home` prints and exits; nothing was written to either home. |
| 5 | in-process: `import fleet`, `fleet.FLEET_HOME = <temp>`, four `_doctor_check_*` calls | **the throwaway home** for all state paths; the LIVE install only for the template **read** | Asserted `state_dir()` was under the temp path before writing anything. The only write was `<temp>/state/worker-settings.json`. `INSTALL_ROOT` was left live on purpose — the template must be the real one. |
| 6 | in-process: `read_homes_list()`, `resolution_population()`, `lookup_home_for_sid()` | read the LIVE home's registry | All three are pure reads; `read_homes_list` on an absent file returns `ok=True, members=[], reason=absent` and creates nothing. |

**Not run, and each explicitly forbidden by the brief:** `fleet init` (with or without
`--statusline`), any write to `~/.claude/settings.json`, any `fleet homes --add`, any modification
of the live `state/worker-settings.json`. **MEASURED after the fact:**
`~/.claude/fleet-homes.list` still does not exist, and the live instance is still 858 bytes with
mtime `2026-07-30 08:12:18`.

---

## 7. Deliverables

| Path | What it is |
|---|---|
| `docs/operator/fleet-init-recipe.md` | Deliverable 1 — the seven-section recipe, written for a human at a shell, with the justification corrected per §2.3. |
| `docs/operator/gate-docket.md` | Deliverable 2 — the docket as a tracked pointer-plus-recommendations digest, explicitly not the record. |
| `CLAUDE.md` | One clause: `docs/OPERATOR-GATES.md` is the record, `docs/operator/` is the digest and the recipes. |
| `docs/lanes/w51-initprep.md` | This report. |

Working state, deliberately disposable, per `docs/lanes/README.md`:
`$(fleet home)/state/journals/w51-initprep.md`.

**No fifth operator gate was added. No gate text was edited. Nothing was ticked. No ref other than
`w51/initprep` was moved, and nothing was pushed.**
