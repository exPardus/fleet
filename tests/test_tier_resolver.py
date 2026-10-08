"""three-tier-command.md §3.1/§3.3/§3.5 -- the role->tier->model resolver.

Roles bind to ABSTRACT tiers (top/second/third), never to model ids (§3.1). The
supervisor's binding is a preference CHAIN `[top, second]` (§3.5). The policy is
OPERATOR-OWNED and lives in supervisor/GOALS.md -- fleet READS it (never a code
constant, §3.3), with a documented default when GOALS is silent and no hardcoded
model id anywhere (the §3.2 receipt: fleet emits a tier ALIAS, the daemon
resolves it). When a tier has no operator-set model alias, the resolver returns
None => omit `--model` and let the namespace default govern (§3.3(d)).
"""
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def goals_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "supervisor").mkdir()
    return tmp_path


def _write_goals(home, text):
    (home / "supervisor" / "GOALS.md").write_text(text, encoding="utf-8")


class TestDefaults:
    def test_absent_goals_yields_documented_defaults(self, goals_home):
        pol = fleet.read_tier_policy()
        assert pol["supervisor_chain"] == ["top", "second"]
        assert pol["worker_tiers"] == ["second", "third"]
        assert pol["_source"] == "default"

    def test_default_tier_model_is_empty_no_hardcoded_ids(self, goals_home):
        # §3.2/§3.3: fleet ships NO model id. Absent operator policy => no
        # tier->alias mapping, so resolution omits --model.
        pol = fleet.read_tier_policy()
        assert pol["tier_model"] == {}
        assert fleet.resolve_model_for_role("supervisor", pol) is None

    def test_goals_without_the_block_uses_defaults(self, goals_home):
        _write_goals(goals_home, "# GOALS\n\nSome prose, no tier policy.\n")
        pol = fleet.read_tier_policy()
        assert pol["supervisor_chain"] == ["top", "second"]
        assert pol["_source"] == "default"


