"""Item 24: `--model openrouter:<slug>` native dispatch.

THE FORK (state/tasks/w93.md), settled by experiment on 2026-09-17 against a
real resident daemon, not by reading: `claude --bg` hands the session to the
daemon's pre-warmed spare pool. An env var set only on the dispatching
`claude --bg` invocation (`_worker_env`'s shape) never reached the session's
own `env` output. A `--settings` `"env"` block DOES reach the session's real
process environment, but its values are literal strings -- `"$VAR"` is never
expanded. `apiKeyHelper` is a shell command the session executes itself, at
auth time, so pointing it at the key FILE (never at the key's value) lets the
session fetch its own credential without the key ever transiting fleet.

The binding rule this file exists to pin: the key's VALUE never appears in
any file fleet writes, any recorded argv, or any exception message -- only
its PATH does, which is not a secret.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

FAKE_KEY_VALUE = "sk-or-v1-w93-canary-do-not-leak-2f9c8a"


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with state/ and a rendered instance settings file,
    matching tests/test_native.py's fixture shape."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(fleet q:*)"]},
                    "hooks": {"Stop": [{"hooks": [{"type": "command",
                                                   "command": "true"}]}]}}),
        encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


@pytest.fixture
def openrouter_key(tmp_path, monkeypatch):
    """A readable key file at the (redirected) default path."""
    path = tmp_path / "openrouter-env" / "env"
    path.parent.mkdir(parents=True)
    path.write_text(f"OPENROUTER_API_KEY={FAKE_KEY_VALUE}\n", encoding="utf-8")
    monkeypatch.setattr(fleet, "openrouter_key_path", lambda: path)
    return path


def _fake_run_factory(stdout="backgrounded \u00b7 aaaabbbb \u00b7 fleet|w1|t\n",
                      rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


SID = "aaaabbbb-1111-2222-3333-444455556666"


def _roster_with(sid=SID):
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [{"id": sid[:8], "sessionId": sid, "name": "n",
                       "cwd": "C:/proj", "startedAt": 1, "kind": "background",
                       "state": "working", "status": "busy", "pid": 1}]
    return fetch


class TestOpenrouterModelSlug:
    def test_parses_the_slug(self):
        assert fleet._openrouter_model_slug("openrouter:stealth/union-alpha") == \
            "stealth/union-alpha"

    def test_non_openrouter_models_return_none(self):
        assert fleet._openrouter_model_slug("haiku") is None
        assert fleet._openrouter_model_slug(None) is None
        assert fleet._openrouter_model_slug("") is None

    def test_substrate_field_helper(self):
        assert fleet._openrouter_substrate("openrouter:z-ai/glm-5.3-flash") == \
            "openrouter/z-ai/glm-5.3-flash"
        assert fleet._openrouter_substrate("haiku") is None
        assert fleet._openrouter_substrate(None) is None


class TestKeyFileGate:
    def test_refuses_naming_the_path_when_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / "nowhere" / "env"
        monkeypatch.setattr(fleet, "openrouter_key_path", lambda: missing)
        with pytest.raises(fleet.NativeDispatchError, match=re_escape_path(missing)):
            fleet._require_openrouter_key_readable()

    def test_readable_file_returns_its_path(self, openrouter_key):
        assert fleet._require_openrouter_key_readable() == openrouter_key

    def test_unreadable_file_is_refused(self, tmp_path, monkeypatch):
        path = tmp_path / "env"
        path.write_text("OPENROUTER_API_KEY=x\n", encoding="utf-8")
        path.chmod(0o000)
        try:
            monkeypatch.setattr(fleet, "openrouter_key_path", lambda: path)
            with pytest.raises(fleet.NativeDispatchError):
                fleet._require_openrouter_key_readable()
        finally:
            path.chmod(0o600)  # restore so tmp_path cleanup can remove it


def re_escape_path(path: Path) -> str:
    import re
    return re.escape(path.as_posix())


class TestOpenrouterSettingsArg:
    def test_merges_env_and_apikeyhelper_without_the_secret(self, tmp_path,
                                                             openrouter_key):
        base = tmp_path / "worker-settings.json"
        base.write_text(json.dumps({"hooks": {"Stop": [{"hooks": []}]}}),
                        encoding="utf-8")
        merged = fleet._openrouter_settings_arg(base, openrouter_key)
        assert FAKE_KEY_VALUE not in merged
        payload = json.loads(merged)
        assert payload["hooks"] == {"Stop": [{"hooks": []}]}  # base preserved
        assert payload["env"]["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert payload["env"]["ANTHROPIC_API_KEY"] == ""
        assert openrouter_key.as_posix() in payload["apiKeyHelper"]
        assert FAKE_KEY_VALUE not in payload["apiKeyHelper"]

    def test_base_settings_file_on_disk_is_never_written(self, tmp_path,
                                                          openrouter_key):
        base = tmp_path / "worker-settings.json"
        original = json.dumps({"hooks": {}})
        base.write_text(original, encoding="utf-8")
        fleet._openrouter_settings_arg(base, openrouter_key)
        assert base.read_text(encoding="utf-8") == original

    def test_missing_base_settings_file_merges_from_empty(self, tmp_path,
                                                           openrouter_key):
        merged = fleet._openrouter_settings_arg(tmp_path / "nope.json",
                                                 openrouter_key)
        payload = json.loads(merged)
        assert payload["env"]["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"


class TestOpenrouterDispatchArgs:
    def test_non_openrouter_model_is_a_pure_passthrough(self, tmp_path):
        settings = tmp_path / "s.json"
        settings.write_text("{}", encoding="utf-8")
        model, arg = fleet._openrouter_dispatch_args("haiku", settings)
        assert model == "haiku"
        assert arg == settings.as_posix()

    def test_none_model_is_a_pure_passthrough(self, tmp_path):
        settings = tmp_path / "s.json"
        settings.write_text("{}", encoding="utf-8")
        model, arg = fleet._openrouter_dispatch_args(None, settings)
        assert model is None
        assert arg == settings.as_posix()

    def test_openrouter_model_returns_bare_slug_and_merged_settings(
            self, tmp_path, openrouter_key):
        settings = tmp_path / "s.json"
        settings.write_text("{}", encoding="utf-8")
        model, arg = fleet._openrouter_dispatch_args(
            "openrouter:stealth/union-alpha", settings)
        assert model == "stealth/union-alpha"
        assert json.loads(arg)["env"]["ANTHROPIC_BASE_URL"] == \
            "https://openrouter.ai/api"

    def test_openrouter_model_without_a_key_file_refuses(self, tmp_path):
        settings = tmp_path / "s.json"
        settings.write_text("{}", encoding="utf-8")
        with pytest.raises(fleet.NativeDispatchError):
            fleet._openrouter_dispatch_args("openrouter:stealth/union-alpha",
                                            settings)


class TestDispatchBgOpenrouterIntegration:
    def test_argv_carries_the_bare_slug_and_merged_settings(
            self, native_home, openrouter_key):
        calls = []
        out = fleet.dispatch_bg("w1", "C:/proj", "BODY", "accept",
                                model="openrouter:stealth/union-alpha",
                                run=_fake_run_factory(calls=calls),
                                which=lambda _: "claude",
                                sleep=lambda s: None, roster_fetch=_roster_with())
        assert out["session_id"] == SID
        argv, kwargs = calls[0]
        assert argv[argv.index("--model") + 1] == "stealth/union-alpha"
        assert "openrouter:" not in " ".join(argv)
        settings_arg = argv[argv.index("--settings") + 1]
        # Not a file path this time -- an inline merged JSON blob.
        payload = json.loads(settings_arg)
        assert payload["env"]["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"

    def test_non_openrouter_dispatch_is_byte_for_byte_unchanged(
            self, native_home):
        """Out of scope: changing any default -- pin that a plain dispatch's
        --settings argv is still the plain file path, not a merged blob."""
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "BODY", "accept", model="haiku",
                          run=_fake_run_factory(calls=calls),
                          which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv, _ = calls[0]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert argv[argv.index("--settings") + 1] == \
            fleet.instance_settings_path().as_posix()

    def test_missing_key_refuses_before_any_write_or_dispatch(
            self, native_home, tmp_path, monkeypatch):
        missing = tmp_path / "nope" / "env"
        monkeypatch.setattr(fleet, "openrouter_key_path", lambda: missing)
        calls = []
        with pytest.raises(fleet.NativeDispatchError, match=re_escape_path(missing)):
            fleet.dispatch_bg("w1", "C:/proj", "BODY", "accept",
                              model="openrouter:stealth/union-alpha",
                              run=_fake_run_factory(calls=calls),
                              which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())
        assert calls == []  # never reached the runner
        assert not fleet.task_file_path("w1").exists()  # no partial dispatch state

    def test_the_key_value_never_appears_anywhere_fleet_touched(
            self, native_home, openrouter_key):
        """The binding rule (state/tasks/w93.md): dispatch through a fake
        runner, then grep every file fleet touched plus the recorded argv."""
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "BODY", "accept",
                          model="openrouter:stealth/union-alpha",
                          run=_fake_run_factory(calls=calls),
                          which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv, kwargs = calls[0]
        assert FAKE_KEY_VALUE not in json.dumps(argv)
        assert FAKE_KEY_VALUE not in json.dumps(dict(kwargs.get("env") or {}))
        assert FAKE_KEY_VALUE not in fleet.task_file_path("w1").read_text(
            encoding="utf-8")
        for path in native_home.rglob("*"):
            if path == openrouter_key:
                continue  # the key file itself is the input, not something fleet wrote
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                assert FAKE_KEY_VALUE not in text, f"leaked into {path}"


class TestSpawnRecordsSubstrate:
    def _spawn_args(self, **kw):
        base = dict(name="w1", dir="C:/proj", task="do it", mode="accept",
                    model=None, max_budget_usd=None, setting_sources=None,
                    token_ceiling=None, category=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_openrouter_spawn_records_the_slug_substrate(
            self, native_home, openrouter_key, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        args = self._spawn_args(model="openrouter:z-ai/glm-5.3-flash",
                                dir=str(native_home))
        rc = fleet.cmd_spawn(args, run=_fake_run_factory(),
                             which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["substrate"] == "openrouter/z-ai/glm-5.3-flash"

    def test_plain_spawn_leaves_substrate_none(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        args = self._spawn_args(model="haiku", dir=str(native_home))
        rc = fleet.cmd_spawn(args, run=_fake_run_factory(),
                             which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["substrate"] is None


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME, same shape as tests/test_handoff_seams.py's."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    return tmp_path


def _fake_which(name):
    return "claude"


def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001",
                          calls=None):
    """Stateful `subprocess.run` double, same shape as
    tests/test_handoff_seams.py's -- the successor appears in the roster only
    after the `--bg` dispatch has been observed (contract G6 join)."""
    assert successor_sid.startswith(short_id)
    state = {"dispatched": False}
    def run(argv, **kw):
        if calls is not None:
            calls.append((argv, kw))
        if "--bg" in argv:
            state["dispatched"] = True
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded · {short_id} · sup\n",
                                   stderr="")
        entries = [{"sessionId": "sid-old", "status": "busy"}]
        if state["dispatched"]:
            entries.append({"sessionId": successor_sid, "status": "busy"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


def _hold(sid="sid-old", inc="inc-20260917T000000Z-w93t"):
    beat = fleet.now_iso()
    fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                             "claimed_at": beat, "heartbeat_at": beat,
                             "claimed_via": "fresh"})


class TestSupHandoffBeginOpenrouter:
    """The OTHER native dispatch site (state/tasks/w93.md: bin/fleet.py:13941
    at eb83e11) needs the same wiring dispatch_bg got -- this is not a lane
    the registry tracks for wave-close, but the successor process itself must
    still really run against OpenRouter when asked."""

    def test_argv_carries_the_bare_slug_and_merged_settings(
            self, sup_home, openrouter_key):
        _hold()
        calls = []
        args = SimpleNamespace(sid="sid-old",
                               model="openrouter:stealth/union-alpha",
                               permission_mode=None, nonce=None)
        rc = fleet.cmd_sup_handoff_begin(
            args, which=_fake_which,
            run=_dispatch_then_roster(calls=calls), sleep=lambda s: None)
        assert rc == 0
        dispatch_argv = next(argv for argv, _ in calls if "--bg" in argv)
        assert dispatch_argv[dispatch_argv.index("--model") + 1] == \
            "stealth/union-alpha"
        settings_arg = dispatch_argv[dispatch_argv.index("--settings") + 1]
        payload = json.loads(settings_arg)
        assert payload["env"]["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert FAKE_KEY_VALUE not in settings_arg

    def test_missing_key_refuses_before_the_claim_is_touched(
            self, sup_home, tmp_path, monkeypatch):
        missing = tmp_path / "nope" / "env"
        monkeypatch.setattr(fleet, "openrouter_key_path", lambda: missing)
        _hold()
        before = fleet.read_incarnation()
        args = SimpleNamespace(sid="sid-old",
                               model="openrouter:stealth/union-alpha",
                               permission_mode=None, nonce=None)
        with pytest.raises(fleet.FleetCliError, match=re_escape_path(missing)):
            fleet.cmd_sup_handoff_begin(
                args, which=_fake_which,
                run=_dispatch_then_roster(), sleep=lambda s: None)
        assert fleet.read_incarnation() == before  # claim unchanged, duty continues
