# Use the kit in a product

## 1. Pin it

The kit needs Python 3.11 or later and git 2.32 or later (`sdlc commit` uses `git commit --trailer`).

```bash
git submodule add https://github.com/ahmedbakr7/Ai-SDLC-kit.git .sdlc
git -C .sdlc checkout v3.1.0     # pin a release tag (CHANGELOG.md lists them)
git add .gitmodules .sdlc && git commit -m "pin ai-sdlc kit v3.1.0"
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
numbers), each with a count. Paths in keys follow the renames git detects, so moving a file
keeps its known failures known. The file only shrinks: `immutable` refuses added entries, a ticket may not create
it, and `gate ci` fails until fixed entries are removed with `sdlc baseline --prune`.
`sdlc trace` reads it too, so shipped tickets adopted without evidence do not keep CI red;
a ticket shipped after the baseline must still be proven. Scope, immutable, review-file,
skills and ac-red are never baselined.

A done ticket `gate ci` names as lacking real-stack proof cannot run its own test play again
(`sdlc run` refuses a done ticket). Prove it with a `type: test` ticket: its real-stack tests carry
their own AC tag and one of the done ticket's, e.g. `T-001-90/AC-1 proves T-001-05/AC-2`. One
test ticket can prove several done tickets. The fallback is a waiver from the lead.

A failure main already has that cannot be fixed yet (a flaky vendor test, a lint rule a hotfix
cannot meet) gets a waiver in `sdlc-waivers.toml` (kit v1.4.0-rc1 or later), in a lead PR: an exact `key` and `count` as
the gate prints it, an `owner`, a `reason` and an `expires` date at most `[waivers] max_days`
(90) away. It applies once merged, and lists every waived failure with its owner and expiry.
`gate ci` fails when it expires, when the failure is gone, or when its renewals (`renews`) reach
twice `max_days`; fix the failure, or move it into the baseline. A ticket PR touching the file
is strict.

A strictness preset sets the lane lists, triggers and limits in one line: `[gate] preset =
"default"` (today's lists), `"hardened"` (no trust-based approvals, a human reviewer for
mechanical PRs, workflows, config, the kit pin and dependency manifests make a PR strict, nothing
optional, 30-day waivers without renewal, and code in a PR that names no ticket fails unless it
exactly reverts code already on the base branch), or `"floor"` (ADR-0001 section 6: no duplication or
smoke checks, for adopting the kit). Your own `[gate]`, `[lanes]` and `[waivers]` keys still
override it, except where `hardened` forbids loosening; `doctor` prints what results.

The app runs on `app.port` (3123) for smoke and the `{port}` / `{base_url}` placeholders. To run
two gates at once on one machine (one worktree each), set `SDLC_APP_PORT` in each shell
(kit v4.0.0 or later); it overrides `app.port` there only, nothing committed changes, and
`doctor` prints the port in effect. Ports your own test configs hard-code (a Playwright
`webServer`, a stub server) need the same treatment in the product.

Parallel gates without per-shell settings (kit v5.1.0 or later): `app.port = "auto"` (or
`SDLC_APP_PORT=auto`) picks a free port for each run. Every command the gate runs sees it as
`SDLC_APP_PORT` (and `{port}`), so read it there instead of hard-coding a port. For a database
or other state two runs must not share, set `[app] setup` and `teardown`. `setup` runs before the
checks with `SDLC_RUN_ID`, `SDLC_APP_PORT` and `SDLC_RUN_ENV` set; each `KEY=VALUE` line it
appends to `$SDLC_RUN_ENV` reaches every command (for example
`DATABASE_URL=postgres://localhost/app_$SDLC_RUN_ID` after it creates that database). A failed
setup fails the gate and skips its checks. `teardown` runs after the checks whatever happened,
and a failed teardown fails the gate. Commands also see `SDLC_RUN_ID`. An auto port is free when
the gate picks it; another process could take it before the app binds, which smoke reports as a
busy port (rerun the gate).

Binary files (icons, fonts, fixture images) are declared, not hand-made (kit v5.5.0, ADR-0009).
The lead lists each in `assets.toml` with its sha256 and either a `generate` command run from
committed text sources or a pinned `source` URL:

    [[asset]]
    path = "public/logo.png"
    sha256 = "<64 hex>"
    generate = "node tools/render-logo.js"

