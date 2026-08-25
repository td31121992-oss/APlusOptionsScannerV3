from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
OUT = DATA / "after_market"
WIN_ROOT = DATA / "research" / "winning_setups"

REPORT_FILES = [
    "paper_trades.csv",
    "paper_trades_latest.json",
    "intraday_movement_latest.json",
    "intraday_entry_ready.csv",
    "intraday_fresh_movement.csv",
    "intraday_wait_for_pullback.csv",
    "intraday_near_misses.csv",
]

EXTRA_FILES = [
    DATA / "intraday_movement" / "paper_trade_journal.json",
    DATA / "intraday_movement" / "quote_tape.json",
    ROOT / "logs" / "scanner.log",
]

WINNER_FIELDS = [
    "trading_date","paper_trade_id","symbol","direction","option_type","strike","expiry",
    "entry_time","exit_time","stage","setup_family","selection_tier","pivot_state",
    "trade_quality_score","movement_capture_score","trend_alignment_score",
    "clean_trend_score","chase_risk_score","entry_price","exit_price",
    "capital_deployed","planned_risk_percent","net_pnl","return_percent",
    "mfe_amount","mae_amount","holding_seconds","exit_reason","entry_reason_full",
]

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def trading_date():
    p = REPORTS / "paper_trades_latest.json"
    if p.is_file():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            d = str(obj.get("trading_date") or "").strip()
            if d:
                return d[:10]
            trades = obj.get("paper_trades") or obj.get("trades") or []
            if trades:
                et = str(trades[0].get("entry_time") or "")
                if len(et) >= 10:
                    return et[:10]
        except Exception:
            pass
    return datetime.now().date().isoformat()

def load_today_trades():
    p = REPORTS / "paper_trades_latest.json"
    if not p.is_file():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    trades = obj.get("paper_trades")
    if not isinstance(trades, list):
        trades = obj.get("trades")
    return [x for x in (trades or []) if isinstance(x, dict)]

def winner_record(t, day):
    return {
        "trading_date": day,
        "paper_trade_id": str(t.get("paper_trade_id") or t.get("trade_id") or ""),
        "symbol": str(t.get("symbol") or ""),
        "direction": str(t.get("direction") or ""),
        "option_type": str(t.get("option_type") or t.get("side") or ""),
        "strike": _num(t.get("strike")),
        "expiry": str(t.get("expiry") or ""),
        "entry_time": str(t.get("entry_time") or ""),
        "exit_time": str(t.get("exit_time") or ""),
        "stage": str(t.get("stage") or ""),
        "setup_family": str(t.get("setup_family") or ""),
        "selection_tier": str(t.get("selection_tier") or ""),
        "pivot_state": str(t.get("pivot_state") or ""),
        "trade_quality_score": _num(t.get("momentum_score") or t.get("trade_quality_score")),
        "movement_capture_score": _num(t.get("movement_capture_score")),
        "trend_alignment_score": _num(t.get("trend_alignment_score")),
        "clean_trend_score": _num(t.get("clean_trend_score")),
        "chase_risk_score": _num(t.get("chase_risk_score")),
        "entry_price": _num(t.get("entry_price")),
        "exit_price": _num(t.get("exit_price")),
        "capital_deployed": _num(t.get("capital_deployed")),
        "planned_risk_percent": _num(t.get("planned_risk_percent")),
        "net_pnl": _num(t.get("net_pnl")),
        "return_percent": _num(t.get("return_percent")),
        "mfe_amount": _num(t.get("mfe_amount")),
        "mae_amount": _num(t.get("mae_amount")),
        "holding_seconds": int(_num(t.get("holding_seconds"), 0)),
        "exit_reason": str(t.get("exit_reason") or ""),
        "entry_reason_full": str(t.get("entry_reason") or ""),
    }

def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WINNER_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

def write_daily_winner_memory(day):
    WIN_ROOT.mkdir(parents=True, exist_ok=True)
    trades = load_today_trades()
    winners = [
        winner_record(t, day)
        for t in trades
        if str(t.get("status") or "").upper() == "CLOSED"
        and (_num(t.get("net_pnl")) > 0 or str(t.get("result") or "").upper() == "WIN")
    ]

    # De-dupe in case the source report contains duplicates.
    dedup = {}
    for w in winners:
        key = w["paper_trade_id"] or f'{w["symbol"]}|{w["entry_time"]}'
        dedup[key] = w
    winners = sorted(dedup.values(), key=lambda x: x["entry_time"])

    daily_json = WIN_ROOT / f"APlus_Winning_Setups_{day}.json"
    daily_csv = WIN_ROOT / f"APlus_Winning_Setups_{day}.csv"
    daily_md = WIN_ROOT / f"APlus_Winning_Setups_{day}.md"

    daily_json.write_text(json.dumps({
        "schema_version": 2,
        "purpose": "Automatic evidence library of profitable APlus PAPER trades.",
        "trading_date": day,
        "winner_count": len(winners),
        "winner_only_pnl": round(sum(_num(x["net_pnl"]) for x in winners), 2),
        "winners": winners,
    }, indent=2), encoding="utf-8")

    write_csv(daily_csv, winners)

    lines = [
        f"# APlus Winning Setup Library — {day}",
        "",
        f"Profitable PAPER trades stored: **{len(winners)}**",
        f"Winner-only P&L: **₹{sum(_num(x['net_pnl']) for x in winners):,.2f}**",
        "",
    ]
    for w in winners:
        mins = w["holding_seconds"] / 60.0
        lines += [
            f"## {w['symbol']} — {w['direction']}",
            f"- Entry ₹{w['entry_price']:.2f} → Exit ₹{w['exit_price']:.2f}; "
            f"P&L ₹{w['net_pnl']:,.2f}; Return {w['return_percent']:+.2f}%; Holding {mins:.0f}m.",
            f"- Activation: `{w['stage']}` / `{w['setup_family']}` / `{w['selection_tier']}`; "
            f"pivot `{w['pivot_state']}`.",
            f"- Quality {w['trade_quality_score']:.2f}; movement {w['movement_capture_score']:.2f}; "
            f"alignment {w['trend_alignment_score']:.2f}; clean trend {w['clean_trend_score']:.2f}; "
            f"chase {w['chase_risk_score']:.2f}.",
            f"- Exit: `{w['exit_reason']}`.",
            f"- Full entry evidence: {w['entry_reason_full']}",
            "",
        ]
    daily_md.write_text("\n".join(lines), encoding="utf-8")
    return winners, [daily_json, daily_csv, daily_md]

