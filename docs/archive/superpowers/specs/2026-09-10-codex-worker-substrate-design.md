# Design — `codex` as a second fleet worker substrate

**Status:** DESIGN + SPIKE. **UNBUILT and not build-eligible.** Nothing in this document
exists in `bin/fleet.py`; no flag, no test, no registry field was added by the lane that wrote it.
**Author:** lane `w62-codex`, 2026-09-10, branch `w62/codex-substrate`.
**Evidence:** `docs/lanes/w62-codex.md` — every claim below is labelled there MEASURED or BELIEVED,
with the full command enumeration and where each number came from.
**Operator ask, verbatim:** *"I want fleet to also be able to call codex cli as its workers"*
(Telegram, 2026-09-10).

**Relationship to `docs/specs/providers.md`:** none, and deliberately so. That spec is **PARKED**
(operator gate, 2026-07-27) and its §"Scope" line 15 puts this work explicitly outside itself —
*"Out: non-Claude-Code worker CLIs (Codex etc. — that's Phase 6 'Reach')"*. **This is a NEW line, not
an un-park.** providers.md swaps what sits *behind* the `claude` CLI; this swaps the CLI. Nothing
here re-litigates it and nothing here depends on it being unparked.

**Note on fenced blocks:** this file lives under `docs/superpowers/specs/`, which
`tests/test_receipts.py` does **not** glob (`SPEC_DIR = REPO/docs/specs`). The blocks below are
quoted transcript excerpts, not harness-verified receipts, and are not marked `# at <sha>`. If any
of this is ever promoted into `docs/specs/**`, every block has to be re-taken as a real receipt
first.

---

## 1. The answer, up front

**Codex can be a fleet worker substrate, and the structural match is genuinely close — but only
behind three preconditions, each of which is an operator decision rather than an implementation
detail.** Two of the three were invisible from the CLI's `--help` and only appeared when the thing
was actually run.

1. **stdin must be closed at spawn.** `codex exec` reads stdin to EOF *even when a prompt argument
   is supplied*. Handed a never-closing stdin — which is exactly what a detached `Popen` or an
   inherited pipe gives it — it blocks forever, before it mints a thread id, so there is nothing for
   fleet to peek at, wait on, or kill by id. This is not a preference; a substrate adapter that
   forgets `stdin=DEVNULL` produces a worker that cannot exist.
2. **the sandbox must be chosen at spawn, because it cannot be chosen later.** `codex exec` defaults
   to a **read-only** filesystem, and a codex worker that cannot write **still exits 0** — it
   reports the failure in prose and succeeds. `codex exec resume` accepts neither `--sandbox` nor
   `--cd`, so the setting is fixed for the life of the thread. And `workspace-write` disables
   network access, so a codex worker at that setting cannot `git push`, cannot use `gh`, and cannot
   fetch a dependency.
3. **a codex worker is NOT limit-invulnerable, and fleet must write its own tombstones.** There is
   no Stop hook. A killed or crashed turn leaves a rollout that simply stops mid-record.

Against those: codex's identity is *better* behaved than claude's for fleet's purposes (a stable
UUIDv7 that does not rotate on resume), and its limit signal is *structured and explicit* where
claude's is a synthetic 429 that fleet has to grep transcripts for.

**The recommended v1 shape is narrow on purpose:** codex workers are opt-in per spawn, sandboxed,
network-less, single-writer-registered under a namespace-qualified id, and **may not be the
supervisor**. §9 argues that last point rather than assuming it.

---

## 2. What the near-match actually is, and where it diverges

The brief's hypothesis was that codex's surface maps 1:1 onto fleet's model — `agents`/roster,
`exec`, `resume`, `queue`/`send`, `archive`, `delete`, a local daemon. Tested, the shape holds and
**three of the analogues carry different semantics under the same name.** Those three are where a
built version would fail silently, so they lead.

### 2.1 `codex queue` is a next-turn inbox, not a mid-turn steer

`codex queue --thread <uuid> --message <text>` looks like `fleet send`. Driven both ways:

