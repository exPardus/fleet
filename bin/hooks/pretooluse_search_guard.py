#!/usr/bin/env python3
"""PreToolUse guard: refuse filesystem searches rooted at `/` or the home dir.

Standalone, stdlib only. Never imports bin/fleet.py. A worker that runs
`find /`, `rg pattern ~` or `grep -r x /home` walks every lane's worktree,
every node_modules and the whole Claude config, which loaded the shared host
for minutes at a time. The worker preamble already says to search only inside
the working tree; this hook makes the common forms of that mistake fail fast
with a reason the worker can act on.

Scope is deliberately narrow and cheap: `find`, `bfs`, `fd`/`fdfind`, `rg`
and recursive `grep` in a Bash command, plus the Grep and Glob tools' `path`.
A root is refused when it is `/`, the home directory, or an ancestor of the
home directory (such as `/home`). Subdirectories of home, including every
worktree, stay allowed. Anything this hook cannot parse is allowed: it is a
guard against an expensive habit, not a sandbox, and it must never block a
legitimate command because of a parsing gap. Exit 0 on every path.
"""
import json
import os
import shlex
import sys

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", "\n"}
WRAPPERS = {"sudo", "time", "nice", "nohup", "command", "exec", "env",
            "ionice", "stdbuf", "builtin"}
FD_VALUE = {"-e", "--extension", "-t", "--type", "-E", "--exclude", "-d",
            "--max-depth", "--min-depth", "--exact-depth", "-j", "--threads",
            "-c", "--color", "-o", "--owner", "-S", "--size", "--changed-within",
            "--changed-before", "--and", "--max-results", "--path-separator",
            "--ignore-file", "--batch-size", "--format"}
FD_PATH_VALUE = {"--search-path", "--base-directory"}
RG_VALUE = {"-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not",
            "-m", "--max-count", "-A", "--after-context", "-B",
            "--before-context", "-C", "--context", "--max-depth", "-d", "-j",
            "--threads", "--type-add", "--type-clear", "-M", "--max-columns",
            "--max-filesize", "--color", "--colors", "-r", "--replace", "--pre",
            "--pre-glob", "--sort", "--sortr", "-E", "--encoding",
            "--path-separator", "--context-separator", "--field-match-separator",
            "--field-context-separator", "--dfa-size-limit", "--regex-size-limit",
            "--engine", "--ignore-file"}
RG_PATTERN_VALUE = {"-e", "--regexp", "-f", "--file"}
GREP_VALUE = {"-m", "--max-count", "-A", "--after-context", "-B",
              "--before-context", "-C", "--context", "-d", "--directories",
              "-D", "--devices", "--label", "--color", "--colour"}
GREP_PATTERN_VALUE = {"-e", "--regexp", "-f", "--file"}


def _home():
    return os.path.normpath(os.path.expanduser("~"))


def _expand(path, cwd, home):
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    for token in ("${HOME}", "$HOME"):
        if path == token or path.startswith(token + "/"):
            path = home + path[len(token):]
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    return os.path.normpath(path)


def too_broad(path, cwd=None, home=None):
    """True for `/`, the home directory, or any ancestor of it."""
    home = home or _home()
    resolved = _expand(path, cwd, home)
    return (resolved == os.sep or resolved == home
            or home.startswith(resolved.rstrip(os.sep) + os.sep))


def _segments(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segment = []
    for token in lexer:
        if token in SEPARATORS or set(token) <= set(";&|()\n"):
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _strip_wrappers(words):
    index = 0
    while index < len(words):
        word = words[index]
        if "=" in word and not word.startswith("-") and word.split("=")[0].isidentifier():
            index += 1
        elif os.path.basename(word) in WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
        elif os.path.basename(word) == "timeout":
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
            index += 1  # the duration
        else:
            break
    return words[index:]


def _find_roots(args):
    roots, index = [], 0
    while index < len(args):
        if args[index] in ("-H", "-L", "-P") or args[index].startswith("-O"):
            index += 1
        elif args[index] == "-D":
            index += 2
        else:
            break
    for arg in args[index:]:
        if arg.startswith("-") or arg in ("(", "!", ","):
            break
        roots.append(arg)
    return roots


def _positional_roots(args, value_options, path_options, pattern_options,
                      pattern_needed=True):
    positionals, paths, pattern_given, index = [], [], False, 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positionals.extend(args[index + 1:])
            break
        if arg.startswith("--") and "=" in arg:
            name, value = arg.split("=", 1)
            if name in path_options:
                paths.append(value)
            elif name in pattern_options:
                pattern_given = True
        elif arg in path_options:
            if index + 1 < len(args):
                paths.append(args[index + 1])
            index += 1
        elif arg in pattern_options:
            pattern_given = True
            index += 1
        elif arg in value_options:
            index += 1
        elif arg.startswith("-") and arg != "-":
            pass
        else:
            positionals.append(arg)
        index += 1
    if pattern_needed and not pattern_given and positionals:
        positionals = positionals[1:]
    return paths + positionals


def search_roots(words):
    """The search roots of one simple command, or [] when it is not a search."""
    words = _strip_wrappers(words)
    if not words:
        return []
    name, args = os.path.basename(words[0]), words[1:]
    if name in ("find", "bfs"):
        return _find_roots(args)
    if name in ("fd", "fdfind"):
        return _positional_roots(args, FD_VALUE, FD_PATH_VALUE, set())
    if name == "rg":
        listing = "--files" in args
        return _positional_roots(args, RG_VALUE, set(), RG_PATTERN_VALUE,
                                 pattern_needed=not listing)
    if name in ("grep", "egrep", "fgrep"):
        recursive = any(arg in ("--recursive", "--dereference-recursive")
                        or (arg.startswith("-") and not arg.startswith("--")
                            and ("r" in arg[1:] or "R" in arg[1:]))
                        for arg in args)
        if not recursive:
            return []
        return _positional_roots(args, GREP_VALUE, set(), GREP_PATTERN_VALUE)
    return []


def refusal(payload):
    """A deny reason for this tool call, or None to allow it."""
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    home = _home()
    roots = []
    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        try:
            for words in _segments(command):
                roots.extend(search_roots(words))
        except ValueError:  # unbalanced quotes: allow rather than guess
            return None
    elif tool in ("Grep", "Glob"):
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            roots.append(path)
    broad = [root for root in roots if too_broad(root, cwd, home)]
    if not broad:
        return None
    return (f"fleet host rule: refusing a search rooted at {broad[0]!r} -- "
            "never search / or the home directory; it walks every lane and "
            "loads the shared host. Search only inside your working tree "
            f"({cwd or 'the current directory'}) or a specific subdirectory.")


def main():
    try:
        payload = json.load(sys.stdin)
        reason = refusal(payload) if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 -- a guard never blocks on its own failure
        return
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))


if __name__ == "__main__":
    main()
    sys.exit(0)
