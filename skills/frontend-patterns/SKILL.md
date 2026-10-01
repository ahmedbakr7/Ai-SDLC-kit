---
name: frontend-patterns
description: Product-locked frontend patterns (routing, data fetching, state, forms, i18n, tokens, component library, tests). Filled in the first /architect and changed only by ADR. Load on every frontend ticket.
---

# Frontend patterns (fill in during the first /architect; cite the stack ADR)

| Concern | Pattern | Module |
|---|---|---|
| Routing / layouts | | |
| Calling the API (one client; base path from CONTRACTS) | | |
| Server vs client components / data loading | | |
| State | | |
| Forms + validation | | |
| Errors and empty states | | |
| i18n / RTL | | |
| Component library | | |
| Design tokens (from DESIGN.md only) | | |

## Rules

- Every API call goes through the one API client; paths come from CONTRACTS.
- Pages implement every state in their `design/pages/*.md` table.
- Components over ~200 lines get split; shared UI lives in the component library folder.

## Tests

- Component tests render and assert on what the user sees (text, roles), never on
  source text or class names.
- E2E (test play): real browser against the running app.
- Every test name carries its AC tag (`T-NNN-NN/AC-n`).
