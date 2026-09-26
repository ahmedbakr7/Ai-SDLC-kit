# Example slice 042 — return status (markdown only)

Fake product slice to walk the kit chain in ~20 minutes. No real app.

## 20-minute walk

| Step | Command you’d run | Artifact to read / accept |
|---|---|---|
| 1 | `/intent` | `intent/intent-042-return-status.md` |
| 2 | `/design` | `design/spec-042-return-status.md`, `design/DESIGN.md`, `design/pages/orders.md` |
| 3 | `/architect` | `arch/plan-042.md`, `arch/CONTRACTS.md`, `decisions/ADR-0001-stack.md` |
| 4 | `/ticketize` | `tickets/T-042-01` … `T-042-04` |
| 5 | `/build T-042-03` (fresh session) | implement only `files:` + unit beside them; unit green → open PR |
| 6 | `/test T-042-03` (on that PR) | integration/e2e for AC (here: read AC; no real runner). No post-merge proof PR |
| 7 | `/review` | `reviews/pr-042.md` — AC↔proof table + green-suite gate |
| 8 | `/observe` (after “incident”) | `ops/incident-118.md` → draft `intent/intent-043-rejected-chip.md` |

Verify a ticket from the kit root:

```bash
./scripts/verify-ticket.sh T-042-03
# → examples/slice-042-return-status/tickets/T-042-03-orders-block.md
```

L0 fail demo:

```bash
./scripts/ticket-files.sh --ticket T-042-03 src/evil.ts   # FAIL
./scripts/no-adr-edit.sh examples/slice-042-return-status/decisions/ADR-0001-stack.md  # FAIL (existing)
```
