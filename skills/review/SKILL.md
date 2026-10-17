---
name: review
description: Adversarially review one built ticket against its AC, CONTRACTS, patterns and evidence, and write reviews/<id>.md with a verdict. Use for /review <ticket-id>. Never the agent that built it.
---

# Play: review

Your job is to find what is wrong before users do. Approving bad work is the failure
this play exists to prevent; a precise `request_changes` is a success. You did not
write this code. Do not trust its PR text, its comments or its tests' names.

## Inputs

The ticket, CONTRACTS excerpt, pattern skills, and the build evidence (gate result,
every check, AC -> test mapping) in your prompt. Read the diff yourself:
`git diff <base>...HEAD` and open every changed file.

## Procedure

1. **Gate.** If the build or test evidence is not `pass`, is from a dirty tree, or the
   test evidence predates the latest build: `request_changes`. Stop reviewing. Missing test
   evidence counts too when the gate requires it: the ticket has a test play, its build was
   not in the mechanical or refactor lane, and `tests.real_stack` is not empty. Then the test play has
   not run, and the gate rejects an approval without it. Otherwise (a ticket marked
   `test: none`, a `type: test` ticket, a spike, a mechanical or refactor build, or
   `tests.real_stack = []`) the prompt says "No test evidence needed"; the build evidence
   is the proof, so never ask for test evidence.
2. **AC by AC.** For each AC, open the test the evidence names and answer: would this
   test fail if the behaviour broke? Reject proof that:
   - asserts on source text, class names or snapshots of markup instead of behaviour;
   - mocks the function under test, or stubs the network call the AC is about;
   - checks only the happy path when the AC names an error/empty case.
3. **Contract and ADRs.** Compare each changed route/handler with CONTRACTS line by line:
   path, method, status codes, payload field names and types, error codes, auth rule.
   Open every ADR in the ticket's `source_adr`; the diff must agree with each. A change
   to what another accepted ADR decides (its subject, the modules or libraries it names)
   that the ticket does not cite is a finding: blocking when it contradicts the ADR,
   otherwise ask the lead to cite it.
4. **Reuse and conventions.** Search the codebase for logic the diff re-implements
   (auth/role checks, db clients, formatters, API clients, parsing). Copied logic is a
   blocking finding. Check each new file's location, library and pattern against the
   **Conventions** in the pattern skills: a deviation is blocking. Where the conventions
   do not settle a choice, the diff must follow the closest existing example (find it);
   name the gap under `## Findings` so the lead can add it to the conventions.
5. **Edges.** Check the failure paths the spec and page files list: empty, error,
   unauthorised, concurrent, invalid input. Missing = finding.
6. **Security.** Authorisation enforced server-side on every new route; input
   validated; no secrets or PII in logs; no injection via string-built queries/HTML.
7. **Scope and amendments.** The build gate's `scope` details list files outside the
   ticket's areas. Accept each one that belongs in this change by naming it under
   `## Out of area` with why; anything else is a blocking finding. Read every new line
   in the ticket's `## Amendments` and name each `strengthen`, `split` and `widen`
   target under `## Amendments` in the review: a `strengthen` that is really weaker,
   or a `split` that drops behaviour, is blocking. In the mechanical lane, judge the transform list:
   a literal applied to a value and its test alike (`"404" -> "200"`) passes the suite
   while changing behaviour. In the refactor lane (ADR-0004), the gate proved the AC tests pass
   on the base and the head; you prove the rest. Read old and new code side by side and write
   under `## Equivalence` why they agree on every input, including inputs no test covers
   (errors, empty values, ordering, side effects, timing). A difference is blocking: the
   ticket is not a refactor. Read every line added inside an existing test: an early
   `return` or a new guard weakens it while the gate sees only added lines.
8. **Write** the review: `reviews/<id>.md`, or, when the prompt names `.sdlc-run/review-<id>.md`,
   that file with front matter `sdlc: approval`, `ticket`, `commit` (the HEAD you reviewed),
   `verdict`, `role: review`, `reviewer`, then the same template. Use the template at the end of
   this skill (for `reviews/<id>.md`: frontmatter `ticket`, `verdict`, `reviewer` = your agent name, `commit` = the
   commit in the latest evidence: test if the test play ran, else build). One AC table row per AC. Each finding has
   `file:line`, the rule it breaks, and the change you want.
9. Run `sdlc gate review <id>` until it passes. Stop.

## Lead PRs

A PR that moves no ticket is the lead's (config, CI, the kit pin, specs, plans, ADRs,
tickets, docs). Its prompt (`sdlc prompt review --pr N`) has no ticket, AC or evidence,
so the procedure's steps 1, 2, 7 and 8 do not apply. Do these instead:

- **Range.** `git log -1` is the HEAD the prompt names. Read the whole diff and every
  changed file at HEAD.
- **Lead write set.** A file the prompt marks "not lead-owned" is code without a ticket:
  blocking. Run `sdlc gate pr` and `sdlc lint`; a failure, or a lint issue the base did
  not have, is blocking.
- **Claims.** Check every factual claim the diff makes (paths, commands, versions,
  shas, what the kit does) against the repository, and run any local, safe command a
  doc tells someone to run. A claim you could not check is a finding.
- **Conventions and ADRs.** A changed pattern skill, CONTRACTS or ticket must agree
  with the accepted ADRs; changing an accepted ADR's decision needs a new ADR.

Then apply steps 3 to 6 where the diff touches what they cover, write the record the
prompt names (**What I verified** and **Findings**, not the template below), and stop.

## Verdict

- `approve`: gate pass, every AC has real proof, no blocking finding.
- `request_changes`: anything else. Minor findings alone do not block; list them.

## Template

```markdown
---
ticket: T-NNN-NN
verdict: approve | request_changes
reviewer: <your agent name>
commit: <commit from evidence>
---

# Review T-NNN-NN: <title>

## Gate
## Acceptance criteria
| AC | Proof | What the test actually asserts |
|---|---|---|
## Findings
## Out of area
## Amendments
## Checklist
```
