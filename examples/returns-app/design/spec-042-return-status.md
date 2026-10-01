---
id: spec-042
title: Return status on the order page
status: accepted
source_intent: intent/intent-042-return-status.md
---

# Spec 042: return status

## Requirements

Each requirement is one observable, testable statement.

- **F-042-1** `GET /api/orders/{id}/returns` answers 200 with every return on the order, each with `id` and `state`.
- **F-042-2** `state` is one of `requested`, `approved`, `rejected`, `received`, `refunded`.
- **F-042-3** An order with no returns answers 200 with `"returns": []`.
- **F-042-4** An unknown order answers 404 with the standard error envelope.
- **F-042-5** The order page `/orders/{id}` lists each return with a human label for its state.
- **F-042-6** The order page shows no returns section when the order has no returns.
- **N-042-1** A state the page does not recognise is shown as "Unknown" instead of failing the page.

## Pages

- `design/pages/order.md`

## Open

None.
