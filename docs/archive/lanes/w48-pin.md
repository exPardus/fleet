# `w48-pin` — the native contract at claude 2.1.226

| | |
|---|---|
| Branch | `w48/pin226` |
| Base | `fa236cb` (`docs(w47): journal through the wave-47 close and stand-down`) |
| Lane | Verification. **No production code changed.** Only this file is added. |
| Vendor | `claude --version` → `2.1.226 (Claude Code)` |
| Prior stamp | `state/pin-pass.json` → `2.1.222`, `passed_at 2026-08-05T15:03:55Z` |
| Interpreters | `py -3.13` → 3.13.12; `py -3.10` → 3.10.1 |
| Stamped? | **NO.** `state/pin-pass.json` untouched — see §7. |

Every line is tagged **MEASURED** (I ran it in this lane) or **BELIEVED** (reasoning I did not
execute). The gate should read §1 and §4 first.

**Headline:** the tier ran with **ZERO skips on both interpreters**. Five of six pins are GREEN on
both. **One pin, `test_3_pin_fork_steer` (G2b), went RED on py3.13 and GREEN on py3.10** — and the
RED is real, reproducible-in-kind, and **not** vendor drift. It exposes a latent reliability defect
in *fleet's own steer delivery*. I did not weaken the pin and did not touch `bin/fleet.py`.

**§8 is a mid-lane containment audit** the manager ordered after a sibling lane found `FLEET_HOME`
can be outranked by the sid→home lookup. Result: **nothing I ran touched `C:/proga/claude-fleet`**,
and `pin-pass.json` was not stamped — but the fence held because `~/.claude/fleet-homes.list` is
absent, not because the brief's mechanism works. One `fleet homes --add` would make this tier mutate
the live fleet.

---

## 1. WHERE THIS BRIEF WAS WRONG

The brief asked me to assume it contained an error and named three candidates. Two were right to
flag, one was wrong in my favour, and it missed a fourth.

### 1a. The contract list was incomplete — MEASURED (derived from the file)

The brief said the contract "covered at least: the closed 9-key roster schema, `claude rm`
clearing `--all`, the `rm` taxonomy still exiting rc=1 with `no job matching`, and the G2b / G10 /
Stop-hook records." Everything in that list is really there. But derived from
`tests/integration/test_native_pin.py` rather than from the journal, the tier asserts more:

| Step | Also asserts, beyond the brief's summary |
|---|---|
| 1 | spawn stamps both `session_id` and `native_short_id`; one of them is echoed in `spawn` stdout; `kind == "background"`; the **status/pid co-presence invariant**; `sessionId` truthy |
| 2 | `result_text` contains the expected token; `model` contains `haiku` |
| 3 | `send` prints `fork-steered`; old sid lands in `retired_sids`; **the old roster entry survives** (fork, not mutation) |
| 4 | `status == "interrupted"`; tombstone `kind == "interrupted"` with `result_text is None` |
| 5 | the entire **archive half** — gate-3 eligibility, `--dry-run` says `eligible`, no per-worker skip line, `archived_at` stamped, files actually moved into `logs/archive/<name>/` |
| 6 | **the whole step**, which the brief omits — `claude --version` rc=0 and non-empty, `record_pin_pass` writes the stamp, `fleet doctor` prints `[PASS] pin-version` |

**The difference that matters is in step 2.** The brief calls it "the Stop-hook records", implying
an assertion on usage counters. It is not one. Under **operator ruling A (2026-08-05, WITHHOLD)**
the usage-provenance verdict is **printed, not asserted** — `test_native_pin.py:398-401`. That is a
finding about the record, as the brief invited: *a summary of a journal is a claim.*

One nuance in fleet's favour, which an adversarial reader should not over-correct on: step 2 is
**not** toothless. `check_outcome_usage_contract` *raises* `PinUsageContractError` on schema drift
(absent keys, missing model, a counter that is neither `None` nor a non-negative int). It refuses
to assert only the *colour* (published vs withheld), because which branch a run lands in is a
coin-flip the tier cannot control. **My two runs landed on opposite branches** — see §3.

### 1b. "`FLEET_LIVE=1` is the whole gate" — the brief was right to doubt, and it IS the whole gate — MEASURED

`tests/conftest.py:160-176` is the only gate: `pytest_collection_modifyitems` marks anything under
`tests/integration/` as `live` and attaches a skip unless `FLEET_LIVE` is set. There is no second
condition. I proved it both directions rather than reading it:

