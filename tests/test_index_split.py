"""The wave A boundary, facade identity, and live cross-module call edges."""
import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import fleet
import fleet_errors
import fleet_index


BIN = Path(__file__).resolve().parents[1] / "bin"
MOVED = frozenset("""
IndexConfigError IndexPathError IndexDigestTooLargeError index_dir
index_symbols_dir index_config_path _index_posix_rel shard_path_for_source
_index_require_inside _index_entry_paths source_rel_from_shard source_lang
_index_tsv_field _index_split_lines _index_row_key render_shard read_shard
_index_unlink_quiet write_shard_atomic header_for_bytes source_header
_index_decode _index_py_sig _index_py_symbols _index_parse_python
_index_parse_markdown parse_source_symbols _index_config_array
_parse_index_config load_index_config _index_glob_regex _index_glob_match
render_digest _index_is_repo_boundary _index_is_reparse_point find_index_root
verified_shard_rows _index_selects index_source_files index_shard_rels
_index_prune_shard _new_index_report _index_refresh_one build_index update_index
index_status index_teach_verbs registered_cli_verbs index_teach_lines
parse_context_arg compose_context_digests _index_root_arg _require_index
_index_files_arg _index_git_common_dir _ensure_index_excluded _print_index_report
cmd_index_init cmd_index_build cmd_index_update cmd_index_status cmd_index
_q_pointer _q_source_lines _q_print_capped _q_print_notes _q_collect_rows
_q_match _q_sorted _q_print_hits _q_print_slice _q_shard_rels
_q_path_dialect_hint _cmd_q_query _q_contained _q_outline_rels _q_outline_known
_q_print_outline_candidates _cmd_q_outline cmd_q
""".split())
CONSTANTS = frozenset("""
INDEX_DIR_NAME INDEX_SYMBOLS_DIR_NAME INDEX_CONFIG_FILE_NAME INDEX_SHARD_SUFFIX
SHARD_KINDS INDEX_SHA_HEX_LEN INDEX_GITIGNORE_ENTRY INDEX_CONFIG_KEYS
INDEX_CONFIG_DEFAULTS INDEX_CONFIG_DEFAULT_TOML INDEX_SKIP_DIR_NAMES
INDEX_NO_INDEX_MESSAGE _INDEX_LINE_BREAK_RE _INDEX_HEX _MD_HEADING_RE
_MD_CLOSING_HASHES_RE INDEX_DIGEST_WARN_CHARS INDEX_DIGEST_REFUSE_CHARS
INDEX_TEACH_LINES INDEX_LIST_CAP INDEX_FAILED_RC Q_LIMIT_DEFAULT
Q_OUTPUT_LINE_CAP Q_TRUNCATION_TRAILER Q_NOTE_CAP
""".split())


