#!/usr/bin/env python3
"""Best-effort post-commit journal. Never reads the agmsg message store."""
import datetime
import json
import os
from pathlib import Path
import stat
import sys
import time


def append(record, path):
    path = Path(path).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('journal must be a regular file')
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(path, 0o600)
        # A bounded lock makes concurrent large UTF-8 lines safe without holding
        # up sends behind a failed observer/writer. Windows uses a one-byte lock.
        deadline = time.monotonic() + .15
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.005)
        payload = (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('short journal write')
            view = view[written:]
    finally:
        os.close(fd)


def main(args):
    message_id, team, sender, recipient, realm, kind, thread, pid, ppid = args
    keys = ('CLAUDE_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'AGMSG_SESSION_ID')
    ids = {key: os.environ[key] for key in keys if os.environ.get(key)}
    preferred = next(((key, ids[key]) for key in keys if key in ids), (None, None))
    runtime = 'claude' if preferred[0] and preferred[0].startswith('CLAUDE') else 'codex' if preferred[0] and preferred[0].startswith('CODEX') else None
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    record = dict(schema='agmsg.send-journal.v1', message_id=message_id, ts=ts,
                  realm=realm, team=team, kind=kind, thread=thread, body=sys.stdin.read(),
                  source=dict(runtime=runtime, session_id=preferred[1], session_ids=ids,
                              pid=int(pid), ppid=int(ppid), cwd=os.getcwd()))
    record.update({'from': sender, 'to': recipient})
    path = os.environ.get('AGMSG_SEND_JOURNAL') or str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'agmsg/send-journal.jsonl')
    append(record, path)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception:
        # The committed message and the caller's stdout/status are authoritative.
        # Journal errors must not make a successful send appear failed/retryable.
        pass
