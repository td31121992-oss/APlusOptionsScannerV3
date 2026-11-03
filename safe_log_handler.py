"""A midnight-rotating log file handler that never breaks logging (no project imports, so it can be tested on its own)."""

from __future__ import annotations

import time
from logging.handlers import TimedRotatingFileHandler


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Midnight rotation that never breaks logging.

    On Windows a file cannot be renamed while another process has it open. The dashboard opens logs/scanner.log as soon as it lazily loads
    core.dhan_client and keeps it open, so the scanner's first log line after midnight used to fail with PermissionError and lose its logs for
    the day. If the rollover is refused we simply keep appending to the same file and try again at the next midnight."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except OSError:                                           # PermissionError / WinError 32: the file is in use by another process
            try:
                if self.stream is None or getattr(self.stream, "closed", False):
                    self.stream = self._open()
            except Exception:                                     # noqa: BLE001 - logging must never raise
                pass
            self.rolloverAt = self.computeRollover(int(time.time()))
