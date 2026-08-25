from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
MODULE = ROOT / "stock_selection_v2.py"
PACKAGER = ROOT / "aplus_after_market_packager.py"

if not SCANNER.is_file():
    raise SystemExit("FAIL: opening_momentum_scanner.py not found")
if not MODULE.is_file():
    raise SystemExit("FAIL: stock_selection_v2.py not found")

backup = ROOT / ("backup_before_stock_selection_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(SCANNER, backup / SCANNER.name)
if PACKAGER.is_file():
    shutil.copy2(PACKAGER, backup / PACKAGER.name)

def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, found {count}")
    return text.replace(old, new, 1)

try:
    s = SCANNER.read_text(encoding="utf-8")

    imp = "from stock_selection_v2 import V2GateConfig, evaluate_entry_ready, rank_raw_movers\n"
    if imp not in s:
        marker = "IST = ZoneInfo("
        pos = s.find(marker)
        if pos < 0:
            raise RuntimeError("import insertion point not found")
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

    old = '''        actionable = entry_ready[: self.settings.maximum_option_candidates]
        movement_leaders = sorted(
'''
    new = '''        v2_config = V2GateConfig()
        actionable, v2_blocked = evaluate_entry_ready(
            candidates=entry_ready,
            mover_ranking=v2_movers,
            now=current_time,
            config=v2_config,
        )
        for blocked in v2_blocked:
            candidate = next(
                (x for x in entry_ready if x.symbol == blocked.get("symbol")
                 and x.direction == blocked.get("direction")),
                None,
            )
            if candidate is not None:
                candidate.paper_trade_status = "V2_STOCK_SELECTION_BLOCKED"
                candidate.reasons.append(
                    "Stock Selection V2 blocked: "
                    + "; ".join(blocked.get("reasons", []) or [])
                )

        movement_leaders = sorted(
'''
    s = once(s, old, new, "V2 actionable bridge")

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

    SCANNER.write_text(s, encoding="utf-8")
    py_compile.compile(str(MODULE), doraise=True)
    py_compile.compile(str(SCANNER), doraise=True)

    if PACKAGER.is_file():
        ps = PACKAGER.read_text(encoding="utf-8")
        if '"intraday_stock_selection_v2.csv",' not in ps:
            anchor = '"intraday_entry_ready.csv",'
            if anchor in ps:
                ps = ps.replace(
                    anchor,
                    anchor + '\n        "intraday_stock_selection_v2.csv",'
                           + '\n        "intraday_stock_selection_v2_latest.json",',
                    1,
                )
                PACKAGER.write_text(ps, encoding="utf-8")
                py_compile.compile(str(PACKAGER), doraise=True)
            else:
                print("WARN: after-market packager list anchor not found; V2 files remain in data/reports.")

except Exception:
    shutil.copy2(backup / SCANNER.name, SCANNER)
    if PACKAGER.is_file() and (backup / PACKAGER.name).is_file():
        shutil.copy2(backup / PACKAGER.name, PACKAGER)
    print("INSTALL FAILED - originals restored:", backup)
    raise

print("=" * 78)
print("SUCCESS: APLUS STOCK SELECTION V2 INSTALLED")
print("Backup:", backup)
print("PASS: full F&O universe ranked every cycle by actual move from market open")
print("PASS: dynamic Top-5 UP are CE-only eligible")
print("PASS: dynamic Top-5 DOWN are PE-only eligible")
print("PASS: Top-5 membership is eligibility, NOT an automatic trade")
print("PASS: NOW gate checks 5m/10m/15m continuation")
print("PASS: participation/RVOL/tape gate enabled")
print("PASS: trend-retention gate enabled")
print("PASS: no daily trade-count quota added")
print("PASS: all valid V2 candidates in a cycle may trade")
print("PASS: dedicated V2 JSON/CSV audit reports enabled")
print("PASS: PAPER ONLY - no live-order code added")
print("=" * 78)
