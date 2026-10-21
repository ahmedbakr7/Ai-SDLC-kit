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
- Exit when finished. Its stdin is closed (or carries the prompt with `stdin = "prompt"`),
  so an agent waiting for interactive input exits or hangs until `timeout`, after which
  the runner kills its whole process tree and gates whatever it left.
- Stay on the branch and do not rewrite history; the runner refuses to commit otherwise.

Consult your agent CLI's documentation for its non-interactive mode and permission
flags, and grant the narrowest set that allows the above.

## Starting the runner from an agent session

`sdlc run` starts agents that edit, commit and (with `vcs.pr_command`) open PRs, so a
harness that screens an interactive agent's commands may block it as an unreviewed
change. Either the lead starts each run, or the harness's permission rules allow the
runner explicitly (for example a rule for `.sdlc/bin/sdlc run:*`). Grant that only where
the lead has agreed that the session may start runs; the gate and the approvals still
judge everything the run produces.

## Where to run

Give unattended agents a disposable environment: a container, a CI runner, or a
fresh clone without production credentials. The runner commits only on the ticket
branch. It pushes only the ticket branch, and only when `vcs.claim = "push"` (the claim, before
the agent runs) or `vcs.pr_command` is set.

## Pick agents per play

Use stronger models where judgement matters (architect, review of `risk: high`
tickets) and faster ones for well-cut build tickets. Review must use a different
agent name than build (`[review] require_distinct_agent = true`, the default);
different vendors make the best reviewers for each other.
