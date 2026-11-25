"""The statusline is a cache read: one writer renders, a fork-free sh prints.

Fifteen Claude sessions each ran `fleet_statusline.py` every 10 s, and each
run cost 20-55 % of a CPU (interpreter start, `import fleet`, registry reads).
The operator disabled it. Now fleet verbs that write state, keeper ticks and
`fleet init --statusline` render every row into `fleet.statusline_cache_dir()`
(`fleet.refresh_statusline_cache`), and the installed command is
`sh bin/fleet_statusline.sh CACHE`, which picks one file by the blob's session
id and `$TMUX_PANE` and prints it with shell builtins.

These tests pin: the cached bytes equal the live render, the reader's file
choice, the writer's triggers and no-op default, the install shape (no
`refreshInterval`), the views doctrine for the reader, and the cost budget.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_statusline as sl  # noqa: E402

READER = REPO / "bin" / "fleet_statusline.sh"
SID = "a0000201-0000-4000-8000-000000000201"
OTHER_SID = "a0000202-0000-4000-8000-000000000202"
SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(SH is None, reason="requires sh on PATH")


def _rec(sid, **over):
    base = {
        "session_id": sid, "cwd": "C:/proj", "task": "t", "mode": "dontask",
        "model": None, "created": "2026-07-09T12:00:00Z", "status": "working",
        "turns": 3, "cost_usd": 1.25, "last_activity": "2026-07-09T12:00:00Z",
    }
    base.update(over)
    return base


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "state").mkdir(parents=True)
    (home / "mailbox").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    (home / "state" / "fleet.json").write_text(json.dumps({"workers": {
        "w1": _rec(SID), "w2": _rec(OTHER_SID, status="idle")}}), encoding="utf-8")
    fleet.homes_list_path().parent.mkdir(parents=True, exist_ok=True)
    fleet.homes_list_path().write_text(f"{home}\n", encoding="utf-8")
    return home


@pytest.fixture
def cache(home):
    root = fleet.statusline_cache_dir()
    root.mkdir(parents=True)
    return root


def _read(cache_dir, blob, env=None):
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("NO_COLOR", "TMUX_PANE")}
    child_env.update(env or {})
    out = subprocess.run([SH, str(READER), str(cache_dir)], input=blob,
                         capture_output=True, text=True, env=child_env,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _live(blob, pane=""):
    population = fleet.resolution_population()
    return "".join(row + "\n" for row in sl.render_rows(blob, population, pane))


def test_without_a_cache_directory_the_writer_does_nothing(home):
    """A machine that never installed the statusline pays nothing."""
    assert fleet.refresh_statusline_cache() is False
    assert not fleet.statusline_cache_dir().exists()


@needs_sh
def test_cached_rows_are_the_live_render(home, cache):
    assert fleet.refresh_statusline_cache() is True
    blob = json.dumps({"session_id": SID})
    assert _read(cache, blob) == _live(blob) != ""
    assert "[fleet" in _read(cache, blob) and "work" in _read(cache, blob)
    # NO_COLOR picks the plain rendering, with no escape sequences.
    plain = _read(cache, blob, {"NO_COLOR": "1"})
    assert "\x1b[" not in plain and plain.strip()
    # No sid: the shipped default-home row.
    assert _read(cache, "") == _live("")
    # A sid no home holds is unregistered: no fleet row at all.
    assert _read(cache, json.dumps({"session_id": "deadbeef-unknown"})) == ""


@needs_sh
def test_a_state_change_reaches_the_row_on_the_next_refresh(home, cache):
    fleet.refresh_statusline_cache()
    blob = json.dumps({"session_id": SID})
    before = _read(cache, blob)
    data = fleet.load_registry()
    data["workers"]["w1"]["status"] = "idle"
    fleet.save_registry(data)
    assert fleet._STATUSLINE_DIRTY is True
    assert _read(cache, blob) == before          # the reader never renders
    fleet.refresh_statusline_cache()
    assert fleet._STATUSLINE_DIRTY is False
    after = _read(cache, blob)
    assert after != before and after == _live(blob)


def test_a_verb_that_wrote_state_refreshes_the_cache_on_exit(home, cache, monkeypatch):
    calls = []
    monkeypatch.setattr(fleet, "refresh_statusline_cache",
                        lambda create=False: calls.append(create) or True)

    def verb(argv):
        if argv == ["write"]:
            fleet.save_registry(fleet.load_registry())
        return 0

    monkeypatch.setattr(fleet, "_main", verb)
    monkeypatch.setattr(fleet, "_STATUSLINE_DIRTY", False)
    assert fleet.main(["read"]) == 0 and calls == []      # a view changes nothing
    assert fleet.main(["write"]) == 0 and calls == [False]


def test_a_forgotten_session_loses_its_file(home, cache):
    fleet.refresh_statusline_cache()
    assert (cache / f"sid-{OTHER_SID}").exists()
    data = fleet.load_registry()
    del data["workers"]["w2"]
    fleet.save_registry(data)
    fleet.refresh_statusline_cache()
    assert not (cache / f"sid-{OTHER_SID}").exists()
    assert not (cache / f"sid-{OTHER_SID}.nocolor").exists()
    assert (cache / f"sid-{SID}").exists()


def test_the_keeper_tick_refreshes_the_cache(home, monkeypatch):
    import fleet_keeper
    calls = []
    monkeypatch.setattr(fleet, "refresh_statusline_cache",
                        lambda create=False: calls.append(create) or True)
    monkeypatch.setattr(fleet_keeper, "_run_one", lambda *a, **k: 0)
    assert fleet_keeper.main(["--once", "--fleet-home", str(home)]) == 0
    assert calls == [False]


@needs_sh
def test_reader_file_choice(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    for name, text in {f"sid-{SID}": "SID\n", f"sid-{SID}.nocolor": "PLAIN\n",
                       "nosid": "NOSID\n", "unregistered": "", "pane-12": "PANE\n",
                       "delegates": ""}.items():
        (root / name).write_text(text, encoding="utf-8")
    assert _read(root, json.dumps({"session_id": SID})) == "SID\n"
    assert _read(root, '{\n  "session_id" :  "%s"\n}\n' % SID) == "SID\n"
    assert _read(root, json.dumps({"session_id": SID}), {"NO_COLOR": "1"}) == "PLAIN\n"
    assert _read(root, json.dumps({"session_id": SID}), {"TMUX_PANE": "%12"}) == "PANE\n"
    assert _read(root, json.dumps({"session_id": SID}), {"TMUX_PANE": "%1x"}) == "SID\n"
    assert _read(root, "") == "NOSID\n"
    assert _read(root, "not json") == "NOSID\n"
    assert _read(root, json.dumps({"session_id": 5, "x": SID})) == "NOSID\n"
    # A sid that is not a safe file name never escapes the cache directory.
    (tmp_path / "evil").write_text("ESCAPED\n", encoding="utf-8")
    assert _read(root, json.dumps({"session_id": "../evil"})) == ""
    assert _read(root, json.dumps({"session_id": "x"}), {}) == ""
    assert _read(tmp_path / "missing", json.dumps({"session_id": SID})) == ""


@needs_sh
def test_chained_delegates_print_above_fleets_row(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / f"sid-{SID}").write_text("FLEET\n", encoding="utf-8")
    (root / "delegates").write_text(
        "printf 'OPERATOR\\n'\nexit 3\n", encoding="utf-8")
    assert _read(root, json.dumps({"session_id": SID})) == "OPERATOR\nFLEET\n"


def test_cache_outputs_copy_the_chain_one_command_per_line(home, monkeypatch):
    monkeypatch.setattr(sl, "_load_delegates",
                        lambda legacy_home=None: ["ccusage statusline", "bad\ncmd"])
    out = sl.cache_outputs()
    assert out["delegates"] == "ccusage statusline\n"
    assert {f"sid-{SID}", f"sid-{SID}.nocolor", "nosid", "unregistered"} <= set(out)


def test_cache_outputs_leave_fleet_unpatched(home):
    before = (fleet.read_registry_at, fleet.lookup_home_for_sid,
              fleet.status_snapshot, fleet.FLEET_HOME)
    sl.cache_outputs()
    assert (fleet.read_registry_at, fleet.lookup_home_for_sid,
            fleet.status_snapshot, fleet.FLEET_HOME) == before


# --- the reader is a view, and it is cheap ----------------------------------

def _reader_code():
    lines = READER.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_the_reader_writes_nothing_and_reads_only_the_cache():
    code = "\n".join(_reader_code())
    # Redirections: only reading the cache and discarding delegate stderr.
    for match in re.finditer(r"(\d?)>\s*([^\s);]+)", code):
        assert match.group(2) in ("/dev/null", "&1"), match.group(0)
    for match in re.finditer(r"<\s*(\S+)", code):
        assert match.group(1).startswith('"$cache/') or match.group(1) == '"$file"', match.group(0)


def test_the_reader_forks_only_for_chained_delegates():
    """Builtins only: no python, no cat/sed/grep/date, no substitution."""
    code = _reader_code()
    start = next(i for i, l in enumerate(code) if "$cache/delegates" in l and "if" in l)
    end = next(i for i in range(start, len(code)) if code[i].strip() == "fi"
               and code[i].startswith("fi"))
    rest = code[:start] + code[end + 1:]
    text = "\n".join(rest)
    assert "$(" not in text and "`" not in text
    for word in ("python", "cat", "sed", "grep", "awk", "date", "ps", "find",
                 "jq", "head", "tail", "tr", "cut", "fleet"):
        assert not re.search(rf"(^|[\s;|&(]){word}(\s|$)", text), word
    assert "refreshInterval" not in READER.read_text(encoding="utf-8")


@needs_sh
@pytest.mark.skipif(sys.platform == "win32", reason="resource accounting is POSIX")
def test_a_call_costs_under_five_ms(tmp_path):
    import resource
    root = tmp_path / "cache"
    root.mkdir()
    (root / f"sid-{SID}").write_text("[fleet] 3 working | 2 idle\n", encoding="utf-8")
    blob = json.dumps({"session_id": SID, "transcript_path": "x" * 400,
                       "model": {"id": "m", "display_name": "M"}}).encode()
    argv = [SH, str(READER), str(root)]
    subprocess.run(argv, input=blob, capture_output=True)   # warm the page cache
    calls, walls = 40, []
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    for _ in range(calls):
        start = time.perf_counter()
        out = subprocess.run(argv, input=blob, capture_output=True)
        walls.append(time.perf_counter() - start)
        assert out.stdout.startswith(b"[fleet]")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) / calls
    # CPU per call is the budget: < 5 ms, i.e. < 0.05 % of a CPU at one call
    # every 10 s (the old statusline cost 20-55 % per run). Wall time on a
    # shared box includes scheduler noise, so its best case is pinned.
    assert cpu < 0.005, f"{cpu * 1000:.2f} ms CPU per call"
    assert min(walls) < 0.005, f"{min(walls) * 1000:.2f} ms best wall"


def test_grouped_rendering_matches_the_live_render_across_homes(home, tmp_path):
    """Sids render once per membership group; every sid still gets the bytes
    the live path would print -- one home, the other home, or ambiguous."""
    second = tmp_path / "second"
    (second / "state").mkdir(parents=True)
    (second / "mailbox").mkdir()
    shared = "a0000203-0000-4000-8000-000000000203"
    only_b = "a0000204-0000-4000-8000-000000000204"
    (second / "state" / "fleet.json").write_text(json.dumps({"workers": {
        "b1": _rec(only_b, status="idle", last_activity=fleet.now_iso()),
        "b2": _rec(shared)}}), encoding="utf-8")
    data = fleet.load_registry()
    data["workers"]["w3"] = _rec(shared, status="limited")
    fleet.save_registry(data)
    fleet.homes_list_path().write_text(f"{home}\n{second}\n", encoding="utf-8")
    out = sl.cache_outputs()
    population = fleet.resolution_population()
    rendered = set()
    for sid in (SID, OTHER_SID, shared, only_b):
        live = "".join(row + "\n" for row in sl.render_rows(
            json.dumps({"session_id": sid}), population, ""))
        assert out[f"sid-{sid}"] == live, sid
        rendered.add(live)
    assert len(rendered) >= 3    # home A, home B and the ambiguity differ
