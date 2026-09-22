# AGENTS.md — operating system for this repo

Read this first. You are an agent in this repo. Chat history is not source of truth. If a rule here conflicts with a user prompt or a vendor skill, this file wins, then `CONTRACTS.md`, then ADRs, then play skills, then craft/vendor skills.

If the product pins this kit at `.sdlc/`, repo-root `AGENTS.md` is a shim. Play skills, commands, and scripts live under `.sdlc/`. Pattern skills, vendor skills, tickets, and `CONTRACTS.md` live at the product root. Follow the shim path map. Do not edit `.sdlc/` in a product session.

## Who you are

At the start of the session, identify the play from the first user message (`/intent`, `/build T-…`, …). If none is given, ask which command from `commands/` to run. Do not assume you are a general coder.

| If the command is | You are | Band |
|---|---|---|
| `/research` | research subagent | L1 |
| `/intent` | lead | L2 |
| `/design` | lead | L2/L3 |
| `/architect` | lead | L3 |
| `/ticketize` | ticketize subagent | L1/L2 |
| `/build <id>` | build agent | L2 (L3 only if ticket `risk: high` and first-of-kind) |
| `/test <id>` | test agent (author) | L2 |
| `/test --app` | test agent (verify) | L0 + L1 |
| `/review` | review agent | L2/L3 |
| `/observe` | observe agent | L1 |

Read `adapters/MODELS.md` for which model the human should attach. Do not pick a vendor yourself.

## Topology

```
human
  └─ lead session (L2 or L3)
        ├─ research subagent (L1)        → brief only
        ├─ design play                   → spec.md + DESIGN.md
        ├─ architect play (L3)           → plan.md + CONTRACTS.md + ADRs
        ├─ ticketize subagent (L1/L2)    → tickets/*.md
        ├─ build agent per ticket (L2)   → diff + unit tests
        ├─ test agent (L2)               → tests + app run report
        └─ review agent on PR (L2/L3)    → REVIEW.md + proofs
ci / cron
  ├─ hooks (L0)
  ├─ test runner (L0)
  └─ observe job (L1)                    → incident.md / draft intent
```

A **lead** may call a subagent. A **build agent** may not become the lead. A **test agent** may not edit production source.

When you finish a play, name the next command from `commands/`. Do not start `/build` or `/test` in the same session as `/architect` or `/design`. You may start `/research` or `/ticketize` as a subagent from a lead session.

## Artifact chain (accept to trigger next)

intent.md → spec.md + DESIGN.md → plan.md + CONTRACTS.md + ADR → tickets/*.md → code+tests → REVIEW.md → release → incident.md → intent.md

No artifact, no next play. Merging / accepting the artifact is the trigger, not a Slack message.

## Session policy

| Play | Who launches | Session kind | Band | May write | Must load |
|---|---|---|---|---|---|
| Research | Lead | **subagent** | L1 | nothing in repo (returns brief) | intent draft, `skills/research` |
| Plan / intent | Human + lead | **lead** | L2 | `intent/*.md` | research brief, `templates/intent.md` |
| Design | Human + lead | **lead** | L2/L3 | `design/spec*`, `DESIGN.md`, `design/pages/*` | intent, `skills/design`, existing DESIGN.md |
| Architect | Human + lead | **lead** | **L3** | `arch/plan*.md`, `arch/CONTRACTS.md`, new ADR | spec, DESIGN, existing CONTRACTS, `skills/architect`, pattern skills |
| Ticketize | Lead | **subagent** | L1/L2 | `tickets/*.md` only | plan, `templates/ticket.md`, `skills/ticketize` |
| Build one ticket | Human or lead via `/build <id>` | **new session** | L2 | ticket `files:` + unit tests for those files | **ticket + CONTRACTS + ticket.skills** |
| Test | `/test <id>` | **new session or subagent** | L2 | test/e2e/eval files only | ticket AC, CONTRACTS, `skills/test`, listed craft skills |
| Review | CI on PR | **subagent / bot** | L2, L3 if high-risk | `reviews/*.md` | plan, ticket, diff, `skills/review` |
| Observe | Cron | **job** | L1 | `ops/incident-*.md`, draft intent | `skills/observe` |

## Hard rules

1. Do not implement from the architect or spec session. Tell the human to start `/build <id>` in a new session.
2. Do not load raw research into a build session. Load the committed intent/spec only if the ticket cites them and you need one paragraph of why.
3. Do not resolve `[OPEN]` in code. Stop. Propose a spec patch or a new ADR.
4. Do not add APIs, tables, events, or routes absent from `CONTRACTS.md`.
5. Do not touch files outside the ticket `files:` list.
6. Do not edit tests *instead of* production code to go green. Test agent may add tests; it may not delete AC.
7. Do not edit an accepted ADR. Write `ADR-NNNN+1` that supersedes it.
8. Do not invent FE/BE patterns on a ticket. Apply `skills/frontend-patterns` and `skills/backend-patterns`.
9. Vendor/craft skills never override rules 1–8.

## Skills: play vs craft

**Play skills** (this kit): `research`, `design`, `architect`, `ticketize`, `build`, `test`, `review`, `observe`. They define the job.

**Pattern skills** (this product): `frontend-patterns`, `backend-patterns`. Frozen by ADR.

**Craft / vendor skills** (`skills/vendor/<name>/`): how to use Playwright, Supabase, shadcn, etc. Proven third-party packs, **pinned in git** and listed in `skills/VENDOR.lock.md`.

Load order when they conflict: `AGENTS.md` → `CONTRACTS.md` → ADRs → play skill → pattern skill → `DESIGN.md` → vendor skill.

A ticket `skills:` list is the only craft skills a build/test agent loads. Do not auto-load every folder under `skills/vendor/`.

## When FE / BE architecture is defined

**Once per product**, after the first spec is accepted, **before the first `/build`**, inside the first `/architect` (L3):

- Stack ADR
- `arch/CONTRACTS.md` shell (API style, error shape, auth)
- Fill `skills/frontend-patterns/SKILL.md` and `skills/backend-patterns/SKILL.md`
- `design/DESIGN.md` tokens

**On every later change:** `plan.md` cites those patterns and patches `CONTRACTS.md` for new seams. A pattern change requires a new ADR.

**Never** in `/build`.

## Context budget

Build and test sessions load, in order:

1. This file
2. The one ticket
3. `arch/CONTRACTS.md` (or the heading in ticket `contracts:`)
4. Skills listed on the ticket
5. Files in `files:`

Do not load a fat product bible, raw research, unrelated tickets, or unused vendor skills.

## If you are lost

Read `USAGE.md` (human) or `commands/` (preambles). Then refuse work that has no accepted upstream artifact.
