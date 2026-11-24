"""Codex launch gate: compare used schema shapes, not the release version."""
import ast
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

import fleet_codex
import fleet_codex_schema as used
from codex_test_support import fake_combined_schema
from test_codex_host_ipc import _fake_app_server, _home, _shutdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "codex_app_server"
REVIEWED = ("0.155.1", "0.160.0", "0.161.0", "0.162.0", "0.171.0")


# --- the used-method inventory is derived from adapter call sites ---------

def _mentions_method(node):
    """True for `method`, `x.method`, or `x.get("method")`."""
    if isinstance(node, ast.Name):
        return node.id == "method"
    if isinstance(node, ast.Attribute):
        return node.attr == "method"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return (node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "method")
    return False


def _constants(node):
    return {item.value for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def _adapter_names(root=ROOT / "bin"):
    """Return (method-position names, slash-shaped literals) in adapter source.

    A method position is a `"method"` dict value, the first argument of
    `.request(...)`, or a comparison with a method value. Every name found
    there counts, whether or not a reviewed Codex release defines it, so a
    call to a method from a later release cannot escape the inventory.
    """
    positions, slashes = set(), set()
    for path in sorted(Path(root).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "/" in node.value:
                    slashes.add(node.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "method":
                        positions |= _constants(value)
            elif (isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr in {"request", "_recovery_request"}
                  and node.args):
                positions |= _constants(node.args[0])
            elif isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(_mentions_method(item) for item in operands):
                    for item in operands:
                        positions |= _constants(item)
    return positions, slashes


# Names in a method position that are not Codex methods: Fleet's own host IPC
# verbs and labels compared with method-like fields. A new name in a method
# position must be added to the inventory or here, by review.
NOT_CODEX_METHODS = frozenset({
    "approval/list", "approval/respond", "approval/supervisor-reservation-v1",
    "expect_method", "from_auth", "host/shutdown", "host/shutdown-restored",
    "interface-registration", "legacy-unverified", "method", "ping",
    "public-evidence/read", "public_method", "rpc", "supervisor-nonce",
    "unverified",
})


def _reviewed_public_methods():
    public = set()
    for version in REVIEWED:
        manifest = json.loads((FIXTURES / version / "manifest.json").read_text())
        public.update(manifest["public_methods"])
    return public


def test_inventory_equals_codex_methods_named_in_adapter_source():
    positions, slashes = _adapter_names()
    unknown = positions - used.USED_METHODS - NOT_CODEX_METHODS
    assert unknown == set(), ("unlisted method-position names:", sorted(unknown))
    named = (slashes | positions) & _reviewed_public_methods()
    assert named == set(used.USED_METHODS), (
        "unlisted:", sorted(named - used.USED_METHODS),
        "stale:", sorted(used.USED_METHODS - named))
    assert not (NOT_CODEX_METHODS & _reviewed_public_methods())


def test_a_call_to_a_method_no_reviewed_release_defines_is_caught(tmp_path):
    (tmp_path / "adapter.py").write_text(
        'def go(client):\n'
        '    client.request("future/newMethod", {}, timeout=1)\n'
        '    return {"method": "future/otherMethod"}\n')
    positions, _ = _adapter_names(tmp_path)
    assert {"future/newMethod", "future/otherMethod"} <= positions
    assert not ({"future/newMethod", "future/otherMethod"}
                & (used.USED_METHODS | NOT_CODEX_METHODS))


def test_inventory_covers_the_adapters_own_method_sets():
    assert fleet_codex._MUTATING_PUBLIC_METHODS <= used.USED_METHODS
    assert fleet_codex._BLOCKING_SERVER_REQUESTS <= used.USED_METHODS


@pytest.mark.parametrize("version", REVIEWED)
def test_reviewed_manifest_pins_used_shapes(version):
    manifest = json.loads((FIXTURES / version / "manifest.json").read_text())
    entries = manifest["used_schema_entries"]
    assert set(entries) == {f"{envelope} {method}" for envelope, method
                            in used.USED_SCHEMA_INVENTORY}
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    assert manifest["used_schema_sha256"] == hashlib.sha256(
        canonical.encode()).hexdigest()


# --- slice comparison -----------------------------------------------------

def test_unrelated_schema_change_keeps_the_used_digest():
    base = fake_combined_schema()
    changed = copy.deepcopy(base)
    changed["definitions"]["v2"]["UnusedParams"]["required"] = ["x"]
    changed["definitions"]["v2"]["BrandNew"] = {"type": "string"}
    assert used.used_schema_digests(changed) == used.used_schema_digests(base)


def test_prose_change_keeps_the_used_digest_but_a_property_named_description_counts():
    base = fake_combined_schema()
    prose = copy.deepcopy(base)
    prose["definitions"]["v2"]["TurnStartParams"]["description"] = "reworded"
    assert used.used_schema_digests(prose) == used.used_schema_digests(base)
    shape = copy.deepcopy(base)
    del shape["definitions"]["v2"]["TurnStartParams"]["properties"]["description"]
    assert used.used_schema_digests(shape) != used.used_schema_digests(base)


def test_used_shape_change_names_the_drifted_calls():
    base = fake_combined_schema()
    _, reviewed_entries = used.used_schema_digests(base)
    changed = copy.deepcopy(base)
    changed["definitions"]["v2"]["TurnSteerParams"]["required"] = ["threadId"]
    total, entries = used.used_schema_digests(changed)
    assert used.drifted_calls(
        entries, {"used_schema_entries": reviewed_entries}) == [
            "ClientRequest turn/steer"]


def test_a_shared_definition_change_drifts_every_call_that_reaches_it():
    base = fake_combined_schema()
    _, reviewed_entries = used.used_schema_digests(base)
    changed = copy.deepcopy(base)
    changed["definitions"]["v2"]["Status"]["enum"].append("cancelled")
    _, entries = used.used_schema_digests(changed)
    drifted = used.drifted_calls(entries, {"used_schema_entries": reviewed_entries})
    assert "ClientRequest turn/start" in drifted
    assert "ClientNotification initialized" not in drifted


@pytest.mark.parametrize("mutate", ["drop-method", "drop-response", "bad-ref"])
def test_unreadable_or_missing_used_shape_refuses(mutate):
    schema = fake_combined_schema()
    definitions = schema["definitions"]
    if mutate == "drop-method":
        definitions["ClientRequest"]["oneOf"] = [
            entry for entry in definitions["ClientRequest"]["oneOf"]
            if entry["properties"]["method"]["enum"] != ["turn/interrupt"]]
    elif mutate == "drop-response":
        del definitions["v2"]["TurnInterruptResponse"]
    else:
        definitions["v2"]["TurnInterruptParams"]["properties"]["x"] = {
            "$ref": "#/definitions/v2/Missing"}
    with pytest.raises(used.SchemaDrift):
        used.used_schema_digests(schema)


# --- launcher and host ----------------------------------------------------

def _reviewed_manifest(tmp_path, schema, version="0.171.0"):
    total, entries = used.used_schema_digests(schema)
    value = json.loads((FIXTURES / version / "manifest.json").read_text())
    value.update(used_schema_sha256=total, used_schema_entries=entries)
    path = tmp_path / f"manifest-{version}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def _fake_codex(tmp_path, version, schema):
    combined = (json.dumps(schema, sort_keys=True) + "\n").encode()
    v2 = (json.dumps({"release": version}, sort_keys=True) + "\n").encode()
    script = tmp_path / f"codex-{version}"
    script.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        f"    print('codex-cli {version}')\n"
        "elif sys.argv[1:3] == ['app-server', 'generate-json-schema']:\n"
        "    out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        f"    (out / 'codex_app_server_protocol.v2.schemas.json').write_bytes({v2!r})\n"
        f"    (out / {used.COMBINED_SCHEMA_FILE!r}).write_bytes({combined!r})\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8")
    script.chmod(0o700)
    return script, hashlib.sha256(v2).hexdigest()


def test_unreviewed_version_selects_the_newest_reviewed_contract(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        fleet_codex.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="codex-cli 9.9.9\n"))
    path, version = fleet_codex._reviewed_schema_selection(
        ["codex"], env={}, cwd=tmp_path)
    assert version == "9.9.9"
    assert path == fleet_codex.REVIEWED_SCHEMA_MANIFESTS["0.171.0"]


@pytest.mark.skipif(os.name == "nt", reason="native host transport is POSIX-only")
def test_new_version_with_unchanged_used_shapes_launches(tmp_path, monkeypatch):
    schema = fake_combined_schema()
    manifest, _ = _reviewed_manifest(tmp_path, schema)
    monkeypatch.setitem(fleet_codex.REVIEWED_SCHEMA_MANIFESTS, "0.171.0", manifest)
    newer = copy.deepcopy(schema)
    newer["definitions"]["v2"]["BrandNew"] = {"type": "string"}
    codex, full_digest = _fake_codex(tmp_path, "9.9.9", newer)
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    client = fleet_codex.CodexHostClient.ensure(
        home, app_server_command=[str(_fake_app_server(tmp_path, "9.9.9"))],
        schema_command=[str(codex)],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
        ready_timeout=5, idle_timeout=30)
    try:
        metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
        assert metadata["codex_version"] == "9.9.9"
        assert metadata["schema_digest"] == full_digest
        assert metadata["used_schema_digest"] == used.used_schema_digests(newer)[0]
        attached = fleet_codex.CodexHostClient._existing(home)
        assert attached is not None and attached.codex_version == "9.9.9"
    finally:
        _shutdown(client)


@pytest.mark.skipif(os.name == "nt", reason="native host transport is POSIX-only")
def test_new_version_with_a_changed_used_shape_is_refused(tmp_path, monkeypatch):
    schema = fake_combined_schema()
    manifest, _ = _reviewed_manifest(tmp_path, schema)
    monkeypatch.setitem(fleet_codex.REVIEWED_SCHEMA_MANIFESTS, "0.171.0", manifest)
    newer = copy.deepcopy(schema)
    newer["definitions"]["v2"]["TurnSteerParams"]["required"] = ["threadId"]
    codex, _ = _fake_codex(tmp_path, "9.9.9", newer)
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    with pytest.raises(fleet_codex.HostUnavailable):
        fleet_codex.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path, "9.9.9"))],
            schema_command=[str(codex)],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
            ready_timeout=3, idle_timeout=30)
    assert not log.exists()
    assert not (home / "state" / "codex" / "host.json").exists()


