# Lane report — `w62-codex`: can `codex` be a fleet worker substrate?

**Lane:** research/design. Worktree `/home/altai/proga/fleet-w62-codex`, branch
`w62/codex-substrate`, based at `374929b`. Mode bypass. **BUILD NOTHING** — nothing under `bin/` or
`tests/` was touched; `git status` shows two new docs and nothing else.
**Design doc:** `docs/superpowers/specs/2026-09-10-codex-worker-substrate-design.md`.
**Journal:** `state/journals/w62-codex.md` (gitignored runtime dir).
**Date:** 2026-09-10. **Host:** the operator's own box. **codex-cli 0.153.4.**

Every line below is labelled **MEASURED** (I ran it, this host, today) or **BELIEVED** (reasoned,
not driven). Section 6 is **WHERE THIS BRIEF WAS WRONG**. Section 7 is **draft gate text — I do not
file gates.**

---

## 1. Lead finding: the stall was stdin, and the brief's hypothesis about it is refuted

The amendment predicted, BELIEVED-high, that *"a headless `codex exec` without an approval bypass
blocks on codex's own interactive approval with no TTY to answer it"* and asked me to lead with it
if it held.

**It does not hold. MEASURED, two ways:**

- **MEASURED** — `codex exec` under `codex`'s own default settings, no `-s`, no bypass, stdin from
  `/dev/null`: **rc=0**, completed, emitted a full event stream. It never asked for approval.
- **MEASURED** — the rollout for that run records `turn_context.approval_policy: "never"`. Codex
  `exec` is non-interactive by design; there is no approval prompt to hang on.

**What actually blocks is stdin. MEASURED:** `codex exec` reads stdin to EOF *even when a PROMPT
argument is supplied*, announcing it on **stdout** as `Reading additional input from stdin...`.
Given a fifo held open by a sleeping writer:

- **MEASURED** — `rc=124` (timeout at 25 s), elapsed 25 027 ms, 39 bytes of output, **no
  `thread.started` event, no session file on disk.** It dies before it has an identity.
- **MEASURED** — the same fifo against `codex exec resume <id>`: **rc=0**, 8 790 ms, normal
  completion. **The two commands disagree.**

**BELIEVED (high):** that asymmetry is what froze my predecessor body for 25 minutes. Its shell's
stdin was not `/dev/null` and never closed. It also predicts a nasty build-time symptom — **spawn
hangs, respawn works** — which presents as an intermittent worker-specific wedge.

**Consequence for a build, MEASURED-grounded:** `stdin=DEVNULL` is a correctness requirement of the
spawn path, not hygiene. And because that non-JSON line lands *inside* a `--json` stream, any digest
parser must tolerate non-JSON lines rather than assume JSONL.

**The operator gate the amendment expected did not materialise in the form it expected.** The
`--full-auto`/bypass question is *not* a precondition for headless operation — headless works at
codex's default. The precondition that does exist is about *writing*, not approving, and it is
section 3.

---

## 2. Commands run, and where they ran

**SAFETY, MEASURED:** every codex invocation ran with cwd under
`/home/altai/.claude/jobs/630d729b/tmp/spike/{a,b,c,d}` — never in `/home/altai/proga/fleet`, never
in a worktree. Every one was wrapped in `timeout`, took stdin from `/dev/null` or a deliberate fifo,
and redirected output to a file. **`--dangerously-bypass-approvals-and-sandbox` was never used.
`codex login` / `codex logout` were never run. `~/.codex/config.toml` was never written by me.**

