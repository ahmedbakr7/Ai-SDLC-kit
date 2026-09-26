# How to use this kit

For agents: `AGENTS.md` (or the product shim that points at `.sdlc/AGENTS.md`) is enough.

Attach the kit at `.sdlc/` first: `CONSUME.md`. Bind the agent: `adapters/GENERIC.md`.

## 1. First product lock (once)

1. `/intent` then `/design` for the first slice. Accept both.
2. `/architect` on **L3**: stack ADR, fill `skills/frontend-patterns` and `skills/backend-patterns`, create `arch/CONTRACTS.md` and `design/DESIGN.md`.
3. Only then `/ticketize` and `/build`.

Before the first real ticket, walk `.sdlc/examples/slice-042-return-status/` (or `examples/…` in this kit repo). From the kit repo, `./scripts/verify-ticket.sh T-042-03` confirms L0 tooling.

## 2. Every later slice

`/intent` → `/design` → `/architect` → `/ticketize` → `/build <id>` (fresh session: code + **unit**; lint + typecheck + unit **green locally**, open PR) → CI required checks (lint + typecheck + unit; integration optional when present) → `/test <id>` (**integration**/e2e on that PR) → `/review` (AC↔proof + required checks green) → lead merges → `/observe` if needed.

Copy `.sdlc/adapters/github/product-pr-checks.yml` into the product `.github/workflows/` and mark lint/typecheck/unit required (see `adapters/github/README.md`). Builder runs those locally before the PR; CI enforces on the PR; merge only when checks green **and** `/review` Approve.

Never `/build` inside the architect chat. Never edit `.sdlc/` in a feature PR. Never open a post-merge proof-only `/test` PR as the default next step — Review stamps AC↔proof on the build PR.

## 3. Vendor skills

Copy craft packs into product `skills/vendor/<name>/`, commit them, and list them on tickets. See `.sdlc/skills/vendor/README.md`.

## 4. After a kit bump

When the product’s `.sdlc` pin moves to a new kit tag (`CONSUME.md`), smoke `/test` one known ticket **on an open PR** (or run the product suite). Do not open a proof-only PR just to stamp a receipt.
