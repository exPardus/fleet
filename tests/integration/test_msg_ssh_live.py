"""T16 (plan PR 7): `msg sync` over a real `ssh` to a user-level `sshd`.

Gated by FLEET_LIVE_SSH=1 and skipped loudly without `sshd`, `ssh` or
`ssh-keygen`. Everything lives in a temp dir on a random high localhost port
with temp keys and a forced-command `authorized_keys`; the user's real
`~/.ssh` and ssh config are never read or written (`-F` and `-o` options point
at temp files, HOME is a temp dir).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import child_env

BIN = Path(__file__).resolve().parents[2] / "bin"
FLEET_PY = str(BIN / "fleet.py")

if os.environ.get("FLEET_LIVE_SSH") != "1":
    pytest.skip("SKIPPED LOUDLY: live ssh test gated; set FLEET_LIVE_SSH=1 (needs sshd)",
                allow_module_level=True)


def _tool(name):
    for cand in (shutil.which(name), f"/usr/sbin/{name}", f"/usr/local/sbin/{name}"):
        if cand and os.access(cand, os.X_OK):
            return cand
    pytest.skip(f"SKIPPED LOUDLY: FLEET_LIVE_SSH=1 but {name} is not installed")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fleet(home, *argv, env, check=True):
    run = subprocess.run([sys.executable, FLEET_PY, "--fleet-home", str(home), *argv],
                         capture_output=True, text=True, timeout=120,
                         env=child_env(Path(home).parent, **env))
    if check:
        assert run.returncode == 0, run.stderr + run.stdout
    return run


def test_t16_forced_command_pins_the_client_site_on_a_non_default_port(tmp_path):
    sshd, ssh, keygen = _tool("sshd"), _tool("ssh"), _tool("ssh-keygen")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(mode=0o700)
    real_ssh = Path(os.path.expanduser("~")) / ".ssh"   # conftest patches Path.home, not HOME
    before = sorted(p.name for p in real_ssh.glob("*")) if real_ssh.is_dir() else None
    env = {**os.environ, "HOME": str(sandbox), "CLAUDE_CODE_SESSION_ID": ""}
    for key in ("host", "client"):
        subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(sandbox / key)],
                       check=True)
    a, b = tmp_path / "alpha", tmp_path / "beta"
    for home, site in ((a, "alpha"), (b, "beta")):
        (home / "state").mkdir(parents=True)
        (home / "supervisor").mkdir()
        (home / "state" / "fleet.json").write_text(json.dumps({"workers": {}}))
        _fleet(home, "msg", "init", "--site", site, env=env)
    port = _free_port()
    forced = (f'command="{sys.executable} {FLEET_PY} --fleet-home {b} msg serve --peer alpha",'
              f"restrict {(sandbox / 'client.pub').read_text()}")
    (sandbox / "authorized_keys").write_text(forced)
    (sandbox / "sshd_config").write_text("\n".join([
        f"Port {port}", "ListenAddress 127.0.0.1", f"HostKey {sandbox / 'host'}",
        f"AuthorizedKeysFile {sandbox / 'authorized_keys'}", "PasswordAuthentication no",
        "PubkeyAuthentication yes", "UsePAM no", "StrictModes no",
        f"PidFile {sandbox / 'sshd.pid'}", "LogLevel ERROR", ""]))
    (sandbox / "ssh_config").write_text("\n".join([
        "Host beta-live", "HostName 127.0.0.1", f"Port {port}",
        f"IdentityFile {sandbox / 'client'}", "IdentitiesOnly yes",
        f"UserKnownHostsFile {sandbox / 'known_hosts'}", "StrictHostKeyChecking no", ""]))
    daemon = subprocess.Popen([sshd, "-D", "-e", "-f", str(sandbox / "sshd_config")],
                              stderr=subprocess.PIPE, env=env)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            pytest.fail("sshd did not listen: " + (daemon.stderr.read().decode() if daemon.poll() else ""))
        # A shim `ssh` that adds the temp config; peers.json names a plain alias and port.
        shim = sandbox / "bin"
        shim.mkdir()
        (shim / "ssh").write_text(f'#!/bin/sh\nexec {ssh} -F {sandbox / "ssh_config"} "$@"\n')
        (shim / "ssh").chmod(0o755)
        env["PATH"] = f"{shim}{os.pathsep}{env['PATH']}"
        (a / "state/msg/peers.json").write_text(json.dumps({"beta": {
            "transport": "ssh", "alias": "beta-live", "port": port, "home": str(b)}}))
        (b / "state/msg/peers.json").write_text(json.dumps({"alpha": {"transport": "ssh"}}))
        sender = subprocess.run(
            [sys.executable, "-c", (
                "import sys; sys.path.insert(0, %r); import fleet_msg_core as c, time;"
                "s=c.Store(%r,'alpha'); d=c.make_draft('supervisor@alpha','supervisor@beta','hello live',"
                "from_auth={'method':'unverified','detail':'t'},sent_at=c.iso_utc(time.time()));"
                "print(c.enqueue(s,d)[0])") % (str(BIN), str(a))],
            capture_output=True, text=True, env=env)
        assert sender.stdout.strip() == "queued", sender.stderr
        sync = _fleet(a, "msg", "sync", "--peer", "beta", env=env)
        assert "SYNC beta" in sync.stdout
        delivered = list((b / "state/msg/spool/supervisor/new").glob("*.json"))
        assert len(delivered) == 1 and "hello live" in delivered[0].read_text()
        # The server pinned the client site from the key, not from the hello.
        assert json.loads(delivered[0].read_text())["from"] == "supervisor@alpha"
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)
    after = sorted(p.name for p in real_ssh.glob("*")) if real_ssh.is_dir() else None
    assert after == before                      # the real ~/.ssh was never touched
