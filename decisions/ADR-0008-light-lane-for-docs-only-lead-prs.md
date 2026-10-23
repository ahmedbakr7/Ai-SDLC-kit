---
id: ADR-0008
title: A light path for lead PRs that change only prose
status: proposed
date: 2026-10-21
source: Hangout pilot assessment ("lead PRs need a lot of ceremony"); ADR-0001 section 4; pilot finding 17, shipped in kit v3.0.0 (lead PRs get an independent review as well as the lead's approval)
---

# ADR-0008: A light path for lead PRs that change only prose

## Context

A PR that moves no ticket is a lead PR. Since v3.0.0 it needs two approvals: an independent
review and the lead's approval, from two identities unless approvals are trust-based
(roles `review` and `lead` in `sdlc/approval.py`). Lead artifacts (tickets, contracts,
ADRs, AGENTS.md, skills) steer every later build, so both are there for a reason. But a typo fix in
a README goes through the same ceremony as a change to `arch/CONTRACTS.md`.

Not all prose is equal. AGENTS.md, skills, play templates and prompts are instructions agents
execute. Tickets, contracts, ADRs and specs change what the gate enforces. Only prose that no
agent reads as instructions, and no check reads as data, is safe to lighten.

Options considered:

- **A `[scope] lead_light` glob list (proposed).** It is an allowlist: only paths the lead names
  qualify. A lead PR whose every changed file matches it needs what a mechanical ticket PR needs,
  one approving review from any reviewer or bot. It no longer needs the independent `review` role,
  the `lead` role or two identities. There is no zero-approval case: with `approval.bots` empty, a
  person still approves. CI still runs. As a second guard, so that a broad glob such as `**/*.md`
  cannot reach instructions, the kit refuses globs that cover the paths it knows are instructions
  or data:
  - `AGENTS.md` and adapter files;
  - `skills/` and `.sdlc/`;
  - tickets, design, contracts and decisions;
  - `sdlc.toml` and the baseline and waivers files.
- **Allowlist only, no protected list.** Simpler, and it already fails safe for paths the lead
  did not name. But one careless glob would lighten AGENTS.md or a ticket. The protected list is
  cheap insurance against that, so the proposal keeps both.
- **Waive review by PR label.** Anyone with label rights could skip review. Rejected.
- **Status quo.** Safe, slow.

## Proposed decision

- Add `lead_light`, empty by default. The `hardened` preset forbids it.
- `doctor` lists the globs and fails on one that overlaps a protected path.
- The approval result names the light path, so the merge record shows it.

## Consequences

- README and guide edits drop from two approvals (independent review plus lead) to one from any
  reviewer or bot. This is weaker than today's lead-PR rule by design, and equal to the mechanical
  lane's floor; it is never zero.
- It changes what ADR-0001 section 4 and v3.0.0 decided for these paths only. Accepting this ADR
  amends that rule; every other lead PR keeps both approvals.
- The protected list must grow with every new kind of instruction or data file the kit reads.
  Missing one matters only if the lead also writes a glob that covers it, since `lead_light` is
  itself an allowlist. The list lives in one function, with a test that
  covers each path kind.

## Open questions

- Should a light PR keep the `lead` role when the lead is not the author (one lead record instead
  of any approval)?
