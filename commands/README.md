# Commands (named plays)

A command is a saved prompt + load list. Humans type it. Leads may invoke it to spawn a session.

| Command | Band | Starts | Loads |
|---|---|---|---|
| `/research` | L1 subagent | research | user notes + research skill |
| `/intent` | L2 lead | write intent.md | template + brief |
| `/design` | L2/L3 lead | spec + DESIGN + pages | accepted intent, design skill |
| `/architect` | L3 lead | plan + CONTRACTS + ADRs | accepted spec, architect skill, pattern skills |
| `/ticketize` | L1/L2 subagent | tickets | accepted plan, ticketize skill |
| `/build <ticket-id>` | L2 **new session** | implement | **ticket + CONTRACTS + ticket.skills** |
| `/test <ticket-id>` | L2 new session or subagent | author tests | ticket + CONTRACTS + test skill |
| `/test --app` | L0+L1 | run app evals | test skill mode B |
| `/review` | L2/L3 CI | REVIEW.md | diff + plan + ticket |
| `/observe` | L1 cron | incident / draft intent | logs + observe notes |

## Launch places (concrete)

- **Human laptop / agent CLI:** `/intent` `/design` `/architect` `/build` `/test`
- **Lead spawns, does not keep context:** `/research` `/ticketize` `/test` after build
- **CI:** `/review` + `scripts/run-tests.sh` + hooks
- **Scheduler:** `/observe`

Do not run `/build` inside the `/architect` conversation.
