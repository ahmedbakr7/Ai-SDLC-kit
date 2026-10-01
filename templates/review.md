---
ticket: T-NNN-NN
verdict: request_changes  # approve | request_changes
reviewer: <agent name from sdlc.toml, not the builder>
commit: <the commit in the latest evidence: evidence/T-NNN-NN.test.json if the test play ran, else .build.json>
---

# Review T-NNN-NN: <title>

## Gate

<Paste result and checks from the build evidence. Anything red or skipped that the
play requires = request_changes.>

## Acceptance criteria

| AC | Proof | What the test actually asserts |
|---|---|---|
| AC-1 | `path/to/test::name` (passed) | <the observable behaviour checked; "asserts on source text" or "mocks the unit under test" is not proof> |

## Findings

- `path:line` <rule violated: CONTRACTS / pattern skill / ADR / AC / duplication> <what to change> [blocking|minor]

(Write "None." only after doing every item in the checklist.)

## Checklist

- Contract: routes, payloads and errors match CONTRACTS exactly.
- Patterns: shared modules reused, nothing copied; no second ORM/client/helper.
- Tests: each AC test fails if the behaviour breaks; no source-text assertions, no mocking the unit under test.
- Edge states: empty, error and unauthorised paths from the spec/page files exist.
- Security: authz checked server-side; input validated; no secrets.
