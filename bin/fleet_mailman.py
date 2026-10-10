from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fleet_errors import FleetCliError

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt below.
    _fcntl = None
try:
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX uses fcntl above.
    _msvcrt = None

CONFIG_NAME = "mailman.json"
MAIL_MAX_BYTES = 1024 * 1024
CLAIMS_DIR_NAME = ".mailman-claims"
CLAIM_STALE_SECONDS = 300
WAKE, FILE = "WAKE", "FILE"
DEFAULT_INTERVAL = 30.0
DIGEST_DEFAULT_SINCE = "24h"

SEED_CONFIG = {
    "wake": {
        "kinds": ["question", "claim", "design-question"],
        "needs_answer": True,
        "ignore_case": True,
        "patterns": [
            "merge-ready", r"^\s*READY:", "retract", "do-not-merge",
            r"\bdo\s+not\s+merge\b", "blocker",
            "founder action", "CRITICAL", "\\bP0\\b",
        ],
    },
    "bridge": {"command": [], "timeout_s": 60, "max_failures": 5},
    "digest": {"summary_max": 160},
}


@dataclass
class Prims:
    append: Callable[[Path, bytes], None]
    write_json: Callable[[Path, dict], None]
    replace: Callable[[str, str], None]
    read_cursor: Callable[[Path], tuple]
    write_cursor: Callable[[Path, dict], None]
    now: Callable[[], str]


def inbox_dir(home) -> Path:
    return Path(home) / "mailbox" / "to-fleet"


def done_dir(home) -> Path:
    return Path(home) / "mailbox" / "done"


def _iface(home) -> Path:
    return Path(home) / "state" / "interface"


def digest_path(home) -> Path:
    return _iface(home) / "digest.md"


def log_path(home) -> Path:
    return _iface(home) / "log.md"


def state_path(home) -> Path:
    return _iface(home) / "mailman-state.json"


def config_path(home) -> Path:
    return Path(home) / CONFIG_NAME


class ConfigError(Exception):
    pass


@dataclass
class Rule:
    regex: "re.Pattern"
    unless: list
    text: str


@dataclass
class Config:
    kinds: list
    needs_answer: bool
    rules: list
    bridge_command: list
    bridge_timeout: float
    bridge_max_failures: int
    summary_max: int


_SCHEMA = {
    "wake": {"kinds", "needs_answer", "ignore_case", "patterns"},
    "bridge": {"command", "timeout_s", "max_failures"},
    "digest": {"summary_max"},
}


def _str_list(value, where):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError(f"{where} must be a list of strings")
    return value


