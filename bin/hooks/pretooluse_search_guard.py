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

The same hook refuses hand-rolled wait loops in Bash and Monitor commands: a
`while`/`until`/`for` loop that polls `pgrep`, `pidof` or `ps` and sleeps, the
shape lanes used to wait for "no other pytest/buf run" before starting their
own. On a shared box some test run is nearly always alive, so such a loop
starved reviewer lanes for hours. The refusal names the replacement,
`fleet exclusive`, which waits a capped time on a lock that names its holder.
A poller counts only as a command word (so `docker ps` is not one), or as a
shell function whose body polls. A single `pgrep` with no loop is allowed.
Loops behind detaching wrappers (`nohup`, `setsid`, `systemd-run`), inside
`sh -c`, in a heredoc fed to a shell, and inside a small script run by path
(`bash $CLAUDE_JOB_DIR/tmp/wait.sh`, `./wait.sh`, `source wait.sh`) are found
too.
"""
import json
import os
import re
import shlex
import sys

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", "\n"}
WRAPPERS = {"sudo", "time", "nice", "nohup", "command", "exec", "env",
            "ionice", "stdbuf", "builtin", "timeout", "setsid", "systemd-run",
            "daemonize"}
# Wrapper options that take a separate value, so the value is not mistaken
# for the wrapped command.
WRAPPER_VALUE = {
    "sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D"},
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"},
    "stdbuf": {"-i", "-o", "-e"}, "env": {"-u", "-C", "-S"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "systemd-run": {"-p", "--property", "-u", "--unit", "--description",
                    "--slice", "-E", "--setenv", "--uid", "--gid", "--nice",
                    "--working-directory", "-M", "--machine", "-H", "--host",
                    "--on-active", "--on-boot", "--on-startup",
                    "--on-unit-active", "--on-unit-inactive", "--on-calendar",
                    "--timer-property", "--path-property", "--socket-property",
                    "--service-type", "--wait-for"},
    "daemonize": {"-a", "-c", "-e", "-o", "-p", "-l", "-u", "-E"},
}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
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
LOOP_OPENERS = {"while", "until", "for"}
# Words that may precede the command word of a segment inside a loop.
LEAD_WORDS = {"{", "}", "!", "then", "else", "elif", "do", "time", "if",
              "while", "until"}
SCRIPT_MAX_BYTES = 64 * 1024
SUBSTITUTION = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)|`([^`]*)`")
FUNCTION_HEAD = re.compile(
    r"(?:^|[;&|\n{(])\s*(?:function\s+([A-Za-z_][\w-]*)\s*(?:\(\s*\))?"
    r"|([A-Za-z_][\w-]*)\s*\(\s*\))\s*\{")


def _core(words, lead=LEAD_WORDS):
    """A segment's words from its command word on: past keywords and wrappers."""
    while True:
        index = 0
        while index < len(words) and words[index] in lead:
            index += 1
        stripped = _strip_wrappers(words[index:])
        if stripped == words:
            return words
        words = stripped


def _command_word(words):
    """The command a segment runs, as a basename."""
    words = _core(words)
    return os.path.basename(words[0]) if words else None


def _loop_opener(words):
    """`while`, `until` or `for` when the segment opens a loop."""
    words = _core(words, LEAD_WORDS - LOOP_OPENERS)
    return words[0] if words and words[0] in LOOP_OPENERS else None


def _shell_c_body(words):
    """The string a `sh -c BODY` (or `bash -lc BODY`) segment runs."""
    if not words or os.path.basename(words[0]) not in SHELLS:
        return None
    for index, word in enumerate(words[1:], start=1):
        if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word):
            return words[index + 1] if index + 1 < len(words) else None
    return None


def _script_path(words, cwd):
    """The script a segment runs by path, if it is a small local file.

    `$VAR` and `~` are expanded from the hook's environment, which is the
    session's: lanes keep scratch scripts under `$CLAUDE_JOB_DIR/tmp`."""
    name, args = os.path.basename(words[0]), words[1:]
    if name in SHELLS:
        args = [a for a in args if not a.startswith("-")]
        target = args[0] if args else None
    elif name in ("source", "."):
        target = args[0] if args else None
    elif words[0].endswith(".sh") or words[0].startswith(("./", "../", "$", "~")):
        target = words[0]
    else:
        return None
    if not target:
        return None
    target = os.path.expanduser(os.path.expandvars(target))
    path = target if os.path.isabs(target) else os.path.join(cwd or os.getcwd(), target)
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= SCRIPT_MAX_BYTES:
            return path
    except OSError:
        return None
    return None


