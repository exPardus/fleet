# Should bin/fleet.py stay one file?

DONE means: this report is committed on `w63/split-research` with all seven sections, every
number carrying a re-runnable receipt, and a ready-to-paste SPEC section. MEASURED.

MEASURED — Baseline: 708fa45246ca957263b3ce299add6f13efb8c330, branch w63/split-research. Source measurements read that commit, not a moving HEAD. No implementation or test changes.

BELIEVED — **Keep the CLI facade and stateful kernel together for now; ratify an index/query extraction pilot.** The deciding measurement is that index/query calls only **three distinct external function/class targets**: FleetCliError, _replace_with_retry and build_parser (R1). Do not authorize a wholesale split from file size alone.

BELIEVED — MEASURED labels observations; BELIEVED labels interpretations, estimates and proposed rules. A label introducing a table, list or receipt governs every row/line until the next label. R1–R8 below are re-runnable receipts; section numbers, source locations, versions and SHAs are identifiers. Wave estimates are planning estimates, not measured delivery time.

## WHERE THIS BRIEF WAS WRONG

- MEASURED — The file is **23,100 lines, 1,245,117 bytes, 487 top-level functions and 15 classes = 502 definitions**, not 22,888 lines. Keeper/statusline are **1,044/898** lines, not 908/796. The four hooks total **1,289** lines (R1/R2).
- MEASURED — SPEC's **7,378 lines at c63d7dd is historically correct**. The current file is **3.131 times** that size. The present-tree description is stale; the pinned historical number is not false (R2).
- MEASURED — The earliest approved design prescribes single-file but provides **no original rationale or separate single-file ratification entry** in the examined record. “One file to copy” would be invented provenance (R2).
- MEASURED — **None of the four hooks imports fleet**. Keeper and statusline do (R4).
- MEASURED — Literal option B, bin/fleet/, collides with the existing regular file bin/fleet, the POSIX launcher (R2/R4).
- MEASURED — The map finds **80 index/query definitions**, an area omitted by the brief. Doctor and views have outgoing dependencies; they are not dependency-free leaves (R1).
- MEASURED — The three sampled journals contain **zero explicit matching fleet.py Read/sed ranges**. Actual lane read-token spending is unavailable; source-slice estimates are labelled separately (R5).
- MEASURED — The rolling-document citation lesson and the ratified deleted-file/history taxonomy have different provenance. Neither removes the existing source self-citation tests (R2/R8).
- MEASURED — Merge 708fa45's “12 line-number citations in one docstring” description overstates its evidence: blocks include comments and multiple literals, and one changes “fourteen” to “fifteen” plus a reader list. All are commentary (R3).
- BELIEVED — “One Opus lane” is stale against this supplied Codex/Astra assignment. Native read-only assistants were used under the worker instruction; no independent mcx workers were launched.

## 1. What the file is, measured

MEASURED — R2 samples **10 evenly spaced positions in the 314-entry** git log --format=%h <baseline> -- bin/fleet.py history. These are history-order quantiles, including merges/reverts, not equally spaced dates.

| History index | Commit | Lines |
|---:|---|---:|
| 0 | 708fa45 | 23,100 |
| 35 | fe75d1b | 19,828 |
| 70 | 483f910 | 17,300 |
| 104 | 0efab34 | 15,056 |
| 139 | a113737 | 11,732 |
| 174 | f3ec329 | 8,755 |
| 209 | 7ac3ae5 | 7,832 |
| 243 | ebab2b0 | 8,944 |
| 278 | 67bbed8 | 5,157 |
| 313 | 26565ba | 445 |

MEASURED — Exclusive line categories: **7,433 docstring, 4,608 other comment, 1,520 other blank, 9,539 remaining**. Remaining lines include data/string literals, not just executable statements. The deployment has **10 tracked bin files**, plus the plugin manifest outside bin (R2).

BELIEVED — The functional partition below follows shipped section boundaries with explicit symbol overrides for dispersed supervisor, doctor and view functions. It is an analyst-defined map, not a proposed dependency law. R1 contains the exhaustive assignment rule.

MEASURED — Definition/class AST spans include their bodies and exclude surrounding section commentary. Out/in are cross-cluster **direct named call sites**, not runtime frequency (R1).

| ID | Area | Defs/classes | AST span lines | Out sites | Out caller–callee pairs | In sites |
|---|---|---:|---:|---:|---:|---:|
| P | paths and locators | 36 | 228 | 3 | 3 | 205 |
| A | platform adapters | 3 | 94 | 0 | 0 | 0 |
| R | registry, lock, events, time/tail helpers | 22 | 758 | 12 | 12 | 285 |
| B | mailbox, briefs, prompt, permission modes | 13 | 333 | 22 | 20 | 29 |
| N | native executable/env, dispatch, outcomes | 26 | 929 | 32 | 24 | 52 |
| O | observation/transcripts/status helpers | 22 | 706 | 15 | 14 | 46 |
| S | supervisor identity, claim, nonce, handoff/lifecycle | 131 | 6,250 | 234 | 160 | 109 |
| H | homes, resolution, wrong-home guard | 32 | 1,205 | 23 | 18 | 28 |
| V | snapshots, projections, interface/tmux | 12 | 427 | 24 | 23 | 11 |
| I | install, CLI errors/shared support | 29 | 981 | 41 | 39 | 169 |
| W | worker verbs, lifecycle/archive | 53 | 3,806 | 451 | 305 | 23 |
| D | doctor checks/orchestration | 40 | 1,721 | 64 | 57 | 2 |
| X | index/shards/digests/query | 80 | 1,818 | 9 | 6 | 6 |
| C | parser/main | 3 | 557 | 36 | 36 | 1 |

MEASURED — AST-derived candidate import-dependency matrix: **row calls column** (R1). These are calls, because there are no actual internal module imports yet. Diagonal cells are internal calls.

~~~text
# at 708fa45246ca957263b3ce299add6f13efb8c330
row P  A R   B  N  O  S   H  V I  W  D X   C
P   28 0 0   0  0  0  1   0  0 1  0  1 0   0
A   0  0 0   0  0  0  0   0  0 0  0  0 0   0
R   11 0 20  0  1  0  0   0  0 0  0  0 0   0
B   14 0 1   4  1  0  0   0  0 3  0  0 3   0
N   15 0 8   2  38 0  3   0  0 1  3  0 0   0
O   3  0 6   0  6  11 0   0  0 0  0  0 0   0
S   41 0 86  4  13 7  311 4  8 69 2  0 0   0
H   4  0 3   0  0  0  1   42 0 15 0  0 0   0
V   2  0 7   0  1  4  9   1  7 0  0  0 0   0
I   16 0 3   0  0  0  2   20 0 34 0  0 0   0
W   83 0 161 23 26 30 56  1  2 68 50 0 1   0
D   16 0 9   0  4  5  25  0  1 1  3  17 0  0
X   0  0 1   0  0  0  0   0  0 7  0  0 156 1
C   0  0 0   0  0  0  12  2  0 4  15 1 2   2
~~~

MEASURED — The **10 hottest cluster edges** by call-site count: W→R **161**, S→R **86**, W→P **83**, S→I **69**, W→I **68**, W→S **56**, S→P **41**, W→O **30**, W→N **26**, D→S **25**. Exception construction contributes to I (R1).

MEASURED — The **10 hottest symbol pairs**: _cmd_respawn_native→FleetCliError **9**; _cmd_send_native→FleetCliError **9**; _cmd_send_native→save_registry **9**; _require_claim_holder→FleetCliError **7**; _archive_file_pairs→outcome_path **6**; _cmd_respawn_native→fleet_lock **6**; _cmd_respawn_native→load_registry **6**; _resolve_supervisor_lifecycle_target→SupervisorLifecycleRefusal **6**; _cmd_respawn_native→save_registry **5**; _cmd_send_native→append_event **5** (R1; ties sorted by symbol).

BELIEVED — Limitations: nested scopes are attributed to their outer top-level owner; direct Name calls are matched by spelling. The matrix does not resolve local shadowing, aliases, callbacks or arbitrary attributes. It is not a complete call graph or permission proof. A's zero column does not mean unused adapters.

