# AGENTS.md (product shim)

This product pins the AI-SDLC kit at `.sdlc/`. Read **`.sdlc/AGENTS.md` first** and obey it.

Path map for this repo:

| Kit path in `.sdlc/AGENTS.md` | Where it is here |
|---|---|
| `AGENTS.md` (kit OS) | `.sdlc/AGENTS.md` |
| play skills `skills/<play>/` | `.sdlc/skills/<play>/` |
| `skills/frontend-patterns`, `backend-patterns` | `skills/frontend-patterns`, `skills/backend-patterns` |
| vendor / craft skills | `skills/vendor/` |
| `adapters/MODELS.md` | `adapters/MODELS.md` |
| `arch/CONTRACTS.md`, tickets, intent, design, decisions | same paths at repo root |
| commands | `.sdlc/commands/` |
| scripts / hooks | `.sdlc/scripts/`, `.sdlc/hooks/` |

If a play skill and a product file disagree, `.sdlc/AGENTS.md` still wins, then this product's `CONTRACTS.md` and ADRs.

Do not edit `.sdlc/` in this session. Open a kit-repo change instead.
