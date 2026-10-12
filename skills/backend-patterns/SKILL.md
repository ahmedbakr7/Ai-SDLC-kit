---
name: backend-patterns
description: Product-locked backend patterns (API style, errors, authz, data access, tests) and conventions (where new things go, use-not, never). Filled in the first /architect and changed only by ADR. Load on every backend ticket.
---

# Backend patterns (fill in during the first /architect; cite the stack ADR)

Every row names a real module path. A builder who needs one of these concerns
imports that module; writing a second one is a review finding.

| Concern | Pattern | Module |
|---|---|---|
| Routing / handlers | | |
| Request validation | | |
| Error envelope | | |
| Authn (who is calling) | | |
| Authz (may they do this) | | |
| Data access / transactions | | |
| External APIs (clients, retries, fakes for tests) | | |
| Config / secrets | | |
| Logging | | |
| Migrations | | |

## Conventions

Short on purpose: this section stops guessing; it is not an architecture spec. A builder
who finds a structural choice it does not settle follows the closest existing example and
names it, or stops (AGENTS.md rule 11). The lead adds each such gap here afterwards.

| New thing | Goes in | Closest example |
|---|---|---|
| Route / handler | | |
| Domain / service module | | |
| Data access | | |
| Migration | | |
| Test | | |

Use, not:

- <use X, not Y>

Never:

- <never allowed, with the ADR or reason>

## Framework rules the build must respect

<!-- e.g. Next.js: route.ts may export only HTTP methods + route config; helpers live in src/server/** -->

## Tests

- Unit: <how handlers are called directly; test DB or fake>
- Integration: <real DB / container; how to seed>
- Every test name carries its AC tag (`T-NNN-NN/AC-n`).
