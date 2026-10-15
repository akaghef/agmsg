import json
import csv
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from acceptance import judge_acceptance, read_messages


WORDS = ["すいか", "からす", "すずめ", "めだか", "かめ", "めじろ", "ろば", "ばら", "らっぱ"]
CHILDREN = ["child-a", "child-b", "child-c"]


class AcceptanceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbpath = Path(self.tmp.name) / "messages.db"
        with sqlite3.connect(self.dbpath) as db:
            db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, message_id TEXT, team TEXT, from_agent TEXT, to_agent TEXT, thread TEXT, kind TEXT, body TEXT, created_at TEXT)")
        self.start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.rows = []
        for n, word in enumerate(WORDS):
            sender = CHILDREN[n % 3]
            body = json.dumps({"word": word, "session_id": "session-" + sender}, ensure_ascii=False)
            self.rows.append((f"m{n+1}", "demo", sender, "peer", None, "message", body, (self.start + timedelta(seconds=n * 2)).isoformat()))
        self._write()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("DELETE FROM messages")
            db.executemany("INSERT INTO messages (message_id,team,from_agent,to_agent,thread,kind,body,created_at) VALUES (?,?,?,?,?,?,?,?)", self.rows)

    def judge(self):
        rows = read_messages("demo", "2026-10-14T00:00:00+00:00", [self.dbpath])
        return judge_acceptance(rows, team="demo", parent="parent", since="2026-10-14T00:00:00+00:00", parent_reported_seconds=20)

    def test_pass(self):
        result = self.judge()
        self.assertEqual(result["status"], "pass", result["failure_reasons"])
        self.assertEqual(result["judge_elapsed_seconds"], 16)

    def test_parent_relay_violation(self):
        row = list(self.rows[0]); row[2] = "parent"; self.rows[0] = tuple(row); self._write()
        self.assertIn("parent_relayed_move", self.judge()["failure_reasons"])

    def test_only_two_children(self):
        self.rows = [tuple([*row[:2], "child-a" if i % 2 == 0 else "child-b", *row[3:]]) for i, row in enumerate(self.rows)]
        self._write()
        self.assertTrue(any(x.startswith("expected_3_child_senders") for x in self.judge()["failure_reasons"]))

    def test_invalid_chain(self):
        row = list(self.rows[1]); row[6] = json.dumps({"word": "ねこ", "session_id": "session-child-b"}, ensure_ascii=False); self.rows[1] = tuple(row); self._write()
        self.assertFalse(self.judge()["criteria"]["nine_valid_moves"])

    def test_unparsed_move_like_message_reported(self):
        self.rows.append(("bad", "demo", "child-a", "peer", None, "message", "しりとりの手 xyz", (self.start + timedelta(seconds=20)).isoformat()))
        self._write()
        result = self.judge()
        self.assertEqual(len(result["unparsed_messages"]), 1)
        self.assertEqual(result["unparsed_messages"][0]["message_id"], "bad")

    def test_turn_n_of_9_format_and_parent_control_traffic_pass(self):
        self.rows = []
        t = lambda n: (self.start + timedelta(seconds=n)).isoformat()
        for i, child in enumerate(CHILDREN):
            self.rows.append((f"r{i}", "demo", "parent", child, None, "message", "Rules: play しりとり, format TURN n/9: <word>. Reply READY.", t(0)))
            self.rows.append((f"k{i}", "demo", child, "parent", None, "message", "READY", t(1)))
        for n, word in enumerate(WORDS):
            self.rows.append((f"m{n+1}", "demo", CHILDREN[n % 3], CHILDREN[(n + 1) % 3], None, "message", f"TURN {n+1}/9: {word}", t(10 + n * 2)))
        self.rows.append(("done", "demo", "child-a", "parent", None, "message", "COMPLETE: 9/9 valid. Chain: " + " → ".join(WORDS), t(40)))
        self._write()
        result = self.judge()
        self.assertEqual(result["status"], "pass", result["failure_reasons"])
        self.assertEqual([m["move_no"] for m in result["moves"]], list(range(1, 10)))
        self.assertEqual(len(result["parent_control_messages"]), 7)

    def test_parent_relay_in_turn_format_still_fails(self):
        row = list(self.rows[4]); row[2] = "parent"; row[6] = "TURN 5/9: " + WORDS[4]; self.rows[4] = tuple(row); self._write()
        self.assertIn("parent_relayed_move", self.judge()["failure_reasons"])

    def test_saved_live_tsv_passes(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/acceptance-live-20261014.tsv"
        fields = ("id", "message_id", "created_at", "team", "from_agent", "to_agent", "kind", "thread", "body")
        with fixture.open(encoding="utf-8", newline="") as source:
            rows = [dict(zip(fields, values)) for values in csv.reader(source, delimiter="\t")]
        with sqlite3.connect(self.dbpath) as db:
            db.executemany("INSERT INTO messages (id,message_id,created_at,team,from_agent,to_agent,kind,thread,body) VALUES (?,?,?,?,?,?,?,?,?)", [tuple(row[k] or None for k in fields) for row in rows])
        messages = read_messages("a-sys", "2026-10-13T23:52:00Z", [self.dbpath])
        result = judge_acceptance(messages, team="a-sys", parent="director", since="2026-10-13T23:52:00Z", parent_reported_seconds=61)
        self.assertEqual(result["status"], "pass", result["failure_reasons"])
        self.assertEqual(len(result["child_senders"]), 3)
        self.assertEqual([m["move_no"] for m in result["moves"]], list(range(1, 10)))
        self.assertEqual(result["judge_elapsed_seconds"], 61)
        self.assertEqual(result["parent_move_message_ids"], [])


if __name__ == "__main__":
    unittest.main()
