#!/bin/sh
# Prepare the throwaway demo used by docs/demo/demo.tape.
#
#   sh docs/demo/setup.sh prepare   create /tmp/demo/acme-app (empty git repo) and a `fleet` shim
#   sh docs/demo/setup.sh seed      add two fictional lanes to the demo home's registry
#
# Nothing here starts a model session or spends quota: the lanes are registry
# records only, so the recording shows read-only and message verbs.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DEMO=/tmp/demo
APP=$DEMO/acme-app

case "${1:-}" in
prepare)
    rm -rf "$DEMO"
    mkdir -p "$DEMO/bin" "$APP"
    git -C "$APP" init -q
    # `fleet msg` needs an explicit home; the shim supplies it after `init`.
    cat > "$DEMO/bin/fleet" <<SHIM
#!/bin/sh
if [ "\${1:-}" = init ]; then exec python3 "$ROOT/bin/fleet.py" "\$@"; fi
exec python3 "$ROOT/bin/fleet.py" --fleet-home "$APP" "\$@"
SHIM
    printf '#!/bin/sh\nexec sh "%s/docs/demo/setup.sh" seed\n' "$ROOT" > "$DEMO/bin/demo-seed"
    chmod +x "$DEMO/bin/fleet" "$DEMO/bin/demo-seed"
    ;;
seed)
    python3 - "$APP/state/fleet.json" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
def rec(turns, cost, minutes, sid):
    ago = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"status": "running", "turns": turns, "cost_usd": cost, "session_id": sid,
            "cwd": "/tmp/demo/acme-app-lanes", "last_activity": ago}
workers = {
    "docs-fix": rec(7, 0.84, 1, "00000000-0000-4000-8000-000000000001"),
    "api-retry": rec(12, 1.37, 3, "00000000-0000-4000-8000-000000000002"),
}
json.dump({"workers": workers}, open(sys.argv[1], "w"), indent=2)
PY
    "$DEMO/bin/fleet" msg init --site acme >/dev/null
    ;;
*)
    echo "usage: setup.sh prepare|seed" >&2
    exit 2
    ;;
esac
