---
id: T-042-02
title: Order page returns section
type: frontend
status: ready
risk: low
depends_on:
  - T-042-01
files:
  - app/pages.py
  - app/server.py
shared: []
skills:
  - build
  - frontend-patterns
contracts:
  - /orders/{id}
requirements:
  - F-042-5
  - F-042-6
  - N-042-1
acceptance_criteria:
  - "AC-1: /orders/ord_1 shows a Returns heading and one row per return with its state label"
  - "AC-2: an order with no returns renders no Returns heading"
  - "AC-3: a state outside the known list renders as Unknown and the page still answers 200"
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
source_adr:
  - decisions/ADR-0001-stack.md
---

Render the page from `app/returns.py` (do not read data any other way). Register the
page in `app/server.py`.
