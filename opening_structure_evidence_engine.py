from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
RESEARCH = ROOT / "data" / "research" / "opening_structure"
LOGS = ROOT / "data" / "logs"
REPORTS.mkdir(parents=True, exist_ok=True)
RESEARCH.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

MARKET_WATCH = REPORTS / "fno_market_watch_latest.json"
INTRADAY = REPORTS / "intraday_movement_latest.json"
PAPER_LATEST = REPORTS / "paper_trades_latest.json"

LATEST_JSON = REPORTS / "opening_structure_evidence_latest.json"
LATEST_CSV = REPORTS / "opening_structure_evidence_latest.csv"

POLL_SECONDS = 5
OPEN_TOLERANCE_PCT = 0.05
MIN_CONFIRM_MOVE_PCT = 0.35


def num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def atomic_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sector_performance(rows: list[dict[str, Any]]) -> dict[str, float]:
    m: dict[str, list[float]] = {}
    for r in rows:
        sec = str(r.get("sector") or "Other/Industrial")
        m.setdefault(sec, []).append(num(r.get("from_open_pct")))
    return {sec: (sum(vals) / len(vals) if vals else 0.0) for sec, vals in m.items()}


def classify(row: dict[str, Any], sec_pct: float) -> dict[str, Any]:
    o = num(row.get("open_0915"))
    h = num(row.get("day_high"))
    l = num(row.get("day_low"))
    move = num(row.get("from_open_pct"))
    if o <= 0:
        return {}

    tolerance_rupees = max(0.05, o * OPEN_TOLERANCE_PCT / 100.0)
    dist_low = abs(o - l)
    dist_high = abs(h - o)
    is_open_low = dist_low <= tolerance_rupees
    is_open_high = dist_high <= tolerance_rupees

    setup = ""
    direction = ""
    option_side = ""
    confirmed = False

    if is_open_low:
        setup = "OPEN_LOW_CE"
        direction = "BULLISH"
        option_side = "CE"
        confirmed = move >= MIN_CONFIRM_MOVE_PCT and sec_pct >= 0
    elif is_open_high:
        setup = "OPEN_HIGH_PE"
        direction = "BEARISH"
        option_side = "PE"
        confirmed = move <= -MIN_CONFIRM_MOVE_PCT and sec_pct <= 0

    if not setup:
        return {}

    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "sector": str(row.get("sector") or "Other/Industrial"),
        "setup_id": setup,
        "direction": direction,
        "option_side": option_side,
        "confirmed": confirmed,
        "open_0915": o,
        "ltp": num(row.get("ltp")),
        "day_high": h,
        "day_low": l,
        "previous_close": num(row.get("previous_close")),
        "gap_pct": num(row.get("gap_pct")),
        "from_open_pct": move,
        "from_prev_close_pct": num(row.get("from_prev_close_pct")),
        "sector_from_open_pct": sec_pct,
        "range_position_pct": num(row.get("range_position_pct")),
        "open_to_low_distance_pct": (dist_low / o * 100.0),
        "open_to_high_distance_pct": (dist_high / o * 100.0),
        "tolerance_rupees": tolerance_rupees,
    }


def find_plan(symbol: str, direction: str) -> dict[str, Any] | None:
    intraday = load_json(INTRADAY)
    plans = intraday.get("trade_plans", []) if isinstance(intraday, dict) else []
    for p in plans:
        if not isinstance(p, dict):
            continue
        psym = str(
            p.get("symbol")
            or p.get("underlying_symbol")
            or (p.get("candidate") or {}).get("symbol")
            or ""
        ).upper()
        pdir = str(
            p.get("direction")
            or (p.get("candidate") or {}).get("direction")
            or ""
        ).upper()
        if psym == symbol and (not pdir or pdir == direction):
            return p
    return None


def option_from_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {}
    option = plan.get("option") if isinstance(plan.get("option"), dict) else plan
    return {
        "option_type": str(option.get("option_type") or option.get("side") or ""),
        "option_security_id": str(option.get("security_id") or option.get("option_security_id") or ""),
        "trading_symbol": str(option.get("trading_symbol") or ""),
        "expiry": str(option.get("expiry") or ""),
        "strike": num(option.get("strike")),
        "option_ltp": num(option.get("ltp") or option.get("option_ltp")),
        "bid": num(option.get("bid")),
        "ask": num(option.get("ask")),
        "limit_price": num(option.get("limit_price")),
        "quantity": int(num(option.get("quantity"))),
        "lot_size": int(num(option.get("lot_size"))),
        "selection_score": num(option.get("selection_score")),
        "spread_percent": num(option.get("spread_percent")),
    }


def paper_trade_for(symbol: str, option_side: str) -> dict[str, Any] | None:
    data = load_json(PAPER_LATEST)
    trades: list[Any] = []
    if isinstance(data, dict):
        for key in ("trades", "rows", "paper_trades"):
            if isinstance(data.get(key), list):
                trades = data[key]
                break
        if not trades and data.get("symbol"):
            trades = [data]
    elif isinstance(data, list):
        trades = data

    today = datetime.now(IST).date().isoformat()
    matches = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        if str(t.get("symbol") or "").upper() != symbol:
            continue
        if str(t.get("option_type") or t.get("side") or "").upper() != option_side:
            continue
        if today not in str(t.get("entry_time") or ""):
            continue
        matches.append(t)
    if not matches:
        return None
    matches.sort(key=lambda x: str(x.get("entry_time") or ""), reverse=True)
    return matches[0]


