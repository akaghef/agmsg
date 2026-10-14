#!/usr/bin/env bash
set -euo pipefail

# File-queue adapter for the explicitly selected private team realm.

ACTION="${1:?Usage: drive.sh health|send-packet|send-file|inbox ...}"
shift
ROOT="${AGMSG_DRIVE_ROOT:-}"
[ -n "$ROOT" ] || { echo "agmsg drive: set AGMSG_DRIVE_ROOT to the mounted Akaghef-Ops root" >&2; exit 20; }
QUEUE="$ROOT/queues/team_agmsg"

case "$ACTION" in
  health)
    [ -d "$ROOT" ] || { echo "status=failed reason=drive_root_missing root=$ROOT"; exit 20; }
    echo "status=available realm=team root=$ROOT"
    ;;
  send-packet)
    packet="${1:?send-packet requires JSON packet path}"
    escaped=$(printf '%s' "$packet" | sed "s/'/''/g")
    [ -f "$packet" ] && [ "$(sqlite3 :memory: "SELECT json_valid(CAST(readfile('$escaped') AS TEXT));")" = 1 ] || { echo "agmsg drive: invalid packet" >&2; exit 2; }
    mkdir -p "$QUEUE"
    base="$(basename "$packet")"; case "$base" in *.json) ;; *) base="$base.json" ;; esac
    tmp="$QUEUE/.$base.$$.$RANDOM.tmp"
    cp "$packet" "$tmp"; mv "$tmp" "$QUEUE/$base"
    echo "status=queued realm=team path=$QUEUE/$base"
    ;;
  send-file)
    source_file="${1:?send-file requires source path}"
    [ -f "$source_file" ] || { echo "agmsg drive: file not found" >&2; exit 2; }
    mkdir -p "$QUEUE/attachments"
    base="$(basename "$source_file")"; tmp="$QUEUE/attachments/.$base.$$.$RANDOM.tmp"
    cp "$source_file" "$tmp"; mv "$tmp" "$QUEUE/attachments/$base"
    echo "status=queued realm=team attachment=$QUEUE/attachments/$base"
    ;;
  inbox)
    [ -d "$QUEUE" ] || { echo "No team messages."; exit 0; }
    find "$QUEUE" -maxdepth 1 -type f -name '*.json' -print | sort
    ;;
  *) echo "agmsg drive: unknown action: $ACTION" >&2; exit 2 ;;
esac
