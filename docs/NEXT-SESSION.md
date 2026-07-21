# Next session — after M-E (merged + pushed, closed 2026-07-21)

Previous handoff (M-D) is superseded and closed. M-E campaign record: `knowledge/lessons.md#2026-07-21-me`. Supervisor journal has the blow-by-blow; the ledger (`docs/PLAN-PROGRESS.md`) has every wave and verdict.

---

# FIRST ACTION — put the ratification docket to Altai, before any work

Four campaigns of decisions are now queued behind the operator, and the queue is the bottleneck: the nonce slice blocks the three-tier re-draft, which blocks the supervisor tier, and eleven contract markers have been sitting `PENDING` since M-D. **Do this in your first turn, in one message, before spawning anything.**

Present the docket below and ask for a decision on each. Use `AskUserQuestion` where the choice is genuinely multiple-choice (items 2 and 3), plain prose for the rest. Give your recommendation on each — the operator's standing preference is a named recommendation with the alternative stated fairly, not a menu.

**Rules that bind you while doing this:**
- **You may not ratify any of it yourself, and neither may a worker.** An author never promotes its own spec; a reviewer may not ratify one either. Record each answer as a dated line in `knowledge/lessons.md` — never session memory.
- If the operator defers an item, mark it deferred **in this file** with the date, and carry on with the work that is not gated on it (§"The job" below has ungated items).
- If the operator ratifies, the follow-through is a *commit*, not a claim: flip the markers, promote the `Status:` line, and say which commit did it.

## The docket

