"""SDD acceptance gate (SPEC §17a): flag, spec lifecycle, criteria, verify, binding."""
import json
import subprocess
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
import fleet_spec
from test_brief_preservation import SID_1, SID_2, _claude, _entry, _roster, _run_for


GOOD = {
    "spec": "md-demo", "status": "proposed", "author": "alice",
    "accepted_by": "", "reviewed_by": "review by bob", "accepted_digest": "",
    "scope_allow": ["src/**", "tests/**"], "scope_deny": ["state/**"],
    "criteria": [{"id": "C1", "ears": "The tool SHALL work.", "kind": "pytest",
                  "nodes": ["tests/test_x.py::test_y"]}],
}


def _spec_text(data=None):
    return fleet_spec.render_spec("md-demo", data or GOOD, "## Context\nBody prose.\n")


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "fleet-home"
    (root / "state").mkdir(parents=True)
    (root / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "mailbox").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", root)
    monkeypatch.setenv("FLEET_SDD", "1")
    monkeypatch.delenv("FLEET_ACTOR", raising=False)
    return root


def _write(data=None, **over):
    data = json.loads(json.dumps(data or GOOD))
    data.update(over)
    fleet.write_spec("md-demo", data, "## Context\nbody\n")
    return data


def _accept(actor="bob"):
    return fleet.cmd_spec_accept(SimpleNamespace(campaign="md-demo", actor=actor))


def _verify(**kw):
    args = SimpleNamespace(campaign="md-demo", worker=kw.pop("worker", None),
                           base=kw.pop("base", None))
    return fleet.cmd_spec_verify(args, **kw)


def _git(repo, *argv):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    *argv], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitignore").write_text("state/\n__pycache__/\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


# --- flag -----------------------------------------------------------------

class TestFlag:
    def test_default_off(self, home, monkeypatch):
        monkeypatch.delenv("FLEET_SDD", raising=False)
        assert fleet.sdd_enabled() is False

    def test_config_file_enables(self, home, monkeypatch):
        monkeypatch.delenv("FLEET_SDD", raising=False)
        fleet.config_path().write_text(json.dumps({"sdd": {"enabled": True}}), encoding="utf-8")
        assert fleet.sdd_enabled() is True

    def test_env_overrides_config(self, home, monkeypatch):
        fleet.config_path().write_text(json.dumps({"sdd": {"enabled": True}}), encoding="utf-8")
        monkeypatch.setenv("FLEET_SDD", "0")
        assert fleet.sdd_enabled() is False

    def test_corrupt_config_is_off(self, home, monkeypatch):
        monkeypatch.delenv("FLEET_SDD", raising=False)
        fleet.config_path().write_text("{not json", encoding="utf-8")
        assert fleet.sdd_enabled() is False

    def test_verbs_refuse_when_off(self, home, monkeypatch):
        _write()
        monkeypatch.setenv("FLEET_SDD", "0")
        with pytest.raises(fleet.FleetCliError, match="disabled"):
            _accept()
        assert fleet.load_spec("md-demo")["status"] == "proposed"
        assert _verify() == 2
        with pytest.raises(fleet.FleetCliError, match="disabled"):
            fleet.cmd_spec_new(SimpleNamespace(campaign="other", actor="alice"))

    def test_main_routes_spec_verb(self, home, monkeypatch, capsys):
        monkeypatch.setenv("FLEET_SDD", "0")
        assert fleet.main(["spec", "verify", "md-demo"]) == 2


# --- parsing and digest ---------------------------------------------------

