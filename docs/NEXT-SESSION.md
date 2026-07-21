# Next session — after M-E (merged + pushed, closed 2026-07-21)

Previous handoff (M-D) is superseded and closed. M-E campaign record: `knowledge/lessons.md#2026-07-21-me`. Supervisor journal has the blow-by-blow; the ledger (`docs/PLAN-PROGRESS.md`) has every wave and verdict.

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
