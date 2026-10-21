# Changelog

Releases are tags on `main` (`vMAJOR.MINOR.PATCH`, with `-rcN` while a version is in
review); `sdlc --version` prints the same number. Products pin a tag (CONSUME.md, "Pin it").
MAJOR moves when an upgrade can fail a product that passed before, MINOR for new checks and
behaviour that existing products keep passing (or that sit behind a setting), PATCH for fixes.

## Unreleased

## v5.1.0 (2026-10-21)

- **Parallel gates.** `app.port = "auto"` or `SDLC_APP_PORT=auto` picks a free port per run.
  `[app] setup` and `teardown` make and remove per-run resources: setup's `KEY=VALUE` lines in
  `$SDLC_RUN_ENV` reach every command, so each run can get its own database. Every command
  now sees `SDLC_APP_PORT` and `SDLC_RUN_ID`. A failed setup or
  teardown fails the gate. `app.port` is now validated (a whole number 1–65535 or "auto").
  Upgrade: optional; read the port from `SDLC_APP_PORT` in test configs that start servers.

## v5.0.0 (2026-10-21)

MAJOR for one item: a ticket PR whose diff raises a mechanical or refactor ticket that has AC
now fails `gate pr` until it records the lane. That includes PRs made by hand and PRs already
open from a v4 runner; add the record with `sdlc commit ... --lane` (below).

