#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$HOME/.agents/skills/agmsg"
case "${1:---dry-run}" in
  --dry-run)
    echo "upstream updater: bash $ROOT/install.sh --cmd agmsg --update"
    exec bash "$ROOT/mod/asys-routing/install.sh" --dry-run
    ;;
  --apply) ;;
  *) echo "Usage: install.sh [--dry-run|--apply]" >&2; exit 2 ;;
esac
[[ "${AGMSG_LIVE_ROOT:-$LIVE}" == "$LIVE" ]] || {
  echo "The upstream updater targets HOME/.agents/skills/agmsg; AGMSG_LIVE_ROOT differs." >&2
  exit 2
}
[[ -f "$LIVE/.agmsg" ]] || { echo "Existing agmsg install is required for --update." >&2; exit 2; }
BACKUP="${XDG_STATE_HOME:-$HOME/.local/state}/akaghef-system/agmsg-migration/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$BACKUP"
(cd "$LIVE" && zip -qry "$BACKUP/code.zip" scripts templates agents plugins SKILL.md VERSION uninstall.sh)
echo "code backup: $BACKUP/code.zip"
bash "$ROOT/install.sh" --cmd agmsg --update
bash "$ROOT/mod/asys-routing/install.sh"
git -C "$ROOT" rev-parse HEAD > "$LIVE/.asys-source-commit"
echo "managed source: $ROOT"
