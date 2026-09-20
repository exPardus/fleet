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

Both prescribed `uv` runs passed 65 targeted tests on Python 3.10 and 3.12,
including the notification, interface-state, and self-citation suites. The
corrected full suite reported 9 failed, 5492 passed, 16 skipped, and 3 xfailed;
its nine failure node IDs exactly equal the stored base run at `f885227`.

The production helper was also exercised against Codex 0.155.1 in the isolated
tmux server `fleet-notify-verify`. An injected runner routed the helper's tmux
argv to that server; `type_interface_line(..., "/status", prefix="")` returned
true after 0.521 seconds. The captured transcript placed `/status` before the
status-only `Account` and `Weekly limit` labels and then displayed a fresh
composer, proving recipient command execution rather than only tmux sender
success. No account values were recorded. Ctrl-C exited Codex and the isolated
server ended without a daemon kill.