def new_record(signal: dict[str, Any], now: datetime) -> dict[str, Any]:
    plan = find_plan(signal["symbol"], signal["direction"])
    opt = option_from_plan(plan)
    trade = paper_trade_for(signal["symbol"], signal["option_side"])
    option_status = "EXACT_EXISTING_SCANNER_PLAN" if opt.get("option_security_id") or opt.get("trading_symbol") else "NO_EXISTING_OPTION_PLAN"

    entry_option_price = num(
        (trade or {}).get("entry_price")
        or opt.get("limit_price")
        or opt.get("ask")
        or opt.get("option_ltp")
    )
    quantity = int(num((trade or {}).get("quantity") or opt.get("quantity")))

    rec = {
        "evidence_id": f"OS-{now:%Y%m%d-%H%M%S}-{signal['symbol']}-{signal['setup_id']}",
        "trading_date": now.date().isoformat(),
        "setup_id": signal["setup_id"],
        "symbol": signal["symbol"],
        "sector": signal["sector"],
        "direction": signal["direction"],
        "option_side": signal["option_side"],
        "signal_time": now.isoformat(),
        "signal_underlying_ltp": signal["ltp"],
        "signal_open_0915": signal["open_0915"],
        "signal_day_high": signal["day_high"],
        "signal_day_low": signal["day_low"],
        "signal_from_open_pct": signal["from_open_pct"],
        "signal_sector_from_open_pct": signal["sector_from_open_pct"],
        "signal_gap_pct": signal["gap_pct"],
        "open_to_low_distance_pct": signal["open_to_low_distance_pct"],
        "open_to_high_distance_pct": signal["open_to_high_distance_pct"],
        "option_evidence_status": option_status,
        **opt,
        "option_entry_price": entry_option_price,
        "quantity": quantity,
        "option_highest_price": entry_option_price,
        "option_lowest_price": entry_option_price,
        "option_last_price": entry_option_price,
        "option_mfe_amount": 0.0,
        "option_mae_amount": 0.0,
        "option_session_high_theoretical_pnl": 0.0,
        "underlying_best_favorable_pct": 0.0,
        "underlying_worst_adverse_pct": 0.0,
        "underlying_last_pct_from_signal": 0.0,
        "paper_trade_id": str((trade or {}).get("paper_trade_id") or ""),
        "actual_exit_time": str((trade or {}).get("exit_time") or ""),
        "actual_exit_price": num((trade or {}).get("exit_price")),
        "actual_net_pnl": num((trade or {}).get("net_pnl") or (trade or {}).get("pnl")),
        "actual_return_percent": num((trade or {}).get("return_percent") or (trade or {}).get("return_pct")),
        "status": "TRACKING",
        "last_updated": now.isoformat(),
        "tape": [],
    }
    return rec


def update_record(rec: dict[str, Any], row: dict[str, Any], now: datetime) -> None:
    underlying_now = num(row.get("ltp"))
    entry_underlying = num(rec.get("signal_underlying_ltp"))
    direction = rec.get("direction")
    raw_pct = ((underlying_now - entry_underlying) / entry_underlying * 100.0) if entry_underlying > 0 else 0.0
    favorable_pct = raw_pct if direction == "BULLISH" else -raw_pct
    rec["underlying_last_pct_from_signal"] = round(favorable_pct, 4)
    rec["underlying_best_favorable_pct"] = round(max(num(rec.get("underlying_best_favorable_pct")), favorable_pct), 4)
    rec["underlying_worst_adverse_pct"] = round(min(num(rec.get("underlying_worst_adverse_pct")), favorable_pct), 4)

    trade = paper_trade_for(str(rec.get("symbol")), str(rec.get("option_side")))
    option_price = 0.0
    if trade:
        rec["paper_trade_id"] = str(trade.get("paper_trade_id") or rec.get("paper_trade_id") or "")
        option_price = num(trade.get("last_option_price") or trade.get("exit_price") or trade.get("entry_price"))
        rec["actual_exit_time"] = str(trade.get("exit_time") or "")
        rec["actual_exit_price"] = num(trade.get("exit_price"))
        rec["actual_net_pnl"] = num(trade.get("net_pnl") or trade.get("pnl"))
        rec["actual_return_percent"] = num(trade.get("return_percent") or trade.get("return_pct"))

    if option_price > 0:
        entry = num(rec.get("option_entry_price"))
        qty = int(num(rec.get("quantity")))
        if entry <= 0:
            rec["option_entry_price"] = option_price
            entry = option_price
        rec["option_last_price"] = option_price
        rec["option_highest_price"] = max(num(rec.get("option_highest_price")), option_price)
        low = num(rec.get("option_lowest_price"))
        rec["option_lowest_price"] = option_price if low <= 0 else min(low, option_price)
        if qty > 0:
            rec["option_mfe_amount"] = round((rec["option_highest_price"] - entry) * qty, 2)
            rec["option_mae_amount"] = round((rec["option_lowest_price"] - entry) * qty, 2)
            rec["option_session_high_theoretical_pnl"] = rec["option_mfe_amount"]

    rec["last_updated"] = now.isoformat()
    rec["tape"].append({
        "timestamp": now.isoformat(),
        "underlying_ltp": underlying_now,
        "favorable_underlying_pct_from_signal": round(favorable_pct, 4),
        "from_0915_open_pct": num(row.get("from_open_pct")),
        "option_price": option_price,
    })
    # Keep full session evidence without letting the latest JSON become enormous.
    if len(rec["tape"]) > 6000:
        rec["tape"] = rec["tape"][-6000:]


