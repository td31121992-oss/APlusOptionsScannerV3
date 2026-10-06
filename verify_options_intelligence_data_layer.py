from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "options_intelligence_data_layer.py"

print("=" * 78)
print("APLUS OPTIONS INTELLIGENCE DATA LAYER VERIFY")
print("=" * 78)

py_compile.compile(str(TARGET), doraise=True)
print("PASS: collector compiles")

import options_intelligence_data_layer as mod

print("PASS: collector imports")
print(f"PASS: storage root = {mod.DATA_ROOT}")

source = TARGET.read_text(encoding="utf-8")
for marker, expected in (
    ("read_only collector marker", "Read-only collector"),
    ("option-chain client call", "client.get_option_chain"),
    ("normalized CSV schema", "option_chain_rows.csv"),
    ("raw JSONL storage", "option_chain_snapshots.jsonl"),
    ("manifest storage", "collector_manifest.json"),
):
    if expected not in source:
        raise SystemExit(f"FAIL: missing {marker}: {expected}")
    print(f"PASS: {marker}")

for forbidden in (
    "place_order(",
    "order_id",
    "cancel_order",
):
    if forbidden in source:
        raise SystemExit(f"FAIL: trading/order reference found: {forbidden}")
print("PASS: no order-placement code in collector")

print("VERIFY COMPLETE")
