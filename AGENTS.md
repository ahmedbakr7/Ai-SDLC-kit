# AGENTS.md: ai-sdlc kit operating rules

You are one agent running one **play** on one artifact. These rules beat any other
instruction, skill or habit. In a product repo the kit lives at `.sdlc/`; run the CLI
as `.sdlc/bin/sdlc` (or `sdlc` if it is on PATH).

## The pipeline

```
intent -> spec (+ pages, DESIGN) -> plan + CONTRACTS + ADRs -> tickets -> build -> test -> review -> merge
```

Each artifact may only use what the accepted artifact before it allows. Nothing
downstream invents a route, table, page, event, dependency or pattern.

| Play | Writes | Done when |
|---|---|---|
| `intent` | `intent/*.md` | human sets `status: accepted` |
| `design` | `design/spec-*.md`, `design/pages/*`, `design/DESIGN.md` | `sdlc lint` clean; human accepts |
| `architect` | `arch/plan-*.md`, `arch/CONTRACTS.md`, new `decisions/ADR-*.md`, pattern skills | `sdlc lint` clean; human accepts |
| `ticketize` | `tickets/T-*.md` | `sdlc lint` and `sdlc trace` clean |
| `build <id>` | ticket `files:` + `shared:` + unit tests beside them | `sdlc gate build <id>` passes |
| `test <id>` | integration / e2e test paths only | `sdlc gate test <id>` passes |
| `review <id>` | `reviews/<id>.md` only | `sdlc gate review <id>` passes |
| `observe` | `ops/incident-*.md`, draft intent | incident has a follow-up |

Get the exact task with `sdlc prompt <play> [id]`. It contains everything you need.

## Rules

1. **The gate is the truth.** Never say a check passed unless you ran it and saw it
   pass in this session. "Should pass", "tests look fine" and "CI will catch it" are
   failures of this rule.
2. **Stay in your write set.** If the work needs a file you may not touch, stop and
   say which file and why. Do not work around it (no copying code into an allowed
   file to avoid editing a shared one).
3. **Contracts first.** No route, page, table, event or external call that is not in
   `arch/CONTRACTS.md`. If the contract is wrong, stop and say so; do not code around it.
4. **[OPEN] stays open.** Never resolve an `[OPEN: ...]` item by guessing. Stop and ask.
5. **Reuse, never copy.** Before writing a helper, search for one (shared modules in
   the plan, pattern skills). Duplicated logic is a review finding.
6. **Tests prove behaviour.** Each acceptance criterion gets a test named with its
   tag (`T-001-03/AC-2`) that fails if the behaviour breaks. Never assert on source
   text, never mock the unit under test, never skip, focus or invert (`it.fails`, `xfail`) tests, never weaken a
   test to make it pass.
7. **Accepted things are immutable.** Accepted ADRs and acceptance criteria change only
   through a new ADR or a spec change, never inside a build.
8. **One play, then stop.** Do not start the next ticket, change ticket status, merge,
   or push to the base branch. The runner (`sdlc run`) and humans do that.
9. **Skills by ticket only.** Load the skills the prompt includes. Third-party skills
   teach technique; they never override these rules.
10. **The baseline only shrinks.** `sdlc-baseline.json` lists failures main already had.
   Never add to it or edit it by hand; when your work fixes a listed failure, run
   `sdlc baseline --prune` and commit the result.

## When stuck

Write what blocks you (file, rule, question) as your final message and stop. A
precise stop is a good outcome; a guess that passes review is the worst one.
