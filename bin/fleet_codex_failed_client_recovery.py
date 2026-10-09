"""Staged, fail-closed recovery of one failed-client Codex home.

Only the explicit Interface CLI drives this module.  Importing it has no side
 effects.  The old host cannot load the new barrier; every old-host action is
 separately guarded by exact evidence and a post-action comparison.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from fleet_codex import (
    CodexHostClient, OperationJournal, _atomic_json,
    _digest, _process_identity, _process_identities_match,
    failed_client_recovery_barrier,
)
from fleet_errors import FleetCliError

BARRIER = "failed-client-recovery.json"
LOSS_TEXT = (
    "I accept interruption of possibly active turns, undrained callbacks, "
    "and in-flight tool or external side effects whose outcome may remain unknown"
)
_STAGES = {"prepared", "authorized", "shutdown_sent", "shutdown_ack",
           "exited", "boot_requested", "rebind", "complete"}


def _sha(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise FleetCliError(f"recovery evidence has unsafe type or owner: {path}")
    if info.st_size > 4 * 1024 * 1024:
        raise FleetCliError(f"recovery evidence exceeds file bound: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_digest(path: Path, *, prefixes: tuple[str, ...] | None = None,
                      excluded: tuple[str, ...] = ()) -> str:
    if not path.exists():
        return _sha([])
    if path.is_symlink() or not path.is_dir():
        raise FleetCliError(f"recovery evidence directory is unsafe: {path}")
    rows = []
    for child in sorted(path.iterdir(), key=lambda p: p.name):
        if prefixes is not None and not child.name.startswith(prefixes):
            continue
        if child.name in excluded:
            continue
        rows.append((child.name, _file_sha(child)))
    return _sha(rows)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args],
                            stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=10, check=False)
    if result.returncode != 0:
        raise FleetCliError(f"cannot verify recovery worktree {cwd}")
    return result.stdout.strip()


def _source_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parent.parent
    head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise FleetCliError("recovery CLI checkout has tracked drift")
    files = ("bin/fleet.py", "bin/fleet_codex.py", "bin/fleet_codex_host.py",
             "bin/fleet_codex_failed_client_recovery.py")
    return {"head": head, "files": {name: _file_sha(root / name) for name in files}}


def _codex_executable_identity(value: str, expected_version: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise FleetCliError("recovery needs an absolute pinned Codex executable")
    path = Path(value)
    try:
        info = path.lstat()
    except OSError as exc:
        raise FleetCliError("pinned Codex executable is unavailable") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.getuid()}
            or info.st_mode & 0o022 or not info.st_mode & 0o111
            or info.st_size > 512 * 1024 * 1024):
        raise FleetCliError("pinned Codex executable has unsafe identity")
    try:
        result = subprocess.run([str(path), "--version"],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FleetCliError("pinned Codex executable version is unavailable") from exc
    if result.returncode != 0 or result.stdout.strip() != f"codex-cli {expected_version}":
        raise FleetCliError("pinned Codex executable version differs from old host")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    after = path.lstat()
    signature = lambda item: (item.st_dev, item.st_ino, item.st_size,
                              item.st_mtime_ns, item.st_ctime_ns)
    if signature(info) != signature(after):
        raise FleetCliError("pinned Codex executable changed during inspection")
    return {"path": str(path), "sha256": digest.hexdigest(),
            "dev": info.st_dev, "ino": info.st_ino, "size": info.st_size,
            "version": expected_version}


def _committed_original_journals(home: Path, generation: str) -> dict[str, int]:
    """Prove startup reconciliation cannot rewrite the original inventory."""
    directory = home / "state" / "codex" / "operations"
    if directory.is_symlink() or not directory.is_dir():
        raise FleetCliError("original operation journal directory is unsafe")
    count = 0
    old_count = 0
    for path in sorted(directory.iterdir()):
        if path.suffix != ".json":
            raise FleetCliError("original operation journal has unknown entry")
        _file_sha(path)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FleetCliError("original operation journal is unreadable") from exc
        if (not isinstance(entry, dict) or entry.get("state") != "committed"
                or entry.get("home") != str(home)
                or entry.get("operation_id") != path.stem):
            raise FleetCliError("original operation journal is unresolved or malformed")
        count += 1
        old_count += entry.get("generation") == generation
    if old_count == 0:
        raise FleetCliError("no original-generation committed operations")
    return {"all_committed": count, "original_generation": old_count}


def _approval_inventory(home: Path, generation: str) -> dict[str, Any]:
    """Classify recorded callbacks; an unresolved one needs separate settlement."""
    directory = home / "state" / "codex" / "approvals"
    if not directory.exists() and not directory.is_symlink():
        return {"count": 0, "old_generation_unresolved": []}
    if directory.is_symlink() or not directory.is_dir():
        raise FleetCliError("approval evidence directory is unsafe")
    unresolved = {"pending", "responding", "responded", "uncertain", "unknown"}
    found = []
    count = 0
    for path in sorted(directory.iterdir()):
        if path.suffix != ".json":
            raise FleetCliError("approval evidence has unknown entry")
        _file_sha(path)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FleetCliError("approval evidence is unreadable") from exc
        if (not isinstance(entry, dict) or entry.get("home") != str(home)
                or entry.get("key") != path.stem
                or entry.get("state") not in unresolved | {"resolved"}):
            raise FleetCliError("approval evidence identity/state is malformed")
        count += 1
        if entry.get("generation") == generation and entry["state"] in unresolved:
            found.append(path.stem)
    return {"count": count, "old_generation_unresolved": found}


def _row_policy(fleet, row: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Use exactly the recorded effective policy, constrained by Fleet mode."""
    model = fleet._codex_model_slug(row.get("model"))
    mode_profile = fleet._codex_permission_profile(row.get("mode"))
    effective = row.get("permission_effective")
    if not model or not isinstance(effective, dict):
        raise FleetCliError("recorded model or effective policy is missing")
    if set(effective) != {"approvalPolicy", "approvalsReviewer", "sandbox"}:
        raise FleetCliError("recorded effective policy has unknown fields")
    sandbox = effective.get("sandbox")
    reverse = {"dangerFullAccess": "danger-full-access",
               "workspaceWrite": "workspace-write", "readOnly": "read-only"}
    sandbox_name = reverse.get(sandbox.get("type")) if isinstance(sandbox, dict) else None
    if sandbox_name == "workspace-write":
        allowed = {"type", "writableRoots", "networkAccess",
                   "excludeTmpdirEnvVar", "excludeSlashTmp"}
        valid_sandbox = (set(sandbox).issubset(allowed)
                         and ("writableRoots" not in sandbox
                              or (isinstance(sandbox["writableRoots"], list)
                                  and all(isinstance(root, str) for root in
                                          sandbox["writableRoots"])))
                         and all(isinstance(sandbox[key], bool) for key in
                                 allowed - {"type", "writableRoots"}
                                 if key in sandbox))
    elif sandbox_name == "read-only":
        valid_sandbox = (set(sandbox).issubset({"type", "networkAccess"})
                         and ("networkAccess" not in sandbox
                              or isinstance(sandbox["networkAccess"], bool)))
    else:
        valid_sandbox = isinstance(sandbox, dict) and set(sandbox) == {"type"}
    approval = effective.get("approvalPolicy")
    if (effective.get("approvalsReviewer") != "user"
            or approval not in {"never", "on-request", "untrusted"}
            or sandbox_name is None or not valid_sandbox
            or (mode_profile["approvalPolicy"] is not None
                and mode_profile["approvalPolicy"] != approval)
            or (mode_profile["sandbox"] is not None
                and mode_profile["sandbox"] != sandbox_name)):
        raise FleetCliError("recorded effective policy differs from Fleet mode")
    return model, {"approvalPolicy": approval, "sandbox": sandbox_name}


