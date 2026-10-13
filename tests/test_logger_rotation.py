import logging
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import safe_log_handler as handler_module


class SafeRotationTests(unittest.TestCase):
    def _setup(self, name):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)                     # runs last (cleanups run in reverse order): the handler is closed first
        h = handler_module.SafeTimedRotatingFileHandler(Path(tmp, "scanner.log"), when="midnight", backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(message)s"))
        log = logging.getLogger(name)
        log.propagate, log.level = False, logging.INFO
        log.addHandler(h)
        self.addCleanup(h.close)
        self.addCleanup(log.removeHandler, h)
        return tmp, h, log

    def test_locked_file_does_not_break_logging(self):
        tmp, h, log = self._setup("test_safe_rotation")
        log.info("before midnight")
        h.rolloverAt = int(time.time()) - 5                           # midnight has passed
        with mock.patch("os.rename", side_effect=PermissionError(32, "in use by another process")):
            log.info("first line after midnight, rename refused")     # used to raise inside logging and lose the line
        log.info("second line")
        h.flush()
        text = Path(tmp, "scanner.log").read_text(encoding="utf-8")
        self.assertIn("first line after midnight, rename refused", text)
        self.assertIn("second line", text)
        self.assertGreater(h.rolloverAt, time.time())                 # will try again at the next midnight, not on every line

    def test_normal_rotation_still_works(self):
        tmp, h, log = self._setup("test_normal_rotation")
        log.info("yesterday")
        h.rolloverAt = int(time.time()) - 5
        log.info("today")
        h.flush()
        rotated = [p for p in os.listdir(tmp) if p.startswith("scanner.log.")]
        self.assertEqual(len(rotated), 1)
        current = Path(tmp, "scanner.log").read_text(encoding="utf-8")
        self.assertIn("today", current)
        self.assertNotIn("yesterday", current)


if __name__ == "__main__":
    unittest.main()
