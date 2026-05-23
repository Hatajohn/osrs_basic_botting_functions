"""Tests for sacred eel session logging."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from SacredEelFishing.sacred_eel_log import (
    LOGS_DIR,
    SESSION_LOG_FILE,
    close_run_logger,
    install_run_logger,
)


class TestSacredEelLog(unittest.TestCase):
    def tearDown(self):
        close_run_logger()

    def test_ensure_logs_dir(self):
        with TemporaryDirectory() as tmp:
            from SacredEelFishing import sacred_eel_log as mod

            orig = mod.LOGS_DIR
            try:
                mod.LOGS_DIR = Path(tmp) / "logs"
                mod.SESSION_LOG_FILE = mod.LOGS_DIR / "sacred_eel_latest.log"
                path = mod.ensure_logs_dir()
                self.assertTrue(path.is_dir())
            finally:
                mod.LOGS_DIR = orig
                mod.SESSION_LOG_FILE = orig / "sacred_eel_latest.log"

    def test_tee_writes_to_file(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            install_run_logger(log)
            print("hello log")
            close_run_logger()
            text = log.read_text(encoding="utf-8")
            self.assertIn("Exodia script logs", text)
            self.assertIn("sacred eel fishing session", text)
            self.assertIn("hello log", text)
            self.assertIn("session end", text)

    def test_session_log_file_constant(self):
        self.assertTrue(str(SESSION_LOG_FILE).endswith("logs/sacred_eel_latest.log"))
        self.assertEqual(LOGS_DIR.name, "logs")


if __name__ == "__main__":
    unittest.main()
