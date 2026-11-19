"""Migration module: render to `to-fleet/`, `import`, fold reader
(spec docs/specs/messaging.md §12 steps 2-3, §8, §14; plan PR 9a)."""
import os
from pathlib import Path

import pytest

import fleet_msg_core as core
import fleet_msg_migrate as mig

NOW = 1_800_000_000.0
AUTH = {"method": "lane-registry", "detail": None}


class Crash(Exception):
    pass


def make_store(tmp_path, site="a", **kw):
    kw.setdefault("clock", lambda: NOW)
    return core.Store(tmp_path / "home", site, **kw)


def env_to_interface(body="please look", **kw):
    kw.setdefault("needs_answer", True)
    draft = core.make_draft("lane-1@a", "interface@a", body, from_auth=AUTH,
                            sent_at=core.iso_utc(NOW), kind="note", **kw)
    return core.validate(dict(draft, seq=1))


def mail(directory, name, text):
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def to_fleet(home):
    return Path(home) / "mailbox" / "to-fleet"


# --- render ----------------------------------------------------------------

def test_render_writes_mailman_format_with_msg_id(tmp_path):
    store, env = make_store(tmp_path), env_to_interface()
    assert mig.render_to_fleet(store, env) == "rendered"
    text = (to_fleet(store.home) / mig.mail_name(env["id"])).read_text()
    assert text == (f"from: lane-1@a\nkind: note\nneeds-answer: yes\n"
                    f"msg-id: {env['id']}\n\nplease look\n")
    parsed = mig.parse_mail(text.encode())
    assert parsed["needs_answer"] and parsed["headers"]["msg-id"] == [env["id"]]
    assert parsed["body"] == "please look"
    assert os.listdir(to_fleet(store.home)) == [mig.mail_name(env["id"])]


def test_render_carries_re_and_needs_answer_no(tmp_path):
    store, parent = make_store(tmp_path), env_to_interface()
    reply = core.validate(dict(core.make_draft(
        "lane-2@a", "interface@a", "ok", from_auth=AUTH, sent_at=core.iso_utc(NOW),
        parent=parent), seq=1))
    mig.render_to_fleet(store, reply)
    text = (to_fleet(store.home) / mig.mail_name(reply["id"])).read_text()
    assert f"re: {parent['id']}\n" in text and "needs-answer: no\n" in text


def test_render_is_idempotent_and_survives_mailman_filing(tmp_path):
    store, env = make_store(tmp_path), env_to_interface()
    home = store.home
    assert mig.render_to_fleet(store, env) == "rendered"
    assert mig.render_to_fleet(store, env) == "duplicate"
    done = home / "mailbox" / "done"
    done.mkdir()
    os.rename(to_fleet(home) / mig.mail_name(env["id"]), done / mig.mail_name(env["id"]))
    assert mig.render_to_fleet(store, env) == "duplicate"
    assert os.listdir(to_fleet(home)) == []


def test_render_filed_copy_with_collision_suffix_counts(tmp_path):
    store, env = make_store(tmp_path), env_to_interface()
    done = store.home / "mailbox" / "done"
    done.mkdir(parents=True)
    (done / f"msg-{env['id']}.abc123def456.mail").write_text("x")
    assert mig.render_to_fleet(store, env) == "duplicate"


@pytest.mark.parametrize("point", ["tmp-written", "linked", "dir-synced",
                                   "render-staged", "render-linked"])
def test_render_crash_at_each_step_never_shows_a_partial_and_retry_writes_one(tmp_path, point):
    home, env = tmp_path / "home", env_to_interface()
    fired = []

    def fault(p):
        if p == point and not fired:
            fired.append(p)
            raise Crash

    with pytest.raises(Crash):
        mig.render_to_fleet(core.Store(home, "a", clock=lambda: NOW, fault=fault), env)
    shown = os.listdir(to_fleet(home)) if to_fleet(home).exists() else []
    assert shown in ([], [mig.mail_name(env["id"])])
    for name in shown:                       # whole or absent, never partial
        assert (to_fleet(home) / name).read_text().endswith("please look\n")
    clean = core.Store(home, "a", clock=lambda: NOW)
    assert mig.render_to_fleet(clean, env) in ("rendered", "duplicate")
    assert mig.render_to_fleet(clean, env) == "duplicate"
    assert os.listdir(to_fleet(home)) == [mig.mail_name(env["id"])]


