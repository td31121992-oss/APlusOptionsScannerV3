"""Manual paper trading: take a call somebody gave you (or your own idea) and trade it on paper with LIVE option quotes, in this software. PAPER ONLY - no order is ever sent anywhere.

    /manual-paper                          the page: enter a trade, watch it live, close it, see the result
    /api/manual-paper                      the open and closed manual trades with live marks and totals
    /api/manual-paper-contracts            expiries and strikes of a stock (for the form)
    /api/manual-paper-quote                the live bid / ask of one contract (the preview before you enter)
    POST /api/manual-paper-open|close|stop|ladder    enter / close / move the stop / switch the exit ladder

These trades live in their own file (data/manual_paper/trades.json) and are NEVER mixed into the scanner's journal, its statistics, the shadow scoreboard or any report: the scanner and its numbers are untouched.

How a trade is filled (the same honest rules as the scanner's paper trades):
  * entry  = the best ASK of the live quote when you press Enter (a buyer pays the ask). The price the caller named is stored next to it ("called price") so you can see how far the real fill was from the call.
  * marks  = the best BID (what a seller gets) - the open profit shown is what you would get by closing now, before costs; costs (brokerage, exchange charges, STT, GST, stamp, impact) are the scanner's own cost model.
  * exits  = (1) the stop: your initial stop (default 20% under the entry), (2) your exit ladder if switched on (once the best bid is +5% the stop moves to -15%, +10% -> +3%, +20% -> +13%, +30% -> +22%, +2 more
             per extra +5% - the same ladder as the scanner), (3) a stop you set yourself (it can only move UP), (4) the 15:15 close ONLY for INTRADAY trades (POSITIONAL trades are held overnight, for days, until a stop / target / Close, and are always closed at 15:15 on the option's expiry day), (5) the Close button. A stop or the 15:15 close sells at the BID of the first check
             that finds it breached (checks run about every 5 seconds while the market is open and the dashboard is up), so a fast gap can fill below the stop - and an overnight gap fills at the first bid of the next morning - as it would in reality. If the
             dashboard is down for a while a stop can only be applied when it is back; an option past its expiry date is closed at its last mark (EXPIRED_LAST_MARK).
  * PENDING ENTRY (like a broker terminal): give an entry price and the order WAITS. If the live ask is above your price it waits for the price to FALL to it (a buy limit); if the ask is below it waits for the price to
    RISE to it (a buy stop / breakout). It triggers when the last traded price touches your entry price and fills at the best ASK of that moment (so the fill can be a little worse than your price; the slippage is
    shown). A pending order is valid for the number of trading days you choose (today, 3, 5 or 10; weekends are skipped, exchange holidays are not known) and expires at 15:15 of its last day. You can cancel it any time. Optional SL price and TARGET price work from the fill on: the target sells at the bid when the bid reaches it.
  * TELEGRAM: the same bot as the scanner's paper alerts sends a message when a trade is filled, when it first reaches +5 / +10 / +20 / +30 / +50 / +100% (price gain on the entry), when the target or a stop is hit,
    when it is closed by hand / at expiry, and when a pending order is cancelled or expires. Each event is sent once (own memory in data/manual_paper). A failed send never affects a trade.
  * entries are refused when the market is closed, the quote is stale or empty, or the spread is wider than 5%.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FILE = ROOT / "data" / "manual_paper" / "trades.json"
IST = timezone(timedelta(hours=5, minutes=30))
LOCK = threading.RLock()
MAX_SPREAD_PCT = 5.0
UPDATE_EVERY = 5.0
_last_update = 0.0
_monitor_started = False
PROFIT_LEVELS = (5, 10, 20, 30, 50, 100)
_notifier: Any = None


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- storage
def _now() -> datetime:
    return datetime.now(IST)


def _load() -> list[dict[str, Any]]:
    try:
        return list(json.loads(FILE.read_text(encoding="utf-8")).get("trades", []))
    except (OSError, ValueError):
        return []


def _save(trades: list[dict[str, Any]]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"trades": trades}, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, FILE)


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- telegram
def _inr(v: Any) -> str:
    x = _f(v)
    return ("-" if x < 0 else "") + f"\u20b9{abs(x):,.0f}"


def _send(event: str, text: str) -> None:
    """Send once per event from a background thread: a slow or failing Telegram never delays or breaks a trade."""
    def work() -> None:
        global _notifier
        try:
            if _notifier is None:
                from telegram_notifier import TelegramPaperTradeNotifier
                _notifier = TelegramPaperTradeNotifier(state_dir=FILE.parent)
            _notifier._send(event, text)
        except Exception:                                      # noqa: BLE001
            pass
    threading.Thread(target=work, name="manual-paper-telegram", daemon=True).start()


def _label(t: dict[str, Any]) -> str:
    return f"{t.get('symbol', '')} {float(t.get('strike', 0)):g} {t.get('side', '')}"


def notify_entry(t: dict[str, Any]) -> None:
    slip = f" (your price {_f(t.get('trigger_price')):g}, slippage {_f(t.get('slippage_pct')):+.1f}%)" if t.get("trigger_price") else ""
    called = f"\nCalled price: {t['called_price']:g}" if t.get("called_price") else ""
    _send(f"{t['id']}|ENTRY", "\n".join([f"\U0001F4D2 MANUAL PAPER ENTRY: {_label(t)} exp {t.get('expiry')}", "",
                                         f"Bought {t.get('lots')} lot ({t.get('quantity')}) at {_f(t.get('entry_price')):.2f} (ask){slip}{called}",
                                         f"Capital {_inr(t.get('capital'))} | SL {stop_price(t):.2f} | Target {(_f(t.get('target_price')) or 0):g}".replace("Target 0", "Target none"),
                                         f"Hold: {'intraday (closes 15:15)' if t.get('hold') == 'INTRADAY' else 'positional (overnight until stop / target / you close it)'}",
                                         (f"Source: {t['source']}" if t.get("source") else ""), f"Trade ID: {t['id']}"]).replace("\n\n\n", "\n\n"))


def notify_profit(t: dict[str, Any], level: int, bid: float, net: float) -> None:
    _send(f"{t['id']}|PROFIT{level}", "\n".join([f"\U0001F7E2 MANUAL PAPER IN PROFIT: {_label(t)} is +{level}% above your entry", "",
                                                f"Entry {_f(t.get('entry_price')):.2f} | bid now {bid:.2f} ({(bid / _f(t['entry_price']) - 1) * 100:+.1f}%) | best {_f(t.get('high_bid')):.2f}",
                                                f"Open P&L after costs: {_inr(net)} | SL now {stop_price(t):.2f}" + (f" | Target {_f(t.get('target_price')):g}" if _f(t.get("target_price")) else ""),
                                                f"Trade ID: {t['id']}"]))


def notify_exit(t: dict[str, Any]) -> None:
    net = _f(t.get("net_pnl"))
    icon = "\u2705" if net > 0 else ("\u274C" if net < 0 else "\u2796")
    why = {"TARGET_HIT": "target hit", "STOP_OR_LADDER": "stop / ladder hit", "MANUAL_MODE_STOP": "your stop hit", "MANUAL_EXIT": "closed by you", "SESSION_END_1515": "intraday close 15:15",
           "EXPIRY_DAY_1515": "expiry day 15:15", "EXPIRED_LAST_MARK": "expired (last mark)"}.get(str(t.get("exit_reason")), str(t.get("exit_reason")))
    _send(f"{t['id']}|EXIT", "\n".join([f"{icon} MANUAL PAPER EXIT: {_label(t)} - {why}", "",
                                       f"Entry {_f(t.get('entry_price')):.2f} -> exit {_f(t.get('exit_price')):.2f} ({_f(t.get('return_percent')):+.1f}% after costs)",
                                       f"Net P&L {_inr(net)} (gross {_inr(t.get('gross_pnl'))}, costs {_inr(t.get('estimated_costs'))})", f"Trade ID: {t['id']}"]))


def notify_cancel(t: dict[str, Any]) -> None:
    why = {"EXPIRED_UNFILLED": "expired without filling", "SL_ALREADY_BREACHED_AT_TRIGGER": "the price touched your entry but was already under your SL, so it was not filled", "CANCELLED_BY_YOU": "cancelled by you"}.get(str(t.get("cancel_reason")), str(t.get("cancel_reason")))
    _send(f"{t['id']}|CANCEL", f"\u26AA MANUAL PAPER ORDER NOT FILLED: {_label(t)} at {_f(t.get('trigger_price')):g} - {why}.\nTrade ID: {t['id']}")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- market data
def _runtime() -> tuple[Any, Any]:
    import stock_analysis_tab
    return stock_analysis_tab._option_chain_runtime()


def market_open(now: datetime | None = None) -> bool:
    n = now or _now()
    m = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9 * 60 + 15 <= m <= 15 * 60 + 30


def _contracts(symbol: str, side: str) -> tuple[Any, list[Any]]:
    _, loader = _runtime()
    u = loader.get(symbol.strip().upper())
    if u is None:
        raise ValueError(f"{symbol} is not in the F&O list.")
    today = date.today().isoformat()
    cs = [c for c in u.contracts if str(c.option_type).upper() == side and str(c.expiry)[:10] >= today]
    return u, cs


def contracts(symbol: str, side: str) -> dict[str, Any]:
    side = "PE" if str(side).upper().startswith("P") else "CE"
    try:
        u, cs = _contracts(symbol, side)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    exp = sorted({str(c.expiry)[:10] for c in cs})
    by = {e: sorted({float(c.strike) for c in cs if str(c.expiry)[:10] == e}) for e in exp}
    return {"ok": True, "symbol": u.symbol, "side": side, "expiries": exp, "strikes": by, "lot_size": int(cs[0].lot_size) if cs else 0}


def chain(symbol: str, expiry: str = "") -> dict[str, Any]:
    """EVERY strike listed for the stock and expiry (both sides, from the instrument master), with the live bid / ask / last price / OI wherever the option chain has them."""
    try:
        u, ce = _contracts(symbol, "CE")
        _, pe = _contracts(symbol, "PE")
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    exps = sorted({str(c.expiry)[:10] for c in ce + pe})
    if not exps:
        return {"ok": False, "error": f"{symbol} has no live option contracts."}
    use = expiry if expiry in exps else exps[0]
    strikes = sorted({float(c.strike) for c in ce + pe if str(c.expiry)[:10] == use})
    live: dict[float, dict[str, Any]] = {}
    spot = 0.0
    note = ""
    try:
        import strategy_builder
        d = strategy_builder.chain(u.symbol, use)
        if d.get("ok"):
            spot = _f(d.get("spot"))
            live = {float(r["strike"]): r for r in d.get("strikes", [])}
        else:
            note = str(d.get("error") or "")[:160]
    except Exception as exc:                                   # noqa: BLE001
        note = f"{type(exc).__name__}: {str(exc)[:120]}"
    rows = [{"strike": k, "ce": (live.get(k) or {}).get("ce"), "pe": (live.get(k) or {}).get("pe")} for k in strikes]
    try:                                                       # strikes the chain feed left out: ask the quote service for them directly (one batched call)
        need = {str(c.derivative_security_id): (float(c.strike), "ce" if str(c.option_type).upper() == "CE" else "pe") for c in ce + pe
                if str(c.expiry)[:10] == use and not (live.get(float(c.strike)) or {}).get("ce" if str(c.option_type).upper() == "CE" else "pe")}
        if need:
            client, _ = _runtime()
            got = client.get_market_quotes({"NSE_FNO": list(need)}, mode="quote").get("NSE_FNO") or {}
            by = {r["strike"]: r for r in rows}
            for sid, (k, sd) in need.items():
                qq = got.get(sid) or {}
                dep = qq.get("depth") or {}
                b = [l for l in dep.get("buy", []) if _f(l.get("price")) > 0]
                a = [l for l in dep.get("sell", []) if _f(l.get("price")) > 0]
                if _f(qq.get("last_price")) > 0 or b or a:
                    by[k][sd] = {"ltp": _f(qq.get("last_price")), "bid": _f(b[0]["price"]) if b else 0.0, "ask": _f(a[0]["price"]) if a else 0.0, "oi": int(_f(qq.get("oi"))), "volume": int(_f(qq.get("volume")))}
    except Exception as exc:                                   # noqa: BLE001 - the rows we have are still shown
        note = (note + " " if note else "") + f"extra quotes unavailable: {type(exc).__name__}"
    lot = next((int(c.lot_size) for c in ce + pe if str(c.expiry)[:10] == use), 0)
    return {"ok": True, "symbol": u.symbol, "expiry": use, "expiries": exps, "spot": spot, "lot_size": lot, "rows": rows, "live_strikes": len([r for r in rows if r["ce"] or r["pe"]]), "note": note}


def _find(symbol: str, side: str, strike: float, expiry: str) -> Any:
    u, cs = _contracts(symbol, side)
    exp = sorted({str(c.expiry)[:10] for c in cs})
    if not exp:
        raise ValueError(f"{symbol} has no live {side} contracts.")
    use = expiry if expiry in exp else exp[0]
    hit = [c for c in cs if str(c.expiry)[:10] == use and abs(float(c.strike) - strike) < 1e-6]
    if not hit:
        raise ValueError(f"No {symbol} {strike:g} {side} contract for {use}.")
    return u, hit[0]


def _quote(sid: str) -> dict[str, float]:
    client, _ = _runtime()
    got = client.get_market_quotes({"NSE_FNO": [sid]}, mode="quote")
    q = (got.get("NSE_FNO") or {}).get(str(sid)) or (got.get("NSE_FNO") or {}).get(sid) or {}
    depth = q.get("depth") or {}
    buys = [l for l in depth.get("buy", []) if _f(l.get("price")) > 0]
    sells = [l for l in depth.get("sell", []) if _f(l.get("price")) > 0]
    return {"bid": _f(buys[0]["price"]) if buys else 0.0, "ask": _f(sells[0]["price"]) if sells else 0.0, "ltp": _f(q.get("last_price")),
            "bid_qty": int(_f(buys[0].get("quantity"))) if buys else 0, "ask_qty": int(_f(sells[0].get("quantity"))) if sells else 0, "time": str(q.get("last_trade_time") or "")}


def quote(symbol: str, side: str, strike: float, expiry: str) -> dict[str, Any]:
    side = "PE" if str(side).upper().startswith("P") else "CE"
    try:
        _, c = _find(symbol, side, float(strike), expiry or "")
        q = _quote(str(c.derivative_security_id))
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    sp = (q["ask"] - q["bid"]) / q["ask"] * 100 if q["ask"] > 0 and q["bid"] > 0 else None
    return {"ok": True, "contract": c.display_name, "expiry": str(c.expiry)[:10], "lot_size": int(c.lot_size), **q, "spread_pct": None if sp is None else round(sp, 2),
            "capital_per_lot": round(q["ask"] * int(c.lot_size), 2), "market_open": market_open()}


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- rules
def ladder_floor(entry: float, high: float) -> float:
    import paper_trade_journal as pj
    return pj.user_ladder_floor(entry, high)


def stop_price(t: dict[str, Any]) -> float:
    entry = _f(t.get("entry_price"))
    s = _f(t.get("sl_price")) if _f(t.get("sl_price")) > 0 else entry * (1.0 - _f(t.get("stop_pct")) / 100.0)
    if t.get("ladder", True):
        s = max(s, ladder_floor(entry, _f(t.get("high_bid"))))
    s = max(s, _f(t.get("manual_stop")))
    return round(s, 2)


def _costs(entry: float, exit_price: float, qty: int, spread_pct: float) -> float:
    from trade_costs import round_trip_costs
    return float(round_trip_costs(entry, exit_price, qty, spread_pct)["total"])


def _close(t: dict[str, Any], price: float, reason: str, when: datetime) -> None:
    entry, qty = _f(t["entry_price"]), int(t["quantity"])
    gross = (price - entry) * qty
    costs = _costs(entry, price, qty, _f(t.get("entry_spread_pct")))
    net = gross - costs
    cap = entry * qty
    t.update({"status": "CLOSED", "exit_time": when.isoformat(), "exit_price": round(price, 2), "exit_reason": reason, "gross_pnl": round(gross, 2), "estimated_costs": round(costs, 2),
              "net_pnl": round(net, 2), "return_percent": round(net / cap * 100, 2) if cap > 0 else 0.0, "result": "WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT")})
    notify_exit(t)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- actions
def _next_session_date(now: datetime, days: int = 1) -> str:
    """The last day a pending order stays valid: `days` trading days counted from the first session that can still fill it (weekends skipped)."""
    d = now.date()
    if now.weekday() >= 5 or now.hour * 60 + now.minute >= 15 * 60 + 15:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    for _ in range(max(1, int(days)) - 1):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d.isoformat()


def _hold_of(req: dict[str, Any]) -> str:
    return "INTRADAY" if str(req.get("hold", "POSITIONAL")).upper().startswith("I") else "POSITIONAL"


def _fill(u: Any, c: Any, q: dict[str, float], req: dict[str, Any], now: datetime, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """The OPEN trade record for a fill at the ask of quote q."""
    spread = (q["ask"] - q["bid"]) / q["ask"] * 100
    lots = int(req["lots"])
    qty = int(c.lot_size) * lots
    t = dict(base or {})
    t.update({"id": t.get("id") or "MP-" + now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4].upper(), "status": "OPEN", "symbol": u.symbol, "side": str(c.option_type).upper(), "strike": float(c.strike),
              "expiry": str(c.expiry)[:10], "contract": c.display_name, "security_id": str(c.derivative_security_id), "lot_size": int(c.lot_size), "lots": lots, "quantity": qty,
              "entry_time": now.isoformat(), "entry_price": round(q["ask"], 2), "entry_bid": round(q["bid"], 2), "entry_spread_pct": round(spread, 2), "called_price": _f(req.get("called_price")) or None,
              "stop_pct": _f(req.get("stop_pct")) or 20.0, "sl_price": _f(req.get("sl_price")) or 0.0, "target_price": _f(req.get("target_price")) or 0.0, "ladder": bool(req.get("ladder", True)),
              "hold": _hold_of(req), "manual_stop": 0.0, "source": str(req.get("source") or "")[:80], "note": str(req.get("note") or "")[:300], "high_bid": round(q["bid"], 2), "low_bid": round(q["bid"], 2),
              "last_bid": round(q["bid"], 2), "last_ask": round(q["ask"], 2), "last_ltp": round(q["ltp"], 2), "last_mark_time": now.isoformat(), "capital": round(q["ask"] * qty, 2), "paper_only": True})
    if t.get("trigger_price"):
        t["slippage_pct"] = round((q["ask"] / _f(t["trigger_price"]) - 1) * 100, 2)
    return t


def _int_days(v: Any) -> int:
    try:
        return max(1, min(30, int(float(v))))
    except (TypeError, ValueError):
        return 1


def _check_levels(entry: float, sl: float, target: float, stop_pct: float) -> str | None:
    if sl > 0 and sl >= entry:
        return f"The SL price ({sl:g}) must be below the entry price ({entry:g})."
    if target > 0 and target <= entry:
        return f"The target ({target:g}) must be above the entry price ({entry:g})."
    if sl <= 0 and not 1.0 <= stop_pct <= 90.0:
        return "The stop % must be between 1 and 90."
    return None


def open_trade(req: dict[str, Any]) -> dict[str, Any]:
    side = "PE" if str(req.get("side", "")).upper().startswith("P") else "CE"
    symbol = str(req.get("symbol", "")).strip().upper()
    try:
        strike = float(req.get("strike"))
        lots = max(1, min(50, int(req.get("lots") or 1)))
        stop_pct = float(req.get("stop_pct") or 20)
        entry_px, sl, target = _f(req.get("entry_price")), _f(req.get("sl_price")), _f(req.get("target_price"))
    except (TypeError, ValueError):
        return {"ok": False, "message": "Check the strike, lots, prices and stop %."}
    try:
        u, c = _find(symbol, side, strike, str(req.get("expiry") or ""))
        q = _quote(str(c.derivative_security_id))
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:200]}"}
    now = _now()
    req = {**req, "lots": lots, "stop_pct": stop_pct}
    if entry_px > 0:                                           # a PENDING order: wait for the price to touch the entry price
        bad = _check_levels(entry_px, sl, target, stop_pct)
        if bad:
            return {"ok": False, "message": bad}
        ref = q["ask"] if q["ask"] > 0 else q["ltp"]
        if ref <= 0:
            return {"ok": False, "message": "No live price to compare your entry price with."}
        if abs(ref / entry_px - 1) < 0.0005:
            return {"ok": False, "message": f"The price is already at {entry_px:g}: leave the entry price empty to buy now."}
        t = {"id": "MP-" + now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4].upper(), "status": "PENDING", "symbol": u.symbol, "side": side, "strike": float(c.strike), "expiry": str(c.expiry)[:10],
             "contract": c.display_name, "security_id": str(c.derivative_security_id), "lot_size": int(c.lot_size), "lots": lots, "quantity": int(c.lot_size) * lots, "trigger_price": round(entry_px, 2),
             "trigger_dir": "FALL" if ref > entry_px else "RISE", "placed_time": now.isoformat(), "valid_date": _next_session_date(now, _int_days(req.get("valid_days"))), "hold": _hold_of(req), "placed_ask": round(ref, 2), "request": dict(req),
             "called_price": _f(req.get("called_price")) or None, "sl_price": sl, "target_price": target, "stop_pct": stop_pct, "ladder": bool(req.get("ladder", True)), "source": str(req.get("source") or "")[:80],
             "note": str(req.get("note") or "")[:300], "last_ltp": round(q["ltp"], 2), "last_ask": round(q["ask"], 2), "last_bid": round(q["bid"], 2), "paper_only": True}
        with LOCK:
            trades = _load()
            trades.append(t)
            _save(trades)
        ensure_monitor()
        way = "falls to" if t["trigger_dir"] == "FALL" else "rises to"
        return {"ok": True, "trade": t, "message": f"Pending order placed: {c.display_name} will be bought when the price {way} {entry_px:g} (now ask {ref:.2f}). Valid until 15:15 on {t['valid_date']}; once filled it is held {'for the day only (closed at 15:15)' if t['hold'] == 'INTRADAY' else 'overnight until a stop, target, Close or its expiry day'}."}
    if not market_open():
        return {"ok": False, "message": "The market is closed, so there is no live quote to fill against. Try again between 09:15 and 15:30 (IST) on a trading day, or give an entry price to place a pending order."}
    if q["ask"] <= 0 or q["bid"] <= 0 or q["ask"] < q["bid"]:
        return {"ok": False, "message": "No usable bid / ask for this contract right now (it may be illiquid), so no fill was made."}
    spread = (q["ask"] - q["bid"]) / q["ask"] * 100
    if spread > MAX_SPREAD_PCT:
        return {"ok": False, "message": f"The bid-ask spread is {spread:.1f}% (limit {MAX_SPREAD_PCT:.0f}%): entering would lose that much at once."}
    bad = _check_levels(q["ask"], sl, target, stop_pct)
    if bad:
        return {"ok": False, "message": bad}
    t = _fill(u, c, q, req, now)
    with LOCK:
        trades = _load()
        trades.append(t)
        _save(trades)
    notify_entry(t)
    ensure_monitor()
    return {"ok": True, "trade": t, "message": f"Paper trade entered: bought {lots} lot ({t['quantity']}) {c.display_name} at {q['ask']:.2f} (ask)."}


def cancel_pending(tid: str) -> dict[str, Any]:
    with LOCK:
        trades = _load()
        t = _find_trade(trades, tid)
        if t is None or t.get("status") != "PENDING":
            return {"ok": False, "message": "That order is not pending."}
        t.update({"status": "CANCELLED", "cancel_reason": "CANCELLED_BY_YOU", "cancel_time": _now().isoformat()})
        _save(trades)
    return {"ok": True, "trade": t, "message": "Pending order cancelled."}


def _find_trade(trades: list[dict[str, Any]], tid: str) -> dict[str, Any] | None:
    return next((t for t in trades if t.get("id") == tid), None)


def close_trade(tid: str) -> dict[str, Any]:
    with LOCK:
        trades = _load()
        t = _find_trade(trades, tid)
        if t is None or t.get("status") != "OPEN":
            return {"ok": False, "message": "That trade is not open."}
        try:
            q = _quote(t["security_id"])
        except Exception as exc:                               # noqa: BLE001
            return {"ok": False, "message": f"No quote to close against: {str(exc)[:160]}"}
        price = q["bid"] if q["bid"] > 0 else _f(t.get("last_bid"))
        if price <= 0:
            return {"ok": False, "message": "No bid to sell into right now."}
        _close(t, price, "MANUAL_EXIT", _now())
        _save(trades)
    return {"ok": True, "trade": t, "message": f"Closed at the bid {price:.2f}."}


def set_stop(tid: str, price: Any) -> dict[str, Any]:
    with LOCK:
        trades = _load()
        t = _find_trade(trades, tid)
        if t is None or t.get("status") != "OPEN":
            return {"ok": False, "message": "That trade is not open."}
        p = _f(price)
        if p <= 0:
            t["manual_stop"] = 0.0
            _save(trades)
            return {"ok": True, "trade": t, "message": "Your own stop was cleared."}
        if p >= _f(t.get("last_bid")):
            return {"ok": False, "message": f"A stop must be below the current bid ({_f(t.get('last_bid')):.2f}); it would trigger at once."}
        if p < _f(t.get("manual_stop")):
            return {"ok": False, "message": "A stop can only move up, never down."}
        t["manual_stop"] = round(p, 2)
        _save(trades)
    return {"ok": True, "trade": t, "message": f"Stop set at {p:.2f}."}


def set_ladder(tid: str, on: bool) -> dict[str, Any]:
    with LOCK:
        trades = _load()
        t = _find_trade(trades, tid)
        if t is None or t.get("status") != "OPEN":
            return {"ok": False, "message": "That trade is not open."}
        t["ladder"] = bool(on)
        _save(trades)
    return {"ok": True, "trade": t, "message": "Exit ladder " + ("ON" if on else "OFF") + "."}


def update(force: bool = False) -> None:
    """Mark every open trade at the live bid; apply the stop / ladder / 15:15 close."""
    global _last_update
    with LOCK:
        if not force and time.monotonic() - _last_update < UPDATE_EVERY - 0.5:
            return
        _last_update = time.monotonic()
        trades = _load()
        open_ = [t for t in trades if t.get("status") == "OPEN"]
        pend = [t for t in trades if t.get("status") == "PENDING"]
        if not open_ and not pend:
            return
        now = _now()
        changed = False
        for t in pend:                                         # expire what is not filled by 15:15 of its valid day
            vd = str(t.get("valid_date") or "")
            if now.date().isoformat() > vd or (now.date().isoformat() == vd and now.hour * 60 + now.minute >= 15 * 60 + 15):
                t.update({"status": "CANCELLED", "cancel_reason": "EXPIRED_UNFILLED", "cancel_time": now.isoformat()})
                notify_cancel(t)
                changed = True
        pend = [t for t in pend if t.get("status") == "PENDING"]
        if not market_open(now):
            if changed:
                _save(trades)
            return
        try:
            client, loader = _runtime()
            ids = [t["security_id"] for t in open_ + pend]
            got = client.get_market_quotes({"NSE_FNO": ids}, mode="quote").get("NSE_FNO") or {}
        except Exception:                                      # noqa: BLE001 - keep the last marks, try again next time
            if changed:
                _save(trades)
            return
        for t in pend:
            q = got.get(str(t["security_id"])) or {}
            buys = [l for l in (q.get("depth") or {}).get("buy", []) if _f(l.get("price")) > 0]
            sells = [l for l in (q.get("depth") or {}).get("sell", []) if _f(l.get("price")) > 0]
            bid, ask, ltp = (_f(buys[0]["price"]) if buys else 0.0), (_f(sells[0]["price"]) if sells else 0.0), _f(q.get("last_price"))
            if ltp <= 0:
                continue
            t["last_ltp"], t["last_ask"], t["last_bid"] = round(ltp, 2), round(ask, 2), round(bid, 2)
            trig = _f(t["trigger_price"])
            touched = ltp <= trig if t.get("trigger_dir") == "FALL" else ltp >= trig
            changed = True
            if not touched or ask <= 0 or bid <= 0 or ask < bid:
                continue
            if (ask - bid) / ask * 100 > MAX_SPREAD_PCT:
                continue                                       # touched, but the quote is too wide to fill honestly: keep waiting
            sl = _f(t.get("sl_price"))
            if sl > 0 and ask <= sl:
                t.update({"status": "CANCELLED", "cancel_reason": "SL_ALREADY_BREACHED_AT_TRIGGER", "cancel_time": now.isoformat()})
                notify_cancel(t)
                continue
            u = loader.get(t["symbol"])
            c = next((x for x in u.contracts if str(x.derivative_security_id) == str(t["security_id"])), None) if u is not None else None
            if c is None:
                continue
            base = {k: t[k] for k in ("id", "trigger_price", "trigger_dir", "placed_time") if k in t}
            filled = _fill(u, c, {"bid": bid, "ask": ask, "ltp": ltp}, dict(t.get("request") or {}), now, base)
            t.clear()
            t.update(filled)
            notify_entry(t)
        open_ = [t for t in trades if t.get("status") == "OPEN"]
        for t in open_:
            exp_day = str(t.get("expiry") or "")[:10]
            if exp_day and exp_day < now.date().isoformat() and _f(t.get("last_bid")) > 0:        # the contract has expired (the dashboard was down on expiry day): settle at the last mark we have
                _close(t, _f(t["last_bid"]), "EXPIRED_LAST_MARK", now)
                changed = True
                continue
            q = got.get(str(t["security_id"])) or {}
            buys = [l for l in (q.get("depth") or {}).get("buy", []) if _f(l.get("price")) > 0]
            sells = [l for l in (q.get("depth") or {}).get("sell", []) if _f(l.get("price")) > 0]
            bid = _f(buys[0]["price"]) if buys else 0.0
            ask = _f(sells[0]["price"]) if sells else 0.0
            if bid > 0:
                t["last_bid"], t["last_mark_time"] = round(bid, 2), now.isoformat()
                t["high_bid"], t["low_bid"] = round(max(_f(t["high_bid"]), bid), 2), round(min(_f(t["low_bid"]), bid), 2)
                changed = True
            if ask > 0:
                t["last_ask"] = round(ask, 2)
            if _f(q.get("last_price")) > 0:
                t["last_ltp"] = round(_f(q.get("last_price")), 2)
            if bid <= 0:
                continue
            gain = (bid / _f(t["entry_price"]) - 1) * 100 if _f(t.get("entry_price")) > 0 else 0.0
            for lvl in PROFIT_LEVELS:
                if gain >= lvl and lvl not in t.setdefault("tg_levels", []):          # each level is announced once per trade
                    t["tg_levels"].append(lvl)
                    changed = True
                    net_now = (bid - _f(t["entry_price"])) * int(t["quantity"]) - _costs(_f(t["entry_price"]), bid, int(t["quantity"]), _f(t.get("entry_spread_pct")))
                    notify_profit(t, lvl, bid, net_now)
            exp_day = str(t.get("expiry") or "")[:10]
            if now.hour * 60 + now.minute >= 15 * 60 + 15 and (t.get("hold") == "INTRADAY" or (exp_day and exp_day <= now.date().isoformat())):
                _close(t, bid, "SESSION_END_1515" if t.get("hold") == "INTRADAY" else "EXPIRY_DAY_1515", now)
                changed = True
            elif _f(t.get("target_price")) > 0 and bid >= _f(t.get("target_price")):
                _close(t, bid, "TARGET_HIT", now)
                changed = True
            elif bid <= stop_price(t):
                _close(t, bid, "MANUAL_MODE_STOP" if _f(t.get("manual_stop")) >= stop_price(t) else "STOP_OR_LADDER", now)
                changed = True
        if changed:
            _save(trades)


def _monitor() -> None:
    while True:
        try:
            if market_open():
                update(force=True)
        except Exception:                                      # noqa: BLE001
            pass
        time.sleep(UPDATE_EVERY)


def ensure_monitor() -> None:
    global _monitor_started
    if not _monitor_started:
        _monitor_started = True
        threading.Thread(target=_monitor, name="manual-paper-monitor", daemon=True).start()


def state() -> dict[str, Any]:
    ensure_monitor()
    update()
    with LOCK:
        trades = _load()
    out = []
    for t in trades:
        r = dict(t)
        if t.get("status") == "OPEN":
            entry, qty, bid = _f(t["entry_price"]), int(t["quantity"]), _f(t.get("last_bid"))
            gross = (bid - entry) * qty
            costs = _costs(entry, bid, qty, _f(t.get("entry_spread_pct"))) if bid > 0 else 0.0
            r.update({"stop": stop_price(t), "gross_pnl": round(gross, 2), "estimated_costs": round(costs, 2), "net_pnl": round(gross - costs, 2),
                      "return_percent": round((gross - costs) / (entry * qty) * 100, 2) if entry * qty > 0 else 0.0, "best_pct": round((_f(t.get("high_bid")) / entry - 1) * 100, 2) if entry > 0 else 0.0})
        out.append(r)
    out.sort(key=lambda x: x.get("entry_time", ""), reverse=True)
    closed = [t for t in out if t.get("status") == "CLOSED"]
    opn = [t for t in out if t.get("status") == "OPEN"]
    wins = [t for t in closed if _f(t.get("net_pnl")) > 0]
    return {"ok": True, "now": _now().isoformat(), "market_open": market_open(), "trades": out,
            "summary": {"pending": len([t for t in out if t.get("status") == "PENDING"]), "open": len(opn), "closed": len(closed), "open_net": round(sum(_f(t.get("net_pnl")) for t in opn), 2), "closed_net": round(sum(_f(t.get("net_pnl")) for t in closed), 2),
                        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None, "costs": round(sum(_f(t.get("estimated_costs")) for t in closed), 2)}}


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- web glue
def handle_get(path: str, q: dict[str, str]) -> tuple[str, bytes]:
    if path == "/manual-paper":
        return "text/html; charset=utf-8", MANUAL_HTML.encode("utf-8")
    if path == "/api/manual-paper":
        out = state()
    elif path == "/api/manual-paper-contracts":
        out = contracts(q.get("symbol") or "", q.get("side") or "CE")
    elif path == "/api/manual-paper-chain":
        out = chain(q.get("symbol") or "", q.get("expiry") or "")
    else:
        out = quote(q.get("symbol") or "", q.get("side") or "CE", _f(q.get("strike")), q.get("expiry") or "")
    return "application/json", json.dumps(out).encode("utf-8")


def handle_post(route: str, req: dict[str, Any]) -> dict[str, Any]:
    if route == "/api/manual-paper-open":
        return open_trade(req)
    if route == "/api/manual-paper-cancel":
        return cancel_pending(str(req.get("id", "")))
    if route == "/api/manual-paper-close":
        return close_trade(str(req.get("id", "")))
    if route == "/api/manual-paper-stop":
        return set_stop(str(req.get("id", "")), req.get("stop"))
    if route == "/api/manual-paper-ladder":
        return set_ladder(str(req.get("id", "")), bool(req.get("on")))
    return {"ok": False, "message": "Unknown action."}


MANUAL_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Manual Paper</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--blue:#4c8dff;--green:#27c281;--red:#ff6b6b;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none;font-weight:700}
.top{display:flex;gap:10px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
button,input,select{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}button{cursor:pointer;font-weight:700}
button.go{background:var(--green);border-color:var(--green);color:#04251a}button.stop{background:#3a1620;border-color:#6b2a2a;color:#ffb9c8}
.wrap{padding:10px 12px;max-width:1500px;margin:0 auto}.sub{color:var(--muted);font-size:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:10px 0}.panel h3{margin:0 0 8px;font-size:13px}
.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px 12px;align-items:end}.form label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;margin-bottom:2px}.form input,.form select{width:100%}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px}.card .l{color:var(--muted);font-size:11px;text-transform:uppercase}.card .v{font-size:18px;font-weight:800}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}th,td{padding:6px 9px;text-align:right;border-bottom:1px solid #1b2640;white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;background:#0f1729}td.l,th.l{text-align:left}
.up{color:var(--green);font-weight:800}.dn{color:var(--red);font-weight:800}.msg{padding:8px 12px;border-radius:8px;margin:8px 0}.msg.ok{background:#0f2a22;border:1px solid #1f6b50}.msg.no{background:#2a1414;border:1px solid #6b2a2a}
</style></head><body>
<div class="top"><a href="/">&larr; Dashboard</a><b>Manual Paper Trading</b><span class="sub" id="meta"></span></div>
<div class="wrap">
<div class="sub">Trade a call you were given (or your own idea) on PAPER with live option quotes. Filled at the ASK, marked and closed at the BID, with the scanner's cost model. Nothing is ever sent to a broker, and these trades never mix with the scanner's numbers.</div>
<div class="panel"><h3>New paper trade</h3>
<div class="form">
<div><label>Stock</label><input id="sym" list="syms" placeholder="e.g. TCS" style="text-transform:uppercase"><datalist id="syms"></datalist></div>
<div><label>Side</label><select id="side"><option value="CE">Call (CE)</option><option value="PE">Put (PE)</option></select></div>
<div><label>Expiry</label><select id="exp"></select></div>
<div><label>Strike</label><input id="strike" list="strikes" type="number" step="any"><datalist id="strikes"></datalist></div>
<div><label>Lots</label><input id="lots" type="number" min="1" max="50" value="1"></div>
<div><label>Called price (optional)</label><input id="called" type="number" step="any" placeholder="what the caller said"></div>
<div><label>Entry price (empty = buy now)</label><input id="entry" type="number" step="any" placeholder="wait for this price"></div>
<div><label>SL price</label><input id="slp" type="number" step="any" placeholder="stop-loss price"></div>
<div><label>Target price</label><input id="tgt" type="number" step="any" placeholder="target price"></div>
<div><label>Stop % (if no SL price)</label><input id="stoppct" type="number" step="any" value="20"></div>
<div><label>Hold</label><select id="hold"><option value="POSITIONAL">Positional (days, overnight)</option><option value="INTRADAY">Intraday (close 15:15)</option></select></div>
<div><label>Pending order valid for</label><select id="valid"><option value="1">Today / next session</option><option value="3">3 trading days</option><option value="5">5 trading days</option><option value="10">10 trading days</option></select></div>
<div><label>Exit ladder</label><select id="ladder"><option value="1">ON (like the scanner)</option><option value="0">OFF (stop only)</option></select></div>
<div><label>Who gave the call</label><input id="src" placeholder="name / channel"></div>
<div><label>Note</label><input id="note"></div>
<div><button id="prev">Get live quote</button> <button id="loadchain">Show all strikes</button> <button class="go" id="enter">Place / enter</button></div>
</div>
<div id="q" class="sub" style="margin-top:8px"></div><div id="msg"></div></div>
<div class="panel" id="chainbox" style="display:none"><h3 id="chaintitle">Option chain</h3><div class="sub">Every listed strike. Click a call or put price to pick that contract (the form fills in and the live quote is shown). Blank prices = the exchange has no live quote for that strike right now.</div><div id="chain" style="max-height:420px;overflow:auto;margin-top:6px"></div></div>
<div class="cards" id="cards"></div>
<div class="panel"><h3>Pending orders (waiting for your entry price)</h3><div id="pend" class="sub">None.</div></div>
<div class="panel"><h3>Open trades</h3><div id="open" class="sub">None.</div></div>
<div class="panel"><h3>Closed trades</h3><div id="closed" class="sub">None.</div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const inr=v=>(v<0?'-':'')+'₹'+Math.abs(v).toLocaleString('en-IN',{maximumFractionDigits:0});
const cls=v=>v>0?'up':v<0?'dn':'';
const t5=s=>s?String(s).slice(11,16):'';
async function jget(u){const r=await fetch(u+(u.includes('?')?'&':'?')+'ts='+Date.now());return r.json();}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
function say(o){$('msg').innerHTML=`<div class="msg ${o.ok?'ok':'no'}">${o.message||o.error||''}</div>`;}
let chain=null;
async function loadSyms(){const d=await jget('/api/contract-lab-symbols');if(d.symbols)$('syms').innerHTML=d.symbols.map(s=>`<option value="${s}">`).join('');}
async function loadChain(){const s=$('sym').value.trim().toUpperCase();if(!s)return;const d=await jget('/api/manual-paper-contracts?symbol='+encodeURIComponent(s)+'&side='+$('side').value);
 if(!d.ok){chain=null;$('q').textContent=d.error;return;}chain=d;$('exp').innerHTML=d.expiries.map(e=>`<option>${e}</option>`).join('');fillStrikes();$('q').textContent=`${d.symbol}: lot size ${d.lot_size}`;}
function fillStrikes(){if(!chain)return;$('strikes').innerHTML=(chain.strikes[$('exp').value]||[]).map(k=>`<option value="${k}">`).join('');}
function body(){return {symbol:$('sym').value.trim().toUpperCase(),side:$('side').value,expiry:$('exp').value,strike:$('strike').value,lots:$('lots').value,called_price:$('called').value,hold:$('hold').value,valid_days:$('valid').value,entry_price:$('entry').value,sl_price:$('slp').value,target_price:$('tgt').value,stop_pct:$('stoppct').value,ladder:$('ladder').value==='1',source:$('src').value,note:$('note').value};}
async function preview(){const b=body();const d=await jget(`/api/manual-paper-quote?symbol=${encodeURIComponent(b.symbol)}&side=${b.side}&strike=${b.strike}&expiry=${b.expiry}`);
 if(!d.ok){$('q').innerHTML=`<span class="dn">${d.error}</span>`;return;}
 const called=parseFloat(b.called_price);const gap=called>0?` | called ${called} vs ask ${d.ask.toFixed(2)} (${((d.ask/called-1)*100).toFixed(1)}%)`:'';
 $('q').innerHTML=`<b>${d.contract}</b> exp ${d.expiry} | bid ${d.bid.toFixed(2)} (${d.bid_qty}) / ask ${d.ask.toFixed(2)} (${d.ask_qty}) | spread ${d.spread_pct==null?'-':d.spread_pct+'%'} | lot ${d.lot_size} | capital per lot ${inr(d.capital_per_lot)}${gap}${d.market_open?'':' | <span class="dn">market closed</span>'}`;}
async function showChain(){const b=body();if(!b.symbol){say({ok:false,message:'Type a stock first.'});return;}
 const d=await jget(`/api/manual-paper-chain?symbol=${encodeURIComponent(b.symbol)}&expiry=${b.expiry||''}`);
 if(!d.ok){say({ok:false,message:d.error});return;}
 if(d.expiries&&$('exp').options.length!==d.expiries.length){$('exp').innerHTML=d.expiries.map(e=>`<option ${e===d.expiry?'selected':''}>${e}</option>`).join('');}
 $('exp').value=d.expiry;$('chainbox').style.display='block';
 const n=v=>v==null||v===0?'':Number(v).toFixed(2);const atm=d.spot>0?d.rows.reduce((a,r)=>Math.abs(r.strike-d.spot)<Math.abs(a-d.spot)?r.strike:a,d.rows[0].strike):null;
 $('chaintitle').textContent=`${d.symbol} option chain - expiry ${d.expiry} - ${d.rows.length} strikes${d.spot>0?' - spot '+d.spot:''} - lot ${d.lot_size}`+(d.note?' ('+d.note+')':'');
 const cell=(r,sd)=>{const q=r[sd];return q?`<td onclick="pick(${r.strike},'${sd.toUpperCase()}')" style="cursor:pointer">${n(q.bid)}</td><td onclick="pick(${r.strike},'${sd.toUpperCase()}')" style="cursor:pointer">${n(q.ask)}</td><td onclick="pick(${r.strike},'${sd.toUpperCase()}')" style="cursor:pointer"><b>${n(q.ltp)}</b></td>`:`<td onclick="pick(${r.strike},'${sd.toUpperCase()}')" style="cursor:pointer" colspan="3" class="sub">&mdash;</td>`;};
 $('chain').innerHTML=`<table><thead><tr><th colspan="3">CALLS (CE)</th><th>Strike</th><th colspan="3">PUTS (PE)</th></tr><tr><th>Bid</th><th>Ask</th><th>LTP</th><th></th><th>Bid</th><th>Ask</th><th>LTP</th></tr></thead><tbody>${d.rows.map(r=>`<tr ${r.strike===atm?'style="background:#16213a"':''}>${cell(r,'ce')}<td><b>${r.strike}</b></td>${cell(r,'pe')}</tr>`).join('')}</tbody></table>`;
 if(atm){const el=[...$('chain').querySelectorAll('tr')].find(x=>x.style.background);if(el)el.scrollIntoView({block:'center'});}}
function pick(k,sd){$('strike').value=k;$('side').value=sd;preview();}
async function enter(){const o=await jpost('/api/manual-paper-open',body());say(o);refresh();}
async function cancelT(id){say(await jpost('/api/manual-paper-cancel',{id}));refresh();}
async function closeT(id){if(!confirm('Close this paper trade at the current bid?'))return;say(await jpost('/api/manual-paper-close',{id}));refresh();}
async function stopT(id){const v=prompt('New stop price (it can only move up):');if(v===null)return;say(await jpost('/api/manual-paper-stop',{id,stop:v}));refresh();}
async function ladT(id,on){say(await jpost('/api/manual-paper-ladder',{id,on}));refresh();}
function row(t,open){const pnl=t.net_pnl||0;
 if(open)return `<tr><td class="l">${t.contract}<div class="sub">${t.id} ${t.source?'| '+t.source:''}</div></td><td>${String(t.entry_time).slice(5,10)} ${t5(t.entry_time)}<div class="sub">${t.hold==='INTRADAY'?'intraday':'positional'}</div></td><td>${t.entry_price.toFixed(2)}${t.called_price?`<div class="sub">called ${t.called_price}</div>`:''}</td><td>${t.last_bid.toFixed(2)} / ${t.last_ask.toFixed(2)}</td><td>${t.best_pct>0?'+':''}${t.best_pct}%</td><td>${t.stop.toFixed(2)}${t.manual_stop?' (yours)':''}${t.target_price?`<div class="sub">target ${t.target_price}</div>`:''}</td><td>${t.quantity}</td><td class="${cls(pnl)}">${inr(pnl)}<div class="sub">${t.return_percent}% after costs ${inr(t.estimated_costs)}</div></td><td class="l"><button class="stop" onclick="closeT('${t.id}')">Close</button> <button onclick="stopT('${t.id}')">Stop</button> <button onclick="ladT('${t.id}',${t.ladder?'false':'true'})">Ladder ${t.ladder?'ON':'OFF'}</button></td></tr>`;
 return `<tr><td class="l">${t.contract}<div class="sub">${t.id} ${t.source?'| '+t.source:''}</div></td><td>${String(t.entry_time).slice(5,10)} ${t5(t.entry_time)} &rarr; ${String(t.exit_time).slice(5,10)} ${t5(t.exit_time)}</td><td>${t.entry_price.toFixed(2)} &rarr; ${t.exit_price.toFixed(2)}</td><td>${t.exit_reason}</td><td>${t.quantity}</td><td class="${cls(pnl)}">${inr(pnl)}</td><td>${t.return_percent}%</td><td>${inr(t.estimated_costs)}</td></tr>`;}
async function refresh(){const d=await jget('/api/manual-paper');if(!d.ok)return;const s=d.summary;
 $('meta').textContent=(d.market_open?'market open':'market closed')+' | updates every 5 s';
 $('cards').innerHTML=`<div class="card"><div class="l">Pending orders</div><div class="v">${s.pending||0}</div></div><div class="card"><div class="l">Open trades</div><div class="v">${s.open}</div></div><div class="card"><div class="l">Open P&L (after costs)</div><div class="v ${cls(s.open_net)}">${inr(s.open_net)}</div></div><div class="card"><div class="l">Closed P&L</div><div class="v ${cls(s.closed_net)}">${inr(s.closed_net)}</div></div><div class="card"><div class="l">Closed trades / win rate</div><div class="v">${s.closed} / ${s.win_rate==null?'-':s.win_rate+'%'}</div></div><div class="card"><div class="l">Costs paid</div><div class="v">${inr(s.costs)}</div></div>`;
 const o=d.trades.filter(t=>t.status==='OPEN'),c=d.trades.filter(t=>t.status==='CLOSED'),pd=d.trades.filter(t=>t.status==='PENDING');
 $('pend').innerHTML=pd.length?`<table><thead><tr><th class="l">Contract</th><th>Waits for</th><th>Now (bid / ask / ltp)</th><th>SL</th><th>Target</th><th>Valid until</th><th class="l"></th></tr></thead><tbody>${pd.map(t=>`<tr><td class="l">${t.contract}<div class="sub">${t.id} ${t.source?'| '+t.source:''}</div></td><td>${t.trigger_dir==='FALL'?'falls to':'rises to'} <b>${t.trigger_price}</b></td><td>${(t.last_bid||0).toFixed(2)} / ${(t.last_ask||0).toFixed(2)} / ${(t.last_ltp||0).toFixed(2)}</td><td>${t.sl_price||'-'}</td><td>${t.target_price||'-'}</td><td>${t.valid_date} 15:15<div class="sub">${t.hold==='INTRADAY'?'then intraday':'then positional'}</div></td><td class="l"><button class="stop" onclick="cancelT('${t.id}')">Cancel</button></td></tr>`).join('')}</tbody></table>`:'None.';
 $('open').innerHTML=o.length?`<table><thead><tr><th class="l">Contract</th><th>Entered</th><th>Entry (ask)</th><th>Bid / ask</th><th>Best so far</th><th>Stop</th><th>Qty</th><th>P&L now</th><th class="l"></th></tr></thead><tbody>${o.map(t=>row(t,true)).join('')}</tbody></table>`:'None.';
 $('closed').innerHTML=c.length?`<table><thead><tr><th class="l">Contract</th><th>Time</th><th>Entry &rarr; exit</th><th>Exit reason</th><th>Qty</th><th>Net P&L</th><th>Return</th><th>Costs</th></tr></thead><tbody>${c.map(t=>row(t,false)).join('')}</tbody></table>`:'None.';}
$('sym').addEventListener('change',loadChain);$('side').addEventListener('change',loadChain);$('exp').addEventListener('change',()=>{fillStrikes();if($('chainbox').style.display==='block')showChain();});
$('prev').onclick=preview;$('enter').onclick=enter;$('loadchain').onclick=showChain;
loadSyms();refresh();setInterval(refresh,5000);
</script></body></html>"""
