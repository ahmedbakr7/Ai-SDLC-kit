# Skill: build

Use when implementing exactly one ticket.

## Load

- `AGENTS.md`
- the ticket file
- `CONTRACTS.md` (full file, or the heading the ticket `contracts:` field names)
- skills listed in ticket `skills:` — play + pattern + vendor/craft
- files in ticket `files:`

Vendor skills under `skills/vendor/` are optional craft. They do not override AGENTS.md hard rules or CONTRACTS.md.

## Band

L2. Escalate to L3 only if the ticket `risk: high` *and* the plan said first-of-kind.

## Procedure

1. Read ticket AC and `files:`. Refuse if `status` is not `ready` or `blocked` with a resolved blocker, or if any `depends_on` ticket is not `done`.
2. Plan mode: list edits. Do not invent files. If you need a file not listed, stop and ask for a ticket patch.
3. Implement the smallest diff that satisfies AC.
4. Add or update **unit** tests next to the code you changed. Do not own e2e — that is the test agent.
5. Run `scripts/verify-ticket.sh <ticket-id>` (L0).
6. Set ticket `status: in_review`.
7. Stop. Do not start the next ticket.

## Forbidden

- New public API / event / table
- Design tokens not in `DESIGN.md`
- Resolving `[OPEN]`
- Editing `CONTRACTS.md`, ADRs, or spec
