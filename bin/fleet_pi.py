#!/usr/bin/env python3
"""fleet_pi -- mcx-shaped external wrapper that runs one pi lane (stdlib only).

Fleet dispatches `--model pi:<openrouter-slug>:free` lanes through this file
exactly as it dispatches `codex:` lanes through `mcx`: one directory per job
under $MCX_DIR (default ./.mcx) holding `state`, `log`, `events.jsonl`,
`result`, `cwd`, `model`, `approval` and `effort`.

  spawn -m SLUG [-r EFFORT] PROMPT   print an 8-char job id, run detached
  result ID                          exit 2 live, 0 done (prints the answer),
                                     1 failed, stopped or unknown
  steer ID -                         follow-up turn on the same pi session
                                     (message on stdin); refuses a live job
  stop ID                            kill the job and mark it stopped
  list                               one line per job

Hard rules, enforced here and again in fleet:
  * only `<vendor>/<model>:free` slugs run; anything else exits 1 before pi
    starts. pi fuzzy-matches model names, so the exact slug is always passed
    together with `--provider openrouter`.
  * the outcome comes from pi's JSON events, never from the exit code
    (`--mode json` exits 0 on a provider failure).
  * a stall watchdog kills a job that emits no event for N minutes and marks
    it stopped.
  * patient retry settings (more attempts, longer backoff) are written to a
    per-job pi agent dir; pi's install telemetry setting is left at default
    because some models 403 without the attribution headers it controls.

Every pi run executes inside bubblewrap (`bwrap`): only the lane worktree, the
job's `home` and `sessions` directories and a private /tmp are writable; the
job's control files (cwd, pid, state, result, ...), the worktree's `.git` and
its gitdir, system dirs and the toolchain are read-only, and the rest of $HOME
(keys, other repos) does not exist inside. If bwrap is missing, is not a
root-owned system binary, or fails its probe the lane is refused; there is no
unsandboxed fallback and no escape variable.

The OpenRouter key is read from the environment or ~/.config/openrouter/env
and handed to the pi child only; it is never printed or written.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fleet_platform import PLATFORM, UnsupportedPlatformError

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*:free$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9]{8}$")
EFFORTS = ("low", "medium", "high", "xhigh")

DEFAULT_STALL_MINUTES = 5.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_MS = 4000
DEFAULT_RETRY_MAX_MS = 120000
DEFAULT_PROVIDER_RESTARTS = 1
DEFAULT_RESTART_PAUSE_SECONDS = 75.0

# Per-model pi `modelOverrides`. dots-3-note-preview's only provider rejects
# the registry's 460,800 max output with a bare 400; 32768 works.
MODEL_OVERRIDES = {
    "dots-studio/dots-3-note-preview:free": {"maxTokens": 32768},
}

_TRANSIENT_RE = re.compile(
    r"\b429\b|\b50[0-4]\b|rate[- ]?limit|no upstreams|overloaded|temporarily",
    re.IGNORECASE)
_TERMINAL_STATES = {"done", "failed", "stopped"}
_LIVE_STATES = {"starting", "running"}


class WrapperError(Exception):
    """A user-facing failure; main() prints it and exits 1."""


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def _env_number(name, default, cast=float):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise WrapperError(f"{name} must be a number, got {raw!r}")
    if value < 0:
        raise WrapperError(f"{name} must not be negative, got {raw!r}")
    return value


def check_slug(model) -> str:
    """Return the bare slug, or raise unless it is an exact `:free` slug."""
    if isinstance(model, str) and model.startswith("pi:"):
        model = model[3:]
    if not isinstance(model, str) or not SLUG_RE.match(model):
        raise WrapperError(
            f"refusing model {model!r}: only exact <vendor>/<model>:free "
            "OpenRouter slugs may run on pi lanes")
    return model


def jobs_root() -> Path:
    return Path(os.environ.get("MCX_DIR") or (Path.cwd() / ".mcx"))


def job_dir(job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id or ""):
        raise WrapperError(f"unknown worker: {job_id!r}")
    return jobs_root() / job_id


ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "TERM", "TMPDIR", "OPENROUTER_API_KEY")
# Exact names the scripted-pi test fixtures read; honoured only under pytest.
_TEST_ENV_NAMES = (
    "FLEET_PI_FAKE_SCENARIO", "FLEET_PI_FAKE_STATE", "FLEET_PI_FAKE_LOG",
    "FLEET_PI_FAKE_BWRAP_LOG", "FLEET_PI_FAKE_BWRAP_FAIL")


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def child_env() -> dict:
    """The environment pi (and the shell it runs) receives: exact allowlisted
    names only, so unrelated secrets in the operator's session never reach a
    free model's tools. There is no pass-everything switch."""
    names = set(ENV_ALLOWLIST)
    if _under_pytest():
        names.update(_TEST_ENV_NAMES)
    return {k: v for k, v in os.environ.items() if k in names}


