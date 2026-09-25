# Commands (named plays)

A command is a saved prompt. Role, band, write set, and load set live in `AGENTS.md`. This folder is the preamble for each play.

| Command | File |
|---|---|
| `/research` | [research.md](research.md) |
| `/intent` | [intent.md](intent.md) |
| `/design` | [design.md](design.md) |
| `/architect` | [architect.md](architect.md) |
| `/ticketize` | [ticketize.md](ticketize.md) |
| `/build <ticket-id>` | [build.md](build.md) |
| `/test <ticket-id>` | [test.md](test.md) |
| `/test --app` | [test.md](test.md) |
| `/review` | [review.md](review.md) |
| `/observe` | [observe.md](observe.md) |

Launch: human CLI for `/intent` `/design` `/architect` `/build` `/test`; lead spawns `/research` `/ticketize` (and `/test` after build); CI for `/review` + `scripts/run-tests.sh`; scheduler for `/observe`. When the product pins the kit at `.sdlc/`, load preambles from `.sdlc/commands/<play>.md`.
