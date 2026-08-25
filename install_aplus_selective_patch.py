from pathlib import Path
from datetime import datetime
import shutil, py_compile
ROOT=Path(__file__).resolve().parent
FILES=['config.py','opening_momentum_scanner.py','option_selector.py','safety_gate.py','paper_trade_journal.py']
missing=[f for f in FILES if not (ROOT/f).is_file()]
if missing: raise SystemExit('FAIL missing: '+', '.join(missing))
backup=ROOT/('backup_before_aplus_selective_'+datetime.now().strftime('%Y%m%d_%H%M%S')); backup.mkdir()
for f in FILES: shutil.copy2(ROOT/f,backup/f)
def rep(fn,old,new):
 p=ROOT/fn; s=p.read_text(encoding='utf-8')
 if old not in s: raise RuntimeError(fn+' expected text not found: '+old[:60])
 p.write_text(s.replace(old,new,1),encoding='utf-8')
try:
 rep('config.py','paper_trade_rearm_minutes: int = 20','paper_trade_rearm_minutes: int = 180')
 rep('config.py','_int("INTRADAY_PAPER_TRADE_REARM_MINUTES", 20, 5)','_int("INTRADAY_PAPER_TRADE_REARM_MINUTES", 180, 5)')
 rep('safety_gate.py','maximum_trades_per_day: int = 3','maximum_trades_per_day: int = 6')
 rep('option_selector.py','stop_loss = self._round_down(','stop_loss = self._round_up(')
 p=ROOT/'opening_momentum_scanner.py'; s=p.read_text(encoding='utf-8')
 old='        actionable = entry_ready[: self.settings.maximum_option_candidates]\n'
 new='''        # A+ selective gate: quality first; daily limit is only a safety ceiling.\n        selective_entry_ready = [\n            item for item in entry_ready\n            if self._aplus_selective_entry_allowed(item)\n        ]\n        # Rank first and allow at most one NEW paper entry per cycle.\n        actionable = selective_entry_ready[:1]\n'''
 if old not in s: raise RuntimeError('scanner actionable anchor not found')
 s=s.replace(old,new,1)
 anchor='    def _build_shortlists(\n'
 method='''    def _aplus_selective_entry_allowed(self, c: MomentumCandidate) -> bool:\n        # High-selectivity PAPER gate based on the 17-Aug forensic review.\n        direction=str(c.direction or "").upper()\n        setup=str(c.setup_family or "").upper()\n        pivot=str(c.pivot_state or "").upper()\n        if pivot == "PIVOT_TO_R1":\n            c.paper_trade_status="A_PLUS_WAIT_PIVOT_TO_R1"; return False\n        if c.chase_risk_score >= 25.0 and abs(c.vwap_distance_percent) >= 0.75:\n            c.paper_trade_status="A_PLUS_WAIT_OVEREXTENDED"; return False\n        if direction == "BULLISH" and c.rsi14_5m >= 85.0 and c.vwap_distance_percent >= 0.60:\n            c.paper_trade_status="A_PLUS_WAIT_BULL_EXHAUSTION"; return False\n        if direction == "BEARISH" and c.rsi14_5m <= 15.0 and c.vwap_distance_percent <= -0.60:\n            c.paper_trade_status="A_PLUS_WAIT_BEAR_EXHAUSTION"; return False\n        if setup == "CLEAN_BEARISH_BREAKDOWN":\n            c.paper_trade_status="A_PLUS_WAIT_BEAR_BREAKDOWN_CONFIRM"; return False\n        conflict=((direction=="BULLISH" and c.day_change_percent < 0) or\n                  (direction=="BEARISH" and c.day_change_percent > 0))\n        fresh=(c.fresh_15m_high or c.fresh_15m_low or c.fresh_30m_high or c.fresh_30m_low or\n               c.fresh_day_high or c.fresh_day_low or c.opening_range_breakout)\n        if conflict and not fresh:\n            c.paper_trade_status="A_PLUS_WAIT_COUNTER_SESSION"; return False\n        if c.relative_volume < 1.0 and c.recent_relative_volume_15m < 1.0 and not fresh:\n            c.paper_trade_status="A_PLUS_WAIT_WEAK_PARTICIPATION"; return False\n        if c.trade_quality_score < 65.0 or c.trend_alignment_score < 60.0:\n            c.paper_trade_status="A_PLUS_WAIT_QUALITY"; return False\n        return True\n\n'''
 if anchor not in s: raise RuntimeError('scanner method anchor not found')
 p.write_text(s.replace(anchor,method+anchor,1),encoding='utf-8')
 pj=ROOT/'paper_trade_journal.py'; ps=pj.read_text(encoding='utf-8')
 if 'rearm_minutes: int = 20' in ps: pj.write_text(ps.replace('rearm_minutes: int = 20','rearm_minutes: int = 180',1),encoding='utf-8')
 for f in FILES: py_compile.compile(str(ROOT/f),doraise=True)
 assert 'selective_entry_ready[:1]' in (ROOT/'opening_momentum_scanner.py').read_text(encoding='utf-8')
 assert 'maximum_trades_per_day: int = 6' in (ROOT/'safety_gate.py').read_text(encoding='utf-8')
 assert 'stop_loss = self._round_up(' in (ROOT/'option_selector.py').read_text(encoding='utf-8')
except Exception:
 for f in FILES:
  if (backup/f).exists(): shutil.copy2(backup/f,ROOT/f)
 print('PATCH FAILED - originals restored. Backup:',backup); raise
print('='*68)
print('SUCCESS: A+ SELECTIVE PAPER PATCH INSTALLED')
print('Backup:',backup)
print('PASS: 6 trades/day maximum (ceiling, not quota)')
print('PASS: max one new paper entry per scanner cycle')
print('PASS: 180-minute same-lane rearm default')
print('PASS: PIVOT/overextension/exhaustion/participation guards')
print('PASS: option stop tick rounding cannot exceed planned 10% by rounding')
print('PASS: touched modules compile')
print('IMPORTANT: no live-order code was added')