```
$ py -3.13 -m pytest tests/integration/test_native_pin.py -v -rs      # no FLEET_LIVE
collected 6 items
... all 6 SKIPPED
SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness
6 skipped in 1.09s
```

With `FLEET_LIVE=1`, **zero** tests skipped on either interpreter. No hidden gate (a live daemon, a
populated roster, an interactive vantage) held anything back. §2 is the accounting.

### 1c. "2.1.222→2.1.226 is four releases and I have measured nothing" — correct to flag, and the answer is reassuring — MEASURED

Across everything this tier touches, **I found no vendor CLI contract drift at 2.1.226.** Roster
schema, dispatch, `--bg --resume` forking, Stop-hook firing, `claude stop`'s no-hook behaviour, the
`rm` taxonomy, and `--version` all behave as the record describes. The one RED is ours, not theirs
(§4).

### 1d. What the brief missed: **the tier's containment does not come from `conftest.py`** — MEASURED

The brief worried about stamping and told me to use a temp `FLEET_HOME`. Correct instinct, but the
reason is sharper than the brief states, and it is worth writing down because it is load-bearing:

`conftest.py`'s autouse sandboxes (`_never_touch_the_real_home`, `_never_touch_the_real_install`)
are **in-process `monkeypatch` calls, and the pin tier drives fleet as a SUBPROCESS.** Monkeypatch
does not cross that boundary — inside every `sb.fleet(...)` child, `Path.home()` is the *real*
home. The containment is therefore supplied entirely by the tier's own fixture, and it holds for
three independent reasons I checked in code before running anything:

1. `FLEET_HOME` is a `tempfile.mkdtemp()` dir, so `state_dir()` — and therefore
   `pin_pass_path() = state_dir()/"pin-pass.json"` (`fleet.py:223`) — resolves into the temp home.
   **Step 6 stamps the throwaway, never the real one.**
2. The fixture copies `bin/` into the temp home and runs `home/bin/fleet.py`, and
   `INSTALL_ROOT = Path(__file__).resolve().parent.parent` (`fleet.py:114`) → the temp home. The
   *code* plane is contained too, not just the data plane.
3. `cmd_init` (`fleet.py:6319-6378`) writes only `instance_settings_path()` unless `--statusline`
   is passed; the fixture passes no flags. `homes_list_path()` (`fleet.py:377`) is written only via
   `fleet homes --add/--retire` and `init --home`, neither of which the tier calls.

So the brief's instruction "if some step stamps as a side effect, run it against a temp
`FLEET_HOME`" was already satisfied by the tier's design. I verified the outcome empirically
anyway (§7) rather than trusting the analysis.

---

## 2. THE SKIP ACCOUNTING — the headline

The brief is right that a green suite certifies nothing unless every skip is accounted for. The
tier's own skips are **zero on both interpreters**, and I am reporting per-test outcomes, not
totals. Both runs used `-v -rs -s` and full output was captured to a file and read from the file —
never piped.

| | py 3.13.12 | py 3.10.1 |
|---|---|---|
| collected | 6 | 6 |
| passed | 5 | 6 |
| **failed** | **1** (`test_3`) | 0 |
| **skipped** | **0** | **0** |
| wall clock | 67.39s | 46.83s |
| exit code | 1 | 0 |

`-rs` printed **no** "short test summary info" skip section in either live run, because there was
nothing to print. For contrast, the ungated baseline in §1b printed exactly one `SKIPPED [6]` line.

Step 5 in particular did **not** take either of its two `ACHIEVABLE-CONTRACT SKIP` branches on
either interpreter — both are dead-daemon branches, and the daemon was alive throughout (§6).
That is the branch this vantage can actually certify.

**The whole-suite skip census corroborates it** — MEASURED, `py -3.13 -m pytest -q -rs` on this
branch, `4139 passed, 14 skipped, 1 xfailed in 403.97s`, exit 0. All 14 skips enumerated:

```
SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: set FLEET_LIVE=1 …
SKIPPED [3] tests\integration\test_sup_tombstone_live.py: live tier gated: set FLEET_LIVE=1 …
SKIPPED [1] tests\test_fleet_index.py:2068: this platform will not create a symlink unprivileged
SKIPPED [1] tests\test_hooks.py:783: pins the hook's os.write partial-write check; the Win32 sibling below pins WriteFile's
SKIPPED [1] tests\test_native.py:168: POSIX sibling of the Win32 partial-write pin
SKIPPED [2] tests\test_views_doctrine.py:247: no view quarantines any more -- D4 is true of shipped code …
```

