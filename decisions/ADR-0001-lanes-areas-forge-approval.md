---
id: ADR-0001
title: Risk lanes, soft areas, ticket amendments, and approvals bound to the PR's own diff
status: accepted
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
| Moving 29 UI call strings from `/v1` to `/api/v1` took two tickets (T-001-32, T-001-33), a full TDD and red-proof cycle, separate review sessions and several lead PRs | One flow for every change; no way to say "this diff is a rename" and have the engine prove it |
| The builder stops and asks whenever it finds a missing file or a gap in the AC | `files:` is a hard write set (`scope` fails); AC are immutable inside a ticket (`immutable` fails) |
| Kit PRs #8, #9, #10 all fixed whether a committed review or evidence file still covers the code after a base merge | Approval and evidence live in the tree, so every base merge forces the engine to decide which commits "count" |
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
  its risk, and approvals stop being files a base merge can strand.

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
| Mechanical only: any changed line, in any file, that the declared transforms do not produce (residue) | standard |
| Mechanical only: a file added or deleted other than by a declared move | standard |
| Mechanical only: the ticket adds or changes an AC | standard |

**Strict always wins.** A change that touches CONTRACTS or a strict path is strict even when
it is a pure rename. Renaming contract paths is a contract change: it needs the contract
diff and lead sign-off, never the mechanical lane.

**mechanical** (renames and moves the engine can prove):

- The ticket declares `transforms:`. Allowed kinds: literal substitution
  (`"/v1/" -> "/api/v1/"`), identifier rename (word-boundary token substitution), and file
  move. No general regex: a pattern with captures can encode any edit.
- The `mechanical` check replays the transforms on the base version of every changed file
  and compares the result with the head, byte for byte. **The transforms must produce the
  whole diff, production and tests alike.** Any residue raises the PR to standard. So a
  refactor that is not a pure rename or move (extracting a function, reordering logic) is
  standard; the lane covers what the engine can prove, not what the author claims.
- Checks: the full `gate ci` list (lint, typecheck, every test suite, `ac-coverage` for every
  shipped ticket, test-quality, contracts, build, smoke, skills, immutable) plus `mechanical`.
  No `ac-red`, no test play, no AC required on the ticket.
- Review: one approving review from an allowlisted reviewer or bot identity (section 4) other
  than the author. The review judges the transform list, which is the only thing the engine
  cannot: a literal substitution applied to both a value and its test (`"404" -> "200"`)
  replays cleanly and passes the suite while changing behaviour.
- A mechanical ticket may be created in the same PR that applies it. The proof above makes
  self-declaring safe; if the PR raises to standard, the ticket must already be `ready` on
  the base branch, as today.

**standard**: today's flow. Build gate with `ac-red`, test play with real-stack proof,
review by an independent session, AC-tagged tests for every AC.

**strict**: standard plus:

- `contract-diff`: a structured diff of CONTRACTS (routes, pages, tables, fields) from the
  merge base to the head, published in the gate output. Every changed key must be cited in
  the ticket's `contracts:`; a removed or narrowed key is marked breaking.
- Real-stack e2e is required: every suite in `tests.real_stack` must be configured and run;
  `skip` is a failure (`[gate] optional` does not apply in this lane).
- Lead sign-off: an approval from an identity in `[approval] leads` (section 4).

### 2. Areas replace `files:`

- Tickets list `areas:` (globs). `files:` is read as `areas:` until `sdlc migrate` rewrites it.
  The `MAX_FILES = 8` rule goes; ticket size is judged by AC count and review.
- A changed file outside the areas is a **flag**, not a `scope` failure. Flags appear in the
  gate output and the PR check summary. The approving review must name each flagged path (or
  a glob covering it) under `## Out of area`; an approval that misses one is invalid. This is
  machine-checked, so soft areas never become silent. The reviewer decides, not the lead, and
  the builder does not stop.
- Tests beside an in-area file are in area.
- `ac-red` reverts the PR's changed files that match `[tests] source_globs` (production
  source; the nextjs profile sets `src/**`) and are not tests, instead of only `files:`.
  Manifests, lockfiles, config and docs are not reverted: reverting them can break the
  install or build and fail ac-red for the wrong reason. Those changes are judged in review.
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

An approval is a record `{reviewed sha R, reviewer identity, role (review | lead | bot),
verdict, body}`. The body is today's review template (gate, AC table, findings, out-of-area).
It is never committed to the tree.

**Coverage is decided by replay, location-exact.** An approval of R covers the current head H
when, for the PR's changed files at H (the same set as at R):

- a file the base did not change between `merge-base(base, R)` and `merge-base(base, H)` is
  byte-identical at R and H;
- a file the base did change is exactly what `git merge-file` produces when it applies the
  base's change (old merge base to new) to R's version, and that merge is clean.