class TestParse:
    def test_reads_first_json_fence(self):
        data = fleet_spec.parse_spec(_spec_text())
        assert data["spec"] == "md-demo" and data["criteria"][0]["id"] == "C1"

    @pytest.mark.parametrize("text", [
        "# no machine block\n",
        "```json\n{not json\n```\n",
        "```json\n[1, 2]\n```\n",
    ])
    def test_rejects_malformed(self, text):
        with pytest.raises(fleet_spec.SpecFormatError):
            fleet_spec.parse_spec(text)

    def test_rejects_missing_key(self):
        bad = dict(GOOD)
        del bad["criteria"]
        with pytest.raises(fleet_spec.SpecFormatError):
            fleet_spec.parse_spec(_spec_text(bad))

    @pytest.mark.parametrize("node", [
        "-p evil", "--rootdir=/", "/abs/test.py", "../outside.py::t", "C:/x.py"])
    def test_rejects_option_or_escaping_node(self, node):
        bad = json.loads(json.dumps(GOOD))
        bad["criteria"][0]["nodes"] = [node]
        with pytest.raises(fleet_spec.SpecFormatError):
            fleet_spec.parse_spec(_spec_text(bad))

    def test_rejects_escaping_scope(self):
        bad = dict(GOOD, scope_allow=["../**"])
        with pytest.raises(fleet_spec.SpecFormatError):
            fleet_spec.parse_spec(_spec_text(bad))

    def test_rejects_bad_campaign_name(self, home):
        with pytest.raises(fleet_spec.SpecFormatError):
            fleet.spec_path("../escape")

    def test_spec_and_stamp_live_in_local_state(self, home):
        assert fleet.spec_path("md-demo") == home / "state" / "specs" / "md-demo.md"
        assert fleet.verify_stamp_path("md-demo") == home / "state" / "spec-verify" / "md-demo.json"

    def test_digest_stable_and_prose_free(self):
        a = fleet_spec.parse_spec(_spec_text())
        b = dict(reversed(list(a.items())))
        assert fleet_spec.spec_digest(a) == fleet_spec.spec_digest(b)
        b = json.loads(json.dumps(a))
        b["criteria"][0]["ears"] = "different prose"
        assert fleet_spec.spec_digest(a) == fleet_spec.spec_digest(b)

    @pytest.mark.parametrize("mutate", [
        lambda d: d["criteria"][0].update(nodes=["tests/test_x.py::test_EVIL"]),
        lambda d: d.update(scope_allow=["**"]),
        lambda d: d.update(scope_deny=[]),
        lambda d: d["criteria"][0].update(kind="files"),
    ])
    def test_digest_covers_executable_fields(self, mutate):
        a = fleet_spec.parse_spec(_spec_text())
        b = json.loads(json.dumps(a))
        mutate(b)
        assert fleet_spec.spec_digest(a) != fleet_spec.spec_digest(b)


# --- scope ----------------------------------------------------------------

class TestScope:
    def test_glob_containment(self):
        assert fleet_spec.glob_contains("src/**", "src/app/**")
        assert fleet_spec.glob_contains("src/**", "src/a.py")
        assert fleet_spec.glob_contains("**", "any/where.py")
        assert not fleet_spec.glob_contains("src/**", "docs/a.py")
        assert not fleet_spec.glob_contains("src/a.py", "src/**")

    def test_effective_scope_narrows(self):
        data = dict(GOOD, slices={"w1": {"scope_allow": ["src/app/**"],
                                         "scope_deny": ["src/app/gen/**"], "criteria": ["C1"]}})
        allow, deny = fleet_spec.effective_scope(data, "w1")
        assert allow == ["src/app/**"] and deny == ["state/**", "src/app/gen/**"]
        assert fleet_spec.effective_scope(GOOD, None) == (["src/**", "tests/**"], ["state/**"])

    def test_widening_slice_rejected(self):
        data = dict(GOOD, slices={"w1": {"scope_allow": ["docs/**"]}})
        assert any("widen" in p for p in fleet_spec.check_slice_scopes(data))

    @pytest.mark.parametrize("a,b", [
        ("src/**", "src/app/**"), ("src/*.py", "src/a.py"), ("src/**/x.py", "src/a/**")])
    def test_overlapping_slices_rejected_in_pattern_domain(self, a, b):
        data = dict(GOOD, slices={"w1": {"scope_allow": [a]}, "w2": {"scope_allow": [b]}})
        assert any("overlap" in p for p in fleet_spec.check_slice_scopes(data))

    def test_disjoint_slices_pass(self):
        data = dict(GOOD, slices={"w1": {"scope_allow": ["src/a/**"]},
                                  "w2": {"scope_allow": ["src/b/**"]}})
        assert fleet_spec.check_slice_scopes(data) == []


# --- touched paths: the four git queries ----------------------------------

