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
`sdlc init`) runs `sdlc doctor`, `sdlc gate ci`, `sdlc trace`, and `sdlc gate pr`,
which finds the ticket a PR moves (in_progress, in_review or done) or, when it moves
none, reports every file beyond the lead artifacts (a failure with
`scope.lead_code = "fail"`). Other CI systems run the same commands. Every gate
uses the base branch's `sdlc.toml`, so a PR cannot weaken the gate that judges it; a
lead PR may still change the config, which takes effect once merged. If the base
branch's config is itself broken (so the fix cannot pass), main is already red: a
maintainer merges the fix with an admin override, and the gate prints that hint. The workflow
file and the `.sdlc` kit checkout are the judge itself and run from the PR: protect
them with CODEOWNERS.
