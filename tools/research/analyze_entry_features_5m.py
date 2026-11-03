from pathlib import Path
import json
import numpy as np
import pandas as pd

root = Path(r"C:\Users\Aplus\Desktop\APlusOptionsScannerV3")
out = root / "data" / "option_response_shadow_20261026"

obs = pd.read_csv(out / "option_response_observations.csv",
                  dtype={"option_security_id": str})
quotes = pd.read_csv(out / "option_chain_quote_quality_rows.csv",
                     dtype={"security_id": str})
audit = pd.read_csv(out / "option_response_exit_quote_audit.csv",
                    dtype={"security_id": str})

obs["day"] = obs["day"].astype(str)
quotes["day"] = quotes["day"].astype(str)
audit["day"] = audit["day"].astype(str)

obs["option_security_id"] = obs["option_security_id"].astype(str)
quotes["security_id"] = quotes["security_id"].astype(str)
audit["security_id"] = audit["security_id"].astype(str)

obs = obs[pd.to_numeric(obs["target_minutes"], errors="coerce") == 5].copy()

key_obs = ["day", "symbol", "kind", "option_security_id", "ready"]
key_quote = ["day", "symbol", "kind", "security_id", "ready"]

qcols = key_quote + [
    "spread_mid_pct", "ask_ltp_ratio", "delta", "iv", "theta",
    "volume", "oi", "bid_qty", "ask_qty", "ltp_inside_bid_ask"
]
q = quotes[qcols].copy()
q = q.rename(columns={"security_id": "option_security_id"})

a = audit[audit["horizon"].astype(str) == "5"].copy()
acols = ["day", "symbol", "kind", "security_id", "ready", "both_clean"]
a = a[acols].rename(columns={
    "security_id": "option_security_id",
    "both_clean": "both_clean"
})

df = obs.merge(q, on=key_obs, how="left", validate="many_to_one")
df = df.merge(a, on=key_obs, how="left", validate="one_to_one")

numeric = [
    "option_return_ask_to_bid_pct", "direction_adjusted_underlying_move_pct",
    "entry_iv", "entry_delta", "entry_theta", "spread_mid_pct",
    "ask_ltp_ratio", "delta", "iv", "theta", "volume", "oi",
    "bid_qty", "ask_qty"
]
for col in numeric:
    if col in df:
        df[col] = pd.to_numeric(df[col], errors="coerce")

df["abs_delta"] = df["delta"].abs()
df["abs_theta"] = df["theta"].abs()
df["both_clean"] = df["both_clean"].astype(str).str.lower().eq("true")
df["entry_quote_inside"] = df["ltp_inside_bid_ask"].astype(str).str.lower().eq("true")

features = {
    "spread_mid_pct": "entry spread",
    "ask_ltp_ratio": "ask / LTP ratio",
    "abs_delta": "absolute delta",
    "iv": "entry IV",
    "abs_theta": "absolute theta",
    "volume": "option volume",
    "oi": "open interest",
}

results = []
for feature, label in features.items():
    valid = df.dropna(subset=[feature, "option_return_ask_to_bid_pct"]).copy()
    if len(valid) < 15 or valid[feature].nunique() < 2:
        continue

    # Quantile bins use entry-time values only. Duplicate boundaries are handled.
    try:
        valid["feature_bin"] = pd.qcut(
            valid[feature].rank(method="first"), q=3,
            labels=["LOW", "MID", "HIGH"]
        )
    except ValueError:
        continue

    for sample_name, subset in [
        ("ALL_5M", valid),
        ("BOTH_ENTRY_EXIT_CLEAN", valid[valid["both_clean"]])
    ]:
        for (day, kind, bucket), g in subset.groupby(
            ["day", "kind", "feature_bin"], observed=True
        ):
            r = g["option_return_ask_to_bid_pct"].dropna()
            m = g["direction_adjusted_underlying_move_pct"].dropna()
            results.append({
                "feature": feature,
                "sample": sample_name,
                "day": day,
                "kind": kind,
                "bin": str(bucket),
                "n": int(len(r)),
                "feature_median": round(float(g[feature].median()), 4),
                "positive_return_pct": round(float((r > 0).mean() * 100), 2),
                "median_option_return_pct": round(float(r.median()), 3),
                "median_underlying_move_pct": round(float(m.median()), 3)
                    if len(m) else None
            })

res = pd.DataFrame(results)
csv_path = out / "option_response_entry_features_5m.csv"
json_path = out / "option_response_entry_features_5m_summary.json"
res.to_csv(csv_path, index=False)

summary = {
    "mode": "READ_ONLY_SHADOW_ANALYSIS",
    "input_rows_5m": int(len(df)),
    "entry_exit_clean_rows_5m": int(df["both_clean"].sum()),
    "features_tested": list(features.keys()),
    "outputs": {"feature_analysis_csv": str(csv_path)},
    "limitations": [
        "Only two trading days are represented.",
        "Feature bins are exploratory, not validated cutoffs.",
        "Quantile bins are calculated from this sample, not a live model.",
        "Repeated symbols and shared market conditions reduce independence.",
        "No strategy, scanner, source data, or paper ledger is modified."
    ]
}
json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("===== SUMMARY =====")
print(json.dumps(summary, indent=2))
print("\n===== ENTRY-FEATURE RESULTS =====")
if len(res):
    print(res.to_string(index=False))
print("\nREAD-ONLY ENTRY FEATURE ANALYSIS COMPLETE")
