"""Real isolated membership/storage checks for the managed start-hook summary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SessionSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agmsg-summary-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.skill = self.root / 'skill'
        shutil.copytree(ROOT / 'scripts', self.skill / 'scripts')
        shutil.copytree(ROOT / 'mod/asys-routing', self.skill / 'scripts/agmsg-routing',
                        ignore=shutil.ignore_patterns('route.sh'))
        shutil.copy2(ROOT / 'mod/asys-routing/route.sh', self.skill / 'scripts/route.sh')
        self.project = self.root / 'project'
        self.project.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('AGMSG_', 'CODEX_', 'CLAUDE_'))}
        self.env.update(HOME=str(self.root / 'home'), CODEX_THREAD_ID='owner-native',
                        AGMSG_STORAGE_PATH=str(self.root / 'db'), AGMSG_BRIDGE_ROOT=str(self.root / 'bridge'),
                        AGMSG_SEND_JOURNAL=str(self.root / 'sends.jsonl'))
        self.hook = self.skill / 'scripts/agmsg-routing/hooks/session-start.sh'

    def script(self, name, *args, env=None, input=''):
        return subprocess.run(['bash', str(self.skill / 'scripts' / name), *args],
                              cwd=self.project, env=env or self.env, input=input,
                              text=True, capture_output=True, timeout=30)

    def join(self, runtime='codex'):
        r = self.script('join.sh', 'test', 'reader', runtime, str(self.project))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.script('send.sh', 'test', 'sender', 'reader', 'Human readable message', '--force')
        self.assertEqual(r.returncode, 0, r.stderr)

    def hook_run(self, runtime='codex', env=None, input=''):
        return self.script('agmsg-routing/hooks/session-start.sh', '--runtime', runtime, env=env, input=input)

    def test_unbound_same_project_and_history_only_are_silent(self):
        self.join()
        self.assertEqual(self.hook_run().stdout, '')
        cmd = 'SKILL_DIR="$1"; source "$1/scripts/lib/role-session.sh"; agmsg_role_session_record test reader owner-native "$2" codex'
        r = subprocess.run(['bash', '-c', cmd, 'fixture', str(self.skill), str(self.project.resolve())],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hook_run().stdout, '')
        self.assertFalse((self.root / 'bridge').exists())

    def test_bound_summary_only_for_owner_and_leave_silences_it(self):
        self.join()
        r = self.script('drivers/types/codex/codex-record-session.sh', 'test', 'reader', str(self.project))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.hook_run()
        self.assertIn('unread count: 1', r.stdout, r.stderr)
        self.assertIn('Human readable message', r.stdout)
        self.assertNotIn('owner-native', r.stdout)
        other = {**self.env, 'CODEX_THREAD_ID': 'other-native'}
        self.assertEqual(self.hook_run(env=other).stdout, '')
        r = self.script('leave.sh', str(self.project), 'codex', 'reader')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hook_run().stdout, '')
        unread = self.script('inbox.sh', 'test', 'reader', '--peek-json')
        self.assertEqual(len(unread.stdout.splitlines()), 1, unread.stderr)

    def test_claude_hook_native_session_not_inherited_codex_environment(self):
        self.join('claude-code')
        r = self.script('actas-claim.sh', str(self.project), 'claude-code', 'reader', 'claude-native')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.hook_run('claude-code', input=json.dumps({'session_id': 'claude-native'}))
        self.assertIn('unread count: 1', r.stdout, r.stderr)
        self.assertEqual(self.hook_run('claude-code', input=json.dumps({'session_id': 'other-native'})).stdout, '')


if __name__ == '__main__':
    unittest.main()
