"""Citation remappers rewrite only prose citations, never code such as slices."""
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import child_env

ROOT = Path(__file__).resolve().parents[1]
PROBES = ["_probe_slice = [1][:2000]", "_probe_dict = {1:2000}",
          "_probe_tail = (1, 2)[:2000]  # trailing comment, no citation"]
PAD = 13


def _copy_bin(dest):
    (dest / "bin").mkdir(parents=True)
    for path in (ROOT / "bin").glob("*.py"):
        shutil.copy2(path, dest / "bin" / path.name)
    return dest / "bin" / "fleet.py"


def _with_probes(source):
    head, sep, tail = source.partition("\nimport ")
    return head + "\n" + "\n".join(PROBES) + sep + tail


def _probe_lines(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("_probe_")]


def test_refresh_citations_leaves_code_slices_and_dict_literals(tmp_path):
    fleet_py = _copy_bin(tmp_path)
    fleet_py.write_text("# pad\n" * PAD + _with_probes(
        (ROOT / "bin" / "fleet.py").read_text(encoding="utf-8")), encoding="utf-8")
    before = fleet_py.read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "refresh_citations.py"),
         "--write", "--path", str(fleet_py)], capture_output=True, text=True,
        env=child_env(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    after = fleet_py.read_text(encoding="utf-8")
    assert after != before, "the shift must move at least one real citation"
    assert _probe_lines(fleet_py) == PROBES


def test_repoint_self_citations_leaves_code_slices_and_dict_literals(tmp_path):
    fleet_py = _copy_bin(tmp_path)
    (tmp_path / "tools").mkdir()
    shutil.copy2(ROOT / "tools" / "repoint_self_citations.py",
                 tmp_path / "tools" / "repoint_self_citations.py")
    base = _with_probes((ROOT / "bin" / "fleet.py").read_text(encoding="utf-8"))
    fleet_py.write_text(base, encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(git + cmd, cwd=tmp_path, check=True, capture_output=True)
    fleet_py.write_text("# pad\n" * PAD + base, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "tools/repoint_self_citations.py", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "re-pointed 0 of" not in result.stdout
    assert _probe_lines(fleet_py) == PROBES