def _tree(name):
    return ast.parse((BIN / (name + ".py")).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_fleet_home(tmp_path, patch_fleet):
    patch_fleet("FLEET_HOME", tmp_path / "fleet-home")


def test_exact_boundary_and_facade_identity():
    definitions = {
        node.name for node in _tree("fleet_index").body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert len(MOVED) == 80
    assert definitions == MOVED
    assert not MOVED.intersection(
        node.name for node in _tree("fleet").body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for name in MOVED | CONSTANTS:
        assert getattr(fleet, name) is getattr(fleet_index, name), name


def test_leaf_has_only_plain_exception_and_shared_identity():
    body = _tree("fleet_errors").body
    assert len(body) == 1
    cls = body[0]
    assert isinstance(cls, ast.ClassDef) and cls.name == "FleetCliError"
    assert len(cls.bases) == 1
    assert isinstance(cls.bases[0], ast.Name) and cls.bases[0].id == "Exception"
    assert fleet_errors.FleetCliError.__bases__ == (Exception,)
    assert fleet.FleetCliError is fleet_index.FleetCliError is fleet_errors.FleetCliError
    for cls in (fleet.IndexConfigError, fleet.IndexPathError,
                fleet.IndexDigestTooLargeError):
        assert cls.__bases__ == (fleet_errors.FleetCliError,)


@pytest.mark.parametrize("module", ["fleet", "fleet_index", "fleet_errors"])
def test_modules_use_only_stdlib_and_approved_siblings(module):
    allowed_siblings = {
        "fleet": {"fleet_index", "fleet_errors"},
        "fleet_index": {"fleet_errors"},
        "fleet_errors": set(),
    }
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports break standalone CLI use"
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        assert set(roots) <= sys.stdlib_module_names | allowed_siblings[module]


def test_index_owns_no_home_claim_or_copied_parser_state():
    # A closed module binding inventory catches new copied state, including names
    # that a blacklist of today's home/claim globals would fail to anticipate.
    allowed_imports = {
        "ast", "fnmatch", "functools", "hashlib", "os", "re", "stat", "sys",
        "tempfile", "Path", "PureWindowsPath", "FleetCliError", "annotations",
    }
    runtime_names = {name for name in vars(fleet_index) if not name.startswith("__")}
    assert runtime_names == MOVED | CONSTANTS | allowed_imports | {
        "_replace_with_retry", "build_parser",
    }


def test_inbound_calls_resolve_through_the_index_owner():
    expected = {
        "compose_prompt": {"index_teach_lines", "compose_context_digests"},
        "_recovered_brief": {"index_teach_lines"},
        "cmd_spawn": {"parse_context_arg"},
        "main": {"cmd_index", "cmd_q"},
    }
    functions = {node.name: node for node in _tree("fleet").body
                 if isinstance(node, ast.FunctionDef)}
    for caller, targets in expected.items():
        calls = [node.func for node in ast.walk(functions[caller])
                 if isinstance(node, ast.Call)]
        actual = {call.attr for call in calls if isinstance(call, ast.Attribute)
                  and isinstance(call.value, ast.Name)
                  and call.value.id == "fleet_index"}
        assert targets <= actual, caller
        assert not targets.intersection(call.id for call in calls
                                        if isinstance(call, ast.Name)), caller


def test_compose_uses_both_injected_index_sentinels(tmp_path, patch_fleet):
    calls = []

    def teach(cwd):
        calls.append(("teach", cwd))
        return "\nTEACH-SENTINEL\n"

    def digests(cwd, context):
        calls.append(("digests", cwd, context))
        return "DIGEST-SENTINEL", []

    patch_fleet("index_teach_lines", teach)
    patch_fleet("compose_context_digests", digests)
    prompt, claim, mail = fleet.compose_prompt(
        "w1", tmp_path, "TASK-SENTINEL", None, context=["src.py"])
    assert calls == [("teach", tmp_path), ("digests", tmp_path, ["src.py"])]
    assert prompt.index("TEACH-SENTINEL") < prompt.index("DIGEST-SENTINEL")
    assert prompt.index("DIGEST-SENTINEL") < prompt.index("TASK-SENTINEL")
    assert claim is None and mail == ""


def test_recovered_brief_uses_index_sentinel(tmp_path, patch_fleet):
    calls = []

    def teach(cwd):
        calls.append(cwd)
        return "\nRECOVERY-SENTINEL\n"

    patch_fleet("index_teach_lines", teach)
    task = "recover this complete task"
    payload = fleet.task_file_path("w1")
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text(fleet._PREAMBLE_TEMPLATE.format(
        name="w1", cwd=str(tmp_path),
        journal_target=fleet.journal_file_path("w1").as_posix())
        + "\nRECOVERY-SENTINEL\n\n" + task, encoding="utf-8")
    assert fleet._recovered_brief("w1", {"cwd": str(tmp_path), "task": task}) == task
    assert calls == [str(tmp_path)]


def test_spawn_passes_context_through_index_parser(tmp_path, patch_fleet):
    seen = []
    context_sentinel = object()

    class StopBeforeClaim(BaseException):
        pass

    def parse(value):
        seen.append(value)
        return context_sentinel

    def compose(name, cwd, task, sid, context):
        assert context is context_sentinel
        raise StopBeforeClaim

    patch_fleet("_supervisor_gate", lambda *a, **kw: None)
    patch_fleet("_ceiling_refuses_dispatch", lambda *a, **kw: None)
    patch_fleet("_require_instance_settings", lambda: None)
    patch_fleet("parse_context_arg", parse)
    patch_fleet("compose_prompt", compose)
    args = SimpleNamespace(dir=str(tmp_path), task="task", name="w1",
                           mode="dontask", context="CONTEXT-SENTINEL")
    with pytest.raises(StopBeforeClaim):
        fleet.cmd_spawn(args)
    assert seen == ["CONTEXT-SENTINEL"]


def test_main_dispatches_both_index_commands_to_owner(patch_fleet):
    seen = []
    patch_fleet("apply_resolved_home", lambda *a, **kw: None)
    patch_fleet("cmd_index", lambda args: seen.append(args.command) or 71)
    patch_fleet("cmd_q", lambda args: seen.append(args.command) or 72)
    assert fleet.main(["index", "status"]) == 71
    assert fleet.main(["q", "needle"]) == 72
    assert seen == ["index", "q"]


@pytest.mark.parametrize("replace_error", [False, True])
def test_real_index_error_reaches_existing_cli_catch(
        tmp_path, patch_fleet, capsys, replace_error):
    class PatchedCliError(Exception):
        pass

    original = fleet_errors.FleetCliError
    if replace_error:
        patch_fleet("FleetCliError", PatchedCliError)
        assert fleet.FleetCliError is fleet_index.FleetCliError is PatchedCliError
        assert fleet_errors.FleetCliError is original
    patch_fleet("apply_resolved_home", lambda *a, **kw: None)
    missing = tmp_path / "absent"
    # Real _index_root_arg raises the owner's live FleetCliError binding.
    assert fleet.main(["index", "status", "--path", str(missing)]) == 1
    assert "is not a directory" in capsys.readouterr().err


def test_replace_capability_resolves_fleet_patch_at_call_time(tmp_path, patch_fleet):
    calls = []

    def replace(source, target, **kwargs):
        calls.append((source, target, kwargs))
        raise OSError("replace sentinel")

    patch_fleet("_replace_with_retry", replace)
    shard = tmp_path / "source.py.tsv"
    assert fleet_index.write_shard_atomic(
        shard, fleet_index.header_for_bytes(b"", "source.py"), []) is False
    assert len(calls) == 1 and calls[0][1] == str(shard)
    assert list(tmp_path.iterdir()) == []


def test_parser_capability_resolves_fleet_patch_at_call_time(patch_fleet):
    parser = argparse.ArgumentParser()
    parser.add_subparsers(dest="command").add_parser("parser-sentinel")
    patch_fleet("build_parser", lambda: parser)
    fleet_index.registered_cli_verbs.cache_clear()
    try:
        assert fleet_index.registered_cli_verbs() == frozenset({"parser-sentinel"})
    finally:
        fleet_index.registered_cli_verbs.cache_clear()


@pytest.mark.parametrize("entry", ["fleet.py", "fleet"])
def test_installed_entrypoints_import_siblings_from_another_cwd(tmp_path, entry):
    if entry == "fleet" and os.name == "nt":
        pytest.skip("POSIX shim needs a POSIX shell")
    command = [str(BIN / entry), "--help"]
    if entry == "fleet.py":
        command.insert(0, sys.executable)
    environment = dict(os.environ, FLEET_HOME=str(tmp_path / "home"),
                       FLEET_PYTHON=sys.executable)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(command, cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "index" in result.stdout and "usage:" in result.stdout


def test_windows_shim_still_dispatches_the_same_standalone_script():
    commands = [line.strip() for line in (BIN / "fleet.cmd").read_text().splitlines()
                if line.strip() and not line.lower().startswith("rem")]
    assert commands == ["@echo off", 'set "NoDefaultCurrentDirectoryInExePath=1"',
                        'py -3.13 "%~dp0fleet.py" %*']
