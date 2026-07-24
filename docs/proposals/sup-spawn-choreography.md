# Proposal: `sup-spawn` (§10.1) dispatch choreography

Status: ratified rulings applied — ready for build

Decision record for the `sup-spawn` verb — the gen-0 supervisor dispatch that three-tier
§10.1 leaves `[UNBUILT]` (SPEC:1059, Appendix-A `grep -c "sup-spawn|cmd_sup_spawn"` → 0 at
SPEC:1620–1622). Produced by the `supspawn-design` design pass (branch `design/sup-spawn`,
no code changes). Grounding conventions: `SPEC:` = `docs/specs/three-tier-command.md`,
`CN:` = `docs/specs/claim-nonce.md`, bare `fleet.py:` = `bin/fleet.py`, all at this
worktree's HEAD (`design/sup-spawn`, base `6a25d10`). Prior thinking built on:
`state/journals/tt-build.md` ("REMAINING SCOPE" item 1 + "⚠ CRITICAL FINDING for
sup-spawn").

## 0. Summary of recommendations

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | Name/inc decoupling | **CONFIRM** the successor map: name = `sup\|<launch-id>\|boot`, launch-id minted by `mint_incarnation_id()` purely for the name; the claim's incarnation id is minted independently inside first-turn `sup-boot`. No preset-inc path. |
| 2 | Send-target | No alias record. `"supervisor"` becomes a **logical name resolved at verb time** to the current claim-holder's registry record; physical record is always the pipe name. Needs an operator ruling (amends ratified spec prose). |
| 3 | Dispatch choreography | Replicate `cmd_spawn`'s pre-claim → dispatch → stamp choreography verbatim (incl. fast-completion, DOA rollback, `_commit_launched_turn`, stranded report). Deltas: minted name, shape-validation instead of `validate_name`, forced `cwd=FLEET_HOME`, bypass default mode, resolved model, self-written prompt body. One enabling code change: widen `dispatch_bg`'s name guard to accept supervisor-shaped names. |
| 4 | Boot ritual | Task-file prompt (written by `dispatch_bg` G8) modeled on `_render_successor_task`: `fleet sup-boot` (no handoff flags) as first act; record the printed `NONCE:`; stop dead on refuse/freeze with a terminal-message contract. GOALS arrives via the boot bundle, not embedded in the prompt. |
| 5 | Reserved name | `allow_reserved=True` is **dead for sup-spawn** (pipe name fails `NAME_RE` before the reserved check). Keep the reservation itself: `"supervisor"` survives as the logical target of Q2 and must never become a physical record. Docstring correction needed. |
| 6 | `--model` default | `resolve_model_for_role("supervisor")`; with the GOALS tier-policy block absent (today) it returns `None` → `--model` omitted, daemon default governs. Explicit `--model <tier-alias>` overrides (§3.5.3(d)). Mode default `bypass` per §10.2, `--permission-mode` override via `MODE_FLAGS`. |
| 7 | Failure modes | Six enumerated: DOA, boot-refuse, corrupt claim (freeze), lost nonce, stranded stamp, fast completion. Each with operator surface + recovery path. |
| 8 | Tests | 16 red-first tests incl. 4 fault-injection targets. |

---

## 1. Name/inc decoupling

**Question.** Successor map recommends: mint a launch-scoped id purely for the NAME
(`sup|<launch-id>|boot`); the fresh claim gets its own incarnation id at first-turn
sup-boot; no fresh-claim-with-preset-inc path. Confirm or refute.

### Options

- **(A) Decouple** — name segment is a launch-scoped `mint_incarnation_id()` value with no
  claim meaning; claim inc minted inside `sup-boot` as today.
- **(B) Couple** — pre-mint the claim's incarnation id at sup-spawn time, name the body
  after it, and add a `sup-boot --preset-inc` arm that claims under the given id
  (mirroring the successor path's pre-minted `successor_inc`).
- **(C) No id at all** — a static middle segment (`sup|gen0|boot`), uniquified only by the
  registry's existing-name collision check.

### Recommended: (A) — confirmed

The successor map's reasoning survives contact with every site checked:

1. **The claim inc is minted inside the `claim` verdict arm and nowhere earlier.**
   `cmd_sup_boot` verdict `"claim"` runs `inc = mint_incarnation_id()` then writes the
   INCARNATION dict-literal with `claimed_via: "fresh"`, `nonce_seq: 1`, fresh
   `lineage_id` (fleet.py:9292–9307). A preset-inc path would need a new flag, a new
   verdict arm, and a way to refuse preset-inc collisions — machinery with **no consumer**:
   the enumeration pass (Q2 grounding) found zero code sites that require the body's name
   segment to equal the claim's `incarnation_id`. Every claim-side predicate is
   identity-based via sids (`_caller_holds_supervisor_claim` fleet.py:1878–1932,
   `_record_is_supervisor_claim_holder` :1935–1963), never name-parsed.
2. **The successor precedent does not transfer.** Handoff-begin pre-mints
   `successor_inc` (fleet.py:10407) because the handoff token, HANDSHAKE file and task
   file are all keyed by that inc (`handoff_task_file_path(successor_inc)`,
   fleet.py:8852–8856) — the coupling is load-bearing there. Gen-0 has no predecessor, no
   token, no HANDSHAKE; nothing needs the id before boot (tt-build journal, REMAINING
   SCOPE item 1).
3. **The minted id is a valid middle segment.** `mint_incarnation_id()` returns
   `inc-<YYYYMMDDTHHMMSSZ>-<4hex>` (fleet.py:8859–8861) — no `|`, so it matches the
   family regex's `[^|]+` middle (fleet.py:1313
   `^sup\|[^|]+\|[a-z][a-z0-9-]*$`). Note it contains uppercase `T`/`Z`, so it would fail
   `NAME_RE` — irrelevant, the family regex is the gate that matters (and precisely why
   handoff-begin bypasses `NAME_RE`, fleet.py:10303–10318).
4. **(C) fails observability.** Two sequential gen-0 launches (spawn, DOA-ish failure the
   rollback missed, spawn again) would be indistinguishable in events/outcomes/logs. The
   launch-scoped id gives each *dispatch attempt* a distinct audit identity for free —
   which is exactly what `outcomes/<name>.jsonl`, `mail_sent` targets and journal grep
   need. The role segment `boot` is the one the shipped family comment already names
   (fleet.py:1300–1313: "`sup-spawn` dispatches its gen-0 body under `sup|<inc>|boot`").
5. **Document the non-identity.** The name's launch-id and the claim's inc will differ.
   That is by design: `sup-status` reads `supervisor/INCARNATION`, never the worker name.
   The proposal's task-file text (Q4) and the skill doc should say "the name segment is a
   launch id, not your incarnation id" to pre-empt confusion.

Refuting (B) explicitly: a fresh-claim-with-preset-inc arm would also weaken the claim
protocol's audit story — CN §5.2 (CN:1183) ties `lineage_id` minting to "first fresh
claim", and the §6.1 decision table (CN:1585–1593) is a pure function of claim-file state
+ roster; feeding it a caller-chosen inc adds an input the table was never adjudicated
against. Do not build it.

## 2. Send-target: alias record or pipe-name only?

**Question.** Does sup-spawn also create a `"supervisor"` alias record, or is the
send-target always the pipe-name? (The predecessor's open question.)

### Enumeration of every site addressing the supervisor body by name

Code (bin/fleet.py) — exhaustive:

| Site | What it does | Survives pipe-named gen-0? |
|------|--------------|---------------------------|
| :731–732 | `SUPERVISOR_BODY_NAME = "supervisor"`, `RESERVED_NAMES` | yes — validation-only (Q5) |
| :735–759 | `validate_name` reserved refusal | yes |
| :5395–5398 | archive gate 0 fallback: `name == SUPERVISOR_BODY_NAME or _is_supervisor_shaped(name)` on indeterminate holder | **yes — already shape-widened** |
| :6107–6116 | husk sweep protection | yes — claim-identity, "under any name" |
| :9772–9779 | `_require_claim_holder` worker arm: refuses `FLEET_WORKER` set and not supervisor-shaped | yes for pipe name; **the literal name `supervisor` is REFUSED here** — a body named `supervisor` cannot run any gated `sup-*` verb |
| :10012–10013 | `_interface_divergence` mail-target filter: `target == SUPERVISOR_BODY_NAME or _is_supervisor_shaped(target)` | **yes — already shape-widened** |
| :3204 etc. | `send`/`kill`/`respawn`/`peek` do plain registry-key lookup; `NAME_RE` is enforced only at creation | yes — `fleet send "sup\|<id>\|boot"` works today |

Spec (three-tier-command.md) — the sites that positively assume a record *named*
`supervisor`:

- v1 beat contract: `fleet send supervisor @brief.md` / `"reconcile"` (SPEC:649–650),
  scheduler beat (SPEC:626), fork-diverged interface steer (SPEC:709), band steer
  (SPEC:1364).
- §10.4 lifecycle: `respawn supervisor` / `kill supervisor` (SPEC:469, 1144–1195).
- §10.2 registry bullet: "the supervisor becomes a worker record named `supervisor`"
  (SPEC:1099–1100).
- §10.3 minting story: "supervisor is spawned by `sup-spawn` under the name `supervisor`"
  (SPEC:885, 1137–1139).
- §3.5.3(d) name-yield choreography: "the parked predecessor's record must yield the
  reserved name before the successor takes it" (SPEC:486–491).

Everything else (claim-nonce.md, terminal-surface.md, SPEC.md, skills/, commands/) is
claim-holder-identity-based or prose-only — zero alias dependency (enumeration pass,
2026-07-24).

### Options

- **(A) Alias record** — sup-spawn writes a second registry record named `supervisor`
  sharing the body's sid.
- **(B) Logical-name resolution** — no alias record. Verbs that accept a target name
  resolve the literal `"supervisor"` to the current claim-holder's record: read
  `supervisor/INCARNATION` → `holder_sid` → the record whose `_record_sids` (session_id ∪
  retired_sids, fleet.py:1878+) contain it. No holder / no claim → named error.
- **(C) Spec-prose amendment only** — operators and the interface address the body by its
  actual pipe name (discovered via `fleet sup-status` / `fleet status`); the spec's
  `fleet send supervisor` lines are rewritten.

### Recommended: (B) — logical-name resolution; physical record never named `supervisor`

- (A) is disqualified on registry invariants: two records sharing one sid breaks every
  sid-union identity predicate (`_record_sids` consumers: ceiling identity
  fleet.py:1966–2014, archive exemption :5395, husk sweep :6107), double-counts in
  `fleet status`, and the Stop hook's `_resolve_name`-by-sid becomes ambiguous. The spec
  itself already rejects name-keyed supervisor identity for protection purposes
  (SPEC:897–901: "keyed on *current live supervisor claim-holder*, under any name").
- (C) breaks the v2 scheduled beat (SPEC:626 — a dumb scheduler line `fleet send
  supervisor "beat"` cannot discover a rotating pipe name) and pushes per-generation name
  discovery onto the operator for no gain.
- (B) is small (one resolver, called from `_cmd_send_native`'s target lookup; later reused
  by §10.4's `kill supervisor` / `respawn supervisor` arms), keeps the beat contract's
  spelling stable across generations (gen-0 `sup|<id>|boot` and successors
  `sup|<inc>|successor` resolve identically), and gives a *correct* failure mode: with no
  live claim, `fleet send supervisor` refuses loudly instead of mailing a husk. It also
  retroactively repairs the §10.4 prose: `kill supervisor` was always about the
  claim-holding body, whatever its name.
- Resolution failure semantics: claim absent/released/corrupt → `FleetCliError`
  ("no supervisor claim is held — nothing answers to 'supervisor'; run `fleet sup-status`").
  Holder sid matches no record (stranded-stamp window, Q7e) → same error naming the sid.
  Never guess by shape: two supervisor-shaped records can coexist (predecessor +
  successor mid-handoff); only the claim disambiguates.

This amends ratified prose (§10.2:1099, §10.3:885/1137, §5.3 beat lines) → **operator
ruling 1**. Precedent: the §7.2 holder-alone amendment, where the build disclosed the
divergence and the operator owns the spec edit (GOALS-tier-chain-proposal.md "Operator
follow-ups").

## 3. Dispatch choreography: what replicates, what differs

**Question.** What of `cmd_spawn`'s pre-claim → dispatch → post-dispatch stamp lock with
`_commit_launched_turn` retry (incl. stranded-turn recovery) is replicated verbatim, and
what differs?

### Replicated verbatim (the delicate parts — do not innovate)

Ordered per `cmd_spawn` (fleet.py:3131–3348):

1. `_require_instance_settings()` before any mutation (fleet.py:3189).
2. **Pre-claim under `fleet_lock`** (:3202–3218): `new_worker_record(None, ...)` with
   `session_id=None` as the pre-claim; `record["last_dispatch_at"] = now_iso()`; save +
   `append_event("spawned", ...)` inside the same lock (F4 doctrine).
3. `pre_claim_at = record["last_dispatch_at"]` (:3220) — the fast-completion fence.
4. **Dispatch outside the lock** via `dispatch_bg` (:3226–3232) — spec mandate SPEC:1059–1064
   ("no hand-rolled argv"), reaffirmed at SPEC:1087–1090 ("`sup-spawn`, having no such
   constraint, uses `dispatch_bg` directly").
5. **`except NativeDispatchError`** (:3233–3281): fast-completion scan
   (`_fast_completion_sid`, :3239–3240; stamp only if `session_id is None`, :3245) else
   DOA rollback — pop the record **only if still `session_id is None`** (:3277, never
   clobber a concurrent fast stamp), `spawn_failed` event only when the pop happened,
   re-raise as `FleetCliError`.
6. **`except BaseException`** (:3282–3306): same guarded pop; `short_id` recovered from
   `exc.__notes__` (:3305) into the `spawn_failed` event; re-raise verbatim.
7. **Success**: `_commit_native_stamp` closure (:3311–3328 — stamp
   `session_id`/`native_short_id`/`status="working"`/`turns=1`, save,
   `_append_event_quiet("turn_started")`), driven by `_commit_launched_turn`
   (:2675–2723, 6 attempts, ~30 s backoff, OSError retried); on exhaustion
   `_report_stranded_native_turn` + `return 1` — **no pre-claim pop** (a live session
   exists; re-running would double-dispatch, :3177–3183), recovery via the 600 s
   `_launch_claim_expired` auto-demotion (:1073, :2287–2293).
8. `_write_ceiling_file(sid, ...)` post-stamp (:3336) if a `--token-ceiling` is accepted
   (G6: only writable post-join).

The wedge-retry inside `dispatch_bg` (:8417–8444: `dispatch_wedged` → cleanup → exactly
one redispatch) is **safe for gen-0**, unlike the handoff path (which avoids `dispatch_bg`
partly because a wedge-retry risks two live successors on one pre-minted inc,
fleet.py:10303–10318). Gen-0 pre-mints no claim state: if a cleanup-miss ever produced two
live boot bodies, they race `sup-boot` and the loser gets verdict `refuse` (rule 2,
roster-live holder, fleet.py:9121–9123) — the claim protocol itself is the tiebreak.

### Differs for the supervisor body

| Aspect | `cmd_spawn` | `sup-spawn` | Grounding |
|--------|-------------|-------------|-----------|
| Name | operator-supplied, `validate_name(name, existing=...)` (:3204) | minted: `f"sup\|{mint_incarnation_id()}\|boot"`; validated by `_is_supervisor_shaped(name)` assertion + the same existing-key collision check; **`validate_name` is not called** (pipe fails `NAME_RE`, Q5) | fleet.py:714, 1313, 8859 |
| cwd | `--dir`, must exist (:3191) | forced `FLEET_HOME` (supervisor runs in the fleet repo; handoff-begin precedent fleet.py:10468–10471) | SPEC:1103 |
| Mode | `--mode`, default `dontask` (:10985) | default `bypass` (§10.2 earned-privilege, SPEC:1103); `--permission-mode` override constrained to `MODE_FLAGS` (G3 vocabulary, cf. successor :11175) | Q6 |
| Model | `--model` passthrough | default `resolve_model_for_role("supervisor")`, explicit `--model <tier-alias>` overrides | Q6, SPEC:483–485 |
| Prompt | `compose_prompt(...)` worker preamble (:3224) | self-composed gen-0 boot task body (Q4); `dispatch_bg` writes it to `task_file_path(name)` (G8, :8232–8242) and dispatches the tiny "Read … and follow it exactly" prompt | fleet.py:8232–8242 |
| `spawned_by` | caller sid | same — `current_caller_session()` (interface sid, or None from a human shell) | SPEC:1101–1102 |
| `spawned_by_lineage` | `_spawning_claim_lineage(spawner)` (:3213) | **same call** — it returns the lineage iff the caller currently holds a live claim (fleet.py:9501–9522); at gen-0 no claim exists → `None` naturally. No special-casing needed; the task's "spawned_by_lineage = null" falls out. | SPEC:1102–1103 |
| Gates | `_supervisor_gate("spawn")` (:3185) + `_ceiling_refuses_dispatch("spawn")` (:3186) | **keep both**, verb string `"sup-spawn"`. The gate disarms with no held claim (fleet.py:9421 "no held claim -> nothing to gate against") — gen-0 passes; with a live fresh claim it refuses a sid-bearing caller without the nonce, which is exactly the accidental-second-supervisor guard. The ceiling structurally exempts the interface (`FLEET_WORKER` absent, :1994–1995) and correctly binds a claim-holding supervisor trying to spawn its own replacement at ≥200k (that path belongs to handoff, not sup-spawn). CN §7 classes sup-spawn as mutating-lifecycle (CN:1953), so gating is taxonomy-consistent. | fleet.py:9391–9465, 1966–2014 |
| `category`/`hint` | operator args | **forced `category=None`, `hint=""`** — `render_native_name` joins `cat\|name\|hint` (:8075–8081); a pipe-bearing worker name inside that rendering would corrupt any round-trip parse. With both empty the rendered `-n` must be the bare name; pin with a test (Q8-3). | fleet.py:8075–8081 |

### The one enabling code change

`dispatch_bg` refuses non-`NAME_RE` names at fleet.py:8220–8223 — today it would refuse
`sup|<id>|boot`. Widen the guard to `NAME_RE.match(name) or _is_supervisor_shaped(name)`
(keeping the sid-shape refusal). This preserves the spec's routing mandate instead of
forking a second hand-rolled argv path, and the shape stays unforgeable from the worker
path (`fleet spawn` → `validate_name` → `NAME_RE` forbids `|`, fleet.py:1300–1313 comment;
CN:2244–2248). Fault-inject in tests (Q8-2).

## 4. First-turn boot ritual

**Question.** Exact dispatched-prompt contract (GOALS + run-sup-boot-first instruction);
interaction with the legacy-claim exemption and the nonce protocol.

### Options

- **(A) Embed GOALS text in the prompt** and instruct boot-first.
- **(B) Boot-first, GOALS via the boot bundle** — the prompt orders `fleet sup-boot` as
  the first act; `cmd_sup_boot` already prints the boot bundle (GOALS + journal tail 5 +
  INDEX head + roster count + status, fleet.py:9359–9368), so GOALS arrives fresh at boot
  time, not stale at compose time.

### Recommended: (B), modeled on `_render_successor_task` (fleet.py:10259–10290)

Task-file contract (written by `dispatch_bg`'s G8 bootstrap to `task_file_path(name)`;
the argv prompt stays the tiny "Read <task file> and follow it exactly", :8244):

1. **Identity preamble**: you are the fleet supervisor's gen-0 body, worker
   `sup|<launch-id>|boot` in `<FLEET_HOME>`. The `<launch-id>` segment is a launch id,
   **not** your incarnation id (Q1).
2. **First act, before anything else**: run `fleet sup-boot`. No `--handoff-*` flags —
   this is the fresh-claim path, and the successor arm is reached only via those flags
   (fleet.py:9241–9263).
3. **Expected outcome**: verdict `claim`, exit 0, output includes `INCARNATION: <inc>` and
   `NONCE: <value>` (fleet.py:9292–9307). **Record the NONCE value** — it is printed
   exactly once (CN:1507–1508), `--nonce` is the only presentation channel (no env
   fallback, CN §6.5/D5 :1763), and every subsequent `sup-*` verb requires it. Losing it
   costs up to 3600 s of lockout (O3, CN:2220–2224).
4. **On `refuse` (exit 2)**: a live claim exists — a supervisor is already running. Do
   NOT retry, do NOT spawn/send/kill anything. End the turn with the terminal message
   `SUP-BOOT-REFUSED <reason>`. (Mirrors the refusal-message doctrine CN:1453–1456 — the
   refused body stops and escalates; and the successor task's `HANDOFF-ORPHAN` terminal
   contract, fleet.py:10288–10289.)
5. **On `freeze` (exit 3)**: ambiguous claim state (unreadable heartbeat / empty-roster
   G9). Same stop discipline; terminal message `SUP-BOOT-FROZEN <reason>`.
6. **After a successful claim**: proceed per `skills/fleet/supervisor.md` — read the boot
   bundle you just printed (GOALS, journal), `sup-checkpoint` early with `--nonce`, then
   begin the campaign brief included below.
7. **Campaign body**: whatever the operator passed as the sup-spawn task argument
   (`@file` or literal, `_read_task_arg` semantics, fleet.py:3200).

Interaction notes, grounded:

- **Nonce protocol.** The fresh claim MINTS (CN:2170–2171 "prints `NONCE: <value>`
  whenever it mints one"; the three dict-literal writers all carry
  `nonce_hash`/`nonce_seq`/`lineage_id`, CN:2033–2035). Gated verbs thereafter
  present-only, never mint-as-side-effect (CN:1257–1258). The ritual's only nonce duty is
  step 3's "record it".
- **Legacy-claim exemption is a non-interaction.** The exemption lives in
  `_require_claim_holder` (honor sid-equality once, upgrade in place —
  fleet.py:9798–9815; CN:1217–1222), i.e. it applies to the five gated `sup-*` verbs, and
  `cmd_sup_boot` is not among them (CN:354–358; fleet.py:9225+ has no legacy arm —
  `_claim_is_legacy` :9372 is consulted by the gate, not by boot). A gen-0 boot over a
  *legacy* claim file therefore takes the ordinary §6.1 table with `nonce_valid=False`:
  holder roster-live → `refuse` (step 4); holder gone + stale → `seize`. Correct in both
  arms; the ritual needs no legacy-special text.
- **B6 released-claim window: already closed.** SPEC:1219–1224 requires automated
  sup-boot callers to gate on `released_by_sid not in live_sids`; `supervisor_claim_decision`
  rule 1 now refuses exactly that case (fleet.py:9087–9091), so the dispatched body needs
  no self-gate. Pin with a test rather than re-implement (Q8-10).
- **Roster non-emptiness.** `cmd_sup_boot` freezes on an empty roster (G9, CN:498–508,
  epoch check before the claim decision fleet.py:9234–9237/:9281–9282). The sup-spawned
  body is itself a roster entry, so gen-0 boot cannot trip G9 by being first — a nice
  side-effect of routing through `dispatch_bg` + registry record rather than a bare
  `claude` launch.

## 5. Reserved-name reconciliation (§10.3)

**Question.** With a pipe-shaped name, is `validate_name(allow_reserved=True)` needed at
all? Is `"supervisor"` still a logical target anywhere?

### Findings

- `validate_name` checks, in order: `NAME_RE` charset → sid-shape → `RESERVED_NAMES`
  (gated by `allow_reserved`) → existing collision (fleet.py:735–761). `sup|<id>|boot`
  fails the **first** check; `allow_reserved` bypasses only the third. So
  `allow_reserved=True` cannot admit the pipe name, and sup-spawn under recommendation
  Q1(A) has no use for it. Today the parameter has **zero callers** passing True.
- The docstring (fleet.py:738–740: "`sup-spawn` passes it True to mint `supervisor`") and
  the §10.3 refusal message ("minted only by `sup-spawn`", :756–759) describe the
  pre-ruling design where gen-0 was named `supervisor` — now stale. Worse, that design is
  *known-broken*: a body with `FLEET_WORKER=supervisor` is refused every gated `sup-*`
  verb (fleet.py:9772–9779), i.e. the reserved name is mintable-but-nonfunctional.

### Options

- **(A) Delete `allow_reserved` + the reservation** — nothing mints the name, so why
  reserve it?
- **(B) Keep the reservation, retire the bypass** — `RESERVED_NAMES` stays and ordinary
  spawn/respawn of `supervisor` stays refused; `allow_reserved` is removed (or kept as an
  inert parameter) and the docstring/refusal text is corrected to "reserved as the
  supervisor's *logical* name (Q2 resolution target); no verb mints a record by this
  name".

### Recommended: (B)

The reservation is *more* load-bearing under Q2(B), not less: `fleet send supervisor`
resolving to the claim-holder only works if no ordinary worker can squat the literal name
(otherwise the resolver has an ambiguity between the squatter record and the logical
target). The F6-mirroring refusal in `validate_name` (SPEC:1137–1142) is the mechanism
that guarantees it. Keep `SUPERVISOR_BODY_NAME`/`RESERVED_NAMES` (fleet.py:731–732) and
the archive/divergence literal-name arms (:5397, :10013) as belt-and-braces for any
pre-ruling record that might exist in an old registry. Whether `allow_reserved` is
deleted outright or left inert is a build-slice call; the docstring correction is
mandatory either way (it currently documents an unsafe path). §10.3's spec text
("the name is minted only by `sup-spawn`", SPEC:1138–1139) needs the same amendment —
folded into operator ruling 1.

`"supervisor"` remains a logical target at exactly three layers: the Q2 send-resolution,
the §10.4 `kill supervisor`/`respawn supervisor` verbs (same resolver), and the
divergence filter's target matching (fleet.py:10013, already handles both spellings).

## 6. `--model` default

**Question.** `resolve_model_for_role("supervisor")`; exact behavior when the GOALS
tier-policy block is absent. Mode = bypass per §10.2.

### Recommended behavior (no real options here — the machinery is built and specified)

- Default: `model = args.model or resolve_model_for_role("supervisor")`.
  `read_tier_policy()` with no `<!-- fleet-tier-policy -->` block in
  `supervisor/GOALS.md` returns pure defaults with `tier_model: {}`
  (fleet.py:8613–8680, `_source: "default"`, never raises — missing/undecodable GOALS
  included). `resolve_model_for_role("supervisor")` then looks up
  `supervisor_chain[0]` (`"top"`) in an empty `tier_model` → **returns `None`**
  (fleet.py:8683–8705). `dispatch_bg` appends `--model` only if truthy (:8272–8273) — so
  today, with the GOALS proposal unapplied (docs/proposals/GOALS-tier-chain-proposal.md,
  operator-owned), **`--model` is omitted and the daemon default governs**, which is
  §3.3(d)'s specified behavior ("let the namespace daemon's default govern rather than
  invent a model id", SPEC:181–185). No fleet-side fallback, no warning needed.
- Explicit `--model <tier-alias>` must exist and override — it is the §3.5.3 fallback's
  dispatch lever ("`sup-spawn` takes an explicit `--model <tier-alias>` … a
  parser-and-pass-through, not new plumbing", SPEC:483–485; §3.5.3(a) SPEC:394–402
  dispatches the successor at the fallback tier through it). Print the resolution the way
  `cmd_spawn` does (`model: {model or '(claude default)'}`, :3341–3347), plus the policy
  source (`default` vs `goals`) for operability.
- Mode: default `bypass` (§10.2: "runs under **bypass** permission mode in the fleet repo
  (earned-privilege doctrine) — stated explicitly in GOALS before it ever runs
  unattended", SPEC:1103). Allow `--permission-mode` override through the one `MODE_FLAGS`
  vocabulary (fleet.py:1244–1260; G3 precedent at the successor parser :11175). Note the
  deliberate asymmetry with `SUCCESSOR_DEFAULT_MODE = "dontask"` (fleet.py:8570): the
  successor inherits a running campaign mid-handoff and the operator is presumed absent;
  gen-0 sup-spawn is an operator-attended act, and §10.2 names bypass for it. Design
  rec (not a ruling): warn — do not refuse — when `supervisor/GOALS.md` lacks the
  bypass-permission acknowledgement §13 requires (SPEC:1551); a grep-shaped refusal on an
  operator-owned prose file is too brittle to be a gate.

## 7. Failure modes: dispatch succeeds, first-turn sup-boot fails — and neighbors

**Question.** Dispatch succeeds but first-turn sup-boot is REFUSED (live claim, corrupt
claim file, nonce gate): operator surface + recovery, each.

| # | Failure | What the operator sees | Recovery |
|---|---------|------------------------|----------|
| a | **Dispatch DOA** (`NativeDispatchError`, no fast-completion) | `spawn_failed` event; `FleetCliError` "native spawn failed"; pre-claim rolled back (fleet.py:3274–3281) — registry clean | Re-run `sup-spawn`. The new launch mints a fresh launch-id name; the old task file is orphaned but name-keyed and inert (doctor hygiene candidate, Q8-16) |
| b | **Boot REFUSED — live claim** (rule 2, fleet.py:9121–9123; or B6 releaser-live :9087–9091) | Body obeys ritual step 4: ends turn with `SUP-BOOT-REFUSED <reason>`; visible via `fleet result "sup\|<id>\|boot"` / `fleet peek`; record goes idle; `fleet sup-status` shows the existing holder. Boot refuse is strictly read-only (fleet.py:9356) — no journal write, no rejection-log entry (that log is for gated-verb nonce refusals, CN:1405–1423) | Usually correct behavior (two-supervisor guard fired). If the refusing claim is a zombie: wait out `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s) and `fleet send` the body to re-run `sup-boot` → `seize`; or operator manual lever `rm supervisor/INCARNATION` (CN:1443–1448 — the enumerated paths; "this spec adds no fourth path"). The idle body record is a non-holder → archive-eligible on normal TTL; no cleanup debt |
| c | **Boot FROZEN — corrupt claim file** (heartbeat unreadable → freeze, fleet.py:9140–9143 "never seize on ambiguity"; also G9 empty-roster/roster-fetch-fail arm :9281–9282) | Terminal message `SUP-BOOT-FROZEN <reason>` (ritual step 5); `sup-status` reports "claim <inc> heartbeat unreadable -- inspect supervisor/INCARNATION" (CN:301); doctor FAILs the claim check | Operator inspects/repairs/removes `supervisor/INCARNATION` by hand (the documented manual lever), then steers the body to retry `sup-boot`, or respawns it. Freeze is exit 3 — deliberately not auto-recoverable |
| d | **Nonce lost after successful boot** (body crashes/compacts and drops the plaintext) | Gated `sup-*` verbs refuse loudly (distinct exit code, expected `nonce_seq` named, record appended to `state/supervisor-nonce-rejections.jsonl`, doctor flips ok=False — CN:1405–1423) | The refused body must NOT unilaterally recover (CN:1453–1456). Paths: wait until heartbeat stale (≤3600 s) then `sup-boot` → `seize` re-mints (own claim, new inc, O3 lockout cost CN:2220–2224); or operator `rm INCARNATION`. Ritual step 3 exists to make this rare |
| e | **Stranded stamp** (`_commit_launched_turn` exhausts post-dispatch) | rc 1 + `_report_stranded_native_turn` (fleet.py:2726–2759): record stuck `session_id=null/status=working`, auto-demotes to dead after 600 s (:1073, :2287–2293), message says do NOT re-run (double-dispatch). **Supervisor-specific sharpening**: the live body will still sup-boot and CLAIM — you then have a live claim whose holder sid is in no registry record, so the claim-identity protections (archive exemption :5395, ceiling identity) see an unmatched holder, and Q2's send-resolution errors with "holder sid matches no record" | Hand-stamp the sid into the record per the stranded message (sid/short_id are printed), or `claude agents` to find it. Once stamped, all identity predicates heal — they key on sids, not on how the stamp got there |
| f | **Fast completion** (first turn finishes before roster join) | "(native bg, fast completion before join)" print; record stamped idle with `turns=1` (fleet.py:3239–3262). For gen-0 this means boot ran to completion before sup-spawn returned — claim likely held, body idle | None needed; `fleet sup-status` confirms the claim. Beat proceeds by `fleet send supervisor` (Q2) |

## 8. Test plan sketch (red-first)

Unit/hook tests (pytest, both floors `py -3.13` and `py -3.10`); fault-injection = mutate
the guard, confirm red, restore (tt-build convention).

1. **Name mint**: sup-spawn record key matches `^sup\|inc-[0-9TZ]+-[0-9a-f]{4}\|boot$`;
   `_is_supervisor_shaped` True; `!= SUPERVISOR_BODY_NAME`.
2. **dispatch_bg guard widening**: accepts supervisor-shaped names; still refuses
   sid-shaped and arbitrary pipe junk (`a|b`, `sup|x|`, `sup||boot`, trailing third
   pipe). **Fault-inject**: revert the widening → sup-spawn dispatch red.
3. **Rendered-name pin**: with `category=None, hint=""` the `-n` argv value is exactly
   the bare pipe name (no `render_native_name` delimiter corruption).
4. **Record fields**: `spawned_by` = caller sid; `spawned_by_lineage is None` when no
   claim held; `mode == "bypass"` default; `dispatch_kind == "bg"`.
5. **Model default matrix**: GOALS block absent → argv has no `--model`; block present →
   `--model <alias of supervisor_chain[0]>`; explicit `--model` beats both. (Resolver
   behavior itself is already pinned in tests/test_tier_resolver.py — these pin the
   *argv*.)
6. **DOA rollback**: dispatch raises `NativeDispatchError` (no fast completion) → record
   popped iff `session_id is None`; `spawn_failed` event present. **Fault-inject**: drop
   the `session_id is None` guard → concurrent-fast-stamp clobber test red.
7. **Fast-completion stamp**: outcome file fresh past `pre_claim_at` → stamped idle,
   `turns=1`, derived `native_short_id`.
8. **Stranded path**: `_commit_launched_turn` forced to exhaust → rc 1, stranded report,
   record NOT popped, `turn_commit_failed` event.
9. **First-turn task-file contract**: file contains `fleet sup-boot` as first instruction
   (no `--handoff` flags), the NONCE-record instruction, `SUP-BOOT-REFUSED`/`SUP-BOOT-FROZEN`
   terminal-message contracts, and the launch-id ≠ incarnation-id note; contains no
   plaintext secret (unlike the successor task's token — nothing to leak here, pin it
   stays that way).
10. **Boot integration (haiku worker or pure-function)**: fresh state → verdict `claim`
    exit 0 mints nonce; live fresh claim → second body's boot → `refuse` exit 2; released
    claim + releaser roster-live → `refuse` (B6 pin, fleet.py:9087–9091).
11. **Gate wiring**: live fresh claim + sid-bearing caller without `--nonce` →
    `SupervisorClaimGateError` on sup-spawn; no claim → passes. **Fault-inject**: remove
    the `_supervisor_gate("sup-spawn", ...)` call → red.
12. **Ceiling wiring**: `FLEET_WORKER`-stamped claim-holding caller at ≥200k occupancy →
    sup-spawn refused; interface caller (no `FLEET_WORKER`) exempt at any occupancy.
13. **Reserved name unchanged**: ordinary `spawn supervisor` still refused; sup-spawn
    never creates a record named `supervisor`; `validate_name` docstring/refusal text no
    longer claims sup-spawn mints it.
14. **Send-resolution (if ruling 1 lands)**: `fleet send supervisor` with a live claim →
    mail lands on the holder's pipe-named record; no claim → named `FleetCliError`; two
    supervisor-shaped records (handoff in flight) → resolves by claim, not shape.
    **Fault-inject**: resolver falls back to shape-guessing → ambiguity test red.
15. **Event ordering**: `spawned` event inside the pre-claim lock; `turn_started` via
    `_append_event_quiet` post-save (contract fleet.py:2702–2711 — no OSError after
    durable save).
16. **Orphaned-task hygiene** (stretch): a DOA'd sup-spawn's task file is flagged by
    doctor or overwritten safely by the next launch (name differs per launch — assert no
    collision).

Integration test (SPEC §12 style, haiku worker in temp dir): full sup-spawn → body runs
`sup-boot` → claim file exists with `claimed_via: "fresh"` → `sup-status` healthy →
second sup-spawn body refused (exit 2) with terminal message.

---

## Operator rulings needed

> **RULING OUTCOMES (2026-07-24, operator, in-session — both RATIFIED):**
> **Ruling 1 — GRANTED, all three arms.** (i) gen-0 body is `sup|<launch-id>|boot`, no
> `supervisor`-named record ever exists; (ii) `"supervisor"` in send/kill/respawn positions is a
> logical name resolved at verb time via the claim to the holder's record; (iii) the contradicting
> ratified prose in `docs/specs/three-tier-command.md` is amended, citing this ruling — applied on
> this branch (10 dated amendment markers: §3.5.3(d) premise + name-yield bullet, §5.1 beat-contract
> note, §5.2 scheduler line, §5.3 B7 line, §7.2 B1 line, §10.2 registry bullet, §10.2 name/shape
> reconciliation line, §10.3 reserved-name prose, §11.3 ND1 blockquote). `[UNBUILT]` markers and all
> pinned receipts untouched.
> **Ruling 2 — WARN.** The §10.2 bypass-acknowledgement check warns when `supervisor/GOALS.md`
> lacks the acknowledgement and proceeds; no refusal, no silence.

1. **Ratify the pipe-named gen-0 + logical-name resolution, and amend the ratified prose
   that contradicts it.** The 2026-07-24 manager ruling (family regex widening,
   fleet.py:1300–1313) already implies gen-0 is `sup|<launch-id>|boot`, but ratified
   three-tier text still says the record is *named* `supervisor` (§10.2 SPEC:1099, §10.3
   SPEC:885/1137–1139, §10.2 SPEC:1115–1116 "today only the handoff-successor shape",
   §3.5.3(d) name-yield SPEC:486–491) and the v1 beat contract addresses `fleet send
   supervisor` literally (SPEC:626/649–650/709/1364). Ruling wanted: (i) gen-0 body name
   is `sup|<launch-id>|boot` (no `supervisor`-named record ever exists); (ii)
   `"supervisor"` in send/kill/respawn positions is a logical name resolved via the
   claim to the holder's record (Q2 option B); (iii) the operator edits the cited spec
   lines accordingly (precedent: the §7.2 holder-alone amendment). Options considered:
   alias record (rejected — sid-union identity breakage), prose-only amendment
   (rejected — breaks the v2 scheduled beat).
2. **§10.2 bypass acknowledgement enforcement level.** §10.2/§13 require the bypass-mode
   acknowledgement to be "stated explicitly in GOALS before it ever runs unattended"
   (SPEC:1103, 1551). Design recommends sup-spawn *warns* when the acknowledgement is
   absent and proceeds; alternatives are refuse (brittle grep-gate on operator prose) or
   silence (drops a ratified precondition on the floor). Pick one.

(No other operator-owned choices surfaced: model default, gate wiring, choreography and
ritual all follow from ratified text + built machinery.)
