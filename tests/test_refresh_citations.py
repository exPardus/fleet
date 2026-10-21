"""The refresher repairs shifted pins and refuses an uncertain target."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "refresh_citations.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_shifted_copy_is_refreshed_and_both_pin_suites_pass(tmp_path):
    source = ROOT / "bin" / "fleet.py"
    copy = tmp_path / "bin" / "fleet.py"
    copy.parent.mkdir()
    for path in (ROOT / "bin").glob("*.py"):
        shutil.copy2(path, copy.parent / path.name)
    copy.write_text("\n" * 43 + source.read_text(encoding="utf-8"),
                    encoding="utf-8")
    assert _run("--check", "--path", copy).returncode == 1
    result = _run("--write", "--path", copy)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _run("--check", "--path", copy).returncode == 0
    assert _run("--write", "--path", copy).returncode == 0

    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("fleet_sources.py", "test_self_citations.py",
                 "test_retired_sid_citations.py"):
        shutil.copy2(ROOT / "tests" / name, tests / name)
    (tests / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))\n",
        encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(copy.parent), str(tests)))
    pin = subprocess.run([sys.executable, "-m", "pytest", "-q",
                          str(tests / "test_self_citations.py"),
                          str(tests / "test_retired_sid_citations.py")],
                         cwd=tmp_path, env=env, capture_output=True, text=True)
    assert pin.returncode == 0, pin.stdout + pin.stderr


def test_ambiguous_anchor_refuses_without_writing(tmp_path):
    source = (ROOT / "bin" / "fleet.py").read_text(encoding="utf-8")
    needle = "_quarantine_artifacts()"
    lines = source.splitlines(keepends=True)
    target = next(i for i, line in enumerate(lines)
                  if needle in line and i > 10000 and "_sweep_husks" not in line)
    lines.insert(target + 1, lines[target])
    copy = tmp_path / "fleet.py"
    copy.write_text("".join(lines), encoding="utf-8")
    before = copy.read_bytes()
    result = _run("--write", "--path", copy)
    assert result.returncode == 1
    assert "ambiguous" in result.stdout
    assert copy.read_bytes() == before


def test_write_is_idempotent_when_a_shift_lands_on_another_old_token(tmp_path):
    """Shifted tokens (:A -> :B, :B -> :C) must not be shifted a second time."""
    source = (ROOT / "bin" / "fleet.py").read_text(encoding="utf-8")
    copy = tmp_path / "bin" / "fleet.py"
    copy.parent.mkdir()
    for path in (ROOT / "bin").glob("*.py"):
        shutil.copy2(path, copy.parent / path.name)
    lines = source.splitlines(keepends=True)
    # Pad before every enumerated target so the union list shifts by 69, the
    # same stride as its adjacent tokens (:4247 + 69 == :4316).
    lines[4000:4000] = ["# pad\n"] * 69
    copy.write_text("".join(lines), encoding="utf-8")
    assert _run("--check", "--path", copy).returncode == 1
    result = _run("--write", "--path", copy)
    assert result.returncode == 0, result.stdout + result.stderr
    again = _run("--check", "--path", copy)
    assert again.returncode == 0, again.stdout + again.stderr
