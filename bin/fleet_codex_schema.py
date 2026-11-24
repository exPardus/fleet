"""Compare only the Codex app-server schema shapes that Fleet uses.

Codex releases change unrelated parts of the generated schema often. The
launch gate compares the schema closure of every method and notification the
adapter sends or consumes. A new Codex version launches when that closure
matches a reviewed release. Any difference in a used shape, a missing used
method, or an unreadable schema refuses launch.

`USED_SCHEMA_INVENTORY` is the reviewed list of used calls. A test derives the
Codex method names from the adapter source and requires them to equal this
list, so an unlisted call fails the gate instead of passing it unchecked.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

# Codex writes every namespace into this one file, including the v1 server
# requests and initialize response that the v2-only file omits.
COMBINED_SCHEMA_FILE = "codex_app_server_protocol.schemas.json"
MAX_COMBINED_SCHEMA_BYTES = 16 * 1024 * 1024

# (envelope definition, method) -> response definition pointer or None.
# A notification has no response. Keep this list equal to the adapter calls.
USED_SCHEMA_INVENTORY: dict[tuple[str, str], str | None] = {
    ("ClientRequest", "initialize"): "#/definitions/InitializeResponse",
    ("ClientRequest", "thread/start"): "#/definitions/v2/ThreadStartResponse",
    ("ClientRequest", "thread/resume"): "#/definitions/v2/ThreadResumeResponse",
    ("ClientRequest", "thread/read"): "#/definitions/v2/ThreadReadResponse",
    ("ClientRequest", "thread/list"): "#/definitions/v2/ThreadListResponse",
    ("ClientRequest", "thread/turns/list"):
        "#/definitions/v2/ThreadTurnsListResponse",
    ("ClientRequest", "thread/items/list"):
        "#/definitions/v2/ThreadItemsListResponse",
    ("ClientRequest", "thread/loaded/list"):
        "#/definitions/v2/ThreadLoadedListResponse",
    ("ClientRequest", "turn/start"): "#/definitions/v2/TurnStartResponse",
    ("ClientRequest", "turn/steer"): "#/definitions/v2/TurnSteerResponse",
    ("ClientRequest", "turn/interrupt"):
        "#/definitions/v2/TurnInterruptResponse",
    ("ClientRequest", "configRequirements/read"):
        "#/definitions/v2/ConfigRequirementsReadResponse",
    ("ClientRequest", "account/rateLimits/read"):
        "#/definitions/v2/GetAccountRateLimitsResponse",
    ("ClientNotification", "initialized"): None,
    ("ServerRequest", "item/commandExecution/requestApproval"):
        "#/definitions/CommandExecutionRequestApprovalResponse",
    ("ServerRequest", "item/fileChange/requestApproval"):
        "#/definitions/FileChangeRequestApprovalResponse",
    ("ServerRequest", "item/tool/requestUserInput"):
        "#/definitions/ToolRequestUserInputResponse",
    ("ServerRequest", "mcpServer/elicitation/request"):
        "#/definitions/McpServerElicitationRequestResponse",
    ("ServerRequest", "item/permissions/requestApproval"):
        "#/definitions/PermissionsRequestApprovalResponse",
    ("ServerNotification", "turn/completed"): None,
    ("ServerNotification", "thread/tokenUsage/updated"): None,
    ("ServerNotification", "item/completed"): None,
    ("ServerNotification", "serverRequest/resolved"): None,
}

USED_METHODS = frozenset(method for _, method in USED_SCHEMA_INVENTORY)

# Prose keys do not change a wire shape. Strip them only in schema position,
# never where they name a property or a definition.
_PROSE_KEYS = frozenset({"description", "title", "$schema"})
_NAME_MAPS = frozenset({"properties", "definitions", "patternProperties"})


class SchemaDrift(ValueError):
    """The installed schema cannot be compared, or a used shape differs."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _strip_prose(node: Any, names: bool = False) -> Any:
    if isinstance(node, dict):
        if names:
            return {key: _strip_prose(value) for key, value in node.items()}
        return {key: _strip_prose(value, key in _NAME_MAPS)
                for key, value in node.items()
                if not (key in _PROSE_KEYS and isinstance(value, str))}
    if isinstance(node, list):
        return [_strip_prose(item) for item in node]
    return node


