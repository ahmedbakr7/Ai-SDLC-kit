---
id: T-NNN-01
title: <imperative, specific>
type: backend             # backend | frontend | fullstack | contract | test | ops | chore | spike
status: draft             # draft -> ready (lead) -> in_progress -> in_review -> done; or blocked
risk: low                 # low | medium | high (high = strict lane: needs accepted_by, set by the lead)
# lane: standard          # mechanical | standard | strict. Default: strict for risk high or type contract,
                          # else standard. The gate may raise it from the diff, never lower it.
# transforms: []          # lane: mechanical only. Each: 'literal "old" -> "new"', 'rename oldName -> newName'
                          # or 'move old/path -> new/path'. They must produce the whole diff.
test: required            # required | none (lead only: no route/page in contracts; skips the test play)
depends_on: []
areas:                    # globs or paths this ticket expects to change. Tests beside them are implied.
  - src/server/things.ts  # a file outside the areas is flagged for the reviewer, not refused
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

<!-- The build records changes to this ticket here, one line each, append-only:
## Amendments

- add AC-3: <why>
- strengthen AC-1: <why it is stronger>
- split AC-2 -> T-NNN-02: <why> (the AC moves verbatim into a new draft ticket with split_from:)
- widen src/server/shared.ts: <why>
-->
