# Adapter: any coding agent

This kit is files + bash. Bind as follows.

## Always-on rules

Point your tool’s “always apply” mechanism at the **product root** `AGENTS.md` (the shim from `templates/product-AGENTS.md`). That file tells the agent to read `.sdlc/AGENTS.md`.

- Claude Code: root `AGENTS.md` and/or `CLAUDE.md` → “read AGENTS.md; kit is .sdlc/”
- Cursor: `@AGENTS.md` in `.cursor/rules/sdlc.mdc` with `alwaysApply: true`
- Codex / OpenCode / Aider / generic: pass `--system AGENTS.md`

Play skills: `.sdlc/skills/<play>/SKILL.md`. Pattern and vendor skills: product `skills/`.

## Skills

A skill is a folder with `SKILL.md`. Load by path when the command says so.

- Claude Code: install or copy into `.claude/skills/` or repo `skills/`
- Cursor: `@file` the SKILL.md
- Others: first user message of `/build` includes the skill text

## Commands

Implement as slash commands, saved prompts, or shell aliases that start a **fresh** session with a fixed preamble:

```
You are the BUILD agent. Band L2.
Load AGENTS.md, skills/build/SKILL.md, $TICKET, CONTRACTS.md, skills listed on the ticket.
Write only files: on the ticket.
```

## Hooks

Git pre-commit + CI. Do not rely on the vendor hook system alone.

```
.git/hooks/pre-commit → ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit
.github/workflows → copy adapters/github/check-kit.yml (runs scripts/check-kit.sh)
```
See `.sdlc/hooks/README.md` for the full L0 table.

Claude Code hooks / Cursor hooks are optional extras that fail faster.

## Models

Map bands in one repo file `adapters/MODELS.md` (not committed secrets):

```
L1=...
L2=...
L3=...
```

Swap vendors by editing that map. Do not put model names in skills.

## Vendor / marketplace skills

Install however you like (`npx skills add`, Claude `/plugin`, Cursor skills). Then **copy the SKILL.md folder into `skills/vendor/<name>/`**, commit it, and list it on tickets. Do not make marketplace skills always-on. See `skills/vendor/README.md`.
