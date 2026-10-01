---
name: research
description: Answer specific questions for the lead with cited, dated sources, separating facts from options and recommendations. Use for /research before an intent or ADR. Writes nothing to the repo.
---

# Play: research

Return one brief to the lead, then stop. Write no files.

## Brief format

```markdown
# Research: <question>  (as of YYYY-MM-DD)

## Answer
<3-6 sentences>

## Facts
- <fact> [source, date]

## Options
| Option | For | Against | Cost/limits |
|---|---|---|---|

## Recommendation
<one option and why; or "no recommendation" and what would decide it>

## Open
- [OPEN: <what the spec must not pretend is decided>]
```

Rules: cite every vendor/library claim with a link and date; prefer primary sources
(official docs, changelogs, pricing pages); say "unknown" rather than guess; stop when
each question has an answer or a clearly stated unknown.
