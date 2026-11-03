"""Sector rotation (RRG-style) from the Nifty sector indices, daily, against the Nifty 50. Read-only; nothing here trades.

For each sector index the relative strength line RS = index / Nifty 50 is standardised over a 10-day window (RS-Ratio, 100 = in line
with the market) and the same is done to the ratio's own change (RS-Momentum). Quadrants:

    LEADING    ratio >= 100, momentum >= 100      WEAKENING  ratio >= 100, momentum < 100
    IMPROVING  ratio <  100, momentum >= 100      LAGGING    ratio <  100, momentum < 100

This is an "RRG-style" read (a standardised version, not the vendor's exact JdK formula). The cache file data/cache/sector_rrg.json is
refreshed once a day (after the close by daily_indicators, or lazily by the dashboard) and is the only thing the scanner reads, so a
trade never waits on a network call. Per trade, `tags_for` records the sector's position and whether the trade's direction was WITH the
sector's relative strength (call in an outperforming sector, put in an underperforming one): a shadow tag, never a filter.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
CACHE = ROOT / "data" / "cache" / "sector_rrg.json"
WINDOW = 10
BENCH = "NIFTY 50"
# display name -> Dhan IDX_I security id
INDICES = {"NIFTY 50": 13, "BANK": 25, "FIN SERV": 27, "IT": 29, "AUTO": 14, "PHARMA": 32, "FMCG": 28, "METAL": 31, "PSU BANK": 33,
           "REALTY": 34, "ENERGY": 42, "INFRA": 43, "MEDIA": 30, "CONSUMPTION": 40, "PSE": 41}
# our F&O sector label (market-watch "sector") -> index used for it; None = no sensible index
SECTOR_TO_INDEX = {"IT": "IT", "Banking/Financial Services": "BANK", "Auto": "AUTO", "Pharma/Healthcare": "PHARMA", "FMCG/Consumer": "FMCG",
                   "Metals": "METAL", "Energy/Oil & Gas": "ENERGY", "Power/Utilities": "ENERGY", "Capital Goods": "INFRA",
                   "Consumer Durables": "CONSUMPTION", "Retail": "CONSUMPTION", "Telecom/Media": "MEDIA", "Logistics/Transportation": "INFRA"}


def quadrant(ratio: float, momentum: float) -> str:
    if ratio >= 100:
        return "LEADING" if momentum >= 100 else "WEAKENING"
    return "IMPROVING" if momentum >= 100 else "LAGGING"


def _stdz(series: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
            continue
        w = series[i + 1 - window:i + 1]
        mean = sum(w) / window
        sd = (sum((x - mean) ** 2 for x in w) / (window - 1)) ** 0.5
        out.append(100.0 + (series[i] - mean) / sd if sd > 0 else None)
    return out


def compute(closes: Mapping[str, Mapping[str, float]], window: int = WINDOW, tail: int = 5) -> dict[str, Any]:
    """closes: {index name: {YYYY-MM-DD: close}} including BENCH. Returns the RRG payload."""
    bench = closes.get(BENCH) or {}
    rows = []
    asof = ""
    for name, series in closes.items():
        if name == BENCH:
            continue
        days = sorted(d for d in series if d in bench)
        if len(days) < window * 2 + tail:
            continue
        rs = [series[d] / bench[d] for d in days if bench[d] > 0]
        ratio = _stdz(rs, window)
        valid = [(d, r) for d, r in zip(days, ratio) if r is not None]
        mom = _stdz([r for _, r in valid], window)
        pts = [(d, r, m) for (d, r), m in zip(valid, mom) if m is not None]
        if len(pts) < tail:
            continue
        d, r, m = pts[-1]
        asof = max(asof, d)

        def rel(n: int) -> float | None:
            if len(days) <= n:
                return None
            return round(((series[days[-1]] / series[days[-1 - n]]) - (bench[days[-1]] / bench[days[-1 - n]])) * 100, 2)

        rows.append({"sector": name, "ratio": round(r, 2), "momentum": round(m, 2), "quadrant": quadrant(r, m),
                     "rel5": rel(5), "rel10": rel(10),
                     "tail": [{"date": td, "ratio": round(tr, 2), "momentum": round(tm, 2), "quadrant": quadrant(tr, tm)} for td, tr, tm in pts[-tail:]]})
    rows.sort(key=lambda x: -x["ratio"])
    return {"ok": bool(rows), "asof": asof, "window": window, "rows": rows}


def fetch_daily(root: Path = ROOT, days: int = 150) -> dict[str, dict[str, float]]:
    import requests
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
    today = datetime.now(IST).date()
    out: dict[str, dict[str, float]] = {}
    for name, sid in INDICES.items():
        r = requests.post("https://api.dhan.co/v2/charts/historical", headers=headers, timeout=30, json={
            "securityId": str(sid), "exchangeSegment": "IDX_I", "instrument": "INDEX", "expiryCode": 0, "oi": False,
            "fromDate": (today - timedelta(days=days)).isoformat(), "toDate": (today + timedelta(days=1)).isoformat()})
        d = r.json() if r.status_code == 200 else {}
        out[name] = {str(datetime.fromtimestamp(int(t), IST).date()): float(c) for t, c in zip(d.get("timestamp") or [], d.get("close") or [])}
        time.sleep(0.4)
    return out


def refresh(root: Path = ROOT, fetch: Callable[..., dict] = fetch_daily, cache: Path | None = None) -> dict[str, Any]:
    payload = compute(fetch(root))
    payload["generated_at"] = datetime.now(IST).isoformat(timespec="seconds")
    if payload["ok"]:
        path = cache or (root / "data" / "cache" / "sector_rrg.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    return payload


def load_cache(path: Path = CACHE) -> dict[str, Any] | None:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if d.get("ok") else None
    except (OSError, ValueError):
        return None


def is_stale(payload: Mapping[str, Any] | None, today: date | None = None, max_days: int = 5) -> bool:
    if not payload or not payload.get("asof"):
        return True
    today = today or datetime.now(IST).date()
    return (today - date.fromisoformat(str(payload["asof"]))).days > max_days


def index_for(sector: str) -> str | None:
    return SECTOR_TO_INDEX.get(str(sector or "").strip())


def tags_for(symbol: str, direction: str, market_rows: Sequence[Mapping[str, Any]], cache: Path = CACHE) -> dict[str, Any]:
    """Shadow tags for one trade. Empty dict when the sector has no index or the cache is missing/stale."""
    try:
        row = next((r for r in market_rows if str(r.get("symbol") or "").upper() == str(symbol).upper()), None)
        sector = str((row or {}).get("sector") or "")
        idx = index_for(sector)
        data = load_cache(cache)
        if not idx or is_stale(data):
            return {"rrg_sector": sector} if sector else {}
        hit = next((r for r in data["rows"] if r["sector"] == idx), None)
        if not hit:
            return {"rrg_sector": sector}
        bull = str(direction).upper() == "BULLISH"
        aligned = (bull and hit["ratio"] >= 100) or ((not bull) and hit["ratio"] < 100)
        return {"rrg_sector": sector, "rrg_index": idx, "rrg_ratio": hit["ratio"], "rrg_momentum": hit["momentum"],
                "rrg_quadrant": hit["quadrant"], "rrg_aligned": bool(aligned), "rrg_asof": data.get("asof", "")}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
