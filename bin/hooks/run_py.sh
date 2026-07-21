#!/bin/sh
# Locate a Python >= 3.10 and exec the given script with it.
#
# Plugin hook commands are a single string run through a shell (Git Bash `sh`
# on Windows, /bin/sh elsewhere), so they cannot branch on OS. Hardcoding
# `py -3.13` breaks every non-Windows collaborator; hardcoding `python3`
# breaks Windows, where `python` may be an old 3.10 and the launcher `py` is
# the only reliable entry point. This shim is the one place that resolves it.
#
# Honors $FLEET_PYTHON as an explicit override.
set -e

script="$1"
shift || true

if [ -n "$FLEET_PYTHON" ]; then
    # Two legitimate override shapes, and they need opposite quoting:
    #   * a PATH to an interpreter, which on Windows very often contains a
    #     space (`C:\Program Files\Python310\python.exe`) and must be quoted;
    #   * a multi-word COMMAND (`py -3.13`), which must be word-split.
    # Unquoted-always was the old behaviour: it word-split the spaced path
    # into `C:\Program`, `exec` failed, and under `set -e` the shim exited
    # NONZERO with no output -- a hook breaking the session, invariant 2,
    # and silently. `-x` discriminates exactly: a real executable file takes
    # the quoted branch, anything else (including `py -3.13`) keeps the
    # word-split one.
    if [ -x "$FLEET_PYTHON" ]; then
        exec "$FLEET_PYTHON" "$script" "$@"
    fi
    exec $FLEET_PYTHON "$script" "$@"
fi

# `py -3.13` first: on Windows a bare `python` can be an older interpreter.
if command -v py >/dev/null 2>&1 && py -3.13 -c "" >/dev/null 2>&1; then
    exec py -3.13 "$script" "$@"
fi

for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
        exec "$candidate" "$script" "$@"
    fi
done

# No usable interpreter. A hook must never break the session: say nothing,
# exit 0 (invariant 2).
exit 0
