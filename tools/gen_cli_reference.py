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
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "cli-reference.md"
# argparse wraps usage and help to the terminal width. Pin it so the output is
# identical in every terminal, including the one the drift test runs in.
PINNED_COLUMNS = "80"

HEADER = """\
# fleet CLI reference

<!-- Generated from bin/fleet.py build_parser() by tools/gen_cli_reference.py.
     Do not edit by hand. Regenerate with: python tools/gen_cli_reference.py -->

Every verb and option below is printed by the parser itself. For the workflow
behind the verbs, read [getting-started.md](getting-started.md); for the
behavioural contract, read [SPEC.md](SPEC.md).

Verbs marked hidden in the parser are not listed here.
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
        # The top-level help lists every verb, hidden ones included, so it is
        # not pasted whole. Its description and epilog carry the global rules.
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
            out.append(_block(subparser.format_help()))
        return "\n".join(out).rstrip("\n") + "\n"
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous


def _block(help_text: str) -> str:
    return "```text\n" + help_text.rstrip("\n") + "\n```\n"


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