This is the replay `same_branch_change` already implements (kit #10), applied per file. A base
merge that leaves the PR's lines where and what they were keeps the approval. Moving an
approved line, editing it, a conflict resolution, an amendment, or a base edit overlapping a
PR line voids it. A content-only hash was rejected: it ignores location, so moving an
approved line elsewhere in the file would keep the approval on code nobody reviewed.

**Identity is verified against an allowlist.** `[approval] reviewers`, `leads` and `bots` list
forge identities. `sdlc/approval` reads who posted each record (the PR review's author, or the
commit status's `creator`) and counts it only when:

- the identity is in the list for the role the lane needs;
- for a standard or strict approval, the identity is not the PR author and did not author
  any PR commit;
- the reviewing agent does not appear in the `Sdlc-Agent` trailer of any PR commit (today's
  rule).

A record from any other identity is ignored, so a builder's token that posts a status
approves nothing. When the agents and the lead share one forge identity, no approval can
pass these rules: `sdlc/approval` fails closed and names the missing separation. Agents
need their own forge identity (an app, or one each for building and reviewing).

**Where records live** (`[approval] mode`):

| Mode | Record | Identity |
|---|---|---|
| `forge` (GitHub first; the interface is forge-neutral) | An approving PR review on R, or a commit status `sdlc/review/<ticket>` on R whose target links the review body (a PR comment) | The review author or the status `creator`, checked against the allowlist |
| `git` (plain-git fallback) | A git note on R in `refs/notes/sdlc`, front matter plus body | The signer of the notes commit, checked against an allowed-signers file. Unsigned notes count only with `[approval] trust_unsigned = true`, and the gate output then says the approval layer is trust-based |

In `git` mode CI must fetch `refs/notes/sdlc` explicitly (`git fetch origin
refs/notes/sdlc:refs/notes/sdlc`); it is not fetched by default, and most fork workflows
drop notes. When the ref is missing, `sdlc/approval` fails closed instead of reading "no
approval needed".

The review agent still only writes a file (`.sdlc-run/review-<id>.md`); the runner publishes
it with the reviewer's credentials. Agents never need forge credentials themselves.

**Checks in CI.** Two required checks, so a new approval does not re-run the tests:

- `sdlc/gate`: the lane's checks on the head.
- `sdlc/approval`: resolves the lane, then requires approvals covering the head for the
  lane's roles (mechanical: a reviewer or bot; standard: an independent reviewer; strict:
  that plus a lead; any lead-only amendment: a lead). Re-runs on review and status events.

The merge rule becomes: both checks green on the head commit.

### 5. Evidence in CI, status derived

- Gate runs write evidence to `.sdlc-run/` only. CI uploads it as an artifact and publishes
  the summary in the `sdlc/gate` check. `evidence/` is no longer written or read.
- Nothing trusts earlier evidence: `gate pr` runs the lane's checks, including `ac-red` and
  real-stack proof, on the head. Today `gate pr` checks only artifacts, scope, immutable and
  the review file, and trusts the committed build and test evidence. This is stricter.
- Cost: `ac-red` adds one extra unit-suite run per push (all source files are reverted
  together, as today). Fine at Hangout's size. Results are cached by the pair (head tree,
  merge-base tree), so a re-run on the same trees, or a push that changes only the PR
  description, reuses them.
- The test and review plays judge what they changed against the HEAD the runner recorded
  before the agent started (`since`), as today; they no longer look it up from evidence commits.
- **Status is derived, not stored.** Stored values shrink to lead decisions:
  `draft | ready | blocked`. Delivery states come from git and the forge:
  - `done`: a commit reachable from the base branch carries `Sdlc-Ticket: <id>`. The runner
    and `sdlc commit` add the trailer; `gate pr` requires it on at least one PR commit per
    ticket, and finds the PR's tickets from it (replacing file-based `pr_tickets`).
  - Merge commits are the default and need no settings: the branch's commits stay reachable.
    Squash merges work when the squash message keeps the trailer (repository setting, or the
    trailer in the PR body). The engine only scans reachable commits, so any strategy that
    keeps the trailer works.
  - `in_progress` / `in_review`: an open (draft / ready-for-review) PR, or in `git` mode an
    unmerged branch, whose commits carry the trailer.
  - Tickets already `done` before migration keep `status: done` as a frozen fact.
- `sdlc status` reports instead of writing delivery states. `depends_on`, `sdlc next`, and
  `gate ci`'s `ac-coverage` read the derived state.

### 6. What stays hard

- `immutable`: accepted ADRs, weakening or removing AC without a spec change or a lead
  approval, deleting a non-draft ticket, growing the baseline.
