# Audit oracle — derangement & bookkeeping-drift detection (M-G candidate)

**Status:** DRAFT v2 — v1 folded three adversarial lenses (correctness, feasibility, doctrine, 2026-07-22). **v1 was reframed, not patched:** all three lenses independently concluded it could not be what it claimed. Not spec-of-record until re-review clears the fold and the operator ratifies. On ratification this file moves to `docs/specs/oracle.md`, inside the receipt harness (`tests/test_receipts.py` scans `docs/specs/*.md` only), with a `# at <sha>` receipt per ground-truth claim — v1 made ~20 un-receipted claims about `bin/fleet.py` and **at least four were false**.
**Origin:** operator-relayed teammate requirement, 2026-07-20 — *"agents cannot truly verify what they're doing cuz all they get is another agent's answer… then u need isolated oracle ish thing."*
**Depends on:** SDD / drift-control (M-F) for the accepted-spec contract, plus prerequisites N1–N9 (§10) — **none of O1–O4 is buildable on the data fleet records today.**

---

## 0. What changed from v1, and why it matters more than the design

v1 claimed an "isolated, non-agentic oracle" reading "evidence agents cannot write." Every lens killed that claim with receipts:

- `state/` carries `Authenticated Users: Modify`; workers run as the **same OS user**, default `--mode dontask`, and `worker-settings.template.json` has **no `permissions` block**. "Append-only" on `events.jsonl` is a comment, not a mechanism (`bin/fleet.py:696-703`, a bare buffered `open(...,"a")`).
- `FLEET_WORKER` is an env var (`env -u FLEET_WORKER …` defeats it), `fleet.py` **never reads it**, and `docs/SPEC.md:189` **forbids keying a guard on it by name** — the supervisor successor carries it, so the check would refuse the one session whose purpose is to receive the claim.
- Git `author` and both timestamps are agent-settable (`GIT_COMMITTER_DATE=… git commit --author=…`), defeating O4's ordering.
- `_confirm_destructive` is a **no-op inside a worker**: `_worker_env` strips `CLAUDE_CODE_SESSION_ID`, so `caller is None` returns early (`bin/fleet.py:2204-2206`) — a worker clears its own alarm while the manager is the only caller challenged.

**The project already learned this.** M-E: *"a bearer secret cannot be an authorization credential on a substrate with no privilege separation"* (`knowledge/lessons.md:649`) — which forced `claim-nonce` from authorization into **detection**. v1 substituted "a file an agent is asked not to write" for the bearer secret: same substrate, same absence of privilege separation, same outcome. v2 takes the same reframe, deliberately.

## 1. Honest threat model — what this does and does not detect

**Detects (non-adaptive faults):** contract tampering, scope escape, stale or absent verification, structural topology anomalies, evidence gaps. These are the fingerprints of a **deranged** agent, a **buggy** one, or **bookkeeping drift**.

**Does not detect, and cannot:** a semantically-wrong change that stays in scope and passes the declared criteria. Concrete trace, from the correctness lens — an injected worker makes a two-character edit to `_worker_is_foreign` so it returns `False` on an unknown owner, disabling the destructive guard fleet-wide. It is inside `scope_allow` (`bin/fleet.py`), every declared pytest node still passes (none covers that branch), task and spec untouched, one dispatch, nothing tampered. **All six checks PASS.** Catching it requires reading the diff's *meaning* — a model or a human, both excluded by construction (§2).

**Does not detect, against an adaptive adversary:** anything at all, once the attacker writes the evidence. Every check below is suppressible by a worker with a shell.

**Therefore the deliverable is a detector, not a boundary.** Selling it as a penetration defense would install a green light with no bulb behind it — strictly worse than today, where the manager knows it is guessing. **Penetration defense requires OS privilege separation and is a separate prerequisite milestone (§11), not a section of this design.**

## 2. Isolation — four properties, honestly graded

| # | Property | Grade |
|---|---|---|
| 1 | Does not run inside an agent session **by default** | **Tripwire, not a boundary.** Keyed on the **registry/claim** — caller sid ∈ registry sids ⇒ refuse — never on `FLEET_WORKER` (`docs/SPEC.md:189` forbids it by name; the supervisor successor carries it). An honest attacker clears the signal, so the tripwire *firing* is itself evidence and is logged CRITICAL. |
| 2 | Verdicts derive only from tamper-**evident** evidence | **Partial.** Only git content-addressed fields (sha/tree/parents) are self-verifying today. A hash-chained `events.jsonl` (N5) would extend this; without it, "evidence integrity" means "cost to forge silently", not "cannot forge". |
| 3 | No LLM in the verdict path | **Holds.** This is the one v1 property that survives intact. The verdict function cannot be persuaded or injected — only its inputs can. |
| 4 | Its own inputs are integrity-checked | **Aspirational until N5.** See O6, which v2 demotes accordingly. |

