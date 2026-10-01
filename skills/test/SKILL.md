---
name: test
description: Add integration and end-to-end tests that prove a built ticket's acceptance criteria against real infrastructure, until `sdlc gate test <id>` passes. Use for /test <ticket-id> on a ticket in review.
---

# Play: test

The build play proved each AC with unit tests. You prove the same AC through the
real stack: real HTTP, real database, real browser. You never edit production code.

## Write set

Only the integration/e2e paths in your prompt (`tests.integration_globs`). If
production code is wrong, that is the finding: stop and report it.

## Procedure

1. For each AC, decide the cheapest test that exercises the real path:
   - API behaviour -> integration test over HTTP against the started app or the
     framework's request handler with a real database.
   - User-visible behaviour -> one e2e journey in a real browser (e.g. Playwright)
     against the running app, asserting on what the user sees.
2. Name each test with its tag (`T-001-03/AC-2 ...`) so the gate can map it.
3. Use the product's fixtures and seeding helpers. Do not create a second test
   framework or a second way to start the app.
4. Run `sdlc gate test <id>` until it passes.
5. If a test fails because production is wrong, do not change the test to match.
   Stop and report: the AC, the command, expected vs actual, and the file:line you
   believe is wrong. The ticket goes back to build.

## Good integration/e2e tests

- Start from the public surface (URL, route, page), never from internal functions.
- Assert on status codes, response bodies and visible text from the contract/page spec.
- Cover the error and empty states the spec names, not just the happy path.
- Clean up their own data; can run in any order.
