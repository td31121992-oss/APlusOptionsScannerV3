"""Offline verification for live unrealized paper-trade P&L.

This verifier is intentionally read-only. It exercises the dashboard's P&L
helpers with representative OPEN/CLOSED paper trades and does not call Dhan.
"""

from aplus_live_pnl_dashboard import (
    _pnl,
    _realized_pnl,
    _return_pct,
    _unrealized_pnl,
)


def main() -> None:
    kotak = {
        "status": "OPEN",
        "entry_price": 10.60,
        "last_option_price": 10.45,
        "quantity": 200,
        "capital_deployed": 2120,
    }
    assert round(_unrealized_pnl(kotak), 2) == -30.0
    assert round(_pnl(kotak), 2) == -30.0
    assert round(_return_pct(kotak), 4) == round(-30.0 / 2120.0 * 100.0, 4)

    kaynes = {
        "status": "OPEN",
        "entry_price": 220.60,
        "last_option_price": 214.75,
        "quantity": 100,
        "capital_deployed": 22060,
    }
    assert round(_unrealized_pnl(kaynes), 2) == -585.0
    assert round(_pnl(kaynes), 2) == -585.0

    closed = {
        "status": "CLOSED",
        "entry_price": 100.0,
        "last_option_price": 110.0,
        "quantity": 10,
        "net_pnl": 100.0,
        "return_percent": 5.0,
    }
    assert round(_realized_pnl(closed), 2) == 100.0
    assert round(_pnl(closed), 2) == 100.0
    assert round(_return_pct(closed), 2) == 5.0

    missing_mark = {
        "status": "OPEN",
        "entry_price": 100.0,
        "quantity": 10,
        "capital_deployed": 1000,
    }
    assert round(_unrealized_pnl(missing_mark), 2) == 0.0
    assert round(_pnl(missing_mark), 2) == 0.0

    print("APLUS_OPEN_TRADE_PNL_OK")
    print("  - OPEN trades use latest option LTP for unrealized P&L")
    print("  - CLOSED trades continue using realized net_pnl")
    print("  - OPEN return uses unrealized P&L / capital")
    print("  - Missing marks remain safely at 0 rather than inventing P&L")


if __name__ == "__main__":
    main()
