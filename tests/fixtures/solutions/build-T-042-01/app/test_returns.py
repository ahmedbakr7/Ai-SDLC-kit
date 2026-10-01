import json
import unittest

from app import returns, server


class ReturnsApi(unittest.TestCase):
    def test_lists_returns_with_id_and_state(self) -> None:
        """T-042-01/AC-1"""
        status, ctype, body = server.dispatch("GET", "/api/orders/ord_1/returns")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        self.assertEqual(data["order_id"], "ord_1")
        self.assertEqual([r["id"] for r in data["returns"]], ["ret_1", "ret_2"])
        self.assertTrue(all(set(r) == {"id", "state"} for r in data["returns"]))

    def test_states_are_from_the_contract_enum(self) -> None:
        """T-042-01/AC-2"""
        _, _, body = server.dispatch("GET", "/api/orders/ord_1/returns")
        for r in json.loads(body)["returns"]:
            self.assertIn(r["state"], returns.STATES)

    def test_no_returns_is_an_empty_list(self) -> None:
        """T-042-01/AC-3"""
        status, _, body = server.dispatch("GET", "/api/orders/ord_2/returns")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["returns"], [])

    def test_unknown_order_is_404_not_found(self) -> None:
        """T-042-01/AC-4"""
        status, _, body = server.dispatch("GET", "/api/orders/nope/returns")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
