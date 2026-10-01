---
name: design
description: Turn an accepted intent into a spec of numbered testable requirements plus page state tables and DESIGN tokens. Use for /design after /intent is accepted.
---

# Play: design

You decide **what** the product does, observably. Not how it is built.

## Procedure

1. Read the accepted intent. Every requirement must serve its outcome; anything else
   is out of scope.
2. Write `design/spec-NNN-<slug>.md` from the template. Requirements:
   - one observable behaviour each, with an id `F-NNN-n` / `N-NNN-n`;
   - name the actor, the trigger, the result, and the failure/empty cases;
   - non-functional ones carry a number (latency, limit, size, locale list).
3. One `design/pages/<route>.md` per screen with the state table: loading, empty, each
   error, loaded, and the exact user-visible copy.
4. `design/DESIGN.md`: tokens (colour, type, spacing) the frontend pattern skill will
   enforce. Reuse existing tokens on later slices.
5. Mark every judgement `[DECISION: ADR-NNNN]` (already decided) or
   `[OPEN: question]` (a human must answer). Never close an OPEN by guessing.
6. No stack, routes or schemas: those belong to /architect.
7. Run `sdlc lint`. Stop and ask the human to accept.

## Testable or not

| Testable | Not |
|---|---|
| **F-001-4** The organizer sees "Link copied" within 1 s of tapping Copy link. | Sharing is easy. |
| **N-001-2** All screens render right-to-left when the locale is `ar`. | Supports Arabic. |
| **F-001-9** A plan with fewer than 2 responses shows "Waiting for friends" and no proposal. | Handles low turnout. |
