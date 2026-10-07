# Changelog

Releases are tags on `main` (`vMAJOR.MINOR.PATCH`, with `-rcN` while a version is in
review); `sdlc --version` prints the same number. Products pin a tag (CONSUME.md, "Pin it").
MAJOR moves when an upgrade can fail a product that passed before, MINOR for new checks and
behaviour that existing products keep passing (or that sit behind a setting), PATCH for fixes.

## Unreleased

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
