#!/usr/bin/env bash
# Device heartbeat: rewrite presence/mac.json with the roles whose explicit
# membership (role-active record + actas lock) is held by a live session.
# The watcher runs this on every tick; the SessionStart hook after a join.
set +e
BASE="$(cd "$(dirname "$0")" && pwd)"
ROUTE="$BASE/route.sh"; [[ -x "$ROUTE" ]] || ROUTE="$BASE/../route.sh"
SKILL_DIR="${AGMSG_SKILL_DIR:-$(cd "$BASE/../.." && pwd)}"
agents=""; teams=""; runtimes=""
if [[ -r "$SKILL_DIR/scripts/lib/subscription.sh" ]]; then
  source "$SKILL_DIR/scripts/lib/subscription.sh"
  for f in "$SKILL_DIR/run"/role-active.*; do
    [[ -f "$f" ]] || continue
    team="$(sed -n 's/^team=//p' "$f" | head -1)"; agent="$(sed -n 's/^agent=//p' "$f" | head -1)"
    [[ -n "$team" && -n "$agent" ]] || continue
    agmsg_role_active_load "$team" "$agent"
    [[ -n "$AGMSG_ROLE_ACTIVE_OWNER" ]] && actas_lock_sid_alive "$AGMSG_ROLE_ACTIVE_OWNER" || continue
    agents+="${agents:+,}$agent"; teams+="${teams:+,}$team"; runtimes+="${runtimes:+,}$AGMSG_ROLE_ACTIVE_TYPE"
  done
fi
exec "$ROUTE" presence write "$agents" "$teams" "$runtimes"