This is exactly the number the brief warned about, and it decomposes cleanly: **6 of the 14 are the
pin tier itself.** That is the arithmetic behind the brief's warning — `4139 passed, 14 skipped` is
what a completely unrun pin tier looks like. The runs in the table above are what makes those 6 zero.

---

## 3. PER-PIN RESULTS

| # | Pin | Contract | py3.13 | py3.10 |
|---|---|---|---|---|
| 1 | `test_1_pin_dispatch_and_roster_contract` | closed 9-key roster schema, `kind=background`, status/pid co-presence, sid stamping | **GREEN** | **GREEN** |
| 2 | `test_2_pin_stop_hook_outcome` | Stop hook writes a `result` outcome; `result_text`, `model`; usage-provenance schema | **GREEN** | **GREEN** |
| 3 | `test_3_pin_fork_steer` | **G2b** — idle `send` forks a new sid, old retires and survives on the roster, hooks fire in the fork, **and the fork obeys the steer** | **RED** | **GREEN** |
| 4 | `test_4_pin_stop_no_hook_tombstone` | **G10** — external stop fires no Stop hook; fleet's own tombstone is the only record | **GREEN** | **GREEN** |
| 5 | `test_5_pin_archive_rm` | archive eligibility/move/`archived_at`; rm clears `--all`; **G12** rm taxonomy rc=1 `no job matching` | **GREEN** | **GREEN** |
| 6 | `test_6_pin_record_pass` | `record_pin_pass` + `fleet doctor` `[PASS] pin-version` (in the temp home) | **GREEN** | **GREEN** |

### The step-2 usage split — MEASURED

Exactly as the tier's own comment instructs (*"report the SPLIT over N runs — never a colour from
one"*), my two runs landed on **opposite ratified branches**:

```
py3.13: [pin] step 2 usage-provenance verdict: published (in=8 out=183 model='claude-haiku-4-5-20251001')
py3.10: [pin] step 2 usage-provenance verdict: withheld  (in=None out=None model='claude-haiku-4-5-20251001')
```

**Split at 2.1.226: 1 published / 1 withheld over 2 samples.** Both are ratified shapes; neither is
drift. `model` was present and correct in both, which is the discriminator that separates
"withheld" from "the vendor stopped emitting usage".

### Two bonus measurements the tier does not make — MEASURED

1. **Roster schema, 119 live entries.** The pin checks the closed 9-key schema against *one*
   entry. I read the whole roster and took the key union across every entry:
   ```
   total entries: 119
   union of keys: ['cwd','id','kind','name','pid','sessionId','startedAt','state','status']
   ```
   That is exactly `ROSTER_SCHEMA_KEYS`. **No unknown key anywhere on the machine's roster at
   2.1.226** — far stronger evidence for the roster contract than the pin itself produces.

2. **G12's last genuinely-UNOBSERVED sub-question, answered incidentally.**
   `docs/specs/native-substrate.md` G12 still lists *"whether `rm` also clears the transcript file
   under `~/.claude/projects/`"* as UNOBSERVED. The 3.13 run archived and `rm`'d pin-w1's sid, and
   afterwards its transcript was **still on disk** at
   `~/.claude/projects/C--Users-Techn-AppData-Local-Temp-fleet-pin-proj-2sp4byj6/6656c4f3-….jsonl`
   — I read all 49 records out of it (§4). **`claude rm` does NOT clear the transcript.** Offered
   as a spec-amendment candidate, not amended here (out of lane).

---

## 4. THE RED: `test_3_pin_fork_steer` — what actually happened

### 4a. The failure — MEASURED

```
>       assert "STEER-OK" in matching[-1].get("result_text", ""), matching[-1]
E       AssertionError: {'ts': '2026-08-08T23:35:16Z',
E        'session_id': '6656c4f3-8057-449d-8661-067a92372b6e',
E        'kind': 'result', 'result_text': 'PIN-OK', ...}
E       assert 'STEER-OK' in 'PIN-OK'
tests\integration\test_native_pin.py:440: AssertionError
```

Note **which** assertion failed. Everything G2b structurally promises passed first: the fork minted
a new sid, the old sid retired into `retired_sids`, the old roster entry survived, and **a
`kind=result` outcome record exists for the forked sid** — so the hooks *did* fire in the fork and
settings *did* survive `--bg --resume`. The only thing wrong is the **content**: the forked turn
answered with the *previous* turn's text.

