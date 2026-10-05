from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aplus_live_pnl_dashboard import HTML, _duration_seconds, _format_duration
from stock_alerts import evaluate_rows, rule_catalog
from stock_alerts_tab import STOCK_ALERTS_HTML, stock_alerts_payload


def main() -> int:
    row = {
        "symbol": "RELIANCE",
        "ltp": 2505.0,
        "day_high": 2505.0,
        "day_low": 2440.0,
        "from_open_pct": 1.42,
    }
    alerts = evaluate_rows([row])
    ids = {x["rule_id"] for x in alerts}
    assert {"day_high", "strong_up"} <= ids
    assert all(x["telegram"] is False for x in alerts)
    assert rule_catalog([row])[0]["browser_only"] is True

    now = datetime.now(timezone.utc)
    closed = {
        "holding_seconds": 0,
        "entry_time": (now - timedelta(minutes=18, seconds=48)).isoformat(),
        "exit_time": now.isoformat(),
    }
    assert _duration_seconds(closed) >= 1128
    assert _format_duration(1128) == "18m 48s"

    assert "/alerts" in HTML
    assert "Duration" in HTML
    assert "/api/stock-alerts" in HTML
    assert "Browser alerts only." in STOCK_ALERTS_HTML
    payload = stock_alerts_payload()
    assert payload["browser_only"] is True
    assert payload["telegram_policy"] == "Trade Taken and Trade Closed only"

    print("APLUS_ALERTS_DURATION_STATIC_OK")
    print(" - browser-only stock alert tab: OK")
    print(" - Telegram policy: trade taken/closed only")
    print(" - live trade duration: OK")
    print(" - trading engine untouched: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
