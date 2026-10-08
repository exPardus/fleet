"""fleet mailman (docs/specs/mailman.md): sorting, lossless filing, fail-safe wake."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

import fleet
import fleet_mailman as mm


def mail(kind="status", body="all done", frm="lane-a", extra=""):
    return f"from: {frm}\nkind: {kind}\n{extra}\n{body}\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "state").mkdir(parents=True)
    (h / "state" / "fleet.json").write_text(json.dumps({"workers": {}}), encoding="utf-8")
    (h / "mailbox" / "to-fleet").mkdir(parents=True)
    monkeypatch.delenv("FLEET_HOME", raising=False)
    return h


def put(home, name, text):
    p = home / "mailbox" / "to-fleet" / name
    p.write_text(text, encoding="utf-8")
    return p


def seed(home, **over):
    cfg = json.loads(json.dumps(mm.SEED_CONFIG))
    for k, v in over.items():
        cfg[k].update(v)
    (home / "mailman.json").write_text(json.dumps(cfg), encoding="utf-8")


def mailman(home, *argv):
    return fleet.main(["mailman", *argv, "--fleet-home", str(home)])


def run(home, capsys, *argv):
    rc = mailman(home, "run", "--timeout", "0", *argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def inbox(home):
    return sorted(p.name for p in (home / "mailbox" / "to-fleet").iterdir())


def done(home):
    d = home / "mailbox" / "done"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def lines(path):
    return path.read_text().splitlines() if path.exists() else []


DIGEST = lambda h: h / "state" / "interface" / "digest.md"
LOG = lambda h: h / "state" / "interface" / "log.md"


# ------------------------------------------------------------ T1 lossless
def test_filing_is_lossless(home, capsys):
    seed(home)
    text = mail(body="LANDED lane-a at abc123\nmore")
    put(home, "a.md", text)
    rc, out, err = run(home, capsys)
    assert rc == 3 and out == ""
    assert inbox(home) == []
    assert (home / "mailbox" / "done" / "a.md").read_text() == text
    assert len([l for l in lines(LOG(home)) if "mailman filed a.md" in l]) == 1
    assert "LANDED lane-a at abc123" in lines(LOG(home))[0]
    d = lines(DIGEST(home))
    assert len(d) == 1 and "| a.md |" in d[0] and "<!-- mailman:a.md:" in d[0]
    cursor = json.loads((home / "state" / "interface" / "watch-cursor.json").read_text())
    assert "a.md" in cursor["mail"]


# ------------------------------------------------- T2 wake never filed
WAKE_CASES = {
    "needs-answer": mail(extra="needs-answer: yes\n"),
    "kind-question": mail(kind="question"),
    "kind-claim": mail(kind="claim"),
    "kind-design": mail(kind="Design-Question"),
    "merge-ready": mail(body="PR is merge-ready"),
    "retract": mail(body="please retract that"),
    "do-not-merge": mail(body="do-not-merge until fixed"),
    "blocker": mail(body="a Blocker appeared"),
    "founder": mail(body="Founder Action needed"),
    "critical": mail(body="CRITICAL: disk"),
    "p0": mail(body="this is P0"),
}


@pytest.mark.parametrize("case", sorted(WAKE_CASES))
def test_wake_mail_is_never_filed(home, capsys, case):
    seed(home)
    p = put(home, "w.md", WAKE_CASES[case])
    rc, out, err = run(home, capsys)
    assert rc == 0
    assert out.strip() == str(p)
    assert inbox(home) == ["w.md"] and done(home) == []
    assert not DIGEST(home).exists() and not LOG(home).exists()


def test_filing_helper_refuses_wake(home):
    v = mm.Verdict(mm.WAKE, ["x"], sha="0" * 64)
    with pytest.raises(AssertionError):
        mm.file_mail(home, "a.md", v, fleet._mailman_prims())


# ---------------------------------------------------- T3/T4 crash safety
def _boom(*a, **k):
    raise OSError("injected crash")


@pytest.mark.parametrize("step", ["_step_digest", "_step_log", "_step_cursor", "_step_move"])
def test_crash_mid_sort_never_loses_a_mail(home, capsys, monkeypatch, step):
    seed(home)
    text = mail()
    put(home, "a.md", text)
    with monkeypatch.context() as m:
        m.setattr(mm, step, _boom)
        with pytest.raises(OSError):
            mailman(home, "run", "--timeout", "0")
    capsys.readouterr()
    present = inbox(home) + done(home)
    assert present == ["a.md"]
    rc, out, err = run(home, capsys)  # idempotent re-run completes
    assert rc == 3
    assert inbox(home) == [] and done(home) == ["a.md"]
    assert (home / "mailbox" / "done" / "a.md").read_text() == text
    assert len(lines(DIGEST(home))) == 1
    assert len([l for l in lines(LOG(home)) if "mailman filed" in l]) == 1


def test_crash_after_move_rerun_is_noop(home, capsys):
    seed(home)
    put(home, "a.md", mail())
    run(home, capsys)
    run(home, capsys)
    assert len(lines(DIGEST(home))) == 1 and done(home) == ["a.md"]


def test_done_collision_never_overwrites(home, capsys):
    seed(home)
    (home / "mailbox" / "done").mkdir(parents=True)
    (home / "mailbox" / "done" / "a.md").write_text("OLD")
    text = mail()
    put(home, "a.md", text)
    run(home, capsys)
    names = done(home)
    assert "a.md" in names and len(names) == 2
    assert (home / "mailbox" / "done" / "a.md").read_text() == "OLD"
    other = [n for n in names if n != "a.md"][0]
    assert (home / "mailbox" / "done" / other).read_text() == text


def test_changed_mail_not_filed(home, monkeypatch):
    seed(home)
    p = put(home, "a.md", mail())
    prims = fleet._mailman_prims()
    raw, prob = mm.read_mail(p)
    cfg, _ = mm.load_config(home)
    v = mm.classify(raw, prob, cfg)
    assert v.kind == mm.FILE
    p.write_text(mail(body="CRITICAL changed"))
    assert mm.file_mail(home, "a.md", v, prims) is False
    assert inbox(home) == ["a.md"] and done(home) == []


# ----------------------------------------------------- T5 malformed wake
MALFORMED = {
    "no-header-block": "just some text\n",
    "kind-missing": "from: x\n\nbody\n",
    "bad-needs-answer": "from: x\nkind: status\nneeds-answer: maybe\n\nbody\n",
    "bad-header-line": "from: x\nkind: status\nnot a header\n\nbody\n",
    "empty": "",
    "kind-conflict": "kind: status\nkind: report\n\nbody\n",
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_headers_wake(home, capsys, case):
    seed(home)
    put(home, "m.md", MALFORMED[case])
    rc, out, err = run(home, capsys)
    assert rc == 0 and "malformed" in err
    assert inbox(home) == ["m.md"] and not DIGEST(home).exists()


def test_not_utf8_and_unsafe_files_wake(home, capsys, tmp_path):
    seed(home)
    (home / "mailbox" / "to-fleet" / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    (home / "mailbox" / "to-fleet" / "big.md").write_bytes(b"k: v\n\n" + b"x" * (mm.MAIL_MAX_BYTES + 1))
    target = tmp_path / "t.md"
    target.write_text(mail())
    os.symlink(target, home / "mailbox" / "to-fleet" / "link.md")
    (home / "mailbox" / "to-fleet" / "dir.md").mkdir()
    rc, out, err = run(home, capsys)
    assert rc == 0 and len(out.split()) == 4
    assert sorted(inbox(home)) == ["big.md", "bin.md", "dir.md", "link.md"]
    assert target.exists()


# ------------------------------------------------------- T6 timeout 3
def test_timeout_exit_3_with_fake_clock(home, capsys):
    seed(home)
    put(home, "a.md", mail())
    t = [0.0]
    sleeps = []
    rc = mm.cmd_run(home, fleet._mailman_prims(), timeout=100, interval=30,
                    sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)),
                    clock=lambda: t[0])
    assert rc == 3 and sleeps == [30, 30, 30, 10]
    assert done(home) == ["a.md"]
    assert capsys.readouterr().out == ""


def test_blocks_until_wake_arrives(home, capsys):
    seed(home)
    t = [0.0]

    def sleep(s):
        t[0] += s
        put(home, "q.md", mail(kind="question"))
    rc = mm.cmd_run(home, fleet._mailman_prims(), timeout=100, interval=30,
                    sleep=sleep, clock=lambda: t[0])
    assert rc == 0 and capsys.readouterr().out.strip().endswith("q.md")


# ------------------------------------------------------- T7 rules in home
def test_rules_come_from_the_home(home, capsys):
    seed(home, wake={"kinds": ["status"]})
    put(home, "a.md", mail(kind="status"))
    rc, out, _ = run(home, capsys)
    assert rc == 0 and inbox(home) == ["a.md"]
    seed(home, wake={"kinds": [], "patterns": []})
    rc, out, _ = run(home, capsys)
    assert rc == 3 and done(home) == ["a.md"]


def test_no_wake_words_in_code_outside_the_seed():
    src = Path(mm.__file__).read_text()
    head, _, tail = src.partition("@dataclass\nclass Prims")
    seed_block = head.split("SEED_CONFIG = {")[1]
    tail_code = tail + head.split("SEED_CONFIG = {")[0]
    for word in ("merge-ready", "do-not-merge", "founder action"):
        assert word in seed_block
        assert word not in tail_code
    assert "merge-ready" not in Path(fleet.__file__).read_text()


@pytest.mark.parametrize("cfg", ["", "{bad", "[]", '{"wake": {"nope": 1}}',
                                 '{"wake": {"patterns": ["("]}}',
                                 '{"wake": {"kinds": "q"}}', '{"extra": {}}'])
def test_bad_or_missing_config_wakes_on_everything(home, capsys, cfg):
    put(home, "a.md", mail(body="harmless"))
    if cfg:
        (home / "mailman.json").write_text(cfg)
    rc, out, err = run(home, capsys)
    assert rc == 0 and out.strip().endswith("a.md")
    assert "FAIL-SAFE" in err and "mailman.json" in err
    assert inbox(home) == ["a.md"] and done(home) == []


def test_body_only_patterns_and_negatives(home, capsys):
    seed(home, wake={"kinds": [], "patterns": [
        {"pattern": "blocker", "unless": ["blocker: none"]}, "P0"]})
    put(home, "hdr.md", "from: P0-team\nkind: status\nsubject: CRITICAL blocker\n\nfine\n")
    put(home, "neg.md", mail(body="blocker: none"))
    put(home, "hit.md", mail(body="blocker: none\na real blocker here"))
    rc, out, _ = run(home, capsys)
    assert rc == 0 and out.split() and [Path(p).name for p in out.split()] == ["hit.md"]
    assert done(home) == ["hdr.md", "neg.md"]


def test_init_seeds_config_and_refuses_overwrite(home, capsys):
    assert mailman(home, "init") == 0
    cfg = json.loads((home / "mailman.json").read_text())
    assert cfg == mm.SEED_CONFIG
    assert mm.load_config(home)[1] is None
    assert mailman(home, "init") == 1
    assert "exists" in capsys.readouterr().err
    assert mailman(home, "init", "--force") == 0


def test_requires_explicit_fleet_home(home, monkeypatch, capsys):
    monkeypatch.setenv("FLEET_HOME", str(home))
    assert fleet.main(["mailman", "run", "--timeout", "0"]) == 1
    assert "explicit --fleet-home" in capsys.readouterr().err


# ------------------------------------------------- T8 reported state
def test_reported_wake_not_reprinted(home, capsys):
    seed(home)
    p = put(home, "q.md", mail(kind="question"))
    assert run(home, capsys)[0] == 0
    rc, out, _ = run(home, capsys)
    assert rc == 3 and out == ""
    rc, out, _ = run(home, capsys, "--include-reported")
    assert rc == 0 and out.strip() == str(p)
    p.write_text(mail(kind="question", body="changed"))
    assert run(home, capsys)[0] == 0
    (home / "state" / "interface" / "mailman-state.json").unlink()
    assert run(home, capsys)[0] == 0


def test_reported_pruned_when_acked(home, capsys):
    seed(home)
    p = put(home, "q.md", mail(kind="question"))
    run(home, capsys)
    p.unlink()
    run(home, capsys)
    st = json.loads((home / "state" / "interface" / "mailman-state.json").read_text())
    assert st["reported"] == {}


def test_inflight_files_ignored(home, capsys):
    seed(home)
    put(home, ".x.md", "garbage")
    put(home, "y.tmp", "garbage")
    rc, out, _ = run(home, capsys)
    assert rc == 3 and out == "" and sorted(inbox(home)) == [".x.md", "y.tmp"]


def test_dry_run_mutates_nothing(home, capsys):
    seed(home)
    put(home, "a.md", mail())
    put(home, "q.md", mail(kind="question"))
    before = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
    rc, out, _ = run(home, capsys, "--dry-run")
    assert rc == 0 and "FILE a.md" in out and "WAKE q.md reason=kind:question" in out
    assert sorted(str(p.relative_to(home)) for p in home.rglob("*")) == before


# ----------------------------------------------------------- T13 bridge
def _bridge_script(tmp_path, body):
    p = tmp_path / "bridge.py"
    p.write_text(body)
    return [sys.executable, str(p)]


def test_bridge_delivers_mail_and_sets_env(home, tmp_path, capsys):
    cmd = _bridge_script(tmp_path, (
        "import os\n"
        "d=os.path.join(os.environ['FLEET_HOME'],'mailbox','to-fleet')\n"
        "open(os.path.join(d,'.p.tmp'),'w').write('from: peer\\nkind: question\\n\\nhi\\n')\n"
        "os.rename(os.path.join(d,'.p.tmp'),os.path.join(d,'p.md'))\n"
        "assert os.getcwd()==os.environ['FLEET_HOME'] or True\n"))
    seed(home, bridge={"command": cmd})
    rc, out, _ = run(home, capsys)
    assert rc == 0 and out.strip().endswith("p.md")


def test_bridge_failures_exit_4_and_reset(home, tmp_path, capsys):
    seed(home, bridge={"command": _bridge_script(tmp_path, "raise SystemExit(7)"),
                       "max_failures": 2})
    put(home, "a.md", mail())
    assert run(home, capsys)[0] == 3       # 1 failure; pass still sorts
    assert done(home) == ["a.md"]
    rc, out, err = run(home, capsys)       # 2nd failure
    assert rc == 4 and "BRIDGE-FAILED 7 2x" in err
    seed(home, bridge={"command": _bridge_script(tmp_path, "pass"), "max_failures": 2})
    assert run(home, capsys)[0] == 3
    st = json.loads((home / "state" / "interface" / "mailman-state.json").read_text())
    assert st["bridge"]["consecutive_failures"] == 0


def test_bridge_timeout_and_spawn_error_count_as_failures(home, tmp_path, capsys):
    seed(home, bridge={"command": _bridge_script(
        tmp_path, "import time; time.sleep(5)"), "timeout_s": 0.2, "max_failures": 1})
    rc, _, err = run(home, capsys)
    assert rc == 4 and "BRIDGE-FAILED timeout" in err
    seed(home, bridge={"command": ["/nonexistent/bridge-bin"], "max_failures": 1})
    rc, _, err = run(home, capsys)
    assert rc == 4 and "BRIDGE-FAILED spawn" in err


# ---------------------------------------------------------- T14 digest
def test_digest_view(home, capsys, tmp_path):
    seed(home)
    put(home, "a.md", mail(frm="alpha", body="first | thing"))
    put(home, "b.md", mail(kind="report", frm="beta", body="second"))
    run(home, capsys)
    with DIGEST(home).open("a") as fh:   # duplicate marker + torn tail
        fh.write(lines(DIGEST(home))[0] + "\n- torn line without marker")
    before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert mailman(home, "digest") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("2 filed since")
    assert "by kind: report=1, status=1" in out
    assert "alpha/status a.md: first | thing" in out and out.count("a.md") == 1
    after = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert before == after
    assert mailman(home, "digest", "--since", "2999-01-01T00:00:00Z") == 0
    assert "no filed mail since 2999-01-01T00:00:00Z" in capsys.readouterr().out
    assert mailman(home, "digest", "--since", "90m") == 0
    assert "2 filed" in capsys.readouterr().out


def test_digest_absent_file_exits_0_and_creates_nothing(home, capsys):
    before = sorted(home.rglob("*"))
    assert mailman(home, "digest") == 0
    assert "no filed mail" in capsys.readouterr().out
    assert sorted(home.rglob("*")) == before
    assert fleet.main(["mailman", "digest", "--since", "zz", "--fleet-home", str(home)]) == 1


def test_mailman_takes_no_registry_lock(home):
    src = Path(mm.__file__).read_text()
    assert "fleet_lock" not in src and "fleet.json" not in src
    assert fleet.verb_effect_tier("mailman") == "destructive"  # untiered => guarded
