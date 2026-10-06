from __future__ import annotations

import argparse
import json
from pathlib import Path

OPTION_REQUIRED = {
    "timestamp",
    "security_id",
    "trading_symbol",
    "expiry",
    "strike",
}
OPTION_TYPE_ALIASES = {"option_type", "ce_pe", "side"}


def normalize(name: object) -> str:
    return str(name).strip().lower().replace(" ", "_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit historical option-contract datasets without calling Dhan")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="data/research/5y_backtest/option_history_audit.json")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = (root / args.output).resolve()
    if root not in output.parents:
        raise SystemExit("Safety guard: output must remain inside project root.")

    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas is required for option-history auditing.")

    candidates = []
    for path in sorted((root / "data").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".parquet", ".pq"}:
            continue
        try:
            frame = pd.read_csv(path, nrows=5) if path.suffix.lower() == ".csv" else pd.read_parquet(path).head(5)
        except Exception:
            continue
        cols = {normalize(c) for c in frame.columns}
        if OPTION_REQUIRED.issubset(cols) and cols.intersection(OPTION_TYPE_ALIASES):
            candidates.append({"file": str(path), "columns": sorted(cols)})

    report = {
        "mode": "READ_ONLY_OPTION_HISTORY_AUDIT",
        "candidate_contract_files": candidates,
        "candidate_file_count": len(candidates),
        "exact_historical_option_replay_ready": bool(candidates),
        "required_fields": sorted(OPTION_REQUIRED | OPTION_TYPE_ALIASES),
        "quality_fields_recommended": [
            "ltp",
            "open",
            "high",
            "low",
            "close",
            "bid",
            "ask",
            "volume",
            "open_interest",
            "iv",
        ],
        "production_files_modified": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
