"""M2's worker-facing surface: `--context` digest injection (§7), the teach
lines (§11.8) and the template's first non-hook key (§11.7 item 1).

Spec of record: `docs/specs/fleet-index.md`. The M1 shard layer these tests
build on lives in `tests/test_fleet_index.py`; `fleet q` itself is a sibling
slice and is not exercised here.

THREE PROPERTIES CARRY THE WHOLE FILE, and each is asserted at the byte level
rather than by a spot check:

1. **An absent `--context` changes the composed prompt not at all** (§12). It is
   what keeps every non-indexed project paying zero, so it is pinned as a
   byte-for-byte equality against the prompt fleet composes today, not as an
   "and the digest is missing" assertion.
2. **A worker in a non-indexed project sees no mention of `fleet q`** (§11.8) --
   a tool that would exit 3 there. Asserted as a substring census over the whole
   composed prompt, so a stray mention anywhere in it fails.
3. **No path serves an unverified coordinate** (§8). The digest reads through
   `verified_shard_rows()` -- §11.3's choke point -- so a stale shard is
   repaired before it is rendered. Pinned twice: behaviourally (edit the source,
   the digest shows the NEW coordinates) and structurally (the choke point is
   actually called), because either alone survives a plausible mutation.

The four compose paths (§11.8: spawn, idle-send fork-steer, resume-limited,
respawn) are each driven END TO END through their real call site with a
capturing `dispatch_bg`, never by calling `compose_prompt` four times. The
teach lines live inside `compose_prompt`, so a per-call-site test looks
redundant -- it is not: it is the only thing that fails if one call site starts
composing its prompt some other way, and the census test below is the only
thing that fails if a FIFTH dispatch path is added.
"""
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _write(path, text):
    """LF newlines on every platform -- a golden prompt is byte-identical on
    win32 and POSIX for the same reason a golden shard is (§11.2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


API_PY = """\
ALPHA = 1


def alpha(x: int) -> str:
    return str(x)


class Beta:

    def run(self, y) -> bool:
        return True
"""

DESIGN_MD = """\
# Design

Prose.

## Rationale

More prose.
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """FLEET_HOME in a tmp dir, with the rendered instance settings the
    dispatch paths require (SPEC §14)."""
    home = tmp_path / "fleet-home"
    home.mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    settings = home / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    return home


@pytest.fixture
def plain_project(tmp_path):
    """A project that never opted in: no `.fleet-index/` anywhere."""
    root = tmp_path / "plain"
    _write(root / "src" / "api.py", API_PY)
    return root


@pytest.fixture
def indexed_project(tmp_path):
    """A project with a built `.fleet-index/` (`fleet index init` shape)."""
    root = tmp_path / "indexed"
    _write(root / "src" / "api.py", API_PY)
    _write(root / "docs" / "DESIGN.md", DESIGN_MD)
    fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
    fleet.build_index(root)
    return root


def _compose(name, cwd, task="the task", sid=None, **kw):
    prompt, _claim = fleet.compose_prompt(name, cwd, task, sid, **kw)
    return prompt


# ---------------------------------------------------------------------------
# §11.8 -- the teach lines
# ---------------------------------------------------------------------------

