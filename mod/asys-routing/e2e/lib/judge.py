import unicodedata

SMALL = str.maketrans({"ゃ":"や", "ゅ":"ゆ", "ょ":"よ", "ぁ":"あ", "ぃ":"い", "ぅ":"う", "ぇ":"え", "ぉ":"お", "ゎ":"わ"})
KANA = set("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをん")


def normalize_word(word):
    word = unicodedata.normalize("NFC", word)
    out = []
    for c in word:
        if "ァ" <= c <= "ヶ":
            c = chr(ord(c) - 0x60)
        out.append(c)
    return "".join(out).translate(SMALL).replace("っ", "つ")


def chain_endpoints(word):
    normalized = normalize_word(word)
    if normalized.startswith("ー"):
        return None
    effective = [c for c in normalized if c != "ー"]
    if not effective or any(c not in KANA for c in effective):
        return None
    return effective[0], effective[-1]


def judge_transcript(moves, expected_moves=10, injected_duplicate_ids=None):
    injected_duplicate_ids = set(map(str, injected_duplicate_ids or []))
    errors, seen, message_ids, previous, last_no = [], set(), set(), None, 0
    expected_player = "shiritori-a"
    move_results = []
    for index, move in enumerate(moves):
        ident = str(move.get("message_id", move.get("move_no", index + 1)))
        n, player, word = move.get("move_no"), move.get("player"), move.get("word")
        local_errors = []
        if ident in message_ids: local_errors.append("duplicate_message_id")
        message_ids.add(ident)
        if not all(k in move for k in ("move_no", "player", "previous_word", "word")): local_errors.append("malformed_payload")
        if not isinstance(n, int) or n != last_no + 1: local_errors.append("gap_or_order")
        if player != expected_player: local_errors.append("player_order")
        if not isinstance(word, str) or not word: local_errors.append("malformed_word")
        endpoints = chain_endpoints(word) if isinstance(word, str) else None
        if not endpoints: local_errors.append("invalid_kana")
        else:
            head, tail = endpoints
            if previous is not None and head != previous: local_errors.append("chain_mismatch")
            expected_previous_word = moves[index - 1].get("word") if index else None
            if move.get("previous_word") != expected_previous_word: local_errors.append("previous_word_mismatch")
            normalized = normalize_word(word)
            if normalized in seen: local_errors.append("duplicate_word")
            if tail == "ん": local_errors.append("ends_in_n")
            seen.add(normalized)
            previous = tail
        if local_errors: errors.extend(f"move {n}: {e}" for e in local_errors)
        move_results.append({"message_id": move.get("message_id"), "move_no": n, "errors": local_errors, "rules_ok": not local_errors})
        if isinstance(n, int): last_no = n
        expected_player = "shiritori-b" if expected_player == "shiritori-a" else "shiritori-a"
    if len(moves) != expected_moves: errors.append(f"expected_{expected_moves}_moves_got_{len(moves)}")
    transport_ok = bool(moves) and all(m.get("transport_ok", True) for m in moves)
    latency_ok = bool(moves) and all(m.get("latency_ms", 0) <= 30000 for m in moves)
    duplicate_ids = [str(m.get("message_id", m.get("move_no"))) for m in moves if "duplicate_word" in next((x["errors"] for x in move_results if x["move_no"] == m.get("move_no")), [])]
    duplicate_ok = not duplicate_ids or (set(duplicate_ids) <= injected_duplicate_ids)
    return {"criteria": {"transport_ok": transport_ok, "rules_ok": not errors, "latency_ok": latency_ok, "observation_ok": "not_available"}, "status": "pass" if transport_ok and not errors and latency_ok else "fail", "failure_reasons": errors, "moves": move_results, "duplicate_evidence": {"duplicate_message_ids": duplicate_ids, "injected_ids": sorted(injected_duplicate_ids), "injected_duplicate_ok": duplicate_ok}}


def judge_t0(moves, game_id=None, expected_moves=10):
    errors, ids, details = [], set(), []
    for i, move in enumerate(moves, 1):
        payload = move.get("payload", {})
        move_errors = []
        if not move.get("message_id") or move.get("message_id") in ids: move_errors.append("missing_or_duplicate_message_id")
        ids.add(move.get("message_id"))
        if move.get("move_no") != i or payload.get("counter") != i or payload.get("move_no") != i: move_errors.append("counter_order")
        if payload.get("thread") != payload.get("game_id") or (game_id and payload.get("game_id") != game_id): move_errors.append("game_thread_mismatch")
        if payload.get("kind") != "request": move_errors.append("not_request")
        if not move.get("transport_ok"): move_errors.append("transport_failed")
        if move.get("latency_ms", 30001) > 30000: move_errors.append("latency_exceeded")
        details.append({"message_id": move.get("message_id"), "move_no": i, "errors": move_errors})
        errors.extend(f"counter {i}: {error}" for error in move_errors)
    if len(moves) != expected_moves: errors.append(f"expected_{expected_moves}_moves_got_{len(moves)}")
    transport = bool(moves) and all(m.get("transport_ok") for m in moves)
    latency = bool(moves) and all(m.get("latency_ms", 30001) <= 30000 for m in moves)
    ok = not errors
    criteria = {"transport_ok": transport, "rules_ok": ok, "latency_ok": latency, "observation_ok": "not_available"}
    return {"criteria": criteria, "status": "pass" if transport and ok and latency else "fail", "failure_reasons": errors, "moves": details}
