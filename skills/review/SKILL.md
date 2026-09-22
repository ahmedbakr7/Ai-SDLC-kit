# Skill: review

Launched by CI on every PR, not by the author session.

## Band

L2 default. L3 if `risk: high`, auth, payments, PII, or first-of-kind ADR.

## Writes

`reviews/<pr-or-sha>.md` plus inline comments. May not merge. May not edit prod.

## Each finding needs a proof

`file:line` + rule violated (ticket `files:`, CONTRACTS.md, DESIGN.md, ADR-N, AC).

## Checks

1. Diff ⊆ ticket `files:`
2. No new public seam vs CONTRACTS.md
3. AC mapped to tests
4. Patterns skills honored
5. No silent `[OPEN]` resolution
