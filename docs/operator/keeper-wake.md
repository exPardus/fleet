# Keeper wake through fleet send — G-K8 C

The keeper's `supervisor-stalled` rule runs
`fleet sup-guard --do --fleet-home <home> --json`. The guard owns the liveness
decision and repeats its observation immediately before acting. The keeper
does not maintain a separate idle detector. G-K8 C replaces the private daemon
socket wake from `851e797`; `--wake-socket`, `--wake-key`, socket credentials,
and the old 15-minute observation window are removed.

| Guard result | Keeper behavior |
| --- | --- |
| `WAKE <body-name>` | The guard calls `fleet send supervisor @supervisor/briefs/wake.md`; it never calls `sup-spawn`. |
| `DISPATCH` | Page the interface, which rechecks the guard and owns `sup-spawn`. |
| `PAGE <reason>` | Page the interface with the reason. A failed guard or send also pages. |
| `quiet: true` (fresh healthy body or inactive goals) | No send or supervisor-stalled page. Other keeper rules still run. |
| `PAGE supervisor limited` | Page once for that body and limit horizon; defer another attempt until the roster's horizon. An unknown horizon does not license a retry. |

A stale idle body must have a live PID in its current body’s SID union before a wake is allowed.
Stale state without a live body pages the interface. Busy, missing, ambiguous,
handoff, or changed-claim observations never authorize a second supervisor.
Successful delivery alone is not a fresh heartbeat or evidence of completed
work. Ordinary page deduplication remains; a limited body's horizon controls
its retry instead of an arbitrary timer interval. The JSON result marks a
successful wake with `sent: true`; the keeper consumes the guard's `sent` and
`quiet` flags without deciding liveness itself. The guard runs before pane
handling, so a broken interface pane cannot prevent the wake attempt.

Limited state is read from native body rows or the matching fleet status row;
the reset field is `limit_reset_at` (ISO timestamp). After the horizon passes,
the page requests interface resume; the guard still does not send to a limited
body because `fleet send` refuses parked bodies. The private native roster
limit-field contract was not established by this fenced lane; preserve the raw
roster and identify the actual limit fields during live acceptance.

An idle `fleet send` fork-steers: it takes `fleet.lock`, calls
`dispatch_bg(resume_sid=...)`, and mints a new SID. The pre-steer SID becomes a
retired SID of the current body. It can be stopped only after the fork is
observed live and there is no unread mail for the retired SID. A successful
send alone is insufficient. This exception retires the old process; it does
not archive the current supervisor body or remove its claim. Unverified forks,
unread mail, and overlapping ownership retain their protection.

## Service configuration

Use the existing oneshot keeper and timer, with the
[service template](systemd/fleet-keeper.service). Remove obsolete wake arguments
from any installed override and remove `FLEET_WAKE_SOCKET`/`FLEET_WAKE_KEY` from
its environment file. Retain `FLEET_HOME`, the intended `CLAUDE_CONFIG_DIR`, and
a stable `PATH` reaching the installed Claude CLI. No socket key is required.
The keeper's `--dry-run` makes no send, page, or keeper-state write. Serialize
manual ticks with the existing timer. These instructions do not install,
activate, or certify a systemd unit.

## One live wake receipt — supervisor executes

The fenced lane cannot run this proof. The supervising tier performs it after
landing, using the intended home and a naturally stale, idle, PID-bearing body
with active goals. Do not force a limit or stale heartbeat to manufacture the
receipt. Arrange that the existing timer cannot overlap this one manual tick;
restore its normal schedule afterward using the installation's operator control.

In one shell, select the home explicitly and capture read-only evidence:

```sh
fleet_wake_home=/home/altai/proga/fleet
fleet_wake_receipt=$(mktemp -d /tmp/fleet-wake-proof.XXXXXX)
env -u CLAUDE_CODE_SESSION_ID claude agents --json --all > "$fleet_wake_receipt/roster-before.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" status --all --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/status-before.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" sup-status --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/sup-before.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" sup-guard --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/guard-before.json"
cat "$fleet_wake_receipt/guard-before.json"
```

Proceed only if the guard says `WAKE <body-name>`. Record the current SID and
PID from the roster and guard SID union. Execute exactly one keeper tick:

```sh
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet_keeper.py" --once --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/keeper.log" 2>&1
env -u CLAUDE_CODE_SESSION_ID claude agents --json --all > "$fleet_wake_receipt/roster-after.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" status --all --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/status-after.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" sup-status --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/sup-after.json"
env -u CLAUDE_CODE_SESSION_ID python3 "$fleet_wake_home/bin/fleet.py" sup-guard --json --fleet-home "$fleet_wake_home" > "$fleet_wake_receipt/guard-after.json"
```

Allow the awakened turn to complete, then repeat only the four read-only
after-capture commands. Preserve intermediate captures if the turn is still
busy. Check all of the following:

- One send and one new SID, belonging to the same supervisor body and claim
  lineage; no `sup-spawn` or additional supervisor body. Normal nonce rotation
  during the resumed claim protocol is expected.
- The fork was observed live before the old PID was stopped. The old SID has
  no unread mail and no live PID afterward; the body's live PID count returns
  to one. A lingering protected parent means the memory acceptance is pending.
- A busy transition or actual response, followed by a refreshed heartbeat;
  neither a successful subprocess return nor an idle roster row proves work.
- Token cost from this body's before/after roster SID union only. Use the
  roster's `usage.input_tokens` + `usage.output_tokens`, equivalent `tokens`
  fields, or its `tokens:in=X out=Y` representation. State which fields and
  whether the fork starts at zero or inherits counters. Subtract a documented
  inherited baseline only; do not subtract the old SID's total from a new
  independent counter or count unrelated workers. Missing counters or an
  unknown fork baseline mean **UNMEASURED**, never zero.
- Report the numeric per-wake delta and both roster files. If it exceeds about
  **20,000 tokens per wake**, say so plainly. The operator decides whether a
  cheaper in-place resume merits a second wave; this lane does not choose it.

A naturally limited body should produce one `supervisor limited` page and no
send or repeat page before its recorded reset horizon. Preserve that horizon
and the keeper log if this case is observed; a synthetic test is not live proof.
