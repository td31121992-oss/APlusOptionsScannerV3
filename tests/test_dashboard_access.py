from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import dashboard_access as da


class AccessTests(unittest.TestCase):
    def test_lan_mode(self) -> None:
        for ip in ("127.0.0.1", "::1", "192.168.1.20", "10.0.0.5", "172.16.4.4", "172.31.255.1", "169.254.1.1",
                   "100.64.1.2", "::ffff:192.168.1.5", "fe80::1%eth0", "fd00::5"):
            self.assertTrue(da.is_allowed(ip, "lan"), ip)
        for ip in ("8.8.8.8", "203.0.113.9", "172.32.0.1", "100.128.0.1", "2001:4860:4860::8888", "not-an-ip", ""):
            self.assertFalse(da.is_allowed(ip, "lan"), ip)

    def test_local_mode_is_loopback_only(self) -> None:
        self.assertTrue(da.is_allowed("127.0.0.1", "local"))
        self.assertTrue(da.is_allowed("::1", "local"))
        self.assertFalse(da.is_allowed("192.168.1.20", "local"))

    def test_any_mode_and_defaults(self) -> None:
        self.assertTrue(da.is_allowed("8.8.8.8", "any"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APLUS_DASHBOARD_ACCESS", None)
            self.assertEqual(da.access_mode(), "lan")
        with mock.patch.dict(os.environ, {"APLUS_DASHBOARD_ACCESS": "nonsense"}):
            self.assertEqual(da.access_mode(), "lan")


class ServerGuardTests(unittest.TestCase):
    def _server(self):
        import aplus_live_pnl_dashboard as dash

        server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_loopback_client_allowed_by_default(self) -> None:
        port = self._server()
        self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=20).status, 200)

    def test_disallowed_client_gets_403(self) -> None:
        port = self._server()
        with mock.patch.object(da, "is_allowed", return_value=False):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=20)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
