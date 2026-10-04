from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ALIASES = {
    "ticker": "symbol",
    "tradingsymbol": "symbol",
    "datetime": "timestamp",
    "date": "timestamp",
    "time": "timestamp",
    "vol": "volume",
}
REQUIRED = {"symbol", "timestamp", "open", "high", "low", "close"}


def load_files(root: Path):
    import pandas as pd
    frames = []
    for path in sorted((root / "data").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".parquet", ".pq"}:
            continue
        try:
            frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
        except Exception:
            continue
        rename = {}
        for col in frame.columns:
            key = str(col).strip().lower().replace(" ", "_")
            rename[col] = ALIASES.get(key, key)
        frame = frame.rename(columns=rename)
        if not REQUIRED.issubset(frame.columns):
            continue
        frame = frame.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        for col in ("open", "high", "low", "close"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["symbol", "timestamp", "open", "high", "low", "close"])
        frame = frame[(frame["open"] > 0) & (frame["close"] > 0)]
        frame["_source"] = str(path)
        if len(frame):
            frames.append(frame[["symbol", "timestamp", "open", "high", "low", "close", "_source"]])
    if not frames:
        raise SystemExit("No usable OHLC data found under data/.")
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build monthly stock performance from real historical observations")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="data/research/5y_backtest/monthly_stock_performance.csv")
    parser.add_argument("--min-year", type=int, default=None)
    parser.add_argument("--max-year", type=int, default=None)
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = (root / args.output).resolve()
    if root not in output.parents:
        raise SystemExit("Safety guard: output must remain inside project root.")

    frame = load_files(root)
    frame["date"] = frame["timestamp"].dt.date
    frame["month"] = frame["timestamp"].dt.to_period("M").astype(str)
    if args.min_year is not None:
        frame = frame[frame["timestamp"].dt.year >= args.min_year]
    if args.max_year is not None:
        frame = frame[frame["timestamp"].dt.year <= args.max_year]

    # For each stock/month, use the first and last actual observation available.
    frame = frame.sort_values(["symbol", "timestamp"])
    first = frame.groupby(["symbol", "month"], as_index=False).first()
    last = frame.groupby(["symbol", "month"], as_index=False).last()
    first = first.rename(columns={"close": "month_start_close", "timestamp": "first_observation"})
    last = last.rename(columns={"close": "month_end_close", "timestamp": "last_observation"})

    out = first[["symbol", "month", "first_observation", "month_start_close"]].merge(
        last[["symbol", "month", "last_observation", "month_end_close"]],
        on=["symbol", "month"],
        how="inner",
    )
    out["absolute_change"] = out["month_end_close"] - out["month_start_close"]
    out["return_percent"] = (
        out["absolute_change"] / out["month_start_close"] * 100.0
    )
    out["rupee_1_growth"] = out["month_end_close"] / out["month_start_close"]
    out["rank_in_month"] = out.groupby("month")["return_percent"].rank(
        method="min", ascending=False
    )
    out["positive_month"] = out["return_percent"] > 0
    out = out.sort_values(["month", "rank_in_month", "symbol"])

    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False, float_format="%.6f")

    summary = {
        "mode": "READ_ONLY_MONTHLY_STOCK_PERFORMANCE",
        "rows": int(len(out)),
        "symbols": int(out["symbol"].nunique()),
        "months": int(out["month"].nunique()),
        "positive_month_rows": int(out["positive_month"].sum()),
        "source_rule": "first and last actual observations available for each stock/month",
        "rupee_1_rule": "month_end_close / month_start_close",
        "production_files_modified": False,
    }
    manifest = output.with_name("monthly_stock_performance_manifest.json")
    manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
