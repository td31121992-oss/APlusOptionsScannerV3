import json
import unittest
from pathlib import Path

import mobile_app
import trading_mode


class MobileAppTests(unittest.TestCase):
    def test_manifest_is_installable(self):
        m = json.loads(mobile_app.manifest_json())
        self.assertEqual((m["display"], m["start_url"]), ("standalone", "/"))
        self.assertTrue({"192x192", "512x512"} <= {i["sizes"] for i in m["icons"]})
        for icon in m["icons"]:
            self.assertTrue(Path(__file__).resolve().parents[1].joinpath(icon["src"].lstrip("/")).exists())

    def test_service_worker_never_caches_live_data(self):
        sw = mobile_app.SERVICE_WORKER
        self.assertIn("startsWith('/api/')) return", sw)
        self.assertIn("Not connected", sw)

    def test_snippet_registers_only_on_https(self):
        self.assertIn("location.protocol==='https:'", mobile_app.PWA_SNIPPET)
        self.assertIn("/manifest.webmanifest", mobile_app.PWA_SNIPPET)

    def test_proxied_requests_are_not_this_pc(self):
        self.assertEqual(mobile_app.effective_remote({}, "127.0.0.1"), "127.0.0.1")
        self.assertEqual(mobile_app.effective_remote({"Tailscale-User-Login": "me@x"}, "127.0.0.1"), "proxied-remote")
        self.assertEqual(mobile_app.effective_remote({"X-Forwarded-For": "100.1.2.3"}, "127.0.0.1"), "proxied-remote")
        self.assertEqual(mobile_app.effective_remote({}, "192.168.1.5"), "192.168.1.5")

    def test_live_is_refused_for_a_proxied_caller(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok, _state, msg = trading_mode.set_mode("LIVE", confirm="LIVE", remote_addr="proxied-remote", path=Path(tmp, "mode.json"))
        self.assertFalse(ok)
        self.assertIn("Staying in PAPER", msg)


if __name__ == "__main__":
    unittest.main()
