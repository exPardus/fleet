"""three-tier-command.md §3.1/§3.3/§3.5 -- the role->tier->model resolver.

Roles bind to ABSTRACT tiers (top/second/third), never to model ids (§3.1). The
supervisor's binding is a preference CHAIN `[top, second]` (§3.5). The policy is
OPERATOR-OWNED and lives in supervisor/GOALS.md -- fleet READS it (never a code
constant, §3.3), with a documented default when GOALS is silent and no hardcoded
model id anywhere (the §3.2 receipt: fleet emits a tier ALIAS, the daemon
resolves it). When a tier has no operator-set model alias, the resolver returns
None => omit `--model` and let the namespace default govern (§3.3(d)).
"""
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
