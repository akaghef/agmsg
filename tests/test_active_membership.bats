#!/usr/bin/env bats
load test_helper
setup() {
  setup_test_env
  export SKILL_DIR="$TEST_SKILL_DIR" AGMSG_AGENT_PID=""
  unset CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID
  export PROJ="$TEST_SKILL_DIR/project"
  mkdir -p "$PROJ" "$SKILL_DIR/run"
  PROJ="$(cd "$PROJ" && pwd -P)"
  source "$SCRIPTS/lib/role-session.sh"
}
teardown() { teardown_test_env; }
register() { bash "$SCRIPTS/join.sh" team "$1" "$2" "$PROJ" >/dev/null; bash "$SCRIPTS/join.sh" team sender "$2" "$PROJ" >/dev/null; }
claim() { agmsg_role_active_claim team "$1" "$3" "$PROJ" "$2" "$3"; }
unread() {
  (source "$SCRIPTS/lib/storage.sh"; agmsg_storage_load; storage_list_unread team "$1")
}
@test "ACTIVE: historical resume record never subscribes an unbound Claude session" {
  register reader claude-code
  agmsg_role_session_record team reader owner "$PROJ" claude-code
  bash "$SCRIPTS/send.sh" team sender reader secret >/dev/null
  run bash -c 'printf "{\"session_id\":\"owner\"}" | "$1/check-inbox.sh" claude-code "$2" 2>/dev/null' _ "$SCRIPTS" "$PROJ"
  [ "$status" -eq 0 ]; [ -z "$output" ]
  [[ "$(unread reader)" == *secret* ]] || return 1
  run bash -c 'printf "{\"session_id\":\"owner\"}" | "$1/session-start.sh" claude-code "$2" 2>/dev/null' _ "$SCRIPTS" "$PROJ"
  [ "$status" -eq 0 ]; [ -z "$output" ]
}
@test "ACTIVE: same-project Claude Stop hook delivers only the explicitly joined owner" {
  register reader claude-code; claim reader claude-code owner
  bash "$SCRIPTS/send.sh" team sender reader secret >/dev/null
  run bash -c 'printf "{\"session_id\":\"stranger\"}" | "$1/check-inbox.sh" claude-code "$2" 2>/dev/null' _ "$SCRIPTS" "$PROJ"
  [ "$status" -eq 0 ]; [[ "$output" != *secret* ]] || return 1
  [[ "$(unread reader)" == *secret* ]] || return 1
  run bash -c 'printf "{\"session_id\":\"owner\"}" | "$1/check-inbox.sh" claude-code "$2" 2>/dev/null' _ "$SCRIPTS" "$PROJ"
  [ "$status" -eq 0 ]; [[ "$output" == *secret* ]] || return 1
  [ -z "$(unread reader)" ]
}
@test "ACTIVE: Codex Stop hook requires CODEX_THREAD_ID and exact active native owner" {
  register reader codex; claim reader codex owner
  bash "$SCRIPTS/send.sh" team sender reader secret >/dev/null
  run bash -c 'printf "{\"session_id\":\"owner\"}" | "$1/check-inbox.sh" codex "$2"' _ "$SCRIPTS" "$PROJ"
  [ "$status" -eq 0 ]; [[ "$output" != *secret* ]] || return 1
  run env CODEX_THREAD_ID=stranger bash "$SCRIPTS/check-inbox.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]; [[ "$output" != *secret* ]] || return 1
  run env AGMSG_AGENT_PID="$$" CODEX_THREAD_ID=owner bash "$SCRIPTS/check-inbox.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]; [[ "$output" == *secret* ]] || return 1
}
@test "ACTIVE: stale leave and session-end cannot remove a newer Codex owner" {
  register reader codex; claim reader codex newer
  run env CODEX_THREAD_ID=older bash "$SCRIPTS/leave.sh" "$PROJ" codex reader
  [ "$status" -eq 0 ]
  run env CODEX_THREAD_ID=older bash "$SCRIPTS/session-end.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]
  agmsg_role_active_matches team reader codex newer "$PROJ" newer
  run env CODEX_THREAD_ID=newer bash "$SCRIPTS/leave.sh" "$PROJ" codex reader
  [ "$status" -eq 0 ]
  ! agmsg_role_active_matches team reader codex newer "$PROJ" newer || return 1
  [[ "$(bash "$SCRIPTS/identities.sh" "$PROJ" codex)" == *reader* ]] || return 1
}
@test "ACTIVE: matching session-end clears membership and preserves resume history" {
  register reader codex; claim reader codex owner
  agmsg_role_session_record team reader owner "$PROJ" codex
  run env CODEX_THREAD_ID=owner bash "$SCRIPTS/session-end.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]
  ! agmsg_role_active_matches team reader codex owner "$PROJ" owner || return 1
  [ "$(agmsg_role_session_uuid team reader)" = owner ]
}
@test "ACTIVE: Codex membership survives stale lock GC and rejects a second native owner" {
  register reader codex; claim reader codex owner
  actas_lock_gc_stale >/dev/null
  agmsg_role_active_matches team reader codex owner "$PROJ" owner
  run agmsg_role_active_claim team reader stranger "$PROJ" codex stranger
  [ "$status" -eq 1 ]; [[ "$output" == held:* ]] || return 1
  agmsg_role_active_matches team reader codex owner "$PROJ" owner
}
@test "ACTIVE: unbound named Claude watcher cannot implicitly join or consume mail" {
  register reader claude-code
  bash "$SCRIPTS/send.sh" team sender reader secret >/dev/null
  run bash "$SCRIPTS/watch.sh" stranger "$PROJ" claude-code reader
  [ "$status" -eq 0 ]; [[ "$output" != *secret* ]] || return 1
  [[ "$(unread reader)" == *secret* ]] || return 1
  ! agmsg_role_active_matches team reader claude-code stranger "$PROJ" stranger || return 1
}
@test "ACTIVE: Codex explicit claim refuses missing native identity and writes both records on success" {
  register reader codex
  run bash "$SCRIPTS/drivers/types/codex/codex-record-session.sh" team reader "$PROJ"
  [ "$status" -eq 1 ]; [[ "$output" == *status=unbound* ]] || return 1
  run env CODEX_THREAD_ID=owner bash "$SCRIPTS/drivers/types/codex/codex-record-session.sh" team reader "$PROJ"
  [ "$status" -eq 0 ]; [[ "$output" == *status=ok* ]] || return 1
  agmsg_role_active_matches team reader codex owner "$PROJ" owner
  [ "$(agmsg_role_session_uuid team reader)" = owner ]
}
@test "ACTIVE: stale Claude process sharing a native session cannot leave the current owner" {
  register reader claude-code
  agmsg_role_active_claim team reader shared "$PROJ" claude-code "shared.$$"
  run env AGMSG_AGENT_PID=999999 bash "$SCRIPTS/leave.sh" "$PROJ" claude-code reader shared
  [ "$status" -eq 0 ]
  agmsg_role_active_matches team reader claude-code shared "$PROJ" "shared.$$"
}
@test "ACTIVE: multi-team claim rollback preserves membership already held before the attempt" {
  register reader codex; claim reader codex owner
  bash "$SCRIPTS/join.sh" zteam reader codex "$PROJ" >/dev/null
  agmsg_role_active_claim zteam reader other "$PROJ" codex other
  run env CODEX_THREAD_ID=owner bash "$SCRIPTS/actas-claim.sh" "$PROJ" codex reader owner
  [ "$status" -eq 1 ]; [[ "$output" == *status=held* ]] || return 1
  agmsg_role_active_matches team reader codex owner "$PROJ" owner
  agmsg_role_active_matches zteam reader codex other "$PROJ" other
}
@test "ACTIVE: Codex SessionStart creates a request only for its active native thread" {
  register reader codex; claim reader codex owner
  run env CODEX_THREAD_ID=stranger AGMSG_CODEX_BRIDGE_LAUNCHER=1 AGMSG_CODEX_BRIDGE_APP_SERVER=ws://localhost:1 bash "$SCRIPTS/session-start.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]; [ -z "$output" ]
  [ -z "$(find "$SKILL_DIR/run" -name 'codex-bridge-request.*' -print)" ]
  run env CODEX_THREAD_ID=owner AGMSG_AGENT_PID="$$" AGMSG_CODEX_BRIDGE_LAUNCHER=1 AGMSG_CODEX_BRIDGE_APP_SERVER=ws://localhost:1 bash "$SCRIPTS/session-start.sh" codex "$PROJ" </dev/null
  [ "$status" -eq 0 ]
  local request
  request="$(find "$SKILL_DIR/run" -name 'codex-bridge-request.*' -print)"
  [ -n "$request" ]; [[ "$(cat "$request")" == *owner* ]] || return 1
}
@test "ACTIVE: clearing an actas lock invalidates active authorization without deleting resume history" {
  register reader codex; claim reader codex owner
  agmsg_role_session_record team reader owner "$PROJ" codex
  actas_lock_release team reader owner
  ! agmsg_role_active_matches team reader codex owner "$PROJ" owner || return 1
  [ "$(agmsg_role_session_uuid team reader)" = owner ]
}
@test "ACTIVE: GC cannot remove a Codex lock between claim and active publication" {
  register reader codex
  # Inject the actual GC operation at the dangerous publication boundary.
  # The existing lock primitive runs under the ACTIVE mutation guard.
  eval "$(declare -f _actas_lock_claim_unlocked | sed '1s/_actas_lock_claim_unlocked/_original_claim_unlocked/')"
  _actas_lock_claim_unlocked() {
    _original_claim_unlocked "$@" || return $?
    actas_lock_gc_stale >/dev/null
  }
  claim reader codex owner
  agmsg_role_active_matches team reader codex owner "$PROJ" owner
}
@test "ACTIVE: bulk release and GC defer to an in-progress membership transaction" {
  register reader claude-code; claim reader claude-code owner
  local guard
  guard="$(_agmsg_role_active_path team reader).guard"
  mkdir "$guard"
  actas_lock_release_all owner
  actas_lock_gc_stale >/dev/null
  [ "$(actas_lock_owner team reader)" = owner ]
  rmdir "$guard"
  actas_lock_release_all owner
  [ -z "$(actas_lock_owner team reader)" ]
}
@test "ACTIVE: clear retires only this Claude process's previous native membership" {
  register reader claude-code
  agmsg_role_active_claim team reader previous "$PROJ" claude-code "previous.$$"
  printf 'previous.%s\n' "$$" > "$SKILL_DIR/run/cc-instance.$$"
  run bash -c 'printf "{\"session_id\":\"new\"}" | AGMSG_AGENT_PID="$3" "$1/session-start.sh" claude-code "$2"' _ "$SCRIPTS" "$PROJ" "$$"
  [ "$status" -eq 0 ]; [ -z "$output" ]
  ! agmsg_role_active_matches team reader claude-code previous "$PROJ" "previous.$$" || return 1
  ! agmsg_role_active_matches team reader claude-code new "$PROJ" "new.$$" || return 1
}
@test "ACTIVE: unexpected exit releases only its acquired guard and preserves caller traps" {
  local before guard
  before="$(trap -p EXIT)"
  guard="$(_agmsg_role_active_path team reader).guard"
  _actas_lock_claim_unlocked() { exit 19; }
  run actas_lock_claim team reader owner
  [ "$status" -eq 19 ]
  [ ! -d "$guard" ]
  [ "$(trap -p EXIT)" = "$before" ]
}
@test "ACTIVE: TERM during owner mutation cleans its acquired guard" {
  local guard
  guard="$(_agmsg_role_active_path team reader).guard"
  _actas_lock_claim_unlocked() { sh -c 'kill -TERM "$PPID"'; }
  run actas_lock_claim team reader owner
  [ "$status" -eq 143 ]
  [ ! -d "$guard" ]
}
