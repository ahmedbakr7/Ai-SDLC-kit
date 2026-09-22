---
id: spec-042
title: Return status on order detail
status: accepted
source_intent: intent/intent-042-return-status.md
---

# Spec 042 — return status

## Requirements

- **F-042-1** Order detail shows a returns block when `GET /v1/orders/{id}/returns` returns one or more returns.
- **F-042-2** Each return shows state in `{ requested, approved, rejected, received, refunded }`.
- **F-042-3** Empty returns list hides the returns block (no empty chrome).
- **N-042-1** Unknown state from API is shown as `unknown` and logged; UI does not crash.

## Open

None for this slice.
