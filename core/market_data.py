"""Which market-data feed the scanner uses. Default = Dhan, exactly as before.

APLUS_DATA_PROVIDER
  DHAN    (default) everything from Dhan.
  UPSTOX  quotes and candles from Upstox; any failure, empty answer or exhausted budget falls back to Dhan for THAT call (logged and
          counted). Option chain, expiries, funds and positions always stay on Dhan.
APLUS_UPSTOX_SHADOW=1  (with DHAN) keep trading on Dhan data, and in the background fetch the same instruments from Upstox and
          write the differences to data/upstox_shadow/<date>.csv. Nothing from Upstox is ever used for a decision in this mode.
"""

from __future__ import annotations

import csv
import logging
import os
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def provider() -> str:
    value = os.getenv("APLUS_DATA_PROVIDER", "DHAN").strip().upper()
    return value if value in {"DHAN", "UPSTOX"} else "DHAN"


def shadow_enabled() -> bool:
    return os.getenv("APLUS_UPSTOX_SHADOW", "").strip().upper() in {"1", "YES", "TRUE", "ON"}


def _quote_ok(quotes: Mapping[str, Mapping[str, Any]], wanted: Mapping[str, Any]) -> bool:
    """An Upstox answer is only used when it covers at least 90% of what was asked for (and has prices)."""
    asked = sum(len(v) for v in wanted.values())
    got = sum(1 for seg in quotes.values() for item in seg.values() if float((item or {}).get("last_price") or 0) > 0)
    return asked == 0 or got >= 0.9 * asked


class HybridClient:
    """Upstox first for quotes and candles, Dhan as the fallback for every call; everything else is Dhan."""

    def __init__(self, dhan: Any, upstox: Any) -> None:
        self._dhan, self._upstox = dhan, upstox
        self.stats = {"upstox_quote_ok": 0, "upstox_quote_fallback": 0, "upstox_candle_ok": 0, "upstox_candle_fallback": 0}
        self._last_error = ""

    def __getattr__(self, name: str) -> Any:                # option chain, expiries, funds, positions, config ...
        return getattr(self._dhan, name)

    def _note(self, kind: str, exc: Exception | str) -> None:
        text = f"{type(exc).__name__}: {exc}" if isinstance(exc, Exception) else str(exc)
        if text != self._last_error:                        # log a changed reason once, not every cycle
            logger.warning("Upstox %s failed, using Dhan: %s", kind, text)
            self._last_error = text

    def get_market_quotes(self, instruments: Mapping[str, Any], *, mode: str = "quote") -> dict[str, dict[str, Any]]:
        try:
            out = self._upstox.get_market_quotes(instruments, mode=mode)
            if _quote_ok(out, instruments):
                self.stats["upstox_quote_ok"] += 1
                return out
            raise RuntimeError("incomplete Upstox quote answer")
        except Exception as exc:                            # noqa: BLE001
            self.stats["upstox_quote_fallback"] += 1
            self._note("quotes", exc)
            return self._dhan.get_market_quotes(instruments, mode=mode)

    def get_intraday_candles(self, **kwargs: Any) -> dict[str, list[Any]]:
        try:
            out = self._upstox.get_intraday_candles(**kwargs)
            if out and out.get("timestamp"):
                self.stats["upstox_candle_ok"] += 1
                return out
            raise RuntimeError("empty Upstox candle answer")
        except Exception as exc:                            # noqa: BLE001
            self.stats["upstox_candle_fallback"] += 1
            self._note("candles", exc)
            return self._dhan.get_intraday_candles(**kwargs)