class TestTouchedPaths:
    def test_four_queries_including_ignored(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            q = argv[3:]
            out = ""
            if q[:2] == ["rev-parse", "--show-prefix"]:
                out = "\n"
            elif q[0] == "diff" and "--cached" in q:
                out = "src/b.py\0"
            elif q[0] == "diff":
                out = "src/a.py\0"
            elif "--ignored" in q:
                out = "state/secret.json\0"
            elif q[0] == "ls-files":
                out = "src/new.py\0"
            return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        changed, ignored = fleet_spec.touched_paths(Path("."), "HEAD", run=run)
        assert changed == {"src/a.py", "src/b.py", "src/new.py"}
        assert ignored == {"state/secret.json"}
        queries = [c[3:] for c in calls[1:]]
        assert len(queries) == 4
        assert any("--ignored" in q for q in queries)

    def test_real_repo(self, repo):
        (repo / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
        (repo / "src" / "staged.py").write_text("s = 1\n", encoding="utf-8")
        _git(repo, "add", "src/staged.py")
        (repo / "fresh.py").write_text("y = 1\n", encoding="utf-8")
        (repo / "state").mkdir()
        (repo / "state" / "leak.json").write_text("{}", encoding="utf-8")
        changed, ignored = fleet_spec.touched_paths(repo, "HEAD")
        assert {"src/a.py", "src/staged.py", "fresh.py"} <= changed
        assert "state/leak.json" in ignored, "the ignored query is what makes scope_deny live"

    def test_committed_work_since_baseline_counts(self, repo):
        base = fleet.current_head_sha(repo)
        (repo / "docs.md").write_text("d\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "work")
        changed, _ = fleet_spec.touched_paths(repo, base)
        assert "docs.md" in changed

    def test_non_repo_raises(self, tmp_path):
        with pytest.raises(fleet_spec.TouchedPathsError):
            fleet_spec.touched_paths(tmp_path, None)


# --- criteria -------------------------------------------------------------

def _rc(code, out=""):
    def run(argv, **kw):
        run.argv = argv
        return types.SimpleNamespace(returncode=code, stdout=out, stderr="")
    return run


class TestCriteria:
    def test_files_in_scope_passes(self):
        r = fleet_spec.eval_files_criterion("C", {"src/a.py"}, ["src/**"], ["state/**"])
        assert r.status == "PASS"

    def test_files_out_of_scope_fails(self):
        r = fleet_spec.eval_files_criterion("C", {"docs/x.md"}, ["src/**"], [])
        assert r.status == "FAIL" and "docs/x.md" in r.detail

    def test_files_denied_ignored_path_fails(self):
        r = fleet_spec.eval_files_criterion("C", set(), ["src/**"], ["state/**"],
                                            ignored={"state/leak.json"})
        assert r.status == "FAIL" and "state/leak.json" in r.detail

    def test_ignored_path_outside_allow_is_not_attributed(self):
        r = fleet_spec.eval_files_criterion("C", set(), ["src/**"], ["state/**"],
                                            ignored={"__pycache__/x.pyc"})
        assert r.status == "PASS"

    def test_unknown_kind_fails_closed(self):
        r = fleet_spec.eval_criterion({"id": "C", "kind": "wishful"}, Path("."), set(), [], [])
        assert r.status == "FAIL" and "unknown kind" in r.detail

    def test_pytest_pass(self):
        run = _rc(0, "1 passed in 0.01s")
        r = fleet_spec.eval_pytest_criterion("C", Path("."), ["tests/t.py::x"], run=run)
        assert r.status == "PASS"
        assert run.argv[1:3] == ["-m", "pytest"] and run.argv[-2:] == ["--", "tests/t.py::x"]

    @pytest.mark.parametrize("code,out", [
        (1, "1 failed"), (5, "collected 0 items"), (4, "ERROR: file or directory not found"),
        (2, "1 error during collection"), (0, "1 skipped")])
    def test_pytest_failure_classes_are_FAIL_not_infra(self, code, out):
        r = fleet_spec.eval_pytest_criterion("C", Path("."), ["tests/t.py::x"], run=_rc(code, out))
        assert r.status == "FAIL", "a missing or empty target is under-delivery, never infra"

    def test_pytest_runner_absent_is_INFRA(self):
        def run(argv, **kw):
            raise FileNotFoundError("no interpreter")
        r = fleet_spec.eval_pytest_criterion("C", Path("."), ["tests/t.py::x"], run=run)
        assert r.status == "INFRA"

    def test_pytest_module_missing_is_INFRA(self):
        r = fleet_spec.eval_pytest_criterion(
            "C", Path("."), ["tests/t.py::x"], run=_rc(1, "No module named pytest"))
        assert r.status == "INFRA"

    def test_pytest_no_nodes_fails(self):
        assert fleet_spec.eval_pytest_criterion("C", Path("."), []).status == "FAIL"


# --- spec new / accept ----------------------------------------------------

class TestLifecycle:
    def test_new_scaffolds_proposed(self, home):
        assert fleet.cmd_spec_new(SimpleNamespace(campaign="md-demo", actor="alice")) == 0
        data = fleet.load_spec("md-demo")
        assert data["status"] == "proposed" and data["author"] == "alice"
        with pytest.raises(fleet.FleetCliError, match="already exists"):
            fleet.cmd_spec_new(SimpleNamespace(campaign="md-demo", actor="alice"))

    def test_new_requires_actor(self, home):
        with pytest.raises(fleet.FleetCliError, match="actor"):
            fleet.cmd_spec_new(SimpleNamespace(campaign="md-demo", actor=None))

    def test_accept_refuses_self_promotion(self, home):
        _write()
        with pytest.raises(fleet.FleetCliError, match="author"):
            _accept("alice")
        assert fleet.load_spec("md-demo")["status"] == "proposed"

    def test_actor_comes_from_env(self, home, monkeypatch):
        _write()
        monkeypatch.setenv("FLEET_ACTOR", "alice")
        with pytest.raises(fleet.FleetCliError, match="author"):
            _accept(None)

    @pytest.mark.parametrize("reviewed", ["", "alice"])
    def test_accept_refuses_without_independent_review(self, home, reviewed):
        _write(reviewed_by=reviewed)
        with pytest.raises(fleet.FleetCliError, match="reviewed_by"):
            _accept()

    def test_accept_stamps_digest_and_keeps_body(self, home):
        data = _write()
        assert _accept() == 0
        got = fleet.load_spec("md-demo")
        assert got["status"] == "accepted" and got["accepted_by"] == "bob"
        assert got["accepted_digest"] == fleet_spec.spec_digest(data)
        assert "## Context\nbody" in fleet.spec_path("md-demo").read_text(encoding="utf-8")

    def test_accept_refuses_twice(self, home):
        _write()
        _accept()
        with pytest.raises(fleet.FleetCliError, match="not 'proposed'"):
            _accept("carol")

    def test_accept_refuses_widening_slice(self, home):
        _write(slices={"w1": {"scope_allow": ["docs/**"]}})
        assert _accept() == 2

    def test_accept_malformed_is_2(self, home):
        fleet.spec_path("md-demo").parent.mkdir(parents=True, exist_ok=True)
        fleet.spec_path("md-demo").write_text("```json\n{\n```\n", encoding="utf-8")
        assert _accept() == 2


# --- verify ---------------------------------------------------------------

class TestVerify:
    def _accepted(self, **over):
        _write(**over)
        assert _accept() == 0

    def test_proposed_is_2(self, home):
        _write()
        assert _verify() == 2

    def test_tamper_is_2(self, home):
        self._accepted()
        data = fleet.load_spec("md-demo")
        data["criteria"][0]["nodes"] = ["tests/test_x.py::test_EVIL"]
        fleet.write_spec("md-demo", data, "body")
        assert _verify() == 2
        assert not fleet.verify_stamp_path("md-demo").exists()

    def test_pass_writes_stamp(self, home, repo, monkeypatch):
        self._accepted()
        monkeypatch.chdir(repo)
        (repo / "src" / "a.py").write_text("x = 3\n", encoding="utf-8")
        assert _verify(run=_rc(0, "1 passed")) == 0
        stamp = json.loads(fleet.verify_stamp_path("md-demo").read_text(encoding="utf-8"))
        assert stamp["overall"] == "PASS" and stamp["spec_status"] == "accepted"
        assert {c["id"] for c in stamp["per_criterion"]} == {"_scope", "C1"}

    def test_out_of_scope_is_1(self, home, repo, monkeypatch, capsys):
        self._accepted()
        monkeypatch.chdir(repo)
        (repo / "README.md").write_text("drift\n", encoding="utf-8")
        assert _verify(run=_rc(0, "1 passed")) == 1
        assert "README.md (out of scope)" in capsys.readouterr().out

    def test_denied_ignored_file_is_1(self, home, repo, monkeypatch):
        self._accepted()
        monkeypatch.chdir(repo)
        (repo / "state").mkdir()
        (repo / "state" / "leak.json").write_text("{}", encoding="utf-8")
        assert _verify(run=_rc(0, "1 passed")) == 1

    def test_failing_criterion_is_1(self, home, repo, monkeypatch):
        self._accepted()
        monkeypatch.chdir(repo)
        assert _verify(run=_rc(1, "1 failed")) == 1
        stamp = json.loads(fleet.verify_stamp_path("md-demo").read_text(encoding="utf-8"))
        assert stamp["overall"] == "FAIL"

    def test_unknown_kind_is_1(self, home, repo, monkeypatch):
        self._accepted(criteria=[{"id": "C9", "kind": "wishful"}])
        monkeypatch.chdir(repo)
        assert _verify() == 1

    def test_non_repo_is_2(self, home, tmp_path, monkeypatch):
        self._accepted(criteria=[])
        monkeypatch.chdir(tmp_path)
        assert _verify() == 2

    def test_option_shaped_base_is_refused(self, home, repo, monkeypatch):
        self._accepted(criteria=[])
        monkeypatch.chdir(repo)
        assert _verify(base="--output=/tmp/x") == 2

    def test_real_pytest_node(self, home, repo, monkeypatch):
        (repo / "tests").mkdir()
        (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                                   encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "t")
        self._accepted(criteria=[
            {"id": "C1", "kind": "pytest", "nodes": ["tests/test_ok.py::test_ok"]},
            {"id": "C2", "kind": "files", "scope_allow": ["src/**"]}])
        monkeypatch.chdir(repo)
        assert _verify() == 0
        self._reaccept_with_nodes(["tests/test_ok.py::test_gone"])
        assert _verify() == 1, "a renamed target is under-delivery, never infra"

    def _reaccept_with_nodes(self, nodes):
        data = fleet.load_spec("md-demo")
        data.update(status="proposed", accepted_by="", accepted_digest="")
        data["criteria"][0]["nodes"] = nodes
        fleet.write_spec("md-demo", data, "body")
        assert _accept() == 0


# --- binding --------------------------------------------------------------

def _spawn(name, cwd, monkeypatch, spec=None, slice_name=None, calls=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, [_entry(SID_1)])))
    args = SimpleNamespace(name=name, dir=str(cwd), task="do the thing", mode="bypass",
                           model=None, max_budget_usd=None, setting_sources=None,
                           token_ceiling=None, category=None, context=None,
                           yes=True, nonce=None, spec=spec, slice=slice_name)
    return fleet.cmd_spawn(args, run=_run_for(SID_1, calls), which=_claude,
                           sleep=lambda s: None, clock=lambda: 0.0)


def _respawn(name, monkeypatch, calls=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, []), (True, [_entry(SID_2)])))
    args = SimpleNamespace(name=name, task=None, force=False, yes=True, max_budget_usd=None,
                           setting_sources=None, token_ceiling=None, nonce=None)
    return fleet.cmd_respawn(args, run=_run_for(SID_2, calls), which=_claude,
                             sleep=lambda s: None, clock=lambda: 0.0)


