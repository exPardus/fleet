# Operator gates

Decisions only Altai can make. **The SessionStart hook reads this file** (`bin/hooks/sessionstart_fleet.py`, `_operator_gate_lines`) and leads every manager briefing with the open items, so a session cannot start work without meeting them.

Format is load-bearing and pinned by `tests/test_supervisor.py::TestOperatorGatesBriefing`:

- `- [ ]` is **open** and gets surfaced. It **must be phrased as a question**, ending in `?`.
- `- [x]` is **settled** and is never re-surfaced. Tick it, append the date and the answer, and leave it in place — a settled gate is the record of a decision, not clutter.
- Keep each line to one decision, front-loaded: the hook shows the line, not this file.

Neither the manager nor any worker may tick a box. An author never promotes its own spec; a reviewer may not ratify one either. Record each answer as a dated line in `knowledge/lessons.md` too — never session memory.

## Open

- [ ] **Contract rows — `docs/specs/native-substrate.md`.** 11 `[PENDING OPERATOR RATIFICATION]` markers across 8 rows: the 2.1.212 set plus M-E's 2.1.216 `daemon.lock` PID-reuse wedge. Each carries executed receipts, and the 2.1.216 row has a shipped detector and a live green pin behind it; the caveat stated in the rows themselves is that three dead-daemon claims stay manager-report-only, because a `--bg` worker is a live daemon client and structurally cannot observe that path. Manager recommends ratifying all eleven — ratify all, ratify some, or reject?
- [ ] **Claim-nonce — what does the claim gate?** On this box there is no authorization input that is neither view-derivable nor an environment variable. Manager recommends (b), documented as bypassable: its failure mode is a determined actor with shell access, who already has everything, where (a)'s failure mode is the motivating incident recurring silently. So: (a) detection-only, which does NOT close the dual-supervisor incident, (b) a knowingly-bypassable gate, the only option that does, or (c) build an authorization input first as separate scope?
- [ ] **`docs/specs/claim-nonce.md`, `Status: drafting`.** Two dual-lens design gates; final verdicts `sound` (break) and `fix-list → closed` (spec, 49/49 receipts sound). Gated on the question above — promoting it without that answer would ratify an unanswered design. Promote to spec-of-record, or send it back?
- [ ] **SDD / drift-control design v3** (`docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md`). Two review rounds folded, including a new-defect hunt that caught a CRITICAL RCE the first fold introduced. Manager recommends narrowing to the Phase-1 `spec verify` gate and deferring the live Stop-hook fence, which is the defect-dense half. M-F candidate, shelved, or Phase-1 only?
- [ ] **`docs/specs/three-tier-command.md`, still `PROPOSAL`.** The restructure was ratified by review, never by you, and the claim-nonce slice is its hard prerequisite. Confirm it stays queued behind the nonce rather than being re-drafted now?
- [ ] **M-F shape and budget.** The dogfood-outward run is overdue since stupidbox on 2026-07-09, and external friction is the highest-value defect report available (standing goal 5). Should it preempt the queue above, and what is the budget envelope?

## Settled

*(Tick a gate above and move it here with its date and the answer. Nothing has been settled through this file yet — it was created 2026-07-21 at the operator's request, after four campaigns of decisions queued up in handoff prose that was read too late.)*
