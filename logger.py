"""
logger.py

Central logging for APlus Options Scanner V3.

- Colored console output (auto-disables when stdout isn't a TTY, e.g. when
  piped to a file or running in CI).
- Daily rotating file logs (rotates at midnight, keeps N days of backups),
  with plain (uncolored) formatting so log files stay grep-friendly.
- Cleaner, aligned formatting including thread name, which matters once
  the scanner is running with max_workers > 1.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from config import CONFIG

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)-22s [%(threadName)s] %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(threadName)-16s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_INITIALIZED = False

# ANSI escape codes -- widely supported on Linux/macOS terminals and modern
# Windows Terminal / VS Code. Falls back to no color automatically when
# stdout isn't a TTY (piped output, log aggregators, CI).
_LEVEL_COLORS = {
    logging.DEBUG: "\033[2;37m",     # dim white
    logging.INFO: "\033[0;36m",      # cyan
    logging.WARNING: "\033[0;33m",   # yellow
    logging.ERROR: "\033[0;31m",     # red
    logging.CRITICAL: "\033[1;41m",  # bold, red background
}
_RESET = "\033[0m"
_DIM = "\033[2m"


class _ColorFormatter(logging.Formatter):
    """Formatter that colors the level name and dims the timestamp/logger
    name, leaving the message itself in the default terminal color."""

    def __init__(self, fmt: str, datefmt: str, *, use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self._use_color:
            return super().format(record)

        color = _LEVEL_COLORS.get(record.levelno, "")
        original_levelname = record.levelname
        original_asctime = getattr(record, "asctime", None)

        try:
            record.levelname = f"{color}{original_levelname:<8}{_RESET}"
            formatted = super().format(record)
        finally:
            record.levelname = original_levelname
            if original_asctime is not None:
                record.asctime = original_asctime

        return formatted


def _supports_color() -> bool:
    color_enabled = getattr(CONFIG.logging, "color", True)
    if not color_enabled:
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def setup_logging() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    log_dir: Path = CONFIG.logging.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, CONFIG.logging.level.upper(), logging.INFO))

    # ------------------------------------------------
    # Console handler -- colored, human-scannable
    # ------------------------------------------------
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        _ColorFormatter(_CONSOLE_FORMAT, _DATEFMT, use_color=_supports_color())
    )
    root.addHandler(console)

    # ------------------------------------------------
    # File handler -- daily rotation, plain text
    # ------------------------------------------------
    backup_days = getattr(CONFIG.logging, "backup_days", 14)

    file_handler = TimedRotatingFileHandler(
        log_dir / CONFIG.logging.log_file,
        when="midnight",
        interval=1,
        backupCount=backup_days,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATEFMT))
    root.addHandler(file_handler)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    if not _INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