def _add_dirs(calls):
    argv = next(a for a in calls if "--bg" in a)
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"]


class TestBinding:
    SLICED = {"w1": {"scope_allow": ["src/**"], "criteria": ["C1"]}}

    def test_flag_off_spawn_is_unchanged(self, home, repo, monkeypatch):
        monkeypatch.setenv("FLEET_SDD", "0")
        calls = []
        assert _spawn("w1", repo, monkeypatch, calls=calls) == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert not {"spec", "spec_slice", "spec_baseline_sha"} & set(rec)
        assert _add_dirs(calls) == []
        assert "BINDING SPEC" not in fleet.task_file_path("w1").read_text(encoding="utf-8")

    def test_spec_flag_refused_when_sdd_off(self, home, repo, monkeypatch):
        monkeypatch.setenv("FLEET_SDD", "0")
        with pytest.raises(fleet.FleetCliError, match="disabled"):
            _spawn("w1", repo, monkeypatch, spec="md-demo")
        assert "w1" not in fleet.load_registry()["workers"]

    def test_refuses_proposed_spec(self, home, repo, monkeypatch):
        _write()
        with pytest.raises(fleet.FleetCliError, match="not accepted"):
            _spawn("w1", repo, monkeypatch, spec="md-demo")
        assert "w1" not in fleet.load_registry()["workers"]

    def test_refuses_unknown_slice(self, home, repo, monkeypatch):
        _write()
        _accept()
        with pytest.raises(fleet.FleetCliError, match="no slice"):
            _spawn("w1", repo, monkeypatch, spec="md-demo", slice_name="nope")

    def test_spawn_binds_and_respawn_carries(self, home, repo, monkeypatch):
        _write(slices=self.SLICED)
        _accept()
        calls = []
        assert _spawn("w1", repo, monkeypatch, spec="md-demo", slice_name="w1", calls=calls) == 0
        rec = fleet.load_registry()["workers"]["w1"]
        first_base = fleet.current_head_sha(repo)
        assert (rec["spec"], rec["spec_slice"], rec["spec_baseline_sha"]) == (
            "md-demo", "w1", first_base)
        assert fleet.campaign_specs_dir().as_posix() in _add_dirs(calls)
        body = fleet.task_file_path("w1").read_text(encoding="utf-8")
        assert "## BINDING SPEC" in body and "src/**" in body and "Re-read" in body

        (repo / "src" / "b.py").write_text("b = 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "merged work")
        fleet.save_registry(fleet.load_registry())
        calls = []
        assert _respawn("w1", monkeypatch, calls=calls) == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert (rec["spec"], rec["spec_slice"]) == ("md-demo", "w1")
        assert rec["spec_baseline_sha"] == fleet.current_head_sha(repo) != first_base
        assert fleet.campaign_specs_dir().as_posix() in _add_dirs(calls)
        assert "## BINDING SPEC" in fleet.task_file_path("w1").read_text(encoding="utf-8")

    def test_verify_worker_uses_registered_cwd_and_slice(self, home, repo, monkeypatch, tmp_path):
        _write(slices=self.SLICED)
        _accept()
        assert _spawn("w1", repo, monkeypatch, spec="md-demo", slice_name="w1") == 0
        monkeypatch.chdir(tmp_path)
        (repo / "tests").mkdir()
        (repo / "tests" / "t.py").write_text("t = 1\n", encoding="utf-8")
        assert _verify(worker="w1", run=_rc(0, "1 passed")) == 1, (
            "tests/** is in the whole-spec scope but outside slice w1")
        stamp = json.loads(fleet.verify_stamp_path("md-demo").read_text(encoding="utf-8"))
        assert stamp["slice"] == "w1" and stamp["cwd"] == str(repo)

    def test_verify_worker_bound_elsewhere_is_2(self, home, repo, monkeypatch):
        monkeypatch.setenv("FLEET_SDD", "0")
        assert _spawn("w1", repo, monkeypatch) == 0
        monkeypatch.setenv("FLEET_SDD", "1")
        _write()
        _accept()
        assert _verify(worker="w1") == 2

    def test_carry_restamps_baseline(self):
        before = {"spec": "md-demo", "spec_slice": "w1", "spec_baseline_sha": "OLD"}
        after = fleet.new_worker_record(None, "/tmp", "task", "bypass")
        fleet.carry_spec_binding(before, after, "NEW")
        assert (after["spec"], after["spec_slice"], after["spec_baseline_sha"]) == (
            "md-demo", "w1", "NEW")