def _resume_policy_config(row: dict[str, Any]) -> dict[str, Any] | None:
    """Encode only policy fields the pinned 0.155.1 resume request can set."""
    sandbox = row["permission_effective"]["sandbox"]
    if sandbox["type"] == "readOnly":
        # The pinned resume request has a sandbox mode, but no read-only
        # network override. The reviewed schema's mode default is false.
        if sandbox.get("networkAccess", False) is True:
            raise FleetCliError(
                "recorded read-only network access cannot be restored by pinned resume")
        return None
    if sandbox["type"] != "workspaceWrite":
        return None
    required = {"type", "writableRoots", "networkAccess",
                "excludeTmpdirEnvVar", "excludeSlashTmp"}
    if set(sandbox) != required:
        raise FleetCliError("recorded workspace policy lacks explicit resume fields")
    roots = sandbox["writableRoots"]
    if (any(not isinstance(root, str) or not Path(root).is_absolute()
            for root in roots) or len(set(roots)) != len(roots)):
        raise FleetCliError("recorded workspace roots are not exact absolute paths")
    return {"sandbox_workspace_write": {
        "writable_roots": roots,
        "network_access": sandbox["networkAccess"],
        "exclude_tmpdir_env_var": sandbox["excludeTmpdirEnvVar"],
        "exclude_slash_tmp": sandbox["excludeSlashTmp"],
    }}


def _require_recorded_effective(result: dict[str, Any], row: dict[str, Any]) -> None:
    observed = {key: result.get(key) for key in (
        "approvalPolicy", "approvalsReviewer", "sandbox")}
    if observed != row.get("permission_effective"):
        raise FleetCliError("resume differs from exact recorded effective policy")


def _descendants(pid: int) -> dict[str, str]:
    """Inventory known Linux descendants without reading argv or private data."""
    proc = Path("/proc")
    if not proc.is_dir():
        raise FleetCliError("failed-client recovery requires reviewed Linux /proc")
    parents: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / "stat").read_text()
            rest = raw.rsplit(") ", 1)[1].split()
            parents[int(entry.name)] = int(rest[1])
        except (OSError, IndexError, ValueError):
            continue
    found: dict[str, str] = {}
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        for child, ppid in parents.items():
            if ppid == parent and str(child) not in found:
                identity = _process_identity(child)
                if identity is None:
                    raise FleetCliError("descendant identity is unavailable")
                found[str(child)] = identity
                frontier.append(child)
    return found


