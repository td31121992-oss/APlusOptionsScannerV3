import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import agent_baseline as ab
import agent_judge as aj
import agent_packet as ap
import agent_run as ar


def trade(i, day="2026-11-11", hhmm="10:05", net=-500.0, **kw):
    base = {"paper_trade_id": i, "symbol": "ABB", "option_type": "CE", "status": "CLOSED", "entry_time": f"{day}T{hhmm}:00", "expiry": "2026-11-24", "setup_family": "HEALTHY_PULLBACK",
            "spread_percent": 1.2, "entry_price": 10.0, "momentum_score": 71.234567, "net_pnl": net, "mfe_amount": 2000.0, "exit_reason": "OPTION_STOP_LOSS",
            # hindsight fields that must never reach the agent
            "highest_option_price": 13.0, "exit_price": 8.0, "opt5": "HELD", "dx_mom5_block": False, "dx_x_wide25": 5000.0, "shadow_ladder_exit_price": 12.0, "stock_move_fav_pct": 0.6}
    base.update(kw)
    return base


class PacketTests(unittest.TestCase):
    def test_only_entry_time_facts_get_in_and_numbers_are_rounded(self):
        p = ap.packet(trade("a", dx_rvol=2.4, dx_lag_min=12, dx_s945_block=False), {"ABB": "Capital Goods"})
        self.assertEqual(p["symbol"], "ABB")
        self.assertEqual((p["entry_minute"], p["weekday"], p["days_to_expiry"], p["sector"]), ("10:05", "Wednesday", 13, "Capital Goods"))
        self.assertEqual((p["opening_volume_x"], p["minutes_since_first_signal"], p["sector_in_0945_picks"]), (2.4, 12, True))
        self.assertEqual(p["momentum_score"], 71.235)
        for k in ("highest_option_price", "exit_price", "opt5", "dx_mom5_block", "dx_x_wide25", "shadow_ladder_exit_price", "stock_move_fav_pct", "net_pnl", "mfe_amount", "exit_reason"):
            self.assertNotIn(k, p)
        self.assertEqual(ap.forbidden(p), [])

    def test_a_hindsight_key_is_detected_and_the_digest_is_stable(self):
        self.assertEqual(ap.forbidden({"symbol": "A", "mfe_amount": 1, "opt5": "HELD", "exit_price": 2}), ["exit_price", "mfe_amount", "opt5"])
        self.assertEqual(ap.digest({"a": 1, "b": 2}), ap.digest({"b": 2, "a": 1}))

    def test_early_entries_do_not_claim_a_0945_sector_pick(self):
        self.assertNotIn("sector_in_0945_picks", ap.packet(trade("a", hhmm="09:30", dx_s945_block=True)))


class FakeClient:
    def __init__(self, text=None, stop="end_turn", raises=None, usage=None):
        self.calls = []
        self.messages = self
        self._text, self._stop, self._raises = text, stop, raises
        self._usage = usage or SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0)

    def create(self, **kw):
        self.calls.append(kw)
        if self._raises:
            raise self._raises
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)], stop_reason=self._stop, usage=self._usage)


class JudgeTests(unittest.TestCase):
    P = {"symbol": "ABB", "spread_percent": 0.8}

    def test_mock_skips_wide_spreads_quiet_openings_and_early_entries(self):
        j = aj.MockJudge()
        self.assertEqual(j.decide({"spread_percent": 0.8, "opening_volume_x": 1.4, "entry_minute": "10:05"})["decision"], "TAKE")
        r = j.decide({"spread_percent": 2.0, "opening_volume_x": 0.5, "entry_minute": "09:30"})
        self.assertEqual(r["decision"], "SKIP")
        self.assertIn("spread", r["reason"])

    def test_claude_answer_is_parsed_and_the_request_is_built_as_documented(self):
        client = FakeClient(json.dumps({"decision": "skip", "p_win": 0.22, "reason": "spread 2%"}))
        d = aj.ClaudeJudge(model="claude-sonnet-5-5", client=client).decide(self.P, {"n": 100, "win_pct": 33, "avg_win": 3700, "avg_loss": -2400, "never_pct": 18})
        self.assertEqual((d["decision"], d["p_win"]), ("SKIP", 0.22))
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-sonnet-5-5")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertIn("100 earlier trades", call["system"][0]["text"])
        self.assertEqual(call["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("thinking", call)                                            # Sonnet 5.5: omit it (adaptive); "disabled" would be a 400
        self.assertAlmostEqual(d["usd"], (1000 * 2.0 + 100 * 10.0) / 1e6)

    def test_refusal_bad_json_out_of_range_and_exceptions_become_errors_never_raised(self):
        self.assertEqual(aj.ClaudeJudge(client=FakeClient("{}", stop="refusal")).decide(self.P)["decision"], "ERROR")
        self.assertEqual(aj.ClaudeJudge(client=FakeClient("not json")).decide(self.P)["decision"], "ERROR")
        self.assertEqual(aj.ClaudeJudge(client=FakeClient(json.dumps({"decision": "TAKE", "p_win": 1.7, "reason": "x"}))).decide(self.P)["decision"], "ERROR")
        self.assertEqual(aj.ClaudeJudge(client=FakeClient(raises=RuntimeError("boom"))).decide(self.P)["decision"], "ERROR")

    def test_daily_cap_stops_further_calls(self):
        client = FakeClient(json.dumps({"decision": "TAKE", "p_win": 0.4, "reason": "ok"}))
        j = aj.ClaudeJudge(client=client, daily_cap_usd=0.0001)
        self.assertEqual(j.decide(self.P)["decision"], "TAKE")                        # the first call is allowed and goes over the cap
        second = j.decide(self.P)
        self.assertEqual((second["decision"], second["stop_reason"]), ("ERROR", "cap"))
        self.assertEqual(len(client.calls), 1)


class RunAndGradeTests(unittest.TestCase):
    def trades(self):
        return [trade("a", "2026-11-09", net=1000.0), trade("b", "2026-11-09", net=-3000.0, spread_percent=2.5), trade("c", "2026-11-10", net=2000.0), trade("d", "2026-11-10", net=-4000.0, spread_percent=3.0)]

    def test_run_judges_once_with_base_rates_from_earlier_days_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self.trades()
            first = ar.run(aj.MockJudge(), trades, ["2026-11-10"], root=root, workers=1)
            self.assertEqual((first["judged"], first["take"], first["skip"]), (2, 1, 1))
            again = ar.run(aj.MockJudge(), trades, ["2026-11-10"], root=root, workers=1)
            self.assertEqual(again["candidates"], 0)                                   # already in the ledger
            self.assertEqual(len(ar.read_ledger(root)), 2)
            stats = ar.base_stats(trades, "2026-11-10")
            self.assertEqual((stats["n"], round(stats["win_pct"])), (2, 50))            # only the 9 Nov trades

    def test_grade_compares_take_and_skip_and_what_enforcing_would_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self.trades()
            ar.run(aj.MockJudge(), trades, None, root=root, workers=1)
            text = ar.grade("mock", trades, root)
            self.assertIn("| TAKE | 2 |", text)
            self.assertIn("| SKIP | 2 |", text)
            self.assertIn("Rs +7,000", text)                                            # skipping -3,000 and -4,000 would have added 7,000

    def test_auc(self):
        self.assertEqual(ar.auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]), 1.0)
        self.assertEqual(ar.auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]), 0.0)
        self.assertIsNone(ar.auc([0.5, 0.6], [True, True]))
        self.assertEqual(ab.auc([0.5, 0.5], [True, False]), 0.5)


if __name__ == "__main__":
    unittest.main()
