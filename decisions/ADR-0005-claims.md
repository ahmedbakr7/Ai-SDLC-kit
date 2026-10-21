---
id: ADR-0005
title: Claiming a ticket by push, claims that expire, open PRs on the board
status: accepted
date: 2026-10-21
source: ADR-0003; Hangout pilot assessment after ~75 tickets (lead question on independent agents); lead decision in the kit session
supersedes: ADR-0003
---

# ADR-0005: Claiming a ticket by push, claims that expire, open PRs on the board

## Context

ADR-0003 makes a ticket `in_progress` while an unmerged branch names it, and `sdlc run build`
refuses a ticket another branch is building. A branch only counts for other people once it is
pushed and they fetch it. `sdlc run build` neither fetches nor pushes, so two agents on two
machines can both build one ticket for a whole build and find out at PR time.

ADR-0003 also leaves two things open: an abandoned branch holds its ticket until someone deletes
it, and the board cannot show that a ticket is in review.

Options considered for the race:

- **Push the ticket's branch first (chosen).** The branch name depends only on the play and the
  ticket id, so every run claims the same ref. A claim commit makes each run's push distinct, and
  git refuses a push that is not a fast-forward. Needs network access and push rights when a
  build starts, nothing else.
- **A lock in a shared service or in the forge (an assignee).** Forge-specific and needs a token.
  The kit installs on any git host.
- **A lock file committed to the base branch.** Every claim becomes a commit on the base: noisy,
  and it contends with every merge.

## Decision

These replace ADR-0003's resume rule in push mode and its "Not decided" section. Everything else
in ADR-0003 stands, and the defaults keep ADR-0003's behaviour.

- **`vcs.claim`** is `"local"` (default, ADR-0003) or `"push"`. With `"push"`, in records mode,
  `sdlc run build` (not a dry run):
  1. fetches every branch from `origin` with `--prune`, so a deleted claim frees its ticket. A
     failed fetch refuses the build.
  2. refuses as ADR-0003 does when another branch builds the ticket. It also refuses when
     `origin/<branch>` names the ticket and this clone has no local `<branch>`: the same name
     cannot tell this run's own claim from someone else's. `--take-over` continues that branch.
     It refuses when the local and remote branches have diverged.
  3. checks out the branch, adds an empty commit `claim <id>` with the usual trailers if no
     unmerged commit names the ticket yet, and pushes the branch without force before the agent
     runs. A refused push undoes the branch it created and refuses the build.
- **`vcs.claim_days`** (default 0, never). In records mode, a branch whose newest commit is older
  than that many days no longer makes a ticket `in_progress` or stops a build. `sdlc status`
  lists it as an expired claim. Any new commit renews the claim. In push mode, an expired claim
  on the ticket's own branch needs no `--take-over`.
- **`sdlc status --prs`** asks the forge (`[approval] repo`, as approval records do) for open PRs
  and shows `in review: PR #n` next to a ticket whose building branch has one, from the same
  repository only. Display only: the status stays `in_progress`, and no check, schedule or gate
  reads it. Opt-in, so `sdlc status` stays offline. A failed lookup warns and shows no PRs.

## Consequences

- With push claims, two runs cannot build one ticket. The loser stops before any agent work.
- The claim commit is empty and carries the build trailers. It ships in the PR and changes no
  check: scope sees no files, and approval reads the same agent as the build.
- A build needs network access and push rights from its first second. Offline work stays on
  `"local"`.
- `--take-over` is a person's statement that the claim is theirs or abandoned. Nothing verifies
  it; push access is the trust boundary, as in ADR-0003.
- An expiry that is too short frees a ticket a slow but live build still holds. The second build
  then finds the branch at PR time, as before this ADR. The value is the product's to tune.
- Expiry and PR display affect scheduling and display only. Gates and approvals do not read them.
