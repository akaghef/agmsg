#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$HOME/.agents/skills/agmsg"
# Scoped maintenance uses this same managed install entry point. It must not
# rerun hook merging, migrate stores, refresh shims, or replace unrelated code.
if [[ "${1:-}" == "--codex-delivery-only" || "${1:-}" == "--codex-capability-info-only" ]]; then
  python3 - "$ROOT" "$LIVE" "${2:---dry-run}" "$1" <<'PYDEPLOY'
from pathlib import Path
import hashlib,json,os,re,subprocess,sys,tempfile,zipfile
from datetime import datetime,timezone
source,live,mode=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
if mode not in ('--dry-run','--apply'):raise SystemExit('expected --dry-run or --apply')
scope=sys.argv[4]
paths={
 '--codex-delivery-only':['scripts/inbox.sh','scripts/drivers/types/codex/codex-bridge.js'],
 '--codex-capability-info-only':['SKILL.md','scripts/drivers/types/codex/_delivery.sh'],
}[scope]
revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
baseline=(live/'.asys-source-commit').read_text().strip()
if not re.fullmatch(r'[0-9a-f]{40}',baseline):raise SystemExit('invalid installed source revision')
sha=lambda b:hashlib.sha256(b).hexdigest()
entries=[]
for name in paths:
 target=live/name
 if target.is_symlink() or not target.is_file():raise SystemExit('expected installed regular file: '+name)
 old=target.read_bytes();new=(source/name).read_bytes()
 base=subprocess.check_output(['git','-C',str(source),'show',baseline+':'+name])
 if old not in (base,new):raise SystemExit('installed source drift: '+name)
 entries.append(dict(path=name,before=sha(old),after=sha(new)))
print(json.dumps(dict(mode=mode,scope=scope,source=str(source),revision=revision,files=entries),indent=2))
if mode=='--dry-run':raise SystemExit(0)
root=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'akaghef-system/agmsg-delivery'
root.mkdir(parents=True,exist_ok=True)
backup=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),dir=root))
with zipfile.ZipFile(backup/'before.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name in paths:z.write(live/name,name)
(backup/'manifest.json').write_text(json.dumps(dict(scope=scope,source=str(source),revision=revision,files=entries),indent=2)+'\n')
for name in paths:
 target=live/name
 fd,temp=tempfile.mkstemp(prefix=target.name+'.',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write((source/name).read_bytes());out.flush();os.fsync(out.fileno())
  os.chmod(temp,target.stat().st_mode & 0o777)
  os.replace(temp,target)
 finally:
  if os.path.exists(temp):os.unlink(temp)
for entry in entries:assert sha((live/entry['path']).read_bytes())==entry['after']
print('backup='+str(backup))
PYDEPLOY
  exit
fi
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