def find_pi() -> str:
    explicit = os.environ.get("FLEET_PI_BIN")
    if explicit:
        return explicit
    local = (Path.home() / ".local" / "share" / "fleet-pi" / "node_modules"
             / ".bin" / "pi")
    if local.is_file():
        return local.as_posix()
    found = shutil.which("pi")
    if found:
        return found
    raise WrapperError(
        "pi not found: install @earendil-works/pi-coding-agent under "
        "~/.local/share/fleet-pi or set FLEET_PI_BIN")


def load_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    path = Path(os.environ.get("FLEET_PI_KEY_FILE")
                or Path.home() / ".config" / "openrouter" / "env")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    except OSError:
        pass
    raise WrapperError("OPENROUTER_API_KEY missing: set it or fill the key file")


# ---------------------------------------------------------------------------
# bubblewrap sandbox (POSIX/Linux; refuse when unavailable, never fall back)
# ---------------------------------------------------------------------------

def _trusted_bwrap(path: str) -> bool:
    """A bwrap that only root can replace: root-owned, not group/world
    writable, in a root-owned directory that others cannot write."""
    try:
        real = _real(path)
        for target in (real, os.path.dirname(real)):
            st = os.stat(target)
            if st.st_uid != 0 or st.st_mode & 0o022:
                return False
        return os.access(real, os.X_OK)
    except OSError:
        return False


def find_bwrap() -> str:
    # FLEET_PI_TEST_BWRAP swaps in a scripted bwrap for the test suite only;
    # outside pytest it is ignored, as is any other bwrap-selecting variable.
    override = os.environ.get("FLEET_PI_TEST_BWRAP")
    if override and _under_pytest():
        return override
    found = shutil.which("bwrap")
    if not found:
        raise WrapperError(
            "bwrap not found: pi lanes run only inside bubblewrap "
            "(install the bubblewrap package); refusing to run unsandboxed")
    if not _trusted_bwrap(found):
        raise WrapperError(
            f"bwrap at {found} is not a root-owned system binary; "
            "refusing to run pi unsandboxed")
    return found


def _real(path) -> str:
    return os.path.realpath(str(path))


def _install_root(pi_bin: str) -> str:
    """The directory holding the pi install: the parent of the node_modules
    that contains the resolved pi entry point, else its own directory."""
    real = Path(_real(pi_bin))
    parts = real.parts
    if "node_modules" in parts:
        return Path(*parts[:parts.index("node_modules")]).as_posix()
    return real.parent.as_posix()


def _git_dirs(cwd: str):
    """(worktree gitdir, common dir) for a linked worktree, else (None, None)
    or (.git dir, None) for a plain checkout."""
    dotgit = Path(cwd) / ".git"
    if dotgit.is_dir():
        return dotgit.as_posix(), None
    text = _read(dotgit)
    if not text or not text.startswith("gitdir:"):
        return None, None
    gitdir = Path(text.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = Path(cwd) / gitdir
    gitdir = Path(_real(gitdir))
    common = _read(gitdir / "commondir")
    if common:
        return gitdir.as_posix(), _real(gitdir / common)
    return gitdir.as_posix(), None


def _sandbox_base_args() -> list:
    args = []
    for top in ("/usr", "/etc"):
        if os.path.isdir(top):
            args += ["--ro-bind", top, top]
    for top in ("/bin", "/sbin", "/lib", "/lib32", "/lib64"):
        if os.path.islink(top):
            args += ["--symlink", os.readlink(top), top]
        elif os.path.isdir(top):
            args += ["--ro-bind", top, top]
    # /etc/resolv.conf is usually a symlink into /run (systemd-resolved).
    resolv = _real("/etc/resolv.conf")
    if resolv.startswith("/run/") and os.path.exists(resolv):
        args += ["--ro-bind", os.path.dirname(resolv), os.path.dirname(resolv)]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
             "--unshare-pid", "--unshare-ipc", "--unshare-uts",
             "--unshare-cgroup-try", "--new-session", "--die-with-parent"]
    return args


