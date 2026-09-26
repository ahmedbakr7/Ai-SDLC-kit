---
name: test
description: Author integration/e2e tests on the build PR, or run the suite in CI. No unit gap-fill. No post-merge proof-only PRs.
---

# Skill: test

Load set, band, write set, and hard rules: `AGENTS.md`.

## Owns

- **Integration** tests (and later e2e / evals) that lock ticket AC
- Running those suites **against the build PR/branch** when invited

## Does not

- Fill unit-test gaps (build owns unit; unit must already be green on the PR)
- Edit production source
- Open post-merge proof-only PRs (drop that as a conveyor step)
- Stamp the AC↔proof table (`/review` owns that)

## Procedure

Two modes. Same agent kind, different write set.

### Mode A — author (default `/test <id>`)

Write **integration** (and later e2e) tests that lock the ticket AC. Work on the **open build PR/branch**, not a new post-merge proof PR.

Globs: integration/contract specs, `e2e/**`, `evals/**`, fixtures. Prefer paths the product already uses for non-unit suites. Do **not** author unit tests beside production files to close gaps — refuse and send that back to `/build`.

1. Load ticket AC + `CONTRACTS.md` + built files on the build branch/PR.
2. Map each AC to an integration (or e2e) test. Missing AC = fail the play, do not skip.
3. Prefer contract/integration tests against schemas in `CONTRACTS.md`, then one e2e path per user-visible AC. Skip unit-layer authorship.
4. Run `scripts/run-tests.sh --ticket <id>` (or the product’s integration target).
5. If red because production is wrong: do **not** fix production. Open a note on the ticket (`blocked_by: prod`) and stop. Build agent owns prod.
6. If red because the test is wrong: fix the test.
7. Never delete or weaken an AC to pass. Never open a separate proof-only PR after merge.

### Mode B — CI run (`/test --app`)

Run the suite on the PR and report. No new PR. No AC↔proof stamp (Review owns that).

- Use `scripts/run-app-eval.sh` / `scripts/run-tests.sh` (whatever the repo wired)
- Report: command, expected, actual, file:line
- Do not open a post-merge proof-only PR

Vendor skills teach the runner. This skill owns integration/e2e authorship and the write set.
