#!/usr/bin/env python3
"""Isolated same-device agmsg E2E harness. Every transport assertion is backed by agmsg readback."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
LIB = HERE / "lib"
sys.path.insert(0, str(LIB))
from judge import judge_transcript, judge_t0
from acceptance import judge_acceptance, read_messages

AGMSG = Path.home() / ".agents/skills/agmsg/scripts"
TEAM = "a-sys"
ROLES = ("shiritori-a", "shiritori-b")
DECK = ["すいか", "からす", "すずめ", "めだか", "かめ", "めじろ", "ろば", "ばら", "らっぱ", "ぱんだ"]
RULES = "しりとり: 直前の語尾のかなから始まる、重複しないかな読みを1語返す。語尾をんにしない。返答はJSON {\"word\":\"ひらがな\"} のみ。"
PLAYER_SETS = {
    "claude-code,codex": ("claude-code", "codex"),
    "codex,codex": ("codex", "codex"),
    "claude-code,claude-code": ("claude-code", "claude-code"),
}


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def agmsg(*args, timeout=30):
    return subprocess.run([str(AGMSG / args[0]), *map(str, args[1:])], capture_output=True, text=True, timeout=timeout, check=False)

def parse_json(text):
    try: return json.loads(text)
    except Exception: pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try: return json.loads(line)
            except Exception: continue
    raise ValueError("CLI output did not contain JSON")

def store_messages(agent):
    p = agmsg("api.sh", "get", "teams", TEAM, "messages", "--agent", agent, "--limit", "10000")
    if p.returncode: raise RuntimeError(f"agmsg api read failed ({p.returncode}): {p.stderr.strip()}")
    out = []
    for line in p.stdout.splitlines():
        if line.strip():
            try: out.append(json.loads(line))
            except json.JSONDecodeError: continue
    return out

def game_transcript(game_id):
    """Re-read this game's moves from both addressed agmsg inboxes."""
    rows = []
    seen = set()
    for agent in ROLES:
        for msg in store_messages(agent):
            if msg.get("id") in seen:
                continue
            try: body = json.loads(msg.get("body", ""))
            except Exception: continue
            if body.get("game_id") == game_id and body.get("kind") == "request" and "word" in body:
                rows.append(body); seen.add(msg.get("id"))
    return sorted(rows, key=lambda m: m.get("move_no", 0))

def send_and_read(payload, sender, receiver, game_id):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    before = {m["id"] for m in store_messages(receiver)}
    started = time.monotonic()
    sent = agmsg("send.sh", TEAM, sender, receiver, body, "--force")
    if sent.returncode: raise RuntimeError(f"agmsg send failed ({sent.returncode}): {sent.stderr.strip()}")
    # Read through the receiver-filtered agmsg API. This avoids marking unrelated
    # unread messages in a human role's inbox while still proving store readback.
    rows = [m for m in store_messages(receiver) if m["id"] not in before and m.get("from") == sender and m.get("to") == receiver]
    selected = []
    for m in rows:
        try: value = json.loads(m.get("body", ""))
        except Exception: continue
        if value.get("game_id") == game_id and value.get("move_no", value.get("counter")) == payload.get("move_no", payload.get("counter")):
            selected.append((m, value))
    latency = round((time.monotonic() - started) * 1000)
    if len(selected) != 1: raise RuntimeError(f"expected one agmsg readback for payload, found {len(selected)}")
    msg, value = selected[0]
    return msg, value, latency

def make_run(tier, started_at_utc=None):
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    base = Path(os.environ.get("AGMSG_E2E_OUTPUT", "~/.local/share/akaghef-system/agmsg-e2e/runs")).expanduser()
    folder = base / run_id
    folder.mkdir(parents=True, exist_ok=False)
    return run_id, folder

def event(folder, name, **data):
    with (folder / "harness-events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at_utc": now(), "event": name, **data}, ensure_ascii=False) + "\n")

