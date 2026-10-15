"""Isolated storage/journal tests; no installed teams or live delivery."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SendJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scripts = self.root/'skill/scripts'
        shutil.copytree(ROOT/'scripts', self.scripts)
        shutil.copyfile(ROOT/'mod/asys-routing/route.sh', self.scripts/'route.sh')
        shutil.copytree(ROOT/'mod/asys-routing/lib', self.scripts/'agmsg-routing/lib')
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('AGMSG_', 'CLAUDE_', 'CODEX_'))}
        self.env.update(HOME=str(self.root), AGMSG_STORAGE_PATH=str(self.root/'db'),
                        AGMSG_SEND_JOURNAL=str(self.root/'journal/sends.jsonl'),
                        AGMSG_CONFIG=str(self.root/'absent.json'), CODEX_THREAD_ID='native-session',
                        AGMSG_BRIDGE_ROOT=str(self.root/'bridge'))
        self.journal = Path(self.env['AGMSG_SEND_JOURNAL'])
    def tearDown(self):
        self.tmp.cleanup()
    def run_script(self, name, *args, env=None):
        return subprocess.run(['bash', str(self.scripts/name), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=20)
    def send(self, body='hello', env=None):
        return self.run_script('send.sh', 'test', 'sender', 'absent', body, '--force', env=env)
    def rows(self):
        return [json.loads(s) for s in self.journal.read_text().splitlines()]
    def test_committed_id_body_milliseconds_session_and_no_schema_change(self):
        init=subprocess.run(['bash','-c','source "$1/lib/storage.sh"; agmsg_storage_load; storage_init test', 'test',str(self.scripts)],env=self.env,capture_output=True,text=True)
        self.assertEqual(init.returncode,0,init.stderr)
        db=self.root/'db/messages.db'
        with sqlite3.connect(db) as c:
            before=c.execute('select sql from sqlite_master order by name').fetchall()
        body='本文 "quoted"\nsecond line 😀'
        result=self.send(body);self.assertEqual(result.returncode,0,result.stderr)
        row=self.rows()[0]
        history=self.run_script('api.sh','get','teams','test','messages')
        sent=json.loads(history.stdout.splitlines()[0])
        self.assertEqual(row['message_id'],sent['id']);self.assertEqual(row['body'],body)
        self.assertRegex(row['ts'],r'\.\d{3}Z$');self.assertEqual(row['source']['session_id'],'native-session')
        self.assertEqual((row['realm'],row['kind'],row['thread']),('local','message',''))
        self.assertEqual(self.journal.stat().st_mode & 0o777,0o600)
        with sqlite3.connect(db) as c:
            self.assertEqual(before,c.execute('select sql from sqlite_master order by name').fetchall())
    def test_failure_is_open_and_failed_send_is_not_journalled(self):
        blocker=self.root/'blocker';blocker.write_text('file')
        env={**self.env,'AGMSG_SEND_JOURNAL':str(blocker/'sends.jsonl')}
        result=self.send(env=env);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'Sent to absent in team test')
        self.assertEqual(len(self.run_script('api.sh','get','teams','test','messages').stdout.splitlines()),1)
        result=self.send(env={**self.env,'AGMSG_STORAGE_PATH':str(blocker/'db')})
        self.assertNotEqual(result.returncode,0);self.assertFalse(self.journal.exists())
    def test_missing_journal_helper_is_also_fail_open(self):
        (self.scripts/"lib/send-journal.sh").unlink()
        result=self.send();self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.journal.exists())
    def test_concurrent_unicode_lines_have_unique_real_ids(self):
        self.run_script('internal/init-db.sh')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda n:self.send(f'{n}:'+('大きい本文\n'*1000)),range(12)))
        self.assertTrue(all(r.returncode==0 for r in results))
        rows=self.rows();self.assertEqual(len(rows),12);self.assertEqual(len({r['message_id'] for r in rows}),12)
        self.assertTrue(all(r['body'].endswith('大きい本文\n') for r in rows))
    def test_jsonl_driver_uses_same_journal(self):
        result=self.send(env={**self.env,'AGMSG_STORAGE_DRIVER':'jsonl'})
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(self.rows()),1)
    def test_route_local_and_remote_queue_metadata_and_pid_fallback(self):
        env={k:v for k,v in self.env.items() if k!='CODEX_THREAD_ID'}
        env['AGMSG_SEND_THREAD']='discussion'
        result=self.run_script('route.sh','send','local:test/absent','sender','route body','notice',env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        result=self.run_script('route.sh','send','win:test/absent','sender','remote body','notice',env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=self.rows();self.assertEqual(len(rows),2)
        self.assertEqual([r['realm'] for r in rows],['local','win'])
        self.assertTrue(all(r['kind']=='notice' and r['thread']=='discussion' for r in rows))
        self.assertTrue(all(r['source']['session_id'] is None and r['source']['pid']>0 and r['source']['cwd'] for r in rows))
        packet=json.loads(next((self.root/'bridge/pending/mac_to_windows').glob('*.json')).read_text())
        self.assertEqual(rows[1]['message_id'],packet['id'])
    @unittest.skipIf(os.name=='nt','POSIX locking test')
    def test_locked_journal_does_not_block_send(self):
        import fcntl,time
        self.journal.parent.mkdir();self.journal.touch()
        with self.journal.open('ab') as locked:
            fcntl.flock(locked,fcntl.LOCK_EX)
            started=time.monotonic();result=self.send()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(self.journal.read_text(),'')

if __name__=='__main__': unittest.main()
