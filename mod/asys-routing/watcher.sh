#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ROUTE="$BASE/route.sh"; [[ -x "$ROUTE" ]] || ROUTE="$BASE/../route.sh"
# A failed heartbeat must not stop packet ingestion.
"$BASE/presence.sh" >/dev/null || echo "agmsg-routing: presence refresh failed" >&2
exec "$ROUTE" watcher
