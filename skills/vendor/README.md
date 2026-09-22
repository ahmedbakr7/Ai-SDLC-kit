# Craft / vendor skills

Play skills (`skills/build`, `skills/test`, …) stay ours. This folder is for **proven third-party** Agent Skills (`SKILL.md` folders).

## Why they are here

Marketplace / `npx skills add` / Claude plugins teach *how to use a stack*. They must not teach *how work moves*. That stays in `AGENTS.md`.

## How to add one

1. Prefer a `SKILL.md` folder (Agent Skills standard). Works in Claude Code, Cursor, Codex, Copilot, OpenCode, others.
2. Install with a cross-harness tool if you want, e.g. `npx skills add <owner>/<repo> --skill <name>`.
3. **Copy the skill folder into** `skills/vendor/<name>/`.
4. Pin source + sha in `skills/VENDOR.lock.md`.
5. Commit it. Do not leave it only in `~/.claude/skills/` or account plugin sync.
6. Put `<name>` on tickets that need it (`skills: [build, frontend-patterns, vendor/shadcn-ui]`).

Do not mark vendor skills always-on. Build/test agents load only `ticket.skills`.

## Conflict order

`AGENTS.md` → `CONTRACTS.md` → ADRs → play skill → pattern skill → `DESIGN.md` → this vendor skill.

A vendor skill may not: add a public seam, edit files outside `files:`, resolve `[OPEN]`, edit an ADR, or start `/build` from an architect session.

## What to import vs write

| Import | Write here / as ADR |
|---|---|
| Playwright, pytest, vendor test runners | When `/test` runs; AC mapping |
| Supabase / Next / Trigger idioms | Whether a table/route exists (`CONTRACTS.md`) |
| shadcn / component kit usage | Tokens and IA (`DESIGN.md`) |
| Deploy checklists | Who is allowed to ship |

If a plugin ships a full “PM + coder” flow, copy only the craft files. Delete process text that fights `AGENTS.md`.

## After bumping a lock sha

Run `/test` on one known ticket. Treat skill bumps like dependency bumps.
