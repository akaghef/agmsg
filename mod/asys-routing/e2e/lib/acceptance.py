"""After-the-fact store judge for the parent initiated child workflow."""
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from judge import chain_endpoints, judge_transcript

KANA_TOKEN = re.compile(r"(?<![ぁ-ゖァ-ヺー])([ぁ-ゖァ-ヺー]+)(?![ぁ-ゖァ-ヺー])")
MOVE_PREFIX = re.compile(r"^(?:T(?P<tno>\d+)\s+|DONE\s+T(?P<done_no>\d+)\s+|move\s+(?P<mno>\d+)\s+|TURN\s+(?P<turn_no>\d+)(?:\s*/\s*\d+)?\s*:?\s*)?", re.I)


def parse_move(body, order):
    try:
        value = json.loads(body)
        if isinstance(value, dict) and isinstance(value.get("word"), str):
            return value["word"], value.get("move_no", order)
    except (json.JSONDecodeError, TypeError):
        pass
    text = (body or "").strip()
    prefix = MOVE_PREFIX.match(text)
    move_no = next((int(prefix.group(key)) for key in ("tno", "done_no", "mno", "turn_no") if prefix and prefix.group(key)), order)
    remainder = text[prefix.end():] if prefix else text
    tokens = [token.strip("。、.!！?？「」『』()（）") for token in remainder.split()]
    tokens = [token for token in tokens if token]
    return (tokens[-1], move_no) if tokens and KANA_TOKEN.fullmatch(tokens[-1]) else (None, None)


def has_explicit_move_no(body):
    try:
        value = json.loads(body)
        if isinstance(value, dict): return isinstance(value.get("word"), str) and "move_no" in value
    except (json.JSONDecodeError, TypeError):
        pass
    prefix = MOVE_PREFIX.match((body or "").strip())
    return bool(prefix and any(prefix.group(k) for k in ("tno", "done_no", "mno", "turn_no")))


def read_messages(team, since, stores):
    rows = []
    for path in stores:
        if not Path(path).is_file():
            continue
        uri = f"file:{Path(path).resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            columns = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
            if not {"team", "from_agent", "body", "created_at"} <= columns:
                continue
            select = [c for c in ("id", "message_id", "team", "from_agent", "to_agent", "thread", "kind", "body", "created_at") if c in columns]
            quoted = ",".join('"' + c + '"' for c in select)
            rows.extend(dict(r) for r in db.execute(f"SELECT {quoted} FROM messages WHERE team=? AND julianday(created_at)>=julianday(?)", (team, since)))
    def chronology(row):
        stamp = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc), str(row.get("id", ""))
    return sorted(rows, key=chronology)


