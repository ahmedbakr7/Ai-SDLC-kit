---
name: review
description: Review a PR against ticket files:, CONTRACTS, DESIGN, and ADRs. Write file:line proofs. Do not merge.
---

# Skill: review

Load set, band, write set, and hard rules: `AGENTS.md`.

## Procedure

Launched by CI on every PR, not by the author session. Extra L3 triggers: auth, payments, PII, or first-of-kind ADR.

Write `reviews/<pr-or-sha>.md` plus inline comments if the host supports them. Do not merge.

Each finding needs a proof: `file:line` + rule violated (ticket `files:`, CONTRACTS.md, DESIGN.md, ADR-N, AC).

Checks:

1. Diff ⊆ ticket `files:`
2. No new public seam vs CONTRACTS.md
3. AC mapped to tests
4. Patterns skills honored
5. No silent `[OPEN]` resolution
