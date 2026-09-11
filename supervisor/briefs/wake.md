# Wake — continue the current supervisor body

Model: retain the current supervisor's assigned model and effort.

This is a keeper wake delivered through `fleet send`. Continue the active
campaign from `supervisor/JOURNAL.md`, `supervisor/GOALS.md`, and pending inbox
items. The campaign and existing task instructions remain in force.

Verify the current claim and your continuity proof before mutating fleet
state. Follow the launch bundle's resume protocol; do not seize a changed
claim or spawn another supervisor. If continuity fails, state the reason to
the interface and stop. Refresh the heartbeat through the normal protocol,
then take the next unfinished action recorded in the journal.

Respect a pending operator decision, handoff, or usage-limit horizon. If work
cannot proceed, report the blocker through `fleet sup-notify`; do not retry a
limited body before its horizon. Keep the report concise and checkpoint real
progress. Successful wake delivery alone is not progress.
