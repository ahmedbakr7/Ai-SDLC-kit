# Hooks (L0 — no LLM)

Run in the agent runtime (pre-write / pre-commit) and again in CI. Same scripts.

**Dependency:** `bash` plus `python3` on `PATH` for YAML frontmatter parsing (stdlib; optional `PyYAML` / `yq` if you prefer richer YAML). No Claude Code APIs.

| Hook | Script | When | Fail if |
|---|---|---|---|
| ticket files | `scripts/ticket-files.sh` | before every write in a `/build` or `/test` session | path not in ticket `files:` / allowed unit-beside (build) / integration-e2e-eval (test) |
| no contract drift | `scripts/no-contract-drift.sh` | before commit | new route/event/table name not present in `arch/CONTRACTS.md` |
| no ADR edit | `scripts/no-adr-edit.sh` | before commit | existing `decisions/ADR-*.md` modified (add ADR-N+1 instead) |
| AC not deleted | `scripts/ac-not-deleted.sh` | before commit on ticket files | an `acceptance_criteria` item removed without a `spec:` citation |
| test edit guard | `scripts/test-edit-guard.sh` | during a “fix tests” turn in **build** | unit test files changed with no production file in the same diff (build). Test agent (`PLAY=test`) is exempt (integration/e2e only). |
| ticket status | `scripts/ticket-status.sh` | CI | `--require-review-status` and ticket status not `in_review`/`done` |

Also used by plays / CI:

| Script | Role |
|---|---|
| `scripts/verify-ticket.sh` | ticket frontmatter + `depends_on` resolve |
| `scripts/run-tests.sh` | product-overridable test runner |
| `scripts/run-app-eval.sh` | product-overridable app eval |
| `scripts/pre-commit.sh` | thin git hook wrapper |
| `scripts/check-kit.sh` | kit-repo honesty check |

## Install pre-commit (product repo)

After `git submodule add <kit> .sdlc && .sdlc/scripts/bootstrap-product.sh`:

```bash
# default bootstrap prints this; or re-run with --hooks
ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit
```

`pre-commit.sh` behavior:

- If `TICKET_FILE` or `TICKET_ID` is set → `verify-ticket.sh` + `ticket-files.sh` on staged paths
- Always → `no-adr-edit.sh` when any `decisions/ADR-*.md` is staged

Wire the same scripts in CI (GitHub Action, etc.). Vendor-neutral: bash + python3 only.

## Required PR checks (product merge gate)

L0 hooks above are local/pre-commit. Products also need **GitHub required checks** on every PR — part of the merge gate with `/review` Approve:

| Check | Required | Notes |
|---|---|---|
| lint | yes | builder runs locally before PR; CI enforces |
| typecheck | yes | same |
| unit | yes | same (`scripts/run-tests.sh` / `npm test`) |
| integration | optional when present | `/test` on the build PR; enable CI job when product has a target |

Template: `.sdlc/adapters/github/product-pr-checks.yml` → product `.github/workflows/` (see `adapters/github/README.md`). Lead merges only when those required checks are green **and** review is Approve. Do not resurrect post-merge proof-only `/test` PRs.
