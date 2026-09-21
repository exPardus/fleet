# Native Codex Interface process authentication

DONE means: Linux process-bound Interface registration and host mutation
authorization are implemented and covered by focused tests.

Date: 2026-09-21

This slice replaces the staged Interface refusal with a Linux-only,
Fleet-owned authorization boundary. `interface-register --codex-thread` still
requires an explicit initialized home and an exact public `thread/read`, then
binds that thread to the nearest real Codex ancestor PID/start identity and a
fresh per-home claim ID. Registration is independent of cwd, so one Interface
can hold separate Fleet, PM, and tap claims.

The per-home host obtains each Unix client PID and uid from `SO_PEERCRED`,
reconstructs its `/proc` lineage, and compares the thread, ancestor PID, start
identity, and uid against the latest claim before every public mutation. A
re-registration immediately disarms the prior lineage. A current native
supervisor remains authorized only when its process thread equals the current
supervisor holder and its Codex ancestor cwd equals the exact home. The external
Interface thread is an observation-only target and cannot be resumed, steered,
started, or interrupted by the host.

Focused acceptance covers three independent homes, wrong UUID before public
read, rotating handoff, unrelated same-user process, PID reuse, a nearer Codex
fork, external-thread write refusal, exact-home supervisor cwd, and unsupported
platform refusal. Provider executables are fail-fast stubs; no app-server or
inference is run by this slice.

## Evidence

- Python 3.10: focused Interface/IPC/source/docs/prose run: `94 passed, 2
  xfailed`.
- Python 3.12: the same run: `94 passed, 2 xfailed`.
- Existing native supervisor, worker, and host recovery regressions: `115
  passed`.
- Deterministic acceptance harness: `overall=PASS`, `22 passed`, and no
  provider process invoked.
- Direct source probe resolved this Interface's exact `CODEX_THREAD_ID`, Codex
  ancestor PID/start tick, uid, and Fleet cwd from public Linux process state.
- Post-test process census found no `fleet_codex_host` or fake app-server.
- `python tests/test_docs_currency.py .` retains the inherited historical
  failure for `f41b91f` (source changed without docs in that old commit); this
  commit includes source and docs together and both new lane documents satisfy
  the current-tree `DONE means` gate.