## 3. Evidence classification

**Rule (unchanged and load-bearing):** a verdict may derive only from tamper-evident inputs and deterministic functions of untrusted bytes. *If removing an untrusted-prose input would change a verdict, the check is malformed.* v1 violated its own rule (O5 derived an alarm from attacker-chosen token integers); v2 does not.

| Class | Inputs |
|---|---|
| **TAMPER-EVIDENT** (v1 called this TRUSTED — a false name) | git `sha`/`tree`/`parents` (content-addressed, self-verifying). Post-N5: `events.jsonl` records with a verified `prev` chain. |
| **UNTRUSTED — measurable** | the diff path set and tree hashes; task-file bytes (hashed); registry fields; `spawned_by`; git `author` and **both timestamps**; outcome-record token counts and timestamps; spec machine-block bytes |
| **UNTRUSTED — never a verdict input** | `result_text` and all assistant prose; journals; commit *messages*; the spec's human body; any reviewer verdict text |

Note what moved down from v1's TRUSTED: registry fields (a worker can invoke the CLI and *become* the single writer under `fleet.lock` — `knowledge/INDEX.md:23`), `spawned_by` (env-derived), and git author/timestamps (env-settable).

## 4. Checks

Thresholds are **deliberately absent**. M-E: *"whenever evidence is demand-driven, a count/span threshold measures the operator, not the system"* (`knowledge/lessons.md:641`) — respawn counts and re-dispatch counts are literally operator retry cadence. v1 listed thresholds in its normative §4 while its own §9 recommended structural-only, i.e. it argued itself out of its own decisions without noticing — the exact M-E claim-nonce failure. All thresholds live in §9 as unbuilt.

