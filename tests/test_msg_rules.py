"""Anti-gridlock rules (spec docs/specs/messaging.md §11; plan PR 3).

Each rule is tested at its bound (allowed) and at bound + 1 (refused).
"""
import ast
from pathlib import Path

import pytest

import fleet_msg_core as core
import fleet_msg_rules as rules
from fleet_msg_rules import Limits, Sent

BIN = Path(__file__).resolve().parents[1] / "bin"
NOW = 1_800_000_000.0
A, B, C = "lane-1@alpha", "lane-2@alpha", "lane-3@alpha"
AUTH = {"method": "unverified", "detail": None}


def draft(frm=A, to=B, body="hello", **kw):
    kw.setdefault("from_auth", AUTH)
    kw.setdefault("sent_at", core.iso_utc(NOW))
    return core.make_draft(frm, to, body, **kw)


def sends(n, frm=A, to=B, kind="note", age=60.0):
    return [Sent(NOW - age - i, frm, to, kind) for i in range(n)]


# --- size -------------------------------------------------------------------

def test_size_120_words_allowed_121_refused():
    assert rules.check_size(" ".join(["w"] * 120)) is None
    assert rules.refusal_code(rules.check_size(" ".join(["w"] * 121))) == "size"


def test_size_8_kib_allowed_8_kib_plus_one_refused():
    assert rules.check_size("x" * 8192) is None
    assert rules.refusal_code(rules.check_size("x" * 8193)) == "size"
    assert rules.check_size("é" * 4096) is None          # 8192 bytes
    assert rules.check_size("é" * 4097) is not None      # 8194 bytes


def test_size_has_no_override_in_config():
    limits = Limits.from_config({"max_words": 500, "max_bytes": 99999})
    assert (limits.max_words, limits.max_bytes) == (120, 8192)


def test_size_matches_the_envelope_bound():
    assert Limits().max_words == core.BODY_MAX_WORDS
    assert Limits().max_bytes == core.BODY_MAX_BYTES


# --- no reply required ------------------------------------------------------

def test_no_reply_required_by_default():
    assert rules.NEEDS_ANSWER_DEFAULT is False
    assert draft()["needs_answer"] is False


# --- hop --------------------------------------------------------------------

def test_hop_at_max_allowed_one_past_refused():
    assert rules.check_hop(6, "a" * 32) is None
    reason = rules.check_hop(7, "a" * 32)
    assert rules.refusal_code(reason) == "hop"
    assert "escalate to the supervisor or the Interface" in reason


def test_hop_root_never_refused():
    assert rules.check_hop(0, None) is None


def test_hop_on_real_reply_chain():
    parent = core.validate(dict(draft(), seq=1))
    chain = parent
    for hop in range(1, 8):
        reply = draft(frm=B if hop % 2 else A, to=A if hop % 2 else B, parent=chain)
        assert reply["hop"] == hop
        refusal = rules.check_hop(reply["hop"], reply["re"])
        assert (refusal is None) == (hop <= 6)
        chain = core.validate(dict(reply, seq=hop + 1))


def test_hop_limit_is_a_setting():
    limits = Limits.from_config({"max_hop": 2})
    assert rules.check_hop(2, "a" * 32, limits) is None
    assert rules.check_hop(3, "a" * 32, limits) is not None


# --- loop -------------------------------------------------------------------

def test_loop_task_to_identity_in_path_refused():
    assert rules.check_loop(A, B, "task", [A], []) is None
    reason = rules.check_loop(B, A, "task", [A, B], [])
    assert rules.refusal_code(reason) == "loop"


def test_loop_path_rule_ignores_notes():
    assert rules.check_loop(B, A, "note", [A, B], []) is None


def _alternating(n):
    """n tasks alternating A, B, A, ... oldest first."""
    return [Sent(NOW - 1000 + i, A if i % 2 == 0 else B, B if i % 2 == 0 else A, "task")
            for i in range(n)]


def test_loop_three_alternating_allow_the_fourth():
    assert rules.check_loop(B, A, "task", [B], _alternating(3)) is None


