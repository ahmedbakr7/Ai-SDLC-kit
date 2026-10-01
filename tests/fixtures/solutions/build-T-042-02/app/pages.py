"""Server-rendered pages (frontend-patterns)."""
from __future__ import annotations

import html

from app import returns

LABELS = {
    "requested": "Requested",
    "approved": "Approved",
    "rejected": "Rejected",
    "received": "Received",
    "refunded": "Refunded",
}


def state_label(state: str) -> str:
    return LABELS.get(state, "Unknown")


def render_order(order_id: str) -> str | None:
    """HTML for /orders/{id}, or None when the order does not exist."""
    rows = returns.returns_for(order_id)
    if rows is None:
        return None
    parts = [f"<h1>Order {html.escape(order_id)}</h1>"]
    if rows:
        parts.append("<h2>Returns</h2><ul>")
        for r in rows:
            parts.append(f"<li>{html.escape(r['id'])}: {html.escape(state_label(r['state']))}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
