"""Per-subcommand effect tiers for `msg` (messaging spec §13, plan PR 12)."""
import argparse

import pytest

import fleet

TIERS = {
    "send": "ordinary", "inbox": "ordinary", "ack": "ordinary",
    "status": "ordinary", "queue": "ordinary", "ids": "ordinary",
    "whois": "ordinary", "init": "ordinary",
    "bind": "disruptive", "retire": "disruptive", "sync": "disruptive",
    "serve": "disruptive", "import": "disruptive", "compact": "disruptive",
    "purge": "destructive",
}


def _ns(sub):
    return argparse.Namespace(command="msg", msg_command=sub)


@pytest.mark.parametrize("sub,tier", sorted(TIERS.items()))
def test_msg_subcommand_tier(sub, tier):
    assert fleet.verb_effect_tier("msg", _ns(sub)) == tier


@pytest.mark.parametrize("args", [None, _ns(None), _ns("frobnicate"), _ns("")])
def test_unknown_msg_subcommand_fails_closed(args):
    assert fleet.verb_effect_tier("msg", args) == "destructive"


def test_msg_is_in_no_flat_tuple():
    for tup in (fleet.VERB_EFFECT_DESTRUCTIVE, fleet.VERB_EFFECT_DISRUPTIVE,
                fleet.VERB_EFFECT_ORDINARY):
        assert not [t for t in tup if t.split()[0] == "msg"]


def test_every_parsed_msg_subcommand_is_classified():
    parser = fleet.build_parser()
    top = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    msg = top.choices["msg"]
    subs = next(a for a in msg._actions
                if isinstance(a, argparse._SubParsersAction)).choices
    listed = {s for t in fleet.VERB_EFFECT_SUBCOMMANDS["msg"][1].values()
              for s in t}
    assert set(subs) <= listed