`sdlc assets` produces or fetches each one and verifies it; `sdlc assets --check` only verifies.
The `assets` check reports every binary a branch adds or changes that is undeclared or differs
from its sha256. It passes with a warning until the lead sets `[assets] mode = "fail"`. A ticket's
gate reads `assets.toml` as the base branch has it: declare an asset in a lead PR first.

Commit, then mark the `gate` job required in branch protection.

## 3. Run the pipeline

| Step | Who | Command |
|---|---|---|
| intent, design, architect | lead + agent, interactive | `sdlc prompt intent` → give the file to your agent; human accepts the artifact |
| ticketize | agent | `sdlc prompt ticketize`; then `sdlc lint && sdlc trace`; `sdlc plan <id>` per ticket; lead sets tickets `ready` |
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
- **refactor** ([ADR-0004](decisions/ADR-0004-refactor-lane.md)): the lead declares a change that
  keeps behaviour (`lane: refactor`, with AC that pin the behaviour kept). Build runs
  `gate.refactor`: the standard build with `refactor` in place of `ac-red`, plus every test suite;
  there is no test play. `refactor` fails unless production code changed, existing tests only
  gained AC tags or new tests, and each AC's tagged tests run and pass with the production files
  put back to the base. The approving review argues why behaviour is unchanged under
  `## Equivalence`.
- **standard**: the flow above.
- **strict**: `risk: high`, `type: contract`, a CONTRACTS change or a `lanes.strict_paths` file.
  The lead sets `accepted_by` on the ticket in a lead PR first; build, test and PR also run
  `contract-diff`, and real-stack suites cannot be skipped.
- **spike** tickets (`type: spike`) answer `questions:` (`Q-1: ...`) in findings files inside
  their areas and change no code or tests.

`areas:` (globs) replaces `files:`. A build may touch other files; the gate flags them and the
approving review names each under `## Out of area`. Lead artifacts, other tickets, config and
the test play's files stay off limits. When the proof needs a fixture or helper outside
`tests.integration_globs`, the lead lists it in the ticket's `test_files:` on the base branch
(ADR-0007): the test play may then write it, the build may not, and the approving review names
each changed one under `## Test files`. Set `[tests] source_globs`: without it the gate counts
only the ticket's own areas as production source, so an entry naming another ticket's source
passes `sdlc lint` and only the reviewer stops it. The build amends its own ticket in `## Amendments`
(`add`, `strengthen`, `split`, `widen`); weakening or removing an AC still needs the spec.

### Approvals outside the tree

Set `[approval] mode = "forge"` (GitHub) or `"git"` (signed notes in `refs/notes/sdlc`) in a lead PR:

- The review play writes `.sdlc-run/review-<id>.md`; `sdlc review publish <id> --pr N` posts it.
- A lead PR's reviewer gets `sdlc prompt review --pr N` and writes `.sdlc-run/lead-review-N.md`;
  `sdlc review publish --pr N` posts it.
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
- A PR that names no ticket (config, CI, the kit pin, contracts, tickets) needs a lead approval
  and an independent review, from two identities (kit v3.0.0 or later; before, the lead alone).
  Exception (kit v5.4.0, ADR-0008): when every changed file matches `[scope] lead_light` (prose
  such as `README.md` or `docs/**`), one approving review from any reviewer or bot is enough.
  Paths agents or checks read (lead artifacts, agent instruction files at any depth, skills,
  config, evidence and reviews, `.github/`, CODEOWNERS, tests) never qualify; `sdlc doctor` fails
  on a glob that covers one. Code is protected only through `tests.source_globs`: set it. `lead_light` changes only
  the approvals: with `scope.lead_code = "fail"`, list the same globs in `lead_allowed` too.
  Review records count only unedited (comments) and on the commit the forge recorded (reviews).
- List the reviewer, lead and bot identities in `[approval]`. They must differ from the identity
  that opens PRs. If one account does everything, set `trust_unsigned = true`: approvals then need
  write access only, and every result says they are trust-based.
