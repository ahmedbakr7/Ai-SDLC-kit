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
| `build <id>` | ticket `areas:` + `shared:` + unit tests beside them; amendments to its own ticket | `sdlc gate build <id>` passes |
| `test <id>` | integration / e2e test paths only | `sdlc gate test <id>` passes |
| `review <id>` | `reviews/<id>.md` only (`.sdlc-run/review-<id>.md` when approvals live outside the tree) | `sdlc gate review <id>` passes |
| `observe` | `ops/incident-*.md`, draft intent | incident has a follow-up |

Get the exact task with `sdlc prompt <play> [id]`. It contains everything you need.

## Rules

1. **The gate is the truth.** Never say a check passed unless you ran it and saw it
   pass in this session. "Should pass", "tests look fine" and "CI will catch it" are
   failures of this rule.
2. **Stay in your areas.** A build may change a file outside its ticket's `areas:` when
   the work needs it: the gate flags it, and the reviewer must accept it by name. Say
   why in your final message. Lead artifacts (specs, plans, ADRs, other tickets,
   `sdlc.toml`), other plays' evidence and reviews, and the test play's files are never
   yours: if the work needs one, stop and say which and why. The test and review plays
   stay inside their write sets. Do not work around a limit (no copying code into an
   allowed file to avoid editing a shared one).
3. **Contracts first.** No route, page, table, event or external call that is not in
   `arch/CONTRACTS.md`. A ticket that changes CONTRACTS runs in the strict lane and needs
   the lead's sign-off; never code around the contract.
4. **[OPEN] stays open.** Never resolve an `[OPEN: ...]` item by guessing. Stop and ask.
5. **Reuse, never copy.** Before writing a helper, search for one (shared modules in
   the plan, pattern skills). Duplicated logic is a review finding.
6. **Tests prove behaviour.** Each acceptance criterion gets a test named with its
   tag (`T-001-03/AC-2`) that fails if the behaviour breaks. Never assert on source
   text, never mock the unit under test, never skip, focus or invert (`it.fails`, `xfail`) tests, never weaken a
   test to make it pass.
7. **Accepted things are immutable; tickets are amended, not rewritten.** Accepted ADRs
   change only through a new ADR. A build may amend its own ticket, one line per change
   in its `## Amendments` section (`- <kind> <target>: <reason>`): `add AC-n`,
   `strengthen AC-n` (the reviewer confirms it is stronger), `split AC-n -> T-id` (the AC
   moves verbatim into a new draft ticket with `split_from:`), `widen <area>`. Weakening
   or removing an AC needs a spec change, or (when approvals live outside the tree) a
   `weaken`/`remove` line plus a lead approval. Everything else on a ticket is the lead's.
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
