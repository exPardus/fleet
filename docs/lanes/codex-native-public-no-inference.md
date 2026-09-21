# Native Codex 0.155.1 public acceptance receipt

Run: `FLEET_CODEX_PUBLIC_ACCEPTANCE=1 python3 tools/codex_native_acceptance.py --public-no-inference`

The installed `codex-cli 0.155.1` passed schema generation/hash validation and
the real public initialize handshake in isolated `HOME`, `CODEX_HOME`, and XDG
directories. Fleet created genuine thread/session
`01a0c223-c4af-7281-a1c2-6d343692f887` in the exact disposable Fleet home.
After host generation changed from
`c3ce0adb-263f-4195-bd6e-7ce5a5ffcd39` to
`1deb04e5-16f8-43a6-b30a-9a7e350fb265`, public `thread/read` recovered that ID
and `thread/resume` returned it unchanged. Foreign-home host attachment refused.
The durable `thread/start` and `thread/resume` journal rows were both committed
under their respective generations. No `turn/*` method, model call, API key, or
inference was used. Both hosts stopped and the disposable tree was removed.

**BLOCKED:** `thread/list` returns zero rows for this genuine zero-turn thread,
before and after restart/resume. Public history injection and supported metadata
paths did not make it listable. Proving list identity therefore requires a real
turn on 0.155.1; this run did not spend provider capacity or broaden lifecycle
claims. The boundary matches the public app-server distinction between stored
history listing and loaded-thread access.