MEASURED — A separate attribute census finds PLATFORM.atomic_append_bytes in append_home_record and _atomic_append_bytes: H→A and N→A each have **1** such call. Parser registration references and module initialization are also outside the direct-call matrix (R8). Include these when designing imports.

MEASURED — Verb tiers overlay functional clusters; R2 reads the actual literal tables:

| Tier | Tokens | Members |
|---|---:|---|
| ordinary | 12 | spawn, status, peek, result, home, knowledge, attach, wait, sup-status, sup-context, q, index |
| disruptive | 7 | kill, interrupt, send, respawn, release, resume-limited, sup-heartbeat |
| destructive | 15 | clean, archive, autoclean, doctor --repair, sup-handoff-abort, sup-boot, sup-handoff-begin, sup-handoff-complete, sup-decision --clear, sup-spawn, sup-checkpoint, sup-release, homes --add, homes --retire, init --home |
| ordinary residual | 4 | doctor, sup-decision, homes, init; flagless forms, with flagged overrides |

BELIEVED — Do not infer “read-only” from ordinary: status authoritatively recomputes under the lock. Functional ownership and effect tiers are different axes.

MEASURED — R1 prints every assigned module binding read by each cluster, using compiler symbol tables including nested scopes. Selected shared bindings below count **definitions reading**, not read instructions.

| Binding | Cluster:reader definitions |
|---|---|
| FLEET_HOME | P:4 S:5 H:1 I:2 D:1 |
| INSTALL_ROOT | P:2 S:3 H:2 I:2 D:2 |
| _GLOBAL_HOME_FLAG | H:2 |
| PLATFORM | N:1 H:1 |
| HANDOFF_PENDING_KEY | S:7 V:1 |
| SUPERVISOR_BODY_NAME | S:2 V:1 W:1 |
| SUPERVISOR_BAND_HARD_TOKENS | O:1 S:1 D:1 |
| _RETIRED_SID_SWEEP_CAP | S:1 W:2 |
| Q_LIMIT_DEFAULT; SHARD_KINDS | each X:1 C:1 |

MEASURED — No one of FLEET_HOME, INSTALL_ROOT or _GLOBAL_HOME_FLAG is directly read by every cluster; many paths reach them indirectly through P. apply_resolved_home and cmd_autoclean declare global FLEET_HOME; statusline also assigns fleet.FLEET_HOME (R8/R4).

MEASURED — External shims: keeper loads **8** distinct fleet attributes; statusline **14**, including private _parse_iso and _multi_fleet_population_is_live. Keeper wire helpers delegate to V. The hooks have no import edges to this module (R4).

## 2. Why single-file was chosen, and which reasons still hold

MEASURED — Earliest tracked rule: cfc1f44, “docs: claude-fleet spec v2 (post adversarial review).” Its CLAUDE.md describes SPEC as “the approved v2 design” and says exactly (R2):

> Python is py -3.13 (bare python resolves to 3.10). bin/fleet.py is stdlib-only, single file.

MEASURED — The original includes Markdown code delimiters around the command/path names; the wording above is otherwise verbatim. Its SPEC tree says:

> fleet.py              # single-file CLI, py -3.13, stdlib only

MEASURED — These are **prescriptions, not an original reason**. No separate single-file ratification/rationale was located in the examined SPEC, CLAUDE, OPERATOR-GATES or lessons history. The original tree already included separate hooks. R2 reproduces the exact raw lines; this wider search is also re-runnable:

~~~sh
# at 708fa45246ca957263b3ce299add6f13efb8c330
git log 708fa45 --format='%h %s' -G 'single.file|stdlib.only|one file' -- CLAUDE.md docs/SPEC.md docs/OPERATOR-GATES.md knowledge/lessons.md
git show 92d0c3f -- knowledge/lessons.md
git show 9b8977c -- docs/OPERATOR-GATES.md knowledge/lessons.md
~~~

BELIEVED — Warranted conclusion: “recorded project rule, original rationale unavailable,” not “never ratified privately.” A new operator ruling should state its reason.

| Candidate rationale from brief | MEASURED evidence | BELIEVED assessment |
|---|---|---|
| One file to copy | README clones repository, adds bin to PATH and installs plugin; original tree already had hooks (R2). A test fixture still copies only fleet.__file__ (R8). | Not a substantiated original reason; real fixture coupling remains. |
| No hook import-path problems | Hooks are standalone; keeper/statusline insert bin on sys.path (R4/R8). | Preserve hook independence; extraction need not affect it. |
| Stdlib-only | All AST import roots, including local zoneinfo, belong to Python 3.12's stdlib set (R2). | Keep dependency/floor constraint; it is independent of file count. |
| Line-pinned receipts | Old receipts archive named commits; current self-citation tests scan the live module (R4/R8). | Preserve old receipts; redesign current pins deliberately if symbols move. |
| Shared namespace | Statusline assignment and test rebinding are observable; R4's re-export probe prints “new old.” | Present maintenance tradeoff, not evidence of original motive. |

MEASURED — Exact lesson at 92d0c3f: **“DOCTRINE, ADDED THIS WAVE: a ROLLING document may never be line-cited.”** It names NEXT-SESSION.md and permits headings, quoted phrases or commit pins. Separate ratified text at 9b8977c: **“a reference to a deleted file is only rot when it is a claim about the CURRENT tree; a pinned receipt and a quoted argument are claims about a PAST tree and are still true.”** Later “ratified” shorthand in lessons should not erase that distinction (R2).

MEASURED — Literal fleet.py:digits census: **20 occurrences / 10 test files; 74 / 5 docs/specs files; 1,056 / 71 other docs files** (R4). These are textual citations, not failing tests or distinct receipts. R8 uses the shipped receipt parser and finds **4 receipt objects containing 9 such citations**: claim-nonce at source lines 777/1040/3441, pinned to 091d5fa/091d5fa/0e8d7ca; graceful-succession at source line 1678, pinned to cebae4f. This regex excludes shorthand self-cites such as (:N), func:N and @N, covered separately by test_self_citations.py and test_retired_sid_citations.py.

## 3. Costs of staying, measured

MEASURED — R5 reads external journals w59-inithome, w61-sidcollision and w63-sidunion, recording their SHA-256 hashes. None contains explicit matching fleet.py Read/sed ranges. Their prose names symbols but not returned bytes, repetitions, cache hits or charged tokens.

MEASURED — Captured external-journal fingerprints (R5; volatile, baseline source 708fa45):

| Journal | Bytes | SHA-256 |
|---|---:|---|
| w59-inithome.md | 7,157 | dce6c93232ae971b289bd98fd7146eef9e0762de0c8914a3144e85ed8b3a7d09 |
| w61-sidcollision.md | 6,051 | 93dd8fa911347aea7400a2bd3cff055ba17e6f97350c80be29b08ef14fa52d9d |
| w63-sidunion.md | 10,777 | fe6a27719e85f234110baf53737f2ed0f0be6fbcf0794c6c6a66689fbc56fee0 |

BELIEVED — The following **source-reading proxies** concatenate named/relevant task definitions once from this baseline and divide characters by **4**, rounding up. This is a heuristic, not a tokenizer or actual session accounting. R5 prints the chosen symbols and arithmetic.

| Journal/task | Source lines | Characters | Estimated tokens |
|---|---:|---:|---:|
| w59-inithome | 239 | 12,965 | 3,242 |
| w61-sidcollision | 157 | 8,352 | 2,088 |
| w63-sidunion | 246 | 14,315 | 3,579 |

MEASURED — Whole-file text has **1,244,139 characters** (R2).
BELIEVED — Reading it all once is approximately **311,035 tokens** under that heuristic. No sampled journal proves this happened. Splitting saves no source tokens if a reader already requests the same symbol ranges.

MEASURED — R3 uses read-only git merge-tree to reconstruct conflicts. Numeric waves **w49–w63** contain **38 labelled first-parent merges**, **10 incoming fleet.py-changing branches**, **4 merges changing it on both parents**, **3 conflicting merges / 26 blocks**, and **2 landing waves** with multiple fleet.py-changing branches. Missing labels do not prove inactivity.

