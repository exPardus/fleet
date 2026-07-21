# Audit oracle — design (M-G candidate)

**Status:** DRAFT — under adversarial review (2026-07-22). Not spec-of-record until review clears and the operator ratifies.
**Origin:** operator-relayed teammate requirement, 2026-07-20 — *"there will be problem with penetration attacks, u need some sort of verification between agents cuz there is barely user present so agents cannot truly verify what they're doing cuz all they get is another agent's answer… then u need isolated oracle ish thing, like it just checks the given task and output and context of task."*
**Depends on:** SDD / drift-control (`2026-07-18-sdd-drift-control-design.md`, v4, M-F) — the oracle's deterministic verifier and the accepted-spec contract are its substrate. Buildable only after M-F slices 0–3.
**Parent spec:** `docs/SPEC.md` v3 (§4 registry, §5 verdict engine, §8 outcome store + hook write boundary, §11 archive, §13 doctor, §15 provenance guard, §16 invariants).

---

## 1. Problem — what an agent cannot verify about another agent

With no human in the loop, worker B's only evidence about worker A's work is **A's own account of it**. Three failure modes follow:

1. **Compromised agent (penetration).** A prompt-injected or hostile worker emits a plausible completion claim. Every downstream consumer — a reviewer worker, the manager reading `fleet result`, the next worker in a chain — receives prose and cannot distinguish a real result from a fabricated one.
2. **Deranged agent (madness).** No attacker needed. A worker loops, re-does finished work, or spirals — and its self-report stays confident throughout. Reviewer agents reviewing reviewer agents compound rather than correct.
3. **Contract subversion.** The artifact that *defines* correct behavior is itself agent-writable (SDD round-2 F1: a bound worker holds `--add-dir` write access to its own spec).

SDD (M-F) already answers a slice of this: the deterministic tier decides and the judge only advises; `accepted_digest` catches contract tampering; git-tracking adds a second tamper surface. **What SDD does not provide is isolation.** `spec verify` runs at the manager's gate, inside the same trust chain as the agents it judges, and nothing anywhere detects a spiral.

**The oracle is the missing piece:** a non-agentic auditor that re-derives the (task, output, context) triple from evidence the agents cannot write, and whose verdict is a gate input rather than another opinion.

**Non-goal:** the oracle is not a reviewer, not a judge, and not an LLM. It never reads intent. It answers only questions with a mechanical answer.

## 2. What "isolated" means here, concretely

Fleet is daemonless (invariant 1) and runs on one box; "isolated" cannot mean a separate machine. It means four specific properties, each testable:

1. **Never runs inside an agent session.** The oracle is a short-lived CLI invocation from the manager or the OS scheduler. `FLEET_WORKER` set in the environment ⇒ refuse and exit non-zero. A worker can never invoke the auditor that judges it.
2. **Reads only agent-unwritable evidence for its verdicts** (§3). Agent-produced bytes are inputs to *measure*, never to *believe*.
3. **Takes no instruction from anything it reads.** Every ingested artifact is untrusted data. The oracle has no LLM in its verdict path, so there is no prompt to inject; where any advisory text is surfaced to a human or a judge, it is fenced with a randomized token (the librarian lesson, `docs/PRIOR-ART.md`).
4. **Its own inputs are integrity-checked.** The evidence it depends on is append-only or hash-pinned; a gap or a rewrite in that evidence is itself a CRITICAL finding, never a silent pass.

## 3. Evidence classification — the trust boundary

Every input is classed. **A verdict may be derived only from TRUSTED inputs and from deterministic functions of UNTRUSTED bytes** (hashes, path sets, counts, diff statistics). No verdict may depend on *interpreting* untrusted prose.

| Class | Inputs | Why |
|---|---|---|
| **TRUSTED** | `state/events.jsonl` (append-only, `fleet.py`-only writer — hooks are forbidden from it, SPEC §8); registry fields written by the single writer under `fleet.lock`; git commit metadata (sha, tree, parents, author, timestamps); the accepted spec's `accepted_digest`; the SDD verify stamp | Agents cannot write these. `events.jsonl` in particular is append-only and survives `clean` (SPEC §15). |
| **UNTRUSTED — measurable** | the diff (path set, line counts, tree hashes); `state/tasks/<name>.md` bytes (hashed); outcome-record token counts and timestamps; spec machine-block bytes (hashed) | Agent-influenced, but the oracle only ever hashes, counts, or set-compares them. |
| **UNTRUSTED — never a verdict input** | `result_text` and all assistant prose; journals; commit *messages*; the spec's human body; any reviewer's verdict text | This is exactly the "all they get is another agent's answer" surface. It may be *displayed*, never *believed*. |

**Rule:** if removing an UNTRUSTED-prose input would change a verdict, the check is malformed.

## 4. What the oracle checks — the (task, output, context) triple

For each worker in a campaign, the oracle independently re-derives the triple and asserts their mutual consistency. Six checks, all mechanical:

