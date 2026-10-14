#!/usr/bin/env bash
set -euo pipefail

# Common application-layer router.
# Address: <realm>:<team>/<agent>; bare <team>/<agent> defaults to local.

ACTION="${1:?Usage: route.sh send|send-packet|send-file|receipt|mark|inbox|health|wait|archive ...}"
shift
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

parse_address() {
  local raw="$1" rest
  if [[ "$raw" == *:* ]]; then REALM="${raw%%:*}"; rest="${raw#*:}"; else REALM=local; rest="$raw"; fi
  [[ "$rest" == */* ]] || { echo "agmsg: address must be <realm>:<team>/<agent>: $raw" >&2; exit 2; }
  TEAM="${rest%%/*}"; AGENT="${rest#*/}"
  case "$REALM" in local|personal|team) ;; *) echo "agmsg: unsupported realm: $REALM" >&2; exit 2 ;; esac
  [ -n "$TEAM" ] && [ -n "$AGENT" ] || { echo "agmsg: empty team or agent in address" >&2; exit 2; }
}

packet_from_message() {
  local address="$1" from="$2" body="$3" thread="${4:-}" kind="${5:-message}" reply_to="${6:-}"
  local id stamp tmp q_id q_realm q_team q_from q_to q_thread q_kind q_reply q_body
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"; id="$stamp-$from-$$-${RANDOM:-0}"
  tmp="${TMPDIR:-/tmp}/agmsg-$id.json"
  q_id=$(printf '%s' "$id" | sed "s/'/''/g"); q_realm=$(printf '%s' "$REALM" | sed "s/'/''/g")
  q_team=$(printf '%s' "$TEAM" | sed "s/'/''/g"); q_from=$(printf '%s' "$from" | sed "s/'/''/g")
  q_to=$(printf '%s' "$AGENT" | sed "s/'/''/g"); q_thread=$(printf '%s' "$thread" | sed "s/'/''/g")
  q_kind=$(printf '%s' "$kind" | sed "s/'/''/g"); q_reply=$(printf '%s' "$reply_to" | sed "s/'/''/g")
  q_body=$(printf '%s' "$body" | sed "s/'/''/g")
  sqlite3 :memory: "SELECT json_object('schema','agmsg.message.v2','id','$q_id','realm','$q_realm','team','$q_team','thread','$q_thread','from','$q_from','to','$q_to','kind','$q_kind','reply_to','$q_reply','created_at_utc',strftime('%Y-%m-%dT%H:%M:%SZ','now'),'body','$q_body','status','queued');" > "$tmp"
  echo "$tmp"
}

address="${1:?$ACTION requires address}"
shift
parse_address "$address"

case "$ACTION" in
  send)
    from="${1:?send requires from agent}"; body="${2:?send requires message}"; thread="${3:-}"; kind="${4:-message}"; reply_to="${5:-}"
    if [ "$REALM" = local ]; then
      exec "$SCRIPT_DIR/send.sh" "$TEAM" "$from" "$AGENT" "$body" local "$thread" "$kind" "$reply_to"
    fi
    packet="$(packet_from_message "$address" "$from" "$body" "$thread" "$kind" "$reply_to")"
    trap 'rm -f "$packet"' EXIT
    if [ "$REALM" = personal ]; then "$SCRIPT_DIR/adapters/bridge.sh" send-packet "$AGENT" "$packet"
    else "$SCRIPT_DIR/adapters/drive.sh" send-packet "$packet"; fi
    ;;
  send-packet)
    packet="${1:?send-packet requires JSON packet path}"
    case "$REALM" in
      personal) exec "$SCRIPT_DIR/adapters/bridge.sh" send-packet "$AGENT" "$packet" ;;
      team) exec "$SCRIPT_DIR/adapters/drive.sh" send-packet "$packet" ;;
      local) echo "agmsg: local send-packet is not supported; use send" >&2; exit 2 ;;
    esac
    ;;
  send-file)
    source_file="${1:?send-file requires source path}"
    case "$REALM" in
      personal) exec "$SCRIPT_DIR/adapters/bridge.sh" send-file "$AGENT" "$source_file" ;;
      team) exec "$SCRIPT_DIR/adapters/drive.sh" send-file "$source_file" ;;
      local) echo "agmsg: local realm does not need file transport" >&2; exit 2 ;;
    esac
    ;;
  receipt)
    from="${1:?receipt requires from agent}"; reply_to="${2:?receipt requires message id}"; receipt_status="${3:?receipt requires status}"; summary="${4:-}"
    case "$receipt_status" in delivered|read|handled|failed) ;; *) echo "agmsg: invalid receipt status" >&2; exit 2 ;; esac
    exec "$0" send "$address" "$from" "$summary" "receipt-$reply_to" "receipt.$receipt_status" "$reply_to"
    ;;
  mark)
    [ "$REALM" = local ] || { echo "agmsg: mark is local-only; send a receipt for remote realms" >&2; exit 2; }
    exec "$SCRIPT_DIR/status.sh" "${1:?mark requires message id}" "${2:?mark requires handled|failed}"
    ;;
  inbox)
    case "$REALM" in
      local) exec "$SCRIPT_DIR/inbox.sh" "$TEAM" "$AGENT" "${1:-}" ;;
      personal) exec "$SCRIPT_DIR/adapters/bridge.sh" inbox "$AGENT" "${1:-}" ;;
      team) exec "$SCRIPT_DIR/adapters/drive.sh" inbox ;;
    esac
    ;;
  health)
    case "$REALM" in
      local) "$SCRIPT_DIR/init-db.sh" >/dev/null; echo "status=available realm=local team=$TEAM" ;;
      personal) exec "$SCRIPT_DIR/adapters/bridge.sh" health "$AGENT" ;;
      team) exec "$SCRIPT_DIR/adapters/drive.sh" health ;;
    esac
    ;;
  wait)
    [ "$REALM" = personal ] || { echo "agmsg: wait currently requires personal realm" >&2; exit 2; }
    exec "$SCRIPT_DIR/adapters/bridge.sh" wait "$AGENT" "${1:?wait requires field}" "${2:?wait requires value}" "${3:-180}"
    ;;
  archive)
    [ "$REALM" = personal ] || { echo "agmsg: archive currently requires personal realm" >&2; exit 2; }
    exec "$SCRIPT_DIR/adapters/bridge.sh" archive "$AGENT" "${1:?archive requires packet}" "${2:-done}"
    ;;
  *) echo "agmsg: unknown route action: $ACTION" >&2; exit 2 ;;
esac
