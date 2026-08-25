from __future__ import annotations
from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT = Path(__file__).resolve().parent
FILES = ["opening_momentum_scanner.py"]
backup = ROOT / ("backup_before_late_overheat_fix_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir(parents=True, exist_ok=False)

for name in FILES:
    p = ROOT / name
    if not p.is_file():
        raise SystemExit(f"FAIL missing: {p}")
    shutil.copy2(p, backup / name)

def restore():
    for name in FILES:
        src = backup / name
        if src.exists():
            shutil.copy2(src, ROOT / name)

try:
    p = ROOT / "opening_momentum_scanner.py"
    s = p.read_text(encoding="utf-8")

    start = s.find("    def _aplus_selective_entry_allowed(")
    if start < 0:
        raise RuntimeError("selective gate method not found")
    end = s.find("\n    def ", start + 10)
    if end < 0:
        raise RuntimeError("selective gate method end not found")

    gate = '''    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:
        # Quality-first PAPER gate. Trade count is deliberately not considered.
        # Evidence update from 18-Aug: do NOT kill strong trends. Reject late,
        # overheated entries where the recent move has already stretched too far.
        direction = str(c.direction or "").upper()
        setup = str(c.setup_family or "").upper()
        pivot = str(c.pivot_state or "").upper()

        fresh = (
            c.fresh_15m_high or c.fresh_15m_low
            or c.fresh_30m_high or c.fresh_30m_low
            or c.fresh_day_high or c.fresh_day_low
            or c.opening_range_breakout
        )
        directional_5m = c.recent_move_5m_percent if direction == "BULLISH" else -c.recent_move_5m_percent
        directional_10m = c.recent_move_10m_percent if direction == "BULLISH" else -c.recent_move_10m_percent
        directional_15m = c.recent_move_15m_percent if direction == "BULLISH" else -c.recent_move_15m_percent
        session_move = c.move_from_open_percent if direction == "BULLISH" else -c.move_from_open_percent
        close_move = c.day_change_percent if direction == "BULLISH" else -c.day_change_percent
        vwap_dir = c.vwap_distance_percent if direction == "BULLISH" else -c.vwap_distance_percent
        vwap_aligned = vwap_dir >= 0.0

        if pivot == "PIVOT_TO_R1":
            c.paper_trade_status = "A_PLUS_WAIT_PIVOT_TO_R1"
            return False

        # Late-entry / overheat guard:
        # Targets trades where the immediate move already ran too far before entry.
        # Avoids killing TIINDIA-style strong trends that were not 10m-overheated.
        late_recent = directional_10m > 0.85
        late_vwap = vwap_dir > 0.87
        late_session = session_move > 2.81
        late_close = close_move > 2.96
        if late_recent:
            c.paper_trade_status = "A_PLUS_WAIT_LATE_10M_OVERHEAT"
            return False
        if late_vwap and (directional_5m > 0.25 or directional_15m > 0.45):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_VWAP_EXTENSION"
            return False
        if late_session and (directional_10m > 0.40 or late_vwap):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_SESSION_EXTENSION"
            return False
        if late_close and (directional_10m > 0.40 or late_vwap):
            c.paper_trade_status = "A_PLUS_WAIT_LATE_CLOSE_EXTENSION"
            return False

        if c.chase_risk_score >= 25.0 and abs(c.vwap_distance_percent) >= 0.75:
            c.paper_trade_status = "A_PLUS_WAIT_OVEREXTENDED"
            return False
        if direction == "BULLISH" and c.rsi14_5m >= 85.0 and c.vwap_distance_percent >= 0.60 and directional_10m > 0.85:
            c.paper_trade_status = "A_PLUS_WAIT_BULL_EXHAUSTION"
            return False
        if direction == "BEARISH" and c.rsi14_5m <= 15.0 and c.vwap_distance_percent <= -0.60 and directional_10m > 0.85:
            c.paper_trade_status = "A_PLUS_WAIT_BEAR_EXHAUSTION"
            return False
        if setup == "CLEAN_BEARISH_BREAKDOWN":
            c.paper_trade_status = "A_PLUS_WAIT_BEAR_BREAKDOWN_CONFIRM"
            return False
        if session_move <= 0.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_DIRECTION_CONFLICT"
            return False
        if not vwap_aligned and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_VWAP_ALIGNMENT"
            return False

        current_follow_through = directional_5m > 0.0 or directional_15m > 0.10
        participation = (
            c.relative_volume >= 1.0
            or c.recent_relative_volume_15m >= 1.0
            or c.tape_volume_acceleration_5m >= 1.15
            or c.tape_volume_acceleration_15m >= 1.15
        )
        if not current_follow_through and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_NO_FOLLOW_THROUGH"
            return False
        if not participation:
            c.paper_trade_status = "A_PLUS_WAIT_WEAK_PARTICIPATION"
            return False
        if c.trade_quality_score < 65.0:
            c.paper_trade_status = "A_PLUS_WAIT_QUALITY"
            return False

        # No hard alignment >=60 rejection. TIINDIA had alignment around 54.5
        # but was a clean +33.5% winner.
        if c.trend_alignment_score < 60.0 and c.clean_trend_score < 90.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_ALIGNMENT_STRUCTURE"
            return False
        if c.clean_trend_score < 72.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_CLEAN_STRUCTURE"
            return False
        return True
'''
    s = s[:start] + gate + s[end:]
    p.write_text(s, encoding="utf-8")

    py_compile.compile(str(p), doraise=True)

    sc = p.read_text(encoding="utf-8")
    assert "A_PLUS_WAIT_LATE_10M_OVERHEAT" in sc
    assert "c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0" not in sc
    assert "A_PLUS_WAIT_ALIGNMENT_STRUCTURE" in sc
    assert "PIVOT_TO_R1" in sc

except Exception:
    restore()
    print("PATCH FAILED - originals restored:", backup)
    raise

print("="*72)
print("SUCCESS: LATE-OVERHEAT FILTER PATCH INSTALLED")
print("Backup:", backup)
print("PASS: hard alignment >=60 rejection removed")
print("PASS: TIINDIA-style strong clean trend can pass even with alignment <60")
print("PASS: PIVOT_TO_R1 rejection preserved")
print("PASS: late 10m acceleration guard added")
print("PASS: VWAP/session/previous-close late extension guards added")
print("PASS: PAPER scanner module compiles")
print("PAPER ONLY - no live-order code added")
print("="*72)
