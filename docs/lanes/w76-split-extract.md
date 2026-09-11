# Lane w76 — split D wave B extraction
DONE means: exception-only leaf; exact 80-definition index boundary; kernel-owned state/CLI; shared exception identity and live patches; stdlib-only modules; all affected suites green on Python 3.10 and 3.12.

STATUS: NOT DONE — extraction implemented; six baseline failures prevent the required green result. No workaround changes consumed behavior or weakens assertions.
`fleet_errors.py` contains only the plain `FleetCliError` class. Fleet and index import the same object.
All 80 moved definition ASTs match `581e3f3` exactly; 25 associated constants retain facade aliases.
The five inbound names/six call edges use the index owner; replace/parser capabilities resolve through late kernel callbacks.
Home, claim and CLI state remain in `fleet.py`; no reverse import or copied parser globals.
`patch_fleet` routes owner patches and mirrors aliases; its AST census rejects moved facade patches and dynamic names, with planted alias/string/assignment violations.
Safety/source censuses scan all three files, with positive per-module seeds; physical self-citations retain their original file.
`tools/repoint_self_citations.py 581e3f3` repointed all 53 citations; final rerun is idempotent.
Direct Python and POSIX entrypoints passed from an unrelated cwd; Windows shim bytes/command contract unchanged (runtime Windows unavailable).

Checks used the exact offline env/uv command requested; no full floor or commits.
Both runtimes: 42 main suites = 2,191 passed / 2 failed / 3 skipped; 17 detector suites = 973 passed.
Both runtimes: 9 patch/index suites = 637 passed / 4 failed / 1 skipped; final strengthened audit = 6 passed; final citation/population pins = 44 passed.
Both runtimes: 2 further doctrine/prose detector suites = 23 passed / 2 existing xfailed.
Exact 70-suite list: [w76-all-suites.txt](../../state/journals/w76-all-suites.txt); separate main/detector/patch manifests and full logs are beside it.

Baseline reproduction uses untouched source AND tests from `git show 581e3f3`, staged only in this worktree's journal directory; all six failures reproduce on both runtimes.
Three `test_fleet_index.py::TestPathContainment` drive-refusal tests use POSIX absolute paths, which the adjacent existing contract explicitly flattens.
`test_fleet_q.py::TestOutlinePathContainment::test_an_absolute_path_outside_the_root_is_refused_too` has the same platform mismatch.
Two `test_terminal_surface.py::TestCollaboratorInstall` FLEET_PYTHON tests copy the uv interpreter binary away from its stdlib; startup fails importing `encodings`.
Exact failing node IDs and traces: `state/journals/w76-baseline-3.{10,12}.log` and `w76-baseline-shims-3.{10,12}.log`.
Resolving those baseline portability contracts/environment fixtures requires separate disposition; failures are retained, not skipped or relaxed.

Navigation: fleet.py 15,814 → 14,372 lines; fleet_index.py 1,575 lines; fleet_errors.py 2 lines. Stdlib/identity/capability/inbound pins passed.
Journal: [w76.md](../../state/journals/w76.md). All native subagents collected and closed; MCX_WORKER=1 retained.
PATH LIST: `bin/fleet.py`, `bin/fleet_index.py`, `bin/fleet_errors.py`, this report, test/fixture changes enumerated in [w76-paths.txt](../../state/journals/w76-paths.txt).