def _published(home, **changes):
    path = home / "state" / "codex" / "host.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="native host transport is POSIX-only")
@pytest.mark.parametrize("changes", [
    {"used_schema_digest": "0" * 64},
    {"used_schema_digest": None},
    {"codex_version": ""},
])
def test_attach_refuses_metadata_without_a_reviewed_contract(
        tmp_path, monkeypatch, changes):
    schema = fake_combined_schema()
    manifest, _ = _reviewed_manifest(tmp_path, schema)
    monkeypatch.setitem(fleet_codex.REVIEWED_SCHEMA_MANIFESTS, "0.171.0", manifest)
    codex, _ = _fake_codex(tmp_path, "9.9.9", schema)
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    client = fleet_codex.CodexHostClient.ensure(
        home, app_server_command=[str(_fake_app_server(tmp_path, "9.9.9"))],
        schema_command=[str(codex)],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
        ready_timeout=5, idle_timeout=30)
    try:
        _published(home, **changes)
        with pytest.raises(fleet_codex.UnsafeHostState):
            fleet_codex.CodexHostClient._existing(home)
    finally:
        _shutdown(client)


@pytest.mark.parametrize("envelope", ["ClientRequest", "ClientNotification",
                                      "ServerRequest", "ServerNotification"])
def test_an_envelope_constraint_changes_the_used_digest(envelope):
    """A container constraint applies to every used variant inside it."""
    base = fake_combined_schema()
    changed = copy.deepcopy(base)
    changed["definitions"][envelope]["additionalProperties"] = False
    assert used.used_schema_digests(changed)[0] != used.used_schema_digests(base)[0]


