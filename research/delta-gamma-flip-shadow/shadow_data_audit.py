#!/usr/bin/env python3
"""Read-only audit of APlus paper-trade ledgers and option-chain snapshot coverage.

This utility never writes to the scanner, ledger, dashboard, or source files. It
is intended to run against a local project checkout where ignored runtime data
may exist. It reports reconciliation status; it does not calculate strategy
profitability or infer missing trade outcomes.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ID_FIELDS = ("paper_trade_id", "trade_id", "id")
STATUS_FIELDS = ("status", "position_lifecycle_status", "position_status")
CSV_LEDGER_NAMES = {"paper_trade_history.csv", "paper_trades.csv"}
JSON_LEDGER_NAMES = {"paper_trade_history.json", "paper_trades_latest.json", "paper_trade_journal.json"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def _first(row: dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _rows_from_json(path: Path) -> list[dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(obj, list):
        candidates = obj
    elif isinstance(obj, dict):
        candidates = None
        for key in ("paper_trades", "trades", "items", "journal"):
            if isinstance(obj.get(key), list):
                candidates = obj[key]
                break
        if candidates is None and all(isinstance(v, dict) for v in obj.values()):
            candidates = list(obj.values())
        if candidates is None:
            raise ValueError("JSON object has no recognized trade list")
    else:
        raise ValueError("JSON root must be a list or object")
    return [dict(row) for row in candidates if isinstance(row, dict)]


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return _rows_from_json(path)


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in SKIP_DIRS or part.startswith("backup_") for part in parts[:-1])


def discover(root: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {"csv": [], "json": [], "snapshots": [], "signals": []}
    for path in root.rglob("*"):
        if not path.is_file() or _is_ignored(path, root):
            continue
        name = path.name.lower()
        if name in CSV_LEDGER_NAMES:
            found["csv"].append(path)
        elif name in JSON_LEDGER_NAMES:
            found["json"].append(path)
        elif name == "option_chain_snapshots.jsonl":
            found["snapshots"].append(path)
        elif name.endswith(".csv") and (path.parent.name == "signal_snapshots" or name.startswith("chain_")):
            found["signals"].append(path)
    for key in found:
        found[key].sort(key=lambda p: str(p).lower())
    return found


def summarize(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [_first(row, ID_FIELDS) for row in rows]
    nonblank = [item for item in ids if item]
    statuses = Counter((_first(row, STATUS_FIELDS) or "UNKNOWN").upper() for row in rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "unique_nonblank_ids": len(set(nonblank)),
        "blank_ids": len(ids) - len(nonblank),
        "duplicate_ids": len(nonblank) - len(set(nonblank)),
        "id_set": set(nonblank),
        "status_counts": dict(sorted(statuses.items())),
    }


def audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    discovered = discover(root)
    ledger_reports: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in discovered["csv"] + discovered["json"]:
        try:
            ledger_reports.append(summarize(path, _read_ledger(path)))
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")

    history_reports = [
        x for x in ledger_reports
        if Path(x["path"]).name.lower() in {"paper_trade_history.csv", "paper_trade_history.json"}
    ]
    reconciliation: list[dict[str, Any]] = []
    for i, left in enumerate(history_reports):
        for right in history_reports[i + 1:]:
            reconciliation.append({
                "left": left["path"],
                "right": right["path"],
                "ids_match": left["id_set"] == right["id_set"],
                "count_match": left["rows"] == right["rows"],
                "left_only_ids": sorted(left["id_set"] - right["id_set"])[:25],
                "right_only_ids": sorted(right["id_set"] - left["id_set"])[:25],
            })

    snapshot_files = discovered["snapshots"]
    snapshot_lines = 0
    snapshot_errors: list[str] = []
    snapshot_symbols: set[str] = set()
    snapshot_dates: set[str] = set()
    for path in snapshot_files:
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                for line_no, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as exc:
                        snapshot_errors.append(f"{path}:{line_no}: invalid JSON ({exc.msg})")
                        continue
                    if not isinstance(item, dict):
                        snapshot_errors.append(f"{path}:{line_no}: JSON record is not an object")
                        continue
                    snapshot_lines += 1
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    stamp = str(metadata.get("captured_at") or item.get("captured_at") or "")
                    symbol = str(metadata.get("symbol") or item.get("symbol") or "").strip().upper()
                    if stamp:
                        snapshot_dates.add(stamp[:10])
                    if symbol:
                        snapshot_symbols.add(symbol)
        except Exception as exc:
            snapshot_errors.append(f"{path}: {type(exc).__name__}: {exc}")

    ledger_integrity_ok = (
        bool(ledger_reports)
        and not errors
        and all(report["blank_ids"] == 0 and report["duplicate_ids"] == 0 for report in ledger_reports)
        and all(item["ids_match"] and item["count_match"] for item in reconciliation)
    )
    return {
        "root": str(root),
        "files": {
            "csv_ledgers": [str(p) for p in discovered["csv"]],
            "json_ledgers": [str(p) for p in discovered["json"]],
            "option_chain_snapshot_files": [str(p) for p in snapshot_files],
            "signal_snapshot_csv_files": [str(p) for p in discovered["signals"]],
        },
        "ledgers": [{k: v for k, v in report.items() if k != "id_set"} for report in ledger_reports],
        "history_reconciliation": reconciliation,
        "ledger_integrity_ok": ledger_integrity_ok,
        "snapshot_coverage": {
            "files": len(snapshot_files),
            "valid_records": snapshot_lines,
            "dates": sorted(snapshot_dates),
            "symbols": sorted(snapshot_symbols),
            "errors": snapshot_errors,
        },
        "errors": errors,
        "ready_for_strategy_replay": ledger_integrity_ok and snapshot_lines > 0 and not snapshot_errors,
        "notes": [
            "This is a read-only inventory/reconciliation preflight, not a profitability backtest.",
            "A clean ledger is not enough: timestamp-aligned historical option-chain snapshots are also required for the delta/gamma shadow replay.",
            "Trade history can only be reconciled against a dashboard/history export if that export is present under the scanned root.",
            "Option-chain open interest alone does not establish dealer positioning or dealer gamma sign.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="Local project root (defaults to the repository root)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional JSON report path outside or inside the research folder")
    args = parser.parse_args()
    result = audit(args.root)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
