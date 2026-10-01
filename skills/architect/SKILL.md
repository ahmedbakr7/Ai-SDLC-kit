---
name: architect
description: Turn an accepted spec into a plan, machine-checkable CONTRACTS, ADRs and locked pattern skills. Use for /architect after /design is accepted; on the first slice also choose the stack.
---

# Play: architect

Everything after you is constrained by what you write. Ambiguity here becomes
inconsistent code in twenty tickets. Decide now; do not leave choices to builders.

## Procedure

1. **Read** the accepted spec, its pages, DESIGN.md, existing CONTRACTS, ADRs and
   pattern skills. List requirements you cannot map; resolve with the human, never by
   guessing (`[OPEN]` stays open).
2. **First slice only:** write the stack ADR (framework, data store, auth, test
   runners, how the app starts locally), fill both pattern skills' tables, create
   `sdlc.toml` commands so every gate check runs for real, and run `sdlc doctor`.
3. **CONTRACTS.md:** add every route/page/table/event to the fenced blocks, with the
   exact path the router will serve (including any base path like `/api`), request
   and response shapes, status codes, error codes and the auth rule. If the framework
   mounts routes under a prefix, the contract says so, and the client calls it.
4. **Plan** (template in your prompt):
   - **Contracts:** requirement -> contract (or "UI-only").
   - **Shared modules:** every concern two tickets touch (db, auth/roles, error
     envelope, API client, i18n, formatting) gets one module and one owner ticket.
   - **File map** and **Ticket cuts** that respect those modules.
   - **Test strategy:** what unit, integration and e2e each prove.
   - **Rollback.**
5. **ADRs** for any new pattern or dependency. Never edit an accepted ADR; supersede it.
6. Run `sdlc lint` until clean. Stop and ask the human to accept.

## Checks before you stop

- Every accepted requirement appears in the Contracts table.
- No two tickets will need to write the same helper.
- The framework's build rules are in the pattern skill (for example: Next.js
  `route.ts` files may only export HTTP handlers and route config).
- `sdlc doctor` passes: no gate check can pass by running nothing.