- **against an idle thread:** the message is written to `~/.codex/queue_1.sqlite`
  (`queued_items`, keyed by `thread_id`, with a `queue_order` column and a
  `queued_thread_revisions` counter), and is delivered at the **next** `codex exec resume`, ordered
  *before* the new prompt, after which the row is deleted. This is a durable, ordered, at-most-once
  mailbox — structurally the same object as fleet's own atomic single-file mailbox (invariant 3).
- **against a thread that is mid-turn:** `codex queue` returns **rc=0** and prints
  `Queued message <id> for thread <id>.` — and **the running turn never sees it.** The model was
  asked to report any additional instructions it received while working and answered `NONE`; the
  file the queued message asked for was never created; the queue row was already gone by turn end.
  The text *did* reach the thread transcript, and became visible on the **next** turn.

So mid-turn steering is **accepted, acknowledged with a success exit code, and silently deferred.**
That is the single most dangerous divergence in the whole surface: a manager that types
`fleet send` at a busy codex worker gets a green result and a worker that does not change course.

**Design consequence.** `fleet send` against a codex worker must NOT be routed to `codex queue`
naively. Two honest options, and the design picks (a):

- **(a) RECOMMENDED — fleet keeps its own mailbox for codex workers too.** `send` writes fleet's
  mailbox exactly as today; the adapter composes pending mail into the prompt of the next
  `exec resume`, which is what fleet's respawn/journal-injection path already does (invariant 4).
  `codex queue` is then not used at all for steering, and the divergence never reaches an operator.
  Cost: one more place mail can sit.
- **(b) route to `codex queue` and re-label the verb.** Cheaper, but it puts the deferral inside a
  substrate fleet cannot instrument, and fleet loses the ability to *see* pending mail — which
  `_doctor_check_mailboxes` and the Stop-hook ceiling interplay both depend on.

Either way, **`fleet interrupt` has no codex analogue at all.** Codex exposes no way to end a turn
early; the only mechanism is signalling the process. §6 treats that as a `kill`, not an `interrupt`.

### 2.2 `codex agents` cannot be used by fleet

`codex agents` is described as *"Browse all agent sessions on the shared local app-server daemon"*
and reads like `claude agents`. Run without a TTY it refuses outright:

```
ERROR: stdin is not a terminal
```

rc=1, 114 ms. It is a TUI, not a roster query, and it has no `--json`.

**This removes fleet's roster from the codex side entirely**, and the roster is load-bearing:
invariant 7's one-live-session-per-name is enforced through a roster-verified stop in `respawn`;
`_doctor_check_claude_agents` is a roster check; the wave-61 keeper gate turns on a roster row's
`status` field. **There is no measured headless substitute.** What exists instead is weaker and
indirect: rollout files under `~/.codex/sessions/<Y>/<M>/<D>/`, whose mtime moves while a turn
runs, plus the fleet-owned child PID. Both are inference, not a roster.

BELIEVED, and the first thing a build should measure: `codex app-server` / `codex exec-server`
(both marked experimental) may expose the same data over a programmatic channel. If they do, the
roster gap closes; if they do not, **fleet must accept that codex workers have no independent
liveness oracle** and say so in `doctor` rather than pretending.

### 2.3 `exec` and `exec resume` disagree about stdin

Fresh `codex exec` with a prompt argument still reads stdin, announcing it on **stdout**:

```
Reading additional input from stdin...
```

Given a fifo held open by a sleeping writer, it produced `rc=124` after 25 027 ms, 39 bytes of
output, **no `thread.started` event and no session file on disk.** `codex exec resume`, under the
identical fifo, completed normally (`rc=0`, 8 790 ms).

Two commands in one family, one blocks and one does not. In fleet terms: **spawn hangs, respawn
works** — which presents as an intermittent, worker-specific wedge and would cost a debugging wave.
It also means that non-JSON line lands in the middle of a `--json` stream, so any digest parser must
tolerate non-JSON lines rather than assuming JSONL.

This is also the corrected explanation for the 25-minute stall that ended this lane's previous body.
The amendment's hypothesis — that a headless `codex exec` blocks on codex's own interactive approval
with no TTY to answer it — is **refuted**: the rollout's `turn_context` records
`"approval_policy": "never"` for `codex exec`. Codex never asked. The predecessor's shell simply
never closed its stdin.

---

## 3. Permission modes — the mapping the brief asked for

