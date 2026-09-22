---
name: research
description: Isolated research subagent. Use when the lead needs sources, options, or risks before writing intent.md. Returns a brief. Writes nothing in the repo.
---

# Skill: research

## Band

L1. Subagent. Dies after the brief.

## Writes

Nothing. Return markdown to the parent lead.

## Do

- Answer the lead’s questions with dated sources when possible.
- Separate facts, options, and recommendations.
- List `[OPEN]` items the spec must not pretend are decided.
- Do not invent vendors. If you name one, cite.

## Do not

- Commit files.
- Start implementation.
- Stay loaded into a later `/build` session. The lead copies conclusions into `intent.md` only.
