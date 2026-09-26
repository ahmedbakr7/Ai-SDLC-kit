---
name: build
description: Implement exactly one ticket with unit tests. Unit suite green before opening the PR. Use on /build after the ticket is ready.
---

# Skill: build

Load set, band, write set, and hard rules: `AGENTS.md`.

## Owns

- Production code in ticket `files:`
- **Unit** tests beside those files
- Unit suite **green before opening the PR**

## Does not

- Write integration or e2e suites (`/test` owns those)
- Push straight to `main` or force-push
- Start the next ticket

## Procedure

1. Read ticket AC and `files:`. Refuse if `status` is not `ready` or `blocked` with a resolved blocker, or if any `depends_on` ticket is not `done`.
2. Plan mode: list edits. Do not invent files. If you need a file not listed, stop and ask for a ticket patch.
3. Implement the smallest diff that satisfies AC on a build branch off `main`.
4. Add or update **unit** tests next to the code you changed. Do not write integration/e2e.
5. Run the unit suite for the changed surface. It must be **green** before you open the PR.
6. Run `scripts/verify-ticket.sh <ticket-id>` (L0).
7. Set ticket `status: in_review`. Open the PR from the build branch (never push straight to `main`).
8. Stop. Next: invite `/test <id>` onto that PR when integration coverage is needed; then `/review`.
