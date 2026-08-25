"""
report_engine.py

Generate JSON, CSV and Excel reports, including executable option contracts.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font

from analytics.models import RankedStock, TradeRecommendation


class ReportEngine:
    def __init__(self, output_dir: str | Path = "data/reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        rankings: list[RankedStock],
        recommendations: list[TradeRecommendation],
    ) -> None:
        self._write_json(rankings, recommendations)
        self._write_rankings_csv(rankings)
        self._write_recommendations_csv(recommendations)
        self._write_excel(rankings, recommendations)

    def _write_json(
        self,
        rankings: list[RankedStock],
        recommendations: list[TradeRecommendation],
    ) -> None:
        payload = {
            "rankings": [asdict(item) for item in rankings],
            "recommendations": [
                asdict(item) for item in recommendations
            ],
        }
        self._atomic_text(
            self.output_dir / "scanner_report.json",
            json.dumps(
                payload,
                indent=4,
                ensure_ascii=False,
                default=str,
            ),
        )

    def _write_rankings_csv(
        self,
        rankings: list[RankedStock],
    ) -> None:
        path = self.output_dir / "rankings.csv"
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "Rank",
                "Symbol",
                "Score",
                "Bias",
                "Recommendation",
                "Confidence",
            ])
            for item in rankings:
                writer.writerow([
                    item.rank,
                    item.symbol,
                    round(item.score, 2),
                    self._enum_value(item.signal.bias),
                    self._enum_value(item.signal.recommendation),
                    round(item.signal.confidence, 2),
                ])
        os.replace(temporary, path)

    def _write_recommendations_csv(
        self,
        recommendations: list[TradeRecommendation],
    ) -> None:
        path = self.output_dir / "recommendations.csv"
        temporary = path.with_suffix(path.suffix + ".tmp")
        headers = self._recommendation_headers()

        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for item in recommendations:
                writer.writerow(self._recommendation_row(item))
        os.replace(temporary, path)

    def _write_excel(
        self,
        rankings: list[RankedStock],
        recommendations: list[TradeRecommendation],
    ) -> None:
        workbook = Workbook()
        ranking_sheet = workbook.active
        ranking_sheet.title = "Rankings"
        ranking_headers = [
            "Rank",
            "Symbol",
            "Score",
            "Bias",
            "Recommendation",
            "Confidence",
        ]
        ranking_sheet.append(ranking_headers)
        self._bold_header(ranking_sheet)

        for item in rankings:
            ranking_sheet.append([
                item.rank,
                item.symbol,
                round(item.score, 2),
                self._enum_value(item.signal.bias),
                self._enum_value(item.signal.recommendation),
                round(item.signal.confidence, 2),
            ])

        option_sheet = workbook.create_sheet("Option Recommendations")
        headers = self._recommendation_headers()
        option_sheet.append(headers)
        self._bold_header(option_sheet)
        for item in recommendations:
            row = self._recommendation_row(item)
            option_sheet.append([row[header] for header in headers])

        for sheet in (ranking_sheet, option_sheet):
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            self._autosize(sheet)

        path = self.output_dir / "rankings.xlsx"
        temporary = path.with_suffix(".xlsx.tmp")
        workbook.save(temporary)
        os.replace(temporary, path)

    @staticmethod
    def _recommendation_headers() -> list[str]:
        return [
            "Symbol",
            "Underlying Recommendation",
            "Confidence",
            "Underlying Entry",
            "Underlying Stop",
            "Underlying Target1",
            "Underlying Target2",
            "Underlying Target3",
            "Option Transaction",
            "Option Type",
            "Option Security ID",
            "Exchange Segment",
            "Trading Symbol",
            "Display Name",
            "Expiry",
            "Strike",
            "Option LTP",
            "Bid",
            "Ask",
            "Limit Price",
            "Option Stop",
            "Option Target1",
            "Option Target2",
            "Option Target3",
            "Lot Size",
            "Lots",
            "Quantity",
            "Premium Per Lot",
            "Total Premium",
            "Risk Per Lot",
            "Total Risk",
            "OI",
            "Volume",
            "IV",
            "Spread Percent",
            "Selection Score",
            "Selection Reason",
            "Safety Decision",
            "Safety Block Reasons",
            "Safety Warnings",
            "Safety Mode",
            "Safety Account Capital",
            "Safety Available Balance",
            "Safety Open Positions",
            "Safety Realized PnL Today",
            "Estimated Round Trip Cost",
            "Expected Gross Reward",
            "Expected Net Reward",
            "Net Reward Cost Multiple",
            "Net Reward Risk Ratio",
        ]

    @classmethod
    def _recommendation_row(
        cls,
        item: TradeRecommendation,
    ) -> dict[str, Any]:
        option = item.option_contract
        base = {
            "Symbol": item.symbol,
            "Underlying Recommendation": cls._enum_value(
                item.recommendation
            ),
            "Confidence": item.confidence,
            "Underlying Entry": item.entry,
            "Underlying Stop": item.stop_loss,
            "Underlying Target1": item.target1,
            "Underlying Target2": item.target2,
            "Underlying Target3": item.target3,
        }

        if option is None:
            for header in cls._recommendation_headers()[8:]:
                base[header] = ""
            return base

        base.update({
            "Option Transaction": option.transaction,
            "Option Type": option.option_type,
            "Option Security ID": option.security_id,
            "Exchange Segment": option.exchange_segment,
            "Trading Symbol": option.trading_symbol,
            "Display Name": option.display_name,
            "Expiry": option.expiry,
            "Strike": option.strike,
            "Option LTP": option.ltp,
            "Bid": option.bid,
            "Ask": option.ask,
            "Limit Price": option.limit_price,
            "Option Stop": option.stop_loss,
            "Option Target1": option.target1,
            "Option Target2": option.target2,
            "Option Target3": option.target3,
            "Lot Size": option.lot_size,
            "Lots": option.lots,
            "Quantity": option.quantity,
            "Premium Per Lot": option.premium_per_lot,
            "Total Premium": option.total_premium,
            "Risk Per Lot": option.risk_per_lot,
            "Total Risk": option.total_risk,
            "OI": option.oi,
            "Volume": option.volume,
            "IV": option.iv,
            "Spread Percent": option.spread_percent,
            "Selection Score": option.selection_score,
            "Selection Reason": option.selection_reason,
        })

        safety = item.safety_gate or {}
        base.update({
            "Safety Decision": safety.get("decision", ""),
            "Safety Block Reasons": "; ".join(
                safety.get("block_reasons", []) or []
            ),
            "Safety Warnings": "; ".join(
                safety.get("warnings", []) or []
            ),
            "Safety Mode": safety.get("mode", ""),
            "Safety Account Capital": safety.get(
                "account_capital", ""
            ),
            "Safety Available Balance": safety.get(
                "available_balance", ""
            ),
            "Safety Open Positions": safety.get(
                "open_positions", ""
            ),
            "Safety Realized PnL Today": safety.get(
                "realized_pnl_today", ""
            ),
            "Estimated Round Trip Cost": safety.get(
                "estimated_round_trip_cost", ""
            ),
            "Expected Gross Reward": safety.get(
                "expected_gross_reward", ""
            ),
            "Expected Net Reward": safety.get(
                "expected_net_reward", ""
            ),
            "Net Reward Cost Multiple": safety.get(
                "net_reward_cost_multiple", ""
            ),
            "Net Reward Risk Ratio": safety.get(
                "net_reward_risk_ratio", ""
            ),
        })
        return base

    @staticmethod
    def _enum_value(value: Any) -> str:
        raw = getattr(value, "value", value)
        return str(raw)

    @staticmethod
    def _bold_header(sheet) -> None:
        for cell in sheet[1]:
            cell.font = Font(bold=True)

    @staticmethod
    def _autosize(sheet) -> None:
        for column_cells in sheet.columns:
            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )
            sheet.column_dimensions[
                column_cells[0].column_letter
            ].width = min(max_length + 2, 45)

    @staticmethod
    def _atomic_text(path: Path, text: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)


__all__ = ["ReportEngine"]
