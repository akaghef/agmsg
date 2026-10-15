#!/usr/bin/env bash
# Observation is best-effort and must never alter the committed send result.
_AGMSG_SEND_JOURNAL_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/send-journal.py"
agmsg_journal_send() {
  ( printf '%s' "$5" | python3 "$_AGMSG_SEND_JOURNAL_HELPER" \
      "$1" "$2" "$3" "$4" "${6:-${AGMSG_SEND_REALM:-local}}" \
      "${7:-${AGMSG_SEND_KIND:-message}}" "${8:-${AGMSG_SEND_THREAD:-}}" "$$" "$PPID" ) >/dev/null 2>&1 || :
  return 0
}