def save(records: list[dict[str, Any]], now: datetime) -> None:
    payload = {
        "generated_at": now.isoformat(),
        "mode": "PAPER_RESEARCH_ONLY",
        "strategy_authority": "NO_EXECUTION",
        "setup_families": ["OPEN_LOW_CE", "OPEN_HIGH_PE"],
        "records": records,
        "summary": {
            "total_signals": len(records),
            "open_low_ce": sum(r.get("setup_id") == "OPEN_LOW_CE" for r in records),
            "open_high_pe": sum(r.get("setup_id") == "OPEN_HIGH_PE" for r in records),
            "with_exact_option_evidence": sum(r.get("option_evidence_status") == "EXACT_EXISTING_SCANNER_PLAN" for r in records),
            "without_option_plan": sum(r.get("option_evidence_status") == "NO_EXISTING_OPTION_PLAN" for r in records),
        },
    }
    atomic_json(LATEST_JSON, payload)

    day_dir = RESEARCH / now.date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(day_dir / "opening_structure_evidence.json", payload)

    fields = [
        "evidence_id","trading_date","setup_id","symbol","sector","direction","option_side",
        "signal_time","signal_underlying_ltp","signal_from_open_pct","signal_sector_from_open_pct",
        "signal_gap_pct","open_to_low_distance_pct","open_to_high_distance_pct",
        "option_evidence_status","trading_symbol","expiry","strike","option_entry_price","quantity",
        "option_highest_price","option_lowest_price","option_last_price","option_mfe_amount",
        "option_mae_amount","option_session_high_theoretical_pnl",
        "underlying_best_favorable_pct","underlying_worst_adverse_pct","underlying_last_pct_from_signal",
        "paper_trade_id","actual_exit_time","actual_exit_price","actual_net_pnl","actual_return_percent","status",
    ]
    with LATEST_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)


def run() -> None:
    print("=" * 82)
    print("APlus Opening Structure Evidence Engine - Step 2")
    print("PAPER / RESEARCH ONLY - NO EXECUTION")
    print("Uses existing APlus report files; ZERO additional Dhan API calls.")
    print("=" * 82)

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    current_date = datetime.now(IST).date()

    # Resume today's evidence if the engine is restarted.
    previous = load_json(LATEST_JSON)
    if isinstance(previous, dict) and str(previous.get("generated_at") or "").startswith(current_date.isoformat()):
        records = [r for r in previous.get("records", []) if isinstance(r, dict)]
        seen = {(str(r.get("symbol")), str(r.get("setup_id"))) for r in records}
        print("Resumed", len(records), "existing evidence records.")

    while True:
        now = datetime.now(IST)
        if now.date() != current_date:
            return
        if now.time() < dtime(9, 15):
            time.sleep(min(30, POLL_SECONDS))
            continue
        if now.time() > dtime(15, 35):
            for r in records:
                r["status"] = "SESSION_COMPLETE"
            save(records, now)
            print("Session evidence complete:", len(records), "signals")
            return

        mw = load_json(MARKET_WATCH)
        rows = [r for r in (mw.get("rows", []) if isinstance(mw, dict) else []) if isinstance(r, dict)]
        if not rows:
            time.sleep(POLL_SECONDS)
            continue

        sec = sector_performance(rows)
        by_symbol = {str(r.get("symbol") or "").upper(): r for r in rows}

        for row in rows:
            sector = str(row.get("sector") or "Other/Industrial")
            sig = classify(row, sec.get(sector, 0.0))
            if not sig or not sig["confirmed"]:
                continue
            key = (sig["symbol"], sig["setup_id"])
            if key in seen:
                continue
            rec = new_record(sig, now)
            records.append(rec)
            seen.add(key)
            print(
                now.strftime("%H:%M:%S"),
                "NEW", rec["setup_id"], rec["symbol"],
                "stock", f"{rec['signal_from_open_pct']:+.2f}%",
                "sector", f"{rec['signal_sector_from_open_pct']:+.2f}%",
                "option", rec["option_evidence_status"],
            )

        for rec in records:
            row = by_symbol.get(str(rec.get("symbol") or "").upper())
            if row:
                update_record(rec, row, now)

        save(records, now)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
