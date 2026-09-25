---
name: build
description: Implement exactly one ticket. Use on /build after the ticket is ready.
---

# Skill: build

Load set, band, write set, and hard rules: `AGENTS.md`.

## Procedure

1. Read ticket AC and `files:`. Refuse if `status` is not `ready` or `blocked` with a resolved blocker, or if any `depends_on` ticket is not `done`.
2. Plan mode: list edits. Do not invent files. If you need a file not listed, stop and ask for a ticket patch.
3. Implement the smallest diff that satisfies AC.
4. Add or update **unit** tests next to the code you changed. Do not own e2e — that is the test agent.
5. Run `scripts/verify-ticket.sh <ticket-id>` (L0).
6. Set ticket `status: in_review`.
7. Stop. Do not start the next ticket.
