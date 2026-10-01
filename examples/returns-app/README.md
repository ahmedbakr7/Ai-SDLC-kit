# Example: returns-app

A complete slice you can run, small enough to read in ten minutes. The kit's own
tests drive it end to end, so it always reflects how the kit really behaves.

| Step | Artifact |
|---|---|
| intent | [intent/intent-042-return-status.md](intent/intent-042-return-status.md) |
| design | [design/spec-042-return-status.md](design/spec-042-return-status.md), [design/pages/order.md](design/pages/order.md), [design/DESIGN.md](design/DESIGN.md) |
| architect | [arch/plan-042-return-status.md](arch/plan-042-return-status.md), [arch/CONTRACTS.md](arch/CONTRACTS.md), [decisions/ADR-0001-stack.md](decisions/ADR-0001-stack.md), [skills/](skills/) |
| ticketize | [tickets/T-042-01](tickets/T-042-01-returns-api.md) (done), [tickets/T-042-02](tickets/T-042-02-order-page.md) (ready) |
| build + test | [evidence/T-042-01.build.json](evidence/T-042-01.build.json), [evidence/T-042-01.test.json](evidence/T-042-01.test.json) |
| review | [reviews/T-042-01.md](reviews/T-042-01.md) |

The evidence and review for T-042-01 were produced by running the conveyor
(`python tests/regen_example.py` in the kit), so their commit ids refer to that run.

## Try it

From the kit root:

```bash
bin/sdlc --root examples/returns-app doctor
bin/sdlc --root examples/returns-app lint
bin/sdlc --root examples/returns-app trace
bin/sdlc --root examples/returns-app next                 # T-042-02
bin/sdlc --root examples/returns-app prompt build T-042-02 --stdout | less
bin/sdlc --root examples/returns-app gate ci
```

Then break something and watch the gate catch it, for example mount the route at
`/api/v1/orders/{id}/returns` in `app/server.py` (contracts check), or remove a
`T-042-01/AC-3` tag from a test docstring (ac-coverage check).

To build T-042-02 with a real agent, copy this folder into its own git repository,
define an agent in `sdlc.toml` ([adapters/AGENTS-RUNNER.md](../../adapters/AGENTS-RUNNER.md)),
and run `sdlc run build T-042-02 --agent <name>`.