_probe_ok = set()


def probe_bwrap(bwrap: str) -> None:
    """Run a trivial command in the real sandbox shape; raise if it fails."""
    if bwrap in _probe_ok:
        return
    try:
        proc = subprocess.run(
            [bwrap, *_sandbox_base_args(), "--clearenv", "--", "/usr/bin/true"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WrapperError(
            f"bwrap probe failed ({exc}); refusing to run pi unsandboxed")
    if proc.returncode != 0:
        raise WrapperError(
            "bwrap probe failed (" + (proc.stderr.strip()[:200]
                                      or f"exit {proc.returncode}")
            + "); refusing to run pi unsandboxed")
    _probe_ok.add(bwrap)


def _home_real() -> str:
    return _real(Path.home())


def _covers_home(path) -> bool:
    """True when `path` is the real HOME or one of its ancestors."""
    home = Path(_home_real())
    target = Path(_real(path))
    return target == home or target in home.parents


def _check_mount(path: str) -> str:
    if _covers_home(path):
        raise WrapperError(
            f"refusing to mount {path}: it is or contains $HOME "
            "(keys and other repositories would be visible to the lane)")
    return path


def check_lane_cwd(cwd) -> str:
    """Return the real lane worktree path, or raise. The sandbox binds this
    path read-write, so it must be a git checkout and never HOME or a parent
    of it; for a linked worktree the gitdir must point back at it."""
    if not cwd or not os.path.isabs(cwd):
        raise WrapperError(f"refusing lane directory {cwd!r}: not absolute")
    real = _real(cwd)
    if not os.path.isdir(real):
        raise WrapperError(f"refusing lane directory {cwd!r}: not a directory")
    if _covers_home(real):
        raise WrapperError(
            f"refusing lane directory {cwd!r}: it is or contains $HOME")
    dotgit = Path(real) / ".git"
    if dotgit.is_dir():
        return real
    gitdir, common = _git_dirs(real)
    if not gitdir:
        raise WrapperError(
            f"refusing lane directory {cwd!r}: not a git worktree")
    back = _read(Path(gitdir) / "gitdir")
    if not back or _real(back) != _real(dotgit):
        raise WrapperError(
            f"refusing lane directory {cwd!r}: its gitdir does not belong "
            "to this worktree")
    return real


def sandbox_command(cmd: list, cwd: str, job: Path, env: dict,
                    bwrap: str | None = None):
    """Wrap `cmd` (cmd[0] is pi) in bwrap; return (argv, child_env). Pure: no
    filesystem writes.

    Writable: cwd, the job's `home` (also the uv cache), `sessions` and `pi-agent`
    (minus its settings.json/models.json), /tmp.
    Read-only: system dirs, the pi install, the node runtime, uv and its
    python builds, the rest of the job dir (control files, agent config), the
    worktree's `.git` and gitdir, and the repository's common git dir. Nothing
    else in the real HOME is mounted.

    The environment travels in `child_env` (Popen env=), never in argv, so
    secrets stay out of /proc/<pid>/cmdline; there is no --clearenv because
    the dict is already the allowlist."""
    bwrap = bwrap or find_bwrap()
    job = Path(job)
    home = (job / "home").as_posix()
    env = dict(env)
    path_dirs = []
    ro = [_install_root(cmd[0])]
    node = shutil.which("node", path=env.get("PATH"))
    if node:
        node_real = Path(_real(node))
        if node_real.parent.name == "bin":
            ro.append(node_real.parent.parent.as_posix())
        else:
            ro.append(node_real.as_posix())
        path_dirs.append(node_real.parent.as_posix())
    uv = shutil.which("uv", path=env.get("PATH"))
    if uv:
        ro.append(uv)
        path_dirs.append(os.path.dirname(uv))
        uv_python = Path.home() / ".local" / "share" / "uv" / "python"
        if uv_python.is_dir():
            ro.append(uv_python.as_posix())
            env["UV_PYTHON_INSTALL_DIR"] = uv_python.as_posix()
        env["UV_CACHE_DIR"] = home + "/.cache/uv"
    gitdir, common = _git_dirs(cwd)
    if common:
        ro.append(common)
    args = [bwrap, *_sandbox_base_args()]
    seen = set()
    for path in ro:
        _check_mount(path)
        if path not in seen and os.path.exists(path):
            seen.add(path)
            args += ["--ro-bind", path, path]
    args += ["--bind", cwd, cwd]
    # Later mounts win: the worktree's git redirection points stay read-only,
    # so a lane cannot repoint git at a config of its own.
    for path in (Path(cwd) / ".git").as_posix(), gitdir:
        if path and os.path.exists(path):
            args += ["--ro-bind", path, path]
    # The jobs root is replaced by an empty tmpfs so sibling jobs vanish; this
    # job comes back read-only except its home and sessions directories.
    args += ["--tmpfs", job.parent.as_posix(),
             "--ro-bind", job.as_posix(), job.as_posix()]
    for sub in ("home", "sessions", "pi-agent"):
        if sub == "pi-agent" and not (job / sub).is_dir():
            continue
        args += ["--bind", (job / sub).as_posix(), (job / sub).as_posix()]
    # pi keeps locks and credentials in its agent dir, but the settings the
    # wrapper wrote (retry knobs, model overrides) stay read-only.
    for name in ("settings.json", "models.json"):
        conf = job / "pi-agent" / name
        if conf.is_file():
            args += ["--ro-bind", conf.as_posix(), conf.as_posix()]
    args += ["--chdir", cwd]
    env["HOME"] = home
    env["TMPDIR"] = "/tmp"
    env["PATH"] = ":".join(path_dirs + ["/usr/local/bin", "/usr/bin", "/bin"])
    return args + ["--", *cmd], env


# ---------------------------------------------------------------------------
# job directory helpers
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path, default=None):
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return default


def _set_state(job: Path, state: str, only_from=None) -> bool:
    if only_from is not None and _read(job / "state") not in only_from:
        return False
    _write(job / "state", state + "\n")
    return True


def _proc_start(pid):
    """Kernel start time (clock ticks) of `pid`, or None if it is gone."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError, TypeError):
        return None


def _write_pid(job: Path, pid: int) -> None:
    _write(job / "pid", f"{pid} {_proc_start(pid) or 0}\n")


def _runner_pid(job: Path):
    """The live runner's pid, or None. A pid is trusted only when its start
    time matches the one recorded at launch, it leads its own session (the
    runner is started with start_new_session) and its command line is this
    wrapper's `_run <job>`; a recycled or rewritten pid fails all three."""
    parts = (_read(job / "pid") or "").split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    pid, started = int(parts[0]), int(parts[1])
    if pid <= 1 or not started or _proc_start(pid) != started:
        return None
    try:
        if os.getpgid(pid) != pid:
            return None
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    if b"_run" not in argv or job.name.encode() not in argv:
        return None
    return pid


def effective_state(job: Path) -> str | None:
    """The state file, corrected when the runner died without writing one."""
    state = _read(job / "state")
    if state in _LIVE_STATES and _runner_pid(job) is None:
        return "failed"
    return state


def write_agent_config(job: Path, slug: str) -> Path:
    """Per-job pi agent dir: patient retry plus per-model overrides only."""
    agent = job / "pi-agent"
    agent.mkdir(exist_ok=True)
    settings = {"retry": {
        "enabled": True,
        "maxRetries": int(_env_number("FLEET_PI_MAX_RETRIES",
                                      DEFAULT_MAX_RETRIES, int)),
        "baseDelayMs": int(_env_number("FLEET_PI_RETRY_BASE_MS",
                                       DEFAULT_RETRY_BASE_MS, int)),
        "maxAgentDelayMs": int(_env_number("FLEET_PI_RETRY_MAX_MS",
                                           DEFAULT_RETRY_MAX_MS, int)),
    }}
    _write(agent / "settings.json", json.dumps(settings))
    overrides = {k: v for k, v in MODEL_OVERRIDES.items() if k == slug}
    if overrides:
        _write(agent / "models.json", json.dumps(
            {"providers": {"openrouter": {"modelOverrides": overrides}}}))
    elif (agent / "models.json").exists():
        (agent / "models.json").unlink()
    return agent


# ---------------------------------------------------------------------------
# event interpretation (outcome comes from here, never the exit code)
# ---------------------------------------------------------------------------

class Outcome:
    """Fold pi JSON events into a verdict."""

    def __init__(self, slug: str):
        self.slug = slug
        self.saw_agent_end = False
        self.final_text = ""
        self.final_thinking = ""
        self.last_error = None       # cleared by a later good assistant message
        self.retries = 0
        self.tool_calls = 0
        self.messages = 0
        self.model_mismatch = None
        self.tokens_in = 0
        self.tokens_out = 0

    def feed(self, event: dict) -> list[str]:
        """Update state from one event; return human log lines for it."""
        kind = event.get("type")
        out = []
        if kind == "message_end":
            msg = event.get("message") or {}
            if msg.get("role") == "assistant":
                self.messages += 1
                usage = msg.get("usage") or {}
                self.tokens_in += (usage.get("input") or 0) + (
                    usage.get("cacheRead") or 0)
                self.tokens_out += usage.get("output") or 0
                got = msg.get("model")
                if got and got != self.slug and self.model_mismatch is None:
                    self.model_mismatch = got
                stop = msg.get("stopReason")
                if stop in ("error", "aborted"):
                    self.last_error = (msg.get("errorMessage") or stop)[:300]
                    out.append(f"error: {self.last_error}")
                else:
                    self.last_error = None
                    content = msg.get("content")
                    if isinstance(content, str):
                        text, thinking = content, ""
                    else:
                        parts = content or []
                        text = "".join(c.get("text", "") for c in parts
                                       if isinstance(c, dict)
                                       and c.get("type") == "text")
                        thinking = "".join(c.get("thinking", "") for c in parts
                                           if isinstance(c, dict)
                                           and c.get("type") == "thinking")
                    if text.strip():
                        self.final_text = text
                        out.append("assistant: " + " ".join(text.split())[:200])
                    if thinking.strip():
                        self.final_thinking = thinking
        elif kind == "tool_execution_start":
            self.tool_calls += 1
            args = json.dumps(event.get("args"), ensure_ascii=False)
            out.append(f"tool {event.get('toolName')}: {args[:160]}")
        elif kind == "tool_execution_end" and event.get("isError"):
            out.append(f"tool {event.get('toolName')} ERROR")
        elif kind == "auto_retry_start":
            self.retries += 1
            out.append("retry {}/{} in {}ms: {}".format(
                event.get("attempt"), event.get("maxAttempts"),
                event.get("delayMs"), str(event.get("errorMessage"))[:160]))
        elif kind == "auto_retry_end":
            if event.get("success") is False:
                self.last_error = str(event.get("finalError") or "retry failed")[:300]
                out.append(f"error: {self.last_error}")
        elif kind == "error":
            detail = event.get("message") or event.get("error") or "error event"
            self.last_error = str(detail)[:300]
            out.append(f"error: {self.last_error}")
        elif kind == "agent_end":
            if not event.get("willRetry"):
                self.saw_agent_end = True
            else:
                self.saw_agent_end = False
        return out

    def verdict(self):
        """('done', text) or ('failed', reason)."""
        if self.model_mismatch:
            return "failed", (f"model mismatch: asked {self.slug}, "
                              f"got {self.model_mismatch}")
        if self.last_error:
            return "failed", self.last_error
        if not self.saw_agent_end:
            return "failed", "pi exited without agent_end"
        if not self.messages:
            return "failed", "pi produced no assistant message"
        text = self.final_text.strip()
        if not text and self.final_thinking.strip():
            text = "[answer found only in the thinking block]\n" + self.final_thinking.strip()
        return "done", text or "(no assistant text)"


# ---------------------------------------------------------------------------
# the detached runner
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, job: Path):
        self.job = job
        self.slug = _read(job / "model")
        self.cwd = check_lane_cwd(_read(job / "cwd"))
        self.effort = _read(job / "effort") or "medium"
        self.stall_seconds = _env_number(
            "FLEET_PI_STALL_MINUTES", DEFAULT_STALL_MINUTES) * 60
        self.restarts_left = int(_env_number(
            "FLEET_PI_PROVIDER_RESTARTS", DEFAULT_PROVIDER_RESTARTS, int))
        self.restart_pause = _env_number(
            "FLEET_PI_RESTART_PAUSE_SECONDS", DEFAULT_RESTART_PAUSE_SECONDS)
        self.proc = None
        self.stop_requested = False
        self.stalled = False
        self.last_event = time.monotonic()
        self.log = open(job / "log", "a", encoding="utf-8", buffering=1)
        self.events = open(job / "events.jsonl", "ab", buffering=0)

    def say(self, line: str) -> None:
        self.log.write(line + "\n")

    def kill_pi(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, AttributeError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                proc.kill()

    def on_term(self, *_):
        self.stop_requested = True
        self.kill_pi()
        _set_state(self.job, "stopped", only_from=_LIVE_STATES)
        os._exit(0)

    def command(self, slug: str, prompt: str, resume: bool) -> list[str]:
        cmd = [find_pi(), "--provider", "openrouter", "--model", slug,
               "--mode", "json", "--session-dir", (self.job / "sessions").as_posix()]
        if not os.environ.get("FLEET_PI_CONTEXT_FILES"):
            cmd.append("-nc")
        if resume:
            cmd.append("--continue")
        if self.effort in EFFORTS:
            cmd += ["--thinking", self.effort]
        cmd += ["--", prompt]
        return cmd

    def run_once(self, prompt: str, resume: bool) -> Outcome:
        slug = check_slug(self.slug)
        agent = write_agent_config(self.job, slug)
        env = child_env()
        env["OPENROUTER_API_KEY"] = load_key()
        env["PI_CODING_AGENT_DIR"] = agent.as_posix()
        env.setdefault("PI_SKIP_VERSION_CHECK", "1")
        outcome = Outcome(slug)
        self.stalled = False
        self.last_event = time.monotonic()
        for sub in ("home", "sessions"):
            (self.job / sub).mkdir(exist_ok=True)
        bwrap = find_bwrap()
        probe_bwrap(bwrap)
        argv, sandbox_env = sandbox_command(
            self.command(slug, prompt, resume), self.cwd, self.job, env, bwrap)
        self.proc = subprocess.Popen(
            argv, cwd=self.cwd, env=sandbox_env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)

        def read_stdout():
            for raw in self.proc.stdout:  # bytes: split on LF only
                self.last_event = time.monotonic()
                self.events.write(raw if raw.endswith(b"\n") else raw + b"\n")
                try:
                    event = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(event, dict):
                    for line in outcome.feed(event):
                        self.say(line)

        def read_stderr():
            for raw in self.proc.stderr:
                text = raw.decode("utf-8", errors="replace").rstrip()
                if text:
                    self.say("stderr: " + text[:300])

        threads = [threading.Thread(target=read_stdout, daemon=True),
                   threading.Thread(target=read_stderr, daemon=True)]
        for t in threads:
            t.start()
        while self.proc.poll() is None:
            time.sleep(0.2)
            if (self.stall_seconds
                    and time.monotonic() - self.last_event > self.stall_seconds):
                self.stalled = True
                self.say(f"stall: no event for {self.stall_seconds / 60:g} min -- killing")
                self.kill_pi()
        for t in threads:
            t.join(timeout=5)
        return outcome

    def finish(self, state: str, text: str) -> None:
        if state == "done":
            _write(self.job / "result", text.rstrip("\n") + "\n")
            (self.job / "error").unlink(missing_ok=True)
        else:
            _write(self.job / "error", text.rstrip("\n") + "\n")
        _set_state(self.job, state, only_from=_LIVE_STATES)
        self.say(f"state: {state}")

    def run(self) -> int:
        job = self.job
        signal.signal(signal.SIGTERM, self.on_term)
        try:
            turn = int(_read(job / "turn", "1") or 1)
            prompt = _read(job / "prompt") or ""
            resume = turn > 1
            (job / "result").unlink(missing_ok=True)
            (job / "error").unlink(missing_ok=True)
            _set_state(job, "running")
            self.say(f"turn {turn} start")
            while True:
                self.events.write((json.dumps(
                    {"type": "fleet_pi", "event": "run_start", "turn": turn,
                     "resume": resume}) + "\n").encode())
                outcome = self.run_once(prompt, resume)
                if self.stalled:
                    self.finish("stopped", f"stalled: no event for "
                                f"{self.stall_seconds / 60:g} min")
                    return 0
                state, text = outcome.verdict()
                if (state == "failed" and self.restarts_left > 0
                        and _TRANSIENT_RE.search(text or "")):
                    self.restarts_left -= 1
                    self.say(f"provider failure ({text[:120]}); "
                             f"restarting in {self.restart_pause:g}s")
                    time.sleep(self.restart_pause)
                    prompt, resume = ("Continue the task from where you left off.",
                                      True)
                    continue
                self.finish(state, text)
                return 0
        except WrapperError as exc:
            self.finish("failed", str(exc))
            return 0
        except BaseException as exc:  # noqa: BLE001 - never leave state live
            self.finish("failed", f"{type(exc).__name__}: {exc}")
            return 0


# ---------------------------------------------------------------------------
# verbs
# ---------------------------------------------------------------------------

def _launch_runner(job: Path) -> None:
    """Start the detached runner and record its pid before returning, so a
    reader never sees a live state with no (or a stale) pid."""
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_run", job.name],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=dict(os.environ), cwd=os.getcwd(),
        start_new_session=True)
    _write_pid(job, proc.pid)