### 4b. The forensics — MEASURED

The temp home is `rmtree`'d in teardown, but the transcript lives under `~/.claude/projects/` and
survived the `rm` (§3). Reading all 49 records of the forked session:

- The transcript contains **two turns**, both under the forked sid.
- **Turn 1 and turn 2's user prompts are byte-identical, 107 chars:**
  `Read C:/…/state/tasks/pin-w1.md and follow it exactly.`
- `STEER-OK` appears 6× in the transcript and **only** in `custom-title` / `agent-name` metadata
  (`fleet|pin-w1|Reply with exactly: STEER-OK` — that is the roster *name*, from `dispatch_bg`'s
  `hint=`). It appears in **no user message content**.
- Turn 1: `Read` the task file → tool_result ends `Reply with exactly: PIN-OK` → replies `PIN-OK`.
- **Turn 2 (the fork): no `Read` at all.** Its first act is a `Write` of the journal it had skipped
  in turn 1, then it replies `PIN-OK`.

### 4c. The mechanism — MEASURED (code) + MEASURED (probe)

`bin/fleet.py:1699-1715` documents the design in fleet's own words: `dispatch_bg`'s prompt is
literally `Read <task file> and follow it exactly`, and **`send`'s fork-steer composes with
`task=""` (F6 — the message rides the mailbox), replacing the task file with a preamble + mail
block.** So a steer is delivered by *rewriting a file the forked session has already read*, then
re-sending a **byte-identical pointer** to it. G2b's "fork carries full transcript" is precisely
what lets the model answer without re-reading.

That left one fork in the diagnosis I refused to guess at: did the rewritten file actually contain
the steer (worker ignored it), or did the mailbox drain lose the body (fleet dropped it)? The tier
deletes the evidence, so I wrote a probe that preserves `FLEET_HOME` across the `send`
(`$CLAUDE_JOB_DIR/tmp/probe_forksteer.py`, temp home + temp project, cleans up its own sids).
**3/3 runs, the task file after `send` reads:**

```
You are fleet worker `probe-w1` in `C:\…\w48-probe-proj-…`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `C:/…/state/journals/probe-w1.md` …
End every turn with a compact result summary: changed, verified, blocked.
Do not leave servers or watchers running past the end of the turn without recording their PIDs in the journal.

<MANAGER MESSAGE>
Reply with exactly: STEER-OK
```

`STEER-OK` present in the rewritten file: **3/3**. Present before the `send`: **0/3**.

**So fleet's mailbox delivery is CORRECT and the steer body reaches disk every time.** The defect
is that nothing *forces the fork to look*. Note the file no longer mentions `PIN-OK` at all — the
worker that answered `PIN-OK` did so purely from carried-over transcript context.

### 4d. Rate — MEASURED

| Sample | Vantage | Fork obeyed the steer? |
|---|---|---|
| tier, py3.13 | pin `test_3` | **NO** |
| tier, py3.10 | pin `test_3` | yes |
| probe run 1 | preserved home | yes |
| probe run 2 | preserved home | yes |
| probe run 3 | preserved home | yes |

**1 failure in 5 samples at 2.1.226.** Small-N; treat ~20% as an order of magnitude, not a
measurement. It is emphatically **not** 0%.

### 4e. Which side moved

- **The vendor did not.** MEASURED: the CLI forked, resumed, carried the transcript, fired hooks in
  the fork, and wrote a correctly-attributed outcome record. Nothing in the observed CLI behaviour
  contradicts the record.
- **The pin's assertion is not wrong.** It asserts a property fleet genuinely needs — *a steer
  changes what the worker does*. That is the entire point of `fleet send`.
- **Fleet's code is the weak side** — specifically the fork-steer *dispatch prompt*, not the
  mailbox. BELIEVED, and I want to be honest about the limit: **I cannot show this is new at
  2.1.226.** I have no 2.1.222 sample. The likeliest reading is that the defect is **latent and
  long-standing**, and that prior green runs of this pin were *samples that got lucky*, not proofs
  — exactly the epistemics the tier's own step-2 comment already applies to usage counters. A 20%
  failure mode needs only a handful of prior single-run greens to stay invisible.

