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
| `lane` | the ticket's lane does not hold: a standard or strict ticket has no AC, a strict ticket has no lead sign-off on the base branch, a non-mechanical ticket was created in its own PR, or (on a PR) evidence ran in a looser lane than the branch needs |
| `scope` | a lead artifact, another ticket or another play's file changed, the ticket was edited beyond amendments, or its status moved in a way the play's role may not; a file outside the ticket's areas is a flag the review must accept, not a failure |
| `immutable` | an accepted ADR was edited, or an acceptance criterion was weakened, removed or added without its spec or an amendment line |
| `mechanical` | the diff is not exactly the ticket's declared transforms, byte for byte (modes, line endings and binaries included; a move must move, never copy or overwrite); such a PR runs in the standard lane instead |
| `contract-diff` | strict lane: a CONTRACTS key (its attributes, its prose section, a table's fields) changed that the ticket does not cite; removed and narrowed keys are reported as breaking, prose outside every key is reported |
| `spike` | a spike changed anything but documents in the areas the lead gave it, or a question has no findings heading |
| `contracts` | the code exposes a route, page or table (`[tables] patterns`, Drizzle in the `nextjs` profile) CONTRACTS does not declare, or UI code calls a path no route serves |
| `lint` `typecheck` `unit` `integration` `e2e` `build` | the product's real command exits non-zero, **is not configured**, or **ran zero tests** |
| `ac-coverage` | an acceptance criterion has no passing test tagged `T-001-03/AC-2` in the JUnit output; in `gate ci`, for every ticket in review or done; in `gate test`, no test from a `tests.real_stack` suite (nextjs: e2e) proves any of the ticket's AC |
| `ac-red` | with the ticket's production files reverted to the base branch, every tagged test of some AC still passes: the test does not depend on the work (`expect(true)`, re-testing old behaviour) |
| `test-quality` | tests are skipped/focused or assert on source text instead of behaviour |
| `smoke` | the started app does not serve every contract route and page (`app.mutating_probe = "options"` checks writes via the `Allow` header instead of sending them; the `nextjs` profile sets it) |
| `skills` | a vendored third-party skill drifted from its pinned commit and hash |
| `review-file` | a review misses an AC row, approves a commit other than the latest proven one, or code changed after the reviewed commit; an approval does not name each out-of-area file under `## Out of area` and each new `strengthen`/`split`/`widen` amendment under `## Amendments`; on a PR, the ticket is not yet reviewed and `done` |

Every ticket runs in a **risk lane** ([ADR-0001](decisions/ADR-0001-lanes-areas-forge-approval.md)), chosen by
the engine from the ticket and the diff; it may raise a lane, never lower it:

| Lane | When | Runs |
|---|---|---|
| mechanical | the ticket declares `lane: mechanical` and `transforms:` (literal, identifier rename, file move), and replaying them on the base gives the whole diff | every `gate ci` check plus `mechanical`; no `ac-red`, no test play; one review |
| standard | the default | build with `ac-red`, test play through the real stack, independent review |
| strict | `risk: high`, `type: contract`, a CONTRACTS change, or a file in `lanes.strict_paths` | standard plus `contract-diff`, real-stack suites that cannot be skipped, and `accepted_by` set by the lead on the base branch |

Approvals can live outside the tree (`[approval] mode = "forge"` or `"git"`, ADR-0001 step 2).
Then an approval is a record bound to the reviewed commit: it covers the head while the PR's own
change is the same, location-exact (a base merge keeps it, editing or moving an approved line voids
it), and it counts only from identities in `[approval] reviewers` / `leads` / `bots` that neither
opened the PR nor wrote its commits. With one identity for everyone that cannot hold: the lead sets
`trust_unsigned = true`, write access is still required, and every result says it is trust-based.
Evidence stays in CI (`.sdlc-run/`, uploaded as an artifact), `gate pr` re-proves the lane's checks
on the head, and a ticket's delivery status is derived: `done` once a merged commit carries
`Sdlc-Ticket: <id>`. The default `mode = "file"` keeps `reviews/<id>.md`, committed evidence and
stored status.

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
| `sdlc approval [--pr N]` | CI (`[approval] mode = forge` or `git`): an approval covers the PR's head for every role its lane needs |
| `sdlc review publish T-001-03 [--pr N]` | publish the review agent's record: a PR comment (forge) or a note on the reviewed commit (git) |
| `sdlc commit T-001-03 -m "..." --agent NAME --play build` | commit with the `Sdlc-Agent`, `Sdlc-Play` and `Sdlc-Ticket` trailers the approval and derived status read |
| `sdlc followups --pr N` | draft tickets from an approval's `[follow-up]` findings |
| `sdlc baseline [--prune]` | record the failures a red base branch already has; gates and `trace` then fail only on new ones, and the file only shrinks |

Stdlib-only Python ≥ 3.11, git ≥ 2.32. Works with any agent CLI that can take a prompt
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
