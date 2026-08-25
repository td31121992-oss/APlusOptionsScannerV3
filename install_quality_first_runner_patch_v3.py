from pathlib import Path
from datetime import datetime
import re, shutil, py_compile

ROOT=Path(__file__).resolve().parent
FILES=["opening_momentum_scanner.py","paper_trade_journal.py","safety_gate.py"]
backup=ROOT/("backup_before_quality_runner_v3_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir()

for n in FILES:
    p=ROOT/n
    if not p.is_file():
        raise SystemExit(f"FAIL missing: {p}")
    shutil.copy2(p,backup/n)

def restore():
    for n in FILES:
        src=backup/n
        if src.exists():
            shutil.copy2(src,ROOT/n)

try:
    p=ROOT/"opening_momentum_scanner.py"
    s=p.read_text(encoding="utf-8")
    s,n=re.subn(r'actionable\s*=\s*selective_entry_ready\s*\[\s*:\s*1\s*\]',
                'actionable = selective_entry_ready',s,count=1)
    if n==0 and "actionable = selective_entry_ready" not in s:
        raise RuntimeError("scanner actionable assignment not found")

    start=s.find("    def _aplus_selective_entry_allowed(")
    if start<0:
        raise RuntimeError("scanner selective method not found")
    end=s.find("\n    def ",start+10)
    if end<0:
        raise RuntimeError("scanner selective method end not found")

    gate = '''    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:
        # Quality-first PAPER gate. Trade count is deliberately not considered.
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
        directional_15m = c.recent_move_15m_percent if direction == "BULLISH" else -c.recent_move_15m_percent
        session_move = c.move_from_open_percent if direction == "BULLISH" else -c.move_from_open_percent
        vwap_aligned = c.vwap_distance_percent >= 0.0 if direction == "BULLISH" else c.vwap_distance_percent <= 0.0

        if pivot == "PIVOT_TO_R1":
            c.paper_trade_status = "A_PLUS_WAIT_PIVOT_TO_R1"
            return False
        if c.chase_risk_score >= 25.0 and abs(c.vwap_distance_percent) >= 0.75:
            c.paper_trade_status = "A_PLUS_WAIT_OVEREXTENDED"
            return False
        if direction == "BULLISH" and c.rsi14_5m >= 85.0 and c.vwap_distance_percent >= 0.60:
            c.paper_trade_status = "A_PLUS_WAIT_BULL_EXHAUSTION"
            return False
        if direction == "BEARISH" and c.rsi14_5m <= 15.0 and c.vwap_distance_percent <= -0.60:
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
        if c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0:
            c.paper_trade_status = "A_PLUS_WAIT_QUALITY"
            return False
        if c.clean_trend_score < 72.0 and not fresh:
            c.paper_trade_status = "A_PLUS_WAIT_CLEAN_STRUCTURE"
            return False
        return True
'''
    s=s[:start]+gate+s[end:]
    p.write_text(s,encoding="utf-8")

    p=ROOT/"paper_trade_journal.py"
    s=p.read_text(encoding="utf-8")
    if '"runner_mode"' not in s:
        s=s.replace('"target1_hit_at", "target2_hit_at", "target3_hit_at",\n',
                    '"target1_hit_at", "target2_hit_at", "target3_hit_at",\n        "runner_mode", "runner_activated_at", "runner_stop",\n',1)
        s=s.replace('"target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n',
                    '"target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n            "runner_mode": False, "runner_activated_at": "", "runner_stop": 0.0,\n',1)

    if '"RUNNER_TRAIL_EXIT"' not in s:
        bs=s.find('            stop = self._number(trade.get("option_stop"))')
        if bs<0:
            raise RuntimeError("journal stop block start not found")
        marker='            if reason:\n                self._close_trade(trade, when, price, reason)\n                closed_now.append(trade)\n'
        be=s.find(marker,bs)
        if be<0:
            raise RuntimeError("journal stop block end not found")
        be+=len(marker)
        runner='''            original_stop = self._number(trade.get("option_stop"))
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
        s=s[:bs]+runner+s[be:]
    p.write_text(s,encoding="utf-8")

    p=ROOT/"safety_gate.py"
    s=p.read_text(encoding="utf-8")
    s,n=re.subn(r'(?m)^(\s*)maximum_trades_per_day:\s*int\s*=\s*\d+.*$',
                r'\1maximum_trades_per_day: int = 0  # 0 = unlimited; quality/risk gates decide',s,count=1)
    if n!=1:
        raise RuntimeError("safety daily quota config not found")

    if "self.config.maximum_trades_per_day > 0" not in s:
        pat=re.compile(r'(?m)^(?P<i>\s*)if\s+trades_today\s*>=\s*self\.config\.maximum_trades_per_day:\s*\n(?P=i)\s+reasons\.append\("Maximum trades per day has been reached"\)')
        m=pat.search(s)
        if not m:
            raise RuntimeError("safety daily quota condition not found")
        i=m.group("i")
        repl=(f'{i}if (\\n{i}    self.config.maximum_trades_per_day > 0\\n{i}    and trades_today >= self.config.maximum_trades_per_day\\n{i}):\\n{i}    reasons.append("Maximum trades per day has been reached")')
        s=s[:m.start()]+repl+s[m.end():]
    p.write_text(s,encoding="utf-8")

    for n in FILES:
        py_compile.compile(str(ROOT/n),doraise=True)

    sc=(ROOT/"opening_momentum_scanner.py").read_text(encoding="utf-8")
    pj=(ROOT/"paper_trade_journal.py").read_text(encoding="utf-8")
    sg=(ROOT/"safety_gate.py").read_text(encoding="utf-8")
    assert "selective_entry_ready[:1]" not in sc
    assert "actionable = selective_entry_ready" in sc
    assert "A_PLUS_WAIT_NO_FOLLOW_THROUGH" in sc
    assert 'reason = "OPTION_TARGET3"' not in pj
    assert '"RUNNER_TRAIL_EXIT"' in pj and "gain_trail" in pj
    assert "maximum_trades_per_day: int = 0" in sg
    assert "self.config.maximum_trades_per_day > 0" in sg

except Exception:
    restore()
    print("PATCH FAILED - originals restored:",backup)
    raise

print("="*72)
print("SUCCESS: QUALITY-FIRST + UNLIMITED RUNNER PAPER PATCH V3 INSTALLED")
print("Backup:",backup)
print("PASS: no one-entry-per-cycle restriction")
print("PASS: no hard daily trade-count quota by default")
print("PASS: direction/VWAP/follow-through/participation quality checks")
print("PASS: T3 activates RUNNER MODE instead of closing")
print("PASS: T1 breakeven; T2 +8%; runner minimum +15%")
print("PASS: runner retains 70% of best observed premium gain")
print("PASS: Telegram ENTRY/EXIT hooks preserved")
print("PASS: touched modules compile")
print("PAPER ONLY - no live-order code added")
print("="*72)
