# Fleet roadmap

Fleet's direction is one durable local state model with several disposable
interfaces. Public source describes generic mechanics; each user's operational
history stays in local per-home storage.

## Current foundation

- Cross-platform Python 3.10+ CLI and hook runtime.
- Native-session lifecycle, mailbox steering, outcome capture, and cleanup.
- Persistent supervisor claim, heartbeat, handoff, and local journal.
- Multi-home resolution with explicit destructive-action guards.
- Read-only terminal views and optional statusline integration.
- Claude and Codex worker substrates behind one registry contract.

## Near-term priorities

- Finish provider-neutral Codex acceptance without relying on private state.
- Improve recovery diagnostics while keeping views lock-free and write-free.
- Reduce context and test cost without weakening the two-interpreter floor.
- Extend portable integration coverage, especially macOS behavior.
- Keep initialization and upgrades non-destructive for existing local homes.

## Design principles

1. One state model, many views.
2. Provider and daemon integrations are replaceable edges.
3. Ambiguity fails closed before mutation.
4. Automation reports evidence; models and humans make judgement calls.
5. Platform-specific behavior stays behind explicit adapters.
6. Tracked files remain generic; operator data remains local.