def rebuild_monthly_master(day):
    month = day[:7]
    all_rows = {}
    for p in sorted(WIN_ROOT.glob(f"APlus_Winning_Setups_{month}-??.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            rows = obj.get("winners") or []
            for w in rows:
                if not isinstance(w, dict):
                    continue
                key = str(w.get("paper_trade_id") or "") or f'{w.get("symbol")}|{w.get("entry_time")}'
                all_rows[key] = w
        except Exception:
            continue

    rows = sorted(all_rows.values(), key=lambda x: str(x.get("entry_time") or ""))
    monthly_json = WIN_ROOT / f"APlus_Winning_Setups_{month}_MONTHLY.json"
    monthly_csv = WIN_ROOT / f"APlus_Winning_Setups_{month}_MONTHLY.csv"
    monthly_md = WIN_ROOT / f"APlus_Winning_Setups_{month}_MONTHLY.md"

    days = sorted({str(x.get("trading_date") or "") for x in rows if x.get("trading_date")})
    total_pnl = round(sum(_num(x.get("net_pnl")) for x in rows), 2)

    monthly_json.write_text(json.dumps({
        "schema_version": 2,
        "month": month,
        "days_included": days,
        "winning_trades": len(rows),
        "winner_only_pnl": total_pnl,
        "trades": rows,
    }, indent=2), encoding="utf-8")

    write_csv(monthly_csv, rows)

    lines = [
        f"# APlus Monthly Winning Trade Report — {month}",
        "",
        f"Days included: **{', '.join(days) if days else '-'}**",
        f"Winning trades stored: **{len(rows)}**",
        f"Winner-only P&L: **₹{total_pnl:,.2f}**",
        "",
    ]
    for x in rows:
        lines.append(
            f"- {x.get('trading_date')} | {x.get('symbol')} | {x.get('direction')} | "
            f"{_num(x.get('return_percent')):+.2f}% | ₹{_num(x.get('net_pnl')):,.2f} | "
            f"{x.get('setup_family') or '-'}"
        )
    monthly_md.write_text("\n".join(lines), encoding="utf-8")
    return [monthly_json, monthly_csv, monthly_md]

def file_summary(path):
    return {
        "name": path.name,
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }

def main():
    day = trading_date()
    day_dir = OUT / day
    day_dir.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []

    # Build winner memory FIRST so it is included in the daily ZIP.
    winners, daily_winner_files = write_daily_winner_memory(day)
    monthly_files = rebuild_monthly_master(day)

    for name in REPORT_FILES:
        src = REPORTS / name
        if src.is_file():
            dst = day_dir / name
            shutil.copy2(src, dst)
            copied.append(dst)
        else:
            missing.append(str(src))

    for src in EXTRA_FILES:
        if src.is_file():
            dst = day_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)

    for src in daily_winner_files + monthly_files:
        if src.is_file():
            dst = day_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)

    manifest = {
        "project": "APlusOptionsScannerV3",
        "trading_date": day,
        "created_at": datetime.now().astimezone().isoformat(),
        "paper_only": True,
        "live_orders_enabled": False,
        "winner_memory": {
            "daily_winners": len(winners),
            "daily_winner_pnl": round(sum(_num(x["net_pnl"]) for x in winners), 2),
            "research_folder": str(WIN_ROOT),
            "monthly_master": f"APlus_Winning_Setups_{day[:7]}_MONTHLY.json",
        },
        "files": [file_summary(p) for p in copied],
        "missing_files": missing,
    }
    mp = day_dir / "after_market_manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    copied.append(mp)

    zip_path = OUT / f"APlus_AfterMarket_{day}.zip"
    tmp = OUT / f".APlus_AfterMarket_{day}.tmp"
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in copied:
            if p.is_file():
                zf.write(p, p.name)
    tmp.replace(zip_path)

    latest = OUT / "APlus_AfterMarket_LATEST.zip"
    shutil.copy2(zip_path, latest)

    print("=" * 72)
    print("APLUS AFTER-MARKET PACKAGE + WINNER MEMORY READY")
    print("Trading date      :", day)
    print("Daily winners     :", len(winners))
    print("Daily winner P&L  : ₹{:,.2f}".format(sum(_num(x["net_pnl"]) for x in winners)))
    print("Winner library    :", WIN_ROOT)
    print("Monthly master    :", WIN_ROOT / f"APlus_Winning_Setups_{day[:7]}_MONTHLY.json")
    print("LATEST ZIP        :", latest)
    print("Files copied      :", len(copied))
    print("Missing           :", len(missing))
    print("=" * 72)

if __name__ == "__main__":
    main()
