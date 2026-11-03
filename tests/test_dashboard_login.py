import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import dashboard_login as dl


class FakeHandler:
    def __init__(self, path="/", method="GET", cookie="", body=b"", ip="192.168.1.5"):
        self.path, self.client_address = path, (ip, 5000)
        self.headers = {"Cookie": cookie, "Content-Length": str(len(body))}
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.status, self.out_headers = None, {}

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.out_headers[k] = v

    def end_headers(self):
        pass


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = dl.CONFIG
        dl.CONFIG = Path(self.tmp.name) / "auth.json"
        dl._CACHE.update(mtime=None, cfg=None, path=None)
        dl._FAILS.clear()
        patcher = mock.patch.object(dl.time, "sleep", lambda s: None)       # the wrong-password delay would only slow the tests
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        dl.CONFIG = self.old
        self.tmp.cleanup()

    def test_password_hash_verify_and_token(self):
        self.assertFalse(dl.is_configured())
        with self.assertRaises(ValueError):
            dl.set_password("short")
        dl.set_password("correct horse")
        self.assertNotIn("correct horse", dl.CONFIG.read_text())              # only a hash is stored
        self.assertTrue(dl.verify("correct horse"))
        self.assertFalse(dl.verify("wrong"))
        tok = dl.make_token()
        self.assertTrue(dl.valid_token(tok))
        self.assertFalse(dl.valid_token(tok[:-2] + "00"))                      # tampered signature
        self.assertFalse(dl.valid_token("1.abc.def"))
        self.assertFalse(dl.valid_token(tok, now=time.time() + 13 * 3600))     # expired
        dl.set_password("another password")                                     # a new password signs every browser out
        self.assertFalse(dl.valid_token(tok))

    def test_gate_is_open_until_a_password_exists(self):
        h = FakeHandler("/journal")
        self.assertFalse(dl.guard(h, "GET"))
        h2 = FakeHandler("/login")
        self.assertTrue(dl.guard(h2, "GET"))
        self.assertEqual((h2.status, h2.out_headers["Location"]), (302, "/"))

    def test_locked_pages_redirect_and_apis_refuse(self):
        dl.set_password("correct horse")
        page = FakeHandler("/journal?d=1")
        self.assertTrue(dl.guard(page, "GET"))
        self.assertEqual(page.status, 302)
        self.assertTrue(page.out_headers["Location"].startswith("/login?next=/journal"))
        api = FakeHandler("/api/snapshot")
        self.assertTrue(dl.guard(api, "GET"))
        self.assertEqual(api.status, 401)
        post = FakeHandler("/api/manual-stop", "POST", body=b"{}")
        self.assertTrue(dl.guard(post, "POST"))
        self.assertEqual(post.status, 401)
        login = FakeHandler("/login")
        self.assertTrue(dl.guard(login, "GET"))
        self.assertEqual(login.status, 200)
        self.assertIn(b"Arjuna", login.wfile.getvalue())
        self.assertNotIn(b"{{", login.wfile.getvalue())
        self.assertNotIn(b"Darpan", login.wfile.getvalue())                       # no personal name unless APLUS_LOGIN_NAME is set
        self.assertIn(b"AI TRADING CORE", login.wfile.getvalue())
        with mock.patch.dict(os.environ, {"APLUS_LOGIN_NAME": "Rahul"}):
            named = FakeHandler("/login")
            dl.guard(named, "GET")
            self.assertIn(b"Rahul", named.wfile.getvalue())

    def test_login_sets_cookie_which_opens_everything(self):
        dl.set_password("correct horse")
        bad = FakeHandler("/api/login", "POST", body=json.dumps({"password": "nope"}).encode())
        self.assertTrue(dl.guard(bad, "POST"))
        self.assertEqual(bad.status, 401)
        good = FakeHandler("/api/login", "POST", body=json.dumps({"password": "correct horse"}).encode())
        self.assertTrue(dl.guard(good, "POST"))
        self.assertEqual(good.status, 200)
        cookie = good.out_headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        jar = cookie.split(";")[0]
        self.assertFalse(dl.guard(FakeHandler("/journal", cookie=jar), "GET"))     # carries on to the normal page
        self.assertFalse(dl.guard(FakeHandler("/api/snapshot", cookie=jar), "GET"))
        again = FakeHandler("/login?next=/journal", cookie=jar)
        self.assertTrue(dl.guard(again, "GET"))
        self.assertEqual(again.out_headers["Location"], "/journal")
        evil = FakeHandler("/login?next=//evil.example", cookie=jar)
        dl.guard(evil, "GET")
        self.assertEqual(evil.out_headers["Location"], "/")                         # no open redirect

    def test_lockout_after_five_failures_and_logout(self):
        dl.set_password("correct horse")
        for _ in range(5):
            dl.guard(FakeHandler("/api/login", "POST", body=b'{"password":"x"}'), "POST")
        locked = FakeHandler("/api/login", "POST", body=json.dumps({"password": "correct horse"}).encode())
        dl.guard(locked, "POST")
        self.assertEqual(locked.status, 429)                                        # even the right password waits
        other = FakeHandler("/api/login", "POST", ip="192.168.1.9", body=json.dumps({"password": "correct horse"}).encode())
        dl.guard(other, "POST")
        self.assertEqual(other.status, 200)                                         # another address is unaffected
        out = FakeHandler("/logout")
        dl.guard(out, "GET")
        self.assertIn("Max-Age=0", out.out_headers["Set-Cookie"])
        status = FakeHandler("/api/auth-status")
        dl.guard(status, "GET")
        self.assertEqual(json.loads(status.wfile.getvalue()), {"configured": True})


if __name__ == "__main__":
    unittest.main()
