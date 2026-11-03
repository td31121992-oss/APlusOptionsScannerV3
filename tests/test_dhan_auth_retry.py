from __future__ import annotations

import unittest
from unittest import mock

import requests

import dhan_auth

GOOD_BODY = {"dhanClientId": "1", "tokenValidity": "31/12/2099 23:59"}


class _Resp:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self) -> dict:
        return self._body


class ProfileRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(dhan_auth.time, "sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_transient_timeouts_then_success_is_valid(self) -> None:
        seq = [requests.Timeout("slow"), requests.ConnectionError("reset"), _Resp(200, GOOD_BODY)]
        with mock.patch.object(dhan_auth.requests, "get", side_effect=seq) as get:
            ok, _ = dhan_auth._profile_valid("1", "tok")
        self.assertTrue(ok)
        self.assertEqual(get.call_count, 3)

    def test_rate_limit_then_success_is_valid(self) -> None:
        seq = [_Resp(429), _Resp(200, GOOD_BODY)]
        with mock.patch.object(dhan_auth.requests, "get", side_effect=seq):
            self.assertTrue(dhan_auth._profile_valid("1", "tok")[0])

    def test_definite_rejection_fails_immediately_without_retry(self) -> None:
        with mock.patch.object(dhan_auth.requests, "get", return_value=_Resp(401)) as get:
            ok, _ = dhan_auth._profile_valid("1", "tok")
        self.assertFalse(ok)
        self.assertEqual(get.call_count, 1)

    def test_persistent_outage_gives_up_after_three_attempts(self) -> None:
        with mock.patch.object(dhan_auth.requests, "get", side_effect=requests.Timeout("down")) as get:
            self.assertFalse(dhan_auth._profile_valid("1", "tok")[0])
        self.assertEqual(get.call_count, 3)

    def test_wrong_client_id_is_invalid(self) -> None:
        with mock.patch.object(dhan_auth.requests, "get", return_value=_Resp(200, {"dhanClientId": "999"})):
            self.assertFalse(dhan_auth._profile_valid("1", "tok")[0])


if __name__ == "__main__":
    unittest.main()