- The base branch's `sdlc.toml` judges every PR, including its lane lists and allowlists.
- `doctor` fails a lane list below the floor. Mechanical must include lint, typecheck, every
  configured test suite, build, `ac-coverage`, test-quality, contracts, immutable and
  `mechanical`. Standard must include `ac-red`. Strict must include `contract-diff`. In
  `forge` mode `doctor` fails when `[approval] reviewers` is empty.
- The test play still may not change production files: the red-proof separation is not an
  area question.
- Contracts first (AGENTS.md rule 3) becomes: a ticket PR that changes CONTRACTS runs in
  strict and needs a lead approval, instead of stopping.

### 7. Later steps (direction only; baseline, waivers and profiles get their own ADR before code)

- **Releases**: semantic version tags with a changelog on the kit repo. Products pin a tag
  through the `.sdlc` submodule, and the lead bumps it in a lead PR. `sdlc init` keeps
  copying the CI workflow into the product.
- **Baseline and waivers**: per-file counts for checks without stable keys (lint, typecheck),
  so moving code does not churn entries; stable keys stay for tests and AC. Time-boxed
  waivers with an owner and an expiry date; an expired waiver fails `gate ci`; only the lead
  adds one.
- **Strictness profiles**: named presets over lane lists and triggers. A profile can tighten
  anything but cannot go below the section 6 floor.

## Consequences

Easier:

- The `/api/v1` UI move becomes one mechanical ticket and one PR: one literal transform, the
  full suite, a bot review. T-001-33 can run this way once step 1 is pinned. (Deleting the
  transitional `/v1` section of CONTRACTS is a contract change and stays a strict lead PR.)
- Builders fix gaps in the PR (add an AC, touch an unlisted file) and the reviewer judges.
- Base merges no longer touch evidence. Approval coverage reuses kit #10's exact replay
  instead of growing a new rule.
- No status, evidence or review commits; no evidence-ordering loop.
- CI proves `ac-red` and real-stack AC on the head instead of trusting committed files.

Harder, or newly risky:

- **Transform lists are judged, not proven.** The engine proves the diff is exactly the
  declared transforms; only review decides the transforms preserve behaviour. The list is
  short, so this is a small review surface, but a bot review is the only guard in this lane.
- **Coverage does not judge base semantics.** A base change elsewhere that alters the meaning
  of an unchanged PR line (a renamed function the PR calls) keeps the approval. CI on the
  merged head still runs every check; the approval only says "a reviewer read these lines,
  here".
- **Exact replay re-voids more often.** A base edit adjacent to a PR line can make the merge
  conflict and void the approval. That costs a re-review, never a bypass.
- **Out-of-area is soft.** A builder can edit any non-strict file; the guard moves from the
  gate to the reviewer, enforced by the `## Out of area` acknowledgement.
- **Approvals need separate identities.** Until agents run under their own forge identity,
  `sdlc/approval` cannot pass in `forge` mode, and `git` mode is trust-based unless notes are
  signed. Hangout needs an app (or bot accounts) for the agents before it pins step 2.
- **Squash merges need a setting** to keep `Sdlc-Ticket:`. A squash that drops it leaves the
  ticket not `done`: its dependents stay blocked and `sdlc trace` shows it.
- Forge mode needs an API token in CI. `git` mode needs notes pushed and fetched.
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
| 1 | Lanes (resolution, triggers, mechanical with `transforms:`, strict's `contract-diff` and required e2e), areas, `[tests] source_globs` for ac-red, amendments (free kinds, split, spike), `doctor` lane floors | Still `reviews/<id>.md`. Lead-only amendments and strict's lead sign-off stay unavailable: weakening still needs a spec change, and a strict ticket needs `accepted_by` on the base branch's version of the ticket (set in a lead PR) |
| 2 | Approval records with replay coverage and identity allowlists (`forge` and `git` modes), `sdlc/gate` and `sdlc/approval`, evidence as CI artifacts with ac-red caching, derived status and `Sdlc-Ticket:`, lead-only amendments, strict lead sign-off, `sdlc followups`, migration | Approval records; `reviews/` and `evidence/` read-only history |
| 3 | Release tags + changelog; the submodule pin documented in CONSUME.md | n/a |
| 4 | Count-based baseline, waivers, strictness profiles | (own ADR) |

## Not decided

Nothing. The one open item was settled after acceptance:

- **Forge identity on Hangout** (decided 2026-10-06 by the lead): one identity, trust-based
  by choice. Hangout is a solo pilot where the lead, the agents and the reviews all post as one
  account, so it keeps `[approval] trust_unsigned = true`, and every approval says
  "[trust-based: identities not verified]". Separate builder and reviewer identities, with
  credentials kept apart, are the way back to verified approvals and to the `hardened` preset
  (ADR-0002), which forbids trust-based approvals.
