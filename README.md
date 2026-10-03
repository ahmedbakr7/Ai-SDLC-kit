# ai-sdlc kit

A contract-driven, agent-agnostic delivery pipeline for AI-built software. Upstream
artifacts (intent → spec → plan + CONTRACTS → tickets) constrain everything
downstream. A deterministic gate decides when each step is done, so the result does
not depend on which agent or model did the work.

```
intent ─► spec ─► plan + CONTRACTS + ADRs ─► tickets ─► build ─► test ─► review ─► merge
  human     design    architect              ticketize   └──── sdlc run + sdlc gate ────┘
```

## Why

Agents are good at writing code and bad at knowing when it is actually done. Left to
report their own progress, they ship code that type-checks but was never built,
routes mounted at paths the client never calls, tests that grep source files, and
reviews that approve all of it. This kit moves every "is it done?" decision out of
the model and into one command:

| `sdlc gate` check | Fails when |
|---|---|
| `artifacts` | a spec/plan/ticket/review is malformed, a reference does not resolve, deps form a cycle |
| `scope` | a file outside the play's write set changed, or the ticket's status moved in a way the play's role may not (a test agent cannot mark its ticket done) |
| `immutable` | an accepted ADR was edited, or an acceptance criterion was weakened without its spec |
| `contracts` | the code exposes a route, page or table (`[tables] patterns`, Drizzle in the `nextjs` profile) CONTRACTS does not declare, or UI code calls a path no route serves |
| `lint` `typecheck` `unit` `integration` `e2e` `build` | the product's real command exits non-zero, **is not configured**, or **ran zero tests** |
| `ac-coverage` | an acceptance criterion has no passing test tagged `T-001-03/AC-2` in the JUnit output; in `gate ci`, for every ticket in review or done; in `gate test`, no test from a `tests.real_stack` suite (nextjs: e2e) proves any of the ticket's AC |
| `ac-red` | with the ticket's production files reverted to the base branch, every tagged test of some AC still passes: the test does not depend on the work (`expect(true)`, re-testing old behaviour) |
| `test-quality` | tests are skipped/focused or assert on source text instead of behaviour |
| `smoke` | the started app does not serve every contract route and page (`app.mutating_probe = "options"` checks writes via the `Allow` header instead of sending them; the `nextjs` profile sets it) |
| `skills` | a vendored third-party skill drifted from its pinned commit and hash |
| `review-file` | a review misses an AC row, approves a commit other than the latest proven one, or code changed after the reviewed commit; on a PR, the ticket is not yet reviewed and `done` |

Every full gate run writes JSON evidence (`--only` runs are partial and never count).
Ticket plays are judged by the base branch's `sdlc.toml`, so an agent cannot reconfigure
its own gate. CI re-runs the gate and judges the whole ticket branch (`sdlc gate pr`);
it never trusts committed evidence on its own.

## How it runs

| Command | What it does |
|---|---|
| `sdlc init --profile nextjs` | scaffold `sdlc.toml`, folders, AGENTS.md, CI workflow, tool adapters |
| `sdlc doctor` | fail if any required check could pass vacuously (missing command, no `{junit}`, no route extractor) |
| `sdlc lint` / `sdlc trace` | validate artifacts; requirement → ticket → AC → passing test matrix |
| `sdlc next` | the next ticket whose dependencies are done |
| `sdlc prompt build T-001-03` | the exact, complete prompt for a play: rules, skill, ticket, cited requirements and contracts, write set, definition of done |
| `sdlc gate build T-001-03` | run every check for the play; write evidence |
| `sdlc gate pr [T-001-03]` | CI: judge a ticket's whole branch (write sets, status moves, the ticket is reviewed and `done`, the approval covers what merges); without an id it finds the ticket the branch moves, or reports code changed without one |
| `sdlc run build T-001-03 --agent X` | branch → status → prompt → agent → commit → gate → retry with the failures → evidence → `in_review` |
| `sdlc status T-001-03 done --as merge` | move through the state machine; `done` requires an approval of the latest proven commit with nothing changed since |
| `sdlc skills add superpowers/test-driven-development` | vendor a proven skill, pinned by commit + content hash |
| `sdlc adapters sync` | regenerate CLAUDE.md, GEMINI.md, Cursor rules, Copilot instructions, slash commands |
| `sdlc routes` | list routes: declared and built, built but undeclared, declared but not built |
| `sdlc migrate` | upgrade v0.x tickets (number acceptance criteria) |
| `sdlc baseline [--prune]` | record the failures a red base branch already has; gates and `trace` then fail only on new ones, and the file only shrinks |

Stdlib-only Python ≥ 3.11. Works with any agent CLI that can take a prompt
(Claude Code, Codex, Gemini CLI, Grok, Cursor agent, Aider, ...): agents only edit
files, and the runner does everything else the same way for all of them.

## Start

- New or existing product: [CONSUME.md](CONSUME.md)
- Agent tools and the runner: [adapters/README.md](adapters/README.md)
- Walk a complete, runnable slice: [examples/returns-app](examples/returns-app/README.md)
- Upgrading from kit v0.x: [MIGRATION.md](MIGRATION.md)
- Rules every agent follows: [AGENTS.md](AGENTS.md)

## Layout

```
AGENTS.md         operating rules (inlined into every generated prompt)
bin/sdlc          CLI entry (sh / .cmd)
sdlc/             the CLI (stdlib Python)
skills/           play skills + pattern-skill templates + vendor catalog
templates/        intent, spec, page, plan, CONTRACTS, ADR, ticket, review, incident, sdlc.toml
profiles/         stack defaults: nextjs, node, python
adapters/         CI workflow template, agent/tool binding docs
examples/         returns-app: a runnable product the kit's own tests drive end to end
tests/            unit, gate-regression and conveyor tests (python -m unittest, from tests/)
```

## Develop the kit

```bash
cd tests && python -m unittest           # parser, every gate check, full conveyor
python tests/regen_example.py            # re-prove the example after changing the gate
```

A kit change that weakens a check must update `tests/test_gate.py`, which exists to
keep every check catching the defect it was added for.
