# claude-fleet

One Claude Code manager session spawns, monitors, steers, and hands off multiple worker sessions across projects on this machine.

## Install

1. Add `bin\` to your `PATH` (contains `fleet.cmd`, the CLI shim).
2. Run `fleet init` once — renders the machine-local `state\worker-settings.json` (hook wiring: real interpreter path + `FLEET_HOME`, forward slashes) from the git-tracked `worker-settings.template.json`. Re-run after editing the template or moving the repo; idempotent.
3. Copy `skill\SKILL.md` to `%USERPROFILE%\.claude\skills\fleet\SKILL.md`.

See `docs\SPEC.md` for the full design.