def cmd_spawn(args) -> int:
    slug = check_slug(args.model)
    check_lane_cwd(os.getcwd())
    effort = args.effort or os.environ.get("MCX_EFFORT") or "medium"
    if effort not in EFFORTS:
        raise WrapperError(f"unsupported effort: {effort!r}")
    find_pi()
    probe_bwrap(find_bwrap())
    load_key()
    jobs_root().mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:8]
    job = jobs_root() / job_id
    job.mkdir()
    _write(job / "cwd", os.getcwd() + "\n")
    _write(job / "model", slug + "\n")
    _write(job / "approval", (os.environ.get("MCX_APPROVAL") or "never") + "\n")
    _write(job / "effort", effort + "\n")
    _write(job / "prompt", args.prompt)
    _write(job / "turn", "1\n")
    _write(job / "state", "starting\n")
    _write(job / "pi", "1\n")
    _launch_runner(job)
    print(job_id)
    return 0


def cmd_result(args) -> int:
    job = job_dir(args.id)
    if not job.is_dir():
        print(f"unknown worker: {args.id}", file=sys.stderr)
        return 1
    state = effective_state(job)
    if state in _LIVE_STATES:
        return 2
    if state == "done":
        sys.stdout.write(_read(job / "result", "") + "\n")
        return 0
    print(f"worker {args.id} {state or 'unknown'}: "
          f"{_read(job / 'error', 'no result')}", file=sys.stderr)
    return 1


