#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$HOME/.agents/skills/agmsg"
# Scoped maintenance uses this same managed install entry point. It must not
# rerun hook merging, migrate stores, refresh shims, or replace unrelated code.
if [[ "${1:-}" == "--codex-delivery-only" || "${1:-}" == "--codex-capability-info-only" || "${1:-}" == "--send-journal-only" || "${1:-}" == "--session-delivery-only" ]]; then
  INSTALLED_REVISION=""
  if [[ $# -gt 2 ]]; then
    [[ $# -eq 4 && "$1" == "--session-delivery-only" && "$3" == "--installed-revision" ]] || {
      echo "Scoped install accepts --dry-run or --apply, with optional --installed-revision COMMIT for session delivery." >&2; exit 2;
    }
    INSTALLED_REVISION="$4"
  fi
  python3 - "$ROOT" "$LIVE" "${2:---dry-run}" "$1" "$INSTALLED_REVISION" <<'PYDEPLOY'
from pathlib import Path
import hashlib,json,os,re,subprocess,sys,tempfile,zipfile
from datetime import datetime,timezone
source,live,mode=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
if mode not in ('--dry-run','--apply'):raise SystemExit('expected --dry-run or --apply')
scope=sys.argv[4]
paths={
 '--send-journal-only':['scripts/lib/storage.sh','scripts/lib/send-journal.sh','scripts/lib/send-journal.py','scripts/drivers/storage/sqlite.sh','scripts/drivers/storage/jsonl.sh','scripts/route.sh'],
 '--codex-delivery-only':['scripts/inbox.sh','scripts/drivers/types/codex/codex-bridge.js'],
 '--codex-capability-info-only':['SKILL.md','scripts/drivers/types/codex/_delivery.sh'],
 '--session-delivery-only':[
  'SKILL.md',
  'scripts/drivers/types/claude-code/template.md',
  'scripts/drivers/types/codex/template.md',
  'scripts/lib/role-session.sh',
  'scripts/lib/actas-lock.sh',
  'scripts/lib/subscription.sh',
  'scripts/actas-claim.sh',
  'scripts/leave.sh',
  'scripts/drivers/types/codex/codex-record-session.sh',
  'scripts/drivers/types/codex/_session-start.sh',
  'scripts/drivers/types/codex/codex-bridge.js',
  'scripts/drivers/types/codex/codex-bridge-launcher.sh',
  'scripts/drivers/types/codex/eligible-pairs.sh',
  'scripts/drivers/types/codex/watch-once.sh',
  'scripts/drivers/types/codex/codex-desktop-ipc.js',
  'scripts/session-start.sh',
  'scripts/session-end.sh',
  'scripts/check-inbox.sh',
  'scripts/delivery.sh',
  'scripts/watch.sh',
  'scripts/agmsg-routing/hooks/session-start.sh',
  'scripts/route.sh',
 ],
}[scope]
source_names={'scripts/route.sh':'mod/asys-routing/route.sh'} if scope=='--send-journal-only' else {}
if scope=='--session-delivery-only':
 source_names.update({'scripts/agmsg-routing/hooks/session-start.sh':'mod/asys-routing/hooks/session-start.sh',
                      'scripts/route.sh':'mod/asys-routing/route.sh'})
targets={name:live/name for name in paths}
rendered=set()
command=Path.home()/'.claude/commands/agmsg.md'
if scope=='--session-delivery-only' and (command.exists() or command.is_symlink()):
 name='claude/commands/agmsg.md'
 paths.append(name)
 targets[name]=command
 source_names[name]='scripts/drivers/types/claude-code/template.md'
 rendered.add(name)
def render(name,data):
 return data.replace(b'__SKILL_NAME__',b'agmsg') if name in rendered else data
revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
installed_revision=sys.argv[5]
if installed_revision:
 if not re.fullmatch(r'[0-9a-f]{40}',installed_revision):raise SystemExit('installed revision must be a full commit hash')
 verified=subprocess.run(['git','-C',str(source),'merge-base','--is-ancestor',installed_revision,revision],capture_output=True)
 if verified.returncode!=0:raise SystemExit('installed revision must be a known ancestor of the selected source')
baseline=(live/'.asys-source-commit').read_text().strip()
if not re.fullmatch(r'[0-9a-f]{40}',baseline):raise SystemExit('invalid installed source revision')
sha=lambda b:hashlib.sha256(b).hexdigest()
root=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'akaghef-system/agmsg-delivery'
def previous_scoped_version(name,source_name,old):
 # A prior scoped update intentionally leaves the full-install baseline alone.
 # Accept its bytes only with a managed receipt AND a matching committed blob.
 if old is None:return False
 digest=sha(old)
 for manifest in root.glob('*/manifest.json'):
  try:
   receipt=json.loads(manifest.read_text())
   recorded=receipt['revision']
   if not isinstance(recorded,str) or not re.fullmatch(r'[0-9a-f]{40}',recorded):continue
   if not any(e.get('path')==name and e.get('source_path')==source_name and e.get('after')==digest for e in receipt['files']):continue
  except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
  ancestor=subprocess.run(['git','-C',str(source),'merge-base','--is-ancestor',recorded,revision],capture_output=True)
  if ancestor.returncode!=0:continue
  committed=subprocess.run(['git','-C',str(source),'show',recorded+':'+source_name],capture_output=True)
  if committed.returncode==0 and sha(render(name,committed.stdout))==digest:return True
 return False
entries=[]
for name in paths:
 target=targets[name]
 boundary=Path.home() if name in rendered else live
 if any(p.is_symlink() for p in target.parents if p==boundary or boundary in p.parents):raise SystemExit('symlink in installed path: '+name)
 if target.is_symlink() or (target.exists() and not target.is_file()):raise SystemExit('expected installed regular file: '+name)
 source_name=source_names.get(name,name)
 old=target.read_bytes() if target.exists() else None
 new=render(name,(source/source_name).read_bytes())
 base_result=subprocess.run(['git','-C',str(source),'show',baseline+':'+source_name],capture_output=True)
 base=render(name,base_result.stdout) if base_result.returncode==0 else None
 explicitly_verified=False
 if installed_revision:
  proof=subprocess.run(['git','-C',str(source),'show',installed_revision+':'+source_name],capture_output=True)
  explicitly_verified=proof.returncode==0 and old==render(name,proof.stdout)
 if old not in (base,new) and not explicitly_verified and not previous_scoped_version(name,source_name,old):raise SystemExit('installed source drift: '+name)
 entries.append(dict(path=name,target=str(target),source_path=source_name,before=sha(old) if old is not None else None,after=sha(new)))
print(json.dumps(dict(mode=mode,scope=scope,source=str(source),revision=revision,installed_revision=installed_revision or None,files=entries),indent=2))
if mode=='--dry-run':raise SystemExit(0)
root.mkdir(parents=True,exist_ok=True)
backup=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),dir=root))
with zipfile.ZipFile(backup/'before.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name in paths:
  if targets[name].exists():z.write(targets[name],name)
(backup/'manifest.json').write_text(json.dumps(dict(scope=scope,source=str(source),revision=revision,installed_revision=installed_revision or None,files=entries),indent=2)+'\n')
for name in paths:
 target=targets[name]
 target.parent.mkdir(parents=True,exist_ok=True)
 fd,temp=tempfile.mkstemp(prefix=target.name+'.',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(render(name,(source/source_names.get(name,name)).read_bytes()));out.flush();os.fsync(out.fileno())
  os.chmod(temp,(target.stat().st_mode if target.exists() else (source/source_names.get(name,name)).stat().st_mode) & 0o777)
  os.replace(temp,target)
 finally:
  if os.path.exists(temp):os.unlink(temp)
for entry in entries:assert sha(targets[entry['path']].read_bytes())==entry['after']
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
  *) echo "Usage: install.sh [--dry-run|--apply] | --session-delivery-only [--dry-run|--apply] [--installed-revision COMMIT]" >&2; exit 2 ;;
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
