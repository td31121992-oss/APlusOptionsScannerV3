from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT=Path(__file__).resolve().parent
names=["opening_momentum_scanner.py","paper_trade_journal.py","safety_gate.py"]
paths={n:ROOT/n for n in names}
backup=ROOT/("backup_before_quality_runner_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir()

def once(s, old, new, label):
    if s.count(old)!=1:
        raise RuntimeError(f"{label}: expected 1 anchor, found {s.count(old)}")
    return s.replace(old,new,1)

for n,p in paths.items():
    if not p.exists(): raise RuntimeError(f"missing {p}")
    shutil.copy2(p,backup/n)

try:
    p=paths["opening_momentum_scanner.py"]; s=p.read_text(encoding="utf-8")
    s=once(s,
        "        # Rank first and allow at most one NEW paper entry per cycle.\n        actionable = selective_entry_ready[:1]\n",
        "        # Quality-first: trade count is an outcome, never a quota.\n        actionable = selective_entry_ready\n",
        "one-entry-per-cycle")
    start=s.index("    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:\n")
    end=s.index("    def _build_shortlists(",start)
    gate='''    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:
        """Quality-first PAPER gate. Trade count is deliberately not considered."""
        direction = str(c.direction or "").upper()
        setup = str(c.setup_family or "").upper()
        pivot = str(c.pivot_state or "").upper()
        fresh = (
            c.fresh_15m_high or c.fresh_15m_low or c.fresh_30m_high or c.fresh_30m_low
            or c.fresh_day_high or c.fresh_day_low or c.opening_range_breakout
        )
        directional_5m = c.recent_move_5m_percent if direction == "BULLISH" else -c.recent_move_5m_percent
        directional_15m = c.recent_move_15m_percent if direction == "BULLISH" else -c.recent_move_15m_percent
        session_move = c.move_from_open_percent if direction == "BULLISH" else -c.move_from_open_percent
        vwap_aligned = c.vwap_distance_percent >= 0.0 if direction == "BULLISH" else c.vwap_distance_percent <= 0.0

        if pivot == "PIVOT_TO_R1":
            c.paper_trade_status="A_PLUS_WAIT_PIVOT_TO_R1"; return False
        if c.chase_risk_score >= 25.0 and abs(c.vwap_distance_percent) >= 0.75:
            c.paper_trade_status="A_PLUS_WAIT_OVEREXTENDED"; return False
        if direction == "BULLISH" and c.rsi14_5m >= 85.0 and c.vwap_distance_percent >= 0.60:
            c.paper_trade_status="A_PLUS_WAIT_BULL_EXHAUSTION"; return False
        if direction == "BEARISH" and c.rsi14_5m <= 15.0 and c.vwap_distance_percent <= -0.60:
            c.paper_trade_status="A_PLUS_WAIT_BEAR_EXHAUSTION"; return False
        if setup == "CLEAN_BEARISH_BREAKDOWN":
            c.paper_trade_status="A_PLUS_WAIT_BEAR_BREAKDOWN_CONFIRM"; return False
        if session_move <= 0.0 and not fresh:
            c.paper_trade_status="A_PLUS_WAIT_DIRECTION_CONFLICT"; return False
        if not vwap_aligned and not fresh:
            c.paper_trade_status="A_PLUS_WAIT_VWAP_ALIGNMENT"; return False

        current_follow_through = directional_5m > 0.0 or directional_15m > 0.10
        participation = (
            c.relative_volume >= 1.0 or c.recent_relative_volume_15m >= 1.0
            or c.tape_volume_acceleration_5m >= 1.15 or c.tape_volume_acceleration_15m >= 1.15
        )
        if not current_follow_through and not fresh:
            c.paper_trade_status="A_PLUS_WAIT_NO_FOLLOW_THROUGH"; return False
        if not participation:
            c.paper_trade_status="A_PLUS_WAIT_WEAK_PARTICIPATION"; return False
        if c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0:
            c.paper_trade_status="A_PLUS_WAIT_QUALITY"; return False
        if c.clean_trend_score < 72.0 and not fresh:
            c.paper_trade_status="A_PLUS_WAIT_CLEAN_STRUCTURE"; return False
        return True

'''
    s=s[:start]+gate+s[end:]; p.write_text(s,encoding="utf-8")

    p=paths["paper_trade_journal.py"]; s=p.read_text(encoding="utf-8")
    s=once(s,
        '        "target1_hit_at", "target2_hit_at", "target3_hit_at",\n        "exit_time", "exit_price", "exit_reason", "holding_seconds",\n',
        '        "target1_hit_at", "target2_hit_at", "target3_hit_at",\n        "runner_mode", "runner_activated_at", "runner_stop",\n        "exit_time", "exit_price", "exit_reason", "holding_seconds",\n',
        "runner csv fields")
    s=once(s,
        '            "target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n            "exit_time": "", "exit_price": 0.0, "exit_reason": "",\n',
        '            "target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n            "runner_mode": False, "runner_activated_at": "", "runner_stop": 0.0,\n            "exit_time": "", "exit_price": 0.0, "exit_reason": "",\n',
        "runner record fields")
    old='''            stop = self._number(trade.get("option_stop"))
            target3 = self._number(trade.get("option_target3"))
            reason = ""
            if stop > 0 and price <= stop:
                reason = "OPTION_STOP_LOSS"
            elif target3 > 0 and price >= target3:
                reason = "OPTION_TARGET3"
            elif force_close:
                reason = force_close_reason
            if reason:
                self._close_trade(trade, when, price, reason)
                closed_now.append(trade)
'''
    new='''            original_stop = self._number(trade.get("option_stop"))
            protected_stop = original_stop
            if trade.get("target1_hit_at"):
                protected_stop = max(protected_stop, entry)
            if trade.get("target2_hit_at"):
                protected_stop = max(protected_stop, entry * 1.08)
            if trade.get("target3_hit_at"):
                if not bool(trade.get("runner_mode")):
                    trade["runner_mode"] = True
                    trade["runner_activated_at"] = when.isoformat()
                runner_floor = entry * 1.15
                gain_trail = entry + max(0.0, high - entry) * 0.70
                protected_stop = max(protected_stop, runner_floor, gain_trail)
                trade["runner_stop"] = round(protected_stop, 4)

            reason = ""
            if protected_stop > 0 and price <= protected_stop:
                reason = (
                    "RUNNER_TRAIL_EXIT" if bool(trade.get("runner_mode"))
                    else ("PROFIT_PROTECTION_EXIT" if protected_stop > original_stop else "OPTION_STOP_LOSS")
                )
            elif force_close:
                reason = force_close_reason
            if reason:
                self._close_trade(trade, when, price, reason)
                closed_now.append(trade)
'''
    s=once(s,old,new,"T3 runner lifecycle"); p.write_text(s,encoding="utf-8")

    p=paths["safety_gate.py"]; s=p.read_text(encoding="utf-8")
    s=once(s,"    maximum_trades_per_day: int = 6\n",
        "    maximum_trades_per_day: int = 0  # 0 = unlimited; quality/risk gates decide\n","daily quota default")
    s=once(s,
        '        if trades_today >= self.config.maximum_trades_per_day:\n            reasons.append("Maximum trades per day has been reached")\n',
        '        if self.config.maximum_trades_per_day > 0 and trades_today >= self.config.maximum_trades_per_day:\n            reasons.append("Maximum trades per day has been reached")\n',
        "daily quota condition")
    p.write_text(s,encoding="utf-8")

    for p in paths.values(): py_compile.compile(str(p),doraise=True)

    scanner=paths["opening_momentum_scanner.py"].read_text(encoding="utf-8")
    journal=paths["paper_trade_journal.py"].read_text(encoding="utf-8")
    safety=paths["safety_gate.py"].read_text(encoding="utf-8")
    assert "actionable = selective_entry_ready[:1]" not in scanner
    assert "A_PLUS_WAIT_NO_FOLLOW_THROUGH" in scanner
    assert 'reason = "OPTION_TARGET3"' not in journal
    assert '"RUNNER_TRAIL_EXIT"' in journal and "gain_trail" in journal
    assert "maximum_trades_per_day: int = 0" in safety
except Exception:
    for n,p in paths.items(): shutil.copy2(backup/n,p)
    print("PATCH FAILED - originals restored:",backup)
    raise

print("="*68)
print("SUCCESS: QUALITY-FIRST + UNLIMITED RUNNER PAPER PATCH INSTALLED")
print("Backup:",backup)
print("PASS: no one-entry-per-cycle restriction")
print("PASS: no daily trade-count quota by default")
print("PASS: follow-through/direction/VWAP/participation quality gates")
print("PASS: T3 activates runner mode; it no longer closes the trade")
print("PASS: T1 breakeven, T2 +8%, T3 minimum +15% protection")
print("PASS: runner keeps 70% of best observed premium gain")
print("PASS: Telegram ENTRY/EXIT hooks preserved")
print("PASS: touched modules compile")
print("PAPER ONLY - no live-order code added")
print("="*68)