def cmd_steer(args) -> int:
    job = job_dir(args.id)
    if not job.is_dir():
        print(f"unknown worker: {args.id}", file=sys.stderr)
        return 1
    if effective_state(job) in _LIVE_STATES:
        raise WrapperError(f"worker {args.id} is running; stop it or wait")
    message = sys.stdin.read() if args.message == "-" else args.message
    if not message.strip():
        raise WrapperError("empty steer message")
    turn = int(_read(job / "turn", "1") or 1) + 1
    _write(job / "prompt", message)
    _write(job / "turn", f"{turn}\n")
    _write(job / "state", "starting\n")
    _launch_runner(job)
    return 0


def cmd_stop(args) -> int:
    job = job_dir(args.id)
    if not job.is_dir():
        print(f"unknown worker: {args.id}", file=sys.stderr)
        return 1
    pid = _runner_pid(job)  # never signal a pid that fails the identity check
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)  # runner kills pi, marks stopped
        except OSError:
            pass
        deadline = time.monotonic() + 8
        while _runner_pid(job) and time.monotonic() < deadline:
            time.sleep(0.1)
    _set_state(job, "stopped", only_from=_LIVE_STATES)
    return 0


def cmd_list(_args) -> int:
    root = jobs_root()
    for job in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        print(f"{job.name} {effective_state(job) or '?'} {_read(job / 'model', '?')}")
    return 0


def cmd_run(args) -> int:
    job = job_dir(args.id)
    try:
        runner = Runner(job)
    except WrapperError as exc:
        _write(job / "error", str(exc) + "\n")
        _set_state(job, "failed", only_from=_LIVE_STATES)
        return 0
    return runner.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet_pi", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    sp = sub.add_parser("spawn")
    sp.add_argument("-m", "--model", required=True)
    sp.add_argument("-r", "--effort")
    sp.add_argument("prompt")
    sp.set_defaults(fn=cmd_spawn)
    for name, fn in (("result", cmd_result), ("stop", cmd_stop), ("_run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.set_defaults(fn=fn)
    st = sub.add_parser("steer")
    st.add_argument("id")
    st.add_argument("message")
    st.set_defaults(fn=cmd_steer)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        try:
            PLATFORM.require_pi_lanes()
        except UnsupportedPlatformError as exc:
            raise WrapperError(str(exc))
        return args.fn(args)
    except WrapperError as exc:
        print(f"fleet_pi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