**Consequence for the operator, which is why this matters beyond a red test:** `fleet send` to an
idle worker can print `fork-steered (new session …)` — a success message — while the worker
silently re-does its previous task and never sees the instruction. There is no signal anywhere that
the steer was ignored.

### 4f. Recommendation (escalated, not implemented)

Per the brief I did **not** touch `bin/fleet.py` (another lane holds it this wave) and did **not**
weaken the pin. For the supervisor to route:

1. **Do not weaken `test_3`.** It is a correct end-to-end assertion that just caught a real defect.
   If anything it is *too weak*: it samples once. Consider making the pin's steer token unique per
   run so a stale answer can never coincidentally match.
2. **The fix belongs in the fork-steer dispatch prompt.** The root cause is that the prompt is
   *byte-identical* to one the fork has already answered. Cheapest candidate: make the pointer
   distinguishable per dispatch (e.g. carry the `<MANAGER MESSAGE>` inline in the tiny prompt, or
   give the payload a dispatch-unique path/revision so a carried transcript cannot satisfy it).
   BELIEVED: inlining the manager message is the smallest change with the largest effect, since it
   removes the re-read from the critical path entirely.
3. **This is a `fleet send` correctness issue, not just a test issue** — worth an entry wherever
   steer semantics are specified, and worth deciding whether `send` should verify the steer landed.

---

## 5. WHAT THE TIER STILL CANNOT SEE — confirmed, not discovered

The brief listed these and asked me to confirm they still hold rather than report them as findings.
They hold.

- **A `--bg` worker cannot observe the dead-daemon path.** MEASURED that the daemon was alive for
  this whole lane: `claude daemon status` → `pid: 4188`, `version: 2.1.226`, `uptime: 21336s`,
  `origin: transient — started on-demand by 'claude --bg'`. I am myself a `--bg` session holding it
  open. **Zero skips here is positive evidence for the live-daemon branch ONLY.** Step 5's two
  `ACHIEVABLE-CONTRACT SKIP` branches were never exercised, in either direction.
- **M4's `"background service may be restarting"` string is STILL uncaptured** — a fifth wave
  without it. It needs an interactive, quiet-machine vantage I do not have. `_NATIVE_CLI_TRANSIENT_RE`
  remains built on a string nobody has observed, and G12's dead-daemon bullet remains
  ratification-withheld. Nothing in this lane changes that.
- **The specs' version receipt is `# volatile`** and WARNs rather than FAILs on a version mismatch.
  By design; not a defect I found.

---

## 6. CONTAINMENT AND INTEGRITY RECEIPTS — MEASURED

Checked after **each** of the two live runs, not once at the end.

| Check | Baseline | After 3.13 | After 3.10 |
|---|---|---|---|
| `git rev-parse HEAD` | `fa236cb` | `fa236cb` | `fa236cb` |
| `git status --porcelain` | empty | **empty** | **empty** |
| real `state/pin-pass.json` | `2.1.222` | `2.1.222` | `2.1.222` |
| `~/.claude/settings.json` md5 | `9958041a6ab22cc125fe70968e142fdb` | unchanged | unchanged |
| `~/.claude/fleet-homes.list` | **absent** | still absent | still absent |

- **`state/pin-pass.json` was NOT stamped.** Step 6 stamped the throwaway temp home; the real
  record still reads `2.1.222 / 2026-08-05T15:03:55Z`. The stamp is the supervisor's to write.
- **BELIEVED (not run):** `fleet doctor` against the real home still reports `[FAIL] pin-version`,
  since its two inputs are unchanged (pinned `2.1.222` vs live `2.1.226`). I deliberately did not
  run `doctor` against `C:/proga/claude-fleet` — my job ends at a report, and the row is arithmetic
  from two values I did measure.
- **`fleet init` was never run against `C:/proga/claude-fleet`.** Nothing was appended to
  `~/.claude/fleet-homes.list` (it still does not exist). `~/.claude/settings.json` was not written.
- **No real sessions leaked.** After everything, `claude agents --json --all` shows **0** entries
  named `fleet|pin-w*` and **0** named `fleet|probe-w*`, against the same 119-entry roster the lane
  started from. Both the tier's teardown and my probe's cleanup did their job.
- The suite's own session-scoped guard `_the_real_install_plane_is_byte_identical_afterwards` was
  active on both runs and did not fire — no repeat of the
  `worker-settings.template.json → {}` incident.

---

## 7. WHAT I DID NOT DO, AND RESIDUAL RISK

