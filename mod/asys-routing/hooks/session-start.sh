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
TEAM=triage
TEAM="$(python3 - "$BASE/team-map.yaml" "$PWD" 2>/dev/null <<'PY'
import os,sys
p=os.path.realpath(sys.argv[2]); t='triage'; rules=[]; path=None
for l in open(sys.argv[1]):
 s=l.strip()
 if s.startswith('- path: '): path=os.path.realpath(os.path.expanduser(s[8:]))
 elif s.startswith('team: ') and path and (p==path or p.startswith(path+os.sep)): t=s[6:]
print(t)
PY
)"
PRESENCE_TEAM="$TEAM"; [[ "$TEAM" == triage ]] && PRESENCE_TEAM=""
AGMSG_BRIDGE_ROOT="$ROOT" "$ROUTE" presence write "${AGMSG_AGENT_ID:-}" "$PRESENCE_TEAM" "$RUNTIME" >/dev/null 2>&1
echo "agmsg SessionStart team=$TEAM"
"$ROUTE" unread-summary "$TEAM" "${AGMSG_AGENT_ID:-}" 2>/dev/null | head -20
AGMSG_BRIDGE_ROOT="$ROOT" "$ROUTE" receive list 2>/dev/null | awk -F '\t' '$2=="triage" && $5=="delivered=False" {n++} END {print "triage count: " n+0}'
AGMSG_BRIDGE_ROOT="$ROOT" "$ROUTE" directory 2>/dev/null | head -10
exit 0
