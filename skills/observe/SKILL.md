---
name: observe
description: Turn production errors, failing evals or user reports into an incident with evidence, the gate gap that let it through, and a draft intent. Use for /observe on a schedule or after a breach.
---

# Play: observe

1. Collect evidence: logs, failing commands, reports. Reproduce if you can and write
   the exact command.
2. Write `ops/incident-NNN.md` from the template.
3. Find the cause in the artifacts: which ticket, contract or plan allowed it, and
   which `sdlc gate` check should have caught it. If no check could have, propose
   one (that is a kit improvement, the most valuable output of this play).
4. Draft `intent/intent-NNN-<slug>.md` with `status: draft`, or an ADR recording
   "no action" and why.
5. Stop. Never fix code from this play.
