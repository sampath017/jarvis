"""A timed-out local inference attempt must not leave CPU workers behind."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from harness.run import ARTIFACTS, execute


class ProcessTimeoutTests(unittest.TestCase):
    def test_timeout_stops_descendant_before_it_can_write_later(self):
        target = ARTIFACTS / "tests/fixtures/harness/process-timeout"
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target) as folder:
            folder = Path(folder)
            ready, leaked = folder / "ready", folder / "leaked"
            child = folder / "child.py"
            child.write_text("from pathlib import Path\nimport time\n"
                             f"Path({str(ready)!r}).touch()\ntime.sleep(5)\n"
                             f"Path({str(leaked)!r}).touch()\n")
            parent = ("import subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable, {str(child)!r}]); time.sleep(60)")
            result = execute([sys.executable, "-c", parent], folder, dict(os.environ),
                             folder / "process.log", timeout=3)
            self.assertEqual(result["error"], "Suite timed out")
            self.assertTrue(ready.exists(), "Child process did not start before the test deadline")
            time.sleep(max(0, ready.stat().st_mtime + 5.25 - time.time()))
            self.assertFalse(leaked.exists(), "Descendant survived the suite timeout")
