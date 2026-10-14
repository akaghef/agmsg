#!/usr/bin/env bash
set -euo pipefail
ROOT="${AGMSG_BRIDGE_ROOT:-$HOME/Akaghef-Bridge}"
ACTION="${1:?inbox|send-packet|receive}"; shift
case "$ACTION" in
 inbox) exec "$(dirname "$0")/../route.sh" receive list ;;
 receive) exec "$(dirname "$0")/../route.sh" receive "$@" ;;
 send-packet)
   dest="${1:?device required}"; packet="${2:?packet required}"
   case "$dest" in mac) out="$ROOT/inbox/mac";; win|dell|windows) out="$ROOT/pending/mac_to_windows";; mini) out="$ROOT/inbox/mini";; *) echo "unknown device: $dest" >&2; exit 2;; esac
   python3 -m json.tool "$packet" >/dev/null; mkdir -p "$out"; cp "$packet" "$out/$(basename "$packet")"; echo "status=queued path=$out/$(basename "$packet")";;
 *) echo "unsupported bridge action: $ACTION" >&2; exit 2;;
esac
