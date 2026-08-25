from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
import py_compile

from stock_selection_v2 import V2GateConfig, evaluate_entry_ready, rank_raw_movers

ROOT = Path(__file__).resolve().parent
scanner = ROOT / "opening_momentum_scanner.py"
py_compile.compile(str(scanner), doraise=True)

src = scanner.read_text(encoding="utf-8")
required = [
    "rank_raw_movers(",
    "forced_symbols=v2_mover_symbols",
    "evaluate_entry_ready(",
    '"stock_selection_v2": {',
    "intraday_stock_selection_v2_latest.json",
    "intraday_stock_selection_v2.csv",
]
missing = [x for x in required if x not in src]
if missing:
    raise SystemExit("VERIFY FAIL: scanner anchors missing: " + repr(missing))

class U:
    def __init__(self, symbol, security_id):
        self.symbol = symbol
        self.security_id = security_id

universe = [U("UP1","1"), U("UP2","2"), U("DN1","3"), U("DN2","4"), U("FLAT","5")]
quotes = {"NSE_EQ": {
    "1":{"last_price":110,"ohlc":{"open":100,"close":101}},
    "2":{"last_price":105,"ohlc":{"open":100,"close":100}},
    "3":{"last_price":90,"ohlc":{"open":100,"close":99}},
    "4":{"last_price":95,"ohlc":{"open":100,"close":100}},
    "5":{"last_price":100,"ohlc":{"open":100,"close":100}},
}}
ranking = rank_raw_movers(universe=universe, quote_map=quotes, top_n=1)
assert ranking["top_up"][0]["symbol"] == "UP1"
assert ranking["top_down"][0]["symbol"] == "DN1"

good = SimpleNamespace(
    symbol="UP1", direction="BULLISH", stage="TEST", setup_family="TEST",
    move_from_0915_open_percent=2.0, recent_move_5m_percent=0.20,
    recent_move_10m_percent=0.25, recent_move_15m_percent=0.30,
    completed_5m_bars=4, fresh_15m_high=True, fresh_15m_low=False,
    relative_volume=1.5, recent_relative_volume_15m=1.3,
    tape_volume_acceleration_5m=1.4, tape_volume_acceleration_15m=1.2,
    trend_retention_percent=85.0,
)
bad_not_top5 = SimpleNamespace(**{**good.__dict__, "symbol":"UP2"})
bad_reverse = SimpleNamespace(**{**good.__dict__, "recent_move_5m_percent":-0.20})

passed, blocked = evaluate_entry_ready(
    candidates=[good, bad_not_top5, bad_reverse],
    mover_ranking=ranking,
    now=datetime.now(ZoneInfo("Asia/Kolkata")),
    config=V2GateConfig(top_n_per_side=1),
)
assert [x.symbol for x in passed] == ["UP1"]
assert len(blocked) == 2

print("=" * 78)
print("APLUS STOCK SELECTION V2 VERIFY: OK")
print("PASS: dynamic top-mover ranking")
print("PASS: direction-specific CE/PE eligibility")
print("PASS: non-Top5 candidate rejected")
print("PASS: current reversal rejected")
print("PASS: scanner compiles")
print("PAPER ONLY")
print("=" * 78)
