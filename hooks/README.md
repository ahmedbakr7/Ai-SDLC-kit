# Hooks (L0 — no LLM)

Run in the agent runtime (pre-write / pre-commit) and again in CI. Same scripts.

| Hook | When | Fail if |
|---|---|---|
| `ticket-files.sh` | before every write in a `/build` session | path not in ticket `files:` and not a test path allowed by the ticket |
| `no-contract-drift.sh` | before commit | new route/event/table name not present in `CONTRACTS.md` |
| `no-adr-edit.sh` | before commit | existing `decisions/ADR-*.md` modified (add ADR-N+1 instead) |
| `ac-not-deleted.sh` | before commit on ticket files | an `acceptance_criteria` item removed without a spec citation |
| `test-edit-guard.sh` | during a “fix tests” turn in **build** | test files changed with no production file in the same diff (build agent). Test agent is exempt. |
| `ticket-status.sh` | CI | PR has no `ticket:` trailer or ticket status not `in_review`/`done` |

Implementations in `scripts/`. Wire them via the adapter for your tool (Claude hooks, git pre-commit, GitHub Action — same bash).