MEASURED, from `codex exec --help` and from driving each:

| codex setting | what it does | headless? | writes? | network? |
|---|---|---|---|---|
| *(default, no flag)* | `sandbox_policy = read-only` | **yes**, rc=0 | **no** — and still exits 0 | not measured |
| `-s workspace-write` | write under cwd + `/tmp` + `$TMPDIR`; read `:root` | **yes**, rc=0 | yes | **no** — `curl: (6) Could not resolve host` |
| `-s danger-full-access` | no sandbox | BELIEVED yes | yes | BELIEVED yes | 
| `--approve-for-me` | routes approvals through auto-review under workspace-write | not measured | — | — |
| `--dangerously-bypass-approvals-and-sandbox` | no sandbox, no prompts | **not run** — forbidden by the brief | — | — |
| `codex sandbox` | run a command under codex's sandbox | **could not be exercised** | — | — |

Two rows need their limits stated rather than glossed:

- **`codex sandbox` is untested and the reason is a fence, not an oversight.** It requires
  `--permission-profile <NAME>`, and a named profile is a `~/.codex/config.toml` entry. The brief
  forbids writing that file, so the question was skipped rather than answered badly.
- **`danger-full-access` is BELIEVED, not measured.** It was not run: this is the operator's own
  host, and the point of the spike was to find out whether a *sandboxed* codex worker is viable.
  It is — which is what makes the "may codex workers run unsandboxed" gate a real choice rather
  than a foregone one.

**The finding that matters most here is the read-only default.** Spike A ran with no `-s` flag, a
trivial write task, and produced:

```
{"type":"item.completed","item":{"type":"agent_message","text":"Couldn't create hello.txt: the filesystem is read-only."}}
{"type":"turn.completed","usage":{...}}
```

`rc=0`. No command was even attempted — the model read its own permission profile and gave up. **A
worker that cannot do any work exits successfully.** Fleet's outcome discriminator would record that
as a clean turn. Under `-s workspace-write` the same prompt wrote the file and answered `DONE`.

**Design consequence.** The substrate adapter must pass an explicit `-s` on every spawn and must
never rely on the default. Because `exec resume` refuses `-s`, the value is **immutable for the life
of the thread** — the same shape as fleet's `cwd` (invariant 5), and it should be recorded in the
registry with the same immutability, changeable only by `respawn`.

**And the network consequence is not a footnote.** A `workspace-write` codex worker cannot reach the
network. Half of what fleet workers do — `git push`, `gh pr create`, `uv run --with pytest` on a
cold cache — is unavailable. Either codex workers are for offline, in-tree work only (recommended
for v1, and honest), or the sandbox question and the network question are the *same* gate.

---

## 4. Identity and the sid union — invariant 6 and 7

MEASURED:

- `codex exec` mints a `thread_id` on `thread.started`, e.g.
  `01a08a4d-9c38-77a2-b138-bb147fec4948`. The version nibble is **7** — a UUIDv7. Claude sids are
  UUIDv4. The two namespaces are therefore **distinguishable by inspection**, without a prefix.
- The rollout's `session_meta` carries `session_id` == `id` == that same value, plus `cwd`,
  `originator: codex_exec`, `source: exec`, `cli_version`, and `model_provider`.
- **The id is STABLE across `exec resume`** — the resumed run reported the same `thread_id`. A
  separate `turn_id` (also UUIDv7) rotates per turn.

That last point is the good news, and it is worth stating plainly because the brief expected pain
here. `_record_sids(rec)` is `session_id ∪ retired_sids`, and the union exists because a **claude**
sid rotates: fork-steer and respawn push the prior sid into `retired_sids` eagerly while
`INCARNATION.session_id` restamps only on the next validated write, and matching the bare
`session_id` fails open across that window (ND4a). **A codex thread id does not rotate at all**, so a
codex record's union is a one-element set and the whole rotation hazard is absent.

**But the collision question the brief raised is real and does not go away.** The registry is a
single-writer flat map (invariant 6) and every ownership, claim, band-ceiling and archive-exemption
path keys on an id drawn from one namespace. Two namespaces sharing one key space means a collision
becomes a **design** question rather than the accident this wave just shipped a fix for. Three
options, and the design picks (a):