MEASURED — The alternative **15 most recent observed landing-wave IDs** spans w43–w63 with gaps: **53 merges, 16 incoming file changes, 4 parent overlaps, 3 conflicts / 26 blocks**, and **3 multi-file-touch landing waves** (R3).

| Conflicting merge | Blocks | Equal after colon-digit masking | Commentary-only |
|---|---:|---:|---:|
| MEASURED — 708fa45 | 12 | 11 | 12 |
| MEASURED — b058d1e | 12 | 12 | 12 |
| MEASURED — 4d74d22 | 2 | 2 | 2 |

BELIEVED — This directly supports reducing fragile live line-number prose. It does not measure reviewer time, actual concurrent execution, blocked work or conflicts avoided by serialization.

MEASURED — Import timing: Python **3.12.3**, **no fleet.pyc present**, cwd at this worktree's bin, -B -X importtime -c 'import fleet'. All **5 runs exited 0** (R6). Bytecode writes disabled; filesystem caches not flushed. This is source import on a loaded host, not a cold-disk or bytecode-warm benchmark.

~~~text
# at 708fa45246ca957263b3ce299add6f13efb8c330
# volatile: host load and filesystem cache affect timings
run self_us cumulative_us process_ms
1   436012  534873        592.751
2   397659  453380        508.016
3   359426  430991        471.629
4   391990  443759        481.929
5   422818  473614        517.077
median 397659 453380      508.016
~~~

MEASURED — Targeted collection: tests/test_load_registry_callers.py yielded **17 tests in 0.54s, exit 0**, using cached Python with pytest, -B and disabled cacheprovider (R6). It includes that file's import/AST setup, not whole-suite collection. The first cached interpreter tried lacked pytest; another succeeded. **No full floor or behavior suite was run.**

BELIEVED — An eager facade still imports essentially all code; splitting alone does not establish a startup improvement. Deferred imports need separate design and measurement.

MEASURED — R7 ranks **distinct surviving blame-origin commits** per definition/class span. This is churn evidence, not a count of every historical edit. Recent lines are dated at or after **2026-09-09 UTC**.

| Symbol | Origins | Recent lines | Span |
|---|---:|---:|---:|
| build_parser | 44 | 38 | 419 |
| cmd_sup_handoff_begin | 25 | 9 | 543 |
| main | 25 | 2 | 122 |
| cmd_spawn | 20 | 0 | 302 |
| cmd_doctor | 16 | 6 | 122 |
| _cmd_respawn_native | 16 | 0 | 366 |
| _supervisor_gate | 15 | 4 | 217 |
| dispatch_bg | 15 | 0 | 287 |
| cmd_clean | 15 | 0 | 202 |
| _require_claim_holder | 13 | 1 | 277 |

BELIEVED — Parser and lifecycle coordination remain shared work after extraction. A layout should not promise to eliminate those edits.

## 4. Costs of splitting, measured

MEASURED — R4's broad discovery grep matches **10,727 lines across 258 files** for bin/fleet.py or fleet.<identifier>. It includes prose and data names such as fleet.json/lock, not only module dependencies. The receipt prints category totals and the command emitting **every matching path:line**. AST narrows test uses to **6,200 attribute occurrences / 82 files / 472 names**.

MEASURED — Tests have **660 setattr(fleet, …) calls / 75 files / 97 names**, including **10 dynamic-name sites**. Leading counts: _fetch_agents_roster **204**, FLEET_HOME **108**, dispatch_bg **30**, _stop_native_session_status **22**, find_transcript_path **18**, INSTALL_ROOT **14** (R4).

BELIEVED — Re-exporting functions preserves their defining globals. Assigning facade.FLEET_HOME does not update a moved function's dictionary: R4's minimal probe returns “new old.” A facade needs explicit state/dependency semantics; public-only re-exports also miss private consumers.

| Consumer | MEASURED current shape (R4/R8 unless specified) | BELIEVED migration obligation |
|---|---|---|
| bin/fleet; bin/fleet.cmd | Execute sibling fleet.py; bin/fleet is a regular file (R2). | Keep launcher and CLI script paths. |
| hooks/run_py.sh | Executes its first script argument; no literal fleet.py. | No edit needed if script path survives. |
| four hooks | Standalone, zero fleet imports. | Preserve independence/exit behavior. |
| keeper/statusline | Import fleet via bin; statusline assigns home. | Preserve private/public API and state rebinding. |
| worker-settings.template.json | Hook paths use FLEET_INSTALL; home passed separately; no fleet.py. | Keep code/data separation and rendered paths. |
| plugin manifest / commands | Metadata, no manifest hooks; command templates invoke fleet CLI. | Preserve CLI grants/resolution; no automatic rewrite. |
| rendered core tasks | _steer_supervisor_release, _render_sup_spawn_task and _render_successor_task use INSTALL_ROOT/bin/fleet.py. | Retain shim and rendered argv. |
| keeper _sup_status | Uses Path(home)/bin/fleet.py instead. | Existing install/home discrepancy; separate from extraction. |
| INSTALL_ROOT / fallback home | Path(__file__).resolve().parent.parent. | A deeper package changes the answer; retain owner or pass locator explicitly. |
| fleet.__file__ | Mentioned by **29 test files** (R4). | Audit source reads, roots, process cwd and copied installs individually. |
| test_sid_collision._install | Hardlinks/copies only fleet.__file__ into install/bin/fleet.py. | Copy dependency tree after extraction. |
| core/index-compose/resilience tests | Derive cwd/repo/template paths from fleet.__file__. | Preserve locator or repair fixtures. |
| tools/verify_receipts.py | pinned_tree archives the named commit. | Old pinned receipts survive; live/repinned claims need edits. |
| tools/repoint_self_citations.py | Maps old/current bin/fleet.py line positions. | Insufficient across moved files. |
| tools/mutate_liveness.py | Names bin/fleet.py and reader symbols. | Move mutation targets with reader pins. |

MEASURED — R4 finds **23 test files calling ast.parse**, including _ast aliases. These **16** inspect the single fleet implementation, sometimes alongside planted/per-function probes:

| File under tests/ | Principal source contract |
|---|---|
| test_autoclean.py | _fleet_call_graph; gate/exemption reachability |
| test_doc_claims.py | _registered_doctor_checks; non-vacuous counts |
| test_fleet_index.py | TestIndexHoldsTheInterpreterFloor; imports |
| test_homes_list.py | isabs, no-rewrite, population, append-writer census |
| test_index_compose.py | call_counts/_call_sites; compose/dispatch coverage |
| test_init_home.py | TestNoCwdResolutionWasAdded |
| test_install_home_split.py | _env_keys_read_by; install not overridable |
| test_liveness_readers.py | tree/_scope_map/TestTheCensus |
| test_load_registry_callers.py | _callers; live allowlist, lexical lock/repair |
| test_respawn_ceiling.py | _ceiling_call_sites |
| test_steering.py | _blank_out_function/_function_code; append/OS boundary |
| test_stillborn_handoff.py | _turns_one_stamp_sites |
| test_unlocked_quarantine.py | _unlocked_load_registry_scopes |
| test_verb_effect_guard.py | arming-symbol naming census |
| test_view_quarantine.py | _calls_in; reachable effects |
| test_views_doctrine.py | rename's exactly-one-caller census |

MEASURED — Remaining **7** subjects: rendered-command quoting recursively scans bin/**/*.py already; keeper doctrine/statusline-home scan siblings; sid-collision/subprocess-home-seam scan tests; pin-usage-contract scans the live pin test; verify-receipts-tristate scans the verifier. The recursive renderer still pins **path + symbol identities**. R4 prints all scanner sites, and R8 prints relevant source.

MEASURED — Non-AST pins include test_self_citations.py, test_retired_sid_citations.py and copy/root fixtures. inspect.getsource(fleet.function) can follow a moved function; Path(fleet.__file__).read_text() sees only the facade (R8).