def judge_acceptance(messages, *, team, parent, since, prompt_level="P0", parent_reported_seconds=None, human_interventions=0):
    errors, moves, unparsed, parent_move_messages, control = [], [], [], [], []
    for order, row in enumerate(messages, 1):
        word, move_no = parse_move(row.get("body", ""), order)
        if parent and row.get("to_agent") == parent and not has_explicit_move_no(row.get("body", "")):
            # Messages to the parent without an explicit move number (READY, completion reports
            # that list the chain) are control traffic. A numbered final move to the parent
            # (e.g. "DONE T9 <word>") still counts as a move.
            control.append({"message_id": row.get("message_id") or row.get("id"), "from_agent": row["from_agent"], "to_agent": row.get("to_agent"), "created_at": row["created_at"]})
            continue
        if word is None:
            # Preserve candidate move-like traffic for audit; routine control messages are omitted.
            # Unparsed traffic to or from the parent is setup/report (rules, START, completion),
            # not a game move: a parent relay is still caught because relayed moves parse as moves.
            if parent in (row.get("from_agent"), row.get("to_agent")):
                control.append({"message_id": row.get("message_id") or row.get("id"), "from_agent": row["from_agent"], "to_agent": row.get("to_agent"), "created_at": row["created_at"]})
                continue
            if re.search(r"しりとり|move|word|語|手番|\bT\d+\b|\bDONE\b", row.get("body", ""), re.I):
                unparsed.append({"message_id": row.get("message_id") or row.get("id"), "from_agent": row["from_agent"], "created_at": row["created_at"], "body": row.get("body", "")})
            continue
        row_session = None
        try:
            payload = json.loads(row.get("body", ""))
            row_session = payload.get("session_id", payload.get("session")) if isinstance(payload, dict) else None
        except Exception:
            payload = {}
        item = {"message_id": str(row.get("message_id") or row.get("id")), "from_agent": row["from_agent"], "word": word, "move_no": move_no, "created_at": row["created_at"], "session_id": row_session or f"agent-session:{row['from_agent']}"}
        moves.append(item)
        if row["from_agent"] == parent:
            parent_move_messages.append(item["message_id"])
    children = list(dict.fromkeys(m["from_agent"] for m in moves if m["from_agent"] != parent))
    if len(children) != 3: errors.append(f"expected_3_child_senders_got_{len(children)}")
    if len(moves) != 9: errors.append(f"expected_9_moves_got_{len(moves)}")
    sessions = {c: {m["session_id"] for m in moves if m["from_agent"] == c and m["session_id"]} for c in children}
    if any(len(sessions.get(c, set())) != 1 for c in children) or len({next(iter(v)) for v in sessions.values() if len(v) == 1}) != len(children):
        errors.append("children_must_have_distinct_sessions")
    if parent_move_messages: errors.append("parent_relayed_move")
    if unparsed: errors.append("unparsed_move_like_messages_present")
    for i, m in enumerate(moves):
        expected = children[i % 3] if len(children) == 3 else None
        if m["from_agent"] == parent or (expected and m["from_agent"] != expected):
            errors.append(f"move_order_violation_at_{i+1}")
    canonical = []
    prev = None
    for i, m in enumerate(moves, 1):
        player = "shiritori-a" if i % 2 else "shiritori-b"
        canonical.append({"message_id": m["message_id"], "move_no": m["move_no"], "player": player, "word": m["word"], "previous_word": prev, "transport_ok": True, "latency_ms": 0})
        prev = m["word"]
    kana = judge_transcript(canonical, expected_moves=9)
    errors.extend(kana["failure_reasons"])
    # --since/run kickoff is the workflow start; elapsed ends at the final move.
    times = ([messages[0]["created_at"]] if messages else []) + [m["created_at"] for m in moves]
    elapsed = None
    if times:
        from datetime import datetime
        try:
            elapsed = (datetime.fromisoformat(times[-1].replace("Z", "+00:00")) - datetime.fromisoformat(times[0].replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            errors.append("invalid_move_timestamp")
    if parent_reported_seconds is None: errors.append("parent_elapsed_time_not_reported")
    if prompt_level not in ("P0", "P1", "P2"): errors.append("invalid_prompt_level")
    result = {"schema_version": 1, "tier": "acceptance", "team": team, "parent": parent, "since": since, "prompt_level": prompt_level, "human_interventions": human_interventions, "parent_reported_seconds": parent_reported_seconds, "judge_elapsed_seconds": elapsed, "child_senders": children, "child_sessions": {k: sorted(v) for k, v in sessions.items()}, "moves": moves, "unparsed_messages": unparsed, "parent_control_messages": control, "parent_move_message_ids": parent_move_messages, "criteria": {"three_children": len(children) == 3, "nine_valid_moves": len(moves) == 9 and kana["criteria"]["rules_ok"], "round_robin": not any("move_order_violation" in e for e in errors), "no_parent_relay": not parent_move_messages, "parent_reported_elapsed": parent_reported_seconds is not None, "judge_elapsed_computed": elapsed is not None, "sessions_distinct": "children_must_have_distinct_sessions" not in errors, "unparsed_messages_clear": not unparsed}, "failure_reasons": errors, "status": "pass" if not errors else "fail"}
    return result
