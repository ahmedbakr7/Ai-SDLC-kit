---
id: T-042-01
title: Returns API route
type: backend
status: done
risk: low
depends_on: []
files:
  - app/returns.py
  - app/server.py
shared: []
skills:
  - build
  - backend-patterns
contracts:
  - GET /api/orders/{id}/returns
requirements:
  - F-042-1
  - F-042-2
  - F-042-3
  - F-042-4
acceptance_criteria:
  - "AC-1: GET /api/orders/ord_1/returns answers 200 with order_id and a returns list whose items have id and state"
  - "AC-2: every state in the response is one of requested, approved, rejected, received, refunded"
  - "AC-3: an order with no returns answers 200 with an empty returns list"
  - "AC-4: an unknown order answers 404 with error.code not_found"
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
source_adr:
  - decisions/ADR-0001-stack.md
---

Add the read route and the shared `app/returns.py` module. Register the route in the
route table in `app/server.py` so `tools/routes.py` reports it.
