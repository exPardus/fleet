# Native Codex bounded live acceptance

DONE means: genuine three-home Interface registration is recorded and one
bounded disposable-home lifecycle either passes or stops with exact public
protocol evidence before any retry.

Date: 2026-09-21

## Interface registration: PASS

`FLEET_CODEX_INTERFACE_ACCEPTANCE=1 python tools/codex_native_acceptance.py
--interface-live` registered the genuine current `CODEX_THREAD_ID` in three
independent disposable Fleet homes named Fleet, PM, and tap. Each claim bound
the same Linux Codex ancestor PID/start identity and a distinct home/claim ID.
The public method sequence was exactly three `thread/read` calls. No provider
mutation journal was written and the external Interface thread was never
resumed or written.

All three host/app-server pairs exited, the process census found no survivors
or tree readers, and the disposable tree was removed. The sealed evidence is
`docs/lanes/codex-native-interface-live.json` (payload SHA-256
`bd38138e4d88771d61dbb7f62572d02971ada4e368f293cc88fcfce8b62f74b6`).

## Bounded lifecycle: BLOCKED before inference

The deterministic fake gate passed 22 probes without starting a provider. The
single authorized live attempt then created a fresh Fleet home, registered the
current Interface read-only, stopped that host, and restarted the home against
a fresh owner-only `CODEX_HOME`. The lifecycle contract permitted at most two
fixed JSON-schema turns (`BOOT`, then one idle `WAKE`), 45 seconds and 64 output
bytes per turn, with no accepted-body retry.

The public `account/rateLimits/read` preflight returned app-server error
`-32600`: `codex account authentication required to read rate limits`.
Therefore no provider thread or turn was created, no prompt reached a model,
and usage remained zero/unmeasured. The harness performed no retry. Both
host/app-server pairs exited, references drained, and the disposable tree was
removed. The sealed evidence is
`docs/lanes/codex-native-bounded-live.json` (payload SHA-256
`8ed4e6bdf7bae2c463adfe36950d11a8b5335cb0313d71a75e242e9f179b01d4`).

CLI `codex login status` reports ChatGPT authentication, but a fresh
`CODEX_HOME` does not inherit it. Closing this blocker requires a supported
public authentication handoff into the disposable home. Copying or reading
private Codex authentication state is prohibited. No full-native claim is made.

## Offline checks

- Deterministic acceptance: `PASS`, `22 passed`, no provider process.
- Python 3.10: `26 passed, 2 skipped` for live/interface/registration tests.
- Python 3.12: `26 passed, 2 skipped` for the same set.
- Source/docs/prose gates: `22 passed, 2 xfailed`.
- Final process census: no Fleet Codex host or Codex app-server remained.
