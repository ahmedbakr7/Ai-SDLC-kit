import unittest

from app import pages, server


class OrderPage(unittest.TestCase):
    def test_lists_returns_with_labels(self) -> None:
        """T-042-02/AC-1"""
        status, ctype, body = server.dispatch("GET", "/orders/ord_1")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "text/html")
        self.assertIn("<h2>Returns</h2>", body)
        self.assertIn("ret_1: Requested", body)
        self.assertIn("ret_2: Refunded", body)

    def test_no_returns_no_heading(self) -> None:
        """T-042-02/AC-2"""
        body = pages.render_order("ord_2")
        self.assertIsNotNone(body)
        self.assertNotIn("Returns", body)

    def test_unknown_state_renders_unknown(self) -> None:
        """T-042-02/AC-3"""
        status, _, body = server.dispatch("GET", "/orders/ord_3")
        self.assertEqual(status, 200)
        self.assertIn("ret_9: Unknown", body)
