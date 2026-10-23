#!/usr/bin/env python3
"""Render docs/cli-reference.md from bin/fleet.py build_parser().

The parser is the only source. Run with no arguments to rewrite the reference,
or with --check to exit 1 when the committed file has drifted from the parser.
Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "cli-reference.md"
# argparse wraps usage and help to the terminal width. Pin it for every
# terminal; Fleet's parser and formatter also normalize Python-version changes.
PINNED_COLUMNS = "80"

HEADER = """\
# fleet CLI reference

<!-- Generated from bin/fleet.py build_parser() by tools/gen_cli_reference.py.
     Do not edit by hand. Regenerate with: python tools/gen_cli_reference.py -->

Every verb and option below comes from the parser. Constraint notes summarize
its mutually exclusive option groups. For the workflow behind the verbs, read
[getting-started.md](getting-started.md); for the behavioural contract, read
[SPEC.md](SPEC.md).

Verbs marked hidden in the parser are not listed here or in top-level
`fleet --help` output.
"""


def load_fleet(repo: Path = REPO):
    """Import bin/fleet.py by path. The module is registered as `fleet`."""
    cached = sys.modules.get("fleet")
    if cached is not None and Path(cached.__file__).resolve() == (
            repo / "bin" / "fleet.py").resolve():
        return cached
    bin_dir = str(repo / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    spec = importlib.util.spec_from_file_location(
        "fleet", repo / "bin" / "fleet.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["fleet"] = module
    spec.loader.exec_module(module)
    return module


def _subparser_action(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _visible_verbs(parser: argparse.ArgumentParser):
    """(name, summary, subparser) for every verb whose help is not SUPPRESS."""
    subs = _subparser_action(parser)
    if subs is None:
        raise SystemExit("fleet parser has no subcommands")
    summaries = {choice.dest: choice.help for choice in subs._choices_actions}
    rows = []
    for name, subparser in subs.choices.items():
        summary = summaries.get(name)
        if summary == argparse.SUPPRESS:
            continue
        rows.append((name, summary or "", subparser))
    return rows


def _visible_commands(parser: argparse.ArgumentParser, prefix=()):
    """(path, summary, parser) for every visible command below *parser*."""
    subs = _subparser_action(parser)
    if subs is None:
        return []
    summaries = {choice.dest: choice.help for choice in subs._choices_actions}
    rows = []
    for name, subparser in subs.choices.items():
        summary = summaries.get(name)
        if summary == argparse.SUPPRESS:
            continue
        path = (*prefix, name)
        rows.append((path, summary or "", subparser))
        rows.extend(_visible_commands(subparser, path))
    return rows


def render(fleet_module=None) -> str:
    """Return the full reference text for the current parser."""
    if fleet_module is None:
        fleet_module = load_fleet()
    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = PINNED_COLUMNS
    try:
        parser = fleet_module.build_parser()
        # Keep the global synopsis stable and compact rather than pasting the
        # width-sensitive top-level help. Its description and epilog carry the
        # global rules.
        out = [HEADER, "## Global options\n"]
        out.append(_block(f"usage: {parser.prog} <verb> [options]\n\n"
                          f"{parser.description}\n\n{parser.epilog}"))
        out.append("## Verbs\n")
        rows = _visible_commands(parser)
        for path, summary, _ in rows:
            command = " ".join(path)
            anchor = "-".join(path)
            indent = "  " * (len(path) - 1)
            out.append(
                f"{indent}- [`fleet {command}`](#fleet-{anchor}) — {summary}")
        out.append("")
        for path, _, subparser in rows:
            command = " ".join(path)
            heading = "#" * min(2 + len(path), 6)
            out.append(f"{heading} fleet {command}\n")
            for constraint in _group_constraints(subparser):
                note = textwrap.wrap(
                    f"Constraint: {constraint}", width=88,
                    subsequent_indent="  ")
                out.append("\n".join(note) + "\n")
            out.append(_block(_stable_help(subparser)))
        return "\n".join(out).rstrip("\n") + "\n"
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous


def _block(help_text: str) -> str:
    return "```text\n" + help_text.rstrip("\n") + "\n```\n"


def _stable_help(parser: argparse.ArgumentParser) -> str:
    """Normalize argparse's Python-version-specific exclusive-group usage.

    Python 3.14 renders a mutually exclusive group with pipe separators while
    3.10/3.12 list the same switches independently. The reference documents
    every option, and `_group_constraints` records the group's exact constraint
    immediately above this display. Parser validation still enforces it.
    """
    groups = parser._mutually_exclusive_groups
    parser._mutually_exclusive_groups = []
    try:
        return parser.format_help()
    finally:
        parser._mutually_exclusive_groups = groups


def _group_constraints(parser: argparse.ArgumentParser) -> list[str]:
    """Describe every parser mutex group without depending on argparse text."""
    constraints = []
    for group in parser._mutually_exclusive_groups:
        members = []
        for action in group._group_actions:
            if not action.option_strings:
                continue
            aliases = action.option_strings[1:]
            label = f"`{action.option_strings[0]}`"
            if aliases:
                label += " (alias " + ", ".join(f"`{item}`" for item in aliases) + ")"
            members.append(label)
        if len(members) < 2:
            continue
        choices = " or ".join(members)
        if group.required:
            constraints.append(f"Exactly one of {choices} is required.")
        else:
            constraints.append(f"At most one of {choices} may be used.")
    return constraints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the committed reference is stale")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(f"{OUTPUT.relative_to(REPO).as_posix()} is stale; run "
                  "python tools/gen_cli_reference.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"wrote {OUTPUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
