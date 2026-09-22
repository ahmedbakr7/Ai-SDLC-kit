---
name: design
description: Turn an accepted intent into spec.md, DESIGN.md, and page files. Use after /intent is accepted. Do not write application code.
---

# Skill: design

## Band

L2, or L3 if this is the first product spec / new IA.

## Writes

`design/spec-<id>.md`, `design/DESIGN.md`, `design/pages/<route>.md`

## Do

- Mark `[DECISION: ADR-…]` or `[OPEN: …]` on every judgment.
- Page files describe empty / error / loaded states.
- Requirements must be testable statements.
- Do not invent stack or API shapes. That is `/architect`.

## Do not

- Implement UI.
- Resolve `[OPEN]` by guessing.
