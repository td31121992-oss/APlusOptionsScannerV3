"""Upstox market-data client with the same two data calls the scanner uses from DhanClient, returning DHAN-SHAPED data so nothing
downstream changes:

    get_market_quotes({"NSE_EQ": [ids], "NSE_FNO": [ids], "IDX_I": [ids]}, mode="quote")
        -> {segment: {security_id: {"last_price", "ohlc": {open, high, low, close}, "volume", "average_price", "oi", "depth", ...}}}
    get_intraday_candles(security_id=, segment=, instrument=, interval=, from_datetime=, to_datetime=, oi=)
        -> {"open": [...], "high": [...], "low": [...], "close": [...], "volume": [...], "timestamp": [epoch seconds], ...}

Read-only: it has no order calls. Token: UPSTOX_ANALYTICS_TOKEN (free, read-only) or UPSTOX_ACCESS_TOKEN. Candle endpoints work without
a token; quote endpoints need one. Dhan security ids are the exchange tokens, which is also what Upstox uses, so equities and
options map by token; indices use the small explicit table below.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.upstox.com"
MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
MASTER_CACHE = ROOT / "data" / "cache" / "upstox_NSE.json.gz"
IST = timezone(timedelta(hours=5, minutes=30))

# Dhan IDX_I security id -> Upstox instrument key
INDEX_KEYS = {
    "13": "NSE_INDEX|Nifty 50", "25": "NSE_INDEX|Nifty Bank", "21": "NSE_INDEX|India VIX", "27": "NSE_INDEX|Nifty Fin Service",
    "442": "NSE_INDEX|NIFTY MID SELECT", "38": "NSE_INDEX|Nifty Next 50", "29": "NSE_INDEX|Nifty IT", "14": "NSE_INDEX|Nifty Auto",
    "32": "NSE_INDEX|Nifty Pharma", "28": "NSE_INDEX|Nifty FMCG", "31": "NSE_INDEX|Nifty Metal", "33": "NSE_INDEX|Nifty PSU Bank",
    "34": "NSE_INDEX|Nifty Realty", "42": "NSE_INDEX|Nifty Energy", "19": "NSE_INDEX|Nifty 500",
}
_SEGMENT_TO_MASTER = {"NSE_EQ": "NSE_EQ", "NSE_FNO": "NSE_FO"}


class UpstoxError(RuntimeError):
    pass


class UpstoxLimit(UpstoxError):
    """Client-side request budget exhausted (the caller should fall back)."""


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


class _Budget:
    """Sliding-window request budget: Upstox allows 50/s, 500/min and 2000 per 30 min; stay well inside."""

    def __init__(self, per_second: float = 20.0, per_minute: int = 400, per_30min: int = 1700) -> None:
        self.min_gap = 1.0 / per_second
        self.per_minute, self.per_30min = per_minute, per_30min
        self.calls: deque[float] = deque()
        self.last = 0.0
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            now = time.time()
            while self.calls and now - self.calls[0] > 1800:
                self.calls.popleft()
            if len(self.calls) >= self.per_30min:
                raise UpstoxLimit("30-minute request budget used up")
            if sum(1 for c in self.calls if now - c <= 60) >= self.per_minute:
                raise UpstoxLimit("1-minute request budget used up")
            wait = self.min_gap - (now - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls.append(self.last)


class UpstoxClient:
    def __init__(self, token: str | None = None, session: Any = None, master: list[dict[str, Any]] | None = None,
                 budget: _Budget | None = None, batch_size: int = 150) -> None:
        self.token = (token or os.getenv("UPSTOX_ANALYTICS_TOKEN", "") or os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()
        self._session = session
        self._master = master
        self._maps: dict[str, dict[str, str]] | None = None
        self._reverse: dict[str, tuple[str, str]] = {}
        self.budget = budget or _Budget()
        self.batch_size = max(1, batch_size)

    # ------------------------------------------------------------------ instrument mapping
    def _http(self):
        if self._session is not None:
            return self._session
        import requests

        return requests

    def _load_master(self) -> list[dict[str, Any]]:
        if self._master is not None:
            return self._master
        try:
            fresh = MASTER_CACHE.exists() and time.time() - MASTER_CACHE.stat().st_mtime < 86400
            if not fresh:
                r = self._http().get(MASTER_URL, timeout=60)
                if r.status_code == 200:
                    MASTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    MASTER_CACHE.write_bytes(r.content)
            self._master = json.loads(gzip.decompress(MASTER_CACHE.read_bytes()).decode("utf-8"))
        except Exception as exc:                            # noqa: BLE001
            raise UpstoxError(f"instrument master unavailable: {type(exc).__name__}") from exc
        return self._master

    def _build_maps(self) -> dict[str, dict[str, str]]:
        if self._maps is not None:
            return self._maps
        maps: dict[str, dict[str, str]] = {"NSE_EQ": {}, "NSE_FNO": {}, "IDX_I": dict(INDEX_KEYS)}
        for row in self._load_master():
            seg = row.get("segment")
            token = str(row.get("exchange_token") or "")
            if not token or not row.get("instrument_key"):
                continue
            if seg == "NSE_EQ" and row.get("instrument_type") == "EQ":
                maps["NSE_EQ"][token] = row["instrument_key"]
            elif seg == "NSE_FO":
                maps["NSE_FNO"][token] = row["instrument_key"]
        self._maps = maps
        for segment, mapping in maps.items():
            for sid, key in mapping.items():
                self._reverse[key] = (segment, sid)
        return maps

    def instrument_key(self, segment: str, security_id: str | int) -> str | None:
        return self._build_maps().get(str(segment).upper(), {}).get(str(int(float(security_id))))

    # ------------------------------------------------------------------ quotes
    def _get(self, path: str, params: Mapping[str, Any], auth: bool) -> dict[str, Any]:
        self.budget.take()
        headers = {"Accept": "application/json"}
        if auth:
            if not self.token:
                raise UpstoxError("UPSTOX_ANALYTICS_TOKEN is not set")
            headers["Authorization"] = f"Bearer {self.token}"
        r = self._http().get(BASE + path, params=dict(params), headers=headers, timeout=15)
        if r.status_code == 429:
            raise UpstoxLimit("HTTP 429")
        if r.status_code != 200:
            raise UpstoxError(f"HTTP {r.status_code}: {str(getattr(r, 'text', ''))[:120]}")
        body = r.json()
        if isinstance(body, Mapping) and body.get("status") == "error":
            raise UpstoxError(str(body.get("errors"))[:160])
        return body

    @staticmethod
    def _normalise_quote(item: Mapping[str, Any]) -> dict[str, Any]:
        ohlc = item.get("ohlc") or {}
        last = _f(item.get("last_price"))
        close = _f(ohlc.get("close"))
        net = _f(item.get("net_change"))
        # Dhan's ohlc.close is YESTERDAY's close during the session; Upstox's close can be the latest close, so fall back to
        # last_price - net_change when close just equals the last price.
        if (close <= 0 or abs(close - last) < 1e-9) and last > 0 and net != 0:
            close = last - net
        out: dict[str, Any] = {
            "last_price": last,
            "ohlc": {"open": _f(ohlc.get("open")), "high": _f(ohlc.get("high")), "low": _f(ohlc.get("low")), "close": close},
            "volume": int(_f(item.get("volume"))),
            "average_price": _f(item.get("average_price")),
            "oi": int(_f(item.get("oi"))),
            "net_change": net,
            "buy_quantity": int(_f(item.get("total_buy_quantity"))),
            "sell_quantity": int(_f(item.get("total_sell_quantity"))),
            "last_trade_time": item.get("last_trade_time") or item.get("timestamp") or "",
        }
        depth = item.get("depth")
        if isinstance(depth, Mapping):
            out["depth"] = {side: [{"quantity": int(_f(l.get("quantity"))), "price": _f(l.get("price")), "orders": int(_f(l.get("orders")))}
                                   for l in (depth.get(side) or [])] for side in ("buy", "sell")}
        return out

    def get_market_quotes(self, instruments: Mapping[str, Sequence[str | int]], *, mode: str = "quote") -> dict[str, dict[str, Any]]:
        mode = str(mode).strip().lower()
        if mode not in {"ltp", "ohlc", "quote"}:
            raise ValueError("Market Quote mode must be ltp, ohlc or quote")
        self._build_maps()
        wanted: list[str] = []
        for segment, ids in instruments.items():
            for sid in ids:
                key = self.instrument_key(str(segment), sid)
                if key:
                    wanted.append(key)
        merged: dict[str, dict[str, Any]] = {}
        for i in range(0, len(wanted), self.batch_size):
            batch = wanted[i:i + self.batch_size]
            body = self._get("/v2/market-quote/quotes", {"instrument_key": ",".join(batch)}, auth=True)
            data = body.get("data") or {}
            for _name, item in data.items():
                if not isinstance(item, Mapping):
                    continue
                key = item.get("instrument_token")
                hit = self._reverse.get(str(key))
                if hit is None:
                    continue
                segment, sid = hit
                merged.setdefault(segment, {})[sid] = self._normalise_quote(item)
        return merged

    # ------------------------------------------------------------------ candles
    def get_intraday_candles(self, *, security_id: str | int, segment: str, instrument: str = "", interval: int, from_datetime: datetime,
                             to_datetime: datetime, oi: bool = False) -> dict[str, list[Any]]:
        if interval not in {1, 5, 15, 25, 60}:
            raise ValueError("Intraday interval must be one of 1, 5, 15, 25 or 60")
        if to_datetime <= from_datetime:
            raise ValueError("to_datetime must be after from_datetime")
        key = self.instrument_key(str(segment), security_id)
        if not key:
            raise UpstoxError(f"no Upstox instrument for {segment}:{security_id}")
        rows: dict[int, list[float]] = {}

        def add(candles: Sequence[Sequence[Any]]) -> None:
            for c in candles:
                ts = datetime.fromisoformat(str(c[0]))
                ts = ts if ts.tzinfo else ts.replace(tzinfo=IST)
                rows[int(ts.timestamp())] = [_f(c[1]), _f(c[2]), _f(c[3]), _f(c[4]), _f(c[5]), _f(c[6]) if len(c) > 6 else 0.0]

        today = datetime.now(IST).date()
        start_day = from_datetime.date()
        if start_day < today:                               # completed sessions
            end_day = min(to_datetime.date(), today - timedelta(days=1))
            if end_day >= start_day:
                body = self._get(f"/v3/historical-candle/{key}/minutes/{interval}/{end_day.isoformat()}/{start_day.isoformat()}", {}, auth=False)
                add((body.get("data") or {}).get("candles") or [])
        if to_datetime.date() >= today:                     # today's session so far
            body = self._get(f"/v3/historical-candle/intraday/{key}/minutes/{interval}", {}, auth=False)
            add((body.get("data") or {}).get("candles") or [])
        stamps = sorted(rows)
        out: dict[str, list[Any]] = {k: [] for k in ("open", "high", "low", "close", "volume", "timestamp")}
        if oi:
            out["open_interest"] = []
        for ts in stamps:
            o, h, l, c, v, oi_v = rows[ts]
            out["timestamp"].append(ts)
            out["open"].append(o); out["high"].append(h); out["low"].append(l); out["close"].append(c); out["volume"].append(v)
            if oi:
                out["open_interest"].append(oi_v)
        return out
