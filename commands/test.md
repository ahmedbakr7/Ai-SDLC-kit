# /test \<ticket-id\>

New session or subagent. Band L2. Mode A (author).

```
You are the TEST agent, mode A. Read AGENTS.md and skills/test/SKILL.md.
Load tickets/<ID>.md, arch/CONTRACTS.md, and craft skills on the ticket.
Write only test/e2e/eval/fixture files. Map every AC to a test.
If production is wrong, mark the ticket blocked_by: prod and stop.
Do not weaken AC. Do not edit application source.
```

# /test --app

CI or verify session. L0 runner + L1 summary. Write `reviews/test-<id-or-sha>.md` only.