def _resolve(document: Mapping[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        raise SchemaDrift(f"unsupported schema reference {pointer!r}")
    node: Any = document
    for raw in pointer[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaDrift(f"schema reference {pointer!r} does not resolve")
        node = node[part]
    return node


def _refs(node: Any):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def _variant(document: Mapping[str, Any], envelope: str, method: str) -> Any:
    container = _resolve(document, f"#/definitions/{envelope}")
    found = []
    for entry in container.get("oneOf", []) if isinstance(container, dict) else []:
        enum = (entry.get("properties", {}).get("method", {}).get("enum")
                if isinstance(entry, dict) else None)
        if enum == [method]:
            found.append(entry)
    if len(found) != 1:
        raise SchemaDrift(f"{envelope} {method} is missing or ambiguous")
    return found[0]


def _entry_slice(document: Mapping[str, Any], envelope: str, method: str,
                 response: str | None) -> dict[str, Any]:
    container = _resolve(document, f"#/definitions/{envelope}")
    # The container's own constraints (for example additionalProperties)
    # apply to every variant. Its variant list is left out, so a new unused
    # method does not change a used digest.
    frame = {key: value for key, value in container.items() if key != "oneOf"}
    roots = {"envelope": frame,
             "variant": _variant(document, envelope, method)}
    if response is not None:
        roots["response"] = _resolve(document, response)
    definitions: dict[str, Any] = {}
    pending = list(_refs(roots))
    while pending:
        pointer = pending.pop()
        if pointer in definitions:
            continue
        definitions[pointer] = _resolve(document, pointer)
        pending.extend(_refs(definitions[pointer]))
    return _strip_prose({**roots, "definitions": definitions})


def used_schema_digests(document: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """Return the total used-shape digest and one digest per used call."""
    if not isinstance(document, dict):
        raise SchemaDrift("Codex schema must be a JSON object")
    entries: dict[str, str] = {}
    for (envelope, method), response in sorted(USED_SCHEMA_INVENTORY.items()):
        piece = _entry_slice(document, envelope, method, response)
        entries[f"{envelope} {method}"] = hashlib.sha256(
            _canonical(piece)).hexdigest()
    return hashlib.sha256(_canonical(entries)).hexdigest(), entries


def read_combined_schema(directory: Path) -> dict[str, Any]:
    """Read the generated combined schema with a size bound."""
    path = Path(directory) / COMBINED_SCHEMA_FILE
    try:
        if path.stat().st_size > MAX_COMBINED_SCHEMA_BYTES:
            raise SchemaDrift("installed Codex combined schema exceeds size bound")
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchemaDrift("installed Codex combined schema is unreadable") from exc
    if not isinstance(value, dict):
        raise SchemaDrift("installed Codex combined schema is not an object")
    return value


def reviewed_used_schemas(manifests: Mapping[str, Path]) -> dict[str, dict]:
    """Map each reviewed used-shape digest to its manifest."""
    reviewed: dict[str, dict] = {}
    for path in manifests.values():
        try:
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        digest = manifest.get("used_schema_sha256") if isinstance(
            manifest, dict) else None
        if isinstance(digest, str) and len(digest) == 64:
            reviewed.setdefault(digest, manifest)
    return reviewed


def drifted_calls(actual: Mapping[str, str],
                  reviewed: Mapping[str, Any]) -> list[str]:
    """Name used calls whose shape differs from one reviewed manifest."""
    expected = reviewed.get("used_schema_entries")
    if not isinstance(expected, dict):
        return sorted(actual)
    return sorted(name for name in set(actual) | set(expected)
                  if actual.get(name) != expected.get(name))


def match_reviewed(document: Mapping[str, Any],
                   manifests: Mapping[str, Path]) -> tuple[str, dict]:
    """Return the used-shape digest and the reviewed manifest it matches.

    Raise SchemaDrift that names the differing calls when nothing matches.
    """
    digest, entries = used_schema_digests(document)
    reviewed = reviewed_used_schemas(manifests)
    if digest in reviewed:
        return digest, reviewed[digest]
    if not reviewed:
        raise SchemaDrift("no reviewed Codex used-schema contract is available")
    newest = max(reviewed.values(), key=lambda item: tuple(
        int(part) if part.isdigit() else 0
        for part in str(item.get("codex_version", "")).split(".")))
    changed = drifted_calls(entries, newest)
    raise SchemaDrift(
        "installed Codex schema differs from every reviewed contract in "
        f"used calls (vs {newest.get('codex_version')}): "
        + ", ".join(changed[:8]) + (" ..." if len(changed) > 8 else ""))
