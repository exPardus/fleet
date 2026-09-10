# Keeper existing-body wake — operator installation

The optional G-K6 B wake runs inside the existing keeper `--once` tick. It sends
local daemon protocol-1 `reply` to the current claim-holder's existing process.
The keeper never launches a supervisor body, calls a model, runs `fleet send`, or
falls back to daemon startup. The existing page/interface behavior remains.
The first possible model call belongs to the target Claude process. If the plan
refuses that call, the keeper continues ticking; delivery is not a heartbeat.

This transport is measured from the installed Claude **2.1.267 source**, not a
public CLI contract or a completed live acceptance run. Recheck the source/API
on a Claude upgrade. The source does not provide atomic compare-and-deliver by
session/claim: final revalidation narrows the race, and the wake prompt requires
the receiver to verify authority before acting.

A wake requires active GOALS, a readable settled nonce-bearing held claim, no
pending nonce, decision, handshake or handoff residue, a resolved sid union,
the current claim sid idle and no union row busy/waiting/unknown-live. After
15 minutes of observed idle, a fresh heartbeat still defers the wake. Otherwise
the keeper refreshes the claim/roster and requires a live `background` `working`
row with a PID. It never targets a retired sid or resumes a corpse. Ordinary
sampling gives the first attempt after 15–30 minutes of idle, well before the
ordinary eight-hour retirement; daemon low-memory retirement can be faster.

`state/keeper/last-page.json` gains one key, `_supervisor_wake`, containing the
identity, idle observation time, last attempt time and transport result. Every
attempt, including a timeout/refusal, is throttled for 15 minutes. An attempt is
saved before sending; its result is saved before accessing the interface pane.
A broken pane therefore cannot stop wake retries. A busy observation or changed
claim starts a new idle window. `accepted` means the daemon acknowledged a
reply, not that the model ran or work succeeded. `rule_supervisor_stalled` remains
unchanged: stale/missing heartbeat plus a non-busy body still pages. It does not
infer causality from the wake record. The known busy-mid-turn blind spot remains.

The feature is **off unless both `--wake-socket` and `--wake-key` are supplied**.
G-K1's future whole-keeper flag should gate this same tick. B adds no independent
scheduler, hook, model waker or always-on service. Disable/enable may retain an
old observation if no disabled tick ran; a fresh identity/roster check still
precedes any attempt. Serialize manual ticks with the existing service; do not
run concurrent direct `--once` invocations against the same keeper state.

## Installation recipe (operator executes; not executed by this lane)

1. Land the code and tests first. Inspect the existing `fleet-keeper.service`
   and timer and preserve any host-specific environment/hardening. Use the
   [service template](systemd/fleet-keeper.service) and
   [timer template](systemd/fleet-keeper.timer) as replacements for the existing
   names, not an additional scheduler. Confirm `/usr/bin/python3` is at least
   Python 3.10 and adjust `WorkingDirectory` for a different fleet home.
2. Identify the config directory used by the running supervisor's Claude daemon.
   For this Linux host the source resolves the socket as
   `/tmp/cc-daemon-<uid>/<hash>/control.sock`, where `<hash>` is the first eight
   lowercase hex characters of SHA256 of the NFC-normalized absolute config
   directory string. Use absolute path normalization without resolving symlinks.
   The key is `<config-dir>/daemon/control.key`. Do not print or copy its contents.
   `CLAUDE_CONFIG_DIR` overrides the normal `$HOME/.claude` root; Termux uses
   `$PREFIX/tmp` instead of `/tmp` when both Termux variables are set.
3. Create `~/.config/fleet/keeper.env`, mode 0600, with these values adjusted for
   the installation. The `PATH` must reach the installed Claude binary without
   relying on an ephemeral login-shell directory. `CLAUDE_CONFIG_DIR` and the
   socket/key must refer to the same daemon. The keeper also verifies the
   socket's listed target by session ID and PID before replying.

   ```ini
   FLEET_HOME=/home/altai/proga/fleet
   CLAUDE_CONFIG_DIR=/home/altai/.claude
   FLEET_WAKE_SOCKET=/tmp/cc-daemon-1000/8e65fa70/control.sock
   FLEET_WAKE_KEY=/home/altai/.claude/daemon/control.key
   PATH=/home/altai/.local/share/fnm/node-versions/v24.20.0/installation/bin:/home/altai/.local/bin:/usr/local/bin:/usr/bin:/bin
   ```

4. First run the keeper with the intended environment, paths and `--dry-run`.
   That mode sends no daemon reply, types nothing, and writes no keeper state.
   It can report eligibility but cannot attest transport acceptance.
5. Copy the reviewed templates into `~/.config/systemd/user/`, then run
   `systemctl --user daemon-reload` and
   `systemctl --user enable --now fleet-keeper.timer`. If replacing an already
   active timer, use `systemctl --user restart fleet-keeper.timer` to apply its
   cadence. The service is oneshot; do not create a separate wake unit.
6. Observe the service journal and keeper state through two idle samples. Record
   the claim sid and roster PID before/after: both must remain the same. Record
   the wake result, then a busy transition and a refreshed heartbeat. A model
   response or heartbeat is needed to establish successful work; an ACK alone
   is insufficient. During a naturally occurring plan refusal, record continued
   timer attempts and C's stall page with no supervisor dispatch. Do not induce
   exhaustion or interfere with active work just to obtain this receipt.

To turn off only B, remove the two wake arguments from the service's `ExecStart`
and reload the unit; to disable the entire keeper use the existing operator
control for its timer (and G-K1's flag when available). There is no wake process
to stop separately. These instructions are deployment text, not evidence that
installation or live acceptance has happened.
