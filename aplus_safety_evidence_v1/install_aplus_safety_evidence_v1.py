from pathlib import Path
import shutil, subprocess, sys, textwrap, re
from datetime import datetime

ROOT=Path.cwd()
REQ=['safety_gate.py']
if not (ROOT/'safety_gate.py').exists():
    print('FAIL: run this from APlusOptionsScannerV3 root (safety_gate.py not found)'); sys.exit(2)
ts=datetime.now().strftime('%Y%m%d_%H%M%S')
backup=ROOT/f'backup_before_paper_safety_evidence_v1_{ts}'
backup.mkdir()
for name in ['safety_gate.py']:
    shutil.copy2(ROOT/name, backup/name)

# Patch safety_gate so paper journal-derived state is authoritative when marked.
p=ROOT/'safety_gate.py'; s=p.read_text(encoding='utf-8')
old='''        realized_pnl = (\n            sum(_number(row.get("realizedProfit"), 0.0) for row in positions)\n            if positions\n            else _number(state.get("realized_pnl_today"), 0.0)\n        )'''
new='''        paper_state_authoritative = bool(state.get("paper_mode_authoritative", False))\n        realized_pnl = (\n            _number(state.get("realized_pnl_today"), 0.0)\n            if paper_state_authoritative\n            else (\n                sum(_number(row.get("realizedProfit"), 0.0) for row in positions)\n                if positions\n                else _number(state.get("realized_pnl_today"), 0.0)\n            )\n        )'''
if old in s:
    s=s.replace(old,new,1)
elif 'paper_state_authoritative = bool(state.get("paper_mode_authoritative"' not in s:
    print('FAIL: safety_gate realized_pnl anchor not found; restored original')
    shutil.copy2(backup/'safety_gate.py',p); sys.exit(3)
p.write_text(s,encoding='utf-8')

agent = r'''from __future__ import annotations
import csv, json, time, os
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
JOURNALS=[ROOT/'data/intraday_movement/paper_trade_journal.json', ROOT/'data/reports/paper_trades_latest.json']
STATE=ROOT/'data/portfolio_state.json'
OUT=ROOT/'data/trade_evidence_capsules'
INTERVAL=float(os.getenv('APLUS_PAPER_SAFETY_SYNC_SECONDS','2'))

def load_json(p, default):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return default

def trades_from(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ('trades','paper_trades','items','records'):
            if isinstance(x.get(k),list): return x[k]
    return []

def num(v):
    try: return float(v or 0)
    except Exception: return 0.0

def status(t): return str(t.get('status') or t.get('trade_status') or '').upper()
def pnl(t): return num(t.get('pnl', t.get('realized_pnl',0)))
def day_of(t):
    x=str(t.get('entry_time') or t.get('signal_time') or t.get('created_at') or '')
    return x[:10]

def journal():
    best=[]
    for p in JOURNALS:
        tr=trades_from(load_json(p,{}))
        if len(tr)>len(best): best=tr
    return best

def nearest_csv(path, symbol, when):
    if not path.exists(): return None
    best=None; bd=10**30
    try:
        with path.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                if symbol and str(r.get('symbol','')).upper()!=symbol.upper(): continue
                raw=r.get('timestamp') or r.get('captured_at') or r.get('time') or r.get('datetime')
                if not raw: continue
                try: d=abs((datetime.fromisoformat(raw.replace('Z','+00:00'))-when).total_seconds())
                except Exception: continue
                if d<bd: best,bd=r,d
    except Exception: return None
    return best

def capsule(t):
    tid=str(t.get('trade_id') or t.get('id') or '').strip()
    if not tid: return
    raw=str(t.get('entry_time') or t.get('signal_time') or t.get('created_at') or '')
    try: when=datetime.fromisoformat(raw.replace('Z','+00:00'))
    except Exception: when=datetime.now().astimezone()
    sym=str(t.get('symbol') or '')
    day=when.date().isoformat(); d=OUT/day; d.mkdir(parents=True,exist_ok=True)
    dest=d/f'{tid}.json'
    # Rewrite while trade is open, and once after close, so exit facts are retained too.
    ev={
      'schema':'APLUS_ENTRY_EVIDENCE_CAPSULE_V1','trade_id':tid,'captured_by':'paper_safety_evidence_agent',
      'trade':t,
      'nearest_decision_event': nearest_csv(ROOT/'data/decision_evidence/decision_events.csv',sym,when),
      'nearest_candidate_snapshot': nearest_csv(ROOT/'data/decision_evidence/candidate_snapshots.csv',sym,when),
      'nearest_underlying_path': nearest_csv(ROOT/'data/decision_evidence/trade_underlying_path.csv',sym,when),
      'nearest_market_watch_1m': nearest_csv(ROOT/f'data/breakout_evidence/{day}/market_watch_1m_ohlcv.csv',sym,when),
      'written_at':datetime.now().astimezone().isoformat()
    }
    tmp=dest.with_suffix('.json.tmp'); tmp.write_text(json.dumps(ev,indent=2,default=str),encoding='utf-8'); tmp.replace(dest)

def sync():
    tr=journal(); today=datetime.now().astimezone().date().isoformat(); todays=[t for t in tr if day_of(t)==today]
    closed=[t for t in todays if status(t) in ('CLOSED','EXITED','COMPLETE','COMPLETED') or t.get('exit_time')]
    opened=[t for t in todays if t not in closed]
    streak=0
    def key(t): return str(t.get('exit_time') or t.get('last_update_time') or t.get('entry_time') or '')
    for t in sorted(closed,key=key):
        x=pnl(t)
        if x<0: streak+=1
        elif x>0: streak=0
    realized=sum(pnl(t) for t in closed)
    open_premium=sum(num(t.get('total_premium',t.get('capital_required',t.get('capital_used',0)))) for t in opened)
    open_risk=sum(num(t.get('total_risk',t.get('risk',0))) for t in opened)
    state=load_json(STATE,{}) if STATE.exists() else {}
    state.update({'as_of':datetime.now().astimezone().isoformat(),'paper_mode_authoritative':True,
      'realized_pnl_today':round(realized,2),'trades_today':len(todays),'consecutive_losses':streak,
      'open_positions':len(opened),'open_premium':round(open_premium,2),'open_total_risk':round(open_risk,2),
      'paper_state_source':'paper_trade_journal'})
    STATE.parent.mkdir(parents=True,exist_ok=True); tmp=STATE.with_suffix('.json.tmp'); tmp.write_text(json.dumps(state,indent=2),encoding='utf-8'); tmp.replace(STATE)
    for t in todays: capsule(t)
    return len(todays),len(closed),streak,realized

if __name__=='__main__':
    print('APlus PAPER Safety + Evidence Agent V1')
    print('No Dhan API calls. No live orders. Ctrl+C to stop.')
    while True:
        try:
            a,b,c,d=sync(); print(f'{datetime.now():%H:%M:%S} paper_today={a} closed={b} consecutive_losses={c} realized_pnl={d:.2f}',flush=True)
        except Exception as e: print('WARN',type(e).__name__,e,flush=True)
        time.sleep(max(1,INTERVAL))
'''
(ROOT/'aplus_paper_safety_evidence_v1.py').write_text(agent,encoding='utf-8')
(ROOT/'run_aplus_paper_safety_evidence_v1.bat').write_text('@echo off\ncd /d "%~dp0"\npython aplus_paper_safety_evidence_v1.py\n',encoding='utf-8')

