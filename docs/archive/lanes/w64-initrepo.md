# w64-initrepo — bare init creates a cwd home [MEASURED]
DONE means: bare init creates a home accepted by later --fleet-home selection, §5 resolution is unchanged, targeted tests pass on Python 3.10 and 3.12, and this report records the registration decision. [MEASURED]

- [MEASURED] Model: gpt-6-astra, high effort; worker branch `w64/init-in-repo`, base `47b8e69`; `MCX_WORKER=1` retained.
- [MEASURED] Bare `fleet init` dispatches creation at exact cwd before resolution, sharing the named-home registry/settings writer and initialization re-read; no git-root search is added.
- [MEASURED] Conservative branch: no homes-list append for bare init; explicit `init --home` still registers its target and retains E2's destructive tier, while bare init remains ordinary by residual.
- [MEASURED] Explicit `--fleet-home` and statusline setup retain their existing resolved-home path; `resolve_home`, the resolver application function, the tier tuples, and the machine exemption tuples are unchanged in executable behavior.
- [MEASURED] Python 3.10.21 and 3.12.14 each passed 171 targeted tests: init/predicate 54, CLI `-k init` 5, citation/doc-claim/currency pins 110, homes-list no-rewrite/writer pins 2. No full suite ran.
- [MEASURED] Real subprocess smoke passed on both interpreters in disposable git repositories under `/tmp`, including a path with spaces: bare init creates there, later `--fleet-home <cwd> home` accepts it, unflagged `home` still selects the ambient home, rerun preserves registry, and isolated list/ambient bytes stay unchanged. Every cross-home call explicitly unsets `CLAUDE_CODE_SESSION_ID`.
- [MEASURED] Smoke checks compare complete function source to `47b8e69`: both `resolve_home` and `apply_resolved_home` are byte-identical. Numeric self-citations were repointed (34 of 45) with the repository tool and all citation pins passed.
- [MEASURED] Commands used the required `uv run --no-project --python 3.1x --with pytest python -m pytest -q` shape, prefixed by `env -u CLAUDE_CODE_SESSION_ID -u FLEET_HOME UV_OFFLINE=1 UV_CACHE_DIR=/tmp/w64-initrepo-uv-cache`. The baseline-red log, each test group/interpreter log, reproducible smoke script, and smoke output are retained under `state/w64-initrepo-logs/`.
- [MEASURED] `git diff --check` passed; the worktree itself has no `state/fleet.json`. Read-only final review found no substantive issues.

## Registration decision and unraised gate draft [MEASURED]

- [MEASURED] `docs/specs/multi-fleet.md` §Definitions requires a parsing `state/fleet.json`, not homes-list membership; §5 step 1 accepts such an unlisted initialized home. Thus local creation satisfies the named-home acceptance requirement without irreversible registration.
- [MEASURED] E2/init is in multi-fleet §5: explicit `init --home` appends permanently to the machine-global list, while its ordinary residual does not. Making bare init append would invalidate that ordinary classification and expand the registration capability to unflagged calls.
- [BELIEVED] Confirm the conservative no-registration reading. Automatic registration needs an explicit operator ruling for the E2 tier and invocation shape; creation alone does not settle that question.
- [BELIEVED] Gate text for supervisor only: “Does G-K5 Reading A mean bare `fleet init` creates an initialized cwd home without machine registration, leaving registration to `init --home` or `homes --add`? If automatic registration is intended, ratify its irreversible E2 tier and command shape, and authorize the corresponding §5 table amendment.” No gate raised or box ticked.

## WHERE THIS BRIEF WAS WRONG [MEASURED]

- [MEASURED] “Equivalent to init --home cwd” is only true for local creation: full equivalence would also append to the machine list, precisely the unresolved act the brief asks this worker to avoid assuming.
- [MEASURED] The predicted terminus-refusal inversion was correct: before changing its assertion, `test_init_home.py` produced 38 passed and that sole failure on Python 3.12.
- [MEASURED] No literal BARE-init quotation pin was found in the citation/doc-claim files; the settings-only predicate test instead carried stale prose and a misleading name, while its False assertion remains correct.
- [MEASURED] Prerequisite DONE: the ordinary uv command cannot acquire its normal cache lock in this sandbox; an offline writable cache copy under `/tmp/w64-initrepo-uv-cache` supplies the prerequisite without network or permission changes.
- [MEASURED] Existing statusline/explicit-home refusal prose claims chain state is home-relative, although `statusline_chain_path()` is machine-global; that pre-existing explanation remains outside this lane's statusline scope.

## Handover [MEASURED]

- [MEASURED] Docs updated: `docs/SPEC.md` command row and §14, plus `docs/PLAN-PROGRESS.md`; multi-fleet §5 text remains untouched, with the newer creation-default amendment described in SPEC.
- [MEASURED] No real homes-list append, retirement, live append-only journal/changelog/lesson edit, keeper change, statusline implementation change, or git add/commit/push/ref update was made. The native read-only audit subagent finished; no independent worker was launched.
- [MEASURED] Implementation/testing blockers: none. Committing is deliberately left to the supervisor under the sandbox fence; the registration question is a draft, not a blocker for the conservative branch.
- [BELIEVED] Supervisor commits the edited worktree and runs the merged-tree full floor. No full suite is run by this lane.

## PATH LIST [MEASURED]

- [MEASURED] `bin/fleet.py`
- [MEASURED] `tests/test_init_home.py`
- [MEASURED] `tests/test_cli.py`
- [MEASURED] `tests/test_read_registry_at.py`
- [MEASURED] `docs/SPEC.md`
- [MEASURED] `docs/PLAN-PROGRESS.md`
- [MEASURED] `docs/lanes/w64-initrepo.md`
- [MEASURED] `state/journals/w64-initrepo.md`
- [MEASURED] `state/w64-initrepo-logs/contract-inversion-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/self-citations.log`
- [MEASURED] `state/w64-initrepo-logs/init-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/init-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/cli-init-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/cli-init-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/pins-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/pins-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/list-pins-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/list-pins-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/smoke.py`
- [MEASURED] `state/w64-initrepo-logs/smoke-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/smoke-3.12.log`
- [MEASURED] `state/w64-initrepo-logs/setup.log`
- [MEASURED] `state/w64-initrepo-logs/final-audit.log`
- [MEASURED] `state/w64-initrepo-logs/final-docs-3.10.log`
- [MEASURED] `state/w64-initrepo-logs/final-docs-3.12.log`
