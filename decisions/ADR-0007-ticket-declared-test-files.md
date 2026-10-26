---
id: ADR-0007
title: Let a ticket name the extra files its test play may write, instead of splitting tickets
status: accepted
date: 2026-10-26
source: Hangout pilot assessment ("the limit on which files the test step may write forces ticket splits"); proposed 2026-10-21, accepted by the lead in the kit session
---

# ADR-0007: Let a ticket name the extra files its test play may write, instead of splitting tickets

## Context

The test play may write only `tests.integration_globs`, plus its own evidence. When the real-stack
proof needs a fixture, a seed script or a test helper outside those globs, the ticket cannot
ship in one PR. The lead splits it: one ticket builds the helper, another tests through it. Each
split costs a full build, test and review round.

The hard test write set exists for a reason. The test play is meant to prove the AC against the
build, not to change what it is proving. A test play that edits production code could make a
failing AC pass.

Options considered:

- **One play that builds and tests together.** Fewer rounds, but it gives up independent test
  authorship: a different agent writing tests from the AC, not from the code. That is one of the
  levers the pilot credits for the quality gain. Rejected as the default.
- **A ticket field `test_files` (proposed).** The lead lists exact paths or globs, outside
  production source, that the test play may also write. The lead writes it on the base branch,
  like `lane`, so a branch cannot widen its own test write set. `scope` enforces it. The review
  names each file under a new `## Test files` heading.
- **Widen `integration_globs` for everyone.** It loosens every ticket to fix some of them.

## Decision

- Add `test_files: [...]`, read from the ticket as the base branch has it.
- `sdlc lint` refuses entries that match the production scope the gate uses: `tests.source_globs`,
  or the ticket's `areas` and `shared` when `source_globs` is empty. Production code stays the
  build's.
- `sdlc lint` also refuses an entry that covers a file no play may write (lead artifacts, kit
  config, evidence, reviews), and `test_files` on a ticket with no test play.
- The gate enforces what lint checks: the test play's `scope` refuses a `test_files` file that is
  production source, and the build may never write the ticket's `test_files`.
- An approving review names each changed file that only `test_files` allowed under
  `## Test files`, in the review file and in a review record alike.
- A `test_files` entry counts as test code. This needs a code change: today
  `Gate._production_changes` leaves out only `tests.globs`, and the refactor lane's base run
  (`every=True`) reverts every other changed file, so it would revert a `test_files` entry too.
  `_production_changes` must also leave out the ticket's `test_files`. `ac-red` and the refactor
  proof otherwise keep their logic.

## Consequences

- Fewer splits for tickets whose proof needs support files.
- Independent test authorship is kept.
- The lead decides each widening, per ticket, and the review sees it.
- If a helper is later shared by many tickets, it should move into `integration_globs` instead.

## Open questions

- Should a `test_files` entry the test play created become part of the build's write set for
  later tickets? Not decided here: today it does not, and a later ticket that needs it lists it
  again, or the lead moves it into `integration_globs`.