- **O1 — task integrity.** The task file the worker was dispatched with hashes to the value recorded in the dispatch event. Catches a post-hoc task swap (a worker rewriting its own instructions, then reporting against the new ones). Requires: `dispatch_bg` records `task_sha256` in its event.
- **O2 — contract stability.** The bound spec's `accepted_digest` matches the spec on disk *and* has not changed across the worker's lifetime (every event carrying a spec reference names the same digest). Catches SDD round-2 F1 from the outside, independent of `spec verify`.
- **O3 — output within contract.** The worker's diff (touched-path union, §6a of the SDD design) ⊆ its effective scope (slice ∩ whole-spec). This duplicates the SDD gate deliberately: **an independent re-derivation is the point.** A disagreement between the oracle and `spec verify` is itself a CRITICAL finding — one of them is wrong or one has been tampered with.
- **O4 — criteria actually ran.** The verify stamp exists for the current spec digest, its criteria set matches the accepted spec's criteria ids, and its timestamp postdates the worker's last commit. Catches a stale or forged green.
- **O5 — topology sanity (spiral / madness detection).** Reconstruct the spawn graph from `events.jsonl` via `spawned_by`. Alarms: any dispatch whose spawner is a worker rather than the manager (fleet's topology is a star — SPEC §15 strips `CLAUDE_CODE_SESSION_ID` from worker envs precisely so this cannot happen; observing it means the guard failed); spawn depth > 1; respawn count for one name > K in a window; N consecutive turns with rising token spend and no change in the passing-criteria set (*spinning*); the same `task_sha256` re-dispatched > K times.
- **O6 — evidence integrity.** `events.jsonl` is append-only and unbroken (monotonic timestamps, no truncation relative to the last audit's recorded length/hash); no `fleet.json.corrupt.*` quarantine artifact is unexplained; the outcome store has no record for a sid absent from the registry's known sids. A failure here voids the whole audit — the oracle reports CANNOT-AUDIT, never a green.

## 5. Verdict semantics + authority

- Findings are `CRITICAL | WARN | NOTE`. A run writes an atomic stamp `state/oracle/<campaign>.json` (`_write_json_atomic`) carrying `{ts, evidence_head, per_check, findings, verdict}`, plus an `oracle_run` event.
- **Gate teeth, no kill authority.** `spec verify` exits non-zero while an **open CRITICAL** oracle finding exists for that campaign — that is the oracle's power. It never stops, kills, respawns, or demotes a worker; those stay manager/operator verbs (never-demote-unknown, SPEC §16). An auditor with kill authority is a new single point of catastrophic failure.
- **CANNOT-AUDIT ≠ pass.** Missing evidence, a non-git cwd, an unreadable spec, or an O6 failure ⇒ verdict `cannot-audit`, which blocks the gate exactly like a CRITICAL. Fail-closed: the one thing an auditor must never do is report green because it could not look. (Contrast the SDD fence, which fails *open* because it is advisory self-correction; the oracle is a gate input, so it fails closed.)
- **Clearing is explicit and human.** `fleet oracle ack <campaign> <finding-id> --reason` records an operator acknowledgement in `events.jsonl`. An agent cannot clear its own alarm: `ack` refuses when `FLEET_WORKER` is set, and refuses a spawned-by-Claude caller without `--yes` (the §15 destructive-guard pattern).
- Views stay probe-free: `status` and doctor read the oracle stamp only (`_doctor_check_oracle`, RED on open CRITICAL — this is genuine infra-broken, not note-only).

## 6. Surface

| verb | behavior |
|---|---|
| `fleet oracle run [<campaign>] [--since <sha>]` | full audit O1–O6; writes stamp + event; exit 0 clean / 1 CRITICAL or cannot-audit / 2 harness failure. Refuses if `FLEET_WORKER` is set. |
| `fleet oracle status [<campaign>]` | read the stamp (view-legal: no lock, no roster, no subprocess). |
| `fleet oracle ack <campaign> <id> --reason <text>` | operator acknowledgement; refuses agent callers. |

Scheduling reuses the autoclean bridge (`fleet init --autoclean` pattern, SPEC §11) so an audit runs on a timer as well as at the gate.

## 7. Why this is not just another agent

The teammate's framing — *"all they get is another agent's answer"* — is precisely why every check in §4 is a hash comparison, a set containment, a graph property, or a timestamp ordering. The oracle has **no model in its verdict path**. It cannot be persuaded, injected, or confused by clever prose, because it never reads prose as evidence. Its failure modes are ordinary software bugs, which are testable, rather than judgment failures, which are not.

This is also why O3 deliberately duplicates the SDD gate rather than trusting it: two independent derivations that must agree turn a silent compromise into a loud contradiction.

## 8. Testing

- **Unit (`tests/test_oracle.py`):** each of O1–O6 with a fault-injected fixture — swapped task file (O1), mutated spec digest (O2), out-of-scope path in the union (O3), stamp with mismatched criteria ids / predating the last commit (O4), a fabricated worker-spawns-worker event and a spinning-turns sequence (O5), a truncated `events.jsonl` and an orphan outcome sid (O6). **Fault-inject every check or the suite is theater** (C4 lesson): break each invariant N ways; any check that stays green is CRITICAL.
- **The founding-incident rule (M-E lesson):** each check must detect the concrete scenario it was written for, using the real artifact shape — never a fabricated evidence line that the producing code cannot emit.
- **Isolation tests:** `oracle run` and `oracle ack` refuse with `FLEET_WORKER` set; no verdict changes when every UNTRUSTED-prose input is replaced with adversarial text (including text that instructs the oracle to pass).
- **Live pin:** a haiku worker bound to a spec commits an out-of-scope file; `oracle run` returns CRITICAL and `spec verify` then refuses to pass until acked.

## 9. Residual operator decisions

1. **Spiral thresholds (O5)** — K for respawn count, the spinning-turn window. M-E's lesson says *demand-driven evidence never carries a count/span threshold* (a threshold measured the operator's retry cadence, not the fault). Recommend: **structural alarms only for v1** (worker-spawns-worker, depth > 1, identical `task_sha256` re-dispatch), and ship rate-shaped alarms only once real campaign data exists.
2. **Scope of the audit** — per-campaign (recommended) vs whole-fleet sweep.
3. **Gate coupling strength** — oracle CRITICAL blocks `spec verify` (recommended, gives it teeth) vs advisory-only (weaker, but no risk of a buggy auditor wedging a campaign).
