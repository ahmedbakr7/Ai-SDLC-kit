---
name: build
description: Implement exactly one ticket test-first, inside its write set, until `sdlc gate build <id>` passes. Use for /build <ticket-id>.
---

# Play: build

You turn one `ready` ticket into working, tested code. The runner has already put you
on the ticket's branch and set it `in_progress`. You edit files; it commits, gates
and retries.

## Inputs (all in your prompt)

Ticket, the requirements it cites, the CONTRACTS excerpt, pattern skills, write set,
definition of done. Read the files named in `areas:` and `shared:` before editing.

## Procedure

1. **Understand.** For each AC, write down (to yourself) the input, the observable
   result, and which file produces it. If an AC is ambiguous, stop now and say exactly
   what is missing. A missing AC or a needed file outside the areas is an amendment
   (AGENTS.md rule 7), not a reason to stop: record it in `## Amendments`.
2. **Find what exists.** Your prompt's *Shared modules* table says which modules
   exist (import them), which are yours to create, and which are not built yet (if
   you need one of those, stop). Also search the pattern skills for helpers you must
   reuse (db client, auth/role checks, error envelope, API client, formatting).
   Never re-implement one in your file, even when your write set seems to force it:
   that is a stop, not a workaround.
3. **Red.** For each AC, write the test first, named with its tag:
   - JS/TS: `it("T-001-03/AC-2 unknown id answers 404 not_found", ...)`
   - Python: docstring or name containing `T-001-03/AC-2`

   Run the unit command and watch it fail for the right reason (assertion, not a
   typo or import error).
4. **Green.** Write the smallest production code that makes it pass, following the
   contract exactly: path, method, status codes, payload shape, error codes.
5. **Refactor.** Remove duplication you introduced; keep functions small; name things
   after the domain. Re-run tests.
6. **Gate.** Run `sdlc gate build <id>`. Read every FAIL line and its details. Fix
   the cause, not the symptom, and run it again. Repeat until PASS.
7. **Stop.** Final message: what you built, the AC → test mapping, anything the
   reviewer should look at. Do not change ticket status or open PRs.

## Tests that count

| Proves behaviour | Does not |
|---|---|
| calls the handler/route/component and asserts on the response or rendered text | reads the source file and greps it |
| uses a real DB/test container or the product's fake from the pattern skill | mocks the function under test |
| asserts the error code and status for the failure path | asserts only that "something" was returned |
| one behaviour per test | `.only`, `.skip`, `xit`, commented-out asserts |

## When the gate fails

Debug systematically: reproduce with the exact failing command from the gate output,
read the full log it points to, form one hypothesis, test it, then fix. Do not change
several things at once, and never edit a test's expectation to match wrong output.

| Gate check | Usual cause |
|---|---|
| scope | you edited a lead artifact, another ticket, the test play's files, or your ticket beyond an amendment; revert it or stop and ask (files outside `areas:` are only flagged: say why in your final message) |
| lane | your mechanical diff has changes the transforms do not produce (now standard: it needs AC), or a strict ticket lacks the lead's `accepted_by` |
| contracts | route path or method differs from CONTRACTS; a client call uses an undeclared path |
| ac-coverage | a test is missing its `T-.../AC-n` tag, or that test fails |
| ac-red | the AC's tests also pass with your files reverted: assert on what you built |
| smoke | the app does not start, or the route is not mounted where the contract says |
| build | framework build rules (e.g. Next.js route files may only export handlers) |
| test-quality | skipped/focused tests, tests reading source text |
