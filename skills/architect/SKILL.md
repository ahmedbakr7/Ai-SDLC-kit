---
name: architect
description: Turn an accepted spec into plan.md, CONTRACTS.md patches, and ADRs. Use after /design. Do not write application source or tickets.
---

# Skill: architect

Use after spec is accepted, before tickets.

## Band

L3. This is the expensive session. Do it once per change.

## Writes

- `arch/plan-<id>.md`
- `arch/CONTRACTS.md` (patch)
- `decisions/ADR-NNNN.md` if a pattern or stack choice is new
- Must **not** write application source or tickets

## Must decide here (not later)

- API / event / table seams for this slice
- Authz boundary
- Which existing FE/BE *patterns* apply (cite skill + ADR)
- Whether a pattern must change → new ADR, do not bury it in plan prose
- File map and ticket cut lines
- Test strategy (what the test agent will own)

## FE / BE patterns

If `skills/frontend-patterns/SKILL.md` or `backend-patterns/SKILL.md` do not exist yet, this play **creates them** plus a stack ADR. That is the product-level architecture moment. After they exist, this play only cites them.

## Output checklist

- [ ] Every user-visible AC in spec has a contract or an explicit “UI-only, no contract”
- [ ] Error shapes match existing CONTRACTS.md
- [ ] Rollback / blast radius
- [ ] `skills:` each future ticket should load
