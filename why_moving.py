"""Why is it moving? A ranked list of likely drivers behind a stock's move today. Read-only; it never claims a cause.

Evidence used (all already collected by APlus): the market-watch snapshot (market, sector and group-peer moves), the daily
indicators (previous-day high/low, 52-week levels), the order-book recorder (volume surges, VWAP side, buy/sell pressure,
level-break times), NSE announcements and news headlines. Drivers are listed as "likely", with times so the sequence
(news -> volume -> move) can be judged. Ownership-group peers come from company_profiles.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
GROUPS = ("Adani", "Tata", "Aditya Birla", "Murugappa", "Bajaj", "JSW", "Mahindra", "Hinduja", "Government of India",
          "Vedanta", "Reliance", "Godrej", "Larsen")


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def group_of(owner: str) -> str:
    for g in GROUPS:
        if g.lower() in str(owner).lower():
            return g
    return ""


def analyse(symbol: str, rows: list[dict[str, Any]], profiles: dict[str, dict[str, str]], indicators: dict[str, Any],
            book: list[dict[str, str]], announcements: list[dict[str, Any]], news: list[dict[str, Any]],
            candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    by = {r["symbol"]: r for r in rows}
    me = by.get(symbol)
    if not me:
        return {"ok": False, "error": "symbol not in today's market watch"}
    move, from_open, gap = _f(me.get("from_prev_close_pct")), _f(me.get("from_open_pct")), _f(me.get("gap_pct"))
    market = median([_f(r.get("from_prev_close_pct")) for r in rows]) if rows else 0.0
    sector = me.get("sector") or ""
    peers = [_f(r.get("from_prev_close_pct")) for r in rows if r.get("sector") == sector and r["symbol"] != symbol]
    sector_med = median(peers) if len(peers) >= 2 else None
    grp = group_of((profiles.get(symbol) or {}).get("owner", ""))
    gpeers = sorted(((s, _f(by[s].get("from_prev_close_pct"))) for s, p in profiles.items()
                     if s != symbol and s in by and group_of(p.get("owner", "")) == grp), key=lambda x: x[1]) if grp else []
    drivers: list[dict[str, Any]] = []

    def add(kind: str, title: str, detail: str = "", time: str = "", strength: int = 1) -> None:
        drivers.append({"kind": kind, "title": title, "detail": detail, "time": time, "strength": strength})

    # 1. market, sector, group
    excess_mkt = move - market
    add("market", f"Market: median F&O stock {market:+.2f}%", f"{symbol} {move:+.2f}% -> {excess_mkt:+.2f} points versus the market",
        strength=3 if abs(market) >= 1.0 and abs(excess_mkt) < 1.0 else 2 if abs(market) >= 0.5 else 1)
    if sector_med is not None:
        ex = move - sector_med
        add("sector", f"Sector ({sector}): median {sector_med:+.2f}% across {len(peers)} peers", f"{ex:+.2f} points versus the sector",
            strength=3 if abs(ex) < 1.0 and abs(sector_med - market) >= 0.5 else 1)
    big = [p for p in gpeers if abs(p[1]) >= 1.0 and (p[1] > 0) == (move > 0)]
    if grp and len(big) >= 2:
        add("group", f"{grp} group move: {len(big)} of {len(gpeers)} group stocks moved the same way",
            ", ".join(f"{s} {c:+.1f}%" for s, c in (big[:6])), strength=3)
    # 2. announcements and news today
    for a in sorted(announcements, key=lambda x: x.get("published_at", "")):
        sev = str(a.get("severity", "LOW")).upper()
        add("announcement", f"NSE announcement ({sev}): {a.get('desc', '')}", str(a.get("text", ""))[:160],
            str(a.get("published_at", ""))[11:16], strength=3 if sev == "HIGH" else 2 if sev == "MEDIUM" else 1)
    for n in news[:3]:
        add("news", str(n.get("title", ""))[:140], str(n.get("source", "")), str(n.get("time", "")), strength=2)
    # 3. technical triggers
    if abs(gap) >= 0.5:
        add("gap", f"Gap {gap:+.2f}% at the open", "the move partly happened before the market opened", "09:15", 2 if abs(gap) >= 1.5 else 1)
    ind = indicators.get(symbol) or {}
    ltp = _f(me.get("ltp"))
    if ind.get("pdl") and ltp < ind["pdl"]:
        add("level", "Below the previous day's low", f"previous low {ind['pdl']:.2f}", strength=2)
    if ind.get("pdh") and ltp > ind["pdh"]:
        add("level", "Above the previous day's high", f"previous high {ind['pdh']:.2f}", strength=2)
    if ind.get("hi_52w") and ltp > ind["hi_52w"]:
        add("level", "New 52-week high", f"{ind['hi_52w']:.2f}", strength=3)
    if ind.get("lo_52w") and 0 < ltp < ind["lo_52w"]:
        add("level", "New 52-week low", f"{ind['lo_52w']:.2f}", strength=3)
    if _f(me.get("range_position_pct")) <= 8 or _f(me.get("range_position_pct")) >= 92:
        add("trend", f"Trading at the {'bottom' if _f(me.get('range_position_pct')) <= 8 else 'top'} of today's range",
            f"range position {_f(me.get('range_position_pct')):.0f}%, {from_open:+.2f}% from the open", strength=1)
    # 4. order-book recorder: volume surge, level-break time, VWAP, pressure
    if len(book) >= 12:
        vols = [_f(r.get("volume")) for r in book]
        buckets = [(book[i]["time"][11:16], vols[i] - vols[i - 5]) for i in range(5, len(vols), 5) if vols[i] >= vols[i - 5]]
        if len(buckets) >= 4:
            med = median(b[1] for b in buckets) or 1.0
            top = max(buckets, key=lambda b: b[1])
            if top[1] / med >= 2.5:
                add("volume", f"Volume surge about {top[1] / med:.1f}x the usual 5-minute pace", "largest burst today", top[0], 2)
        pdl, pdh = _f(ind.get("pdl")), _f(ind.get("pdh"))
        for r in book:
            p = _f(r.get("ltp"))
            if pdl and 0 < p < pdl:
                add("level", "First trade below the previous day's low", f"{pdl:.2f}", r["time"][11:16], 2)
                break
            if pdh and p > pdh and move > 0:
                add("level", "First trade above the previous day's high", f"{pdh:.2f}", r["time"][11:16], 2)
                break
        last = book[-1]
        avg, imb = _f(last.get("avg_price")), sum(_f(r.get("imbalance")) for r in book[-10:]) / min(10, len(book))
        if avg and ltp:
            add("vwap", f"Price is {'below' if ltp < avg else 'above'} the day's average price (VWAP {avg:.2f})", "", strength=1)
        if abs(imb) >= 0.2:
            add("flow", f"Order book leaning {'to sellers' if imb < 0 else 'to buyers'}", f"net {imb:+.2f} over the last 10 readings", strength=1)
    if candidate:
        rv = _f(candidate.get("recent_relative_volume_15m"))
        if rv >= 2:
            add("volume", f"Last 15 minutes' volume is {rv:.1f}x normal", "scanner measurement", strength=2)
    timed = {d["title"].replace("First trade ", "") for d in drivers if d["title"].startswith("First trade")}
    drivers = [d for d in drivers if not (d["title"] in ("Below the previous day's low", "Above the previous day's high")
                                          and d["title"].replace("Below", "below").replace("Above", "above") in timed)]
    drivers.sort(key=lambda d: (-d["strength"], d["time"] or "99:99"))
    # verdict
    parts = [f"{symbol} {move:+.2f}% today (market {market:+.2f}%"]
    if sector_med is not None:
        parts.append(f", sector {sector_med:+.2f}%")
    if big:
        parts.append(f", {grp} group peers moving alike")
    text = "".join(parts) + ")."
    strong_news = [d for d in drivers if d["kind"] in ("announcement", "news") and d["strength"] >= 2]
    if big or (sector_med is not None and abs(move - sector_med) < 1.0 and abs(sector_med) >= 0.7):
        text += " Mostly a group or sector move rather than something specific to this company."
    elif abs(excess_mkt) < 1.0 and abs(market) >= 1.0:
        text += " Mostly the broad market."
    elif strong_news:
        text += " Company news today may be a factor."
    else:
        text += " No clear single driver in the data we hold."
    text += " These are likely drivers, not confirmed causes."
    return {"ok": True, "symbol": symbol, "move_pct": round(move, 2), "market_pct": round(market, 2),
            "sector": sector, "sector_pct": None if sector_med is None else round(sector_med, 2), "summary": text, "drivers": drivers[:12]}


def payload(symbol: str, root: Path = ROOT) -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    try:
        report = json.loads((root / "data" / "reports" / "intraday_movement_latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "scanner report not available"}
    rows = (report.get("fno_market_watch") or {}).get("rows", [])
    candidate = next((c for c in report.get("candidates", []) if c.get("symbol") == symbol), None)
    try:
        import company_profiles
        profiles = company_profiles.PROFILES
    except Exception:                                      # noqa: BLE001
        profiles = {}
    try:
        indicators = json.loads((root / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        indicators = {}
    book: list[dict[str, str]] = []
    try:
        files = sorted((root / "data" / "order_book").glob("*.csv"))
        if files:
            with files[-1].open(encoding="utf-8", newline="") as handle:
                book = [r for r in csv.DictReader(handle) if r.get("symbol") == symbol]
    except OSError:
        pass
    today = date.today().isoformat()
    announcements: list[dict[str, Any]] = []
    try:
        for line in (root / "data" / "news_intelligence" / "announcements.jsonl").read_text(encoding="utf-8").splitlines():
            a = json.loads(line)
            if a.get("symbol") == symbol and str(a.get("published_at", ""))[:10] == today:
                announcements.append(a)
    except (OSError, ValueError):
        pass
    news: list[dict[str, Any]] = []
    try:
        name = (profiles.get(symbol) or {}).get("name", symbol).split(" (")[0].lower()
        for line in (root / "data" / "news_intelligence" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1500:]:
            n = json.loads(line)
            try:
                when = parsedate_to_datetime(n.get("published_at_raw", "")).astimezone(IST)
            except (TypeError, ValueError):
                continue
            if when.date().isoformat() != today:
                continue
            if n.get("category") == f"STOCK_{symbol}" or name in str(n.get("title", "")).lower():
                news.append({"title": n.get("title", ""), "source": n.get("source", ""), "time": when.strftime("%H:%M")})
    except (OSError, ValueError):
        pass
    return analyse(symbol, rows, profiles, indicators, book, announcements, news, candidate)
