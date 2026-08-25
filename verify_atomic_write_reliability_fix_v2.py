from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import importlib, json, py_compile

ROOT=Path(__file__).resolve().parent
py_compile.compile(str(ROOT/'paper_trade_journal.py'), doraise=True)

import paper_trade_journal as m
m=importlib.reload(m)
J=m.PaperTradeJournal

print('='*92)
print('APLUS ATOMIC-WRITE RELIABILITY V2 SELF-TEST')
print('='*92)

with TemporaryDirectory() as tmp:
    root=Path(tmp)
    j=J(state_dir=root/'state', report_dir=root/'reports')
    assert j.flush() is True
    print('PASS: normal flush')

    real_replace=m.os.replace
    calls={'n':0}
    def flaky(src,dst):
        calls['n']+=1
        if calls['n']<=2:
            raise PermissionError(5,'Access is denied')
        return real_replace(src,dst)

    target=root/'reports'/'retry.json'
    with patch.object(m.os,'replace',side_effect=flaky):
        J._atomic_json(target,{'ok':True})
    assert json.loads(target.read_text(encoding='utf-8'))['ok'] is True
    print('PASS: transient WinError 5 recovered')

    with patch.object(J,'_atomic_json',side_effect=PermissionError(5,'Access is denied')):
        assert j.flush() is False
    print('PASS: permanent JSON lock is non-fatal')

    with patch.object(J,'_write_csv',side_effect=PermissionError(5,'Access is denied')):
        assert j.flush() is False
    print('PASS: permanent CSV lock is non-fatal')

print('PASS: scanner-killing PermissionError path covered')
print('='*92)
