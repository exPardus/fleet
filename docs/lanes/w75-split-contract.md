# Lane w75 — split contract (Wave A)
DONE means: this report fixes the exact boundary, dependencies, inbound calls, import direction, discovery/fixture plan, and falsification answers; no extraction is made.

MEASURED — Current `bin/fleet.py` has exactly 80 boundary definitions (3 classes + 77 functions, lines 13745–15254, stopping before `build_parser`):
`IndexConfigError`, `IndexPathError`, `IndexDigestTooLargeError`, `index_dir`, `index_symbols_dir`, `index_config_path`, `_index_posix_rel`, `shard_path_for_source`, `_index_require_inside`, `_index_entry_paths`, `source_rel_from_shard`, `source_lang`, `_index_tsv_field`, `_index_split_lines`, `_index_row_key`, `render_shard`, `read_shard`, `_index_unlink_quiet`, `write_shard_atomic`, `header_for_bytes`, `source_header`, `_index_decode`, `_index_py_sig`, `_index_py_symbols`, `_index_parse_python`, `_index_parse_markdown`, `parse_source_symbols`, `_index_config_array`, `_parse_index_config`, `load_index_config`, `_index_glob_regex`, `_index_glob_match`, `render_digest`, `_index_is_repo_boundary`, `_index_is_reparse_point`, `find_index_root`, `verified_shard_rows`, `_index_selects`, `index_source_files`, `index_shard_rels`, `_index_prune_shard`, `_new_index_report`, `_index_refresh_one`, `build_index`, `update_index`, `index_status`, `index_teach_verbs`, `registered_cli_verbs`, `index_teach_lines`, `parse_context_arg`, `compose_context_digests`, `_index_root_arg`, `_require_index`, `_index_files_arg`, `_index_git_common_dir`, `_ensure_index_excluded`, `_print_index_report`, `cmd_index_init`, `cmd_index_build`, `cmd_index_update`, `cmd_index_status`, `cmd_index`, `_q_pointer`, `_q_source_lines`, `_q_print_capped`, `_q_print_notes`, `_q_collect_rows`, `_q_match`, `_q_sorted`, `_q_print_hits`, `_q_print_slice`, `_q_shard_rels`, `_q_path_dialect_hint`, `_cmd_q_query`, `_q_contained`, `_q_outline_rels`, `_q_outline_known`, `_q_print_outline_candidates`, `_cmd_q_outline`, `cmd_q`.

MEASURED — External fleet targets are `FleetCliError` (three class bases plus catches/raises), `_replace_with_retry` (`write_shard_atomic:13969`), and `build_parser` (`registered_cli_verbs:14558`). Inbound calls are `_recovered_brief:1231` and `compose_prompt:1135` → `index_teach_lines`; `compose_prompt:1138` → `compose_context_digests`; `cmd_spawn:4148` → `parse_context_arg`; `main:15757/15759` → `cmd_index/cmd_q`.

BELIEVED — Required direction is `fleet.py` facade/kernel → `fleet_index.py`, with qualified calls/wrappers and injected replace/parser capabilities; `fleet_index.py` must not import `fleet.py`, and no FLEET_HOME/claim/parser-cache globals may be copied. Exact 80-set D has an abort signal: its exception class bases need `FleetCliError` at definition time; reverse import is a facade cycle, while a local base/factory changes exception identity/consumed API. Widen the dependency boundary or keep A; no extraction here.

MEASURED — Wave B must first collect `import fleet` aliases, then AST-scan every `tests/**/*.py` (including `conftest.py`) for calls whose patch receiver resolves to an alias (`setattr`/`.setattr`/`patch.object`), string patch paths, direct assignments, `fleet.__file__`, and AST source readers; current census is 714 setattr calls/84 files/105 names, with 31 moved-or-dynamic calls/8 files/10 dynamic names. Its `patch_fleet(monkeypatch)` fixture must route moved names to `fleet_index`, mirror the facade alias for direct probes, fail unknown/dynamic names, and exercise every inbound path with sentinels.

Falsification — home/claim state: no move is allowed; any requirement aborts D.
Falsification — consumed API/state behavior: no change is allowed; `FleetCliError` identity is currently an abort signal.
Falsification — safety detector: no weakening; every implementation file and positive population must remain scanned.
Falsification — facade cycle: exact 80-set currently requires one for `FleetCliError`; D is not approved without a widened leaf dependency.
Falsification — installed CLI semantics: retain `bin/fleet`, `bin/fleet.cmd`, and `python bin/fleet.py`; any change aborts D.
Falsification — no navigation/context gain while maintenance expands: remeasure after a reviewed seam; otherwise return to A.
Falsification — defer broad split: only executable same-function conflicts or blocked independent work can overturn deferral; none is shown here.

WHERE THIS BRIEF WAS WRONG — the cited 660 patch count is 714 in this current tree; the 80-name boundary remains exact. No code was extracted.

PATH LIST:
- `docs/lanes/w75-split-contract.md`
- `state/journals/w75.md`