- **Did not stamp** `state/pin-pass.json`. **Did not** run `fleet init` against the real home.
  **Did not** touch `bin/fleet.py` or any pin file. The only file this branch adds is this report.
- **Did not** establish a 2.1.222 baseline for the fork-steer failure rate, so "latent and
  long-standing" (§4e) is BELIEVED, not MEASURED. Settling it means running the same probe against
  an older `claude`, which I cannot install from this vantage.
- **n=5** on the fork-steer rate and **n=2** on the usage split. Both are small. The direction is
  solid; the percentages are not.
- The dead-daemon branch of step 5 remains uncertified from any `--bg` vantage, this wave included.

## 8. `FLEET_HOME` FENCE AUDIT — requested mid-lane by the manager

The manager steered mid-lane with a correction: a sibling lane measured that **`FLEET_HOME` is
silently ignored inside a fleet-launched session** because the sid→home lookup (§5 step 2) outranks
the validated env var (§5 step 3), so the brief's temp-home fence may have been fencing with
nothing. I was asked to audit every `fleet` command I ran and disclose any write to the real home.

**Finding: nothing I ran wrote to `C:/proga/claude-fleet`. The fence held — but NOT for the reason
the brief assumed, and the machine is one command away from the hazard being live.**

### 8a. The mechanism is real; its precondition is not met on this machine — MEASURED

The manager's ordering is structurally correct. `fleet.py:4756-4800`: step 1 is the `--fleet-home`
flag, **step 2 is the sid→home lookup and it returns before env is ever consulted**, and only on a
lookup *miss* does control reach the env/legacy branch. So a sid that HITS does outrank `FLEET_HOME`.

The precondition is a population to search. Measured for this session's real sid:

```
my sid       : 23592cba-af43-4680-8d0c-792662d2acfd
lookup state : miss
population   : ['C:/proga/fleet-w48-pin']
legacy       : C:/proga/fleet-w48-pin
list_ok      : True | reason: absent
hits         : []
homes_list_path exists : False  C:\Users\Techn\.claude\fleet-homes.list
```

`~/.claude/fleet-homes.list` **does not exist on this machine** (I recorded its absence as a
baseline before the first run, and it is still absent). With no list, `resolution_population()`
falls back to the legacy/install home alone — **`C:/proga/claude-fleet` is not even a candidate.**
Step 2 therefore cannot hit, and env wins every time.

Confirmed behaviourally with the read-only `home` view, run four ways from this session:

| Invocation (sid present unless noted) | Resolves to |
|---|---|
| `FLEET_HOME=<temp> fleet home` | `<temp>` — **env honoured** |
| `FLEET_HOME=<temp> fleet home`, sid+`FLEET_WORKER` stripped | `<temp>` — identical |
| `fleet --fleet-home <temp> home` | refused: `not initialized (not_initialized) … Nothing was created.` |
| `fleet home`, no override | `C:/proga/fleet-w48-pin` — my worktree, **not** the real fleet home |

The last row is the direct refutation of the steer's premise for this session: with no override at
all, my sid does not resolve to `C:/proga/claude-fleet`.

### 8b. Independent evidence that no write reached the real home — MEASURED

I did not rely on the resolver analysis. Four independent checks, all clean:

| Artifact in `C:/proga/claude-fleet` | Result |
|---|---|
| `state/worker-settings.json` (what `fleet init` writes) | mtime **2026-07-30 08:12:18**, ten days stale; contains **no** temp path; names only real `C:/proga/claude-fleet/bin/hooks/*` |
| `state/pin-pass.json` | mtime **2026-08-05 20:03:55 +0500** = the original `15:03:55Z` stamp; content still `2.1.222` |
| `state/fleet.json` | 141 workers, **zero** named `pin-w*` or `probe-w*` |
| `state/tasks/`, `state/journals/`, `state/outcomes/`, `logs/archive/` | **no** `pin-w*` / `probe-w*` entries |

A fifth, and the one I trust most because the worker itself produced it: the surviving fork
transcript records the task-file path the dispatched worker was told to read —
`C:/Users/Techn/AppData/Local/Temp/fleet-pin-home-35vhv0wq/state/tasks/pin-w1.md`. The **temp**
home. The tier's dispatches genuinely composed against the sandbox, in the worker's own words.

### 8c. Command-by-command audit

