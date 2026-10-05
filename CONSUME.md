# Use the kit in a product

## 1. Pin it

```bash
git submodule add https://github.com/ahmedbakr7/Ai-SDLC-kit.git .sdlc
git -C .sdlc checkout v1.2.0-rc1     # pin a release tag (CHANGELOG.md lists them)
git add .gitmodules .sdlc && git commit -m "pin ai-sdlc kit v1.2.0-rc1"
.sdlc/bin/sdlc init --profile nextjs # or node | python | (none)
```

The product records the commit the tag names, so every clone and CI run gets the same kit.
`git -C .sdlc describe --tags` and `.sdlc/bin/sdlc --version` show which release is pinned.
Pin tags, not `main`: `git submodule update --remote` moves the pin to the newest commit on the
kit's branch, released or not, so leave it out of scripts and CI (`actions/checkout` with
`submodules: true` checks out the recorded commit).

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

### Approvals outside the tree

Set `[approval] mode = "forge"` (GitHub) or `"git"` (signed notes in `refs/notes/sdlc`) in a lead PR:

- The review play writes `.sdlc-run/review-<id>.md`; `sdlc review publish <id> --pr N` posts it.
- CI runs the `gate` job (`.github/workflows/sdlc.yml`: the lane's checks on the head) and
  `.github/workflows/sdlc-approval.yml`, which `sdlc init` installs with its relay
  `sdlc-approval-review.yml`: on `pull_request_target`, comments, and each review (relayed with
  no permissions, then judged on `workflow_run`), it runs the base branch's kit against the PR
  head (read as data) and posts the `sdlc/approval` commit status. Require both the `gate`
  check and the `sdlc/approval` status.
- What branch protection can and cannot prove: the `gate` check and the `sdlc/approval` status
  come from GitHub Actions, and any workflow or token with write access can post a check or status
  with the same name (a same-repository PR can add a workflow that does, or edit its copy of the
  review relay so a dismissal is never relayed; `gate` fails a ticket PR that touches
  `.github/workflows/`, and a PR without a ticket needs a lead). Against that, post the
  approval from a GitHub App and pin the app as the required check's source, and require review
  of `.github/workflows/`. Without it, the gate and the approval stop mistakes and confused
  agents, not someone with write access.
- The token goes only to the API host in `GITHUB_API_URL` (Actions sets it; default
  `https://api.github.com`), never to a host named in `sdlc.toml`, which a PR can edit.
- In `git` mode a lead's own PR needs a second lead (a signer may not approve their own commits).
- A PR that names no ticket (config, CI, the kit pin, contracts, tickets) needs a lead approval.
  Review records count only unedited (comments) and on the commit the forge recorded (reviews).
- List the reviewer, lead and bot identities in `[approval]`. They must differ from the identity
  that opens PRs. If one account does everything, set `trust_unsigned = true`: approvals then need
  write access only, and every result says they are trust-based.
- Commits carry `Sdlc-Ticket: <id>` (`sdlc run` and `sdlc commit` add it). Tickets store only
  `draft`, `ready` or `blocked`; `sdlc migrate` rewrites old delivery statuses. `reviews/` and
  `evidence/` stay as read-only history.
- Weakening or removing an AC by amendment needs a lead approval; a strict ticket needs one too.

Without `sdlc run` (agent in an IDE): `sdlc status T-001-03 in_progress --as build`,
give the agent `sdlc prompt build T-001-03`, have it iterate on `sdlc gate build
T-001-03`, commit, then `sdlc status T-001-03 in_review --as build`.

## 4. Upgrade the kit

Read the CHANGELOG.md entries between your tag and the new one first: a MAJOR bump can fail
checks that passed, and an entry's new settings stay off until `sdlc.toml` turns them on.

```bash
git -C .sdlc fetch --tags && git -C .sdlc checkout <new tag>
.sdlc/bin/sdlc doctor && .sdlc/bin/sdlc adapters sync && .sdlc/bin/sdlc gate ci
git add .sdlc && git commit -m "bump ai-sdlc kit to <tag>"
```

The bump is a lead PR (it changes no ticket). If the kit's CI workflow templates changed
(`adapters/github/*.yml`), copy them into `.github/workflows/` in the same PR. The approval
check runs the base branch's kit, so a PR that both bumps the kit and relies on its new
behaviour sees the old kit until it merges.

Never edit `.sdlc/` inside a product: change the kit repo and bump the pin.
