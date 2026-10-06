"""Control-room data for the APlus dashboard: health, 'why no trades?', positions, performance.

Pure read-only functions over the scanner's own files. Every section is isolated:
a failing source returns {"error": ...} for that section only. The access token is
never read into any returned value (only its expiry time).
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
SESSION_START, SESSION_STOP = clock_time(9, 15), clock_time(15, 30)


# ----------------------------------------------------------------------------- helpers
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=IST)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _clock_env(name: str, default: str) -> clock_time:
    raw = os.getenv(name, default).strip()
    try:
        hh, mm = raw.split(":")[:2]
        return clock_time(int(hh), int(mm))
    except (ValueError, TypeError):
        hh, mm = default.split(":")
        return clock_time(int(hh), int(mm))


def _safe(section: Callable[[], Any]) -> Any:
    try:
        return section()
    except Exception as exc:  # noqa: BLE001 - one broken source must not break the page
        return {"error": f"{type(exc).__name__}: {exc}"}


def _level(ok: bool | None, warn: bool = False) -> str:
    if ok is None:
        return "unknown"
    return "ok" if ok and not warn else ("warn" if ok else "bad")


# ----------------------------------------------------------------------------- market
def market_status(now: datetime, base: Path = ROOT) -> dict[str, Any]:
    from trading_calendar import is_trading_day

    holiday_file = base / "data" / "safety" / "nse_holidays.csv"
    trading_day, reason = is_trading_day(now.date(), holiday_file)
    last_entry = _clock_env("INTRADAY_LAST_NEW_ENTRY", "13:00")
    t = now.time()
    if not trading_day:
        state, note = "CLOSED", reason
    elif t < SESSION_START:
        state, note = "PRE_OPEN", f"opens in {int((datetime.combine(now.date(), SESSION_START, IST) - now).total_seconds() // 60)} min"
    elif t <= SESSION_STOP:
        state = "OPEN"
        note = "new entries allowed" if t <= last_entry else f"new entries closed after {last_entry.strftime('%H:%M')}"
    else:
        state, note = "CLOSED", "after market close"
    return {
        "state": state, "note": note, "trading_day": trading_day, "day_reason": reason,
        "entries_open": state == "OPEN" and t <= last_entry,
        "last_new_entry": last_entry.strftime("%H:%M"),
    }


# ----------------------------------------------------------------------------- health
def health(base: Path, now: datetime, market: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    report_path = base / "data" / "reports" / "intraday_movement_latest.json"
    report = _read_json(report_path) or {}
    in_market = market["state"] == "OPEN"

    # scanner heartbeat
    age = None
    generated = _parse_dt(report.get("generated_at"))
    if generated:
        age = max(0, int((now - generated).total_seconds()))
    if age is None:
        items.append({"key": "Scanner heartbeat", "level": "bad" if in_market else "unknown", "value": "no report yet", "detail": str(report_path.name)})
    else:
        stale = age > 300
        items.append({
            "key": "Scanner heartbeat",
            "level": ("bad" if stale else "ok") if in_market else "unknown",
            "value": f"last cycle {age}s ago" if age < 3600 else f"last cycle {age // 3600}h ago",
            "detail": f"cycle took {report.get('elapsed_seconds', '?')}s, phase {report.get('session_phase', '?')}",
        })

    # authorization latch
    runtime = _read_json(base / "data" / "intraday_movement" / "scanner_runtime_health.json") or {}
    status = str(runtime.get("status") or "UNKNOWN").upper()
    items.append({"key": "Market-data authorization", "level": "ok" if status == "HEALTHY" else ("bad" if status == "AUTHORIZATION_FAILED" else "unknown"), "value": status.title(), "detail": "run validate_market_data_authorization.py if blocked" if status == "AUTHORIZATION_FAILED" else ""})

    # token expiry (expiry only - the token itself is never read into the result)
    cache = _read_json(base / "data" / "cache" / "dhan_access_token.json") or {}
    expiry = _parse_dt(cache.get("expiryTime"))
    if expiry:
        hours = (expiry - now).total_seconds() / 3600
        items.append({"key": "Dhan token", "level": "bad" if hours <= 0 else ("warn" if hours < 6 else "ok"),
                      "value": "expired" if hours <= 0 else f"{hours:.1f} h left", "detail": f"expires {expiry.strftime('%d %b %H:%M')}"})
    else:
        items.append({"key": "Dhan token", "level": "unknown", "value": "no cached expiry", "detail": ""})

    # supervisor
    sup = _read_json(base / "data" / "aplus_master_health.json") or {}
    sup_at = _parse_dt(sup.get("updated_at"))
    if sup_at:
        sup_age = int((now - sup_at).total_seconds())
        count = sup.get("scanner_count")
        items.append({"key": "Supervisor", "level": "ok" if sup_age < 120 else "bad", "value": f"alive ({sup_age}s ago)" if sup_age < 120 else f"silent {sup_age // 60} min",
                      "detail": f"scanner processes: {count}"})
    else:
        items.append({"key": "Supervisor", "level": "unknown", "value": "no health file", "detail": ""})

    # safety data freshness
    safety = base / "data" / "safety"
    mwpl_dates, mwpl_ban = [], 0
    try:
        with (safety / "mwpl_status.csv").open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                d = _parse_dt(row.get("as_of"))
                if d:
                    mwpl_dates.append(d.date())
                if str(row.get("status", "")).upper() == "FNO_BAN":
                    mwpl_ban += 1
    except OSError:
        pass
    if mwpl_dates:
        newest = max(mwpl_dates)
        age_days = (now.date() - newest).days
        items.append({"key": "MWPL / ban data", "level": "ok" if age_days <= 2 else "warn", "value": f"as of {newest.isoformat()}", "detail": f"{mwpl_ban} stocks in F&O ban"})
    else:
        items.append({"key": "MWPL / ban data", "level": "warn", "value": "empty", "detail": "run update_safety_data.py"})
    try:
        with (safety / "corporate_events.csv").open(newline="", encoding="utf-8-sig") as handle:
            ev = list(csv.DictReader(handle))
        ev_dates = [d.date() for d in (_parse_dt(r.get("as_of")) for r in ev) if d]
        ev_age = (now.date() - max(ev_dates)).days if ev_dates else None
        items.append({"key": "Corporate events", "level": "ok" if ev_age is not None and ev_age <= 7 else "warn",
                      "value": f"{len(ev)} events", "detail": f"as of {max(ev_dates).isoformat()}" if ev_dates else "empty"})
    except OSError:
        items.append({"key": "Corporate events", "level": "warn", "value": "missing", "detail": ""})

    # market regime (shadow data)
    regime = None
    ctx_file = base / "data" / "market_context" / f"{now.date().isoformat()}.csv"
    try:
        with ctx_file.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            last = rows[-1]
            regime = {k: last.get(k) for k in ("time", "regime", "nifty_ltp", "nifty_pct_prev", "nifty_pct_open", "banknifty_pct_prev", "vix", "vix_pct_prev")}
    except OSError:
        pass

    return {"items": items, "regime": regime,
            "overall": "bad" if any(i["level"] == "bad" for i in items) else ("warn" if any(i["level"] == "warn" for i in items) else "ok")}


# ----------------------------------------------------------------------------- funnel
def diagnose(report: dict[str, Any], market: dict[str, Any], age: int | None) -> str:
    """One plain-language sentence answering 'why are there (no) trades?'."""
    if market["state"] != "OPEN":
        return f"Market is {market['state'].replace('_', ' ').lower()} ({market['note']})."
    if age is None:
        return "No scanner report found yet - the scanner has not completed a cycle."
    if age > 300:
        return f"The scanner has not produced a cycle for {age // 60} min - check the supervisor and scanner log."
    breaker = report.get("paper_native_circuit_breaker") or {}
    if breaker.get("blocked"):
        return "Trading is blocked by the paper circuit breaker: " + "; ".join(map(str, breaker.get("reasons") or [])) + "."
    created = int(_num(report.get("new_paper_trades_this_cycle")))
    if created:
        return f"{created} new paper trade(s) created this cycle."
    if not market["entries_open"]:
        return f"New entries are closed after {market['last_new_entry']} (INTRADAY_LAST_NEW_ENTRY); open trades are still being managed."
    sel = report.get("aplus_selective_gate") or {}
    ready = int(_num(sel.get("entry_ready_before_selective"), _num(report.get("entry_ready_count"))))
    passed = int(_num(sel.get("passed_selective")))
    plans = int(_num(report.get("option_trade_plans")))
    blocked = int(_num(report.get("safety_blocked_count")))
    if ready == 0:
        return f"No stock is entry-ready this cycle ({int(_num(report.get('candles_analysed')))} analysed)."
    if passed == 0:
        top = sorted((sel.get("rejection_counts") or {}).items(), key=lambda kv: -_num(kv[1]))[:2]
        why = ", ".join(f"{k.replace('A_PLUS_WAIT_', '').replace('_', ' ').lower()} ({int(_num(v))})" for k, v in top)
        return f"All {ready} entry-ready setups were rejected by the A+ filter" + (f", mostly: {why}." if why else ".")
    if plans == 0 and blocked:
        return f"{passed} setups passed the filters but {blocked} were blocked by safety checks (see reasons below)."
    if plans == 0:
        return f"{passed} setups passed the filters but produced no trade plan (no suitable option within the spread/liquidity limits, or already journaled)."
    return f"{plans} trade plan(s) generated."


def funnel(base: Path, now: datetime, market: dict[str, Any]) -> dict[str, Any]:
    report = _read_json(base / "data" / "reports" / "intraday_movement_latest.json") or {}
    generated = _parse_dt(report.get("generated_at"))
    age = max(0, int((now - generated).total_seconds())) if generated else None
    sel = report.get("aplus_selective_gate") or {}
    v2 = report.get("stock_selection_v2") or {}
    steps = [
        ("Universe", report.get("universe")),
        ("Quotes received", report.get("raw_quotes_received")),
        ("Radar qualified", report.get("radar_qualified_quotes")),
        ("Candles analysed", report.get("candles_analysed")),
        ("Entry-ready", sel.get("entry_ready_before_selective", report.get("entry_ready_count"))),
        ("Passed A+ filter", sel.get("passed_selective")),
        ("Passed stock-selection V2", v2.get("passed_v2")),
        ("Trade plans", report.get("option_trade_plans")),
        ("New paper trades", report.get("new_paper_trades_this_cycle")),
    ]
    reasons = sorted((sel.get("rejection_counts") or {}).items(), key=lambda kv: -_num(kv[1]))[:8]
    safety_reasons: dict[str, int] = {}
    for ev in report.get("safety_gate_evaluations") or []:
        for r in ev.get("block_reasons") or []:
            key = str(r)[:90]
            safety_reasons[key] = safety_reasons.get(key, 0) + 1
    leaders = [
        {"symbol": x.get("symbol"), "direction": x.get("direction"), "stage": x.get("stage"), "score": round(_num(x.get("score")), 1)}
        for x in (report.get("movement_leaders") or [])[:8]
    ]
    return {
        "cycle_at": report.get("generated_at"), "age_seconds": age, "diagnosis": diagnose(report, market, age),
        "steps": [{"label": k, "value": (None if v is None else int(_num(v)))} for k, v in steps],
        "rejection_reasons": [{"reason": k, "count": int(_num(v))} for k, v in reasons],
        "safety_block_reasons": [{"reason": k, "count": v} for k, v in sorted(safety_reasons.items(), key=lambda kv: -kv[1])[:6]],
        "leaders": leaders, "paper_today": report.get("paper_trades_today"),
    }


# ----------------------------------------------------------------------------- positions
def positions(base: Path, now: datetime) -> dict[str, Any]:
    journal = _read_json(base / "data" / "intraday_movement" / "paper_trade_journal.json") or {}
    rows, total = [], 0.0
    for t in journal.get("trades") or []:
        if str(t.get("status") or "").upper() != "OPEN":
            continue
        entry, last = _num(t.get("entry_price")), _num(t.get("last_option_price"))
        qty, stop = int(_num(t.get("quantity"))), _num(t.get("option_stop"))
        pnl = (last - entry) * qty if entry and last else 0.0
        total += pnl
        opened = _parse_dt(t.get("entry_time"))
        marked = _parse_dt(t.get("last_successful_mark_at") or t.get("last_quote_time"))
        rows.append({
            "symbol": t.get("symbol"), "side": f"{t.get('direction', '')} {t.get('option_type', '')}".strip(),
            "entry": round(entry, 2), "last": round(last, 2), "pnl": round(pnl, 0),
            "stop": round(stop, 2), "stop_distance_pct": round((last - stop) / last * 100, 1) if last and stop else None,
            "held_min": int((now - opened).total_seconds() // 60) if opened else None,
            "mark_age_s": int((now - marked).total_seconds()) if marked else None,
            "status": t.get("position_lifecycle_status") or "OPEN",
        })
    rows.sort(key=lambda r: r["pnl"])
    journal_date = str(journal.get("trading_date") or "")
    stale = bool(rows) and journal_date != now.date().isoformat()
    return {
        "count": len(rows), "unrealized": round(total, 0), "rows": rows, "trading_date": journal_date,
        "stale_session": stale,
        "note": (f"These {len(rows)} trade(s) are from the {journal_date} session; the scanner closes them at their last price "
                 "on its first cycle today." if stale else ""),
    }


# ----------------------------------------------------------------------------- performance
_perf_cache: dict[str, Any] = {"sig": None, "value": None, "at": 0.0}


def _perf_signature(base: Path) -> tuple:
    hist = base / "data" / "reports" / "paper_trade_history.csv"
    caps = base / "data" / "trade_evidence_capsules"
    try:
        h = hist.stat().st_mtime
    except OSError:
        h = 0
    try:
        newest = max((p.stat().st_mtime for p in caps.glob("*/*.json")), default=0)
    except OSError:
        newest = 0
    return (h, newest)


def performance(base: Path, since: str = "2026-08-28") -> dict[str, Any]:
    sig = _perf_signature(base)
    if _perf_cache["sig"] == sig and time.time() - _perf_cache["at"] < 600:
        return _perf_cache["value"]
    import evaluate_rules as er

    trades = er.prepare(er.load_trades(base), since)
    value = summarize_performance(trades)
    _perf_cache.update(sig=sig, value=value, at=time.time())
    return value


def summarize_performance(trades: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [t["_net"] for t in trades]
    n = len(nets)
    if not n:
        return {"n": 0}
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    cum, curve, peak, max_dd = 0.0, [], 0.0, 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        curve.append(round(cum))
    if len(curve) > 300:
        step = len(curve) / 300
        curve = [curve[int(i * step)] for i in range(300)] + [curve[-1]]

    def group(key: Callable[[dict], str]) -> list[dict[str, Any]]:
        buckets: dict[str, list[float]] = {}
        for t in trades:
            buckets.setdefault(key(t), []).append(t["_net"])
        out = []
        for name, vals in sorted(buckets.items()):
            w, l = sum(v for v in vals if v > 0), -sum(v for v in vals if v < 0)
            out.append({"name": name, "n": len(vals), "win_pct": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1),
                        "net": round(sum(vals)), "pf": round(w / l, 2) if l > 0 else None})
        return out

    return {
        "n": n, "win_pct": round(100 * len(wins) / n, 1), "net": round(sum(nets)), "gross": round(sum(t["_gross"] for t in trades)),
        "costs": round(sum(t["_costs"] for t in trades)),
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "expectancy": round(sum(nets) / n), "avg_win": round(sum(wins) / len(wins)) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses)) if losses else 0, "max_drawdown": round(max_dd),
        "curve": curve,
        "by_exit": group(lambda t: str(t.get("exit_reason") or "-")),
        "by_hour": group(lambda t: f"{t['_entry_clock'].hour:02d}:00"),
        "by_direction": group(lambda t: str(t.get("direction") or "-")),
    }


# ----------------------------------------------------------------------------- payload
def control_room_payload(base: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    market = _safe(lambda: market_status(now, base))
    if "error" in market:
        market = {"state": "UNKNOWN", "note": market["error"], "entries_open": False, "last_new_entry": "13:00", "trading_day": True}
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "market": market,
        "health": _safe(lambda: health(base, now, market)),
        "funnel": _safe(lambda: funnel(base, now, market)),
        "positions": _safe(lambda: positions(base, now)),
        "performance": _safe(lambda: performance(base)),
    }
