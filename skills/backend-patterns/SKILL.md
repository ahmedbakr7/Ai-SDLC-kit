---
name: backend-patterns
description: Product-locked backend patterns (API style, authz, persistence). Fill via ADR in the first /architect.
---

# Skill: backend-patterns

Hard rules: `AGENTS.md`.

Fill the Lock in the first `/architect`. Change only by a superseding ADR.

## Lock (fill in per product)

- API style (REST/RPC) and error envelope:
- Authn / authz placement:
- Persistence / transactions:
- Jobs / queues:
- Logging / trace ids:
- Migrations:
- Testing: handler + contract tests; no hitting real third parties in unit tests

## Build agent rules

- Do not introduce a second ORM, logger, or auth helper
