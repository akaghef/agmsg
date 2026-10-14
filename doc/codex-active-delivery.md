# Codex active-turn delivery

The Codex monitor's inline inbox path supports both idle `turn/start` and active
`turn/steer`. The latter uses a native `turn/started` id, or one summary from
`thread/turns/list`, as `expectedTurnId`. Notifications from other threads cannot
change this state. This matches the schema emitted by Codex.app CLI
0.162.0-alpha.17.2. No game prompt or agent instruction is added.

`inbox.sh TEAM AGENT --peek-json` reads without acknowledgement;
`--ack ID...` acknowledges only those ids for that recipient through the existing
storage facade. The ordinary human inbox command retains its previous behavior.
The bridge revalidates eligible role pairs before reading and acknowledgement.
Only a successful app-server response allows acknowledgement.

A per-role `run/codex-bridge.TEAM.AGENT.delivery.json` file records ids, recipient
and native thread, not message bodies. `sending` is saved before the request;
`accepted` is saved before marking read. An accepted journal is acknowledged on
restart without resending. An explicit RPC rejection leaves messages unread and
removes the sending record, allowing a launcher restart to resolve fresh state.
Timeout/disconnect cannot prove whether input reached the server: leave unread
and stop on an uncertain journal rather than replay potentially delivered input.
This does not promise exactly-once delivery across an ambiguous network/crash
boundary. Such a record needs a human or verified native-log reconciliation.

A mutex serializes coincident wake/turn-ended callbacks. After accepted input the
watch re-arms even while the receiver works, so a later reply can reach an active
parent. Non-inline legacy delivery retains its idle-turn behavior.

## Scoped deployment

For the owner-approved delivery repair, use the existing managed installer:

```sh
bash src/install.sh --codex-delivery-only --dry-run
bash src/install.sh --codex-delivery-only --apply
```

It permits only `scripts/inbox.sh` and
`scripts/drivers/types/codex/codex-bridge.js`. The installed copies must match the
recorded installed base revision or the selected source bytes. It backs up those
files and records before/after hashes and source revision beneath
`~/.local/state/akaghef-system/agmsg-delivery/`, atomically replaces each file,
and checks installed hashes. It does not update hooks, skills, shims, store
schema, registrations or watcher configuration. Stop task-owned players before
applying; existing unrelated bridge processes are not restarted.

```sh
node --test tests/codex_delivery.test.js
npx bats tests/test_inbox.bats tests/test_codex_bridge.bats
```