class TestTeachLines:

    def test_no_mention_of_fleet_q_in_a_non_indexed_project(self, plain_project):
        """A worker must not be told about a tool that would exit 3 there.

        A byte-level census over the WHOLE composed prompt, not a spot check on
        the preamble: the cost of a stray mention is a worker burning a turn on
        a command that cannot work, and it does not matter which section it
        leaked into.
        """
        prompt = _compose("w1", plain_project)
        lowered = prompt.lower()
        for token in ("fleet q", "fleet-index", ".fleet-index", "--outline", "--src"):
            assert token not in lowered, (
                f"a non-indexed project's prompt mentions {token!r} -- that tool "
                f"exits 3 here (§11.8)")

    def test_rendered_when_the_dispatch_dir_carries_an_index(self, indexed_project):
        prompt = _compose("w1", indexed_project)
        assert fleet.INDEX_TEACH_LINES in prompt

    def test_at_most_four_lines(self):
        """§11.8's cap. The preamble is fleet's only worker-facing channel and
        every line in it is re-paid per DISPATCH (§3), not per spawn."""
        lines = [l for l in fleet.INDEX_TEACH_LINES.splitlines() if l.strip()]
        assert len(lines) <= 4, f"{len(lines)} teach lines, §11.8 allows at most 4"

    def test_teaches_the_name_the_contract_and_both_flags(self):
        text = fleet.INDEX_TEACH_LINES
        assert "fleet q" in text
        assert "--src" in text
        assert "--outline" in text

    def test_they_sit_in_the_preamble_ahead_of_everything_else(self, indexed_project):
        """Composition order (§7): the teach lines are preamble, so they precede
        the mailbox, the task and the journal."""
        prompt = _compose("w1", indexed_project, task="TASK-MARKER")
        assert prompt.index(fleet.INDEX_TEACH_LINES) < prompt.index("TASK-MARKER")

    def test_the_check_is_the_dispatch_dir_not_the_process_cwd(
            self, indexed_project, plain_project, monkeypatch):
        """§11.8 keys on the dispatch target's `--dir`. A manager standing in an
        indexed repo must not teach a worker it is sending somewhere else."""
        monkeypatch.chdir(indexed_project)
        assert "fleet q" not in _compose("w1", plain_project)
        monkeypatch.chdir(plain_project)
        assert fleet.INDEX_TEACH_LINES in _compose("w1", indexed_project)

    def test_a_file_named_fleet_index_is_not_an_index(self, tmp_path):
        """`.fleet-index` must be a DIRECTORY. A stray file of that name is not
        an opt-in, and treating it as one teaches a tool that cannot run."""
        root = tmp_path / "decoy"
        root.mkdir()
        (root / ".fleet-index").write_text("not a directory", encoding="utf-8")
        assert "fleet q" not in _compose("w1", root)


# ---------------------------------------------------------------------------
# §11.8 -- all four compose paths, driven through their real call sites
# ---------------------------------------------------------------------------

class _Captured(Exception):
    """Raised by the dispatch stub once it has the composed prompt.

    Deliberately not `NativeDispatchError`: three of the four call sites catch
    that and run a rollback, which would bury a failure to compose behind a
    successful rollback assertion. This one propagates.
    """

    def __init__(self, prompt):
        super().__init__("captured")
        self.prompt = prompt


@pytest.fixture
def captured(monkeypatch):
    """Replace `dispatch_bg` with a prompt capturer. Returns a list that the
    stub appends the composed prompt to before raising."""
    seen = []

    def _stub(name, cwd, prompt, mode, **kw):
        seen.append(prompt)
        raise _Captured(prompt)

    monkeypatch.setattr(fleet, "dispatch_bg", _stub)
    return seen


SID = "aaaabbbb-1111-2222-3333-444455556666"