BELIEVED — **Static red lower bound: 12 distinct test functions**, under a defined hypothetical: move all implementation functions/assignments into a differently named internal package, preserve runtime behavior, leave an import/entrypoint-only facade at bin/fleet.py, and edit no tests. This is **not an executed total**. Literal bin/fleet/ cannot coexist with the launcher. Additional binding/import/root/citation failures are excluded from this lower bound.

BELIEVED — R8 enumerates and prints the full existing source for the following predicates, permitting the count and reasoning to be re-derived:

- test_load_registry_callers.py::TestLoadRegistryCallSites.test_the_matcher_finds_call_sites_at_all.
- Same file, TestTheDetectorCannotBeWalkedAround: test_the_allowlist_has_no_dead_entries; test_cmd_status_quarantines_ONLY_under_the_lock; test_cmd_doctor_quarantines_ONLY_behind_the_repair_flag.
- test_unlocked_quarantine.py::TestTheUnlockedCensusIsPinned: test_the_matcher_finds_call_sites_at_all; test_the_allowlist_has_no_dead_entries; test_holder_is_limited_really_is_lock_held_by_its_caller; test_the_two_preflight_helpers_do_not_regain_load_registry.
- test_views_doctrine.py::test_the_rename_has_exactly_one_caller.
- test_stillborn_handoff.py::TestEveryFirstTurnStampIsAlsoAnEvent.test_every_turns_equals_one_stamp_sits_beside_a_turn_started_event.
- test_install_home_split.py::TestInstallRootIsNotOverridable.test_nothing_reads_a_fleet_install_environment_variable.
- test_rendered_command_quoting.py::TestTheCensusIsTheGate.test_the_census_finds_exactly_the_renders_it_is_pinned_to.

MEASURED — Existing source contains **50 direct load_registry calls**; an import/entrypoint-only source contains none (R8).
BELIEVED — Positive population/function checks fail while some absence checks pass vacuously. Migration must retain planted offenders across the implementation tree and resolve imported/qualified calls; merely parsing more files while matching only Name("load_registry") is insufficient.

MEASURED — Pinned archive equals pinned fleet.py blob, SHA-256 **c1866ff7b5df4c1e750d051b940e7f3e1caaad1fbeeb2da5527c35dc1d0a78aa** (R4).
BELIEVED — Together with pinned_tree's source, this explains why later renames preserve old materialized receipts. It does not authorize changing a historical receipt's path while retaining its old pin.

## 5. Options, concrete shape and migration cost

BELIEVED — Wave counts are planning estimates derived from the work packets stated below, excluding operator waiting time. A wave means a build/review/landing packet, not a fixed duration; none authorizes implementation.

