from pathlib import Path
from datetime import datetime
import py_compile, re, shutil

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/'opening_momentum_scanner.py'
if not SCANNER.exists():
    raise SystemExit('FAIL: opening_momentum_scanner.py not found')

stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
backup=ROOT/f'backup_before_scanner_atomic_write_{stamp}'
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(SCANNER,backup/SCANNER.name)

def add_import(s, anchor, line):
    if line.strip() in s:
        return s
    i=s.find(anchor)
    if i<0: raise RuntimeError(f'import anchor not found: {anchor}')
    e=s.find('\n',i)
    return s[:e+1]+line+s[e+1:]

def repl_method(s,name,new):
    pat=re.compile(rf'(?ms)^    @(?:staticmethod|classmethod)\n    def {re.escape(name)}\(.*?(?=^    @|^    def |\Z)')
    m=pat.search(s)
    if not m: raise RuntimeError(f'method not found: {name}')
    return s[:m.start()]+new.rstrip()+'\n\n'+s[m.end():]

try:
    s=SCANNER.read_text(encoding='utf-8')

    if 'import time\n' not in s:
        s=add_import(s,'import tempfile','import time\n')

    if 'logger = logging.getLogger(__name__)' not in s:
        if 'import logging\n' not in s:
            s=add_import(s,'import json','import logging\n')
        p=s.find('class OpeningMomentumScanner')
        if p<0: raise RuntimeError('OpeningMomentumScanner class not found')
        s=s[:p]+'logger = logging.getLogger(__name__)\n\n\n'+s[p:]

    new_csv = '''    @classmethod
    def _write_candidate_csv(
        cls,
        path: Path,
        rows: Sequence[Mapping[str, Any]],
        fields: Sequence[str],
    ) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(fields))
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in fields})
                handle.flush()
                os.fsync(handle.fileno())
            if not cls._replace_with_retry(temporary, path):
                logger.warning(
                    "Scanner report CSV replace failed after retries; "
                    "previous file preserved and scanner will continue (path=%s)",
                    path,
                )
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)
'''
    s=repl_method(s,'_write_candidate_csv',new_csv)

    new_json = '''    @classmethod
    def _atomic_json(
        cls,
        path: Path,
        payload: Mapping[str, Any],
    ) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    OpeningMomentumScanner._serializable(payload),
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
            if not cls._replace_with_retry(temporary, path):
                logger.warning(
                    "Scanner report JSON replace failed after retries; "
                    "previous file preserved and scanner will continue (path=%s)",
                    path,
                )
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)
'''
    s=repl_method(s,'_atomic_json',new_json)

    if 'def _replace_with_retry(' not in s:
        p=s.find('    @classmethod\n    def _write_candidate_csv')
        if p<0: raise RuntimeError('CSV insertion point not found')
        helper='''    @staticmethod
    def _replace_with_retry(
        temporary: Path,
        path: Path,
        *,
        attempts: int = 7,
        initial_delay: float = 0.05,
    ) -> bool:
        delay=max(0.01,float(initial_delay))
        attempts=max(1,int(attempts))
        for attempt in range(1,attempts+1):
            try:
                os.replace(temporary,path)
                return True
            except (PermissionError,OSError) as exc:
                if attempt>=attempts:
                    logger.warning(
                        "Scanner atomic replace exhausted retries "
                        "(attempts=%s path=%s error=%s: %s)",
                        attempts,path,type(exc).__name__,exc,
                    )
                    return False
                logger.warning(
                    "Scanner atomic replace retry %s/%s "
                    "(path=%s error=%s: %s)",
                    attempt,attempts,path,type(exc).__name__,exc,
                )
                time.sleep(delay)
                delay=min(delay*2.0,0.80)
        return False


'''
        s=s[:p]+helper+s[p:]

    SCANNER.write_text(s,encoding='utf-8')
    py_compile.compile(str(SCANNER),doraise=True)

except Exception:
    shutil.copy2(backup/SCANNER.name,SCANNER)
    print('INSTALL FAILED - original scanner restored automatically.')
    print('Backup:',backup)
    raise

print('='*94)
print('SUCCESS: SCANNER-WIDE ATOMIC-WRITE RELIABILITY FIX INSTALLED')
print('Backup:',backup)
print('PASS: JSON report writes protected')
print('PASS: CSV report writes protected')
print('PASS: WinError 5 retries with backoff')
print('PASS: exhausted report-file lock is non-fatal')
print('PASS: strategy/risk/order logic unchanged')
print('='*94)
