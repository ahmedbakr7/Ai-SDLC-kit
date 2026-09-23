---
name: ticketize
description: Split an accepted plan into tickets/*.md with exhaustive files:, resolvable depends_on, and testable AC. Write tickets only.
---

# Skill: ticketize

## Band

L1 to draft, L2 if the plan is large. Human or lead accepts the graph if any ticket is `risk: high`.

## Writes

`tickets/<id>.md` only.

## Rules

- One ticket, one file
- `depends_on` only existing ids; contract tickets before FE/BE consumers
- `files:` exhaustive
- `skills:` what the build agent must load
- `contracts:` heading or path in CONTRACTS.md
- AC checkbox-testable
- No ticket for a phase that is not in the accepted plan
- Split if > ~6 files or > ~8 AC or mixed FE+BE+contract in one ticket
