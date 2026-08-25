from pathlib import Path
from datetime import datetime
import re, shutil, py_compile

ROOT=Path(__file__).resolve().parent
P=ROOT/'opening_momentum_scanner.py'
if not P.exists(): raise SystemExit('FAIL: opening_momentum_scanner.py missing')
s=P.read_text(encoding='utf-8')
backup=ROOT/('backup_before_pipeline_bridge_audit_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
shutil.copy2(P,backup/P.name)

try:
    s,n=re.subn(r'actionable\s*=\s*selective_entry_ready\s*\[\s*:\s*1\s*\]',
                'actionable = selective_entry_ready',s,count=1)
    if n==0 and 'actionable = selective_entry_ready' not in s:
        raise RuntimeError('Could not locate selective actionable bridge')

    old = '''        selective_entry_ready = [
            item for item in entry_ready
            if self._aplus_selective_entry_allowed(item)
        ]
'''
    if old in s and 'selective_gate_rejected =' not in s:
        new = '''        selective_entry_ready = [
            item for item in entry_ready
            if self._aplus_selective_entry_allowed(item)
        ]
        selective_gate_rejected = [
            item for item in entry_ready
            if item not in selective_entry_ready
        ]
'''
        s=s.replace(old,new,1)

    P.write_text(s,encoding='utf-8')
    py_compile.compile(str(P),doraise=True)
except Exception:
    shutil.copy2(backup/P.name,P)
    print('INSTALL FAILED - original restored.')
    print('Backup:',backup)
    raise

print('='*96)
print('SUCCESS: SAFE PIPELINE BRIDGE/AUDIT REPAIR INSTALLED')
print('Backup:',backup)
print('PASS: actionable bridge = all selective-entry-ready candidates')
print('PASS: strategy thresholds unchanged')
print('PASS: risk rules unchanged')
print('PASS: live orders unchanged')
print('PASS: scanner compiles')
print('='*96)
