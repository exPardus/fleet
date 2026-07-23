# Three-tier command: interface / supervisor / workers — SPEC DRAFT

**Status: `drafting`.** This document re-drafts the withdrawn PROPOSAL (its full prior text is
recoverable from git history at `235421e`^) on top of two things that did not exist when the PROPOSAL
was frozen: `docs/specs/claim-nonce.md` (**spec-of-record, ratified by Altai 2026-07-23**, gate
question decided **option (b)**) and the re-pinned `docs/specs/native-substrate.md` (2.1.212 transient
daemon, 2.1.216 daemon-wedge). It answers the 2026-07-17 dual-lens adjudication's binding items **4–10**
(`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md`) and folds in the operator's 2026-07-23
requirements (swap band, tier-model configurability, worker-model policy, event-driven beats) plus the
manager's same-day refinement (tier-based, provider-agnostic resolution).

**An author never promotes its own spec.** This draft goes to a fresh dual-lens design gate. Nothing
here ratifies anything; every operator gate stays open until Altai ticks it.

**Inherits, and must not contradict:** `docs/specs/claim-nonce.md` (INCARNATION schema v2, the boot
verdict order §6.1, `resume`/`released` states, `sup-release`, handoff-verifies-a-token §6.4, the
option-(b) gate §7 and its corrected verb taxonomy); `docs/specs/native-substrate.md` (the G-row
contract, read as observed behaviour); `docs/SPEC.md` v3 invariants (additive schema §4, single-writer
registry, one-live-session-per-name §16.7, platform-adapter-only OS branching §16.8, G9 epoch freeze);
`docs/specs/terminal-surface.md` (views doctrine, D7 pull-only); `CLAUDE.md` repo rules (`py -3.13`
with a 3.10 floor, `bin/fleet.py` stdlib-only single file, forward slashes in hook commands).

---

## Vantage and receipt pin

Every `$ ` receipt below was executed by the author in worktree `C:\proga\fleet-mf-threetier`
(branch `mf/three-tier`), and is pinned **`# at 235421e56bfd328a7e913e519a1459ccf55918dc`** — this
worktree's HEAD at authoring time. `tools/verify_receipts.py` materialises that commit's tree and
re-runs each block against it, so an unrelated later change to `bin/fleet.py` cannot rot these lines.
Line numbers below are this commit's; they differ from `claim-nonce.md`'s (pinned `091d5fa`) because
`bin/fleet.py` has moved since. Where a claim describes behaviour **not yet in shipped code**, it
carries `[UNBUILT — owned by the three-tier build slice]` and a no-match receipt proving its absence
at this commit (§Appendix A collects them).

^ `git show 235421e~0:docs/specs/three-tier-command.md` is the withdrawn PROPOSAL; not re-pasted here
because verify would re-run it, and it is prose, not a receipt.

---

## 1. The operator's model (verbatim intent — preserved)

> CEO (human-facing session) takes input from the investors (human), translates it down to the staff
> manager (supervisor session) who slices up the task, gives it to employees (worker sessions) and
> makes sure the task is completed. The top session saves its context for talking, interpreting, and
> long-term ideas; the lower tiers get respawned and killed constantly for fresh context.

The tier model itself is **not** what the 2026-07-17 gate refuted — both lenses agreed the split is
sound. What it refuted was the drafted *mechanism*, whose root cause (identity keyed on a session id
that every steering primitive rotates) is now fixed at the design level by `claim-nonce.md`. This
draft builds the three tiers on that fixed foundation.

## 2. What exists today (M-E reality)

- **Two tiers, merged at the top.** The session the human talks to IS the supervisor: it holds the
  claim (`supervisor/INCARNATION`), runs the beats, dispatches workers, merges and reviews. Its
  context carries both the human conversation and the campaign mechanics — the mix the operator wants
  split.
- **Supervisor identity survives bodies** via GOALS.md + JOURNAL.md + INCARNATION + the sup-boot /
  seize / handoff rituals — and, after the claim-nonce slice ships, survives fork-steer/respawn/handoff
  too. What does not exist: a supervisor body that acts without a human-attached session driving it.
- **Workers are native `--bg` sessions** — durable, daemon-hosted, survive host restarts, but run only
  when a turn is dispatched. Nothing self-continues (`ScheduleWakeup`, the one native self-wake
  primitive, dies on `claude stop`; native-substrate G7).
- **The scheduler bridge is already generalized** (M-C autoclean + M-E hardening): a platform adapter
  with `autoclean_task_query/install/remove(task_name, command, interval)` on both a Windows
  (schtasks) and a POSIX (crontab) backend, and an F4 ownership predicate that is now full-identity,
  not path-only. A supervisor beat task would reuse it verbatim (§6).
- **Fleet is pull-only** (terminal-surface D7): the plugin injects nothing into any session. Every
  tier boundary in this design is therefore an explicit `fleet` call or a file the next tier reads,
  never an injected briefing.

---

## 3. The tier model, and where role→model lives (operator req 2026-07-23 + manager refinement)

### 3.1 Roles bind to abstract tiers, never to model ids

The operator's binding requirement: *tier models by role, configurable, never hardcoded ids*
(`knowledge/lessons.md#2026-07-23-three-tier-inputs`), refined the same day to **tier-based**: roles
bind to abstract tiers (`highest` / `second` / `third`); a resolver maps tier → concrete model at
dispatch time from what the active provider currently offers. Concrete ids (Fable 5, Opus 4.8) are
**illustrative of today's Anthropic resolution only**, never normative.

| Role | Tier | Today's Anthropic example | Who sets the model |
|---|---|---|---|
| Interface session ("CEO") | highest | Fable 5 | the human, in their own foreground session — **fleet never launches it** |
| Supervisor | second | Opus 4.8 | `fleet sup-spawn --model <tier-alias>` (§7) — resolved from policy, never a constant |
| Worker | third | Opus **or** Sonnet (operator: **never Haiku**) | supervisor's call, per-spawn `--model` |

**The interface tier is outside fleet's launch surface entirely.** Fleet has no verb that starts the
human's session; its "tier" is advisory (a note in policy that the human should run their highest
tier). Only the supervisor and worker tiers are fleet-dispatched, and only those two get a
fleet-resolved model.

### 3.2 The only model surface shipped today is `--model`, and it carries a tier alias

There is no hardcoded model id anywhere in `bin/fleet.py`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "claude-opus\|claude-sonnet\|claude-haiku\|claude-fable" bin/fleet.py
0
```

The model reaches a session exactly one way — `--model <value>` on the dispatch argv, defaulting to
absent (the CLI/daemon's own default):

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -n '"--model"\|argv += \["--model"' bin/fleet.py
7733:        argv += ["--model", model]
8529:        argv += ["--model", args.model]
8823:    p_spawn.add_argument("--model", default=None)
8952:    p_suphb.add_argument("--model", help="model for the successor session")
```

