# PR2.5 verification

Verification date: 2026-10-15, macOS workspace sandbox. The installed agmsg,
Akaghef-System working files, and dashboard were not modified. No push or live
Desktop IPC delivery was performed. Test homes, stores, logs, and temporary
checkouts were isolated under `TMPDIR`.

Commit creation is blocked in this session. `git add` failed before staging with
`Operation not permitted` while creating
`/Users/akaghef/dev/Akaghef-System/.git/modules/systems/agmsg/worktrees/session-delivery/index.lock`.
The directories have ordinary user-owned write permissions, but the effective
execution environment denied the operation. The 45 changes remain in the worktree;
no commit was created. Commit them before applying the scoped deployment so its
backup records a source revision that actually contains these bytes.

The full Bats suite is not green. All 1,647 unique cases across 87 files were
attempted, with no missing or unmatched cases. Results combine batch runs with
targeted final rechecks; they are not one monolithic successful execution.

## Results

| Check | Result |
| --- | --- |
| Node test suite | 168 passed, 0 failed, 0 skipped |
| Root Python tests | 21 passed: scoped installer 11, send results 7, SessionStart summary 3 |
| Routing Python tests | 7 passed |
| End-to-end Python tests | 14 passed |
| npm package smoke test | Passed |
| Bats suite | 1,440 passed, 181 failed, 17 skipped, 9 blocked |
| Changed shell/JavaScript syntax and whitespace | Passed |
| Managed installer read-only preflight | Passed, exactly 23 targets on this installation |
| Enforced assertion audit | Failed: 625 existing unenforceable assertions versus baseline 638; baseline unchanged |

The Node total includes 21 Desktop protocol tests and 8 bridge recovery tests.
Those use framed in-memory streams through a `net.createConnection` test double,
not the real Desktop socket. Bound/unbound sessions, idle/active routing,
owner/request/turn correlation, rejection, ambiguous timeout, and accepted-state
acknowledgement recovery are covered. Membership/lock tests passed 39/39 and
Codex resume/recorder tests passed 33/33; these are included in the Bats total.

Existing timing assertions were retained. The bridge's 10-second deadline passed
after removing redundant registry scans while preserving the full roster check
immediately before delivery. Test fixture updates explicitly join the intended
session before exercising previously implicit subscriptions; they retain the
delivery, control-message, replacement, and cleanup assertions.

The final despawn broad-watcher recheck passed with its original two-second
observation window. An intermediate extended-window diagnostic is excluded from
the final result. One concurrent-join case initially failed under load, then
passed an unchanged focused rerun; both observations are retained.

The case ledger, observation history, coverage audit, and runner manifests are
under `$TMPDIR/agmsg-pr25-suite-batches/`: `case-ledger.json`,
`case-history.json`, and `ledger-summary.json`. Earlier focused evidence includes
explicitly labeled transcriptions of tool TAP output; full batches and final
fixture rechecks have raw logs. Membership/recorder evidence records affected
case rechecks after the final changes, rather than claiming all cases were
repeated on one immutable snapshot.

## Environment and baseline limitations

Native loopback TCP/Unix socket binding is denied with `EPERM`. Process argument
inspection through `ps`/`pgrep` is also denied. Native integration tests depending
on these capabilities cannot establish their intended behavior here. Interrupted
runner output is not counted as a test assertion failure; cases that cannot
complete are recorded separately as blocked attempts.

| Completed failure category | Cases |
| --- | ---: |
| TCP fixture startup | 159 |
| Native process identification/startup/child-count dependencies | 18 |
| Denied descriptor write under `/dev/fd` | 1 |
| Unchanged assertion ratchet mismatch | 2 |
| Pre-existing `SKILL.md` heading mismatch | 1 |

Native process dependency is a classification, not proof that all 18 failures
were reproduced on the starting commit. Eight roster cases and one Codex
monitor case were blocked. An isolated archive of the starting commit reproduced
a representative roster hang with the same source/test bytes. The monitor
fixture waits indefinitely for a port file after socket binding is denied.
The 17 existing skips cover Windows/MSYS conditions (12), a Unix socket sandbox
condition (1), POSIX command-name shape (1), and JSONL backend conditions (3).

