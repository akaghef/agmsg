import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run.sh"


class T0Integration(unittest.TestCase):
    def test_t0_uses_temp_agmsg_store_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, AGMSG_STORAGE_PATH=td, AGMSG_E2E_OUTPUT=td + "/runs")
            p = subprocess.run([str(RUN), "t0", "--moves", "4"], env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            result_path = next((Path(td) / "runs").glob("*/result.json"))
            data = json.loads(result_path.read_text())
            self.assertEqual(data["tier"], "t0")
            self.assertEqual(len(data["moves"]), 4)
            self.assertTrue(data["criteria"]["transport_ok"])
            self.assertTrue(all(m.get("message_id") for m in data["moves"]))
            replay = subprocess.run([str(RUN), "replay", str(result_path.parent)], env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(replay.returncode, 0, replay.stderr + replay.stdout)

    def test_t1_rejects_non_ten_move_count(self):
        p = subprocess.run([str(RUN), "t1", "--moves", "4"], text=True, capture_output=True, timeout=10)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("invalid choice", p.stderr)


if __name__ == "__main__":
    unittest.main()
