---
id: T-042-01
title: Document returns contract
type: contract
status: done
risk: low
depends_on: []
files:
  - arch/CONTRACTS.md
skills:
  - architect
contracts: "CONTRACTS.md#GET /v1/orders/{id}/returns"
requirements:
  - F-042-1
acceptance_criteria:
  - GET /v1/orders/{id}/returns and state enum are present in arch/CONTRACTS.md
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042.md
source_adr:
  - decisions/ADR-0001-stack.md
---

Lock the public seam before FE/BE consumers.
