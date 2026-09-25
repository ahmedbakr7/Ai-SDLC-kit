# Craft / vendor skills

Play skills (`skills/build`, `skills/test`, …) stay ours. This folder is for **proven third-party** Agent Skills (`SKILL.md` folders).

Marketplace / `npx skills add` / Claude plugins teach *how to use a stack*. How work moves stays in `AGENTS.md`.

## How to add one

1. Prefer a `SKILL.md` folder (Agent Skills standard).
2. Copy it into `skills/vendor/<name>/`.
3. Commit it. Git is the pin; do not leave it only in `~/.claude/skills/` or account plugin sync.
4. Put `vendor/<name>` on tickets that need it (`skills: [build, frontend-patterns, vendor/shadcn-ui]`).

Do not mark vendor skills always-on. Build/test agents load only `ticket.skills`. Hard rules: `AGENTS.md`.

If a plugin ships a full “PM + coder” flow, copy only the craft files.

| Import | Write here / as ADR |
|---|---|
| Playwright, pytest, vendor test runners | When `/test` runs; AC mapping |
| Supabase / Next / Trigger idioms | Whether a table/route exists (`CONTRACTS.md`) |
| shadcn / component kit usage | Tokens and IA (`DESIGN.md`) |
| Deploy checklists | Who is allowed to ship |

After updating a vendor skill, `/test` one known ticket.
