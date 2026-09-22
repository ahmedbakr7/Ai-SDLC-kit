# Skill: frontend-patterns

Replace the examples with this repo’s real choices via an ADR. Until then, treat this file as the pattern lock.

## Defined when

After first accepted spec, inside the first architect play. Frozen by ADR-0001 (stack) + ADR-0002 (UI patterns). Change only by superseding ADR.

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
- No fetching shape that contradicts `CONTRACTS.md`