The template routing check expects a `Step 2a` heading absent from both the
starting commit and the final `SKILL.md`. This pre-existing source/test layout
mismatch was retained. The static assertion audit requires an exact baseline;
strengthening/removing old ineffective assertions reduced the count from 638 to
625. The baseline was not changed without the requested approval.

Seven isolated blocked roster process groups, plus the isolated baseline
reproduction, were terminated and reaped; their groups were verified absent.
Final delivery rechecks also ended with their process group absent. Cleanup of
earlier non-isolated interrupted runs and focused watchers could not be fully
verified because process inspection is denied. No global kill or signalling of
unverified old process identifiers was performed.

App and Server tests/typechecks/builds were not run: both `node_modules`
directories are absent, and no PostgreSQL test database was provisioned.
The App also lacks `app/src-tauri/resources/agmsg-core`; its canonical bundler
fetches the pinned upstream resource. Offline locked Cargo metadata failed with
exit 101 because the `base64` crate is unavailable in the local cache. No
dependencies or resources were downloaded to route around these limits.

## Reproduction

Use the existing Bats runner against `tests/`, or the repository's
`.github/scripts/shard-tests.sh` partitions, on a host that permits socket binding
and process inspection. This run used the already cached Bats executable with
`--print-output-on-failure`, file manifests, and exact-name remainder filters.

```sh
bats --print-output-on-failure tests/
node --test --test-concurrency=1 tests/*.test.*
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
bash .github/scripts/check-enforced-assertions.sh
```

Run the routing and end-to-end Python suites with isolated homes as well. The
unchanged static assertion baseline currently reports the mismatch above.

The Director's scoped deployment and lifecycle prerequisites are in
[session-scoped-delivery.md](session-scoped-delivery.md). The scoped installer
backs up all targets before replacing them and preserves hooks/settings/state.
Existing delivery processes need restarting, and sessions must explicitly join
after deployment. SessionEnd configuration/emission needs verification on the
deployment host. A SIGKILL or host crash can leave a membership mutation guard;
only remove it after independently confirming no mutation owns it. Ambiguous
IPC journals deliberately prevent automatic replay and require reconciliation.

## Changed files

45 files changed:

```text
SKILL.md
doc/session-scoped-delivery-verification.md
doc/session-scoped-delivery.md
mod/asys-routing/hooks/session-start.sh
mod/asys-routing/route.sh
mod/asys-routing/tests/test_routing.py
scripts/actas-claim.sh
scripts/check-inbox.sh
scripts/delivery.sh
scripts/drivers/types/claude-code/template.md
scripts/drivers/types/codex/_session-start.sh
scripts/drivers/types/codex/codex-bridge-launcher.sh
scripts/drivers/types/codex/codex-bridge.js
scripts/drivers/types/codex/codex-desktop-ipc.js
scripts/drivers/types/codex/codex-record-session.sh
scripts/drivers/types/codex/eligible-pairs.sh
scripts/drivers/types/codex/template.md
scripts/drivers/types/codex/watch-once.sh
scripts/leave.sh
scripts/lib/actas-lock.sh
scripts/lib/role-session.sh
scripts/lib/subscription.sh
scripts/session-end.sh
scripts/session-start.sh
scripts/watch.sh
src/install.sh
tests/codex_delivery.test.js
tests/codex_desktop_ipc.test.js
tests/test_actas_integration.bats
tests/test_active_membership.bats
tests/test_codex_bridge.bats
tests/test_codex_bridge_launcher.bats
tests/test_codex_resume.bats
tests/test_delivery.bats
tests/test_despawn.bats
tests/test_inbox.bats
tests/test_messaging.bats
tests/test_resolve_project.bats
tests/test_scoped_delivery_install.py
tests/test_session_start_summary.py
tests/test_storage.bats
tests/test_sync_autostart.bats
tests/test_watch.bats
tests/test_watch_install_changed.bats
tests/test_watch_once.bats
```
