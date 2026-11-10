"""Which market-data feed the scanner uses. Default = Dhan, exactly as before.

APLUS_DATA_PROVIDER
  DHAN    (default) everything from Dhan.
  UPSTOX  quotes, candles, option chains and expiries from Upstox ONLY (the Dhan plan expired on 3 Nov 2026; Dhan is no longer called).
          Funds and positions: the scanner is PAPER only, so there is no broker account; they are answered as "not available" (empty).
          Set APLUS_DHAN_FALLBACK=1 to bring back the old behaviour (Upstox first, Dhan as the fallback for each failed call).
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


def dhan_fallback_enabled() -> bool:
    return os.getenv("APLUS_DHAN_FALLBACK", "").strip().upper() in {"1", "YES", "TRUE", "ON"}


def upstox_only() -> bool:
    """True when Dhan is not used at all (the Dhan plan expired on 3 Nov 2026): APLUS_DATA_PROVIDER=UPSTOX and no APLUS_DHAN_FALLBACK."""
    return provider() == "UPSTOX" and not dhan_fallback_enabled()


def upstox_quote(segment: str, ids: Any) -> dict[str, dict[str, Any]]:
    """One quote call through Upstox for scripts outside the scanner: {security_id: Dhan-shaped quote with last_price / ohlc / volume}."""
    from core.upstox_client import UpstoxClient

    return UpstoxClient().get_market_quotes({segment: [str(i) for i in ids]}).get(segment, {})


def chart_call(url: str, body: Mapping[str, Any]) -> dict[str, Any] | None:
    """Answer a Dhan `charts/intraday` or `charts/historical` request body from Upstox, in the Dhan response shape (lists open/high/low/close/volume/timestamp).
    For the report / shadow scripts that used to post to api.dhan.co directly. None on any failure (they already treat None as 'no data')."""
    from core.upstox_client import UpstoxClient

    try:
        client = _CHART_CLIENT.setdefault("c", UpstoxClient())
        sid, segment = str(int(float(body["securityId"]))), str(body.get("exchangeSegment") or "NSE_EQ")
        if url.rstrip("/").endswith("charts/historical"):
            out = client.get_daily_candles(security_id=sid, segment=segment, from_date=datetime.fromisoformat(str(body["fromDate"])[:10]).date(),
                                           to_date=min(datetime.fromisoformat(str(body["toDate"])[:10]).date(), datetime.now().date()))
        else:
            out = client.get_intraday_candles(security_id=sid, segment=segment, instrument=str(body.get("instrument") or ""), interval=int(body.get("interval") or 5),
                                              from_datetime=datetime.fromisoformat(str(body["fromDate"])), to_datetime=datetime.fromisoformat(str(body["toDate"])))
        return out if out and out.get("timestamp") else None
    except Exception as exc:                                # noqa: BLE001
        logger.warning("Upstox chart call failed (%s): %s", type(exc).__name__, str(exc)[:120])
        return None


_CHART_CLIENT: dict[str, Any] = {}


def shadow_enabled() -> bool:
    return os.getenv("APLUS_UPSTOX_SHADOW", "").strip().upper() in {"1", "YES", "TRUE", "ON"}


def _quote_ok(quotes: Mapping[str, Mapping[str, Any]], wanted: Mapping[str, Any]) -> bool:
    """An Upstox answer is only used when it covers at least 90% of what was asked for (and has prices)."""
    asked = sum(len(v) for v in wanted.values())
    got = sum(1 for seg in quotes.values() for item in seg.values() if float((item or {}).get("last_price") or 0) > 0)
    return asked == 0 or got >= 0.9 * asked


def _quote_missing(quotes: Mapping[str, Mapping[str, Any]], wanted: Mapping[str, Any]) -> dict[str, list[str]]:
    """Per segment, the asked-for ids that came back without a positive price."""
    missing: dict[str, list[str]] = {}
    for segment, ids in wanted.items():
        have = quotes.get(segment) or {}
        gone = [str(i) for i in ids if float((have.get(str(i)) or {}).get("last_price") or 0) <= 0]
        if gone:
            missing[str(segment)] = gone
    return missing


def _merge_quotes(base: dict[str, dict[str, Any]], extra: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    for segment, items in extra.items():
        base.setdefault(segment, {}).update(items)
    return base


class _WrapsDhan:
    """`with build_client(cfg) as client:` works for the wrappers exactly as it does for DhanClient."""

    _dhan: Any

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        close = getattr(self._dhan, "close", None)
        if callable(close):
            close()


class HybridClient(_WrapsDhan):
    """Upstox first for quotes, candles, option chains and expiries, Dhan as the fallback for every call; everything else is Dhan."""

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
            # Partial answer: ask again for just the instruments that came back unpriced (up to twice) before giving up on Upstox.
            for _ in range(2):
                gaps = _quote_missing(out, instruments)
                if not gaps:
                    break
                time.sleep(0.4)
                _merge_quotes(out, self._upstox.get_market_quotes(gaps, mode=mode))
                if _quote_ok(out, instruments):
                    self.stats["upstox_quote_ok"] += 1
                    self.stats["upstox_quote_gapfilled"] = self.stats.get("upstox_quote_gapfilled", 0) + 1
                    return out
            gaps = _quote_missing(out, instruments)
            raise RuntimeError("incomplete Upstox quote answer: unpriced " + ", ".join(f"{seg} {len(ids)}" for seg, ids in gaps.items()))
        except Exception as exc:                            # noqa: BLE001
            self.stats["upstox_quote_fallback"] += 1
            self._note("quotes", exc)
            return self._dhan.get_market_quotes(instruments, mode=mode)

    def get_option_chain(self, security_id: Any, expiry: Any = None, segment: str = "NSE_EQ") -> Any:
        """Upstox chain reshaped to the Dhan response the scanner already parses; Dhan for this call when Upstox fails or the chain looks thin."""
        try:
            from core.upstox_client import UpstoxClient

            shaped = UpstoxClient.chain_as_dhan(self._upstox.get_option_chain(security_id, expiry, segment))
            oc = shaped["data"]["oc"]
            priced = sum(1 for entry in oc.values() for leg in entry.values() if float(leg.get("last_price") or 0) > 0)
            if len(oc) < 6 or float(shaped["data"].get("last_price") or 0) <= 0 or priced == 0:
                raise RuntimeError(f"thin Upstox option chain: {len(oc)} strikes, {priced} priced legs")
            self.stats["upstox_chain_ok"] = self.stats.get("upstox_chain_ok", 0) + 1
            return shaped
        except Exception as exc:                            # noqa: BLE001
            self.stats["upstox_chain_fallback"] = self.stats.get("upstox_chain_fallback", 0) + 1
            self._note("option chain", exc)
            return self._dhan.get_option_chain(security_id, expiry, segment)

    def get_expiries(self, security_id: Any, segment: str = "NSE_EQ") -> Any:
        try:
            out = self._upstox.get_expiries(security_id, segment)
            if out:
                return out
            raise RuntimeError("empty Upstox expiry list")
        except Exception as exc:                            # noqa: BLE001
            self._note("expiries", exc)
            return self._dhan.get_expiries(security_id, segment)

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


class UpstoxOnlyClient:
    """Upstox is the only market-data source; there is no Dhan call anywhere. A failed call raises (the scanner's cycle handles it); an
    Upstox 401/403 raises DhanMarketDataAuthorizationError (the name the scanner already latches on) so an expired Upstox token stops the scan
    loudly instead of trading on nothing. Funds / positions: PAPER only, no broker account, so they are empty."""

    def __init__(self, upstox: Any) -> None:
        self._upstox = upstox
        self.stats = {"upstox_quote_ok": 0, "upstox_candle_ok": 0, "upstox_chain_ok": 0}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def close(self) -> None:
        return None

    @staticmethod
    def _auth_check(exc: Exception, endpoint: str) -> None:
        text = str(exc)
        for code in (401, 403):
            if f"HTTP {code}" in text:
                from core.dhan_client import DhanMarketDataAuthorizationError

                raise DhanMarketDataAuthorizationError(status_code=code, endpoint=f"upstox:{endpoint}", rate_bucket="upstox") from exc

    def get_market_quotes(self, instruments: Mapping[str, Any], *, mode: str = "quote") -> dict[str, dict[str, Any]]:
        try:
            out = self._upstox.get_market_quotes(instruments, mode=mode)
            for _ in range(2):                              # ask again for just the unpriced instruments before giving up
                if _quote_ok(out, instruments):
                    break
                gaps = _quote_missing(out, instruments)
                if not gaps:
                    break
                time.sleep(0.4)
                _merge_quotes(out, self._upstox.get_market_quotes(gaps, mode=mode))
        except Exception as exc:                            # noqa: BLE001
            self._auth_check(exc, "quotes")
            raise
        if not _quote_ok(out, instruments):
            gaps = _quote_missing(out, instruments)
            raise RuntimeError("incomplete Upstox quote answer: unpriced " + ", ".join(f"{seg} {len(ids)}" for seg, ids in gaps.items()))
        self.stats["upstox_quote_ok"] += 1
        return out

    def get_option_chain(self, security_id: Any, expiry: Any = None, segment: str = "NSE_EQ") -> Any:
        from core.upstox_client import UpstoxClient

        try:
            shaped = UpstoxClient.chain_as_dhan(self._upstox.get_option_chain(security_id, expiry, segment))
        except Exception as exc:                            # noqa: BLE001
            self._auth_check(exc, "option_chain")
            raise
        oc = shaped["data"]["oc"]
        priced = sum(1 for entry in oc.values() for leg in entry.values() if float(leg.get("last_price") or 0) > 0)
        if len(oc) < 6 or float(shaped["data"].get("last_price") or 0) <= 0 or priced == 0:
            raise RuntimeError(f"thin Upstox option chain: {len(oc)} strikes, {priced} priced legs")
        self.stats["upstox_chain_ok"] += 1
        return shaped

    def get_expiries(self, security_id: Any, segment: str = "NSE_EQ") -> Any:
        try:
            out = self._upstox.get_expiries(security_id, segment)
        except Exception as exc:                            # noqa: BLE001
            self._auth_check(exc, "expiries")
            raise
        if not out:
            raise RuntimeError("empty Upstox expiry list")
        return out

    def get_intraday_candles(self, **kwargs: Any) -> dict[str, list[Any]]:
        try:
            out = self._upstox.get_intraday_candles(**kwargs)
        except Exception as exc:                            # noqa: BLE001
            self._auth_check(exc, "candles")
            raise
        if not (out and out.get("timestamp")):
            raise RuntimeError("empty Upstox candle answer")
        self.stats["upstox_candle_ok"] += 1
        return out

    def get_fund_limits(self) -> dict[str, Any]:
        return {}                                           # paper only: no broker account

    def get_positions(self) -> list[dict[str, Any]]:
        return []


class ShadowClient(_WrapsDhan):
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

    mode = provider()
    if mode == "UPSTOX" and not dhan_fallback_enabled():
        from core.upstox_client import UpstoxClient

        up = UpstoxClient()
        if not up.token:
            raise RuntimeError("APLUS_DATA_PROVIDER=UPSTOX (Dhan plan expired) but UPSTOX_ANALYTICS_TOKEN is not set")
        logger.info("Market data provider: UPSTOX only (no Dhan)")
        return UpstoxOnlyClient(up)
    dhan = DhanClient(config.dhan)
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
