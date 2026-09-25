---
name: frontend-patterns
description: Product-locked frontend patterns (framework, data fetching, tokens). Fill via ADR in the first /architect.
---

# Skill: frontend-patterns

Hard rules: `AGENTS.md`.

Fill the Lock in the first `/architect`. Change only by a superseding ADR.

## Lock (fill in per product)

- Framework / router / bundler:
- Folder layout:
- Server vs client data fetching:
- Global state (allowed / forbidden):
- Forms:
- i18n:
- Design tokens: load `DESIGN.md`, no raw hex / ad-hoc spacing
- Testing: component tests next to file; e2e owned by test agent

## Build agent rules

- New page = add/update `design/pages/<route>.md` first (spec play), not here
- No new component library
