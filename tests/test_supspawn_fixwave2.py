"""sup-spawn build -- fix wave 2 (re-gate findings, 2026-07-24).

NEW-1 (MAJ)  the rendered boot ritual's `sup-boot > <bundle>` left the minted
             nonce plaintext AT REST in state/tasks/<stem>.boot-bundle.txt,
             violating claim-nonce §5.8 ("printed exactly once ... and nowhere
             else"; §5.9: gitignored is not a retention policy). Two layers:
             (a) the ritual itself reads the bundle into working context, then
                 DELETES it -- nonce carried in context ONLY, never into the
                 journal, never into any file;
             (b) belt: `_remove_worker_files` and `_archive_file_pairs` sweep
                 an abandoned bundle at retire/archive time.
NEW-2 (MIN)  `{bundle}` and `{fleet_py}` were rendered unquoted in the step
             commands -- a space anywhere under FLEET_HOME breaks the ritual.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
SID = "aaaabbbb-1111-2222-3333-444455556666"
SUP_PIPE = "sup|inc-1|boot"


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="sup|inc|boot", state="working",
                      status="busy", pid=1234, kind="background"):
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_run_factory(stdout="backgrounded · aaaabbbb · sup\n", rc=0):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


def _roster_with(sid=SID, **kw):
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [make_roster_entry(sid, **kw)]
    return fetch


def _sup_args(**kw):
    base = dict(task="run the campaign", model=None, permission_mode=None, nonce=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _happy_spawn(native_home, monkeypatch, args=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
    return fleet.cmd_sup_spawn(args or _sup_args(),
                               run=_fake_run_factory(),
                               which=lambda _: "claude", sleep=lambda s: None)


def _the_one_worker():
    workers = fleet.load_registry()["workers"]
    assert len(workers) == 1, workers
    name = next(iter(workers))
    return name, workers[name]


def _spawned_task_text(native_home, monkeypatch, **kw):
    assert _happy_spawn(native_home, monkeypatch, **kw) == 0
    name, _ = _the_one_worker()
    return name, fleet.task_file_path(name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NEW-1 layer (a): the ritual deletes the bundle and warns off durable copies.
# ---------------------------------------------------------------------------
class TestBootBundleRetentionRitual:
    def test_ritual_deletes_bundle_with_exact_quoted_path(self, native_home, monkeypatch):
        name, text = _spawned_task_text(native_home, monkeypatch)
        bundle = fleet.boot_bundle_path(name).as_posix()
        assert f'rm "{bundle}"' in text

    def test_ritual_warns_nonce_context_only_never_journal_or_file(self, native_home, monkeypatch):
        _, text = _spawned_task_text(native_home, monkeypatch)
        low = text.lower()
        assert "working context only" in low
        assert "never into the journal" in low
        assert "never into any" in low and "file" in low

    def test_ritual_states_the_retention_why(self, native_home, monkeypatch):
        # One line citing the claim-nonce §5.8 retention rule ("printed exactly
        # once ... and nowhere else") as the reason for the delete.
        _, text = _spawned_task_text(native_home, monkeypatch)
        assert "5.8" in text
        assert "exactly once" in text.lower()

    def test_delete_step_follows_the_grep_step(self, native_home, monkeypatch):
        _, text = _spawned_task_text(native_home, monkeypatch)
        assert text.index('grep -E') < text.index('rm "')


# ---------------------------------------------------------------------------
# NEW-1 layer (b): belt -- retire/archive sweep the abandoned bundle.
# ---------------------------------------------------------------------------
class TestBootBundleBeltSweep:
    def test_boot_bundle_path_routes_through_stem_mapping(self, native_home):
        p = fleet.boot_bundle_path(SUP_PIPE)
        assert p.name == "sup~inc-1~boot.boot-bundle.txt"
        assert p.parent == fleet.tasks_dir()

    def test_remove_worker_files_sweeps_planted_bundle(self, native_home):
        bundle = fleet.boot_bundle_path(SUP_PIPE)
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text("NONCE: deadbeef\n", encoding="utf-8")
        removed = fleet._remove_worker_files(SUP_PIPE, SID)
        assert not bundle.exists()
        assert bundle in removed

    def test_archive_pairs_include_bundle(self, native_home):
        pairs = fleet._archive_file_pairs(SUP_PIPE, SID, [])
        assert (fleet.boot_bundle_path(SUP_PIPE), "boot-bundle.txt") in pairs


# ---------------------------------------------------------------------------
# NEW-2: rendered step commands quote {bundle} and {fleet_py}.
# ---------------------------------------------------------------------------
class TestRenderedCommandQuoting:
    def test_bundle_quoted_in_redirect_grep_and_rm(self, native_home, monkeypatch):
        name, text = _spawned_task_text(native_home, monkeypatch)
        bundle = fleet.boot_bundle_path(name).as_posix()
        assert f'> "{bundle}" 2>&1' in text
        assert f'grep -E "^(VERDICT|INCARNATION|NONCE):" "{bundle}"' in text
        assert f"> {bundle} " not in text          # unquoted form gone

    def test_fleet_py_quoted_in_every_command(self, native_home, monkeypatch):
        _, text = _spawned_task_text(native_home, monkeypatch)
        fleet_py = (fleet.FLEET_HOME / "bin" / "fleet.py").as_posix()
        assert f'"{fleet_py}" sup-boot' in text
        assert f'"{fleet_py}" sup-checkpoint' in text
        assert f' {fleet_py} sup' not in text      # unquoted form gone

    def test_space_in_fleet_home_renders_quoted_commands(self, tmp_path, monkeypatch):
        # The class the finding names: any space under FLEET_HOME. Direct
        # template render -- no spawn choreography needed for a string pin.
        home = tmp_path / "fleet home"
        monkeypatch.setattr(fleet, "FLEET_HOME", home)
        name = SUP_PIPE
        text = fleet._render_sup_spawn_task(name, "inc-1", "camp")
        bundle = fleet.boot_bundle_path(name).as_posix()
        fleet_py = (home / "bin" / "fleet.py").as_posix()
        assert " " in bundle and " " in fleet_py    # the fixture really has a space
        assert f'> "{bundle}" 2>&1' in text
        assert f'grep -E "^(VERDICT|INCARNATION|NONCE):" "{bundle}"' in text
        assert f'rm "{bundle}"' in text
        assert f'"{fleet_py}" sup-boot' in text
