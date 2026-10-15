#!/usr/bin/env bash
set +e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
ROUTE="$BASE/route.sh"; [[ -x "$ROUTE" ]] || ROUTE="$BASE/../route.sh"
ROOT="${AGMSG_BRIDGE_ROOT:-$HOME/Akaghef-Bridge}"
RUNTIME="${AGMSG_RUNTIME:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in --runtime) RUNTIME="${2:-}"; shift 2;; *) shift;; esac
done
if [[ -z "$RUNTIME" ]]; then
  if [[ -n "${CLAUDE_CODE:-}${CLAUDE_CODE_SESSION:-}" ]]; then RUNTIME=claude-code
  elif [[ -n "${CODEX_THREAD_ID:-}${CODEX_HOME:-}" ]]; then RUNTIME=codex
  else RUNTIME=unknown; fi
fi
# The routing hook shares the native-session membership gate with delivery.
# Project/team-map matches and presence history never authorize inbox summaries.
SKILL_DIR="$(cd "$BASE/../.." && pwd)"
[[ -r "$SKILL_DIR/scripts/lib/subscription.sh" ]] || exit 0
source "$SKILL_DIR/scripts/lib/resolve-project.sh"
source "$SKILL_DIR/scripts/lib/subscription.sh"
SESSION=""
case "$RUNTIME" in
  codex) SESSION="${CODEX_THREAD_ID:-}" ;;
  claude-code)
    INPUT=""
    [[ -t 0 ]] || INPUT="$(cat 2>/dev/null)"
    SESSION="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id", ""))
except (ValueError, TypeError): pass' 2>/dev/null)"
    [[ -n "$SESSION" ]] || SESSION="${CLAUDE_CODE_SESSION_ID:-}"
    ;;
  *) exit 0 ;;
esac
[[ -n "$SESSION" ]] || exit 0
OWNER="$SESSION"
[[ "$RUNTIME" != claude-code ]] || OWNER="$(agmsg_normalize_instance_id "$SESSION" "$RUNTIME" 2>/dev/null)"
PROJECT="$(agmsg_resolve_project "$PWD" "$RUNTIME")"
PAIRS="$(agmsg_subscription_pairs "$PROJECT" "$RUNTIME" "$OWNER" 2>/dev/null)"
[[ -n "$PAIRS" ]] || exit 0
while IFS=$'\t' read -r team agent; do
  [[ -n "$team" && -n "$agent" ]] || continue
  agmsg_role_active_matches "$team" "$agent" "$RUNTIME" "$SESSION" "$(agmsg_canonical_path "$PROJECT")" "$OWNER" || continue
  AGMSG_BRIDGE_ROOT="$ROOT" "$ROUTE" presence write "$agent" "$team" "$RUNTIME" >/dev/null 2>&1
  echo "agmsg SessionStart team=$team role=$agent"
  "$ROUTE" unread-summary "$team" "$agent" 2>/dev/null | head -20
done <<< "$PAIRS"
exit 0
