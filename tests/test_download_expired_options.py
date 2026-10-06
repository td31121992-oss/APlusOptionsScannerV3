from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import download_expired_options as d

IST = ZoneInfo("Asia/Kolkata")


def night() -> datetime:
    return datetime(2026, 10, 7, 22, 0, tzinfo=IST)          # Wednesday 22:00, outside market hours


class PlanningTests(unittest.TestCase):
    def test_windows_cover_range_newest_first_and_never_exceed_30_days(self) -> None:
        w = d.windows(date(2026, 1, 1), date(2026, 4, 10))
        self.assertEqual(w[0][1], date(2026, 4, 10))                  # newest first
        self.assertEqual(w[-1][0], date(2026, 1, 1))
        for start, end in w:
            self.assertLessEqual((end - start).days + 1, 30)
        flat = sorted(w)
        for (a0, a1), (b0, b1) in zip(flat, flat[1:]):
            self.assertEqual((b0 - a1).days, 1)                       # contiguous, no gaps/overlap

    def test_labels_and_paths(self) -> None:
        self.assertEqual([d.strike_label(o) for o in (-3, 0, 2)], ["ATM-3", "ATM", "ATM+2"])
        p = d.file_for(Path("out"), "TCS", date(2026, 9, 1), 1, "PUT", -2)
        self.assertEqual(p.as_posix(), "out/TCS/2026-09-01/1_PE_ATM-2.json.gz")

    def test_tasks_atm_first_and_skip_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            wins = d.windows(date(2026, 9, 1), date(2026, 9, 30))
            first = next(d.tasks(out, {"TCS": 11536}, wins, [1], 2))
            self.assertEqual((first["offset"], first["side"]), (0, "CALL"))
            d.write_atomic_gz(first["path"], {"x": 1})
            again = next(d.tasks(out, {"TCS": 11536}, wins, [1], 2))
            self.assertNotEqual((again["offset"], again["side"]), (0, "CALL"))     # stored one is skipped
            total = sum(1 for _ in d.tasks(out, {"TCS": 11536}, wins, [1], 2))
            self.assertEqual(total, 1 * 2 * 5 - 1)                                  # 2 sides x 5 strikes, minus the stored one

    def test_request_body(self) -> None:
        t = {"security_id": 2885, "exp_code": 1, "offset": 3, "side": "CALL", "from": date(2026, 9, 1), "to": date(2026, 9, 30)}
        b = d.build_body(t)
        self.assertEqual((b["strike"], b["drvOptionType"], b["instrument"], b["securityId"]), ("ATM+3", "CALL", "OPTSTK", 2885))
        self.assertIn("oi", b["requiredData"])
        self.assertIn("iv", b["requiredData"])


class SafetyTests(unittest.TestCase):
    def test_rate_limiter_spaces_calls(self) -> None:
        t = {"now": 0.0}
        sleeps = []
        lim = d.RateLimiter(2.0, clock=lambda: t["now"], sleep=lambda s: (sleeps.append(round(s, 3)), t.__setitem__("now", t["now"] + s)))
        for _ in range(4):
            lim.wait()
        self.assertEqual(sleeps, [0.5, 0.5, 0.5])

    def test_market_pause_only_on_weekday_market_hours(self) -> None:
        self.assertTrue(d.in_market_pause(datetime(2026, 10, 7, 10, 0, tzinfo=IST)))
        self.assertFalse(d.in_market_pause(datetime(2026, 10, 7, 8, 59, tzinfo=IST)))
        self.assertFalse(d.in_market_pause(datetime(2026, 10, 7, 15, 45, tzinfo=IST)))
        self.assertFalse(d.in_market_pause(datetime(2026, 10, 10, 11, 0, tzinfo=IST)))    # Saturday

    def test_fetch_retries_rate_limit_then_succeeds(self) -> None:
        class R:
            def __init__(self, code, body=None): self.status_code, self._b, self.text = code, body or {}, ""
            def json(self): return self._b
        seq = [R(429), R(503), R(200, {"data": {"ce": {"timestamp": [1]}}})]
        sess = mock.Mock(); sess.post.side_effect = seq
        sleeps = []
        res = d.fetch(sess, {}, {}, sleep=sleeps.append)
        self.assertEqual(res["status"], 200)
        self.assertEqual(sess.post.call_count, 3)
        self.assertEqual(sleeps, [10, 20])                                  # backs off

    def test_fetch_auth_failure_raises(self) -> None:
        class R:
            status_code, text = 401, ""
            def json(self): return {}
        sess = mock.Mock(); sess.post.return_value = R()
        with self.assertRaises(d.AuthError):
            d.fetch(sess, {}, {}, sleep=lambda s: None)


