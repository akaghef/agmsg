#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1
LIVE="${AGMSG_LIVE_ROOT:-$HOME/.agents/skills/agmsg}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$LIVE/.akaghef-backup-$STAMP"
CLAUDE="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
CODEX="${CODEX_HOOKS:-$HOME/.codex/hooks.json}"
PLIST="$HOME/Library/LaunchAgents/org.akaghef.agmsg-bridge-watcher.plist"
paths=(scripts/route.sh scripts/adapters/bridge.sh scripts/adapters/drive.sh scripts/agmsg-routing)
echo "mode=$([[ $DRY == 1 ]] && echo dry-run || echo install)"
echo "live=$LIVE backup=$BACKUP"
printf 'copy: %s\n' "${paths[@]}"
echo "merge hooks: $CLAUDE ; $CODEX (backup each existing file first)"
echo "install plist: $PLIST"
[[ $DRY == 1 ]] && exit 0
[[ -d "$LIVE" ]] || { echo "live agmsg install missing: $LIVE" >&2; exit 2; }
mkdir -p "$BACKUP"
for p in "${paths[@]}"; do
  [[ -e "$LIVE/$p" ]] && { mkdir -p "$BACKUP/$(dirname "$p")"; cp -R "$LIVE/$p" "$BACKUP/$p"; }
done
for f in "$CLAUDE" "$CODEX"; do [[ -f "$f" ]] && cp -p "$f" "$BACKUP/$(basename "$(dirname "$f")")-$(basename "$f")"; done
mkdir -p "$LIVE/scripts/adapters" "$LIVE/scripts/agmsg-routing/hooks" "$HOME/Library/LaunchAgents"
cp "$HERE/route.sh" "$LIVE/scripts/route.sh"
cp "$HERE/adapters/bridge.sh" "$LIVE/scripts/adapters/bridge.sh"
cp "$HERE/adapters/drive.sh" "$LIVE/scripts/adapters/drive.sh"
chmod +x "$LIVE/scripts/route.sh" "$LIVE/scripts/adapters/bridge.sh" "$LIVE/scripts/adapters/drive.sh"
cp -R "$HERE/lib" "$LIVE/scripts/agmsg-routing/"
cp -R "$HERE/legacy" "$LIVE/scripts/agmsg-routing/"
for dep in send.sh inbox.sh status.sh init-db.sh; do
  ln -sfn "../../$dep" "$LIVE/scripts/agmsg-routing/legacy/$dep"
done
for dep in lib internal drivers; do
  ln -sfn "../../$dep" "$LIVE/scripts/agmsg-routing/legacy/$dep"
done
ln -sfn "../../teams" "$LIVE/scripts/agmsg-routing/teams"
cp "$HERE/watcher.sh" "$LIVE/scripts/agmsg-routing/watcher.sh"
cp "$HERE/hooks/session-start.sh" "$LIVE/scripts/agmsg-routing/hooks/session-start.sh"
chmod +x "$LIVE/scripts/agmsg-routing/watcher.sh" "$LIVE/scripts/agmsg-routing/hooks/session-start.sh"
cp "$HERE/team-map.yaml" "$LIVE/scripts/agmsg-routing/team-map.yaml"
sed "s#/Users/akaghef/.agents/skills/agmsg/scripts/agmsg-routing/watcher.sh#$LIVE/scripts/agmsg-routing/watcher.sh#" "$HERE/org.akaghef.agmsg-bridge-watcher.plist" > "$PLIST"
python3 - "$CLAUDE" "$CODEX" "$LIVE/scripts/agmsg-routing/hooks/session-start.sh" <<'PY'
import json,os,sys
claude,codex,hook=sys.argv[1:]
def update(path,runtime,kind):
 os.makedirs(os.path.dirname(path),exist_ok=True)
 data=json.load(open(path)) if os.path.exists(path) else {}
 hooks=data.setdefault('hooks',{})
 arr=hooks.setdefault('SessionStart',[])
 command=hook+' --runtime '+runtime
 marker='agmsg-routing/session-start.sh'
 matched=False
 for item in arr:
  for entry in item.get('hooks',[]):
   if marker in entry.get('command',''):
    entry.update({'command':command,'timeout':10}); matched=True
 if not matched:
  item={'hooks':[{'type':'command','command':command,'timeout':10}]}
  if kind=='claude': item['matcher']=''
  arr.append(item)
 with open(path,'w') as f: json.dump(data,f,indent=2); f.write('\n')
update(claude,'claude-code','claude'); update(codex,'codex','codex')
PY
"$LIVE/scripts/route.sh" watcher --seed
echo "installed; enable with: launchctl bootstrap gui/$(id -u) '$PLIST'"
