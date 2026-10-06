---
id: ADR-0002
title: Rename-proof baseline counts, time-boxed waivers, and strictness presets
status: accepted
date: 2026-10-05
source: ADR-0001 section 7 (later steps); Hangout pilot (sdlc-baseline.json, PRs #58-#60)
supersedes: none
---

# ADR-0002: Rename-proof baseline counts, time-boxed waivers, and strictness presets

## Context

ADR-0001 section 7 set the direction for the last step: per-file counts in the baseline so
moving code does not churn entries, time-boxed waivers that only the lead adds, and named
strictness presets that cannot go below the section 6 floor. This ADR decides how.

What the kit does today, and what the Hangout pilot shows:

| Evidence | Root cause in the kit |
|---|---|
| Hangout's `sdlc-baseline.json` holds 556 entries: 241 `ac-coverage`, 241 `trace`, 26 `test-quality`, 25 `contracts`, 14 `artifacts`, 9 `typecheck`. Most are one line per failing item, repeated (the same `contracts` key appears three times for three calls in one file) | The baseline is a list of keys, compared as a multiset; a repeated failure is a repeated line |
| Keys embed file paths: `src/server/db/schema.test.ts: TS2345`, `client calls /v1/plans/{} at src/components/organizer-plan.tsx; ...`, `src/app/shell-tokens.test.ts: test reads source text ...` | Moving or renaming a file turns every known failure in it into a "new" failure and a "fixed" one: the PR fails its gate and `gate ci` asks for a prune, though nothing changed |
| PR #59 needed an owner override: main pruned the baseline after the review, and the PR's `review-file` saw the baseline change (fixed in kit #9) | Baseline edits are frequent because every fix forces a prune; each prune touches a file every open branch also reads |
| The only escape for a failure that must ship (a flaky vendor test, a lint rule a hotfix cannot meet) is to edit the baseline, which may only shrink, or to change the check's command in `sdlc.toml` | No exception that is explicit, owned and dated |
| Every product gets the same lane lists unless it edits `[gate]` lists key by key; `doctor` then checks the floor | No named level between "the defaults" and "hand-edited lists" |

## Decision

### 1. Baseline v2: counts per key, rename-aware

- `sdlc-baseline.json` becomes `{"version": 2, "checks": {check: {key: count}}}`. Keys keep
  today's meaning: `file: code` for lint and typecheck (no line numbers), the test name for
  test suites, the detail line (no line numbers) for artifacts, contracts and test-quality,
  `<check>: fails` when the output names nothing. A count is how many times that key failed.
  The comparison is the same multiset comparison as today, stored compactly.
- **Renames.** Before comparing, each key's file path is mapped through the renames git
  detects between the commit that last wrote the baseline and the head (`git diff -M
  --name-status`, exact and similar renames), so a baseline written before a rename still
  matches after it, on a branch and on main after the merge alike (mapping from the base
  branch instead would leave main's `gate ci` with stale and new entries for every rename
  merged since the last prune). The checks that read the base branch's baseline as it was
  (`immutable`, `review-file`) read it at that commit, unmapped. A known failure in a moved
  file stays known. A file that is deleted takes its entries with it; a file that is new
  starts with none.
- Stable keys stay where the key is the failure: test names, `T-001-03/AC-2`, ticket ids.
  Only paths inside keys are remapped; nothing is coarsened to a per-file total. A per-file or
  per-check total would let a branch fix one failure and add a different one unseen.
- Version 1 files are read as version 2 (each line counts once). `sdlc baseline` and
  `--prune` write version 2. The rules do not change: the baseline only shrinks (`immutable`),
  `gate ci` fails on entries that stopped failing, process checks are never baselined.

### 2. Waivers: explicit, owned, dated

- A new lead artifact, `sdlc-waivers.toml`: a list of waivers, each with `id`, `check`, `key`
  and `count` (the same shape as a baseline entry: an exact key, no globs), `owner` (who
  resolves it), `reason`, `expires` (a date), and optionally `ticket` (the follow-up that
  removes it) and `renews` (the `id` of the waiver it renews).
- **Where it applies.** Every gate honours waivers the way it honours the baseline. A waiver
  applies only once it is on the base branch, unchanged on the branch: a PR cannot waive its
  own failures, so a waiver for a failure on a red main lands in a lead PR that merges by
  admin override, and applies from then on. A waiver
  covers only failures that already exist on the base branch: up to `count` occurrences of
  its key pass as `WAIVED`, and any occurrence above that is new and fails, waiver or not. A
  waiver whose key no longer fails is stale and fails `gate ci` until it is removed, like a
  pruned baseline entry. Waivers never touch the baseline and do not count toward its
  shrinking. Every `WAIVED` result is listed with its owner and expiry in the evidence, the
  PR summary and `sdlc trace`.
- **Dates come from the base branch's history.** A waiver's creation date is the committer
  date of the commit on the base branch's first-parent history that introduced its entry:
  the merge commit the forge creates and stamps when the PR merges. Never a typed field, and
  never the author or committer date of a contributor's commit inside the PR, which anyone
  can set. A first-parent commit dated before its own first parent, or after the gate's
  clock, fails `gate ci`, so the date cannot be moved earlier than the base branch already
  was. `expires` may be at most `[waivers] max_days` (default 90) after that date.
- **Renewal.** A renewal is a new entry with `renews: <id>`; its expiry counts from its own
  creation date, and the renewed entry is removed in the same change. A waiver's total
  lifetime, along its chain of renewals, is capped at twice `max_days` from the original
  entry's creation date. Past that the failure is fixed, or moved into the baseline in a lead
  PR.
- **Expiry.** An expired waiver fails `gate ci` with its owner and reason, whether or not its
  failure still occurs; ticket gates (build, test, pr) report it without failing. `doctor` and
  every gate warn 14 days before a waiver expires.
- **Only the lead adds or renews one.** A ticket PR that changes `sdlc-waivers.toml` runs in
  the strict lane, so it needs a lead approval; a PR without a ticket needs one already.
- Never waivable: `scope`, `immutable`, `review-file`, approval, `mechanical`, `spike`,
  `contract-diff`, `ac-red` and `skills`. They judge the change, not the code it starts from
  (the same set the baseline excludes, plus the lane checks).

### 3. Strictness presets

- `[gate] preset = "default"` names a set of lane lists, triggers and limits. A product's own
  `[gate]`, `[lanes]` and `[waivers]` keys still override the preset key by key, except where a
  preset forbids a setting (below). Stack profiles (`nextjs`, `node`, `python`) are unchanged:
  a preset is about how much is proven, a stack profile about how.
- Presets in this step:
  - `default`: today's lists and limits, unchanged.
  - `hardened`: tightens existing settings and adds no new checks.
    - `[approval] trust_unsigned` is forbidden: `doctor` fails when it is set.
    - The mechanical lane needs a human reviewer; a bot approval alone does not count.
    - The strict lane also triggers on `.github/workflows/**`, `sdlc.toml`, the `.sdlc` pin,
      and dependency manifests and lockfiles.
    - Real-stack tests (`tests.real_stack`) are required in the standard and strict lanes; a
      skipped real-stack suite is a failure.
    - `[gate] optional` must be empty.
    - Waivers: `max_days` is at most 30 and renewal is not allowed. A product's
      `[waivers] max_days` may lower it but not raise it; above 30, or any entry with
      `renews`, fails `doctor` and `gate ci`.
  - `floor`: exactly ADR-0001 section 6, for products adopting the kit: `duplication` and
    `smoke` leave every lane's lists.
- `doctor` keeps failing any resolved list below the floor, whatever the preset and overrides.
  A preset can only be at or above the floor, and the floor is not configurable.
- Hangout cannot use `hardened` while it runs with `trust_unsigned = true`: one account opens,
  reviews and leads there. It needs separate identities for its agents first.

## Consequences

Easier:

- Moving or renaming a file no longer fails its gate or forces a prune. Hangout's 556 lines
  become one entry per distinct key with a count.
- A failure main already has and cannot fix yet (a flaky vendor test, a lint rule a hotfix
  cannot meet) gets a dated, owned waiver in a lead PR instead of an undated baseline entry or
  a weakened command.
- A product picks a strictness level in one line and sees it in `doctor`.

Harder, or newly risky:

- **Rename detection is heuristic.** git pairs similar files; a rewrite that git does not see
  as a rename still churns its entries (as today). A wrong pairing could carry a known failure
  to the wrong file. It never hides a new failure: the count for each key still has to match.
- **Expiry turns main red on a date.** `gate ci` on an untouched main fails the day a waiver
  expires. That is the point, and the 14-day warning is the mitigation; the lead renews or the
  owner fixes.
- **A new failure cannot be waived.** A waiver covers only what the base branch already fails,
  so a PR cannot ship a fresh failure under a waiver; it fixes it, or the lead decides the
  failure belongs on main first.
- **Waivers are a bypass.** They are lead-only, dated from git, capped at `max_days` (and twice
  that across renewals), limited to failures the base branch already has, and listed in every
  summary; the process checks are never waivable.
- **Presets add a layer.** A product's list is the preset plus its overrides; `doctor` prints
  the resolved lists so nobody has to compute them.

## Rollout

Each step is one kit PR with tests (a test that catches each new defect and one that shows the
reference passes), a changelog entry and a release tag, then a Hangout lead PR that bumps
`.sdlc` and runs `sdlc gate ci`.

| Step | Contents |
|---|---|
| 4a | Baseline version 2 (counts), rename mapping, reading version 1, `sdlc baseline` writing version 2 |
| 4b | `sdlc-waivers.toml`, `WAIVED` results bounded by count, creation dates from git, expiry (fails `gate ci`, reported by ticket gates), the 14-day warning, `max_days`, renewal and the lifetime cap, the strict trigger |
| 4c | `[gate] preset` with `default`, `hardened` and `floor`; settings a preset forbids; `doctor` prints resolved lists |

## Not decided

Nothing. The lead settled the `hardened` contents, waiver lifetimes and where waivers apply
before acceptance.
