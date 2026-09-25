---
name: architect
description: Turn an accepted spec into plan.md, CONTRACTS.md patches, and ADRs. Use after /design.
---

# Skill: architect

Load set, band, write set, and hard rules: `AGENTS.md`.

Use after spec is accepted, before tickets. Once per change.

## Procedure

1. Decide here, not later:
   - API / event / table seams for this slice
   - Authz boundary
   - Which existing FE/BE patterns apply (cite skill + ADR) vs a new ADR; do not bury a pattern change in plan prose
   - File map and ticket cut lines
   - Test strategy (what the test agent will own)
2. If `skills/frontend-patterns/SKILL.md` or `skills/backend-patterns/SKILL.md` do not exist yet, this play creates them plus a stack ADR. Later slices only cite them.
3. Output checklist:
   - [ ] Every user-visible AC has a contract or an explicit “UI-only, no contract”
   - [ ] Error shapes match existing CONTRACTS.md
   - [ ] Rollback / blast radius
   - [ ] `skills:` each future ticket should load
