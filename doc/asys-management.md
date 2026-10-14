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
