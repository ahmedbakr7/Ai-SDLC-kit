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
3. **areas:** the paths (or narrow globs) this ticket creates or edits. Tests beside
   them are implied; the build may touch other files, which the reviewer must accept.
   A shared module is created by its owner ticket (the plan's Shared modules table; the
   owner lists it in `areas:`) and listed in `shared:` or `areas:` by later tickets that
   must extend it. Two open tickets that list the same area must be ordered with
   `depends_on` (`sdlc lint` checks both).
   - A rename or move that preserves behaviour is `lane: mechanical` with `transforms:`
     (`'literal "/v1/" -> "/api/v1/"'`, `rename oldName -> newName`, `move a -> b`) and
     no acceptance criteria. Anything that changes behaviour is not mechanical.
   - An unknown that blocks planning is `type: spike` with `questions:` (`Q-1: ...`).
4. **acceptance_criteria:** `AC-n: <observable behaviour>`. One behaviour each, <= 8.
   Each must be checkable by a test without asking anyone:
   - Good: `AC-2: PUT /api/v1/plans/{id}/response with an unknown planId answers 404 not_found`
   - Bad: `AC-2: handles errors properly` / `AC-2: the build agent does not edit tests`
   Include the error, empty and permission cases the spec names.
5. **requirements:** the F-/N- ids it serves. Every accepted requirement must be
   covered by at least one ticket (`sdlc trace` checks).
6. **contracts:** the route/page/table/event keys from CONTRACTS it implements.
7. **skills:** `build`, the pattern skill(s), and any vendor skill the work needs.
8. **test:** `required` (default) or `none`. With integration/e2e tests configured, a
   ticket cannot be approved until its test play proves an AC through the real stack.
   Use `none` only for tickets nothing reaches over HTTP or a browser (shared
   libraries, config, tooling); `sdlc lint` refuses it on tickets that implement a
   contract route or page.
9. `status: draft`. The lead moves tickets to `ready` after reading the graph;
   `risk: high` tickets also need `accepted_by:`.
10. Run `sdlc lint` and `sdlc trace` until both are clean. Stop.

## Sizing

Split when a ticket has > 8 AC, spans unrelated areas, mixes contract + backend + frontend, or
cites more than ~6 requirements. Smaller tickets build, review and revert better.