def _process_state(pid: int, identity: str) -> str:
    current = _process_identity(pid)
    if current is not None:
        match = _process_identities_match(identity, current)
        if match is True:
            return "live"
        return "reused" if match is False else "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "absent"
    except (PermissionError, OSError):
        return "unknown"
    return "unknown"


def _snapshot(fleet, generation: str, *, names: list[str] | None = None,
              resume_operations: dict[str, str] | None = None) -> dict[str, Any]:
    home = fleet.FLEET_HOME.resolve()
    claim = fleet.read_incarnation()
    registry = fleet.read_registry_no_repair()
    workers = registry.get("workers") if isinstance(registry, dict) else None
    if not isinstance(claim, dict) or not isinstance(workers, dict):
        raise FleetCliError("recovery claim or registry is malformed")
    current_generation_names = {name for name, row in workers.items()
                                if isinstance(row, dict)
                                and row.get("codex_host_generation") == generation}
    if names is not None and not current_generation_names.issubset(set(names)):
        raise FleetCliError("new row appeared on original host generation")
    affected = {name: workers.get(name) for name in
                (current_generation_names if names is None else names)}
    if any(not isinstance(row, dict) for row in affected.values()):
        raise FleetCliError("affected recovery row was removed or malformed")
    if not affected:
        raise FleetCliError("recovery host generation has no registry rows")
    supervisor = [(name, row) for name, row in affected.items()
                  if row.get("codex_thread_id")
                  == (claim.get("holder") or {}).get("thread_id")]
    if len(supervisor) != 1:
        raise FleetCliError("recovery supervisor identity is ambiguous")
    thread_ids = []
    worktrees = {}
    receipts = {}
    for name, row in sorted(affected.items()):
        thread_id = row.get("codex_thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise FleetCliError(f"{name}: missing bound thread")
        thread_ids.append(thread_id)
        cwd = row.get("cwd")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise FleetCliError(f"{name}: missing exact cwd")
        path = Path(cwd)
        worktrees[name] = {"cwd": str(path.resolve()),
                           "head": _git(path, "rev-parse", "HEAD"),
                           "tracked_status": _sha(_git(path, "status", "--porcelain",
                                                        "--untracked-files=no"))}
        receipts[name] = {
            ext: _file_sha(home / "docs" / "lanes" / (name + ext))
            for ext in (".md", ".json")}
    if len(set(thread_ids)) != len(thread_ids):
        raise FleetCliError("recovery thread IDs are duplicated")
    for other_name, other_row in workers.items():
        if (other_name not in affected and isinstance(other_row, dict)
                and other_row.get("codex_thread_id") in thread_ids):
            raise FleetCliError("affected thread has another registry owner")
    mailbox = home / "mailbox"
    return {
        "claim": _sha(claim),
        "rows": {name: _sha(row) for name, row in affected.items()},
        "names": sorted(affected),
        "thread_ids": sorted(thread_ids),
        "operations": _directory_digest(home / "state" / "codex" / "operations",
                                        excluded=tuple(op + ".json" for op in
                                                       (resume_operations or {}).values())),
        "approvals": _directory_digest(home / "state" / "codex" / "approvals"),
        "mail": _directory_digest(mailbox,
                                  prefixes=tuple(thread_ids)),
        "queue": _file_sha(home / "supervisor" / "QUEUE.md"),
        "journal": _file_sha(home / "supervisor" / "JOURNAL.md"),
        "worktrees": worktrees, "receipts": receipts,
    }


def _load(fleet) -> dict[str, Any]:
    barrier = failed_client_recovery_barrier(fleet.FLEET_HOME)
    if barrier is None:
        raise FleetCliError("no failed-client recovery barrier exists")
    return barrier


def _save(fleet, record: dict[str, Any]) -> None:
    if record.get("state") not in _STAGES:
        raise FleetCliError("invalid failed-client recovery stage")
    _atomic_json(fleet.FLEET_HOME / "state" / "codex" / BARRIER, record)


def _source_and_caller(fleet, args, record=None):
    if not getattr(args, "_fleet_home_explicit", False):
        raise FleetCliError("failed-client recovery requires explicit --fleet-home")
    source = fleet._codex_recovery_interface_source()
    source_id = _sha(source)
    identity = _source_identity()
    if record is not None and (record.get("interface_source") != source_id
                               or record.get("source") != identity):
        raise FleetCliError("failed-client recovery Interface or source changed")
    return source_id, identity


def _compare(fleet, record: dict[str, Any], *, claim=True) -> None:
    generation = record["old_host"]["generation"]
    observed = _snapshot(fleet, generation, names=record["evidence"]["names"],
                         resume_operations=record.get("resume_operations", {}))
    expected = record["evidence"]
    for key in ("rows", "names", "thread_ids", "operations", "approvals",
                "mail", "queue", "journal", "worktrees", "receipts"):
        if observed[key] != expected[key]:
            raise FleetCliError(f"failed-client recovery {key} changed")
    if claim and observed["claim"] != expected["claim"]:
        raise FleetCliError("failed-client recovery claim changed")


def _compare_except_current(fleet, record: dict[str, Any]) -> None:
    """Permit only the one known partial row/claim update after a resume."""
    observed = _snapshot(
        fleet, record["old_host"]["generation"],
        names=record["evidence"]["names"],
        resume_operations=record.get("resume_operations", {}))
    expected = record["evidence"]
    for key in ("names", "thread_ids", "operations", "approvals", "mail",
                "queue", "journal", "worktrees", "receipts"):
        if observed[key] != expected[key]:
            raise FleetCliError(f"failed-client recovery {key} changed")
    for name, digest in expected["rows"].items():
        if name != record["current_name"] and observed["rows"][name] != digest:
            raise FleetCliError(f"failed-client recovery row {name} changed")
    if record["current_name"] != _supervisor_name(fleet, record):
        if observed["claim"] != expected["claim"]:
            raise FleetCliError("failed-client recovery claim changed")


def _check_old_host(record: dict[str, Any], *, require_live=True) -> None:
    host = record["old_host"]
    for pid_key, identity_key in (("pid", "process_identity"),
                                  ("app_server_pid", "app_server_process_identity")):
        state = _process_state(host[pid_key], host[identity_key])
        if state != ("live" if require_live else "absent"):
            raise FleetCliError(f"old {pid_key} is {state}; recovery refuses")


def _expect_metadata(fleet, record: dict[str, Any]) -> None:
    path = fleet.FLEET_HOME / "state" / "codex" / "host.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    for key, expected in record["old_host"].items():
        if current.get(key) != expected:
            raise FleetCliError(f"old host {key} changed")


def _prepare(fleet, args) -> None:
    source_id, source = _source_and_caller(fleet, args)
    if failed_client_recovery_barrier(fleet.FLEET_HOME) is not None:
        raise FleetCliError("failed-client recovery barrier already exists")
    client = CodexHostClient.connect_existing(fleet.FLEET_HOME)
    meta = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    keys = ("generation", "pid", "process_identity", "app_server_pid",
            "app_server_process_identity", "codex_version", "schema_digest")
    old_host = {key: meta[key] for key in keys}
    if (old_host["generation"] != args.generation
            or old_host["pid"] != args.host_pid
            or old_host["process_identity"] != args.host_start
            or old_host["app_server_pid"] != args.child_pid
            or old_host["app_server_process_identity"] != args.child_start):
        raise FleetCliError("original host identity differs from pinned incident")
    _check_old_host({"old_host": old_host})
    executable = _codex_executable_identity(args.codex_executable,
                                            old_host["codex_version"])
    claim = fleet.read_incarnation()
    if (claim.get("state") != "held"
            or claim.get("incarnation_id") != args.incarnation
            or (claim.get("holder") or {}).get("thread_id") != args.thread
            or claim.get("current_turn_id") != args.turn
            or claim.get("host_generation") != args.generation
            or claim.get("pending_operation") is not None):
        raise FleetCliError("held supervisor claim differs from pinned incident")
    with fleet.fleet_lock():
        if failed_client_recovery_barrier(fleet.FLEET_HOME) is not None:
            raise FleetCliError("failed-client recovery barrier appeared")
        evidence = _snapshot(fleet, args.generation)
        journals = _committed_original_journals(fleet.FLEET_HOME.resolve(),
                                                args.generation)
        approvals = _approval_inventory(fleet.FLEET_HOME.resolve(), args.generation)
        if approvals["old_generation_unresolved"]:
            raise FleetCliError("unresolved original callback needs separate settlement")
        _check_old_host({"old_host": old_host})
        if fleet.read_incarnation() != claim:
            raise FleetCliError("held supervisor claim changed during preparation")
        descendants = _descendants(args.host_pid)
        record = {
            "schema": 1, "home": str(fleet.FLEET_HOME.resolve()),
            "id": str(uuid.uuid4()), "state": "prepared",
            "created_at": time.time(), "interface_source": source_id,
            "source": source, "old_host": old_host,
            "codex_executable": executable,
            "incarnation": args.incarnation, "supervisor_thread": args.thread,
            "supervisor_turn": args.turn, "evidence": evidence,
            "original_journals": journals,
            "original_approvals": approvals,
            "descendants": descendants, "decision": None,
            "shutdown_operation": "failed-client-shutdown-" + uuid.uuid4().hex,
            "rebound": [], "held": [], "resume_operations": {},
            "current_operation": None,
            "current_thread": None, "current_payload_digest": None,
        }
        _save(fleet, record)
    print(f"failed-client recovery prepared {record['id']}; provider unchanged")


def _decision(fleet, args, record):
    if record["state"] != "prepared":
        raise FleetCliError("interruption decision requires prepared stage")
    if not isinstance(args.decision_file, str) or not args.decision_file:
        raise FleetCliError("explicit decision receipt path is required")
    path = Path(args.decision_file)
    try:
        info = path.lstat()
    except OSError as exc:
        raise FleetCliError("explicit decision receipt is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 8192:
        raise FleetCliError("interruption decision receipt has unsafe type or owner")
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FleetCliError("explicit decision receipt is unreadable") from exc
    if (not isinstance(decision, dict)
            or decision.get("recovery_id") != record["id"]
            or decision.get("home") != record["home"]
            or decision.get("old_generation") != record["old_host"]["generation"]
            or decision.get("authority") != "founder"
            or decision.get("decision") != "accept-controlled-interruption"
            or decision.get("consequence") != LOSS_TEXT):
        raise FleetCliError("explicit interruption decision receipt is missing or mismatched")
    with fleet.fleet_lock():
        _compare(fleet, record)
        _expect_metadata(fleet, record)
        _check_old_host(record)
        record["decision"] = {"sha256": _file_sha(path), "text": LOSS_TEXT}
        record["state"] = "authorized"
        _save(fleet, record)
    print("explicit interruption decision recorded; no shutdown sent")


def _shutdown(fleet, record):
    if record["state"] != "authorized" or not record.get("decision"):
        raise FleetCliError("shutdown requires explicit recorded interruption decision")
    with fleet.fleet_lock():
        _compare(fleet, record)
        _expect_metadata(fleet, record)
        _check_old_host(record)
        if _descendants(record["old_host"]["pid"]) != record["descendants"]:
            raise FleetCliError("known descendant inventory changed before shutdown")
        client = CodexHostClient.connect_existing(fleet.FLEET_HOME)
        if client.generation != record["old_host"]["generation"]:
            raise FleetCliError("old host generation changed")
        record["state"] = "shutdown_sent"
        _save(fleet, record)  # Durable before the one irreversible IPC write.
        try:
            reply = client.call({"operation_id": record["shutdown_operation"],
                                 "method": "host/shutdown", "payload": {}}, timeout=10)
        except BaseException:
            raise FleetCliError("shutdown reply unknown; inspect exact process absence; never resend")
        if reply.generation != client.generation or reply.result != {"stopping": True}:
            raise FleetCliError("shutdown reply ambiguous; inspect exact process absence")
        record["state"] = "shutdown_ack"
        _save(fleet, record)
    print("one exact host/shutdown acknowledged; process exit still unproved")


def _exit(fleet, record):
    if record["state"] not in {"shutdown_sent", "shutdown_ack"}:
        raise FleetCliError("exit check requires one staged shutdown")
    _compare(fleet, record)
    _expect_metadata(fleet, record)
    _check_old_host(record, require_live=False)
    for pid, identity in record["descendants"].items():
        state = _process_state(int(pid), identity)
        if state != "absent":
            raise FleetCliError(f"known descendant {pid} is {state}")
    client = CodexHostClient.connect_existing(fleet.FLEET_HOME)
    if not client._metadata_stale():
        raise FleetCliError("old host heartbeat is not stale")
    record["state"] = "exited"
    _save(fleet, record)
    print("exact old host, child, and known descendants absent; side effects remain uncertain")


def _boot(fleet, record):
    if record["state"] != "exited":
        raise FleetCliError("new host start requires exited stage")
    _compare(fleet, record)
    _expect_metadata(fleet, record)
    _check_old_host(record, require_live=False)
    if _committed_original_journals(fleet.FLEET_HOME.resolve(),
                                    record["old_host"]["generation"]) != record["original_journals"]:
        raise FleetCliError("original operation journal inventory changed")
    if _approval_inventory(fleet.FLEET_HOME.resolve(),
                           record["old_host"]["generation"]) != record["original_approvals"]:
        raise FleetCliError("original callback inventory changed")
    executable = record["codex_executable"]
    if _codex_executable_identity(executable["path"],
                                  record["old_host"]["codex_version"]) != executable:
        raise FleetCliError("pinned Codex executable changed")
    if not CodexHostClient.connect_existing(fleet.FLEET_HOME)._metadata_stale():
        raise FleetCliError("old heartbeat is still fresh")
    record["state"] = "boot_requested"
    _save(fleet, record)
    command = executable["path"]
    child_env = dict(os.environ)
    child_env.pop("CODEX_THREAD_ID", None)
    child_env.pop("CLAUDE_CODE_SESSION_ID", None)
    client = CodexHostClient.ensure(
        fleet.FLEET_HOME, app_server_command=[command, "app-server", "--listen", "stdio://"],
        schema_command=[command], env=child_env)
    _adopt_boot(fleet, record, client=client)


def _adopt_boot(fleet, record, *, client=None):
    """Adopt an already started reviewed host after an interrupted CLI call."""
    if record["state"] != "boot_requested":
        raise FleetCliError("no exact boot request is pending")
    _compare(fleet, record)
    _check_old_host(record, require_live=False)
    client = client or CodexHostClient.connect_existing(fleet.FLEET_HOME)
    if client.generation == record["old_host"]["generation"]:
        raise FleetCliError("new host not observed; no automatic second launch")
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    if (metadata.get("codex_version") != record["old_host"]["codex_version"]
            or client.schema_digest != record["old_host"]["schema_digest"]
            or _process_state(client.host_pid, client.host_process_identity) != "live"
            or _process_state(client.app_server_pid,
                              client.app_server_process_identity) != "live"):
        raise FleetCliError("replacement host schema changed")
    try:
        argv = (Path("/proc") / str(client.host_pid) / "cmdline").read_bytes().split(b"\0")
        launched_script = argv[1].decode("utf-8")
    except (OSError, UnicodeError, IndexError):
        raise FleetCliError("replacement host source path is unavailable")
    if Path(launched_script).resolve() != Path(__file__).with_name("fleet_codex_host.py").resolve():
        raise FleetCliError("replacement host is not running reviewed recovery source")
    executable = record["codex_executable"]
    if _codex_executable_identity(executable["path"],
                                  record["old_host"]["codex_version"]) != executable:
        raise FleetCliError("pinned Codex executable changed after boot")
    try:
        child_exe = Path("/proc") / str(client.app_server_pid) / "exe"
        if not os.path.samefile(child_exe, executable["path"]):
            raise FleetCliError("replacement child is not the pinned Codex executable")
    except OSError as exc:
        raise FleetCliError("replacement child executable identity is unavailable") from exc
    record["new_generation"] = client.generation
    record["state"] = "rebind"
    _save(fleet, record)
    print(f"reviewed new host ready {client.generation}; no thread or turn created")


def _call_read(client, method, params):
    reply = client.call({"operation_id": "failed-client-read-" + uuid.uuid4().hex,
                         "method": "rpc", "payload": {"method": method, "params": params}},
                        timeout=10)
    if not isinstance(reply.result, dict):
        raise FleetCliError(f"{method} returned malformed data")
    return reply.result


def _complete_history(fleet, client, thread_id, turn_id, cwd):
    thread = _call_read(client, "thread/read", {"threadId": thread_id,
                                                 "includeTurns": False}).get("thread")
    if (not isinstance(thread, dict) or thread.get("id") != thread_id
            or thread.get("cwd") != cwd):
        raise FleetCliError("rebind public thread identity/cwd differs")
    status = thread.get("status")
    if (not isinstance(status, dict)
            or status.get("type") not in {"idle", "notLoaded"}
            or status.get("activeFlags", []) != []):
        raise FleetCliError("rebind public thread is active or has unknown flags")
    ids = []
    cursor = None
    seen = set()
    for _ in range(64):
        params = {"threadId": thread_id, "limit": 100,
                  "sortDirection": "desc", "itemsView": "notLoaded"}
        if cursor is not None:
            params["cursor"] = cursor
        page = _call_read(client, "thread/turns/list", params)
        data = page.get("data")
        if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
            raise FleetCliError("rebind turn page malformed")
        ids.extend((x.get("id"), x.get("status")) for x in data)
        cursor = page.get("nextCursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor or cursor in seen or not data:
            raise FleetCliError("rebind turn cursor malformed")
        seen.add(cursor)
    else:
        raise FleetCliError("rebind turn history exceeds page bound")
    if (not ids or len({x[0] for x in ids}) != len(ids)
            or ids[0][0] != turn_id
            or any(not isinstance(turn, str) or not turn
                   or status not in {"completed", "failed", "interrupted"}
                   for turn, status in ids)):
        raise FleetCliError("turn history has absent, nonterminal, or malformed turn")
    first_again = _call_read(client, "thread/turns/list", {
        "threadId": thread_id, "limit": 100, "sortDirection": "desc",
        "itemsView": "notLoaded"}).get("data")
    if not isinstance(first_again, list) or [
            (x.get("id"), x.get("status")) for x in first_again
            if isinstance(x, dict)] != ids[:len(first_again)]:
        raise FleetCliError("rebind turn history changed during read")
    hydrated = fleet._codex_paged_thread_read(
        client, thread_id, client.generation, "failed-client-history",
        hydrate_turn=turn_id)
    turns = hydrated.result.get("thread", {}).get("turns", [])
    if (not isinstance(turns, list) or not turns
            or turns[-1].get("id") != turn_id
            or turns[-1].get("itemsView") != "full"
            or turns[-1].get("status") != ids[0][1]):
        raise FleetCliError("bound turn item history is incomplete or changed")
    return {"thread_status": status["type"], "bound_turn_status": ids[0][1],
            "turn_count": len(ids)}


def _rebind(fleet, args, record):
    if record["state"] != "rebind" or record.get("current_operation") is not None:
        raise FleetCliError("rebind stage has an unresolved operation")
    name = args.name
    if name not in record["evidence"]["names"] or name in record["rebound"] or name in record["held"]:
        raise FleetCliError("rebind name is not one unresolved affected row")
    _compare(fleet, record)
    client = CodexHostClient.connect_existing(fleet.FLEET_HOME)
    if client.generation != record["new_generation"]:
        raise FleetCliError("new host generation changed")
    row = fleet.read_registry_no_repair()["workers"][name]
    if row.get("status") in {"dead", "interrupted"}:
        # A local tombstone is not public terminal evidence. Inspect even rows
        # whose cached provider_status says active before holding them.
        _complete_history(fleet, client, row.get("codex_thread_id"),
                          row.get("codex_turn_id"), str(Path(row["cwd"]).resolve()))
        # Retain terminal rows as old-generation historical owners. No resume
        # or turn is needed; the completed barrier continues to fence them.
        record["held"].append(name)
        _save(fleet, record)
        print(f"{name}: historical terminal row held without resume")
        return
    if row.get("status") not in {"idle", "working"}:
        raise FleetCliError("affected row has an unknown/live status")
    thread_id, turn_id = row.get("codex_thread_id"), row.get("codex_turn_id")
    cwd = str(Path(row["cwd"]).resolve())
    _complete_history(fleet, client, thread_id, turn_id, cwd)
    model, profile = _row_policy(fleet, row)
    policy_config = _resume_policy_config(row)
    operation_id = "failed-client-rebind-" + hashlib.sha256(
        (record["id"] + "\0" + name).encode()).hexdigest()[:36]
    params = {"threadId": thread_id, "excludeTurns": True, "cwd": cwd,
              "model": model, "approvalPolicy": profile["approvalPolicy"],
              "approvalsReviewer": "user", "sandbox": profile["sandbox"]}
    if policy_config is not None:
        params["config"] = policy_config
    operation = {"operation_id": operation_id, "method": "rpc",
                 "payload": {"method": "thread/resume", "params": params},
                 "recovery": {"kind": "failed-client/thread-resume",
                              "recovery_id": record["id"], "fleet_name": name,
                              "thread_id": thread_id, "bound_turn_id": turn_id,
                              "previous_host_generation": record["old_host"]["generation"],
                              "canonical_cwd": cwd}}
    with fleet.fleet_lock():
        _compare(fleet, record)
        if fleet.read_registry_no_repair()["workers"].get(name) != row:
            raise FleetCliError("rebind row changed before reservation")
        record["current_operation"] = operation_id
        record["current_thread"] = thread_id
        record["current_payload_digest"] = _digest("rpc", operation["payload"])
        record["current_name"] = name
        record["current_row"] = dict(row)
        if name == _supervisor_name(fleet, record):
            record["current_claim"] = dict(fleet.read_incarnation())
        record["resume_operations"][name] = operation_id
        _save(fleet, record)  # Any lost reply freezes this one-shot operation.
        try:
            reply = client.call(operation, timeout=30)
            result = reply.result
            thread = result.get("thread") if isinstance(result, dict) else None
            if (not isinstance(thread, dict) or thread.get("id") != thread_id
                    or {thread.get("cwd"), result.get("cwd")} != {cwd}):
                raise FleetCliError("rebound thread identity/cwd differs")
            fleet._validate_codex_thread_effective(result, model, profile,
                                                   verb="thread/resume")
            _require_recorded_effective(result, row)
        except BaseException as exc:
            raise FleetCliError(
                f"{name}: rebind outcome uncertain; barrier retained and resume never replayed") from exc
    _settle_rebind(fleet, record)


def _settle_rebind(fleet, record):
    """Settle a one-shot observed resume; never call thread/resume again."""
    if (record["state"] != "rebind" or not record.get("current_operation")
            or not record.get("current_name")
            or not record.get("current_thread")
            or not record.get("current_payload_digest")):
        raise FleetCliError("no exact pending rebind to settle")
    name = record["current_name"]
    operation_id = record["current_operation"]
    client = CodexHostClient.connect_existing(fleet.FLEET_HOME)
    if client.generation != record["new_generation"]:
        raise FleetCliError("new host generation changed during settlement")
    journal = OperationJournal(fleet.FLEET_HOME, client.generation).load(operation_id)
    if journal.get("state") not in {"observed", "committed"}:
        raise FleetCliError("resume acceptance or reply is unresolved; no replay")
    original = record["current_row"]
    thread_id, turn_id = original["codex_thread_id"], original["codex_turn_id"]
    cwd = str(Path(original["cwd"]).resolve())
    expected_recovery = {
        "kind": "failed-client/thread-resume", "recovery_id": record["id"],
        "fleet_name": name, "thread_id": thread_id, "bound_turn_id": turn_id,
        "previous_host_generation": record["old_host"]["generation"],
        "canonical_cwd": cwd,
    }
    if (journal.get("home") != str(fleet.FLEET_HOME.resolve())
            or journal.get("generation") != client.generation
            or journal.get("operation_id") != operation_id
            or journal.get("method") != "rpc"
            or journal.get("public_method") != "thread/resume"
            or journal.get("payload_digest") != record["current_payload_digest"]
            or journal.get("recovery") != expected_recovery
            or record["current_thread"] != thread_id
            or record["resume_operations"].get(name) != operation_id):
        raise FleetCliError("observed resume journal differs from staged exact intent")
    model, profile = _row_policy(fleet, original)
    result = journal.get("result")
    thread = result.get("thread") if isinstance(result, dict) else None
    if (not isinstance(thread, dict) or thread.get("id") != thread_id
            or {thread.get("cwd"), result.get("cwd")} != {cwd}):
        raise FleetCliError("observed resume result has wrong thread/cwd")
    fleet._validate_codex_thread_effective(result, model, profile,
                                           verb="thread/resume")
    _require_recorded_effective(result, original)
    observed = _complete_history(fleet, client, thread_id, turn_id, cwd)
    if observed["thread_status"] != "idle":
        raise FleetCliError("resumed thread is not loaded idle")
    if journal["state"] == "observed":
        OperationJournal(fleet.FLEET_HOME, client.generation).commit(operation_id)
    new_row = dict(original)
    new_row.update({
        "codex_host_generation": client.generation, "provider_status": "idle",
        "status": "idle", "adapter_state": "idle",
        "last_operation_id": operation_id,
        "failed_client_interruption": observed["bound_turn_status"],
    })
    old_claim = record.get("current_claim")
    new_claim = None
    if old_claim is not None:
        new_claim = dict(old_claim)
        new_claim.update({
            "host_generation": client.generation, "provider_status": "idle",
            "last_operation_id": operation_id,
            "failed_client_interruption": observed["bound_turn_status"],
        })
    with fleet.fleet_lock():
        _compare_except_current(fleet, record)
        data = fleet.read_registry_no_repair()
        actual_row = data["workers"].get(name)
        if actual_row not in (original, new_row):
            raise FleetCliError("rebind row changed before CAS")
        if new_claim is not None:
            actual_claim = fleet.read_incarnation()
            if actual_claim not in (old_claim, new_claim):
                raise FleetCliError("supervisor claim changed before rebind")
            if actual_claim == old_claim:
                fleet.write_incarnation(new_claim)
        if actual_row == original:
            data["workers"][name] = new_row
            fleet.save_registry(data)
        record["evidence"]["rows"][name] = _sha(new_row)
        if new_claim is not None:
            record["evidence"]["claim"] = _sha(new_claim)
        record["rebound"].append(name)
        record["current_operation"] = None
        record["current_thread"] = None
        record["current_payload_digest"] = None
        record.pop("current_name", None)
        record.pop("current_row", None)
        record.pop("current_claim", None)
        _save(fleet, record)
    print(f"{name}: same thread rebound idle; no turn started")


def _supervisor_name(fleet, record):
    data = fleet.read_registry_no_repair()["workers"]
    matches = [name for name in record["evidence"]["names"]
               if data[name].get("codex_thread_id") == record["supervisor_thread"]]
    if len(matches) != 1:
        raise FleetCliError("supervisor row identity changed")
    return matches[0]


def _finish(fleet, record):
    if record["state"] != "rebind" or record.get("current_operation") is not None:
        raise FleetCliError("cannot finish with an unresolved resume")
    if set(record["rebound"]) | set(record["held"]) != set(record["evidence"]["names"]):
        raise FleetCliError("not every affected row is rebound or explicitly held")
    if _supervisor_name(fleet, record) not in record["rebound"]:
        raise FleetCliError("supervisor was not rebound")
    _compare(fleet, record)
    record["held_threads"] = [fleet.read_registry_no_repair()["workers"][name]["codex_thread_id"]
                              for name in record["held"]]
    record["state"] = "complete"
    _save(fleet, record)
    print("failed-client recovery complete; historical held threads remain fenced")


def cmd_recover(fleet, args) -> int:
    source_id, source = _source_and_caller(fleet, args)
    if args.recovery_action == "prepare":
        _prepare(fleet, args)
        return 0
    record = _load(fleet)
    if record["interface_source"] != source_id or record["source"] != source:
        raise FleetCliError("recovery caller/source changed")
    action = args.recovery_action
    if action == "status":
        print(json.dumps({"id": record["id"], "state": record["state"],
                          "old_generation": record["old_host"]["generation"],
                          "new_generation": record.get("new_generation"),
                          "affected": record["evidence"]["names"],
                          "rebound": record["rebound"], "held": record["held"],
                          "remaining": sorted(set(record["evidence"]["names"])
                                              - set(record["rebound"])
                                              - set(record["held"])),
                          "current_operation": record.get("current_operation")},
                         sort_keys=True))
    elif action == "decision":
        _decision(fleet, args, record)
    elif action == "shutdown":
        _shutdown(fleet, record)
    elif action == "verify-exit":
        _exit(fleet, record)
    elif action == "boot":
        _boot(fleet, record)
    elif action == "adopt-boot":
        _adopt_boot(fleet, record)
    elif action == "rebind":
        _rebind(fleet, args, record)
    elif action == "settle-rebind":
        _settle_rebind(fleet, record)
    elif action == "finish":
        _finish(fleet, record)
    else:
        raise FleetCliError("unknown failed-client recovery action")
    return 0
