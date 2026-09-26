---
name: review
description: Review a PR with a required AC↔proof table. Approve only when diff is in bounds and the PR suite is green. Do not merge.
---

# Skill: review

Load set, band, write set, and hard rules: `AGENTS.md`.

## Owns

- **AC↔proof** mapping (what post-merge `/test` used to stamp)
- Diff ⊆ ticket `files:` (plus allowed unit/integration paths per play)
- Contracts, patterns, DESIGN, ADR checks
- Merge gate signal: Approve **only** when that table is complete **and** the suite on the PR is green

## Does not

- Merge the PR (human/CI merges after Approve + green)
- Rewrite production or tests to force green
- Accept a post-merge proof-only test PR as a substitute for proof on the build PR

## Procedure

Launched by CI on every PR, not by the author session. Extra L3 triggers: auth, payments, PII, or first-of-kind ADR.

Write `reviews/<pr-or-sha>.md` plus inline comments if the host supports them. Do not merge.

Required sections in the review artifact:

1. **AC↔proof table** — every ticket AC → proof (test id / command / `file:line` on the PR). Missing row = do not Approve.
2. Findings — each needs `file:line` + rule violated (ticket `files:`, CONTRACTS.md, DESIGN.md, ADR-N, AC).
3. **Suite on PR** — unit (from `/build`) and integration/e2e (from `/test` when invited) green on this PR. Red = do not Approve.
4. Verdict — Approve or Request changes.

Checks:

1. Diff ⊆ ticket `files:` (and allowed test paths for the play that wrote them)
2. No new public seam vs CONTRACTS.md
3. AC↔proof table complete
4. Patterns skills honored
5. No silent `[OPEN]` resolution
6. PR suite green

Merge only when verdict is Approve and the PR suite is green. Never treat a post-merge proof-only `/test` PR as the proof conveyor.
