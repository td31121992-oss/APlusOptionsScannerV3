"""After-market Telegram message: top 5 gainers and top 5 losers of the day among the F&O stocks.

    python daily_movers_telegram.py [--dry-run] [--force]

Reads the final prices with one read-only quote call, takes each stock's previous close from the scanner's market
watch report, ranks by % change from the previous close and sends one Telegram message formatted to screenshot for a
WhatsApp status. Sends once per trading day (state file), only after 15:35 and never on a holiday. Never places orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time as clock
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
STATE = ROOT / "data" / "dashboard_state" / "daily_movers_sent.json"
REPORT = ROOT / "data" / "reports" / "intraday_movement_latest.json"


def _f(value: Any) -> float:
    try:
        out = float(value)
        return out if out == out else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_movers(rows: list[dict[str, Any]], n: int = 5) -> tuple[list[dict], list[dict]]:
    """rows: {symbol, ltp, previous_close}. Returns (gainers, losers) with pct, best first; zero/missing prices are dropped."""
    ranked = []
    for r in rows:
        ltp, prev = _f(r.get("ltp")), _f(r.get("previous_close"))
        if ltp > 0 and prev > 0:
            ranked.append({"symbol": str(r["symbol"]), "ltp": ltp, "prev": prev, "pct": (ltp / prev - 1) * 100})
    ranked.sort(key=lambda x: x["pct"], reverse=True)
    gainers = [x for x in ranked[:n] if x["pct"] > 0]
    losers = [x for x in sorted(ranked, key=lambda x: x["pct"])[:n] if x["pct"] < 0]
    return gainers, losers


def format_message(day: date, gainers: list[dict], losers: list[dict], total: int) -> str:
    def line(i: int, x: dict) -> str:
        return f"{i}. {x['symbol']}  ₹{x['ltp']:,.2f}  ({x['pct']:+.2f}%)"

    out = [f"📊 F&O Top Movers - {day.strftime('%d %b %Y')}", ""]
    out.append("🟢 TOP 5 GAINERS")
    out += [line(i, x) for i, x in enumerate(gainers, 1)] or ["(none)"]
    out += ["", "🔴 TOP 5 LOSERS"]
    out += [line(i, x) for i, x in enumerate(losers, 1)] or ["(none)"]
    out += ["", f"{total} F&O stocks, change vs previous close"]
    return "\n".join(out)


def _already_sent(day: str) -> bool:
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("day") == day
    except (OSError, ValueError):
        return False


def _mark_sent(day: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"day": day, "sent_at": datetime.now(IST).isoformat()}), encoding="utf-8")


def fetch_rows(day: str) -> list[dict[str, Any]]:
    """Final prices from one quote call; previous close from today's market-watch report."""
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token
    from order_book_recorder import _universe

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if str(report.get("generated_at", ""))[:10] != day:
        raise RuntimeError("market-watch report is not from today")
    prev = {r["symbol"]: _f(r.get("previous_close")) for r in (report.get("fno_market_watch") or {}).get("rows", [])}
    universe = _universe()
    by_id = {v: k for k, v in universe.items()}
    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    resp = requests.post("https://api.dhan.co/v2/marketfeed/quote", timeout=25, json={"NSE_EQ": list(universe.values())},
                         headers={"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"})
    if resp.status_code != 200:
        raise RuntimeError(f"quote HTTP {resp.status_code}")
    data = (resp.json().get("data") or {}).get("NSE_EQ") or {}
    return [{"symbol": by_id.get(int(k), str(k)), "ltp": v.get("last_price"), "previous_close": prev.get(by_id.get(int(k), ""))}
            for k, v in data.items() if v]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the message, send nothing, record nothing")
    ap.add_argument("--force", action="store_true", help="ignore the time-of-day and already-sent checks")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # emoji in the message must not crash a Windows console
    except Exception:  # noqa: BLE001
        pass
    now = datetime.now(IST)
    day = now.date().isoformat()
    sys.path.insert(0, str(ROOT))
    from trading_calendar import is_trading_day

    if not args.force:
        if not is_trading_day(now.date())[0]:
            print("not a trading day")
            return 0
        if now.time() < clock(15, 35):
            print("market not closed yet")
            return 0
        if _already_sent(day):
            print("already sent today")
            return 0
    rows = fetch_rows(day)
    gainers, losers = compute_movers(rows)
    message = format_message(now.date(), gainers, losers, len(rows))
    if args.dry_run:
        print(message)
        return 0
    from announcement_feed import send_telegram

    ok, detail = send_telegram(message)
    print("sent" if ok else f"send failed: {detail}")
    if ok:
        _mark_sent(day)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
