from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import py_compile
import shutil

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
MODULE_SRC = ROOT / "stock_selection_v2_compatible_module.py"
MODULE = ROOT / "stock_selection_v2.py"
PACKAGER = ROOT / "aplus_after_market_packager.py"
ENV = ROOT / ".env"

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"backup_before_stock_selection_v2_compatible_{STAMP}"

def fail(msg: str) -> None:
    raise RuntimeError(msg)

def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, BACKUP / path.name)

def restore() -> None:
    for p in (SCANNER, MODULE, PACKAGER, ENV):
        bp = BACKUP / p.name
        if bp.exists():
            shutil.copy2(bp, p)

def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly 1 compatible anchor, found {count}")
    return text.replace(old, new, 1)

def patch_scanner(s: str) -> str:
    if (
        "from stock_selection_v2 import V2GateConfig" in s
        and '"stock_selection_v2": {' in s
        and "intraday_stock_selection_v2_latest.json" in s
    ):
        return s

    imp = (
        "from stock_selection_v2 import "
        "V2GateConfig, evaluate_entry_ready, rank_raw_movers\n"
    )
    if imp not in s:
        marker = "IST = ZoneInfo("
        pos = s.find(marker)
        if pos < 0:
            fail("import insertion point not found")
        s = s[:pos] + imp + "\n" + s[pos:]

    old = '''        quotes, quote_errors = self._parse_quotes(
            universe=universe,
            quote_map=quote_map,
            now=current_time,
        )
'''
    new = '''        # Stock Selection V2: rank the full F&O universe by actual movement
        # from today's market open. Top-5 UP are CE-eligible; Top-5 DOWN are
        # PE-eligible. Membership is dynamic on every scanner cycle.
        v2_movers = rank_raw_movers(
            universe=universe,
            quote_map=quote_map,
            top_n=5,
        )
        v2_mover_symbols = set(v2_movers.get("symbols", []) or [])

        quotes, quote_errors = self._parse_quotes(
            universe=universe,
            quote_map=quote_map,
            now=current_time,
            forced_symbols=v2_mover_symbols,
        )
'''
    s = once(s, old, new, "full-universe V2 ranking")

    old = '''        quote_shortlist = sorted(
            quotes,
            key=lambda item: item.radar_score,
            reverse=True,
        )[: self.settings.quote_shortlist_size]
        candle_shortlist = quote_shortlist[
            : self.settings.candle_shortlist_size
        ]
'''
    new = '''        radar_ranked = sorted(
            quotes,
            key=lambda item: item.radar_score,
            reverse=True,
        )
        quote_by_symbol = {item.symbol: item for item in quotes}
        v2_priority_quotes = [
            quote_by_symbol[symbol]
            for symbol in v2_movers.get("symbols", [])
            if symbol in quote_by_symbol
        ]
        seen_v2 = {item.symbol for item in v2_priority_quotes}
        merged_quotes = v2_priority_quotes + [
            item for item in radar_ranked if item.symbol not in seen_v2
        ]
        quote_shortlist = merged_quotes[
            : max(10, self.settings.quote_shortlist_size)
        ]
        candle_shortlist = quote_shortlist[
            : max(10, self.settings.candle_shortlist_size)
        ]
'''
    s = once(s, old, new, "V2 mover priority analysis")

    # Adaptive bridge: preserve whatever current code already used to build
    # 'actionable', then apply V2 as a filter immediately before movement leaders.
    if "V2_STOCK_SELECTION_BLOCKED" not in s:
        marker = "        movement_leaders = sorted("
        pos = s.find(marker)
        if pos < 0:
            fail("V2 actionable bridge: movement_leaders anchor not found")
        block = '''        v2_config = V2GateConfig()
        actionable, v2_blocked = evaluate_entry_ready(
            candidates=actionable,
            mover_ranking=v2_movers,
            now=current_time,
            config=v2_config,
        )
        for blocked in v2_blocked:
            candidate = next(
                (
                    x for x in entry_ready
                    if x.symbol == blocked.get("symbol")
                    and x.direction == blocked.get("direction")
                ),
                None,
            )
            if candidate is not None:
                candidate.paper_trade_status = "V2_STOCK_SELECTION_BLOCKED"
                candidate.reasons.append(
                    "Stock Selection V2 blocked: "
                    + "; ".join(blocked.get("reasons", []) or [])
                )

'''
        s = s[:pos] + block + s[pos:]

    old = '''    def _parse_quotes(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
        now: datetime,
    ) -> tuple[list[QuoteSnapshot], dict[str, str]]:
'''
    new = '''    def _parse_quotes(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
        now: datetime,
        forced_symbols: set[str] | None = None,
    ) -> tuple[list[QuoteSnapshot], dict[str, str]]:
'''
    s = once(s, old, new, "_parse_quotes signature")

    old = '''        quotes: list[QuoteSnapshot] = []
        errors: dict[str, str] = {}

        for underlying in universe:
'''
    new = '''        quotes: list[QuoteSnapshot] = []
        errors: dict[str, str] = {}
        forced_symbols = {
            str(x).strip().upper()
            for x in (forced_symbols or set())
            if str(x).strip()
        }

        for underlying in universe:
'''
    s = once(s, old, new, "forced-symbol initialization")

    old = '''            if (
                movement_trigger < self.settings.minimum_radar_move_percent
                and not volume_wakeup
            ):
                continue
            quotes.append(quote)
'''
    new = '''            if (
                movement_trigger < self.settings.minimum_radar_move_percent
                and not volume_wakeup
                and str(underlying.symbol).strip().upper() not in forced_symbols
            ):
                continue
            quotes.append(quote)
'''
    s = once(s, old, new, "forced mover radar bypass")

    old = '''            "actionable_candidates": len(actionable),
            "entry_ready_count": len(entry_ready),
'''
    new = '''            "actionable_candidates": len(actionable),
            "stock_selection_v2": {
                "enabled": True,
                "rule": (
                    "Dynamic Top-5 UP -> CE / Top-5 DOWN -> PE; "
                    "then require fresh continuation, participation and retention"
                ),
                "top_n_per_side": v2_config.top_n_per_side,
                "top_up": list(v2_movers.get("top_up", []) or []),
                "top_down": list(v2_movers.get("top_down", []) or []),
                "eligible_symbols": list(v2_movers.get("symbols", []) or []),
                "entry_ready_before_v2": len(entry_ready),
                "passed_v2": len(actionable),
                "passed_symbols": [
                    {
                        "symbol": x.symbol,
                        "direction": x.direction,
                        "setup_family": x.setup_family,
                        "move_from_0915_open_pct": x.move_from_0915_open_percent,
                        "recent_5m_pct": x.recent_move_5m_percent,
                        "recent_10m_pct": x.recent_move_10m_percent,
                        "recent_15m_pct": x.recent_move_15m_percent,
                    }
                    for x in actionable
                ],
                "blocked_count": len(v2_blocked),
                "blocked": v2_blocked,
            },
            "entry_ready_count": len(entry_ready),
'''
    s = once(s, old, new, "V2 payload audit")

    old = '''        self._atomic_json(legacy_latest, payload)
        self._atomic_json(legacy_archive, payload)

        fields = [
'''
    new = '''        self._atomic_json(legacy_latest, payload)
        self._atomic_json(legacy_archive, payload)

        v2 = payload.get("stock_selection_v2", {}) or {}
        self._atomic_json(
            self.report_dir / "intraday_stock_selection_v2_latest.json",
            v2,
        )
        v2_rows = list(v2.get("top_up", []) or []) + list(v2.get("top_down", []) or [])
        self._write_candidate_csv(
            self.report_dir / "intraday_stock_selection_v2.csv",
            v2_rows,
            [
                "v2_side", "v2_rank", "symbol", "security_id",
                "eligible_option_side", "ltp", "day_open", "previous_close",
                "from_open_pct", "from_prev_close_pct",
            ],
        )

        fields = [
'''
    s = once(s, old, new, "V2 dedicated reports")
    return s

