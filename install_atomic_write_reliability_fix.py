from __future__ import annotations
from pathlib import Path
from datetime import datetime
import py_compile, shutil

ROOT = Path(__file__).resolve().parent
JOURNAL = ROOT / "paper_trade_journal.py"

if not JOURNAL.is_file():
    raise SystemExit("FAIL: paper_trade_journal.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_atomic_write_reliability_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(JOURNAL, backup / JOURNAL.name)

def once(s, old, new, label):
    c = s.count(old)
    if c != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, found {c}")
    return s.replace(old, new, 1)

try:
    s = JOURNAL.read_text(encoding="utf-8")

    if "import logging\n" not in s:
        s = once(s, "import json\n", "import json\nimport logging\n", "logging import")
    if "import time\n" not in s:
        s = once(s, "import tempfile\n", "import tempfile\nimport time\n", "time import")

    if "logger = logging.getLogger(__name__)" not in s:
        s = once(
            s,
            "from typing import Any, Mapping, Sequence\n\n\nclass PaperTradeJournal:",
            "from typing import Any, Mapping, Sequence\n\n\nlogger = logging.getLogger(__name__)\n\n\nclass PaperTradeJournal:",
            "logger",
        )

    old_flush = """    def flush(self) -> None:
        state_payload = {
            "trading_date": self.trading_date,
            "rearm_minutes": self.rearm_minutes,
            "lanes": self.lanes,
            "trades": self.trades,
        }
        self._atomic_json(self.state_path, state_payload)
        self._atomic_json(self.report_json, {
            "trading_date": self.trading_date,
            "paper_trades": self.trades,
        })
        self._write_csv(self.report_csv, self.trades)
"""
    new_flush = """    def flush(self) -> bool:
        state_payload = {
            "trading_date": self.trading_date,
            "rearm_minutes": self.rearm_minutes,
            "lanes": self.lanes,
            "trades": self.trades,
        }
        ok = True
        targets = (
            ("journal_state", lambda: self._atomic_json(self.state_path, state_payload), self.state_path),
            ("paper_trades_json", lambda: self._atomic_json(self.report_json, {
                "trading_date": self.trading_date,
                "paper_trades": self.trades,
            }), self.report_json),
            ("paper_trades_csv", lambda: self._write_csv(self.report_csv, self.trades), self.report_csv),
        )
        for label, writer, path in targets:
            try:
                writer()
            except Exception as exc:
                ok = False
                logger.warning(
                    "Paper journal persistence failed but scanner will continue "
                    "(target=%s path=%s error=%s: %s)",
                    label, path, type(exc).__name__, exc,
                )
        return ok
"""
    if "scanner will continue" not in s:
        s = once(s, old_flush, new_flush, "flush")

    old_methods = """    @classmethod
    def _write_csv(cls, path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(cls.CSV_FIELDS))
            writer.writeheader()
            for row in rows:
                payload = {field: row.get(field, "") for field in cls.CSV_FIELDS}
                for field in ("safety_block_reasons", "safety_warnings"):
                    value = payload.get(field)
                    if isinstance(value, (list, tuple, set)):
                        payload[field] = " | ".join(str(item) for item in value)
                writer.writerow(payload)
        os.replace(temporary, path)

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
"""
    new_methods = """    @staticmethod
    def _replace_with_retry(
        temporary: Path,
        path: Path,
        *,
        attempts: int = 7,
        initial_delay: float = 0.05,
    ) -> None:
        delay = max(0.01, float(initial_delay))
        attempts = max(1, int(attempts))
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                os.replace(temporary, path)
                return
            except (PermissionError, OSError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "Atomic replace retry %s/%s for %s after %s: %s",
                    attempt, attempts, path, type(exc).__name__, exc,
                )
                time.sleep(delay)
                delay = min(delay * 2.0, 0.80)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Atomic replace failed for {path}")

    @classmethod
    def _write_csv(cls, path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            with temporary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(cls.CSV_FIELDS))
                writer.writeheader()
                for row in rows:
                    payload = {field: row.get(field, "") for field in cls.CSV_FIELDS}
                    for field in ("safety_block_reasons", "safety_warnings"):
                        value = payload.get(field)
                        if isinstance(value, (list, tuple, set)):
                            payload[field] = " | ".join(str(item) for item in value)
                    writer.writerow(payload)
                handle.flush()
                os.fsync(handle.fileno())
            cls._replace_with_retry(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _atomic_json(cls, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            cls._replace_with_retry(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
"""
    if "_replace_with_retry(" not in s:
        s = once(s, old_methods, new_methods, "atomic methods")

    JOURNAL.write_text(s, encoding="utf-8")
    py_compile.compile(str(JOURNAL), doraise=True)

    final = JOURNAL.read_text(encoding="utf-8")
    for marker in (
        "def _replace_with_retry(",
        "attempts: int = 7",
        "time.sleep(delay)",
        "os.fsync(handle.fileno())",
        "scanner will continue",
        "def flush(self) -> bool:",
    ):
        if marker not in final:
            raise RuntimeError("Missing post-install marker: " + marker)

except Exception:
    shutil.copy2(backup / JOURNAL.name, JOURNAL)
    print("INSTALL FAILED - original restored automatically.")
    print("Backup:", backup)
    raise

print("=" * 92)
print("SUCCESS: APLUS ATOMIC-WRITE RELIABILITY FIX INSTALLED")
print("Backup:", backup)
print("PASS: unique temp files for JSON and CSV")
print("PASS: Windows file-lock retry with exponential backoff")
print("PASS: flush + fsync before replace")
print("PASS: failed journal persistence is non-fatal")
print("PASS: strategy/risk/trading logic unchanged")
print("=" * 92)