def test_render_refuses_other_recipient(tmp_path):
    env = core.validate(dict(core.make_draft(
        "lane-1@a", "lane-2@a", "x", from_auth=AUTH, sent_at=core.iso_utc(NOW)), seq=1))
    with pytest.raises(mig.MigrateError):
        mig.render_to_fleet(make_store(tmp_path), env)


@pytest.mark.parametrize("link", ["mailbox", "to-fleet", "render"])
def test_render_refuses_a_symlinked_component(tmp_path, link):
    store, env = make_store(tmp_path), env_to_interface()
    home = store.home
    target = tmp_path / "elsewhere"
    target.mkdir()
    if link == "mailbox":
        home.mkdir()
        (home / "mailbox").symlink_to(target)
    elif link == "to-fleet":
        (home / "mailbox").mkdir(parents=True)
        (home / "mailbox" / "to-fleet").symlink_to(target)
    else:
        (home / "state" / "msg").mkdir(parents=True)
        (home / "state" / "msg" / "render").symlink_to(target)
    with pytest.raises((mig.MigrateError, core.StoreError)):
        mig.render_to_fleet(store, env)
    assert os.listdir(target) == []


def test_render_refuses_a_planted_staged_symlink(tmp_path):
    store, env = make_store(tmp_path), env_to_interface()
    victim = tmp_path / "victim.mail"
    victim.write_text("keep")
    staged = store.root / "render"
    staged.mkdir(parents=True)
    (staged / mig.mail_name(env["id"])).symlink_to(victim)
    with pytest.raises(core.StoreError):
        mig.render_to_fleet(store, env)
    assert victim.read_text() == "keep"
    assert not (to_fleet(store.home) / mig.mail_name(env["id"])).exists()


# --- import -----------------------------------------------------------------

