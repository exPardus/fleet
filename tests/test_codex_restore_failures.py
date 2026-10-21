"""Rejected native Codex settle paths report restore failures, never hide them."""
from pathlib import Path

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    return tmp_path


def test_prior_file_restore_oserror_warns_and_returns_failed_key(home, capsys):
    # A regular file where the briefs directory belongs makes mkdir fail.
    fleet.brief_file_path("lane").parent.parent.mkdir(parents=True, exist_ok=True)
    fleet.brief_file_path("lane").parent.write_text("blocker")
    task = fleet.task_file_path("lane")
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text("replaced")
    failed = fleet._restore_codex_prior_files(
        "lane", {"brief": "b2xk", "task": None})
    assert failed == ["brief"]
    assert not task.exists()
    err = capsys.readouterr().err
    assert "warning" in err and "lane" in err and "prior brief" in err


def test_claimed_mail_unlink_failure_rolls_back_restored_link(home, monkeypatch):
    mailbox = fleet.mailbox_dir()
    mailbox.mkdir(parents=True)
    claimed = mailbox / f"{THREAD_ID}.md.claimed.op1"
    claimed.write_text("mail body\n")
    real_unlink = Path.unlink

    def unlink(self, *a, **kw):
        if self == claimed:
            raise PermissionError("denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(fleet.FleetCliError, match="rolled back"):
        fleet._restore_rejected_codex_mail(claimed, THREAD_ID)
    # Exactly one copy remains: the claim, never a second deliverable inbox.
    assert claimed.read_text() == "mail body\n"
    assert not (mailbox / f"{THREAD_ID}.md").exists()


def test_claimed_mail_double_unlink_failure_names_both_copies(home, monkeypatch):
    mailbox = fleet.mailbox_dir()
    mailbox.mkdir(parents=True)
    claimed = mailbox / f"{THREAD_ID}.md.claimed.op1"
    claimed.write_text("mail body\n")

    def unlink(self, *a, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(fleet.FleetCliError, match="both") as info:
        fleet._restore_rejected_codex_mail(claimed, THREAD_ID)
    assert str(mailbox / f"{THREAD_ID}.md") in str(info.value)


def test_claimed_mail_rollback_keeps_mail_that_replaced_the_link(
        home, monkeypatch):
    mailbox = fleet.mailbox_dir()
    mailbox.mkdir(parents=True)
    claimed = mailbox / f"{THREAD_ID}.md.claimed.op1"
    claimed.write_text("mail body\n")
    target = mailbox / f"{THREAD_ID}.md"
    real_unlink = Path.unlink

    def unlink(self, *a, **kw):
        if self == claimed:
            # A concurrent writer replaces the restored link with new mail.
            fresh = mailbox / "fresh.tmp"
            fresh.write_text("newer mail\n")
            fleet.os.replace(fresh, target)
            raise PermissionError("denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(fleet.FleetCliError):
        fleet._restore_rejected_codex_mail(claimed, THREAD_ID)
    assert claimed.read_text() == "mail body\n"
    assert target.read_text() == "newer mail\n"


def test_release_keeps_pending_prior_files_when_restore_fails(home, capsys):
    binding = fleet.CodexWorkerBinding(
        "lane", THREAD_ID, "turn-1", "gen-1", str(home), {})
    pending = {"operation_id": "op1", "previous_status": "idle",
               "previous_adapter_state": "idle",
               "prior_files": {"brief": "b2xk", "task": None}}
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["lane"] = {
            "status": "working", "adapter_state": "pending",
            "codex_thread_id": THREAD_ID, "codex_turn_id": "turn-1",
            "pending_operation": pending}
        fleet.save_registry(data)
    blocker = fleet.brief_file_path("lane").parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("blocker")
    assert fleet._release_codex_rejected_worker(binding, "op1") is False
    row = fleet.load_registry()["workers"]["lane"]
    assert row["pending_operation"]["prior_files"] == {"brief": "b2xk"}
    assert row["status"] == "dead-suspected"
    assert "brief" in row["uncertain_reason"]
    assert "prior brief" in capsys.readouterr().err
    # A later settle retries the kept bytes and releases the row.
    blocker.unlink()
    assert fleet._release_codex_rejected_worker(binding, "op1") is True
    assert fleet.brief_file_path("lane").read_bytes() == b"old"
    assert "pending_operation" not in fleet.load_registry()["workers"]["lane"]
