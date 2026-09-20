# w101 — Codex tmux notification settle

DONE means: the shared sender waits for pasted input to settle before its one
Enter; fake receiver timing proves immediate Enter is consumed while a 0.5s
settled Enter submits; supervisor and keeper producers retain their shared path.

## Result

`bin/fleet.py:type_interface_line` now sleeps
`INTERFACE_PASTE_SETTLE_SECONDS` (0.5s) only after a successful literal send.
The sleep function and duration are injectable for tests. Literal failure sends
no Enter; Enter failure returns false. Sanitisation, prefixes, limits, and the
single-Enter behavior are unchanged.

## Verification

The system pytest 3.12 run passed the targeted suite. The prescribed `uv` runs
could not fetch pytest because DNS/network access is unavailable in this worker;
see `w101-codex-notify.json`. Live scratch-Codex proof is intentionally left to
the interface before landing.