`--model opus` / `--model sonnet` are **tier aliases**, not model ids: the CLI resolves the alias to a
concrete model using the daemon's environment (`ANTHROPIC_DEFAULT_OPUS_MODEL`,
`ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_MODEL`). This is the tier→model resolver, and **it lives
below fleet, in the daemon env** — `bin/fleet.py` has no provider or model-mapping surface of its own:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "CLAUDE_CONFIG_DIR\|ANTHROPIC_\|--provider\|provider" bin/fleet.py
0
```

### 3.3 Provider-agnostic resolution: the daemon namespace is the tier table

Fleet workers do **not** read their endpoint/auth/model-map from the spawn-time environment — they
inherit it from the **background daemon**, fixed at daemon-boot, and one daemon serves one backend
(`docs/longcat-fleet-usage.md`, verified 2026-07-21: a `--bg` worker spawned with correct LongCat env
still failed `model_not_found` because a pre-existing Anthropic daemon owned it). The working
mechanism for a non-Anthropic provider is an **isolated `CLAUDE_CONFIG_DIR` namespace** → a separate
daemon whose env carries that provider's base URL, auth, and tier→model map
(`ANTHROPIC_DEFAULT_OPUS_MODEL=LongCat-2.0`, etc.).

This fixes where each piece lives:

- **Per-provider tier table** = the daemon-env of that provider's `CLAUDE_CONFIG_DIR` namespace
  (`ANTHROPIC_DEFAULT_*_MODEL` + `ANTHROPIC_MODEL`). It is set by the launcher that boots the daemon
  (e.g. the `longcat-fleet` launcher), **not** by fleet. Fleet has no `CLAUDE_CONFIG_DIR` handling
  (receipt §3.2), so it neither sets nor reads the table — it only emits a tier alias and lets the
  namespace's daemon resolve it.
- **Role → tier alias** (interface=highest, supervisor=second, worker=third) is the fleet-level policy.
  It belongs in `supervisor/GOALS.md` — the git-tracked, human-editable, operator-owned policy file the
  supervisor already reads at boot — as a small role→tier table, **not** as a constant in a code path.
  A machine-read of that table by `sup-spawn`/`spawn` to auto-select `--model` is
  `[UNBUILT — owned by the three-tier build slice]`; today the operator/supervisor types the alias
  into `--model` by hand, guided by GOALS.md.
- **When the fleet spans providers**, a role resolves **per namespace**: cross-provider work needs
  separate `CLAUDE_CONFIG_DIR` namespaces (one daemon each), and each namespace's daemon resolves the
  same tier alias to its own provider's model. There is no per-worker mixing within one daemon — that
  is a shared-daemon architecture limit, not a fleet choice (`longcat-fleet-usage.md` §"What does NOT
  work"), and the shelved `--provider` flag (`docs/specs/providers.md`) does not change it.
- **When a provider lacks a tier** (e.g. LongCat exposes one model, so `--model opus` has nothing to
  resolve to): the honest options are (a) **omit `--model`** and let the namespace's `ANTHROPIC_MODEL`
  default govern — the LongCat doc's explicit instruction, and the **specified v1 behaviour** — or (b)
  **pass the alias and accept the CLI's `model_not_found` refusal** at dispatch. Either way the failure
  is loud (the daemon refuses at dispatch), never silent wrong-model execution.
  **B8 reconciliation:** the earlier draft also recommended fleet *pre-flight* the tier-resolution, which
  is in direct tension with this section's own boundary — to "confirm the alias is resolvable in the
  active namespace" fleet would have to read that namespace's `ANTHROPIC_DEFAULT_*_MODEL`, the exact
  provider-env surface §3.2 shows fleet does not have and this section argues it should not acquire (`grep
  -c "CLAUDE_CONFIG_DIR\|ANTHROPIC_" bin/fleet.py` → 0, §3.2). So the pre-flight recommendation is
  **dropped**: v1 relies on the daemon's own loud refusal, and fleet is **not** given a provider-env read
  surface. A fleet-owned pre-flight would be a *deliberate new provider-env read surface*, priced as its
  own scope (a `[UNBUILT]` that the boundary of this section argues against, not for) — recorded here so
  the tension is resolved on the page rather than left for the reader to notice.

### 3.4 Worker-model policy: Opus or Sonnet, never Haiku

Operator, binding: workers are the supervisor's call, **Opus and Sonnet only**; **Haiku is never a
worker** — Haiku is a subagent *inside* a worker session. Nothing in shipped code enforces a
worker-model allowlist (the only model surface is a free `--model` string, §3.2). Enforcing
"third-tier ∈ {opus, sonnet}" at `spawn` is `[UNBUILT — owned by the three-tier build slice]`; until
built it is doctrine in GOALS.md, not a guard. Note the interaction with §3.3(d): on a single-model
provider the "Opus or Sonnet" rule is moot — the namespace has one model — so the allowlist is
Anthropic-namespace policy, not a universal invariant.

---

## 4. Item 4 — substrate re-pin FIRST: daemon-lifecycle assumptions and the beat's G9 behaviour

**Adjudication item 4** binds this spec to state its daemon-lifecycle assumptions against
`native-substrate.md`'s rows, and to state the beat's G9 behaviour explicitly: *a stale roster
currently PASSES the epoch check; a beat is a `send`, and `send` refuses under a suspicious roster —
scheduler ignores exit codes ⇒ silently dropped beats.*

### 4.1 Daemon-lifecycle assumptions, stated against the contract rows

This spec assumes the substrate exactly as `native-substrate.md` observes it (all
`[PENDING OPERATOR RATIFICATION]`; this spec changes no verdict there):

- **The daemon is transient** (2.1.212 hazard row): started on demand by a dispatch, idle-exits ~5s
  after the last client disconnects **and** live-worker count reaches 0. A live supervisor `--bg`
  session holds it open; a supervisor that has idle-exited its process does not. **Consequence for the
  supervisor:** an idle supervisor (no turn running) does not keep the daemon alive, so a beat that
  arrives via a fresh dispatch is what both wakes the daemon and runs the supervisor — consistent with
  §5 (a beat is a `send`).
- **An idle-exit cannot strand a live-looking roster entry** (G9 row, 15/15 `live_workers=0`): so the
  supervisor's own roster liveness (the claim-nonce roster-liveness guard, §8) is trustworthy across a
  daemon idle-exit. The residual stale-roster vector is `cause=upgrade` (4/4 with live workers), which
  is exactly what the epoch freeze defends.
- **The daemon-wedge outage** (2.1.216 row): a stale `daemon.lock` + PID reuse can make *every*
  dispatch on the machine fail for hours while `fleet doctor` reads healthy; M-E shipped
  `_doctor_check_daemon_wedge` and a `dispatch_bg` classifier. **Consequence for the supervisor:** a
  wedged daemon means beats silently do not run (no dispatch succeeds); §5's run-stamp is what makes
  that visible, and the wedge doctor check is the machine-wide backstop.
- **`claude stop` fires no Stop hook** on a not-yet-ended session (G10): every stop-shaped verb against
  the supervisor owes its own tombstone (§10).

### 4.2 A stale roster PASSES the epoch check — receipt

`supervisor_epoch_check` tests fetch-success and non-emptiness only; there is **no staleness test**:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8117,8126p' bin/fleet.py
def supervisor_epoch_check(roster_ok: bool, payload):
    """Roster-epoch sanity check, run BEFORE any claim decision (spec §4).
    A failed or empty roster freezes the decision -- a daemon restart (G9)
    must never let a fresh boot seize a claim whose holder is alive."""
    if not roster_ok:
        return (False, f"roster unavailable ({payload}) -- freeze, never decide blind")
    if not payload:
        return (False, "roster is EMPTY -- not even this session is listed; "
                       "daemon restart suspected (G9). Freeze + page operator.")
    return (True, f"roster holds {len(payload)} entr{'y' if len(payload) == 1 else 'ies'}")
```

The claim-nonce spec (§6.6) declines the staleness axis explicitly, ruling it gated on the substrate
re-pin and out of that slice's scope, and relies on the fail-safe analysis (a dead holder shown live ⇒
`refuse`, a live holder shown gone with fresh heartbeat ⇒ `freeze`; never seize on ambiguity). **This
three-tier spec inherits that disposition and does not reopen it** — the residual is
`[MANAGER-VERIFICATION REQUIRED]` per claim-nonce §12 O4, not a three-tier deliverable.

### 4.3 A beat is a `send`, and `send` refuses under a suspicious roster

