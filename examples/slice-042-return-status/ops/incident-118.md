# Incident 118 — rejected chip missing

- Evidence: eval `rejected` fixture showed empty chip text in staging.
- Suspected: T-042-03 ReturnChip mapping omitted `rejected`.
- Control: L0 hooks did not catch copy; need intent follow-up.

Draft intent: `intent/intent-043-rejected-chip.md`.
