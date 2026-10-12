---
name: frontend-patterns
description: Product-locked frontend patterns (routing, data fetching, state, forms, i18n, tokens, component library, tests) and conventions (where new things go, use-not, never). Filled in the first /architect and changed only by ADR. Load on every frontend ticket.
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

## Conventions

Short on purpose: this section stops guessing; it is not an architecture spec. A builder
who finds a structural choice it does not settle follows the closest existing example and
names it, or stops (AGENTS.md rule 11). The lead adds each such gap here afterwards.

| New thing | Goes in | Closest example |
|---|---|---|
| Page | | |
| Component | | |
| Hook / client helper | | |
| Server call (API client use) | | |
| Test | | |

Use, not:

- <use X, not Y>

Never:

- <never allowed, with the ADR or reason>

## Rules

- Every API call goes through the one API client; paths come from CONTRACTS.
- Pages implement every state in their `design/pages/*.md` table.
- Components over ~200 lines get split; shared UI lives in the component library folder.

## Tests

- Component tests render and assert on what the user sees (text, roles), never on
  source text or class names.
- E2E (test play): real browser against the running app.
- Every test name carries its AC tag (`T-NNN-NN/AC-n`).