| Commands | Home actually touched | Basis |
|---|---|---|
| `sb.fleet("init")` in the tier's module fixture (×2 runs) — the one call made **before** conftest's function-scoped sid-stripping fixture applies, and so the highest-risk call | temp | real `state/worker-settings.json` mtime ten days stale, no temp paths in it |
| `spawn`/`wait`/`send`/`interrupt`/`archive`/`doctor` inside test bodies (×2 runs) | temp | worker's own prompt names the temp task path; no `pin-w*` in the real registry/state |
| `record_pin_pass` subprocess (step 6, ×2 runs) | temp | real `pin-pass.json` mtime + content unchanged |
| my probe's `init`/`spawn`/`wait`/`send` (×3 runs) | temp | probe's `env()` explicitly `pop`s `CLAUDE_CODE_SESSION_ID` and `FLEET_WORKER`; no `probe-w*` in the real registry/state |
| my four `fleet home` audit calls | read-only view; one named temp, one named my worktree | `home` is in `TERMINUS_VIEW_VERBS` |

**No stamp, no registry mutation, no state file, no spawned worker reached `C:/proga/claude-fleet`.**

### 8d. The finding worth keeping — this is one `fleet homes --add` away from being live

The fence held by luck of configuration, not by design. **My sid IS in the real fleet's registry:**

```
my sid present in the REAL fleet registry under worker(s): ['w48-pin']
```

So if `~/.claude/fleet-homes.list` existed and listed `C:/proga/claude-fleet`, `lookup_home_for_sid`
would return **hit** on that home, step 2 would return before env was read, and **every
`sb.fleet(...)` call in the pin tier would have acted on the real fleet** — spawning `pin-w1`/`pin-w2`
into the live registry, archiving into real `logs/`, and **stamping the real `pin-pass.json` at
step 6.** The tier's containment rests entirely on `FLEET_HOME`, which is the one override that
step 2 outranks.

Consequences worth routing beyond this lane (BELIEVED — mechanism MEASURED, blast radius reasoned):

1. **The manager's corrected fence is the right one and should be adopted**: `--fleet-home` (step 1)
   is the only override that outranks the lookup. Note it is also stricter — it *validates* the home
   and refuses an uninitialized one, which is why my flag probe was refused where the env var was
   silently accepted. A tier switching to the flag must `fleet init` the temp home first.
2. **`tests/integration/test_native_pin.py`'s `Sandbox.env()` sets `FLEET_HOME` and does not strip
   `CLAUDE_CODE_SESSION_ID`.** It is safe today only because the homes list is absent. Populating
   that list — the multi-fleet slice-0 build is heading exactly there — would silently convert this
   suite into one that mutates the operator's live fleet. That is a test-isolation hazard of the
   same class as the two `conftest.py` already documents, and it is not covered by either, because
   both are in-process monkeypatches and this tier drives fleet as a subprocess.
3. **Every brief on this machine that fences a lane with `FLEET_HOME` is fencing with something that
   a future `fleet homes --add` disarms.** Not my slice, reported as asked.

I did not "fix" any of this: no pin file and no `bin/fleet.py` change, per the lane's fence.

## 9. VERDICT

**The native contract at 2.1.226 is intact on every axis this tier can reach from a `--bg` vantage,
with zero unaccounted skips on two interpreters — except that `fleet send`'s fork-steer can
silently fail to steer, ~1 run in 5, because it re-sends a byte-identical prompt to a session that
already carries the answer.** The vendor did not move. The pin is right. Fleet needs the fix, and
`bin/fleet.py` belongs to another lane this wave, so it comes back to the supervisor.

Recommended: **do not stamp `pin-pass.json` to 2.1.226 yet.** Five of six pins justify it, but
stamping records that the native contract was verified, and `test_3` is currently RED-capable
against shipped code. Stamp after the fork-steer defect is dispositioned — either fixed, or
explicitly accepted with the pin adjusted for the right reason rather than a convenient one.

---

# CORRECTION — 2026-08-09, appended by `w49-fs`

**Appended, not merged.** Everything above stands as written on 2026-08-08 and is left byte-for-byte
intact, including the two claims this note corrects. This repo's doctrine is that *a dated record of
an act is corrected by appending* — rewriting one to fix a lookup problem falsifies the lesson to
save the index. Read §4b and §4d first; then read this.

Both corrections make the report's **conclusion stronger**, not weaker. The defect it found is real,
it was root-caused in wave 49 (`docs/lanes/w49-fs.md` §2), and its §9 recommendation — do not stamp
`pin-pass.json` yet — was and remains correct.

