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
