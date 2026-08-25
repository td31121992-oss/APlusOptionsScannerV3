from __future__ import annotations
import json,re
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DAY='2026-08-21'
LOG=ROOT/'logs'/'scanner.log'
REPORTS=ROOT/'data'/'reports'
patterns={
 'fund_fail':r'Safety fund-limit fetch failed',
 'positions_fail':r'positions.*failed|position.*fetch failed',
 '429':r'\b429\b',
 'option_chain':r'option[- ]chain|option chain',
 'option_plan_failed':r'OPTION_PLAN_FAILED|Option plan',
 'safety_blocked':r'SAFETY_BLOCKED',
 'quote_fail':r'marketfeed/quote',
 'historical_fail':r'charts/intraday',
 'scanner_terminated':r'Scanner terminated',
 'permission':r'PermissionError',
}
lines=[]
if LOG.exists():
    lines=[x for x in LOG.read_text(encoding='utf-8',errors='ignore').splitlines() if x.startswith(DAY)]
print('='*132)
print('APLUS 21-AUG CANDIDATE->OPTION->SAFETY CONVERSION FORENSIC')
print('='*132)
counts=Counter(); examples=defaultdict(list)
for line in lines:
    for k,p in patterns.items():
        if re.search(p,line,re.I):
            counts[k]+=1
            if len(examples[k])<8: examples[k].append(line)
print('\nFAILURE COUNTS')
for k,v in counts.most_common(): print(f'{k:<24}: {v}')
print('\nEXAMPLES')
for k in ('option_chain','option_plan_failed','safety_blocked','fund_fail','positions_fail','429','scanner_terminated','permission'):
    if examples[k]:
        print('\n--',k,'--')
        for line in examples[k]: print(line)
cycles=[]
for line in lines:
    if 'Intraday movement cycle' not in line: continue
    d={'time':line[11:19],'line':line}
    for k in ('entry_ready','fresh','plans','paper_today','safety_blocked'):
        m=re.search(rf'\b{k}=([0-9]+)',line)
        d[k]=int(m.group(1)) if m else 0
    cycles.append(d)
ready=[x for x in cycles if x['entry_ready']>0]
print('\nCYCLE CONVERSION SPLIT')
print('cycles total                         :',len(cycles))
print('cycles with entry_ready > 0          :',len(ready))
print('ready cycles with safety_blocked > 0 :',sum(x['safety_blocked']>0 for x in ready))
print('ready cycles safety_blocked == 0     :',sum(x['safety_blocked']==0 for x in ready))
print('ready cycles with plans > 0          :',sum(x['plans']>0 for x in ready))
print('\nFIRST 25 READY CYCLES')
for x in ready[:25]: print(x['line'])
p=REPORTS/'intraday_movement_latest.json'
if p.exists():
    try:data=json.loads(p.read_text(encoding='utf-8'))
    except Exception:data={}
    cand=[]
    for key in ('candidates','movement_leaders','entry_ready','fresh_movement'):
        arr=data.get(key)
        if isinstance(arr,list): cand.extend(z for z in arr if isinstance(z,dict))
    c=Counter()
    for z in cand:
        for k,prefix in (('paper_trade_status','status:'),('option_error','option:'),('safety_decision','safety:')):
            v=str(z.get(k) or '')
            if v: c[prefix+v]+=1
    print('\nLATEST PERSISTED CANDIDATE STATUS/ERROR COUNTS')
    for k,v in c.most_common(40): print(v,k)
print('\nINTERPRETATION')
if ready and all(x['plans']==0 for x in ready):
    print('CONFIRMED: shortlist discovery worked; conversion failed downstream.')
if any(x['safety_blocked']>0 for x in ready):
    print('CONFIRMED: some entry-ready candidates reached safety evaluation and were blocked.')
if any(x['safety_blocked']==0 for x in ready):
    print('CONFIRMED: safety blocking alone cannot explain every zero-plan cycle.')
if counts['fund_fail']: print('CONFIRMED: account/fund-data reliability degraded the safety path.')
if counts['429']: print('CONFIRMED: Dhan rate limiting degraded data availability.')
print('='*132)
