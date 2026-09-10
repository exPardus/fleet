"""Lossless supervisor journal board rolling."""

from contextlib import nullcontext

import pytest

import fleet


def _entry(kind, number, body):
    return (f"## 2026-09-10T00:00:{number:02d}Z {kind} "
            f"inc=inc-{number} sid=sid-{number}\n\n{body}\n")


def test_roll_moves_old_entries_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    board = tmp_path / "supervisor" / "JOURNAL.md"
    board.parent.mkdir(parents=True)
    seed = "# Supervisor Journal\n\nseed: café\n"
    old = _entry("BOOT", 1, "old boot\r\nline")
    first = _entry("CHECKPOINT", 2, "old checkpoint")
    second = _entry("CHECKPOINT", 3, "older checkpoint")
    third = _entry("CHECKPOINT", 4, "kept one")
    fourth = _entry("CHECKPOINT", 5, "kept two")
    fifth = _entry("CHECKPOINT", 6, "kept three")
    board.write_bytes((seed + old + first + second + third + fourth + fifth).encode())

    before = board.read_bytes()
    result = fleet.roll_supervisor_journal()
    after = board.read_bytes()
    history = fleet.supervisor_journal_history_path().read_bytes()

    assert result["rolled"] is True
    assert result["checkpoints"] == 5
    assert before == seed.encode() + history + after[len(seed.encode()):]
    assert b"old boot" in history and b"old checkpoint" in history
    assert b"kept one" not in history
    assert after.startswith(seed.encode())
    assert b"kept one" in after and b"kept three" in after


def test_roll_is_idempotent_after_the_board_is_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    board = tmp_path / "supervisor" / "JOURNAL.md"
    board.parent.mkdir(parents=True)
    board.write_text("".join(_entry("CHECKPOINT", n, str(n)) for n in range(4)),
                     encoding="utf-8")
    fleet.roll_supervisor_journal()
    history = fleet.supervisor_journal_history_path().read_bytes()
    assert fleet.roll_supervisor_journal()["rolled"] is False
    assert fleet.supervisor_journal_history_path().read_bytes() == history


def test_malformed_board_is_left_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    board = tmp_path / "supervisor" / "JOURNAL.md"
    board.parent.mkdir(parents=True)
    board.write_text(_entry("CHECKPOINT", 1, "ok") +
                     "## 2026-09-10T00:00:02Z CHECKPOINT missing-fields\n",
                     encoding="utf-8")
    before = board.read_bytes()

    with pytest.raises(ValueError, match="malformed"):
        fleet.roll_supervisor_journal()

    assert board.read_bytes() == before
    assert not fleet.supervisor_journal_history_path().exists()


def test_sup_checkpoint_rolls_after_appending(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    board = tmp_path / "supervisor" / "JOURNAL.md"
    board.parent.mkdir(parents=True)
    board.write_text("".join(_entry("CHECKPOINT", n, str(n))
                              for n in range(1, 4)), encoding="utf-8")
    monkeypatch.setattr(fleet, "fleet_lock", lambda: nullcontext())
    monkeypatch.setattr(
        fleet, "_require_claim_holder",
        lambda *args, **kwargs: ({"incarnation_id": "inc-test"},
                                 "sid-test", []))
    monkeypatch.setattr(fleet, "write_incarnation", lambda claim: None)
    args = type("Args", (), {"body": "new", "kind": "CHECKPOINT",
                              "sid": None, "nonce": None})()

    assert fleet.cmd_sup_checkpoint(args) == 0

    assert [e["body"] for e in fleet.supervisor_journal_entries()] == [
        "2", "3", "new"]
    assert "1" in fleet.supervisor_journal_history_path().read_text()
