# Skill: test

Two modes. Same agent kind, different write set.

## Mode A — author (default after a build)

Write tests that lock the ticket AC.

- Band: L2
- May write: `**/*.{test,spec}.*`, `e2e/**`, `evals/**`, fixtures
- May not write: production source, `CONTRACTS.md`, tickets (except `status` / links to test files)

Procedure:

1. Load ticket AC + `CONTRACTS.md` + built files.
2. Map each AC to a test. Missing AC = fail the play, do not skip.
3. Prefer contract tests against schemas in `CONTRACTS.md`, then unit, then one e2e path per user-visible AC.
4. Run `scripts/run-tests.sh --ticket <id>`.
5. If red because production is wrong: do **not** fix production. Open a note on the ticket (`blocked_by: prod`) and stop. Build agent owns prod.
6. If red because the test is wrong: fix the test.
7. Never delete or weaken an AC to pass.

## Mode B — verify (CI or `/test --app`)

Run the app and report. Write only `reviews/test-<ticket-or-sha>.md`.

- Band: L1 to drive the runner + summarize; L0 runs the suite
- Use `scripts/run-app-eval.sh` (browser, API, screenshot diff — whatever the repo wired)
- Proof format: command, expected, actual, file:line

## Load

ticket.md, CONTRACTS.md, this skill, existing tests for `files:`, plus craft skills listed on the ticket (e.g. `skills/vendor/playwright`).

Vendor skills teach the runner. This skill owns AC mapping and the write set.