- **(a) RECOMMENDED — namespace-qualify at the boundary.** The registry stores
  `substrate: "codex"` alongside a `session_id` written as `codex:<uuid>`. `_record_sids` is
  unchanged (it is namespace-agnostic string set arithmetic); what changes is that a claude sid can
  never equal a codex sid by construction, so no comparison anywhere in the ownership machinery can
  cross namespaces. Cost: every place that hands a sid to `claude` must strip or refuse the prefix,
  and there are many — this is the bulk of the build.
- **(b) rely on the UUID version nibble.** Free, and MEASURED true today. Rejected: it is an
  observation about two CLIs' current id generators, not a contract either one publishes. A future
  claude that emits UUIDv7 would silently collapse the namespaces, and the failure would be a
  cross-namespace ownership match — the worst possible place for a silent failure.
- **(c) a second registry keyed separately.** Rejected outright: it breaks invariant 9
  (one-state-many-views) and invariant 6's single writer, and `status_snapshot()` would have to
  merge two sources of truth.

**Invariant status:** 6 **HOLDS** under (a) — one file, one writer, one lock. 7 (one live session per
name) **BENDS**: the pre-claim window and the fork-steer restamp still work, but the *roster-verified*
stop that respawn relies on has no codex equivalent (§2.2), so the enforcement degrades from
verified to inferred. **That degradation is a gate, not a design decision** (§9, gate C).

---

## 5. Cost, `--token-ceiling`, and the limit discriminator — G11 and standing goal 2

### 5.1 There is a token source, and it is not where you would look

`--token-ceiling` is fleet's only spend bound under native dispatch (contract G3 refuses
`--max-budget-usd` outright), and it needs a token count per turn. Codex has one.

**On stdout, from `--json`:** the `turn.completed` event carries
`usage: {input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
reasoning_output_tokens}` — turn-cumulative.

**In the on-disk rollout, and ONLY there:** `token_usage_record` entries carry the same fields
split three ways (`usage`, `turn_token_usage`, `thread_token_usage`) plus `response_id`, and
`event_msg`/`token_count` entries carry `model_context_window` **and a `rate_limits` object**:

```
"rate_limits": {"limit_id": "codex", "primary": {"used_percent": 17.0,
 "window_minutes": 10080, "resets_at": 1789546486}, "credits": {...},
 "plan_type": "pro", "spend_control_reached": null, "rate_limit_reached_type": null}
```

**`rate_limits` never appears in the `--json` stream.** Grepped across four separate captured
streams: 0 occurrences in each. The `--json` stdout stream is a **lossy projection** of the rollout,
and any build that treats it as the full event log will silently lose the limit signal.

**Design consequence.** The digest path for `peek`/`result`/ceiling accounting must read the
**rollout file**, not stdout — or read both, with stdout for liveness and the rollout for
accounting. `--token-ceiling` is implementable for codex; there is no USD figure, which matches
fleet's existing token-not-dollars doctrine rather than fighting it.

### 5.2 The limit discriminator — better than claude's, and still not free

Standing goal 2 and G11 exist because **claude's limit death is silent**: a 429 fires no Stop hook,
the roster still looks healthy, and the only sanctioned evidence is a synthetic assistant record
inside the transcript that `transcript_limit_scan` greps for under a deliberately narrow structured
gate (`isApiErrorMessage` AND (`apiErrorStatus == 429` OR `error == "rate_limit"`)).

**Codex's equivalent is structured and explicit.** `rate_limits.rate_limit_reached_type` and
`spend_control_reached` are dedicated fields, present on every `token_count` record, alongside a
`resets_at` epoch that needs no timezone parsing — which is the exact hazard `_parse_limit_signal`
and `_LIMIT_RESET_LOCAL_RE` were built to survive on the claude side. A codex park could compute its
horizon arithmetically instead of parsing prose.

**So, plainly, for the operator:** a **codex worker is NOT limit-invulnerable** — it runs against an
OpenAI plan with its own weekly window (measured: `window_minutes: 10080`, `used_percent: 17.0`,
`plan_type: "pro"`), and it can be limited exactly as a claude worker can. What changes is that
**the signal is legible rather than inferred**, which makes a codex `resume-limited` path cheaper
and more reliable than the one fleet already ships.

