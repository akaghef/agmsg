# agmsg E2E harness

Mac-local harness for verified agmsg transport and deterministic shiritori.

## How to start (for Codex)

From the repository root:

```sh
tools/agmsg-routing/e2e/run.sh t0
tools/agmsg-routing/e2e/run.sh t1 --players codex,codex
```

T0 checks agmsg transport only. T1 runs a ten-move shiritori game; choose
`--players claude-code,codex` (the default), `--players codex,codex`, or
`--players claude-code,claude-code`. Each distinct player CLI is preflighted
once before the game starts. T1 launches nested `claude -p` and `codex exec`
processes; these do not work inside the Codex sandbox. In the Codex desktop app,
run the command with sandbox escalation / outside the sandbox and approve the
prompt. A failed preflight stops the run and records the exact error.

Results go to
`~/.local/share/akaghef-system/agmsg-e2e/runs/<run_id>/` by default. Open
`summary.md` first: it shows the tier, run/game IDs, move count, independent
transport/rules/latency/observation verdicts, and artifact directory. Use
`result.json` for per-move details and `harness-events.jsonl` for the event
timeline. `observation_ok: not_available` means no observation source is
configured; it is not a pass.

Every T0/T1 invocation creates a fresh run directory immediately, including
preflight failures. `result.json` begins with status `running`; failures update
it to `preflight_failed` or `error`. The command's final output line is
`THIS_RUN: ...` and identifies that invocation's run ID and summary path. Report
only the `THIS_RUN` line from your own invocation; never cite an older run.

```sh
tools/agmsg-routing/e2e/run.sh t0 [--moves N]
tools/agmsg-routing/e2e/run.sh t1 [--moves 10] [--deck]
tools/agmsg-routing/e2e/run.sh judge <result.json|transcript.json|transcript.jsonl>
tools/agmsg-routing/e2e/run.sh replay <run_dir>
python3 -m unittest discover -s tools/agmsg-routing/e2e/tests -v
```

Run artifacts default to `~/.local/share/akaghef-system/agmsg-e2e/runs/<run_id>/`.
For isolated tests only, `AGMSG_E2E_OUTPUT` selects a temporary output root;
`AGMSG_STORAGE_PATH` selects the agmsg temporary store. Live runs use the
installed `~/.agents/skills/agmsg/scripts` adapter and store read API. Each
message embeds `game_id` and `thread` in its JSON body because the installed
`send.sh` ignores thread and has no separate thread argument. The envelope thread
is therefore unsupported by the installed agmsg send.sh; this remains an open
integration item. Readback is filtered as the addressed
role and does not mark unrelated messages read. The four verdicts remain
independent; observation is `not_available` until a source is selected.

T1 invokes Claude Code with `claude -p --output-format json` and Codex with the
bundled CLI in read-only mode and closed stdin. The harness does not test
monitor/turn hooks. T4 is intentionally not implemented.