`_cmd_send_native` refuses up front when the roster snapshot is epoch-suspicious:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '3595,3599p' bin/fleet.py
        if native_epoch_suspicious(roster_ok, roster_entries, {name: rec}):
            raise FleetCliError(
                f"{name}: roster fetch unavailable/suspicious (G9) -- "
                "refusing to send while native verdicts are frozen; retry shortly"
            )
```

**The G9 hazard is real and this is where item 4 lands in the design:** if a beat is delivered by a
scheduler that runs `fleet send supervisor "beat"`, and the roster is transiently suspicious, `send`
raises `FleetCliError`, exits non-zero, and **the scheduler ignores the exit code** — the beat is
silently dropped with no record. This is the single strongest reason the beat is **not** a scheduled
`send` in v1 (§5): v1 beats are interface-originated `fleet send` turns whose failure the human sees
immediately, and the *scheduled* form is deferred (§9) precisely because its silent-drop failure mode
needs the first-class `fleet beat` verb (§5) with its own run-stamp and non-zero-safe error semantics
before it is safe to schedule.

---

## 5. Item 5 — beat = a first-class `fleet beat` verb (design answer; v1 uses only the interface arm)

**Adjudication item 5** binds this spec to answer the beat as a first-class `fleet beat` verb with its
own error semantics (limited / freeze / handoff-in-flight / pending-decision without burning a model
turn), a run-stamp, and to be the only thing `--supervisor-beat` installs; and to consider the
break-lens beat-worker split (a claimless cheap beat that only decides "wake the supervisor?").

**Operator override, 2026-07-23:** *beats event-driven only in v1; scheduled heartbeat deferred until a
campaign demonstrably stalls for want of one.* So this item is **answered as design** (the adjudication
binds the answer) but its *scheduled* half is scoped to §9 (deferred), citing the operator decision.

### 5.1 v1: a beat is an interface-originated `fleet send` turn

In v1 the only beat is the interface session steering the supervisor: `fleet send supervisor @brief.md`
(or `fleet send supervisor "reconcile"`). This is a real, shipped mechanism (`cmd_send`), its failure
is synchronous and human-visible (the interface session sees the `FleetCliError`), and it burns a model
turn **only when the human intends one**. No scheduler, no run-stamp, no silent drop. This is the whole
v1 beat surface.

### 5.2 The `fleet beat` verb — specified, `[UNBUILT]`, needed before any *scheduled* beat

The scheduled beat of §9 must not be a bare `fleet send`, for the item-4 reason (§4.3): `send` refuses
under a suspicious roster and the scheduler eats the exit code. `fleet beat` is the first-class verb
that fixes this. It does not exist today:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c 'add_parser("beat"' bin/fleet.py
0
```

`[UNBUILT — owned by the three-tier build slice]` — `fleet beat` semantics:

- **Own error taxonomy, no model turn burned to discover it.** Before dispatching a supervisor turn,
  `fleet beat` reads state and returns a typed, exit-code-and-stdout result for each of:
  *supervisor limited* (a `_parse_limit_signal` hit on its transcript tail), *claim frozen/ambiguous*
  (sup-boot would `freeze`), *handoff in flight* (`supervisor/HANDSHAKE` present / abort flag set), and
  *operator decision pending* (the §8 gate state file exists). In every one of these it **does not
  steer the supervisor** — it records why and returns. A beat that finds nothing to do costs no model
  turn.
- **Run-stamp.** Each invocation writes a `state/supervisor-beat.jsonl` run record (ts, verdict,
  whether a turn was dispatched) so a *silently dropped* beat becomes a *visibly missing* run-stamp —
  the exact gap the scheduler's exit-code-blindness (§4.3) would otherwise hide. `fleet doctor` reads
  the newest stamp and warns on staleness (§6).
- **The only thing `--supervisor-beat` installs.** The scheduled task (§9, deferred) runs
  `fleet beat`, never `fleet send` — so the refuse-under-suspicious-roster path is handled inside a verb
  that knows the scheduler is blind, instead of leaking a dropped `send`.
- **Beat-worker split — considered, deferred.** The break-lens proposal (a claimless cheap-tier beat
  that only decides "wake the supervisor?") is the only drafted-mechanism answer to beat cost, and it
  interacts with `send has no --model` / `model is spawn-immutable`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8865,8866p' bin/fleet.py
    p_send.add_argument("name")
    p_send.add_argument("message")
```

  `send` takes only `name` and `message` — no `--model` — so a beat delivered by `send` cannot pick a
  cheap tier, and the model is fixed at spawn (§3.2). A cheap beat-worker would therefore be its **own**
  spawned session at the third/cheap tier, not a re-model of an existing one. In v1, with beats
  human-originated and scheduled beats deferred, **beat cost is not yet a problem to solve** — the
  split is recorded as the v2 answer (§9), not built.

### 5.3 The split moves the fork-divergence class up to the interface tier — stated, mitigated, residual owned (B7, B10)

**B7 (MAJOR).** claim-nonce protects the *supervisor* claim. The **interface** tier holds no claim by
construction (§11.3: *"it never held the claim, so nothing transfers to it"*) and steers the supervisor
with `fleet send`, which is **not** claim-gated — claim-nonce §4.2 enumerates the five
`_require_claim_holder` callers and they are all `sup-*`; `send` is unguarded. So the 2026-07-16 incident
1 class — a host-restart `--fork-session` of the manager conversation *"independently re-deriving and
dispatching my decisions in paraphrase"* (claim-nonce §1.2) — is not removed by the split; it **moves up
a tier**: a fork-resumed *interface* body carrying campaign context can re-derive and issue
`fleet send supervisor …` steers, and the supervisor cannot tell two interface bodies apart (no claim,
no nonce, `send` accepts either). The exposure is worst in the scenario the tiers exist for — the
supervisor running unattended while the human is away, so no human notices the second interface body.

`send` today records the *target's* sid in its event, **not** any caller/interface provenance:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -n 'append_event("mail_sent"' bin/fleet.py
3654:                append_event("mail_sent", name, sid=raw_sid, status="working")
3710:            append_event("mail_sent", name, sid=sid, status=status)
3767:    append_event("mail_sent", name, sid=old_sid, status="idle")
```

