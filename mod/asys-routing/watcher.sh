#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ROUTE="$BASE/route.sh"; [[ -x "$ROUTE" ]] || ROUTE="$BASE/../route.sh"
exec "$ROUTE" watcher
