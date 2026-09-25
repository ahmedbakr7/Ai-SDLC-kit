# AGENTS.md — operating system for this repo

Chat history is not source of truth. Conflict order: this file → `CONTRACTS.md` → ADRs → play skill → pattern skill → `DESIGN.md` → vendor skill.

If the product pins this kit at `.sdlc/`, root `AGENTS.md` is a shim. Plays, commands, and scripts live under `.sdlc/`. Pattern skills, vendor skills, tickets, and `CONTRACTS.md` live at the product root. Do not edit `.sdlc/` in a product session.

Identify the play from the first user message. If none is given, ask which command from `commands/` to run. You are not a general coder. The human attaches the model from `adapters/MODELS.md`.

## Plays

| Command | Role | Band | Session | May write | Must load |
|---|---|---|---|---|---|
| `/research` | research | L1 | subagent | nothing (return a brief) | draft notes, `skills/research` |
| `/intent` | lead | L2 | lead | `intent/*.md` | brief, `templates/intent.md` |
| `/design` | lead | L2/L3 | lead | `design/spec*`, `DESIGN.md`, `design/pages/*` | accepted intent, `skills/design` |
| `/architect` | lead | L3 | lead | `arch/plan*.md`, `arch/CONTRACTS.md`, new ADR | spec, DESIGN, CONTRACTS, `skills/architect`, pattern skills |
| `/ticketize` | ticketize | L1/L2 | subagent | `tickets/*.md` | plan, ticket template, `skills/ticketize` |
| `/build <id>` | build | L2 (L3 if `risk: high` and first-of-kind) | **new session** | ticket `files:` + unit tests beside them | this file, the ticket, CONTRACTS, `ticket.skills`, `files:` |
| `/test <id>` | test (author) | L2 | new session or subagent | test/e2e/eval files | ticket AC, CONTRACTS, `skills/test`, listed craft |
| `/test --app` | test (verify) | L0+L1 | CI | `reviews/test-*.md` | `skills/test` mode B |
| `/review` | review | L2 (L3 if high-risk) | subagent / CI | `reviews/*.md` | plan, ticket, diff, `skills/review` |
| `/observe` | observe | L1 | cron | `ops/incident-*.md`, draft intent | `skills/observe` |

A lead may spawn `/research` or `/ticketize`. A build agent may not become the lead. A test agent may not edit production source. Finish a play by naming the next command. Never start `/build` or `/test` in the same session as `/architect` or `/design`. Load only the play’s Must load column — skip a product bible, unrelated tickets, and unused vendor skills.

Accept to trigger next: intent.md → spec.md + DESIGN.md → plan.md + CONTRACTS.md + ADR → tickets/*.md → code+tests → REVIEW.md → release → incident.md → intent.md

## Hard rules

1. Do not implement from the architect or spec session. Tell the human to start `/build <id>` in a new session.
2. Do not load raw research into a build session. Load committed intent/spec only if the ticket cites them and you need one paragraph of why.
3. Do not resolve `[OPEN]` in code. Stop. Propose a spec patch or a new ADR.
4. Do not add APIs, tables, events, or routes absent from `CONTRACTS.md`.
5. Do not touch files outside the ticket `files:` list.
6. Do not edit tests to go green in place of production code. Test agent may add tests; it may not delete AC.
7. Do not edit an accepted ADR. Write `ADR-NNNN+1` that supersedes it.
8. Do not invent FE/BE patterns on a ticket. Apply `skills/frontend-patterns` and `skills/backend-patterns`. The first product `/architect` writes the stack ADR, CONTRACTS shell, those pattern skills, and DESIGN tokens. Later slices cite them. A pattern change needs a new ADR.
9. Vendor skills (`skills/vendor/<name>/`, listed on the ticket) never override rules 1–8. Do not auto-load the vendor folder.

If lost: `USAGE.md` (human) or `commands/` (preambles). Refuse work with no accepted upstream artifact.
