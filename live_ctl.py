"""Control panel for live trading (command line only, on purpose: nothing here can be triggered from a web page).

    python live_ctl.py check [SECURITY_ID]   READ-ONLY connection test with the Dhan credentials in .env: auth, fund limits, positions, today's orders and (optionally) one option quote. Prints the raw
                                             responses so their shape can be confirmed. Places nothing.
    python live_ctl.py status                mode, armed, halted, today's live P&L and orders (from data/live/state.json)
    python live_ctl.py arm                   arm REAL orders for TODAY. Asks you to type a confirmation. Needs APLUS_LIVE_MODE=LIVE in the engine's environment as well.
    python live_ctl.py disarm                remove today's arming (the engine stops sending new orders; open positions keep their protective stops)
    python live_ctl.py kill                  create the kill-switch file: the engine sends no new orders and FLATTENS every open live position
    python live_ctl.py unkill                remove the kill-switch file
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / "data" / "control"
PHRASE = "I ACCEPT REAL ORDERS TODAY"


def cmd_check(sid: str | None) -> int:
    sys.path.insert(0, str(ROOT))
    from config import AppConfig
    from core.dhan_client import DhanClient
    from live_broker import DhanBroker

    cfg = AppConfig.from_env()
    client = DhanClient(cfg.dhan)
    print("auth ok:", client.test_connection())
    b = DhanBroker(client)
    for name, fn in (("fund limits", b.funds), ("positions (net qty by security id)", b.positions)):
        try:
            print(f"{name}:", json.dumps(fn(), default=str)[:600])
        except Exception as exc:                                    # noqa: BLE001
            print(f"{name}: FAILED {type(exc).__name__}: {exc}")
    try:
        rows = b._get_json("orders")
        print(f"today's orders: {len(rows) if isinstance(rows, list) else rows}")
        if isinstance(rows, list) and rows:
            print("first order record keys:", sorted(rows[0]))
    except Exception as exc:                                        # noqa: BLE001
        print("orders: FAILED", type(exc).__name__, exc)
        print("(an order-API failure here usually means the machine's IP is not on Dhan's static-IP whitelist, or the token has no trading permission)")
    if sid:
        try:
            print("raw quote:", json.dumps(client.get_quote(sid, "NSE_FNO"), default=str)[:800])
            print("parsed (bid, ask):", b.quote(sid))
        except Exception as exc:                                    # noqa: BLE001
            print("quote: FAILED", type(exc).__name__, exc)
    return 0


def cmd_status() -> int:
    p = ROOT / "data" / "live" / "state.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("no live state yet (engine has not run today)")
        return 0
    print(f"day {d.get('day')} mode {d.get('mode')} halted: {d.get('halted') or 'no'} updated {d.get('updated')}")
    for r in d.get("recs", {}).values():
        print(f"  {r['symbol']:28s} {r['status']:10s} qty {r['qty']:5d} entry {r['entry_price']} exit {r['exit_price']} P&L {r['realized']:+.0f} {r['reason']}")
    armed = CONTROL / "live_armed.json"
    print("armed today:", armed.exists() and json.loads(armed.read_text(encoding="utf-8")).get("date") == date.today().isoformat(), "| kill switch:", (CONTROL / "LIVE_KILL").exists())
    return 0


def cmd_arm() -> int:
    sys.path.insert(0, str(ROOT))
    from live_engine import LiveConfig

    c = LiveConfig.from_env()
    print(f"REAL orders will be sent today by the live engine if APLUS_LIVE_MODE=LIVE.\n  lots cap {c.lots_cap} | max order value {c.max_order_value:.0f} | daily loss cap {c.max_daily_loss:.0f} | stops: protective SL on every entry")
    if input(f'Type exactly "{PHRASE}" to arm: ').strip() != PHRASE:
        print("not armed")
        return 1
    CONTROL.mkdir(parents=True, exist_ok=True)
    (CONTROL / "live_armed.json").write_text(json.dumps({"date": date.today().isoformat(), "armed_at": datetime.now().isoformat(timespec="seconds"), "lots_cap": c.lots_cap,
                                                         "max_daily_loss": c.max_daily_loss}), encoding="utf-8")
    print("armed for", date.today().isoformat())
    return 0


def main() -> int:
    a = sys.argv[1:] or ["status"]
    if a[0] == "check":
        return cmd_check(a[1] if len(a) > 1 else None)
    if a[0] == "status":
        return cmd_status()
    if a[0] == "arm":
        return cmd_arm()
    if a[0] == "disarm":
        (CONTROL / "live_armed.json").unlink(missing_ok=True)
        print("disarmed")
        return 0
    if a[0] == "kill":
        CONTROL.mkdir(parents=True, exist_ok=True)
        (CONTROL / "LIVE_KILL").write_text(datetime.now().isoformat(), encoding="utf-8")
        print("KILL switch set: the engine will flatten and stop")
        return 0
    if a[0] == "unkill":
        (CONTROL / "LIVE_KILL").unlink(missing_ok=True)
        print("kill switch cleared")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
