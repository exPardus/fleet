"""`fleet clean` preserves recoverable evidence before deleting a row."""

import argparse
import json
from types import SimpleNamespace

import pytest

import fleet


def test_clean_dead_only_archives_brief_and_journal_before_removal(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "state/briefs", "state/journals"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    sid = "sid-clean"
    record = fleet.new_worker_record(
        sid, str(tmp_path), "task", "acceptEdits", dispatch_kind="bg")
    record.update({"status": "dead", "session_id": sid})
    fleet.save_registry({"workers": {"w1": record}})
    fleet.brief_file_path("w1").write_text("brief", encoding="utf-8")
    fleet.journal_file_path("w1").write_text("journal", encoding="utf-8")

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    rc = fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude")

    assert rc == 0
    archive = fleet.archive_root() / "w1"
    assert (archive / "brief.md").read_text(encoding="utf-8") == "brief"
    assert (archive / "journal.md").read_text(encoding="utf-8") == "journal"
    out = capsys.readouterr().out
    assert "archived evidence" in out


def test_clean_dead_only_archives_native_codex_thread_mail_and_claim(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    thread_id = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
    record = fleet.new_worker_record(
        None, str(tmp_path), "task", "acceptEdits",
        dispatch_kind="codex-app-server", substrate="codex")
    record.update({
        "status": "dead",
        "codex_thread_id": thread_id,
        "codex_turn_id": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8",
        "adapter_state": "dead",
    })
    fleet.save_registry({"workers": {"cx-dead": record}})
    (tmp_path / "mailbox" / f"{thread_id}.md").write_text(
        "new mail\n", encoding="utf-8")
    claimed = tmp_path / "mailbox" / f"{thread_id}.md.claimed.12345"
    claimed.write_text("claimed mail\n", encoding="utf-8")

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    assert fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude") == 0

    archive = fleet.archive_root() / "cx-dead"
    assert (archive / f"{thread_id}.md").read_text(encoding="utf-8") == "new mail\n"
    assert (archive / f"mailbox-{thread_id}.md.claimed.12345").read_text(
        encoding="utf-8") == "claimed mail\n"
    assert list((tmp_path / "mailbox").iterdir()) == []
    assert "cx-dead" not in fleet.load_registry()["workers"]


def test_clean_refusal_happens_before_any_archive_move(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "state/briefs", "state/journals"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: "foreign")
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    record = fleet.new_worker_record(
        "sid-refuse", str(tmp_path), "task", "acceptEdits", spawned_by="owner")
    record["status"] = "dead"
    fleet.save_registry({"workers": {"w1": record}})
    brief = fleet.brief_file_path("w1")
    brief.write_text("brief", encoding="utf-8")

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    with pytest.raises(fleet.DestructiveActionRefused):
        fleet.cmd_clean(
            argparse.Namespace(yes=False, dead_only=True, tombstones=False),
            run=roster, which=lambda _: "claude")

    assert brief.read_text(encoding="utf-8") == "brief"
    assert not fleet.archive_root().exists()
    assert "w1" in fleet.load_registry()["workers"]


def test_clean_rescans_mailbox_before_deleting_row(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    sid = "sid-mail-race"
    record = fleet.new_worker_record(
        sid, str(tmp_path), "task", "acceptEdits", dispatch_kind="bg")
    record["status"] = "dead"
    fleet.save_registry({"workers": {"w1": record}})

    real_archive = fleet._archive_clean_evidence
    calls = {"count": 0}

    def inject_after_first_archive(*args, **kwargs):
        result = real_archive(*args, **kwargs)
        calls["count"] += 1
        if calls["count"] == 1:
            (tmp_path / "mailbox" / f"{sid}.md").write_text(
                "arrived after archive\n", encoding="utf-8")
        return result

    monkeypatch.setattr(fleet, "_archive_clean_evidence", inject_after_first_archive)

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    assert fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude") == 0

    archive = fleet.archive_root() / "w1"
    assert (archive / f"{sid}.md").read_text(encoding="utf-8") == (
        "arrived after archive\n")
    assert not (tmp_path / "mailbox" / f"{sid}.md").exists()


def test_clean_rolls_back_partial_archive_move(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "state/briefs", "state/journals"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    record = fleet.new_worker_record(
        "sid-rollback", str(tmp_path), "task", "acceptEdits")
    record["status"] = "dead"
    fleet.save_registry({"workers": {"w1": record}})
    journal = fleet.journal_file_path("w1")
    brief = fleet.brief_file_path("w1")
    journal.write_text("journal", encoding="utf-8")
    brief.write_text("brief", encoding="utf-8")

    real_move = fleet._archive_move
    calls = {"count": 0}

    def fail_on_second_move(src, dest, name):
        calls["count"] += 1
        if calls["count"] == 2:
            return
        return real_move(src, dest, name)

    monkeypatch.setattr(fleet, "_archive_move", fail_on_second_move)

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    assert fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude") == 0

    assert journal.read_text(encoding="utf-8") == "journal"
    assert brief.read_text(encoding="utf-8") == "brief"
    assert not fleet.archive_root().exists()
    assert "w1" in fleet.load_registry()["workers"]


def test_clean_refuses_when_evidence_cannot_be_archived(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "state/briefs", "state/journals"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    sid = "sid-clean"
    record = fleet.new_worker_record(
        sid, str(tmp_path), "task", "acceptEdits", dispatch_kind="bg")
    record["status"] = "dead"
    fleet.save_registry({"workers": {"w1": record}})
    brief = fleet.brief_file_path("w1")
    brief.write_text("brief", encoding="utf-8")
    monkeypatch.setattr(fleet, "_archive_move", lambda *a, **k: None)

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    assert fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude") == 0
    assert "w1" in fleet.load_registry()["workers"]
    assert brief.exists()
    assert "could not archive" in capsys.readouterr().err


def test_clean_never_unlinks_mailbox_written_after_lock_release(
        tmp_path, monkeypatch):
    """A delivery racing the post-lock cleanup remains recoverable."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)

    sid = "sid-after-lock-release"
    record = fleet.new_worker_record(
        sid, str(tmp_path), "task", "acceptEdits", dispatch_kind="bg")
    record["status"] = "dead"
    fleet.save_registry({"workers": {"w1": record}})

    real_remove = fleet._remove_worker_files

    def deliver_after_lock_release(name, current_sid, *args, **kwargs):
        (tmp_path / "mailbox" / f"{sid}.md").write_text(
            "late delivery\n", encoding="utf-8")
        return real_remove(name, current_sid, *args, **kwargs)

    monkeypatch.setattr(fleet, "_remove_worker_files",
                        deliver_after_lock_release)

    def roster(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    assert fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=roster, which=lambda _: "claude") == 0
    late_mail = tmp_path / "mailbox" / f"{sid}.md"
    assert late_mail.read_text(encoding="utf-8") == "late delivery\n"