- Commits carry `Sdlc-Agent`, `Sdlc-Play` and `Sdlc-Ticket` trailers (`sdlc run` and
  `sdlc commit --agent NAME --play build|test` add them). A ticket PR with a commit that names no
  agent gets no approval: nothing would show the reviewer is not the builder. Tickets store only
  `draft`, `ready` or `blocked`; `sdlc migrate` rewrites old delivery statuses. The rest is
  derived: `in_progress` while an unmerged branch (local, or fetched from the remote) has a commit
  naming the ticket, `done` once one is merged. `sdlc status` lists every ticket that way (run
  `git fetch` first to see other people's branches); `sdlc next` skips tickets in progress, and
  `sdlc run build` refuses one in progress on another branch. Delete an abandoned branch to free
  its ticket, or set `vcs.claim_days`: a branch with no commit for that many days stops holding
  it (`sdlc status` shows the expired claim). `sdlc status --prs` also shows open PRs from the
  building branches (display only; it needs the network and `[approval] repo`).
- Several agents on several machines: set `vcs.claim = "push"`. `sdlc run build` then fetches
  origin and pushes the ticket's branch with a new empty `claim <id>` commit (every run, resumes
  included) before the agent
  starts, so a second run building the same ticket is refused (git rejects its push). A run on
  another clone is refused while the ticket's branch on origin holds the claim; `--take-over`
  continues that branch when it is yours or abandoned. Builds then need network access and push
  rights (ADR-0005). Every build run pushes its claim first, a rebuild after review included: on a branch
  with an open PR that push starts CI and may dismiss approvals before the fix exists. A ticket waits on every `depends_on` id that is not done, including an id that
  names no ticket. `sdlc run build` resumes the ticket's own branch, local or fetched as
  `origin/<branch>`, with its commits. It refuses when `vcs.base` exists neither locally nor on
  origin, because it cannot then check other branches: fetch it first. `reviews/` and
  `evidence/` stay as read-only history.
- Merge ticket PRs with a merge commit; turn off squash and rebase merging in the repository
  settings. A squash folds the trailers into the commit body, where derived status cannot read
  them, so the ticket never becomes `done`: it shows `in_progress` while its branch exists and
  `ready` (offered again by `sdlc next`) once the branch is deleted. `gate ci` fails on such a
  commit until the PR's own commits are merged with a merge commit (no revert needed).
- A ticket declared `mechanical` or `refactor` whose diff raises its lane owes real-stack
  proof; `gate pr` then asks the PR to record the lane with an `Sdlc-Lane:` trailer, so CI keeps
  asking for that proof after the merge. `sdlc run build` adds it; by hand, `sdlc commit <id>
  --agent <name> --play build --lane <lane> --allow-empty -m "lane <id>: <lane>"`.
- Weakening or removing an AC by amendment needs a lead approval; a strict ticket needs one too.
- Derived status needs the whole history. Check out with `fetch-depth: 0` (the installed
  workflow does; a clone made with `--depth`, as some agent sandboxes make, needs
  `git fetch --unshallow` once), and keep tools from fetching into the repository with `--depth`: past a shallow
  boundary (`.git/shallow`) merged tickets read `ready` and a PR seems to move every ticket
  merged since it branched. Playwright does this on GitHub PRs (its `captureGitInfo` fetches
  the PR base with `--depth=1`); set `captureGitInfo: { commit: false, diff: false }` in
  `playwright.config`. `gate`, `gate pr` and `trace` fail on a shallow repository, and `gate`
  checks again after its other checks, so a tool that cuts history mid-run fails the run.
  `sdlc status`, `next` and `run` do not check: in a shallow clone they offer merged tickets
  as ready, so unshallow first.

Without `sdlc run` (agent in an IDE), file mode: `sdlc status T-001-03 in_progress --as build`,
give the agent `sdlc prompt build T-001-03`, have it iterate on `sdlc gate build
T-001-03`, commit, then `sdlc status T-001-03 in_review --as build`.

In records mode the status commands refuse `in_progress` (derived) and `in_review` (records mode
has none: a ticket under review reads `in_progress`, ADR-0003).
Check out the ticket branch (`build/T-001-03` by default), give the agent `sdlc prompt build
T-001-03`, have it iterate on `sdlc gate build T-001-03`, then commit with
`sdlc commit T-001-03 --agent <name> --play build -m "..."`. The trailer makes the ticket
`in_progress` for everyone who fetches the branch once you push it.

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
