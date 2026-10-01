# Binding tools and agents

The kit needs nothing from any vendor. Two things connect it to a tool: the tool
reads the rules, and the runner can start the tool.

## Rules: AGENTS.md everywhere

`AGENTS.md` at the product root is read natively by most coding agents (Codex,
Cursor, Copilot, Aider, Zed, Jules, Devin, and others). For tools with their own
format, `sdlc adapters sync` writes a generated pointer (never hand-edit these):

| Tool | Generated file |
|---|---|
| Claude Code | `CLAUDE.md` (`@AGENTS.md`), `.claude/commands/sdlc-<play>.md` |
| Gemini CLI | `GEMINI.md` (`@AGENTS.md`) |
| Cursor | `.cursor/rules/sdlc.mdc` (always apply) |
| GitHub Copilot | `.github/copilot-instructions.md` |

Choose tools with `[adapters] tools = [...]` in `sdlc.toml`. `sdlc doctor` reports
stale files; CI can run `sdlc adapters sync --check`.

Skills are not installed into any tool's auto-load folder. `sdlc prompt` inlines the
exact skills a ticket lists, so every agent sees the same context.

## The runner: `sdlc run`

`sdlc run <build|test|review> <ticket> --agent <name>` starts the command configured
for that agent, once per attempt, with a one-line instruction to read the generated
prompt file. See [AGENTS-RUNNER.md](AGENTS-RUNNER.md).

## Enforcement

Local hooks are a convenience; CI is the guarantee. `github/sdlc.yml` (installed by
`sdlc init`) runs `sdlc doctor`, `sdlc gate ci`, `sdlc trace`, and the build gate
for every ticket the PR moves to `in_review`. Other CI systems run the same commands.