def test_a_new_unused_variant_in_an_envelope_keeps_the_used_digest():
    base = fake_combined_schema()
    changed = copy.deepcopy(base)
    changed["definitions"]["ServerNotification"]["oneOf"].append({
        "properties": {"method": {"enum": ["brand/new"]}}, "type": "object"})
    assert used.used_schema_digests(changed) == used.used_schema_digests(base)


@pytest.mark.skipif(os.name == "nt", reason="native host transport is POSIX-only")
@pytest.mark.parametrize("combined_ok", [True, False])
def test_exact_version_and_v2_digest_still_compare_used_shapes(
        tmp_path, monkeypatch, combined_ok):
    """The combined schema carries used v1 shapes the v2 digest never sees."""
    schema = fake_combined_schema()
    installed = schema if combined_ok else {"definitions": {}}
    codex, v2_digest = _fake_codex(tmp_path, "0.171.0", installed)
    manifest, value = _reviewed_manifest(tmp_path, schema)
    value["schema_sha256"] = v2_digest
    manifest.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setitem(fleet_codex.REVIEWED_SCHEMA_MANIFESTS, "0.171.0", manifest)
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    kwargs = dict(app_server_command=[str(_fake_app_server(tmp_path, "0.171.0"))],
                  schema_command=[str(codex)],
                  env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
                  idle_timeout=30)
    if not combined_ok:
        with pytest.raises(fleet_codex.HostUnavailable):
            fleet_codex.CodexHostClient.ensure(home, ready_timeout=3, **kwargs)
        assert not log.exists()
        assert not (home / "state" / "codex" / "host.json").exists()
        return
    client = fleet_codex.CodexHostClient.ensure(home, ready_timeout=5, **kwargs)
    try:
        metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
        assert metadata["schema_digest"] == v2_digest
        # An exact host compared used shapes but stays bound to its reviewed
        # version and raw digest, so it publishes no used-schema digest.
        assert metadata["used_schema_digest"] is None
    finally:
        _shutdown(client)