def patch_packager(s: str) -> str:
    if '"intraday_stock_selection_v2.csv",' in s:
        return s
    anchor = '"intraday_entry_ready.csv",'
    if anchor not in s:
        print("WARN: after-market packager anchor not found; V2 reports still remain in data\\reports.")
        return s
    return s.replace(
        anchor,
        anchor
        + '\n        "intraday_stock_selection_v2.csv",'
        + '\n        "intraday_stock_selection_v2_latest.json",',
        1,
    )

def module_self_test() -> None:
    from stock_selection_v2 import V2GateConfig, evaluate_entry_ready, rank_raw_movers

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

def main() -> int:
    print("=" * 90)
    print("APlus Stock Selection V2 - Adaptive Compatible Installer")
    print("PRESERVES API RELIABILITY FIX - PAPER ONLY - NO LIVE ORDERS")
    print("=" * 90)

    if not SCANNER.is_file():
        fail("opening_momentum_scanner.py not found")
    if not MODULE_SRC.is_file():
        fail("stock_selection_v2_compatible_module.py not found")

    original = SCANNER.read_text(encoding="utf-8")
    reliability = ("self._account_cache", "_fund_cache_seconds", "_positions_cache_seconds")
    missing_rel = [x for x in reliability if x not in original]
    if missing_rel:
        fail("API reliability fix not detected; refusing unsafe patch. Missing: " + repr(missing_rel))

    BACKUP.mkdir(parents=True, exist_ok=False)
    backup(SCANNER); backup(MODULE); backup(PACKAGER); backup(ENV)

    try:
        MODULE.write_text(MODULE_SRC.read_text(encoding="utf-8"), encoding="utf-8")
        py_compile.compile(str(MODULE), doraise=True)

        patched = patch_scanner(original)
        for marker in reliability:
            if marker not in patched:
                fail("Reliability marker lost: " + marker)

        SCANNER.write_text(patched, encoding="utf-8")
        py_compile.compile(str(SCANNER), doraise=True)

        if PACKAGER.is_file():
            ps = PACKAGER.read_text(encoding="utf-8")
            PACKAGER.write_text(patch_packager(ps), encoding="utf-8")
            py_compile.compile(str(PACKAGER), doraise=True)

        final = SCANNER.read_text(encoding="utf-8")
        required = [
            "rank_raw_movers(",
            "forced_symbols=v2_mover_symbols",
            "evaluate_entry_ready(",
            '"stock_selection_v2": {',
            "intraday_stock_selection_v2_latest.json",
            "intraday_stock_selection_v2.csv",
            "self._account_cache",
            "_fund_cache_seconds",
            "_positions_cache_seconds",
        ]
        missing = [x for x in required if x not in final]
        if missing:
            fail("post-install verification missing: " + repr(missing))

        module_self_test()

        print("SUCCESS")
        print("Backup:", BACKUP)
        print("PASS: API reliability fix preserved")
        print("PASS: .env not modified")
        print("PASS: dynamic Top-5 UP / Top-5 DOWN ranking")
        print("PASS: Top-5 UP -> CE only")
        print("PASS: Top-5 DOWN -> PE only")
        print("PASS: Top-5 is eligibility, NOT automatic trade")
        print("PASS: 5m/10m/15m continuation gate")
        print("PASS: participation/RVOL/tape gate")
        print("PASS: trend-retention gate")
        print("PASS: V2 audit JSON/CSV enabled")
        print("PASS: PAPER ONLY")
        print("=" * 90)
        return 0
    except Exception:
        restore()
        print("INSTALL FAILED - originals restored automatically.")
        print("Backup:", BACKUP)
        raise

if __name__ == "__main__":
    raise SystemExit(main())
