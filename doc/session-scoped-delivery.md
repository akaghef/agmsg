# Session-scoped delivery (PR2.5)

A project registration is an address-book entry. A session receives automatic
team mail only after an explicit `actas` in that session. Claude uses its native
session ID; Codex uses `CODEX_THREAD_ID`. No recent-rollout or project-wide
fallback grants receive permission. Unclaimed role mail remains unread.

`run/role-session.*` remains advisory resume history. Separate
`run/role-active.*` records bind a role to its native session and actas owner.
Delivery must match both the active record and current ownership. Claude
Monitor, Stop-hook inbox delivery, SessionStart output, and both Codex bridge
transports use that binding. Historical resume alone never joins a session.

Use the existing `actas-claim.sh` flow for Claude and
`drivers/types/codex/codex-record-session.sh TEAM ROLE [PROJECT]` for Codex.
`leave.sh PROJECT TYPE ROLE [NATIVE_SESSION]` removes only the caller's matching
membership, preserving registration and resume history. Codex requires
`CODEX_THREAD_ID`; Claude supplies its native session argument. Where the runtime
invokes the configured SessionEnd hook, it uses the same
matching-owner cleanup. A new session must explicitly join again. The scoped
installer preserves hook configuration: projects without SessionEnd need their
existing delivery mode reapplied through `delivery.sh` before relying on
automatic cleanup. Desktop native SessionEnd emission has not been verified
live; explicitly `leave` before closing when that event is unavailable.

## Codex Desktop transport

The existing Codex bridge accepts `--desktop` (the default Desktop socket) or
`--desktop-ipc PATH`, together with `--thread THREAD --inline-inbox` and its
existing project/role arguments. It connects to `~/.codex/ipc/ipc.sock`, initializes
a distinct client, discovers the thread owner, follows that thread's native
state, then issues `thread-follower-start-turn` version 2 when idle or
`thread-follower-steer-turn` version 1 when active. Unknown state fails closed.
The request inherits the thread's settings. No model or approval changes occur.

The adapter reuses the bridge's delivery journal and acknowledgement path.
The bridge writes `sending` before submission and `accepted` only after a
matching successful response with a turn ID. Only then does it acknowledge the
selected unread messages. An accepted record can finish acknowledgement after
restart without submitting the input again. Explicit rejection leaves mail
unread. Timeout, disconnect, malformed response, or uncertain outcome leaves mail
unread with a journal and blocks automatic replay. Correlation details remain in
the journal, outside ordinary human-facing messages.

Acceptance of an IPC request is distinct from observing target input, an AI
response, and delivery of a reply. The IPC tests use framed in-memory streams
through a `net.createConnection` test double and isolated stores. The sandbox
denied native socket binding; no live Desktop delivery is claimed.

## Scoped installation

From the committed worktree, the Director can preview and apply the exact
PR2.5 deployment manifest:

```sh
bash src/install.sh --session-delivery-only --dry-run \
  --installed-revision 96a5f25638f1ab7188e118e59c0458bf6ea69c1d
bash src/install.sh --session-delivery-only --apply \
  --installed-revision 96a5f25638f1ab7188e118e59c0458bf6ea69c1d
```

The explicit installed revision proves the current installed files against the
committed predecessor; older scoped receipts recorded dirty source and cannot
on their own prove those bytes. Other local modifications still stop the install.

This uses the managed installer's explicit file list, drift checks, before/after
hashes and backup archive under
`~/.local/state/akaghef-system/agmsg-delivery/`. It changes only the listed runtime
and command files, including the existing generated Claude command when present.
It does not migrate the database or rewrite hooks/settings. For a project that
lacks SessionEnd, the Director can use the existing configuration entry point
(e.g. `bash ~/.agents/skills/agmsg/scripts/delivery.sh set monitor codex PROJECT`).
Use the project's intended mode; do not enable project-wide Codex turn delivery.
The updated turn-mode installer also installs SessionEnd for Claude/Codex.
Existing processes keep their loaded code: restart task-owned delivery processes
before relying on the new membership gate. Sessions must explicitly `actas`
after deployment; old historical records do not become active memberships.

Membership mutations serialize through a per-role guard. Normal exits and
catchable termination signals remove the acquired guard. SIGKILL or host failure
can leave it behind and block later claim/leave operations. Recovery requires
independently confirming that no mutation still owns that exact guard before
removing its empty directory and retrying the explicit operation. There is no
automatic blind removal. Bundle replacement is atomic per file, not across the
entire installation; the backup supports recovery from an interrupted install.

The socket protocol is private and can change with Codex Desktop updates.
An absent/inaccessible socket or unrecognized state is a failed transport,
never a reason to resume another process or append history as a substitute.
