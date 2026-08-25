from pathlib import Path
from datetime import datetime
import py_compile,shutil
ROOT=Path(__file__).resolve().parent
P=ROOT/'opening_momentum_scanner.py'
if not P.exists(): raise SystemExit('opening_momentum_scanner.py missing')
backup=ROOT/('backup_before_conversion_audit_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
shutil.copy2(P,backup/P.name)
s=P.read_text(encoding='utf-8')
needle = """                plan = self._build_option_plan(
                    candidate=candidate,
                    underlying=underlying,
                    now=current_time,
                    account_context=account_context,
                    safety_evaluations=safety_evaluations,
                )
"""
if needle not in s:
    print('NOTE: exact option-plan anchor not found; no code changed.')
else:
    repl = needle + """                logger.info(
                    'PAPER conversion audit symbol=%s direction=%s plan=%s safety=%s option_error=%s',
                    candidate.symbol,
                    candidate.direction,
                    'PASS' if plan is not None else 'FAIL',
                    candidate.safety_decision or '',
                    candidate.option_error or '',
                )
"""
    if 'PAPER conversion audit symbol=' not in s:
        s=s.replace(needle,repl,1)
        P.write_text(s,encoding='utf-8')
        py_compile.compile(str(P),doraise=True)
        print('SUCCESS: conversion audit logging installed')
        print('Backup:',backup)
        print('NO strategy/risk/safety decision logic changed')
    else:
        print('Conversion audit logging already present; no change.')
py_compile.compile(str(P),doraise=True)
