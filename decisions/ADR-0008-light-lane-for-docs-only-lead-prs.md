---
id: ADR-0008
title: A light path for lead PRs that change only prose
status: proposed
date: 2026-10-21
source: Hangout pilot assessment ("lead PRs need a lot of ceremony"); ADR-0001 section 4 (lead PRs get independent review, kit v3.0.0 finding 17)
---

# ADR-0008: A light path for lead PRs that change only prose

## Context

A PR that moves no ticket is a lead PR. Since v3.0.0 it needs an independent review, because lead
artifacts (tickets, contracts, ADRs, AGENTS.md, skills) steer every later build. A typo fix in a
README goes through the same ceremony as a change to `arch/CONTRACTS.md`.

Not all prose is equal. AGENTS.md, skills, play templates and prompts are instructions agents
execute. Tickets, contracts, ADRs and specs change what the gate enforces. Only prose that no
agent reads as instructions, and no check reads as data, is safe to lighten.

Options considered:

- **A `[scope] lead_light` glob list (proposed).** A lead PR whose every changed file matches it
  needs only the bot review the mechanical lane accepts, or none when `approval.bots` is empty. CI
  still runs. The kit refuses globs that cover the paths it knows are instructions or data:
  - `AGENTS.md` and adapter files;
  - `skills/` and `.sdlc/`;
  - tickets, design, contracts and decisions;
  - `sdlc.toml` and the baseline and waivers files.
- **Waive review by PR label.** Anyone with label rights could skip review. Rejected.
- **Status quo.** Safe, slow.

## Proposed decision

- Add `lead_light`, empty by default. The `hardened` preset forbids it.
- `doctor` lists the globs and fails on one that overlaps a protected path.
- The approval result names the light path, so the merge record shows it.

## Consequences

- README and guide edits stop costing a review round.
- The protected list must grow with every new kind of instruction or data file the kit reads.
  Missing one would let a light PR steer agents. The list lives in one function, with a test that
  covers each path kind.

## Open questions

- Should a light PR still need the lead's own approval record when the lead is not the author?