| Option | Concrete shape | Estimated waves and basis | Tradeoff |
|---|---|---|---|
| A: keep one file | Add symbol/section TOC and marker/coverage lint. | **0 extraction waves; about 1 small doc/lint packet.** Cost ≈0 is not literally no work. | Navigation improves; imported code and shared parser/lifecycle edits remain. |
| B: package/facade | **bin/fleet_core/** with paths, registry, homes, native, observation, supervisor, views, doctor, index and CLI modules. Keep bin/fleet.py and both launchers. | **4–6 waves**: source/state seams; shared types/paths/import order; homes/native/registry; remaining supervisor/verbs/views/doctor; optional correction and install/portability repair waves. | Broad ownership separation, broadest pin/state regression surface. A five-line re-export shim is inadequate. |
| C: suggested leaves | fleet_platform.py or fleet_doctor.py with explicit dependencies; views receive read capabilities only. | **1–2 waves per family**: boundary plus move/pins; optional repairs. | Platform moves only **94 AST span lines**; doctor/views have **64/24 outgoing sites**, not zero (R1). |
| D: index/query pilot | **bin/fleet_index.py**, with bin/fleet.py owning state/CLI and reviewed wrappers/dependencies for tested APIs. | **2 waves**: source-discovery/fixture/dependency contract and review; extraction, affected pins, review and measurement. Rejection returns to A. | Moves **80 definitions / 1,818 AST span lines** across **3 external direct-call targets** without first moving home/claim/dispatch state (R1). |

BELIEVED — B's requested “forbid imports outside facade” needs correction: internals importing the facade create cycles and hide dependencies. Use an explicit acyclic internal dependency allowlist; facade aggregates, internals never import facade, upward capabilities are injected. Seed the lint with a forbidden edge and a qualified effect call.

MEASURED — D's outward pairs: _ensure_index_excluded→FleetCliError **2**; _index_files_arg→FleetCliError **2**; _index_root_arg→FleetCliError **2**; _require_index→FleetCliError **1**; registered_cli_verbs→build_parser **1**; write_shard_atomic→_replace_with_retry **1**. Inward sites, each **1**: _recovered_brief→index_teach_lines; compose_prompt→index_teach_lines; compose_prompt→compose_context_digests; cmd_spawn→parse_context_arg; main→cmd_index; main→cmd_q. Parser also reads index constants (R1).

BELIEVED — D is not copy/paste. registered_cli_verbs is cached and calls build_parser: inject parser-derived capability/callback while preserving invalidation tests. Preserve exception identity and purposeful patch seams. Copying dictionaries or executing moved source into the old namespace would retain the monolith while obscuring it.

## 6. Recommendation, invariants, sequencing and falsification

BELIEVED — **Recommend D after operator ratification, with A until its seam is reviewed.** The ONE deciding measurement is index/query's **3 distinct external direct-call targets** (R1); the explicit inbound surface makes it a bounded experiment. File size and timing are context, not thresholds.

MEASURED — SPEC §16 enumerates the following existing invariants; R8 prints their source.
BELIEVED — No invariant's policy needs changing, but these contracts must survive a layout change:

| Invariant | Migration obligation |
|---|---|
| §16.1 fleet-daemonless | No import-time service/process side effects. |
| §16.2 exit-0 hooks | Preserve standalone scripts and exit boundaries. |
| §16.3 atomic mailbox | Preserve append/claim primitives and ordering. |
| §16.4 journal at respawn | Preserve prompt/brief/context composition. |
| §16.5 cwd-scoped dispatch | Never derive registered cwd from module depth. |
| §16.6 single-writer registry | Preserve lock ownership/no-lock-across-subprocess and non-vacuous tree-wide callers. |
| §16.7 one live session/name | Preserve stop/restamp/dispatch/nonce choreography. |
| §16.8 platform-only branching | Follow implementations with OS/floor pins. |
| §16.9 one state/many views | Preserve snapshots; no read-surface writes/probes/quarantine/roster fetches. |
| §16.10 spec-bound work, currently unbuilt | Do not implement or promote that separate feature. |

MEASURED — w62 codex-substrate/keeper/dogfood and w63 statusline-home/sid-union landings are already in this baseline's ancestry. OPERATOR-GATES distinguishes built multi-fleet Reading A from unbuilt cwd Reading B and further init/statusline obligations (R3/R8). Actual in-flight branch ownership is not inferable from commit history.

BELIEVED — At kickoff, settle active home/init, keeper-identity and codex-substrate behavior edits before moving their source. Then fence D to index/compose/fixtures while the stateful kernel stays stable. Rebase and repeat the map at the chosen start commit. This report changes neither multi-fleet §5 nor keeper/substrate behavior.

BELIEVED — Falsify D if the reviewed boundary requires moving home/claim state, changing consumed API/state behavior, weakening a safety detector, introducing a facade cycle or changing installed CLI semantics. Reconsider after a matched symbol-reading comparison if the pilot provides no navigation/context gain while maintenance expands; A remains valid. Falsify “defer a broad split” if later waves demonstrate executable same-function conflicts or blocked independent work that smaller seams cannot address. Collect that evidence instead of extrapolating these commentary conflicts.

## 7. Ready-to-paste SPEC section — draft, not promoted

BELIEVED — This is proposed normative text for operator review. N is deliberately unassigned; the author has not amended or promoted SPEC.

~~~markdown
## N. Module layout [DRAFT — AWAITING OPERATOR RATIFICATION]

Fleet remains stdlib-only at its declared Python floor. File count is an
implementation choice constrained by dependency ownership and preserved
contracts, not a requirement that all runtime code occupy one file.

Keep bin/fleet, bin/fleet.cmd and python bin/fleet.py as supported entrypoints.
Keep import fleet as the compatibility API, including currently consumed
private symbols and documented/tested state-rebinding behavior. FLEET_HOME
and INSTALL_ROOT each have one authoritative owner; module depth must not
change the code root or resolved home.

Authorize only an index/query extraction pilot into bin/fleet_index.py,
after a reviewed dependency contract and source-pin migration design.
Retain registry, home resolution, dispatch, supervisor claim/nonce/handoff
and snapshot ownership in the current kernel during the pilot. This ruling
does not authorize a wholesale package conversion or a resolver change.

Internal dependencies are explicit and acyclic. Implementation modules do
not import the facade. Pass upward capabilities through reviewed boundaries.
Re-exporting functions alone does not establish mutable-state compatibility.

A source-derived safety pin inspects every implementation file it claims to
cover and resolves imported/qualified call forms introduced by the split.
Keep positive populations and planted forbidden effects so a facade cannot
make a detector pass by hiding implementation. Move install-copy, root,
source-citation and command-render identities with their code.

Preserve §16 and the binding view, hook, interpreter-floor and multi-fleet
contracts. Worker hooks stay standalone. Introduce no runtime dependency on
tests or Markdown. Historical commit-pinned receipts remain unchanged;
new/live claims cite their actual tree and source symbols.

Run affected behavior, source, installation and portability checks at every
supported floor for the extraction, then record the dependency and reading
measurements that motivated it. Further extraction needs its own measured
boundary and reviewed scope. The author never promotes this draft; operator
ratification and its rationale use the existing gate/lesson process.
~~~

## Receipts and research journal

MEASURED — Deterministic scripts read baseline 708fa45 through git. R5 is volatile because journals are external; R6 because timings/interpreters are host-specific. Tables above preserve measured outputs. Full worker/tool transcripts are tool-managed in .mcx/nSsQ6ufB/log and .mcx/nSsQ6ufB/events.jsonl; they are not staged.

BELIEVED — Re-run an embedded Python receipt with this dispatcher, replacing R1 as needed. These blocks use an explicit research runner and are not implicitly registered in the narrower docs/specs receipt harness.

~~~sh
# at 708fa45246ca957263b3ce299add6f13efb8c330
MCX_WORKER=1 PYTHONDONTWRITEBYTECODE=1 python3 -B - R1 <<'PY'
from pathlib import Path
import re, sys
text = Path("docs/lanes/w6x-split-research.md").read_text()
code = re.search(r"<!-- receipt:" + re.escape(sys.argv[1]) +
                 r" -->\n~~~python\n(.*?)\n~~~", text, re.S).group(1)
exec(compile(code, "<split-research-" + sys.argv[1] + ">", "exec"))
PY
~~~

MEASURED — Journal constraint: requested /home/altai/proga/fleet/state/journals/w63-split-research.md is outside this worker's writable roots; approval is unavailable. No write was attempted there. This embedded journal records baseline/fence inspection, native read-only provenance/source-pin assistance, graph/history/import/collection measurements and report drafting. Subagents returned findings and were collected.

MEASURED — Attempt log: first cached interpreter lacked pytest; fallback collected successfully. Per-definition blame was interrupted for cost. Two header-parsing attempts failed; R7 is the corrected single-blame receipt whose successful output appears above. Failed results were not used as evidence. Implementation/tests remain unchanged; final commit/check status follows the receipts.

docs updated: docs/lanes/w6x-split-research.md

### R1

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R1 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import ast, collections, subprocess, symtable
SHA = "708fa45246ca957263b3ce299add6f13efb8c330"
def git(*args):
    return subprocess.check_output(["git", *args], text=True)
src = git("show", SHA + ":bin/fleet.py")
tree = ast.parse(src)
defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
# Functional labels are analyst choices; all metrics below follow this explicit partition.
ranges = [(438,"P"),(575,"A"),(1507,"R"),(1928,"B"),(2104,"N"),
          (2972,"O"),(3707,"S"),(4092,"O"),(5671,"H"),(6044,"V"),
          (7172,"I"),(9780,"W"),(10550,"S"),(12022,"W"),(13650,"D"),
          (14662,"N"),(20302,"S"),(22520,"X"),(99999,"C")]
def cluster(n):
    if n.name.startswith("_doctor_check_"): return "D"
    if n.name in ("supervisor_status_line","_project_claim","_project_handshake","_interface_divergence"): return "V"
    if n.name in ("supervisor_band_verdict","_record_sids","_caller_holds_supervisor_claim","supervisor_claim_sids","band_tier_for_sid","_record_is_supervisor_claim_holder","_successor_worker_name","_is_supervisor_shaped"): return "S"
    return next(c for end,c in ranges if n.lineno<=end)
labels = {"P":"paths","A":"platform","R":"registry/lock/events","B":"mailbox/brief/prompt",
          "N":"native dispatch/outcomes","O":"observation/transcripts","S":"supervisor/identity",
          "H":"home resolution/guard","V":"views/interface","I":"install/CLI support",
          "W":"worker verbs","D":"doctor","X":"index/query","C":"parser/main"}
cs = list(labels)
byname={n.name:n for n in defs}
edges = collections.Counter()
for n in defs:
    for call in ast.walk(n):
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id in byname:
            edges[n.name,call.func.id]+=1
matrix=collections.Counter()
for (a,b),cnt in edges.items(): matrix[cluster(byname[a]),cluster(byname[b])]+=cnt
print("lines",len(src.splitlines()),"bytes",len(src.encode()),"defs",len(defs),
      "functions",sum(isinstance(n,ast.FunctionDef) for n in defs),"classes",sum(isinstance(n,ast.ClassDef) for n in defs))
print("CLUSTERS: id definitions AST-span-lines outbound-call-sites outbound-symbol-pairs inbound-call-sites")
for c in cs:
    ns=[n for n in defs if cluster(n)==c]
    outs=[(a,b,v) for (a,b),v in edges.items() if cluster(byname[a])==c and cluster(byname[b])!=c]
    print(c,labels[c],len(ns),sum(n.end_lineno-n.lineno+1 for n in ns),sum(v for a,b,v in outs),len(outs),sum(v for (a,b),v in matrix.items() if b==c and a!=c))
print("MATRIX (direct Name call sites; row caller, col callee)")
print(" ".join(["row"]+cs))
for a in cs:print(a,*[matrix[a,b] for b in cs])
print("TOP CLUSTER EDGES",sorted(((v,a,b) for (a,b),v in matrix.items() if a!=b),reverse=True)[:10])
print("TOP SYMBOL EDGES")
for (a,b),v in sorted(edges.items(),key=lambda kv:(-kv[1],kv[0])):
    if cluster(byname[a])!=cluster(byname[b]):
        print(v,cluster(byname[a]),a,"->",cluster(byname[b]),b)
        if not hasattr(cluster,"count"):cluster.count=0
        cluster.count+=1
        if cluster.count==10:break
# Global load names from the compiler symbol tables, includes nested scopes.
tab=symtable.symtable(src,"fleet.py","exec")
def global_reads(t):
    out={s.get_name() for s in t.get_symbols() if s.is_global() and s.is_referenced()}
    for child in t.get_children():out |= global_reads(child)
    return out
tables={(t.get_name(),t.get_lineno()):t for t in tab.get_children()}
assigned={s.get_name() for s in tab.get_symbols() if s.is_assigned() and not s.is_namespace()}
reads={}
for n in defs:
    t=tables[(n.name,n.lineno)]
    reads[n.name]=global_reads(t)&assigned
print("MODULE STATE: name => clusters(definitions reading it)")
for name in sorted(assigned):
    counts=collections.Counter(cluster(byname[n]) for n,ns in reads.items() if name in ns)
    if counts:print(name," ".join(c+":"+str(counts[c]) for c in cs if counts[c]))
print("INDEX OUTBOUND")
for (a,b),v in sorted(edges.items()):
    if cluster(byname[a])=="X" and cluster(byname[b])!="X":print(a,b,v)
print("INDEX INBOUND")
for (a,b),v in sorted(edges.items()):
    if cluster(byname[b])=="X" and cluster(byname[a])!="X":print(a,b,v)
print("MODULE IMPORTS", [ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))])

print("INDEX distinct external direct-call targets",len({b for (a,b) in edges if cluster(byname[a])=="X" and cluster(byname[b])!="X"}))
~~~

### R2

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R2 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import ast,subprocess,re,sys
SHA="708fa45246ca957263b3ce299add6f13efb8c330"
def g(*args):return subprocess.check_output(["git",*args],text=True)
src=g("show",SHA+":bin/fleet.py");t=ast.parse(src);ls=src.splitlines()
cs=g("log","--format=%h",SHA,"--","bin/fleet.py").splitlines()
print("history commits",len(cs))
for i in sorted({round(j*(len(cs)-1)/9) for j in range(10)}):
    print(i,cs[i],len(g("show",cs[i]+":bin/fleet.py").splitlines()))
print("SPEC pin c63d7dd",len(g("show","c63d7dd:bin/fleet.py").splitlines()))
print("growth ratio",round(len(ls)/len(g("show","c63d7dd:bin/fleet.py").splitlines()),3))
paths=g("ls-tree","-r","--name-only",SHA,"bin/").splitlines()
print("bin files",len(paths))
for p in paths:print(p,len(g("show",SHA+":"+p).splitlines()))
doc=set();comment={i+1 for i,l in enumerate(ls) if l.lstrip().startswith("#")};blank={i+1 for i,l in enumerate(ls) if not l.strip()}
for n in ast.walk(t):
    if isinstance(n,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Constant) and isinstance(n.body[0].value.value,str):
        doc.update(range(n.body[0].lineno,n.body[0].end_lineno+1))
print("exclusive lines docstring/comment/blank/remaining",len(doc),len(comment-doc),len(blank-doc-comment),len(ls)-len(doc|comment|blank))
print("characters/chars-per-four estimate",len(src),(len(src)+3)//4)
imports=set()
for n in ast.walk(t):
    if isinstance(n,ast.Import):imports|={a.name.split(".")[0] for a in n.names}
    if isinstance(n,ast.ImportFrom) and n.module:imports.add(n.module.split(".")[0])
print("all import roots",sorted(imports));print("not Python "+sys.version.split()[0]+" stdlib",sorted(imports-sys.stdlib_module_names))
for n in t.body:
    if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ("VERB_EFFECT_DESTRUCTIVE","VERB_EFFECT_DISRUPTIVE","VERB_EFFECT_ORDINARY","VERB_EFFECT_RESIDUAL"):
        v=ast.literal_eval(n.value);print(n.targets[0].id,len(v),v)
for rev,p,pattern in [
    ("cfc1f44","CLAUDE.md",r"approved|single file"),
    ("cfc1f44","docs/SPEC.md",r"single-file|posttooluse_mailbox.py|stop_mailbox.py"),
    (SHA,"docs/SPEC.md",r"single-file CLI"),
    (SHA,"docs/OPERATOR-GATES.md",r"single.file|one file to copy|import.path"),
    (SHA,"README.md",r"git clone|PATH|plugin install"),
]:
    hits=[l for l in g("show",rev+":"+p).splitlines() if re.search(pattern,l,re.I)]
    print("provenance",rev,p,hits)
print("rule introduction",g("log",SHA,"--reverse","--format=%h %s","-S","single file","--","CLAUDE.md","docs/SPEC.md","docs/OPERATOR-GATES.md","knowledge/lessons.md").strip())
print("rolling lesson",*[l for l in g("show","92d0c3f:knowledge/lessons.md").splitlines() if "a ROLLING document" in l])
print("ratified taxonomy",*[l for l in g("show","9b8977c:docs/OPERATOR-GATES.md").splitlines() if "a reference to a deleted file" in l])
~~~

### R3

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R3 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import subprocess as s,re,ast
H="708fa45246ca957263b3ce299add6f13efb8c330"
def g(*a):return s.check_output(["git",*a],text=True)
rows=[];waves=[]
for line in g("log",H,"--first-parent","--merges","--format=%H%x09%P%x09%s").splitlines():
    sha,ps,sub=line.split("\t",2);m=re.search(r"(?i)\bw(\d+)",sub)
    if not m:continue
    w=int(m[1])
    if w not in waves:
        if len(waves)==15:break
        waves.append(w)
    p=ps.split();base=g("merge-base",*p).strip()
    left=set(g("diff","--name-only",base,p[0]).splitlines())
    right=set(g("diff","--name-only",base,p[1]).splitlines())
    out=g("merge-tree",base,*p);path=part=None;blocks=[];ours=[];theirs=[]
    for l in out.splitlines():
        fm=re.match(r"  (?:base|our|their)\s+\d+\s+[0-9a-f]+\s+(.+)",l)
        if fm:path=fm[1]
        if re.match(r"^\+?<<<<<<< ",l):part="ours";ours=[];theirs=[];continue
        if part and re.match(r"^\+?=======",l):part="theirs";continue
        if part and re.match(r"^\+?>>>>>>> ",l):
            if path=="bin/fleet.py":blocks.append((ours,theirs))
            part=None;continue
        if part and not l.startswith("-"):
            (ours if part=="ours" else theirs).append(l[1:] if l[:1] in "+ " else l)
    digit_only=commentary=0
    if blocks:
        banks=[]
        for parent in p:
            code=g("show",parent+":bin/fleet.py");ls=code.splitlines()
            banks.append(["\n".join(ls[n.lineno-1:n.end_lineno]) for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Constant) and isinstance(n.value,str)])
        for sides in blocks:
            def mask(ls):return re.sub(r":\d+(?:[-–]\d+)?",":N","\n".join(ls))
            digit_only+=mask(sides[0])==mask(sides[1])
            commentary+=all(all(not x.strip() or x.lstrip().startswith("#") for x in side) or any("\n".join(side) in literal for literal in bank) for side,bank in zip(sides,banks))
    rows.append((w,sha[:7],int("bin/fleet.py" in right),int("bin/fleet.py" in left&right),int(bool(blocks)),len(blocks),digit_only,commentary))
print("wave merges incoming_fleet parent_overlap conflict_merges blocks digit_only commentary")
for w in waves:
    rr=[r for r in rows if r[0]==w];print(w,len(rr),*[sum(r[i] for r in rr) for i in range(2,8)])
for name,rr in [("15_observed",rows),("numeric_w49_w63",[r for r in rows if 49<=r[0]<=63])]:
    print(name,len(rr),*[sum(r[i] for r in rr) for i in range(2,8)],"waves_with_two_fleet_lanes",sum(sum(r[2] for r in rr if r[0]==w)>=2 for w in waves))
print("conflicting rows",[r for r in rows if r[4]])
~~~

### R4

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R4 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import ast,collections,subprocess,io,tarfile,hashlib,re,pathlib
SHA="708fa45246ca957263b3ce299add6f13efb8c330"
def g(*args):return subprocess.check_output(["git",*args],text=True)
paths=g("ls-tree","-r","--name-only",SHA).splitlines()
def source(p):return g("show",SHA+":"+p)
uses=[]; patches=[]; parsers={}; filedunders=[]
for p in paths:
    if not p.startswith("tests/") or not p.endswith(".py"):continue
    s=source(p);t=ast.parse(s)
    if "fleet.__file__" in s:filedunders.append(p)
    aliases={a.asname or a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names if a.name=="ast"}
    calls=[]
    for n in ast.walk(t):
        if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=="fleet":uses.append((p,n.lineno,n.attr))
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
            if n.func.attr=="setattr" and len(n.args)>=2 and isinstance(n.args[0],ast.Name) and n.args[0].id=="fleet":
                name=ast.literal_eval(n.args[1]) if isinstance(n.args[1],ast.Constant) else "<dynamic>"
                patches.append((p,n.lineno,name))
            if isinstance(n.func.value,ast.Name) and n.func.value.id in aliases and n.func.attr=="parse":calls.append(n.lineno)
    if calls:parsers[p]=sorted(calls)
print("fleet attributes occurrences/files/names",len(uses),len({r[0] for r in uses}),len({r[2] for r in uses}))
print("setattr occurrences/files/names",len(patches),len({r[0] for r in patches}),len({r[2] for r in patches}))
print("top patches",collections.Counter(r[2] for r in patches).most_common(10))
print("fleet.__file__ files",len(filedunders))
print("AST parse files",len(parsers))
for p,ls in parsers.items():print(p,",".join(map(str,ls)))
for area in ("tests/","docs/specs/","docs/","bin/","tools/"):
    selected=[p for p in paths if p.startswith(area) and (area!="docs/" or not p.startswith("docs/specs/"))]
    matches=[]
    for p in selected:
        if not p.endswith((".py",".md",".sh")):continue
        for i,line in enumerate(source(p).splitlines(),1):
            for match in re.finditer(r"fleet\.py:[0-9]+",line):matches.append((p,i,match[0]))
    print("literal fleet.py:digits",area,"occurrences",len(matches),"files",len({r[0] for r in matches}))
print("RUNTIME CONSUMERS")
for p in paths:
    if p.startswith("bin/") and p.endswith(".py") and p!="bin/fleet.py":
        t=ast.parse(source(p))
        imports=[ast.unparse(n) for n in ast.walk(t) if isinstance(n,(ast.Import,ast.ImportFrom)) and "fleet" in ast.unparse(n)]
        attrs=[n for n in ast.walk(t) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=="fleet"]
        print(p,"imports",imports,"loads",sorted({n.attr for n in attrs if isinstance(n.ctx,ast.Load)}),"stores",sorted({n.attr for n in attrs if isinstance(n.ctx,ast.Store)}))
print("PATH AND SYMBOL TEXT INVENTORY (complete sites: git grep -n -I -E 'bin/fleet\\.py|fleet\\.[A-Za-z_][A-Za-z_0-9]*' "+SHA+")")
raw=g("grep","-n","-I","-E",r"bin/fleet\.py|fleet\.[A-Za-z_][A-Za-z_0-9]*",SHA)
counts=collections.Counter()
for line in raw.splitlines():
    _,p,number,text=line.split(":",3);counts[p]+=1
byarea=collections.Counter()
for p,cnt in counts.items():byarea[p.split("/")[0]]+=cnt
print("matching lines/files",sum(counts.values()),len(counts));print("matching lines by root",sorted(byarea.items()))
print("runtime/config/tool matching files",[(p,cnt) for p,cnt in sorted(counts.items()) if not p.startswith(("docs/","tests/","knowledge/","spike/"))])
blob=subprocess.check_output(["git","show",SHA+":bin/fleet.py"])
archive=subprocess.check_output(["git","archive",SHA,"bin/fleet.py"])
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:print("archive equals blob",tar.extractfile("bin/fleet.py").read()==blob)
print("blob sha256",hashlib.sha256(blob).hexdigest())
core={};exec('FLEET_HOME="old"\ndef state_dir(): return FLEET_HOME\n',core)
facade={k:v for k,v in core.items() if k!="__builtins__"};facade["FLEET_HOME"]="new"
print("reexport rebinding",facade["FLEET_HOME"],facade["state_dir"]())
~~~

### R5

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R5 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
# volatile: source journals are outside the repository and may change
import ast,subprocess,pathlib,re,hashlib,math
root=pathlib.Path("/home/altai/proga/fleet/state/journals")
s=subprocess.check_output(["git","show","708fa45246ca957263b3ce299add6f13efb8c330:bin/fleet.py"],text=True)
ls=s.splitlines(keepends=True);ds={n.name:n for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
cases={"w59-inithome.md":["homes_list_path","read_homes_list","append_home_record","cmd_homes","cmd_init"],"w61-sidcollision.md":["resolution_population","_record_sids","apply_resolved_home"],"w63-sidunion.md":["_record_sids","supervisor_claim_sids","cmd_sup_status"]}
for name,symbols in cases.items():
    b=(root/name).read_bytes();txt=b.decode()
    explicit=[l for l in txt.splitlines() if re.search(r"(?:sed.*fleet\.py|Read.*fleet\.py.*(?:offset|limit|\d+[-–]\d+)|fleet\.py.*(?:offset|limit))",l)]
    chars=sum(len("".join(ls[ds[n].lineno-1:ds[n].end_lineno])) for n in symbols)
    print(name,"sha256",hashlib.sha256(b).hexdigest(),"bytes",len(b),"explicit Read/sed ranges",len(explicit))
    print("proxy symbols",",".join(symbols),"lines",sum(ds[n].end_lineno-ds[n].lineno+1 for n in symbols),"chars",chars,"ceil chars/4",math.ceil(chars/4))
~~~

### R6

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R6 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
# volatile: host load, caches and cached interpreter availability affect results
import sys,subprocess,os,statistics,time,importlib.util,pathlib,hashlib
root=pathlib.Path.cwd()
assert hashlib.sha256((root/"bin/fleet.py").read_bytes()).hexdigest()=="c1866ff7b5df4c1e750d051b940e7f3e1caaad1fbeeb2da5527c35dc1d0a78aa","use the baseline source tree"
print("python",sys.version.split()[0])
print("bytecode_exists",pathlib.Path(importlib.util.cache_from_source(str(root/"bin/fleet.py"))).exists())
wall=[];own=[];cum=[]
for i in range(5):
    start=time.perf_counter()
    p=subprocess.run([sys.executable,"-B","-X","importtime","-c","import fleet"],cwd=root/"bin",capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"))
    wall.append(round((time.perf_counter()-start)*1000,3))
    assert p.returncode==0,p.stderr
    line=next(x for x in p.stderr.splitlines() if x.endswith("| fleet"));cols=line.split("|")
    own.append(int(cols[0].split(":")[1]));cum.append(int(cols[1]))
    print("run",i+1,"rc",p.returncode,"self/cumulative us",own[-1],cum[-1],"process ms",wall[-1])
print("medians us/us/ms",statistics.median(own),statistics.median(cum),statistics.median(wall))
# Exact successful targeted collection command used on this host; no full floor.
py="/home/altai/.cache/uv/archive-v0/hRf30whVn5xzWp_8/bin/python"
p=subprocess.run([py,"-B","-m","pytest","--collect-only","-q","-p","no:cacheprovider","tests/test_load_registry_callers.py"],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"))
print(p.stdout,p.stderr,"collection rc",p.returncode)
~~~

### R7

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R7 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import ast,subprocess,collections,datetime,re
SHA="708fa45246ca957263b3ce299add6f13efb8c330"
s=subprocess.check_output(["git","show",SHA+":bin/fleet.py"],text=True)
raw=subprocess.check_output(["git","blame","--line-porcelain",SHA,"--","bin/fleet.py"],text=True)
lines={}; sha=None; dest=None;stamp=0
for l in raw.splitlines():
    words=l.split()
    if len(words) in (3,4) and len(words[0])==40 and all(c in "0123456789abcdef" for c in words[0]):
        sha=words[0];dest=int(words[2])
    elif l.startswith("author-time "):stamp=int(words[1])
    elif l.startswith("\t"):lines[dest]=(sha,stamp)
threshold=int(datetime.datetime(2026,9,9,tzinfo=datetime.timezone.utc).timestamp())
rows=[]
for n in ast.parse(s).body:
    if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
        vals=[lines[i] for i in range(n.lineno,n.end_lineno+1)]
        rows.append((len({x[0] for x in vals}),sum(x[1]>=threshold for x in vals),len(vals),n.name))
print("distinct blame origins / lines dated >=2026-09-09 UTC / AST span / symbol")
for row in sorted(rows,reverse=True)[:10]:print(*row)
~~~

### R8

MEASURED — Executable receipt source; output appears in the corresponding measurements above.

<!-- receipt:R8 -->
~~~python
# at 708fa45246ca957263b3ce299add6f13efb8c330
import ast,subprocess,re,pathlib
SHA="708fa45246ca957263b3ce299add6f13efb8c330"
def g(*a):return subprocess.check_output(["git",*a],text=True)
def src(p):return g("show",SHA+":"+p)
s=src("bin/fleet.py");t=ast.parse(s)
calls=[n for n in ast.walk(t) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="load_registry"]
print("direct load_registry calls",len(calls))
for n in ast.walk(t):
    if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=="PLATFORM":print("PLATFORM call",n.lineno,ast.unparse(n))
for n in t.body:
    if isinstance(n,ast.FunctionDef) and any(isinstance(c,ast.Global) and "FLEET_HOME" in c.names for c in ast.walk(n)):print("FLEET_HOME global declaration",n.name)
# Reference census uses the shipped receipt parser; it executes no receipts.
ns={"__name__":"split_receipt_inspection","__file__":str(pathlib.Path("tools/verify_receipts.py").resolve())}
exec(compile(src("tools/verify_receipts.py"),ns["__file__"],"exec"),ns)
receipt_hits=[]
for p in g("ls-tree","-r","--name-only",SHA,"docs/specs/").splitlines():
    if not p.endswith(".md"):continue
    checkable,unclassified,_=ns["parse"](src(p))
    for r in checkable+unclassified:
        hits=re.findall(r"fleet\.py:[0-9]+",r.cmd+"\n"+"\n".join(r.expected))
        if hits:receipt_hits.append((p,r.line,r.pin,len(hits)))
print("parsed docs/specs receipts containing fleet.py:digits",len(receipt_hits),"citation occurrences",sum(r[3] for r in receipt_hits))
for row in receipt_hits:print(row)
candidates={
"tests/test_load_registry_callers.py":[
("TestLoadRegistryCallSites","test_the_matcher_finds_call_sites_at_all"),
("TestTheDetectorCannotBeWalkedAround","test_the_allowlist_has_no_dead_entries"),
("TestTheDetectorCannotBeWalkedAround","test_cmd_status_quarantines_ONLY_under_the_lock"),
("TestTheDetectorCannotBeWalkedAround","test_cmd_doctor_quarantines_ONLY_behind_the_repair_flag")],
"tests/test_unlocked_quarantine.py":[("TestTheUnlockedCensusIsPinned",n) for n in ("test_the_matcher_finds_call_sites_at_all","test_the_allowlist_has_no_dead_entries","test_holder_is_limited_really_is_lock_held_by_its_caller","test_the_two_preflight_helpers_do_not_regain_load_registry")],
"tests/test_views_doctrine.py":[(None,"test_the_rename_has_exactly_one_caller")],
"tests/test_stillborn_handoff.py":[("TestEveryFirstTurnStampIsAlsoAnEvent","test_every_turns_equals_one_stamp_sits_beside_a_turn_started_event")],
"tests/test_install_home_split.py":[("TestInstallRootIsNotOverridable","test_nothing_reads_a_fleet_install_environment_variable")],
"tests/test_rendered_command_quoting.py":[("TestTheCensusIsTheGate","test_the_census_finds_exactly_the_renders_it_is_pinned_to")]}
print("static red candidate functions",sum(map(len,candidates.values())))
for p,entries in candidates.items():
    text=src(p);tree=ast.parse(text)
    for cls,name in entries:
        scope=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls) if cls else tree
        fn=next(n for n in scope.body if isinstance(n,ast.FunctionDef) and n.name==name)
        print(p,cls,name,fn.lineno)
        print(ast.get_source_segment(text,fn))
# Exact path/import/root/text-pin source receipts; all output remains pinned.
patterns={
"bin/fleet.py":r"INSTALL_ROOT =|Path\(__file__\)|global FLEET_HOME|INSTALL_ROOT / .bin. / .fleet.py.|PLATFORM\.",
"bin/fleet":r".",
"bin/fleet.cmd":r"fleet.py|py -",
"bin/hooks/run_py.sh":r"exec|\$@|\$1",
"bin/fleet_keeper.py":r"sys.path|import fleet|Path\(home\).*fleet.py",
"bin/fleet_statusline.py":r"sys.path|import fleet|fleet.FLEET_HOME",
"worker-settings.template.json":r".",
".claude-plugin/plugin.json":r".",
"tests/test_sid_collision.py":r"fleet.__file__|install.*bin|hardlink|copy2",
"tests/test_core.py":r"fleet.__file__",
"tests/test_index_compose.py":r"fleet.__file__|getsource",
"tests/test_resilience.py":r"fleet.__file__",
"tests/test_self_citations.py":r"fleet.__file__|line.number|SRC_PATH",
"tests/test_retired_sid_citations.py":r"fleet.__file__|read_text",
"tools/repoint_self_citations.py":r"fleet.py",
"tools/mutate_liveness.py":r"fleet.py",
"tools/verify_receipts.py":r"def pinned_tree|archive|extractall",
}
for p,pat in patterns.items():
    print("SOURCE",p)
    for i,line in enumerate(src(p).splitlines(),1):
        if re.search(pat,line):print(i,line)
for p in g("ls-tree","-r","--name-only",SHA,"commands/").splitlines():
    if p.endswith(".md"):
        print("COMMAND",p)
        for i,line in enumerate(src(p).splitlines(),1):
            if re.search(r"fleet(?: |\.py|\.)",line):print(i,line)
spec=src("docs/SPEC.md")
print(spec[spec.index("## 16."):spec.index("## 17.")])
print("RECENT LANDINGS",g("log",SHA,"-35","--format=%h %s","--first-parent"))
gates=src("docs/OPERATOR-GATES.md")
print("GATE INPUT",*[l for l in gates.splitlines() if "Reading A" in l or "G-K5" in l])
~~~

## Delivery status and final checks

MEASURED — The report is complete as a working-tree file, including the requested sections, correction section, draft SPEC and embedded receipts. The required commit is **blocked**, so the lane's commit-based DONE condition is **not met**. Only this report is an authored workspace change; the pre-existing .mcx directory remains untracked.

MEASURED — The authorized branch-local staging attempt failed before creating an index lock:

~~~text
# at 708fa45246ca957263b3ce299add6f13efb8c330
# volatile: filesystem permissions in this worker session
$ git add -- docs/lanes/w6x-split-research.md
fatal: Unable to create '/home/altai/proga/fleet/.git/worktrees/fleet-w63-split/index.lock': Read-only file system
exit: 128
~~~

MEASURED — No commit, push, merge or ref update was performed. The journal path is also outside writable roots, as recorded above. Finishing delivery requires the parent to commit this existing report on w63/split-research from a context allowed to write that branch's Git metadata; no implementation work remains in this research scope.

MEASURED — Final source fence/check commands (the report's syntax and section check is read-only):

~~~sh
# at 708fa45246ca957263b3ce299add6f13efb8c330
# live: validates this report and the current worktree fence
python3 -B - <<'PY'
from pathlib import Path
import re, subprocess
p=Path('docs/lanes/w6x-split-research.md'); text=p.read_text()
blocks=re.findall(r'<!-- receipt:(R[0-9]+) -->\n~~~python\n(.*?)\n~~~',text,re.S)
assert [ident for ident,_ in blocks]==['R'+str(i) for i in range(1,9)]
for ident,code in blocks: compile(code,ident,'exec')
assert len(re.findall(r'^## [1-7]\. ',text,re.M))==7
assert '## WHERE THIS BRIEF WAS WRONG' in text
assert 'docs updated: docs/lanes/w6x-split-research.md' in text
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()=='w63/split-research'
subprocess.run(['git','diff','--exit-code','708fa45','--','bin','tests'],check=True)
subprocess.run(['git','diff','--check'],check=True)
assert not any(line.rstrip()!=line for line in text.splitlines())
print('report sections/receipt syntax/whitespace: PASS')
print('branch and bin/tests fence: PASS')
PY
~~~

MEASURED — Captured result: report sections/receipt syntax/whitespace **PASS**; branch and bin/tests fence **PASS**. Targeted collection and import outcomes are in R6/§3. Full floors intentionally not run. Native assistants completed, were collected, and closed; MCX_WORKER remains 1.
