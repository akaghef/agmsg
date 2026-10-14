#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
PY="$BASE/lib/routing.py"; [[ -f "$PY" ]] || PY="$BASE/agmsg-routing/lib/routing.py"
ACTION="${1:?Usage: route.sh parse|send|receive|directory|presence|watcher ...}"; shift
export AGMSG_BRIDGE_ROOT="${AGMSG_BRIDGE_ROOT:-$HOME/Akaghef-Bridge}"
case "$ACTION" in
  parse) exec python3 "$PY" parse "${1:?address required}" ;;
  receive) exec python3 "$PY" receive "${@:-list}" ;;
  directory) exec python3 "$PY" directory ;;
  presence) exec python3 "$PY" presence "$@" ;;
  watcher) exec python3 "$PY" watcher "$@" ;;
  unread-summary)
    team="${1:?team required}"; agent="${2-}"; scripts="$(dirname "$0")"
    [[ -n "$agent" ]] || agent="$team"
    source "$scripts/lib/storage.sh" 2>/dev/null || source "$(dirname "$0")/../lib/storage.sh"
    agmsg_storage_load
    rows="$(storage_list_unread "$team" "$agent" 2>/dev/null || true)"
    python3 -c 'import json,sys; rows=[json.loads(x) for x in sys.stdin if x.strip()]; print(f"unread count: {len(rows)}"); [print("unread: "+str(x.get("title",x.get("id","(untitled)")))+" — from "+str(x.get("from","unknown"))) for x in rows]' <<<"$rows"
    ;;
  send)
    addr="${1:?address required}"; from="${2:?from required}"; body="${3:?body required}"; kind="${4:-message}"
    parsed="$(python3 "$PY" parse "$addr")"
    realm="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["realm"])' <<<"$parsed")"
    team="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["team"])' <<<"$parsed")"
    to="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["agent"])' <<<"$parsed")"
    python3 "$PY" validate-kind "$realm" "$kind"
    if [[ "$realm" == local || "$realm" == mac ]]; then exec "$(dirname "$0")/send.sh" "$team" "$from" "$to" "$body" --force; fi
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"; id="$stamp-$from-$$"
    packet="${TMPDIR:-/tmp}/agmsg-$id.json"
    python3 - "$packet" "$id" "$realm" "$team" "$from" "$to" "$kind" "$body" <<'PY'
import datetime,json,sys
f,i,r,t,fr,to,k,b=sys.argv[1:]
json.dump({"schema":"agmsg.message.v2","id":i,"realm":r,"team":t,"from":fr,"to":to,"kind":k,"reply_to":"","thread":"","created_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"body":b,"status":"queued"},open(f,"w"))
PY
    case "$realm" in
      mac) target="$AGMSG_BRIDGE_ROOT/inbox/mac" ;;
      win) target="$AGMSG_BRIDGE_ROOT/pending/mac_to_windows" ;;
      mini) target="$AGMSG_BRIDGE_ROOT/inbox/mini" ;;
      personal) target="$AGMSG_BRIDGE_ROOT/inbox/mac";;
      team)
        [[ "$kind" == notice* ]] || { rm -f "$packet"; exit 2; }
        target="$AGMSG_BRIDGE_ROOT/inbox/mini"; mkdir -p "$target"; cp "$packet" "$target/$id.json"
        "$(dirname "$0")/adapters/drive.sh" send-packet "$packet" || { rm -f "$packet"; exit 20; }
        rm -f "$packet"; echo "status=queued realm=team team=$team to=$to targets=mini,drive"; exit 0 ;;
    esac
    [[ "$realm" != personal || "$kind" == notice* ]] || { rm -f "$packet"; echo "personal realm supports notice.* only" >&2; exit 2; }
    mkdir -p "$target"; cp "$packet" "$target/$id.json"
    if [[ "$realm" == personal ]]; then mkdir -p "$AGMSG_BRIDGE_ROOT/pending/mac_to_windows"; cp "$packet" "$AGMSG_BRIDGE_ROOT/pending/mac_to_windows/$id.json"; fi
    rm -f "$packet"; echo "status=queued realm=$realm team=$team to=$to path=$target/$id.json" ;;
  *)
    LEGACY="$BASE/legacy/route-legacy.sh"
    [[ -x "$LEGACY" ]] || LEGACY="$BASE/agmsg-routing/legacy/route-legacy.sh"
    [[ -x "$LEGACY" ]] || { echo "legacy route unavailable for action: $ACTION" >&2; exit 2; }
    exec "$LEGACY" "$ACTION" "$@" ;;
esac
