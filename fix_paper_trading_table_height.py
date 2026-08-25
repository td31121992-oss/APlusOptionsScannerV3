from __future__ import annotations

import ast
import py_compile
import shutil
from datetime import datetime
from pathlib import Path

class FixError(RuntimeError):
    pass

def main() -> int:
    root = Path.cwd().resolve()
    target = root / "dashboard" / "paper_trading_widget.py"
    if not target.exists():
        raise FixError("dashboard\\paper_trading_widget.py not found. Run from CAlphaTrader project root.")

    original = target.read_text(encoding="utf-8")

    table_anchor = """        h.setSectionResizeMode(19, QHeaderView.Stretch)
        root.addWidget(self.table, 2)
"""
    table_patch = """        h.setSectionResizeMode(19, QHeaderView.Stretch)

        # Dashboard layout guard: keep the paper-trade ledger visibly usable.
        self.table.setMinimumHeight(190)
        self.table.verticalHeader().setDefaultSectionSize(28)
        root.addWidget(self.table, 4)
"""

    bottom_anchor = """        bottom.addWidget(trade_frame, 1)
        bottom.addWidget(context_frame, 1)
        root.addLayout(bottom, 1)
"""
    bottom_patch = """        # Prevent wrapped details from squeezing the ledger to near-zero height.
        trade_frame.setMaximumHeight(190)
        context_frame.setMaximumHeight(190)

        bottom.addWidget(trade_frame, 1)
        bottom.addWidget(context_frame, 1)
        root.addLayout(bottom, 1)
"""

    updated = original
    if "self.table.setMinimumHeight(190)" not in updated:
        if table_anchor not in updated:
            raise FixError("Paper-trading table layout anchor not found.")
        updated = updated.replace(table_anchor, table_patch, 1)

    if "trade_frame.setMaximumHeight(190)" not in updated:
        if bottom_anchor not in updated:
            raise FixError("Paper-trading bottom-panel layout anchor not found.")
        updated = updated.replace(bottom_anchor, bottom_patch, 1)

    ast.parse(updated, filename=str(target))
    compile(updated, str(target), "exec")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "backup" / f"paper_trading_table_layout_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "paper_trading_widget.py"
    shutil.copy2(target, backup)

    try:
        target.write_text(updated, encoding="utf-8")
        py_compile.compile(str(target), doraise=True)
    except Exception:
        shutil.copy2(backup, target)
        raise

    print("=" * 76)
    print("CAlphaTrader Paper Trading Table Layout Fix: INSTALLED")
    print("=" * 76)
    print("UI-only changes:")
    print("  Trade table minimum height: 190 px")
    print("  Trade table stretch priority: 4")
    print("  Row height: 28 px")
    print("  Bottom detail/context panels capped at 190 px")
    print("  Vertical scrolling remains available")
    print()
    print("Trading logic / paper ledger / P&L calculations: UNCHANGED")
    print("Backup:", backup)
    print()
    print("Restart the dashboard to load the fix.")
    print("PAPER_TRADING_TABLE_LAYOUT_FIX_OK")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FixError as exc:
        print()
        print("PAPER_TRADING_TABLE_LAYOUT_FIX_FAILED")
        print(type(exc).__name__ + ":", exc)
        raise SystemExit(1)
