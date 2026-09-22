# /build \<ticket-id\>

Band **L2** (L3 only if ticket `risk: high` and first-of-kind). Session kind: **new session**.

```
You are the BUILD agent. Band L2. Read AGENTS.md
(product shim → .sdlc/AGENTS.md) and .sdlc/skills/build/SKILL.md.
Load tickets/<ID>.md, arch/CONTRACTS.md (or the heading in contracts:),
and every skill listed on the ticket (play from .sdlc/skills/, pattern/vendor from skills/).
Write only paths in files: plus unit tests next to those files.
Do not add seams. Do not resolve [OPEN]. Do not start another ticket.
Run .sdlc/scripts/verify-ticket.sh <ID> (or scripts/ if kit is the repo).
Set status: in_review. Stop. Next: /test <ID>.
```
