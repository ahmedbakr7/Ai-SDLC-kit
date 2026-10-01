# Configuring agents for `sdlc run`

The kit ships no agent definitions. How much an unattended agent may do (edit files,
run shell commands, reach the network) is the product owner's decision, so each
product declares its agents in `sdlc.toml`:

```toml
[agents.<name>]
command = "<agent CLI> ... {instruction}"   # or {prompt_file}
stdin = ""        # "" | "prompt" (pipe the whole prompt) | "instruction"
timeout = 3600    # seconds per attempt
```

| Placeholder | Becomes |
|---|---|
| `{instruction}` | quoted one-liner: "Read the file .sdlc-run/prompts/build-T-001-03.md completely and do exactly what it says..." |
| `{prompt_file}` | quoted repo-relative path of the generated prompt |

## What the agent must be able to do

- Read and edit files in the repository.
- Run `.sdlc/bin/sdlc gate <play> <id>` and the product's test commands, so it can
  iterate before the runner's own gate run. (It still works without this; the runner
  gates every attempt and feeds failures back, but each round trip costs an attempt.)
- Exit when finished. Interactive prompts will hang until `timeout`.

Consult your agent CLI's documentation for its non-interactive mode and permission
flags, and grant the narrowest set that allows the above.

## Where to run

Give unattended agents a disposable environment: a container, a CI runner, or a
fresh clone without production credentials. The runner commits only on the ticket
branch and never pushes unless `vcs.pr_command` is set.

## Pick agents per play

Use stronger models where judgement matters (architect, review of `risk: high`
tickets) and faster ones for well-cut build tickets. Review must use a different
agent name than build (`[review] require_distinct_agent = true`, the default);
different vendors make the best reviewers for each other.
