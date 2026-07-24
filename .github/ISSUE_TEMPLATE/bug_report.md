---
name: Bug report
about: Something broke — a command errored, a worker vanished, state got weird
labels: bug
---

**What happened**

<!-- What you ran, what you expected, what you got. Paste exact commands and exact output. -->

**Environment**

- OS (Windows 10/11, Linux distro, macOS):
- Python (`py -3.13 --version` or `python3 --version`):
- Claude Code CLI (`claude --version`):
- fleet commit (`git rev-parse --short HEAD`):

**`fleet doctor` output**

<!-- Paste it — it exists for exactly this. If doctor itself crashes, paste the traceback. -->

**State (if a specific worker is involved)**

<!-- `fleet status` line for the worker, and `fleet peek <name>` if it still answers. -->
