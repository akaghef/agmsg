#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export AGMSG_BRIDGE_ROOT="$TMP/Bridge"
export AGMSG_SEND_JOURNAL="$TMP/send-journal.jsonl"
export AGMSG_STATE_DIR="$TMP/state"
export AGMSG_STORAGE_PATH="$TMP/sqlite"
export AGMSG_ROUTING_ROOT="$HERE"
python3 "$HERE/tests/test_routing.py"
