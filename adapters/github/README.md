# GitHub Actions adapter

Two templates live here (not under `.github/`) so a kit push works without the GitHub `workflow` OAuth scope. Install is one copy each.

| Template | For | Jobs |
|---|---|---|
| `check-kit.yml` | **This kit repo** | `scripts/check-kit.sh` + example ticket verify |
| `product-pr-checks.yml` | **Product repos** that pin the kit | **lint** + **typecheck** + **unit** (required); **integration** optional when present |

```bash
mkdir -p .github/workflows
# kit repo:
cp adapters/github/check-kit.yml .github/workflows/check-kit.yml
# product repo (kit at .sdlc/):
cp .sdlc/adapters/github/product-pr-checks.yml .github/workflows/product-pr-checks.yml
```

## Product merge gate

Required GitHub checks are part of the merge gate **with** `/review` Approve:

1. **Builder (`/build`)** runs lint, typecheck, and unit locally; suite **green before opening the PR**.
2. **CI** re-runs those checks on every `pull_request` (`product-pr-checks.yml`).
3. **Tester (`/test`)** adds integration/e2e on that same build PR when invited — not a post-merge proof-only PR.
4. **Reviewer (`/review`)** writes AC↔proof; Approve only when the table is complete **and** required checks are green.
5. **Lead / conveyor** merges only when required checks are green **and** review verdict is Approve.

Wire branch protection (or rulesets) so `lint`, `typecheck`, and `unit` are **required** status checks. Add `integration` as required only after the product enables that job.

Do not resurrect post-merge proof-only `/test` PRs as the default next step after merge.

Adapt the npm placeholders in `product-pr-checks.yml` to the product stack (`make lint`, `pytest`, `go test`, …). Prefer `.sdlc/scripts/run-tests.sh` when the kit is pinned.
