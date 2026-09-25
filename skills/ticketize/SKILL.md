---
name: ticketize
description: Split an accepted plan into tickets/*.md with exhaustive files:, resolvable depends_on, and testable AC.
---

# Skill: ticketize

Load set, band, write set, and hard rules: `AGENTS.md`.

## Procedure

1. One ticket, one file.
2. `depends_on` only existing ids; contract tickets before FE/BE consumers.
3. `files:` exhaustive.
4. `skills:` what the build agent must load.
5. `contracts:` heading or path in CONTRACTS.md.
6. AC checkbox-testable.
7. No ticket for a phase not in the accepted plan.
8. Split if > ~6 files or > ~8 AC or mixed FE+BE+contract in one ticket.
9. Human or lead accepts the graph if any ticket is `risk: high`.
