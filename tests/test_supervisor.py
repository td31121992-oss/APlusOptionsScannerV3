import csv
import json
import tempfile
import unittest
from pathlib import Path

import supervisor_facts as sf
import supervisor_notify as sn


class NotifyTests(unittest.TestCase):
    def test_only_the_telegram_summary_section_is_sent_and_trimmed(self):
        text = "# Review\n\nlong text\n\n## Telegram summary\n\nLine one\nLine two\n\n## Notes\n\nnot sent\n"
        self.assertEqual(sn.summary_of(text), "Line one\nLine two")
        self.assertEqual(sn.summary_of("no such section"), "")
        self.assertLessEqual(len(sn.summary_of("## Telegram summary\n" + "x" * 5000)), sn.MAX_CHARS)


class FactsTests(unittest.TestCase):
    def test_scanner_day_counts_starts_cycles_failures_and_dhan_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "scanner.log").write_text("\n".join([
                "2026-11-11 09:11:04 | INFO | x | MainThread | Continuous Intraday Movement Scanner started: 09:15-15:30",
                "2026-11-11 09:16:00 | INFO | x | MainThread | Intraday movement cycle phase=OPENING",
                "2026-11-11 09:17:00 | INFO | x | MainThread | Intraday movement cycle phase=OPENING",
                "2026-11-11 09:18:00 | ERROR | x | MainThread | Intraday market-data cycle failed category=ConnectTimeout",
                "2026-11-11 09:19:00 | WARNING | x | MainThread | Upstox quotes failed, using Dhan: RuntimeError",
                "2026-11-11 09:20:00 | INFO | core.market_data | MainThread | Market data provider: UPSTOX only (no Dhan)",
                "2026-11-10 09:11:04 | INFO | x | MainThread | Continuous Intraday Movement Scanner started"]), encoding="utf-8")
            d = sf.scanner_day("2026-11-11", root)
            self.assertEqual((d["scanner_starts"], d["cycles"], d["failed_cycles"], d["network_errors"], d["dhan_mentions"]), (["09:11:04"], 2, 1, 1, 1))

    def test_trades_day_and_history(self):
        t = lambda i, day, net, mfe, reason="SESSION_END": {"paper_trade_id": i, "symbol": "ABB", "option_type": "CE", "status": "CLOSED", "entry_time": f"{day}T10:00:00",      # noqa: E731
                                                              "net_pnl": net, "mfe_amount": mfe, "exit_reason": reason}
        hist = [t("a", "2026-11-11", 1000.0, 3500.0), t("b", "2026-11-11", -500.0, 0.0, "OPTION_STOP_LOSS"), t("c", "2026-11-10", -200.0, 100.0)]
        d = sf.trades_day("2026-11-11", hist)
        self.assertEqual((d["closed"], d["net"], d["winners"], d["losers"], d["never_in_profit"], d["touched_3k"]), (2, 500, 1, 1, 1, 1))
        h = sf.history_summary(hist, "2026-11-11")
        self.assertEqual((h["sessions_total"], h["net_total"]), (2, 300))

    def test_variant_status_counts_only_days_after_registration_and_keeps_the_pass_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "trade_archive").mkdir(parents=True)
            with (root / "data" / "trade_archive" / "exit_variants.csv").open("w", encoding="utf-8", newline="") as h:
                w = csv.writer(h)
                w.writerow(["day", "variant", "trades", "real_net", "variant_net"])
                w.writerow(["2026-11-09", "dx_x_wide25", 40, -100, 5000])                              # before registration: ignored
                for i in range(1, 11):
                    w.writerow([f"2026-11-{10 + i}", "dx_x_wide25", 12, 0, 100 if i <= 7 else -50])    # 10 forward sessions, 7 of them better
            exp = {"id": "V01", "kind": "variant", "key": "dx_x_wide25", "registered": "2026-11-10"}
            r = sf.variant_status(exp, root)
            self.assertEqual((r["forward_sessions"], r["forward_trades"], r["positive_days"], r["change"]), (10, 120, 7, 550))
            self.assertEqual(r["status"], "READY: meets the pass mark")
            self.assertEqual(sf.variant_status({**exp, "registered": "2026-11-18"}, root)["status"], "COLLECTING")

    def test_experiments_file_lists_every_experiment_with_a_key_and_a_registration_day(self):
        data = json.loads((sf.ROOT / "ai_supervisor" / "experiments.json").read_text(encoding="utf-8"))
        for e in data["experiments"]:
            self.assertTrue(e["key"] and e["registered"] and e["kind"] in ("gate", "variant"))


if __name__ == "__main__":
    unittest.main()