def _function_bodies(command):
    """{name: body} for every shell function defined in the text."""
    bodies = {}
    for match in FUNCTION_HEAD.finditer(command):
        name = match.group(1) or match.group(2)
        depth, index = 1, match.end()
        while index < len(command) and depth:
            depth += {"{": 1, "}": -1}.get(command[index], 0)
            index += 1
        bodies[name] = command[match.end():index - 1]
    return bodies


def _segment_commands(words, pollers):
    """Command words a loop segment runs, including `$(...)` and backticks."""
    found = {_command_word(words)}
    for word in words:
        for match in SUBSTITUTION.finditer(word):
            inner = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                for inner_words in _segments(inner):
                    found |= _segment_commands(inner_words, pollers)
            except ValueError:
                pass
    return found


def _poller_functions(command):
    """Names of shell functions whose bodies call a process poller."""
    bodies = _function_bodies(command)
    pollers = set(PROCESS_POLLERS)
    changed = True
    while changed:  # a function may poll through another function
        changed = False
        for name, body in bodies.items():
            if name in pollers:
                continue
            try:
                words = set()
                for segment in _segments(body):
                    words |= _segment_commands(segment, pollers)
            except ValueError:
                continue
            if words & pollers:
                pollers.add(name)
                changed = True
    return pollers


def _heredoc_shell_bodies(command):
    """Bodies of heredocs fed to a shell (`bash <<EOF`, `cat <<EOF | sh`)."""
    bodies, lines, index = [], command.split("\n"), 0
    while index < len(lines):
        line = lines[index]
        index += 1
        heads = list(HEREDOC.finditer(line))
        if not heads:
            continue
        try:
            feeds_shell = any(_command_word(words) in SHELLS
                              for words in _segments(HEREDOC.sub(" ", line)))
        except ValueError:
            feeds_shell = False
        for head in heads:
            body = []
            while index < len(lines):
                text = lines[index].lstrip("\t") if head.group(1) else lines[index]
                index += 1
                if text == head.group(3):
                    break
                body.append(lines[index - 1])
            if feeds_shell:
                bodies.append("\n".join(body))
    return bodies


def wait_loop(command, cwd=None, depth=0, pollers=None):
    """True when the command polls for a process in a sleeping loop.

    A poller counts only as the command word of a segment (or of a `$(...)`
    inside one), so `docker ps` or a variable named `ps` is not a poller. A
    shell function whose body polls counts as a poller where it is called."""
    pollers = set(pollers or ()) | _poller_functions(command)
    if depth < 3:
        for body in _heredoc_shell_bodies(command):
            if wait_loop(body, cwd, depth + 1, pollers):
                return True
    nesting, seen = 0, set()
    for words in _segments(command):
        opener = _loop_opener(words)
        if nesting:
            seen |= _segment_commands(words, pollers)
            if words and words[0] == "done":
                nesting -= 1
                if not nesting:
                    if seen & pollers and "sleep" in seen:
                        return True
                    seen = set()
                continue
            if opener:
                nesting += 1
            continue
        if opener:
            nesting, seen = 1, _segment_commands(words, pollers)
            continue
        words = _core(words)
        if not words or depth >= 3:
            continue
        body = _shell_c_body(words)
        if body is not None:
            if wait_loop(body, cwd, depth + 1, pollers):
                return True
            continue
        script = _script_path(words, cwd)
        if script:
            try:
                with open(script, encoding="utf-8", errors="replace") as stream:
                    if wait_loop(stream.read(), cwd, depth + 1, pollers):
                        return True
            except (OSError, ValueError):
                pass
    return bool(nesting and seen & pollers and "sleep" in seen)


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
    if tool in ("Bash", "Monitor"):
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
