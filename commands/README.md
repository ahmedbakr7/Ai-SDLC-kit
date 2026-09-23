# Commands (named plays)

A command is a saved prompt + load list. Humans type it. Leads may invoke it to spawn a session.

| Command | File | Band | Starts | Loads |
|---|---|---|---|---|
| `/research` | [research.md](research.md) | L1 subagent | research | user notes + research skill |
| `/intent` | [intent.md](intent.md) | L2 lead | write intent.md | template + brief |
| `/design` | [design.md](design.md) | L2/L3 lead | spec + DESIGN + pages | accepted intent, design skill |
| `/architect` | [architect.md](architect.md) | L3 lead | plan + CONTRACTS + ADRs | accepted spec, architect skill, pattern skills |
| `/ticketize` | [ticketize.md](ticketize.md) | L1/L2 subagent | tickets | accepted plan, ticketize skill |
| `/build <ticket-id>` | [build.md](build.md) | L2 **new session** | implement | **ticket + CONTRACTS + ticket.skills** |
| `/test <ticket-id>` | [test.md](test.md) | L2 new session or subagent | author tests | ticket + CONTRACTS + test skill |
| `/test --app` | [test.md](test.md) | L0+L1 | run app evals | test skill mode B |
| `/review` | [review.md](review.md) | L2/L3 CI | REVIEW.md | diff + plan + ticket |
| `/observe` | [observe.md](observe.md) | L1 cron | incident / draft intent | logs + observe notes |

## Launch places (concrete)

- **Human laptop / agent CLI:** `/intent` `/design` `/architect` `/build` `/test`
- **Lead spawns, does not keep context:** `/research` `/ticketize` `/test` after build
- **CI:** `/review` + `scripts/run-tests.sh` + hooks
- **Scheduler:** `/observe`

Do not run `/build` inside the `/architect` conversation.

When the product pins the kit at `.sdlc/`, load preambles from `.sdlc/commands/<play>.md` (or symlink into your tool’s command dir).
