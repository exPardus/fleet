# Security policy

## Supported versions

Fleet has one supported line: the `main` branch of this repository. Fixes land there.

## Reporting a vulnerability

Private vulnerability reporting is not enabled on this repository. Do not put
vulnerability details in a public issue. Instead:

1. Open a public issue titled `Security contact request`. Say only that you have a
   security report and need a private channel. Do not include exploit details,
   reproduction steps, or secrets.
2. A maintainer replies on that issue with a private channel. Send the report there.

Include in the private report:

- the fleet command or hook involved, and the version or commit;
- the steps that reproduce the problem;
- what an attacker could read, change or run.

Do not include real credentials, API keys or private repository content in a
report. If you need to show a secret, replace the value with a placeholder.

## Scope

In scope: the `fleet` CLI in `bin/`, the hook scripts in `bin/hooks/`, the plugin
skill and slash commands, and the keeper script.

Out of scope: the Claude Code and Codex CLIs, the model providers, and your own
repositories and fleet homes. Report problems in those to their maintainers.

## Operating safely

- Keep API keys in the environment or in key files outside the repository. Do not
  paste them into briefs, journals or task files.
- Use the narrowest permission mode that lets a task finish. `bypass` skips
  permission prompts.
- Keep fleet homes out of version control. They hold logs, mail and journals.
- Run `fleet doctor` after you change settings, and review each worker's branch
  before you land it.
