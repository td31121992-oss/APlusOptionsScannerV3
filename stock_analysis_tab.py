from __future__ import annotations

import csv
import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from analytics.order_flow import build_order_flow
from stock_movement_intelligence import build_why_moving

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
CHART_BASE = ROOT / "data" / "chart_history"

CANDIDATE_FILES = (
    "intraday_movement_candidates.csv",
    "opening_momentum_candidates.csv",
    "intraday_entry_ready.csv",
    "intraday_fresh_movement.csv",
    "intraday_wait_for_pullback.csv",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _read_market_watch() -> dict[str, Any]:
    path = REPORTS / "fno_market_watch_latest.json"
    if not path.is_file():
        return {"generated_at": "", "rows": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"generated_at": "", "rows": []}
    except Exception:
        return {"generated_at": "", "rows": []}


def _market_row(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    payload = _read_market_watch()
    for row in payload.get("rows", []):
        if str(row.get("symbol") or "").upper() == symbol:
            return dict(row)
    return {}


def _latest_candidate(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    best: dict[str, Any] = {}
    best_mtime = -1.0
    for name in CANDIDATE_FILES:
        path = REPORTS / name
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        for row in _read_csv(path):
            if str(row.get("symbol") or "").upper() != symbol:
                continue
            if not best or mtime >= best_mtime:
                best = dict(row)
                best["_source_file"] = name
                best_mtime = mtime
    return best


def _safe_day(day: str) -> str:
    value = str(day or "").strip()
    try:
        from datetime import date, datetime
        parsed = date.fromisoformat(value)
        return parsed.isoformat()
    except ValueError:
        return ""


def _load_points(day: str, symbol: str) -> list[dict[str, Any]]:
    safe_day = _safe_day(day)
    if not safe_day:
        return []
    path = CHART_BASE / safe_day / "market_watch_1m.csv"
    rows = _read_csv(path)
    symbol = symbol.strip().upper()
    out = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        out.append({
            "time": str(row.get("minute") or ""),
            "ltp": _f(row.get("ltp")),
            "from_open_pct": _f(row.get("from_open_pct")),
            "day_high": _f(row.get("day_high")),
            "day_low": _f(row.get("day_low")),
            "range_position_pct": _f(row.get("range_position_pct")),
            "volume": _f(row.get("volume")),
        })
    if out:
        return out
    return _load_dhan_intraday_points(safe_day, symbol)


_CHART_FALLBACK_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_CHART_FALLBACK_CACHE_SECONDS = 15.0


def _load_dhan_intraday_points(day: str, symbol: str) -> list[dict[str, Any]]:
    """Fallback to Dhan 1-minute candles when the local chart-history file is absent."""
    safe_day = _safe_day(day)
    symbol = str(symbol or "").strip().upper()
    if not safe_day or not symbol:
        return []
    # Dhan intraday fallback is used only for the current trading day.
    # Historical days must continue to rely on the local chart-history archive.
    from datetime import date
    if safe_day != date.today().isoformat():
        return []

    cache_key = (safe_day, symbol)
    now = time.monotonic()
    cached = _CHART_FALLBACK_CACHE.get(cache_key)
    if cached and now - cached[0] < _CHART_FALLBACK_CACHE_SECONDS:
        return cached[1]

    try:
        from config import AppConfig
        from core.dhan_client import DhanClient
        from core.instrument_loader import InstrumentLoader

        cfg = AppConfig.from_env()
        loader = InstrumentLoader(cfg).load(force_refresh=False)
        underlying = loader.get(symbol)
        if underlying is None:
            return []

        security_id = int(getattr(underlying, "security_id"))
        segment = str(getattr(underlying, "exchange_segment", "NSE_EQ") or "NSE_EQ").upper()

        start = datetime.strptime(f"{safe_day} 09:15:00", "%Y-%m-%d %H:%M:%S")
        end = datetime.now()
        if end <= start:
            return []

        client = DhanClient(cfg.dhan)
        candles = client.get_intraday_candles(
            security_id=security_id,
            segment=segment,
            instrument="EQUITY",
            interval=1,
            from_datetime=start,
            to_datetime=end,
            oi=False,
        )

        closes = candles.get("close", [])
        timestamps = candles.get("timestamp", [])
        size = min(len(closes), len(timestamps))
        points: list[dict[str, Any]] = []
        for idx in range(size):
            ltp = _f(closes[idx])
            if ltp <= 0:
                continue
            points.append({
                "time": str(timestamps[idx]),
                "ltp": ltp,
                "from_open_pct": 0.0,
                "day_high": 0.0,
                "day_low": 0.0,
                "range_position_pct": 0.0,
                "volume": _f((candles.get("volume", []) or [0])[idx]) if idx < len(candles.get("volume", []) or []) else 0.0,
            })

        _CHART_FALLBACK_CACHE[cache_key] = (now, points)
        return points
    except Exception:
        return []


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    value = values[0]
    for x in values[1:]:
        value = alpha * x + (1.0 - alpha) * value
    return value


def _rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = []
    losses = []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _move(values: list[float], minutes: int) -> float:
    if len(values) <= minutes:
        return 0.0
    base = values[-minutes - 1]
    return ((values[-1] - base) / base * 100.0) if base else 0.0


def _technical(points: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    prices = [x["ltp"] for x in points if x["ltp"] > 0]
    volumes = [max(0.0, _f(x.get("volume"))) for x in points]
    vwap_num = sum(_f(x.get("ltp")) * v for x, v in zip(points, volumes))
    vwap_den = sum(volumes)
    vwap = vwap_num / vwap_den if vwap_den else _f(market.get("vwap"))
    ltp = prices[-1] if prices else _f(market.get("ltp"))
    vwap_gap = ((ltp - vwap) / vwap * 100.0) if vwap and ltp else 0.0
    recent = volumes[-1] if volumes else 0.0
    baseline = [v for v in volumes[-21:-1] if v > 0]
    rvat = (recent / (sum(baseline) / len(baseline))) if baseline else 0.0
    return {
        "ema9_1m": round(_ema(prices, 9), 2) if prices else 0.0,
        "ema20_1m": round(_ema(prices, 20), 2) if prices else 0.0,
        "ema50_1m": round(_ema(prices, 50), 2) if prices else 0.0,
        "rsi14_1m": round(_rsi(prices, 14), 1) if prices else 50.0,
        "move_5m_pct": round(_move(prices, 5), 3),
        "move_10m_pct": round(_move(prices, 10), 3),
        "move_15m_pct": round(_move(prices, 15), 3),
        "move_30m_pct": round(_move(prices, 30), 3),
        "points": len(prices),
        "vwap": round(vwap, 2),
        "vwap_distance_percent": round(vwap_gap, 3),
        "rvat_1m": round(rvat, 2),
    }


def _status(candidate: dict[str, Any]) -> str:
    if not candidate:
        return "NOT_IN_CURRENT_SHORTLIST"
    decision = str(candidate.get("safety_decision") or "").upper()
    paper = str(candidate.get("paper_trade_status") or "").upper()
    actionable = str(candidate.get("actionable") or "").lower() == "true"
    if decision:
        return decision
    if paper:
        return paper
    if actionable:
        return "ACTIONABLE_CANDIDATE"
    return str(candidate.get("selection_tier") or candidate.get("stage") or "ANALYZED")


_ORDER_FLOW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ORDER_FLOW_CACHE_SECONDS = 4.0


def order_flow_payload(symbol: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "data_status": "UNAVAILABLE", "error": "Symbol is required"}
    now = time.monotonic()
    cached = _ORDER_FLOW_CACHE.get(symbol)
    if cached and now - cached[0] < _ORDER_FLOW_CACHE_SECONDS:
        return cached[1]
    try:
        client, loader = _option_chain_runtime()
        underlying = loader.get(symbol)
        if underlying is None:
            return {"ok": False, "data_status": "UNAVAILABLE", "error": f"{symbol} is not in the loaded F&O universe"}
        segment = str(getattr(underlying, "exchange_segment", "NSE_EQ") or "NSE_EQ").upper()
        payload = build_order_flow(
            client=client,
            security_id=int(getattr(underlying, "security_id")),
            segment=segment,
            points=points,
        )
    except Exception as exc:
        payload = {"ok": False, "data_status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
    _ORDER_FLOW_CACHE[symbol] = (now, payload)
    return payload


def analysis_payload(day: str, symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    market = _market_row(symbol)
    points = _load_points(day, symbol)
    candidate = _latest_candidate(symbol)
    technical = _technical(points, market)
    order_flow = order_flow_payload(symbol, points)
    intelligence = build_why_moving(
        day=day,
        symbol=symbol,
        market=market,
        technical=technical,
        points=points,
        candidate=candidate,
    )
    direction = str(market.get("direction") or "").upper()
    bullish = direction == "UP"
    bearish = direction == "DOWN"

    def _first_number(*keys: str) -> float | None:
        for key in keys:
            value = candidate.get(key)
            if value not in (None, ""):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
            value = market.get(key)
            if value not in (None, ""):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    breakout = bool(candidate.get("opening_range_breakout")) or (
        bool(candidate.get("fresh_day_high")) if bullish
        else bool(candidate.get("fresh_day_low")) if bearish
        else False
    )
    vwap_gap = _f(candidate.get("vwap_distance_percent"), technical.get("vwap_distance_percent"))
    vwap_ok = (vwap_gap > 0.05) if bullish else (vwap_gap < -0.05) if bearish else False
    day_level = bool(candidate.get("fresh_day_high")) if bullish else bool(candidate.get("fresh_day_low")) if bearish else False
    prev_level = bool(
        candidate.get("previous_day_high_breakout")
        or candidate.get("previous_day_low_breakdown")
        or candidate.get("fresh_previous_day_high")
        or candidate.get("fresh_previous_day_low")
        or candidate.get("pdh_breakout")
        or candidate.get("pdl_breakdown")
    )
    structure_checks = {
        "breakout": breakout,
        "vwap": vwap_ok,
        "day_level": day_level,
        "previous_day_level": prev_level,
    }
    structure_score = sum(1 for value in structure_checks.values() if value)
    relative_strength = _first_number("relative_strength_pct", "vs_nifty_pct", "nifty_relative_pct")
    futures_oi = _first_number("futures_oi_pct", "fut_oi_pct", "futures_oi_change_pct", "oi_change_pct")

    confirmation = {
        "direction": "BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL",
        "structure_score": structure_score,
        "structure_total": 4,
        "structure_checks": structure_checks,
        "relative_strength_pct": round(relative_strength, 3) if relative_strength is not None else None,
        "rvat": round(_f(candidate.get("relative_volume"), technical.get("rvat_1m")), 2),
        "vwap_gap_pct": round(vwap_gap, 3),
        "futures_oi_pct": round(futures_oi, 3) if futures_oi is not None else None,
        "order_flow_score": order_flow.get("order_flow_score") if order_flow.get("ok") else None,
        "order_flow_bias": order_flow.get("order_flow_bias") if order_flow.get("ok") else "UNAVAILABLE",
    }
    signals: list[str] = []

    if direction == "UP":
        signals.append("Price is above its 09:15 open")
    elif direction == "DOWN":
        signals.append("Price is below its 09:15 open")

    if _f(market.get("range_position_pct")) >= 80:
        signals.append("Trading near the day's upper range")
    elif _f(market.get("range_position_pct")) <= 20:
        signals.append("Trading near the day's lower range")

    if technical["rsi14_1m"] >= 70:
        signals.append("Short-term RSI is elevated")
    elif technical["rsi14_1m"] <= 30:
        signals.append("Short-term RSI is depressed")

    if technical["ema9_1m"] and technical["ema20_1m"]:
        signals.append(
            "1-minute EMA9 is above EMA20"
            if technical["ema9_1m"] > technical["ema20_1m"]
            else "1-minute EMA9 is below EMA20"
        )

    if candidate:
        for key in ("setup_family", "pivot_state", "opening_range_breakout", "opening_direction_confirmed"):
            value = candidate.get(key)
            if value not in (None, "", False, "False"):
                signals.append(f"{key.replace('_', ' ').title()}: {value}")

    return {
        "generated_at": _read_market_watch().get("generated_at", ""),
        "day": day,
        "symbol": symbol,
        "market": market,
        "technical": technical,
        "order_flow": order_flow,
        "confirmation": confirmation,
        "candidate": candidate,
        "candidate_status": _status(candidate),
        "intelligence": intelligence,
        "points": points[-180:],
        "signals": signals[:12],
        "read_only": True,
        "trading_engine_untouched": True,
    }




_OPTION_CHAIN_LOCK = threading.Lock()
_OPTION_CHAIN_CLIENT: Any = None
_OPTION_CHAIN_LOADER: Any = None
_OPTION_CHAIN_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_OPTION_CHAIN_CACHE_SECONDS = 15.0


def _option_chain_runtime() -> tuple[Any, Any]:
    global _OPTION_CHAIN_CLIENT, _OPTION_CHAIN_LOADER
    if _OPTION_CHAIN_CLIENT is None or _OPTION_CHAIN_LOADER is None:
        from config import AppConfig
        from core.dhan_client import DhanClient
        from core.instrument_loader import InstrumentLoader
        cfg = AppConfig.from_env()
        _OPTION_CHAIN_CLIENT = DhanClient(cfg.dhan)
        _OPTION_CHAIN_LOADER = InstrumentLoader(cfg).load(force_refresh=False)
    return _OPTION_CHAIN_CLIENT, _OPTION_CHAIN_LOADER


def _chain_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict) and isinstance(data.get("oc"), dict):
        return data
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        nested = data["data"]
        if isinstance(nested.get("oc"), dict):
            return nested
    if isinstance(raw.get("oc"), dict):
        return raw
    return {}


def _chain_leg(raw: Any, side: str, strike: float) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    greeks = raw.get("greeks") if isinstance(raw.get("greeks"), dict) else {}
    oi = int(_f(raw.get("oi")))
    previous_oi = int(_f(raw.get("previous_oi")))
    oi_change = oi - previous_oi if previous_oi else 0
    volume = int(_f(raw.get("volume")))
    return {
        "side": side, "strike": strike,
        "security_id": str(raw.get("security_id") or ""),
        "ltp": round(_f(raw.get("last_price")), 2),
        "oi": oi, "previous_oi": previous_oi, "oi_change": oi_change,
        "oi_change_pct": round(oi_change / previous_oi * 100.0, 2) if previous_oi else 0.0,
        "volume": volume, "iv": round(_f(raw.get("implied_volatility")), 2),
        "delta": round(_f(greeks.get("delta")), 4),
        "gamma": round(_f(greeks.get("gamma")), 6),
        "theta": round(_f(greeks.get("theta")), 4),
        "vega": round(_f(greeks.get("vega")), 4),
        "bid": round(_f(raw.get("top_bid_price")), 2),
        "ask": round(_f(raw.get("top_ask_price")), 2),
    }


def option_chain_payload(symbol: str, expiry: str = "") -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "Symbol is required"}

    now = time.monotonic()
    with _OPTION_CHAIN_LOCK:
        client, loader = _option_chain_runtime()
        underlying = loader.get(symbol)
        if underlying is None:
            return {"ok": False, "error": f"{symbol} is not in the loaded F&O universe"}

        expiries = sorted({
            str(getattr(c, "expiry", "") or "")
            for c in getattr(underlying, "contracts", []) or []
            if str(getattr(c, "expiry", "") or "")
        })
        selected_expiry = expiry if expiry in expiries else (expiries[0] if expiries else "")
        if not selected_expiry:
            return {"ok": False, "error": f"No active expiry found for {symbol}"}

        cache_key = (symbol, selected_expiry)
        cached = _OPTION_CHAIN_CACHE.get(cache_key)
        if cached and now - cached[0] < _OPTION_CHAIN_CACHE_SECONDS:
            return cached[1]

        raw = client.get_option_chain(int(underlying.security_id), selected_expiry, "NSE_EQ")
        data = _chain_payload(raw)
        chain = data.get("oc")
        if not isinstance(chain, dict) or not chain:
            return {"ok": False, "error": "Dhan returned no option-chain strikes"}

        spot = _f(data.get("last_price"))
        rows = []
        for raw_strike, raw_entry in chain.items():
            try:
                strike = float(raw_strike)
            except (TypeError, ValueError):
                continue
            if not isinstance(raw_entry, dict):
                continue
            ce = _chain_leg(raw_entry.get("ce"), "CE", strike)
            pe = _chain_leg(raw_entry.get("pe"), "PE", strike)
            if ce or pe:
                rows.append({"strike": strike, "ce": ce, "pe": pe})

        rows.sort(key=lambda x: x["strike"])
        if not rows:
            return {"ok": False, "error": "No usable option-chain rows"}

        atm = min(rows, key=lambda x: abs(x["strike"] - spot))["strike"] if spot else rows[len(rows)//2]["strike"]
        idx = next((i for i, row in enumerate(rows) if row["strike"] == atm), 0)
        visible = rows[max(0, idx - 8):min(len(rows), idx + 9)]

        total_ce_oi = sum((r["ce"] or {}).get("oi", 0) for r in rows)
        total_pe_oi = sum((r["pe"] or {}).get("oi", 0) for r in rows)
        total_ce_vol = sum((r["ce"] or {}).get("volume", 0) for r in rows)
        total_pe_vol = sum((r["pe"] or {}).get("volume", 0) for r in rows)

        call_wall = max(rows, key=lambda r: (r["ce"] or {}).get("oi", 0))["strike"]
        put_wall = max(rows, key=lambda r: (r["pe"] or {}).get("oi", 0))["strike"]

        pain = []
        for settlement in rows:
            settle = settlement["strike"]
            value = 0.0
            for r in rows:
                value += max(0.0, settle - r["strike"]) * (r["ce"] or {}).get("oi", 0)
                value += max(0.0, r["strike"] - settle) * (r["pe"] or {}).get("oi", 0)
            pain.append((value, settle))
        max_pain = min(pain)[1] if pain else 0.0

        payload = {
            "ok": True, "symbol": symbol, "security_id": str(underlying.security_id),
            "spot": round(spot, 2), "expiry": selected_expiry,
            "expiries": expiries[:20], "atm": atm,
            "pcr_oi": round(total_pe_oi / total_ce_oi, 3) if total_ce_oi else 0.0,
            "pcr_volume": round(total_pe_vol / total_ce_vol, 3) if total_ce_vol else 0.0,
            "call_wall": call_wall, "put_wall": put_wall, "max_pain": max_pain,
            "captured_at": datetime.now().isoformat(), "rows": visible,
        }
        _OPTION_CHAIN_CACHE[cache_key] = (now, payload)
        return payload


STOCK_ANALYSIS_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Stock Analysis</title>
<style>
:root{--bg:#080d19;--panel:#11192b;--panel2:#0d1424;--line:#26334c;--text:#e8effc;--muted:#91a3c0;--green:#17c964;--red:#f31260;--cyan:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.nav{position:sticky;top:0;z-index:20;display:flex;gap:7px;overflow:auto;padding:10px 14px;border-bottom:1px solid var(--line);background:#080d19}
.nav a{white-space:nowrap;color:var(--text);text-decoration:none;border:1px solid var(--line);background:var(--panel);padding:8px 11px;border-radius:9px;font-size:12px;font-weight:700}
.header{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.title{font-size:24px;font-weight:850}.sub{font-size:12px;color:var(--muted);margin-top:4px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 18px}.toolbar input,.toolbar button{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:9px;padding:9px 12px}.toolbar button{cursor:pointer;font-weight:700}
.wrap{padding:0 18px 22px}.cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:11px}.label{font-size:10px;color:var(--muted)}.value{font-size:18px;font-weight:800;margin-top:5px}.up{color:var(--green)}.down{color:var(--red)}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:10px;margin-top:10px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.pt{padding:11px 13px;border-bottom:1px solid var(--line);font-weight:800}.body{padding:12px}.rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px}.metric b{display:block;font-size:13px}.metric span{font-size:11px;color:var(--muted)}
.intel-sections{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.intel-section{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:10px}.intel-section h3{font-size:11px;color:var(--muted);margin:0 0 6px}.intel-section ul{margin:0;padding-left:17px;font-size:12px;line-height:1.5}.intel-confidence{color:#9ff0bd;font-size:11px;font-weight:700;margin-bottom:9px}
#chart{height:390px;padding:8px}.chartline{fill:none;stroke:var(--cyan);stroke-width:2.5}.gridline{stroke:var(--line);stroke-width:1}.point{font-size:10px;fill:var(--muted)}
ul{margin:0;padding-left:18px;color:#cbd7eb;font-size:12px;line-height:1.8}.notice{margin-top:10px;padding:10px 12px;border:1px solid #3a2e60;background:#15112a;border-radius:10px;color:#cfc5f7;font-size:11px}
@media(max-width:1000px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.grid{grid-template-columns:1fr}}
 @media(max-width:600px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.wrap{padding:0 10px 16px}.header{padding:12px}.toolbar{padding:10px}.title{font-size:19px}.rows,.intel-sections{grid-template-columns:1fr}#chart{height:300px}}
</style></head>
<body>
<div class="nav">
<a href="/">LIVE TRADING</a><a href="/fno-market-watch">F&amp;O MARKET WATCH</a><a href="/stock-analysis">STOCK ANALYSIS</a>
<a href="/sector-performance">SECTOR PERFORMANCE</a><a href="/opening-structure">OPENING STRUCTURE</a><a href="/stock-charts">STOCK CHARTS</a>
</div>
<div class="header"><div><div class="title" id="title">APlus Stock Analysis</div><div class="sub">Read-only analysis layer • does not place, modify or cancel orders</div></div><div class="sub" id="updated">Loading...</div></div>
<div class="toolbar"><input id="symbol" placeholder="Enter F&amp;O symbol e.g. RELIANCE"><input type="date" id="day"><button onclick="load()">Analyze</button><button onclick="backToWatch()">← Market Watch</button><select id="expiry"><option value="">Current expiry</option></select><button onclick="loadChain()">Load Option Chain</button></div>
<div class="wrap">
<div class="cards">
<div class="card"><div class="label">LTP</div><div class="value" id="ltp">-</div></div>
<div class="card"><div class="label">From 09:15</div><div class="value" id="fromopen">-</div></div>
<div class="card"><div class="label">Prev Close %</div><div class="value" id="prev">-</div></div>
<div class="card"><div class="label">Range Position</div><div class="value" id="range">-</div></div>
<div class="card"><div class="label">Direction</div><div class="value" id="direction">-</div></div>
<div class="card"><div class="label">APlus Status</div><div class="value" id="status">-</div></div>
</div>
 <div class="grid">
 <div class="panel"><div class="pt">Intraday Price / Movement</div><div id="chart"></div><div class="body"><div class="rows" id="market"></div></div></div>
 <div class="panel"><div class="pt">Technical Snapshot</div><div class="body"><div class="rows" id="technical"></div></div></div>
 </div>
 <div class="panel" style="margin-top:10px"><div class="pt">Order Flow &amp; Market Depth <span class="sub">Live Dhan depth • read-only confirmation layer</span></div><div class="body"><div class="rows" id="orderflow"></div><div class="notice">Depth values are live exchange-book quantities. Candle delta is a direction/volume proxy, not true aggressor-tagged trade delta.</div></div></div>
 <div class="panel" style="margin-top:10px"><div class="pt">APlus Multi-Factor Confirmation <span class="sub">Structure + relative strength + RVAT + VWAP + futures/OI + order flow</span></div><div class="body"><div class="rows" id="confirmation"></div></div></div>
 <div class="panel" style="margin-top:10px"><div class="pt">Why this stock is moving • local read-only evidence</div><div class="body"><div id="intelligence"></div><div class="notice">Possible drivers are evidence-based context, not confirmed causality or a trading recommendation.</div></div></div>
<div class="panel" style="margin-top:10px"><div class="pt">F&amp;O Option Chain <span class="sub">Read-only • cached to respect Dhan API limits</span></div><div class="body"><div class="rows" id="chainSummary"></div><div id="chain" style="margin-top:10px;overflow:auto"><div class="sub">Click “Load Option Chain” to fetch the selected expiry.</div></div></div></div>
<div class="grid">
<div class="panel"><div class="pt">APlus Scanner Context</div><div class="body"><div id="candidate"></div></div></div>
<div class="panel"><div class="pt">Why this stock is interesting</div><div class="body"><ul id="signals"></ul><div class="notice">This screen is diagnostic/read-only. It is intentionally isolated from APlus automated entry, risk, safety-gate and order-execution code.</div></div></div>
</div>
</div>
<script>
const q=s=>document.querySelector(s);
const n=v=>Number(v||0);
const pct=v=>(n(v)>=0?"+":"")+n(v).toFixed(2)+"%";
function cls(v){return n(v)>=0?"up":"down"}
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]))}
function card(k,v){return "<div class='metric'><b>"+esc(k)+"</b><span>"+v+"</span></div>"}
function drawChart(points){
  if(!points.length){q("#chart").innerHTML="<div class='sub' style='padding:20px'>No saved intraday history for this symbol/date.</div>";return}
  const w=1000,h=350,p=34,vals=points.map(x=>n(x.ltp)).filter(x=>x>0);
  let min=Math.min(...vals),max=Math.max(...vals);if(min===max){min-=1;max+=1}
  const x=i=>p+(w-2*p)*(i/(vals.length-1||1)),y=v=>h-p-(h-2*p)*(v-min)/(max-min);
  const line=vals.map((v,i)=>x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
  let grid="";for(let i=0;i<5;i++){const yy=p+(h-2*p)*i/4;grid+="<line class='gridline' x1='"+p+"' y1='"+yy+"' x2='"+(w-p)+"' y2='"+yy+"'/>";}
  q("#chart").innerHTML="<svg viewBox='0 0 "+w+" "+h+"' width='100%' height='100%' preserveAspectRatio='none'>"+grid+"<polyline class='chartline' points='"+line+"'/><text class='point' x='"+p+"' y='"+(h-8)+"'>"+esc(points[0].time)+"</text><text class='point' x='"+(w-p)+"' y='"+(h-8)+"' text-anchor='end'>"+esc(points[points.length-1].time)+"</text></svg>";
}
function render(d){
  const m=d.market||{},t=d.technical||{},c=d.candidate||{};
  const intel=d.intelligence||{},sections=intel.sections||[];
  q("#intelligence").innerHTML="<div class='intel-confidence'>Evidence confidence: "+esc(intel.confidence||"INSUFFICIENT_DATA")+" • Technical "+esc(intel.technical_alignment||"unknown")+" • Sector "+esc(intel.sector_alignment||"unknown")+" • Options "+esc(intel.options_alignment||"unknown")+"</div><div class='intel-sections'>"+sections.map(s=>"<section class='intel-section'><h3>"+esc(s.title)+"</h3><ul>"+(s.items||[]).map(x=>"<li>"+esc(x)+"</li>").join("")+"</ul></section>").join("")+"</div>";
  q("#title").textContent="APlus Stock Analysis • "+d.symbol;
  q("#updated").textContent=(d.generated_at?"Market snapshot "+d.generated_at:"No market snapshot")+" • "+(d.read_only?"READ ONLY":"");
  q("#ltp").textContent=m.ltp?Number(m.ltp).toLocaleString("en-IN",{maximumFractionDigits:2}):"-";
  q("#fromopen").textContent=pct(m.from_open_pct);q("#fromopen").className="value "+cls(m.from_open_pct);
  q("#prev").textContent=pct(m.from_prev_close_pct);q("#prev").className="value "+cls(m.from_prev_close_pct);
  q("#range").textContent=n(m.range_position_pct).toFixed(1)+"%";
  q("#direction").textContent=m.direction||"-";q("#direction").className="value "+(m.direction==="UP"?"up":m.direction==="DOWN"?"down":"");
  q("#status").textContent=d.candidate_status||"-";
  q("#status").className="value "+(String(d.candidate_status).includes("BLOCK")?"down":String(d.candidate_status).includes("ACTION")?"up":"");
  q("#market").innerHTML=[
    card("Sector",esc(m.sector||"UNCLASSIFIED")),card("09:15 Open",n(m.open_0915).toFixed(2)),
    card("Previous Close",n(m.previous_close).toFixed(2)),card("Gap",pct(m.gap_pct)),
    card("Day High",n(m.day_high).toFixed(2)),card("Day Low",n(m.day_low).toFixed(2)),
    card("From Open",pct(m.from_open_pct)),card("From Prev Close",pct(m.from_prev_close_pct))
  ].join("");
  q("#technical").innerHTML=[
    card("EMA9 (1m)",n(t.ema9_1m).toFixed(2)),card("EMA20 (1m)",n(t.ema20_1m).toFixed(2)),
    card("EMA50 (1m)",n(t.ema50_1m).toFixed(2)),card("RSI14 (1m)",n(t.rsi14_1m).toFixed(1)),
    card("5m Move",pct(t.move_5m_pct)),card("10m Move",pct(t.move_10m_pct)),
    card("15m Move",pct(t.move_15m_pct)),card("30m Move",pct(t.move_30m_pct)),
    card("VWAP",n(t.vwap).toFixed(2)),card("VWAP Gap",pct(t.vwap_distance_percent)),
    card("RVAT (1m)",n(t.rvat_1m).toFixed(2)+"x")
  ].join("");
  const cf=d.confirmation||{};
  const checks=cf.structure_checks||{};
  q("#confirmation").innerHTML=[
    card("Structure",n(cf.structure_score)+"/"+n(cf.structure_total||4)),
    card("Breakout",checks.breakout?"YES":"NO"),
    card("VWAP",checks.vwap?"YES":"NO"),
    card("Day Level",checks.day_level?"YES":"NO"),
    card("PDH/PDL",checks.previous_day_level?"YES":"NO"),
    card("vs NIFTY",cf.relative_strength_pct==null?"N/A":pct(cf.relative_strength_pct)),
    card("RVAT",n(cf.rvat).toFixed(2)+"x"),
    card("VWAP Gap",pct(cf.vwap_gap_pct)),
    card("Futures OI",cf.futures_oi_pct==null?"N/A":pct(cf.futures_oi_pct)),
    card("Order Flow",cf.order_flow_score==null?"N/A":n(cf.order_flow_score).toFixed(1)+"/100"),
    card("OF Bias",esc(cf.order_flow_bias||"-")),
    card("Overall Bias",esc(cf.direction||"-"))
  ].join("");
  const of=d.order_flow||{};
  if(of.ok){
    q("#orderflow").innerHTML=[
      card("Order Flow Bias",esc(of.order_flow_bias||"-")),
      card("Order Flow Score",n(of.order_flow_score).toFixed(1)+"/100"),
      card("5-Level Bid Depth",n(of.bid_depth_5).toLocaleString()),
      card("5-Level Ask Depth",n(of.ask_depth_5).toLocaleString()),
      card("Book Imbalance",pct(of.book_imbalance_pct)),
      card("Pending Buy/Sell",pct(of.pending_book_imbalance_pct)),
      card("Best Bid",n(of.best_bid).toFixed(2)+" × "+n(of.best_bid_qty).toLocaleString()),
      card("Best Ask",n(of.best_ask).toFixed(2)+" × "+n(of.best_ask_qty).toLocaleString()),
      card("Spread",n(of.spread).toFixed(4)),
      card("Candle Delta Proxy",n(of.candle_delta_proxy).toLocaleString()),
      card("Delta Proxy %",pct(of.candle_delta_proxy_pct)),
      card("Event",esc(of.event||"-"))
    ].join("");
  }else{
    q("#orderflow").innerHTML="<div class='sub'>Order flow unavailable: "+esc(of.error||"no depth data")+"</div>";
  }
  if(c && Object.keys(c).length){
    const keys=["stage","selection_tier","setup_family","score","trade_quality_score","movement_capture_score","trend_alignment_score","clean_trend_score","chase_risk_score","relative_volume","recent_relative_volume_15m","vwap","vwap_distance_percent","ema9_5m","ema20_5m","ema50_5m","ema9_15m","ema20_15m","rsi14_5m","adx14_5m","plus_di_5m","minus_di_5m","pivot_state","pivot_point","r1","r2","s1","s2","opening_range_breakout","opening_direction_confirmed","safety_decision","paper_trade_status"];
    q("#candidate").innerHTML=keys.filter(k=>c[k]!==undefined&&c[k]!==""&&c[k]!==null).map(k=>card(k.replaceAll("_"," "),esc(c[k]))).join("");
  }else{
    q("#candidate").innerHTML="<div class='sub'>This stock is not in the current detailed APlus candidate shortlist. Market-watch and locally calculated technical data are still shown.</div>";
  }
  q("#signals").innerHTML=(d.signals||[]).map(x=>"<li>"+esc(x)+"</li>").join("")||"<li>No additional local signals available.</li>";
  drawChart(d.points||[]);
}
async function load(){
  const sym=q("#symbol").value.trim().toUpperCase();if(!sym)return;
  const day=q("#day").value;
  const r=await fetch("/api/stock-analysis?symbol="+encodeURIComponent(sym)+"&day="+encodeURIComponent(day)+"&ts="+Date.now());
  render(await r.json());
}
async function loadChain(){
  const sym=q("#symbol").value.trim().toUpperCase();if(!sym)return;
  const expiry=q("#expiry").value;
  const r=await fetch("/api/stock-option-chain?symbol="+encodeURIComponent(sym)+"&expiry="+encodeURIComponent(expiry)+"&ts="+Date.now());
  const d=await r.json();
  if(!d.ok){q("#chain").innerHTML="<div class='sub'>"+esc(d.error||"Option chain unavailable")+"</div>";return}
  q("#expiry").innerHTML=(d.expiries||[]).map(x=>"<option value='"+esc(x)+"'>"+esc(x)+"</option>").join("");
  q("#expiry").value=d.expiry;
  q("#chainSummary").innerHTML=[
    card("ATM",n(d.atm).toFixed(2)),card("PCR OI",n(d.pcr_oi).toFixed(3)),card("PCR Volume",n(d.pcr_volume).toFixed(3)),
    card("Call OI Wall",n(d.call_wall).toFixed(2)),card("Put OI Wall",n(d.put_wall).toFixed(2)),card("Max Pain",n(d.max_pain).toFixed(2))
  ].join("");
  q("#chain").innerHTML="<table style='width:100%;border-collapse:collapse'><thead><tr><th>Strike</th><th>CE OI</th><th>CE ΔOI</th><th>CE IV</th><th>CE LTP</th><th>PE LTP</th><th>PE IV</th><th>PE ΔOI</th><th>PE OI</th></tr></thead><tbody>"+
    (d.rows||[]).map(r=>"<tr><td><b>"+n(r.strike).toFixed(2)+"</b></td><td>"+n(r.ce&&r.ce.oi).toLocaleString()+"</td><td>"+n(r.ce&&r.ce.oi_change).toLocaleString()+"</td><td>"+n(r.ce&&r.ce.iv).toFixed(2)+"</td><td>"+n(r.ce&&r.ce.ltp).toFixed(2)+"</td><td>"+n(r.pe&&r.pe.ltp).toFixed(2)+"</td><td>"+n(r.pe&&r.pe.iv).toFixed(2)+"</td><td>"+n(r.pe&&r.pe.oi_change).toLocaleString()+"</td><td>"+n(r.pe&&r.pe.oi).toLocaleString()+"</td></tr>").join("")+
    "</tbody></table>";
}
function backToWatch(){location.href="/fno-market-watch"}
const params=new URLSearchParams(location.search);
q("#symbol").value=(params.get("symbol")||"").toUpperCase();
const now=new Date();const localDate=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
q("#day").value=params.get("day")||localDate;
if(q("#symbol").value){load();setInterval(load,5000);}
</script></body></html>"""


__all__ = ["STOCK_ANALYSIS_HTML", "analysis_payload", "option_chain_payload", "order_flow_payload"]