def test_loop_four_alternating_refuse_the_fifth():
    history = _alternating(4)          # A, B, A, B
    assert history[-1].frm == B
    reason = rules.check_loop(A, B, "task", [A], history)
    assert rules.refusal_code(reason) == "loop"


def test_loop_same_sender_again_is_not_alternating():
    assert rules.check_loop(B, A, "task", [B], _alternating(4)) is None


def test_loop_interrupted_alternation_resets():
    history = _alternating(4)
    history[2] = Sent(history[2].ts, B, A, "task")      # A, B, B, B
    assert rules.check_loop(A, B, "task", [A], history) is None


def test_loop_ignores_other_pairs_and_notes():
    history = _alternating(4) + [Sent(NOW - 1, C, A, "task")]
    assert rules.check_loop(A, B, "task", [A], history) is not None  # C-A is another pair
    notes = [s._replace(kind="note") for s in _alternating(4)]
    assert rules.check_loop(A, B, "task", [A], notes) is None


def test_loop_uses_timestamps_not_list_order():
    history = list(reversed(_alternating(4)))
    assert rules.check_loop(A, B, "task", [A], history) is not None


# --- task budget ------------------------------------------------------------

def test_task_budget_fourth_allowed_fifth_refused():
    assert rules.check_task_budget(A, B, "task", sends(3, kind="task"), NOW) is None
    reason = rules.check_task_budget(A, B, "task", sends(4, kind="task"), NOW)
    assert rules.refusal_code(reason) == "task-budget"


def test_task_budget_ignores_threads_notes_and_other_pairs():
    history = sends(4, kind="note") + sends(4, frm=B, to=A, kind="task") + sends(4, to=C, kind="task")
    assert rules.check_task_budget(A, B, "task", history, NOW) is None


def test_task_budget_only_binds_tasks():
    assert rules.check_task_budget(A, B, "note", sends(9, kind="task"), NOW) is None


def test_task_budget_window_edge():
    just_in = [Sent(NOW - 3599.0, A, B, "task")] * 4
    just_out = [Sent(NOW - 3600.0, A, B, "task")] * 4
    assert rules.check_task_budget(A, B, "task", just_in, NOW) is not None
    assert rules.check_task_budget(A, B, "task", just_out, NOW) is None


# --- rate -------------------------------------------------------------------

def test_rate_twentieth_allowed_twenty_first_refused():
    assert rules.check_rate(A, B, sends(19), NOW) is None
    reason = rules.check_rate(A, B, sends(20), NOW)
    assert rules.refusal_code(reason) == "rate"


def test_rate_counts_notes_and_tasks_not_receipts_or_other_pairs():
    mixed = sends(10) + sends(10, kind="task")
    assert rules.check_rate(A, B, mixed, NOW) is not None
    quiet = sends(20, kind="receipt") + sends(20, to=C) + sends(20, frm=B, to=A)
    assert rules.check_rate(A, B, quiet, NOW) is None


def test_rate_window_edge():
    assert rules.check_rate(A, B, [Sent(NOW - 3599.0, A, B, "note")] * 20, NOW) is not None
    assert rules.check_rate(A, B, [Sent(NOW - 3600.0, A, B, "note")] * 20, NOW) is None


def test_rate_limit_is_a_setting():
    limits = Limits.from_config({"rate": 3})
    assert rules.check_rate(A, B, sends(2), NOW, limits) is None
    assert rules.check_rate(A, B, sends(3), NOW, limits) is not None


# --- per-peer ingest cap ----------------------------------------------------

def test_peer_ingest_200th_accepted_201st_rejected():
    assert rules.check_peer_ingest([NOW - 5] * 199, NOW) is None
    reason = rules.check_peer_ingest([NOW - 5] * 200, NOW)
    assert rules.refusal_code(reason) == "rate"


def test_peer_ingest_window_edge():
    assert rules.check_peer_ingest([NOW - 3599.0] * 200, NOW) is not None
    assert rules.check_peer_ingest([NOW - 3600.0] * 200, NOW) is None


