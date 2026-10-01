"""Read returns for an order. The only module that knows where returns come from."""
from __future__ import annotations

STATES = ("requested", "approved", "rejected", "received", "refunded")

# Stand-in for the returns projection (ADR-0001: no database in the example).
_ORDERS: dict[str, list[dict[str, str]]] = {
    "ord_1": [{"id": "ret_1", "state": "requested"}, {"id": "ret_2", "state": "refunded"}],
    "ord_2": [],
    "ord_3": [{"id": "ret_9", "state": "lost_in_space"}],
}


def returns_for(order_id: str) -> list[dict[str, str]] | None:
    """Returns on the order, or None when the order does not exist."""
    rows = _ORDERS.get(order_id)
    return None if rows is None else [dict(r) for r in rows]
