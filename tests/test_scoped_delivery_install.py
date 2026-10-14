import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=('scripts/inbox.sh','scripts/drivers/types/codex/codex-bridge.js')

class ScopedInstall(unittest.TestCase):
    def test_delivery_scope(self):
        self.check_scope("--codex-delivery-only", FILES)

    def test_capability_info_scope(self):
        self.check_scope("--codex-capability-info-only", ("SKILL.md", "scripts/drivers/types/codex/_delivery.sh"))

    def check_scope(self, scope, files):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);live=home/'.agents/skills/agmsg';live.mkdir(parents=True)
            base=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
            (live/'.asys-source-commit').write_text(base)
            for name in files:
                p=live/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(subprocess.check_output(['git','-C',str(ROOT),'show','HEAD:'+name]));p.chmod(0o755)
            sentinels=[home/'.claude/settings.json',home/'.codex/hooks.json',live/'scripts/unrelated.sh']
            for p in sentinels:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('preserve exactly\n')
            before={str(p):p.read_bytes() for p in sentinels}
            env={**os.environ,'HOME':tmp,'XDG_STATE_HOME':str(home/'state')}
            def run(mode):return subprocess.run(['bash',str(ROOT/'src/install.sh'),scope,mode],env=env,capture_output=True,text=True)
            dry=run('--dry-run');self.assertEqual(dry.returncode,0,dry.stderr);self.assertFalse((home/'state').exists())
            result=run('--apply');self.assertEqual(result.returncode,0,result.stderr)
            for name in files:self.assertEqual((live/name).read_bytes(),(ROOT/name).read_bytes())
            self.assertEqual(before,{str(p):p.read_bytes() for p in sentinels})
            self.assertEqual((live/'.asys-source-commit').read_text(),base)
            self.assertTrue(list((home/'state').rglob('before.zip')))
            (live/files[0]).write_text('unrelated installed modification')
            rejected=run('--apply');self.assertNotEqual(rejected.returncode,0);self.assertIn('drift',rejected.stderr)

if __name__=='__main__':unittest.main()
