from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parent
required=["option_impact.py","stock_analysis_tab.py"]
for name in required:
    path=ROOT/name
    if not path.is_file():
        raise SystemExit(f"MISSING {name}")
    ast.parse(path.read_text(encoding="utf-8"),filename=name)

text=(ROOT/"stock_analysis_tab.py").read_text(encoding="utf-8")
checks=[
    'from option_impact import build_option_impact',
    '"option_impact": option_impact',
    '"previous_close": round(_f(raw.get("previous_close_price")), 2)',
    '"all_rows": rows',
    'id="optionImpact"',
]
for marker in checks:
    if marker not in text:
        raise SystemExit(f"MISSING MARKER: {marker}")
opt=(ROOT/"option_impact.py").read_text(encoding="utf-8")
for marker in ['previous_close','premium_change_pct','day_high','high_time','day_low','low_time','oi_change','trading_engine_untouched']:
    if marker not in opt:
        raise SystemExit(f"MISSING OPTION MARKER: {marker}")
print("APLUS_OPTION_IMPACT_STATIC_OK")
