---
name: backend-patterns
description: Product-locked backend patterns (API style, authz, persistence). Fill via ADR in the first /architect. Build agents must apply, not invent.
---

# Skill: backend-patterns

Same freeze rule as frontend-patterns. Fill via ADR.

## Defined when

First architect play after first spec. Frozen by stack ADR + backend-patterns ADR.

## Lock (fill in per product)

- API style (REST/RPC) and error envelope:
- Authn / authz placement:
- Persistence / transactions:
- Jobs / queues:
- Logging / trace ids:
- Migrations:
- Testing: handler + contract tests; no hitting real third parties in unit tests

## Build agent rules

- New endpoint = already in `CONTRACTS.md`
- New job name = already in `CONTRACTS.md`
- Do not introduce a second ORM, logger, or auth helper