def test_import_sends_each_file_as_legacy_unverified(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: Ops Desk\nkind: question\nneeds-answer: yes\n\nhello there\n")
    mail(out, "b.mail", "from: x\nkind: note\n\nsecond\n")
    result = mig.import_dir(store, out, "hub@a")
    assert [n for n, _ in result.imported] == ["a.mail", "b.mail"]
    env = core.parse((store.spool("hub", "new") / f"{result.imported[0][1]}.json").read_bytes())
    assert env["from"] == "ops-desk@a" and env["from_auth"]["method"] == "legacy-unverified"
    assert env["needs_answer"] is True and env["kind"] == "note" and env["body"] == "hello there"
    assert sorted(os.listdir(out)) == ["a.mail", "b.mail"]        # source untouched


def test_import_remote_target_queues(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    result = mig.import_dir(store, out, "hub@b")
    assert len(result.imported) == 1
    assert len(os.listdir(store.outbox("b", "q"))) == 1


def test_import_second_run_is_all_duplicates(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    first = mig.import_dir(store, out, "hub@a")
    second = mig.import_dir(store, out, "hub@a")
    assert second.imported == [] and second.duplicate == first.imported
    assert len(os.listdir(store.spool("hub", "new"))) == 1


def test_import_crash_mid_run_then_rerun_delivers_each_once(tmp_path):
    out = tmp_path / "out"
    for i in range(3):
        mail(out, f"m{i}.mail", f"from: ops\nkind: note\n\nbody {i}\n")
    for point in ("seq-allocated", "marked", "ledgered"):
        home = tmp_path / point
        calls = []

        def fault(p, point=point, calls=calls):
            if p == point and not calls:
                calls.append(p)
                raise Crash

        crashing = core.Store(home, "a", clock=lambda: NOW, fault=fault)
        with pytest.raises(Crash):
            mig.import_dir(crashing, out, "hub@a")
        clean = core.Store(home, "a", clock=lambda: NOW)
        mig.import_dir(clean, out, "hub@a")
        mig.import_dir(clean, out, "hub@a")
        names = sorted(os.listdir(clean.spool("hub", "new")))
        assert len(names) == 3 == len(set(names)), point


def test_import_ids_are_stable_and_msg_id_header_wins(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    known = "ab" * 16
    mail(out, "a.mail", f"from: ops\nkind: note\nmsg-id: {known}\n\nhi\n")
    result = mig.import_dir(store, out, "hub@a")
    assert result.imported == [("a.mail", known)]
    raw = (out / "a.mail").read_bytes()
    assert mig.legacy_id("x.mail", raw) == mig.legacy_id("x.mail", raw)
    assert mig.legacy_id("x.mail", raw) != mig.legacy_id("y.mail", raw)


def test_render_then_import_is_one_message(tmp_path):
    """A rendered mail imported back keeps its id, so the store dedups it."""
    store = make_store(tmp_path)
    env = env_to_interface()
    core.publish(store, "interface", env)
    mig.render_to_fleet(store, env)
    result = mig.import_dir(store, to_fleet(store.home), "interface@a")
    assert result.imported == [] and [i for _, i in result.duplicate] == [env["id"]]


@pytest.mark.parametrize("name, text, why", [
    ("bad.mail", "no header block here\n", "header"),
    ("nokind.mail", "from: x\n\nbody\n", "kind"),
    ("na.mail", "from: x\nkind: note\nneeds-answer: maybe\n\nb\n", "needs-answer"),
    ("big.mail", "from: x\nkind: note\n\n" + "word " * 200 + "\n", "words"),
])
def test_import_skips_bad_files_and_leaves_them(tmp_path, name, text, why):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, name, text)
    result = mig.import_dir(store, out, "hub@a")
    assert result.imported == [] and result.skipped and why in result.skipped[0][1]
    assert (out / name).exists()


def test_import_skips_hidden_tmp_dirs_and_non_utf8(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, ".hidden", "from: x\nkind: note\n\nb\n")
    mail(out, "x.tmp", "from: x\nkind: note\n\nb\n")
    (out / "sub").mkdir()
    (out / "bin.mail").write_bytes(b"\xff\xfe\x00bad")
    result = mig.import_dir(store, out, "hub@a")
    assert result.imported == []
    assert [n for n, _ in result.skipped] == ["bin.mail", "sub"]


def test_import_refuses_symlinked_files_and_directory(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    secret = tmp_path / "secret.mail"
    secret.write_text("from: x\nkind: note\n\nTOPSECRET\n")
    out.mkdir()
    (out / "link.mail").symlink_to(secret)
    result = mig.import_dir(store, out, "hub@a")
    assert result.imported == [] and result.skipped == [("link.mail", "not a regular file")]
    assert not os.path.lexists(store.root / "spool")
    linked = tmp_path / "linked"
    linked.symlink_to(out)
    with pytest.raises(mig.MigrateError):
        mig.import_dir(store, linked, "hub@a")


def test_import_oversize_file_never_read_in_full(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    out.mkdir()
    (out / "big.mail").write_bytes(b"from: x\nkind: note\n\n" + b"a" * (mig.MAIL_MAX_BYTES + 1))
    result = mig.import_dir(store, out, "hub@a")
    assert result.skipped == [("big.mail", "over the mailman bound")]


def test_import_missing_directory_and_bad_target(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(mig.MigrateError):
        mig.import_dir(store, tmp_path / "nope", "hub@a")
    with pytest.raises(core.EnvelopeError):
        mig.import_dir(store, tmp_path, "nosite")


def test_import_sender_label_cleanup():
    assert mig.legacy_sender("Ops Desk", "a") == "ops-desk@a"
    assert mig.legacy_sender("12345", "a") == "legacy@a"
    assert mig.legacy_sender("", "a") == "legacy@a"
    assert mig.legacy_sender("bob@elsewhere", "a") == "bob@a"


# --- fold ---------------------------------------------------------------------

def test_fold_tracks_spool_states_and_verified(tmp_path):
    store = make_store(tmp_path)
    env = env_to_interface()
    assert mig.fold(store, env["id"]) is None
    core.publish(store, "interface", env)
    folded = mig.fold(store, env["id"])
    assert (folded.state, folded.where, folded.verified) == (
        "new", "spool/interface/new", True)
    assert [e for _, e in folded.events] == ["delivered"]
    core.move(store, "interface", env["id"], "new", "cur")
    assert mig.fold(store, env["id"]).state == "read"
    core.move(store, "interface", env["id"], "cur", "done")
    assert mig.fold(store, env["id"]).state == "acked"


def test_fold_unverified_import_is_not_verified(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    msg_id = mig.import_dir(store, out, "hub@a").imported[0][1]
    folded = mig.fold(store, msg_id)
    assert folded.state == "new" and folded.verified is False
    assert "imported" in [e for _, e in folded.events]


def test_fold_outbox_and_rejected_and_marker_only(tmp_path):
    store = make_store(tmp_path)
    draft = core.make_draft("lane-1@a", "hub@b", "x", from_auth=AUTH,
                            sent_at=core.iso_utc(NOW))
    core.enqueue(store, draft)
    assert mig.fold(store, draft["id"]).state == "queued"
    core.outbox_commit(store, "b", [draft["id"]])
    assert mig.fold(store, draft["id"]).state == "sent"
    rid = "cd" * 16
    core.reject(store, b"junk", "corrupt", msg_id=rid)
    rejected = mig.fold(store, rid)
    assert rejected.state == "rejected" and rejected.reason == "corrupt"
    assert rejected.verified is False
    mid = "ef" * 16
    store._ensure_dir(store.marker(mid).parent)
    store.marker(mid).write_text("")
    assert mig.fold(store, mid).state == "marked"


def test_fold_ignores_bad_ids_and_planted_links(tmp_path):
    store = make_store(tmp_path)
    assert mig.fold(store, "not-an-id") is None
    env = env_to_interface()
    core.publish(store, "interface", env)
    path = store.spool("interface", "new") / f"{env['id']}.json"
    real = path.read_bytes()
    os.unlink(path)
    other = tmp_path / "other.json"
    other.write_bytes(real)
    path.symlink_to(other)
    folded = mig.fold(store, env["id"])
    assert folded is not None and folded.envelope is None and folded.verified is False


# --- review fixes (w485 PR 83) ----------------------------------------------

def _age_all(root, seconds):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            os.utime(p, (NOW - seconds, NOW - seconds))


def test_import_stays_duplicate_after_compact_remote(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    first = mig.import_dir(store, out, "hub@b")
    assert len(first.imported) == 1
    store.outbox("b", "sent").mkdir(parents=True, exist_ok=True)
    for n in os.listdir(store.outbox("b", "q")):
        os.rename(store.outbox("b", "q") / n, store.outbox("b", "sent") / n)
    _age_all(store.root, 40 * 86400)
    assert core.compact(store, now=NOW + 1)["sent"] == 1
    second = mig.import_dir(store, out, "hub@b")
    assert second.imported == [] and second.duplicate == first.imported
    assert not os.listdir(store.outbox("b", "q"))


def test_import_compact_after_ack_local(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    mig.import_dir(store, out, "hub@a")
    (store.spool("hub", "done")).mkdir(parents=True, exist_ok=True)
    for n in os.listdir(store.spool("hub", "new")):
        os.rename(store.spool("hub", "new") / n, store.spool("hub", "done") / n)
    _age_all(store.root, 40 * 86400)
    counts = core.compact(store, now=NOW + 1)
    assert counts["done"] == 1
    again = mig.import_dir(store, out, "hub@a")
    assert again.imported == [] and len(again.duplicate) == 1
    assert not os.listdir(store.spool("hub", "new"))


def test_declared_msg_id_collision_is_skipped(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    known = "cd" * 16
    mail(out, "a.mail", f"from: ops\nkind: note\nmsg-id: {known}\n\nfirst\n")
    mig.import_dir(store, out, "hub@a")
    mail(out, "b.mail", f"from: ops\nkind: note\nmsg-id: {known}\n\nedited\n")
    mail(out, "c.mail", f"from: ops\nkind: note\nmsg-id: {known}\n\nfirst\n")
    result = mig.import_dir(store, out, "hub@a")
    assert ("b.mail", mig.COLLISION) in result.skipped
    assert [n for n, _ in result.duplicate] == ["a.mail", "c.mail"]
    assert len(os.listdir(store.spool("hub", "new"))) == 1


def test_declared_msg_id_collision_other_recipient(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    known = "ef" * 16
    mail(out, "a.mail", f"from: ops\nkind: note\nmsg-id: {known}\n\nhi\n")
    mig.import_dir(store, out, "hub@a")
    result = mig.import_dir(store, out, "other@a")
    assert result.skipped == [("a.mail", mig.COLLISION)]
    assert result.imported == []


def test_duplicate_writes_missing_imported_ledger_line(tmp_path):
    store, out = make_store(tmp_path), tmp_path / "out"
    mail(out, "a.mail", "from: ops\nkind: note\n\nhi\n")
    raw = (out / "a.mail").read_bytes()
    draft = mig._envelope_for(store, "a.mail", raw, "hub@a")
    core.enqueue(store, draft)          # delivered, crash before the `imported` line
    assert not any(e == "imported" for _t, e in mig._events(store, draft["id"]))
    result = mig.import_dir(store, out, "hub@a")
    assert len(result.duplicate) == 1
    assert [e for _t, e in mig._events(store, draft["id"]) if e == "imported"] == ["imported"]
    mig.import_dir(store, out, "hub@a")
    assert [e for _t, e in mig._events(store, draft["id"]) if e == "imported"] == ["imported"]
