# How to use this kit

For agents: `AGENTS.md` (or the product shim that points at `.sdlc/AGENTS.md`) is enough.

This kit is consumed with **option B**: pin it at `.sdlc/` in each product repo. Full git steps: `CONSUME.md`.

## 1. Host the kit, attach it

```bash
# kit remote already exists
cd myapp
git submodule add git@github.com:YOU/ai-sdlc-kit.git .sdlc
.sdlc/scripts/bootstrap-product.sh
```

Subtree alternative is in `CONSUME.md`.

## 2. Bind the agent tool

Always-on file = **product root** `AGENTS.md` (the shim). See `adapters/GENERIC.md`. Fill `adapters/MODELS.md`. Install pre-commit: `ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit` (or `bootstrap-product.sh --hooks`).

## 3. First product lock (once)

1. `/intent` then `/design` for the first slice. Accept both.
2. `/architect` on **L3**: stack ADR, fill `skills/frontend-patterns` and `skills/backend-patterns`, create `arch/CONTRACTS.md` and `design/DESIGN.md`.
3. Only then `/ticketize` and `/build`.

## 4. Every later slice

`/intent` → `/design` → `/architect` → `/ticketize` → `/build <id>` (fresh session) → `/test <id>` → `/review` → ship → `/observe` if needed.

Never `/build` inside the architect chat. Never edit `.sdlc/` in a feature PR.

## 5. Vendor skills

Pin under product `skills/vendor/` and `skills/VENDOR.lock.md`. See `.sdlc/skills/vendor/README.md`.

## 6. Bump the kit

`.sdlc/scripts/update-kit.sh v0.2.0` then `/test` one ticket.


## 7. Pre-commit + example walk

After bootstrap:

```bash
ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit
```

Walk `.sdlc/examples/slice-042-return-status/` (or `examples/…` in this kit repo) before your first real ticket — run `./scripts/verify-ticket.sh T-042-03` to confirm L0 tooling.