def _seed(name, cwd, status="idle", sid=SID, **extra):
    rec = fleet.new_worker_record(sid, str(cwd), "seeded task", "dontask",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec.update(extra)
    fleet.save_registry({"workers": {name: rec}})
    return rec


def _drive(fn):
    """Run `fn`, expect the capture, return the composed prompt."""
    with pytest.raises(_Captured) as exc:
        fn()
    return exc.value.prompt


class TestAllFourComposePaths:
    """§11.8: the check runs wherever compose runs, so the teach lines render
    on every dispatch -- a respawned or steered worker in an indexed project is
    re-taught (§3: the cost is per dispatch, not per spawn)."""

    def _spawn(self, project, captured, **kw):
        args = SimpleNamespace(
            name="w1", dir=str(project), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None, context=kw.get("context"))
        return _drive(lambda: fleet.cmd_spawn(
            args, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))

    def test_path_1_spawn(self, indexed_project, captured):
        assert fleet.INDEX_TEACH_LINES in self._spawn(indexed_project, captured)

    def test_path_1_spawn_stays_silent_without_an_index(self, plain_project, captured):
        assert "fleet q" not in self._spawn(plain_project, captured)

    def _send(self, project, captured, monkeypatch):
        _seed("w1", project, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        # The verdict engine is not what this test is about: force the idle
        # branch so the assertion is about the COMPOSE call, not about
        # recompute's liveness heuristics.
        def _idle(name, rec, roster, **kw):
            out = dict(rec)
            out["status"] = "idle"
            return out
        monkeypatch.setattr(fleet, "recompute_worker_native", _idle)
        return _drive(lambda: fleet._cmd_send_native(
            "w1", "steer me", run=lambda *a, **k: None,
            which=lambda _: "claude", sleep=lambda s: None))

    def test_path_2_idle_send_fork_steer(self, indexed_project, captured, monkeypatch):
        assert fleet.INDEX_TEACH_LINES in self._send(indexed_project, captured, monkeypatch)

    def test_path_2_idle_send_stays_silent_without_an_index(
            self, plain_project, captured, monkeypatch):
        assert "fleet q" not in self._send(plain_project, captured, monkeypatch)

    def _resume(self, project, captured):
        return _drive(lambda: fleet._resume_one_limited_native(
            "w1", SID, str(project), "dontask", None, None, None, None,
            run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None))

    def test_path_3_resume_limited(self, indexed_project, captured):
        _seed("w1", indexed_project, status="working")
        assert fleet.INDEX_TEACH_LINES in self._resume(indexed_project, captured)

    def test_path_3_resume_limited_stays_silent_without_an_index(
            self, plain_project, captured):
        _seed("w1", plain_project, status="working")
        assert "fleet q" not in self._resume(plain_project, captured)

    def _respawn(self, project, captured, monkeypatch):
        before = _seed("w1", project, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        args = SimpleNamespace(name="w1", task=None, force=False, mode=None,
                               model=None, category=None, token_ceiling=None)
        return _drive(lambda: fleet._cmd_respawn_native(
            args, before, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))

    def test_path_4_respawn(self, indexed_project, captured, monkeypatch):
        assert fleet.INDEX_TEACH_LINES in self._respawn(
            indexed_project, captured, monkeypatch)

    def test_path_4_respawn_stays_silent_without_an_index(
            self, plain_project, captured, monkeypatch):
        assert "fleet q" not in self._respawn(plain_project, captured, monkeypatch)


def test_no_fifth_compose_path_appeared_uncovered():
    """The census. §3 enumerates FOUR `compose_prompt` call sites and §11.8
    binds the teach lines to all of them; a fifth dispatch path added later
    would be silently untaught, and the four tests above would still pass.

    Re-derived from the source on every run, like the `retired_sids` citation
    test -- a new call site is a deliberate one-line change here, not an
    omission.
    """
    src = Path(fleet.__file__).read_text(encoding="utf-8").splitlines()
    callers = set()
    for n, line in enumerate(src, start=1):
        if "compose_prompt(" not in line or line.lstrip().startswith(("#", "*", '"')):
            continue
        if line.lstrip().startswith("def compose_prompt"):
            continue
        # Walk back to the enclosing `def`.
        for m in range(n - 1, 0, -1):
            stripped = src[m - 1]
            if stripped.startswith("def "):
                callers.add(stripped[4:].split("(")[0])
                break
    assert callers == {"cmd_spawn", "_cmd_send_native",
                       "_resume_one_limited_native", "_cmd_respawn_native"}, (
        f"the set of compose_prompt call sites changed: {sorted(callers)}. §11.8 "
        f"binds the teach lines to EVERY dispatch path -- add the new one to "
        f"TestAllFourComposePaths and re-pin this set.")


# ---------------------------------------------------------------------------
# §7 -- `--context` digest injection
# ---------------------------------------------------------------------------

class TestAbsentContextIsFree:
    """The property that keeps every non-indexed project paying zero."""

    def test_absent_context_is_byte_identical_in_a_plain_project(self, plain_project):
        assert _compose("w1", plain_project) == _compose(
            "w1", plain_project, context=None)
        assert _compose("w1", plain_project) == _compose(
            "w1", plain_project, context=[])

    def test_absent_context_is_byte_identical_in_an_indexed_project(self, indexed_project):
        """An index in the project changes the prompt (the teach lines do that,
        §11.8) but `--context` still costs nothing when it is not given."""
        assert _compose("w1", indexed_project) == _compose(
            "w1", indexed_project, context=None)

    def test_absent_context_matches_the_prompt_fleet_composes_today(self, plain_project):
        """The regression pin, spelled out rather than inferred: for a project
        with no index and no `--context`, the composed prompt is EXACTLY the
        preamble template and the task, byte for byte."""
        expected = fleet._PREAMBLE_TEMPLATE.format(
            name="w1", cwd=plain_project,
            journal_target=fleet.journal_file_path("w1").as_posix()) + "\nthe task"
        assert _compose("w1", plain_project) == expected

    def test_absent_context_writes_nothing_into_the_index(self, indexed_project):
        """Composition is a read. Without `--context` it must not even look."""
        before = {p: p.stat().st_mtime_ns
                  for p in fleet.index_dir(indexed_project).rglob("*") if p.is_file()}
        _compose("w1", indexed_project)
        after = {p: p.stat().st_mtime_ns
                 for p in fleet.index_dir(indexed_project).rglob("*") if p.is_file()}
        assert before == after


class TestContextDigest:

    def test_digest_is_rendered_for_each_named_file(self, indexed_project):
        prompt = _compose("w1", indexed_project,
                          context=["src/api.py", "docs/DESIGN.md"])
        assert "## src/api.py" in prompt
        assert "## docs/DESIGN.md" in prompt
        assert "- L4 alpha(x: int) -> str" in prompt
        assert "- L8 class Beta" in prompt
        assert "- L10   Beta.run(self, y) -> bool" in prompt

    def test_composition_order_preamble_digest_mailbox_task_journal(
            self, indexed_project, tmp_path):
        """§7's order, all five sources present in one prompt."""
        sid = SID
        fleet.append_mailbox(sid, "MAIL-MARKER")
        journal = _write(tmp_path / "j.md", "JOURNAL-MARKER\n")
        prompt, claim = fleet.compose_prompt(
            "w1", indexed_project, "TASK-MARKER", sid,
            journal_path=journal, context=["src/api.py"])
        fleet.restore_mailbox_claim(claim)
        order = [prompt.index(tok) for tok in (
            "You are fleet worker", "## src/api.py", "MAIL-MARKER",
            "TASK-MARKER", "JOURNAL-MARKER")]
        assert order == sorted(order), (
            f"§7 composition order violated: {order}")

    def test_paths_resolve_against_the_dispatch_dir_not_the_manager_cwd(
            self, indexed_project, plain_project, monkeypatch):
        """§7 / invariant 5: one cwd frame, the worker's `--dir`."""
        monkeypatch.chdir(plain_project)
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "## src/api.py" in prompt

    def test_unknown_path_warns_and_is_skipped_but_never_fails(
            self, indexed_project, capsys):
        prompt = _compose("w1", indexed_project,
                          context=["src/api.py", "src/nope.py"])
        assert "## src/api.py" in prompt
        assert "nope.py" not in prompt
        assert "nope.py" in capsys.readouterr().err

    def test_a_path_escaping_the_dispatch_dir_is_skipped(
            self, indexed_project, plain_project, capsys):
        """`--context ../plain/src/api.py` must not reach outside `--dir`:
        the digest would describe a file the worker's index does not cover."""
        prompt = _compose("w1", indexed_project,
                          context=["../plain/src/api.py"])
        assert "api.py (" not in prompt
        assert capsys.readouterr().err.strip()

    def test_context_in_a_project_with_no_index_warns_and_proceeds(
            self, plain_project, capsys):
        """§9's no-index row: spawn injects nothing and proceeds."""
        prompt = _compose("w1", plain_project, context=["src/api.py"])
        assert "## src/api.py" not in prompt
        assert "no index" in capsys.readouterr().err

    def test_the_spawn_time_digest_is_not_capped_at_400_lines(self, tmp_path):
        """§11.4/§11.1: the 400-line cap is `--outline`'s, not the spawn-time
        digest's. The two outputs differ only when the cap truncates, so a cap
        applied here would silently impose `q`'s limit on a path the spec
        exempts."""
        root = tmp_path / "big"
        body = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(500))
        _write(root / "big.py", body)
        fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
        fleet.build_index(root)
        prompt = _compose("w1", root, context=["big.py"])
        assert "- L1993 f498()" in prompt
        assert "truncated" not in prompt

    def test_a_file_the_index_config_excludes_is_skipped_not_indexed(
            self, indexed_project, capsys):
        """A shard written for an unselected file would be pruned by the very
        next `build` -- `update_index` refuses for exactly this reason, and the
        digest path must not make a promise the index cannot keep."""
        _write(indexed_project / "notes.txt", "plain text\n")
        prompt = _compose("w1", indexed_project, context=["notes.txt"])
        assert "## notes.txt" not in prompt
        assert "notes.txt" in capsys.readouterr().err
        assert not fleet.shard_path_for_source(indexed_project, "notes.txt").exists()

    def test_spawn_accepts_a_comma_separated_context_flag(self, indexed_project, captured):
        args = SimpleNamespace(
            name="w1", dir=str(indexed_project), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None,
            context="src/api.py,docs/DESIGN.md")
        prompt = _drive(lambda: fleet.cmd_spawn(
            args, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))
        assert "## src/api.py" in prompt
        assert "## docs/DESIGN.md" in prompt

    def test_the_parser_accepts_context(self):
        args = fleet.build_parser().parse_args(
            ["spawn", "w1", "--dir", ".", "--task", "t", "--context", "a.py,b.md"])
        assert fleet.parse_context_arg(args.context) == ["a.py", "b.md"]

    def test_parse_context_arg_tolerates_spacing_and_empties(self):
        assert fleet.parse_context_arg(None) == []
        assert fleet.parse_context_arg("") == []
        assert fleet.parse_context_arg(" a.py , , b.md ") == ["a.py", "b.md"]


class TestDigestNeverServesAnUnverifiedCoordinate:
    """§8's single most important property, applied to the digest path."""

    def test_a_stale_shard_is_repaired_before_it_is_rendered(self, indexed_project):
        """The behavioural half. Edit the source after the build: a digest read
        straight off the shard would print the OLD line numbers, which do not
        error -- they silently point the worker at the wrong code."""
        shard = fleet.shard_path_for_source(indexed_project, "src/api.py")
        stale = shard.read_bytes().decode("utf-8")
        assert "alpha\t4\t" in stale
        _write(indexed_project / "src" / "api.py", "\n\n\n\n\n" + API_PY)
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "- L9 alpha(x: int) -> str" in prompt
        assert "- L4 alpha(x: int) -> str" not in prompt

    def test_a_corrupt_shard_is_repaired_before_it_is_rendered(self, indexed_project):
        shard = fleet.shard_path_for_source(indexed_project, "src/api.py")
        shard.write_bytes(b"#\tdeadbeef\t3\tpython\ngarbage\n")
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "- L4 alpha(x: int) -> str" in prompt

    def test_the_digest_reads_through_the_choke_point(self, indexed_project, monkeypatch):
        """The structural half. §11.3's `verified_shard_rows` is THE choke
        point; a digest built off `read_shard` directly would pass the
        behavioural test above whenever the shard happened to be fresh.
        """
        calls = []
        real = fleet.verified_shard_rows

        def spy(root, rel, **kw):
            calls.append((Path(root), rel))
            return real(root, rel, **kw)

        monkeypatch.setattr(fleet, "verified_shard_rows", spy)
        _compose("w1", indexed_project, context=["src/api.py"])
        assert calls == [(Path(indexed_project), "src/api.py")], (
            "the digest did not go through verified_shard_rows() -- some other "
            "path is reading shards, and §8's no-unverified-coordinate property "
            "does not bind it")

    def test_a_deleted_source_is_suppressed_not_rendered(self, indexed_project, capsys):
        """Orphan row (§11.3): the shard survives the source. Its coordinates
        describe a file that is gone, so they are suppressed, not served."""
        (indexed_project / "src" / "api.py").unlink()
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "## src/api.py" not in prompt
        assert capsys.readouterr().err.strip()


# ---------------------------------------------------------------------------
# §11.7 item 1 -- the template grant, and its narrowness
# ---------------------------------------------------------------------------

TEMPLATE = Path(fleet.__file__).resolve().parents[1] / "worker-settings.template.json"


def _template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


class TestTemplateGrant:

    def test_the_template_carries_the_subcommand_scoped_grant(self):
        assert _template()["permissions"]["allow"] == ["Bash(fleet q:*)"]

    def test_the_grant_is_narrow_and_stays_narrow(self):
        """THE guard for §11.7 item 1, and it is the whole guard: the next
        person to widen this will have a good reason.

        `Bash(fleet:*)` is a KILL grant -- `fleet kill` and `fleet clean` are
        irreversible (CLAUDE.md), and this repo has a recorded incident where a
        READ-ONLY slash command reached `fleet clean`. `fleet index:*` is
        excluded on a second ground: index lifecycle is manager-side (§8), so a
        worker has no business holding it.
        """
        entries = []
        for bucket in _template().get("permissions", {}).values():
            entries.extend(bucket)
        fleet_grants = [e for e in entries if "fleet" in e]
        assert fleet_grants == ["Bash(fleet q:*)"], (
            f"the worker-settings template carries fleet grants other than the "
            f"one subcommand-scoped `Bash(fleet q:*)`: {fleet_grants}. A wider "
            f"grant reaches `fleet kill` and `fleet clean`, both irreversible.")

    def test_the_template_grants_nothing_else_at_all(self):
        """§11.7: `Bash(fleet q:*)` is the only fleet grant the template will
        ever carry for workers. Any other allow entry is a new, unspecified
        privilege reaching every worker on the machine."""
        permissions = _template().get("permissions", {})
        assert set(permissions) == {"allow"}, (
            f"unexpected permission buckets in the template: {sorted(permissions)}")
        assert permissions["allow"] == ["Bash(fleet q:*)"]

    def test_the_hooks_block_is_untouched(self):
        hooks = _template()["hooks"]
        assert set(hooks) == {"PostToolUse", "Stop", "PostCompact"}


class TestTemplateRenderAndFreshnessHandleTheNewKey:
    """§11.7 item 2's claim, MEASURED. It says the `instance-freshness` doctor
    check already covers the migration -- but that check compares MTIMES, not
    content (`instance_freshness_info`), so "already diffs the two" is not what
    the code does. What matters is that neither the render nor the freshness
    probe mishandles a template that is no longer hooks-only."""

    def test_render_preserves_the_permissions_key(self, tmp_path):
        rendered = fleet.render_worker_settings_template(
            TEMPLATE.read_text(encoding="utf-8"), "C:/py/python.exe", tmp_path)
        parsed = json.loads(rendered)
        assert parsed["permissions"]["allow"] == ["Bash(fleet q:*)"]
        assert "{{" not in rendered

    def test_render_still_rejects_an_unrendered_placeholder(self, tmp_path):
        """Non-vacuity: the loud-failure arm still fires with the new key
        present, so the render test above is not passing because the checker
        went quiet."""
        text = TEMPLATE.read_text(encoding="utf-8").replace(
            '"permissions"', '"{{NOPE}}permissions"')
        with pytest.raises(ValueError, match="unrendered placeholder"):
            fleet.render_worker_settings_template(text, "C:/py/python.exe", tmp_path)

    def test_fleet_init_writes_the_grant_into_the_instance(self, isolated_home, monkeypatch):
        """End to end: `pull, re-run fleet init` (§11.7 item 2) actually puts
        the grant where a worker's `--settings` file will find it."""
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)
        rc = fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))
        assert rc == 0
        instance = json.loads(
            fleet.instance_settings_path().read_text(encoding="utf-8"))
        assert instance["permissions"]["allow"] == ["Bash(fleet q:*)"]

    def test_instance_freshness_flags_the_template_change_then_clears(
            self, isolated_home, monkeypatch):
        """The migration story, measured rather than assumed: an instance
        rendered from the OLD hooks-only template reads stale against the new
        one, and `fleet init` clears it."""
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text('{"hooks": {}}', encoding="utf-8")
        # An instance rendered before the template changed.
        os.utime(instance, (0, 0))
        assert fleet.instance_freshness_info()["stale"] is True
        assert fleet._doctor_check_instance_freshness()[1] is False

        fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))
        assert fleet.instance_freshness_info()["stale"] is False
        assert fleet._doctor_check_instance_freshness()[1] is True
