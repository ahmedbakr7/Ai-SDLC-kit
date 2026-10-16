---
id: ADR-0004
title: A refactor lane for changes the lead declares behaviour-neutral
status: accepted
date: 2026-10-16
source: ADR-0001 section 1; Hangout pilot T-001-56 (three failed builds on ac-red); lead approval in the kit session
supersedes: ADR-0001
---

# ADR-0004: A refactor lane for changes the lead declares behaviour-neutral

## Context

ADR-0001 section 1 gives every ticket PR one of three lanes, `mechanical < standard < strict`.
The mechanical lane takes renames and moves that declared transforms reproduce exactly. Anything
else is standard, and the standard build runs `ac-red`: each AC needs a tagged test that fails
with the ticket's production files put back to the base.

A refactor that is not a rename (merge two copies of a loader into one function, extract a
helper, simplify a branch) keeps behaviour by design. Every test of that behaviour passes on the
base, so `ac-red` can never pass. `ac-red` is never waived or baselined, so the ticket cannot
ship. The Hangout pilot hit this on T-001-56: three build attempts, all red on `ac-red`, and the
agent reported it could write no test that is red on the base without changing behaviour or
reading source text. Other refactor tickets on that roadmap would hit the same wall.

Options considered:

- **A refactor lane (chosen).** The lead declares the lane; its build proves the opposite of
  `ac-red`: the AC tests pass on the base and on the head. Guards keep the proof from being
  rewritten along with the code.
- **Waive `ac-red` per ticket.** Keeps no proof at all, and `ac-red` is unwaivable for a reason.
- **Write the refactor as a behaviour change.** Forces a fake AC, or a test on source text.
- **Mechanical transforms for refactors.** Transforms are literal replays; a refactor is not one.

## Decision

1. **Lanes.** The lane order becomes `mechanical < refactor < standard < strict`. This replaces
   the lane list in ADR-0001 section 1 and nothing else in ADR-0001. The engine still never
   lowers a lane: `lane: refactor` is a lead decision on the base branch, and a ticket PR may not
   move a ticket from standard to refactor (`scope` refuses lowering the lane). Triggers that
   raise a lane apply unchanged: a refactor that touches CONTRACTS, the waivers or a
   `lanes.strict_paths` file becomes strict.
2. **Build list.** `[gate] refactor` is the standard build list with `refactor` in place of
   `ac-red`, plus every configured test suite. Like the mechanical lane it has no test play: the
   whole suite in its build is the proof, and `gate test` refuses the lane. `doctor` holds the
   list to a floor (`artifacts`, `scope`, `immutable`, `contracts`, `lint`, `typecheck`, `unit`,
   `ac-coverage`, `refactor`, `test-quality`, `build`, and every configured suite).
3. **The `refactor` check** fails unless all of these hold:
   - Some production file (as `ac-red` counts them: `[tests] source_globs`, else the ticket's
     areas and shared globs, minus tests) differs from the merge base. A refactor changes code.
   - Every test file that exists on the base still exists, and none of its lines is removed or
     rewritten, except to add AC tags (`<ticket>/AC-n`) in a title or docstring. New tests and
     new test files are free.
   - With the production files put back to the base, each AC has at least one tagged test that
     runs, and every tagged test passes. A test that needs the new code, or fails on the base,
     pins new behaviour. `ac-coverage` already proves the same tests pass on the head.
   `refactor` is never waived or baselined.
4. **Review.** An approval of a refactor argues why behaviour is unchanged in a non-empty
   `## Equivalence` section, beside the AC rows. `review-file` (file mode) and `sdlc approval`
   (records mode) reject an approval without one. Approval roles are the standard lane's: an
   independent reviewer.

## Consequences

- Refactor tickets can ship with proof: the tests that pin the old behaviour still pass against
  the base and the head, the diff cannot rewrite them, and a reviewer argues equivalence.
- The proof is weaker than `ac-red`: a change that keeps every tagged test green but alters
  untested behaviour passes the gate. The non-empty diff, the frozen tests, the whole suite in the
  build and the `## Equivalence` argument narrow that gap; the reviewer closes it.
- Lines added inside an existing test can still weaken it (an early `return`, a new guard).
  `test-quality` catches skipped and focused tests; the reviewer reads every added line in an
  existing test file.
- Moving or renaming an existing test file fails the frozen-test rule. Split such a ticket: a
  mechanical move, then the refactor.
- A refactor raised to strict by a trigger runs the strict lane, which runs `ac-red`, so it
  cannot pass. Keep refactors off strict paths, or split the strict part out.
- Tests that call a function the refactor creates fail on the base and so cannot be AC proof.
  AC tests go through interfaces the base already has.

## Not decided

- Requiring the AC tests to cover the changed lines, when a product configures a coverage
  command. It would close most of the remaining gap, but needs per-stack coverage output.
- Letting a ticket name a metric that must improve (for example duplicated blocks in the
  changed files).
