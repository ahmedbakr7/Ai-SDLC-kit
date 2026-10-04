---
id: ADR-0001
title: Risk lanes, soft areas, ticket amendments, and approvals bound to the PR's own diff
status: proposed          # proposed -> accepted (lead) | rejected
date: 2026-10-04
source: Hangout pilot (hangout-planner docs/sdlc-pilot-report.md, PRs #54-#64; kit PRs #8-#10)
supersedes: none
---

# ADR-0001: Risk lanes, soft areas, ticket amendments, and approvals bound to the PR's own diff

## Context

The Hangout pilot proved the gate catches real defects, but it costs the same for every
change and pushes bookkeeping into git:

| Evidence from the pilot | Root cause in the kit |
|---|---|
| Moving 29 UI call strings from `/v1` to `/api/v1` took two tickets (T-001-32, T-001-33), a full TDD and red-proof cycle, separate review sessions and several lead PRs | One flow for every change; no way to say "this diff preserves behaviour" and have the engine check it |
| The builder stops and asks whenever it finds a missing file or a gap in the AC | `files:` is a hard write set (`scope` fails); AC are immutable inside a ticket (`immutable` fails) |
| Kit PRs #8, #9, #10 all fixed whether a committed review or evidence file still covers the code after a base merge | Approval and evidence live in the tree, so every base merge forces the engine to decide which commits "count" (`_changed_after_review`, `same_branch_change`) |
| Status edits create commits; evidence must be committed after the gate that produced it, and review after that | Ticket status, evidence JSON and `reviews/<id>.md` are files the PR itself must carry |

What worked and must survive: an independent reviewer, AC-tagged tests, mutation or red proof
of each AC, real-stack tests, a baseline that only shrinks, and one gate engine.

Options considered:

- **Loosen the existing checks** (warn instead of fail on scope and AC edits). Rejected: it
  weakens every change to make small ones cheap, and leaves the commit loops in place.
- **A separate "fast path" tool for small changes.** Rejected: two engines drift, and the
  pilot's bugs came from exactly that kind of special case.
- **Lanes inside the one engine, chosen by the engine from the ticket and the diff, plus
  approvals and evidence moved out of the tree** (this ADR). The cost of a change follows
  its risk, and the base-merge question goes away instead of getting another fix.

## Decision

### 1. Risk lanes

Every ticket PR runs in one of three lanes, ordered `mechanical < standard < strict`. Each
lane is a check list in `[gate]` (`mechanical`, `standard`, `strict`), read from the base
branch's `sdlc.toml` as today, so a PR cannot loosen its own lane.

**Resolution.** `effective = max(declared, classified, override)`.

- `declared`: the ticket's `lane:` field. If absent: `strict` when `risk: high` or
  `type: contract`, else `standard`. `mechanical` is never inferred; it must be declared.
- `classified`: what the diff shows (triggers below). It can only raise the lane.
- `override`: `sdlc gate pr --lane <lane>` or a forge label `sdlc:<lane>`. It can only raise.
- The engine never lowers a lane. Every raise is reported with the file and the trigger.

**Escalation triggers** (from the diff against the merge base):

| Trigger | Raises to |
|---|---|
| `arch/CONTRACTS.md` changed | strict |
| A file matches `[lanes] strict_paths` (globs; profiles ship migration dirs, products add auth and money paths) | strict |
| Mechanical only: a test file changed beyond the declared transforms, a test file deleted, or fewer test declarations in a file | standard |
| Mechanical only: a dependency added or changed in a manifest (`package.json`, `pyproject.toml`, ...) | standard |
| Mechanical only: the ticket adds or changes an AC | standard |

**mechanical** (rename, move, refactor; behaviour-preserving):

- Checks: the full `gate ci` list (lint, typecheck, every test suite, `ac-coverage` for every
  shipped ticket, test-quality, contracts, build, smoke, skills, immutable) plus a new
  `mechanical` check. No `ac-red`, no test play, no AC required on the ticket.
- The ticket declares `transforms:`: literal or regex substitutions and file moves
  (`"/v1/" -> "/api/v1/"`). The `mechanical` check replays them on the base version of every
  changed file and diffs the result against the head.
  - **Residue in test files fails the lane** (raises to standard). This is the invariant that
    replaces red proof: tests change only by the declared transforms, and the whole suite
    still passes. A refactor in Fowler's sense: same tests, same results.
  - Residue in production files is allowed (a refactor). It is listed for the reviewer.
- Review: one approving review from any reviewer identity other than the author; a review bot
  configured in `[approval] bots` qualifies. No separate reviewer session.
- A mechanical ticket whose transforms explain the **entire** diff (zero residue anywhere)
  may be created in the same PR that applies it. Otherwise the ticket must already be
  `ready` on the base branch.

**standard**: today's flow. Build gate with `ac-red`, test play with real-stack proof,
review by an independent session, AC-tagged tests for every AC.

**strict**: standard plus:

- `contract-diff`: a structured diff of CONTRACTS (routes, pages, tables, fields) from the
  merge base to the head, published in the gate output. Every changed key must be cited in
  the ticket's `contracts:`; a removed or narrowed key is marked breaking.
- Real-stack e2e is required: every suite in `tests.real_stack` must be configured and run;
  `skip` is a failure (`[gate] optional` does not apply in this lane).
- Lead sign-off: an approval whose reviewer is in `[approval] leads` (section 4).

### 2. Areas replace `files:`

- Tickets list `areas:` (globs). `files:` is read as `areas:` until `sdlc migrate` rewrites it.
  The `MAX_FILES = 8` rule goes; ticket size is judged by AC count and review.
- A changed file outside the areas is a **flag**, not a `scope` failure. Flags appear in the
  gate output and the PR check summary. The approving review must name each flagged path (or
  a glob covering it) under `## Out of area`; an approval that misses one is invalid. The
  reviewer decides, not the lead, and the builder does not stop.
- Tests beside an in-area file are in area.
- `ac-red` reverts every non-test file the PR changed, not only `files:`. This is stricter
  than today.
- Out-of-area edits to lead artifacts and strict paths are not soft: they raise the lane
  (section 1) or stay governed by `immutable` and the trusted config (section 6).

### 3. Ticket amendments, spikes and follow-ups

Amendments are edits to the ticket file inside the PR, so the PR diff is the record and the
reviewer sees them. Each one gets a line in an append-only `## Amendments` section of the
ticket body: `- <kind> <AC-n | area | T-id>: <reason>`.

| Amendment | Who decides | Engine rule |
|---|---|---|
| Add an AC | reviewer | New AC id; needs a tagged test like any AC |
| Strengthen an AC (reword) | reviewer | Reworded AC needs a `strengthen AC-n` line; the reviewer confirms it is stronger, else it is a weakening |
| Widen an area | reviewer | Free; areas are soft anyway |
| Split into a follow-up | reviewer | The AC moves verbatim to a new `draft` ticket with `split_from: <id>` in the same PR |
| Weaken or remove an AC | lead | `weaken AC-n` / `remove AC-n` line plus a lead approval of the head (section 4); without it `immutable` fails as today |

- A reworded AC without an amendment line still fails `immutable`, unless a requirement it
  serves changed in the spec (today's rule, unchanged).
- **Spike tickets** (`type: spike`): `questions:` instead of acceptance criteria. Deliverable:
  a findings file in the ticket's areas that answers each question under its own heading. A
  spike may not change production code or tests; any such change fails (a spike must not
  become a path around the lanes). Lane: standard review, no test play, no `ac-red`.
- **Follow-ups from review**: non-blocking findings in an approval are tagged `[follow-up]`.
  `sdlc followups <pr|sha>` turns them into `draft` tickets with `source_review:` in a lead
  PR after merge. They are not written into the reviewed PR, because that edit would make
  the approval it came from stale.

### 4. Approval bound to the PR's own diff

An approval is a record `{head sha, fingerprint, reviewer, role (review | lead | bot),
verdict, body}`. The body is today's review template (gate, AC table, findings, out-of-area).
It is never committed to the tree.

**Fingerprint.** For each changed path (renames detected), the ordered removed and added lines
of `git diff -U0 <merge-base>..<head>`, with hunk headers and line numbers dropped, hashed
with SHA-256. Whitespace is kept (indentation is code).

**Staleness.** An approval of sha R covers head H when `fingerprint(R) == fingerprint(H)`.
A base merge that leaves the PR's own lines unchanged keeps the approval. A conflict
resolution, an amendment, or any edit to a PR line makes it stale. This replaces
`_changed_after_review`, `same_branch_change` in approval checks, and `reviews/<id>.md`.

**Independence.** The reviewer must not appear in the `Sdlc-Agent` trailer of any PR commit
(today's rule). In forge mode, the forge identity that posted the approval must also differ
from the PR author for a standard or strict approval.

**Where records live** (`[approval] mode`):

| Mode | Record | Identity |
|---|---|---|
| `forge` (GitHub adapter first; the interface is forge-neutral) | An approving PR review on R, or a commit status `sdlc/review/<ticket>` on R whose target links the review body (a PR comment). A status works when the reviewer cannot approve in the forge (same account as the author) | The review author or the status `creator` |
| `git` (plain-git fallback) | A git note on R in `refs/notes/sdlc`, front matter plus body, pushed with the branch | Committer; `[approval] require_signed = true` verifies signed notes commits against an allowed-signers file |

The review agent still only writes a file (`.sdlc-run/review-<id>.md`); the runner publishes
it. Agents never need forge credentials.

**Checks in CI.** Two required checks, so a new approval does not re-run the tests:

- `sdlc/gate`: the lane's checks on the head.
- `sdlc/approval`: resolves the lane, then requires an approval covering the head for the
  lane's roles (mechanical: any reviewer or bot; standard: an independent reviewer; strict:
  that plus a lead; any lead-only amendment: a lead). Re-runs on review and status events.

The merge rule becomes: both checks green on the head commit.

### 5. Evidence in CI, status derived

- Gate runs write evidence to `.sdlc-run/` only. CI uploads it as an artifact and publishes
  the summary in the `sdlc/gate` check. `evidence/` is no longer written or read.
- Nothing trusts earlier evidence: `gate pr` runs the lane's checks, including `ac-red` and
  real-stack proof, on the head. Today `gate pr` checks only artifacts, scope, immutable and
  the review file, and trusts the committed build and test evidence. This is stricter.
- The test and review plays judge what they changed against the HEAD the runner recorded
  before the agent started (`since`), as today; they no longer look it up from evidence commits.
- **Status is derived, not stored.** Stored values shrink to lead decisions:
  `draft | ready | blocked`. Delivery states come from git and the forge:
  - `done`: a commit reachable from the base branch carries `Sdlc-Ticket: <id>`. The runner
    and `sdlc commit` add the trailer; `gate pr` requires it on at least one PR commit per
    ticket, and finds the PR's tickets from it (replacing file-based `pr_tickets`).
  - `in_progress` / `in_review`: an open (draft / ready-for-review) PR, or in `git` mode an
    unmerged branch, whose commits carry the trailer.
  - Tickets already `done` before migration keep `status: done` as a frozen fact.
- `sdlc status` reports instead of writing delivery states. `depends_on`, `sdlc next`, and
  `gate ci`'s `ac-coverage` read the derived state.

### 6. What stays hard

- `immutable`: accepted ADRs, weakening or removing AC without a spec change or a lead
  approval, deleting a non-draft ticket, growing the baseline.
- The base branch's `sdlc.toml` judges every PR, including its lane lists.
- `doctor` fails a lane list below the floor. Mechanical must include lint, typecheck, every
  configured test suite, build, `ac-coverage`, test-quality, contracts, immutable and
  `mechanical`. Standard must include `ac-red`. Strict must include `contract-diff`.
- The test play still may not change production files: the red-proof separation is not an
  area question.
- Contracts first (AGENTS.md rule 3) becomes: a ticket PR that changes CONTRACTS runs in
  strict and needs a lead approval, instead of stopping.

### 7. Later steps (direction only; each gets its own ADR before code)

- **Packaging and releases**: a stdlib zipapp and a pip-installable package, a reusable
  GitHub Action in the kit repo (doctor, gate, approval, evidence upload), semantic version
  tags with a changelog, and Renovate bumping the product's pin.
- **Baseline and waivers**: per-file counts for checks without stable keys (lint, typecheck),
  so moving code does not churn entries; stable keys stay for tests and AC. Time-boxed
  waivers with an owner and an expiry date; an expired waiver fails `gate ci`; only the lead
  adds one.
- **Strictness profiles**: named presets over lane lists and triggers. A profile can tighten
  anything but cannot go below the section 6 floor.

## Consequences

Easier:

- The `/api/v1` rename becomes one mechanical ticket and one PR: declared transforms, the full
  suite, a bot review. T-001-33 can run this way once step 1 is pinned.
- Builders fix gaps in the PR (add an AC, touch an unlisted file) and the reviewer judges.
- Base merges no longer touch approvals or evidence. The `_changed_after_review` family of
  bugs (#8-#10) has nothing left to decide.
- No status, evidence or review commits; no evidence-ordering loop.
- CI proves `ac-red` and real-stack AC on the head instead of trusting committed files.

Harder, or newly risky:

- **Mechanical residue in production code is judged, not proven.** A refactor that changes
  behaviour no test covers passes. The guard is: tests unchanged except declared transforms,
  every suite green, every shipped AC still proven, plus review. This is the accepted price
  of dropping red proof for this lane.
- **Fingerprints ignore context.** A base change that alters the meaning of an unchanged PR
  line (a renamed function the PR calls) keeps the approval. CI on the merged head still runs
  every check; the approval only says "a person or agent read these lines".
- **Out-of-area is soft.** A builder can edit any non-strict file; the guard moves from the
  gate to the reviewer, enforced only by the `## Out of area` acknowledgement.
- **Forge identity is only as strong as account separation.** If agents and the lead push
  and review under one forge account, lead sign-off cannot be told apart from the agent's.
  Real separation needs agents on their own account or app.
- **Merge-commit trailers.** Squash merges keep `Sdlc-Ticket:` only if the squash message
  includes commit messages or the PR body; products using squash must configure that.
  A squash that drops the trailer leaves the ticket not `done`: its dependents stay blocked
  and `sdlc trace` shows it, so the failure is visible, not silent.
- Forge mode needs an API token in CI. `git` mode needs notes pushed and fetched
  (`refs/notes/sdlc`).
- Play skills, templates, AGENTS.md rules 2, 3, 7 and 8, CONSUME.md, the CI workflow template
  and the example product all change. `sdlc migrate` must convert `files:` to `areas:`,
  drop delivery statuses, and leave `reviews/` and `evidence/` in place, read-only, for
  history.

## Rollout

Each step is one kit PR with tests (a test that catches each new defect and one that shows
the reference passes), a release tag, and a Hangout lead PR that bumps `.sdlc` and runs
`sdlc gate ci` and `sdlc gate pr`.

| Step | Contents | Approval storage in that step |
|---|---|---|
| 1 | Lanes (resolution, triggers, mechanical with `transforms:`, strict's `contract-diff` and required e2e), areas, amendments (free kinds, split, spike), `doctor` lane floors | Still `reviews/<id>.md`. Lead-only amendments and strict's lead sign-off stay unavailable: weakening still needs a spec change, and a strict ticket needs `accepted_by` on the base branch's version of the ticket (set in a lead PR) |
| 2 | Approval records and fingerprints (`forge` and `git` modes), `sdlc/gate` and `sdlc/approval`, evidence as CI artifacts, derived status and `Sdlc-Ticket:`, lead-only amendments, strict lead sign-off, `sdlc followups`, migration | Approval records; `reviews/` and `evidence/` read-only history |
| 3 | Packaging, Action, releases, Renovate | (own ADR) |
| 4 | Count-based baseline, waivers, strictness profiles | (own ADR) |

## Not decided

- [OPEN: Should a mechanical ticket created in the same PR be allowed only at zero residue
  (proposed), or never?]
- [OPEN: Should the `## Out of area` acknowledgement be required for a valid approval
  (proposed), or should out-of-area flags be advisory only?]
- [OPEN: Forge identity for agents on Hangout: a separate bot account or app, so that lead
  sign-off is verifiable. Without one, strict's lead sign-off is honour-system.]
- [OPEN: Merge strategy the kit assumes for `Sdlc-Ticket:`: merge commits (works as-is) or
  squash (needs repository settings).]
