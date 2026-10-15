#!/usr/bin/env bash
set -euo pipefail

# Print identities this bridge may read right now. This deliberately resolves
# locks at read time: a role may be claimed by another session after the bridge
# armed its watcher, and inbox.sh would otherwise mark that role's rows read.
PROJECT="${1:?project required}"
TYPE="${2:?type required}"
shift 2
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
source "$SCRIPT_DIR/../../../lib/actas-lock.sh"
source "$SCRIPT_DIR/../../../lib/resolve-project.sh"
source "$SCRIPT_DIR/../../../lib/subscription.sh"

requested=""
session="${CODEX_THREAD_ID:-}"
binding_only=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pair) requested="${requested:+$requested$'\n'}${2:?pair required}"; shift 2 ;;
    --session) session="${2:-}"; shift 2 ;;
    --binding-only) binding_only=1; shift ;;
    *) echo "eligible-pairs: unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ "$binding_only" = 1 ]; then
  # The bridge resolved its registered identities at startup. Its hot guards
  # need a fresh ACTIVE read, not another scan of every team's registration.
  # Peek/ack and watch still use the full subscription path below.
  project_phys="$(agmsg_canonical_path "$PROJECT")"
  while IFS=$'\t' read -r team name; do
    [ -n "$team" ] && [ -n "$name" ] || continue
    agmsg_role_active_matches "$team" "$name" "$TYPE" "$session" "$project_phys" "$session" && printf '%s\t%s\n' "$team" "$name"
  done <<< "$requested"
  exit 0
fi

pairs="$(CODEX_THREAD_ID="$session" agmsg_subscription_pairs "$PROJECT" "$TYPE" "$session")"
if [ -n "$requested" ]; then
  pairs="$(printf '%s\n' "$pairs" | while IFS=$'\t' read -r team name; do
    printf '%s\n' "$requested" | grep -Fxq "${team}"$'\t'"${name}" && printf '%s\t%s\n' "$team" "$name"
  done || true)"
fi
printf '%s\n' "$pairs"
