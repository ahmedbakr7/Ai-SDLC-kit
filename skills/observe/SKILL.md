---
name: observe
description: Turn production or eval failures into incident.md and a draft intent. Use on a schedule or after a breach. Do not ship a fix from this session.
---

# Skill: observe

## Band

L1.

## Writes

`ops/incident-<id>.md` and optionally `intent/intent-<id>-draft.md` with `status: draft`.

## Do

- Evidence, suspected ticket/plan, what control band broke.
- Draft intent for the human to accept. That starts the loop again.

## Do not

- Patch production in this session.
- Close an incident without a follow-on intent or an explicit “no action” ADR.
