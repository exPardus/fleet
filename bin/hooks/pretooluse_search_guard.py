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

The same hook refuses hand-rolled wait loops: a `while`/`until` loop that
polls `pgrep`, `pidof` or `ps` and sleeps, the shape lanes used to wait for
"no other pytest/buf run" before starting their own. On a shared box some
test run is nearly always alive, so such a loop starved reviewer lanes for
hours. The refusal names the replacement, `fleet exclusive`, which waits a
capped time on a lock that names its holder. A single `pgrep` with no loop is
allowed. Loops inside `sh -c`, and inside a small script run by path
(`bash wait.sh`, `./wait.sh`, `source wait.sh`), are found too.
"""
import json
import os
import re
import shlex
import sys

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", "\n"}
WRAPPERS = {"sudo", "time", "nice", "nohup", "command", "exec", "env",
            "ionice", "stdbuf", "builtin", "timeout"}
# Wrapper options that take a separate value, so the value is not mistaken
# for the wrapped command.
WRAPPER_VALUE = {
    "sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D"},
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"},
    "stdbuf": {"-i", "-o", "-e"}, "env": {"-u", "-C", "-S"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
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
            "--engine", "--ignore-file", "--hyperlink-format"}
RG_PATTERN_VALUE = {"-e", "--regexp", "-f", "--file"}
GREP_VALUE = {"-m", "--max-count", "-A", "--after-context", "-B",
              "--before-context", "-C", "--context", "-d", "--directories",
              "-D", "--devices", "--label", "--color", "--colour", "--include",
              "--exclude", "--exclude-dir", "--exclude-from", "--binary-files"}
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


def _strip_heredocs(command):
    """Drop heredoc bodies: they are data, not commands."""
    kept, closing = [], []
    for line in command.split("\n"):
        if closing:
            delimiter, strip_tabs = closing[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                closing.pop(0)
            continue
        kept.append(line)
        closing.extend((m.group(3), m.group(1) == "-")
                       for m in HEREDOC.finditer(line))
    return "\n".join(kept)


def _segments(command):
    lexer = shlex.shlex(_strip_heredocs(command), posix=True,
                        punctuation_chars=";&|()\n")
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"  # a newline separates commands
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
        name = os.path.basename(word)
        if "=" in word and not word.startswith("-") and word.split("=")[0].isidentifier():
            index += 1
        elif name in WRAPPERS:
            index += 1
            values = WRAPPER_VALUE.get(name, set())
            while index < len(words) and words[index].startswith("-"):
                index += 2 if words[index] in values else 1
            if name == "timeout":
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
    """The search roots of one simple command, or [] when it is not a search.

    A search with no explicit root searches its working directory: `.`.
    """
    roots = _explicit_roots(words)
    return roots if roots is None or roots else ["."]


def _explicit_roots(words):
    words = _strip_wrappers(words)
    if not words:
        return None
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
        recursive = any(
            arg in ("--recursive", "--dereference-recursive",
                    "--directories=recurse", "-drecurse")
            or (arg in ("-d", "--directories") and index + 1 < len(args)
                and args[index + 1] == "recurse")
            or (arg.startswith("-") and not arg.startswith("--")
                and not arg.startswith("-d")
                and ("r" in arg[1:] or "R" in arg[1:]))
            for index, arg in enumerate(args))
        if not recursive:
            return None
        return _positional_roots(args, GREP_VALUE, set(), GREP_PATTERN_VALUE)
    return None


def command_roots(command, cwd, home, depth=0):
    """(root, cwd) pairs for every search in a Bash command.

    `cd` and `pushd` move the cwd for the segments after them, so
    `cd / && find .` is judged at `/`. `sh -c '...'` and its siblings are
    parsed recursively. Raises ValueError on unbalanced quotes.
    """
    roots = []
    for words in _segments(command):
        words = _strip_wrappers(words)
        if not words:
            continue
        name, args = os.path.basename(words[0]), words[1:]
        if name in ("cd", "pushd"):
            targets = [a for a in args if a == "-" or not a.startswith("-")]
            if not targets:
                cwd = home if name == "cd" else cwd
            elif targets[0] != "-":
                cwd = _expand(targets[0], cwd, home)
            continue
        if name in SHELLS and "-c" in args and depth < 3:
            index = args.index("-c")
            if index + 1 < len(args):
                roots.extend(command_roots(args[index + 1], cwd, home, depth + 1))
            continue
        roots.extend((root, cwd) for root in search_roots(words) or [])
    return roots


PROCESS_POLLERS = {"pgrep", "pidof", "ps"}
LOOP_KEYWORDS = {"{", "}", "!", "then", "else", "elif", "do", "time"}
SCRIPT_MAX_BYTES = 64 * 1024


def _lead(words):
    index = 0
    while index < len(words) and words[index] in LOOP_KEYWORDS:
        index += 1
    return words[index:]


def _script_path(words, cwd):
    """The script a segment runs by path, if it is a small local file."""
    name, args = os.path.basename(words[0]), words[1:]
    if name in SHELLS:
        args = [a for a in args if not a.startswith("-")]
        target = args[0] if args else None
    elif name in ("source", "."):
        target = args[0] if args else None
    elif words[0].endswith(".sh") or words[0].startswith("./"):
        target = words[0]
    else:
        return None
    if not target:
        return None
    path = target if os.path.isabs(target) else os.path.join(cwd or os.getcwd(), target)
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= SCRIPT_MAX_BYTES:
            return path
    except OSError:
        return None
    return None


def wait_loop(command, cwd=None, depth=0):
    """True when the command polls for a process in a sleeping loop."""
    segments = [_strip_wrappers(words) for words in _segments(command)]
    loop = None  # words seen since the open `while`/`until`
    for raw in segments:
        words = _lead(raw)
        if raw and raw[0] == "done" and loop is not None:
            names = {os.path.basename(w) for w in loop}
            if names & PROCESS_POLLERS and "sleep" in names:
                return True
            loop = None
            continue
        if words and words[0] in ("while", "until") and loop is None:
            loop = list(words[1:])
            continue
        if loop is not None:
            loop.extend(_lead(raw))
            continue
        if not words or depth >= 3:
            continue
        name, args = os.path.basename(words[0]), words[1:]
        if name in SHELLS and "-c" in args:
            index = args.index("-c")
            if index + 1 < len(args) and wait_loop(args[index + 1], cwd, depth + 1):
                return True
            continue
        script = _script_path(words, cwd)
        if script:
            try:
                with open(script, encoding="utf-8", errors="replace") as stream:
                    if wait_loop(stream.read(), cwd, depth + 1):
                        return True
            except (OSError, ValueError):
                pass
    return False


WAIT_LOOP_REASON = (
    "fleet host rule: refusing a wait loop that polls pgrep/pidof/ps and "
    "sleeps -- on a shared box some test run is nearly always alive, so this "
    "can wait for hours. Run the command under the box-wide lock instead: "
    "`fleet exclusive --label <lane> -- <cmd>` (waits at most 30 minutes, "
    "names the holder, takes over a dead one).")


def _glob_root(pattern):
    """The literal directory an absolute Glob pattern starts from."""
    if not isinstance(pattern, str) or not pattern.startswith(("/", "~")):
        return None
    prefix = re.split(r"[*?\[{]", pattern, maxsplit=1)[0]
    if prefix in ("~", "~/"):
        return "~"
    return prefix if prefix.endswith("/") else os.path.dirname(prefix) or "/"


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
            if wait_loop(command, cwd):
                return WAIT_LOOP_REASON
            roots = command_roots(command, cwd, home)
        except ValueError:  # unbalanced quotes: allow rather than guess
            return None
    elif tool in ("Grep", "Glob"):
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            roots.append((path, cwd))
        elif tool == "Glob":
            root = _glob_root(tool_input.get("pattern"))
            if root:
                roots.append((root, cwd))
    broad = [root for root, at in roots if too_broad(root, at, home)]
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