def test_admit_reasons_are_core_reject_reasons():
    env = core.validate(dict(draft(frm="lane-1@beta", to=B), seq=1))
    assert rules.check_admit(env, "beta", [], NOW) is None
    assert rules.check_admit(env, "beta", [NOW - 5] * 200, NOW) == "rate"
    assert rules.check_admit(env, "beta", [], NOW, retired={"lane-2"}) == "retired"
    assert {"rate", "retired"} <= set(core.REJECT_REASONS)


def test_admit_hook_drives_ingest_to_a_201st_rate_reject(tmp_path):
    store = core.Store(tmp_path / "home", "alpha", clock=lambda: NOW)
    stamps = [NOW - 5] * 200
    admit = rules.make_admit(Limits(), "beta", lambda peer: stamps, lambda: (), lambda: NOW)
    env = core.validate(dict(draft(frm="lane-1@beta", to=B), seq=1))
    result = core.ingest(store, core.canonical(env), peer_site="beta",
                         hosted={"lane-1"}, admit=admit)
    assert result == "rejected:rate"
    stamps.pop()
    assert core.ingest(store, core.canonical(env), peer_site="beta",
                       hosted={"lane-1"}, admit=admit) == "accepted"


# --- notice coalescing ------------------------------------------------------

def test_notice_one_pending_per_sender():
    assert rules.notice_due(0) is True
    assert rules.notice_due(1) is False


# --- check_draft and the enqueue hook ---------------------------------------

def test_check_draft_first_refusal_wins_and_receipts_only_size():
    oversize = dict(draft(), body=" ".join(["w"] * 121))   # bypasses make_draft's own bound
    assert rules.refusal_code(rules.check_draft(oversize, [], NOW)) == "size"
    assert rules.refusal_code(rules.check_draft(dict(oversize, kind="receipt"), [], NOW)) == "size"
    receipt = draft(kind="receipt")
    assert rules.check_draft(receipt, sends(99), NOW) is None
    assert rules.check_draft(draft(), sends(20), NOW) is not None
    assert rules.check_draft(draft(kind="task"), sends(4, kind="task"), NOW) is not None


def test_make_rules_refuses_inside_enqueue_and_allocates_nothing(tmp_path):
    store = core.Store(tmp_path / "home", "alpha", clock=lambda: NOW)
    history = lambda d: sends(20, frm=d["from"], to=d["to"])
    hook = rules.make_rules(Limits(), history, lambda: NOW)
    with pytest.raises(core.Refused) as err:
        core.enqueue(store, draft(), rules=hook)
    assert rules.refusal_code(err.value.reason) == "rate"
    assert store.last_seq(A, B) == 0                      # a refusal leaves no seq gap
    ok = rules.make_rules(Limits(), lambda d: sends(19, frm=d["from"], to=d["to"]),
                          lambda: NOW)
    status, env = core.enqueue(store, draft(), rules=ok)
    assert (status, env["seq"]) == ("delivered", 1)


# --- config -----------------------------------------------------------------

def test_defaults_are_the_spec_values():
    limits = Limits()
    assert (limits.max_hop, limits.task_budget, limits.rate, limits.peer_ingest,
            limits.loop_alternating) == (6, 4, 20, 200, 4)


@pytest.mark.parametrize("bad", [0, -1, "5", 2.0, True, None])
def test_config_rejects_non_positive_integers(bad):
    with pytest.raises(rules.RulesError):
        Limits.from_config({"rate": bad})


def test_config_ignores_unknown_keys():
    assert Limits.from_config({"outbox_warn_s": 900, "interface_site": "x"}) == Limits()


# --- doctrine pins ----------------------------------------------------------

def test_module_is_pure_and_stdlib_only():
    tree = ast.parse((BIN / "fleet_msg_rules.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    local = {p.stem for p in BIN.glob("*.py")}
    assert imported & local == {"fleet_msg_core"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not ({"open", "time"} & names)
    assert not ({"time", "now", "write_text", "read_text", "listdir", "unlink"} & attrs)
