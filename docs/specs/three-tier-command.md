# Three-tier command: interface / supervisor / workers — SPEC DRAFT

**Status: spec-of-record — ratified by Altai 2026-07-23** (in-session docket; record
`knowledge/lessons.md#2026-07-23-three-tier-ratified`, ticked in `docs/OPERATOR-GATES.md`; ratified
at `c73ab84` after 5 waves, 3 dual-lens gate rounds + 2 confirmation passes, final break-lens merge
verdict "fit for operator ratification"; the three claim-nonce build-slice prerequisites disclosed
at ratification gate the build, not this status). This document re-drafts the withdrawn PROPOSAL (its full prior text is
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
bind to abstract tiers (`top` / `second` / `third`); a resolver maps tier → concrete model at
dispatch time from what the active provider currently offers. Concrete ids (Fable 5, Opus 4.8) are
**illustrative of today's Anthropic resolution only**, never normative.

**Amended 2026-07-23 (operator, second addendum — wave 3): the supervisor is promoted to the TOP tier,
and its binding is a preference chain rather than a single tier.** The earlier draft put the supervisor
on the second tier; the operator's reasoning for the promotion is a division of labour, not a budget:

| Role | Tier binding | Today's Anthropic example | Owns | Who sets the model |
|---|---|---|---|---|
| Interface session ("CEO") | **top** | Fable 5 | the **long-term goals** — intent, interpretation, spec/brief authoring | the human, in their own foreground session — **fleet never launches it** |
| Supervisor | **top, falling back to second** (§3.5 preference chain) | Fable 5 → Opus 4.8 | **solid plans, details, and splitting tasks** to workers | `fleet sup-spawn --model <tier-alias>` (§7) — resolved from policy, never a constant |
| Worker | second **or** third | Opus **or** Sonnet (operator: **never Haiku**) | executing one bounded task | supervisor's call, per-spawn `--model` |

**Why the supervisor earns the top tier:** planning quality is the scarce resource. The interface tier
holds *what we are trying to achieve over the long run*; the supervisor turns that into *a plan that is
actually correct at the level of detail a worker can execute* — slicing tasks, sequencing waves, judging
whether a result discharges the brief. That is the reasoning-heaviest job in the system, so it gets the
strongest available model, with §3.5's fallback covering the top tier's tighter usage limit.

**The interface tier is outside fleet's launch surface entirely.** Fleet has no verb that starts the
human's session; its tier is advisory (a note in policy that the human should run their top tier). Only
the supervisor and worker tiers are fleet-dispatched, and only those two get a fleet-resolved model —
which is also why §11.3's context ceiling can never apply to the interface (ND1).

### 3.2 The only model surface shipped today is `--model`, and it carries a tier alias

There is no hardcoded model id anywhere in `bin/fleet.py`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "claude-opus\|claude-sonnet\|claude-haiku\|claude-fable" bin/fleet.py
0
```

The invariant is **machine-checked at the built commit, not only at the pin**: the three-tier build
slice added a tier resolver, band/ceiling/archive/provenance surfaces, and the supervisor-shaped name
family — none of it a model id. Re-verified after that work:

```
# at 99bb0d6e101f91f30ce9f3b58e8206952fe3591f
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
"worker tier ∈ {second, third}" at `spawn` is `[UNBUILT — owned by the three-tier build slice]`; until
built it is doctrine in GOALS.md, not a guard. Note the interaction with §3.3(d): on a single-model
provider the "Opus or Sonnet" rule is moot — the namespace has one model — so the allowlist is
Anthropic-namespace policy, not a universal invariant.

### 3.5 The supervisor's tier binding is a PREFERENCE CHAIN, not a single tier (operator, wave 3)

**Operator, binding:** the top tier's usage limit is roughly **half** the standard limit, so binding the
supervisor to it outright would park the campaign's manager twice as often. The binding is therefore a
**chain**: the supervisor **prefers the top tier and automatically falls back to the second tier when
the top tier's usage limit is hit, returning to the top tier once the reset horizon passes.**

**Tier order (policy, in `supervisor/GOALS.md`, never a code constant):** `[top, second]`. Today's
Anthropic resolution: `[Fable 5, Opus 4.8]`. A chain of length 1 is legal (no fallback); the chain is
per-namespace, so a single-model provider (§3.3) collapses it to one entry and the mechanism is inert.

#### 3.5.1 Why a fallback is necessarily a NEW session — the constraint that shapes everything else

Two shipped facts decide the mechanism, and they point the same way:

1. **The model is fixed at spawn.** `--model` is a dispatch-time argv flag (§3.2 receipt); `send` has no
   `--model` (§5.2 receipt). No verb re-models a live session.
2. **`resume-limited` resumes the *same* session and therefore cannot change tier — and, equally
   important, is *not* a context reset.** Its native path dispatches with `resume_sid=old_sid`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '3909,3912p' bin/fleet.py
        result = dispatch_bg(
            name, cwd, body, mode, model=model, category=category,
            hint="resume past limit", resume_sid=old_sid,
            setting_sources=setting_sources, run=run, which=which, sleep=sleep,
```

A `--bg --resume` dispatch **forks and carries the entire prior transcript forward** (native-substrate
G2, CONFIRMED) — so the resumed body keeps its context *and* its model. `resume-limited` is the
right recovery for *"the same tier is available again"*; it is **not** a tier-change mechanism.

**Therefore a tier fallback is a body change**: a fresh session dispatched at the other tier, i.e. the
respawn/handoff path, which mints a fresh record and so a fresh context:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '4367,4368p' bin/fleet.py
        new_record = new_worker_record(
            None, cwd, task_for_record, mode, model=model,
```

**Read that receipt precisely (ND8 correction).** An earlier draft introduced it as the respawn path
*"taking `model` as a dispatch-time argument"*. **It does not.** The `model` passed at @4367 was read
out of the *prior* record a few lines above, unconditionally:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '4309p' bin/fleet.py
    model = before.get("model")
```

and `respawn`'s parser offers no `--model` to override it — note the contrast with its two neighbours,
which *do* get carry-forward-or-override treatment:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8878,8891p' bin/fleet.py | grep -c -- "--model"
0
```

So the receipt proves the model is **carried**, never that a respawn can **set** it. Stated correctly:
**the record carries a model; a tier fallback needs the *dispatch* to override it, and no shipped verb
does.** That gap is what §3.5.3 must design against rather than assume away — and it is why the third
body change (a fresh spawn at the fallback tier) is the shape the fallback actually needs.

This is not a limitation to work around — it is what makes §3.5.4's band interaction clean.

#### 3.5.2 The mechanism, on the shipped usage-limit machinery

**Detection and parking already exist; the return logic does not** (ND7 — the earlier draft's *"every
input the chain needs already exists"* overstated the receipts, and the overstatement is corrected below
rather than trimmed). Limit detection is the G11 transcript-tail scan (limit walls are silent — no Stop
hook, no roster change, §4.1), and the park records a **reset horizon**:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '1920,1924p' bin/fleet.py
        is_limit, reset_at, kind = scan(sid, transcript_path=path)
        if is_limit:
            updated["status"] = "limited"
            updated["limit_reset_at"] = reset_at
            updated["limit_kind"] = kind
```

and the horizon gate that decides when a parked body may return:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '1635,1640p' bin/fleet.py
    """True iff a `limited` record's limit_reset_at is set AND now >= it. A null
    horizon returns False (never auto-eligible -- needs an operator-set reset or
    --force-now)."""
    reset = record.get("limit_reset_at")
    if not reset:
        return False
```

**Detection is per-session, and that bounds what the chain can know.** The scan is a per-session
transcript read (`scan(sid, transcript_path=path)` in the receipt above), so fleet learns *"**this
session** hit a wall"* — never *"the top tier is exhausted."* **A tier limit and an account-wide limit
are therefore indistinguishable to fleet.** If the wall was account-wide, the fallback dispatches a
fresh second-tier body that limits immediately; that costs one body change to discover, after which
step 4 handles it correctly. No shipped surface reports remaining usage per tier, so this is a real
limit of the substrate, not an omission to be designed around.

The chain, `[UNBUILT — owned by the three-tier build slice]`:

1. **Detect.** The supervisor's body hits the top tier's limit → existing detection parks it
   `status="limited"` with `limit_reset_at` (above). No new detection is needed; the supervisor is a
   fleet worker record (§10.2), so this fires for it exactly as for any worker.
2. **Fall back — driven from OUTSIDE the parked body (ND6).** See §3.5.3: the trigger is precisely the
   state that disables the predecessor, so the successor at the fallback tier is dispatched by the
   **interface tier**, not by the supervisor handing itself off. The new body records **which tier it is
   on** and **the horizon it is waiting out** (`tier_preferred`, `tier_current`, and the inherited
   `limit_reset_at` — additive registry fields).
3. **Return.** Once `limit_reset_at` passes, the supervisor's *next* body change (§3.5.4) is dispatched
   at the preferred tier again. **The return is not itself a trigger for a body change** — it is a
   preference consulted at the next boundary that was going to happen anyway. This is deliberate: a
   forced respawn purely to climb back a tier would throw away a live plan's context to buy model
   quality it does not yet need.
4. **Both tiers limited** ⇒ no fallback remains; the supervisor stays parked `limited` on the existing
   machinery and the interface tier is nagged (§8's routing surface is the natural place). The chain
   never invents a tier below the policy list, and never silently downgrades to a worker-only tier.

**The return logic is NEW code, not existing input (ND7).** The earlier draft said *"every input the
chain needs already exists"* — that **overstates the receipts**. `limit_reset_at` exists, but shipped
code consults it only for records whose status *is* `limited`:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '2162p' bin/fleet.py
            "resume_eligible": status == "limited" and _limit_reset_passed(rec),
```

The chain puts an **inherited** horizon on a *running* second-tier body — a record whose status is
`working`/`idle`, which this machinery never examines. So detection and parking are existing input;
**the return is entirely new logic.** Related and also unhandled by the earlier draft: a **null horizon**.
`_limit_reset_passed` returns `False` forever when `limit_reset_at` is absent (*"never auto-eligible —
needs an operator-set reset or `--force-now"*, receipt above), so a top-tier limit parked **without** a
horizon would strand the supervisor on the second tier permanently with nothing nagging. **Binding:** a
null inherited horizon must raise the §8 operator-gate routing surface rather than silently becoming a
permanent demotion.

**Failure direction:** if the tier cannot be resolved (§3.3's provider-lacks-a-tier case) the fallback
**omits `--model`** and lets the namespace default govern, rather than refusing — a supervisor that
cannot dispatch is worse than one on an unexpected model, and the daemon's own refusal (§3.3) still
bounds the wrong-model case loudly.

#### 3.5.3 ND6 — the fallback cannot be performed BY the parked body, so it is driven from outside

**The defect this section exists to fix.** The earlier draft bound the fallback to the handoff ritual.
That ritual must be run **by the claim-holding body** — `cmd_sup_handoff_begin` is one of the five
`_require_claim_holder` callers:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8492p' bin/fleet.py
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
```

But the chain's only trigger is the usage limit, and hitting it parks the body `limited` — after which
fleet refuses to give it a turn at all:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '3681,3687p' bin/fleet.py
        if status == "limited":
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(
                f"{name}: parked (limited) -- use `fleet resume-limited {name}` "
                "instead (never steer a parked worker)"
            )
```

**So at the exact moment the fallback fires, the predecessor cannot be steered, cannot run
`sup-handoff-begin`, and cannot write a successor document or mint a handoff token.** The other routes
are shut too: a **bare respawn** mints a body that holds no generation (claim-nonce §5.10(b)), so its
`sup-boot` finds the holder either roster-live (⇒ `refuse`) or roster-gone with a *fresh* heartbeat — the
limited body was working seconds ago — which is `freeze`, not `seize`, and seizure waits out
`SUPERVISOR_CLAIM_STALE_SECONDS` (3600s). **`sup-release` by the holder** hits the same wall, and
claim-nonce §6.3 deleted the non-continuity escape, so no other actor may release for it (B5, on a new
path). A ritual that cannot run is not a design.

**The redesign, in three parts:**

**(a) The fallback is dispatched by the interface tier, not by the supervisor.** The interface is the
one actor that is never parked (it holds no claim, is outside fleet's launch surface, §3.1) and it
already observes the supervisor's state through `fleet status` / `sup-status`. On seeing the supervisor
parked `limited` with a horizon, the interface dispatches the successor at the fallback tier
(`sup-spawn --model <second-tier>`). This keeps v1 consistent with the rest of the design — beats are
interface-originated (§5.1), fleet is pull-only — and it is honest about what "automatic" means here:
**the tier *selection* is automatic; the *dispatch* needs the interface tier to act**, because the party
that would otherwise act is disabled by the very condition being handled. A `fleet sup-fallback` verb
that performs the same sequence in one step is the natural v2 automation, `[UNBUILT]`.

**(b) The successor is seeded from what survives the body — and the working plan is what is lost.**
Because the predecessor cannot write a successor document, the successor boots from the durable
artifacts only: `supervisor/GOALS.md`, the append-only `supervisor/JOURNAL.md`, its last checkpoint, and
the worker journals. **Stated plainly, as the worst case: the in-flight working plan — everything the
parked body had reasoned out since its last checkpoint but not written down — is LOST.** No mechanism
recovers it, because the body that holds it cannot be given a turn to write it out.
**Mitigation, and it is doctrine rather than machinery:** the supervisor checkpoints its plan to the
journal at each wave boundary (`sup-checkpoint`, which also refreshes the heartbeat), so the loss window
is bounded to **one wave** rather than to the whole campaign. That is the real reason the checkpoint
cadence matters, and it belongs in `supervisor/GOALS.md` (§12).

**A limit landing *mid-handoff* leaves stranded state the seeding must clear (ND9).** If the wall hits
while a handoff is already in flight, the predecessor is parked holding an **open
`supervisor/HANDSHAKE`** — and it can neither finish nor undo the ritual, because `sup-handoff-abort` is
*also* a `_require_claim_holder` caller:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8654p' bin/fleet.py
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
```

So the artifacts the interface-driven fallback must handle are not only the ones it *reads*: the seeding
step **clears a stale `HANDSHAKE` and the doctor-visible abort flag**, and stops the orphaned successor
that the interrupted handoff may already have dispatched (it will otherwise sit out its poll window and
end `HANDOFF-ORPHAN`). The claim-nonce prerequisite in (c) must therefore cover a holder parked
**mid-handoff**, not merely a holder parked idle. Narrow window — but it is exactly the stranded state a
loss statement exists to enumerate, and §3.5.4's *"one body change satisfies both"* assumes the two
triggers arrive sequentially rather than overlapped.

**(c) The claim transfer needs a claim-nonce change, filed as a prerequisite — not invented here.**
Even interface-driven, the successor still meets `sup-boot`'s verdict order, which today offers only
`refuse` or an hour-long `freeze` against a parked predecessor. The clean fix is to make **holder parked
`limited` with a recorded horizon** an authorized claim-transfer state: unlike roster-gone — which is
G9-ambiguous, and is exactly why the freeze exists — `limited` is a **fleet-observed, unambiguous** state
that fleet itself wrote. A successor should be able to take the claim immediately, with a distinct
journal kind recording that it was a limit transfer rather than a seizure.

> **Prerequisite (owned by the claim-nonce build slice, not this one):** add a `limited`-holder branch to
> the `sup-boot` verdict order authorizing immediate transfer when the recorded holder's registry status
> is `limited` with a horizon — **including a holder parked mid-handoff**, i.e. one whose `HANDSHAKE` is
> still open (ND9), since that body can neither complete nor abort the ritual it started. This is a
> boot-order change, and **this spec does not own the boot verdict order** — filed exactly as B6's rule-1
> guard and §10.2's `FLEET_WORKER` refusal already are.

**STATUS — BUILT (verified by the three-tier build slice, 2026-07-24).** The claim-nonce slice shipped
this prerequisite: `supervisor_claim_decision` gained verdict `1b`, a `limited`-holder branch that
authorizes immediate transfer (`limit-transfer`, RC 0) when the holder is parked `limited` **with a
horizon** and is not itself resumable, ordered **ahead of** the roster-liveness refuse (rule 2) so a
still-roster-live parked body is reached at all. The behaviour matches this section verbatim, the
`HANDSHAKE`-agnostic mid-handoff clause included (the branch consults only the fleet-observed `limited`
status via `_holder_is_limited`, never the handshake, so a body parked mid-handoff transfers too — the
stale-`HANDSHAKE` *seeding* cleanup remains the interface-driven fallback's job, `[UNBUILT]` v2, §3.5.3a).
Pinned to the build slice's base commit, where the merged branch is present:

```
# at 31a21f871e643e20f784048b7e80460986eaefce
$ sed -n '8506p;8563p' bin/fleet.py
      1b. holder parked `limited` with a horizon, and not resumable
    if holder_limited and not resume_ok:
```

**(d) The dispatch needs a `--model` override and the reserved name — neither exists today (ND8).**
There is **no shipped path from "parked on the top tier" to "running on the second tier."** `respawn`
inherits the model unconditionally and offers no override (§3.5.1's receipts), so
`fleet respawn supervisor` would mint a fresh body **on the same tier that is limited** — burning the
in-flight plan *and* landing back on the exhausted tier. That is strictly worse than doing nothing, so
it is **withdrawn as a remedy**: a bare respawn is a context-reset lever, never a fallback. The other
route — a fresh spawn at the fallback tier — collides with the reserved name (§10.3), because the parked
predecessor's record still holds it:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '2815p' bin/fleet.py
        validate_name(args.name, existing=data["workers"].keys())
```

**Binding, and cheap because `sup-spawn` is `[UNBUILT]` anyway:**

- **`sup-spawn` takes an explicit `--model <tier-alias>`.** It is the fallback's dispatch verb, so the
  tier must be settable at dispatch, not inherited. (`dispatch_bg` already accepts `model` — §10.1 — so
  this is a parser-and-pass-through, not new plumbing.)
- **The parked predecessor's record must yield the reserved name before the successor takes it.** Two
  admissible shapes, and the build picks one: *replace* the record in place (the successor becomes the
  `supervisor` record, the parked sid moving to `retired_sids`), or *rename the parked record to a husk*
  and let the sweep collect it once it is no longer the live claim-holder (§7.2's predicate already
  stops protecting it at that point). Either way the reserved-name check must see the name free, and
  the parked body's own tombstone obligation (§10.4) still applies.
- **If option (i) is ever to be usable at all, `respawn` needs the same `--model` carry-forward-or-
  override treatment its `--setting-sources` / `--token-ceiling` neighbours already have.** Recorded as
  the smaller alternative; the `sup-spawn` route above is the one this spec specifies.

**Until the claim-nonce prerequisite and (d) ship, the arm degrades — and the spec says which cost is
paid rather than mandating an unrunnable ritual.** The honest v1 menu is now **two** options, not three:
**(i) fall back via a fresh `sup-spawn` at the second tier** — available only once (d) ships — losing the
in-flight plan (bounded to one wave by (b)'s checkpoint doctrine) and accepting the `freeze` window
unless the predecessor's heartbeat has aged out; or **(ii) wait out the horizon** and `resume-limited`
the original body, which keeps the plan *and* the tier but stalls the campaign until reset. Neither is
free. (i) is right when the horizon is long and the plan is cheap to rebuild; (ii) when the reverse.
**With neither (d) nor the prerequisite built, (ii) is the ONLY working option** — which is worth stating
plainly, because it means today's honest answer to a top-tier limit is *wait*, not *fall back*.
**The operator asked for an automatic fallback; what v1 can honestly deliver without those two pieces is
an automatic tier *choice* with an operator-visible cost at the moment of the fall.**

#### 3.5.4 Interaction with the swap band — a fallback body change IS a band handoff

The question the operator asked to have answered explicitly: *a fallback respawn is also a context
reset — does it count as the band handoff?* **Yes, and the two must be treated as one event.**

- A tier fallback is a body change with a **fresh context** (§3.5.1). That is precisely what the
  150–200k band's handoff exists to produce. Performing a fallback and then *also* demanding a separate
  band handoff would burn two context resets for one need.
- **So: a tier fallback discharges any outstanding band obligation**, and conversely a band handoff that
  happens while the top tier is limited is dispatched at the fallback tier. Whichever trigger fires
  first, **one** body change satisfies both.
- **Which ritual it uses depends on which trigger fired — and only one of the two can choose (ND6).**
  - **Band-triggered** (occupancy crossed the band while the body is *healthy*): the predecessor can
    act, so it runs the **full handoff ritual** — the successor document carries the working plan across
    the reset. This is the good case and it is unchanged.
  - **Limit-triggered** (the fallback): the predecessor is parked and **cannot act at all** (§3.5.3), so
    the handoff ritual is unavailable and the successor is seeded from the durable artifacts only, with
    the in-flight plan lost back to the last checkpoint. The earlier draft's *"it must go through the
    handoff ritual, not a bare respawn"* is **withdrawn for this arm**: it mandated the one thing the
    trigger makes impossible.
  - **Consequence worth acting on:** when both are approaching, **hand off on the band before the limit
    arrives** — a band handoff is a clean transfer, a limit fallback is a lossy one. That is a real
    argument for treating the 150k soft trigger as a deadline rather than a suggestion.
- **The band's ceiling (§11.3) does not block a band-triggered handoff**: the handoff verbs are exempt
  above `H`, and the handoff dispatch hand-rolls its own argv (§10.1), so a supervisor that is both
  over-band and still healthy can always hand off. (The limit-triggered arm never reaches the ceiling
  question — a parked body issues no dispatches.) This is the deadlock the two mechanisms could otherwise
  have created, and it is closed by the same exemption that closes ND2.

---

## 4. Item 4 — substrate re-pin FIRST: daemon-lifecycle assumptions and the beat's G9 behaviour

**Adjudication item 4** binds this spec to state its daemon-lifecycle assumptions against
`native-substrate.md`'s rows, and to state the beat's G9 behaviour explicitly: *a stale roster
currently PASSES the epoch check; a beat is a `send`, and `send` refuses under a suspicious roster —
scheduler ignores exit codes ⇒ silently dropped beats.*

### 4.1 Daemon-lifecycle assumptions, stated against the contract rows

This spec assumes the substrate exactly as `native-substrate.md` observes it, and **changes no verdict
there**. *(Status corrected in wave 3: when this section was written every row read
`[PENDING OPERATOR RATIFICATION]`. `main` has since merged the second docket's* ***partial ratification***
*— the rows are now `RATIFIED 2026-07-23`* ***except*** *three dead-daemon manager-report-only claims
carrying `RATIFICATION WITHHELD 2026-07-23` pending a quiet-machine capture. The correction matters in
this spec's favour and is stated rather than silently inherited:)*

```
# live: ratification status is a property of the working tree, not of this spec's pinned commit
$ grep -c "PENDING OPERATOR RATIFICATION" docs/specs/native-substrate.md
0
```

**None of the three withheld claims is load-bearing here.** They are the dead-daemon `rm` message, its
`stop` twin, and *"rm/stop do not revive the daemon"*. This section leans on the **ratified** halves —
the transient daemon's idle-exit (`live_workers=0`, 15/15), the residual `cause=upgrade` vector, G7's
`ScheduleWakeup` behaviour, the 2.1.216 wedge, and G10's tombstone obligation. Where §4.1 says a wedged
daemon means beats silently do not run, that rests on the wedge row (ratified), not on any withheld
dead-daemon string:

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

**B1 fix (CRITICAL — the exemption must not be keyed on a static name).** The first-generation
supervisor is spawned by `sup-spawn` under the name `supervisor` (§10.3), but the operator's model
respawns and hands it off "constantly" (§1), and the shipped handoff dispatches its successor under a
**pipe-delimited** name, `f"sup|{successor_inc}|successor"`, which nothing renames back to
`supervisor` — `sup-handoff-complete` transfers the INCARNATION claim only, and registry records are
independent:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '8522p' bin/fleet.py
    name = f"sup|{successor_inc}|successor"
```

So a `name == "supervisor"` equality protects generation 0 and **no successor** — after the first
swap (which §11's 150–200k band makes routine, not exceptional) the live claim-holder runs under
`sup|<inc>|successor`, the exemption misses it, and the 24h-vs-23h collision is live again against the
actual running manager. **The exemption is therefore keyed on *is this record the current live
supervisor claim-holder*, under any name, not on a static registry name.**

**The predicate**, `[UNBUILT — owned by the three-tier build slice]`: a record is protected iff its
`session_id` (or a member of its `retired_sids`) equals `supervisor/INCARNATION`'s
`incarnation_id`-body — i.e. the record is the body that currently holds the claim — **holder alone**.
*(Amended 2026-07-24 by operator: the ratified text read "and that body is roster-live". That conjunct
made this gate a no-op — `_archive_eligible` gate 3 already refuses every roster-live record — and
failed to close this section's own disaster case, an idle/roster-gone claim-holder crossing the 24h
TTL. Built as holder-alone in `5a8860b`; the divergence was disclosed in
`docs/proposals/GOALS-tier-chain-proposal.md` rather than edited unilaterally by the build.)*
Concretely: read `read_incarnation()`; protect the registry record whose sid is the
claim's restamped `session_id` (claim-nonce restamps `session_id` on every validated `sup-*` write, so
the claim tracks the acting body). Two directions, both mandatory:

- **Protects the running manager under any name** (closes B1): a successor named `sup|<inc>|successor`
  that holds the claim is exempt — roster-live or not.
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
  stamps `FLEET_WORKER=<name>` — the worker's **name**, not the value `1`. *(Corrected by the three-tier
  build slice per the claim-nonce §13 disclosure: earlier drafts of this line read `FLEET_WORKER=1`; the
  code of record `_worker_env` (`bin/fleet.py`) writes `env["FLEET_WORKER"] = name`, and the shipped
  refusal keys on that name — an arm keyed on the value `1` would be a no-op. The receipt at §11.4
  (`env["FLEET_WORKER"] = name`) already pasted the correct line.)* The `FLEET_WORKER` stamp matters:
  claim-nonce §6.5 requires a `FLEET_WORKER` refusal in `_require_claim_holder` (a worker turn must not
  hold the supervisor claim), filed there as a separate shipped-code prerequisite — and because that
  refusal keys on the **name** and exempts only a **supervisor-shaped** value, `sup-spawn` must dispatch
  the supervisor body under a name the shipped `_is_supervisor_shaped` predicate accepts (today only the
  handoff-successor shape `sup|<inc>|successor`), or the supervisor would be refused its own claim. The
  supervisor is spawned as a fleet worker, so this spec depends on that refusal existing — and on that
  name/shape reconciliation — before `sup-spawn` is safe.

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

So the honest design rule (`[UNBUILT]`), in two arms **with a bounded transition between them**:
  - **Body responsive:** `kill supervisor` **steers the body to release itself** — it delivers a
    `sup-release` turn to the supervisor (which holds its own nonce), waits **at most `T_release`** for
    `supervisor/INCARNATION` to read `released`, then stops the body. This is a *graceful stop*, not an
    unattended kill, and the successor boots clean off the `released` record.
    ⚠ but see the B6 window below — the stop must complete before any successor consumes the record.

**ND3 fix (MINOR) — arm 1 is bounded and always falls through; it never hangs.** The self-release
steer can fail to land in ways `kill` cannot distinguish from a slow turn: `send` **refuses under a
suspicious roster** (§4.3's receipt — the G9 refusal is a `FleetCliError`, not a delivered steer), the
body can accept the steer and error inside the turn, or it can be wedged. An unbounded *"waits for the
record to read `released`"* therefore lets `kill supervisor` hang instead of falling to arm 2.
**Binding:** arm 1 takes a bounded wait `T_release`, and the shipped handoff bound is the precedent for
its shape — "how long a supervisor-protocol turn may take before the caller gives up":

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '7919p' bin/fleet.py
SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0   # T: handoff wait before abort (spec §4)
```

An immediate `send` refusal fails over at once, without waiting out `T_release`. On timeout **or**
immediate refusal, `kill` **stops the body anyway and falls through to arm 2** — announcing which arm
it took, because the two have materially different recovery costs (clean successor boot vs.
up-to-one-hour freeze). `kill` never blocks indefinitely on a supervisor that cannot answer.

  - **Body unresponsive / already gone / arm-1 timed out:** self-release is impossible, so `kill supervisor` falls to the
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

## 11. The self-monitored context band — supervisor AND workers (operator req 2026-07-23, extended wave 3)

**Operator, binding:** the supervisor self-monitors its context; band **150–200k tokens**. Entering the
band → hand off at the next wave/task boundary. Past 200k → strongest directive to hand off, but finish
the current *urgent* task first (no new work). Handoff ritual = the existing sup-handoff machinery
(write the successor document, hand control back to the interface session).

**Extended 2026-07-23 (operator, third docket + second addendum — wave 3): the same 150–200k band
applies to WORKERS.** A worker self-monitors its context; entering the band → hand off / respawn at the
next **task** boundary. The operator's rationale is not spend but drift: *unbounded worker counts and
contexts drift the parts apart and the waste reappears as reconciliation effort* — keep worker counts
small and respawn before a context gets expensive. §11.4 states the worker arm; the mechanism is shared
with the supervisor arm, and **every "supervisor only" / "second tier only" scoping in the earlier draft
is retired by this extension** (§11.3's ND1 gate is re-stated accordingly — it scopes *the fleet-enforced
refusal*, which is a different question from *who observes the band*; see §11.4).

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
- **200k is a hard, enforced ceiling, not a directive** — **and it applies to exactly one caller.** At
  and above a fixed `H` (the 200k band top), `fleet spawn`/`fleet send` **refuse to start new worker
  turns** when — and only when — the caller **is the current supervisor claim-holder**. The enforcement
  reuses B3's rotation-safe resolution: the dispatch verb reads the caller's own
  `CLAUDE_CODE_SESSION_ID` (fresh for the acting body, §11.2 receipt), resolves the caller's live
  transcript, computes the B2-correct occupancy, and refuses above `H`. So "zero new dispatches past
  200k" is a fleet refusal, not supervisor good behaviour.

  > **ND1 fix (MAJOR) — the ceiling MUST carry a supervisor-identity gate; a caller-agnostic occupancy
  > refusal would silence the human's control channel.** An occupancy ceiling keyed on *"any caller above
  > `H`"* fires on the **interface session** too: the interface issues `fleet send supervisor …` (the v1
  > beat, §5.1), it is the tier the operator's model deliberately keeps long-lived (*"saves its context
  > for talking, interpreting, and long-term ideas"*, §1), and it is **outside fleet's launch surface**
  > (§3.1) — fleet cannot hand it off, respawn it, or reset it. A caller-agnostic refusal would therefore
  > block the human's only steering verb once the interface's own context passed 200k, **with no
  > recourse**.
  >
  > **Wave-3 restatement (the earlier basis is retired).** The first version of this paragraph justified
  > the exemption with *"the operator set the band for the second tier only"* — that scoping is **retired**:
  > the band now applies to the supervisor **and** to workers (§11, §11.4). The exemption's real and
  > durable basis is **recourse and dispatch**, not tier: (a) the interface is outside fleet's launch
  > surface, so a refusal it cannot escape has no remedy; and (b) workers, who *do* observe the band, are
  > not refused here either — they do not call `spawn`/`send`, so there is nothing to refuse. Their band is
  > enforced by respawn at a task boundary (§11.4), not by a dispatch ceiling.
  >
  > **Binding for the build:** the refusal predicate is *caller-is-the-supervisor-claim-holder* — the
  > same `CLAUDE_CODE_SESSION_ID` vs `supervisor/INCARNATION` resolution B1 uses for the archive
  > exemption and B3 uses for the occupancy read (one identity concept, three consumers). **The interface
  > tier is explicitly exempt: it has no fleet-enforced band, and no fleet verb may refuse it on
  > occupancy.** A caller that holds no claim is never subject to the ceiling. Workers are likewise
  > unaffected — they do not dispatch.

- **Past `H`, what remains is deliberately narrow, and reconcile is READ-ONLY (ND2 fix).** Above the
  ceiling the supervisor may run: the handoff verbs (`sup-handoff-begin` / `-complete` / `-abort`), and
  **read-only** reconciliation of already-dispatched work — `fleet status`, `wait`, `result`, `peek`
  (outcome/roster reads). It may **not** issue a `fleet send` to "steer an in-flight worker to wrap up":
  that send is a new worker turn and is caught by the very refusal above, so leaving it implicitly
  permitted would have made the carve-out undecidable. Finishing the in-flight wave therefore means
  *letting it finish and reading its outcomes*, not steering it further. (The handoff dispatch itself is
  not caught: `sup-handoff-begin` hand-rolls its own argv and routes through neither `cmd_spawn` nor
  `dispatch_bg` (§10.1), so a ceiling scoped to `spawn`/`send` cannot deadlock the handoff it exists to
  force.)

  `[UNBUILT — owned by the three-tier build slice]` — neither the ceiling nor the identity concept it
  must be gated on exists today:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat\|SUPERVISOR_BODY_NAME" bin/fleet.py
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

**ND4 fix (MINOR, r3 carry-item) — the identity gate must resolve through `retired_sids`, must fail
toward the band, and gets a structural interface exemption.** Read literally as
`caller_sid == INCARNATION.session_id`, the gate **fails open on exactly the path every supervisor turn
starts with.** claim-nonce §5.10(a) makes the restamp *pull, not push*: `session_id` is restamped only
*"as part of the next validated `sup-*` write"*. So after the interface fork-steers the supervisor (the
v1 beat, §5.1) the body has a **new** sid while `INCARNATION.session_id` still holds the **old** one; if
the supervisor then runs `fleet spawn` above `H` before any `sup-checkpoint`, the gate concludes *"not
the claim-holder"* and **the hard ceiling silently does not fire** — the exact outcome B4 exists to
prevent, failing unsafe. Three bindings close it:

- **(a) Resolve through the registry, not the claim alone.** Use §7.2's predicate shape — match the
  caller's sid against the record's `session_id` **or a member of its `retired_sids`** — because
  `_restamp_after_steer` pushes the old sid into `retired_sids` at steer time, which bridges
  *caller → registry record → claim* across the un-restamped window. Same predicate as B1: one identity
  concept, now three consumers (archive exemption, occupancy read, ceiling gate).
- **(b) Fail toward the band.** If identity is unresolvable, **treat the caller as the supervisor** and
  apply the ceiling — mirroring §11.2's *"assume near-band"* direction. An unresolvable identity must
  never be the reason a ceiling stays dormant.
- **(c) Exempt the interface structurally, with no sid at all.** The interface is not a fleet worker;
  the supervisor is (§10.2). `FLEET_WORKER` is stamped into every fleet-launched child's environment, so
  its **absence** exempts the interface unconditionally — independent of any sid resolution, and
  therefore immune to (a)'s window:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '1284p' bin/fleet.py
    env["FLEET_WORKER"] = name
```

Note (b) and (c) compose safely rather than fighting: (c) exempts the interface *before* (b)'s
fail-toward-the-band default can catch it, so failing closed for the supervisor does not silence the
human's control channel (ND1).

### 11.4 The worker arm of the band (operator, wave 3)

Workers observe the same 150–200k band: a worker self-monitors its context and, **on entering the band,
hands off / respawns at the next task boundary.** Three differences from the supervisor arm, each
following from what a worker is:

- **The boundary is a task, not a wave.** A worker owns one bounded task; its natural reset point is
  that task's completion, not a wave's.
- **The reset is a `respawn`, not a claim handoff.** A worker holds no claim, so none of the
  claim-nonce ritual applies — `fleet respawn` already does exactly this ("same name, cwd, mode; journal
  and drained mailbox carried over" — the shipped context-reset lever) and mints a fresh record
  (§3.5.1's receipt). The worker's continuity lives in its journal and task file, which respawn carries.
- **Enforcement is by the supervisor, not by a dispatch refusal.** §11.3's ceiling refuses `spawn`/`send`
  *for the supervisor caller*; a worker calls neither, so there is nothing to refuse. The worker arm is
  therefore: the worker self-reports occupancy (the same §11.2 `sup-context`-shaped read, which is not
  supervisor-specific — it reads the caller's own transcript), and the **supervisor respawns an
  over-band worker at its next task boundary**. `[UNBUILT — owned by the three-tier build slice]`.

**Why the operator asked for this** (recorded because it is not a spend argument, and reading it as one
would justify dropping it under §11.5's cap doctrine): unbounded worker contexts *drift the parts apart*,
and that waste returns as reconciliation effort on the supervisor. The worker band is a **coherence**
control — small worker counts, fresh contexts — of a piece with the supervisor band, not a budget cap.

### 11.5 Reconciliation with the third-docket cap doctrine — SETTLED (operator ruling, 2026-07-23)

The third docket established a standing doctrine that appears, on its face, to collide with §11.3's
fleet-enforced ceiling: **"no fleet-enforced token or USD ceilings — for workers or managers"**, with the
plan's own usage limits as the cap for every session alike, fleet's limit-park/resume as the recovery
path, and cost/token *counting* demoted to a flag, default off
(`docs/OPERATOR-GATES.md` §Settled, M-F budget envelope tick; `knowledge/lessons.md#2026-07-23-operator-decisions-caps`).

**This is decided, not pending** — and the decision is witnessed in-tree, not by this document. The
manager's reading was put to the operator and **confirmed**; the ruling is recorded as the **third
addendum** to `knowledge/lessons.md#2026-07-23-three-tier-inputs` (the same anchor whose earlier text
said the operator *"rules on it at ratification"* — this addendum is that ruling):

```
# live: a claim about the working tree's recorded operator decisions, not about this spec's pinned commit
$ grep -c "Third addendum (2026-07-23, operator ruling on the cap-doctrine reading)" knowledge/lessons.md
1
```

> **Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — **cost/spend
> ceilings are gone unless the counting flag puts them back** (flag default off; enabling it may re-arm
> spend caps). The context band (150–200k, supervisors AND workers) is a freshness mechanism, not a
> budget, and its enforcement stays. **Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before
> ratification.**

*(Wave-4 note, recorded because the process is the point: wave 3 wrote this section SETTLED while the
addendum existed only on `main`, so for one wave this spec was the sole witness to a ruling that binds
it — correctly caught as ND5/W1. The ruling was genuine and has since merged; the citation above is now
self-verifying, which is what it should have been before the framing changed.)*

So the doctrine reads, as settled: a token/USD ceiling answers *"has this session cost too much?"* — and
the plan's own usage limit already answers that, for everyone, so fleet adds no second budget authority.
A context band answers a different question, *"is this session still sharp?"*, and its remedy is a
handoff to a fresh body, never a stop. That is why the same operator extended the band to workers
(§11.4) in the very docket that retired the spend caps: the two decisions are consistent because they
are about different things.

**What this settles for B4's arm — retained, with one boundary made explicit:**

- **§11.3's context ceiling STAYS**, supervisors and workers alike (§11.4 for the worker arm's different
  enforcement shape). It is denominated in **context occupancy** and its only consequence is **hand off**
  — never *stop*, *kill*, or *refuse-until-cheaper*. Nothing structural changes; the earlier draft's
  contingency branch ("if the operator rules the other way, the band becomes advisory") is **withdrawn**,
  since the operator ruled.
- **Any spend-denominated refusal surface may exist ONLY behind the counting flag, default off.** With
  the flag off there is no fleet-enforced token or USD cap for any tier; enabling it is what may re-arm
  one. This spec therefore specifies **no** spend-denominated refusal at all — an important negative:
  §11.3's ceiling must not be implemented by reusing, extending, or re-denominating the spend machinery,
  or it would silently inherit the flag's off-by-default state and stop firing.

What the doctrine *does* retire is the **`--token-ceiling` spend denomination** as an always-on
fleet-enforced cap — a real, shipped registry field today:

```
# at 235421e56bfd328a7e913e519a1459ccf55918dc
$ sed -n '858p' bin/fleet.py
        "token_ceiling": token_ceiling,
```

That field's retirement / flag-gating is **not** this spec's slice (it belongs to the queued PLAN §0.4
ceiling-denomination retirement); this spec records only that §11.3 is **not** an instance of it and must
not be swept up with it when that retirement is executed — which is why §12 lists that retirement as
doc-sync owed.

---

## 12. Doc-sync owed (write-set is this file only)

Every file below carries text this spec obsoletes or must be reconciled with; **this task edits none of
them** — listed for the build slice / a doc-sync pass:

- **`skills/fleet/supervisor.md`** — quotes the drafted **300–500k** swap band (`:51`); must become
  **150–200k** (§11.1). Also gains the tier-model doctrine (§3) and the swap-trigger rule (§11.3).
- **`skills/fleet/SKILL.md`** (S1) — the `sup-handoff` command row (`:44`) states *"Trigger band: begin
  ~300k tokens, hard-latest 500k"*; a user-facing skill table (sibling of `supervisor.md`) that a
  literal §12 pass would otherwise leave stale. Must become 150–200k.
- **`supervisor/GOALS.md`** — must carry the role→tier table (§3.1), the **supervisor tier preference
  chain `[top, second]`** (§3.5 — the policy surface the chain is read from, never a code constant), the
  worker-model allowlist (Opus/Sonnet-only, §3.4), the bypass-permission acknowledgement (§10.2), and
  the context band **for both supervisor and workers** (§11, §11.4). It is the operator-owned policy
  surface this spec routes configurability to.
- **`skills/fleet/SKILL.md` + `skills/fleet/supervisor.md` (wave-3 additions)** — beyond the band number:
  the supervisor is now **top tier** with a fallback chain (§3.1, §3.5), and the **worker** band (§11.4)
  needs a home in the worker-facing spawn etiquette, which today says nothing about a worker watching its
  own context.
- **`docs/PLAN.md` §0.4 (ceiling denomination) / the queued C-soak retirement** — §11.5 records that the
  third-docket cap doctrine retires the **`--token-ceiling` spend** denomination but **not** §11.3's
  context band. Whoever executes that retirement must not sweep the context band up with it.
- **`docs/specs/claim-nonce.md` (prerequisite, wave 4)** — §3.5.3(c) files a **third** claim-nonce
  build-slice prerequisite alongside B6's rule-1 guard and §10.2's `FLEET_WORKER` refusal: a
  `limited`-holder branch in the `sup-boot` verdict order, authorizing immediate claim transfer when the
  recorded holder's registry status is `limited` with a horizon — **including a holder parked
  mid-handoff** (ND9). Without it the UL fallback is lossy or slow by construction (§3.5.3). Filed, not
  built here — this spec does not own the boot verdict order.
- **`docs/SPEC.md` §5 spawn/respawn rows (wave 5, ND8)** — `sup-spawn` gains an explicit `--model`
  override (§3.5.3(d)); the reserved name must be yielded by a parked predecessor before a fallback
  successor can take it. If `respawn` also gains `--model`, its carry-forward-or-override note joins
  the existing `--setting-sources` / `--token-ceiling` ones.
- **`supervisor/GOALS.md` (wave-4 addition)** — the **checkpoint-cadence doctrine** of §3.5.3(b): the
  supervisor checkpoints its plan to the journal at each wave boundary, because that cadence is exactly
  what bounds the plan loss when a usage-limit fallback fires. It is the only mitigation available for
  that loss, so it belongs in policy rather than in a reviewer's memory.
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
- **`docs/longcat-fleet-usage.md`** — the reference for §3.3's provider resolution. It gains a supervisor
  row only if a namespace-aware tier-resolution pre-flight is ever built as **separate scope** — which
  §3.3 argues *against* for v1 (it would need the provider-env read fleet disclaims) and §13 records as a
  non-goal. Listed as a conditional consequence of a decision already made the other way, **not** a live
  `[UNBUILT]` deliverable of this slice.

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

## 13.1 Future design note — multi-supervisor campaigns (operator-added 2026-07-24, v-next)

*(Direction, not a v1/v2 commitment: recorded by operator directive so the v1 build does not paint
it out.)* Eventually the top-tier interface session should be able to run **multiple fleet
supervisors at once, as different teams working on different things** — one interface fanning out
to N supervisors, each a team lead owning its own claim, worker set, and workstream (e.g. one team
on a product repo, one on infrastructure, one on a research spike), with the interface
coordinating across teams and arbitrating shared resources (usage limits, machine load, operator
attention). Design consequences v1 should not foreclose:

- The claim file, journal, and `sup-*` verb surface are singletons today (`supervisor/INCARNATION`,
  one claim per fleet home). Multi-supervisor needs either per-campaign fleet homes (works today —
  `--fleet-home` partitioning, zero new machinery, and the concurrent-manager name-prefix
  discipline in `knowledge/` already rehearses it) or a claim namespace keyed by campaign — the
  former is the presumptive v-next path, the latter is a real redesign.
- `sup-spawn`'s gen-0 naming (`sup|<launch-id>|boot`) already mints unique supervisor bodies —
  nothing in the name scheme assumes a singleton; keep it that way.
- The interface-divergence detection (§5.3) and operator-gate routing (§8) are per-fleet-home;
  N supervisors means N provenance streams the interface must keep distinct.
- The 150–200k band binds each supervisor independently; the interface's own occupancy becomes the
  new scarce resource and may need its own doctrine (today: interface is structurally exempt,
  ND4c).

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
