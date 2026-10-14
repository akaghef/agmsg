import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run as harness


class RunLifecycle(unittest.TestCase):
    def test_t1_preflight_failure_creates_current_run_and_locator(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "runs"
            env = patch.dict(os.environ, {"AGMSG_E2E_OUTPUT": str(output)})
            printed = io.StringIO()

            def fail_preflight(runtime):
                run_dirs = list(output.iterdir())
                self.assertEqual(len(run_dirs), 1)
                result = json.loads((run_dirs[0] / "result.json").read_text())
                self.assertEqual(result["status"], "running")
                raise RuntimeError(f"{runtime} preflight exact failure")

            with env, patch.object(harness, "preflight", side_effect=fail_preflight):
                with contextlib.redirect_stdout(printed):
                    code = harness.run_t1(Namespace(players="codex,codex", deck=False, moves=10))

            self.assertNotEqual(code, 0)
            run_dirs = list(output.iterdir())
            self.assertEqual(len(run_dirs), 1)
            folder = run_dirs[0]
            result = json.loads((folder / "result.json").read_text())
            self.assertEqual(result["status"], "preflight_failed")
            self.assertEqual(result["error"], "codex preflight exact failure")
            self.assertTrue((folder / "summary.md").is_file())
            summary_first_line = (folder / "summary.md").read_text().splitlines()[0]
            self.assertIn(f"run_id={result['run_id']}", summary_first_line)
            self.assertIn(f"started_at_utc={result['started_at_utc']}", summary_first_line)
            self.assertTrue(printed.getvalue().splitlines()[-1].startswith(f"THIS_RUN: run_id={result['run_id']} "))
            self.assertIn(str(folder / "summary.md"), printed.getvalue().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
