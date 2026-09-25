---
name: test
description: Author or verify tests for one ticket. Mode A writes test/e2e/eval files; Mode B runs app evals.
---

# Skill: test

Load set, band, write set, and hard rules: `AGENTS.md`.

## Procedure

Two modes. Same agent kind, different write set.

### Mode A — author

Write tests that lock the ticket AC. Globs: `**/*.{test,spec}.*`, `e2e/**`, `evals/**`, fixtures.

1. Load ticket AC + `CONTRACTS.md` + built files.
2. Map each AC to a test. Missing AC = fail the play, do not skip.
3. Prefer contract tests against schemas in `CONTRACTS.md`, then unit, then one e2e path per user-visible AC.
4. Run `scripts/run-tests.sh --ticket <id>`.
5. If red because production is wrong: do **not** fix production. Open a note on the ticket (`blocked_by: prod`) and stop. Build agent owns prod.
6. If red because the test is wrong: fix the test.
7. Never delete or weaken an AC to pass.

### Mode B — verify

Run the app and report. Proof artifact: `reviews/test-<ticket-or-sha>.md`.

- Use `scripts/run-app-eval.sh` (browser, API, screenshot diff — whatever the repo wired)
- Proof format: command, expected, actual, file:line

Vendor skills teach the runner. This skill owns AC mapping and the write set.
