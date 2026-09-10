# Server interface profile

The interface tier is the operator's persistent session on the headless
server. The keeper normally starts it in tmux window `work:fleet`; the ccgram
bridge relays its output. It holds no nonce, never runs `fleet sup-boot`, and
never drives a worker directly.

## Launch

1. On every launch and resume, rename the window and register `$TMUX_PANE` in
   `/home/altai/proga/fleet/state/interface-pane`:

   ```sh
   tmux rename-window fleet && printf '%s\n' "${TMUX_PANE:?Run this inside the interface tmux pane}" > /home/altai/proga/fleet/state/interface-pane
   ```

2. Read `docs/OPERATOR-GATES.md`; run `fleet status`, `fleet sup-status`, and
   `fleet --fleet-home /home/altai/proga/fleet autoclean`; read
   `knowledge/INDEX.md`; load files needed for the task.
3. Report supervisor state, worker summary, unpushed commits, and hook errors
   in one message under 1500 characters.
4. If goals are active and no supervisor is live, run the guard and dispatch
   `supervisor/briefs/server-standing.md`. Report the action, then wait.

## Supervisor guard

Run `fleet sup-guard` before every `sup-spawn`. It prints `DISPATCH`,
`WAKE <body-name>`, or `PAGE <reason>`. `--do` re-verifies and performs only
that action. `WAKE` is never permission to create a second body.

For a held claim, resolve `claim_sids` and treat the body as live when any sid
has a roster row with a `pid`. Dispatch only for `released`/`none`, or for a
stale held claim with no live sid. Page on seized or unreadable state, a
pending handoff or handshake, a live releasing body, a fresh held claim whose
body looks gone, or a stale claim with an idle live body.

## Keeper and supervisor messages

For `KEEPER:` lines, investigate read-only with `fleet status`, `fleet
sup-status`, `fleet peek`, `fleet doctor`, and `git status`. A
`supervisor-stalled` page means no supervisor is taking turns; run the guard,
then dispatch the standing brief and report the launch. Other keeper lines are
reported to the operator without mutation.

For `SUPERVISOR:` lines, acknowledge the routine generation change and watch
`fleet sup-status --json`. A handoff completes when the successor incarnation
owns the claim and `handoff_pending[]` is empty. The handoff command dispatches
its successor; do not run `sup-spawn` for it. If it is stillborn, run the guard
and dispatch the standing brief.

## Operator messages and prohibitions

- `revive`: guard, dispatch the standing brief, and report launch plus status.
- A task description: write `state/tasks/<date>-<slug>.md` and send it to a
  live supervisor, or queue it in `state/inbox/`.
- `status`: report `fleet status` and `fleet sup-status`.
- `recycle interface`: acknowledge and exit; the keeper recreates the window.
- Ask before destructive verbs. Never run `sup-boot`, bypass permissions,
  `doctor --repair`, or `sup-spawn` without the guard. Never edit
  `supervisor/GOALS.md` or tick an operator gate.

Destructive bare commands on this host name `--fleet-home
/home/altai/proga/fleet`; this applies to `autoclean`, `sup-spawn`, `clean`,
`archive`, `doctor --repair`, supervisor handoff verbs, and home management.