| # | command (elided) | cwd | rc | notes |
|---|---|---|---|---|
| 1 | `codex --version` | spike/ | 0 | `codex-cli 0.153.4` |
| 2 | `codex exec --help`, `codex help {exec,exec resume,queue,agents,resume,archive,delete,sandbox,fork}` | tmp/ | 0 | surface recon |
| 3 | `timeout 120 codex exec --json --skip-git-repo-check -C spike/a -o last-a.txt '<write hello.txt>'` | spike/a | 0 | **read-only default; wrote nothing; still exit 0** |
| 4 | `timeout 25 codex exec --json ... < <held fifo>` | spike/a | **124** | 25 027 ms, no thread id minted |
| 5 | `timeout 120 codex exec --json -s workspace-write -C spike/b -o last-b.txt '<write hello.txt>'` | spike/b | 0 | 18 543 ms; `hello.txt` == `SPIKE_OK` |
| 6 | `codex exec resume <b-id> --json -s ... -C ...` | spike/b | **2** | `error: unexpected argument '-s'` / `'-C'` |
| 7 | `codex exec resume <b-id> --json --skip-git-repo-check '<recall + write resumed.txt>'` | spike/b | 0 | 13 434 ms; context preserved; wrote |
| 8 | `codex exec resume <b-id> ... < <held fifo>` | spike/b | 0 | 8 790 ms — **does not block** |
| 9 | `codex queue --thread <b-id> --message QUEUED_PROBE_IDLE` | tmp/ | 0 | 806 ms |
| 10 | `codex exec resume <b-id> '<list every user message>'` | spike/b | 0 | queued message **delivered**, queue row gone |
| 11 | `codex exec --json -s workspace-write -C spike/c '<3× sleep 20>'` + `codex queue` at ~t+20 s | spike/c | 0 / 0 | **mid-turn: never seen by the running turn** |
| 12 | `codex exec resume <c-id> '<list every user message>'` | spike/c | 0 | the deferred message **is** in the transcript |
| 13 | `codex exec --json -s workspace-write -C spike/d '<3× sleep 20>'`, then `SIGTERM` at t+25 s | spike/d | — | rollout ends mid-record; no orphan process |
| 14 | `codex agents` | tmp/ | **1** | `ERROR: stdin is not a terminal`, 114 ms |
| 15 | `codex exec --json -s workspace-write -C spike/b '<curl example.com>'` | spike/b | 0 | `curl: (6) Could not resolve host` |
| 16 | `codex sandbox -C spike/b -- …` | tmp/ | **2** | requires `--permission-profile <NAME>` — **not pursued** |
| 17 | `codex archive <a-id>` | tmp/ | 0 | rollout moved to `~/.codex/archived_sessions/` |
| 18 | `codex exec resume <a-id>` (archived) | spike/a | **1** | error names `codex unarchive` |
| 19 | `codex exec resume 00000000-…` / `codex queue --thread 00000000-…` | spike/a | **1** / **1** | clean nonzero on a missing thread |

Read-only inspection, no codex invocation: `~/.codex/` listing, the two rollout `.jsonl` files,
`queue_1.sqlite` opened `mode=ro`, `pgrep`, `free -m`.

**One thing I did not do and should flag:** `~/.codex/config.toml`'s mtime moved during my runs
(**MEASURED**: 12:52 on 2026-09-10). I did not write it; codex itself touched it. I did not read its
prior content, so I **cannot** claim it is byte-identical — only that no command of mine wrote it.

---

## 3. The precondition that does exist: the sandbox, chosen once, at spawn

- **MEASURED** — `codex exec` with no `-s` runs under `sandbox_policy: read-only`. Spike A's model
  attempted no command at all, replied *"Couldn't create hello.txt: the filesystem is read-only"*,
  and the process **exited 0**. A codex worker that cannot do any work reports success.
- **MEASURED** — `-s workspace-write` writes: `hello.txt` == `SPIKE_OK`, rc=0, 18 543 ms. The
  rollout's `world_state` shows write access to the workspace root, `/tmp` and `$TMPDIR`, read
  access to `:root`.
