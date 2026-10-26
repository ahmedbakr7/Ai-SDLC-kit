---
id: ADR-0008
title: A light path for lead PRs that change only prose
status: accepted
date: 2026-10-26
source: Hangout pilot assessment ("lead PRs need a lot of ceremony"); ADR-0001 section 4; pilot finding 17, shipped in kit v3.0.0 (lead PRs get an independent review as well as the lead's approval); proposed 2026-10-21, accepted by the lead in the kit session
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
  listed reviewer still approves. CI still runs. As a second guard, so that a broad glob such as `**/*.md`
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

## Decision

- Add `[scope] lead_light`, empty by default. The `hardened` preset forbids it.
- A PR that moves no ticket, and whose every changed file matches `lead_light` and no protected
  path, needs one approving review from any reviewer or bot (role `any`, the mechanical lane's
  floor). It no longer needs the independent `review` role, the `lead` role, or the review and
  the lead approval from two identities. One approval is still required; CI still runs.
- The protected paths live in one function (`gate.light_protected`): the kit's own lead write set
  (lead artifacts, AGENTS.md and adapter files, skills, the kit pin, config, baseline, waivers,
  CI workflows); agent instruction files and agent or CI folders at any depth, for every tool
  (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.claude/`, `.cursor/`, `.github/` and the like);
  CODEOWNERS, `.gitattributes` and `.gitmodules`; evidence, review files and `.sdlc-run/`; and
  the test and source globs. Code outside `tests.source_globs` is not protected, so doctor notes
  an empty `source_globs`. A path the lead adds with `scope.lead_allowed` may be light; a kit path repeated
  there stays protected. The approval check refuses the light path for a protected file whatever
  the globs say.
- `lead_light` is read from the base branch's config, like the rest of the approval check, so a PR
  cannot lighten itself.
- `doctor` lists the globs and fails on one that covers a protected path. A `lead_light` value
  that is not a list of globs takes no light path.
- A counted request for changes blocks the light path, as it blocks every other role.
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
  of any approval)? Not decided here: any approval counts.
