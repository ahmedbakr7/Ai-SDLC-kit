# Consume this kit from a product repo (option B)

This repo is the kit. Product repos **do not copy it**. They pin it at `.sdlc/` and keep product files beside it.

## Product repo layout after bootstrap

```
myapp/
  AGENTS.md                     ← shim (always-on). Points at .sdlc/AGENTS.md
  adapters/MODELS.md            ← this product's L1/L2/L3
  skills/
    frontend-patterns/          ← THIS product's lock (copied once, then yours)
    backend-patterns/
    vendor/                     ← pinned craft skills for this product
    VENDOR.lock.md
  intent/  design/  arch/  decisions/  tickets/  reviews/  ops/
  .sdlc/                        ← this kit (subtree or submodule). Treat as read-only.
  src/                          ← application
```

Do not edit files under `.sdlc/` in a product PR. Change the kit repo, tag, bump.

---

## 1. Put the kit on git

```bash
# in the kit directory
git init
git add .
git commit -m "ai-sdlc-kit"
git remote add origin git@github.com:YOU/ai-sdlc-kit.git
git push -u origin main
git tag v0.1.0 && git push --tags
```

Replace `YOU/ai-sdlc-kit` with your remote. Use SSH or HTTPS consistently in the product.

---

## 2. Attach it to a product (pick one)

### Submodule (default — exact sha pin)

```bash
cd myapp
git submodule add -b main git@github.com:YOU/ai-sdlc-kit.git .sdlc
git submodule update --init --recursive
.sdlc/scripts/bootstrap-product.sh
git add AGENTS.md adapters skills intent design arch decisions tickets reviews ops
git commit -m "pin ai-sdlc-kit at .sdlc"
```

Clone later:

```bash
git clone --recurse-submodules git@github.com:YOU/myapp.git
# existing clone:
git submodule update --init --recursive
```

CI: `submodules: true` and a deploy key that can read the kit repo.

### Subtree (if you hate submodules)

```bash
cd myapp
git subtree add --prefix .sdlc git@github.com:YOU/ai-sdlc-kit.git main --squash
.sdlc/scripts/bootstrap-product.sh
```

---

## 3. Bind the agent

Root `AGENTS.md` is the shim. Point the tool at **repo-root** `AGENTS.md` (not only `.sdlc/AGENTS.md`).

Skills live in two trees. Agents must load:

- play skills from `.sdlc/skills/<play>/SKILL.md`
- pattern + vendor skills from `skills/`

Command preambles: copy or symlink `.sdlc/commands/*.md` into your tool’s command dir if it does not search `.sdlc/commands/`.

Hooks: install the wrapper after bootstrap (see `hooks/README.md`):

```bash
ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit
# or: .sdlc/scripts/bootstrap-product.sh --hooks
```

Before the first real ticket, walk `.sdlc/examples/slice-042-return-status/` (20-minute README).

---

## 4. Bump the kit

```bash
.sdlc/scripts/update-kit.sh          # submodule: checkout latest main (or pass a tag)
# subtree:
#   git subtree pull --prefix .sdlc git@github.com:YOU/ai-sdlc-kit.git main --squash
```

Then `/test` one known ticket. Commit the new `.sdlc` sha.

---

## 5. What you never put in the kit remote

Product `intent/`, tickets, `CONTRACTS.md`, filled pattern skills, `adapters/MODELS.md`, `skills/vendor/`. Those stay in `myapp`.
