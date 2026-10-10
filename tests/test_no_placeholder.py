"""PRIORITY 1 (founder, 2026-10-08): a handoff must not stall on a template.

Incident class: a holder copied the literal `<value>` from a printed
`--nonce <value>` recipe, the verb was refused, and the claim went unowned
until an operator recovered it by hand. Three properties are pinned here:

1. No string fleet prints -- verb output, refusal text, bootstrap templates or
   argparse help -- carries an identity placeholder token (`<value>`,
   `<nonce>`, `<sid>`, `<inc>`, ...). Fleet prints the exact command or none.
2. A placeholder-looking `--nonce`/`--handoff-token` is refused BEFORE any
   state change: registry, claim, journal and rejection-log bytes are equal
   before and after.
3. A continuity refusal prints the exact recovery: the idle-holder
   `send supervisor` wake and each pending successor's exact abort handle
   (claim-nonce §5.7 founder override).
"""
import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(REPO_ROOT.joinpath("bin").glob("*.py")) + sorted(
    REPO_ROOT.joinpath("bin", "hooks").glob("*.py"))

TOKEN = re.compile(r"<\s*([A-Za-z][A-Za-z0-9 _-]{0,40}?)\s*>")
IDENTITY_WORD = re.compile(
    r"(?:^|-)(?:value|nonce|sid|inc|incarnation|session|token|generation)(?:-|$)")


def _is_identity_placeholder(inner: str) -> bool:
    word = inner.strip().lower().replace("_", "-").replace(" ", "-")
    return "nonce" in word or bool(IDENTITY_WORD.search(word))


def _offending_tokens(text: str) -> list:
    text = re.sub(r"\(\?P<[^>]*>", "", text)      # regex named groups are not output
    return [m.group(0) for m in TOKEN.finditer(text)
            if _is_identity_placeholder(m.group(1))]


def _docstring_nodes(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


class TestTheDetector:
    @pytest.mark.parametrize("text", [
        "--nonce <value>", "--nonce <YOUR-NONCE>", "--nonce <your nonce>",
        "--successor-sid <sid>", "--successor-inc <inc>", "<CURRENT-NONCE>",
        "<session-id>", "<incarnation-id>", "--handoff-token <token>"])
    def test_flags_identity_placeholders(self, text):
        assert _offending_tokens(text)

    @pytest.mark.parametrize("text", [
        "<MANAGER MESSAGE>", "sup|<launch-id>|boot", "codex:<model>",
        "--fleet-home <PATH>", r"(?P<inc>inc-\d+)", "<redacted>"])
    def test_ignores_other_tokens(self, text):
        assert not _offending_tokens(text)


class TestNoPlaceholderIsPrinted:
    def test_no_output_or_template_string_in_bin_carries_one(self):
        offenders = []
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docs):
                    for tok in _offending_tokens(node.value):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT).as_posix()}:"
                            f"{node.lineno}: {tok}")
        assert not offenders, (
            "printed strings carry placeholder tokens (print the exact command "
            "or none):\n" + "\n".join(offenders))

    def test_no_verb_help_carries_one(self):
        parser = fleet.build_parser()
        texts = [parser.format_help()]
        for action in parser._actions:
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                texts.extend(sub.format_help() for sub in choices.values())
        assert len(texts) > 20
        offenders = [tok for t in texts for tok in _offending_tokens(t)]
        assert not offenders, offenders


