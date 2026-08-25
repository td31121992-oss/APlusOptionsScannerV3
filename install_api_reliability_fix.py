from __future__ import annotations
import os, re, shutil, py_compile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
ENV = ROOT / ".env"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"backup_before_api_reliability_fix_{STAMP}"

ADDITION = '        self._account_cache: dict[str, tuple[float, Any]] = {}\n        self._fund_cache_seconds = max(\n            30,\n            int(os.getenv("INTRADAY_ACCOUNT_FUND_CACHE_SECONDS", "300")),\n        )\n        self._positions_cache_seconds = max(\n            5,\n            int(os.getenv("INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS", "30")),\n        )\n'
NEW_METHOD = '    def _load_account_safety_context(self) -> dict[str, Any]:\n        """Load account safety data with conservative short-lived caching."""\n        context: dict[str, Any] = {\n            "fund_limits": {},\n            "positions": [],\n            "fund_limits_fetch_ok": False,\n            "positions_fetch_ok": False,\n            "errors": [],\n            "cache": {"fund_limits": "MISS", "positions": "MISS"},\n        }\n        now_mono = time.monotonic()\n\n        cached_funds = self._account_cache.get("fund_limits")\n        if cached_funds is not None:\n            created_at, payload = cached_funds\n            age = now_mono - created_at\n            if age <= self._fund_cache_seconds:\n                context["fund_limits"] = payload\n                context["fund_limits_fetch_ok"] = True\n                context["cache"]["fund_limits"] = f"HIT age={age:.1f}s"\n\n        if not context["fund_limits_fetch_ok"]:\n            try:\n                funds = self.client.get_fund_limits()\n                context["fund_limits"] = funds\n                context["fund_limits_fetch_ok"] = True\n                self._account_cache["fund_limits"] = (now_mono, funds)\n                context["cache"]["fund_limits"] = "REFRESHED"\n            except Exception as exc:\n                context["errors"].append(f"fund_limits {type(exc).__name__}: {exc}")\n                logger.warning("Safety fund-limit fetch failed: %s", exc)\n                if cached_funds is not None:\n                    _, payload = cached_funds\n                    context["fund_limits"] = payload\n                    context["fund_limits_fetch_ok"] = True\n                    context["cache"]["fund_limits"] = "STALE_FALLBACK"\n\n        cached_positions = self._account_cache.get("positions")\n        if cached_positions is not None:\n            created_at, payload = cached_positions\n            age = now_mono - created_at\n            if age <= self._positions_cache_seconds:\n                context["positions"] = payload\n                context["positions_fetch_ok"] = True\n                context["cache"]["positions"] = f"HIT age={age:.1f}s"\n\n        if not context["positions_fetch_ok"]:\n            try:\n                positions = self.client.get_positions()\n                context["positions"] = positions\n                context["positions_fetch_ok"] = True\n                self._account_cache["positions"] = (now_mono, positions)\n                context["cache"]["positions"] = "REFRESHED"\n            except Exception as exc:\n                context["errors"].append(f"positions {type(exc).__name__}: {exc}")\n                logger.warning("Safety positions fetch failed: %s", exc)\n                if cached_positions is not None:\n                    _, payload = cached_positions\n                    context["positions"] = payload\n                    context["positions_fetch_ok"] = True\n                    context["cache"]["positions"] = "STALE_FALLBACK"\n\n        return context\n\n'

def fail(msg):
    raise RuntimeError(msg)

def backup_file(src):
    if src.exists():
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, BACKUP / src.name)

def set_env_value(path, key, value):
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    found = False
    out = []
    for line in lines:
        if pat.match(line):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")

def patch_scanner(text):
    anchor = "        self._option_cache: dict[str, tuple[float, dict[str, Any]]] = {}\n"
    if "_fund_cache_seconds" not in text:
        if anchor not in text:
            fail("Scanner anchor for _option_cache was not found.")
        text = text.replace(anchor, anchor + ADDITION, 1)

    start = text.find("    def _load_account_safety_context(self) -> dict[str, Any]:")
    end = text.find("    def _cached_option(", start)
    if start < 0 or end < 0:
        fail("Could not locate account-safety context block.")
    text = text[:start] + NEW_METHOD + text[end:]
    return text

def main():
    print("="*86)
    print("APlus API Reliability Fix")
    print("PAPER ONLY - no strategy/risk threshold changes - no live orders")
    print("="*86)

    if not SCANNER.is_file():
        fail("opening_momentum_scanner.py not found")

    BACKUP.mkdir(parents=True, exist_ok=True)
    backup_file(SCANNER)
    backup_file(ENV)

    env_existed = ENV.exists()
    try:
        s = SCANNER.read_text(encoding="utf-8")
        SCANNER.write_text(patch_scanner(s), encoding="utf-8")

        set_env_value(ENV, "HISTORICAL_REQUESTS_PER_SECOND", "1.0")
        set_env_value(ENV, "OPTION_CHAIN_REQUESTS_PER_SECOND", "0.25")
        set_env_value(ENV, "INTRADAY_HISTORICAL_WORKERS", "1")
        set_env_value(ENV, "INTRADAY_ACCOUNT_FUND_CACHE_SECONDS", "300")
        set_env_value(ENV, "INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS", "30")

        py_compile.compile(str(SCANNER), doraise=True)

        check = SCANNER.read_text(encoding="utf-8")
        required = [
            "self._account_cache",
            "INTRADAY_ACCOUNT_FUND_CACHE_SECONDS",
            "INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS",
            '"live_orders_enabled": False',
        ]
        missing = [x for x in required if x not in check]
        if missing:
            fail("Static verification failed: " + repr(missing))

        print("SUCCESS")
        print("Backup:", BACKUP)
        print("Historical rate     : 1.0 req/sec")
        print("Historical workers  : 1")
        print("Option-chain rate   : 0.25 req/sec (~1 call/4 sec)")
        print("Fund-limit cache    : 300 sec")
        print("Positions cache     : 30 sec")
        print("Strategy thresholds : UNCHANGED")
        print("Live orders         : STILL DISABLED")
        print("="*86)

    except Exception:
        if (BACKUP / SCANNER.name).exists():
            shutil.copy2(BACKUP / SCANNER.name, SCANNER)
        if (BACKUP / ENV.name).exists():
            shutil.copy2(BACKUP / ENV.name, ENV)
        elif not env_existed and ENV.exists():
            ENV.unlink()
        print("INSTALL FAILED - originals restored:", BACKUP)
        raise

if __name__ == "__main__":
    main()
