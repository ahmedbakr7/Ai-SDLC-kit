# AI-SDLC kit (vendor-neutral)

Host this repo on git. Product repos pin it at `.sdlc/` (submodule by default). See `CONSUME.md`. It does not depend on Claude Code, Cursor, Codex, or a particular model. Those are *adapters*.

## v0.2

Importable: pin at `.sdlc/`, run `bootstrap-product.sh`, install the pre-commit wrapper as documented in `hooks/README.md`. L0 scripts under `scripts/` exist and fail loud on `files:` / CONTRACTS / ADR / AC violations. Test and app-eval runners remain product-overridable (`scripts/run-tests.sh`, `scripts/run-app-eval.sh`). Walk `examples/slice-042-return-status/` before your first real ticket.

CI workflow template: `adapters/github/check-kit.yml` (copy into `.github/workflows/` — see that folder’s README).

## Ideas

| Concept | Meaning | Not |
|---|---|---|
| **Lead session** | Human + one agent. Decides. Writes artifacts. May spawn subagents. | A place to implement a whole feature |
| **Subagent** | Isolated child: fresh context, narrow job, returns a brief or a diff, dies | A standing teammate with memory |
| **Skill** | Versioned instruction pack + optional scripts an agent loads on demand | Chat history |
| **Hook** | Deterministic gate (script). Pass/fail. No LLM. | A polite reminder in AGENTS.md |
| **Command** | Named play a human or lead starts (`/plan`, `/ticketize`, `/build T-042-03`) | A free-form prompt |
| **Band** | Capability class for the model, not a vendor name | “Always use the smartest model” |

## Bands (pick any vendor that fits)

| Band | Job type | Examples (illustrative, not required) |
|---|---|---|
| **L0** | Deterministic: hooks, schema check, test runner, lint | bash, tsc, pytest, spectral, playwright |
| **L1** cheap/fast | Research digest, ticket-split draft, status rewrite, boilerplate | Haiku / Flash / Mini class |
| **L2** mid | Bounded implement, test authoring from AC, routine review | Sonnet / GPT-4.1 / comparable |
| **L3** frontier | Ambiguous spec, architecture, security review, first-of-kind plan, ADR | Opus / flagship reasoning class |

Never put L3 on a greenfield “change the button color” ticket. Never put L1 on “design the billing state machine.”

## What this kit contains

- `AGENTS.md` — always-on OS for **agents** (they need this; humans are not enough)
- `USAGE.md` — how a human copies, binds, and launches plays
- `skills/` — play skills + pattern skills + `vendor/` for pinned third-party skills
- `skills/VENDOR.lock.md` — sha pins for craft skills
- `hooks/` — L0 gates
- `commands/` — named plays and copy-paste preambles for every play
- `examples/slice-042-return-status/` — markdown-only golden walkthrough
- `scripts/` — portable runners
- `templates/` — intent, ADR, ticket
- `adapters/` — bind to any tool; `MODELS.md` is the only place model names live

## Start here

1. Push this repo. In a product: `git submodule add <this-remote> .sdlc && .sdlc/scripts/bootstrap-product.sh` (`CONSUME.md`)
2. Human: `USAGE.md` then `adapters/GENERIC.md`
3. Agent: product `AGENTS.md` shim → `.sdlc/AGENTS.md`
4. Walk `.sdlc/examples/slice-042-return-status/` (or `examples/…` in this repo)
5. Third-party skills: `skills/vendor/README.md` (in the product after bootstrap)