class TestParsing:
    def test_reads_supervisor_chain_from_goals(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\n"
                     "supervisor-tier-chain: top, second\n"
                     "-->\n")
        pol = fleet.read_tier_policy()
        assert pol["supervisor_chain"] == ["top", "second"]
        assert pol["_source"] == "goals"

    def test_one_line_block_closes_before_following_stray(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy -->\n"
                     "tier-model: top=opus\n")
        pol = fleet.read_tier_policy()
        assert pol["_stray_tier_model_lines"] == [2]
        with pytest.raises(fleet.FleetCliError, match="line 2"):
            fleet._enforce_tier_policy("supervisor", None, pol)

    def test_unterminated_block_is_refused(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\n"
                     "supervisor-tier-chain: top\n")
        pol = fleet.read_tier_policy()
        assert pol["_unterminated_tier_policy"] == 1
        with pytest.raises(fleet.FleetCliError, match="unterminated"):
            fleet._enforce_tier_policy("supervisor", None, pol)

    def test_reads_a_length_one_chain(self, goals_home):
        # §3.5: a chain of length 1 is legal (no fallback -- single-model provider).
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\nsupervisor-tier-chain: second\n-->\n")
        assert fleet.read_tier_policy()["supervisor_chain"] == ["second"]

    def test_reads_tier_model_aliases(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\n"
                     "supervisor-tier-chain: top, second\n"
                     "tier-model: top=opus, second=opus, third=sonnet\n"
                     "-->\n")
        pol = fleet.read_tier_policy()
        assert pol["tier_model"] == {"top": "opus", "second": "opus", "third": "sonnet"}

    def test_reads_worker_tiers(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\nworker-tiers: second, third\n-->\n")
        assert fleet.read_tier_policy()["worker_tiers"] == ["second", "third"]

    def test_malformed_block_falls_back_to_defaults_never_raises(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\nsupervisor-tier-chain:\ngarbage line\n-->\n")
        pol = fleet.read_tier_policy()
        # empty value -> keep the default chain rather than an empty list
        assert pol["supervisor_chain"] == ["top", "second"]

    def test_stray_tier_model_line_is_recorded_for_spawn_refusal(self, goals_home):
        _write_goals(goals_home, "# GOALS\n\ntier-model: top=opus\n")
        pol = fleet.read_tier_policy()
        assert pol["_stray_tier_model_lines"] == [3]
        with pytest.raises(fleet.FleetCliError, match="outside"):
            fleet._enforce_tier_policy("supervisor", None, pol)

    def test_stray_tier_model_after_policy_block_is_recorded(self, goals_home):
        _write_goals(
            goals_home,
            "<!-- fleet-tier-policy\n"
            "forbid-default: true\n"
            "-->\n"
            "tier-model: top=opus\n",
        )
        pol = fleet.read_tier_policy()
        assert pol["_stray_tier_model_lines"] == [4]
        with pytest.raises(fleet.FleetCliError, match="line 4"):
            fleet._enforce_tier_policy("supervisor", None, pol)

    def test_forbid_default_rejects_unresolved_role(self, goals_home):
        _write_goals(goals_home,
                     "<!-- fleet-tier-policy\n"
                     "forbid-default: true\n"
                     "supervisor-tier-chain: top\n"
                     "tier-model: second=opus\n"
                     "-->\n")
        pol = fleet.read_tier_policy()
        assert pol["forbid_default"] is True
        with pytest.raises(fleet.FleetCliError, match="Anthropic default"):
            fleet._enforce_tier_policy("supervisor", None, pol)

    def test_blank_model_is_treated_as_omitted(self, goals_home):
        _write_goals(
            goals_home,
            "<!-- fleet-tier-policy\n"
            "forbid-default: true\n"
            "supervisor-tier-chain: top\n"
            "-->\n",
        )
        pol = fleet.read_tier_policy()
        with pytest.raises(fleet.FleetCliError, match="Anthropic default"):
            fleet._enforce_tier_policy("supervisor", "  \t", pol)

    def test_sup_spawn_refuses_stray_policy_before_dispatch(self, goals_home,
                                                             monkeypatch):
        _write_goals(goals_home, "tier-model: top=opus\n")
        (goals_home / "state").mkdir()
        (goals_home / "state" / "worker-settings.json").write_text("{}")
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setattr(fleet, "_require_instance_settings", lambda: None)
        monkeypatch.setattr(fleet, "_dispatch_supervisor_body",
                            lambda *a, **k: pytest.fail("dispatch must not run"))
        args = SimpleNamespace(task="campaign", model=None,
                               permission_mode=None, codex_adapter=None,
                               setting_sources=None, nonce=None,
                               force_band=False)
        with pytest.raises(fleet.FleetCliError, match="outside"):
            fleet.cmd_sup_spawn(args)

    @staticmethod
    def _forbid_default_goals(home):
        _write_goals(home,
                     "<!-- fleet-tier-policy\n"
                     "forbid-default: true\n"
                     "supervisor-tier-chain: top\n"
                     "-->\n")

    def test_spawn_blank_model_is_refused_by_command_policy(self, goals_home,
                                                             monkeypatch):
        self._forbid_default_goals(goals_home)
        worker_dir = goals_home / "project"
        worker_dir.mkdir()
        (goals_home / "state").mkdir()
        (goals_home / "state" / "worker-settings.json").write_text("{}")
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        args = SimpleNamespace(name="worker", dir=str(worker_dir), task="do work",
                               mode="dontask", model="", category=None,
                               setting_sources=None, token_ceiling=None,
                               max_budget_usd=None, nonce=None, force_band=False,
                               codex_adapter="mcx", effort="medium", context=None)
        with pytest.raises(fleet.FleetCliError, match="Anthropic default"):
            fleet.cmd_spawn(args)

    def test_sup_spawn_blank_model_is_refused_by_command_policy(self, goals_home,
                                                                 monkeypatch):
        self._forbid_default_goals(goals_home)
        (goals_home / "state").mkdir()
        (goals_home / "state" / "worker-settings.json").write_text("{}")
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        args = SimpleNamespace(task="campaign", model="", permission_mode=None,
                               codex_adapter=None, setting_sources=None, nonce=None,
                               force_band=False)
        with pytest.raises(fleet.FleetCliError, match="Anthropic default"):
            fleet.cmd_sup_spawn(args)

    def test_handoff_blank_model_is_refused_by_command_policy(self, goals_home,
                                                               monkeypatch):
        self._forbid_default_goals(goals_home)
        monkeypatch.setattr(fleet, "_claim_uses_native_codex",
                            lambda claim=None: False)
        args = SimpleNamespace(sid="sid-old", model="", permission_mode=None)
        # A blank --model is omission; with no resolvable predecessor the
        # handoff refuses before any default model can be chosen.
        with pytest.raises(fleet.FleetCliError, match=r"unresolved.*pass --model"):
            fleet.cmd_sup_handoff_begin(args)


class TestResolve:
    def _pol(self, home, tier_model):
        _write_goals(home,
                     "<!-- fleet-tier-policy\n"
                     "supervisor-tier-chain: top, second\n"
                     "worker-tiers: second, third\n"
                     f"tier-model: {tier_model}\n"
                     "-->\n")
        return fleet.read_tier_policy()

    def test_supervisor_resolves_to_first_tier_alias(self, goals_home):
        pol = self._pol(goals_home, "top=opus, second=opus")
        assert fleet.resolve_model_for_role("supervisor", pol) == "opus"

    def test_worker_resolves_to_first_worker_tier_alias(self, goals_home):
        pol = self._pol(goals_home, "second=opus, third=sonnet")
        assert fleet.resolve_model_for_role("worker", pol) == "opus"

    def test_unmapped_tier_resolves_to_none_omit_model(self, goals_home):
        pol = self._pol(goals_home, "third=sonnet")  # top unmapped
        assert fleet.resolve_model_for_role("supervisor", pol) is None

    def test_supervisor_resolves_first_mapped_tier_in_preference_chain(
            self, goals_home):
        pol = self._pol(goals_home, "second=opus")  # top unmapped; fall back
        assert fleet.resolve_model_for_role("supervisor", pol) == "opus"

    def test_interface_role_is_advisory_top(self, goals_home):
        pol = self._pol(goals_home, "top=opus")
        assert fleet.resolve_model_for_role("interface", pol) == "opus"

    def test_resolve_reads_policy_itself_when_not_passed(self, goals_home):
        self._pol(goals_home, "top=opus")
        assert fleet.resolve_model_for_role("supervisor") == "opus"


class TestProposal:
    def test_proposed_goals_block_names_the_chain(self):
        block = fleet.proposed_goals_tier_block()
        assert "fleet-tier-policy" in block
        assert "supervisor-tier-chain: top, second" in block
        assert "worker-tiers: second, third" in block
