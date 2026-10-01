"""Integration: the returns route over real HTTP (test play owns this folder)."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import Handler


class ReturnsOverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_route_is_mounted_at_the_contract_path(self) -> None:
        """T-042-01/AC-1"""
        status, data = self.get("/api/orders/ord_1/returns")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["returns"]), 2)

    def test_unknown_order_over_http(self) -> None:
        """T-042-01/AC-4"""
        status, data = self.get("/api/orders/nope/returns")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "not_found")
