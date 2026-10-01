---
id: plan-042
title: Return status on the order page
status: accepted
source_spec: design/spec-042-return-status.md
---

# Plan 042: return status

## Contracts

- New route `GET /api/orders/{id}/returns` (CONTRACTS.md). Read-only; no new tables or events.
- New page `/orders/{id}`.

## Shared modules

Code more than one ticket uses. The first ticket that needs a module creates it; later tickets list it in `files:` or `shared:`.

| Module | Owner ticket | Purpose |
|---|---|---|
| `app/returns.py` | T-042-01 | read returns for an order; the only place that knows the data source |
| `app/server.py` | T-042-01 | route table + error envelope |

## File map

| File | Ticket |
|---|---|
| `app/returns.py`, `app/server.py` | T-042-01 |
| `app/pages.py` | T-042-02 |

## Test strategy

- Unit (build): handler and rendering functions, tagged `T-042-0n/AC-n`.
- Integration (test): real HTTP against `app/server.py` on a free port.
- Smoke (gate): every route and page in CONTRACTS answers on a running server.

## Ticket cuts

1. T-042-01 API route (backend). Unblocks the page.
2. T-042-02 order page (frontend), depends on T-042-01.

## Rollback

Read-only feature: revert the PR. No data migration.