@pytest.mark.parametrize("branch", [
    {"properties": {"method": {"enum": ["turn/start", "brand/new"]}},
     "type": "object"},
    {"properties": {"method": {"const": "turn/start"}}, "type": "object"},
    {"properties": {"method": {"type": "string"}}, "type": "object"},
    {"properties": {"method": {"$ref": "#/definitions/v2/AnyMethod"}},
     "type": "object"},
    {"$ref": "#/definitions/v2/UnusedParams"},
])
def test_a_branch_that_may_also_match_a_used_method_changes_its_digest(branch):
    """`oneOf` rejects a request two branches accept: overlap is a shape change."""
    base = fake_combined_schema()
    base["definitions"]["v2"]["AnyMethod"] = {"type": "string"}
    changed = copy.deepcopy(base)
    changed["definitions"]["ClientRequest"]["oneOf"].append(branch)
    _, before = used.used_schema_digests(base)
    try:
        _, after = used.used_schema_digests(changed)
    except used.SchemaDrift:
        return  # a second exact branch is ambiguous and refuses outright
    assert before["ClientRequest turn/start"] != after["ClientRequest turn/start"]


def test_a_branch_that_provably_rejects_used_methods_keeps_their_digests():
    base = fake_combined_schema()
    changed = copy.deepcopy(base)
    changed["definitions"]["ClientRequest"]["oneOf"].append({
        "properties": {"method": {"enum": ["brand/new", "other/new"]}},
        "type": "object"})
    assert used.used_schema_digests(changed) == used.used_schema_digests(base)


@pytest.mark.skipif(os.name == "nt", reason="native host transport is POSIX-only")
def test_exact_release_without_a_used_contract_is_refused(tmp_path, monkeypatch):
    """A reviewed manifest must carry a used contract; no exact-path bypass."""
    codex, v2_digest = _fake_codex(tmp_path, "0.171.0", {"definitions": {}})
    manifest, value = _reviewed_manifest(tmp_path, fake_combined_schema())
    value["schema_sha256"] = v2_digest
    del value["used_schema_sha256"], value["used_schema_entries"]
    manifest.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setitem(fleet_codex.REVIEWED_SCHEMA_MANIFESTS, "0.171.0", manifest)
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    with pytest.raises(fleet_codex.HostUnavailable):
        fleet_codex.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path, "0.171.0"))],
            schema_command=[str(codex)],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
            ready_timeout=3, idle_timeout=30)
    assert not log.exists()
    assert not (home / "state" / "codex" / "host.json").exists()
