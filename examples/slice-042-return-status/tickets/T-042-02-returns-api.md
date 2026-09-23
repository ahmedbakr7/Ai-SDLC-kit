---
id: T-042-02
title: Returns API handler
type: backend
status: done
risk: low
depends_on:
  - T-042-01
files:
  - src/api/orders/returns.ts
skills:
  - build
  - backend-patterns
contracts: "CONTRACTS.md#GET /v1/orders/{id}/returns"
requirements:
  - F-042-1
  - F-042-2
acceptance_criteria:
  - Handler serves GET /v1/orders/{id}/returns with the documented JSON shape
  - States outside the enum are rejected at the boundary
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042.md
source_adr:
  - decisions/ADR-0001-stack.md
---

Implement the read handler only. No new tables.