def parse_config(text: str) -> Config:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError("top level must be an object")
    for table, body in data.items():
        if table not in _SCHEMA:
            raise ConfigError(f"unknown table {table!r}")
        if not isinstance(body, dict):
            raise ConfigError(f"{table!r} must be an object")
        for key in body:
            if key not in _SCHEMA[table]:
                raise ConfigError(f"unknown key {table}.{key}")
    wake = data.get("wake") or {}
    bridge = data.get("bridge") or {}
    digest = data.get("digest") or {}
    if "wake" not in data:
        raise ConfigError("missing 'wake' table")
    kinds = [k.strip().lower() for k in _str_list(wake.get("kinds", []), "wake.kinds")]
    needs = wake.get("needs_answer", True)
    if not isinstance(needs, bool):
        raise ConfigError("wake.needs_answer must be a boolean")
    icase = wake.get("ignore_case", True)
    if not isinstance(icase, bool):
        raise ConfigError("wake.ignore_case must be a boolean")
    flags = re.IGNORECASE if icase else 0
    rules = []
    raw_patterns = wake.get("patterns", [])
    if not isinstance(raw_patterns, list):
        raise ConfigError("wake.patterns must be a list")
    for i, item in enumerate(raw_patterns):
        if isinstance(item, str):
            pat, unless = item, []
        elif isinstance(item, dict) and set(item) <= {"pattern", "unless"} \
                and isinstance(item.get("pattern"), str):
            pat = item["pattern"]
            unless = _str_list(item.get("unless", []), f"wake.patterns[{i}].unless")
        else:
            raise ConfigError(f"wake.patterns[{i}] must be a string or "
                              f"{{pattern, unless}} object")
        try:
            rules.append(Rule(re.compile(pat, flags),
                              [re.compile(u, flags) for u in unless], pat))
        except re.error as exc:
            raise ConfigError(f"wake.patterns[{i}] does not compile: {exc}") from None
    command = _str_list(bridge.get("command", []), "bridge.command")
    timeout = bridge.get("timeout_s", 60)
    maxf = bridge.get("max_failures", 5)
    smax = digest.get("summary_max", 160)
    for name, val in (("bridge.timeout_s", timeout), ("bridge.max_failures", maxf),
                      ("digest.summary_max", smax)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
            raise ConfigError(f"{name} must be a positive number")
    return Config(kinds, needs, rules, command, float(timeout), int(maxf), int(smax))


def load_config(home):
    path = config_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"{CONFIG_NAME} missing (run `fleet mailman init`)"
    except (OSError, UnicodeError) as exc:
        return None, f"{CONFIG_NAME} unreadable: {exc}"
    try:
        return parse_config(text), None
    except ConfigError as exc:
        return None, f"{CONFIG_NAME} invalid: {exc}"


def cmd_init(home, prims: Prims, force=False) -> int:
    home = Path(home)
    path = config_path(home)
    if not home.is_dir():
        raise FleetCliError(f"fleet home {home} is not a directory")
    if path.exists() and not force:
        raise FleetCliError(f"{path} exists; pass --force to overwrite")
    prims.write_json(path, SEED_CONFIG)
    print(f"wrote {path}")
    return 0


_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class Verdict:
    kind: str
    reasons: list
    sha: str | None = None
    sender: str = "unknown"
    mail_kind: str = "unknown"
    summary: str = "(no body)"
    inode: tuple[int, int] | None = None


def clean_field(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]", "_", value.strip())[:64] or "unknown"


def clean_text(value: str, limit: int) -> str:
    text = _CTRL_RE.sub(" ", value)
    text = text.replace("<!--", "< !--").replace("-->", "-- >")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:max(0, limit - 3)] + "..."
    return text


def clean_name(name: str) -> str:
    return clean_text(name, 200).replace("|", "_")


def file_identity(path: Path):
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def claims_dir(home) -> Path:
    return inbox_dir(home) / CLAIMS_DIR_NAME


def _owner_lock_path(claim_dir: Path) -> Path:
    return claim_dir.with_name(claim_dir.name + ".lock")


def _acquire_owner_lock(fd: int, *, initialize=False) -> None:
    """Acquire an exclusive nonblocking lock; close(fd) releases it."""
    if _fcntl is not None:
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        return
    if _msvcrt is not None:
        if initialize and os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        elif os.fstat(fd).st_size == 0:
            raise OSError("empty Windows claim lock")
        os.lseek(fd, 0, os.SEEK_SET)
        _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
        return
    raise OSError("mailman filing requires an OS-supported claim lock")


def _ensure_claims_dir(home) -> Path:
    root = claims_dir(home)
    try:
        os.mkdir(root, 0o700)
    except FileExistsError:
        try:
            st = os.lstat(root)
        except OSError:
            raise
        if not stat.S_ISDIR(st.st_mode):
            raise OSError("mailman claims path is not a directory")
    return root


