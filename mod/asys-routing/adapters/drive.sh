#!/usr/bin/env bash
set -euo pipefail
ACTION="${1:?Usage: drive.sh health|send-packet|send-file|inbox ...}"; shift
ROOT="${AGMSG_DRIVE_ROOT:-}"
[ -n "$ROOT" ] || { echo "agmsg drive: set AGMSG_DRIVE_ROOT to the mounted Akaghef-Ops root" >&2; exit 20; }
QUEUE="$ROOT/queues/team_agmsg"
case "$ACTION" in
 health) [ -d "$ROOT" ] || { echo "status=failed reason=drive_root_missing root=$ROOT"; exit 20; }; echo "status=available realm=team root=$ROOT" ;;
 send-packet)
   packet="${1:?send-packet requires JSON packet path}"
   python3 -m json.tool "$packet" >/dev/null || { echo "agmsg drive: invalid packet" >&2; exit 2; }
   kind="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("kind",""))' "$packet")"
   [[ "$kind" == notice* ]] || { echo "agmsg drive: group realm supports notice.* only" >&2; exit 2; }
   mkdir -p "$QUEUE"; base="$(basename "$packet")"; tmp="$QUEUE/.$base.$$.$RANDOM.tmp"; cp "$packet" "$tmp"; mv "$tmp" "$QUEUE/$base"; echo "status=queued realm=team path=$QUEUE/$base" ;;
 send-file) echo "agmsg drive: send-file is not a notice operation" >&2; exit 2 ;;
 inbox) [ -d "$QUEUE" ] && find "$QUEUE" -maxdepth 1 -type f -name '*.json' -print | sort || echo "No team messages." ;;
 *) echo "agmsg drive: unknown action: $ACTION" >&2; exit 2 ;;
esac
