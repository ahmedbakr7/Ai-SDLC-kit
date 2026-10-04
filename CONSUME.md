# Use the kit in a product

## 1. Pin it

```bash
git submodule add -b main https://github.com/ahmedbakr7/Ai-SDLC-kit.git .sdlc
git -C .sdlc checkout <tag>          # pin a release
.sdlc/bin/sdlc init --profile nextjs # or node | python | (none)
```

`init` creates (never overwrites):

```
sdlc.toml                 commands, routes extractor, test globs, agents
AGENTS.md                 points every agent at .sdlc/AGENTS.md and the CLI
skills.lock.json          pinned vendor skills (empty)
skills/frontend-patterns, skills/backend-patterns   filled in the first /architect
intent/ design/ arch/ decisions/ tickets/ reviews/ evidence/ ops/
.github/workflows/sdlc.yml                          the gate on every PR
CLAUDE.md GEMINI.md .cursor/rules/ .github/copilot-instructions.md .claude/commands/   (adapters sync)
.gitignore += .sdlc-run/
```

On Windows use `.sdlc\bin\sdlc.cmd`. Put `.sdlc/bin` on PATH to type `sdlc`.

If the kit repo is private, CI cannot clone `.sdlc` with the default token ("repository not
found" in checkout). Create a fine-grained token with Contents read on the product and the kit,
and add it as the product secret `SDLC_KIT_TOKEN`; the installed workflow uses it.

## 2. Make the gate real

Edit `sdlc.toml` until `sdlc doctor` passes. Doctor fails when a required check could
pass without checking anything:

- every required command is set (`lint`, `typecheck`, `unit`, `build`, `start`);
- test commands write JUnit to `{junit}` (vitest: `--reporter=junit --outputFile.junit={junit}`,
  jest: `jest-junit`, pytest: `--junitxml={junit}`, Playwright: `PLAYWRIGHT_JUNIT_OUTPUT_NAME={junit}` with the `junit` reporter);
- a real-stack suite runs (`tests.real_stack`: integration or e2e; nextjs: e2e, because Vitest
  integration tests call handlers in-process), or the lead sets `tests.real_stack = []` to accept
  unit-only proof;
- a route extractor is configured (`nextjs-app`, which also reports pages, or `command` printing
  `METHOD /path` lines and, optionally, `PAGE /path` lines for server-rendered pages).

An existing codebase over the duplication threshold: set `--threshold` in `commands.duplication`
to today's level and lower it as clones are removed, so new copies fail from the first PR.

An existing codebase whose main is already red: run `sdlc baseline` and commit
`sdlc-baseline.json` in a lead PR. Every gate then fails only on failures it does not list
(type errors keyed `file: code`, failing tests by name, other findings without line
numbers). The file only shrinks: `immutable` refuses added entries, a ticket may not create
it, and `gate ci` fails until fixed entries are removed with `sdlc baseline --prune`.
`sdlc trace` reads it too, so shipped tickets adopted without evidence do not keep CI red;
a ticket shipped after the baseline must still be proven. Scope, immutable, review-file,
skills and ac-red are never baselined.

Commit, then mark the `gate` job required in branch protection.

## 3. Run the pipeline

| Step | Who | Command |
|---|---|---|
| intent, design, architect | lead + agent, interactive | `sdlc prompt intent` → give the file to your agent; human accepts the artifact |
| ticketize | agent | `sdlc prompt ticketize`; then `sdlc lint && sdlc trace`; lead sets tickets `ready` |
| build | any agent, unattended | `sdlc run build $(sdlc next) --agent <name>` |
| test | any agent | `sdlc run test T-001-03 --agent <name>` |
| review | a **different** agent | `sdlc run review T-001-03 --agent <other>` |
| merge | human | on the ticket branch: `sdlc status T-001-03 done --as merge`, commit, push; open the PR; CI runs `sdlc gate pr`; merge on green |

`sdlc run` refuses a dirty tree, unmet dependencies, and a reviewer that made any
build or test commit on the ticket. Every runner commit carries `Sdlc-Agent:` and
`Sdlc-Play:` trailers. Agent output goes to `.sdlc-run/logs/agent-<play>-<id>-<n>.log`.
The runner stops without committing if the agent switched branches or rewrote history.

Review happens before the PR. `done` is set on the ticket branch, so the PR that merges
the code also carries the status and CI checks the approval with `sdlc gate pr`, which
fails on a ticket that is not `done`. A PR therefore arrives reviewed and merges on green.
PR-level review bots (configured by the product, not the kit) comment on that PR; resolve
their blocking findings before merging.

### Lanes, areas and amendments

The gate picks each ticket's lane ([ADR-0001](decisions/ADR-0001-lanes-areas-forge-approval.md)):

- **mechanical**: a rename or move. The lead (or the PR itself, for a ticket whose transforms
  explain the whole diff) writes `lane: mechanical` and `transforms:`; build runs `gate.mechanical`
  (every `gate ci` check plus `mechanical`), there is no test play, and one review approves.
  Any change the transforms do not produce makes the PR standard.
- **standard**: the flow above.
- **strict**: `risk: high`, `type: contract`, a CONTRACTS change or a `lanes.strict_paths` file.
  The lead sets `accepted_by` on the ticket in a lead PR first; build, test and PR also run
  `contract-diff`, and real-stack suites cannot be skipped.
- **spike** tickets (`type: spike`) answer `questions:` (`Q-1: ...`) in findings files inside
  their areas and change no code or tests.

`areas:` (globs) replaces `files:`. A build may touch other files; the gate flags them and the
approving review names each under `## Out of area`. Lead artifacts, other tickets, config and
the test play's files stay off limits. The build amends its own ticket in `## Amendments`
(`add`, `strengthen`, `split`, `widen`); weakening or removing an AC still needs the spec.

Without `sdlc run` (agent in an IDE): `sdlc status T-001-03 in_progress --as build`,
give the agent `sdlc prompt build T-001-03`, have it iterate on `sdlc gate build
T-001-03`, commit, then `sdlc status T-001-03 in_review --as build`.

## 4. Upgrade the kit

```bash
git -C .sdlc fetch --tags && git -C .sdlc checkout <new tag>
.sdlc/bin/sdlc doctor && .sdlc/bin/sdlc adapters sync && .sdlc/bin/sdlc gate ci
git add .sdlc && git commit -m "bump ai-sdlc kit to <tag>"
```

Never edit `.sdlc/` inside a product: change the kit repo and bump the pin.
