"""After-market Telegram message: top 5 gainers and top 5 losers of the day among the F&O stocks, plus the top 5 CALL and top 5 PUT
option-premium gainers (stock, strike and % change of the premium versus the previous close; picture cards for both).

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


OPTION_MIN_PREV = 3.0                 # previous close at least Rs 3, so a 0.05 -> 0.30 print does not top the list
OPTION_MIN_LOTS = 20                  # at least 20 lots traded
OPTION_STRIKES = 6                    # strikes each side of the money, nearest expiry


def rank_option_movers(rows: list[dict[str, Any]], n: int = 5) -> tuple[list[dict], list[dict]]:
    """rows: {symbol, strike, type CE|PE, ltp, prev, volume, lot, stock_pct}. Best strike per stock, top n per side by % premium change."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        ltp, prev, vol, lot = _f(r.get("ltp")), _f(r.get("prev")), _f(r.get("volume")), _f(r.get("lot")) or 1.0
        if ltp <= 0 or prev < OPTION_MIN_PREV or vol < OPTION_MIN_LOTS * lot:
            continue
        pct = (ltp / prev - 1.0) * 100.0
        key = (str(r["symbol"]), str(r["type"]))
        if key not in best or pct > best[key]["pct"]:
            best[key] = {**r, "ltp": ltp, "prev": prev, "pct": pct}
    calls = sorted((v for (s, t), v in best.items() if t == "CE"), key=lambda x: -x["pct"])[:n]
    puts = sorted((v for (s, t), v in best.items() if t == "PE"), key=lambda x: -x["pct"])[:n]
    return [x for x in calls if x["pct"] > 0], [x for x in puts if x["pct"] > 0]