def _new_claim_dir(home) -> tuple[Path, int]:
    # Fail before creating claim state on platforms without a safe lock API.
    if _fcntl is None and _msvcrt is None:
        raise FleetCliError("mailman filing requires an OS-supported claim lock")
    root = _ensure_claims_dir(home)
    while True:
        path = root / f"claim-{uuid.uuid4().hex}"
        try:
            os.mkdir(path, 0o700)
            owner_fd = None
            try:
                owner_fd = os.open(_owner_lock_path(path),
                                   os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                _acquire_owner_lock(owner_fd, initialize=True)
            except OSError:
                if owner_fd is not None:
                    os.close(owner_fd)
                    try:
                        os.unlink(_owner_lock_path(path))
                    except OSError:
                        pass
                path.rmdir()
                raise
            return path, owner_fd
        except FileExistsError:
            continue


def _remove_private_claim(claim: Path, claim_dir: Path) -> None:
    """Remove only a claim path inside our exclusive private claim directory."""
    try:
        os.unlink(claim)
    except FileNotFoundError:
        pass
    try:
        os.unlink(claim_dir / "origin")
    except FileNotFoundError:
        pass
    try:
        claim_dir.rmdir()
    except OSError:
        pass


def _release_owner_lock(claim_dir: Path, owner_fd: int) -> None:
    """Close the OS lock before removing its sibling lockfile (Windows-safe)."""
    try:
        opened = os.fstat(owner_fd)
        opened_id = (opened.st_dev, opened.st_ino)
    except OSError:
        opened_id = None
    os.close(owner_fd)
    # A surviving claim directory represents an interrupted filing attempt;
    # its released lockfile is the proof recovery needs on the next pass.
    if claim_dir.exists():
        return
    try:
        lock_path = _owner_lock_path(claim_dir)
        current = os.lstat(lock_path)
    except FileNotFoundError:
        pass
    else:
        if (opened_id is not None and stat.S_ISREG(current.st_mode)
                and (current.st_dev, current.st_ino) == opened_id):
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass


def _recovered_name(original_name: str | None) -> str:
    stem = clean_name(_canonical_mail_name(original_name or "mail"))
    return f"{stem}.recovered-{uuid.uuid4().hex}.mail"


def _publish_claim(home, claim: Path, claim_dir: Path,
                   original_name: str | None = None) -> bool:
    """Expose a private claim under a fresh name without replacing an arrival."""
    inbox = inbox_dir(home)
    for _ in range(8):
        target = inbox / _recovered_name(original_name)
        try:
            os.link(claim, target, follow_symlinks=False)
        except FileExistsError:
            continue
        except OSError:
            return False
        claim_id = file_identity(claim)
        if claim_id is None or file_identity(target) != claim_id:
            return False
        # Producers write only their original inbox publication names; this
        # random path is private to mailman and cannot replace a new arrival.
        _remove_private_claim(claim, claim_dir)
        return True
    return False


def _recover_stale_claims(home, *, now=None) -> int:
    """Recover only stale claims whose per-claim owner lock is released."""
    root = claims_dir(home)
    try:
        st = os.lstat(root)
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return 0
    current = time.time() if now is None else now
    recovered = 0
    for entry in list(root.iterdir()):
        try:
            entry_stat = os.lstat(entry)
        except OSError:
            continue
        if (not stat.S_ISDIR(entry_stat.st_mode)
                or current - entry_stat.st_mtime < CLAIM_STALE_SECONDS):
            continue
        try:
            lock_path = _owner_lock_path(entry)
            lock_stat = os.lstat(lock_path)
            if not stat.S_ISREG(lock_stat.st_mode):
                continue
            owner_fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            continue
        try:
            opened_stat = os.fstat(owner_fd)
            if ((opened_stat.st_dev, opened_stat.st_ino)
                    != (lock_stat.st_dev, lock_stat.st_ino)):
                continue
            try:
                _acquire_owner_lock(owner_fd)
            except OSError:
                continue
            # Recheck after acquiring the owner's kernel-released lock.
            try:
                if (not stat.S_ISDIR(os.lstat(entry).st_mode)
                        or current - os.lstat(entry).st_mtime < CLAIM_STALE_SECONDS):
                    continue
            except OSError:
                continue
            claim = entry / "mail"
            try:
                claim_stat = os.lstat(claim)
            except OSError:
                # A directory without its mail entry is ambiguous even after
                # it is old; leave it untouched instead of guessing ownership.
                continue
            if not stat.S_ISREG(claim_stat.st_mode):
                continue
            try:
                original_name = os.fsdecode((entry / "origin").read_bytes())
            except OSError:
                original_name = None
            # Never restore a claim at the producer-mutable original name:
            # a replacement there could remove the last old-content link.
            if _publish_claim(home, claim, entry, original_name):
                recovered += 1
        finally:
            _release_owner_lock(entry, owner_fd)
    return recovered


def _claim_source(home, name: str, v: Verdict):
    """Atomically move the exact classified inbox entry into a private claim."""
    src = inbox_dir(home) / name
    raw, problem, inode = read_mail_snapshot(src)
    if (problem is not None or inode != v.inode
            or hashlib.sha256(raw).hexdigest() != v.sha):
        return None
    claim_dir, owner_fd = _new_claim_dir(home)
    claim = claim_dir / "mail"
    try:
        (claim_dir / "origin").write_bytes(os.fsencode(name))
        # The fresh, exclusive directory means this target cannot overwrite
        # an existing claim or another home-inbox file.
        os.rename(src, claim)
    except FileNotFoundError:
        _remove_private_claim(claim, claim_dir)
        _release_owner_lock(claim_dir, owner_fd)
        return None
    except OSError:
        _remove_private_claim(claim, claim_dir)
        _release_owner_lock(claim_dir, owner_fd)
        return None
    claimed, claimed_problem, claimed_inode = read_mail_snapshot(claim)
    if (claimed_problem is not None or claimed_inode != v.inode
            or hashlib.sha256(claimed).hexdigest() != v.sha):
        _publish_claim(home, claim, claim_dir, name)
        _release_owner_lock(claim_dir, owner_fd)
        return None
    return claim, claim_dir, owner_fd


def read_mail_snapshot(path: Path):
    try:
        st = os.lstat(path)
    except OSError as exc:
        return None, f"unreadable: {exc.__class__.__name__}", None
    if not stat.S_ISREG(st.st_mode):
        return None, "not-a-regular-file", None
    if st.st_size > MAIL_MAX_BYTES:
        return None, "oversize", (st.st_dev, st.st_ino)
    expected = (st.st_dev, st.st_ino)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            opened = os.fstat(fh.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != expected):
                return None, "changed-before-read", None
            raw = fh.read(MAIL_MAX_BYTES + 1)
            after = os.fstat(fh.fileno())
            if ((after.st_dev, after.st_ino) != expected
                    or after.st_size != opened.st_size
                    or after.st_mtime_ns != opened.st_mtime_ns):
                return None, "changed-during-read", None
    except OSError as exc:
        return None, f"unreadable: {exc.__class__.__name__}", None
    if len(raw) > MAIL_MAX_BYTES:
        return None, "oversize", expected
    return raw, None, expected


def read_mail(path: Path):
    raw, problem, _ = read_mail_snapshot(path)
    return raw, problem


def classify(raw: bytes | None, problem: str | None, cfg: Config | None,
             failsafe: str | None = None, inode=None) -> Verdict:
    if problem is not None:
        return Verdict(WAKE, [f"malformed:{problem}"], inode=inode)
    sha = hashlib.sha256(raw).hexdigest()
    if cfg is None:
        return Verdict(WAKE, [f"failsafe:{failsafe}"], sha=sha, inode=inode)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        return Verdict(WAKE, ["malformed:not-utf8"], sha=sha, inode=inode)
    if not text.strip():
        return Verdict(WAKE, ["malformed:empty"], sha=sha, inode=inode)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headers: dict[str, list] = {}
    idx = 0
    while idx < len(lines) and lines[idx].strip():
        m = _HEADER_RE.match(lines[idx])
        if not m:
            return Verdict(WAKE, ["malformed:bad-header-line"], sha=sha, inode=inode)
        headers.setdefault(m.group(1).lower(), []).append(m.group(2).strip())
        idx += 1
    if not headers:
        return Verdict(WAKE, ["malformed:no-header-block"], sha=sha, inode=inode)
    body_lines = lines[idx + 1:]
    kinds = headers.get("kind", [])
    if not kinds or not kinds[0]:
        return Verdict(WAKE, ["malformed:kind-missing"], sha=sha, inode=inode)
    if any(k.lower() != kinds[0].lower() for k in kinds[1:]):
        return Verdict(WAKE, ["malformed:kind-conflict"], sha=sha, inode=inode)
    answers = [a.lower() for a in headers.get("needs-answer", [])]
    if any(a not in ("yes", "no") for a in answers):
        return Verdict(WAKE, ["malformed:needs-answer"], sha=sha, inode=inode)
    sender = clean_field((headers.get("from") or ["unknown"])[0])
    mail_kind = clean_field(kinds[0])
    body_first = next((ln for ln in body_lines if ln.strip()), "")
    summary = clean_text(body_first, cfg.summary_max) if body_first else "(no body)"
    reasons = []
    if cfg.needs_answer and "yes" in answers:
        reasons.append("needs-answer")
    if kinds[0].strip().lower() in cfg.kinds:
        reasons.append(f"kind:{kinds[0].strip().lower()}")
    for rule in cfg.rules:
        for ln in body_lines:
            if rule.regex.search(ln) and not any(u.search(ln) for u in rule.unless):
                reasons.append(f"pattern:{rule.text}")
                break
    return Verdict(WAKE if reasons else FILE, reasons, sha, sender, mail_kind,
                   summary, inode)


def list_inbox(home) -> list:
    try:
        names = [e.name for e in os.scandir(inbox_dir(home))]
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(n for n in names if not n.startswith(".") and not n.endswith(".tmp"))


def _contains(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _step_digest(home, name, v: Verdict, prims: Prims):
    cname = clean_name(_canonical_mail_name(name))
    marker = f"mailman:{cname}:{v.sha[:12]}"
    if _contains(digest_path(home), marker):
        return
    line = (f"- {prims.now()} | {v.sender} | {v.mail_kind} | {cname} | "
            f"{v.summary} <!-- {marker} -->\n")
    digest_path(home).parent.mkdir(parents=True, exist_ok=True)
    prims.append(digest_path(home), line.encode("utf-8", "replace"))


def _step_log(home, name, v: Verdict, prims: Prims):
    cname = clean_name(_canonical_mail_name(name))
    marker = f"[mailman:{cname}:{v.sha[:12]}]"
    if _contains(log_path(home), marker):
        return
    line = (f"{prims.now()} mailman filed {cname} ({v.sender}/{v.mail_kind}): "
            f"{v.summary} {marker}\n")
    log_path(home).parent.mkdir(parents=True, exist_ok=True)
    prims.append(log_path(home), line.encode("utf-8", "replace"))


def _step_cursor(home, name, v: Verdict, prims: Prims):
    cursor, _ = prims.read_cursor(home)
    canonical = _canonical_mail_name(name)
    if canonical not in cursor["mail"]:
        cursor["mail"].append(canonical)
        prims.write_cursor(home, cursor)


def _canonical_mail_name(name: str) -> str:
    while True:
        match = re.fullmatch(r"(.+)\.recovered-[0-9a-f]{32}\.mail", name)
        if match is None:
            return name
        name = match.group(1)


def _step_move(home, name, v: Verdict, prims: Prims,
               claim: Path, claim_dir: Path):
    raw, problem, inode = read_mail_snapshot(claim)
    if (problem is not None or inode != v.inode
            or hashlib.sha256(raw).hexdigest() != v.sha):
        _publish_claim(home, claim, claim_dir, name)
        raise _Changed(name)
    target_dir = done_dir(home)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem, suffix = os.path.splitext(name)
    collision = False
    attempt = 0
    while True:
        if attempt == 0:
            dest = target_dir / name
        elif attempt == 1:
            dest = target_dir / f"{stem}.{v.sha[:12]}{suffix}"
        else:
            dest = target_dir / f"{stem}.{v.sha[:12]}.{attempt - 1}{suffix}"

        try:
            os.link(claim, dest)
        except FileExistsError:
            old, old_problem, _ = read_mail_snapshot(dest)
            if (old_problem is None
                    and hashlib.sha256(old).hexdigest() == v.sha):
                _remove_private_claim(claim, claim_dir)
                return
            collision = True
            attempt += 1
            continue
        except FileNotFoundError:
            _publish_claim(home, claim, claim_dir, name)
            return

        # The pathname can be replaced between the pre-link read and link(2).
        # Keep only a link to the inode that was actually classified.
        linked_raw, linked_problem, linked_inode = read_mail_snapshot(dest)
        if (linked_problem is not None or linked_inode != v.inode
                or hashlib.sha256(linked_raw).hexdigest() != v.sha):
            # Leave an unexpected destination in place for inspection; a
            # check-then-unlink would recreate the same replacement race.
            _publish_claim(home, claim, claim_dir, name)
            raise _Changed(name)

        if collision:
            prims.append(log_path(home), (
                f"{prims.now()} mailman done-collision {clean_name(name)} -> "
                f"{clean_name(dest.name)}\n").encode("utf-8", "replace"))
        # The only removable source is inside our private exclusive claim
        # directory. A producer's replacement at the published inbox name is
        # never unlinked after a check.
        _remove_private_claim(claim, claim_dir)
        return


class _Changed(Exception):
    pass


def file_mail(home, name, v: Verdict, prims: Prims) -> bool:
    if v.kind != FILE:
        raise AssertionError(f"refusing to file a {v.kind} mail: {name}")
    claimed = _claim_source(home, name, v)
    if claimed is None:
        return False
    claim, claim_dir, owner_fd = claimed
    try:
        _step_digest(home, name, v, prims)
        _step_log(home, name, v, prims)
        _step_cursor(home, name, v, prims)
        _step_move(home, name, v, prims, claim, claim_dir)
    except _Changed:
        return False
    finally:
        _release_owner_lock(claim_dir, owner_fd)
    return True


def read_state(home) -> dict:
    empty = {"schema": 1, "reported": {},
             "bridge": {"last_run": None, "last_rc": None, "consecutive_failures": 0}}
    try:
        data = json.loads(state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    rep = data.get("reported")
    br = data.get("bridge")
    if isinstance(rep, dict):
        empty["reported"] = {str(k): str(v) for k, v in rep.items()}
    if isinstance(br, dict):
        empty["bridge"].update({k: br[k] for k in empty["bridge"] if k in br})
    return empty


def run_bridge(home, cfg: Config, state: dict, prims: Prims, run=subprocess.run) -> None:
    if not cfg.bridge_command:
        return
    env = dict(os.environ)
    env["FLEET_HOME"] = str(home)
    rc = None
    try:
        proc = run(cfg.bridge_command, cwd=str(home), env=env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=cfg.bridge_timeout)
        rc = proc.returncode
        tail = (proc.stderr or b"")[-2048:]
    except subprocess.TimeoutExpired:
        rc, tail = "timeout", b""
    except (OSError, ValueError) as exc:
        rc, tail = "spawn", str(exc).encode()
    bridge = state["bridge"]
    bridge["last_run"] = prims.now()
    bridge["last_rc"] = rc
    bridge["consecutive_failures"] = (
        0 if rc == 0 else int(bridge.get("consecutive_failures") or 0) + 1)
    if rc != 0 and tail:
        sys.stderr.write(f"mailman: bridge {rc}: "
                         f"{tail.decode('utf-8', 'replace').strip()[:500]}\n")


def _sort_pass(home, cfg, failsafe, prims):
    _recover_stale_claims(home)
    wakes, filed = [], 0
    for name in list_inbox(home):
        raw, problem, inode = read_mail_snapshot(inbox_dir(home) / name)
        v = classify(raw, problem, cfg, failsafe, inode=inode)
        if v.kind == WAKE:
            wakes.append((name, v))
        elif file_mail(home, name, v, prims):
            filed += 1
    return wakes, filed


def cmd_run(home, prims: Prims, *, timeout=None, interval=DEFAULT_INTERVAL,
            dry_run=False, include_reported=False,
            sleep=time.sleep, clock=time.monotonic, run=subprocess.run,
            out=None) -> int:
    out = sys.stdout if out is None else out
    home = Path(home)
    started = clock()
    while True:
        cfg, failsafe = load_config(home)
        if failsafe:
            sys.stderr.write(f"mailman: FAIL-SAFE, waking on every mail: {failsafe}\n")
        if dry_run:
            for name in list_inbox(home):
                raw, problem, inode = read_mail_snapshot(inbox_dir(home) / name)
                v = classify(raw, problem, cfg, failsafe, inode=inode)
                print(f"{v.kind} {name} reason={','.join(v.reasons) or '-'}", file=out)
            return 0
        state = read_state(home)
        if cfg is not None:
            run_bridge(home, cfg, state, prims, run=run)
        wakes, filed = _sort_pass(home, cfg, failsafe, prims)
        if filed:
            sys.stderr.write(f"mailman: filed {filed} mail(s)\n")
        reported = state["reported"]
        present = {n for n, _ in wakes}
        fresh = [(n, v) for n, v in wakes
                 if include_reported or reported.get(n) != (v.sha or "")[:12]]
        state["reported"] = {n: s for n, s in reported.items() if n in present}
        bridge_dead = (cfg is not None and cfg.bridge_command
                       and int(state["bridge"]["consecutive_failures"])
                       >= cfg.bridge_max_failures)
        if fresh:
            for name, v in fresh:
                sys.stderr.write(f"WAKE {name} reason={','.join(v.reasons)}\n")
                print(str(inbox_dir(home) / name), file=out)
            out.flush()
            for name, v in fresh:
                state["reported"][name] = (v.sha or "")[:12]
        prims.write_json(state_path(home), state)
        if fresh:
            return 0
        if bridge_dead:
            b = state["bridge"]
            sys.stderr.write("BRIDGE-FAILED %s %sx\n" % (
                b["last_rc"], b["consecutive_failures"]))
            return 4
        if timeout is not None and clock() - started >= timeout:
            return 3
        delay = interval
        if timeout is not None:
            delay = min(delay, max(0.0, timeout - (clock() - started)))
        if delay <= 0:
            return 3
        sleep(delay)


_DURATION_RE = re.compile(r"^(\d+)([mhd])$")
_ENTRY_RE = re.compile(r" <!-- mailman:(.+):([0-9a-f]{12}) -->$")


def parse_since(value: str, now: datetime) -> datetime:
    m = _DURATION_RE.match(value.strip())
    if m:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return now - timedelta(**{unit: int(m.group(1))})
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        raise FleetCliError(
            f"--since must be <n>m|h|d or YYYY-MM-DDTHH:MM:SSZ, got {value!r}") from None


def cmd_digest(home, since=DIGEST_DEFAULT_SINCE, now=None, out=None) -> int:
    out = sys.stdout if out is None else out
    now = now or datetime.now(timezone.utc)
    cutoff = parse_since(since, now)
    stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = digest_path(home).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    seen, entries = set(), []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        m = _ENTRY_RE.search(line)
        if not m:
            continue
        parts = line[2:m.start()].split(" | ", 3)
        if len(parts) != 4:
            continue
        ts, sender, kind, rest = parts
        key = (m.group(1), m.group(2))
        if key in seen:
            continue
        try:
            when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        seen.add(key)
        if when < cutoff:
            continue
        prefix = m.group(1) + " | "
        summary = rest[len(prefix):] if rest.startswith(prefix) else rest
        entries.append((ts, sender, kind, m.group(1), summary))
    if not entries:
        print(f"no filed mail since {stamp}", file=out)
        return 0
    entries.sort(key=lambda e: e[0])
    print(f"{len(entries)} filed since {stamp}", file=out)
    for label, idx in (("kind", 2), ("from", 1)):
        counts: dict = {}
        for e in entries:
            counts[e[idx]] = counts.get(e[idx], 0) + 1
        print(f"by {label}: " + ", ".join(
            f"{k}={counts[k]}" for k in sorted(counts)), file=out)
    for ts, sender, kind, name, summary in entries:
        print(f"{ts} {sender}/{kind} {name}: {summary}", file=out)
    return 0
