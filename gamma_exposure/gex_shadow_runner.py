"""Offline/read-only GEX runner for existing normalized option-chain CSV files.

It never creates broker clients or calls trading/order APIs. It requires the
instrument master to supply each option contract's actual lot size.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from gamma_exposure.gex_calculator import calculate_snapshot


def load_lot_sizes(master_path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    with master_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            security_id = str(row.get("SECURITY_ID") or "").strip()
            instrument_type = str(row.get("INSTRUMENT_TYPE") or "").strip().upper()
            try:
                lot_size = int(float(row.get("LOT_SIZE") or 0))
            except (TypeError, ValueError):
                continue
            if security_id and lot_size > 0 and instrument_type in {"OP", "OPTSTK", "OPTIDX"}:
                result[security_id] = lot_size
    return result


def _read_rows(paths: list[Path], lot_sizes: dict[str, int]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                security_id = str(row.get("option_security_id") or "").strip()
                row["lot_size"] = lot_sizes.get(security_id)
                output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only APlus GEX calculations on saved option-chain CSVs.")
    parser.add_argument("--input", required=True, help="CSV file or directory containing option_chain_rows.csv files.")
    parser.add_argument("--instrument-master", default="data/cache/api-scrip-master-detailed.csv")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    input_path = Path(args.input)
    master_path = Path(args.instrument_master)
    if not master_path.is_file():
        parser.error(f"instrument master not found: {master_path}")
    if input_path.is_file():
        input_files = [input_path]
    elif input_path.is_dir():
        input_files = sorted(input_path.rglob("option_chain_rows.csv"))
    else:
        parser.error(f"input path not found: {input_path}")
    if not input_files:
        parser.error("no option_chain_rows.csv files found")

    lot_sizes = load_lot_sizes(master_path)
    rows = _read_rows(input_files, lot_sizes)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("symbol") or ""), str(row.get("captured_at") or ""))].append(row)

    results = [calculate_snapshot(group) for _, group in sorted(groups.items())]
    output_path = Path(args.output) if args.output else (
        Path("data") / "gex_shadow" / datetime.now().astimezone().date().isoformat() / "gex_snapshots.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({
        "input_files": len(input_files),
        "input_rows": len(rows),
        "snapshots": len(results),
        "ok": sum(1 for item in results if item.get("status") == "OK"),
        "output": str(output_path),
        "read_only": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
