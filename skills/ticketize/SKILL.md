---
name: ticketize
description: Cut an accepted plan into small, ordered, gate-ready tickets with exact files, numbered testable AC and full traceability. Use for /ticketize after /architect is accepted.
---

# Play: ticketize

Every ticket you write becomes one agent's entire world. If it is vague, too big, or
lists the wrong files, the build will be wrong no matter how good the agent is.

## Procedure

1. Follow the plan's **Ticket cuts** and **File map** exactly. A ticket for work not in
   the plan is forbidden; if the plan is missing something, stop and say what.
2. Order: shared-module and contract tickets first, then backend, then frontend.
   `depends_on` lists every ticket whose code this one imports or calls.
3. **files:** the exact paths this ticket creates or edits (no globs, <= 8). Tests
   beside them are implied. A shared module is created by its owner ticket (the
   plan's Shared modules table; the owner lists it in `files:`) and listed in
   `shared:` or `files:` by later tickets that must extend it. Two open tickets that
   write the same file must be ordered with `depends_on` (`sdlc lint` checks both).
4. **acceptance_criteria:** `AC-n: <observable behaviour>`. One behaviour each, <= 8.
   Each must be checkable by a test without asking anyone:
   - Good: `AC-2: PUT /api/v1/plans/{id}/response with an unknown planId answers 404 not_found`
   - Bad: `AC-2: handles errors properly` / `AC-2: the build agent does not edit tests`
   Include the error, empty and permission cases the spec names.
5. **requirements:** the F-/N- ids it serves. Every accepted requirement must be
   covered by at least one ticket (`sdlc trace` checks).
6. **contracts:** the route/page/table/event keys from CONTRACTS it implements.
7. **skills:** `build`, the pattern skill(s), and any vendor skill the work needs.
8. `status: draft`. The lead moves tickets to `ready` after reading the graph;
   `risk: high` tickets also need `accepted_by:`.
9. Run `sdlc lint` and `sdlc trace` until both are clean. Stop.

## Sizing

Split when a ticket has > 8 files, > 8 AC, mixes contract + backend + frontend, or
cites more than ~6 requirements. Smaller tickets build, review and revert better.
