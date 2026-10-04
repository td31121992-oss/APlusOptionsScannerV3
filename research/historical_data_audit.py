from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

SUPPORTED = {".csv", ".parquet", ".pq"}
REQUIRED_OHLCV = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
ALIASES = {
    "ticker": "symbol",
    "tradingsymbol": "symbol",
    "datetime": "timestamp",
    "date": "timestamp",
    "time": "timestamp",
    "vol": "volume",
}


def _normalize_columns(columns: Iterable[str]) -> set[str]:
    out = set()
    for raw in columns:
        key = str(raw).strip().lower().replace(" ", "_")
        out.add(ALIASES.get(key, key))
    return out


def _csv_profile(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {"rows": 0, "columns": [], "required_ohlcv": False}
        rows = sum(1 for _ in reader)
    cols = sorted(_normalize_columns(header))
    return {
        "rows": rows,
        "columns": cols,
        "required_ohlcv": REQUIRED_OHLCV.issubset(cols),
    }


def _profile(path: Path) -> dict:
    if path.suffix.lower() == ".csv":
        return _csv_profile(path)
    try:
        import pandas as pd
        frame = pd.read_parquet(path)
        cols = sorted(_normalize_columns(frame.columns))
        return {
            "rows": int(len(frame)),
            "columns": cols,
            "required_ohlcv": REQUIRED_OHLCV.issubset(cols),
        }
    except Exception as exc:
        return {
            "rows": 0,
            "columns": [],
            "required_ohlcv": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _coverage_years(files: list[Path]) -> tuple[list[int], list[dict]]:
    years: set[int] = set()
    details: list[dict] = []
    for path in files:
        if path.suffix.lower() != ".csv":
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    continue
                normalized = {ALIASES.get(str(c).strip().lower().replace(" ", "_"), str(c).strip().lower().replace(" ", "_")): c
                              for c in reader.fieldnames}
                ts_key = normalized.get("timestamp")
                if not ts_key:
                    continue
                file_years: set[int] = set()
                for row in reader:
                    raw = str(row.get(ts_key) or "").strip()
                    if not raw:
                        continue
                    try:
                        year = datetime.fromisoformat(raw.replace("Z", "+00:00")).year
                    except ValueError:
                        try:
                            year = datetime.strptime(raw[:10], "%Y-%m-%d").year
                        except ValueError:
                            continue
                    years.add(year)
                    file_years.add(year)
                if file_years:
                    details.append({"file": str(path), "years": sorted(file_years)})
        except Exception:
            continue
    return sorted(years), details


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only APlus historical research data audit")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="data/research/5y_backtest/historical_data_audit.json")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = (root / args.output).resolve()
    if root not in output.parents:
        raise SystemExit("Safety guard: output must remain inside project root.")

    candidates = [p for p in (root / "data").rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED]
    profiles = []
    for path in sorted(candidates):
        profile = _profile(path)
        profile["file"] = str(path)
        profiles.append(profile)

    years, year_files = _coverage_years(candidates)
    current_year = datetime.now().year
    requested = list(range(current_year - 4, current_year + 1))
    present_requested = [y for y in requested if y in years]
    missing_requested = [y for y in requested if y not in years]

    ohlcv_files = [p for p in profiles if p.get("required_ohlcv")]
    option_like = [
        p for p in profiles
        if {"strike", "expiry"}.issubset(set(p.get("columns", [])))
        and any(x in p.get("columns", []) for x in ("option_type", "ce_pe", "side"))
    ]

    report = {
        "mode": "READ_ONLY_RESEARCH_AUDIT",
        "generated_at": datetime.now().astimezone().isoformat(),
        "requested_years": requested,
        "years_found": years,
        "requested_years_present": present_requested,
        "requested_years_missing": missing_requested,
        "file_count": len(profiles),
        "ohlcv_file_count": len(ohlcv_files),
        "option_contract_like_file_count": len(option_like),
        "files": profiles,
        "year_file_map": year_files,
        "five_year_ohlcv_ready": bool(not missing_requested and ohlcv_files),
        "exact_option_replay_ready": bool(not missing_requested and option_like),
        "gaps": [
            "Five-year coverage is not established until every requested year is present in usable OHLCV data.",
            "Exact option P&L requires historical option-contract observations; underlying candles are insufficient.",
            "Bid/ask, OI, volume and IV coverage must be audited separately before claiming realistic option fills.",
        ],
        "production_files_modified": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
