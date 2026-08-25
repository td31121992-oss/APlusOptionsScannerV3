from __future__ import annotations
import csv, json, re, hashlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LOG=ROOT/'logs'/'scanner.log'
REPORTS=ROOT/'data'/'reports'
SCANNER=ROOT/'opening_momentum_scanner.py'
DAYS=['2026-08-17','2026-08-18','2026-08-19','2026-08-20','2026-08-21']

def read_csv(p):
    if not p.exists(): return []
    try:
        with p.open('r',encoding='utf-8-sig',newline='') as h:
            return list(csv.DictReader(h))
    except Exception:
        return []

def pick(r,*ks):
    for k in ks:
        v=r.get(k)
        if v not in ('',None): return v
    return ''

def parse_cycles():
    by=defaultdict(list)
    if not LOG.exists(): return by
    for line in LOG.read_text(encoding='utf-8',errors='ignore').splitlines():
        day=line[:10]
        if day not in DAYS or 'Intraday movement cycle' not in line: continue
        d={'time':line[11:19]}
        for k in ('entry_ready','fresh','plans','paper_today','safety_blocked'):
            m=re.search(rf'\b{k}=([0-9]+)',line)
            d[k]=int(m.group(1)) if m else 0
        by[day].append(d)
    return by

def log_counts(day):
    c=Counter()
    if not LOG.exists(): return c
    for line in LOG.read_text(encoding='utf-8',errors='ignore').splitlines():
        if not line.startswith(day): continue
        low=line.lower()
        if '429' in line: c['429']+=1
        if 'fund-limit fetch failed' in low: c['fund_fail']+=1
        if 'scanner terminated' in low: c['terminated']+=1
        if 'permissionerror' in low: c['permission']+=1
    return c

def trade_days():
    out=Counter()
    for r in read_csv(REPORTS/'paper_trades.csv'):
        t=str(pick(r,'entry_time','trading_date'))
        for d in DAYS:
            if t.startswith(d): out[d]+=1
    return out

def extract_gate(text):
    start=text.find('    def _aplus_selective_entry_allowed(')
    if start<0: return ''
    end=text.find('\n    def ',start+10)
    if end<0: end=len(text)
    return text[start:end]

def extract_actionable(text):
    m=re.search(r'(?m)^\s*actionable\s*=.*$',text)
    return m.group(0) if m else ''

def sh(s):
    return hashlib.sha256(s.encode('utf-8',errors='ignore')).hexdigest()[:12]

cycles=parse_cycles()
trades=trade_days()
print('='*126)
print('APLUS 5-DAY PIPELINE COMPARISON / REGRESSION FINDER')
print('='*126)
print(f"{'DAY':<12}{'CYCLES':>7}{'MAX_READY':>11}{'MAX_PLANS':>11}{'MAX_PAPER':>11}{'TRADES':>9}{'429':>8}{'FUND_FAIL':>11}{'TERM':>7}")
for day in DAYS:
    arr=cycles.get(day,[])
    c=log_counts(day)
    mx=lambda k:max([x.get(k,0) for x in arr],default=0)
    print(f"{day:<12}{len(arr):>7}{mx('entry_ready'):>11}{mx('plans'):>11}{mx('paper_today'):>11}{trades[day]:>9}{c['429']:>8}{c['fund_fail']:>11}{c['terminated']:>7}")

if SCANNER.exists():
    cur=SCANNER.read_text(encoding='utf-8',errors='ignore')
    print('\nCURRENT BRIDGE')
    print('scanner sha :',sh(cur))
    print('gate sha    :',sh(extract_gate(cur)) if extract_gate(cur) else 'NONE')
    print('actionable  :',extract_actionable(cur).strip())

backups=[]
for d in ROOT.glob('backup*'):
    if not d.is_dir(): continue
    p=d/'opening_momentum_scanner.py'
    if not p.exists(): continue
    try: txt=p.read_text(encoding='utf-8',errors='ignore')
    except Exception: continue
    backups.append((d.name,txt,extract_gate(txt),extract_actionable(txt)))

print('\nBACKUP BRIDGE HISTORY')
seen=set()
for name,txt,gate,act in sorted(backups,key=lambda x:x[0]):
    sig=(sh(gate) if gate else 'NONE', sh(act) if act else 'NONE')
    if sig in seen: continue
    seen.add(sig)
    print(f"{name:<72} gate={sig[0]} bridge={sig[1]} actionable={act.strip()}")

good=[x for x in backups if re.search(r'202608(17|18|19)_',x[0])]
if good and SCANNER.exists():
    g=sorted(good,key=lambda x:x[0])[-1]
    cur=SCANNER.read_text(encoding='utf-8',errors='ignore')
    print('\nLAST PRE-20AUG BACKUP COMPARISON')
    print('backup        :',g[0])
    print('gate_changed  :',sh(g[2])!=sh(extract_gate(cur)))
    print('bridge_changed:',sh(g[3])!=sh(extract_actionable(cur)))

print('\nVERDICT')
for day in DAYS:
    arr=cycles.get(day,[])
    if not arr: continue
    mr=max(x['entry_ready'] for x in arr)
    mp=max(x['plans'] for x in arr)
    if trades[day]>0:
        print(day,': GOOD DAY - trades recorded',trades[day],'max_plans',mp)
    elif mr>0 and mp==0:
        print(day,': BROKEN CONVERSION - ENTRY_READY existed but plans stayed ZERO')
    else:
        print(day,': no conversion evidence')
print('='*126)