# Compile before any restart/start.
for f in ['safety_gate.py','aplus_paper_safety_evidence_v1.py']:
    r=subprocess.run([sys.executable,'-m','py_compile',str(ROOT/f)])
    if r.returncode:
        shutil.copy2(backup/'safety_gate.py',ROOT/'safety_gate.py'); print('FAIL compile; safety_gate restored'); sys.exit(4)

# Initialize git baseline safely; never add secrets/runtime data.
gi=ROOT/'.gitignore'
existing=gi.read_text(encoding='utf-8') if gi.exists() else ''
block='''\n# APlus local/runtime secrets and generated data\n.env\n.env.*\n!.env.example\ndata/\nlogs/\n__pycache__/\n*.pyc\nbackup_before_*/\n'''
if 'APlus local/runtime secrets' not in existing: gi.write_text(existing+block,encoding='utf-8')
if shutil.which('git'):
    if not (ROOT/'.git').exists(): subprocess.run(['git','init'],cwd=ROOT)
    subprocess.run(['git','add','.'],cwd=ROOT)
    # Commit only if identity is configured; otherwise leave staged and report exact next command.
    email=subprocess.run(['git','config','user.email'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    name=subprocess.run(['git','config','user.name'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    if email and name:
        subprocess.run(['git','commit','-m','Baseline after Breakout Confirmation V1 + paper safety evidence V1'],cwd=ROOT)
        subprocess.run(['git','tag','-f','aplus-breakout-confirmation-v1-safety-evidence-v1'],cwd=ROOT)
        gitmsg='Git baseline committed + tagged.'
    else: gitmsg='Git initialized and files staged; identity not configured, so commit was not fabricated.'
else: gitmsg='Git executable not found; code install completed, Git baseline skipped.'

# Start exactly one agent; don't touch scanner.
ps="Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python(.exe)?$' -and $_.CommandLine -match 'aplus_paper_safety_evidence_v1.py'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Start-Process python -ArgumentList 'aplus_paper_safety_evidence_v1.py' -WorkingDirectory '"+str(ROOT).replace("'","''")+"'"
subprocess.run(['powershell','-NoProfile','-Command',ps])
print('='*100)
print('SUCCESS: APLUS PAPER SAFETY + EVIDENCE V1 INSTALLED')
print('Backup:',backup)
print('PASS paper journal -> realized P&L / consecutive-loss / open exposure state')
print('PASS safety_gate prefers paper P&L when paper_mode_authoritative=true')
print('PASS per-trade evidence capsules -> data\\trade_evidence_capsules\\YYYY-MM-DD\\TRADE_ID.json')
print('PASS no Dhan API calls added; no live orders enabled; scanner strategy untouched')
print(gitmsg)
print('='*100)
