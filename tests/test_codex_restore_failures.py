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