- **O1 — task integrity.** The dispatched prompt body, hashed **at dispatch into an oracle-owned evidence store**, matches what was dispatched. Hashing the live task file is useless: `state/tasks/<name>.md` is name-keyed, overwritten in place by every respawn/steer/resume, and handed to the worker read+write via `--add-dir tasks_dir()` (`bin/fleet.py:7395`) — a worker can rewrite its instructions, do the wrong work, and rewrite them back. Requires N1 at **five** dispatch sites, not one.
- **O2 — contract stability.** The bound spec's `accepted_digest` matches the file and is unchanged across the worker's lifetime. Requires N4 (a spec reference on dispatch events; no event carries one today).
- **O3 — output within contract.** The touched-path set ⊆ effective scope, derived by a **genuinely disjoint mechanism** from the SDD gate: `git diff-tree -r --name-only <base> <head>` over commit objects, versus the gate's worktree-state union. v1 claimed "independent re-derivation" while its own header made the SDD verifier its substrate — one file, one helper, one bug, shared fate. Different inputs, different failure modes, or the disagreement rule is dead code.
- **O4 — verification actually ran.** The verify stamp exists for the current digest and its criteria ids match. Ordering is by **event-log arrival**, which fleet writes — never by commit dates, which the subject writes.
- **O5 — topology (structural only).** Alarms: spawn depth > 1; identical `task_sha256` re-dispatched. **v1's flagship alarm is deleted:** "spawner is a worker" is not derivable — the sid strip makes a worker-invoked spawn record `spawned_by = None`, *indistinguishable from a human shell*, and the `spawned` event carries only `cwd`+`mode` (`bin/fleet.py:2464`). v1 would have passed on its own founding scenario — the M-E "a detector must detect its founding incident" failure, repeated. Restoring it requires N2 (`spawner_kind` as **data**, not authz). The spinning detector is also deleted: a worker spiraling *inside* one turn emits no outcome record at all, so v1 was blind to its own §1.2 founding case.
- **O6 — evidence integrity (NOTE, not CRITICAL, until N5).** `_append_event_quiet` **deliberately swallows `OSError`** (`bin/fleet.py:706-721`) and `append_event` uses a plain buffered append — the very API `stop_outcome.py` documents as losing whole records under concurrent Windows writers. Lost events are a *designed-in normal condition*. **A CRITICAL derived from a knowingly lossy channel is inadmissible**, and would wedge campaigns on benign interleaving. Orphan-sid detection must compare against `_events_sids() ∪ registry sids ∪ archive sids` (the husk sweep's existing union) or it false-positives on every `clean`ed and every `archive`d worker — permanently and cumulatively.

## 5. Verdicts and authority

**Split lattice** (v1 collapsed two conditions onto one verb, which let an operator permanently silence a *broken auditor* — the one thing §2.4 says must never be silent):

- **`cannot-audit` = frozen, not concluded.** Blocks the gate, surfaces loudly, and is cleared **only by a successful re-run** — never ackable. This matches fleet's ambiguity doctrine everywhere else (`dead-suspected` surfaced-never-acted, G9 epoch freeze, "never assume dead on ambiguity"): when fleet cannot see, it freezes and refuses to *conclude*, it does not convert uncertainty into a negative verdict about the subject.
- **`CRITICAL` = a detected violation.** Ackable, scoped to `(finding-id, evidence_head)` so an ack never carries across new evidence.
- **Circuit breaker** (librarian doctrine, `knowledge/INDEX.md:8` — *mass-ref-miss = config-error abort*): if more than N campaigns fail in one run, the verdict is `oracle-misconfigured` — abort, block **nothing**. A bad `--fleet-home` must not wedge the fleet.
- **Escape hatch:** `spec verify --no-oracle`, loudly stamped. One auditor bug must not wedge a fleet with no human watching — and since workers can write the evidence, `cannot-audit` is *worker-triggerable*, making a DoS the cheapest attack without this.
- **No kill authority.** Never stops, kills, respawns, or demotes. Gate teeth only.
- **`ack` cannot reuse `_confirm_destructive`** — that guard exempts callers with no `CLAUDE_CODE_SESSION_ID`, which is exactly what a worker looks like after the env strip. `ack` needs affirmative operator proof (claim-holder + an out-of-band challenge value), and must record which was used.
- **The oracle's own stamp needs the freshness rule it demands of others** — v1 required verify stamps to postdate the last commit while its own stamp had no freshness rule at all, i.e. O4's stale-green applied to the auditor. The gate requires a stamp whose `evidence_head` equals the audited head.

**Doctor is note-only** (`ok=True` always), matching `dead_suspected`/`limited_parks`/`autoclean`. An open CRITICAL is *worker misbehaviour* — the note-only category. FAIL only when the **auditor itself** is broken (stamp unwritable, scheduled task absent, last run older than its interval). v1's RED would have turned the whole machine's health red until a human acked, on a box premised on there being no human.

## 6. Surface

`oracle run [<campaign>]` (mutating; refuses a registry-sid caller) · `oracle status` · `oracle ack <campaign> <id> --reason`.

- Flags route through **`status_snapshot()`**, not a parallel stamp-read view path — invariant 9 is *one state, many views*; a view holding independent state is a second derivation.
- Mutating `/fleet:oracle-*` commands are **prompt templates, never inline `` !`cmd` ``** (CLAUDE.md; `tests/test_terminal_surface.py` lint).
- **Fencing applies to every agent-read surface** — doctor message, status flag, SessionStart briefing — not just "a human or a judge". The manager LLM reads those, and it is the injection target. Cap embedded untrusted prose to a hash + length rather than the text (`knowledge/INDEX.md:8`, evaluate-never-obey).
- Scheduling: needs its **own** subcommand-keyed ownership predicate (`_fleet_task_is_ours(cmd, "oracle")`) — path-only ownership silently voided the F4 guard the moment a second fleet task existed (`docs/SPEC.md:247`), and `/Create /F` would clobber. **`[UNBUILT — POSIX seam]`**: the autoclean bridge is Windows-only (`_PosixPlatform` raises); invariant 8 requires all three OS implementations or an explicit gap note. This is the gap note.
- **Stamp lifecycle:** `archive`/`clean` enumerate from *registry records*; campaign-keyed stamps have none. Either autoclean Tier 1 reaps stamps whose campaign has no non-archived worker, or mark `[UNBUILT — no sweep owns these]` so it lands on the docket (`docs/SPEC.md:191` records this exact litter class).

## 7. Snapshot discipline

The oracle audits a live, concurrently-written substrate. It must take a coherent snapshot before evaluating: read `events.jsonl` to a fixed byte offset and **discard a trailing partial line** (never read it as truncation — that path produces a spurious `cannot-audit`, i.e. a self-inflicted wedge); pin `git rev-parse HEAD` once and evaluate O3/O4 against **that commit's materialised tree**. CLAUDE.md already binds this discipline for receipts — *"a receipt is a claim about a commit, not about `HEAD`"* — and it applies verbatim. Record all four evidence-source identities in the stamp, not one scalar.

## 8. Testing

- **Founding-incident rule, honestly stated.** M-E requires a detector to detect the real artifact of its founding incident. **No penetration or spiral artifact exists in this repo** — so that rule cannot be executed here, and v1's fabricated worker-spawns-worker fixture was the exact fabrication M-E indicted. The live pin is the substitute; **the first real incident becomes the fixture, and every check is re-run against it before being trusted.**
- **Adversarial pin that must SUCCEED today.** A live worker tasked with defeating the audit by any means — clearing the tripwire, rewriting `events.jsonl`, forging a commit date, setting `CLAUDE_CODE_SESSION_ID`. It is expected to win, and that pins the gap. A design claiming isolation must have a test that tries to break it.
- **Theater probe:** disable each check in turn; any suite that stays green is a CRITICAL finding. v1 fault-injected inputs but never the checks.
- **Untested in v1, required:** `ack` against a caller with no `CLAUDE_CODE_SESSION_ID`; behaviour under G9 epoch-suspicion; a tampered/absent stamp; concurrent `oracle run` × `autoclean` on `events.jsonl`; a post-`clean` and post-`archive` fixture for O6's orphan check (the dominant benign source).
- Register as a numbered pin in `tests/integration/test_native_pin.py` (FLEET_LIVE tier), which has caught three prod CRITICALs invisible to 1,300 unit tests.

## 9. Unbuilt / deferred (was v1 §4, wrongly normative)

Respawn-count and re-dispatch-count thresholds; token-spend spiral detection; the "spawner is a worker" alarm (needs N2); O6 gap detection as CRITICAL (needs N5).

## 10. Prerequisites — none of O1–O4 is buildable today

**N1** `task_sha256` + a `dispatched` event at **five** sites (`dispatch_bg` emits no success event at all) → O1.
**N2** provenance on events: `spawned_by` + `spawner_kind` from `FLEET_WORKER` **as data** → O5.
**N3** **git at all** — `bin/fleet.py` contains *zero* git invocations; no sha, tree, diff or base-ref is recorded anywhere → O2/O3/O4. (M-F's job.)
**N4** a `campaign` identity — the word appears in **no** `.py` file; per-campaign scoping is currently unimplementable, so §residual "per-campaign vs fleet-wide" is not a preference.
**N5** hash chain + `_atomic_append_bytes` for `events.jsonl` → O6 as CRITICAL.
**N6** a registry/claim-keyed caller refusal (no verb refuses a worker caller today; `_require_claim_holder`'s missing refusal is already a filed defect).
**N7** a caller-is-an-agent guard distinct from `_confirm_destructive`.
**N8** a second scheduled-task identity + POSIX seam.
**N9** orphan-sid attribution via the three-way sid union.

## 11. Prerequisite milestone if penetration defense is actually wanted

Detection is the honest v1. A real boundary needs, in order: `state/` write-denied to the worker token; the oracle running under a **separate service account**; a hash chain anchored outside `state/`; and worker `permissions` deny-rules in `worker-settings.template.json` (there are none today). That is a security milestone with its own spec — and it is the only path that makes any of §4 an actual control rather than a speed bump.

## 12. Shipped defects surfaced by this review (independent of the oracle)

1. **`append_event` uses a buffered text append** where `stop_outcome.py:41-60` documents that plain `open(...,"a")` loses whole records under concurrent Windows writers. The event log fleet calls durable evidence is written with the API its own hook rejects. → use `_atomic_append_bytes`.
2. **`--add-dir tasks_dir()`** grants every worker write access to **every other worker's** task file. → move task files to a sibling `worker-tasks/` so `--add-dir` never hands a worker a path adjacent to the registry and event log.
3. **`_confirm_destructive` is a no-op inside a worker** — the env strip makes every worker present as the human shell the guard deliberately exempts.

## 13. Residual operator decisions

1. **Ship as an honest detector (recommended), or hold until the §11 boundary exists?** Recommend shipping detection — it has real value against derangement and drift, and M-E set the precedent with claim-nonce. But it must be *documented and named* as detection, never as a penetration defense.
2. **N1–N9 as their own milestone, or folded into M-G?** Recommend a prerequisites slice first — most of them (git substrate, campaign identity, event provenance) are useful to fleet independently of the oracle.
3. **Do the three §12 shipped defects preempt this work?** Recommend yes for #1 and #3 — both are small, both are live, and #1 undermines any future evidence claim.
