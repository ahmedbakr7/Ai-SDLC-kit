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
   test evidence predates the latest build: `request_changes`. Stop reviewing. When the
   product configures `commands.integration` or `commands.e2e`, missing test evidence
   counts too: the test play has not run, and the gate rejects an approval without it.
2. **AC by AC.** For each AC, open the test the evidence names and answer: would this
   test fail if the behaviour broke? Reject proof that:
   - asserts on source text, class names or snapshots of markup instead of behaviour;
   - mocks the function under test, or stubs the network call the AC is about;
   - checks only the happy path when the AC names an error/empty case.
3. **Contract.** Compare each changed route/handler with CONTRACTS line by line: path,
   method, status codes, payload field names and types, error codes, auth rule.
4. **Reuse.** Search the codebase for logic the diff re-implements (auth/role checks,
   db clients, formatters, API clients, parsing). Copied logic is a blocking finding.
5. **Edges.** Check the failure paths the spec and page files list: empty, error,
   unauthorised, concurrent, invalid input. Missing = finding.
6. **Security.** Authorisation enforced server-side on every new route; input
   validated; no secrets or PII in logs; no injection via string-built queries/HTML.
7. **Write** `reviews/<id>.md` from the template at the end of this skill
   (frontmatter `ticket`, `verdict`, `reviewer` = your agent name, `commit` = the
   commit in the latest evidence: test if the test play ran, else build). One AC table row per AC. Each finding has
   `file:line`, the rule it breaks, and the change you want.
8. Run `sdlc gate review <id>` until it passes. Stop.

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
## Checklist
```
