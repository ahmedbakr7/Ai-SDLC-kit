---
id: ADR-0003
title: In-progress status comes from unmerged branches in every records mode
status: accepted
date: 2026-10-14
source: ADR-0001 section 5; kit PR #43 (v3.3.0); lead request for tracked ticket status
supersedes: ADR-0001 section 5, the `in_progress` / `in_review` bullet only
---

# ADR-0003: In-progress status comes from unmerged branches in every records mode

## Context

ADR-0001 section 5 derives delivery status instead of storing it. Its `in_progress` /
`in_review` bullet reads: "an open (draft / ready-for-review) PR, or in `git` mode an
unmerged branch, whose commits carry the trailer". So in `forge` mode, `in_progress` would
come from the forge's open PRs.

v3.3.0 shipped the derivation that the product needed to stop two agents taking the same
ticket, and it uses unmerged branches in both modes. The record and the code disagree, and an
accepted ADR cannot be edited, so this ADR replaces that one bullet.

Options considered:

- **Branches in every mode (chosen).** Git only: works offline, needs no token, works on any
  git host. Cannot tell `in_review` from `in_progress`.
- **Open PRs in `forge` mode, as ADR-0001 says.** Gives `in_review` (ready for review) apart
  from `in_progress` (draft). But every `sdlc status` and `sdlc next` would need the network and
  a token, would fail or degrade offline, and would add forge-specific code to a read that
  every play makes. That works against a kit that installs anywhere.
- **Branches, enriched by PRs when a token is available.** The most precise, but two
  derivations can disagree, and nothing needs `in_review` yet.

## Decision

- In records mode (`[approval] mode = "forge"` or `"git"`), a ticket whose stored status is
  `ready` is `in_progress` while a branch not merged into the base has a commit naming it in an
  `Sdlc-Ticket:` trailer. Branches are local heads and remote-tracking refs. The base is
  `vcs.base` and `origin/<base>`, whichever exist. Symbolic refs are skipped.
- `done` (a merged trailer) wins over `in_progress`. The stored lead decisions `draft` and
  `blocked` are never overridden.
- `in_review` is not derived. A ticket under review reads `in_progress`.
- `Repo.tracked_status` gives this status. People and scheduling read it: `sdlc status`,
  `sdlc next`, and `sdlc run build`'s refusal of a ticket in progress on another branch. Checks
  that judge a branch keep reading `Repo.status_of` (merged trailers and stored status). Work on
  another branch therefore never changes a gate verdict.
- File mode keeps stored status, unchanged.
- The rest of ADR-0001 section 5 stands.

## Consequences

- Status works without network access or credentials. To see other people's branches, run
  `git fetch` first. The board reflects the last fetch.
- A branch that is abandoned holds its ticket until it is deleted. A squash-merged ticket reads
  `in_progress` while its branch exists, since the squash drops the trailer from the base.
- Anyone with push access can name a ticket in a commit on any branch and so hold it out of
  `sdlc next` and `sdlc run build`. This affects scheduling only. Approvals, gates and merges do
  not read it. Deleting the branch frees the ticket. Push access is already the trust boundary
  for every branch, so no ownership claim is added.
- The derivation runs one `git log` per branch ref. Repositories with many stale
  remote-tracking refs should prune them (`git fetch --prune`).

## Not decided

- Whether to add `in_review` from the forge's open PRs as an optional enrichment when a token
  is present. Revisit when a product needs a review queue on the board.