- **MEASURED** — `codex exec resume` **rejects both `-s` and `-C`** with `error: unexpected
  argument`. Sandbox mode and cwd are fixed for the life of a thread. A resumed thread **did** write
  (command #7), so the mode is inherited, not reset.
- **MEASURED** — under `workspace-write` the sandbox has **no network**: `curl -sS -m 8
  https://example.com` returned `curl: (6) Could not resolve host`, exit 6; the rollout's
  `sandbox_policy` reads `network_access: false`.
- **NOT MEASURED, by the brief's fence** — `danger-full-access`, `--approve-for-me`, and the bypass
  flag. `codex sandbox` could not be exercised at all: it requires `--permission-profile <NAME>`,
  and a named profile means writing `~/.codex/config.toml`, which the brief forbids. **I skipped the
  question rather than answering it badly.**

**So the operator's real choice is not "may codex run unsandboxed" in the abstract — it is: a
sandboxed codex worker cannot reach the network, therefore cannot `git push`, `gh`, or fetch a
dependency.** That is gate B.

---

## 4. The three name-shaped divergences

**`codex queue` is a next-turn inbox, not a steer.**
- **MEASURED, idle:** queued (rc=0, 806 ms) into `~/.codex/queue_1.sqlite`, table `queued_items`
  keyed by `thread_id` with a `queue_order` column; **delivered** at the next `exec resume`, ordered
  before the new prompt; row then deleted.
- **MEASURED, mid-turn:** queued ~20 s into a ~65 s turn. `codex queue` returned **rc=0** and printed
  `Queued message <id> for thread <id>.` The running turn **never saw it** — the model was asked to
  report any additional instruction received while working and answered `NONE`; the file it asked
  for was never created; the queue row was gone by turn end.
- **MEASURED, next turn:** the text **is** in the thread, and the model listed it verbatim on the
  following turn.
- **The failure mode this predicts:** `fleet send` at a busy codex worker → green exit, unchanged
  worker. Design doc §2.1 routes around it by keeping fleet's own mailbox.

**`codex agents` is not a roster.** **MEASURED** — `ERROR: stdin is not a terminal`, rc=1, 114 ms,
no `--json`. Fleet's roster is load-bearing for invariant 7 and for the keeper's supervisor rule;
there is **no measured headless substitute**. `codex app-server` / `codex exec-server` are
**BELIEVED** to be the likely place one exists; neither was driven.

**`exec` and `exec resume` disagree about stdin** — §1.

---

## 5. Identity, tokens, limits, tombstones

- **MEASURED** — thread id `01a08a4d-9c38-77a2-b138-bb147fec4948`: version nibble **7**, a UUIDv7.
  Claude sids are UUIDv4. **BELIEVED (and explicitly rejected as a mechanism in the design doc):**
  that the version difference is a safe namespace discriminator. It is an observation about two
  generators, not a contract.
- **MEASURED** — the thread id is **stable across `exec resume`**. Codex needs no `retired_sids`
  analogue; `turn_id` is what rotates.
- **MEASURED** — `session_meta` carries `session_id`/`id`/`cwd`/`originator: codex_exec`/`source:
  exec`/`cli_version`/`model_provider`.
- **MEASURED** — `--json`'s `turn.completed.usage` carries five token fields. **A token source for
  `--token-ceiling` exists.** There is no USD figure anywhere, which matches fleet's
  tokens-not-dollars doctrine.
- **MEASURED, and the sharpest gotcha in the whole spike** — `rate_limits` (with `used_percent`,
  `window_minutes`, `resets_at`, `plan_type`, **`rate_limit_reached_type`**, `spend_control_reached`)
  appears **only in the on-disk rollout**, never on stdout. `grep -c rate_limits` over four captured
  `--json` streams: **0, 0, 0, 0**. The `--json` stream is a lossy projection.
- **MEASURED** — `rate_limit_reached_type` and `spend_control_reached` were `null` in every capture;
  no limit was hit. **BELIEVED:** non-null means limited. The populated shape is **not measured** and
  a build must not hard-code an expected value.
- **The honest answer to the standing-goal-2 question:** a **codex worker is NOT limit-invulnerable**
  — measured plan `pro`, a 10 080-minute window at 17.0% used. What differs from claude is that the
  signal is a **structured field with an epoch `resets_at`**, not a synthetic 429 record fleet has to
  grep for and a local time it has to parse. Legible, not absent.
- **MEASURED** — SIGTERM to a running `codex exec`: rollout ends mid `custom_tool_call`, no
  `task_complete`, no `turn.completed`, no orphan process 3 s later. **There is no Stop hook.** Fleet
  must author every outcome record itself.
- **MEASURED** — `-o/--output-last-message` writes the final message to a fleet-chosen path; a clean
  turn's rollout `task_complete` carries `last_agent_message`, `duration_ms`,
  `time_to_first_token_ms`. `--output-schema` exists (not driven).
- **MEASURED** — no resident codex daemon between runs; `~/.codex/ipc/ipc.sock` present but unheld.
  Invariant 1 survives.
- **NOT MEASURED, and it matters on this host:** N concurrent codex workers against one
  `~/.codex/*.sqlite` set. Every run was a single process. Nothing here says three codex workers
  coexist on an 8 GB box.

---

## 6. WHERE THIS BRIEF WAS WRONG

**Four items. Two are corrections of the brief, one is a correction of the brief's own correction,
and one is mine.**

**6.1 — The amendment's headline hypothesis is refuted.** It said, BELIEVED-high, that a headless
`codex exec` blocks on codex's own interactive approval, and that if it held it would be *"the
single most important result of this spike"*, making the sandbox gate a precondition. **MEASURED:
`codex exec` runs headlessly at codex's defaults, rc=0, and its rollout records
`approval_policy: "never"`. The stall was stdin.** The instruction that came with the hypothesis
(`timeout` + `< /dev/null` + redirect to a file) was nonetheless exactly right, and is what let me
separate `124` from slow on the first try — the prescription was correct while the diagnosis was
not.

**6.2 — The brief's own correction table was right to call the ask pessimistic, and then
over-corrected on one row.** The table says *"`codex queue` exists … it may make the honest
semantics much better than 'none'"*. **MEASURED: for the mid-turn case the honest semantics really
are "none"** — rc=0, acknowledged, never delivered to the running turn. The ask's original framing
(*"steer mid-turn has no hook boundary in codex"*) was closer to the measured truth than the
correction was. The correction is right about the *idle* case, where `queue` is a real and durable
mailbox. **This is exactly the "near-match is the trap" failure the brief warned about, and the
brief walked into it.**

**6.3 — `codex agents` is not a `claude agents` analogue in any way fleet can use.** The table lists
it as one. **MEASURED: rc=1, `ERROR: stdin is not a terminal`, no `--json`.** It is a TUI. This is
the most consequential gap in the mapping and it is the reason gate C exists.

**6.4 — The providers.md / `feat/worker-providers` tension: both summaries are true and about
different paths, and I can name them.** MEASURED from `docs/longcat-fleet-usage.md`:
- **spike-NEGATIVE** = §2b — one *shared* `claude --bg` daemon rebooted under proxy env. Dead as
  written: the daemon is auto-respawned by the Anthropic monarch in under a second.
- **VERIFIED end-to-end** = §2a — a separate `CLAUDE_CONFIG_DIR` (`~/.claude-longcat`) giving an
  *isolated* daemon namespace. That is what tip commit `92fa85e` refers to.
I inherited neither summary; both are re-derived from the doc. **MEASURED and worth saying: neither
applies to codex.** `codex exec` resolves auth from `CODEX_HOME`/`~/.codex/auth.json` in its own
process env, and there is no shared resident daemon to inherit a backend from — the entire
env-delivery problem that killed providers.md §4 does not exist on this substrate.

**6.5 — Mine.** My first attempt to measure the stdin block was `( sleep 300 | timeout 25 codex … )`,
which waits on `sleep` as well as on codex and would have measured 300 s regardless of what codex
did. It was killed and redone with a fifo. **A control must have the shape of the thing it
controls**; the pipeline shape did not.

---

## 7. Draft gates — DRAFTED, NOT FILED

`docs/OPERATOR-GATES.md` format: one line, question-form, ending in `?`; grounds on continuation
lines. **I do not tick boxes and I do not file these.** Four.

- [ ] **A codex worker substrate needs a shape — a `Substrate` seam in `bin/fleet.py`, or the divergences absorbed at the handful of call sites that actually differ?**
  *(Drafted 2026-09-10 by lane `w62-codex`; evidence `docs/lanes/w62-codex.md`, design
  `docs/superpowers/specs/2026-09-10-codex-worker-substrate-design.md` §7(8).)* **The reason this is
  a gate and not an implementation choice:** invariant 8's own history argues against the reflex. The
  platform adapter reached cross-platform parity on 2026-07-27 by **deleting the seam** — the
  autoclean scheduling methods died on both backends rather than being ported, and SPEC §16(8) records
  that *"the cheapest way to reach cross-platform parity on a seam turned out to be not needing the
  seam."* MEASURED, the codex divergences are few and concentrated: spawn argv, the digest source,
  the outcome record, and `send`'s routing. A seam is the tidier design; four call sites may be the
  cheaper truth. **A seam built before the divergence list is known is a seam built against unknown
  requirements**, which is the stated reason providers.md is parked.

- [ ] **May a codex worker run unsandboxed — and if the answer is no, is a worker with no network access useful enough to build?**
  *(Drafted 2026-09-10 by lane `w62-codex`.)* **These are one question, not two, and that is the
  finding.** MEASURED: `codex exec` defaults to a **read-only** filesystem and a worker that cannot
  write **still exits 0**; `-s workspace-write` writes but has `network_access: false`, measured as
  `curl: (6) Could not resolve host`. MEASURED: `codex exec resume` accepts neither `-s` nor `-C`, so
  **the choice is made once, at spawn, and cannot be revised for the life of the thread** — the only
  escape hatch on a resume is `--dangerously-bypass-approvals-and-sandbox`. **Reading A
  (`workspace-write`, recommended for v1):** codex workers do offline, in-tree work — edit, test, and
  hand the branch to a claude worker or the operator to push. No `git push`, no `gh`, no cold-cache
  `uv`. **Reading B (`danger-full-access`):** a full worker, no sandbox, on the operator's own
  machine. **NOT MEASURED** — this lane did not run it, by fence, so B's viability is unproven.
  **What the lane will not do is present B as merely a preference:** A is measured to work, B is not
  measured at all.

- [ ] **Codex has no headless roster — accept inferred liveness for codex workers, or block the build until `codex app-server` has been measured?**
  *(Drafted 2026-09-10 by lane `w62-codex`.)* MEASURED: `codex agents` refuses without a TTY
  (`ERROR: stdin is not a terminal`, rc=1) and has no `--json`. **What that costs, specifically:**
  invariant 7's one-live-session-per-name is enforced through respawn's roster-verified stop, and
  `_doctor_check_claude_agents` is a roster check — for codex workers both degrade to child-PID and
  rollout-mtime inference. This wave's own keeper gate turned on a roster row's `status` field, so
  the fleet has just finished learning what a roster is worth. **Reading A (accept):** build it, and
  make `doctor` carry an explicit row saying codex workers have no independent liveness oracle,
  rather than omitting the check and looking green. **Reading B (block):** measure `codex app-server`
  / `codex exec-server` first — both exist, both are marked experimental, **neither was driven by
  this lane**, and they are the most likely place a programmatic roster lives. B is one cheap spike,
  and it is the highest-value unmeasured thing on the list.

- [ ] **May the supervisor ever be a codex session — the ask says no for v1, and the measured answer is that it is not merely unwise but currently unbuildable, so is that ruling permanent or revisitable behind gate C?**
  *(Drafted 2026-09-10 by lane `w62-codex`; the ask recommends NO for v1 and this lane agrees, on
  measured grounds.)* **The case, not taste:** the supervisor's duty cycle is claim, heartbeat,
  handoff, and each is a *turn*. Three measured absences remove the mechanisms that cycle is built
  from. (i) **No roster** — the supervisor could not verify its own workers, and the keeper's
  `rule_supervisor_dead` joins on a roster row, so a codex supervisor would be invisible to the exact
  rule this wave is already amending. (ii) **No interrupt** — codex exposes no end-the-turn
  mechanism, so a wedged codex supervisor could only be killed, and `sup-handoff-abort`'s "stop the
  limbo successor" has no gentle form. (iii) **No hooks** — there is no Stop hook, so no Stop-hook
  outcome, and the claim's heartbeat freshness derives from turns ending. **The refutation, if
  someone wants to make it, is specific:** show that `codex app-server` supplies a roster, a turn
  boundary, and a stop — which is gate C. **Until then the honest phrasing is not "we prefer claude"
  but "three of the supervisor's load-bearing mechanisms are measured absent."**

---

## 8. Suite floor — prediction, then measurement

**PREDICTION, written before measuring** (and recorded in the journal before the docs were
committed): `_HISTORICAL_PREFIXES` in `tests/test_doc_claims.py` contains **both** `docs/lanes/` and
`docs/superpowers/`, so `CHECK_COUNT_DOCS = current_tree_docs()` excludes both new files;
`tests/test_receipts.py` globs `SPEC_DIR = REPO/docs/specs` only, and `docs/superpowers/specs/` is
not under it. **Predicted movement: 0. Predicted floor: 4965.**

**MEASUREMENT:** see §8.1, taken from a separate `git clone --no-local` on both floors, never in the
main checkout.

<!-- MEASUREMENT-PENDING -->
