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

Commit, then mark the `gate` job required in branch protection.

## 3. Run the pipeline

| Step | Who | Command |
|---|---|---|
| intent, design, architect | lead + agent, interactive | `sdlc prompt intent` → give the file to your agent; human accepts the artifact |
| ticketize | agent | `sdlc prompt ticketize`; then `sdlc lint && sdlc trace`; lead sets tickets `ready` |
| build | any agent, unattended | `sdlc run build $(sdlc next) --agent <name>` |
| test | any agent | `sdlc run test T-001-03 --agent <name>` |
| review | a **different** agent | `sdlc run review T-001-03 --agent <other>` |
| merge | human | on the ticket branch: `sdlc status T-001-03 done --as merge`, commit, push; CI runs `sdlc gate pr`; then merge the PR |

`sdlc run` refuses a dirty tree, unmet dependencies, and a reviewer that made any
build or test commit on the ticket. Every runner commit carries `Sdlc-Agent:` and
`Sdlc-Play:` trailers. Agent output goes to `.sdlc-run/logs/agent-<play>-<id>-<n>.log`.
The runner stops without committing if the agent switched branches or rewrote history.

`done` is set on the ticket branch, so the PR that merges the code also carries the
status and CI checks the approval with `sdlc gate pr`. Setting `done` on the base
branch after merging also works, but then no CI run covers the status change.

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
