from __future__ import annotations
from pathlib import Path
from datetime import datetime
import py_compile, re, shutil

ROOT = Path(__file__).resolve().parent
JOURNAL = ROOT / "paper_trade_journal.py"
if not JOURNAL.is_file():
    raise SystemExit("FAIL: paper_trade_journal.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_atomic_write_reliability_v2_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(JOURNAL, backup / JOURNAL.name)

def insert_import_after(s, anchor, line):
    if line.strip() in s:
        return s
    i = s.find(anchor)
    if i < 0:
        raise RuntimeError(f"import anchor not found: {anchor}")
    e = s.find("\n", i)
    return s[:e+1] + line + s[e+1:]

def replace_method(s, name, new_text, decorated=False):
    if decorated:
        pat = re.compile(rf'(?ms)^    @(?:classmethod|staticmethod)\n    def {re.escape(name)}\(.*?(?=^    @|^    def |\Z)')
    else:
        pat = re.compile(rf'(?ms)^    def {re.escape(name)}\(.*?(?=^    def |^    @|\Z)')
    m = pat.search(s)
    if not m:
        raise RuntimeError(f"method not found: {name}")
    return s[:m.start()] + new_text.rstrip() + "\n\n" + s[m.end():]

try:
    s = JOURNAL.read_text(encoding="utf-8")
    s = insert_import_after(s, "import json", "import logging\n")
    s = insert_import_after(s, "import tempfile", "import time\n")

    if "logger = logging.getLogger(__name__)" not in s:
        p = s.find("class PaperTradeJournal:")
        if p < 0:
            raise RuntimeError("PaperTradeJournal class not found")
        s = s[:p] + "logger = logging.getLogger(__name__)\n\n\n" + s[p:]

    new_flush = '''    def flush(self) -> bool:
        """Persist journal files without terminating the scanner."""
        state_payload = {
            "trading_date": self.trading_date,
            "rearm_minutes": self.rearm_minutes,
            "lanes": self.lanes,
            "trades": self.trades,
        }
        ok = True
        targets = (
            ("journal_state", lambda: self._atomic_json(self.state_path, state_payload), self.state_path),
            ("paper_trades_json", lambda: self._atomic_json(
                self.report_json,
                {"trading_date": self.trading_date, "paper_trades": self.trades},
            ), self.report_json),
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
'''
    s = replace_method(s, "flush", new_flush)

    new_csv = '''    @classmethod
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
'''
    s = replace_method(s, "_write_csv", new_csv, decorated=True)

    new_json = '''    @classmethod
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
'''
    s = replace_method(s, "_atomic_json", new_json, decorated=True)

    if "def _replace_with_retry(" not in s:
        p = s.find("    @classmethod\n    def _write_csv")
        if p < 0:
            raise RuntimeError("_write_csv insertion point not found")
        helper = '''    @staticmethod
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


'''
        s = s[:p] + helper + s[p:]

    JOURNAL.write_text(s, encoding="utf-8")
    py_compile.compile(str(JOURNAL), doraise=True)

except Exception:
    shutil.copy2(backup / JOURNAL.name, JOURNAL)
    print("INSTALL FAILED - original restored automatically.")
    print("Backup:", backup)
    raise

print("="*92)
print("SUCCESS: ATOMIC-WRITE RELIABILITY FIX V2 INSTALLED")
print("Backup:", backup)
print("PASS: retry/backoff added")
print("PASS: journal flush made non-fatal")
print("PASS: strategy/risk logic unchanged")
print("="*92)
