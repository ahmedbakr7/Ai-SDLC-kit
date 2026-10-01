"""Integration: the order page over real HTTP (test play owns this folder)."""
import threading
import unittest
import urllib.request

from app.server import Handler, Server


class OrderPageOverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read().decode("utf-8")

    def test_page_lists_returns_at_the_contract_path(self) -> None:
        """T-042-02/AC-1"""
        status, body = self.get("/orders/ord_1")
        self.assertEqual(status, 200)
        self.assertIn("<h2>Returns</h2>", body)
        self.assertIn("ret_2: Refunded", body)

    def test_unknown_state_over_http(self) -> None:
        """T-042-02/AC-3"""
        status, body = self.get("/orders/ord_3")
        self.assertEqual(status, 200)
        self.assertIn("ret_9: Unknown", body)
