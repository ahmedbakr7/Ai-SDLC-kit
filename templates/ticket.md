---
id: T-NNN-01
title: <imperative, specific>
type: backend             # backend | frontend | fullstack | contract | test | ops | chore
status: draft             # draft -> ready (lead) -> in_progress -> in_review -> done; or blocked
risk: low                 # low | medium | high (high needs accepted_by)
depends_on: []
files:                    # exact paths this ticket creates or edits (<= 8). Tests beside them are implied.
  - src/server/things.ts
shared: []                # globs of shared modules this ticket may also touch (from the plan's Shared modules)
skills:                   # loaded into the prompt, in order
  - build
  - backend-patterns
contracts:                # route/page/table/event keys from CONTRACTS.md this ticket implements
  - GET /api/v1/things/{id}
requirements:             # F-/N- ids from the spec
  - F-NNN-1
acceptance_criteria:      # one observable behaviour each; tests are named with T-NNN-01/AC-n
  - "AC-1: GET /api/v1/things/demo answers 200 with id and name"
  - "AC-2: an unknown id answers 404 with error.code not_found"
source_intent: intent/intent-NNN-<slug>.md
source_spec: design/spec-NNN-<slug>.md
source_plan: arch/plan-NNN-<slug>.md
source_adr: []
---

<One paragraph: what to build and which shared modules to reuse. No new seams.>