**Both fields read `null` in every capture taken.** No limit was hit during the spike, so the
*populated* shape of `rate_limit_reached_type` is **BELIEVED, not measured** — the field name and
its position are measured, its values are not. A build must not hard-code an expected value; it
should treat non-null as limited and log the value it saw.

### 5.3 Outcome and tombstone — invariant "tombstone obligation"

There is **no Stop hook.** Fleet's four worker hooks (invariant 2) are a claude-settings mechanism
and have no codex counterpart. What codex offers instead:

- a clean turn ends with `turn.completed` on stdout and `task_complete` in the rollout, the latter
  carrying `last_agent_message`, `started_at`, `completed_at`, `duration_ms`, `time_to_first_token_ms`;
- `-o/--output-last-message <FILE>` writes the final message to a path fleet chooses — the cleanest
  `fleet result` source available, and it needs no parsing at all;
- `--output-schema <FILE>` constrains the final response to a JSON Schema, which is a genuinely
  better `result` contract than anything the claude side has.

**A killed turn leaves nothing.** SIGTERM to a running `codex exec`: the rollout ends mid
`custom_tool_call`, with no `task_complete` and no `turn.completed`. No orphaned codex process was
observed three seconds later.

**Design consequence.** The discriminator is *absence* of `task_complete`, which is exactly the
shape of fleet's existing stop-no-hook tombstone problem — and fleet already has the answer:
**every fleet-initiated stop writes its own outcome record.** For codex that obligation widens from
"fleet-initiated stops" to "every turn", because the adapter is the process parent and is the only
thing that can observe the exit code at all. The invariant **HOLDS**, but only because fleet takes
on work the claude substrate gets from a hook.

---

## 6. The verb-by-verb contract

Invariant column cites `docs/SPEC.md` §16. **H** = holds, **B** = bends (works, with a stated loss),
**X** = breaks (needs an operator ruling before it can be built).

| fleet verb | codex mechanism | inv. | status and the catch |
|---|---|---|---|
| `spawn` | `codex exec --json -s <mode> -C <cwd> -o <file> <prompt>`, `stdin=DEVNULL`, detached | 1,5 | **H** — but `stdin=DEVNULL` is a correctness requirement, not hygiene (§2.3), and `-s` is immutable after this point (§3) |
| identity / sid | `thread.started.thread_id`, UUIDv7, stable across resume | 6,7 | **B** — needs `codex:` qualification (§4a); no rotation, so no `retired_sids` |
| `send` | fleet's own mailbox, composed into the next `exec resume` prompt | 3,4 | **B** — `codex queue` is NOT used: it accepts mid-turn mail with rc=0 and defers it silently (§2.1) |
| `peek` | tail the rollout at `~/.codex/sessions/<Y>/<M>/<D>/rollout-*-<id>.jsonl` | 9 | **H** — richer than the claude transcript; parser must tolerate the non-JSON stdin line |
| `result` | `-o/--output-last-message`, optionally `--output-schema` | 9 | **H** — strictly better than the claude path |
| `wait` | poll the child PID + rollout mtime | 7 | **B** — no roster to verify against (§2.2); liveness is inferred |
| `interrupt` | **none** | — | **X** — codex has no end-the-turn mechanism. Either `interrupt` refuses on codex workers with a clear message, or it silently becomes `kill`. **Refusing is the honest option**; the alternative violates invariant 15's own logic that `interrupt` ends a turn, not a worker |
| `kill` | SIGTERM the child; fleet writes the tombstone | tombstone | **B** — no `task_complete` is left behind, so fleet must author the outcome record itself (§5.3) |
| `respawn` | new `codex exec` with the journal composed in | 4,5 | **H** — journal-injection-at-respawn is substrate-independent; and respawn is the ONLY way to change `-s` or `cwd` |
| `resume-limited` | `codex exec resume <id>` after `rate_limits.resets_at` | — | **H**, and cheaper than the claude path: an epoch, not a parsed local time (§5.2) |
| `archive` / husks | `codex archive <uuid>` → `~/.codex/archived_sessions/`; `codex unarchive`; `codex delete` | 9 | **H** — a resume of an archived thread fails rc=1 with a message naming `codex unarchive` |
| permission modes | `-s read-only\|workspace-write\|danger-full-access` | 8 | **X** — the mode vocabulary does not map onto fleet's `--mode` values, and `workspace-write` costs the network (§3, gate B) |
| `--token-ceiling` | `token_usage_record.thread_token_usage` from the rollout | — | **H** — a real token source exists; `--max-budget-usd` stays refused as it already is |
| `doctor` rows | new checks: codex on PATH + version, `~/.codex/auth.json` present, orphaned rollouts, **and an explicit row saying codex workers have no roster** | 9 | **B** — `_doctor_check_claude_agents` has no codex counterpart and doctor must say so rather than omit it |
| `status` flags | `substrate` column; the `limited` flag from `rate_limit_reached_type` | 9 | **H** — one derivation, `status_snapshot()`, unchanged |
| outcome / limit discriminator | absence of `task_complete` = abnormal; non-null `rate_limit_reached_type` = limited | G11 | **B** — legible where claude's is silent, but fleet must author every outcome record (§5.3) |