## C1. §4b's observation is sound; the inference drawn from it is only half of what it supports

§4b reports, correctly and by direct transcript reading:

> `STEER-OK` appears 6× in the transcript and **only** in `custom-title` / `agent-name` metadata
> (`fleet|pin-w1|Reply with exactly: STEER-OK` — that is the roster *name*, from `dispatch_bg`'s
> `hint=`). It appears in **no user message content**.

That is offered as proof the steer was absent from the user message, and for that it is conclusive.
**It is equally proof of a second thing the report did not draw, and the second thing is about the
pin rather than about the defect:** a fork that answered `STEER-OK` need not have read anything at
all. Same observation, two readings; the report took only the one that supported its conclusion.

The mechanism, measured (`bin/fleet.py` at `bcc6522`): `_cmd_send_native:7614` passes
`hint=message[:NATIVE_NAME_HINT_MAX]` to `dispatch_bg`, which renders the forked session's roster
name as `cat|name|hint` (`:13132`). `NATIVE_NAME_HINT_MAX` is `40`; step 3 steered with
`Reply with exactly: STEER-OK`, **28 characters**. So the pin handed its own success token to the
session under test *as that session's title*, on a channel that has nothing to do with whether the
steer was delivered.

**Consequence: `test_3_pin_fork_steer` could pass while the path it tests was broken.** Every GREEN
it produced across five waves is weaker evidence than it looks — the failures it produced are
unaffected, which is why the RED in §4a remains sound evidence and the conclusion above stands.

The name §4b quotes is reproducible without spending anything, and is exactly what wave 49's guard
now refuses to run against:

```
$ py -3.13 -c "... _assert_steer_token_has_one_way_in('pin-w1', 'Reply with exactly: STEER-OK', 'STEER-OK')"
CONFOUNDED PIN -- refusing to run a delivery test that cannot fail. The step-3 success token
'STEER-OK' is inside the roster name the fork is dispatched under
('fleet|pin-w1|Reply with exactly: STEER-OK') ...
```

Fixed on `w49/fs`: the token is now per-run unique and positioned past the hint window by
construction, `test_3` refuses to spend before proving the token has one way in, and
`tests/test_fork_steer_delivery.py::test_the_pin_tiers_steer_token_cannot_reach_the_session_name`
holds that property in the unit tier so the next person to shorten the message reds immediately
instead of at the next expensive live run.

## C2. §4d's "1 failure in 5 samples" is not a rate, and the rate is ~20× lower

§4d tabulates 5 samples, 1 failure, and says *"1 failure in 5 samples at 2.1.226. Small-N; treat
~20% as an order of magnitude, not a measurement."* The hedge was right and was not enough: the
figure travelled two waves as though it were a measurement, and §9's "~1 run in 5" restates it
without the hedge.

Wave 49 drove the failure deliberately, on both interpreters, and measured:

| source | failures / samples | point estimate | 95% CI (Clopper–Pearson) |
|---|---|---|---|
| `w48-pin` §4d | 1 / 5 | 20% | **0.51% – 71.64%** |
| `w49-fs` §3c | 1 / 92 | **1.09%** | **0.03% – 5.91%** |

The intervals overlap, so wave 48's samples are not contradicted — they were never capable of
contradicting anything. **An interval spanning 0.5% to 72% is a number that says almost nothing**,
and that is the correction worth keeping, more than the point estimate that replaces it.

The lesson wave 49 drew from the same data is the one that explains how five waves of green pin runs
missed a defect that is **unconditional in the code**: `dispatch_bg`'s fork-steer turn is
byte-identical to one the resumed session already answered on *every* fork-steer, without exception —
what is ~1% is only the *outcome*, i.e. how often the model takes the cheap reading. A defect that is
certain in the code and rare in the outcome is invisible to single-run pins, and the fix belongs in
the code, not in the sampling.

## What this does NOT change

- §4a's RED, §4c's mechanism, and §4e's "the vendor did not move" — all confirmed independently by
  wave 49 (`docs/lanes/w49-fs.md` §2, §3).
- §4f's three recommendations, all of which were right. Item 1's *"consider making the pin's steer
  token unique per run"* was the correct instinct; note that uniqueness **alone** would not have been
  enough, since a unique token under 40 characters still lands in the roster name.
- §8's `FLEET_HOME` fence audit and §9's stamping recommendation.

— `w49-fs`, 2026-08-09, on branch `w49/fs`
