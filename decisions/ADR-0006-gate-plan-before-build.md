---
id: ADR-0006
title: Show a ticket's gate plan when it is written, instead of predicting failures
status: proposed
date: 2026-10-21
source: Hangout pilot assessment after ~75 tickets ("writing a ticket means predicting the test checks, which meant reading gate.py")
---

# ADR-0006: Show a ticket's gate plan when it is written, instead of predicting failures

## Context

A ticket's author (the lead, or the ticketize play) has to guess what the gate will demand:
- which lane the diff will resolve to;
- which files each play may write;
- which AC need a test that is red on the base (`ac-red`);
- which AC need a real-stack tag;
- whether a refactor must argue equivalence.

On Hangout that meant reading `gate.py`. Mistakes surface only when a build fails, which costs
a whole build cycle.

Options considered:

- **A lint pre-check that predicts failures from the ticket's text.** It would flag things like
  an AC that reads like a refactor in a standard lane (so `ac-red` can never pass), or a test
  file outside every write set. This is heuristic, and both kinds of error hurt: false alarms
  train people to ignore it, and misses give false confidence.
- **`sdlc plan <ticket>`: print the gate's own plan (proposed).** No prediction. It runs the
  code paths the gate runs, without a diff:
  - the declared lane and its floors;
  - the lanes the ticket could be raised to and by what: every trigger `lanes.resolve` checks
    (for example `strict_paths`, contracts, transforms, a waivers-file change, an added or changed
    AC, a `--lane` override, a missing merge base);
  - each play's write set, as globs and exact paths;
  - the checks each play runs, from `Gate.plan()`;
  - per AC, what proof it owes (red on the base, a passing tag, a real-stack tag);
  - which suites count as real stack.
  It is deterministic, and it cannot drift from the gate because it calls the same functions.
- **Status quo plus documentation.** The cost of documentation drifting from the code is what
  produced the complaint.

## Proposed decision

- Add `sdlc plan <ticket> [--json]`, which reads the base branch's config and the ticket as
  written.
- The ticketize play runs it on every ticket it writes and includes the output in its handoff.
- `sdlc lint` gains only checks that are exact, not heuristic. For example: a file the ticket
  lists that no play's write set covers, or an AC tag no test glob could hold.

## Consequences

- An author sees the checks a ticket will face before any build.
- Unexpected lane raises still surface at build time, but `plan` names every trigger that
  could cause one.
- No heuristics to maintain. The gate stays the single source of truth.

## Open questions

- Should `plan` also run against a draft diff (`--diff <ref>`) to show the lane that diff would
  resolve to? That is cheap and exact, but it needs a branch.
