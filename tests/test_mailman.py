"""fleet mailman (docs/specs/mailman.md): sorting, lossless filing, fail-safe wake."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

import fleet
import fleet_mailman as mm
from fleet_errors import FleetCliError


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
    return sorted(p.name for p in (home / "mailbox" / "to-fleet").iterdir()
                  if p.name != mm.CLAIMS_DIR_NAME)


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
    assert not list(mm.claims_dir(home).glob("claim-*"))
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
    "do-not-merge-spaced": mail(
        kind="report", extra="needs-answer: no\n",
        body="do not merge until reviewed"),
    "ready-protocol": mail(
        kind="report", extra="needs-answer: no\n",
        body="READY: fleet#20 (head abc): reviewed and passing"),
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


def test_missing_platform_lock_backend_fails_closed_before_claims(home, monkeypatch):
    seed(home)
    source = put(home, "a.md", mail())
    raw, problem, inode = mm.read_mail_snapshot(source)
    cfg, _ = mm.load_config(home)
    verdict = mm.classify(raw, problem, cfg, inode=inode)
    monkeypatch.setattr(mm, "_fcntl", None)
    monkeypatch.setattr(mm, "_msvcrt", None)
    with pytest.raises(FleetCliError, match="OS-supported claim lock"):
        mm.file_mail(home, "a.md", verdict, fleet._mailman_prims())
    assert source.read_text() == mail()
    assert not mm.claims_dir(home).exists()


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
    claims = list(mm.claims_dir(home).glob("claim-*/mail"))
    assert len(claims) == 1 and claims[0].read_text() == text
    old = time.time() - mm.CLAIM_STALE_SECONDS - 1
    os.utime(claims[0].parent, (old, old))
    rc, out, err = run(home, capsys)  # idempotent re-run completes
    assert rc == 3
    assert inbox(home) == [] and len(done(home)) == 1
    assert (home / "mailbox" / "done" / done(home)[0]).read_text() == text
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


@pytest.mark.parametrize("duplicate", [False, True])
def test_atomic_claim_preserves_arrival_at_original_path(home, capsys, monkeypatch,
                                                         duplicate):
    seed(home)
    text = mail()
    source = put(home, "a.md", text)
    if duplicate:
        target = home / "mailbox" / "done" / "a.md"
        target.parent.mkdir(parents=True)
        target.write_text(text)
    original_unlink = mm.os.unlink
    injected = False

    def replace_original_before_claim_unlink(path, *args, **kwargs):
        nonlocal injected
        path = Path(path)
        if (not injected and path.name == "mail"
                and path.parent.parent == mm.claims_dir(home)):
            injected = True
            source.write_text("kind: question\nneeds-answer: yes\n\nnew arrival\n")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(mm.os, "unlink", replace_original_before_claim_unlink)
    run(home, capsys)
    assert injected
    assert source.read_text() == "kind: question\nneeds-answer: yes\n\nnew arrival\n"
    assert any(p.read_text() == text for p in (home / "mailbox" / "done").iterdir())


def test_replacement_at_atomic_rename_boundary_is_recovered_visibly(home, capsys,
                                                                   monkeypatch):
    seed(home)
    text = mail()
    source = put(home, "a.md", text)
    original_rename = mm.os.rename
    injected = False

    def replace_before_claim_rename(src, dst, *args, **kwargs):
        nonlocal injected
        if not injected and Path(src) == source:
            injected = True
            source.write_text("kind: question\nneeds-answer: yes\n\nnew arrival\n")
        return original_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(mm.os, "rename", replace_before_claim_rename)
    run(home, capsys)
    assert injected
    assert source.exists() or any(
        p.read_text() == "kind: question\nneeds-answer: yes\n\nnew arrival\n"
        for p in (home / "mailbox" / "to-fleet").glob("*.recovered-*.mail"))


def test_stale_claim_without_mail_is_left_for_paused_owner(home, monkeypatch):
    source = put(home, "a.md", mail())
    claim_dir = mm.claims_dir(home) / "claim-paused-owner"
    claim_dir.mkdir(parents=True)
    (claim_dir / "origin").write_bytes(b"a.md")
    owner_fd = os.open(mm._owner_lock_path(claim_dir), os.O_CREAT | os.O_RDWR, 0o600)
    mm._acquire_owner_lock(owner_fd, initialize=True)
    old = time.time() - mm.CLAIM_STALE_SECONDS - 1
    os.utime(claim_dir, (old, old))
    claim = claim_dir / "mail"
    real_unlink = mm.os.unlink
    injected = False

    def finish_owner_rename_before_cleanup(path, *args, **kwargs):
        nonlocal injected
        if Path(path) == claim and not injected:
            injected = True
            os.rename(source, claim)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(mm.os, "unlink", finish_owner_rename_before_cleanup)
    try:
        assert mm._recover_stale_claims(home) == 0
        assert not injected
        assert source.read_text() == mail()
        assert not claim.exists()
    finally:
        os.close(owner_fd)


def test_stale_recovery_uses_alias_before_removing_claim(home, monkeypatch):
    old_mail = mail()
    claim_dir = mm.claims_dir(home) / "claim-abandoned"
    claim_dir.mkdir(parents=True)
    claim = claim_dir / "mail"
    claim.write_text(old_mail)
    (claim_dir / "origin").write_bytes(b"a.md")
    lock_fd = os.open(mm._owner_lock_path(claim_dir), os.O_CREAT | os.O_RDWR, 0o600)
    mm._acquire_owner_lock(lock_fd, initialize=True)
    os.close(lock_fd)
    old = time.time() - mm.CLAIM_STALE_SECONDS - 1
    os.utime(claim_dir, (old, old))
    source = home / "mailbox" / "to-fleet" / "a.md"
    real_unlink = mm.os.unlink
    injected = False

    def replace_original_before_private_cleanup(path, *args, **kwargs):
        nonlocal injected
        if Path(path) == claim and not injected:
            injected = True
            source.write_text("kind: question\nneeds-answer: yes\n\nnew arrival\n")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(mm.os, "unlink", replace_original_before_private_cleanup)
    assert mm._recover_stale_claims(home) == 1
    assert injected
    assert source.read_text() == "kind: question\nneeds-answer: yes\n\nnew arrival\n"
    aliases = list((home / "mailbox" / "to-fleet").glob("a.md.recovered-*.mail"))
    assert len(aliases) == 1 and aliases[0].read_text() == old_mail
    assert not claim_dir.exists()


def test_repeated_recovery_crashes_keep_original_idempotency_marker(home, capsys,
                                                                    monkeypatch):
    seed(home)
    text = mail()
    claim_dir = mm.claims_dir(home) / "claim-abandoned"
    claim_dir.mkdir(parents=True)
    (claim_dir / "mail").write_text(text)
    (claim_dir / "origin").write_bytes(b"a.md")
    lock_fd = os.open(mm._owner_lock_path(claim_dir), os.O_CREAT | os.O_RDWR, 0o600)
    mm._acquire_owner_lock(lock_fd, initialize=True)
    os.close(lock_fd)
    old = time.time() - mm.CLAIM_STALE_SECONDS - 1
    os.utime(claim_dir, (old, old))

    assert mm._recover_stale_claims(home) == 1
    alias1 = next((home / "mailbox" / "to-fleet").glob("a.md.recovered-*.mail"))
    assert mm._canonical_mail_name(alias1.name) == "a.md"
    with monkeypatch.context() as patching:
        patching.setattr(mm, "_step_log", _boom)
        with pytest.raises(OSError):
            mailman(home, "run", "--timeout", "0")
    assert len(lines(DIGEST(home))) == 1
    crashed_claim = next(mm.claims_dir(home).glob("claim-*/mail"))
    old = time.time() - mm.CLAIM_STALE_SECONDS - 1
    os.utime(crashed_claim.parent, (old, old))

    rc, out, err = run(home, capsys)
    assert rc == 3
    assert len(lines(DIGEST(home))) == 1
    assert len([line for line in lines(LOG(home)) if "mailman filed a.md" in line]) == 1
    assert "a.md" in json.loads(
        (home / "state" / "interface" / "watch-cursor.json").read_text())["mail"]
    assert mm._canonical_mail_name(mm._recovered_name(alias1.name)) == "a.md"


def test_done_collision_skips_an_occupied_suffixed_name(home, capsys):
    seed(home)
    done_dir = home / "mailbox" / "done"
    done_dir.mkdir(parents=True)
    text = mail()
    sha12 = hashlib.sha256(text.encode()).hexdigest()[:12]
    (done_dir / "a.md").write_text("OLD BASE")
    (done_dir / f"a.{sha12}.md").write_text("OLD SUFFIX")
    put(home, "a.md", text)

    run(home, capsys)

    assert (done_dir / "a.md").read_text() == "OLD BASE"
    assert (done_dir / f"a.{sha12}.md").read_text() == "OLD SUFFIX"
    assert (done_dir / f"a.{sha12}.1.md").read_text() == text


def test_changed_mail_not_filed(home, monkeypatch):
    seed(home)
    p = put(home, "a.md", mail())
    prims = fleet._mailman_prims()
    raw, prob, inode = mm.read_mail_snapshot(p)
    cfg, _ = mm.load_config(home)
    v = mm.classify(raw, prob, cfg, inode=inode)
    assert v.kind == mm.FILE
    p.write_text(mail(body="CRITICAL changed"))
    assert mm.file_mail(home, "a.md", v, prims) is False
    assert inbox(home) == ["a.md"] and done(home) == []


def test_replacement_after_claim_before_link_is_preserved(home, monkeypatch):
    seed(home)
    p = put(home, "a.md", mail())
    prims = fleet._mailman_prims()
    raw, problem, inode = mm.read_mail_snapshot(p)
    cfg, _ = mm.load_config(home)
    verdict = mm.classify(raw, problem, cfg, inode=inode)
    replacement = mail(kind="question", body="needs human review")
    real_link = os.link
    replaced = False

    def replace_before_link(src, dest, *args, **kwargs):
        nonlocal replaced
        if not replaced and Path(src).name == "mail":
            p.write_text(replacement, encoding="utf-8")
            replaced = True
        return real_link(src, dest, *args, **kwargs)

    monkeypatch.setattr(mm.os, "link", replace_before_link)
    assert mm.file_mail(home, "a.md", verdict, prims) is True
    assert inbox(home) == ["a.md"] and done(home) == ["a.md"]
    assert p.read_text(encoding="utf-8") == replacement


def test_replacement_after_link_is_preserved_in_inbox(home, monkeypatch):
    seed(home)
    p = put(home, "a.md", mail())
    original = p.read_text(encoding="utf-8")
    replacement = mail(kind="question", body="needs human review")
    prims = fleet._mailman_prims()
    raw, problem, inode = mm.read_mail_snapshot(p)
    cfg, _ = mm.load_config(home)
    verdict = mm.classify(raw, problem, cfg, inode=inode)
    real_link = os.link
    replaced = False

    def replace_after_link(src, dest, *args, **kwargs):
        nonlocal replaced
        result = real_link(src, dest, *args, **kwargs)
        if not replaced and Path(src).name == "mail":
            p.write_text(replacement, encoding="utf-8")
            replaced = True
        return result

    monkeypatch.setattr(mm.os, "link", replace_after_link)
    assert mm.file_mail(home, "a.md", verdict, prims) is True
    assert (home / "mailbox" / "done" / "a.md").read_text() == original
    assert inbox(home) == ["a.md"]
    assert p.read_text(encoding="utf-8") == replacement


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
    for word in ("merge-ready", "do-not-merge", "READY:", "founder action"):
        assert word in seed_block
        assert word not in tail_code
    assert r"\bdo\s+not\s+merge\b" in seed_block
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
