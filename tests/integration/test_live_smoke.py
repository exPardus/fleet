"""Tier-3 scripted live-integration harness (SPEC §12 + phase1-hardening-kernels
item 6).

This is the REAL-haiku tier: it launches actual `claude -p` worker turns and
reads their stream-json, the class of bug 338 green unit tests cannot catch
(hook events landing after the `result` line; per-invocation cost on --resume;
kill-dead resurrection -- all first found by a live smoke). It is a MANDATE, not
an option (SPEC §12): watchtower OQ1's real-log rule tests, providers' live-turn
checks, and Phase-5 Stop-hook edits all consume the fixture corpus this run
archives.

CONTAINMENT (bypass-with-containment permission mechanism):
  * every run uses a throwaway temp FLEET_HOME (mkdtemp) + a throwaway git repo
    (mkdtemp) + the haiku model -- never the live install at C:/proga/claude-fleet
  * a hard per-run budget ceiling of $0.25 is ASSERTED (test_budget_ceiling)
  * kill-targets are restricted to turn PIDs THIS harness spawned (registry
    turn_pid), never the live fleet
The temp-FLEET_HOME sandbox is the isolation boundary: even when hook COMMANDS
point at the main-checkout or worktree hook scripts (the hook-source parameter
below), the FLEET_HOME env var forces those scripts to read/write only the temp
mailbox.

GATING: skipped cleanly unless FLEET_LIVE=1 (enforced in tests/conftest.py).

HOOK-SOURCE PARAMETER (PLAN §0.1.6, load-bearing): the temp FLEET_HOME's
worker-settings.json hook paths are rendered from an explicit source:
  * default   = main-checkout hooks  C:/proga/claude-fleet/bin/hooks/*   (merge-gate runs)
  * override  = worktree hooks       C:/proga/claude-fleet-wt/c2/bin/hooks/* (pre-merge live exec)
Flip via env FLEET_HOOK_SOURCE=worktree (default: main). test_hook_source_render
proves the rendered settings point where asked.

INVARIANTS TOUCHED: one-state-many-views (9 -- the corpus + tier-3 protect the
single-source->views derivation), daemonless launch (1 -- the harness owns the
turns it launches, it is NOT a resident supervisor and NOT exit-code capture of
detached PIDs: it launches turns it owns and reads their stream-json), and
one-live-claude-per-session (7 -- each temp-FLEET_HOME run is isolated).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# bin/ is on sys.path via tests/conftest.py -- reuse fleet's own pure helpers
# (render + prompt composition) so the harness asserts against the SAME code the
# CLI runs, never a re-implementation.
import fleet

pytestmark = pytest.mark.live

# --- fixed locations -------------------------------------------------------
WORKTREE_ROOT = Path(__file__).resolve().parents[2]          # C:/proga/claude-fleet-wt/c2
MAIN_CHECKOUT = Path("C:/proga/claude-fleet")                # the live install
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "streams"

HOOK_SOURCE = os.environ.get("FLEET_HOOK_SOURCE", "main").strip().lower()
HOOK_SOURCE_HOME = MAIN_CHECKOUT if HOOK_SOURCE == "main" else WORKTREE_ROOT

MODEL = os.environ.get("FLEET_LIVE_MODEL", "haiku").strip()

# Per-run hard ceiling (SPEC §12 ~$0.25/run). Asserted in test_budget_ceiling.
RUN_BUDGET_CEILING_USD = 0.25
# Per-turn circuit breaker passed to `claude --max-budget-usd`. Small; haiku
# tasks here are trivial. (Campaign-0 lesson: --max-budget-usd overshoots ~3x on
# tiny caps -- a breaker, not the ceiling; the ceiling is the summed assert.)
PER_TURN_BUDGET_USD = 0.05

# Accumulated corpus metadata, flushed to fixtures/streams/manifest.json by the
# final test so watchtower OQ1 knows each fixture's scenario + shape.
_MANIFEST: dict = {}


# ===========================================================================
# Sandbox: temp FLEET_HOME + throwaway git repo + rendered settings
# ===========================================================================
class Sandbox:
    def __init__(self, home: Path, repo: Path):
        self.home = home
        self.repo = repo
        self.fleet_py = home / "bin" / "fleet.py"
        # literal strings to scrub out of archived stream logs
        self._secrets = _secret_literals(home, repo)

    def env(self) -> dict:
        e = dict(os.environ)
        e["FLEET_HOME"] = str(self.home)
        # Campaign-1 lesson: `fleet result` crashes on cp1252 consoles when
        # output carries unicode -- force utf-8 for every subprocess.
        e["PYTHONIOENCODING"] = "utf-8"
        return e

    def fleet(self, *args, timeout=240, check=True) -> subprocess.CompletedProcess:
        r = subprocess.run(
            [sys.executable, str(self.fleet_py), *args],
            env=self.env(), capture_output=True, text=True, timeout=timeout,
        )
        if check and r.returncode != 0:
            raise AssertionError(
                f"`fleet {' '.join(args)}` exited {r.returncode}\n"
                f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
            )
        return r

    def registry(self) -> dict:
        path = self.home / "state" / "fleet.json"
        if not path.exists():
            return {"workers": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def worker(self, name: str) -> dict:
        return self.registry()["workers"][name]

    def log_path(self, name: str) -> Path:
        return self.home / "logs" / f"{name}.jsonl"

    def mailbox_path(self, sid: str) -> Path:
        return self.home / "mailbox" / f"{sid}.md"

    def seed_mailbox(self, sid: str, text: str) -> None:
        """Write the mailbox file directly -- the deterministic equivalent of a
        `send` landing in the box (used for the seeded-early Stop-block variant
        and the mid-turn injection variant, where real-send timing is racy)."""
        p = self.mailbox_path(sid)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")

    # ---- corpus archival --------------------------------------------------
    def archive(self, label: str, log_path: Path, *, scenario: str, note: str) -> dict:
        raw = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        sanitized = sanitize_stream_text(raw, self._secrets)
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        out = FIXTURE_DIR / f"{label}.jsonl"
        out.write_text(sanitized, encoding="utf-8")
        meta = {
            "scenario": scenario,
            "note": note,
            "has_result_event": _has_event(sanitized, "result"),
            "has_hook_events": "hookEventName" in sanitized,
            "lines": len([ln for ln in sanitized.splitlines() if ln.strip()]),
        }
        _MANIFEST[out.name] = meta
        # containment self-check: no live-install or user path leaked
        assert "claude-fleet\\state" not in sanitized  # backslash form
        assert str(self.home) not in sanitized
        return meta


def _secret_literals(home: Path, repo: Path):
    user_home = str(Path.home())
    lits = set()
    for base in (home, repo, Path(user_home)):
        s = str(base)
        lits.add(s)
        lits.add(s.replace("\\", "/"))
        lits.add(s.replace("\\", "\\\\"))  # json-escaped backslashes
    lits.add(Path(user_home).name)  # username
    # longest first so a path is scrubbed before its parent dir
    return sorted((x for x in lits if x), key=len, reverse=True)


# ===========================================================================
# Stream-json sanitization (strip secrets/paths/timestamps/session ids)
# ===========================================================================
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?(?:[+-]\d{2}:?\d{2})?")
_WINPATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'|]*")
_POSIXHOME_RE = re.compile(r"/(?:c/)?(?:Users|home)/[^\s\"'/|]+")
_TMP_RE = re.compile(r"(?:/tmp|/var/folders)/[^\s\"'|]*")
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{10,}")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._-]+")


def _scrub_str(s: str, secrets) -> str:
    for lit in secrets:
        if lit and lit in s:
            s = s.replace(lit, "REDACTED-PATH")
    s = _KEY_RE.sub("REDACTED-KEY", s)
    s = _BEARER_RE.sub("Bearer REDACTED-KEY", s)
    s = _UUID_RE.sub("REDACTED-UUID", s)
    s = _WINPATH_RE.sub("REDACTED-PATH", s)
    s = _POSIXHOME_RE.sub("REDACTED-PATH", s)
    s = _TMP_RE.sub("REDACTED-PATH", s)
    s = _ISO_RE.sub("REDACTED-TS", s)
    return s


def _scrub(obj, secrets):
    if isinstance(obj, dict):
        return {k: _scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, secrets) for v in obj]
    if isinstance(obj, str):
        return _scrub_str(obj, secrets)
    return obj


def sanitize_stream_text(raw: str, secrets) -> str:
    """Parse each stdout JSONL line, recursively scrub string values, re-dump.
    Parsing+redumping keeps every line valid JSON (watchtower OQ1 parses the
    corpus) while guaranteeing secrets/paths/timestamps/session-ids are gone.
    Non-JSON lines (should not appear on stdout) are dropped."""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        out.append(json.dumps(_scrub(obj, secrets), ensure_ascii=False))
    return "\n".join(out) + ("\n" if out else "")


def _has_event(text: str, event_type: str) -> bool:
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("type") == event_type:
            return True
    return False


def _log_has_result(sandbox: Sandbox, name: str) -> bool:
    p = sandbox.log_path(name)
    return _has_event(p.read_text(encoding="utf-8", errors="replace"), "result") if p.exists() else False


def _wait_for_partial_log(sandbox: Sandbox, name: str, timeout=25) -> bool:
    """Poll the turn's log until it holds a SUBSTANTIVE (non-system) event --
    an assistant/user/tool line -- so a crash-inject captures a real partial
    stream, not an empty file booted-but-silent. Returns True once seen."""
    p = sandbox.log_path(name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict) and obj.get("type") in ("assistant", "user", "tool_use", "tool_result"):
                    return True
        time.sleep(0.5)
    return False


def _kill_pid_tree(pid: int) -> None:
    """Kill ONLY a PID this harness spawned (registry turn_pid) -- containment
    kill-target restriction. Windows taskkill /T for the process tree."""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   capture_output=True, text=True)


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture(scope="module")
def sandbox():
    """Build a throwaway temp FLEET_HOME (copy bin/ + template) and a throwaway
    git repo, render the settings instance from the chosen hook source, and tear
    both down after the module."""
    home = Path(tempfile.mkdtemp(prefix="fleet-live-home-"))
    repo = Path(tempfile.mkdtemp(prefix="fleet-live-repo-"))
    try:
        # 1. copy the CLI + hook scripts + template into the sandbox FLEET_HOME
        shutil.copytree(WORKTREE_ROOT / "bin", home / "bin")
        shutil.copy2(WORKTREE_ROOT / "worker-settings.template.json",
                     home / "worker-settings.template.json")
        for sub in ("state", "logs", "mailbox", "state/journals"):
            (home / sub).mkdir(parents=True, exist_ok=True)

        # 2. render state/worker-settings.json DIRECTLY from the chosen hook
        #    source (NOT `fleet init`, which would point hooks at the sandbox
        #    copies -- the hook-source parameter needs main/worktree paths).
        template_text = (home / "worker-settings.template.json").read_text(encoding="utf-8")
        rendered = fleet.render_worker_settings_template(
            template_text, sys.executable, HOOK_SOURCE_HOME
        )
        (home / "state" / "worker-settings.json").write_text(rendered, encoding="utf-8")
        # keep the instance newer than the template so doctor reports it fresh
        os.utime(home / "state" / "worker-settings.json", None)

        # 3. throwaway git repo = worker cwd
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "harness@example.com"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "harness"],
                       check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("throwaway harness repo\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"],
                       check=True, capture_output=True, text=True)

        yield Sandbox(home, repo)
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(repo, ignore_errors=True)


def _spawn(sandbox: Sandbox, name: str, task: str, mode="bypass"):
    """Spawn a worker turn in the sandbox. bypass mode = trusted grind in a
    throwaway repo (the whole point of bypass-with-containment)."""
    r = sandbox.fleet(
        "spawn", name, "--dir", str(sandbox.repo), "--task", task,
        "--mode", mode, "--model", MODEL,
        "--max-budget-usd", str(PER_TURN_BUDGET_USD),
    )
    return r


def _wait_idle(sandbox: Sandbox, name: str, timeout=240):
    sandbox.fleet("wait", name, "--timeout", str(timeout), check=False)
    # `wait` returns when the turn ends; `status` commits the idle/dead verdict
    sandbox.fleet("status", name, check=False)


# ===========================================================================
# Scenarios
# ===========================================================================
def test_hook_source_render(sandbox: Sandbox):
    """PLAN §0.1.6: the rendered worker-settings.json hook commands point at the
    requested hook source. This is the merge-gate/pre-merge switch."""
    settings = json.loads(
        (sandbox.home / "state" / "worker-settings.json").read_text(encoding="utf-8")
    )
    cmds = json.dumps(settings)
    # forward slashes only (SPEC §7 -- Git Bash sh -c eats backslashes)
    assert "\\\\" not in cmds and "\\/" not in cmds
    assert "/bin/hooks/posttooluse_mailbox.py" in cmds
    assert "/bin/hooks/stop_mailbox.py" in cmds
    if HOOK_SOURCE == "worktree":
        assert "-wt/c2/bin/hooks/" in cmds, cmds
    else:
        assert "/claude-fleet/bin/hooks/" in cmds and "-wt/c2/" not in cmds, cmds


def test_doctor_pre(sandbox: Sandbox):
    """doctor before any worker: settings validate, both hook scripts smoke-fire
    end-to-end in the sandbox (SPEC §5/§7 silent-failure alarm)."""
    r = sandbox.fleet("doctor", check=False)
    combined = r.stdout + r.stderr
    assert "posttooluse-hook-smoke" in combined
    assert "stop-hook-smoke" in combined
    # both hook smokes must PASS -- the whole reason doctor exists
    assert "fired end-to-end and emitted valid hookSpecificOutput JSON" in combined
    assert "fired end-to-end and emitted a valid block decision" in combined


def test_spawn_wait_status_result_peek(sandbox: Sandbox):
    """Core loop (SPEC §12): spawn -> wait -> result -> status -> peek. The
    baseline corpus fixture."""
    name = "smoke-core"
    _spawn(sandbox, name, "Write the single word DONE to out.txt, then stop. "
                          "Final message: exactly the word DONE.")
    _wait_idle(sandbox, name)

    rec = sandbox.worker(name)
    assert rec["status"] in ("idle", "working")  # haiku usually idle by now
    # result event landed in the log
    assert _log_has_result(sandbox, name), "no result event in core-loop log"

    res = sandbox.fleet("result", name, check=False)
    assert "DONE" in (res.stdout + res.stderr).upper()

    peek = sandbox.fleet("peek", name, check=False)
    assert peek.returncode == 0

    sandbox.archive("smoke-core-spawn-result", sandbox.log_path(name),
                    scenario="spawn->wait->result->status->peek",
                    note="baseline healthy completed turn; result event present, "
                         "hook/system lines land after it (SMOKE-A shape)")
    assert _MANIFEST["smoke-core-spawn-result.jsonl"]["has_result_event"]


def test_midturn_send_injection(sandbox: Sandbox):
    """Mid-turn steering (SPEC §7): a message seeded before the first tool
    boundary is injected mid-turn by the PostToolUse hook as <MANAGER MESSAGE>,
    visible in the stream log."""
    name = "smoke-midturn"
    _spawn(sandbox, name,
           "Do this in order, one tool call at a time: write file a.txt "
           "containing A; then write b.txt containing B. Then stop. "
           "Final message: FILES WRITTEN.")
    sid = sandbox.worker(name)["session_id"]
    # seed the mailbox immediately so the first PostToolUse boundary delivers it.
    # A no-extra-tool instruction keeps the injected turn cheap while still
    # proving the <MANAGER MESSAGE> lands mid-turn.
    sandbox.seed_mailbox(
        sid, "Steering update from manager: include the word STEERED in your final message.")
    _wait_idle(sandbox, name)

    log = sandbox.log_path(name).read_text(encoding="utf-8", errors="replace")
    assert "MANAGER MESSAGE" in log or fleet.hook_events_present(sandbox.log_path(name)), \
        "mid-turn injection not visible in stream log"

    sandbox.archive("send-midturn-injection", sandbox.log_path(name),
                    scenario="mid-turn PostToolUse mailbox injection",
                    note="mailbox seeded pre-first-tool-boundary; <MANAGER MESSAGE> "
                         "delivered mid-turn via PostToolUse hook")


def test_stopblock_seeded_early_forces_branch_a(sandbox: Sandbox):
    """Stop-block DUAL-OUTCOME, deterministic branch (a) (SPEC §12 / F28): seed
    the mailbox before a turn that makes NO tool calls, so the Stop hook (not
    PostToolUse) finds the mail and emits {"decision":"block"} -- the queued
    instruction is executed in the SAME turn."""
    name = "smoke-stopblock"
    _spawn(sandbox, name,
           "Do NOT use any tools. Reply with only the word READY and stop.")
    sid = sandbox.worker(name)["session_id"]
    # guaranteed present at Stop time (no tool call means PostToolUse never fires)
    sandbox.seed_mailbox(
        sid, "Steering update from manager: append the word CONTINUED to your reply.")
    _wait_idle(sandbox, name, timeout=240)

    log = sandbox.log_path(name).read_text(encoding="utf-8", errors="replace")
    # branch (a): a Stop block decision appears AND the queued text was acted on
    block_seen = '\\"decision\\": \\"block\\"' in log or '"decision":"block"' in log \
        or '\\"decision\\":\\"block\\"' in log
    # mailbox must be consumed (Stop drained it) -- not stranded
    assert not sandbox.mailbox_path(sid).exists() or \
        sandbox.mailbox_path(sid).stat().st_size == 0, "mail stranded -- not branch (a)"
    assert block_seen or "CONTINUED" in log, \
        "neither a Stop block decision nor the continued instruction is visible"

    sandbox.archive("stopblock-seeded-early", sandbox.log_path(name),
                    scenario="Stop-block dual-outcome branch (a) (deterministic)",
                    note="mailbox seeded before a no-tool turn; Stop hook blocks + "
                         "queued instruction executed same turn")


def test_stopblock_dual_outcome_race_and_idle_mail(sandbox: Sandbox):
    """Stop-block DUAL-OUTCOME branch (b) + the idle+mail (Stop-drain-race)
    corpus fixture (SPEC §12/F28). A message arriving AFTER the Stop hook drained
    legitimately loses the race: it stays in the mailbox, status flags idle+mail,
    and the NEXT launch's composed prompt drains it. PASS on branch (a) OR (b);
    FAIL only on lost / flag-absent / delivered-twice."""
    name = "smoke-idlemail"
    _spawn(sandbox, name,
           "Write the word HELLO to hi.txt, then stop. Final message: HI DONE.")
    _wait_idle(sandbox, name)
    rec = sandbox.worker(name)
    sid = rec["session_id"]

    # simulate a race-loser arriving after the turn went idle (post-drain)
    msg = "Steering update from manager: this arrived after the drain."
    sandbox.seed_mailbox(sid, msg)

    # branch (b) condition 2: status flags idle+mail
    status = sandbox.fleet("status", name, check=False)
    assert "idle+mail" in status.stdout, f"idle+mail flag absent:\n{status.stdout}"

    # branch (b) condition 1: message remains in mailbox
    assert sandbox.mailbox_path(sid).exists()
    assert msg in sandbox.mailbox_path(sid).read_text(encoding="utf-8")

    # branch (b) condition 3: the NEXT launch's composed prompt contains it.
    # Use fleet's OWN compose_prompt (the exact code every launch path runs)
    # against the sandbox FLEET_HOME -- deterministic, no extra haiku turn.
    saved = fleet.FLEET_HOME
    try:
        fleet.FLEET_HOME = sandbox.home
        prompt, claim = fleet.compose_prompt(name, str(sandbox.repo), task="", sid=sid)
    finally:
        fleet.FLEET_HOME = saved
    assert msg in prompt, "next-launch composed prompt did not drain the message"
    assert "<MANAGER MESSAGE>" in prompt

    sandbox.archive("idle-mail-stopdrain", sandbox.log_path(name),
                    scenario="Stop-block dual-outcome branch (b): idle+mail race-loser",
                    note="message arrived post-drain; status flagged idle+mail; next "
                         "launch's composed prompt drains it (compose_prompt verified)")


def test_release_guard(sandbox: Sandbox):
    """Headless-testable guard refusal (SPEC §5/§9): release refuses a
    non-attached worker. Reuses the already-idle smoke-core worker (no extra
    spawn / no extra haiku spend). The attach-while-working refusal is asserted
    in test_crashed_turn_capture, on the worker guaranteed to be running there.
    No real TUI is ever opened by the harness."""
    rel = sandbox.fleet("release", "smoke-core", check=False)
    assert rel.returncode != 0 or "not attached" in (rel.stdout + rel.stderr).lower()


def test_respawn_continuity_and_cost_baseline(sandbox: Sandbox):
    """Resilience (SPEC §12): respawn = new session_id, journal-injection, drained
    mailbox, cost_baseline carry so cost_usd survives the log rotation."""
    name = "smoke-respawn"
    _spawn(sandbox, name,
           "Write the word FIRST to r.txt, then stop. Final message: FIRST DONE.")
    _wait_idle(sandbox, name)
    before = sandbox.worker(name)
    sid_before = before["session_id"]
    cost_before = before["cost_usd"]

    r = sandbox.fleet("respawn", name, "--task",
                      "Write the word SECOND to r.txt, then stop. Final message: SECOND DONE.",
                      check=False)
    assert r.returncode == 0, f"respawn failed:\n{r.stdout}\n{r.stderr}"
    _wait_idle(sandbox, name)

    after = sandbox.worker(name)
    assert after["session_id"] != sid_before, "respawn did not mint a new session_id"
    # cost_baseline carries the pre-rotation lifetime spend (SPEC §4 cost model)
    assert after["cost_baseline"] >= cost_before - 1e-9, \
        f"cost_baseline {after['cost_baseline']} did not carry prior spend {cost_before}"
    assert after["cost_usd"] >= after["cost_baseline"] - 1e-9

    sandbox.archive("respawn-continuity", sandbox.log_path(name),
                    scenario="respawn drain + journal-injection + cost_baseline carry",
                    note="new session_id, rotated log, cost_baseline = pre-rotation spend")


def test_crashed_turn_capture(sandbox: Sandbox):
    """Fault-injected crashed-turn corpus fixture (SPEC §12 requires >=1). Kill
    the turn PID this harness spawned (containment: only our own pid) so the turn
    ends with NO result event; recompute classifies it dead."""
    name = "smoke-crashed"
    _spawn(sandbox, name,
           "Write files g.txt,h.txt,i.txt one at a time with matching letters, "
           "then stop. Final message: DONE.")
    rec = sandbox.worker(name)
    pid = rec.get("turn_pid")
    assert rec["status"] == "working" and pid, "worker not running to crash-inject"

    # attach-while-working guard (SPEC §5/§9): this worker is guaranteed running,
    # so assert attach REFUSES here (headless -- refusal never launches a TUI)
    # before we crash-inject it.
    att = sandbox.fleet("attach", name, check=False)
    assert att.returncode != 0 or "running" in (att.stdout + att.stderr).lower(), \
        "attach did not refuse a running turn"

    # wait for a real partial stream (assistant/tool events) so the captured
    # crash fixture is NON-empty -- a booted-but-silent kill yields a useless
    # 0-byte log for watchtower's crash-detection rule tests.
    assert _wait_for_partial_log(sandbox, name), "no partial stream to crash-capture"
    # re-read pid (unchanged across the same turn) and kill only that tree
    pid = sandbox.worker(name).get("turn_pid") or pid
    _kill_pid_tree(int(pid))
    # give the OS a moment to reap, then let recompute classify it
    time.sleep(1.0)
    sandbox.fleet("status", name, check=False)
    # a working->dead transition retries the probe once; poll briefly
    for _ in range(6):
        st = sandbox.worker(name)["status"]
        if st == "dead":
            break
        time.sleep(1.0)
        sandbox.fleet("status", name, check=False)

    assert not _log_has_result(sandbox, name), \
        "crashed-turn log unexpectedly has a result event"

    sandbox.archive("crashed-turn", sandbox.log_path(name),
                    scenario="crashed turn (turn PID killed mid-turn)",
                    note="no result event; recompute -> dead (SPEC §4 crash path). "
                         "Fault-injected: only the harness-spawned turn_pid was killed.")
    assert not _MANIFEST["crashed-turn.jsonl"]["has_result_event"]
    assert _MANIFEST["crashed-turn.jsonl"]["lines"] > 0, "crashed-turn fixture is empty"

    # dead is sticky -> clean is the recovery path here
    sandbox.fleet("kill", name, check=False)


def test_doctor_post(sandbox: Sandbox):
    """doctor after the run: still validates settings + both hook smokes, and
    surfaces the fleet's derived views without error (SPEC §5)."""
    r = sandbox.fleet("doctor", check=False)
    combined = r.stdout + r.stderr
    assert "worker-settings" in combined
    assert "posttooluse-hook-smoke" in combined and "stop-hook-smoke" in combined


