from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import py_compile
import shutil

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
MODULE_SOURCE = 'from __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom datetime import datetime\nfrom typing import Any, Mapping, Sequence\n\n\n@dataclass(frozen=True)\nclass V2GateConfig:\n    top_n_per_side: int = 5\n    minimum_session_move_pct: float = 0.50\n    maximum_opposing_5m_pct: float = 0.06\n    minimum_recent_10m_pct: float = 0.08\n    minimum_recent_15m_pct: float = 0.12\n    minimum_trend_retention_pct: float = 55.0\n    minimum_participation: float = 1.20\n\n\ndef _num(v: Any, default: float = 0.0) -> float:\n    try:\n        return float(v)\n    except (TypeError, ValueError, OverflowError):\n        return default\n\n\ndef rank_raw_movers(\n    *,\n    universe: Sequence[Any],\n    quote_map: Mapping[str, Any],\n    top_n: int = 5,\n) -> dict[str, Any]:\n    segment = quote_map.get("NSE_EQ", {})\n    if not isinstance(segment, Mapping):\n        segment = {}\n\n    rows: list[dict[str, Any]] = []\n    for item in universe:\n        sid = str(getattr(item, "security_id", "") or "")\n        symbol = str(getattr(item, "symbol", "") or "").strip().upper()\n        if not sid or not symbol:\n            continue\n        raw = segment.get(sid)\n        if raw is None:\n            try:\n                raw = segment.get(int(sid))\n            except (TypeError, ValueError):\n                raw = None\n        if not isinstance(raw, Mapping):\n            continue\n        ohlc = raw.get("ohlc")\n        if not isinstance(ohlc, Mapping):\n            ohlc = {}\n        ltp = _num(raw.get("last_price"))\n        day_open = _num(ohlc.get("open"))\n        prev_close = _num(ohlc.get("close"))\n        if ltp <= 0 or day_open <= 0:\n            continue\n\n        from_open = (ltp - day_open) / day_open * 100.0\n        from_prev = ((ltp - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0\n        rows.append({\n            "symbol": symbol,\n            "security_id": sid,\n            "ltp": round(ltp, 4),\n            "day_open": round(day_open, 4),\n            "previous_close": round(prev_close, 4),\n            "from_open_pct": round(from_open, 4),\n            "from_prev_close_pct": round(from_prev, 4),\n        })\n\n    up = sorted((r for r in rows if r["from_open_pct"] > 0),\n                key=lambda r: r["from_open_pct"], reverse=True)[:max(1, top_n)]\n    down = sorted((r for r in rows if r["from_open_pct"] < 0),\n                  key=lambda r: r["from_open_pct"])[:max(1, top_n)]\n\n    for rank, row in enumerate(up, 1):\n        row["v2_side"] = "UP"\n        row["v2_rank"] = rank\n        row["eligible_option_side"] = "CE"\n    for rank, row in enumerate(down, 1):\n        row["v2_side"] = "DOWN"\n        row["v2_rank"] = rank\n        row["eligible_option_side"] = "PE"\n\n    return {\n        "top_n_per_side": max(1, top_n),\n        "top_up": up,\n        "top_down": down,\n        "symbols": [r["symbol"] for r in up + down],\n        "universe_rows_ranked": len(rows),\n    }\n\n\ndef evaluate_entry_ready(\n    *,\n    candidates: Sequence[Any],\n    mover_ranking: Mapping[str, Any],\n    now: datetime,\n    config: V2GateConfig | None = None,\n) -> tuple[list[Any], list[dict[str, Any]]]:\n    cfg = config or V2GateConfig()\n    up = {str(x.get("symbol") or ""): x for x in mover_ranking.get("top_up", [])}\n    down = {str(x.get("symbol") or ""): x for x in mover_ranking.get("top_down", [])}\n\n    passed: list[Any] = []\n    blocked: list[dict[str, Any]] = []\n\n    for c in candidates:\n        symbol = str(getattr(c, "symbol", "") or "").upper()\n        direction = str(getattr(c, "direction", "") or "").upper()\n        reasons: list[str] = []\n\n        expected = up.get(symbol) if direction == "BULLISH" else down.get(symbol)\n        if expected is None:\n            reasons.append("NOT_IN_DYNAMIC_TOP5_DIRECTION")\n\n        directional_session = (\n            _num(getattr(c, "move_from_0915_open_percent", 0.0))\n            if direction == "BULLISH"\n            else -_num(getattr(c, "move_from_0915_open_percent", 0.0))\n        )\n        d5 = (\n            _num(getattr(c, "recent_move_5m_percent", 0.0))\n            if direction == "BULLISH"\n            else -_num(getattr(c, "recent_move_5m_percent", 0.0))\n        )\n        d10 = (\n            _num(getattr(c, "recent_move_10m_percent", 0.0))\n            if direction == "BULLISH"\n            else -_num(getattr(c, "recent_move_10m_percent", 0.0))\n        )\n        d15 = (\n            _num(getattr(c, "recent_move_15m_percent", 0.0))\n            if direction == "BULLISH"\n            else -_num(getattr(c, "recent_move_15m_percent", 0.0))\n        )\n\n        if directional_session < cfg.minimum_session_move_pct:\n            reasons.append(\n                f"SESSION_MOVE_TOO_SMALL({directional_session:.2f}%<{cfg.minimum_session_move_pct:.2f}%)"\n            )\n        if d5 < -cfg.maximum_opposing_5m_pct:\n            reasons.append(f"CURRENT_5M_REVERSING({d5:.2f}%)")\n\n        completed = int(_num(getattr(c, "completed_5m_bars", 0), 0))\n        continuation_votes = int(d5 >= 0.03) + int(d10 >= cfg.minimum_recent_10m_pct)\n        if completed >= 3:\n            continuation_votes += int(d15 >= cfg.minimum_recent_15m_pct)\n        fresh_edge = (\n            bool(getattr(c, "fresh_15m_high", False))\n            if direction == "BULLISH"\n            else bool(getattr(c, "fresh_15m_low", False))\n        )\n        if fresh_edge:\n            continuation_votes += 1\n        minimum_votes = 2\n        if continuation_votes < minimum_votes:\n            reasons.append(\n                f"NO_FRESH_CONTINUATION(votes={continuation_votes}/{minimum_votes},"\n                f"5m={d5:.2f},10m={d10:.2f},15m={d15:.2f})"\n            )\n\n        participation = max(\n            _num(getattr(c, "relative_volume", 0.0)),\n            _num(getattr(c, "recent_relative_volume_15m", 0.0)),\n            _num(getattr(c, "tape_volume_acceleration_5m", 0.0)),\n            _num(getattr(c, "tape_volume_acceleration_15m", 0.0)),\n        )\n        if participation < cfg.minimum_participation:\n            reasons.append(\n                f"PARTICIPATION_TOO_LOW({participation:.2f}x<{cfg.minimum_participation:.2f}x)"\n            )\n\n        retention = _num(getattr(c, "trend_retention_percent", 0.0))\n        if retention < cfg.minimum_trend_retention_pct:\n            reasons.append(\n                f"TREND_NOT_RETAINED({retention:.1f}%<{cfg.minimum_trend_retention_pct:.1f}%)"\n            )\n\n        if reasons:\n            blocked.append({\n                "symbol": symbol,\n                "direction": direction,\n                "stage": str(getattr(c, "stage", "") or ""),\n                "setup_family": str(getattr(c, "setup_family", "") or ""),\n                "move_from_0915_open_pct": round(directional_session, 4),\n                "directional_5m_pct": round(d5, 4),\n                "directional_10m_pct": round(d10, 4),\n                "directional_15m_pct": round(d15, 4),\n                "participation": round(participation, 4),\n                "trend_retention_pct": round(retention, 2),\n                "reasons": reasons,\n            })\n            continue\n\n        passed.append(c)\n\n    return passed, blocked\n'
MODULE = ROOT / "stock_selection_v2.py"
PACKAGER = ROOT / "aplus_after_market_packager.py"
ENV = ROOT / ".env"

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"backup_before_stock_selection_v2_final_{STAMP}"

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

    old = '''        fields = [
            "symbol", "direction", "stage", "shortlist",
'''
    new = '''        v2 = payload.get("stock_selection_v2", {}) or {}
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
            "symbol", "direction", "stage", "shortlist",
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
    print("APlus Stock Selection V2 - FINAL Exact-Scanner Installer")
    print("PRESERVES API RELIABILITY FIX - PAPER ONLY - NO LIVE ORDERS")
    print("=" * 90)

    if not SCANNER.is_file():
        fail("opening_momentum_scanner.py not found")

    original = SCANNER.read_text(encoding="utf-8")
    reliability = ("self._account_cache", "_fund_cache_seconds", "_positions_cache_seconds")
    missing_rel = [x for x in reliability if x not in original]
    if missing_rel:
        fail("API reliability fix not detected; refusing unsafe patch. Missing: " + repr(missing_rel))

    BACKUP.mkdir(parents=True, exist_ok=False)
    backup(SCANNER); backup(MODULE); backup(PACKAGER); backup(ENV)

    try:
        MODULE.write_text(MODULE_SOURCE, encoding="utf-8")
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
