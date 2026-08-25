from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import importlib, json, py_compile

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/'opening_momentum_scanner.py'
py_compile.compile(str(SCANNER),doraise=True)

import opening_momentum_scanner as m
m=importlib.reload(m)
S=m.OpeningMomentumScanner

print('='*94)
print('APLUS SCANNER-WIDE ATOMIC-WRITE SELF-TEST')
print('='*94)

with TemporaryDirectory() as tmp:
    root=Path(tmp)

    target=root/'normal.json'
    assert S._atomic_json(target,{'ok':True}) is True
    print('PASS: normal JSON write')

    real=m.os.replace
    calls={'n':0}
    def flaky(src,dst):
        calls['n']+=1
        if calls['n']<=2:
            raise PermissionError(5,'Access is denied')
        return real(src,dst)

    target=root/'retry.json'
    with patch.object(m.os,'replace',side_effect=flaky):
        assert S._atomic_json(target,{'retry':True}) is True
    print('PASS: transient WinError 5 recovered')

    locked=root/'locked.json'
    locked.write_text('{"old":true}',encoding='utf-8')
    with patch.object(m.os,'replace',side_effect=PermissionError(5,'Access is denied')):
        assert S._atomic_json(locked,{'new':True}) is False
    assert json.loads(locked.read_text(encoding='utf-8'))['old'] is True
    print('PASS: permanent JSON lock non-fatal; old file preserved')

    csvp=root/'report.csv'
    csvp.write_text('symbol\nOLD\n',encoding='utf-8')
    with patch.object(m.os,'replace',side_effect=PermissionError(5,'Access is denied')):
        assert S._write_candidate_csv(csvp,[{'symbol':'NEW'}],['symbol']) is False
    assert 'OLD' in csvp.read_text(encoding='utf-8')
    print('PASS: permanent CSV lock non-fatal; old file preserved')

print('PASS: fno_market_watch_latest.json crash class covered')
print('='*94)
