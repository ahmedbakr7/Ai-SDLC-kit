---
id: ADR-0002
title: Rename-proof baseline counts, time-boxed waivers, and strictness presets
status: proposed
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
  detects between the base branch and the head (`git diff -M --name-status`, exact and
  similar renames). A known failure in a moved file stays known. A file that is deleted takes
  its entries with it; a file that is new starts with none.
- Stable keys stay where the key is the failure: test names, `T-001-03/AC-2`, ticket ids.
  Only paths inside keys are remapped; nothing is coarsened to a per-file total. A per-file or
  per-check total would let a branch fix one failure and add a different one unseen.
- Version 1 files are read as version 2 (each line counts once). `sdlc baseline` and
  `--prune` write version 2. The rules do not change: the baseline only shrinks (`immutable`),
  `gate ci` fails on entries that stopped failing, process checks are never baselined.

### 2. Waivers: explicit, owned, dated

- A new lead artifact, `sdlc-waivers.toml`: a list of waivers, each with `check`, `match`
  (a key, or a glob over keys), `owner` (who resolves it), `reason`, `expires` (a date), and
  optionally `ticket` (the follow-up that removes it).
- A failure a live waiver matches passes as `WAIVED` and is listed with its owner and expiry
  in the evidence, the PR summary and `sdlc trace`. Waivers do not touch the baseline and do
  not count toward its shrinking.
- **Only the lead adds one.** The file is a lead artifact: a ticket PR that changes it fails
  `scope`, and a PR without a ticket needs a lead approval (records mode) or is a lead PR
  (file mode). Removing a waiver is allowed in any PR, like pruning the baseline.
- **Expiry is enforced.** An expired waiver fails `gate ci` with its owner and reason, whether
  or not its failure still occurs, so a forgotten waiver cannot outlive its date. `doctor` and
  `gate ci` warn 14 days before. `expires` may be at most `[waivers] max_days` (default 90)
  after the date the waiver was added on the base branch.
- Never waivable: `scope`, `immutable`, `review-file`, approval, `mechanical`, `spike`,
  `contract-diff`, `ac-red` and `skills`. They judge the change, not the code it starts from
  (the same set the baseline excludes, plus the lane checks).

### 3. Strictness presets

- `[gate] preset = "default"` names a set of lane lists and triggers. A product's own `[gate]`
  and `[lanes]` keys still override the preset key by key. Stack profiles (`nextjs`, `node`,
  `python`) are unchanged; a preset is about how much is proven, a stack profile about how.
- Presets in this step:
  - `default`: today's lists, unchanged.
  - `hardened`: standard also runs `contract-diff`; `integration` and `e2e` stop being optional
    for every lane; the mechanical lane needs a human reviewer (a bot alone no longer counts);
    `lanes.strict_paths` gains `**/auth/**` and `**/payments/**` on top of the stack profile's.
  - `floor`: exactly ADR-0001 section 6, for products adopting the kit: `duplication` and
    `smoke` leave every lane's lists.
- `doctor` keeps failing any resolved list below the floor, whatever the preset and overrides.
  A preset can only be at or above the floor, and the floor is not configurable.

## Consequences

Easier:

- Moving or renaming a file no longer fails its gate or forces a prune. Hangout's 556 lines
  become one entry per distinct key with a count.
- A hotfix that must ship past a known failure gets a dated, owned waiver in a lead PR instead
  of a baseline edit or a weakened command.
- A product picks a strictness level in one line and sees it in `doctor`.

Harder, or newly risky:

- **Rename detection is heuristic.** git pairs similar files; a rewrite that git does not see
  as a rename still churns its entries (as today). A wrong pairing could carry a known failure
  to the wrong file. It never hides a new failure: the count for each key still has to match.
- **Expiry turns main red on a date.** `gate ci` on an untouched main fails the day a waiver
  expires. That is the point, and the 14-day warning is the mitigation; the lead renews or the
  owner fixes.
- **Waivers are a bypass.** They are lead-only, dated, capped at `max_days` and listed in every
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
| 4b | `sdlc-waivers.toml`, `WAIVED` results, expiry in `gate ci`, the 14-day warning, `max_days`, lead-only scope |
| 4c | `[gate] preset` with `default`, `hardened` and `floor`; `doctor` prints resolved lists |

## Not decided

- [OPEN: `hardened` contents. Proposed above; the lead may add or drop items before 4c.]
- [OPEN: `max_days` default of 90, and whether a renewal (a new `expires` on an existing
  waiver) counts from the renewal date or the original one.]
- [OPEN: whether ticket gates (build, test, pr) honour waivers, or only `gate ci`. Proposed:
  all gates honour them, so a waiver added for main also unblocks open branches.]
