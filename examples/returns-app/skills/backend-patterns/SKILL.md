---
name: backend-patterns
description: Locked backend patterns for the returns example (route table, error envelope, data access). Load on every backend ticket.
---

# Backend patterns (locked by ADR-0001)

Change only with a superseding ADR.

| Concern | Pattern | Where |
|---|---|---|
| Routing | one `ROUTES` table; every handler registered there | `app/server.py` |
| Errors | `error(status, code, message)` → `{"error": {"code", "message"}}` | `app/server.py` |
| Data access | only through `app/returns.py`; handlers never touch `_ORDERS` | `app/returns.py` |
| Tests | unit: call `dispatch()` directly; integration: real HTTP on port 0 | `app/test_*.py`, `tests/` |

## Rules

- Reuse `error()`; never hand-build an error body.
- A second module that needs returns data imports `app.returns`; it never copies the lookup.
- Every test docstring starts with the AC tag it proves (`T-042-01/AC-1`).
