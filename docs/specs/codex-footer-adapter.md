# Codex native footer adapter

`bin/fleet_codex_statusline.py` is the file-only adapter for an opt-in Codex
native composer-footer command item. It requires `--fleet-home` or `FLEET_HOME`
and never falls back to the Fleet install root. It imports `fleet`, calls
`fleet.status_snapshot()`, and passes that snapshot to
`fleet_statusline.render_statusline(..., color=False)`. It reads the last
committed state and does not assert live process status. A missing or corrupt
home prints a bounded `fleet unavailable` view and exits zero.

This adapter does not read Claude status-line payloads, run chain delegates,
invoke the Fleet CLI, take `fleet.lock`, probe workers, write registry/events,
or quarantine damaged state. Codex controls cadence and child lifetime. The
Codex source prototype and its version-pinned configuration instructions live
in the separate Codex checkout under `codex-rs/tui/EXTERNAL_STATUS_LINE.md`.