def write_artifacts(folder, result, *, emit_locator=False):
    if emit_locator:
        event(folder, "run_finished", status=result["status"], criteria=result["criteria"])
        result["ended_at_utc"] = now()
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = result["criteria"]
    lines = [f"# agmsg E2E {result['tier'].upper()} — {result['status']} | run_id={result['run_id']} | started_at_utc={result['started_at_utc']}", "", f"- Run: `{result['run_id']}`", f"- Game: `{result['game_id']}`", f"- Device scope: `{result['device_scope']}`", f"- Moves: {len(result['moves'])}", f"- Transport: {c['transport_ok']}", f"- Rules: {c['rules_ok']}", f"- Latency: {c['latency_ok']}", f"- Observation: {c['observation_ok']}", f"- Thread interface: game_id is carried in message JSON body; installed send API has no separate thread field", ""]
    if result.get("failure_reasons"): lines += ["## Failures", ""] + [f"- {x}" for x in result["failure_reasons"]] + [""]
    lines += [f"Artifacts: `{folder}`", ""]
    (folder / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    if emit_locator:
        print(f"THIS_RUN: run_id={result['run_id']} summary={folder / 'summary.md'}")

def base_result(tier, run_id, folder, game_id, started_at_utc=None):
    return {"schema_version": 1, "run_id": run_id, "game_id": game_id, "tier": tier, "device_scope": "mac-local", "started_at_utc": started_at_utc or now(), "ended_at_utc": None, "expected_moves": 10, "runtimes": {}, "moves": [], "faults": [], "harness_events_log": "harness-events.jsonl", "observation_records": [], "criteria": {"transport_ok": False, "rules_ok": False, "latency_ok": False, "observation_ok": "not_available"}, "status": "running", "failure_reasons": []}

def start_run(tier, expected_moves=10):
    started_at_utc = now()
    run_id, folder = make_run(tier, started_at_utc)
    result = base_result(tier, run_id, folder, "agmsg-e2e-" + run_id, started_at_utc)
    result["expected_moves"] = expected_moves
    event(folder, "run_started", tier=tier, game_id=result["game_id"])
    write_artifacts(folder, result)
    return result, folder

def fail_run(folder, result, status, error):
    result["status"] = status
    result["error"] = str(error)
    result["failure_reasons"].append(str(error))
    event(folder, "run_error", status=status, error=str(error))
    write_artifacts(folder, result, emit_locator=True)
    return 1

def run_t0(args):
    result, folder = start_run("t0", args.moves); game_id = result["game_id"]
    result["status"] = "error"
    event(folder, "observation_availability", observation_ok="not_available", reason="no observation source configured")
    try:
        for n in range(1, args.moves + 1):
            sender, receiver = ROLES[(n - 1) % 2], ROLES[n % 2]
            payload = {"game_id": game_id, "thread": game_id, "kind": "request", "counter": n, "move_no": n, "player": sender}
            event(folder, "send", move_no=n, sender=sender, receiver=receiver)
            msg, value, latency = send_and_read(payload, sender, receiver, game_id)
            ok = value == payload and msg.get("to") == receiver
            result["moves"].append({"message_id": msg["id"], "move_no": n, "player": sender, "receiver": receiver, "payload": value, "sent_at_utc": msg.get("at"), "received_at_utc": now(), "latency_ms": latency, "transport_ok": ok, "rules_ok": ok})
            event(folder, "receive", message_id=msg["id"], move_no=n, receiver=receiver, transport_ok=ok)
            if not ok: result["failure_reasons"].append(f"counter {n} payload mismatch")
        result["criteria"].update(transport_ok=len(result["moves"]) == args.moves and all(m["transport_ok"] for m in result["moves"]), rules_ok=not result["failure_reasons"], latency_ok=all(m["latency_ms"] <= 30000 for m in result["moves"]))
        result["status"] = "pass" if all(result["criteria"][k] for k in ("transport_ok", "rules_ok", "latency_ok")) else "fail"
    except Exception as e:
        result["error"] = str(e); result["failure_reasons"].append(str(e)); event(folder, "run_error", error=str(e))
        result["criteria"]["transport_ok"] = False
    finally:
        event(folder, "judge", status=result["status"], criteria=result["criteria"]); write_artifacts(folder, result, emit_locator=True)
    return 0 if result["status"] == "pass" else 1

def driver(runtime, prompt, timeout=60):
    if runtime == "claude-code":
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
    else:
        cmd = ["/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", prompt]
    started = time.monotonic()
    try: p = subprocess.run(cmd, stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as e: raise RuntimeError(f"{runtime} CLI missing: {e}")
    except subprocess.TimeoutExpired: raise RuntimeError(f"{runtime} invocation timed out after {timeout}s")
    elapsed = round((time.monotonic() - started) * 1000)
    if p.returncode:
        detail = (p.stderr or p.stdout)[-1200:]
        if runtime == "claude-code" and any(x in detail.lower() for x in ("not logged", "login", "authentication", "credential")):
            raise RuntimeError("Claude Code preflight/invocation is not authenticated. Use --players codex,codex inside the Codex sandbox, or run from an escalated unsandboxed shell where Claude Code is logged in.")
        raise RuntimeError(f"{runtime} CLI exit {p.returncode}: {detail}")
    try:
        response = parse_json(p.stdout)
        if isinstance(response.get("result"), str): response = parse_json(response["result"])
        word = response["word"]
    except Exception as e: raise RuntimeError(f"{runtime} returned invalid move JSON: {e}; output={(p.stdout or '')[-500:]}")
    if not isinstance(word, str): raise RuntimeError(f"{runtime} response word is not a string")
    return word, elapsed, p

def preflight(runtime):
    prompt = json.dumps({"check": "Reply with JSON only: {\"word\":\"あ\"}"}, ensure_ascii=False)
    try:
        driver(runtime, prompt, timeout=30)
    except Exception as e:
        if runtime == "claude-code":
            raise RuntimeError(f"Claude Code preflight failed: {e}. Fix: use --players codex,codex in the Codex sandbox, or run from an escalated unsandboxed shell with Claude Code logged in.")
        raise RuntimeError(f"Codex CLI preflight failed: {e}. Fix: ensure the bundled Codex CLI is available and authenticated in this environment.")

def run_t1(args):
    result, folder = start_run("t1", args.moves); game_id = result["game_id"]
    phase = "preflight"
    result["status"] = "error"
    try:
        runtimes = PLAYER_SETS[args.players]
        for runtime in dict.fromkeys(runtimes):
            preflight(runtime)
        phase = "setup"
        deck = DECK if args.deck else None
        if args.deck:
            (folder / "deck.json").write_text(json.dumps(DECK, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for i, role in enumerate(ROLES):
            runtime = runtimes[i]
            cli = "claude -p" if runtime == "claude-code" else "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex exec"
            invocation_config = {"cli": cli, "timeout_seconds": 60, "stdin": "devnull", "sandbox": "read-only" if runtime == "codex" else None, "output_format": "json" if runtime == "claude-code" else None, "skip_git_repo_check": runtime == "codex"}
            result["runtimes"][role] = {"runtime": runtime, "cli": cli, "prompt_sha256": [], "config_sha256": hashlib.sha256(json.dumps(invocation_config, sort_keys=True).encode()).hexdigest(), "config_hash_scope": "harness invocation settings; ambient runtime config not read"}
        result["delivery_mode"] = "one-shot CLI; monitor/turn hooks bypassed and not verified"
        event(folder, "observation_availability", observation_ok="not_available", reason="no observation source configured")
        phase = "game"
    except Exception as e:
        return fail_run(folder, result, "preflight_failed" if phase == "preflight" else "error", e)
    previous = None
    try:
        for n in range(1, args.moves + 1):
            role = ROLES[(n - 1) % 2]; receiver = ROLES[n % 2]
            transcript = game_transcript(game_id)
            used_words = [m["word"] for m in transcript]
            rule_text = RULES + " Do not reuse any of these already-used words: " + json.dumps(used_words, ensure_ascii=False) + "." + (f" このfixtureでは今回の語は{deck[n-1]}にする。" if deck else "")
            prompt_obj = {"rules": rule_text, "game_id": game_id, "move_no": n, "previous_word": previous, "already_used_words": used_words}
            prompt = json.dumps(prompt_obj, ensure_ascii=False)
            result["runtimes"][role]["prompt_sha256"].append(hashlib.sha256(prompt.encode()).hexdigest())
            runtime = runtimes[ROLES.index(role)]
            word, invoke_ms, proc = driver(runtime, prompt)
            if deck and word != deck[n - 1]: raise RuntimeError(f"{role} fixture mismatch on move {n}: expected {deck[n-1]}, got {word}")
            payload = {"game_id": game_id, "thread": game_id, "kind": "request", "move_no": n, "previous_word": previous, "word": word, "player": role}
            event(folder, "send", move_no=n, sender=role, receiver=receiver)
            msg, value, latency = send_and_read(payload, role, receiver, game_id)
            result["moves"].append({"message_id": msg["id"], **value, "sent_at_utc": msg.get("at"), "received_at_utc": now(), "latency_ms": latency, "invocation_ms": invoke_ms, "transport_ok": value == payload, "player_result": "returned"})
            (folder / f"{role}-{n:02d}.stdout.txt").write_text(proc.stdout[-4000:], encoding="utf-8")
            if proc.stderr: (folder / f"{role}-{n:02d}.stderr.txt").write_text(proc.stderr[-4000:], encoding="utf-8")
            previous = word
            event(folder, "player_result", role=role, move_no=n, invocation_ms=invoke_ms)
            event(folder, "receive", message_id=msg["id"], receiver=receiver, move_no=n, latency_ms=latency)
        judged = judge_transcript(result["moves"], expected_moves=args.moves)
        result["criteria"] = judged["criteria"]; result["status"] = judged["status"]
        result["failure_reasons"] = judged["failure_reasons"]
        result["judge"] = judged
    except Exception as e:
        result["status"] = "error"
        result["failure_reasons"].append(str(e)); result["error"] = str(e); result["criteria"]["transport_ok"] = bool(result["moves"]) and all(m.get("transport_ok") for m in result["moves"])
        result["judge"] = judge_transcript(result["moves"], expected_moves=args.moves)
        event(folder, "run_error", error=str(e))
    finally:
        event(folder, "judge", status=result["status"], criteria=result["criteria"]); write_artifacts(folder, result, emit_locator=True)
    return 0 if result["status"] == "pass" else 1

def replay(path):
    folder = Path(path).expanduser(); data = json.loads((folder / "result.json").read_text())
    judged = judge_t0(data["moves"], data.get("game_id"), data.get("expected_moves", len(data["moves"]))) if data.get("tier") == "t0" else judge_transcript(data["moves"], expected_moves=10)
    print(json.dumps(judged, ensure_ascii=False, indent=2)); return 0 if judged["status"] == "pass" else 1

def run_accept_judge(args):
    import glob
    stores = [Path.home() / ".agents/skills/agmsg/db/messages.db"]
    stores.extend(Path(p) for p in glob.glob(str(Path.home() / ".agents/skills/agmsg/db/teams/*/messages.db")))
    if os.environ.get("AGMSG_E2E_TEST_STORES"):
        stores = [Path(p) for p in os.environ["AGMSG_E2E_TEST_STORES"].split(os.pathsep)]
    messages = read_messages(args.team, args.since, stores)
    result = judge_acceptance(messages, team=args.team, parent=args.parent, since=args.since, prompt_level=args.prompt_level, parent_reported_seconds=args.parent_reported_seconds, human_interventions=args.human_interventions)
    run_id, folder = make_run("acceptance")
    result.update(run_id=run_id, started_at_utc=now(), ended_at_utc=now())
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# agmsg E2E acceptance — {result['status']} | run_id={run_id}", "", f"- Team: `{args.team}`", f"- Parent: `{args.parent}`", f"- Prompt level: {args.prompt_level}", f"- Human interventions: {args.human_interventions}", f"- Moves: {len(result['moves'])}", f"- Parent reported elapsed seconds: {args.parent_reported_seconds}", f"- Store computed elapsed seconds: {result['judge_elapsed_seconds']}", f"- Criteria: `{json.dumps(result['criteria'], ensure_ascii=False)}`", f"- Unparsed move-like messages: {len(result['unparsed_messages'])}", ""]
    if result["failure_reasons"]: lines += ["## Failures", ""] + [f"- {x}" for x in result["failure_reasons"]] + [""]
    lines += [f"Artifacts: `{folder}`", ""]
    (folder / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"THIS_RUN: run_id={run_id} summary={folder / 'summary.md'}")
    return 0 if result["status"] == "pass" else 1

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name, default in (("t0", 10), ("t1", 10)):
        p = sub.add_parser(name)
        p.add_argument("--moves", type=int, default=default, choices=[10] if name == "t1" else None)
        if name == "t1":
            p.add_argument("--deck", action="store_true")
            p.add_argument("--players", choices=PLAYER_SETS, default="claude-code,codex")
    p = sub.add_parser("judge"); p.add_argument("source")
    p = sub.add_parser("replay"); p.add_argument("run_dir")
    p = sub.add_parser("accept-judge")
    p.add_argument("--team", required=True); p.add_argument("--parent", required=True); p.add_argument("--since", required=True)
    p.add_argument("--prompt-level", choices=("P0", "P1", "P2"), default="P0")
    p.add_argument("--parent-reported-seconds", type=float); p.add_argument("--human-interventions", type=int, default=0)
    a = parser.parse_args()
    if a.command == "t0": return run_t0(a)
    if a.command == "t1": return run_t1(a)
    if a.command == "accept-judge": return run_accept_judge(a)
    if a.command == "judge":
        source = Path(a.source)
        raw = source.read_text(encoding="utf-8")
        try: data = json.loads(raw)
        except json.JSONDecodeError: data = [json.loads(line) for line in raw.splitlines() if line.strip()]
        moves = data.get("moves", []) if isinstance(data, dict) else data
        result = judge_t0(moves, data.get("game_id"), data.get("expected_moves", len(moves))) if isinstance(data, dict) and data.get("tier") == "t0" else judge_transcript(moves, expected_moves=10)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "pass" else 1
    return replay(a.run_dir)

if __name__ == "__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: sys.exit(130)
