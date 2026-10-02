# Migrating a product from kit v0.x

v0.x enforced most rules in prose. v1 enforces them in `sdlc gate`, so a v0 product
will fail checks it used to "pass". That is the point: each failure is a real gap.

## Steps

1. Bump the pin (`git -C .sdlc checkout <v1 tag>`), then `.sdlc/bin/sdlc init --profile <stack>`.
   Existing files are kept; review the new `sdlc.toml`, CI workflow and adapters.
2. `.sdlc/bin/sdlc migrate` numbers acceptance criteria (`AC-1: ...`). Then rename
   tests so each AC's test carries its tag (`T-001-03/AC-1`).
3. `.sdlc/bin/sdlc doctor` until clean: real lint, typecheck that includes test files,
   unit with `{junit}`, build, start, route extractor.
4. `.sdlc/bin/sdlc lint`: fix ticket errors (oversized tickets, missing requirements,
   unresolvable `contracts:`). Contracts may stay as `### METHOD /path` headings and a
   `## Tables` markdown table with `` `table_name` `` in its first column; the parser reads
   those as routes and tables.
5. `.sdlc/bin/sdlc routes` and `.sdlc/bin/sdlc gate ci`: every FAIL is a defect the old
   process let through. Fix them through new tickets, not by editing old ones.
6. Move third-party skills to `skills/vendor/` with `sdlc skills add`, and delete
   copies in auto-loaded folders (`.agents/skills`, `.grok/skills`, `.claude/skills`).

## Removed in v1

| v0 | v1 |
|---|---|
| `scripts/verify-ticket.sh`, `ticket-files.sh`, `ticket-status.sh`, `no-contract-drift.sh`, `no-adr-edit.sh`, `ac-not-deleted.sh`, `test-edit-guard.sh`, `pre-commit.sh` | `sdlc lint`, `sdlc gate` (`artifacts`, `scope`, `immutable`, `contracts`, `test-quality`) |
| `scripts/run-tests.sh`, `run-app-eval.sh` (exited 0 with no runner) | `[commands]` in `sdlc.toml`; a missing required command fails |
| `scripts/bootstrap-product.sh` | `sdlc init` |
| `commands/*.md` copy-paste preambles | `sdlc prompt <play> [id]` (generated, complete) |
| `adapters/MODELS.md` bands | `[agents.*]` in `sdlc.toml`; pick an agent per run |
| `adapters/github/product-pr-checks.yml` (lint/typecheck/unit only) | `adapters/github/sdlc.yml` (doctor + full gate + trace) |
| "status: done" set by hand or product scripts | `sdlc status <id> done --as merge` (requires an approving review) |
| markdown-only golden example | `examples/returns-app`, run by the kit's own tests |
