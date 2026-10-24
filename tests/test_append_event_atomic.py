"""append_event writes each record with one unbuffered append syscall.

A buffered text append can split a record across writes and interleave with
other writers. These pins hold the single-write invariant and prove that
concurrent processes lose or tear no record.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import fleet  # noqa: E402

WRITER = (
    "import sys; sys.path.insert(0, sys.argv[1]); import fleet\n"
    "from pathlib import Path\n"
    "fleet.FLEET_HOME = Path(sys.argv[2])\n"
    "w, m = sys.argv[3], int(sys.argv[4])\n"
    "for i in range(m):\n"
    "    fleet.append_event('pin', w, seq=i, pad='x' * 3000)\n"
)


def test_append_event_issues_one_write_per_record(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    real_write = os.write
    seen = []

    def spy(fd, data):
        if data.startswith(b'{"ts"'):
            seen.append(bytes(data))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy)
    fleet.append_event("pin", "w1", pad="y" * 20000)
    assert len(seen) == 1
    assert seen[0].endswith(b"\n") and seen[0].count(b"\n") == 1
    assert json.loads(seen[0])["name"] == "w1"


@pytest.mark.parametrize("procs,per_proc", [(8, 150)])
def test_concurrent_append_event_loses_no_record(tmp_path, procs, per_proc):
    children = [
        subprocess.Popen([sys.executable, "-c", WRITER, str(REPO / "bin"),
                          str(tmp_path), f"w{n}", str(per_proc)])
        for n in range(procs)
    ]
    assert [c.wait(timeout=120) for c in children] == [0] * procs
    lines = (tmp_path / "state" / "events.jsonl").read_bytes().split(b"\n")
    assert lines[-1] == b""
    records = [json.loads(line) for line in lines[:-1]]
    assert len(records) == procs * per_proc
    got = {(r["name"], r["seq"]) for r in records}
    assert got == {(f"w{n}", i) for n in range(procs) for i in range(per_proc)}
