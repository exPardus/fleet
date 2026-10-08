# Security policy

## Supported versions

Fleet has one supported line: the `main` branch of this repository. Fixes land there.

## Reporting a vulnerability

Report security problems privately. Use GitHub's private vulnerability reporting
for this repository. Do not open a public issue for a vulnerability.

Include:

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
