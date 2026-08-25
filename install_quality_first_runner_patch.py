from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT=Path(__file__).resolve().parent
FILES=["opening_momentum_scanner.py","paper_trade_journal.py","safety_gate.py"]
missing=[f for f in FILES if not (ROOT/f).is_file()]
if missing: raise SystemExit("FAIL missing: "+", ".join(missing))
backup=ROOT/("backup_before_quality_runner_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir()
for f in FILES: shutil.copy2(ROOT/f,backup/f)

try:
    p=ROOT/"safety_gate.py"; s=p.read_text(encoding="utf-8")
    s=s.replace("maximum_trades_per_day: int = 6","maximum_trades_per_day: int = 0")
    s=s.replace("maximum_trades_per_day: int = 3","maximum_trades_per_day: int = 0")
    p.write_text(s,encoding="utf-8")

    p=ROOT/"opening_momentum_scanner.py"; s=p.read_text(encoding="utf-8")
    s=s.replace("actionable = selective_entry_ready[:1]",
                "actionable = selective_entry_ready[: self.settings.maximum_option_candidates]")

    anchor = '        if c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0:\n            c.paper_trade_status="A_PLUS_WAIT_QUALITY"\n            return False\n'
    addition = '''        intraday_conflict = (
            (direction == "BULLISH" and c.move_from_open_percent < -0.10)
            or (direction == "BEARISH" and c.move_from_open_percent > 0.10)
        )
        if intraday_conflict and not fresh_trigger:
            c.paper_trade_status = "A_PLUS_WAIT_INTRADAY_CONFLICT"
            return False

        if setup == "CONTINUATION_BREAKOUT":
            signed_15m = c.recent_move_15m_percent if direction == "BULLISH" else -c.recent_move_15m_percent
            has_follow_through = (
                signed_15m >= 0.15
                or fresh_trigger
                or c.recent_relative_volume_15m >= 1.20
            )
            if not has_follow_through:
                c.paper_trade_status = "A_PLUS_WAIT_NO_FOLLOW_THROUGH"
                return False
            if c.clean_trend_score < 88.0:
                c.paper_trade_status = "A_PLUS_WAIT_STRUCTURE_QUALITY"
                return False

        if c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0:
            c.paper_trade_status="A_PLUS_WAIT_QUALITY"
            return False
'''
    if "A_PLUS_WAIT_NO_FOLLOW_THROUGH" not in s:
        if anchor not in s: raise RuntimeError("selective gate anchor not found")
        s=s.replace(anchor,addition,1)
    p.write_text(s,encoding="utf-8")

    p=ROOT/"paper_trade_journal.py"; s=p.read_text(encoding="utf-8")
    old = '''            stop = self._number(trade.get("option_stop"))
            target3 = self._number(trade.get("option_target3"))
            reason = ""
            if stop > 0 and price <= stop:
                reason = "OPTION_STOP_LOSS"
            elif target3 > 0 and price >= target3:
                reason = "OPTION_TARGET3"
            elif force_close:
                reason = force_close_reason
'''
    new = '''            stop = self._number(trade.get("option_stop"))
            target1 = self._number(trade.get("option_target1"))
            target2 = self._number(trade.get("option_target2"))
            target3 = self._number(trade.get("option_target3"))

            protected_stop = stop
            if target1 > 0 and trade.get("target1_hit_at"):
                protected_stop = max(protected_stop, entry)
            if target2 > 0 and trade.get("target2_hit_at"):
                protected_stop = max(protected_stop, entry * 1.08)

            runner_active = bool(trade.get("runner_active"))
            if target3 > 0 and trade.get("target3_hit_at"):
                runner_active = True
                trade["runner_active"] = True
                if not trade.get("runner_activated_at"):
                    trade["runner_activated_at"] = when.isoformat()

            if runner_active:
                gain = max(0.0, high - entry)
                runner_floor = max(entry * 1.15, high - gain * 0.30)
                protected_stop = max(protected_stop, runner_floor)
                trade["runner_stop"] = round(protected_stop, 4)
                trade["runner_peak_price"] = round(high, 4)

            reason = ""
            if protected_stop > 0 and price <= protected_stop:
                reason = "RUNNER_TRAIL_EXIT" if runner_active else (
                    "PROFIT_PROTECT_EXIT" if protected_stop > stop else "OPTION_STOP_LOSS"
                )
            elif force_close:
                reason = force_close_reason
'''
    if "RUNNER_TRAIL_EXIT" not in s:
        if old not in s: raise RuntimeError("paper exit block not found")
        s=s.replace(old,new,1)

    initold='            "target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n            "exit_time": "", "exit_price": 0.0, "exit_reason": "",\n'
    initnew='            "target1_hit_at": "", "target2_hit_at": "", "target3_hit_at": "",\n            "runner_active": False, "runner_activated_at": "",\n            "runner_stop": 0.0, "runner_peak_price": 0.0,\n            "exit_time": "", "exit_price": 0.0, "exit_reason": "",\n'
    if initold in s: s=s.replace(initold,initnew,1)

    csvold='        "target1_hit_at", "target2_hit_at", "target3_hit_at",\n        "exit_time", "exit_price", "exit_reason", "holding_seconds",\n'
    csvnew='        "target1_hit_at", "target2_hit_at", "target3_hit_at",\n        "runner_active", "runner_activated_at", "runner_stop", "runner_peak_price",\n        "exit_time", "exit_price", "exit_reason", "holding_seconds",\n'
    if csvold in s: s=s.replace(csvold,csvnew,1)
    p.write_text(s,encoding="utf-8")

    for f in FILES: py_compile.compile(str(ROOT/f),doraise=True)
    sc=(ROOT/"opening_momentum_scanner.py").read_text(encoding="utf-8")
    pj=(ROOT/"paper_trade_journal.py").read_text(encoding="utf-8")
    sg=(ROOT/"safety_gate.py").read_text(encoding="utf-8")
    assert "selective_entry_ready[:1]" not in sc
    assert "A_PLUS_WAIT_NO_FOLLOW_THROUGH" in sc
    assert "A_PLUS_WAIT_INTRADAY_CONFLICT" in sc
    assert "RUNNER_TRAIL_EXIT" in pj
    assert 'reason = "OPTION_TARGET3"' not in pj
    assert "maximum_trades_per_day: int = 0" in sg
except Exception:
    for f in FILES:
        if (backup/f).exists(): shutil.copy2(backup/f,ROOT/f)
    print("PATCH FAILED - originals restored. Backup:",backup)
    raise

print("="*72)
print("SUCCESS: QUALITY-FIRST + UNLIMITED-RUNNER PAPER PATCH INSTALLED")
print("Backup:",backup)
print("PASS: no hard daily trade-count quota")
print("PASS: one-entry-per-cycle emergency throttle removed")
print("PASS: quality/coherence/follow-through gates active")
print("PASS: T1 protects capital; T2 locks +8%")
print("PASS: T3 activates runner mode; it no longer forces exit")
print("PASS: runner has no fixed upside target")
print("PASS: runner floor >= +15%; then trails 30% of peak gain")
print("PASS: session-end exit retained")
print("PASS: PAPER ONLY; no live-order code added")
print("NOTE: synthetic paper stops are checked on quote refresh; a price gap can")
print("still exceed planned 10%. True hard-stop execution requires broker-side orders.")
print("="*72)
