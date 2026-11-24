"""Test-only command adaptation for the hermetic Codex fixture."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


def hermetic_codex_argv(
    argv: Sequence[str], root: Path, *, platform: str | None = None,
    comspec: str | None = None,
) -> list[str]:
    """Return an argv that can launch the fixture with ``shell=False``.

    ``CreateProcess`` does not apply ``PATHEXT`` to a bare command, so a
    ``codex.cmd`` shim is not a valid target for Windows' shell-disabled
    subprocess path.  Route only the fixture's Codex command through the
    system command interpreter there.  POSIX names the fixture executable
    explicitly too, preserving its direct ``shell=False`` execution while
    removing PATH from the test's trust boundary.
    """
    command = list(argv)
    if not command:
        return command
    name = Path(command[0]).name.lower()
    if name not in {"codex", "codex.cmd"}:
        return command
    if (platform or os.name) != "nt":
        return [str(root / "codex"), *command[1:]]
    return [
        comspec or os.environ.get("COMSPEC") or "cmd.exe",
        "/d", "/c", str(root / "codex.cmd"), *command[1:],
    ]


def fake_combined_schema():
    """A minimal combined Codex schema with every used call and one unused call."""
    import fleet_codex_schema as used

    definitions = {"v2": {}, "RequestId": {"type": ["string", "integer"]}}
    envelopes = {name: {"oneOf": []} for name in (
        "ClientRequest", "ClientNotification", "ServerRequest",
        "ServerNotification")}
    for (envelope, method), response in used.USED_SCHEMA_INVENTORY.items():
        stem = "".join(part[:1].upper() + part[1:]
                       for part in method.replace("/", " ").split())
        definitions["v2"][f"{stem}Params"] = {
            "description": f"Params for {method}.",
            "properties": {"threadId": {"type": "string"},
                           "description": {"type": "string"}},
            "type": "object"}
        envelopes[envelope]["oneOf"].append({
            "properties": {
                "id": {"$ref": "#/definitions/RequestId"},
                "method": {"enum": [method]},
                "params": {"$ref": f"#/definitions/v2/{stem}Params"}},
            "required": ["id", "method", "params"], "type": "object"})
        if response is not None:
            parts = response.split("/")[2:]
            node = definitions
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = {
                "properties": {"status": {"$ref": "#/definitions/v2/Status"}},
                "type": "object"}
    definitions["v2"]["Status"] = {"enum": ["completed", "failed"]}
    definitions["v2"]["UnusedParams"] = {"type": "object"}
    envelopes["ClientRequest"]["oneOf"].append({
        "properties": {"method": {"enum": ["unused/method"]},
                       "params": {"$ref": "#/definitions/v2/UnusedParams"}},
        "type": "object"})
    definitions.update(envelopes)
    return {"$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": definitions, "title": "CodexAppServerProtocol"}