class RunTests(unittest.TestCase):
    def _args(self, tmp, *extra):
        return d.parse_args(["--out", tmp, "--since", "2026-09-01", "--until", "2026-09-30", "--strikes", "1", "--rps", "1000", *extra])

    def _session(self, status_by_side):
        class R:
            def __init__(self, code, body): self.status_code, self._b, self.text = code, body, ""
            def json(self): return self._b
        def post(url, headers=None, json=None, timeout=None):
            side = "ce" if json["drvOptionType"] == "CALL" else "pe"
            code, n = status_by_side[json["drvOptionType"]]
            body = {"data": {side: {"timestamp": list(range(n))}, ("pe" if side == "ce" else "ce"): None}}
            return R(code, body)
        s = mock.Mock(); s.post.side_effect = post
        return s

    def test_stores_data_empty_and_error_markers_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(d, "load_universe", return_value={"TCS": 11536}):
            sess = self._session({"CALL": (200, 5), "PUT": (200, 0)})
            stats = d.run(self._args(tmp), session=sess, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            self.assertEqual(stats["calls"], 6)                              # 2 sides x 3 strikes
            self.assertEqual((stats["with_data"], stats["empty"]), (3, 3))
            f = Path(tmp, "TCS", "2026-09-01", "1_CE_ATM.json.gz")
            with gzip.open(f, "rt", encoding="utf-8") as h:
                saved = json.load(h)
            self.assertEqual(saved["candles"], 5)
            self.assertTrue(Path(tmp, "TCS", "2026-09-01", "1_PE_ATM+1.json.gz").exists())   # empty response still recorded
            again = d.run(self._args(tmp), session=sess, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            self.assertEqual(again["calls"], 0)                              # fully resumable

    def test_bad_request_marker_and_transient_errors_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(d, "load_universe", return_value={"TCS": 1}):
            s400 = self._session({"CALL": (400, 0), "PUT": (400, 0)})
            st = d.run(self._args(tmp), session=s400, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            self.assertEqual(st["errors"], 6)
            self.assertEqual(len(list(Path(tmp).rglob("*.json.gz"))), 6)     # 400s are remembered, never retried
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(d, "load_universe", return_value={"TCS": 1}):
            s500 = self._session({"CALL": (500, 0), "PUT": (500, 0)})
            st = d.run(self._args(tmp, "--max-calls", "2"), session=s500, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            self.assertEqual(len(list(Path(tmp).rglob("*.json.gz"))), 0)     # transient failures retried by a later run

    def test_max_calls_and_market_hours_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(d, "load_universe", return_value={"TCS": 1}):
            sess = self._session({"CALL": (200, 1), "PUT": (200, 1)})
            st = d.run(self._args(tmp, "--max-calls", "2"), session=sess, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            self.assertEqual(st["calls"], 2)
            slept = []
            midday = lambda: datetime(2026, 10, 7, 11, 0, tzinfo=IST)
            calls = {"n": 0}
            def now_seq():
                calls["n"] += 1
                return midday() if calls["n"] <= 2 else night()              # market hours first, then after close
            st2 = d.run(self._args(tmp, "--max-calls", "1"), session=sess, headers_factory=lambda: {}, now_fn=now_seq, sleep=slept.append)
            self.assertTrue(slept and slept[0] >= 60)                         # paused instead of calling Dhan at 11:00
            self.assertEqual(st2["calls"], 1)

    def test_progress_file_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(d, "load_universe", return_value={"TCS": 1}):
            sess = self._session({"CALL": (200, 2), "PUT": (200, 0)})
            d.run(self._args(tmp), session=sess, headers_factory=lambda: {}, now_fn=night, sleep=lambda s: None)
            prog = json.loads(Path(tmp, "_progress.json").read_text(encoding="utf-8"))
            self.assertEqual(prog["planned_total"], 6)
            self.assertEqual(prog["stored_total"], 6)
            self.assertEqual(prog["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
