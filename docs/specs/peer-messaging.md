# Native peer messaging (w110 design + spike)

Status: design and spike, 2026-09-30, Claude Code 2.1.285. Built in this
branch: `fleet address` and `crossSessionInbound: "accept"` in the worker
settings template. Everything under "Proposed" is not built.

Operator request (interface log 2026-09-30T01:36:46Z): "put native
cross-session messaging (ListAgents/SendMessage) into fleet."

## What the native surface is

Claude Code 2.1.28x gives every session two tools:

- `ListAgents` lists live peer sessions on this machine as `name [ref]`, with
  kind (bg or interactive) and busy or idle.
- `SendMessage(to, message, notify_when_idle)` delivers text to a peer. The
  receiver drains it at its next tool round. An idle receiver starts a turn.
  `notify_when_idle: true` subscribes once: the sender gets one
  `[Cross-session idle notice]` when the peer next goes idle or exits.

The receiver sees `<cross-session-message from="uds:..." from-name="..."
from-mode="...">`. The sender is a verified pid. The name is a claim.

Only a Claude session can call these tools. `bin/fleet.py` cannot: the
transport is a per-session unix socket plus a key file under
`~/.claude/sessions/`, which is not a sanctioned surface (native-substrate
contract: fleet reads only `claude agents --json`). Fleet therefore does not
send native messages itself. Fleet tells a session what to send and to whom.

## Spike findings (2026-09-30, two haiku bg sessions, this machine)

| # | Observation | Consequence |
|---|---|---|
| F1 | `to` must match the full name exactly. A prefix (`w110spike\|byp`) is refused with `No agent is named '...' exactly. Re-send with the ref to confirm you mean: w110spike\|bypass [414367]`. | Fleet names are `cat\|name\|hint`, where the hint is the first 40 characters of the dispatch prompt. A caller cannot guess it. `fleet address` prints it. |
| F2 | A `dontAsk` receiver HELD a message from a bypass sender: "Held peer message ... The sending session's permission mode class doesn't match this session's. Review it below, or set "crossSessionInbound" to "accept"." A bg session has no user to approve it. | Fleet lanes default to `--mode dontask`; supervisors run bypass. Without an opt-in, supervisor-to-lane messages never arrive. |
| F3 | bypass to bypass: the idle receiver woke, replied, and went idle again. | Delivery to an idle session works. |
| F4 | The receiver's first reply used the truncated display name and failed (`Not sent -- no agent named '...Read and execute the brief /home/user…' is reachable`). It retried with the full name and succeeded. | Long names cost retries. Reply to the `from` attribute. |
| F5 | An incoming message fires the receiver's `UserPromptSubmit` hook. | A fleet hook can log inbound peer traffic. Not built. |
| F6 | The subscribe result says an idle notice goes to the model only when both sessions share a permission class. Otherwise it goes to the user's transcript. | LANE-DONE by subscription needs the lane and the supervisor in one class, or the opt-in below. Not verified with the opt-in. |
| F7 | A `dontAsk` receiver started with `--settings '{"crossSessionInbound":"accept"}'` received the bypass message and replied. Its reply was then held at the bypass sender, which had no opt-in. | Holding is decided by the receiver. Both ends need the opt-in. The worker settings template reaches supervisors and lanes, so one key covers both. |
| F8 | No idle notice reached this session while its turn ran. When the turn ended, three notices arrived together as a new turn: the idle notice for `w110spike\|bypass` ("finished a turn at 06:38. Its harness reports: «Done.»"), a delivery notice that the dontAsk message was held for approval, and a later notice that it "was not approved before expiry". | Notices queue until the subscriber is between turns, then wake it. A held message to a headless session expires silently from the receiver's side; only the sender learns it. |
| F9 | The woken session kept its session id (`3ec7f1b0` before and after). | Native steering does not fork. This removes the G2 fork-steer cost for live idle workers. |

### Registry drift found during the spike

`fleet address px-w12-advmodels` (projectx home) showed that the registry sid
`1455e86b` has no process, while the retired pre-fork sid `a56265ad` is still
live and idle under the old name `fleet|px-w12-advmodels|You are fleet worker
...`. px-w18-q36wx has the same shape. Fork-steer (`--bg --resume`) leaves the
original body running. The fork exits after its turn. Two consequences:

1. A native message sent to the worker's usual name reaches a retired body
   that fleet no longer tracks. The operator's live "pong" test on
   2026-09-30 was answered by that retired body.
2. Retired bodies hold RAM on an 8 GB host.

`fleet address` refuses to return a retired sid and warns when one is live.

## Built in this branch

### `fleet address <worker|supervisor> [--json]`

Read-only. No lock, no writes, effect tier `ordinary` (pending operator
ratification). It resolves `supervisor` to the claim holder, joins the
registry `session_id` to one `claude agents --json --all` row, and prints that
row's exact `name`. Use that value as the `SendMessage` `to`.

- Refuses when the sid has no process (`pid` absent) or a status outside
  `idle`, `busy`, `waiting`. Use `fleet send` in that case.
- `waiting` (the session is on a permission prompt) is addressable. It prints
  a note that the message queues until the prompt clears.
- Warns when a retired sid of the worker is live, and names it.
- Refuses when two or more live sessions share the name: SendMessage resolves
  by name and ListAgents shows no session id, so the caller cannot tell the
  bodies apart. Exit is non-zero; the message (and the `--json` `error`
  field, with a `duplicates` list) names each pid and session id and the
  `claude stop <sid>` for each body that is not the registry sid.
- Codex workers are refused. They have no Claude session.

### `crossSessionInbound: "accept"` in `worker-settings.template.json`

Every session that fleet dispatches with the rendered instance settings
(lanes, supervisors, successors) accepts cross-session messages from any
permission class. Re-render with `fleet init` in each home to apply it.

Risk: a bypass supervisor now acts on messages from dontAsk lanes and from any
other same-user Claude session without a held-message prompt. Fleet already
steers workers through a same-user mailbox file, so this adds no new principal.
It does remove the class check that stops a lower-permission session from
directing a bypass session. Sessions that must keep the check can drop the key
from their home's rendered `state/worker-settings.json`.

The interface session is the operator's own interactive session and is not
rendered by fleet. The operator decides whether to set the key there.

## Proposed (not built)

Ordered by value.

1. **Supervisor subscribes to its lanes.** After `fleet spawn`, the supervisor
   calls `SendMessage(to=<fleet address lane>, notify_when_idle=true)` with no
   message. The idle notice wakes the supervisor in the same session with the
   lane's turn summary, which is a LANE-DONE payload. Re-subscribe after each
   notice, because it is one-shot. The Stop-hook LANE-DONE path stays as the
   backstop. Today that path fork-steers the supervisor, which replays its
   whole transcript into a new sid. Needs: a skill rule, and a dedupe rule in
   the skill (a notice and a LANE-DONE for the same lane turn are one event).
2. **Idle steer without a fork.** `fleet send` keeps its gates (supervisor
   nonce, token ceiling, status checks), then for a live idle native worker
   prints `NATIVE <address>` and records a `native_steer` event instead of
   fork-steering. The calling session then sends the text with SendMessage.
   A dead or reaped worker still fork-steers. Fleet cannot enforce that the
   caller sends. This is protocol, like every other skill rule.
3. **Lane-to-supervisor questions.** The task-file preamble names the
   supervisor address (`fleet address supervisor`). A lane that is blocked
   asks there instead of ending its turn with a question.
4. **Inbound audit hook.** A `UserPromptSubmit` hook (F5) appends
   `peer_message_in` events with `from-name` and `from-mode`. Workers act only
   on messages from their supervisor or the interface and report others.
5. **Stop the retired body after a fork-steer.** Until item 2 lands, a fork
   steer should `claude stop` the pre-fork sid once the fork is joined. That
   frees RAM and removes the stale address. This touches the dispatch path and
   needs its own review.

## Open questions

- Q1. Answered by F8: a busy subscriber gets the notice when its turn ends.
- Q2. With `crossSessionInbound: "accept"` on both ends, does an idle notice
  across permission classes go to the model? (F6)
- Q3. Does an idle bg original stay live without limit? Retired bodies were
  live after 2 days, but G5 reports a roughly one-hour process stop for done
  sessions. If processes are reaped, item 2 falls back to fork-steer more
  often.