**1. `docs/specs/native-substrate.md` — 11 `[PENDING OPERATOR RATIFICATION]` markers across 8 rows.** Ten are the 2.1.212 set from M-D (transient daemon and its idle-exit; `claude daemon stop`'s machine-wide blast radius; the `gone`→success precondition; `stop` firing no Stop hook; the 3-way `rm`/`stop` ambiguity). One is M-E's new 2.1.216 row: the `daemon.lock` PID-reuse wedge. Ratifying makes them contract-of-record — the thing every future spec and pin test is written against. **Recommendation: ratify all eleven.** Each carries executed receipts, and the 2.1.216 row additionally has a shipped detector and a live green pin behind it. The one honest caveat, stated in the rows themselves: three dead-daemon claims remain manager-report-only, because a `--bg` worker is a live daemon client and structurally cannot observe that path.

**2. `docs/specs/claim-nonce.md` — `Status: drafting`, and five open questions.** Two full dual-lens design gates; final verdicts `sound` (break lens, which verified the env-var spoof by *executing* the pure decision function against shipped code, v3's rules and v2's clause) and `fix-list(F1,F2) → closed` (spec lens, 49/49 receipts sound, harness seeded by the reviewer). Adjudication + the manager's own three corrections: `docs/reviews/ME-NONCE-ADJUDICATION-2026-07-21.md`.

  **The load-bearing question, which the others hang off:** on this box there is **no authorization input that is neither view-derivable nor an environment variable**. Every worker can read `FLEET_HOME`; `sup-status` publishes the holder's identity. So:
  - **(a) detection-only, no gate** — cheap, ships alone, and **does not close the dual-supervisor incident** (the 2026-07-16 zombie ran only `fleet send`, and non-presenters never enter the mechanism);
  - **(b) a gate that is knowingly bypassable** — the only option that *does* close it, at the cost of documenting a bypass in the design;
  - **(c) build an authorization input first** — new scope, new slice, and nothing ships until it exists.
  **Recommendation: (b), explicitly documented as bypassable.** Its honest failure mode is a determined actor with shell access — who already has everything. Option (a)'s failure mode is the incident that motivated the whole slice recurring silently.

  Then: promote the spec to spec-of-record, or send it back. **Do not build until this is answered.**

**3. `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` — DRAFT v3, untouched since 2026-07-18.** Two review rounds folded (four lenses, then a new-defect hunt that found a CRITICAL RCE the first fold had introduced). It is a large subsystem — spec artifact, verifier, binding, a Stop-hook fence. Ask: **M-F candidate, shelved, or narrowed to its Phase-1 gate only?** **Recommendation: narrow to Phase 1 (the deterministic `spec verify` gate) and defer the live Stop-fence** — the fence is the defect-dense half and the gate delivers most of the value alone.

**4. `docs/specs/three-tier-command.md` — still `PROPOSAL`.** Restructure ratified by review, never by the operator. Gated on item 2: the nonce is its hard prerequisite. Nothing to decide today beyond confirming it stays queued behind the nonce.

**5. Confirm the standing budget envelope for M-F**, and whether the dogfood-outward run (§"The job" item 5) should preempt the queue. It has been overdue since 2026-07-09 and is the highest-value defect report available.

---

## State (all verified at close)

- **M-E shipped and pushed.** `main` = `fleet-impl` = `6cd4fa7`. Four branches merged (`me/ul`, `me/daemon`, `me/defects`, `me/nonce`). **1302 unit tests + 6-pin FLEET_LIVE tier green on claude 2.1.216; doctor 23 PASS / 0 FAIL; pin-gate stamped 2.1.216.**
- **The 9th live catch was a SUBSTRATE failure, not a contract break.** A stale `~/.claude/daemon.lock` naming a **recycled pid** (Windows gave 15740 to `WacomHost`, whose start time is unreadable to a normal-token probe) killed every `--bg` dispatch machine-wide for ~16h while `fleet doctor` read all-PASS. `claude daemon stop --any` does **not** clear it; removing the lock does. Fleet now has `_doctor_check_daemon_wedge` (file-only signal, starts no daemon) and a dispatch-error classifier that names the cause and a precondition-first remedy. Receipts in `docs/specs/native-substrate.md`.
- **New standing tooling: `tools/verify_receipts.py` + `tests/test_receipts.py`.** Every pasted receipt in `docs/specs/**` is re-executed and diffed, resolved at its `# at <sha>` pin via `git archive`. Unpinned receipts, moving pins (`# at HEAD`) and absent commits are errors under `--strict`, never skips. `CLAUDE.md` carries the doctrine line. **Run `--self-test` before trusting a green run.**
- **Campaign template → v1.8** (vantage gate, founding-incident gate, demand-driven-evidence rule, reviewer-remedies-are-fix-waves, receipts-as-executable-claims, merge-target testing, commit-only, RESULT-line exemption).

## Operator gates open (need Altai — nothing below is ratified)

1. **Ratify or reject the `native-substrate.md` rows.** The 2.1.212 set from M-D is still `[PENDING OPERATOR RATIFICATION]`, and M-E added a 2.1.216 row for the daemon-wedge hazard. Eight markers total, all untouched by the merges.
2. **Claim-nonce spec — `docs/specs/claim-nonce.md`, `Status: drafting`.** Two full dual-lens design gates; final verdicts **`sound`** (break) and **`fix-list(F1,F2)` → closed** (spec, 49/49 receipts sound, harness seeded by the reviewer). Not spec-of-record, no build has started. Adjudication + addendum: `docs/reviews/ME-NONCE-ADJUDICATION-2026-07-21.md`. **Five questions are waiting on you**, the load-bearing one being: on this box there is **no authorization input that is neither view-derivable nor an environment variable**, so the honest options are (a) detection-only with no gate — which *does not close* the dual-supervisor incident, (b) a gate that is knowingly bypassable — the only option that does close it, or (c) build an authorization input first, as separate scope.
3. **SDD / drift-control design v3** (`docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md`) — still DRAFT, untouched this campaign, still operator-gated.
4. **Three-tier command** — `PROPOSAL`, restructure ratified by review only. The nonce slice it depends on is now gated-and-sound; a re-draft is the next step *after* decision 2.

## The job: pick and run M-F

Priority-ordered:

1. **Decide the nonce gate question (2 above), then either build the detection slice or re-draft three-tier on top of it.** This is the critical path for the supervisor tier and everything queued behind it.
2. **Three shipped-code defects filed by the nonce gate, none fixed:** (a) **a worker turn can hold the supervisor claim** — `_require_claim_holder` has no `FLEET_WORKER` refusal, and today it is prevented only by accident; (b) `supervisor/INCARNATION.tmp` and `supervisor/HANDSHAKE.tmp` are not gitignored; (c) the published exit-code contract says 0/2/3 while the code has a 4 with no seam. Small reviewed fix task; (a) is the one that matters.
3. **Residuals carried from M-E's final gates**, all named with exact fixes: nonce break-lens F1/F3 (a `fleet clean` double standard; a "stops" that is really a two-TTL bound); spec-lens F3 note (three latent harness gaps, all documented); `me/defects` G-nits (G1 the shape guard's newline case is fixed but its class deserves a lint; G4's stale line-anchored receipt — now exactly what `verify_receipts.py` exists to prevent, so point it at more documents).
4. **Point `verify_receipts.py` at the rest of `docs/specs/`.** Only `claim-nonce.md` is enforced today; `native-substrate.md` pastes evidence with no `# at <sha>` pins and is declared UNENFORCED with a reason. Adopting the convention there is that spec's owner's call — and it is the highest-value place to adopt it, since those receipts are the vendor contract.
5. **Dogfood outward** (standing goal 5): now badly overdue — last external run was stupidbox, 2026-07-09. An external campaign is still the highest-value defect report available.

## Standing rules (unchanged, they keep earning it)

- CLAUDE.md binds (`py -3.13`; forward slashes in hook commands; no Git-Bash `&`; views read-only; **receipts re-executed by `tools/verify_receipts.py`**). On Windows post-restart the Git-Bash PATH can come up broken — call `py -3.13 bin/fleet.py` directly and `export PATH=/usr/bin:/bin:/mingw64/bin` in Bash.
- **Run the live pin tier on every `claude` bump.** It has now caught nine things, and the 9th was neither our code nor the vendor's contract but the substrate underneath both. **State the probe context AND the vantage** of every receipt: who ran it, and from which worktree / `FLEET_HOME` / commit. The manager filed a phantom regression this campaign for want of the second half.
- **Replay the founding incident through any detector before believing it**, and when the real artifact exists, the fixture *is* the real artifact. A test that fabricates its own evidence is how a check that cannot fire ships green.
- Adversarial + spec review pairs on every branch; **new-defect hunt on every wave, including waves the reviewer itself prescribed** (fired 6/6); grep-receipt gate on every enumeration; no author promotes its own spec; **`ESCALATE` beats a third wave** — used correctly this campaign, twice, with a named restructuring instead of a third finding list.
- **Disputes carry receipts, in both directions.** A builder overturned a manager ruling with PEP 495 and an 8784-sample sweep and was ratified; a reviewer withdrew its own CRITICAL's remedy on an author's three receipts. Both outcomes are the process working.
- `git log` is the only truth a turn landed. A Monitor until-loop survives session teardown better than `fleet wait ... run_in_background` — but re-arm it after any conflicted merge, since it parses a broken `fleet.py` as garbage and exits.
- Push `fleet-impl` + ff `main` at every green milestone. Supervisor `GOALS.md` binds the manager (frugality, long beats, 300–500k handoff band). **Claim wart, still live until the nonce ships:** after a >60m heartbeat gap `sup-boot` refuses the same-sid holder — recover with `sup-heartbeat`, not `sup-boot`.
