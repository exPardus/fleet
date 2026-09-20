# Native Codex supervisor boot 6549085 — GREEN

Reviewed exact source `6549085896b6295966330c07448c1a0af6b87a23` on
`4823a5e7ff24fa41749d632ba63d42c20c1f3769`. No blocker remains in the
bounded first-boot slice.

The route requires explicit `sup-spawn --codex-adapter native`; omitted
supervisor routing and worker `mcx` default remain unchanged
(`bin/fleet.py:15142-15164,16523-16535,16727-16742`). Provider-returned thread
and turn IDs require canonical UUIDv7; both cwd fields, model, approval,
reviewer, and sandbox are validated before binding. Preclaim, pending, and held
writes use exact conditional claim/record identity. Changed claims are
preserved; stale provider holders cannot call. Thread/turn journal failures
freeze the matching claim and record, while recovery metadata and conservative
host reconciliation remain intact. Fleet-level host-restart resumption stays
explicitly unsupported (`docs/plans/2026-09-20-codex-native-integration.md:135-143`).

Python 3.10 and 3.12 each passed 61 native/journal, 146 legacy-route, and 16
adversarial tests. Every invocation prepended fail-fast `claude`/`mcx` stubs;
the attempt marker stayed zero. The incident is recorded at
`state/interface/log.md:229`; current exact `claude`/`mcx`, incident-session,
and `codex app-server` process counts were all zero. No live provider, bridge,
default enablement, descendant, or external action ran.
