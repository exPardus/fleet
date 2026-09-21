# GREEN — native Interface process-auth review

**Head:** `7083acd71f78ee061a81ac3118f4bf77056b5ca5` atop `53ad638ae0ee8e51b4e5c1fe0b69a58aaef6da09`.

**Verdict:** GREEN. Registration requires an explicit canonical home, exact public `thread/read`, matching `CODEX_THREAD_ID`, and the nearest Linux Codex ancestor's PID/start identity and uid. Each of the five public mutation methods reaches per-connection `SO_PEERCRED` authorization before provider dispatch. The exact-home claim rejects wrong UUID, unrelated same-user lineage, rotated predecessor, PID reuse, nearer Codex fork, malformed claim, and unsupported platforms. One Interface registers independently in three homes without cwd inference. Its own thread remains observe-only. The supervisor exception requires the current Codex holder thread and exact canonical home cwd; UUID alone is insufficient.

**Checks:** Python 3.10 and 3.12 focused auth/register/host nodes: `11 passed` each under fail-fast `codex`/`claude`/`mcx` stubs. Shipped fake acceptance: `22 passed`, `overall=PASS`, `provider_processes_started=false`. `py_compile` and `git diff --check` passed.

**Blockers:** None in this head. `tests/test_docs_currency.py` remains RED only for inherited ancestor `f41b91f` (source-without-docs); `7083acd` changes source and docs together.
