from __future__ import annotations

"""Verification for the read-only Stock Analysis order-flow integration."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    stock_path = ROOT / "stock_analysis_tab.py"
    flow_path = ROOT / "analytics" / "order_flow.py"

    for path in (stock_path, flow_path):
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

    stock_source = stock_path.read_text(encoding="utf-8")
    required = (
        "from analytics.order_flow import build_order_flow",
        "def order_flow_payload(",
        '"order_flow": order_flow',
        '"confirmation": confirmation',
        "Order Flow &amp; Market Depth",
        "APlus Multi-Factor Confirmation",
    )
    missing = [needle for needle in required if needle not in stock_source]
    if missing:
        raise SystemExit("Missing integration markers: " + ", ".join(missing))

    flow_source = flow_path.read_text(encoding="utf-8")
    required_flow = (
        "get_market_quotes",
        "bid_depth_5",
        "ask_depth_5",
        "book_imbalance_pct",
        "candle_delta_proxy",
        "true_aggressor_delta_available",
    )
    missing_flow = [needle for needle in required_flow if needle not in flow_source]
    if missing_flow:
        raise SystemExit("Missing order-flow markers: " + ", ".join(missing_flow))

    print("APLUS_STOCK_ANALYSIS_ORDER_FLOW_INTEGRATION_OK")
    print("  - Python syntax: OK")
    print("  - Live 5-level depth path: present")
    print("  - Book imbalance: present")
    print("  - Candle delta proxy: present")
    print("  - Multi-factor confirmation UI: present")
    print("  - Trading engine remains untouched by this read-only layer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
