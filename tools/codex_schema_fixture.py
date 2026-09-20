#!/usr/bin/env python3
"""Extract Fleet's reviewed contract from Codex's public v2 JSON Schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_SCHEMA_BYTES = 8 * 1024 * 1024
SCHEMA_FILE = "codex_app_server_protocol.v2.schemas.json"
SELECTED_METHODS = (
    "initialize",
    "thread/start",
    "thread/read",
    "thread/list",
    "thread/resume",
    "thread/turns/list",
    "thread/items/list",
    "turn/start",
    "turn/steer",
    "turn/interrupt",
    "configRequirements/read",
    "account/usage/read",
    "account/rateLimits/read",
)
SELECTED_SERVER_NOTIFICATIONS = (
    "thread/status/changed",
    "thread/tokenUsage/updated",
    "turn/started",
    "turn/completed",
    "item/completed",
    "account/rateLimits/updated",
)


@dataclass(frozen=True)
class ContractManifest:
    codex_version: str
    protocol_version: int
    schema_sha256: str
    contract_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "codex_version": self.codex_version,
            "contract_sha256": self.contract_sha256,
            "protocol_version": self.protocol_version,
            "schema_file": SCHEMA_FILE,
            "schema_sha256": self.schema_sha256,
        }


def _read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    size = path.stat().st_size
    if size > MAX_SCHEMA_BYTES:
        raise ValueError(f"public schema {path.name} exceeds {MAX_SCHEMA_BYTES} bytes")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in public schema {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"public schema {path.name} must be a JSON object")
    return raw, value


def _method_variants(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}
    for entry in document.get("oneOf", []):
        if not isinstance(entry, dict):
            continue
        method = entry.get("properties", {}).get("method", {}).get("enum", [])
        if isinstance(method, list) and len(method) == 1 and isinstance(method[0], str):
            variants[method[0]] = entry
    return variants


def _ref_name(schema: object) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    prefix = "#/definitions/"
    if isinstance(ref, str) and ref.startswith(prefix):
        return ref[len(prefix):]
    return None


def _required_params(variant: dict[str, Any], definitions: dict[str, Any]) -> list[str]:
    params = variant.get("properties", {}).get("params", {})
    name = _ref_name(params)
    if name is None:
        return []
    definition = definitions.get(name)
    if not isinstance(definition, dict):
        raise ValueError(f"missing params definition {name}")
    required = definition.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(f"invalid required fields for {name}")
    return sorted(required)


def _enum(definitions: dict[str, Any], name: str) -> list[str]:
    value = definitions.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"missing public definition {name}")
    result: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            enum = node.get("enum")
            if isinstance(enum, list):
                result.update(item for item in enum if isinstance(item, str))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    if not result:
        raise ValueError(f"public definition {name} has no string enum")
    return sorted(result)


def _codex_errors(definitions: dict[str, Any]) -> list[str]:
    value = definitions.get("CodexErrorInfo")
    if not isinstance(value, dict):
        raise ValueError("missing public definition CodexErrorInfo")
    result = set(_enum(definitions, "CodexErrorInfo"))
    for entry in value.get("oneOf", []):
        if not isinstance(entry, dict):
            continue
        required = entry.get("required", [])
        if isinstance(required, list):
            result.update(item for item in required if isinstance(item, str))
    return sorted(result)


def _extract_contract(bundle: Path) -> tuple[bytes, dict[str, Any]]:
    raw_schema, full = _read_json(bundle / SCHEMA_FILE)
    _, client_requests = _read_json(bundle / "ClientRequest.json")
    _, client_notifications = _read_json(bundle / "ClientNotification.json")
    _, server_notifications = _read_json(bundle / "ServerNotification.json")

    definitions = full.get("definitions")
    request_definitions = client_requests.get("definitions")
    if not isinstance(definitions, dict) or not isinstance(request_definitions, dict):
        raise ValueError("public v2 schema has no definitions object")

    request_variants = _method_variants(client_requests)
    # Some releases omit account methods in reduced test fixtures. Runtime
    # acceptance requires them, but extraction still reports every available
    # reviewed method so a fixture test can identify the drift precisely.
    required_core = set(SELECTED_METHODS) - {"account/usage/read", "account/rateLimits/read"}
    core_missing = sorted(required_core - set(request_variants))
    if core_missing:
        raise ValueError(f"public v2 schema missing required methods: {', '.join(core_missing)}")

    methods: dict[str, Any] = {}
    for method in SELECTED_METHODS:
        variant = request_variants.get(method)
        if variant is None:
            continue
        methods[method] = {
            "params_required": _required_params(variant, request_definitions),
            "request_required": sorted(variant.get("required", [])),
        }

    client_note_names = sorted(_method_variants(client_notifications))
    if "initialized" not in client_note_names:
        raise ValueError("public v2 schema missing initialized notification")
    server_note_names = sorted(
        set(_method_variants(server_notifications)).intersection(SELECTED_SERVER_NOTIFICATIONS))

    start_response = definitions.get("ThreadStartResponse")
    if not isinstance(start_response, dict):
        raise ValueError("missing public definition ThreadStartResponse")
    start_fields = start_response.get("properties")
    if not isinstance(start_fields, dict):
        raise ValueError("ThreadStartResponse has no properties")
    effective = [
        name for name in
        ("thread", "cwd", "model", "approvalPolicy", "approvalsReviewer", "sandbox")
        if name in start_fields
    ]
    if len(effective) != 6:
        raise ValueError("ThreadStartResponse lacks effective identity/permission fields")

    contract = {
        "client_methods": methods,
        "client_notifications": ["initialized"],
        "enums": {
            "approval_policy": _enum(definitions, "AskForApproval"),
            "approvals_reviewer": _enum(definitions, "ApprovalsReviewer"),
            "codex_error_codes": _codex_errors(definitions),
            "sandbox_mode": _enum(definitions, "SandboxMode"),
            "thread_active_flags": _enum(definitions, "ThreadActiveFlag"),
            "thread_status": _enum(definitions, "ThreadStatus"),
            "turn_status": _enum(definitions, "TurnStatus"),
        },
        "protocol_version": 2,
        "server_notifications": server_note_names,
        "thread_start_effective_fields": effective,
    }
    return raw_schema, contract


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def generate_contract(codex: str, destination: Path) -> ContractManifest:
    """Generate a deterministic bounded Fleet contract from public Codex schema."""
    destination = Path(destination)
    version_proc = subprocess.run(
        [codex, "--version"], capture_output=True, text=True, timeout=10, check=False)
    if version_proc.returncode != 0:
        raise RuntimeError(f"codex --version failed ({version_proc.returncode})")
    match = re.fullmatch(r"codex-cli\s+([^\s]+)\s*", version_proc.stdout)
    if match is None:
        raise ValueError("could not parse codex --version output")
    version = match.group(1)

    with tempfile.TemporaryDirectory(prefix="fleet-codex-schema-") as temp:
        bundle = Path(temp)
        proc = subprocess.run(
            [codex, "app-server", "generate-json-schema", "--out", str(bundle)],
            capture_output=True, timeout=60, check=False)
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Codex schema generation failed ({proc.returncode}): {detail}")
        raw_schema, contract = _extract_contract(bundle)

    contract_bytes = _json_bytes(contract)
    manifest = ContractManifest(
        codex_version=version,
        protocol_version=2,
        schema_sha256=hashlib.sha256(raw_schema).hexdigest(),
        contract_sha256=hashlib.sha256(contract_bytes).hexdigest(),
    )
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in (("v2-contract.json", contract_bytes),
                       ("manifest.json", _json_bytes(manifest.as_dict()))):
        temporary = destination / f".{name}.{os.getpid()}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, destination / name)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", default="codex")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    manifest = generate_contract(args.codex, args.destination)
    print(json.dumps(manifest.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