@pytest.fixture
def held(tmp_path, monkeypatch):
    """A fresh v2 claim held by sid-me, an idle holder row, one pending successor."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# Goals\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    live = fleet.mint_nonce()
    beat = fleet.now_iso()
    fleet.write_incarnation({
        "incarnation_id": "inc-me", "session_id": "sid-me", "claimed_at": beat,
        "heartbeat_at": beat, "claimed_via": "fresh", "nonce_seq": 3,
        "lineage_id": "lin-x", "nonce_hash": fleet.nonce_digest(live),
        fleet.HANDOFF_PENDING_KEY: [{
            "successor_inc": "inc-20261008T000000Z-ab12", "successor_sid": "sid-succ-exact",
            "minted_at": beat, "state": fleet.HANDOFF_JOINING}]})
    fleet.supervisor_journal_append("BOOT", "inc-me", "sid-me", "fresh claim")
    rec = fleet.new_worker_record("sid-me", str(tmp_path), "supervisor", "bypass")
    rec["status"] = "idle"
    fleet.save_registry({"workers": {"sup|inc-me|boot": rec}})
    return tmp_path, live


def _state_bytes(home: Path) -> dict:
    return {p.relative_to(home).as_posix(): p.read_bytes()
            for p in sorted(home.rglob("*")) if p.is_file()}


PLACEHOLDERS = ["<value>", "<nonce>", "<YOUR-NONCE>", "", "   ", "value", "VALUE",
                "Nonce", " nonce ", "$NONCE", "{nonce}", "<anything at all>"]


class TestPlaceholderNonceIsRefusedBeforeAnyStateChange:
    @pytest.mark.parametrize("bad", PLACEHOLDERS)
    def test_holder_verb(self, held, capsys, bad):
        home, _live = held
        before = _state_bytes(home)
        rc = fleet.main(["sup-checkpoint", "body", "--sid", "sid-me", "--nonce", bad])
        err = capsys.readouterr().err
        assert rc == 1
        assert "placeholder" in err and "before any state change" in err
        assert "send supervisor" in err            # the recovery path is named
        assert _state_bytes(home) == before
        assert not fleet.nonce_rejection_log_path().exists()

    @pytest.mark.parametrize("bad", ["<value>", "", "nonce"])
    def test_handoff_complete(self, held, capsys, bad):
        home, _live = held
        before = _state_bytes(home)
        rc = fleet.main(["sup-handoff-complete", "--sid", "sid-me",
                         "--expect-inc", "inc-20261008T000000Z-ab12", "--nonce", bad])
        assert rc == 1
        assert "placeholder" in capsys.readouterr().err
        assert _state_bytes(home) == before

    def test_handoff_token(self, held, capsys):
        home, _live = held
        before = _state_bytes(home)
        rc = fleet.main(["sup-boot", "--sid", "sid-succ-exact", "--handoff-inc",
                         "inc-20261008T000000Z-ab12", "--handoff-token", "<value>"])
        assert rc == 1
        assert "--handoff-token" in capsys.readouterr().err
        assert _state_bytes(home) == before

    def test_shared_path_refuses_in_process_callers_too(self, held):
        home, _live = held
        before = _state_bytes(home)
        with pytest.raises(fleet.FleetCliError, match="placeholder"):
            fleet._require_claim_holder("sid-me", nonce="<value>", verb="sup-x")
        with pytest.raises(fleet.FleetCliError, match="placeholder"):
            fleet._supervisor_gate("spawn", nonce="value")
        assert _state_bytes(home) == before

    def test_a_real_minted_value_is_never_mistaken_for_one(self):
        for _ in range(200):
            assert not fleet._is_ph(fleet.mint_nonce())

    def test_the_real_generation_still_passes(self, held, capsys):
        _home, live = held
        assert fleet.main(["sup-checkpoint", "body", "--sid", "sid-me",
                           "--nonce", live]) == 0


class TestContinuityRefusalNamesTheRecovery:
    def test_refusal_prints_wake_and_exact_abort_handle(self, held, capsys):
        home, live = held
        rejected = fleet.mint_nonce()
        rc = fleet.main(["sup-checkpoint", "body", "--sid", "sid-me",
                         "--nonce", rejected])
        err = capsys.readouterr().err
        assert rc == fleet.SUPERVISOR_CONTINUITY_RC
        assert "escalate" in err
        assert "status now: idle" in err
        assert (f'--fleet-home "{home.as_posix()}" send supervisor '
                '"Continuity recovery: ') in err
        assert "sup-handoff-abort --successor-sid sid-succ-exact" in err
        assert "woken body's most recent `NONCE:` output" in err
        assert live not in err and rejected not in err
        assert "2026-10-08" in err
        assert not _offending_tokens(err)

    def test_live_handshake_exception_never_repeats_presented_generation(
            self, held):
        _home, live = held
        fleet.write_handshake("inc-20261008T000000Z-ab12", "sid-succ-exact")
        args = SimpleNamespace(
            sid="sid-me", nonce=live, successor_sid=None, successor_inc=None,
            force=False, retire_all=True)
        with pytest.raises(fleet.FleetCliError) as caught:
            fleet.cmd_sup_handoff_abort(args)
        text = str(caught.value)
        assert live not in text
        assert fleet._wake_cmd() in text
        assert "sup-handoff-abort --successor-sid sid-succ-exact --nonce" in text
        assert "woken body's own `sup-boot` output" in text
        assert "followed by that output's generation" in text
        assert not _offending_tokens(text)


class TestPrintedRecipesAreExact:
    def test_sup_status_recipe_has_no_placeholder(self, held, capsys):
        _home, live = held
        assert fleet.cmd_sup_status(type("A", (), {"json": False})()) == 0
        out = capsys.readouterr().out
        assert "sup-handoff-abort --successor-sid sid-succ-exact --nonce" in out
        assert live not in out
        assert not _offending_tokens(out)

    def test_wake_template_renders_exact_aborts(self):
        task = fleet._render_supervisor_wake_task(
            "sup|inc-me|boot", "inc-me", "wake-nonce-xyz", "",
            pending_handles=["--successor-sid sid-succ-exact"])
        assert ("sup-handoff-abort --successor-sid sid-succ-exact "
                "--nonce wake-nonce-xyz") in task
        assert not _offending_tokens(task)
