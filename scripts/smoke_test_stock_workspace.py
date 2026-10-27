"""Read-only HTTP smoke test for the unified stock workspace.

Run against an already-running local APlus dashboard:
  python scripts/smoke_test_stock_workspace.py
Optional:
  python scripts/smoke_test_stock_workspace.py --base-url http://127.0.0.1:8765 --symbol MANKIND

This script performs GET requests only. It does not call data APIs, place orders,
change configuration, or modify project files.
"""
from __future__ import annotations

import argparse
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def get_text(url: str) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "APlus-Workspace-SmokeTest/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--symbol", default="MANKIND")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    symbol = args.symbol.strip().upper()
    if not symbol or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&_-" for ch in symbol):
        parser.error("symbol must contain only letters, digits, &, _ or -")

    checks = [
        (f"{base}/stock-detail?symbol={quote(symbol)}", "APlus Stock Workspace", "unified workspace page"),
        (f"{base}/stock-chart?symbol={quote(symbol)}", "get(\"symbol\")", "chart reads the selected symbol"),
        (f"{base}/stock-analysis?symbol={quote(symbol)}", 'params.get("symbol")', "analysis reads the selected symbol"),
        (f"{base}/trade", 'data-interval="5"', "trade chart exposes timeframe controls"),
    ]
    failed = False
    for url, marker, label in checks:
        try:
            status, body = get_text(url)
            ok = status == 200 and marker in body
            print(f'{"PASS" if ok else "FAIL"}: {label} (HTTP {status})')
            if not ok:
                failed = True
            if label == "trade chart exposes timeframe controls" and ok:
                required = {
                    "stock chart on left": body.find('id="stkCard"') < body.find('id="optCard"') and 'id="stkCard"' in body and 'id="optCard"' in body,
                    "15-minute timeframe": 'data-interval="15"' in body,
                    "1-hour timeframe": 'data-interval="60"' in body,
                    "EMA 9 overlay": 'data-ind="ema9"' in body,
                    "SMA 20 overlay": 'data-ind="sma20"' in body,
                    "VWAP overlay": 'data-ind="vwap"' in body,
                    "fullscreen chart controls": "function expandCard(id)" in body,
                }
                for sublabel, subok in required.items():
                    print(f'{"PASS" if subok else "FAIL"}: {sublabel}')
                    if not subok:
                        failed = True
        except RuntimeError as exc:
            print(f"FAIL: {label} — {exc}")
            failed = True

    print()
    if failed:
        print("Smoke test failed. No files or trading settings were changed.")
        return 1
    print(f"HTTP workspace smoke test passed for {symbol}.")
    print("Note: this checks route delivery and UI wiring only; verify chart data and fullscreen resizing in the browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
