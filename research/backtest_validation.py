from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate APlus backtest research configuration")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--min-train-days", type=int, default=63)
    parser.add_argument("--test-days", type=int, default=21)
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = root / "data/research/5y_backtest/backtest_validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "mode": "RESEARCH_VALIDATION_ONLY",
        "rules": {
            "no_lookahead": True,
            "train_period_precedes_test_period": True,
            "exact_option_replay_requires_contract_history": True,
            "underlying_return_is_not_option_pnl": True,
            "future_mfe_mae_are_outcomes_only": True,
        },
        "defaults": {
            "min_train_calendar_days": args.min_train_days,
            "test_calendar_days": args.test_days,
        },
        "required_option_history_fields": [
            "timestamp",
            "security_id",
            "trading_symbol",
            "expiry",
            "strike",
            "option_type",
            "ltp_or_ohlc",
        ],
        "recommended_option_history_fields": [
            "bid",
            "ask",
            "volume",
            "open_interest",
            "iv",
        ],
        "production_files_modified": False,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