class ShadowClient:
    """Dhan answers every call. In a background thread the same quote request goes to Upstox and the difference is logged."""

    FIELDS = ["time", "instruments", "matched", "missing", "median_ltp_diff_pct", "max_ltp_diff_pct", "median_prev_close_diff_pct",
              "median_volume_ratio", "dhan_seconds", "upstox_seconds", "error"]

    def __init__(self, dhan: Any, upstox: Any, out_dir: Path | None = None, min_gap_seconds: float = 55.0) -> None:
        self._dhan, self._upstox = dhan, upstox
        self.out_dir = out_dir or ROOT / "data" / "upstox_shadow"
        self.min_gap = min_gap_seconds
        self._last = 0.0
        self._busy = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dhan, name)

    def get_intraday_candles(self, **kwargs: Any) -> dict[str, list[Any]]:
        return self._dhan.get_intraday_candles(**kwargs)

    def get_market_quotes(self, instruments: Mapping[str, Any], *, mode: str = "quote") -> dict[str, dict[str, Any]]:
        t0 = time.time()
        result = self._dhan.get_market_quotes(instruments, mode=mode)
        dhan_seconds = time.time() - t0
        if mode == "quote" and time.time() - self._last >= self.min_gap and self._busy.acquire(blocking=False):
            self._last = time.time()
            snapshot = {seg: list(ids) for seg, ids in instruments.items()}
            threading.Thread(target=self._compare, args=(snapshot, result, dhan_seconds), daemon=True).start()
        return result

    def _compare(self, instruments: Mapping[str, Any], dhan_quotes: Mapping[str, Mapping[str, Any]], dhan_seconds: float) -> None:
        row: dict[str, Any] = {"time": datetime.now().strftime("%H:%M:%S"), "instruments": sum(len(v) for v in instruments.values()),
                               "dhan_seconds": round(dhan_seconds, 2)}
        try:
            t0 = time.time()
            up = self._upstox.get_market_quotes(instruments, mode="quote")
            row["upstox_seconds"] = round(time.time() - t0, 2)
            diffs, prev, vol, missing = [], [], [], 0
            for seg, ids in instruments.items():
                for sid in ids:
                    d = (dhan_quotes.get(seg) or {}).get(str(sid)) or {}
                    u = (up.get(seg) or {}).get(str(sid)) or {}
                    dl, ul = float(d.get("last_price") or 0), float(u.get("last_price") or 0)
                    if dl <= 0 or ul <= 0:
                        missing += 1
                        continue
                    diffs.append(abs(ul / dl - 1) * 100)
                    dp, upc = float((d.get("ohlc") or {}).get("close") or 0), float((u.get("ohlc") or {}).get("close") or 0)
                    if dp > 0 and upc > 0:
                        prev.append(abs(upc / dp - 1) * 100)
                    dv, uv = float(d.get("volume") or 0), float(u.get("volume") or 0)
                    if dv > 0 and uv > 0:
                        vol.append(uv / dv)
            row.update({"matched": len(diffs), "missing": missing,
                        "median_ltp_diff_pct": round(statistics.median(diffs), 4) if diffs else "",
                        "max_ltp_diff_pct": round(max(diffs), 4) if diffs else "",
                        "median_prev_close_diff_pct": round(statistics.median(prev), 4) if prev else "",
                        "median_volume_ratio": round(statistics.median(vol), 3) if vol else "", "error": ""})
        except Exception as exc:                            # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        finally:
            try:
                self.out_dir.mkdir(parents=True, exist_ok=True)
                path = self.out_dir / f"{datetime.now().date().isoformat()}.csv"
                new = not path.exists()
                with path.open("a", newline="", encoding="utf-8") as handle:
                    w = csv.DictWriter(handle, fieldnames=self.FIELDS, extrasaction="ignore")
                    if new:
                        w.writeheader()
                    w.writerow(row)
            except OSError:
                pass
            self._busy.release()


def build_client(config: Any) -> Any:
    """DhanClient (default), or the Upstox-first hybrid, or the Dhan client with the Upstox shadow comparison."""
    from core.dhan_client import DhanClient

    dhan = DhanClient(config.dhan)
    mode = provider()
    if mode == "UPSTOX":
        from core.upstox_client import UpstoxClient

        up = UpstoxClient()
        if up.token:
            logger.info("Market data provider: UPSTOX first, Dhan fallback")
            return HybridClient(dhan, up)
        logger.warning("APLUS_DATA_PROVIDER=UPSTOX but no UPSTOX_ANALYTICS_TOKEN; staying on Dhan")
        return dhan
    if shadow_enabled():
        from core.upstox_client import UpstoxClient

        up = UpstoxClient()
        if up.token:
            logger.info("Market data provider: DHAN with Upstox shadow comparison")
            return ShadowClient(dhan, up)
        logger.warning("APLUS_UPSTOX_SHADOW is on but no UPSTOX_ANALYTICS_TOKEN; shadow comparison disabled")
    return dhan