---

## 7. The nine invariants, ledgered

1. **fleet-daemonless — HOLDS.** No resident codex process was found between runs; `~/.codex/ipc/ipc.sock`
   exists but was unheld. Codex's app-server is the substrate's, exactly as the native daemon is
   Anthropic's. Fleet still ships no resident process.
2. **exit-0 hooks — NOT APPLICABLE, and that is a loss.** Codex has no hook mechanism fleet can use.
   The four worker hooks simply do not exist on this substrate; §5.3 says what replaces them.
3. **atomic single-file mailbox — HOLDS** under §2.1(a). Codex ships its own sqlite mailbox; fleet
   does not use it for steering, precisely so there is one mailbox and not two.
4. **journal-injection-at-respawn — HOLDS.** Prompt composition is fleet-side and substrate-blind.
5. **cwd-scoped dispatch — HOLDS, and codex enforces it harder than claude does.** `-C` fixes the
   workspace root at spawn; `exec resume` refuses `-C`, so the cwd is immutable by construction, and
   the sandbox's write set is scoped to it.
6. **single-writer registry — HOLDS** under §4(a) namespace qualification.
7. **one live session per name — BENDS.** No headless roster (§2.2); respawn's roster-verified stop
   degrades to PID-and-mtime inference. This is the invariant most damaged by adding codex.
8. **platform-adapter-only OS branching — HOLDS as a rule, with a new obligation.** A codex substrate
   is a *substrate* seam, not an OS seam, and must not be built by scattering `if substrate ==` through
   `bin/fleet.py`. The 2026-07-17 portability directive's logic applies by analogy: a new seam lands
   with all its implementations or an explicit gap note. **Note the counter-lesson the adapter itself
   taught on 2026-07-27** — the cheapest way to reach parity on a seam turned out to be *not needing
   the seam*. Before building a substrate abstraction, check whether the divergences above can be
   absorbed at the two or three call sites that actually differ.
9. **one-state-many-views — HOLDS.** Registry + outcome store stay the state, `status_snapshot()` the
   one derivation. A `substrate` column is additive.

**Of the newer invariants:** never-demote-unknown **HOLDS** (nothing here auto-respawns);
G9 epoch freeze **HOLDS** (there is no codex roster to mass-demote from); tombstone obligation
**HOLDS but widens** (§5.3); no-daemon/jobs-file-access **BENDS** — fleet would read
`~/.codex/sessions/**` rollout files directly, which is the codex analogue of the daemon's session
storage. Reading rollouts is unavoidable (§5.1 puts the limit signal only there), so the rule should
be restated for codex as *read the session store, never write it* rather than quietly broken.
`~/.codex/queue_1.sqlite` and `~/.codex/config.toml` stay off-limits entirely.

**Invariant 10 (spec-bound work) is unaffected**: it is PRESCRIPTIVE and UNBUILT, and its
corollaries — verdicts from tamper-evident inputs, no author-supplied executable input — are
substrate-independent. A codex worker binding to a campaign spec would use the same `files` and
`pytest` criteria kinds; nothing in §17a needs a codex clause.

---

## 8. The flag

**Proposal: `fleet spawn <name> --substrate codex` (default `claude`).**

