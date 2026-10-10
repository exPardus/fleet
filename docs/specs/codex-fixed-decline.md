# Typed fixed-request decline on a retained old host

This describes `codex-decline-fixed`, introduced by commit
`8c3f73a9ab86a6b30d8598680c772a34c4d00781`. Its original source commit
omitted public documentation; this forward document preserves that omission
in history and documents the current retained implementation. Source adoption
is separate from an independently reviewed home-specific execution procedure.

The operation sends only the literal command-approval `decline` response for
one fully pinned pending native supervisor request. It never accepts a command,
changes permission policy, creates a replacement body, or replays a provider
mutation. It applies only to the reviewed old host identified by
`FIXED_DECLINE_OLD_HOST_SHA256`, whose supervisor reservation capability returns
exactly `unknown host method`; capable or ambiguously responding hosts refuse
this compatibility path and retain their supported reservation route.

Use the CLI help to prepare a complete invocation in an independently reviewed
procedure: explicit `--fleet-home`, typed request ID (`--request-id-type int` or
`string`), literal `decline`, and every required `--expect-*` argument. Integer
IDs must be canonical decimal; JSON integer6 and string"6" remain distinct.
Pins bind the incarnation, thread, current turn, host generation, original host
source SHA, host PID/start identity, original app-server child PID/start
identity/start time, method, item, command, store key and complete request
record digest. Request cwd must match the expected value, or its absence must
be explicitly selected with `--expect-cwd-absent`; absence is not a wildcard.

The current process-bound Interface must own the exact home. The held supervisor
claim and full registry row must match. Public provider and durable callback
observations must agree on the pending command request and its offered `decline`
choice. Unresolved journals, unknown/ambiguous callbacks, typed-ID collisions,
source/process changes and altered request bytes refuse. The implementation
reopens supported metadata and rechecks original host/child OS identity after
its final reads and immediately before the locked claim/row reservation. It
compares the full claim/row, Interface source, journal and callback evidence
again at reservation and settlement. Sibling rows and retained mail are not
rewritten to manufacture continuity.

The response is sent once through the retained supported host. An exactly
proved pre-acceptance rejection may release only its own reservation after
full unchanged-state checks. An accepted response, lost acknowledgement or
ambiguous provider consumption stays fenced and requires supported observation
of the original operation; never resend merely because the caller lost its
reply. A resolved callback is not permission to replay the same fixed action.
Keep original journals, source provenance, process identities and operational
receipts. No source test or publication authorizes live callback handling,
manual journal edits, host termination or a supervisor restart.

Tests: `tests/test_codex_fixed_decline.py` covers typed IDs, complete request
binding, real old-host transport with fake provider, refusal/settlement races,
unchanged capable-host behavior and lost-response containment. These fixtures
are not live procedure acceptance.
