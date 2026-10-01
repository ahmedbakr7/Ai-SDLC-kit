---
id: spec-NNN
title: <title>
status: draft            # draft | accepted | superseded
source_intent: intent/intent-NNN-<slug>.md
---

# Spec NNN: <title>

## Requirements

One observable behaviour per line, with a stable id. A test can pass or fail on it
without asking anyone. F = functional, N = non-functional (limits, fallbacks, a11y,
i18n, performance with a number).

- **F-NNN-1** <actor> <does/sees> <result> when <condition>.
- **N-NNN-1** <quality> is <measurable bound>.

Bad: "Fast page." "Nice errors." "Supports Arabic."
Good: "**N-NNN-2** The plan page renders its first meaningful content within 1.5 s on a cold load over Fast 3G."

## Pages

- `design/pages/<route>.md` (one per screen; every state: loading, empty, error, loaded)

## Decisions

- [DECISION: ADR-NNNN] <choice already made, with the ADR that records it>

## Open

- [OPEN: <question>] (Tickets must not resolve these in code. "None." when empty.)
