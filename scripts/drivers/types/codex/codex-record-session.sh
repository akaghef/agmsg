#!/usr/bin/env bash
# Explicit Codex role membership plus advisory resume history.
# Usage: codex-record-session.sh <team> <agent> [project]
# CODEX_THREAD_ID is mandatory; same-project rollouts never identify the caller.
set -uo pipefail

TEAM="${1:-}"; AGENT="${2:-}"; PROJECT="${3-${PWD:-}}"
[ "$#" -le 3 ] && [ -n "$TEAM" ] && [ -n "$AGENT" ] || {
  echo status=invalid_arguments; exit 2;
}
# No <project> argument -> this script's own $PWD (see header: deterministic
# under bash even when the caller's shell is PowerShell).
[ -n "$PROJECT" ] || { echo status=invalid_project; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# types/codex/ -> up 4 (codex -> types -> drivers -> scripts -> skill root).
SKILL_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
export SKILL_DIR
# shellcheck disable=SC1091
. "$SKILL_DIR/scripts/lib/resolve-project.sh"
# shellcheck disable=SC1091
. "$SKILL_DIR/scripts/lib/role-session.sh"

# Reject invalid projects before claiming membership. A mangled
# <project> argument -- e.g. the lone `\` a PowerShell-parsed \"$PWD\" collapses
# to -- must never be recorded: the launcher's project-mismatch safety valve
# would then exclude the role and silently stop its delivery. Reject anything
# that is not a real directory, and anything whose physical path is a
# filesystem root (`/`, an MSYS drive root like `/c`, or a Windows drive root)
# -- no real project lives there, so such a value can only be quoting damage.
[ -d "$PROJECT" ] && (cd -- "$PROJECT" 2>/dev/null) || { echo status=invalid_project; exit 2; }
project_phys="$(agmsg_canonical_path "$PROJECT")" || { echo status=invalid_project; exit 2; }
[ -n "$project_phys" ] && [ -d "$project_phys" ] || { echo status=invalid_project; exit 2; }
case "$project_phys" in
  / | /[A-Za-z] | [A-Za-z]: | [A-Za-z]:/ | [A-Za-z]:\\) echo status=invalid_project; exit 2 ;;
esac

# Only the runtime's native identity can authorize this role. Loaded-thread
# subtraction and rollout history are not proof of the current caller.
thread="${CODEX_THREAD_ID:-}"
[ -n "$thread" ] || { echo status=unbound; exit 1; }
if ! "$SKILL_DIR/scripts/identities.sh" "$PROJECT" codex | awk -F'\t' -v t="$TEAM" -v a="$AGENT" '$1==t && $2==a {found=1} END {exit !found}'; then
  echo status=not_registered; exit 2
fi
if ! result="$(agmsg_role_active_claim "$TEAM" "$AGENT" "$thread" "$project_phys" codex "$thread")"; then
  case "$result" in
    held:*) echo status=held ;;
    *) echo status=error ;;
  esac
  exit 1
fi
agmsg_role_session_record "$TEAM" "$AGENT" "$thread" "$project_phys" codex || true
# An explicit Desktop join starts the existing bridge via the same SessionStart
# path, after activation. Missing/inaccessible sockets leave messages unread.
if [ -S "${AGMSG_CODEX_DESKTOP_SOCKET:-${HOME:-}/.codex/ipc/ipc.sock}" ]; then
  "$SKILL_DIR/scripts/session-start.sh" codex "$PROJECT" </dev/null || true
fi
printf 'status=ok team=%s\n' "$TEAM"
exit 0