- **A PR records the lane a raised ticket ships in (issue #51).** A ticket declared
  `mechanical` or `refactor` that its diff raises to a lane with a test play owes real-stack
  proof, and gave it at PR time. CI used to see only the declared lane after the merge, so a
  later change could delete that real-stack test unnoticed. Now `gate pr` (records mode) adds a
  failing `lane-record` check for such a ticket until one of the PR's commits naming it carries
  `Sdlc-Lane: <lane>`; `gate ci` takes the strictest of the declared and recorded lanes.
  `sdlc run build` adds the record after a build that raises the lane; by hand:
  `sdlc commit <id> --agent <name> --play build --lane <lane> --allow-empty -m "lane <id>: <lane>"`.
  A PR that keeps its declared lane, or whose ticket owes no real-stack proof (no AC), records
  nothing. `gate ci`'s `trailers` check also fails on a lane record a squash merge buried in a
  commit body. MAJOR: such a PR fails `gate pr` until it records the lane. Already-merged
  tickets carry no record and keep being judged by their declared lanes.

## v4.1.0 (2026-10-21)

From the Hangout pilot's question on independent agents working one repository. All three sit
behind settings or a flag; with the defaults nothing changes (ADR-0005).

- **`vcs.claim = "push"`.** `sdlc run build` fetches origin, then pushes the ticket's branch with
  a new empty `claim <id>` commit (every run, resumes included) before the agent runs. Two runs on one ticket push different
  commits and git refuses the second, which stops before any agent work. A clone without the
  local branch is refused while `origin/<branch>` holds the claim; `--take-over` continues it.
  Upgrade: optional; builds then need network access and push rights.
- **`vcs.claim_days`.** A branch with no commit for that many days stops holding its ticket;
  `sdlc status` shows it as an expired claim. Default 0 (never).
- **`sdlc status --prs`.** Shows `in review: PR #n` for a ticket whose building branch has an
  open PR in the same repository. Display only; the status stays `in_progress`.
- `sdlc doctor` prints the claim settings and fails on invalid values.

## v4.0.0 (2026-10-20)

From the Hangout pilot. MAJOR for one item: a records-mode product whose CI reads a shallow
repository now fails where it used to pass (on history it could not see). The other two only
loosen a check or add a setting. Each item has its upgrade step.

- **Records mode fails on a shallow repository.** Derived status and the tickets a PR moves
  walk the base branch's history; past a shallow boundary (`.git/shallow`) they read nothing,
  silently. On Hangout, Playwright's `captureGitInfo` ran `git fetch --depth=1 <PR base>` during
  `gate ci`, after which every merged ticket read `ready`, `trace` was baselined on that view,
  and a PR that had merged main "moved 31 tickets". Now `gate` (any play) adds a failing
  `history` check when the repository is shallow, run after its other checks so a tool that
  cuts history mid-run fails the run; `gate pr` refuses before it reads the PR's trailers;
  `trace` refuses before it derives status (`status`, `next` and `run` do not check). Upgrade: check out with `fetch-depth: 0` (the
  installed workflow does; a local clone made with `--depth` needs `git fetch --unshallow`)
  and stop tools fetching into the repository with `--depth`
  (Playwright: `captureGitInfo: { commit: false, diff: false }`). Then expect derived status to
  change: tickets merged by trailer read `done`, and `gate ci`/`trace` judge them (CONSUME,
  "Approvals outside the tree").
- **One rule for when a ticket owes real-stack proof.** A passing real-stack test with one of
  the ticket's AC tags is owed only when the ticket has AC and its lane has a test play.
  - A ticket with `acceptance_criteria: []` has no tag to carry: CI no longer calls it unproven
    once merged (a mechanical ticket turned main red).
  - Mechanical and refactor tickets: the build's full suite is the proof and `gate test`
    refuses the lane (ADR-0004), yet `gate pr` asked for a real-stack tag, so no refactor
    ticket could pass. Their AC still need a passing tagged test in some suite.
  - The test/PR check uses the lane the gate resolved (a ticket the diff raises out of
    refactor owes the proof again); `gate ci` reads a shipped ticket's lane from the base
    branch too and takes the stricter, so a branch cannot relabel a ticket to drop its proof.
  Nothing to do; a `test: none` added as a workaround stays valid. Known gap: CI knows only
  the declared lanes, not the lane a ticket shipped in, so a mechanical or refactor ticket that
  its diff raised (and that gave real-stack proof at PR time) no longer owes that proof in
  `gate ci`; deleting its real-stack test later goes unnoticed while its tagged tests still
  pass. Recording the shipped lane is a follow-up.
- **`SDLC_APP_PORT` overrides `app.port` on one machine**, for smoke, the `PORT` the app
  gets and every `{port}`/`{base_url}`, so two worktrees can gate at once without editing the
  committed `sdlc.toml`. `doctor` prints the port in effect and where it came from, and fails
  on a value that is not a port. Unset, nothing changes.

## v3.4.1 (2026-10-19)

PATCH: a fix; nothing an existing product passes fails.

- **Changing `tests.real_stack` no longer invalidates the baseline.** ac-coverage's
  "done, but no passing <suites> test carries its tag" entry was keyed by the suite names, so
  changing `real_stack` turned every known entry into a new failure that no PR could clear (the
  baseline only shrinks, and CI reads the base branch's config). The ac-coverage key now reads
  "no passing real-stack test". Baseline entries and `sdlc-waivers.toml` keys an older kit wrote
  are matched as that form, so they keep working without a rewrite; rewriting a baseline in the
  new form is not growth, and a renewal may restate its waiver's key in the new form. A failing
  ac-coverage check still names the suites; baselined and waived entries show the new key.
- `tickets.DERIVED` no longer lists `in_review`, which records mode does not derive (ADR-0003).
  No behaviour change: `sdlc status <id> in_review` was already refused first, with its own message.

## v3.4.0 (2026-10-16)

MINOR: a new lane that existing tickets do not use; nothing an existing product passes fails.

- **Refactor lane** ([ADR-0004](decisions/ADR-0004-refactor-lane.md)). A lead marks a ticket that
  keeps behaviour `lane: refactor`. The lane order is now `mechanical < refactor < standard <
  strict`. Only the lead declares it: a ticket PR may neither lower a standard ticket to refactor
  nor raise a mechanical one to it, and `--lane refactor` on a mechanical ticket gives standard.
  Its build runs `[gate] refactor`: the standard build with a new `refactor` check in place of
  `ac-red`, plus every configured test suite. It has no test play, like the mechanical lane.
- The `refactor` check fails unless production code changed, every test file the base has keeps
  its lines, and each AC's tagged tests run and pass with every changed file but tests put back
  to the base (in the ticket's areas or not). A kept line may only gain AC tags, with their own
  separator or brackets: indentation, punctuation, the spaces inside the line and the tags it
  already had all stay, in the same diff hunk (a line may not move to another test). When the
  unit command reports no test on the base, the check names its exit code. It is never waived or
  baselined.
- An approval of a refactor needs a `## Equivalence` section with an argument in it, not empty
  and not the template's `<...>` placeholder (`review-file` and `sdlc approval` share one rule).
  The review skill and template say what to argue there.
- A product that sets `[gate] build` but not `[gate] refactor` gets the checks it added to its
  build in the refactor build too. `doctor` holds `gate.refactor` to a floor, refuses `ac-red` in
  it, and notes a check in `gate.build` that an explicit `gate.refactor` lacks. `sdlc gate --lane` accepts
  `refactor`. Presets apply to the new list. The build prompt, the build, review and ticketize
  skills, the ticket template, README and CONSUME.md describe the lane.
- `ac-red` and `refactor` share one helper that runs the unit command with the production files
  at the base; `ac-red`'s behaviour is unchanged.

## v3.3.3 (2026-10-16)

PATCH: wording only, no behaviour change.

- Records mode no longer calls `in_review` derived. ADR-0003 does not derive it: a ticket under
  review reads `in_progress`. `sdlc status <id> in_review`, `sdlc lint` and CONSUME.md now say
  so. `in_progress` keeps the v3.3.2 message.
- CONSUME.md: a records-mode build commit makes the ticket `in_progress` for others once pushed.
- `artifacts.py`: the branch-scan comment also says the per-base scans are intersected (a ref
  counts only if no base has merged it). One `--no-merged` per call stays, for git before 2.29.

## v3.3.2 (2026-10-15)

PATCH: documentation and one message, no behaviour change.

- CONSUME.md section 3 covers v3.3.1's runner behaviour: unknown `depends_on` ids count as not
  done, `sdlc run build` resumes a fetched `origin/<branch>`, and it refuses without a base.
- CONSUME.md gives the records-mode steps for building without `sdlc run`. The old steps set
  `in_progress` and `in_review` by hand, which records mode refuses.
- `sdlc status <id> in_progress` (or `in_review`) in records mode says the status comes from an
  unmerged branch, as ADR-0003 decided, instead of "an open PR", and points to `sdlc commit`.
- Correction to v3.3.1: the one-`--no-merged`-per-call change is defensive only. The kit already
  requires git 2.32 or later, which accepts several.

## v3.3.1 (2026-10-15)

PATCH: follow-ups from the v3.3.0 review.

- ADR-0003 records v3.3.0's status derivation: `in_progress` comes from unmerged branches in both
  records modes, replacing the `in_progress` / `in_review` bullet of ADR-0001 section 5 (which
  named open PRs in `forge` mode). No code change.
- `sdlc run build` and `sdlc status <id> in_progress` count a `depends_on` id that names no ticket
  as not done, as `sdlc next` and the board already did. Before, they skipped it. (`sdlc lint`
  and the gate already fail such a ticket.)
- The branch scan reads only refs not yet merged into the base (one `for-each-ref --no-merged`
  per base, as git before 2.29 takes only one), so stale remote-tracking refs no longer cost a
  `git log` each. The result is the same. A scan that fails now raises instead of reading as
  "nothing in flight", and in records mode `sdlc run build` refuses when `vcs.base` exists neither
  locally nor on origin, since it cannot check other branches for the ticket.
- A play whose ticket branch exists only as `origin/<branch>` (fetched, no local branch) now
  checks it out from that ref. Before, `sdlc run build` started a new branch from the base and
  dropped the fetched commits, so the resume ADR-0003 allows did not keep the earlier work.
- Tests: the board tests run when `tests/test_gate.py` is run directly, and the runner's
  `origin/<branch>` exemption has a test.

## v3.3.0 (2026-10-14)

MINOR: ticket status is tracked end to end. No gate check changes: checks that judge a branch
still read merged trailers and stored status.

- Records mode derives `in_progress` as well as `done`: a `ready` ticket is in progress while an
  unmerged branch (local, or fetched under `refs/remotes`) has a commit naming it in an
  `Sdlc-Ticket:` trailer. Lead decisions (`draft`, `blocked`) are never overridden, and `done`
  still wins. File mode keeps its stored status.
- `sdlc status` with no ticket lists every ticket: its status, the dependencies not yet done, the
  branches building it, and why it is blocked; `--json` prints the same rows for tools.
  `sdlc status <id>` prints the derived status (so `in_progress` where it printed `ready`).
- `sdlc next` skips a ticket an unmerged branch is building, so two agents do not take the same
  ticket. `sdlc run build` refuses one in progress on any branch but its own; delete an abandoned
  branch to free its ticket.

## v3.2.1 (2026-10-12)

From the Hangout pilot (T-001-35). PATCH: a review skill and prompt that contradicted the gate.

- The review skill told reviewers to reject a ticket without test evidence whenever the product
  configures integration or e2e commands, and the review prompt printed "No test evidence". The
  gate and the runner exempt tickets with no test play (`test: none`, `type: test`, spikes), so a
  reviewer following the skill asked for a test play `sdlc run test` refuses to start. The skill
  and the prompt now follow the gate's rule: test evidence is required only for a ticket with a
  test play, built outside the mechanical lane, in a product whose `tests.real_stack` is not
  empty. Otherwise the prompt says "No test evidence needed (<reason>)".
  `sdlc run test` names a spike as a spike in its refusal, and a `type: test` ticket marked
  `test: none` as marked `test: none`.
- `--extra` on `sdlc prompt` and `sdlc run` takes a file path: `--help` now says so, and a path
  that cannot be read, or is not UTF-8 text, is a one-line error instead of a traceback.

## v3.2.0 (2026-10-12)

From the Hangout pilot. MINOR: prompts, skills and docs change; no check can fail a product
that passes on v3.1.0.

- Fix: a ticket naming `frontend-patterns` or `backend-patterns` got the kit's empty template,
  not the product's filled-in skill, because skill lookup searched the kit first. Play skills
  (`build`, `review`, ...) still come only from the kit; every other name is the product's
  first, then the kit's, then a vendor skill.
- The prompt adds the pattern skills a ticket's type needs when the ticket does not list them:
  `frontend` gets `frontend-patterns`, `backend` gets `backend-patterns`, `fullstack` both, when
  the product has filled in its own copy (an untouched copy of the kit's template, from any
  version, is not added).
- `sdlc prompt review --pr N [--base B]` assembles the review of a lead PR (one that moves no
  ticket): its HEAD and merge base, its files marked against the base's lead write set, the
  base's pattern skills, and the record to write (`.sdlc-run/lead-review-<N>.md`, `ticket:` empty).
  `sdlc review publish --pr N` without a ticket publishes that record. The review skill has a
  **Lead PRs** section.
- The pattern skill templates gain a short **Conventions** section: where new things go, "use,
  not" and "never". AGENTS.md rule 11: when the ticket, CONTRACTS and the conventions do not
  settle a structural choice, follow the closest existing example and name it, or stop and
  name the gap. Products fill in their own copies; the templates only change new products.
- The review skill opens every `source_adr` and checks the diff against it, flags a change to
  an accepted ADR's subject that the ticket does not cite, and checks new files against the
  conventions.
- `adapters/AGENTS-RUNNER.md`: a harness that screens an agent session's commands may block
  `sdlc run`; the lead starts runs, or a permission rule allows the runner.

## v3.1.0 (2026-10-11)

From the v3.0.2 review (finding 4). MINOR: a new warning, and a failure only behind a new
setting, so nothing that passes on v3.0.3 can fail.

- `scope` reports tracked files anywhere in the repository that git is told to ignore edits
  to (`git update-index --skip-worktree` or `--assume-unchanged`). An edit to such a file, or
  its deletion, can be missed by status, diff and `add -A`, and so by every other check: a run
  could test code no commit holds, and its evidence said the tree was clean. Evidence lists
  the files under `"hidden_from_git"`, with paths relative to the repository top.
- `scope.hidden_files = "fail"` fails `scope` on them (default `"warn"`). Sparse checkout sets
  skip-worktree on the files its patterns leave out, so a skip-worktree file that is not on
  disk is exempt only when `git sparse-checkout check-rules` (git 2.41+) places it outside
  the patterns; a file the patterns include, or any file when git cannot answer (no
  patterns file, older git), counts. Turning on `core.sparseCheckout` alone exempts nothing;
  the patterns file itself is local state (see the known gaps below). An
  assume-unchanged file counts whether or not it is on disk. The hardened preset does not
  set `"fail"` yet: turning it on there could fail a hardened product that passes today,
  which would be MAJOR.
- In records mode CI re-runs the checks on a clean checkout, where no such flag exists, so
  this mainly closes the gap for local evidence and file-mode products.
- Known gaps, for a later release: a local `core.fsmonitor` hook that reports no changes,
  a local clean filter (`.git/info/attributes`), a local `submodule.<name>.ignore`,
  `.git/info/exclude`, and a local sparse-checkout patterns file (`.git/info/sparse-checkout`,
  which can exclude any file, and an empty one excludes all) can also hide changes. The same CI re-run covers these
  local settings; an `ignore` committed in `.gitmodules` is a change the PR's scope judges.

## v3.0.3 (2026-10-11)

From the v3.0.2 review. No check changes what it accepts.

- Evidence's `"untracked_allowed"` no longer lists a file HEAD holds. A lockfile taken out of
  the index with `git rm --cached` was listed as an untracked file that does not ship. The
  evidence already said `"dirty": true`, so nothing was let through.
- A test pins that a test run which fails its first attempt also leaves an untracked
  lockfile out of its fail-evidence commit. Without it, attempt 2 would fail
  `scope` on the file attempt 1 committed.
- CHANGELOG v3.0.2 now says that one of its changes makes a check stricter: a git failure in
  the clean-tree check stops the run.

## v3.0.2 (2026-10-10)

From the v3.0.1 review and the Hangout pilot. Every change but one relaxes a check that failed
a correct run. The exception is the clean-tree check: when its git command fails, the run now
stops; v3.0.1 treated that failure as a clean tree. Only a broken git hits this: with a
working git, nothing that passes on v3.0.1 can fail.

- `sdlc run test` and `sdlc run review` leave an untracked `scope.always_allowed` file
  (a lockfile the product does not commit, a fresh snapshot) out of their commits, unless
  the play's write set covers it. The runner committed every file the agent left, so on a
  fresh clone of a product that neither commits nor ignores its lockfile, `npm install` in
  the test play failed `scope` on every attempt. A change to a tracked lockfile is still
  committed and judged by the write set: it changes what the PR ships. A build still commits
  both, and the review names them when they are outside the ticket's areas. A file HEAD holds
  is never left out, so `git rm --cached` cannot pass a tracked lockfile off as untracked.
- An untracked `always_allowed` file no longer makes the tree dirty, for evidence (`"dirty"`)
  or for the clean-tree check `sdlc run` makes before it starts. No commit holds the file, as
  with an ignored one. Any other uncommitted change still counts, including a change to a
  tracked lockfile and files of other products in a monorepo. Evidence lists these files under
  `"untracked_allowed"`: a run could read them, but the PR does not ship them. A snapshot the
  test play writes outside `tests.integration_globs` is one, and CI that refuses new snapshots
  will fail on it.
- Upgrade note: a lockfile a test or review run left untracked no longer stops the next
  `sdlc run`, and a later build commits it as an out-of-area file. A product that does not
  commit its lockfile should list it in `.gitignore`.
- CHANGELOG v3.0.1: its first sentence said every fix corrected a check that failed closed;
  the third fixed one that failed open. The v3.0.1 `--since` relaxation helps a gate run by
  hand: `sdlc run` commits a tracked lockfile the play rewrote, and the write set judges it.

## v3.0.1 (2026-10-10)

From the review of v3.0.0. Each fix corrects a check (two failed closed, one failed open on a
dirty tree) or adds a missing test. In CI, which checks out a clean tree, none can fail a product that passes on v3.0.0;
locally, a `gate pr` with uncommitted edits to reverted files now fails (third item).

- A play that starts from an earlier one (`--since`, as the test and review plays do) answers
  only for the lockfile and snapshot changes it commits. A lockfile the build committed and
  the test play's `npm install` rewrote without committing failed the test play's `scope`.
  The review's out-of-area list still counts every lockfile the branch commits, since the PR
  gate asks the review to name them.
- The exact-revert check runs from the work tree's top. In a product nested in a monorepo, a
  revert of a commit that also touched files outside the product was refused.
- The revert exemption no longer excuses uncommitted edits to the reverted files (a local
  `gate pr` on a dirty tree; CI checks out a clean one), nor any edit when git cannot list
  them.
- CHANGELOG v3.0.0: the lead-PR review step names who counts as the reviewer.
- Tests pin three guards no test covered: a revert of a commit that is not on the base branch
  (a side branch's deletion) is no exact revert; an untracked lockfile is not an out-of-area
  file; and when git cannot list the committed files, every lockfile counts as committed.

## v3.0.0 (2026-10-10)

From the Hangout pilot (findings 7 and 17), issue #27, and a v2.0.0 review deferral. MAJOR:
each item below can fail a product that passed on v2.0.1. Each has an upgrade step.

- **`gate ci` re-proves every ticket whose derived status is done.** In records mode a ticket
  is done once a merged commit names it in an `Sdlc-Ticket:` trailer, even if its file still
  says `ready`. `ac-coverage` already checked such a ticket's AC, but the real-stack re-proof
  read the stored `status` and skipped it. Now it fails unless a passing real-stack test
  carries one of the ticket's declared AC tags. Upgrade: run the test play for each ticket
  that `gate ci` names, or have the lead waive it in `sdlc-waivers.toml` (check
  `ac-coverage`, key as printed).
- **`scope.always_allowed` covers only what a run leaves uncommitted** (finding 7). The node
  and nextjs profiles list the lockfiles there (nextjs also `**/__snapshots__/**`), so a
  committed dependency or snapshot change passed every scope check, lead PRs included. A
  committed change to such a file is now judged by the play's write set: on a build it is an
  out-of-area file the approving review must name, the test and review plays may not change
  it, and on a lead PR it falls under `scope.lead_code`. A lockfile `npm install` leaves
  untracked stays ignored. Upgrade: list the lockfile or snapshot directory in the ticket's
  `files`/areas when the ticket changes dependencies or snapshots, or name it under
  `## Out of area` in the review.
- **The hardened preset fails code in a PR that names no ticket** (issue #27):
  `scope.lead_code = "fail"`, and a product's `"warn"` is reported by `doctor` and put back.
  A lead PR whose commits all exactly revert commits already on the base branch passes. Each
  commit must name its target ("This reverts commit") and carry the inverse of its diff (the
  patch-id test); a merge from the base branch, or any extra change, makes the PR no exact
  revert. Upgrade, hardened products only: send code changes through a ticket, or merge by
  admin override. Rebase a revert branch instead of merging the base into it.
- **A PR that names no ticket needs an independent review as well as the lead's approval**
  (finding 17), from two identities unless approvals are trust-based. Before, the lead's
  record alone approved it, though the lead wrote or asked for the change. Upgrade: have a
  listed reviewer who neither opened the PR nor wrote its commits review each lead PR (with
  `trust_unsigned = true`, a fresh session's `role: review` record from the shared account
  counts; the hardened preset forbids that).

## v2.0.1 (2026-10-10)

From the review of v2.0.0. No behaviour changes.

- CHANGELOG v2.0.0: approval's check that a test ticket's build evidence records real-stack
  proof does not apply to a mechanical-lane build, whose full suite is the proof (`gate pr`
  re-checks the lane), as for every other ticket.
- A test pins that a test ticket naming a route in `contracts:` lints clean: it still owes
  real-stack proof, which its build gives.

## v2.0.0 (2026-10-10)

Found by the Hangout pilot (finding 19). MAJOR: a product that passed on v1.5.5 can fail on
upgrade in two ways.

- A `type: test` ticket whose build also changes a file outside `tests.globs` and
  `tests.integration_globs` (a manifest such as `package.json` or `pyproject.toml`,
  test-runner config, fixtures elsewhere) now fails `scope`, where v1.5.5 flagged that file
  for review. To upgrade, move such changes to a ticket of another type (an `ops` or `chore`
  ticket for a manifest or runner config), or widen `tests.globs` to cover the fixtures.
- A real-stack test tagged with an AC its ticket does not declare (the AC was removed or
  renumbered, or the tag has a typo) no longer proves that ticket, so its test play fails
  `ac-coverage` and `gate ci` fails for it once done. To upgrade, retag the test with an AC the
  ticket declares.

A test ticket in flight across the upgrade keeps its approval when its test play passed.

- A `type: test` ticket (it changes tests only) has no test play: its build is that play. Its
  `gate build` also runs the real-stack suites (`tests.real_stack`, moved before `ac-coverage`
  wherever the build list puts them), its build may write the files in
  `tests.integration_globs`, and it carries the test play's proof: `ac-coverage` fails unless a
  passing real-stack test carries one of its AC tags (unless the lead marked it `test: none`).
  The build evidence records that proof (`real_stack_proof`). Approval refuses a test ticket
  whose build evidence lacks it, unless a passing test play gave the proof, as it did before
  this release, or the build ran in the mechanical lane.
- Real-stack proof (the test play, a records-mode `gate pr`, and a test ticket's build) needs a
  passing real-stack test tagged with an AC the ticket declares. Before, any `<ticket>/AC-n` tag
  counted, including an AC the ticket does not have. A test tagged with an undeclared AC proved
  nothing, so this closes a check that passed without checking. Before, a ticket whose AC only an
  integration test could prove could not pass `gate build`, which ran `unit` alone and refused
  integration files to the build. `sdlc lint` no longer asks such a ticket for a test play, and
  `sdlc run test` says why it has none. Because it skips the test play, a test ticket may
  change only files in `tests.globs` or `tests.integration_globs`, plus a draft ticket it splits
  an AC into: any other file fails `scope` (the MAJOR change above), so the type cannot carry
  production code past real-stack proof. `gate ci` still re-proves a done test ticket through
  the real stack. Other ticket types are unchanged.

## v1.5.5 (2026-10-10)

Found by the Hangout pilot (findings 2 to 6), checked against v1.5.4, and in review of this
release. A product whose PRs pass on v1.5.4 keeps passing unless a commit names two agents.

- `sdlc commit` and `sdlc run` add `Sdlc-Agent`, `Sdlc-Play` and `Sdlc-Ticket` to the message's
  own trailer block (`git commit --trailer`: git 2.32 or later, now stated in CONSUME.md).
  Before, they went into a paragraph of their own, so a `Co-Authored-By` above them was no
  longer a trailer.
- `sdlc approval` and `sdlc run review` read each repeated `Sdlc-Agent` trailer as its own
  agent. Before, "other" and "builder" on one commit read as one agent "other,builder", so the
  builder's own review record looked independent. Keeping the message's trailers made this
  reachable through `sdlc commit`; found in review of this release.
- A build, test or review gate run on uncommitted changes says it proves no commit: its evidence
  names HEAD, which does not hold them. The build skill says to commit first when no runner does.
- With approval records, the review prompt names one commit for the record: the HEAD reviewed.
  It used to say both that and "Set `commit: <proven commit>`". A review file still takes the
  evidence commit.
- A play's prompt leaves out other plays' skills. A ticket listing `skills: [build]` put the
  build play's instructions into the test play's prompt.
- `sdlc baseline --prune` prints failures and keys apart ("pruned 14 failure(s) across 7
  key(s)"); it said "pruned 14 entries". The build skill no longer says the runner sets the
  ticket `in_progress` when status is derived from commits.

## v1.5.4 (2026-10-09)

Found in the separate-session review of v1.5.3.

- `sdlc baseline --prune` drops a known `unit`, `integration` or `e2e` failure only when the
  JUnit reports that test as passed. A test that is missing from the report (its file failed to
  import, a filter left it out) or skipped keeps its entry, and the prune says how many it kept.
  Before, a suite that ran only in part still named its other failures, so the tests that did
  not run looked fixed and were pruned for good. It keeps more than before and cannot fail a
  product that passed.

## v1.5.3 (2026-10-09)

Found by the Hangout pilot (finding 15).

- `sdlc baseline --prune` drops a check's entries only when that check ran and named its
  failures. A check that was skipped, left out of the run, or failed as a whole (it crashed, or
  wrote no results, so its only finding is `<check>: fails`) keeps its entries, and the prune
  says which and why. Before, such a prune emptied that check's baseline: Hangout's dropped all
  241 `ac-coverage` entries when no test command wrote JUnit, and since the baseline only
  shrinks the commit could not be undone. It keeps more than before and cannot fail a product
  that passed.

## v1.5.2 (2026-10-07)

Found by the Hangout pilot recovering T-001-33 from a squash merge on kit v1.5.0.

- `gate ci`'s `trailers` check reports only tickets that no commit delivers as a trailer.
  Merging a squashed PR's own commits with a merge commit now clears it. Before, v1.5.1 kept
  failing until the squash was reverted, and that revert cannot merge when the PR pruned the
  baseline (the baseline only shrinks). The fix advice now says to merge the original commits;
  a revert is not needed. It removes a false failure and cannot fail a product that passed.

## v1.5.1 (2026-10-07)

Found by the Hangout pilot on kit v1.5.0 (T-001-33, PR #73). Both close a check that passed
without checking; a product whose PRs already follow the documented flow keeps passing.
Released as a patch although it can turn a PR red that passed before: such a PR either has a
commit naming no agent (`sdlc approval`) or a squash-merged ticket on its base (`gate ci`), and
v1.5.0 accepted both only because the check did not run.

- `sdlc approval` fails a ticket PR with a commit that has no `Sdlc-Agent` trailer ("needs
  Sdlc-Agent trailers on N commit(s) ... to check reviewer independence"). Before, the
  independent-reviewer rule had no agent to compare, so the builder's own record counted.
- `sdlc commit` takes `--agent` and `--play` (both required) and writes the same trailers as
  `sdlc run`.
- `gate ci` (records mode) fails with a `trailers` check when a merged commit names
  `Sdlc-Ticket` outside its trailers, as a squash merge leaves it: derived status cannot see the
  ticket. A commit is exempt only while a later commit reverses its diff exactly (same patch
  id) and that revert is not itself reverted; a revert message alone exempts nothing. The fix is
  to revert it and merge the PR's own commits with a merge commit.

## v1.5.0 (2026-10-06)

The first stable release: ADR-0001 (lanes, areas, approval records, evidence in CI, derived
status) and ADR-0002 (baseline counts, waivers, strictness presets), as released in
v1.0.0-rc1 to v1.5.0-rc1. No behaviour change since v1.5.0-rc1. Upgrading from an rc needs
nothing; from an older pin, read each rc entry below.

- Tests: `tests/test_lifecycle.py` takes the example product's main branch through a ticket
  (records-mode approval, derived status), baselined debt, a file move, a waiver and the fix,
  with the full gates at each step, under the default and the hardened preset. No behaviour change.

## v1.5.0-rc1 (2026-10-05)

ADR-0002 step 4c: strictness presets. `[gate] preset` defaults to `"default"`, which changes nothing.

- `[gate] preset = "hardened"` tightens existing settings and adds no check: no trust-based
  approvals; a mechanical PR needs a human reviewer, not a bot alone; `.github/workflows/**`,
  `sdlc.toml`, the `.sdlc` pin and dependency manifests and lockfiles make a PR strict; nothing
  is optional and `tests.real_stack` may not be emptied; waivers last at most 30 days and are
  not renewed. A product's own keys still override the preset key by key, except these: the
  stricter value holds and `doctor` fails the setting.
- `[gate] preset = "floor"` is exactly ADR-0001 section 6, for products adopting the kit:
  `duplication` and `smoke` leave every lane's lists.
- `doctor` prints the resolved lane lists, strict paths and waiver limit, and still fails any
  list below the floor.

## v1.4.0-rc1 (2026-10-05)

ADR-0002 step 4b: time-boxed waivers. Nothing changes for a product without `sdlc-waivers.toml`.

- `sdlc-waivers.toml` (`[[waiver]]`: `id`, `check`, `key`, `count`, `owner`, `reason`, `expires`,
  optional `ticket` and `renews`) waives up to `count` occurrences of one exact key, after the
  baseline. A waiver applies only once it is on the base branch, unchanged, so a PR cannot waive
  its own new failure; a renewal keeps the renewed waiver's coverage in its own PR.
- The creation date is the committer date of the base branch's first-parent commit that
  introduced the entry; a commit dated before its parent, or in the future, is refused. A waiver
  lasts at most `[waivers] max_days` (90) from that date, a renewal chain at most twice that.
- `gate ci` fails on an expired, stale (covers nothing), invalid or over-long waiver; every other
  gate, and `doctor`, reports it, with a warning 14 days before expiry. Waived failures are listed
  with owner and expiry in the gate output, the evidence and `sdlc trace`.
- Scope, immutable, review-file, approval, mechanical, spike, contract-diff, ac-red and skills are
  never waivable. A ticket PR that changes `sdlc-waivers.toml` is strict, so it needs a lead
  approval.

## v1.3.0-rc1 (2026-10-05)

ADR-0002 step 4a: a rename-proof baseline.

- `sdlc-baseline.json` version 2 stores a count per key (`{check: {key: count}}`); version 1
  files are still read, each line counting once. `sdlc baseline` and `--prune` write version 2,
  so the first prune converts the file.
- Paths inside keys follow the renames git detects since the baseline was last committed, so
  moving a file keeps its known failures known, on the branch and on main after the merge.
  `--prune` writes the new paths; `immutable` and the review-file check compare both sides
  renamed, so a move is not growth. A count above the baseline's is still a new failure.
- CHANGELOG.md, and CONSUME.md on pinning a release tag and upgrading between tags.

## v1.2.0-rc1 (2026-10-04)

ADR-0001 step 2: approvals outside the tree, evidence in CI, derived status. Opt in with
`[approval] mode = "forge"` (GitHub) or `"git"` (signed notes); the default `"file"` keeps v1.1.

- Approvals are PR reviews or comments (forge) or notes in `refs/notes/sdlc` (git), each bound
  to the commit it reviewed. They still count after later pushes only when replaying those
  pushes cannot change what was reviewed (`git merge-file` per file).
- `[approval] reviewers`, `leads`, `bots`: the identities whose approvals count. Review and lead
  approvals may not come from the PR author, a commit author or the building agent.
  `trust_unsigned = true` accepts declared roles from collaborators with write access, for a
  single account; every result then says it is trust-based.
- Roles per lane: mechanical needs any reviewer or bot, standard a review, strict a review and a
  lead; weakening or removing an AC by amendment, and any PR without a ticket, need a lead.
- `sdlc approval` (CI check, `--publish-status` posts `sdlc/approval`), `sdlc review publish`,
  `sdlc followups`, `sdlc commit`, `sdlc migrate --areas`.
- Evidence stays in `.sdlc-run/`; `gate pr` re-proves the lane's checks on the head and
  `gate ci` records shipped AC proof for `trace`.
- Ticket status is derived: `done` once a merged commit names the ticket in an `Sdlc-Ticket:`
  trailer. Tickets store only `draft`, `ready` and `blocked`.
- `sdlc init` installs `sdlc-approval.yml` and its review relay `sdlc-approval-review.yml`: the
  check runs the base branch's kit against the PR head (read as data), from the default branch
  on every trigger, one run per PR at a time. The forge token goes only to `GITHUB_API_URL`.
- Fixes: a commit with several `Sdlc-Play` trailers counts for each; a local base behind
  `origin/<base>` no longer hides merged tickets; front matter keeps an integer with a leading
  zero as text (`commit: 0510682`).

## v1.1.0-rc1 (2026-10-04)

ADR-0001 step 1 (accepted in decisions/ADR-0001).

- Risk lanes `mechanical < standard < strict`, resolved from the ticket and the diff and never
  lowered. A mechanical ticket's `transforms:` (literal, identifier rename, move) must produce
  the whole diff byte for byte; anything else raises it to standard. `risk: high`,
  `type: contract`, a CONTRACTS change and `lanes.strict_paths` are strict.
- Soft areas (`areas:` globs replace `files:`): a file outside them is flagged and the approving
  review names it under `## Out of area`; lead artifacts, CI workflows, the kit pin, other
  tickets and the test play's files still fail scope.
- Ticket amendments (`## Amendments`, append only): `add`, `strengthen`, `split`, `widen` by the
  build; `weaken` and `remove` need the spec (or, in records mode, a lead approval).
- Spikes (`type: spike`, `questions:`): documents only, inside their areas.
- `contract-diff` on strict PRs: route, page, table and event changes, narrowed keys marked
  breaking, prose outside every key reported.
- `ac-red` reverts only `tests.source_globs`; gates count only this branch's changes after a
  base merge.

## v1.0.0-rc4 (2026-10-03)

- `trace` honours `sdlc-baseline.json`.

## v1.0.0-rc3 (2026-10-03)

- `sdlc baseline`: record a red main's known failures in a lead PR; gates fail only on new ones,
  and `--prune` removes fixed entries.
- CI workflow: clone a private kit with `SDLC_KIT_TOKEN`, upload `.sdlc-run/` evidence, and run
  trace and the PR gate even when `gate ci` fails.

## v1.0.0-rc2 (2026-10-02)

- `tests.real_stack`: name the suites that prove a ticket over the real stack.
- `legacy: v0` marks tickets that shipped under kit v0; `sdlc migrate` sets it.
- Contracts: a UI call must hit a built route; v0 `## Tables` markdown tables are read as
  declared tables; smoke fails when the app serves no route at a contract path.
- nextjs profile: duplication scans production code only and `--threshold` decides it; tests
  that read source through a helper are flagged.

## v1.0.0-rc1 (2026-10-01)

The kit's rules move from prose into `sdlc gate` (MIGRATION.md).

- The `sdlc` CLI: deterministic gates per play, the conveyor (`sdlc run`), contracts drift,
  trace, doctor, and a runnable example product.
- Gates run with the base branch's `sdlc.toml`; evidence binds to the commit it proves; a play
  may move its ticket's status only along its own role's moves.
- `ac-red`: each AC needs a test that fails without the ticket's code. Test quality forbids
  inverted and conditionally skipped tests.
- Lead PRs (no ticket) report code changed without a ticket; the lead may mark a ticket
  `test: none`.

## v0.1.0 (2026-09-22)

- First version: plays, templates and adapters, with the rules in prose.
