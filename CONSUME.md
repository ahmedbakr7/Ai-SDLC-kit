# Consume this kit from a product repo

Pin this repo at `.sdlc/` (submodule SHA or subtree squash). Product files stay at the product root. Do not edit `.sdlc/` in a feature PR. To take a kit change: tag it here, then bump the pin in the product.

## Layout after bootstrap

```
myapp/
  AGENTS.md                 shim → .sdlc/AGENTS.md
  adapters/MODELS.md
  skills/frontend-patterns, backend-patterns, vendor/
  intent/ design/ arch/ decisions/ tickets/ reviews/ ops/
  .sdlc/                    this kit, read-only
  src/
```

Product intent, tickets, CONTRACTS, filled pattern skills, `adapters/MODELS.md`, and `skills/vendor/` stay in `myapp`.

## Attach

Submodule (default):

```bash
cd myapp
git submodule add -b main git@github.com:YOU/ai-sdlc-kit.git .sdlc
.sdlc/scripts/bootstrap-product.sh          # add --hooks to install pre-commit
git add AGENTS.md adapters skills intent design arch decisions tickets reviews ops
git commit -m "pin ai-sdlc-kit at .sdlc"
```

Later clones: `git clone --recurse-submodules …`. CI: `submodules: true`.

Subtree:

```bash
git subtree add --prefix .sdlc git@github.com:YOU/ai-sdlc-kit.git main --squash
.sdlc/scripts/bootstrap-product.sh
```

Bind the tool to repo-root `AGENTS.md` (`adapters/GENERIC.md`). Pre-commit without `--hooks`: `ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit`. Walk `.sdlc/examples/slice-042-return-status/`, then plays in `USAGE.md`.

## Bump the pin

```bash
.sdlc/scripts/update-kit.sh v0.2.0    # omit arg → origin/main
# subtree: git subtree pull --prefix .sdlc <remote> v0.2.0 --squash
```

`/test` one known ticket. Commit the new `.sdlc` gitlink or subtree merge.
