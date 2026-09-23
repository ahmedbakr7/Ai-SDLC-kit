---
id: T-042-04
title: Return status evals
type: test
status: ready
risk: low
depends_on:
  - T-042-03
files:
  - evals/returns-status.eval.md
skills:
  - test
contracts: "CONTRACTS.md#GET /v1/orders/{id}/returns"
requirements:
  - F-042-2
  - N-042-1
acceptance_criteria:
  - Fixture covers requested, approved, rejected, received, refunded
  - Fixture covers unknown state → unknown chip
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042.md
source_adr:
  - decisions/ADR-0001-stack.md
---

Eval fixtures only (play=test).
