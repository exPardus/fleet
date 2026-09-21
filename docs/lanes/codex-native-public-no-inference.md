# Native Codex 0.155.1 public acceptance receipt

Run: `FLEET_CODEX_PUBLIC_ACCEPTANCE=1 python3 tools/codex_native_acceptance.py --public-no-inference`

The sealed JSON receipt is `codex-native-public-no-inference.json`; canonical
payload SHA-256 is
`ccc752c3b50f3f0f5d994593315069ac7ab42b9c9e2b1e11752fb320822f5db1`.
Installed schema/init and canonical disposable `CODEX_HOME` binding passed.
Thread/session `01a0c231-8c0e-7053-894b-7d71dab838be` survived Fleet-host
generation change `cedb0482-41b6-475e-a330-b02c7231513b` to
`dd3397dd-a111-40b0-ba64-f5d6114be85c`; read/resume returned the same ID.
Start/resume journals contain input/output hashes and are committed. The receipt
records both host/app-server PID plus start identity pairs and eight successful
post-exit checks.

The harness proved no live readers before deleting its active tree, repeated
tree/lock absence checks, and removed two prior task-owned trees after finding
zero reference PIDs and one lock each. No private Codex database or rollout was
read. No turn, model call, API key, inference, or provider spend occurred.

**BLOCKED:** Codex 0.155.1 `thread/list` returns zero rows for this genuine
zero-turn thread. Read/resume recovery passed; no broader lifecycle claim is
made.