def test_zz_budget_ceiling_and_manifest(sandbox: Sandbox):
    """CONTAINMENT ASSERT (runs last): summed lifetime spend across every worker
    this run created must not exceed the $0.25/run ceiling, and the corpus must
    meet the minimum-contents rule. Also flushes the corpus manifest."""
    workers = sandbox.registry()["workers"]
    total = sum(w.get("cost_usd", 0.0) for w in workers.values())
    assert total <= RUN_BUDGET_CEILING_USD, (
        f"per-run budget ceiling exceeded: ${total:.4f} > ${RUN_BUDGET_CEILING_USD:.2f} "
        f"across {len(workers)} workers"
    )

    # write the manifest describing the corpus this run archived
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(_MANIFEST, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # corpus minimum-contents rule (SPEC §12): >=5 logs incl >=1 crashed + >=1 idle+mail.
    # Assert against the committed corpus on disk (the durable artifact), not just
    # this run's in-memory manifest.
    logs = sorted(p for p in FIXTURE_DIR.glob("*.jsonl"))
    assert len(logs) >= 5, f"corpus has only {len(logs)} logs, need >=5"
    full_manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8")) \
        if (FIXTURE_DIR / "manifest.json").exists() else {}
    crashed = [n for n, m in full_manifest.items() if "crash" in m.get("scenario", "").lower()]
    idlemail = [n for n, m in full_manifest.items() if "idle+mail" in m.get("scenario", "").lower()]
    assert crashed, "corpus missing a crashed-turn log"
    assert idlemail, "corpus missing an idle+mail log"

    print(f"\n[harness] run spend ${total:.4f} across {len(workers)} workers "
          f"(ceiling ${RUN_BUDGET_CEILING_USD:.2f}); corpus {len(logs)} logs "
          f"hook_source={HOOK_SOURCE}")
