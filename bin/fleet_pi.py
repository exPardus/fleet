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


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def effective_state(job: Path) -> str | None:
    """The state file, corrected when the runner died without writing one."""
    state = _read(job / "state")
    if state in _LIVE_STATES and not _pid_alive(_read(job / "pid")):
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
        self.cwd = _read(job / "cwd")
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
        env = dict(os.environ)
        env["OPENROUTER_API_KEY"] = load_key()
        env["PI_CODING_AGENT_DIR"] = agent.as_posix()
        env.setdefault("PI_SKIP_VERSION_CHECK", "1")
        outcome = Outcome(slug)
        self.stalled = False
        self.last_event = time.monotonic()
        self.proc = subprocess.Popen(
            self.command(slug, prompt, resume), cwd=self.cwd, env=env,
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
    _write(job / "pid", f"{proc.pid}\n")


def cmd_spawn(args) -> int:
    slug = check_slug(args.model)
    effort = args.effort or os.environ.get("MCX_EFFORT") or "medium"
    if effort not in EFFORTS:
        raise WrapperError(f"unsupported effort: {effort!r}")
    find_pi()
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
    pid = _read(job / "pid")
    if pid and _pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)  # runner kills pi, marks stopped
        except OSError:
            pass
        deadline = time.monotonic() + 8
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
    _set_state(job, "stopped", only_from=_LIVE_STATES)
    return 0


def cmd_list(_args) -> int:
    root = jobs_root()
    for job in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        print(f"{job.name} {effective_state(job) or '?'} {_read(job / 'model', '?')}")
    return 0


def cmd_run(args) -> int:
    return Runner(job_dir(args.id)).run()


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
        return args.fn(args)
    except WrapperError as exc:
        print(f"fleet_pi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