(All three `mail_sent` events carry the *target/worker* `sid`; none records the caller's — the
interface-tier provenance B7's mitigation would add.)

**Mitigation (`[UNBUILT — owned by the three-tier build slice]`), and its honest limit:** record
**interface-caller provenance** on `send` — the caller's `CLAUDE_CODE_SESSION_ID` — into `events.jsonl`
(`append_event` already takes `**fields`, so this is one keyword), and have the supervisor **surface a
divergence warning** when briefs/steers for its campaign arrive from two distinct interface sids within
a window. This is the interface-tier analog of the supervisor nonce, and it is deliberately *weaker*: the
interface tier holds no claim **by design** (the human owns that tier), so this is *detection and
surfacing*, never a refusal — the same shape as the 2026-07-17 adjudication's same-milestone candidate
(*"caller provenance in `events.jsonl` + foreign-claim warn on `send`"*). **Residual, stated not
buried:** full interface-fork *prevention* is out of v1 scope, because the tier that would need a claim
is the one the operator's model keeps human and claimless; the v1 mitigations are the provenance warn
above plus the operator-gate routing (§8, which keeps a divergent body from self-approving anything
irreversible) plus the doctrine that a human talks only to the interface tier. §13 records this as a
scoped non-goal rather than leaving the new top boundary silently unguarded.

**B10 (MINOR) — the supervisor's dominant verb is exactly option-(b)'s accepted blind spot.** claim-nonce
§2.2/§7 accept, as option (b)'s stated price, that a divergent body confining itself to **ungated** verbs
(`send`, `spawn`, `kill`) is undetected. §5.1 makes the supervisor's core loop precisely that —
dispatching workers via `fleet send`. So the design concentrates the supervisor's activity in the
ratified gate's blind spot rather than in the `sup-*` verbs the nonce guards. This is **priced upstream**
(claim-nonce's ratified option (b), not a new defect here), but it is recorded so the operator reads
option (b)'s residual against the tier that *maximises* it: a zombie supervisor's most likely behaviour
is send-only worker churn, which the gate does not catch — and the §8 operator-gate routing, not the
nonce, is what bounds the damage such a body can do.

---

## 6. Item 6 — scheduler bridge through the platform adapter, generalized (largely SHIPPED)

**Adjudication item 6** binds a generic installer (`task_name`+`command`+`interval`), the fix to the
`_autoclean_task_is_ours` path-only predicate, three backends or an explicit `UnsupportedPlatformError`
seam, a doctor check for the new task, multi-flag refusal semantics, and reconciliation with the
`ScheduleWakeup` primitive the draft never mentioned.

### 6.1 The generic installer already exists

The platform adapter method is already generic over `task_name`, `command`, `interval_hours`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -n "def autoclean_task_install" bin/fleet.py
409:    def autoclean_task_install(self, task_name: str, command: str,
567:    def autoclean_task_install(self, task_name: str, command: str,
```

Two backends exist — Windows (schtasks, @409) and POSIX (crontab, @567) — so item 6's "three backends
or an explicit `UnsupportedPlatformError` seam" is met by **two shipped backends + the adapter seam**
(a third platform raises through the adapter, not a hardcoded branch; SPEC §16.8). A supervisor-beat
task is installed by calling the same three methods with `task_name="claude-fleet-supervisor-beat"` and
`command=<fleet beat argv>`; the method name (`autoclean_task_*`) is now a misnomer for a generic
scheduler seam — a **rename to `scheduled_task_*` is `[UNBUILT]` cosmetic cleanup**, not a blocker.

### 6.2 The path-only ownership hole is already fixed (M-E)

Item 6's `_autoclean_task_is_ours` path-only defect — which would let `fleet init --autoclean`
`/Create /F` over a second fleet task — was fixed in M-E. Ownership is now full-identity (resolved
fleet.py path **and** subcommand **and** fleet-home), on whole quote-stripped tokens, not a substring:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -n "def _fleet_task_is_ours\|def _autoclean_task_is_ours" bin/fleet.py
5946:def _fleet_task_is_ours(command: str, subcommand: str) -> bool:
6022:def _autoclean_task_is_ours(command: str) -> bool:
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '6022,6026p' bin/fleet.py
def _autoclean_task_is_ours(command: str) -> bool:
    """F4 for the autoclean task specifically -- see `_fleet_task_is_ours`.
    Kept as a named seam so the sole consumer (`_install_autoclean_task`)
    reads the same as before and a second fleet task gets its own one-liner."""
    return _fleet_task_is_ours(command, "autoclean")
```

The function's own docstring names *the three-tier adjudication's `fleet init --supervisor-beat` as the
concrete near-term case* the fix protects against. **Consequence:** the supervisor-beat task installs as
`_fleet_task_is_ours(command, "beat")` and coexists with the autoclean task without either
`/Create /F`-ing the other. The multi-flag refusal (item 6): `fleet init` with both `--autoclean` and a
future `--supervisor-beat` in one invocation must install both idempotently or refuse cleanly — the
per-task ownership predicate makes independent install/refuse safe; the combined-flag CLI wiring is
`[UNBUILT]`.

### 6.3 The doctor check, and reconciliation with `ScheduleWakeup`

- **Doctor check for the beat task** = `[UNBUILT — owned by the three-tier build slice]`: a
  `_doctor_check_supervisor_beat` mirroring the autoclean/wedge checks — task present when
  `--supervisor-beat` was installed, its `command` still `_fleet_task_is_ours(…, "beat")`, and the
  §5.2 run-stamp not stale. Grep confirms no such check today (Appendix A).
- **`ScheduleWakeup` reconciliation (the draft never mentioned it):** `ScheduleWakeup` is a native,
  **in-session** self-rearming tool (native-substrate G7 — 17 beats at ~173s cadence, context
  continuous). It is **not a fleet verb and not an OS scheduler**, and it has a disqualifying property
  for a supervisor heartbeat: *`claude stop` permanently kills the self-wake loop; a wakeup already
  scheduled at stop time never fires* (G7). A supervisor that is respawned/handed-off/stopped — the
  normal lower-tier lifecycle — would lose its `ScheduleWakeup` loop silently. So the beat is an
  **external** OS-scheduler dispatch (the schtasks/crontab adapter, §6.1), **not** `ScheduleWakeup`.
  `ScheduleWakeup` is recorded here only to state, per item 6, why it is not the mechanism. It is not
  referenced in `bin/fleet.py`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "ScheduleWakeup" bin/fleet.py
0
```

---

## 7. Item 7 — heartbeat decoupled from beat period; supervisor record protected by construction

**Adjudication item 7 / MF3:** the 3600s seizure/nag threshold (S) versus N-hour beats means the
supervisor is seizable for N−1h of every N; and the archive TTL (24h) versus the schtasks 23h interval
clamp means `autoclean` can rm the supervisor. Both must be resolved by construction.

### 7.1 S=3600 vs beat period — decoupled, and largely mooted by the roster-liveness guard

The seizure threshold is a standalone constant, already independent of any beat period:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '7918p' bin/fleet.py
SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
```

The MF3 worry — a supervisor idle >1h becomes seizable — is **largely closed by the claim-nonce boot
verdict order** (§6.1 there): a roster-**live** holder is `refuse`d regardless of heartbeat age (rule
2), and `seize` requires `holder_sid not in live_sids` **and** a stale heartbeat. So a supervisor whose
body is alive but idle (roster-live, stale heartbeat) is **frozen/refused, never seized** — the
"seizable N−1h" window closes for any live body. The residual is a genuinely dead supervisor
(roster-gone) past 3600s, which *should* be seizable — that is recovery, correct.

**This spec's design rule (v1):** with scheduled beats deferred (§9), S is **not** coupled to any beat
period at all; it is purely the dead-body recovery floor. When a scheduled beat is later built (§9), the
binding constraint is `S > beat_period + margin` (as the comment already states) so a live supervisor's
heartbeat is refreshed by its own beat turns before S elapses — and the beat writes the heartbeat, which
`fleet beat` (§5.2) does as part of the supervisor turn it dispatches. Encoding `S ≥ beat_period +
margin` as an install-time check in `--supervisor-beat` is `[UNBUILT]`.

### 7.2 Archive TTL 24h vs schtasks 23h clamp ⇒ the supervisor must be archive/autoclean-exempt

The two constants that collide:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '4914p' bin/fleet.py
ARCHIVE_TTL_HOURS_DEFAULT = 24.0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '6033,6034p' bin/fleet.py
    if not 1 <= interval_hours <= 23:
        raise FleetCliError("--autoclean-interval-hours must be 1..23 (schtasks /SC HOURLY /MO)")
```

The autoclean scheduled task runs at most every 23h; the archive TTL is 24h. If the supervisor's
registry record goes idle, it crosses the 24h archive threshold and an autoclean pass (cadence ≤23h)
archives/rm's it — deleting the running campaign's manager. **Resolution, by construction:** the
supervisor record is **exempt from both the archive TTL pass and the daemon-husk sweep**.

> **B1 fix (CRITICAL — the exemption must not be keyed on a static name).** The first-generation
> supervisor is spawned by `sup-spawn` under the name `supervisor` (§10.3), but the operator's model
> respawns and hands it off "constantly" (§1), and the shipped handoff dispatches its successor under a
> **pipe-delimited** name, `f"sup|{successor_inc}|successor"`, which nothing renames back to
> `supervisor` — `sup-handoff-complete` transfers the INCARNATION claim only, and registry records are
> independent:
>
> ```
> # at 235421e56bfd328a7e913e519a1459ccf55918dc
> $ sed -n '8522p' bin/fleet.py
>     name = f"sup|{successor_inc}|successor"
> ```
>
> So a `name == "supervisor"` equality protects generation 0 and **no successor** — after the first
> swap (which §11's 150–200k band makes routine, not exceptional) the live claim-holder runs under
> `sup|<inc>|successor`, the exemption misses it, and the 24h-vs-23h collision is live again against the
> actual running manager. **The exemption is therefore keyed on *is this record the current live
> supervisor claim-holder*, under any name, not on a static registry name.**

**The predicate**, `[UNBUILT — owned by the three-tier build slice]`: a record is protected iff its
`session_id` (or a member of its `retired_sids`) equals `supervisor/INCARNATION`'s
`incarnation_id`-body — i.e. the record is the body that currently holds the claim — **and that body is
roster-live**. Concretely: read `read_incarnation()`; protect the registry record whose live sid is the
claim's restamped `session_id` (claim-nonce restamps `session_id` on every validated `sup-*` write, so
the claim tracks the acting body). Two directions, both mandatory:

- **Protects the running manager under any name** (closes B1): a successor named `sup|<inc>|successor`
  that holds the claim and is roster-live is exempt.
- **Stops protecting a dead husk** (closes B9, MINOR): a supervisor record that is roster-gone and whose
  body no longer holds the claim (seized/released away) is **not** exempt — it is an ordinary husk and
  the sweep removes it. A static-name exemption would have protected dead husks forever; the
  live-claim-holder predicate does not. B1 and B9 are the same fix in opposite directions.

Today's archive is registry-worker-only with **no** exemption of either kind, and the reserved name it
would key on does not exist:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '4917,4920p' bin/fleet.py
def _archive_eligible(name: str, record: dict, roster_entries: list, now,
                      ttl_hours: float = ARCHIVE_TTL_HOURS_DEFAULT) -> tuple:
    """Every gate must hold; returns (True, "eligible") or (False, reason)
    naming the FIRST failed gate (binding order, task-9-brief.md):
```

So the build adds a first gate to `_archive_eligible` **and** to `_sweep_husks` (@5568):
*the record is the current live claim-holder ⇒ `(False, "supervisor claim-holder — protected while
live")`*. Note the supervisor's *claim* (`supervisor/INCARNATION`) and its `supervisor/JOURNAL.md`
already live outside the archive path (archive moves `state/outcomes|journals|tasks/<name>` and the
roster entry, not the top-level `supervisor/` dir), so only the supervisor's **registry/outcome**
footprint needs the exemption — but that footprint is exactly what a husk sweep would rm, so the
exemption is mandatory, not belt-and-braces.

### 7.3 Heartbeat decoupled from beat period — stated

The heartbeat (`heartbeat_at` in INCARNATION, refreshed by every validated `sup-*` write and by
`sup-heartbeat`, which does not gate on staleness) is **not** driven by the beat scheduler. In v1 it is
refreshed whenever the interface steers the supervisor and the supervisor acts. The beat period (v2)
and S are separate axes: S is the recovery floor, the beat period is a liveness cadence, and the
install-time invariant `S > beat_period + margin` (§7.1) is what keeps a live supervisor from aging past
its own recovery floor. No shipped constant couples them today; keeping them decoupled is the design
rule.

---

## 8. Item 8 — operator-gate routing is a state file, not a journal kind

**Adjudication item 8 / MF7 / H5:** operator-gate routing must be a **state file** — answerable,
un-re-derivable, nag-visible — that stops the beat from burning turns while a decision is open.

A background supervisor must route operator-only decisions (destructive ops, HALT ratification, GOALS
edits, spec promotion — everything in `docs/OPERATOR-GATES.md`) to the interface tier and **park**,
never self-approve. No such routing surface exists today:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "NEEDS-OPERATOR\|needs_operator\|pending-decision\|pending_decision" bin/fleet.py
0
```

`[UNBUILT — owned by the three-tier build slice]` — the design:

- **A state file, `state/supervisor-pending-decision.json`** (not a journal kind — the withdrawn
  PROPOSAL's `NEEDS-OPERATOR` journal kind is rejected here per item 8: a journal is append-only and
  cannot be *cleared*, so it cannot represent an open-then-answered decision; and it is not a single
  answerable object). One open decision at a time: `{question, raised_by_inc, raised_at, context_ref}`.
- **Answerable and un-re-derivable:** the interface session answers by writing the operator's decision
  into the file's `answer` field (or removing it), through a `fleet sup-decision` verb `[UNBUILT]`; the
  supervisor never writes its own answer. The file's presence *is* the "open" state — nothing re-derives
  it from journal scanning.
- **Nag-visible:** `fleet doctor` and `sup-status` surface an open pending-decision (a `[UNBUILT]`
  doctor check + a `sup-status --json` field, both trivially additive since `sup-status` already dumps a
  dict; the terminal-surface D2 rule holds — it stays a lock-free projection).
- **Stops the beat from burning turns:** `fleet beat` (§5.2) lists *operator decision pending* among the
  states in which it **does not dispatch a supervisor turn** — it records the skip and returns. So while
  a gate is open, the scheduled beat (v2) costs nothing, and the v1 interface-originated beat is the
  human, who is the one who must answer anyway.

This file is **routing**, not authorization: it never lets the supervisor act on the operator's behalf.
It is the mechanism by which "operator gates stay human" (a standing invariant) survives an unattended
supervisor body.

---

## 9. Item 9 — drop the event-driven arm (v2/deferred: the scheduled beat)

**Adjudication item 9 / MF9 / D7:** drop the event-driven arm. Its stated blocker misread SPEC §8(a)
(mailbox writes ARE sanctioned); the *real* blockers make poll-on-beat strictly safer.

The withdrawn PROPOSAL floated an event-driven arm (worker Stop-hook outcomes enqueue a "reconcile"
mail) and justified dropping it by claiming hooks can't write the mailbox. **That justification was
wrong** — mailbox writes are sanctioned (SPEC §8(a)). The arm is dropped anyway, for the real reasons,
which are decisive and which item 9 names:

1. **Hooks can't dispatch.** A Stop hook can write a file, but nothing in a hook can *start a supervisor
   turn* — the supervisor is an idle `--bg` session, and the only way to start its turn is a fork-steer
   dispatch (`fleet send`), which a hook subprocess is not positioned to do safely.
2. **The target sid rotates.** Even if a hook could dispatch, the supervisor's sid rotates on every
   fork-steer (the whole reason claim-nonce exists); a hook holding a stale sid would steer a retired
   body.
3. **Lost events are silent.** A dropped hook-event leaves no trace; a poll-on-beat that fails leaves a
   missing run-stamp (§5.2).

So **poll-on-beat is strictly safer**, and v1's poll is the interface session (§5.1). This item is fully
answered: the event-driven arm is gone.

### 9.1 The scheduled beat — deferred to v2 (operator decision, 2026-07-23)

The operator deferred the *scheduled* beat entirely: *event-driven only in v1; scheduled heartbeat
deferred until a campaign demonstrably stalls for want of one.* So the poll's **scheduled** form (a
schtasks/crontab task running `fleet beat` every N hours) is **v2**, not v1. When a campaign
demonstrably stalls for want of an autonomous beat, the v2 build is:

- `fleet init --supervisor-beat N` installs a `claude-fleet-supervisor-beat` task via the §6.1 adapter,
  `command = fleet beat` (never `fleet send`, §4.3/§5.2), owned via `_fleet_task_is_ours(…, "beat")`
  (§6.2), with `N` constrained so `S > N·3600 + margin` (§7.1).
- The beat-worker split (§5.2) becomes the cost answer: a claimless cheap-tier session that only decides
  "wake the supervisor?" — its own spawn at the third/cheap tier, because model is spawn-immutable and
  `send` has no `--model` (§5.2 receipt).
- All of §5.2's `fleet beat` error taxonomy and run-stamp are prerequisites of this v2 slice.

Everything in §9.1 is `[UNBUILT — owned by the three-tier build slice]`, and explicitly deferred beyond
v1 by the 2026-07-23 operator decision — recorded so a future author does not read v1's silence as an
oversight.

---

## 10. Item 10 — `sup-spawn` routes through `dispatch_bg`; reserved name at `validate_name`

**Adjudication item 10 / D5 / D6:** `sup-spawn` routes through `dispatch_bg` (`--settings`/`--add-dir`/
registry record/`_worker_env` implications stated); rule on `respawn supervisor`/`kill supervisor`
(each stop-shaped verb owes a tombstone); reserve the body name mechanically (no RESERVED list today).

### 10.1 `dispatch_bg` is the sanctioned choke point, and it takes a model

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '7670,7673p' bin/fleet.py
def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
                hint="", resume_sid=None, settings_path=None,
                setting_sources=None,
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
```

`dispatch_bg` renders `--settings` (the instance hook-wiring, so the child gets fleet's hooks) and
`--add-dir` for the tasks/journals dirs, and launches under `env=_worker_env(name)`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '7708,7708p;7721,7722p' bin/fleet.py
    argv += ["-n", rendered, "--settings", settings.as_posix()]
    argv += ["--add-dir", tasks_dir().as_posix(),
             "--add-dir", journals_dir().as_posix()]
```

**`sup-spawn` (`[UNBUILT]`) routes through `dispatch_bg`** exactly as `cmd_spawn` does — no hand-rolled
argv — so the supervisor body gets: fleet's hooks (`--settings`), the tasks/journals dirs
(`--add-dir`), the `_worker_env` process identity (parent env copied, `CLAUDE_CODE_SESSION_ID`
stripped, `FLEET_WORKER` stamped), and a registry record. The one thing it adds over `cmd_spawn` is the
first-turn sup-boot ritual (the successor bootstrap already models this; §10.4). `sup-spawn` does not
exist yet:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "sup-spawn\|cmd_sup_spawn" bin/fleet.py
0
```

**Precedent that this pattern is already proven (M-E):** the handoff-begin path — which the 2026-07-17
adjudication flagged as hand-rolling argv and giving successors *no hooks at all* — was fixed to carry
`--settings` + `_worker_env`, the same defense `dispatch_bg` applies:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8526,8531p' bin/fleet.py
    argv = [exe, "--bg", "-n", name,
            "--settings", instance_settings_path().as_posix()]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    # B4/D6: never leave the mode to claude's default -- see the docstring.
    # G3: ONE vocabulary. `--permission-mode` takes a FLEET mode name
```

(The handoff path is deliberately **not** `dispatch_bg` itself — its docstring explains why: the
successor body is already written to its own file and a single-successor guard must hold — but it
applies the same `--settings`/`_worker_env` guarantees. `sup-spawn`, having no such constraint, uses
`dispatch_bg` directly.)

### 10.2 `--settings` / `--add-dir` / registry / `_worker_env` implications, stated

- **`--settings`:** the supervisor gets the instance-rendered hooks. Without it the supervisor runs with
  none of fleet's mailbox/outcome/journal hooks — the same silent-hookless failure the M-E handoff fix
  closed. Mandatory, inherited free from `dispatch_bg`.
- **`--add-dir`:** the supervisor can read `state/tasks` and `state/journals` (its briefs and worker
  journals) without per-turn path wrangling. Inherited from `dispatch_bg`.
- **Registry record:** the supervisor becomes a worker record named `supervisor`, which is what makes it
  visible to `fleet status` — and what makes it archive/husk-eligible unless §7.2's exemption is built.
  Its `spawned_by` is the interface session's sid (or null if launched by a human shell); its
  `spawned_by_lineage` (claim-nonce §6.2) is null at first spawn (the supervisor is not spawned *by* a
  supervisor claim). It runs under **bypass** permission mode in the fleet repo (earned-privilege
  doctrine) — stated explicitly in GOALS before it ever runs unattended.
- **`_worker_env`:** copies the parent environment (so the supervisor inherits the interface session's
  `CLAUDE_CONFIG_DIR` namespace → the same provider daemon, §3.3), strips `CLAUDE_CODE_SESSION_ID`,
  stamps `FLEET_WORKER=1`. The `FLEET_WORKER` stamp matters: claim-nonce §6.5 requires a `FLEET_WORKER`
  refusal in `_require_claim_holder` (a worker turn must not hold the supervisor claim), filed there as
  a separate shipped-code prerequisite — the supervisor is spawned as a fleet worker, so this spec
  depends on that refusal existing before `sup-spawn` is safe.

### 10.3 Reserve the body name mechanically — at `validate_name`

There is no RESERVED list today, and `validate_name` is the single creation choke point:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "RESERVED" bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '721,722p' bin/fleet.py
def validate_name(name: str, existing=()) -> None:
    """Raise ValueError unless name matches [a-z0-9-]+ and isn't in `existing`.
```

`[UNBUILT]` — a `RESERVED = {SUPERVISOR_BODY_NAME}` set checked in `validate_name`: `spawn`/`respawn`
of the name `supervisor` by the ordinary worker path is **refused** (the name is minted only by
`sup-spawn`). This mirrors the existing F6 uuid-shape refusal already in `validate_name` (a name-space
conflation made unrepresentable at the one choke point rather than patched per reader) — the same
technique, one more reserved shape. Because `validate_name` is the choke point every creation path
already calls, the reservation is mechanical, not advisory.

### 10.4 `respawn supervisor` / `kill supervisor` — each stop-shaped verb owes a tombstone

The supervisor is a lower tier: it gets respawned and killed for fresh context (the operator's intent,
§1). But it holds the claim, so a stop-shaped verb against it has claim consequences a plain worker's
does not. The rule (`[UNBUILT]`):

- **`respawn supervisor`** = a body change. It must go through the claim-nonce respawn path: the fresh
  body holds no generation and boots via `sup-boot`, which `resume`s if it can prove continuity, else
  `seize`s once the heartbeat is stale, else takes an explicit release (claim-nonce §5.10(b)). A
  `respawn` that silently re-claimed would reintroduce the two-bodies hole. The old body gets a
  tombstone (native-substrate G10: `claude stop` fires no Stop hook, so the verb writes its own outcome
  record) **and** the claim transition is journaled.
- **`kill supervisor`** = terminate the body **and release the claim** — but the release cannot be
  performed *by the killer*, and B5 (MAJOR) is the correction of the earlier draft's rule that said it
  could. `kill supervisor` is an interface/operator verb; the killer is **not** the supervisor body, and
  `sup-release` requires continuity proof — the holder's current nonce — which a different session does
  not have, and claim-nonce §6.3 **deleted** the non-continuity escape (`--force --confirm-inc`).
  `sup-release` does not exist yet and, when built, needs continuity:

  ```
  # at 235421e56bfd328a7e913e519a1459ccf55918dc
  $ grep -c "sup-release\|cmd_sup_release" bin/fleet.py
  0
  ```

  So the honest design rule (`[UNBUILT]`), in two arms:
  - **Body responsive:** `kill supervisor` **steers the body to release itself** — it delivers a
    `sup-release` turn to the supervisor (which holds its own nonce), waits for the record to read
    `released`, then stops the body. This is a *graceful stop*, not an unattended kill, and the successor
    boots clean off the `released` record.
    ⚠ but see the B6 window below — the stop must complete before any successor consumes the record.
  - **Body unresponsive / already gone:** self-release is impossible, so `kill supervisor` falls to the
    **bounded-freeze-then-seize** recovery — claim-nonce incident 3 exactly (roster-gone + fresh
    heartbeat ⇒ `freeze`) until the heartbeat ages past `SUPERVISOR_CLAIM_STALE_SECONDS = 3600s`, then a
    successor `seize`s. This is a real up-to-one-hour recovery hole, and the design **accepts and
    documents it** for this arm rather than pretending the killer can release. `kill` writes the G10
    tombstone for this path (a `claude stop` on a not-yet-ended session fires no Stop hook, §4.1).
  - Both arms reuse the native tombstone obligation (G10); this spec adds the claim half (self-release
    steer, or documented bounded-freeze), not a new stop mechanism, and never a killer-side release the
    caller cannot perform.

**B6 (MAJOR) — the release→stop window and claim-nonce boot rule 1.** claim-nonce §6.1 checks rule 1
(`state == "released" ⇒ claim` fresh) **ahead of** rule 2 (roster-liveness refuse) and with **no
roster-liveness precondition**. So during any `release → stop` window — the planned `sup-release`
doctrine (claim-nonce §6.3) *and* the graceful-`kill` arm above — INCARNATION reads `released` while the
old body is still roster-**live**, and any session that runs `sup-boot` in that window is granted a
fresh claim while the predecessor is still executing: the 2026-07-16 dual-live-body class reappears.
claim-nonce blesses this ordering only for the *manual, single-operator, serial* case; three-tier adds
**automated** occupants of the window — the v2 scheduled `fleet beat`, a `sup-spawn`, an in-flight
handoff successor polling `sup-boot`. `one-live-session-per-name` (SPEC §16.7) blocks a second
`supervisor`-named spawn but **not** a `sup-boot` from an already-live differently-named session (the
interface, a successor). **This spec does not own the boot verdict order** (claim-nonce does), so it
states the constraint and files the guard as a **claim-nonce build-slice prerequisite**, exactly as
§10.2 files the `FLEET_WORKER` refusal:

> **Prerequisite (owned by the claim-nonce build slice, not this one):** `sup-boot` must not consume a
> `released` record whose `released_by_sid` is still roster-live — either rule 1 gains a roster-liveness
> precondition, or release+stop is made atomic from the claim's perspective (the record is never left
> `released`-and-live). Until that guard exists, three-tier's automated callers (`sup-spawn`, the v2
> scheduled beat, the handoff successor) **must gate their own `sup-boot` on `released_by_sid not in
> live_sids`** — the graceful-`kill` arm above is only safe once the old body is confirmed roster-gone.

This is why the graceful-`kill` arm's ⚠ is load-bearing: "stop the body, *then* let a successor boot"
is the ordering that keeps the window shut.

---

## 11. Supervisor self-monitored swap band (operator req 2026-07-23)

**Operator, binding:** the supervisor self-monitors its context; band **150–200k tokens**. Entering the
band → hand off at the next wave/task boundary. Past 200k → strongest directive to hand off, but finish
the current *urgent* task first (no new work). Handoff ritual = the existing sup-handoff machinery
(write the successor document, hand control back to the interface session).

### 11.1 The band replaces the drafted 300–500k band

The drafted band was 300–500k; the operator's is **150–200k**. This spec adopts 150–200k everywhere.
**Three** live user-facing surfaces still quote the old 300–500k band — `skills/fleet/supervisor.md`,
`skills/fleet/SKILL.md` (the `sup-handoff` command row), and `docs/SPEC.md §6` (the Handoff row) — all
**doc-sync collisions** (§12), not changes this write-set makes:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "500k" skills/fleet/SKILL.md docs/SPEC.md
skills/fleet/SKILL.md:1
docs/SPEC.md:1
```

### 11.2 Measurement source — stated with a receipt, and it is inadequate

"Supervisor self-monitors its token count" needs a stated measurement source. **What fleet records
today about a session's token usage is per-turn, and it does not record context-window occupancy at
all.** The Stop-hook outcome record captures `input_tokens` and `output_tokens` from the last assistant
turn's `message.usage`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '220,223p' bin/hooks/stop_outcome.py
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "session_id": sid, "kind": "result", "result_text": text,
                  "input_tokens": tokens_in, "output_tokens": tokens_out,
                  "model": model, "transcript_path": transcript_path}
```

It records neither the cumulative context occupancy nor any of the three per-turn prompt-token
summands. **B2 correction:** context-window occupancy is not a single field — Anthropic per-turn usage
splits the prompt three ways, `input_tokens` (uncached) **+** `cache_creation_input_tokens` **+**
`cache_read_input_tokens`, and occupancy is the **sum of all three**. `cache_read_input_tokens` alone is
the substrate's *continuity* signal (does the cached prefix persist across a beat —
native-substrate: *"session context (`cache_read_input_tokens`) provably continuous across beats"*),
**not** an occupancy figure; the earlier draft mis-cited that continuity line as if it justified an
occupancy formula, and dropped `cache_creation_input_tokens` — the one term that grows on exactly the
supervisor's characteristic turn (a large read, a fresh worker digest folded in). On a single 40–60k
creation turn that omission understates occupancy enough to skip the band-entry trigger. The stop hook
records none of the three cache fields:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "cache_read\|cache_creation" bin/hooks/stop_outcome.py
0
```

The statusline surfaces only aggregate `cost_usd`, not any per-session context size:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "cache_read\|context_tokens\|context_window" bin/fleet_statusline.py
0
```

**So there is no adequate shipped source for a supervisor to read its own context occupancy**, and (B3)
no rotation-safe way for it to even *find its own current transcript* — every candidate key is unsafe in
exactly the conditions the band matters. `INCARNATION.session_id` is **stale after any fork-steer**
(claim-nonce §4.5: the three sid-rotation writers are registry-only and *"none touches
`supervisor/INCARNATION`"*, and §5.10(a) keeps it so), and a v1 beat *is* an interface fork-steer (§5.1)
— so resolving through it reads the **retired** body's context. The current turn's outcome record
**does not exist yet** (it is written by the Stop hook, which has not fired mid-turn), and immediately
after a fork-steer there is no record for the new sid at all. The registry record has a fresh sid but an
unstable *name* (B1). `[UNBUILT — owned by the three-tier build slice]`, smallest additive mechanism —
built to be rotation-safe:

- **Resolve the transcript from the running process's own `CLAUDE_CODE_SESSION_ID`**, the one key
  guaranteed fresh for the actor doing the reading: the daemon sets it to the child's *own* sid
  (native-substrate G4), and `current_caller_session()` is exactly that read:

  ```
  # at 235421e56bfd328a7e913e519a1459ccf55918dc
  $ sed -n '826,827p' bin/fleet.py
      sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
      return sid or None
  ```

  So a `[UNBUILT]` `fleet sup-context` helper, **run by the supervisor itself**, reads its own sid from
  the environment, locates its transcript file directly (by sid, not via an outcome record), and returns
  **occupancy = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`** from the last
  assistant `message.usage` (the B2-correct sum), plus the two thresholds (150k / 200k).
- **Specify the absent/stale return: fail toward the band.** If the transcript is missing, unpariseable,
  or the last usage record is older than the current turn, the helper returns **"assume near-band, hand
  off at the next boundary"** — the safe direction for a ceiling nobody else enforces (this composes with
  B4's hard ceiling below). Never returns "plenty of room" on missing data.
- This is a **read**, not a hook, run at a `fleet beat` / checkpoint boundary (consistent with
  poll-on-beat, §9) — no always-on cost.
- **Belt-and-braces:** add `cache_creation_input_tokens` **and** `cache_read_input_tokens` to the
  Stop-hook outcome record (additive schema) so a *third party* — the interface tier via `sup-status`,
  or B4's fleet-side ceiling — can also read the supervisor's occupancy without being the supervisor.
  This is the same one additive-schema change; the outcome record then carries all three summands, not
  the `cache_read`-only half the earlier draft named.

### 11.3 The band drives the existing handoff — with a decidable, fleet-enforced ceiling (B4)

The operator requirement **stands and is not weakened** (manager ruling, 2026-07-23): 150k → hand off at
the next wave/task boundary; 200k → finish the current urgent task, no new work. B4's defect is that the
earlier draft made this *self-enforced discretion* over an *undefined* "urgent" — a supervisor whose
judgement is degrading under context pressure (the exact condition the band exists to catch) could label
every next task "the current urgent task" and never cross into hand-off. The fix makes the ceiling
**decidable** and **fleet-enforced**, not a directive the pressured actor may ignore:

- **"Urgent" is replaced by a decidable predicate fleet can read**: *work already dispatched and not yet
  reconciled* — i.e. a wave whose worker turns are in flight (roster-live or awaiting an outcome record).
  Finishing that is bounded (the workers were already spawned); it is a state fleet reads, not a
  self-asserted importance label. Nothing else qualifies as "the current urgent task."
- **200k is a hard, enforced ceiling, not a directive.** At and above a fixed `H` (the 200k band top),
  `fleet spawn`/`fleet send` **refuse to start new worker turns** for a supervisor caller — leaving only
  the handoff verbs (`sup-handoff-begin/complete/abort`) and reconcile-of-in-flight-work. The enforcement
  reuses B3's rotation-safe resolution: the dispatch verb reads the **caller's** own
  `CLAUDE_CODE_SESSION_ID` (fresh for the acting body, §11.2 receipt), resolves the caller's live
  transcript, computes the B2-correct occupancy, and refuses above `H`. So "zero new dispatches past
  200k" is a fleet refusal, not supervisor good behaviour. `[UNBUILT — owned by the three-tier build
  slice]` — no such ceiling exists today:

  ```
  # at 235421e56bfd328a7e913e519a1459ccf55918dc
  $ grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat" bin/fleet.py
  0
  ```

- **150k is the soft trigger** (hand off at the next wave/task boundary): the `[UNBUILT]` `fleet beat` /
  checkpoint check (§5.2) emits the hand-off directive when occupancy first crosses 150k, and the
  supervisor completes the current wave, then hands off. Between 150k and `H` the supervisor may finish
  in-flight work but the directive is standing; at `H` the refusal makes it unconditional.
- **The handoff itself is unchanged** — the shipped sup-handoff machinery (claim-nonce §6.4:
  `sup-handoff-begin` mints a token, the successor boots via `sup-boot --handoff-inc --handoff-token`,
  `sup-handoff-complete` verifies the token). This spec adds only **when** to trigger it (the decidable
  band) and the **fleet-side refusal** that enforces the ceiling. The successor document +
  hand-control-back-to-interface is the existing ritual; the interface session receives control (it never
  held the claim, so nothing transfers to it — it resumes steering the fresh supervisor body).

---

## 12. Doc-sync owed (write-set is this file only)

Every file below carries text this spec obsoletes or must be reconciled with; **this task edits none of
them** — listed for the build slice / a doc-sync pass:

- **`skills/fleet/supervisor.md`** — quotes the drafted **300–500k** swap band (`:51`); must become
  **150–200k** (§11.1). Also gains the tier-model doctrine (§3) and the swap-trigger rule (§11.3).
- **`skills/fleet/SKILL.md`** (S1) — the `sup-handoff` command row (`:44`) states *"Trigger band: begin
  ~300k tokens, hard-latest 500k"*; a user-facing skill table (sibling of `supervisor.md`) that a
  literal §12 pass would otherwise leave stale. Must become 150–200k.
- **`supervisor/GOALS.md`** — must carry the role→tier table (§3.1), the worker-model allowlist
  (Opus/Sonnet-only, §3.4), the bypass-permission acknowledgement (§10.2), and the swap band. It is the
  operator-owned policy surface this spec routes configurability to.
- **`docs/SPEC.md`** — the **Handoff row (`:261`) carries the obsoleted 300–500k band** (S1) and must
  become 150–200k; §4 registry (a `supervisor`-named worker record + reserved-name rule); §6 the new
  `sup-spawn` choke-point; a new scheduled-task family beyond autoclean (§6); the operator-gate state
  file (§8). Fold in when built.
- **`docs/specs/autoclean.md`** — the generic scheduler adapter now serves a second task family
  (§6.1); the `_fleet_task_is_ours(…, "beat")` coexistence (§6.2); and the supervisor archive/husk
  exemption (§7.2).
- **`docs/OPERATOR-GATES.md`** — the three-tier build slice is itself an open gate (`M-F shape and
  budget`); this spec's own design gate is the next step.
- **`knowledge/lessons.md#2026-07-23-three-tier-inputs`** — the manager's tier-based / provider-agnostic
  refinement is recorded as an addendum (done alongside this draft, per manager instruction).
- **`docs/longcat-fleet-usage.md`** — the reference for §3.3's provider resolution; if `sup-spawn`
  gains a namespace-aware pre-flight (§3.3 `[UNBUILT]`), that how-to gains a supervisor row.

---

## 13. Non-goals

- **Not replacing the human.** The interface tier interprets operator intent; it does not invent
  mandates. Operator gates stay human (§8 routes, never authorizes).
- **Not the claim-nonce mechanism.** INCARNATION v2, the boot verdict order, `sup-release`, handoff-token
  — all owned by `claim-nonce.md`; this spec consumes them and must not redefine them.
- **Not per-worker provider mixing.** A shared-daemon architecture limit (§3.3), not a fleet choice.
- **Not the scheduled beat.** Deferred to v2 by the 2026-07-23 operator decision (§9.1).
- **Not interface-fork *prevention* in v1 (B7).** The split moves the 2026-07-16 fork-divergence class up
  to the interface tier (§5.3), and preventing it would require a claim on the tier the operator's model
  keeps human and claimless. v1 *detects and surfaces* interface-body divergence (provenance warn on
  `send`, §5.3) and bounds its blast radius (operator-gate routing, §8); full prevention is out of scope
  and stated here so the new top boundary is not silently unguarded.
- **Not a fleet provider-env read surface (B8).** Fleet emits a tier alias and lets the daemon resolve
  it; it does not read `ANTHROPIC_DEFAULT_*_MODEL` / `CLAUDE_CONFIG_DIR` (§3.3). No tier-resolution
  pre-flight in v1.
- **Not building during the design gate.** This is a `drafting` spec; the build slice starts only after
  a fresh dual-lens gate and operator ratification.

---

## Appendix A — `[UNBUILT]` proofs (no-match receipts at `235421e5`)

Every prescriptive `[UNBUILT]` claim above is grep-verifiable as absent at this commit. Collected:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "sup-spawn\|cmd_sup_spawn" bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c 'add_parser("beat"' bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "RESERVED" bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "NEEDS-OPERATOR\|needs_operator\|pending-decision\|pending_decision" bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "_doctor_check_supervisor_beat\|supervisor-beat.jsonl\|sup-context\|sup-decision" bin/fleet.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "cache_read" bin/hooks/stop_outcome.py
0
```

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "CLAUDE_CONFIG_DIR\|ANTHROPIC_" bin/fleet.py
0
```

Each `0` proves the named behaviour is not in shipped code at the pin — the `[UNBUILT]` tag is a claim
about the future, receipted as absent in the present.
