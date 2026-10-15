# A-sys management of agmsg

The canonical source is the `akaghef/agmsg` fork, branch
`codex/asys-canonical`, checked out as the A-sys submodule `systems/agmsg`.
Its upstream is `fujibee/agmsg`. The migration base is `v1.2.2`, matching the
installed runtime. Advancing to a newer upstream release is a separate update.

The fork retains the upstream layout. A-sys routing, hooks, device adapters,
watcher and E2E harness live in `mod/asys-routing`; the install entry point is
`src/install.sh`, management documentation lives in `doc`, and migration
provenance in `repo`. The A-sys parent retains the
cross-system Inko and agmsg protocols.

`~/.agents/skills/agmsg` is a generated runtime installation, not a source
checkout. Installation reuses the upstream `install.sh --update` followed by
the existing A-sys routing installer. The entry point backs up code and records
the source commit. The upstream updater preserves DB/team contents; it may
correct old team-config permissions, using its existing migration behavior.
The routing installer merges its existing hooks and seeds its existing watcher.
Do not symlink the entire installation to the
fork: upstream storage defaults are relative to the installed script paths.

From the A-sys root:

```sh
git submodule update --init systems/agmsg
bash systems/agmsg/src/install.sh --dry-run
bash systems/agmsg/src/install.sh --apply
```

Do not run the upstream `npx agmsg` / `setup.sh` update route over this managed
installation: it would replace the fork's changes. Update the fork, verify it,
commit and push, update the parent gitlink, and deploy that commit instead.
The `upstream` remote is local Git configuration; after a fresh checkout add
`https://github.com/fujibee/agmsg.git` as `upstream` before fetching changes.

Verification:

```sh
bash systems/agmsg/mod/asys-routing/tests/test_routing.sh
python3 -m unittest discover -s systems/agmsg/mod/asys-routing/e2e/tests -v
```

SkillPort is a distribution pointer to this source, not a second editable
copy. Its former v1.1.0 code and local diff are preserved in
`repo/legacy-skillport-source.zip` and `doc/migration/skillport-local.patch`.
The old direct-SQL message schema is not overlaid on the v1.2.2 event store.
Older compatibility files left in the runtime installation are preserved in
`repo/legacy-installed-source.zip`; they are not shipped by the fork's updater.
Migration provenance and archive hashes are in
`doc/migration/source-inventory.json`.

Transport acceptance, recipient input, recipient response, and delivery of
that response back to the originating session are separate verification
gates. Source migration alone does not establish Desktop-to-Desktop push.

The experimentally verified Claude-command-to-Codex Desktop route is documented
in [Codex Desktop IPC sending](codex-desktop-ipc-send.md), with a separate
[verification record](verification/claude-to-codex-ipc-261009.md).
It is not yet an agmsg delivery adapter.

## Committed-send journal

`storage_send` in both built-in drivers and the routing outbox writer append
one `agmsg.send-journal.v1` JSON line after their successful write. This is
observation data, not a replacement store or the delivery/acceptance judge.
The database schema and normal command output are unchanged. Shell functions,
loops, variable expansion and redirected stdout cannot hide the committed body
from this hook.

Default file: `${XDG_STATE_HOME:-$HOME/.local/state}/agmsg/send-journal.jsonl`.
`AGMSG_SEND_JOURNAL` overrides the file for tests or a managed installation.
Rows include the actual message ID, millisecond UTC timestamp, realm, team,
from/to, kind, thread, body and available native session IDs plus PID/cwd.
Direct storage writes default to local/message; route sends preserve realm/kind.
`AGMSG_SEND_THREAD` supplies optional thread metadata. A remote journal entry
means the local outgoing packet was written; it does not prove remote receipt.

Files are private (0600). Concurrent append uses a bounded lock. Every journal
failure, including a missing helper or Python runtime, is fail-open: the
already-committed send remains successful. Such a failure can lose observation
records; it must never trigger a duplicate message retry. There is no database
readback, message-body argv, new daemon, or hook configuration in this path.
Custom third-party storage drivers must call the same post-commit helper to
participate; the managed built-in SQLite and JSONL drivers already do.

Use the existing managed installer for this bounded update:

```sh
bash systems/agmsg/src/install.sh --send-journal-only --dry-run
bash systems/agmsg/src/install.sh --send-journal-only --apply
python3 -m unittest discover -s systems/agmsg/tests -p test_send_journal.py -v
```

The scoped installer backs up replaced files and records their before/after
hashes. It updates the helper, both built-in writers and route script without
rerunning hook merging, storage migration, or watcher installation. Tests set
an isolated journal path so fixtures never enter the live telemetry stream.
