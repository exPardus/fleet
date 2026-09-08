# Keeper soak — September 2026

Host receipts for `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
Every block here is `# volatile: host state` — evidence lives on kz-work, not in the tree.

## Baseline (before Task 1)

```text
# volatile: host state — measured 2026-09-08, commit 09819e1
3.12: 6 failed, 4638 passed, 7 skipped, 1 xfailed in ~6 min
3.10: 6 failed, 4638 passed, 7 skipped, 1 xfailed in ~6 min
pre-existing failures (6, same set on both): tests/test_fleet_index.py::TestPathContainment x3, tests/test_fleet_q.py::TestOutlinePathContainment x1, tests/test_terminal_surface.py::TestCollaboratorInstall x2
```

## Pages observed

| when (UTC) | rule | text | true/false page | action taken |
|---|---|---|---|---|
