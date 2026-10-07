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


TAGLINE = "APlus Software made by Mr. Darpan Bobhate (F&O Trader with 7 years of experience)"


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
    out += ["", f"{total} F&O stocks, change vs previous close", "", TAGLINE]
    return "\n".join(out)


def render_card(day: date, gainers: list[dict], losers: list[dict], path: Path) -> Path:
    """Portrait 1080x1920 picture (WhatsApp-status shaped) with the same top-5 lists and the tagline."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (11, 16, 32))
    draw = ImageDraw.Draw(img)
    for y in range(H):                                              # soft vertical gradient
        shade = int(11 + 22 * y / H)
        draw.line([(0, y), (W, y)], fill=(shade, shade + 5, shade + 22))

    def font(size: int, bold: bool = False):
        for name in ("arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf" if bold else "segoeui.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def centered(text: str, y: int, f, fill) -> None:
        w = draw.textlength(text, font=f)
        draw.text(((W - w) / 2, y), text, font=f, fill=fill)

    centered("APlus", 70, font(64, True), (231, 238, 252))
    centered("F&O TOP MOVERS", 150, font(78, True), (255, 255, 255))
    centered(day.strftime("%d %B %Y"), 255, font(46), (142, 160, 189))

    def section(title: str, rows: list[dict], top: int, colour: tuple[int, int, int]) -> int:
        draw.rounded_rectangle([60, top, W - 60, top + 64], radius=16, fill=colour)
        draw.text((90, top + 8), title, font=font(44, True), fill=(10, 14, 26))
        y = top + 84
        for i, x in enumerate(rows or [], 1):
            draw.rounded_rectangle([60, y, W - 60, y + 96], radius=16, fill=(18, 26, 45))
            draw.text((90, y + 22), str(i), font=font(44, True), fill=(142, 160, 189))
            draw.text((170, y + 6), x["symbol"], font=font(46, True), fill=(231, 238, 252))
            draw.text((170, y + 58), f"₹{x['ltp']:,.2f}", font=font(30), fill=(142, 160, 189))
            pct = f"{x['pct']:+.2f}%"
            w = draw.textlength(pct, font=font(52, True))
            draw.text((W - 90 - w, y + 20), pct, font=font(52, True), fill=colour)
            y += 110
        if not rows:
            draw.text((90, y + 20), "none", font=font(40), fill=(142, 160, 189))
            y += 110
        return y

    end = section("TOP 5 GAINERS", gainers, 340, (46, 204, 113))
    section("TOP 5 LOSERS", losers, end + 20, (255, 99, 99))
    draw.line([(120, H - 190), (W - 120, H - 190)], fill=(60, 72, 100), width=2)
    centered("APlus Software made by", H - 160, font(34), (142, 160, 189))
    centered("Mr. Darpan Bobhate", H - 112, font(48, True), (231, 238, 252))
    centered("(F&O Trader with 7 years of experience)", H - 52, font(32), (142, 160, 189))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def send_telegram_photo(path: Path, caption: str = "") -> tuple[bool, str]:
    """Send the picture with CAlphaTrader's stored Telegram credentials (never printed)."""
    from announcement_feed import CALPHA

    py = CALPHA / ".venv" / "Scripts" / "python.exe"
    tools_dir = CALPHA / "tools"
    if not py.exists() or not (tools_dir / "telegram_alerts.py").exists():
        return False, "CAlpha Telegram sender missing"
    code = (f"import sys, requests; sys.path.insert(0, r'{tools_dir}'); import telegram_alerts as t; c = t.load_credentials(); "
            "f = open(sys.argv[1], 'rb'); "
            "r = requests.post(f'{t.API_BASE}/bot{c.token}/sendPhoto', data={'chat_id': c.chat_id, 'caption': sys.argv[2]}, files={'photo': f}, timeout=60); "
            "sys.exit(0 if r.status_code == 200 else 1)")
    try:
        import subprocess

        p = subprocess.run([str(py), "-c", code, str(path), caption], cwd=str(CALPHA), capture_output=True, text=True, timeout=120)
        return p.returncode == 0, "photo sent" if p.returncode == 0 else "photo send failed"
    except Exception as exc:  # noqa: BLE001
        return False, f"photo send failed: {type(exc).__name__}"


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
    ap.add_argument("--no-image", action="store_true", help="send the text message only")
    ap.add_argument("--card", metavar="PNG", help="only render the picture card to this file (no sending), using the latest data")
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
    rows = fetch_rows(args_day if (args_day := os.getenv("APLUS_MOVERS_DAY")) else day)
    gainers, losers = compute_movers(rows)
    if args.card:
        print(render_card(now.date(), gainers, losers, Path(args.card)))
        return 0
    message = format_message(now.date(), gainers, losers, len(rows))
    if args.dry_run:
        print(message)
        return 0
    from announcement_feed import send_telegram

    ok, detail = send_telegram(message)
    print("sent" if ok else f"send failed: {detail}")
    if ok:
        _mark_sent(day)
        if not args.no_image:                              # the picture is a bonus: its failure never affects the text message
            try:
                card_path = render_card(now.date(), gainers, losers, ROOT / "data" / "daily_movers" / f"{day}.png")
                print(send_telegram_photo(card_path, "APlus F&O top movers")[1])
            except Exception as exc:  # noqa: BLE001
                print(f"picture skipped: {type(exc).__name__}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