def fetch_option_rows(day: str, stock_pct_override: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Quote every CE/PE within OPTION_STRIKES of the money (nearest expiry) for all F&O stocks. Read-only; about 6 quote calls."""
    import pandas as pd
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token
    from order_book_recorder import _universe

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}

    def quote(segment: str, ids: list[int]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i in range(0, len(ids), 900):
            r = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=headers, timeout=30, json={segment: ids[i:i + 900]})
            if r.status_code == 200:
                out.update((r.json().get("data") or {}).get(segment) or {})
        return out

    universe = _universe()
    by_id = {v: k for k, v in universe.items()}
    eq = quote("NSE_EQ", list(universe.values()))
    stock_ltp = {by_id.get(int(k)): _f(v.get("last_price")) for k, v in eq.items()}
    stock_pct = dict(stock_pct_override or {})                # from the previous close in the market-watch report (the quote's own
    for k, v in eq.items():                                   # close is today's close once the session has ended)
        sym = by_id.get(int(k))
        if sym not in stock_pct:
            prev = _f((v.get("ohlc") or {}).get("close"))
            stock_pct[sym] = (_f(v.get("last_price")) / prev - 1.0) * 100.0 if prev > 0 else 0.0
    m = pd.read_csv(ROOT / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                    usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "LOT_SIZE"])
    m = m[m.INSTRUMENT == "OPTSTK"].copy()
    m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
    m = m[m.exp >= day]
    meta: dict[int, dict[str, Any]] = {}
    for sym, g in m.groupby("UNDERLYING_SYMBOL"):
        px = stock_ltp.get(sym) or 0.0
        if px <= 0:
            continue
        g = g[g.exp == g.exp.min()]
        strikes = sorted({float(x) for x in g.STRIKE_PRICE})
        if not strikes:
            continue
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - px))
        keep = set(strikes[max(0, atm - OPTION_STRIKES):atm + OPTION_STRIKES + 1])
        for r in g.itertuples():
            if float(r.STRIKE_PRICE) in keep:
                meta[int(r.SECURITY_ID)] = {"symbol": sym, "strike": float(r.STRIKE_PRICE), "type": str(r.OPTION_TYPE), "lot": float(r.LOT_SIZE),
                                            "stock_pct": stock_pct.get(sym, 0.0), "expiry": r.exp}
    data = quote("NSE_FNO", list(meta))
    rows = []
    for k, v in data.items():
        info = meta.get(int(k))
        if not info or not v:
            continue
        rows.append({**info, "ltp": _f(v.get("last_price")), "prev": _f((v.get("ohlc") or {}).get("close")), "volume": _f(v.get("volume")),
                     "oi": _f(v.get("oi"))})
    return rows


def format_option_section(calls: list[dict], puts: list[dict]) -> list[str]:
    def line(i: int, x: dict) -> str:
        return (f"{i}. {x['symbol']} {x['strike']:g} {x['type']}  \u20b9{x['prev']:,.2f} \u2192 \u20b9{x['ltp']:,.2f}  "
                f"({x['pct']:+.0f}%)  stock {x['stock_pct']:+.1f}%")

    out = ["", "\U0001F7E2 TOP 5 CALL PREMIUM GAINERS"]
    out += [line(i, x) for i, x in enumerate(calls, 1)] or ["(none)"]
    out += ["", "\U0001F534 TOP 5 PUT PREMIUM GAINERS"]
    out += [line(i, x) for i, x in enumerate(puts, 1)] or ["(none)"]
    out += ["", f"Nearest expiry, +/-{OPTION_STRIKES} strikes, previous close >= \u20b9{OPTION_MIN_PREV:g}, >= {OPTION_MIN_LOTS} lots traded"]
    return out


def format_message(day: date, gainers: list[dict], losers: list[dict], total: int, calls: list[dict] | None = None,
                   puts: list[dict] | None = None) -> str:
    def line(i: int, x: dict) -> str:
        return f"{i}. {x['symbol']}  ₹{x['ltp']:,.2f}  ({x['pct']:+.2f}%)"

    out = [f"📊 F&O Top Movers - {day.strftime('%d %b %Y')}", ""]
    out.append("🟢 TOP 5 GAINERS")
    out += [line(i, x) for i, x in enumerate(gainers, 1)] or ["(none)"]
    out += ["", "🔴 TOP 5 LOSERS"]
    out += [line(i, x) for i, x in enumerate(losers, 1)] or ["(none)"]
    if calls is not None or puts is not None:
        out += format_option_section(calls or [], puts or [])
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


def render_options_card(day: date, calls: list[dict], puts: list[dict], path: Path) -> Path:
    """Portrait 1080x1920 picture with the top-5 call and top-5 put premium gainers (stock, strike, premium move)."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (11, 16, 32))
    draw = ImageDraw.Draw(img)
    for y in range(H):
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
    centered("OPTION PREMIUM GAINERS", 150, font(66, True), (255, 255, 255))
    centered(day.strftime("%d %B %Y"), 245, font(46), (142, 160, 189))

    def section(title: str, rows: list[dict], top: int, colour: tuple[int, int, int]) -> int:
        draw.rounded_rectangle([60, top, W - 60, top + 64], radius=16, fill=colour)
        draw.text((90, top + 8), title, font=font(44, True), fill=(10, 14, 26))
        y = top + 84
        for i, x in enumerate(rows or [], 1):
            draw.rounded_rectangle([60, y, W - 60, y + 110], radius=16, fill=(18, 26, 45))
            draw.text((90, y + 28), str(i), font=font(44, True), fill=(142, 160, 189))
            draw.text((170, y + 6), f"{x['symbol']} {x['strike']:g} {x['type']}", font=font(44, True), fill=(231, 238, 252))
            draw.text((170, y + 64), f"\u20b9{x['prev']:,.2f} \u2192 \u20b9{x['ltp']:,.2f}   stock {x['stock_pct']:+.1f}%", font=font(30), fill=(142, 160, 189))
            pct = f"{x['pct']:+.0f}%"
            w = draw.textlength(pct, font=font(54, True))
            draw.text((W - 90 - w, y + 26), pct, font=font(54, True), fill=colour)
            y += 124
        if not rows:
            draw.text((90, y + 20), "none", font=font(40), fill=(142, 160, 189))
            y += 110
        return y

    end = section("TOP 5 CALL PREMIUMS", calls, 330, (46, 204, 113))
    section("TOP 5 PUT PREMIUMS", puts, end + 20, (255, 99, 99))
    draw.text((60, H - 250), f"Nearest expiry, +/-{OPTION_STRIKES} strikes, prev close >= \u20b9{OPTION_MIN_PREV:g}, {OPTION_MIN_LOTS}+ lots traded",
              font=font(26), fill=(142, 160, 189))
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
    ap.add_argument("--options-card", metavar="PNG", help="only render the option-premium picture card to this file (no sending)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # emoji in the message must not crash a Windows console
    except Exception:  # noqa: BLE001
        pass
    now = datetime.now(IST)
    day = now.date().isoformat()
    report_day = date.fromisoformat(os.getenv("APLUS_MOVERS_DAY") or day)
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
    calls = puts = None
    try:                                                   # the option lists are an extra: stocks still go out if they fail
        spct = {str(r["symbol"]): (_f(r.get("ltp")) / _f(r.get("previous_close")) - 1.0) * 100.0 for r in rows
                if _f(r.get("ltp")) > 0 and _f(r.get("previous_close")) > 0}
        calls, puts = rank_option_movers(fetch_option_rows(os.getenv("APLUS_MOVERS_DAY") or day, spct))
    except Exception as exc:  # noqa: BLE001
        print(f"option premium section skipped: {type(exc).__name__}: {exc}")
    if args.options_card:
        print(render_options_card(report_day, calls or [], puts or [], Path(args.options_card)))
        return 0
    if args.card:
        print(render_card(report_day, gainers, losers, Path(args.card)))
        return 0
    message = format_message(report_day, gainers, losers, len(rows), calls, puts)
    try:                                                   # premium tracker line + the day's history file: an extra, never blocks the message
        import premium_tracker

        pday = report_day.isoformat()
        prows = premium_tracker.compute(pday, ROOT)
        if not args.dry_run:
            premium_tracker.record(pday, prows, ROOT)
        message += "\n".join(premium_tracker.telegram_lines(premium_tracker.enrich(prows, ROOT, pday)))
    except Exception as exc:  # noqa: BLE001
        print(f"premium tracker skipped: {type(exc).__name__}: {exc}")
    if args.dry_run:
        print(message)
        return 0
    from announcement_feed import send_telegram

    ok, detail = send_telegram(message)
    print("sent" if ok else f"send failed: {detail}")
    if ok:
        _mark_sent(report_day.isoformat())                 # the day the message is about (a manual re-send of an earlier day must not block today's)
        if not args.no_image:                              # the picture is a bonus: its failure never affects the text message
            try:
                card_path = render_card(report_day, gainers, losers, ROOT / "data" / "daily_movers" / f"{report_day.isoformat()}.png")
                print(send_telegram_photo(card_path, "APlus F&O top movers")[1])
                if calls is not None:
                    oc = render_options_card(report_day, calls, puts or [], ROOT / "data" / "daily_movers" / f"{report_day.isoformat()}_options.png")
                    print(send_telegram_photo(oc, "APlus option premium gainers")[1])
            except Exception as exc:  # noqa: BLE001
                print(f"picture skipped: {type(exc).__name__}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
