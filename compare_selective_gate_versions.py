from __future__ import annotations
from pathlib import Path
import difflib, hashlib, re

ROOT=Path(__file__).resolve().parent
CUR=ROOT/'opening_momentum_scanner.py'

def extract_gate(text):
    start=text.find('    def _aplus_selective_entry_allowed(')
    if start<0:return ''
    end=text.find('\n    def ',start+10)
    if end<0:end=len(text)
    return text[start:end]

def sig(s):
    return hashlib.sha256(s.encode('utf-8',errors='ignore')).hexdigest()[:12]

if not CUR.exists():
    raise SystemExit('opening_momentum_scanner.py missing')

cur_text=CUR.read_text(encoding='utf-8',errors='ignore')
cur_gate=extract_gate(cur_text)

candidates=[]
for d in ROOT.glob('backup*'):
    p=d/'opening_momentum_scanner.py'
    if not p.exists():
        continue
    try:
        txt=p.read_text(encoding='utf-8',errors='ignore')
    except Exception:
        continue
    gate=extract_gate(txt)
    if gate:
        candidates.append((d.name,p,gate))

uniq={}
for name,p,gate in sorted(candidates,key=lambda x:x[0]):
    uniq.setdefault(sig(gate),(name,p,gate))

print('='*128)
print('APLUS SELECTIVE-GATE REGRESSION FORENSIC')
print('NO FILE CHANGES')
print('='*128)
print('CURRENT gate:',sig(cur_gate))
print()

for gs,(name,p,gate) in uniq.items():
    print('-'*128)
    print(name)
    print('gate:',gs,'same_as_current:',gs==sig(cur_gate))
    statuses=sorted(set(re.findall(r'paper_trade_status\s*=\s*[\"\']([^\"\']+)',gate)))
    print('statuses:',', '.join(statuses) if statuses else 'none')
    print('gate head:',' '.join(gate.split())[:900])

prior=[x for x in uniq.values() if re.search(r'202608(18|19)_',x[0]) and sig(x[2])!=sig(cur_gate)]
prior=sorted(prior,key=lambda x:x[0])
if prior:
    name,p,gate=prior[-1]
    print('\n'+'='*128)
    print('DIFF: LAST DISTINCT 18/19-AUG GATE -> CURRENT')
    print('SOURCE:',name)
    print('='*128)
    diff=difflib.unified_diff(
        gate.splitlines(),cur_gate.splitlines(),
        fromfile=name,tofile='CURRENT',lineterm=''
    )
    for line in diff:
        print(line)
else:
    print('\nNo distinct 18/19-Aug gate backup found.')

print('\nIMPORTANT')
print('The previous 5-day comparison had no 17-20 cycle logs, so it could not prove which historical gate produced those trades.')
print('This report isolates the gate evolution so we can restore only a proven-good gate, not guess.')
print('='*128)
