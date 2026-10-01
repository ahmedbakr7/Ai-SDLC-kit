---
id: plan-NNN
title: <title>
status: draft            # draft | accepted | superseded
source_spec: design/spec-NNN-<slug>.md
---

# Plan NNN: <title>

## Contracts

Every route, page, table and event this slice adds or changes, already written into
`arch/CONTRACTS.md` (fenced ```routes / ```pages / ```tables / ```events blocks).
Every user-visible requirement maps to a contract or says "UI-only, no contract".

| Requirement | Contract |
|---|---|
| F-NNN-1 | `POST /api/...` |

## Shared modules

Code more than one ticket needs (auth/role checks, db client, error envelope, API
client, formatting). Name the module, its owner ticket, and its public functions.
Later tickets import it; nobody copies it. If this table is empty and two tickets
touch the same concern, the plan is wrong.

| Module | Owner ticket | Exposes |
|---|---|---|
| `src/server/db.ts` | T-NNN-01 | `db()` singleton |

## File map

| File | Ticket |
|---|---|

## Test strategy

- Unit (build play): <what>, tagged `T-NNN-nn/AC-n`.
- Integration (test play): <what runs against real infrastructure>.
- E2E (test play): <which user journeys, in a real browser against the running app>.
- Smoke (gate): every contract route and page answers on the started app.

## Ticket cuts

Ordered list. Contract and shared-module tickets first. Each ticket: <= 8 files,
<= 8 AC, one of backend/frontend/fullstack.

1. T-NNN-01 <title> (type, depends on)

## Rollback

<How to undo: revert, flag, migration down. Blast radius if it goes wrong.>
