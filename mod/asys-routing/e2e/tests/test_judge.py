import unittest

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from judge import judge_transcript, normalize_word, chain_endpoints


class KanaRules(unittest.TestCase):
    def test_small_kana_and_sokuon(self):
        self.assertEqual(chain_endpoints("きゃっ"), ("き", "つ"))
        self.assertEqual(normalize_word("キャッ"), "きやつ")

    def test_long_mark_uses_preceding_kana(self):
        self.assertEqual(chain_endpoints("らーめん"), ("ら", "ん"))
        self.assertIsNone(chain_endpoints("ー"))

    def test_dakuten_distinct_and_nfc(self):
        self.assertNotEqual(chain_endpoints("が"), chain_endpoints("か"))
        self.assertEqual(normalize_word("ガ"), normalize_word("か\u3099"))

    def test_final_n_and_repeats_rejected(self):
        self.assertFalse(judge_transcript([move(1, "a", "みかん")])['criteria']['rules_ok'])
        self.assertFalse(judge_transcript([move(1, "a", "りんご"), move(2, "b", "ごりら", "りんご"), move(3, "a", "りんご", "ごりら")])['criteria']['rules_ok'])

    def test_gaps_duplicates_order_and_valid_chain(self):
        chain = ["しりとり", "りんご", "ごりら"]
        self.assertTrue(judge_transcript([move(i, "a" if i % 2 else "b", w, chain[i-2] if i > 1 else None) for i,w in enumerate(chain, 1)], expected_moves=3)['criteria']['rules_ok'])
        chain = ["すいか", "からす", "すずめ"]
        valid = [move(i, "a" if i % 2 else "b", w, chain[i-2] if i > 1 else None) for i,w in enumerate(chain, 1)]
        self.assertTrue(judge_transcript(valid, expected_moves=3)['criteria']['rules_ok'])
        self.assertFalse(judge_transcript([move(1,"a","すいか"), move(3,"b","からす")], expected_moves=2)['criteria']['rules_ok'])
        self.assertFalse(judge_transcript([move(1,"b","すいか")], expected_moves=1)['criteria']['rules_ok'])
        dup = [move(1,"a","すいか"), move(2,"b","すいか")]
        self.assertFalse(judge_transcript(dup, expected_moves=2)['criteria']['rules_ok'])
        self.assertTrue(judge_transcript(dup, expected_moves=2, injected_duplicate_ids=["2"])['duplicate_evidence']['injected_duplicate_ok'])


def move(n, player, word, previous=None):
    return {"move_no": n, "player": {"a":"shiritori-a", "b":"shiritori-b"}.get(player, player), "word": word, "previous_word": previous, "transport_ok": True, "latency_ms": 2}


if __name__ == "__main__":
    unittest.main()
