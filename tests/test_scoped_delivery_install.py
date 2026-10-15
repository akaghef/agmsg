"""Installer plumbing in isolated homes/repos; never touches the live install."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('scripts/inbox.sh', 'scripts/drivers/types/codex/codex-bridge.js')
SESSION_FILES = (
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
)
NEW_FILES = ('scripts/drivers/types/codex/codex-desktop-ipc.js',)
SOURCE_NAMES = {
    'scripts/agmsg-routing/hooks/session-start.sh': 'mod/asys-routing/hooks/session-start.sh',
    'scripts/route.sh': 'mod/asys-routing/route.sh',
}
COMMAND = 'claude/commands/agmsg.md'
CLAUDE_TEMPLATE = 'scripts/drivers/types/claude-code/template.md'


class InstallFixture:
    def __init__(self, root, scope, files, new_files=(), command=False):
        self.root, self.scope, self.files = root, scope, files
        self.home, self.source = root/'home', root/'source'
        self.live = self.home/'.agents/skills/agmsg'
        self.live.mkdir(parents=True)
        (self.source/'src').mkdir(parents=True)
        shutil.copyfile(ROOT/'src/install.sh', self.source/'src/install.sh')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(HOME=str(self.home), XDG_STATE_HOME=str(self.home/'state'),
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.before = {}
        for name in files:
            source = self.source_file(name)
            source.parent.mkdir(parents=True, exist_ok=True)
            if name not in new_files:
                data = ('original __SKILL_NAME__ '+name+'\n').encode()
                source.write_bytes(data)
                source.chmod(0o755 if name.endswith('.sh') else 0o644)
                target = self.live/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                self.before[name] = data
        self.git('init', '-q')
        self.baseline = self.commit()
        (self.live/'.asys-source-commit').write_text(self.baseline)
        self.command = self.home/'.claude/commands/agmsg.md'
        if command:
            self.command.parent.mkdir(parents=True)
            data = self.before[CLAUDE_TEMPLATE].replace(b'__SKILL_NAME__', b'agmsg')
            self.command.write_bytes(data)
            self.before[COMMAND] = data
        for name in files:
            target = self.source_file(name)
            target.write_text('updated __SKILL_NAME__ '+name+'\n')
            target.chmod(0o755 if name.endswith('.sh') else 0o644)
        self.revision = self.commit()
        self.sentinels = [
            self.home/'.claude/settings.json', self.home/'.codex/hooks.json',
            self.home/'.codex/config.toml', self.live/'scripts/unrelated.sh',
            self.live/'db/messages.db', self.live/'teams/roster.json',
            self.live/'run/owner.json', self.live/'.asys-source-commit',
        ]
        for path in self.sentinels[:-1]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('preserve exactly\n')
        self.preserved = {path: path.read_bytes() for path in self.sentinels}

    def source_file(self, name):
        return self.source/SOURCE_NAMES.get(name, name)

    def git(self, *args):
        return subprocess.check_output(
            ['git', '-C', str(self.source), *args], env=self.env, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Installer Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'Installer fixture')
        return self.git('rev-parse', 'HEAD')

    def run(self, mode='--dry-run', *args):
        return subprocess.run(['bash', str(self.source/'src/install.sh'), self.scope, mode, *args],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def backups(self):
        return sorted((self.home/'state').rglob('manifest.json'))

    def expected(self):
        result = {name: self.source_file(name).read_bytes() for name in self.files}
        if COMMAND in self.before:
            result[COMMAND] = result[CLAUDE_TEMPLATE].replace(b'__SKILL_NAME__', b'agmsg')
        return result

    def target(self, name):
        return self.command if name == COMMAND else self.live/name


class ScopedInstall(unittest.TestCase):
    @contextmanager
    def fixture(self, scope='--codex-delivery-only', files=FILES, **kwargs):
        # Python's tempfile honors TMPDIR; no /tmp or live HOME assumptions.
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            yield InstallFixture(Path(tmp), scope, files, **kwargs)

    def test_delivery_scope(self):
        self.check_scope('--codex-delivery-only', FILES)

    def test_capability_info_scope(self):
        self.check_scope('--codex-capability-info-only',
                         ('SKILL.md', 'scripts/drivers/types/codex/_delivery.sh'))

    def test_session_delivery_exact_scope_backup_and_command(self):
        self.check_scope('--session-delivery-only', SESSION_FILES,
                         new_files=NEW_FILES, command=True)

    def test_session_delivery_does_not_create_absent_claude_command(self):
        with self.fixture('--session-delivery-only', SESSION_FILES, new_files=NEW_FILES) as fixture:
            result = fixture.run('--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(fixture.command.exists())
            self.assertEqual({e['path'] for e in json.loads(fixture.backups()[0].read_text())['files']},
                             set(SESSION_FILES))

    def check_scope(self, scope, files, **kwargs):
        with self.fixture(scope, files, **kwargs) as fixture:
            dry = fixture.run()
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse((fixture.home/'state').exists())
            planned = json.loads(dry.stdout)
            self.assertEqual({e['path'] for e in planned['files']}, set(fixture.expected()))
            for name, data in fixture.before.items():
                self.assertEqual(fixture.target(name).read_bytes(), data)
            result = fixture.run('--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = fixture.expected()
            for name, data in expected.items():
                self.assertEqual(fixture.target(name).read_bytes(), data)
            self.assertEqual(fixture.preserved,
                             {path: path.read_bytes() for path in fixture.sentinels})
            backups = fixture.backups()
            self.assertEqual(len(backups), 1)
            manifest = json.loads(backups[0].read_text())
            self.assertEqual(manifest['revision'], fixture.revision)
            self.assertEqual({e['path'] for e in manifest['files']}, set(expected))
            with zipfile.ZipFile(backups[0].parent/'before.zip') as archive:
                self.assertEqual(set(archive.namelist()), set(fixture.before))
                for name, data in fixture.before.items():
                    self.assertEqual(archive.read(name), data)
            for entry in manifest['files']:
                self.assertEqual(entry['after'], hashlib.sha256(expected[entry['path']]).hexdigest())
                previous = fixture.before.get(entry['path'])
                self.assertEqual(entry['before'], hashlib.sha256(previous).hexdigest() if previous else None)
            fixture.target(files[0]).write_text('unrelated installed modification')
            rejected = fixture.run('--apply')
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('drift', rejected.stderr)
            self.assertEqual(len(fixture.backups()), 1)

    def test_committed_previous_scoped_receipt_allows_upgrade(self):
        with self.fixture('--session-delivery-only', SESSION_FILES,
                          new_files=NEW_FILES, command=True) as fixture:
            first = fixture.run('--apply')
            self.assertEqual(first.returncode, 0, first.stderr)
            for name in fixture.files:
                with fixture.source_file(name).open('a') as stream:
                    stream.write('second committed update\n')
            fixture.commit()
            second = fixture.run('--apply')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(fixture.backups()), 2)
            for name, data in fixture.expected().items():
                self.assertEqual(fixture.target(name).read_bytes(), data)

    def test_receipt_hash_without_matching_committed_blob_is_rejected(self):
        with self.fixture() as fixture:
            self.assertEqual(fixture.run('--apply').returncode, 0)
            modified = b'uncommitted local modification\n'
            fixture.target(FILES[0]).write_bytes(modified)
            path = fixture.backups()[0]
            receipt = json.loads(path.read_text())
            receipt['files'][0]['after'] = hashlib.sha256(modified).hexdigest()
            path.write_text(json.dumps(receipt))
            result = fixture.run('--apply')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('drift', result.stderr)

    def test_arbitrary_ancestor_without_managed_receipt_is_rejected(self):
        with self.fixture() as fixture:
            fixture.target(FILES[0]).write_bytes(fixture.source_file(FILES[0]).read_bytes())
            fixture.source_file(FILES[0]).write_text('newest source\n')
            fixture.commit()
            result = fixture.run('--apply')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('drift', result.stderr)

    def test_command_drift_fails_before_any_runtime_replacement(self):
        with self.fixture('--session-delivery-only', SESSION_FILES,
                          new_files=NEW_FILES, command=True) as fixture:
            fixture.command.write_text('custom local command\n')
            result = fixture.run('--apply')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('drift: '+COMMAND, result.stderr)
            self.assertEqual(fixture.target('SKILL.md').read_bytes(), fixture.before['SKILL.md'])
            self.assertEqual(fixture.backups(), [])

    def test_explicit_installed_revision_proves_files_without_relaxing_drift(self):
        with self.fixture('--session-delivery-only', SESSION_FILES,
                          new_files=NEW_FILES, command=True) as fixture:
            # Model an earlier dirty-tree deployment whose bytes were committed
            # later, so its original receipt cannot establish their provenance.
            for name, data in fixture.expected().items():
                fixture.target(name).write_bytes(data)
            installed_revision = fixture.revision
            for name in fixture.files:
                with fixture.source_file(name).open('a') as stream:
                    stream.write('next source revision\n')
            fixture.commit()
            blocked = fixture.run('--dry-run')
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn('drift', blocked.stderr)
            dry = fixture.run('--dry-run', '--installed-revision', installed_revision)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual(json.loads(dry.stdout)['installed_revision'], installed_revision)
            self.assertEqual(fixture.backups(), [])
            result = fixture.run('--apply', '--installed-revision', installed_revision)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(fixture.backups()[0].read_text())['installed_revision'],
                             installed_revision)
            fixture.command.write_text('unrelated command drift\n')
            rejected = fixture.run('--apply', '--installed-revision', installed_revision)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('drift: '+COMMAND, rejected.stderr)

    def test_explicit_installed_revision_requires_known_full_commit(self):
        with self.fixture('--session-delivery-only', SESSION_FILES, new_files=NEW_FILES) as fixture:
            for revision in ('HEAD', 'f'*40):
                result = fixture.run('--apply', '--installed-revision', revision)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('installed revision must be', result.stderr)
                self.assertEqual(fixture.backups(), [])

    def test_symlink_target_and_extra_arguments_are_rejected(self):
        with self.fixture() as fixture:
            target = fixture.target(FILES[0])
            target.unlink()
            target.symlink_to(fixture.sentinels[0])
            result = fixture.run('--apply')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('regular file', result.stderr)
            result = fixture.run('--apply', '--unexpected')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(fixture.backups(), [])


if __name__ == '__main__':
    unittest.main()
