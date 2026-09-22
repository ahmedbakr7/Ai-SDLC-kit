---
id: T-042-03
title: Orders detail returns block
type: frontend
status: in_review
risk: low
depends_on:
  - T-042-01
  - T-042-02
files:
  - src/ui/orders/ReturnsBlock.tsx
  - src/ui/orders/ReturnChip.tsx
skills:
  - build
  - frontend-patterns
contracts: "CONTRACTS.md#GET /v1/orders/{id}/returns"
requirements:
  - F-042-1
  - F-042-2
  - F-042-3
  - N-042-1
acceptance_criteria:
  - Returns block renders one chip per return when the list is non-empty
  - Returns block is omitted when returns is []
  - Unknown state renders as unknown without throwing
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042.md
source_adr:
  - decisions/ADR-0001-stack.md
---

UI-only. Call the contracted endpoint; do not invent fields.
