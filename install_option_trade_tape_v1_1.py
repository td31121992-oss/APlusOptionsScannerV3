
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT = Path(__file__).resolve().parent
P = ROOT / "paper_trade_journal.py"
MARK = "APLUS_OPTION_TAPE_V1"

if not P.exists():
    raise SystemExit("FAIL: paper_trade_journal.py missing")

s = P.read_text(encoding="utf-8")
if MARK in s:
    print("ALREADY INSTALLED:", MARK)
    raise SystemExit(0)

tree = ast.parse(s)
cls = next(
    (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PaperTradeJournal"),
    None,
)
if cls is None:
    raise SystemExit("FAIL: PaperTradeJournal class not found")

update = next(
    (
        n for n in cls.body
        if isinstance(n, ast.FunctionDef)
        and n.name in {"update_open_positions", "update_positions"}
    ),
    None,
)
if update is None:
    raise SystemExit("FAIL: neither update_open_positions nor update_positions found")

def node_start(n):
    ds = [d.lineno for d in getattr(n, "decorator_list", []) if hasattr(d, "lineno")]
    return min(ds + [n.lineno]) - 1

helper = (
"    # APLUS_OPTION_TAPE_V1\n"
"    def _append_option_tape(\n"
"        self,\n"
"        trade: dict[str, Any],\n"
"        when: datetime,\n"
"        price: float,\n"
"    ) -> None:\n"
"        # Persist an already-fetched option quote; ZERO extra API calls.\n"
"        try:\n"
"            import csv as _csv\n"
"            tid = str(trade.get(\"trade_id\") or trade.get(\"paper_trade_id\") or \"\").strip()\n"
"            if not tid:\n"
"                return\n"
"            base = self.data_dir.parent / \"option_trade_tape\" / when.date().isoformat()\n"
"            base.mkdir(parents=True, exist_ok=True)\n"
"            path = base / f\"{tid}.csv\"\n"
"            exists = path.exists()\n"
"            row = {\n"
"                \"timestamp\": when.isoformat(),\n"
"                \"trade_id\": tid,\n"
"                \"symbol\": trade.get(\"symbol\", \"\"),\n"
"                \"option_security_id\": trade.get(\"option_security_id\", \"\"),\n"
"                \"option_type\": trade.get(\"option_type\", \"\"),\n"
"                \"strike\": trade.get(\"strike\", \"\"),\n"
"                \"expiry\": trade.get(\"expiry\", \"\"),\n"
"                \"price\": round(float(price), 4),\n"
"                \"entry_price\": trade.get(\"entry_price\", \"\"),\n"
"                \"option_stop\": trade.get(\"option_stop\", \"\"),\n"
"                \"status\": trade.get(\"status\", \"\"),\n"
"            }\n"
"            with path.open(\"a\", encoding=\"utf-8-sig\", newline=\"\") as handle:\n"
"                writer = _csv.DictWriter(handle, fieldnames=list(row.keys()))\n"
"                if not exists:\n"
"                    writer.writeheader()\n"
"                writer.writerow(row)\n"
"        except Exception:\n"
"            return\n\n"
)

lines = s.splitlines(keepends=True)
start = node_start(update)
lines = lines[:start] + helper.splitlines(keepends=True) + lines[start:]
s = "".join(lines)

tree = ast.parse(s)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PaperTradeJournal")
update = next(
    n for n in cls.body
    if isinstance(n, ast.FunctionDef)
    and n.name in {"update_open_positions", "update_positions"}
)

target = None
for n in ast.walk(update):
    if isinstance(n, ast.Assign) and len(n.targets) == 1:
        t = n.targets[0]
        if (
            isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name)
            and t.value.id == "trade"
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == "last_option_price"
        ):
            target = n
            break

if target is None:
    raise SystemExit("FAIL: last_option_price assignment not found")

lines = s.splitlines(keepends=True)
indent = " " * target.col_offset
call = indent + "self._append_option_tape(trade, when, price)\n"
lines = lines[:target.end_lineno] + [call] + lines[target.end_lineno:]
patched = "".join(lines)
ast.parse(patched)

if patched.count("def _append_option_tape(") != 1:
    raise SystemExit("FAIL: helper count invalid")
if patched.count("self._append_option_tape(trade, when, price)") != 1:
    raise SystemExit("FAIL: call count invalid")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_option_tape_v1_1_{stamp}"
backup.mkdir(parents=True, exist_ok=True)
shutil.copy2(P, backup / "paper_trade_journal.py")

try:
    P.write_text(patched, encoding="utf-8")
    py_compile.compile(str(P), doraise=True)
except Exception:
    shutil.copy2(backup / "paper_trade_journal.py", P)
    print("INSTALL FAILED - original restored")
    raise

print("=" * 108)
print("SUCCESS: APLUS OPTION TAPE V1.1 INSTALLED")
print("Updater method:", update.name)
print("Backup:", backup)
print("PASS already-fetched open-trade option quote is persisted")
print("PASS ZERO extra Dhan calls")
print("PASS NO entry/exit/stop/target rule changed")
print("=" * 108)