Justified against the existing vocabulary. `spawn` already carries `--mode`, `--model`, `--category`,
`--setting-sources`, `--token-ceiling`, `--context`, `--max-budget-usd`. Of these, `--model` is the
near-miss and should be rejected: a substrate is not a model, it is a different CLI with a different
identity space, a different permission vocabulary and no hooks, and overloading `--model` would make
`--model gpt-6` and `--model opus` look like peers when one of them changes the entire contract.
`--provider` is also rejected — it is providers.md's word for *what sits behind the claude CLI*, and
reusing it would collapse the very distinction §"Relationship" draws.

`--substrate` reads as what it is, has no existing meaning in the flag set, and leaves room for a
third. **It must be spawn-only and immutable per worker**, recorded in the registry as provenance —
the same rule `--provider` was going to have and the same rule `cwd` already has, for the same
reason: provenance must stay honest. Changing it means `respawn`.

**Keep claude the default.** Nothing about this design proposes otherwise.

---

## 9. What a build would need ruled first

Draft gate text — one line each, question-form, grounds on continuation lines — is in
**`docs/lanes/w62-codex.md` §"Draft gates"**. It is drafted there and not filed here: filing is the
supervisor's, and the `sup-decision` routing slot is single-occupancy. The four are, in short:

- **A — the abstraction shape.** A `Substrate` seam, or absorbed at the differing call sites? §7(8)
  argues the seam is not obviously the cheaper answer.
- **B — sandbox and network.** May codex workers run unsandboxed? And if not, is a network-less
  worker useful enough to build?
- **C — the roster gap.** Accept inferred liveness for codex workers, or block the build until
  `codex app-server` is measured?
- **D — may the supervisor ever be codex?** **The ask recommends NO for v1 and this lane agrees, on
  measured grounds rather than taste.** The supervisor's duty cycle is claim/heartbeat/handoff, and
  every one of those is a *turn*: `sup-heartbeat` refreshes a beat, `sup-handoff-complete` verifies a
  HANDSHAKE, and the claim machinery keys on a sid. Three measured facts make a codex supervisor
  unbuildable today rather than merely unwise: (i) **no roster** means the supervisor could not
  verify its own workers' liveness, and the keeper's `rule_supervisor_dead` joins on a roster row;
  (ii) **no interrupt** means a wedged supervisor could only be killed; (iii) **no hooks** means no
  Stop-hook outcome, which is what the claim's heartbeat freshness is derived from. A codex
  supervisor is not a harder version of the claude one; it is missing the three mechanisms the
  supervisor design is built out of. **Refuting this would require showing `app-server` supplies all
  three, which is exactly gate C.**

---

## 10. What is not known, and was not guessed

Listed rather than smoothed over, because a design doc full of confident unmeasured mappings is
worse than a short one with an honest unknown list.

- **`codex app-server` / `codex exec-server`** — both experimental, neither driven. They are the
  single most likely source of a headless roster and therefore the highest-value next measurement.
- **`CODEX_HOME` isolation** — BELIEVED to give a per-worker namespace the way `CLAUDE_CONFIG_DIR`
  does. Not measured: testing it means placing credentials in a second directory on the operator's
  own host, which is beyond a read-only spike.
- **`danger-full-access` and `--approve-for-me`** — not run, by the brief's fence.
- **`codex sandbox`** — requires `--permission-profile`, which requires writing
  `~/.codex/config.toml`. Not run.
- **The populated shape of `rate_limit_reached_type`** — the field is measured, its non-null values
  are not (§5.2).
- **Concurrency.** Every spike run was a single codex process. **N codex workers against one
  `~/.codex/*.sqlite` set is completely unmeasured**, and it is a single-writer question on someone
  else's store — on a host that is already RAM-bound. Nothing here should be read as evidence that
  three codex workers coexist.
- **Session names.** `queue`, `archive`, `delete` and `exec resume` all accept *"session id (UUID)
  or session name"*, but no flag on `codex exec` was found that sets a name. If one exists, it is a
  direct `fleet` worker-name analogue and worth finding.
- **`codex review`, `codex apply`, `codex fork`, `codex doctor`, `codex features`** — out of scope
  for the worker contract, unexamined.
